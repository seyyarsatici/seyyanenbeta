"""
Seyyanen Diagnostic Engine — Phase F-1: Live Acquisition Runtime
================================================================
Continuous, drift-controlled, thread-safe, and cancellable live acquisition layer.
Integrates with existing AutoExpertEngine and SerialIOThread priority queue.
"""

import math
import time
import threading
import logging
import uuid
import queue
from collections import deque
from typing import Callable, Optional, Dict, List, Any, Tuple, Union

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
    STATUS_DID_MISMATCH,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    QUALITY_SUSPECT,
    derive_quality_from_status,
)
from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterConnectionState,
    ELM327DiagnosticAdapter,
    PROHIBITED_SERVICES,
)
try:
    from diagnostic_persistence import DiagnosticRepository
except ImportError:
    DiagnosticRepository = None

# =====================================================================
# F-1.1: RUNTIME STATES
# =====================================================================
LIVE_IDLE = "LIVE_IDLE"
LIVE_STARTING = "LIVE_STARTING"
LIVE_RUNNING = "LIVE_RUNNING"
LIVE_DEGRADED = "LIVE_DEGRADED"
LIVE_STOPPING = "LIVE_STOPPING"
LIVE_STOPPED = "LIVE_STOPPED"
LIVE_ERROR = "LIVE_ERROR"

VALID_TRANSITIONS = {
    LIVE_IDLE: {LIVE_STARTING},
    LIVE_STARTING: {LIVE_RUNNING, LIVE_DEGRADED, LIVE_ERROR, LIVE_STOPPED, LIVE_STOPPING},
    LIVE_RUNNING: {LIVE_DEGRADED, LIVE_STOPPING, LIVE_ERROR},
    LIVE_DEGRADED: {LIVE_RUNNING, LIVE_STOPPING, LIVE_ERROR},
    LIVE_STOPPING: {LIVE_STOPPED, LIVE_ERROR},
    LIVE_STOPPED: {LIVE_STARTING},  # Can be restarted
    LIVE_ERROR: {LIVE_STOPPING, LIVE_STOPPED, LIVE_STARTING, LIVE_DEGRADED},
}

# =====================================================================
# STANDARD PID METADATA & DECODERS (Mode 01)
# =====================================================================
DEFAULT_PID_CATALOG: Dict[str, Dict[str, Any]] = {
    "010C": {"name": "RPM", "unit": "rpm", "decode": lambda x: (x[0]*256 + x[1]) / 4},
    "010D": {"name": "SPEED", "unit": "km/h", "decode": lambda x: x[0]},
    "0105": {"name": "ECT", "unit": "°C", "decode": lambda x: x[0] - 40},
    "010B": {"name": "MAP", "unit": "kPa", "decode": lambda x: x[0]},
    "0111": {"name": "TPS", "unit": "%", "decode": lambda x: x[0] * 100 / 255},
    "0104": {"name": "LOAD", "unit": "%", "decode": lambda x: x[0] * 100 / 255},
    "010F": {"name": "IAT", "unit": "°C", "decode": lambda x: x[0] - 40},
    "0110": {"name": "MAF", "unit": "g/s", "decode": lambda x: (x[0]*256 + x[1]) / 100},
    "0106": {"name": "STFT", "unit": "%", "decode": lambda x: (x[0] - 128) * 100 / 128},
    "0107": {"name": "LTFT", "unit": "%", "decode": lambda x: (x[0] - 128) * 100 / 128},
    "0114": {"name": "O2_B1S1_V", "unit": "V", "decode": lambda x: x[0] * 0.005 if len(x)>0 else None},
    "011F": {"name": "RUN_TIME", "unit": "s", "decode": lambda x: (x[0]*256 + x[1])},
}

DEFAULT_LIVE_PIDS = ["010C", "010D", "0105", "010B", "0111"]


class LiveAcquisitionRuntime:
    """
    Phase F-1: Live Acquisition Runtime Engine.
    
    Provides continuous, drift-managed polling of OBD-II PIDs over an existing
    AutoExpertEngine without duplicating serial communication or worker threads.
    """

    def __init__(
        self,
        engine: Optional[AutoExpertEngine] = None,
        pids: Optional[List[str]] = None,
        cycle_interval: float = 0.1,
        history_maxlen: int = 200,
        on_sample: Optional[Callable[[Dict[str, Any]], None]] = None,
        quality_assessor: Optional[Any] = None,
        intelligence_engine: Optional[Any] = None,
        dtc_lifecycle_engine: Optional[Any] = None,
        safety_manager: Optional[Any] = None,
        adapter: Optional[DiagnosticAdapter] = None,
        repository: Optional[Any] = None,
        session_id: Optional[str] = None,
        vehicle_id: Optional[str] = None,
        vehicle_context: Optional[Any] = None,
        target_ecu: str = "ECM",
        persistence_queue_size: int = 1000,
    ):
        self.engine = engine if engine is not None else AutoExpertEngine()
        if adapter is not None:
            self.adapter = adapter
        else:
            try:
                self.adapter = ELM327DiagnosticAdapter(engine=self.engine)
            except Exception as e:
                logging.warning(f"Could not initialize ELM327DiagnosticAdapter: {e}")
                self.adapter = None

        # J-3 Persistence Integration & Multi-ECU / Vehicle Context
        self.repository = repository
        self.session_id = session_id or f"live_sess_{uuid.uuid4().hex[:10]}"
        self.vehicle_id = vehicle_id
        self.vehicle_context = vehicle_context
        self.target_ecu = str(target_ecu).upper().strip() if target_ecu else "ECM"
        self.persistence_queue_size = max(50, int(persistence_queue_size))
        
        # Standardize PID format (ensure 4 chars e.g. "010C")
        raw_pids = pids if pids is not None else DEFAULT_LIVE_PIDS
        self.pids = [p.upper().strip() if len(p.strip()) == 4 else f"01{p.upper().strip()}" for p in raw_pids]
        
        self.cycle_interval = max(0.01, float(cycle_interval))
        self.history_maxlen = max(10, int(history_maxlen))
        self._on_sample = on_sample

        # Phase F-2: Real-Time Data Quality Assessor
        if quality_assessor is not None:
            self.quality_assessor = quality_assessor
        else:
            try:
                from live_quality import LiveQualityAssessor
                self.quality_assessor = LiveQualityAssessor(
                    engine=self.engine,
                    history_maxlen=self.history_maxlen,
                )
            except Exception as e:
                logging.warning(f"Could not initialize LiveQualityAssessor: {e}")
                self.quality_assessor = None

        # Phase F-3: Live Diagnostic Intelligence Engine
        if intelligence_engine is not None:
            self.intelligence_engine = intelligence_engine
        else:
            try:
                from live_intelligence import LiveDiagnosticIntelligence
                self.intelligence_engine = LiveDiagnosticIntelligence(
                    engine=self.engine,
                    history_maxlen=self.history_maxlen,
                )
            except Exception as e:
                logging.warning(f"Could not initialize LiveDiagnosticIntelligence: {e}")
                self.intelligence_engine = None

        # Phase F-4: Fault & DTC Lifecycle Engine
        if dtc_lifecycle_engine is not None:
            self.dtc_lifecycle_engine = dtc_lifecycle_engine
        else:
            try:
                from live_dtc_lifecycle import LiveDTCLifecycleEngine
                self.dtc_lifecycle_engine = LiveDTCLifecycleEngine(
                    engine=self.engine,
                    intelligence_engine=self.intelligence_engine,
                    history_maxlen=self.history_maxlen,
                )
            except Exception as e:
                logging.warning(f"Could not initialize LiveDTCLifecycleEngine: {e}")
                self.dtc_lifecycle_engine = None

        # Phase F-5: Runtime Safety & Recovery Manager
        if safety_manager is not None:
            self.safety_manager = safety_manager
        else:
            try:
                from live_safety import RuntimeSafetyManager
                self.safety_manager = RuntimeSafetyManager(
                    pids=self.pids,
                    history_maxlen=self.history_maxlen,
                )
            except Exception as e:
                logging.warning(f"Could not initialize RuntimeSafetyManager: {e}")
                self.safety_manager = None

        # State management
        self._state = LIVE_IDLE
        self._state_lock = threading.RLock()
        self._error_reason: Optional[str] = None

        # Concurrency & Worker
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Decoupled Persistence Worker (Phase K-3)
        self._persistence_queue: queue.Queue = queue.Queue(maxsize=self.persistence_queue_size)
        self._persistence_thread: Optional[threading.Thread] = None
        self._persistence_stop_event = threading.Event()
        self._persistence_written_count = 0
        self._persistence_dropped_count = 0
        self._persistence_error_count = 0

        # Bounded Sample History & Value Caches
        self._sample_lock = threading.RLock()
        self._recent_samples: deque = deque(maxlen=self.history_maxlen)
        self._latest_by_pid: Dict[str, Dict[str, Any]] = {}
        self._latest_successful_by_pid: Dict[str, Dict[str, Any]] = {}

        # Runtime Statistics
        self._stats_lock = threading.Lock()
        self._reconnect_lock = threading.Lock()
        self._dtc_poll_lock = threading.Lock()
        self._cycle_count = 0
        self._successful_reads = 0
        self._failed_reads = 0
        self._sequence_counter = 0
        self._start_monotonic: Optional[float] = None
        self._start_wall_time: Optional[float] = None

    # =================================================================
    # STATE MANAGEMENT
    # =================================================================
    def get_state(self) -> str:
        """Returns the current state of the live runtime."""
        with self._state_lock:
            return self._state

    def is_running(self) -> bool:
        """Returns True if runtime is actively running or degraded."""
        with self._state_lock:
            active = self._state in (LIVE_RUNNING, LIVE_DEGRADED)
            if active:
                if self._worker_thread is None or not self._worker_thread.is_alive():
                    # Worker thread died unexpectedly
                    self._state = LIVE_ERROR
                    self._error_reason = "Worker thread died unexpectedly"
                    if hasattr(self, "safety_manager") and self.safety_manager is not None:
                        self.safety_manager.record_failure(
                            category="WORKER_FAILURE",
                            component="LiveAcquisitionWorker",
                            severity="CRITICAL",
                            reason="Worker thread died unexpectedly while state was active",
                        )
                    return False
            return active

    def get_error_reason(self) -> Optional[str]:
        """Returns the error message if runtime transitioned to LIVE_ERROR."""
        with self._state_lock:
            return self._error_reason

    def _transition_state(self, new_state: str, error_reason: Optional[str] = None) -> bool:
        """Controlled transition between runtime states."""
        with self._state_lock:
            allowed = VALID_TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                logging.warning(f"Illegal state transition attempted: {self._state} -> {new_state}")
                return False
            self._state = new_state
            if error_reason:
                self._error_reason = error_reason
            logging.debug(f"LiveRuntime state changed: {self._state}")
            return True

    # =================================================================
    # ADAPTER CONNECTION LIFECYCLE (PHASE K-1)
    # =================================================================
    @property
    def connection_state(self) -> AdapterConnectionState:
        """Exposes authoritative adapter connection state."""
        if hasattr(self, "adapter") and self.adapter is not None:
            return self.adapter.connection_state
        is_open = bool(self.engine and hasattr(self.engine, "ser") and self.engine.ser and getattr(self.engine.ser, "is_open", False))
        return AdapterConnectionState.CONNECTED if is_open else AdapterConnectionState.DISCONNECTED

    def is_connected(self) -> bool:
        """Check whether the underlying adapter/serial is connected."""
        return self.connection_state == AdapterConnectionState.CONNECTED

    def connect(self, timeout: float = 5.0) -> bool:
        """Synchronous connect via authoritative adapter or engine."""
        if hasattr(self, "adapter") and self.adapter is not None:
            try:
                return self.adapter.connect(timeout=timeout)
            except Exception as e:
                logging.warning(f"LiveRuntime adapter connect failed: {e}")
                return False
        if hasattr(self.engine, "baglan"):
            return bool(self.engine.baglan())
        return False

    def connect_async(self, timeout: float = 5.0, on_finished: Optional[Callable[[bool, Optional[Exception]], None]] = None) -> bool:
        """Non-blocking connect via authoritative adapter."""
        if hasattr(self, "adapter") and self.adapter is not None:
            return self.adapter.connect_async(timeout=timeout, on_finished=on_finished)
        return False

    # =================================================================
    # LIFECYCLE (START / STOP)
    # =================================================================
    def start(self) -> bool:
        """
        Starts live acquisition in a background worker thread.
        Protected against duplicate start calls.

        SAFETY NOTE: connect() is intentionally called OUTSIDE the state lock to
        avoid blocking concurrent get_state()/is_running() callers for the full
        serial port connection timeout (up to 5 s). The state is set to
        LIVE_STARTING before releasing the lock, so duplicate start calls that
        arrive during connection are correctly rejected.
        """
        # --- Phase 1: Guard and claim LIVE_STARTING (lock held briefly) ---
        with self._state_lock:
            if self._state in (LIVE_RUNNING, LIVE_STARTING, LIVE_DEGRADED):
                logging.warning("LiveRuntime is already running or starting. Duplicate start call ignored.")
                return False
            if not self._transition_state(LIVE_STARTING):
                return False
            already_connected = self.is_connected()

        # --- Phase 2: Connect outside the lock (may block up to timeout) ---
        if not already_connected:
            if not self.connect():
                with self._state_lock:
                    self._transition_state(LIVE_ERROR, "Serial port connection failed during start")
                return False

        # --- Phase 3: Launch workers (lock held briefly) ---
        with self._state_lock:
            # Re-check: stop() may have fired while we were connecting
            if self._state not in (LIVE_STARTING, LIVE_ERROR):
                logging.warning("LiveRuntime state changed while connecting; start aborted.")
                return False
            if self._state == LIVE_ERROR:
                logging.warning("LiveRuntime entered error state while connecting; start aborted.")
                return False

            # Reset lifecycle control
            self._stop_event.clear()
            self._error_reason = None
            with self._stats_lock:
                self._start_monotonic = time.monotonic()
                self._start_wall_time = time.time()

            # Start decoupled persistence worker if repository is configured
            if self.repository is not None and (self._persistence_thread is None or not self._persistence_thread.is_alive()):
                self._persistence_stop_event.clear()
                self._persistence_thread = threading.Thread(
                    target=self._persistence_loop,
                    name="LivePersistenceWorker",
                    daemon=True,
                )
                self._persistence_thread.start()

            self._worker_thread = threading.Thread(
                target=self._acquisition_loop,
                name="LiveAcquisitionWorker",
                daemon=True,
            )
            self._worker_thread.start()

            self._transition_state(LIVE_RUNNING)
            logging.debug("LiveRuntime worker started successfully.")
            return True

    def stop(self, timeout: float = 2.0) -> bool:
        """
        Stops live acquisition cleanly and joins worker thread.
        Idempotent: safe to call repeatedly.
        """
        with self._state_lock:
            if self._state in (LIVE_STOPPED, LIVE_IDLE):
                return True

            current = self._state
            if current not in (LIVE_STOPPING, LIVE_ERROR):
                self._transition_state(LIVE_STOPPING)

        # Signal stop events
        self._stop_event.set()
        self._persistence_stop_event.set()

        # Phase K-1: Cancel any in-progress adapter connection attempt
        if hasattr(self, "adapter") and self.adapter is not None:
            if self.adapter.connection_state == AdapterConnectionState.CONNECTING:
                try:
                    self.adapter.disconnect()
                except Exception as e:
                    logging.debug(f"Adapter disconnect during runtime stop: {e}")

        # Join worker thread without holding state lock
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logging.warning(f"LiveAcquisitionWorker did not terminate within {timeout}s")

        # Join persistence thread without holding state lock
        if self._persistence_thread and self._persistence_thread.is_alive():
            self._persistence_thread.join(timeout=timeout)
            if self._persistence_thread.is_alive():
                logging.warning(f"LivePersistenceWorker did not terminate within {timeout}s")

        with self._state_lock:
            if self._state != LIVE_ERROR:
                self._state = LIVE_STOPPED
            logging.debug("LiveRuntime stopped cleanly.")
            return True

    # =================================================================
    # DATA ACCESS API (THREAD-SAFE)
    # =================================================================
    def get_latest_sample(self, pid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Returns the latest sample for a specific PID, or a dictionary of all latest samples.
        Note: The latest sample reflects the last poll result, which may be a failure.
        """
        with self._sample_lock:
            if pid is not None:
                clean_pid = pid.upper().strip()
                if len(clean_pid) == 2:
                    clean_pid = f"01{clean_pid}"
                sample = self._latest_by_pid.get(clean_pid)
                return dict(sample) if sample else None
            return {p: dict(s) for p, s in self._latest_by_pid.items()}

    def get_latest_successful(self, pid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Returns the last KNOWN SUCCESSFUL (STATUS_VALID) sample for a specific PID,
        or a dictionary of all latest successful samples.
        Preserved across subsequent transient query failures (timeouts, NO DATA).
        """
        with self._sample_lock:
            if pid is not None:
                clean_pid = pid.upper().strip()
                if len(clean_pid) == 2:
                    clean_pid = f"01{clean_pid}"
                sample = self._latest_successful_by_pid.get(clean_pid)
                return dict(sample) if sample else None
            return {p: dict(s) for p, s in self._latest_successful_by_pid.items()}

    # Alias for naming consistency
    get_latest_successful_sample = get_latest_successful

    def get_recent_samples(self, limit: Optional[int] = None, pid: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns recent samples from the bounded history buffer (oldest to newest).
        Optionally filtered by PID and truncated to `limit`.
        """
        with self._sample_lock:
            if pid is not None:
                clean_pid = pid.upper().strip()
                if len(clean_pid) == 2:
                    clean_pid = f"01{clean_pid}"
                filtered = [dict(s) for s in self._recent_samples if s["pid"] == clean_pid]
            else:
                filtered = [dict(s) for s in self._recent_samples]

        if limit is not None and limit > 0:
            return filtered[-limit:]
        return filtered

    def get_runtime_stats(self) -> Dict[str, Any]:
        """Returns diagnostic statistics for the current runtime session."""
        with self._stats_lock:
            cycle_cnt = self._cycle_count
            succ = self._successful_reads
            fail = self._failed_reads
            start_m = self._start_monotonic
            now_m = time.monotonic()
            elapsed = (now_m - start_m) if start_m is not None else 0.0
            p_written = self._persistence_written_count
            p_dropped = self._persistence_dropped_count
            p_errors = self._persistence_error_count
            p_queue_size = self._persistence_queue.qsize()

        total_reads = succ + fail
        sample_rate = (total_reads / elapsed) if elapsed > 0.05 else 0.0

        with self._sample_lock:
            history_size = len(self._recent_samples)

        return {
            "state": self.get_state(),
            "cycle_count": cycle_cnt,
            "successful_reads": succ,
            "failed_reads": fail,
            "total_reads": total_reads,
            "elapsed_time": round(elapsed, 3),
            "elapsed_time_sec": round(elapsed, 3),
            "effective_sample_rate": round(sample_rate, 2),
            "sample_rate_sps": round(sample_rate, 2),
            "pids_count": len(self.pids),
            "history_size": history_size,
            "history_maxlen": self.history_maxlen,
            "persistence_written": p_written,
            "persistence_dropped": p_dropped,
            "persistence_errors": p_errors,
            "persistence_queue_size": p_queue_size,
            "target_ecu": getattr(self, "target_ecu", "ECM"),
            "vehicle_id": getattr(self, "vehicle_id", None),
        }

    # =================================================================
    # MULTI-ECU & VEHICLE IDENTITY ACCESSORS (PHASE K-3)
    # =================================================================
    def set_target_ecu(self, ecu_id: str) -> None:
        """Sets target ECU context for subsequent acquisitions."""
        with self._state_lock:
            self.target_ecu = str(ecu_id).upper().strip()

    def get_target_ecu(self) -> str:
        """Returns the current target ECU context."""
        with self._state_lock:
            return self.target_ecu

    def set_vehicle_context(self, vehicle_id: Optional[str], vehicle_context: Optional[Any] = None) -> None:
        """
        Updates active vehicle identity.
        If vehicle identity changes, flushes stale latest/history caches to avoid cross-vehicle contamination.
        """
        with self._state_lock:
            if self.vehicle_id != vehicle_id:
                with self._sample_lock:
                    self._recent_samples.clear()
                    self._latest_by_pid.clear()
                    self._latest_successful_by_pid.clear()
            self.vehicle_id = vehicle_id
            self.vehicle_context = vehicle_context

    def invalidate_vehicle_context(self) -> None:
        """Explicitly invalidates vehicle identity, clearing caches to prevent stale data pollution."""
        with self._state_lock:
            self.vehicle_id = None
            self.vehicle_context = None
            with self._sample_lock:
                self._recent_samples.clear()
                self._latest_by_pid.clear()
                self._latest_successful_by_pid.clear()

    # =================================================================
    # PHASE F-2: REAL-TIME DATA QUALITY ACCESSORS
    # =================================================================
    def get_quality(self, pid: Optional[str] = None) -> Any:
        """Returns structured quality result for one PID, or dict of all PIDs."""
        if not self.quality_assessor:
            return None
        if pid is not None:
            return self.quality_assessor.get_quality(pid)
        return self.quality_assessor.get_all_quality()

    def get_quality_snapshot(self) -> Dict[str, Any]:
        """Returns consolidated quality status summary across all live signals."""
        if not self.quality_assessor:
            return {}
        return self.quality_assessor.get_quality_snapshot()

    def get_quality_transitions(self, pid: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent quality transition events."""
        if not self.quality_assessor:
            return []
        return self.quality_assessor.get_quality_transitions(pid=pid, limit=limit)

    def get_quality_history(self, pid: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns bounded quality evaluation history."""
        if not self.quality_assessor:
            return []
        return self.quality_assessor.get_quality_history(pid=pid, limit=limit)

    def get_trusted_value(self, pid: str) -> Optional[float]:
        """Returns live value only if VALID, QUALITY_GOOD, and fresh."""
        if not self.quality_assessor:
            return None
        return self.quality_assessor.get_trusted_value(pid)

    # =================================================================
    # PHASE F-3: LIVE DIAGNOSTIC INTELLIGENCE ACCESSORS
    # =================================================================
    def get_current_intelligence(self) -> Dict[str, Any]:
        """Returns snapshot of current diagnostic intelligence state."""
        if not self.intelligence_engine:
            return {}
        return self.intelligence_engine.get_current_intelligence()

    def get_active_events(self) -> List[Dict[str, Any]]:
        """Returns list of currently active anomaly events."""
        if not self.intelligence_engine:
            return []
        return self.intelligence_engine.get_active_events()

    def get_recent_events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent diagnostic events from bounded history."""
        if not self.intelligence_engine:
            return []
        return self.intelligence_engine.get_recent_events(limit=limit)

    def get_active_hypotheses(self) -> List[Dict[str, Any]]:
        """Returns current list of active diagnostic hypotheses."""
        if not self.intelligence_engine:
            return []
        return self.intelligence_engine.get_active_hypotheses()

    def get_all_hypotheses(self) -> List[Dict[str, Any]]:
        """Returns all tracked diagnostic hypotheses."""
        if not self.intelligence_engine:
            return []
        return self.intelligence_engine.get_all_hypotheses()

    def get_active_observations(self) -> Dict[str, Dict[str, Any]]:
        """Returns dictionary of active ongoing observations."""
        if not self.intelligence_engine:
            return {}
        return self.intelligence_engine.get_active_observations()

    def get_intelligence_state(self) -> Dict[str, Any]:
        """Returns consolidated intelligence state for UI and higher layers."""
        if not self.intelligence_engine:
            return {}
        return self.intelligence_engine.get_intelligence_state()

    def clear_intelligence_state(self) -> None:
        """Resets all live diagnostic intelligence session state cleanly."""
        if self.intelligence_engine:
            self.intelligence_engine.clear_session_state()

    # =================================================================
    # PHASE F-4: FAULT & DTC LIFECYCLE ACCESSORS & SNAPSHOT METHODS
    # =================================================================
    def process_dtc_snapshot(self, snapshot: Any) -> Dict[str, Any]:
        """Processes a DTC observation snapshot through the lifecycle engine."""
        if not self.dtc_lifecycle_engine:
            return {}
        return self.dtc_lifecycle_engine.process_dtc_snapshot(snapshot)

    def poll_dtcs(self, header: Optional[str] = None) -> Dict[str, Any]:
        """
        Polls DTCs from vehicle using existing read_diagnostic_trouble_codes
        without spawning a secondary serial worker, and feeds result to F-4.
        Thread-safe, serialized, and failure-isolated.
        """
        with self._dtc_poll_lock:
            if not hasattr(self.engine, "read_diagnostic_trouble_codes"):
                return {}
            try:
                dtc_read_result = self.engine.read_diagnostic_trouble_codes(header=header)
            except Exception as e:
                logging.error(f"LiveRuntime: Exception during DTC read: {e}")
                dtc_read_result = {
                    "type": "DTC",
                    "status": STATUS_SERIAL_ERROR,
                    "codes": [],
                    "details": [],
                    "raw_response": [],
                    "timestamp": time.time(),
                    "error": str(e),
                }
            return self.process_dtc_snapshot(dtc_read_result)

    def get_dtc_state(self, code: str) -> Optional[Dict[str, Any]]:
        """Returns lifecycle state for a single DTC code."""
        if not self.dtc_lifecycle_engine:
            return None
        return self.dtc_lifecycle_engine.get_dtc_state(code)

    def get_all_dtc_states(self) -> Dict[str, Dict[str, Any]]:
        """Returns dictionary of all tracked DTCs and their lifecycle states."""
        if not self.dtc_lifecycle_engine:
            return {}
        return self.dtc_lifecycle_engine.get_all_dtc_states()

    def get_active_dtcs(self) -> List[Dict[str, Any]]:
        """Returns list of currently active DTCs."""
        if not self.dtc_lifecycle_engine:
            return []
        return self.dtc_lifecycle_engine.get_active_dtcs()

    def get_recovering_dtcs(self) -> List[Dict[str, Any]]:
        """Returns list of DTCs in RECOVERING state."""
        if not self.dtc_lifecycle_engine:
            return []
        return self.dtc_lifecycle_engine.get_recovering_dtcs()

    def get_resolved_dtcs(self) -> List[Dict[str, Any]]:
        """Returns list of DTCs resolved by observation."""
        if not self.dtc_lifecycle_engine:
            return []
        return self.dtc_lifecycle_engine.get_resolved_dtcs()

    # =================================================================
    # PHASE L-2: DYNAMIC OPERATING CONTEXT & EXPECTED BEHAVIOR ACCESSORS
    # =================================================================
    def build_operating_context(self) -> Any:
        """
        Builds a structured Phase L-2 OperatingContext snapshot from current
        live telemetry in the acquisition runtime.
        """
        from dynamic_operating_reference import OperatingContext, VariableQuality
        
        ctx = OperatingContext(
            timestamp=time.time(),
            vehicle_instance_id=self.vehicle_id,
            primary_ecu=self.target_ecu,
        )
        
        pid_name_map = {
            "010C": ("RPM", "rpm"),
            "010D": ("SPEED", "km/h"),
            "0105": ("ECT", "°C"),
            "010B": ("MAP", "kPa"),
            "0111": ("TPS", "%"),
            "0104": ("LOAD", "%"),
            "010F": ("IAT", "°C"),
            "0110": ("MAF", "g/s"),
            "0106": ("STFT", "%"),
            "0107": ("LTFT", "%"),
            "0114": ("O2_B1S1_V", "V"),
        }
        
        with self._sample_lock:
            for pid, sample in self._latest_successful_by_pid.items():
                clean_pid = pid.upper().strip()
                if clean_pid in pid_name_map:
                    var_name, unit = pid_name_map[clean_pid]
                    val = sample.get("value")
                    ts = sample.get("timestamp", ctx.timestamp)
                    status = sample.get("status", "")
                    
                    qual = VariableQuality.KNOWN_VALID if status == STATUS_VALID else VariableQuality.UNKNOWN
                    ctx.set_variable(
                        name=var_name,
                        value=val,
                        unit=unit,
                        timestamp=ts,
                        quality=qual,
                        source_ecu=sample.get("target_ecu", self.target_ecu),
                    )
                    
        ctx.classify_operating_state()
        return ctx

    def get_recent_dtc_events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent DTC lifecycle events from bounded history."""
        if not self.dtc_lifecycle_engine:
            return []
        return self.dtc_lifecycle_engine.get_recent_dtc_events(limit=limit)

    def get_dtc_lifecycle_summary(self) -> Dict[str, Any]:
        """Returns consolidated DTC lifecycle summary."""
        if not self.dtc_lifecycle_engine:
            return {}
        return self.dtc_lifecycle_engine.get_dtc_lifecycle_summary()

    def reset_dtc_lifecycle(self) -> None:
        """Resets local in-memory DTC lifecycle tracking. Non-destructive; never sends Mode 04."""
        if self.dtc_lifecycle_engine:
            self.dtc_lifecycle_engine.reset_session()

    # =================================================================
    # PHASE F-5: RUNTIME SAFETY & RECOVERY ACCESSORS
    # =================================================================
    def get_runtime_health(self) -> Dict[str, Any]:
        """Returns overall runtime health summary including circuit breaker state."""
        if not hasattr(self, "safety_manager") or not self.safety_manager:
            return {"status": "HEALTHY", "state": self.get_state()}
        status, summary = self.safety_manager.evaluate_overall_health()
        summary["runtime_state"] = self.get_state()
        summary["is_running"] = self.is_running()
        return summary

    def get_failure_state(self) -> Dict[str, Any]:
        """Returns consolidated failure metrics and recent counts."""
        if not hasattr(self, "safety_manager") or not self.safety_manager:
            return {}
        history = self.safety_manager.get_failure_history()
        critical_cnt = sum(1 for f in history if f.get("severity") == "CRITICAL")
        warning_cnt = sum(1 for f in history if f.get("severity") == "WARNING")
        return {
            "total_failures_recorded": len(history),
            "critical_failures_count": critical_cnt,
            "warning_failures_count": warning_cnt,
            "recent_failure": history[-1] if history else None,
        }

    def get_failure_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent failure history records from bounded buffer."""
        if not hasattr(self, "safety_manager") or not self.safety_manager:
            return []
        return self.safety_manager.get_failure_history(limit=limit)

    def get_pid_health(self, pid: Optional[str] = None) -> Any:
        """Returns health/circuit metrics for a specific PID, or all PIDs."""
        if not hasattr(self, "safety_manager") or not self.safety_manager:
            return None if pid else {}
        return self.safety_manager.get_pid_health(pid)

    def reconnect(self, max_attempts: int = 3, timeout: float = 2.0) -> bool:
        """
        Controlled reconnection with bounded backoff and probe validation.
        Non-blocking cancellation through _stop_event.
        Returns True if reconnection and probe succeeded.
        """
        if not self._reconnect_lock.acquire(blocking=False):
            logging.warning("LiveRuntime: Reconnection already in progress. Duplicate call rejected.")
            return False

        try:
            self._stop_event.clear()
            logging.info("LiveRuntime: Initiating controlled reconnection...")
            for attempt in range(1, max_attempts + 1):
                if self._stop_event.is_set():
                    logging.info("LiveRuntime: Reconnection cancelled by stop event.")
                    return False

                backoff = 0.2 if attempt == 1 else min(2.0, 0.2 * (2 ** (attempt - 1)))
                if self._stop_event.wait(timeout=backoff):
                    return False

                try:
                    conn_ok = False
                    if hasattr(self, "adapter") and self.adapter is not None:
                        conn_ok = self.adapter.connect(timeout=timeout)
                    elif hasattr(self.engine, "baglan"):
                        conn_ok = bool(self.engine.baglan())

                    if conn_ok:
                        # Post-reconnect verification probe
                        probe_pid = self.pids[0] if self.pids else "010C"
                        if hasattr(self, "adapter") and self.adapter is not None and self.adapter.is_connected():
                            res, probe_status = self.adapter.send_command(probe_pid, timeout=1.0)
                        else:
                            res = self.engine.komut_gonder(probe_pid, timeout=1.0)
                            probe_status = getattr(self.engine, "last_response_status", STATUS_VALID)

                        if probe_status == STATUS_VALID or res:
                            logging.info(f"LiveRuntime: Reconnected successfully on attempt {attempt}.")
                            if hasattr(self, "safety_manager") and self.safety_manager:
                                self.safety_manager.reset_faults()
                            with self._state_lock:
                                if self._state in (LIVE_ERROR, LIVE_DEGRADED):
                                    if self._worker_thread and self._worker_thread.is_alive():
                                        self._transition_state(LIVE_RUNNING)
                                    else:
                                        self._transition_state(LIVE_STOPPED)
                            return True
                except Exception as e:
                    logging.warning(f"LiveRuntime reconnect attempt {attempt} failed: {e}")

            logging.error(f"LiveRuntime: Reconnection failed after {max_attempts} attempts.")
            return False
        finally:
            self._reconnect_lock.release()

    def reset_runtime_faults(self) -> None:
        """
        Resets local runtime error counters, failure history, and PID circuit breakers.
        HARD SAFETY: Strictly local in-memory. NEVER communicates Mode 04 or erases ECU DTCs!
        """
        if hasattr(self, "safety_manager") and self.safety_manager:
            self.safety_manager.reset_faults()
        with self._state_lock:
            if self._state == LIVE_DEGRADED:
                self._transition_state(LIVE_RUNNING)

    # =================================================================
    # INTERNAL ACQUISITION LOOP (MONOTONIC CLOCK DRIVEN)
    # =================================================================
    def _acquisition_loop(self) -> None:
        """
        Worker thread function. Continuously executes PID polling cycles
        with monotonic clock scheduling to minimize timing drift.
        """
        next_cycle_time = time.monotonic()

        while not self._stop_event.is_set():
            now_m = time.monotonic()

            # Drift correction: if we have time left before the next cycle, wait with event check
            if now_m < next_cycle_time:
                wait_duration = next_cycle_time - now_m
                if self._stop_event.wait(timeout=wait_duration):
                    break

            # Advance next target cycle schedule
            next_cycle_time = max(time.monotonic(), next_cycle_time + self.cycle_interval)

            # Check communication health before cycle
            if not self._check_serial_health():
                break

            # Execute one full acquisition cycle across all PIDs
            cycle_ok = self._execute_cycle()
            if not cycle_ok:
                # Critical communication breakdown occurred
                break

            with self._stats_lock:
                self._cycle_count += 1

        logging.debug("LiveAcquisitionWorker exited loop.")

    def _check_serial_health(self) -> bool:
        """Verifies serial port / adapter and worker thread are still alive."""
        if hasattr(self, "adapter") and self.adapter is not None:
            if not self.adapter.is_connected():
                logging.error("LiveRuntime: Adapter disconnected during execution.")
                if hasattr(self, "safety_manager") and self.safety_manager is not None:
                    self.safety_manager.record_failure(
                        category="CONNECTION_LOST",
                        component="ADAPTER",
                        severity="CRITICAL",
                        reason="Adapter disconnected during execution",
                    )
                self._transition_state(LIVE_ERROR, "Adapter disconnected")
                return False
            return True

        if not self.is_connected():
            logging.error("LiveRuntime: Serial port / adapter disconnected during execution.")
            if hasattr(self, "safety_manager") and self.safety_manager is not None:
                self.safety_manager.record_failure(
                    category="CONNECTION_LOST",
                    component="SERIAL_PORT",
                    severity="CRITICAL",
                    reason="Serial port / adapter disconnected during execution",
                )
            self._transition_state(LIVE_ERROR, "Serial port / adapter disconnected")
            return False

        if hasattr(self.engine, "io_worker") and self.engine.io_worker is not None:
            if not getattr(self.engine.io_worker, "running", True):
                logging.error("LiveRuntime: SerialIOThread stopped unexpectedly.")
                if hasattr(self, "safety_manager") and self.safety_manager is not None:
                    self.safety_manager.record_failure(
                        category="WORKER_FAILURE",
                        component="SerialIOThread",
                        severity="CRITICAL",
                        reason="SerialIOThread stopped unexpectedly",
                    )
                self._transition_state(LIVE_ERROR, "SerialIOThread down")
                return False

        return True

    def _execute_cycle(self) -> bool:
        """Polls each configured PID sequentially in this cycle with circuit-breaker protection."""
        for pid in self.pids:
            if self._stop_event.is_set():
                return True

            # Phase F-5: Circuit Breaker Check to prevent timeout storm
            if hasattr(self, "safety_manager") and self.safety_manager is not None:
                if not self.safety_manager.should_poll_pid(pid):
                    logging.debug(f"LiveRuntime: Polling skipped for PID {pid} (Circuit OPEN/Throttled)")
                    continue

            sample, is_fatal_comm_error = self._acquire_pid(pid)

            if is_fatal_comm_error:
                return False

            # Process and record sample
            self._record_sample(sample)

            # Fire callback safely
            self._fire_callback(sample)

        # Phase F-5: Evaluate transition between LIVE_RUNNING and LIVE_DEGRADED
        self._evaluate_runtime_health_transition()

        return True

    def _evaluate_runtime_health_transition(self) -> None:
        """Dynamically transitions between LIVE_RUNNING and LIVE_DEGRADED based on PID health."""
        if not hasattr(self, "safety_manager") or self.safety_manager is None:
            return

        with self._state_lock:
            if self._state not in (LIVE_RUNNING, LIVE_DEGRADED):
                return

            health_status, _ = self.safety_manager.evaluate_overall_health()
            if health_status == "DEGRADED" and self._state == LIVE_RUNNING:
                self._transition_state(LIVE_DEGRADED, "Partial PID acquisition failure")
            elif health_status == "HEALTHY" and self._state == LIVE_DEGRADED:
                self._transition_state(LIVE_RUNNING)

    def _acquire_pid(self, pid: str) -> tuple:
        """
        Executes OBD query for a single PID and constructs standard sample dict.
        Returns: (sample_dict, is_fatal_comm_error)
        """
        clean_pid = pid.upper().strip()
        catalog_entry = DEFAULT_PID_CATALOG.get(clean_pid, {})
        sensor_name = catalog_entry.get("name", clean_pid)
        unit = catalog_entry.get("unit", "")
        decode_func = catalog_entry.get("decode", None)

        with self._stats_lock:
            self._sequence_counter += 1
            seq = self._sequence_counter

        start_t = time.time()
        timeout_val = 0.5 if getattr(self.engine, "is_can", True) else 2.5

        # Check safety policy against prohibited services (e.g. 04, 14, 2E, 27, 2F, 34-37, 3D)
        clean_tok = clean_pid.split()[0] if clean_pid else ""
        if clean_tok in PROHIBITED_SERVICES or clean_tok[:2] in PROHIBITED_SERVICES:
            logging.error(f"LiveRuntime: Blocked prohibited service execution for {clean_pid}")
            elapsed_ms = (time.time() - start_t) * 1000.0
            sample = {
                "timestamp": time.time(),
                "pid": clean_pid,
                "name": sensor_name,
                "value": None,
                "unit": unit,
                "raw_value": None,
                "raw_bytes": b"",
                "status": STATUS_NRC,
                "acquisition_time_ms": round(elapsed_ms, 2),
                "sequence": seq,
                "error": "Safety violation: Prohibited service blocked",
                "ecu_id": getattr(self, "target_ecu", "ECM"),
                "vehicle_id": getattr(self, "vehicle_id", None),
            }
            return sample, False

        # Query vehicle through authoritative DiagnosticAdapter (J-1) or AutoExpertEngine fallback
        res = None
        raw_status = STATUS_VALID
        if hasattr(self, "adapter") and self.adapter is not None and self.adapter.is_connected():
            res, raw_status = self.adapter.send_command(clean_pid, timeout=timeout_val)
        elif hasattr(self.engine, "komut_gonder"):
            res = self.engine.komut_gonder(clean_pid, timeout=timeout_val)
            raw_status = getattr(self.engine, "last_response_status", STATUS_VALID)
        else:
            raw_status = STATUS_NO_CONNECTION

        elapsed_ms = (time.time() - start_t) * 1000.0
        raw_str = " ".join(res) if res else None
        raw_bytes = raw_str.encode("utf-8") if raw_str else b""

        # Critical communication failure check
        if raw_status in (STATUS_NO_CONNECTION, STATUS_WORKER_DOWN, STATUS_SERIAL_ERROR):
            logging.error(f"LiveRuntime fatal communication error on {clean_pid}: status={raw_status}")
            self._transition_state(LIVE_ERROR, f"Communication error: {raw_status}")
            sample = {
                "timestamp": time.time(),
                "pid": clean_pid,
                "name": sensor_name,
                "value": None,
                "unit": unit,
                "raw_value": raw_str,
                "raw_bytes": raw_bytes,
                "status": raw_status,
                "acquisition_time_ms": round(elapsed_ms, 2),
                "sequence": seq,
                "error": f"Fatal communication error ({raw_status})",
                "ecu_id": getattr(self, "target_ecu", "ECM"),
                "vehicle_id": getattr(self, "vehicle_id", None),
            }
            return sample, True

        decoded_val = None
        error_msg = None

        if raw_status == STATUS_VALID and res:
            # Decode using engine parser or catalog decoder
            decoded_val = self._decode_pid_response(clean_pid, res, sensor_name, decode_func)
            if decoded_val is None:
                raw_status = STATUS_NO_DATA
                error_msg = f"Failed to parse payload for {clean_pid}"
        else:
            error_msg = f"PID query failed ({raw_status})"

        sample = {
            "timestamp": time.time(),
            "pid": clean_pid,
            "name": sensor_name,
            "value": decoded_val,
            "unit": unit,
            "raw_value": raw_str,
            "raw_bytes": raw_bytes,
            "status": raw_status,
            "acquisition_time_ms": round(elapsed_ms, 2),
            "sequence": seq,
            "error": error_msg,
            "ecu_id": getattr(self, "target_ecu", "ECM"),
            "vehicle_id": getattr(self, "vehicle_id", None),
        }

        return sample, False

    def _decode_pid_response(self, pid: str, res_lines: List[str], sensor_name: str, decode_func: Optional[Callable]) -> Optional[float]:
        """Decodes raw hex response lines into a numeric value."""
        # Try engine's parse_pid_line if available
        if decode_func is not None and hasattr(self.engine, "parse_pid_line"):
            for line in res_lines:
                try:
                    val = self.engine.parse_pid_line(line, pid, (sensor_name, decode_func))
                    if val is not None:
                        return float(val) if isinstance(val, (int, float)) else val
                except Exception:
                    pass

        # Fallback manual Mode 01 hex decoding
        clean_target = "41" + pid[-2:].upper()
        for line in res_lines:
            hex_str = line.replace(" ", "").upper()
            if hex_str.startswith(('7E8', '7E0', '7E1')):
                hex_str = hex_str[3:]
            elif hex_str.startswith(('7E9', '7EA')):
                continue  # Skip TCM / secondary modules

            idx = hex_str.find(clean_target)
            if idx != -1:
                payload_hex = hex_str[idx + len(clean_target):]
                try:
                    payload_bytes = [
                        int(payload_hex[i:i+2], 16)
                        for i in range(0, len(payload_hex), 2)
                        if len(payload_hex[i:i+2]) == 2
                    ]
                except ValueError:
                    continue
                if payload_bytes and decode_func is not None:
                    try:
                        res = decode_func(payload_bytes)
                        return float(res) if isinstance(res, (int, float)) else res
                    except Exception:
                        pass
                elif payload_bytes:
                    return float(payload_bytes[0])

        return None

    def _record_sample(self, sample: Dict[str, Any]) -> None:
        """Stores sample in bounded history, latest maps, and updates counters."""
        pid = sample["pid"]
        is_success = (
            sample["status"] == STATUS_VALID
            and sample["value"] is not None
            and not (isinstance(sample["value"], float) and math.isnan(sample["value"]))
        )

        with self._sample_lock:
            self._recent_samples.append(sample)
            self._latest_by_pid[pid] = sample
            if is_success:
                self._latest_successful_by_pid[pid] = sample

        with self._stats_lock:
            if is_success:
                self._successful_reads += 1
            else:
                self._failed_reads += 1

        # Phase F-2: Evaluate Real-Time Data Quality
        quality_res = None
        if hasattr(self, "quality_assessor") and self.quality_assessor is not None:
            try:
                quality_res = self.quality_assessor.evaluate_sample(sample)
            except Exception as e:
                logging.warning(f"LiveRuntime quality assessment error on PID {pid}: {e}")

        # Update engine sensor cache on valid read to keep C/E cache in sync
        # Only valid + quality-evaluated readings update value and history
        if is_success:
            sensor_name = sample.get("name", pid)
            try:
                if hasattr(self.engine, "_update_sensor_cache"):
                    evaluated_q = quality_res.get("quality") if quality_res else QUALITY_GOOD
                    self.engine._update_sensor_cache(
                        sensor_name,
                        sample["value"],
                        status=STATUS_VALID,
                        quality=evaluated_q,
                        timestamp=sample["timestamp"],
                        source="LIVE_RUNTIME",
                    )
            except Exception as e:
                logging.debug(f"Cache update exception: {e}")

        # Phase F-3: Real-Time Diagnostic Intelligence
        if hasattr(self, "intelligence_engine") and self.intelligence_engine is not None:
            try:
                self.intelligence_engine.process_live_sample(sample, quality_res)
            except Exception as e:
                logging.warning(f"LiveRuntime intelligence processing error on PID {pid}: {e}")

        # Phase F-5: Record PID result in RuntimeSafetyManager (circuit breaker)
        if hasattr(self, "safety_manager") and self.safety_manager is not None:
            try:
                self.safety_manager.record_pid_result(
                    pid=pid,
                    is_success=is_success,
                    raw_status=sample.get("status", STATUS_VALID),
                    error_msg=sample.get("error"),
                    timestamp=sample.get("timestamp"),
                )
            except Exception as e:
                logging.debug(f"Safety manager record error on PID {pid}: {e}")

        # Decoupled Asynchronous Persistence (Phase K-3)
        if hasattr(self, "repository") and self.repository is not None:
            self._enqueue_persistence(sample)

    # =================================================================
    # ASYNCHRONOUS PERSISTENCE PIPELINE (PHASE K-3)
    # =================================================================
    def _enqueue_persistence(self, sample: Dict[str, Any]) -> bool:
        """Enqueues sample for decoupled asynchronous persistence."""
        if self.repository is None:
            return False
        try:
            self._persistence_queue.put_nowait(sample)
            return True
        except queue.Full:
            with self._stats_lock:
                self._persistence_dropped_count += 1
            logging.warning("LiveRuntime persistence queue full; telemetry sample dropped to prevent acquisition stalls.")
            return False

    def _persistence_loop(self) -> None:
        """Drains persistence queue and writes records in batches without blocking acquisition."""
        batch: List[Dict[str, Any]] = []
        last_flush = time.monotonic()

        while not self._persistence_stop_event.is_set() or not self._persistence_queue.empty():
            try:
                sample = self._persistence_queue.get(timeout=0.1)
                batch.append(sample)
                self._persistence_queue.task_done()
            except queue.Empty:
                pass

            now = time.monotonic()
            if batch and (len(batch) >= 10 or (now - last_flush) >= 0.2 or self._persistence_stop_event.is_set()):
                self._flush_persistence_batch(batch)
                batch.clear()
                last_flush = now

        if batch:
            self._flush_persistence_batch(batch)
            batch.clear()

    def _flush_persistence_batch(self, batch: List[Dict[str, Any]]) -> None:
        """Writes batch to repository cleanly with error isolation."""
        if not self.repository:
            return
        for s in batch:
            try:
                raw_bytes = s.get("raw_bytes")
                if raw_bytes is None:
                    raw_val = s.get("raw_value") or ""
                    raw_bytes = raw_val.encode("utf-8") if isinstance(raw_val, str) else b""

                if hasattr(self.repository, "save_raw_acquisition"):
                    self.repository.save_raw_acquisition(
                        session_id=self.session_id,
                        source_ecu=s.get("ecu_id") or self.target_ecu,
                        command_or_pid=s.get("pid", ""),
                        raw_payload=raw_bytes,
                        metadata={
                            "name": s.get("name"),
                            "value": s.get("value"),
                            "unit": s.get("unit"),
                            "status": s.get("status"),
                            "sequence": s.get("sequence"),
                            "acquisition_time_ms": s.get("acquisition_time_ms"),
                            "vehicle_id": s.get("vehicle_id") or self.vehicle_id,
                        },
                    )
                with self._stats_lock:
                    self._persistence_written_count += 1
            except Exception as e:
                with self._stats_lock:
                    self._persistence_error_count += 1
                logging.warning(f"LiveRuntime persistence save error: {e}")

    def _fire_callback(self, sample: Dict[str, Any]) -> None:
        """Fires user-supplied callback safely without blocking or throwing."""
        if self._on_sample and callable(self._on_sample):
            try:
                self._on_sample(sample)
            except Exception as e:
                logging.warning(f"LiveAcquisitionRuntime on_sample callback raised exception: {e}")
                if hasattr(self, "safety_manager") and self.safety_manager is not None:
                    self.safety_manager.record_failure(
                        category="CALLBACK_FAILURE",
                        component="on_sample_callback",
                        severity="WARNING",
                        reason=f"Callback raised exception: {e}",
                    )
