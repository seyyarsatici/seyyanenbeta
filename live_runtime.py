"""
Seyyanen Diagnostic Engine — Phase F-1: Live Acquisition Runtime
================================================================
Continuous, drift-controlled, thread-safe, and cancellable live acquisition layer.
Integrates with existing AutoExpertEngine and SerialIOThread priority queue.
"""

import time
import threading
import logging
from collections import deque
from typing import Callable, Optional, Dict, List, Any

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
)

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
    ):
        self.engine = engine if engine is not None else AutoExpertEngine()
        
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
    # LIFECYCLE (START / STOP)
    # =================================================================
    def start(self) -> bool:
        """
        Starts live acquisition in a background worker thread.
        Protected against duplicate start calls.
        """
        with self._state_lock:
            if self._state in (LIVE_RUNNING, LIVE_STARTING, LIVE_DEGRADED):
                logging.warning("LiveRuntime is already running or starting. Duplicate start call ignored.")
                return False

            if not self._transition_state(LIVE_STARTING):
                return False

            # Ensure engine serial connection exists or attempts to start
            if not self.engine.ser or not self.engine.ser.is_open:
                if not hasattr(self.engine, "baglan") or not self.engine.baglan():
                    self._transition_state(LIVE_ERROR, "Serial port connection failed during start")
                    return False

            # Reset lifecycle control
            self._stop_event.clear()
            self._error_reason = None
            with self._stats_lock:
                self._start_monotonic = time.monotonic()
                self._start_wall_time = time.time()

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

        # Signal stop event
        self._stop_event.set()

        # Join worker thread without holding state lock
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logging.warning(f"LiveAcquisitionWorker did not terminate within {timeout}s")

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
        }

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
                    if hasattr(self.engine, "baglan") and self.engine.baglan():
                        # Post-reconnect verification probe
                        probe_pid = self.pids[0] if self.pids else "010C"
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
        """Verifies serial port and worker thread are still alive."""
        if not self.engine.ser or not self.engine.ser.is_open:
            logging.error("LiveRuntime: Serial port disconnected during execution.")
            if hasattr(self, "safety_manager") and self.safety_manager is not None:
                self.safety_manager.record_failure(
                    category="CONNECTION_LOST",
                    component="SERIAL_PORT",
                    severity="CRITICAL",
                    reason="Serial port disconnected during execution",
                )
            self._transition_state(LIVE_ERROR, "Serial port disconnected")
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

        # Query vehicle through AutoExpertEngine
        res = self.engine.komut_gonder(clean_pid, timeout=timeout_val)
        elapsed_ms = (time.time() - start_t) * 1000.0

        raw_status = getattr(self.engine, "last_response_status", STATUS_VALID)
        raw_str = " ".join(res) if res else None

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
                "status": raw_status,
                "acquisition_time_ms": round(elapsed_ms, 2),
                "sequence": seq,
                "error": f"Fatal communication error ({raw_status})",
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
            "status": raw_status,
            "acquisition_time_ms": round(elapsed_ms, 2),
            "sequence": seq,
            "error": error_msg,
        }

        # Update engine sensor cache on valid read to keep C/E cache in sync
        if raw_status == STATUS_VALID and decoded_val is not None:
            try:
                if hasattr(self.engine, "_update_sensor_cache"):
                    self.engine._update_sensor_cache(
                        sensor_name,
                        decoded_val,
                        status=STATUS_VALID,
                        timestamp=sample["timestamp"],
                        source="LIVE_RUNTIME",
                    )
            except Exception as e:
                logging.debug(f"Cache update exception: {e}")

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
                payload_bytes = [
                    int(payload_hex[i:i+2], 16)
                    for i in range(0, len(payload_hex), 2)
                    if len(payload_hex[i:i+2]) == 2
                ]
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
        is_success = (sample["status"] == STATUS_VALID and sample["value"] is not None)

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
