"""
Seyyanen Diagnostic Engine — Phase F-2: Real-Time Data Quality
==============================================================
Real-time quality assessment layer consuming live diagnostic samples from Phase F-1.
Reuses and extends Phase C data quality contracts (C-1 through C-6).
Provides deterministic, explainable, thread-safe quality evaluation per PID.
"""

import time
import threading
import logging
from collections import deque
from typing import Callable, Optional, Dict, List, Any, Tuple

from motor import (
    AutoExpertEngine,
    # Data Quality constants (Phase C-1/C-3)
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    QUALITY_SUSPECT,
    # Acquisition status constants
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_EMPTY_RESPONSE,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    STATUS_DID_MISMATCH,
    # Physical Plausibility constants (Phase C-3)
    PHYSICS_PLAUSIBLE,
    PHYSICS_IMPLAUSIBLE_HIGH,
    PHYSICS_IMPLAUSIBLE_LOW,
    PHYSICS_UNKNOWN,
    PHYSICAL_LIMITS,
    # Temporal Plausibility constants (Phase C-4)
    TEMPORAL_PLAUSIBLE,
    TEMPORAL_SUSPECT,
    TEMPORAL_UNKNOWN,
    TEMPORAL_LIMITS,
    # Cross-Sensor Correlation constants (Phase C-5)
    CORRELATION_COHERENT,
    CORRELATION_INCONSISTENT,
    CORRELATION_UNKNOWN,
    CORRELATION_THRESHOLDS,
    # Vehicle Operating Envelope constants (Phase C-6)
    ENVELOPE_NORMAL,
    ENVELOPE_OUT_OF_RANGE_HIGH,
    ENVELOPE_OUT_OF_RANGE_LOW,
    ENVELOPE_UNKNOWN,
    # Status to quality mapping helper
    derive_quality_from_status,
)

# Standard PID name mapping fallback
DEFAULT_NAME_MAP = {
    "010C": "RPM",
    "010D": "SPEED",
    "0105": "ECT",
    "010B": "MAP",
    "0111": "TPS",
    "0104": "LOAD",
    "010F": "IAT",
    "0110": "MAF",
    "0106": "STFT",
    "0107": "LTFT",
    "0114": "O2_B1S1_V",
    "011F": "RUN_TIME",
}


class LiveQualityAssessor:
    """
    Phase F-2: Real-Time Data Quality Assessor.
    
    Consumes live samples from F-1, evaluates layered quality checks (status,
    physical, temporal, envelope, correlation, freshness), maintains per-PID
    state, and tracks quality transitions.
    """

    def __init__(
        self,
        engine: Optional[AutoExpertEngine] = None,
        max_age: float = 2.0,
        history_maxlen: int = 200,
        transition_maxlen: int = 100,
        on_quality_change: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.engine = engine
        self.max_age = max(0.1, float(max_age))
        self.history_maxlen = max(10, int(history_maxlen))
        self.transition_maxlen = max(10, int(transition_maxlen))
        self._on_quality_change = on_quality_change

        self._lock = threading.RLock()

        # Current per-PID quality result: {pid: QualityResult dict}
        self._current_quality: Dict[str, Dict[str, Any]] = {}

        # Last valid trusted measurement per sensor: {sensor_name: (val, timestamp)}
        # Used for temporal plausibility and cross-sensor correlation
        self._trusted_sensor_history: Dict[str, deque] = {}

        # Last successful sample per PID: {pid: (sample_dict, quality_result_dict)}
        # Preserved across transient acquisition failures (timeouts, NO DATA)
        self._last_successful_by_pid: Dict[str, Dict[str, Any]] = {}

        # Bounded evaluation history & transition records
        self._history: deque = deque(maxlen=self.history_maxlen)
        self._transitions: deque = deque(maxlen=self.transition_maxlen)

    # =================================================================
    # SAMPLE EVALUATION PIPELINE
    # =================================================================
    def evaluate_sample(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates real-time quality for a single live sample from F-1.
        Thread-safe, failure-isolated, and deterministic.
        """
        try:
            return self._do_evaluate_sample(sample)
        except Exception as e:
            logging.error(f"[QUALITY_EVAL_ERROR] Exception evaluating sample {sample}: {e}")
            # Failure isolation: produce structured error result for this PID
            pid = str(sample.get("pid", "UNKNOWN")).upper().strip()
            name = str(sample.get("name", DEFAULT_NAME_MAP.get(pid, pid)))
            err_result = {
                "pid": pid,
                "name": name,
                "value": sample.get("value"),
                "timestamp": sample.get("timestamp", time.time()),
                "acquisition_status": sample.get("status", STATUS_SERIAL_ERROR),
                "quality": QUALITY_ERROR,
                "quality_reasons": [f"Quality evaluator exception: {e}"],
                "is_fresh": False,
                "age": 0.0,
                "max_age": self.max_age,
                "physical_plausibility": PHYSICS_UNKNOWN,
                "temporal_plausibility": TEMPORAL_UNKNOWN,
                "rate_of_change": None,
                "correlation_status": CORRELATION_UNKNOWN,
                "correlation_details": [],
                "envelope_status": ENVELOPE_UNKNOWN,
                "is_trusted": False,
                "sequence": sample.get("sequence", 0),
            }
            with self._lock:
                self._current_quality[pid] = err_result
                self._history.append(err_result)
            return err_result

    def _do_evaluate_sample(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        pid = str(sample.get("pid", "")).upper().strip()
        if len(pid) == 2:
            pid = f"01{pid}"
        name = str(sample.get("name", DEFAULT_NAME_MAP.get(pid, pid)))
        val = sample.get("value")
        ts = float(sample.get("timestamp", time.time()))
        acq_status = str(sample.get("status", STATUS_VALID))
        seq = int(sample.get("sequence", 0))

        reasons = []
        now = time.time()
        age = max(0.0, now - ts)
        is_fresh = (age <= self.max_age)

        # -------------------------------------------------------------
        # 1. ACQUISITION STATUS EVALUATION
        # -------------------------------------------------------------
        if acq_status in (STATUS_TIMEOUT, STATUS_NO_CONNECTION, STATUS_WORKER_DOWN, STATUS_SERIAL_ERROR):
            final_quality = QUALITY_ERROR
            reasons.append(f"Communication failure: {acq_status}")
            physical_status = PHYSICS_UNKNOWN
            temporal_status = TEMPORAL_UNKNOWN
            rate_of_change = None
            envelope_status = ENVELOPE_UNKNOWN
            correlation_status = CORRELATION_UNKNOWN
            corr_details = []

        elif acq_status in (STATUS_NO_DATA, STATUS_EMPTY_RESPONSE, STATUS_NRC, STATUS_DID_MISMATCH):
            final_quality = QUALITY_INVALID
            reasons.append(f"Invalid ECU response: {acq_status}")
            physical_status = PHYSICS_UNKNOWN
            temporal_status = TEMPORAL_UNKNOWN
            rate_of_change = None
            envelope_status = ENVELOPE_UNKNOWN
            correlation_status = CORRELATION_UNKNOWN
            corr_details = []

        elif acq_status != STATUS_VALID or val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            final_quality = QUALITY_INVALID
            reasons.append(f"Invalid or null measurement: {acq_status}")
            physical_status = PHYSICS_UNKNOWN
            temporal_status = TEMPORAL_UNKNOWN
            rate_of_change = None
            envelope_status = ENVELOPE_UNKNOWN
            correlation_status = CORRELATION_UNKNOWN
            corr_details = []

        else:
            # ---------------------------------------------------------
            # 2. VALID ACQUISITION: LAYERED EVALUATION
            # ---------------------------------------------------------
            val = float(val)

            # (A) Physical Plausibility (Phase C-3)
            physical_status = self._check_physical_plausibility(name, val)
            if physical_status in (PHYSICS_IMPLAUSIBLE_LOW, PHYSICS_IMPLAUSIBLE_HIGH):
                limits = PHYSICAL_LIMITS.get(name, ("?", "?"))
                reasons.append(f"Physical limit violation ({physical_status}): {val} outside {limits}")

            # (B) Temporal Plausibility (Phase C-4)
            with self._lock:
                temporal_status, rate_of_change = self._check_temporal_plausibility(name, val, ts)
            if temporal_status == TEMPORAL_SUSPECT:
                max_rate = TEMPORAL_LIMITS.get(name, "?")
                reasons.append(f"Temporal rate-of-change suspect: {round(rate_of_change, 2)}/s (limit: {max_rate})")

            # (C) Vehicle Operating Envelope (Phase C-6)
            envelope_status = self._check_vehicle_envelope(name, val)
            if envelope_status in (ENVELOPE_OUT_OF_RANGE_HIGH, ENVELOPE_OUT_OF_RANGE_LOW):
                reasons.append(f"Operating envelope violation: {envelope_status}")

            # (D) Freshness
            if not is_fresh:
                reasons.append(f"Measurement is stale: age {round(age, 2)}s > max_age {self.max_age}s")

            # (E) Deterministic Precedence Hierarchy
            # ERROR > INVALID > IMPLAUSIBLE > SUSPECT > STALE > GOOD
            if physical_status in (PHYSICS_IMPLAUSIBLE_LOW, PHYSICS_IMPLAUSIBLE_HIGH):
                final_quality = QUALITY_IMPLAUSIBLE
            elif temporal_status == TEMPORAL_SUSPECT:
                final_quality = QUALITY_SUSPECT
            elif not is_fresh:
                final_quality = QUALITY_STALE
            else:
                final_quality = QUALITY_GOOD

            # (F) Cross-Sensor Correlation (Phase C-5)
            # Evaluated with currently trusted live snapshot
            with self._lock:
                correlation_status, corr_details = self._check_correlations(name, val, final_quality)
            if correlation_status == CORRELATION_INCONSISTENT:
                for cd in corr_details:
                    if cd.get("status") == CORRELATION_INCONSISTENT:
                        reasons.append(f"Cross-sensor inconsistency: {cd.get('details', cd.get('rule'))}")

        # Construct structured quality result
        is_trusted = (
            acq_status == STATUS_VALID
            and final_quality == QUALITY_GOOD
            and is_fresh
            and val is not None
        )

        result = {
            "pid": pid,
            "name": name,
            "value": val,
            "timestamp": ts,
            "acquisition_status": acq_status,
            "quality": final_quality,
            "quality_reasons": reasons,
            "is_fresh": is_fresh,
            "age": round(age, 3),
            "max_age": self.max_age,
            "physical_plausibility": physical_status,
            "temporal_plausibility": temporal_status,
            "rate_of_change": round(rate_of_change, 2) if rate_of_change is not None else None,
            "correlation_status": correlation_status,
            "correlation_details": corr_details,
            "envelope_status": envelope_status,
            "is_trusted": is_trusted,
            "sequence": seq,
        }

        # -------------------------------------------------------------
        # 3. STATE UPDATE & TRANSITION TRACKING
        # -------------------------------------------------------------
        with self._lock:
            old_result = self._current_quality.get(pid)
            old_quality = old_result.get("quality") if old_result else None

            # Detect transition
            if old_quality is not None and old_quality != final_quality:
                transition = {
                    "pid": pid,
                    "name": name,
                    "old_quality": old_quality,
                    "new_quality": final_quality,
                    "timestamp": ts,
                    "reason": "; ".join(reasons) if reasons else f"Transition {old_quality} -> {final_quality}",
                    "value": val,
                }
                self._transitions.append(transition)
                if self._on_quality_change and callable(self._on_quality_change):
                    try:
                        self._on_quality_change(transition)
                    except Exception as e:
                        logging.warning(f"LiveQualityAssessor on_quality_change callback error: {e}")

            # Update current quality and history
            self._current_quality[pid] = result
            self._history.append(result)

            # Update trusted history and last successful value
            if is_trusted:
                if name not in self._trusted_sensor_history:
                    self._trusted_sensor_history[name] = deque(maxlen=50)
                self._trusted_sensor_history[name].append({
                    "val": val,
                    "time": ts,
                })
                self._last_successful_by_pid[pid] = {
                    "sample": dict(sample),
                    "quality_result": dict(result),
                    "timestamp": ts,
                    "value": val,
                }

        return result

    # =================================================================
    # INTERNAL QUALITY CHECK HELPERS (REUSING PHASE C LOGIC)
    # =================================================================
    def _check_physical_plausibility(self, name: str, value: float) -> str:
        """Phase C-3: Checks wide physical plausibility limits."""
        if name not in PHYSICAL_LIMITS:
            return PHYSICS_UNKNOWN

        min_val, max_val = PHYSICAL_LIMITS[name]
        if value < min_val:
            return PHYSICS_IMPLAUSIBLE_LOW
        elif value > max_val:
            return PHYSICS_IMPLAUSIBLE_HIGH
        return PHYSICS_PLAUSIBLE

    def _check_temporal_plausibility(self, name: str, value: float, timestamp: float) -> Tuple[str, Optional[float]]:
        """Phase C-4: Checks rate-of-change against previous trusted measurement."""
        hist = self._trusted_sensor_history.get(name)
        if not hist:
            return TEMPORAL_UNKNOWN, None

        prev_entry = hist[-1]
        prev_val = prev_entry.get("val")
        prev_time = prev_entry.get("time")

        if not isinstance(prev_val, (int, float)) or not isinstance(prev_time, (int, float)):
            return TEMPORAL_UNKNOWN, None

        dt = timestamp - prev_time
        if dt <= 0.0001:  # Identical or inverted timestamp -> unknown
            return TEMPORAL_UNKNOWN, None

        rate = abs(value - prev_val) / dt
        max_rate = TEMPORAL_LIMITS.get(name)

        if max_rate is not None and rate > max_rate:
            return TEMPORAL_SUSPECT, rate
        return TEMPORAL_PLAUSIBLE, rate

    def _check_vehicle_envelope(self, name: str, value: float) -> str:
        """Phase C-6: Checks vehicle operating envelope (e.g. RPM vs redline)."""
        profile = getattr(self.engine, "vehicle_profile", None) if self.engine else None
        if profile is None:
            return ENVELOPE_UNKNOWN

        if name == "RPM":
            redline = getattr(profile, "redline", None)
            if isinstance(redline, (int, float)) and redline > 0:
                if value > redline:
                    return ENVELOPE_OUT_OF_RANGE_HIGH
                elif value >= 0:
                    return ENVELOPE_NORMAL
                else:
                    return ENVELOPE_OUT_OF_RANGE_LOW
            return ENVELOPE_UNKNOWN

        return ENVELOPE_UNKNOWN

    def _check_correlations(self, sensor_name: str, current_value: float, current_quality: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Phase C-5: Checks cross-sensor correlations against active trusted live snapshot."""
        # Helper to get current trusted value for a sensor
        def get_trusted(s_name: str) -> Optional[float]:
            if s_name == sensor_name:
                return current_value if current_quality == QUALITY_GOOD else None
            hist = self._trusted_sensor_history.get(s_name)
            if not hist:
                return None
            last = hist[-1]
            if (time.time() - last["time"]) <= self.max_age:
                return float(last["val"])
            return None

        rules_evaluated = []
        overall_status = CORRELATION_UNKNOWN

        # RULE 1: RPM vs SPEED at Standstill
        if sensor_name in ("RPM", "SPEED"):
            rpm = get_trusted("RPM")
            speed = get_trusted("SPEED")
            if rpm is None or speed is None:
                rules_evaluated.append({
                    "rule": "RPM_VSS",
                    "status": CORRELATION_UNKNOWN,
                    "details": "Missing or untrusted RPM or SPEED",
                })
            elif (
                rpm <= CORRELATION_THRESHOLDS["RPM_STANDSTILL_MAX"]
                and speed >= CORRELATION_THRESHOLDS["SPEED_MOVING_MIN"]
            ):
                rules_evaluated.append({
                    "rule": "RPM_VSS",
                    "status": CORRELATION_INCONSISTENT,
                    "details": f"Standstill RPM ({rpm}) but moving vehicle (SPEED={speed} km/h)",
                })
            else:
                rules_evaluated.append({
                    "rule": "RPM_VSS",
                    "status": CORRELATION_COHERENT,
                    "details": "RPM and SPEED coherent",
                })

        # RULE 2: TPS vs RPM Response
        if sensor_name in ("TPS", "RPM"):
            tps = get_trusted("TPS")
            rpm = get_trusted("RPM")
            if tps is None or rpm is None:
                rules_evaluated.append({
                    "rule": "TPS_RPM",
                    "status": CORRELATION_UNKNOWN,
                    "details": "Missing or untrusted TPS or RPM",
                })
            elif (
                tps >= CORRELATION_THRESHOLDS["TPS_HIGH"]
                and rpm <= CORRELATION_THRESHOLDS["RPM_LOW"]
            ):
                rules_evaluated.append({
                    "rule": "TPS_RPM",
                    "status": CORRELATION_INCONSISTENT,
                    "details": f"High throttle (TPS={tps}%) but low RPM ({rpm})",
                })
            else:
                rules_evaluated.append({
                    "rule": "TPS_RPM",
                    "status": CORRELATION_COHERENT,
                    "details": "TPS and RPM coherent",
                })

        # RULE 3: TPS vs MAP Airflow Consistency
        if sensor_name in ("TPS", "RPM", "MAP"):
            tps = get_trusted("TPS")
            rpm = get_trusted("RPM")
            map_val = get_trusted("MAP")
            if tps is None or rpm is None or map_val is None:
                rules_evaluated.append({
                    "rule": "TPS_MAP",
                    "status": CORRELATION_UNKNOWN,
                    "details": "Missing or untrusted TPS, RPM, or MAP",
                })
            elif (
                tps >= CORRELATION_THRESHOLDS["TPS_HIGH"]
                and rpm >= CORRELATION_THRESHOLDS["RPM_RUNNING"]
                and map_val <= CORRELATION_THRESHOLDS["MAP_EXTREMELY_LOW"]
            ):
                rules_evaluated.append({
                    "rule": "TPS_MAP",
                    "status": CORRELATION_INCONSISTENT,
                    "details": f"High throttle (TPS={tps}%) with running engine ({rpm} RPM) but extremely low MAP ({map_val} kPa)",
                })
            else:
                rules_evaluated.append({
                    "rule": "TPS_MAP",
                    "status": CORRELATION_COHERENT,
                    "details": "TPS, RPM, and MAP coherent",
                })

        if any(r["status"] == CORRELATION_INCONSISTENT for r in rules_evaluated):
            overall_status = CORRELATION_INCONSISTENT
        elif any(r["status"] == CORRELATION_COHERENT for r in rules_evaluated):
            overall_status = CORRELATION_COHERENT
        else:
            overall_status = CORRELATION_UNKNOWN

        return overall_status, rules_evaluated

    # =================================================================
    # READ APIS (THREAD-SAFE)
    # =================================================================
    def get_quality(self, pid: str) -> Optional[Dict[str, Any]]:
        """Returns the current structured quality result for a specific PID."""
        clean_pid = pid.upper().strip()
        if len(clean_pid) == 2:
            clean_pid = f"01{clean_pid}"
        with self._lock:
            res = self._current_quality.get(clean_pid)
            return dict(res) if res else None

    def get_all_quality(self) -> Dict[str, Dict[str, Any]]:
        """Returns a snapshot of the current quality results for all PIDs."""
        with self._lock:
            return {p: dict(q) for p, q in self._current_quality.items()}

    def get_quality_snapshot(self) -> Dict[str, Any]:
        """Returns a consolidated summary of quality states across all live PIDs."""
        with self._lock:
            items = list(self._current_quality.values())

        good = [s["pid"] for s in items if s["quality"] == QUALITY_GOOD]
        suspect = [s["pid"] for s in items if s["quality"] == QUALITY_SUSPECT]
        implausible = [s["pid"] for s in items if s["quality"] == QUALITY_IMPLAUSIBLE]
        stale = [s["pid"] for s in items if s["quality"] == QUALITY_STALE]
        invalid = [s["pid"] for s in items if s["quality"] == QUALITY_INVALID]
        error = [s["pid"] for s in items if s["quality"] == QUALITY_ERROR]
        trusted = [s["pid"] for s in items if s.get("is_trusted", False)]

        return {
            "total_tracked_pids": len(items),
            "trusted_count": len(trusted),
            "trusted_pids": trusted,
            "good_count": len(good),
            "suspect_count": len(suspect),
            "implausible_count": len(implausible),
            "stale_count": len(stale),
            "invalid_count": len(invalid),
            "error_count": len(error),
            "details": {s["pid"]: s["quality"] for s in items},
        }

    def get_quality_history(self, pid: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent quality evaluations from bounded history buffer."""
        with self._lock:
            if pid is not None:
                clean_pid = pid.upper().strip()
                if len(clean_pid) == 2:
                    clean_pid = f"01{clean_pid}"
                filtered = [dict(q) for q in self._history if q["pid"] == clean_pid]
            else:
                filtered = [dict(q) for q in self._history]

        if limit is not None and limit > 0:
            return filtered[-limit:]
        return filtered

    def get_quality_transitions(self, pid: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent quality transitions from bounded transition log."""
        with self._lock:
            if pid is not None:
                clean_pid = pid.upper().strip()
                if len(clean_pid) == 2:
                    clean_pid = f"01{clean_pid}"
                filtered = [dict(t) for t in self._transitions if t["pid"] == clean_pid]
            else:
                filtered = [dict(t) for t in self._transitions]

        if limit is not None and limit > 0:
            return filtered[-limit:]
        return filtered

    def get_trusted_value(self, pid: str) -> Optional[float]:
        """
        Returns the current live value only if the measurement is STATUS_VALID,
        QUALITY_GOOD, and fresh. Otherwise returns None.
        """
        q = self.get_quality(pid)
        if q and q.get("is_trusted", False):
            return q.get("value")
        return None

    def get_last_successful(self, pid: str) -> Optional[Dict[str, Any]]:
        """
        Returns the last known successful measurement and its original timestamp/quality.
        Preserved across subsequent transient failures (TIMEOUT, NO_DATA).
        """
        clean_pid = pid.upper().strip()
        if len(clean_pid) == 2:
            clean_pid = f"01{clean_pid}"
        with self._lock:
            res = self._last_successful_by_pid.get(clean_pid)
            if not res:
                return None
            # Calculate freshness of the preserved value based on its original timestamp
            now = time.time()
            age = max(0.0, now - res["timestamp"])
            copy_res = dict(res)
            copy_res["current_age"] = round(age, 3)
            copy_res["is_still_fresh"] = (age <= self.max_age)
            return copy_res
