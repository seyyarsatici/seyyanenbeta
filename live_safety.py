"""
Seyyanen Diagnostic Engine — Phase F-5: Runtime Safety & Recovery
=================================================================
Fault classification, PID health tracking, circuit breaker protection,
and controlled recovery for the live acquisition runtime.
HARD SAFETY: Strictly transport/runtime level. Never executes Mode 04 or clears ECU DTCs.
"""

import time
import logging
import threading
from collections import deque
from typing import Dict, Any, List, Optional, Tuple

from motor import (
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

# =====================================================================
# F-5 CONSTANTS: FAILURE CATEGORIES & CIRCUIT STATES
# =====================================================================
FAIL_TRANSIENT_TIMEOUT = "TRANSIENT_TIMEOUT"
FAIL_NO_DATA = "NO_DATA"
FAIL_NRC = "NRC"
FAIL_SERIAL_ERROR = "SERIAL_ERROR"
FAIL_CONNECTION_LOST = "CONNECTION_LOST"
FAIL_WORKER_FAILURE = "WORKER_FAILURE"
FAIL_QUEUE_FAILURE = "QUEUE_FAILURE"
FAIL_CALLBACK_FAILURE = "CALLBACK_FAILURE"
FAIL_PARSER_FAILURE = "PARSER_FAILURE"
FAIL_INTERNAL_ERROR = "INTERNAL_ERROR"

# Circuit Breaker States
CIRCUIT_CLOSED = "CLOSED"        # Normal operation: all queries executed
CIRCUIT_HALF_OPEN = "HALF_OPEN"  # Testing recovery: single probe allowed
CIRCUIT_OPEN = "OPEN"            # Throttled: rapid polling suppressed to prevent timeout storm


class RuntimeFailure:
    """Encapsulates a classified runtime failure event."""

    def __init__(
        self,
        category: str,
        component: str,
        severity: str,
        reason: str,
        is_recoverable: bool = True,
        retry_count: int = 0,
        timestamp: Optional[float] = None,
    ):
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.timestamp_monotonic = time.monotonic()
        self.category = category
        self.component = component
        self.severity = severity
        self.reason = reason
        self.is_recoverable = is_recoverable
        self.retry_count = retry_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "category": self.category,
            "component": self.component,
            "severity": self.severity,
            "reason": self.reason,
            "is_recoverable": self.is_recoverable,
            "retry_count": self.retry_count,
        }


class PIDHealthTracker:
    """
    Tracks query reliability for a single PID and manages circuit-breaker tripping
    to prevent timeout storms and queue starvation during partial ECU failure.
    """

    def __init__(
        self,
        pid: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 2.0,
    ):
        self.pid = pid.upper().strip()
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.5, float(cooldown_seconds))

        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_successes = 0
        self.last_status: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_success_timestamp: Optional[float] = None
        self.last_failure_timestamp: Optional[float] = None

        self.circuit_state = CIRCUIT_CLOSED
        self.circuit_open_until_m: float = 0.0

    def record_success(self, timestamp: float) -> None:
        """Records a successful read, resetting failure count and closing circuit."""
        self.consecutive_failures = 0
        self.total_successes += 1
        self.last_status = STATUS_VALID
        self.last_error = None
        self.last_success_timestamp = timestamp
        self.circuit_state = CIRCUIT_CLOSED
        self.circuit_open_until_m = 0.0

    def record_failure(self, status: str, error_msg: Optional[str], timestamp: float) -> bool:
        """
        Records a failed query. Trips circuit breaker to OPEN if threshold reached.
        Returns True if circuit state changed (tripped).
        """
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_status = status
        self.last_error = error_msg
        self.last_failure_timestamp = timestamp

        tripped = False
        if self.consecutive_failures >= self.failure_threshold and self.circuit_state == CIRCUIT_CLOSED:
            self.circuit_state = CIRCUIT_OPEN
            self.circuit_open_until_m = time.monotonic() + self.cooldown_seconds
            tripped = True
            logging.warning(
                f"[CIRCUIT_BREAKER] PID {self.pid} tripped to OPEN after {self.consecutive_failures} failures. "
                f"Suppressed for {self.cooldown_seconds}s."
            )
        return tripped

    def should_poll(self, now_monotonic: float) -> bool:
        """
        Evaluates whether this PID should be polled in the current cycle.
        Throttles queries when circuit is OPEN until cooldown expires.
        """
        if self.circuit_state == CIRCUIT_CLOSED:
            return True

        if self.circuit_state == CIRCUIT_OPEN:
            if now_monotonic >= self.circuit_open_until_m:
                # Cooldown expired: enter HALF_OPEN to test a recovery probe
                self.circuit_state = CIRCUIT_HALF_OPEN
                return True
            # Still in cooldown: skip polling to avoid timeout storm
            return False

        if self.circuit_state == CIRCUIT_HALF_OPEN:
            return True

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "circuit_state": self.circuit_state,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_success_timestamp": self.last_success_timestamp,
            "last_failure_timestamp": self.last_failure_timestamp,
            "cooldown_remaining_seconds": max(0.0, round(self.circuit_open_until_m - time.monotonic(), 2))
            if self.circuit_state == CIRCUIT_OPEN else 0.0,
        }


class RuntimeSafetyManager:
    """
    Central safety coordinator for LiveAcquisitionRuntime.
    Classifies errors, tracks PID health, maintains bounded failure history,
    and coordinates non-blocking controlled reconnection with bounded backoff.
    """

    def __init__(
        self,
        pids: Optional[List[str]] = None,
        history_maxlen: int = 100,
        failure_threshold: int = 3,
        cooldown_seconds: float = 2.0,
    ):
        self.history_maxlen = max(10, int(history_maxlen))
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.RLock()

        # Per-PID Health Trackers: {clean_pid: PIDHealthTracker}
        self._pid_trackers: Dict[str, PIDHealthTracker] = {}
        if pids:
            for p in pids:
                clean_p = p.upper().strip()
                self._pid_trackers[clean_p] = PIDHealthTracker(
                    clean_p, failure_threshold=self.failure_threshold, cooldown_seconds=self.cooldown_seconds
                )

        # Bounded Failure History
        self._failure_history: deque = deque(maxlen=self.history_maxlen)

        # Rate-limiting / deduplicating log tracking: {(component, category): last_log_time}
        self._last_log_times: Dict[Tuple[str, str], float] = {}

    def ensure_pid_tracker(self, pid: str) -> PIDHealthTracker:
        """Ensures a health tracker exists for the given PID."""
        clean_p = pid.upper().strip()
        with self._lock:
            if clean_p not in self._pid_trackers:
                self._pid_trackers[clean_p] = PIDHealthTracker(
                    clean_p, failure_threshold=self.failure_threshold, cooldown_seconds=self.cooldown_seconds
                )
            return self._pid_trackers[clean_p]

    def classify_status(self, raw_status: str, error_msg: Optional[str] = None) -> Tuple[str, str, bool]:
        """
        Classifies raw response status into (category, severity, is_recoverable).
        """
        if raw_status == STATUS_TIMEOUT:
            return FAIL_TRANSIENT_TIMEOUT, SEVERITY_WARNING, True
        elif raw_status in (STATUS_NO_CONNECTION, STATUS_WORKER_DOWN):
            return FAIL_CONNECTION_LOST, SEVERITY_CRITICAL, True
        elif raw_status == STATUS_SERIAL_ERROR:
            return FAIL_SERIAL_ERROR, SEVERITY_CRITICAL, True
        elif raw_status in (STATUS_NO_DATA, STATUS_EMPTY_RESPONSE):
            return FAIL_NO_DATA, SEVERITY_INFO, True
        elif raw_status == STATUS_NRC:
            return FAIL_NRC, SEVERITY_WARNING, True
        elif error_msg and "parse" in error_msg.lower():
            return FAIL_PARSER_FAILURE, SEVERITY_WARNING, True
        else:
            return FAIL_INTERNAL_ERROR, SEVERITY_WARNING, True

    def record_failure(
        self,
        category: str,
        component: str,
        severity: str,
        reason: str,
        is_recoverable: bool = True,
        retry_count: int = 0,
    ) -> RuntimeFailure:
        """Records a structured failure, logging with deduplication/rate-limiting."""
        now = time.time()
        failure = RuntimeFailure(
            category=category,
            component=component,
            severity=severity,
            reason=reason,
            is_recoverable=is_recoverable,
            retry_count=retry_count,
            timestamp=now,
        )

        with self._lock:
            self._failure_history.append(failure)

            # Rate-limited logging: log at most once per 2 seconds for identical (component, category)
            log_key = (component, category)
            last_logged = self._last_log_times.get(log_key, 0.0)
            if now - last_logged >= 2.0:
                self._last_log_times[log_key] = now
                lvl = logging.CRITICAL if severity == SEVERITY_CRITICAL else (logging.WARNING if severity == SEVERITY_WARNING else logging.INFO)
                logging.log(lvl, f"[RUNTIME_SAFETY] {category} on {component}: {reason}")

        return failure

    def record_pid_result(
        self,
        pid: str,
        is_success: bool,
        raw_status: str,
        error_msg: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Updates health tracker and circuit breaker for a PID query result."""
        ts = timestamp if timestamp is not None else time.time()
        clean_p = pid.upper().strip()
        tracker = self.ensure_pid_tracker(clean_p)

        with self._lock:
            if is_success:
                tracker.record_success(ts)
            else:
                cat, sev, rec = self.classify_status(raw_status, error_msg)
                tracker.record_failure(raw_status, error_msg, ts)
                self.record_failure(
                    category=cat,
                    component=f"PID_{clean_p}",
                    severity=sev,
                    reason=error_msg or f"Status: {raw_status}",
                    is_recoverable=rec,
                    retry_count=tracker.consecutive_failures,
                )

    def should_poll_pid(self, pid: str) -> bool:
        """Returns True if PID is allowed to be polled in the current cycle."""
        clean_p = pid.upper().strip()
        with self._lock:
            tracker = self._pid_trackers.get(clean_p)
            if not tracker:
                return True
            return tracker.should_poll(time.monotonic())

    def evaluate_overall_health(self) -> Tuple[str, Dict[str, Any]]:
        """
        Determines whether runtime should be considered HEALTHY (RUNNING), DEGRADED, or ERROR.
        Returns: (health_status, health_summary_dict)
        - If all PIDs failing: returns ("FAILING", summary)
        - If some PIDs failing, some succeeding: returns ("DEGRADED", summary)
        - If all PIDs succeeding (or no failures): returns ("HEALTHY", summary)
        """
        with self._lock:
            if not self._pid_trackers:
                return "HEALTHY", {"healthy_pids": [], "failing_pids": [], "open_circuits": []}

            failing = []
            healthy = []
            open_circuits = []

            for p, tracker in self._pid_trackers.items():
                if tracker.circuit_state == CIRCUIT_OPEN:
                    open_circuits.append(p)
                if tracker.consecutive_failures > 0:
                    failing.append(p)
                else:
                    healthy.append(p)

            total = len(self._pid_trackers)
            if len(failing) == total and total > 0 and all(self._pid_trackers[p].consecutive_failures >= 2 for p in failing):
                overall = "FAILING"
            elif len(failing) > 0:
                overall = "DEGRADED"
            else:
                overall = "HEALTHY"

            summary = {
                "overall_status": overall,
                "total_tracked": total,
                "healthy_pids_count": len(healthy),
                "failing_pids_count": len(failing),
                "open_circuits_count": len(open_circuits),
                "healthy_pids": healthy,
                "failing_pids": failing,
                "open_circuits": open_circuits,
            }
            return overall, summary

    def get_pid_health(self, pid: Optional[str] = None) -> Any:
        """Returns health metrics for one PID, or dict of all tracked PIDs."""
        with self._lock:
            if pid is not None:
                clean_p = pid.upper().strip()
                tracker = self._pid_trackers.get(clean_p)
                return tracker.to_dict() if tracker else None
            return {p: t.to_dict() for p, t in self._pid_trackers.items()}

    def get_failure_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recent failure history from bounded buffer."""
        with self._lock:
            items = [f.to_dict() for f in self._failure_history]
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def reset_faults(self) -> None:
        """
        Resets in-memory safety state (failure history, PID consecutive failures, circuit breakers).
        HARD SAFETY: Strictly local in-memory. NEVER communicates Mode 04 or touches ECU!
        """
        with self._lock:
            self._failure_history.clear()
            self._last_log_times.clear()
            for tracker in self._pid_trackers.values():
                tracker.consecutive_failures = 0
                tracker.circuit_state = CIRCUIT_CLOSED
                tracker.circuit_open_until_m = 0.0
                tracker.last_error = None
            logging.debug("RuntimeSafetyManager faults reset cleanly.")

    @staticmethod
    def calculate_backoff(attempt: int, base: float = 0.2, max_backoff: float = 2.0) -> float:
        """Calculates bounded exponential backoff delay for retries/reconnection."""
        delay = base * (2 ** max(0, attempt - 1))
        return min(max_backoff, delay)
