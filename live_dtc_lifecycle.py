"""
Seyyanen Diagnostic Engine — Phase F-4: Fault & DTC Lifecycle
=============================================================
Deterministic, non-destructive DTC lifecycle engine.
Builds on Phase F-1 (Live Acquisition), F-2 (Real-Time Quality), and F-3 (Diagnostic Intelligence).
Tracks DTC presence, persistence, recovery, and reappearance across verified snapshots.
Enforces strict trust boundaries: failed reads NEVER falsely resolve DTCs.
Integrates with F-3 live observations while preserving uncertainty.
HARD SAFETY: Strictly read-only. Never executes Mode 04 or erases ECU memory.
"""

import time
import re
import threading
import logging
from collections import deque
from typing import Callable, Optional, Dict, List, Any, Set, Tuple, Union

from motor import (
    AutoExpertEngine,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_EMPTY_RESPONSE,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
)

# Confidence Levels
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MODERATE = "MODERATE"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_UNKNOWN = "UNKNOWN"

# =====================================================================
# F-4 CONSTANTS: DTC LIFECYCLE STATES
# =====================================================================
DTC_UNKNOWN = "UNKNOWN"
DTC_NEW = "NEW"
DTC_ACTIVE = "ACTIVE"
DTC_PERSISTING = "PERSISTING"
DTC_INTERMITTENT = "INTERMITTENT"
DTC_RECOVERING = "RECOVERING"
DTC_RESOLVED = "RESOLVED"
DTC_REAPPEARED = "REAPPEARED"

# Active states set (DTC is considered currently present or suspected)
ACTIVE_DTC_STATES = {DTC_NEW, DTC_ACTIVE, DTC_PERSISTING, DTC_REAPPEARED, DTC_INTERMITTENT}

# Diagnostic Trouble Code Lifecycle Events
EVENT_DTC_FIRST_SEEN = "DTC_FIRST_SEEN"
EVENT_DTC_ACTIVE = "DTC_ACTIVE"
EVENT_DTC_PERSISTING = "DTC_PERSISTING"
EVENT_DTC_DISAPPEARED = "DTC_DISAPPEARED"
EVENT_DTC_RECOVERING = "DTC_RECOVERING"
EVENT_DTC_RESOLVED = "DTC_RESOLVED"
EVENT_DTC_REAPPEARED = "DTC_REAPPEARED"
EVENT_DTC_INTERMITTENT = "DTC_INTERMITTENT"

# Standard DTC Pattern: 1 letter (P, C, B, U) + 4 hex characters
DTC_REGEX = re.compile(r"^[PCBU][0-9A-F]{4}$")

# Deterministic DTC -> Sensor / Subsystem Mapping
DTC_SUBSYSTEM_MAP: Dict[str, Dict[str, Any]] = {
    "P0300": {"subsystem": "IGNITION_MISFIRE", "sensors": ["RPM"], "obs_types": ["SENSOR_ABNORMAL", "RAPID_CHANGE"]},
    "P0301": {"subsystem": "CYLINDER_1_MISFIRE", "sensors": ["RPM"], "obs_types": ["SENSOR_ABNORMAL"]},
    "P0302": {"subsystem": "CYLINDER_2_MISFIRE", "sensors": ["RPM"], "obs_types": ["SENSOR_ABNORMAL"]},
    "P0303": {"subsystem": "CYLINDER_3_MISFIRE", "sensors": ["RPM"], "obs_types": ["SENSOR_ABNORMAL"]},
    "P0304": {"subsystem": "CYLINDER_4_MISFIRE", "sensors": ["RPM"], "obs_types": ["SENSOR_ABNORMAL"]},
    "P0171": {"subsystem": "FUEL_SYSTEM_LEAN", "sensors": ["STFT", "LTFT"], "obs_types": ["SENSOR_ABNORMAL"], "hyp": "FUEL_SYSTEM_LEAN"},
    "P0174": {"subsystem": "FUEL_SYSTEM_LEAN", "sensors": ["STFT", "LTFT"], "obs_types": ["SENSOR_ABNORMAL"], "hyp": "FUEL_SYSTEM_LEAN"},
    "P0172": {"subsystem": "FUEL_SYSTEM_RICH", "sensors": ["STFT", "LTFT"], "obs_types": ["SENSOR_ABNORMAL"], "hyp": "FUEL_SYSTEM_RICH"},
    "P0175": {"subsystem": "FUEL_SYSTEM_RICH", "sensors": ["STFT", "LTFT"], "obs_types": ["SENSOR_ABNORMAL"], "hyp": "FUEL_SYSTEM_RICH"},
    "P0117": {"subsystem": "COOLING_ECT_LOW", "sensors": ["ECT"], "obs_types": ["SENSOR_IMPLAUSIBLE", "SENSOR_ABNORMAL"]},
    "P0118": {"subsystem": "COOLING_ECT_HIGH", "sensors": ["ECT"], "obs_types": ["SENSOR_IMPLAUSIBLE", "SENSOR_ABNORMAL", "OPERATING_ENVELOPE_VIOLATION"]},
    "P0217": {"subsystem": "ENGINE_OVERHEAT", "sensors": ["ECT"], "obs_types": ["SENSOR_ABNORMAL", "OPERATING_ENVELOPE_VIOLATION"], "hyp": "COOLING_SYSTEM_ISSUE"},
    "P0112": {"subsystem": "INTAKE_AIR_TEMP_LOW", "sensors": ["IAT"], "obs_types": ["SENSOR_IMPLAUSIBLE"]},
    "P0113": {"subsystem": "INTAKE_AIR_TEMP_HIGH", "sensors": ["IAT"], "obs_types": ["SENSOR_IMPLAUSIBLE"]},
    "P0101": {"subsystem": "MASS_AIR_FLOW_RANGE", "sensors": ["MAF"], "obs_types": ["SENSOR_ABNORMAL", "CORRELATION_ANOMALY"]},
    "P0102": {"subsystem": "MASS_AIR_FLOW_LOW", "sensors": ["MAF"], "obs_types": ["SENSOR_ABNORMAL", "SIGNAL_STUCK"]},
    "P0103": {"subsystem": "MASS_AIR_FLOW_HIGH", "sensors": ["MAF"], "obs_types": ["SENSOR_ABNORMAL", "OPERATING_ENVELOPE_VIOLATION"]},
    "P0562": {"subsystem": "SYSTEM_VOLTAGE_LOW", "sensors": ["Voltaj", "BATTERY"], "obs_types": ["OPERATING_ENVELOPE_VIOLATION"], "hyp": "ELECTRICAL_SYSTEM_ISSUE"},
    "P0563": {"subsystem": "SYSTEM_VOLTAGE_HIGH", "sensors": ["Voltaj", "BATTERY"], "obs_types": ["OPERATING_ENVELOPE_VIOLATION"], "hyp": "ELECTRICAL_SYSTEM_ISSUE"},
}


class DTCObservationSnapshot:
    """
    Encapsulates a verified DTC acquisition snapshot from the vehicle.
    Distinguishes valid reads (including clean zero-DTC responses) from comm failures.
    """

    def __init__(
        self,
        timestamp: float,
        status: str,
        codes: Optional[List[str]] = None,
        details: Optional[List[Dict[str, Any]]] = None,
        source: str = "PRIMARY",
        raw_response: Any = None,
        error: Optional[str] = None,
    ):
        self.timestamp = float(timestamp)
        self.status = str(status)
        self.source = str(source)
        self.raw_response = raw_response
        self.error = error

        # Determine validity: only clean VALID or legitimate NO_DATA are valid acquisitions
        # TIMEOUT, NO_CONNECTION, SERIAL_ERROR, NRC, EMPTY_RESPONSE are NOT valid DTC observations!
        is_comm_failure = self.status in (
            STATUS_TIMEOUT,
            STATUS_NO_CONNECTION,
            STATUS_WORKER_DOWN,
            STATUS_SERIAL_ERROR,
            STATUS_NRC,
            STATUS_EMPTY_RESPONSE,
        )
        self.is_valid_acquisition = (not is_comm_failure) and (self.error is None)

        # Sanitize and canonicalize DTC codes
        raw_codes = codes or []
        self.codes: List[str] = []
        for c in raw_codes:
            if isinstance(c, str):
                clean_c = c.strip().upper()
                if DTC_REGEX.match(clean_c):
                    if clean_c not in self.codes:
                        self.codes.append(clean_c)

        self.details: List[Dict[str, Any]] = details or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "is_valid_acquisition": self.is_valid_acquisition,
            "codes": list(self.codes),
            "details": [dict(d) for d in self.details],
            "source": self.source,
            "error": self.error,
        }


class DTCRecord:
    """
    Canonical in-memory lifecycle state for a single Diagnostic Trouble Code.
    Maintains timing, presence counters, lifecycle transitions, and evidence associations.
    """

    def __init__(
        self,
        code: str,
        source: str = "PRIMARY",
        description: Optional[str] = None,
        severity: str = SEVERITY_WARNING,
        timestamp: Optional[float] = None,
    ):
        now = timestamp if timestamp is not None else time.time()
        self.code = code.upper().strip()
        self.source = source
        self.description = description
        self.severity = severity
        self.confidence = CONFIDENCE_MODERATE

        # Timestamps
        self.first_seen = now
        self.last_seen = now
        self.last_present = now
        self.resolved_at: Optional[float] = None

        # Counters
        self.observation_count = 1
        self.consecutive_present_count = 1
        self.consecutive_absent_valid_count = 0
        self.reappearance_count = 0

        # State tracking
        self.lifecycle_state = DTC_NEW
        self.previous_state = DTC_UNKNOWN
        self.last_transition = now

        # Live Evidence Correlation
        self.associated_evidence: List[Dict[str, Any]] = []
        self.associated_pids: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "source": self.source,
            "description": self.description,
            "severity": self.severity,
            "confidence": self.confidence,
            "lifecycle_state": self.lifecycle_state,
            "previous_state": self.previous_state,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_present": self.last_present,
            "resolved_at": self.resolved_at,
            "observation_count": self.observation_count,
            "consecutive_present_count": self.consecutive_present_count,
            "consecutive_absent_valid_count": self.consecutive_absent_valid_count,
            "reappearance_count": self.reappearance_count,
            "last_transition": self.last_transition,
            "associated_evidence": [dict(e) for e in self.associated_evidence],
            "associated_pids": list(self.associated_pids),
        }


class LiveDTCLifecycleEngine:
    """
    Phase F-4: Fault & DTC Lifecycle Engine.
    
    Processes verified DTC observation snapshots, executes deterministic lifecycle
    transitions, emits deduplicated events, correlates with F-3 live evidence,
    and maintains bounded thread-safe history.
    """

    def __init__(
        self,
        engine: Optional[AutoExpertEngine] = None,
        intelligence_engine: Optional[Any] = None,
        persistence_threshold: int = 2,
        resolution_threshold: int = 2,
        intermittent_threshold: int = 1,
        history_maxlen: int = 100,
        event_maxlen: int = 100,
        on_dtc_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.engine = engine
        self.intelligence_engine = intelligence_engine
        self.persistence_threshold = max(1, int(persistence_threshold))
        self.resolution_threshold = max(1, int(resolution_threshold))
        self.intermittent_threshold = max(1, int(intermittent_threshold))
        self.history_maxlen = max(10, int(history_maxlen))
        self.event_maxlen = max(10, int(event_maxlen))
        self._on_dtc_event = on_dtc_event

        self._lock = threading.RLock()

        # Tracked DTC Records: {code: DTCRecord}
        self._tracked_dtcs: Dict[str, DTCRecord] = {}

        # Bounded History Deques
        self._recent_snapshots: deque = deque(maxlen=self.history_maxlen)
        self._recent_events: deque = deque(maxlen=self.event_maxlen)

        # Statistics
        self._total_snapshots_processed = 0
        self._valid_snapshots_count = 0
        self._failed_snapshots_count = 0

    # =================================================================
    # SNAPSHOT PROCESSING PIPELINE
    # =================================================================
    def process_dtc_snapshot(
        self,
        snapshot: Union[Dict[str, Any], DTCObservationSnapshot],
    ) -> Dict[str, Any]:
        """
        Processes a DTC snapshot, updates lifecycle states, emits deduplicated events,
        and correlates with live F-3 evidence.
        Thread-safe and failure-isolated.
        """
        try:
            return self._do_process_snapshot(snapshot)
        except Exception as e:
            logging.error(f"[DTC_LIFECYCLE_ERROR] Exception processing DTC snapshot: {e}")
            fallback_res = {
                "timestamp": time.time(),
                "is_valid_acquisition": False,
                "status": "PROCESSING_ERROR",
                "error": str(e),
                "events": [],
                "active_dtcs": self.get_active_dtcs(),
                "summary": f"DTC snapshot processing error: {e}",
            }
            return fallback_res

    def _do_process_snapshot(
        self,
        snapshot: Union[Dict[str, Any], DTCObservationSnapshot],
    ) -> Dict[str, Any]:
        # Coerce to DTCObservationSnapshot if dict
        if isinstance(snapshot, DTCObservationSnapshot):
            snap = snapshot
        elif isinstance(snapshot, dict):
            snap = DTCObservationSnapshot(
                timestamp=snapshot.get("timestamp", time.time()),
                status=snapshot.get("status", STATUS_VALID),
                codes=snapshot.get("codes", []),
                details=snapshot.get("details", []),
                source=snapshot.get("source", "PRIMARY"),
                raw_response=snapshot.get("raw_response"),
                error=snapshot.get("error"),
            )
        else:
            raise ValueError(f"Invalid snapshot object type: {type(snapshot)}")

        ts = snap.timestamp
        new_events: List[Dict[str, Any]] = []

        with self._lock:
            self._total_snapshots_processed += 1
            self._recent_snapshots.append(snap.to_dict())

            # ---------------------------------------------------------
            # TRUST BOUNDARY CHECK: FAILED ACQUISITIONS
            # ---------------------------------------------------------
            if not snap.is_valid_acquisition:
                # Critical Rule: Failed reads (TIMEOUT, NO_CONNECTION, SERIAL_ERROR, NRC)
                # NEVER resolve or alter active DTC lifecycles!
                self._failed_snapshots_count += 1
                logging.debug(f"DTC read failed ({snap.status}): Active DTCs preserved intact.")
                return {
                    "timestamp": ts,
                    "is_valid_acquisition": False,
                    "status": snap.status,
                    "error": snap.error or f"Acquisition status: {snap.status}",
                    "events": [],
                    "active_dtcs": self.get_active_dtcs(),
                    "summary": f"DTC read was not valid ({snap.status}). Previous lifecycle state preserved.",
                }

            self._valid_snapshots_count += 1
            observed_codes = set(snap.codes)

            # ---------------------------------------------------------
            # 1. PROCESS PRESENT DTCS
            # ---------------------------------------------------------
            for code in observed_codes:
                try:
                    evt = self._process_present_dtc(code, snap, ts)
                    if evt:
                        new_events.append(evt)
                except Exception as code_err:
                    logging.error(f"[DTC_PARSE_ERROR] Error updating DTC {code}: {code_err}")

            # ---------------------------------------------------------
            # 2. PROCESS ABSENT DTCS (RECOVERY / RESOLUTION)
            # ---------------------------------------------------------
            # All previously tracked DTCs not present in this valid snapshot
            for code, record in list(self._tracked_dtcs.items()):
                if code not in observed_codes:
                    try:
                        evt = self._process_absent_dtc(record, ts)
                        if evt:
                            new_events.append(evt)
                    except Exception as abs_err:
                        logging.error(f"[DTC_RECOVERY_ERROR] Error updating absent DTC {code}: {abs_err}")

            # ---------------------------------------------------------
            # 3. CORRELATE ACTIVE DTCS WITH F-3 LIVE DIAGNOSTIC EVIDENCE
            # ---------------------------------------------------------
            self._correlate_with_live_intelligence(ts)

            # ---------------------------------------------------------
            # 4. DISPATCH EVENTS DEDUPLICATED
            # ---------------------------------------------------------
            for evt in new_events:
                self._recent_events.append(evt)
                if self._on_dtc_event and callable(self._on_dtc_event):
                    try:
                        self._on_dtc_event(evt)
                    except Exception as cb_err:
                        logging.warning(f"on_dtc_event callback exception: {cb_err}")

            # Construct summary
            active_list = self.get_active_dtcs()
            recovering_list = self.get_recovering_dtcs()
            resolved_list = self.get_resolved_dtcs()

            summary = self._build_lifecycle_summary_text(active_list, recovering_list, resolved_list)

            return {
                "timestamp": ts,
                "is_valid_acquisition": True,
                "status": snap.status,
                "observed_codes_count": len(observed_codes),
                "active_dtcs_count": len(active_list),
                "recovering_dtcs_count": len(recovering_list),
                "resolved_dtcs_count": len(resolved_list),
                "events": [dict(e) for e in new_events],
                "active_dtcs": active_list,
                "recovering_dtcs": recovering_list,
                "resolved_dtcs": resolved_list,
                "summary": summary,
            }

    # =================================================================
    # STATE MACHINE TRANSITIONS (PRESENT & ABSENT)
    # =================================================================
    def _process_present_dtc(self, code: str, snap: DTCObservationSnapshot, timestamp: float) -> Optional[Dict[str, Any]]:
        """Handles lifecycle transition for a DTC observed in the current valid snapshot."""
        # Check description from details or lookup
        description = None
        for d in snap.details:
            if isinstance(d, dict) and d.get("kod") == code:
                description = d.get("aciklama")
                break
        if not description and self.engine and hasattr(self.engine, "dtc_lookup_get"):
            try:
                description = self.engine.dtc_lookup_get(code)
            except Exception:
                pass

        # Severity determination
        sev = SEVERITY_CRITICAL if code.startswith("P0") else SEVERITY_WARNING

        if code not in self._tracked_dtcs:
            # First valid observation: UNKNOWN -> NEW
            record = DTCRecord(code, source=snap.source, description=description, severity=sev, timestamp=timestamp)
            self._tracked_dtcs[code] = record
            return self._build_event(record, timestamp, EVENT_DTC_FIRST_SEEN, DTC_NEW, "DTC first seen in valid ECU read")

        record = self._tracked_dtcs[code]
        record.last_seen = timestamp
        record.last_present = timestamp
        record.observation_count += 1
        record.consecutive_present_count += 1
        record.consecutive_absent_valid_count = 0  # Reset absent counter
        if description and not record.description:
            record.description = description

        prev = record.lifecycle_state

        # Case 1: DTC was previously RESOLVED or RECOVERING -> Reappearance
        if prev in (DTC_RESOLVED, DTC_RECOVERING):
            record.reappearance_count += 1
            record.previous_state = prev
            record.last_transition = timestamp

            if record.reappearance_count >= self.intermittent_threshold:
                record.lifecycle_state = DTC_INTERMITTENT
                return self._build_event(record, timestamp, EVENT_DTC_INTERMITTENT, DTC_INTERMITTENT, "DTC reappeared repeatedly; classified as intermittent")
            else:
                record.lifecycle_state = DTC_REAPPEARED
                return self._build_event(record, timestamp, EVENT_DTC_REAPPEARED, DTC_REAPPEARED, "DTC reappeared after previous disappearance/resolution")

        # Case 2: DTC was NEW -> transitions to ACTIVE on 2nd cycle
        if prev == DTC_NEW:
            record.previous_state = DTC_NEW
            record.lifecycle_state = DTC_ACTIVE
            record.last_transition = timestamp
            return self._build_event(record, timestamp, EVENT_DTC_ACTIVE, DTC_ACTIVE, "DTC confirmed active on subsequent valid observation")

        # Case 3: DTC was ACTIVE -> transitions to PERSISTING at threshold
        if prev == DTC_ACTIVE and record.consecutive_present_count >= self.persistence_threshold:
            record.previous_state = DTC_ACTIVE
            record.lifecycle_state = DTC_PERSISTING
            record.last_transition = timestamp
            return self._build_event(record, timestamp, EVENT_DTC_PERSISTING, DTC_PERSISTING, f"DTC observed persisting across {record.consecutive_present_count} valid cycles")

        # Case 4: Ongoing persisting/intermittent without state transition -> deduplicate!
        return None

    def _process_absent_dtc(self, record: DTCRecord, timestamp: float) -> Optional[Dict[str, Any]]:
        """Handles lifecycle transition for a previously tracked DTC absent from a valid snapshot."""
        # If already resolved, maintain resolved state (deduplicated)
        if record.lifecycle_state == DTC_RESOLVED:
            record.consecutive_absent_valid_count += 1
            return None

        record.consecutive_absent_valid_count += 1
        record.consecutive_present_count = 0  # Reset present counter
        prev = record.lifecycle_state

        # First absent valid observation: ACTIVE/PERSISTING/NEW/REAPPEARED -> RECOVERING
        if prev in (DTC_NEW, DTC_ACTIVE, DTC_PERSISTING, DTC_REAPPEARED, DTC_INTERMITTENT):
            record.previous_state = prev
            record.lifecycle_state = DTC_RECOVERING
            record.last_transition = timestamp
            return self._build_event(
                record,
                timestamp,
                EVENT_DTC_DISAPPEARED,
                DTC_RECOVERING,
                "DTC not observed in latest valid ECU read; entering recovery monitoring",
            )

        # Subsequent absent valid reads while in RECOVERING: check resolution threshold
        if prev == DTC_RECOVERING:
            if record.consecutive_absent_valid_count >= self.resolution_threshold:
                record.previous_state = DTC_RECOVERING
                record.lifecycle_state = DTC_RESOLVED
                record.resolved_at = timestamp
                record.last_transition = timestamp
                return self._build_event(
                    record,
                    timestamp,
                    EVENT_DTC_RESOLVED,
                    DTC_RESOLVED,
                    f"Resolved by observation: DTC absent across {record.consecutive_absent_valid_count} consecutive valid reads (not confirmed physically repaired)",
                )
            else:
                # Deduplicate: still in recovering state below resolution threshold
                return None

        return None

    def _build_event(
        self,
        record: DTCRecord,
        timestamp: float,
        event_type: str,
        new_state: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Creates a structured DTC lifecycle event."""
        return {
            "event_id": f"EVT_DTC_{record.code}_{int(timestamp * 1000)}",
            "event_type": event_type,
            "type": event_type,
            "dtc": record.code,
            "source": record.source,
            "timestamp": timestamp,
            "previous_state": record.previous_state,
            "new_state": new_state,
            "observation_count": record.observation_count,
            "consecutive_present_count": record.consecutive_present_count,
            "consecutive_absent_count": record.consecutive_absent_valid_count,
            "reappearance_count": record.reappearance_count,
            "severity": record.severity,
            "confidence": record.confidence,
            "description": record.description,
            "associated_evidence": [dict(e) for e in record.associated_evidence],
            "associated_pids": list(record.associated_pids),
            "reason": reason,
        }

    # =================================================================
    # F-3 LIVE DIAGNOSTIC EVIDENCE CORRELATION
    # =================================================================
    def _correlate_with_live_intelligence(self, timestamp: float) -> None:
        """
        Correlates active DTCs with live diagnostic observations and hypotheses from F-3.
        Only associates deterministic mappings; unknown relationships remain unknown.
        """
        if not self.intelligence_engine or not hasattr(self.intelligence_engine, "get_active_observations"):
            return

        try:
            active_obs = self.intelligence_engine.get_active_observations()
            active_hyps = self.intelligence_engine.get_active_hypotheses() if hasattr(self.intelligence_engine, "get_active_hypotheses") else []
        except Exception as e:
            logging.debug(f"Live evidence retrieval exception: {e}")
            return

        for code, record in self._tracked_dtcs.items():
            # Only correlate currently active or recovering DTCs
            if record.lifecycle_state == DTC_RESOLVED:
                continue

            mapping = DTC_SUBSYSTEM_MAP.get(code)
            if not mapping:
                # No deterministic mapping: leave unknown
                continue

            target_sensors = set(mapping.get("sensors", []))
            target_types = set(mapping.get("obs_types", []))
            target_hyp = mapping.get("hyp")

            matched_evidence = []
            matched_pids = set()

            # Correlate with active live observations
            for obs_key, obs in active_obs.items():
                sensor = obs.get("sensor")
                obs_type = obs.get("type")
                pid = obs.get("pid")

                if (sensor in target_sensors) or (obs_type in target_types and sensor in target_sensors):
                    matched_evidence.append({
                        "key": obs_key,
                        "type": obs_type,
                        "sensor": sensor,
                        "reason": obs.get("reason"),
                        "severity": obs.get("severity"),
                        "first_seen": obs.get("first_seen"),
                    })
                    if pid:
                        matched_pids.add(pid)

            # Correlate with active hypotheses
            if target_hyp:
                for h in active_hyps:
                    if h.get("id") == target_hyp:
                        matched_evidence.append({
                            "type": "HYPOTHESIS_CORROBORATION",
                            "hypothesis_id": h.get("id"),
                            "status": h.get("status"),
                            "confidence": h.get("confidence"),
                            "reason": h.get("reason"),
                        })

            record.associated_evidence = matched_evidence
            record.associated_pids = list(matched_pids)

            # Corroborate confidence: high if backed by active live sensor evidence
            if matched_evidence:
                record.confidence = CONFIDENCE_HIGH
            else:
                record.confidence = CONFIDENCE_MODERATE

    def _build_lifecycle_summary_text(
        self,
        active: List[Dict[str, Any]],
        recovering: List[Dict[str, Any]],
        resolved: List[Dict[str, Any]],
    ) -> str:
        """Builds human-readable summary of current DTC lifecycle state."""
        parts = []
        if active:
            codes_str = ", ".join(d["code"] for d in active)
            parts.append(f"Active DTCs ({len(active)}): {codes_str}")
        if recovering:
            rec_str = ", ".join(d["code"] for d in recovering)
            parts.append(f"Recovering ({len(recovering)}): {rec_str}")
        if resolved:
            parts.append(f"Resolved by observation: {len(resolved)}")
        if not parts:
            return "No DTCs tracked in fault memory."
        return "; ".join(parts)

    # =================================================================
    # READ APIS (THREAD-SAFE & DEFENSIVE COPIES)
    # =================================================================
    def get_dtc_state(self, code: str) -> Optional[Dict[str, Any]]:
        """Returns snapshot of lifecycle state for a specific DTC code, or None."""
        clean_code = code.strip().upper()
        with self._lock:
            record = self._tracked_dtcs.get(clean_code)
            return record.to_dict() if record else None

    def get_all_dtc_states(self) -> Dict[str, Dict[str, Any]]:
        """Returns dictionary of all tracked DTCs and their lifecycle states."""
        with self._lock:
            return {c: r.to_dict() for c, r in self._tracked_dtcs.items()}

    def get_active_dtcs(self) -> List[Dict[str, Any]]:
        """Returns list of currently active DTCs (NEW, ACTIVE, PERSISTING, REAPPEARED, INTERMITTENT)."""
        with self._lock:
            return [
                r.to_dict() for r in self._tracked_dtcs.values()
                if r.lifecycle_state in ACTIVE_DTC_STATES
            ]

    def get_recovering_dtcs(self) -> List[Dict[str, Any]]:
        """Returns list of DTCs currently in RECOVERING state."""
        with self._lock:
            return [
                r.to_dict() for r in self._tracked_dtcs.values()
                if r.lifecycle_state == DTC_RECOVERING
            ]

    def get_resolved_dtcs(self) -> List[Dict[str, Any]]:
        """Returns list of DTCs in RESOLVED state (resolved by observation)."""
        with self._lock:
            return [
                r.to_dict() for r in self._tracked_dtcs.values()
                if r.lifecycle_state == DTC_RESOLVED
            ]

    def get_recent_dtc_events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent DTC lifecycle events from bounded history."""
        with self._lock:
            items = [dict(e) for e in self._recent_events]
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def get_recent_snapshots(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent DTC observation snapshots."""
        with self._lock:
            items = [dict(s) for s in self._recent_snapshots]
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def get_dtc_lifecycle_summary(self) -> Dict[str, Any]:
        """Returns consolidated DTC lifecycle metrics and summary."""
        with self._lock:
            active = self.get_active_dtcs()
            recovering = self.get_recovering_dtcs()
            resolved = self.get_resolved_dtcs()
            critical_count = sum(1 for d in active if d.get("severity") == SEVERITY_CRITICAL)

            return {
                "total_snapshots_processed": self._total_snapshots_processed,
                "valid_snapshots_count": self._valid_snapshots_count,
                "failed_snapshots_count": self._failed_snapshots_count,
                "active_dtc_count": len(active),
                "recovering_dtc_count": len(recovering),
                "resolved_dtc_count": len(resolved),
                "critical_dtc_count": critical_count,
                "active_codes": [d["code"] for d in active],
                "recent_event_count": len(self._recent_events),
                "summary": self._build_lifecycle_summary_text(active, recovering, resolved),
            }

    # =================================================================
    # NON-DESTRUCTIVE SESSION RESET
    # =================================================================
    def reset_session(self) -> None:
        """
        Resets in-memory DTC lifecycle tracking for this application session.
        HARD SAFETY: Strictly in-memory. NEVER communicates Mode 04 or erases ECU memory!
        """
        with self._lock:
            self._tracked_dtcs.clear()
            self._recent_snapshots.clear()
            self._recent_events.clear()
            self._total_snapshots_processed = 0
            self._valid_snapshots_count = 0
            self._failed_snapshots_count = 0
            logging.debug("LiveDTCLifecycleEngine session state reset cleanly.")
