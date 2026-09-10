"""
Seyyanen Diagnostic Engine — Phase F-3: Live Diagnostic Intelligence
====================================================================
Deterministic, persistence-aware real-time diagnostic intelligence engine.
Consumes qualified live samples from Phase F-2, enforces strict trust boundaries,
tracks anomaly persistence (NEW -> PERSISTING -> ESCALATING -> RECOVERING -> RESOLVED),
deduplicates diagnostic events, and maintains active hypotheses without false alarms.
"""

import time
import threading
import logging
from collections import deque
from typing import Callable, Optional, Dict, List, Any, Set, Tuple

from motor import (
    AutoExpertEngine,
    # Quality states (Phase F-2 / C-1)
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    QUALITY_SUSPECT,
    STATUS_VALID,
    # Physical / Temporal / Correlation / Envelope constants
    PHYSICS_PLAUSIBLE,
    PHYSICS_IMPLAUSIBLE_HIGH,
    PHYSICS_IMPLAUSIBLE_LOW,
    PHYSICS_UNKNOWN,
    TEMPORAL_PLAUSIBLE,
    TEMPORAL_SUSPECT,
    TEMPORAL_UNKNOWN,
    CORRELATION_COHERENT,
    CORRELATION_INCONSISTENT,
    CORRELATION_UNKNOWN,
    ENVELOPE_NORMAL,
    ENVELOPE_OUT_OF_RANGE_HIGH,
    ENVELOPE_OUT_OF_RANGE_LOW,
    ENVELOPE_UNKNOWN,
    # Phase D Severities & Evidence
    EVIDENCE_SUPPORTED,
    EVIDENCE_CONTRADICTED,
    EVIDENCE_UNKNOWN,
    EVIDENCE_INFO,
    EVIDENCE_WARNING,
    EVIDENCE_CRITICAL,
    # Phase D-2 Fault Hypotheses
    HYPOTHESIS_SUPPORTED,
    HYPOTHESIS_POSSIBLE,
    HYPOTHESIS_CONTRADICTED,
    HYPOTHESIS_INSUFFICIENT,
    HYPOTHESIS_INFO,
    HYPOTHESIS_WARNING,
    HYPOTHESIS_CRITICAL,
)

# =====================================================================
# F-3 CONSTANTS & LIFECYCLE STATES
# =====================================================================
LIFECYCLE_NEW = "NEW"
LIFECYCLE_PERSISTING = "PERSISTING"
LIFECYCLE_ESCALATING = "ESCALATING"
LIFECYCLE_RECOVERING = "RECOVERING"
LIFECYCLE_RESOLVED = "RESOLVED"

# Diagnostic Event Types
EVENT_SENSOR_ABNORMAL = "SENSOR_ABNORMAL"
EVENT_SENSOR_IMPLAUSIBLE = "SENSOR_IMPLAUSIBLE"
EVENT_RAPID_CHANGE = "RAPID_CHANGE"
EVENT_CORRELATION_ANOMALY = "CORRELATION_ANOMALY"
EVENT_OPERATING_ENVELOPE_VIOLATION = "OPERATING_ENVELOPE_VIOLATION"
EVENT_SIGNAL_STUCK = "SIGNAL_STUCK"
EVENT_MULTI_SENSOR_PATTERN = "MULTI_SENSOR_PATTERN"
EVENT_CONDITION_RESOLVED = "CONDITION_RESOLVED"

# Severities
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"

# Confidence Levels
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MODERATE = "MODERATE"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_UNKNOWN = "UNKNOWN"

# Hypotheses IDs
HYP_FUEL_SYSTEM_LEAN = "FUEL_SYSTEM_LEAN"
HYP_FUEL_SYSTEM_RICH = "FUEL_SYSTEM_RICH"
HYP_AIRFLOW_ISSUE = "AIRFLOW_MEASUREMENT_ISSUE"
HYP_COOLING_ISSUE = "COOLING_SYSTEM_ISSUE"
HYP_CORRELATION_ISSUE = "SENSOR_CORRELATION_ISSUE"
HYP_ELECTRICAL_ISSUE = "ELECTRICAL_SYSTEM_ISSUE"


class LiveDiagnosticIntelligence:
    """
    Phase F-3: Real-Time Diagnostic Intelligence Engine.
    
    Interprets qualified live diagnostic samples, tracks anomaly persistence,
    emits deduplicated events on lifecycle changes, and updates active hypotheses.
    """

    def __init__(
        self,
        engine: Optional[AutoExpertEngine] = None,
        persistence_threshold: int = 2,
        recovery_threshold: int = 2,
        history_maxlen: int = 100,
        event_maxlen: int = 100,
        on_diagnostic_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.engine = engine
        self.persistence_threshold = max(1, int(persistence_threshold))
        self.recovery_threshold = max(1, int(recovery_threshold))
        self.history_maxlen = max(10, int(history_maxlen))
        self.event_maxlen = max(10, int(event_maxlen))
        self._on_diagnostic_event = on_diagnostic_event

        self._lock = threading.RLock()

        # Engine context
        self._engine_state = "UNKNOWN"  # RUNNING, NOT_RUNNING, UNKNOWN
        self._last_trusted_values: Dict[str, Tuple[float, float]] = {}  # {name: (val, time)}

        # Flatline / Stuck detection tracking: {pid: {"val": float, "count": int}}
        self._stuck_tracker: Dict[str, Dict[str, Any]] = {}

        # Active Observations: {obs_key: observation_dict}
        self._active_observations: Dict[str, Dict[str, Any]] = {}

        # Recovery candidates: {obs_key: consecutive_healthy_count}
        self._recovery_candidates: Dict[str, int] = {}

        # Active Hypotheses: {hyp_id: hypothesis_dict}
        self._active_hypotheses: Dict[str, Dict[str, Any]] = {}

        # Bounded history & event logs
        self._recent_events: deque = deque(maxlen=self.event_maxlen)
        self._recent_intelligence: deque = deque(maxlen=self.history_maxlen)

        # Initialize hypotheses base structure
        self._init_hypotheses()

    def _init_hypotheses(self) -> None:
        """Initializes empty hypotheses structures conforming to Phase D-2."""
        base_ids = [
            (HYP_FUEL_SYSTEM_LEAN, "Fuel mixture appears lean", HYPOTHESIS_WARNING),
            (HYP_FUEL_SYSTEM_RICH, "Fuel mixture appears rich", HYPOTHESIS_WARNING),
            (HYP_AIRFLOW_ISSUE, "Airflow measurement or estimation appears inconsistent", HYPOTHESIS_WARNING),
            (HYP_COOLING_ISSUE, "Engine coolant temperature behavior is abnormal", HYPOTHESIS_WARNING),
            (HYP_CORRELATION_ISSUE, "Multi-sensor correlation inconsistency detected", HYPOTHESIS_WARNING),
            (HYP_ELECTRICAL_ISSUE, "Electrical system charging/voltage anomaly detected", HYPOTHESIS_WARNING),
        ]
        for h_id, title, sev in base_ids:
            self._active_hypotheses[h_id] = {
                "id": h_id,
                "title": title,
                "status": HYPOTHESIS_INSUFFICIENT,
                "severity": sev,
                "confidence": CONFIDENCE_LOW,
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "reason": "Yeterli canlı teşhis kanıtı bulunmuyor",
                "next_step": None,
                "last_updated": time.time(),
            }

    # =================================================================
    # LIVE SAMPLE PROCESSING PIPELINE
    # =================================================================
    def process_live_sample(
        self,
        sample: Dict[str, Any],
        quality_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Consumes live sample and its F-2 quality assessment, evaluates observations,
        updates anomaly lifecycles, computes hypotheses, and returns structured intelligence result.
        Thread-safe and failure-isolated.
        """
        try:
            return self._do_process_sample(sample, quality_result)
        except Exception as e:
            logging.error(f"[LIVE_INTEL_ERROR] Exception processing live intelligence: {e}")
            is_dict = isinstance(sample, dict)
            pid = str(sample.get("pid", "UNKNOWN")).upper().strip() if is_dict else "UNKNOWN"
            name = str(sample.get("name", pid)) if is_dict else "UNKNOWN"
            fallback_res = {
                "timestamp": sample.get("timestamp", time.time()) if is_dict else time.time(),
                "sample_pid": pid,
                "sample_name": name,
                "sample_value": sample.get("value") if is_dict else None,
                "quality_state": quality_result.get("quality") if isinstance(quality_result, dict) else QUALITY_ERROR,
                "is_trusted": False,
                "active_observations": [],
                "active_hypotheses": [],
                "events": [],
                "diagnostic_summary": f"Intelligence processing error: {e}",
                "confidence": CONFIDENCE_LOW,
                "severity": SEVERITY_WARNING,
            }
            with self._lock:
                self._recent_intelligence.append(fallback_res)
            return fallback_res

    def _do_process_sample(
        self,
        sample: Dict[str, Any],
        quality_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        pid = str(sample.get("pid", "")).upper().strip()
        name = str(sample.get("name", pid))
        val = sample.get("value")
        ts = float(sample.get("timestamp", time.time()))

        q_res = quality_result if quality_result is not None else {}
        is_trusted = bool(q_res.get("is_trusted", False))
        quality_state = str(q_res.get("quality", QUALITY_INVALID))

        new_events = []

        with self._lock:
            # ---------------------------------------------------------
            # 1. UPDATE ENGINE CONTEXT & TRUSTED LIVE SNAPSHOT
            # ---------------------------------------------------------
            if is_trusted and val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
                val_num = float(val)
                self._last_trusted_values[name] = (val_num, ts)
                if name == "RPM":
                    self._engine_state = "RUNNING" if val_num > 400 else "NOT_RUNNING"

            # ---------------------------------------------------------
            # 2. EVALUATE LIVE OBSERVATIONS FOR CURRENT SIGNAL
            # ---------------------------------------------------------
            current_cycle_obs = self._evaluate_observations_for_signal(sample, q_res)

            # ---------------------------------------------------------
            # 3. UPDATE OBSERVATION LIFECYCLES (PERSISTENCE & RECOVERY)
            # ---------------------------------------------------------
            # Identify which anomalies for this signal are present vs absent
            signal_obs_keys = {obs["key"] for obs in current_cycle_obs}

            # Update present anomalies
            for obs in current_cycle_obs:
                evt = self._update_active_observation(obs, ts)
                if evt:
                    new_events.append(evt)

            # Check recovery for previously active anomalies related to this signal
            active_keys_for_signal = [
                k for k, a_obs in self._active_observations.items()
                if a_obs.get("pid") == pid or a_obs.get("sensor") == name
            ]
            for act_key in active_keys_for_signal:
                if act_key not in signal_obs_keys:
                    rec_evt = self._record_healthy_signal(act_key, ts)
                    if rec_evt:
                        new_events.append(rec_evt)

            # ---------------------------------------------------------
            # 4. HYPOTHESES REASONING (REUSING D-2 WITH LIVE PERSISTENCE)
            # ---------------------------------------------------------
            self._update_hypotheses(ts)

            # ---------------------------------------------------------
            # 5. DEDUPLICATE & EMIT EVENTS
            # ---------------------------------------------------------
            for evt in new_events:
                self._recent_events.append(evt)
                if self._on_diagnostic_event and callable(self._on_diagnostic_event):
                    try:
                        self._on_diagnostic_event(evt)
                    except Exception as cb_err:
                        logging.warning(f"on_diagnostic_event callback exception: {cb_err}")

            # ---------------------------------------------------------
            # 6. CONSTRUCT STRUCTURED INTELLIGENCE RESULT
            # ---------------------------------------------------------
            active_obs_list = [dict(o) for o in self._active_observations.values()]
            active_hyp_list = [dict(h) for h in self._active_hypotheses.values() if h.get("status") in (HYPOTHESIS_POSSIBLE, HYPOTHESIS_SUPPORTED)]

            summary, overall_conf, overall_sev = self._build_diagnostic_summary(active_obs_list, active_hyp_list, is_trusted)

            intel_result = {
                "timestamp": ts,
                "sample_pid": pid,
                "sample_name": name,
                "sample_value": val,
                "quality_state": quality_state,
                "is_trusted": is_trusted,
                "engine_state": self._engine_state,
                "active_observations": active_obs_list,
                "active_hypotheses": active_hyp_list,
                "events": [dict(e) for e in new_events],
                "diagnostic_summary": summary,
                "confidence": overall_conf,
                "severity": overall_sev,
            }

            self._recent_intelligence.append(intel_result)
            return intel_result

    # =================================================================
    # OBSERVATION EVALUATION RULES
    # =================================================================
    def _evaluate_observations_for_signal(
        self,
        sample: Dict[str, Any],
        q_res: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Applies deterministic diagnostic rules to the qualified sample.
        Respects F-2 quality: untrusted data never asserts mechanical vehicle faults!
        """
        pid = str(sample.get("pid", "")).upper().strip()
        name = str(sample.get("name", pid))
        val = sample.get("value")
        quality = str(q_res.get("quality", QUALITY_INVALID))
        is_trusted = bool(q_res.get("is_trusted", False))
        observations = []

        # -------------------------------------------------------------
        # TRUST BOUNDARY CHECK: QUALITY_IMPLAUSIBLE (Sensor Integrity)
        # -------------------------------------------------------------
        if quality == QUALITY_IMPLAUSIBLE:
            phys_status = q_res.get("physical_plausibility", PHYSICS_UNKNOWN)
            observations.append({
                "key": f"SENSOR_IMPLAUSIBLE:{pid}",
                "type": EVENT_SENSOR_IMPLAUSIBLE,
                "pid": pid,
                "sensor": name,
                "value": val,
                "severity": SEVERITY_WARNING,
                "confidence": CONFIDENCE_HIGH,
                "reason": f"{name} sensör ölçümü ({val}) fiziksel sınırların dışında ({phys_status})",
                "is_sensor_fault": True,
            })
            return observations

        # -------------------------------------------------------------
        # TRUST BOUNDARY CHECK: QUALITY_SUSPECT (Rapid Jump)
        # -------------------------------------------------------------
        if quality == QUALITY_SUSPECT:
            rate = q_res.get("rate_of_change")
            observations.append({
                "key": f"RAPID_CHANGE:{pid}",
                "type": EVENT_RAPID_CHANGE,
                "pid": pid,
                "sensor": name,
                "value": val,
                "severity": SEVERITY_WARNING,
                "confidence": CONFIDENCE_MODERATE,
                "reason": f"{name} sensöründe aşırı zamansal değişim hızı tespit edildi ({rate}/s)",
                "is_sensor_fault": True,
            })
            return observations

        # -------------------------------------------------------------
        # TRUST BOUNDARY CHECK: UNTRUSTED / INVALID / ERROR / STALE
        # -------------------------------------------------------------
        if not is_trusted or quality != QUALITY_GOOD or val is None or not isinstance(val, (int, float)) or isinstance(val, bool):
            # Do NOT create mechanical fault observations on corrupt or missing data!
            return observations

        val_num = float(val)

        # -------------------------------------------------------------
        # RULE: Vehicle Operating Envelope Violation (C-6)
        # -------------------------------------------------------------
        env_status = q_res.get("envelope_status", ENVELOPE_UNKNOWN)
        if env_status in (ENVELOPE_OUT_OF_RANGE_HIGH, ENVELOPE_OUT_OF_RANGE_LOW):
            sev = SEVERITY_CRITICAL if name == "RPM" else SEVERITY_WARNING
            observations.append({
                "key": f"ENVELOPE_VIOLATION:{pid}",
                "type": EVENT_OPERATING_ENVELOPE_VIOLATION,
                "pid": pid,
                "sensor": name,
                "value": val_num,
                "severity": sev,
                "confidence": CONFIDENCE_HIGH,
                "reason": f"{name} çalışma zarfı sınırını aştı ({env_status}: {val_num})",
                "is_sensor_fault": False,
            })

        # -------------------------------------------------------------
        # RULE: Cross-Sensor Inconsistency (C-5)
        # -------------------------------------------------------------
        corr_status = q_res.get("correlation_status", CORRELATION_UNKNOWN)
        if corr_status == CORRELATION_INCONSISTENT:
            details = q_res.get("correlation_details", [])
            detail_str = "; ".join(d.get("details", d.get("rule", "")) for d in details if d.get("status") == CORRELATION_INCONSISTENT)
            observations.append({
                "key": f"CORRELATION_ANOMALY:{pid}",
                "type": EVENT_CORRELATION_ANOMALY,
                "pid": pid,
                "sensor": name,
                "value": val_num,
                "severity": SEVERITY_WARNING,
                "confidence": CONFIDENCE_HIGH,
                "reason": f"Sensörler arası çapraz tutarsızlık: {detail_str or 'Inconsistent relationship'}",
                "is_sensor_fault": False,
            })

        # -------------------------------------------------------------
        # RULE: Engine Coolant Temperature Behavior (ECT)
        # -------------------------------------------------------------
        if name == "ECT" and self._engine_state == "RUNNING":
            if val_num > 115.0:
                sev = SEVERITY_CRITICAL if val_num >= 120.0 else SEVERITY_WARNING
                observations.append({
                    "key": "COOLING_OVERHEAT:0105",
                    "type": EVENT_SENSOR_ABNORMAL,
                    "pid": "0105",
                    "sensor": "ECT",
                    "value": val_num,
                    "severity": sev,
                    "confidence": CONFIDENCE_HIGH,
                    "reason": f"Motor aşırı ısınma durumunda: Soğutma suyu sıcaklığı {val_num}°C (>115°C)",
                    "is_sensor_fault": False,
                })

        # -------------------------------------------------------------
        # RULE: Fuel Trim / Mixture Balance (STFT / LTFT)
        # -------------------------------------------------------------
        if name in ("STFT", "LTFT") and self._engine_state == "RUNNING":
            if val_num >= 15.0:
                observations.append({
                    "key": f"FUEL_TRIM_LEAN:{pid}",
                    "type": EVENT_SENSOR_ABNORMAL,
                    "pid": pid,
                    "sensor": name,
                    "value": val_num,
                    "severity": SEVERITY_WARNING,
                    "confidence": CONFIDENCE_MODERATE,
                    "reason": f"Pozitif yakıt trim düzeltmesi yüksek ({name}={val_num}%), fakir karışım telafisi",
                    "is_sensor_fault": False,
                })
            elif val_num <= -15.0:
                observations.append({
                    "key": f"FUEL_TRIM_RICH:{pid}",
                    "type": EVENT_SENSOR_ABNORMAL,
                    "pid": pid,
                    "sensor": name,
                    "value": val_num,
                    "severity": SEVERITY_WARNING,
                    "confidence": CONFIDENCE_MODERATE,
                    "reason": f"Negatif yakıt trim düzeltmesi yüksek ({name}={val_num}%), zengin karışım telafisi",
                    "is_sensor_fault": False,
                })

        # -------------------------------------------------------------
        # RULE: Airflow Measurement with Running Engine (MAF)
        # -------------------------------------------------------------
        if name == "MAF" and self._engine_state == "RUNNING":
            rpm_tuple = self._last_trusted_values.get("RPM")
            rpm_now = rpm_tuple[0] if rpm_tuple else None
            if rpm_now is not None and rpm_now >= 1000 and val_num <= 0.5:
                observations.append({
                    "key": "AIRFLOW_ZERO:0110",
                    "type": EVENT_SENSOR_ABNORMAL,
                    "pid": "0110",
                    "sensor": "MAF",
                    "value": val_num,
                    "severity": SEVERITY_WARNING,
                    "confidence": CONFIDENCE_HIGH,
                    "reason": f"Motor çalışırken ({rpm_now} RPM) hava akışı sıfır veya sıfıra yakın ({val_num} g/s)",
                    "is_sensor_fault": False,
                })

        # -------------------------------------------------------------
        # RULE: Battery Voltage / Charging System
        # -------------------------------------------------------------
        if name in ("Voltaj", "MODULE_VOLT"):
            if self._engine_state == "RUNNING" and val_num < 12.0:
                sev = SEVERITY_CRITICAL if val_num < 11.0 else SEVERITY_WARNING
                observations.append({
                    "key": f"VOLTAGE_LOW:{pid}",
                    "type": EVENT_SENSOR_ABNORMAL,
                    "pid": pid,
                    "sensor": name,
                    "value": val_num,
                    "severity": sev,
                    "confidence": CONFIDENCE_HIGH,
                    "reason": f"Motor çalışırken şarj voltajı yetersiz ({val_num}V < 12.0V)",
                    "is_sensor_fault": False,
                })
            elif val_num > 15.5:
                observations.append({
                    "key": f"VOLTAGE_HIGH:{pid}",
                    "type": EVENT_SENSOR_ABNORMAL,
                    "pid": pid,
                    "sensor": name,
                    "value": val_num,
                    "severity": SEVERITY_WARNING,
                    "confidence": CONFIDENCE_HIGH,
                    "reason": f"Şarj voltajı aşırı yüksek ({val_num}V > 15.5V), regülatör arızası şüphesi",
                    "is_sensor_fault": False,
                })

        # -------------------------------------------------------------
        # RULE: Signal Stuck / Flatlining
        # -------------------------------------------------------------
        if name in ("RPM", "MAP", "SPEED", "TPS") and self._engine_state == "RUNNING":
            stuck_entry = self._stuck_tracker.get(pid, {"val": val_num, "count": 1})
            if stuck_entry["val"] == val_num:
                stuck_entry["count"] += 1
            else:
                stuck_entry = {"val": val_num, "count": 1}
            self._stuck_tracker[pid] = stuck_entry

            if stuck_entry["count"] >= 15:
                observations.append({
                    "key": f"SIGNAL_STUCK:{pid}",
                    "type": EVENT_SIGNAL_STUCK,
                    "pid": pid,
                    "sensor": name,
                    "value": val_num,
                    "severity": SEVERITY_WARNING,
                    "confidence": CONFIDENCE_MODERATE,
                    "reason": f"{name} sensör sinyali motor çalışırken {stuck_entry['count']} çevrim boyunca donuk kaldı ({val_num})",
                    "is_sensor_fault": True,
                })

        return observations

    # =================================================================
    # PERSISTENCE & LIFECYCLE MANAGEMENT
    # =================================================================
    def _update_active_observation(self, obs: Dict[str, Any], timestamp: float) -> Optional[Dict[str, Any]]:
        """
        Updates anomaly persistence state.
        Emits events ONLY on meaningful lifecycle transitions (Deduplication):
        - First detection -> NEW (event emitted)
        - Persistence threshold reached -> PERSISTING (event emitted)
        - Severity increases -> ESCALATING (event emitted)
        - Unchanged persisting -> no event emitted (suppressed duplicate spam)
        """
        key = obs["key"]
        self._recovery_candidates.pop(key, None)  # Reset recovery counter if observed

        if key not in self._active_observations:
            # NEW Anomaly
            record = {
                "key": key,
                "type": obs["type"],
                "pid": obs.get("pid"),
                "sensor": obs.get("sensor"),
                "value": obs.get("value"),
                "severity": obs.get("severity", SEVERITY_WARNING),
                "confidence": obs.get("confidence", CONFIDENCE_MODERATE),
                "reason": obs.get("reason", ""),
                "is_sensor_fault": obs.get("is_sensor_fault", False),
                "lifecycle": LIFECYCLE_NEW,
                "persistence_count": 1,
                "first_seen": timestamp,
                "last_seen": timestamp,
            }
            self._active_observations[key] = record

            # Emit NEW Event
            return self._build_event(record, timestamp, LIFECYCLE_NEW)

        # Already active
        existing = self._active_observations[key]
        existing["persistence_count"] += 1
        existing["last_seen"] = timestamp
        existing["value"] = obs.get("value")

        # Check escalation (e.g. WARNING -> CRITICAL)
        if obs.get("severity") == SEVERITY_CRITICAL and existing["severity"] != SEVERITY_CRITICAL:
            existing["severity"] = SEVERITY_CRITICAL
            existing["lifecycle"] = LIFECYCLE_ESCALATING
            return self._build_event(existing, timestamp, LIFECYCLE_ESCALATING)

        # Check persistence transition
        if existing["persistence_count"] == self.persistence_threshold and existing["lifecycle"] == LIFECYCLE_NEW:
            existing["lifecycle"] = LIFECYCLE_PERSISTING
            return self._build_event(existing, timestamp, LIFECYCLE_PERSISTING)

        # No state change -> deduplicate event (do not emit spam)
        return None

    def _record_healthy_signal(self, key: str, timestamp: float) -> Optional[Dict[str, Any]]:
        """
        Tracks recovery of a previously active anomaly.
        Requires consecutive recovery cycles before marking RESOLVED.
        """
        existing = self._active_observations.get(key)
        if not existing:
            return None

        # Reset stuck counter if applicable
        pid = existing.get("pid")
        if pid and pid in self._stuck_tracker:
            self._stuck_tracker.pop(pid, None)

        self._recovery_candidates[key] = self._recovery_candidates.get(key, 0) + 1
        cnt = self._recovery_candidates[key]

        if cnt == 1:
            existing["lifecycle"] = LIFECYCLE_RECOVERING
            return self._build_event(existing, timestamp, LIFECYCLE_RECOVERING)

        if cnt < self.recovery_threshold:
            return None

        # Fully recovered -> RESOLVED
        self._recovery_candidates.pop(key, None)
        resolved_record = dict(existing)
        resolved_record["lifecycle"] = LIFECYCLE_RESOLVED
        resolved_record["type"] = EVENT_CONDITION_RESOLVED
        resolved_record["resolved_at"] = timestamp

        self._active_observations.pop(key, None)
        return self._build_event(resolved_record, timestamp, LIFECYCLE_RESOLVED)

    def _build_event(self, record: Dict[str, Any], timestamp: float, event_lifecycle: str) -> Dict[str, Any]:
        """Creates a structured diagnostic event."""
        return {
            "event_id": f"EVT_{record['key']}_{int(timestamp * 1000)}",
            "type": record["type"],
            "event_type": record["type"],
            "lifecycle": event_lifecycle,
            "timestamp": timestamp,
            "pid": record.get("pid"),
            "sensor": record.get("sensor"),
            "value": record.get("value"),
            "severity": record.get("severity", SEVERITY_WARNING),
            "confidence": record.get("confidence", CONFIDENCE_MODERATE),
            "reason": record.get("reason", ""),
            "persistence_count": record.get("persistence_count", 1),
            "duration_seconds": round(timestamp - record.get("first_seen", timestamp), 3),
            "is_sensor_fault": record.get("is_sensor_fault", False),
        }

    # =================================================================
    # FAULT HYPOTHESES EVALUATION (REUSING D-2 WITH LIVE EVIDENCE)
    # =================================================================
    def _update_hypotheses(self, timestamp: float) -> None:
        """
        Updates active hypotheses based on currently active persistent observations.
        Preserves uncertainty: never asserts confirmed mechanical failure!
        """
        active_keys = set(self._active_observations.keys())

        # 1. COOLING SYSTEM ISSUE
        h_cool = self._active_hypotheses[HYP_COOLING_ISSUE]
        if "COOLING_OVERHEAT:0105" in active_keys:
            obs = self._active_observations["COOLING_OVERHEAT:0105"]
            h_cool["status"] = HYPOTHESIS_SUPPORTED
            h_cool["severity"] = obs["severity"]
            h_cool["confidence"] = CONFIDENCE_HIGH if obs["persistence_count"] >= self.persistence_threshold else CONFIDENCE_MODERATE
            h_cool["supporting_evidence"] = [obs["reason"]]
            h_cool["reason"] = "Canlı soğutma suyu sıcaklığında aşırı yükselme tespit edildi"
            h_cool["last_updated"] = timestamp
        else:
            h_cool["status"] = HYPOTHESIS_INSUFFICIENT
            h_cool["confidence"] = CONFIDENCE_LOW
            h_cool["supporting_evidence"] = []

        # 2. FUEL SYSTEM LEAN
        h_lean = self._active_hypotheses[HYP_FUEL_SYSTEM_LEAN]
        lean_keys = [k for k in active_keys if k.startswith("FUEL_TRIM_LEAN")]
        if lean_keys:
            obs = self._active_observations[lean_keys[0]]
            h_lean["status"] = HYPOTHESIS_SUPPORTED if obs["persistence_count"] >= self.persistence_threshold else HYPOTHESIS_POSSIBLE
            h_lean["confidence"] = CONFIDENCE_HIGH if obs["persistence_count"] >= self.persistence_threshold + 2 else CONFIDENCE_MODERATE
            h_lean["supporting_evidence"] = [obs["reason"]]
            h_lean["reason"] = "Yakıt trim değerlerinde sürekli pozitif zenginleştirme telafisi gözlendi"
            h_lean["last_updated"] = timestamp
        else:
            h_lean["status"] = HYPOTHESIS_INSUFFICIENT
            h_lean["confidence"] = CONFIDENCE_LOW
            h_lean["supporting_evidence"] = []

        # 3. FUEL SYSTEM RICH
        h_rich = self._active_hypotheses[HYP_FUEL_SYSTEM_RICH]
        rich_keys = [k for k in active_keys if k.startswith("FUEL_TRIM_RICH")]
        if rich_keys:
            obs = self._active_observations[rich_keys[0]]
            h_rich["status"] = HYPOTHESIS_SUPPORTED if obs["persistence_count"] >= self.persistence_threshold else HYPOTHESIS_POSSIBLE
            h_rich["confidence"] = CONFIDENCE_MODERATE
            h_rich["supporting_evidence"] = [obs["reason"]]
            h_rich["reason"] = "Yakıt trim değerlerinde sürekli negatif fakirleştirme telafisi gözlendi"
            h_rich["last_updated"] = timestamp
        else:
            h_rich["status"] = HYPOTHESIS_INSUFFICIENT
            h_rich["confidence"] = CONFIDENCE_LOW
            h_rich["supporting_evidence"] = []

        # 4. AIRFLOW MEASUREMENT ISSUE
        h_air = self._active_hypotheses[HYP_AIRFLOW_ISSUE]
        if "AIRFLOW_ZERO:0110" in active_keys:
            obs = self._active_observations["AIRFLOW_ZERO:0110"]
            h_air["status"] = HYPOTHESIS_SUPPORTED
            h_air["confidence"] = CONFIDENCE_HIGH
            h_air["supporting_evidence"] = [obs["reason"]]
            h_air["reason"] = "Motor çalışırken MAF hava akış ölçümü sıfır değer üretiyor"
            h_air["last_updated"] = timestamp
        else:
            h_air["status"] = HYPOTHESIS_INSUFFICIENT
            h_air["confidence"] = CONFIDENCE_LOW
            h_air["supporting_evidence"] = []

        # 5. SENSOR CORRELATION ISSUE
        h_corr = self._active_hypotheses[HYP_CORRELATION_ISSUE]
        corr_keys = [k for k in active_keys if k.startswith("CORRELATION_ANOMALY")]
        if corr_keys:
            obs = self._active_observations[corr_keys[0]]
            h_corr["status"] = HYPOTHESIS_SUPPORTED
            h_corr["confidence"] = CONFIDENCE_HIGH
            h_corr["supporting_evidence"] = [obs["reason"]]
            h_corr["reason"] = "Çoklu sensör çapraz tutarlılık kontrolünde uyuşmazlık tespit edildi"
            h_corr["last_updated"] = timestamp
        else:
            h_corr["status"] = HYPOTHESIS_INSUFFICIENT
            h_corr["confidence"] = CONFIDENCE_LOW
            h_corr["supporting_evidence"] = []

        # 6. ELECTRICAL SYSTEM ISSUE
        h_elec = self._active_hypotheses[HYP_ELECTRICAL_ISSUE]
        volt_keys = [k for k in active_keys if k.startswith("VOLTAGE_")]
        if volt_keys:
            obs = self._active_observations[volt_keys[0]]
            h_elec["status"] = HYPOTHESIS_SUPPORTED if obs["persistence_count"] >= self.persistence_threshold else HYPOTHESIS_POSSIBLE
            h_elec["confidence"] = CONFIDENCE_HIGH
            h_elec["supporting_evidence"] = [obs["reason"]]
            h_elec["reason"] = "Sistem voltajı şarj sınırlarının dışında seyrediyor"
            h_elec["last_updated"] = timestamp
        else:
            h_elec["status"] = HYPOTHESIS_INSUFFICIENT
            h_elec["confidence"] = CONFIDENCE_LOW
            h_elec["supporting_evidence"] = []

    def _build_diagnostic_summary(
        self,
        active_obs: List[Dict[str, Any]],
        active_hyps: List[Dict[str, Any]],
        is_trusted: bool,
    ) -> Tuple[str, str, str]:
        """Builds human- and machine-readable diagnostic state summary."""
        if not active_obs and not active_hyps:
            return "Normal live operating state. No active anomalies.", CONFIDENCE_HIGH, SEVERITY_INFO

        criticals = [o for o in active_obs if o.get("severity") == SEVERITY_CRITICAL]
        warnings = [o for o in active_obs if o.get("severity") == SEVERITY_WARNING]

        sev = SEVERITY_CRITICAL if criticals else (SEVERITY_WARNING if warnings else SEVERITY_INFO)
        conf = CONFIDENCE_HIGH if any(o.get("confidence") == CONFIDENCE_HIGH for o in active_obs) else CONFIDENCE_MODERATE

        reasons = [o["reason"] for o in active_obs]
        summary_text = f"Active anomalies ({len(active_obs)}): " + "; ".join(reasons[:2])
        if len(reasons) > 2:
            summary_text += f" (+{len(reasons) - 2} more)"

        return summary_text, conf, sev

    # =================================================================
    # READ APIS (THREAD-SAFE)
    # =================================================================
    def get_current_intelligence(self) -> Dict[str, Any]:
        """Returns snapshot of current diagnostic intelligence state."""
        with self._lock:
            if self._recent_intelligence:
                return dict(self._recent_intelligence[-1])
            return {
                "timestamp": time.time(),
                "engine_state": self._engine_state,
                "active_observations": [],
                "active_hypotheses": [],
                "events": [],
                "diagnostic_summary": "No intelligence data processed yet.",
                "confidence": CONFIDENCE_UNKNOWN,
                "severity": SEVERITY_INFO,
            }

    def get_active_events(self) -> List[Dict[str, Any]]:
        """Returns list of currently active anomaly events."""
        with self._lock:
            events = []
            now = time.time()
            for obs in self._active_observations.values():
                events.append(self._build_event(obs, now, obs["lifecycle"]))
            return events

    def get_recent_events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent diagnostic events from bounded history."""
        with self._lock:
            items = [dict(e) for e in self._recent_events]
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def get_active_hypotheses(self) -> List[Dict[str, Any]]:
        """Returns active hypotheses that are either POSSIBLE or SUPPORTED."""
        with self._lock:
            return [
                dict(h) for h in self._active_hypotheses.values()
                if h.get("status") in (HYPOTHESIS_POSSIBLE, HYPOTHESIS_SUPPORTED)
            ]

    def get_all_hypotheses(self) -> List[Dict[str, Any]]:
        """Returns all tracked diagnostic hypotheses."""
        with self._lock:
            return [dict(h) for h in self._active_hypotheses.values()]

    def get_active_observations(self) -> Dict[str, Dict[str, Any]]:
        """Returns dictionary of active ongoing observations."""
        with self._lock:
            return {k: dict(v) for k, v in self._active_observations.items()}

    def get_intelligence_state(self) -> Dict[str, Any]:
        """Returns consolidated intelligence state for UI and higher layers."""
        with self._lock:
            obs = list(self._active_observations.values())
            hyps = [h for h in self._active_hypotheses.values() if h.get("status") in (HYPOTHESIS_POSSIBLE, HYPOTHESIS_SUPPORTED)]
            critical_cnt = sum(1 for o in obs if o.get("severity") == SEVERITY_CRITICAL)
            warning_cnt = sum(1 for o in obs if o.get("severity") == SEVERITY_WARNING)

            return {
                "engine_state": self._engine_state,
                "active_observation_count": len(obs),
                "active_hypothesis_count": len(hyps),
                "critical_anomaly_count": critical_cnt,
                "warning_anomaly_count": warning_cnt,
                "recent_event_count": len(self._recent_events),
                "observations": [dict(o) for o in obs],
                "hypotheses": [dict(h) for h in hyps],
            }

    def clear_session_state(self) -> None:
        """Resets all live diagnostic intelligence session state cleanly."""
        with self._lock:
            self._engine_state = "UNKNOWN"
            self._last_trusted_values.clear()
            self._stuck_tracker.clear()
            self._active_observations.clear()
            self._recovery_candidates.clear()
            self._recent_events.clear()
            self._recent_intelligence.clear()
            self._init_hypotheses()
            logging.debug("LiveDiagnosticIntelligence session state cleared.")
