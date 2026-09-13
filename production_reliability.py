#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-6
===================================================
Production Reliability, Resilience & Observability Layer
`production_reliability.py`

Architectural Role:
    C → I Diagnostic Intelligence
        ↓
    H Workflow & Test Execution
        ↓
    J-5 Security & Authorization Gate
        ↓
    J-4 Application User & Session Management
        ↓
    J-3 Versioned Persistence Layer
        ↓
    J-2 Multi-Platform Abstraction
        ↓
    J-1 Hardware / Adapter Abstraction
        ↓
    Diagnostic Transport & Protocols
        ↓
    Vehicle / Physical ECUs
    
    ===================================================
    J-6 Production Reliability Foundation (Cross-Cutting):
      - Global Error Boundary & Incident Classification
      - Runtime Health & Observability Engine
      - Idempotency & Duplicate Execution Protection
      - Operation-Aware Retry & Bounded Timeout Policy
      - Bounded Memory (Ring Buffers) & Log Rotation
      - Graceful Shutdown & Resource Cleanup Coordinator
      - Crash Reconciliation & Partial Failure Isolation

Strict Architectural Invariants:
1.  Diagnostic Semantics Unchanged: J-6 is infrastructure reliability, NEVER diagnostic reasoning.
2.  Communication Failure != Component Failure: Network, adapter, or bus errors are infrastructure events,
    NEVER vehicle ECU faults or component defects.
3.  Fail-Safe over Guess-and-Continue: When state is uncertain, stop safely; NEVER blindly retry
    state-changing operations.
4.  Zero Automatic Privileged Resumes: Crash reconciliation marks sessions INTERRUPTED, but NEVER
    transmits ECU frames or auto-resumes actuator tests on restart.
5.  Double-Gate & Safety Intact: J-6 never weakens ServiceSafetyPolicy or J-5 Authorization.
6.  Bounded Resources: All queues, ring buffers, and logs have hard capacity caps to prevent memory leaks.
7.  Multi-ECU Isolation: A failure on ECU A never corrupts or invalidates diagnostic data from ECU B.
8.  Idempotency: Dangerous state-changing commands cannot execute twice accidentally.
"""

from __future__ import annotations

import collections
import contextlib
import copy
import enum
import functools
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Set, Tuple, TypeVar, Union

# Platform, Adapter, Persistence, Session, and Security Integrations
from platform_abstraction import PlatformManager
from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterConnectionState,
    AdapterStateError,
    AdapterTimeoutError,
    TransportFailureError,
    MalformedResponseError,
    STATUS_NO_CONNECTION,
    STATUS_TIMEOUT,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
)
from diagnostic_persistence import (
    DiagnosticRepository,
    PersistenceManager,
    PersistenceError,
    StorageBackendError,
    RecordNotFoundError,
)
from user_session_manager import (
    UserSessionManager,
    ApplicationSessionState,
    UserSessionError,
)
from diagnostic_security import (
    SecurityManager,
    SecurityError,
    AuthorizationDeniedError,
)

logger = logging.getLogger("seyyanen.reliability")

T = TypeVar("T")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class ReliabilityCategory(str, enum.Enum):
    """Categorization of operational incidents and errors."""
    COMMUNICATION = "COMMUNICATION"        # Transport timeouts, bus errors, dropped frames
    PLATFORM = "PLATFORM"                  # OS permissions, port unavailable, missing executables
    PERSISTENCE = "PERSISTENCE"            # Database locks, disk errors, corrupted records
    SECURITY = "SECURITY"                  # Authorization denied, invalid context, stale token
    VALIDATION = "VALIDATION"              # Malformed input data, illegal parameters
    OPERATIONAL = "OPERATIONAL"            # Handled business/workflow state blocks
    DEVELOPER = "DEVELOPER"                # Programming defects, assertion failures
    FATAL = "FATAL"                        # Critical unrecoverable failure requiring safe stop


class SystemHealthStatus(str, enum.Enum):
    """Holistic health assessment of application infrastructure."""
    HEALTHY = "HEALTHY"                    # All subsystems operating normally
    DEGRADED = "DEGRADED"                  # One or more non-critical subsystems reporting issues
    DISCONNECTED = "DISCONNECTED"          # Diagnostic adapter or transport offline
    RECOVERING = "RECOVERING"              # Subsystem undergoing controlled recovery
    FAILED = "FAILED"                      # Critical subsystem in unrecoverable error state


class SubsystemType(str, enum.Enum):
    """Identifiable platform subsystems for observability."""
    ADAPTER = "ADAPTER"
    PERSISTENCE = "PERSISTENCE"
    SECURITY = "SECURITY"
    SESSION = "SESSION"
    WORKFLOW = "WORKFLOW"
    TRANSPORT = "TRANSPORT"


class ShutdownState(str, enum.Enum):
    """Lifecycle phase of application shutdown."""
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    TERMINATED = "TERMINATED"


# =====================================================================
# 2. STRUCTURED ERROR MODEL
# =====================================================================

class ReliabilityError(Exception):
    """
    Base exception for all J-6 reliability and resilience boundaries.
    Enforces invariant: Reliability errors are infrastructure errors,
    NEVER vehicle ECU defects.
    """
    def __init__(
        self,
        message: str,
        category: ReliabilityCategory = ReliabilityCategory.OPERATIONAL,
        subsystem: Optional[SubsystemType] = None,
        recoverable: bool = True,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.subsystem = subsystem
        self.recoverable = recoverable
        self.original_exception = original_exception
        self.is_reliability_error = True
        self.is_communication_failure = (category == ReliabilityCategory.COMMUNICATION)
        self.is_diagnostic_fault = False
        self.timestamp = time.time()

    def __str__(self) -> str:
        sub_str = f"[{self.subsystem.value}] " if self.subsystem else ""
        return f"[{self.__class__.__name__}:{self.category.value}] {sub_str}{self.message}"


class FatalReliabilityError(ReliabilityError):
    """Critical unrecoverable error demanding immediate fail-safe stop."""
    def __init__(self, message: str, subsystem: Optional[SubsystemType] = None, original_exception: Optional[Exception] = None):
        super().__init__(message, category=ReliabilityCategory.FATAL, subsystem=subsystem, recoverable=False, original_exception=original_exception)


class TimeoutExceededError(ReliabilityError):
    """Operation exceeded strict bounded execution time."""
    def __init__(self, message: str, subsystem: Optional[SubsystemType] = None):
        super().__init__(message, category=ReliabilityCategory.COMMUNICATION, subsystem=subsystem, recoverable=True)


class DuplicateOperationError(ReliabilityError):
    """Attempted to execute an operation that was already in-flight or completed."""
    def __init__(self, message: str, operation_id: str):
        super().__init__(message, category=ReliabilityCategory.OPERATIONAL, recoverable=False)
        self.operation_id = operation_id


class ShutdownInProgressError(ReliabilityError):
    """Request rejected because the application is shutting down."""
    def __init__(self, message: str = "Application shutdown is in progress; new operations rejected."):
        super().__init__(message, category=ReliabilityCategory.OPERATIONAL, recoverable=False)


@dataclass
class ReliabilityIncident:
    """
    Structured observability record capturing an operational fault or anomaly.
    """
    incident_id: str
    category: ReliabilityCategory
    message: str
    subsystem: Optional[SubsystemType]
    timestamp: float = field(default_factory=time.time)
    recoverable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "category": self.category.value,
            "message": self.message,
            "subsystem": self.subsystem.value if self.subsystem else None,
            "timestamp": round(self.timestamp, 3),
            "recoverable": self.recoverable,
            "details": copy.deepcopy(self.details),
        }


# =====================================================================
# 3. BOUNDED MEMORY RING BUFFER
# =====================================================================

class BoundedRingBuffer(Generic[T]):
    """
    Thread-safe, fixed-capacity circular ring buffer.
    Guarantees strict $O(1)$ append and prevents unbounded memory growth
    in long-running diagnostic acquisition or event streams.
    """
    def __init__(self, capacity: int = 1000):
        if capacity <= 0:
            raise ValueError(f"BoundedRingBuffer capacity must be positive, got {capacity}")
        self._capacity = capacity
        self._buffer: collections.deque[T] = collections.deque(maxlen=capacity)
        self._lock = threading.RLock()
        self._total_appended = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def total_appended(self) -> int:
        with self._lock:
            return self._total_appended

    def append(self, item: T) -> None:
        """Appends an item, automatically evicting the oldest if full."""
        with self._lock:
            self._buffer.append(item)
            self._total_appended += 1

    def extend(self, items: Sequence[T]) -> None:
        with self._lock:
            for item in items:
                self.append(item)

    def to_list(self) -> List[T]:
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def is_full(self) -> bool:
        with self._lock:
            return len(self._buffer) == self._capacity

    def __len__(self) -> int:
        return self.size()

    def __iter__(self) -> Iterator[T]:
        with self._lock:
            return iter(list(self._buffer))


# =====================================================================
# 4. IDEMPOTENCY & DUPLICATE EXECUTION PROTECTION
# =====================================================================

class IdempotencyRegistry:
    """
    Thread-safe registry preventing accidental duplicate execution of
    dangerous or state-changing operations (actuator tests, writes, commits).
    """
    def __init__(self, default_ttl_seconds: float = 120.0):
        self._default_ttl = default_ttl_seconds
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def acquire(self, operation_id: str, ttl_seconds: Optional[float] = None) -> bool:
        """
        Attempts to acquire execution ownership for an operation ID.
        Returns True if acquired; False if already in-flight or completed.
        """
        if not operation_id or not str(operation_id).strip():
            raise ValueError("operation_id must be a non-empty string.")

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = time.time()

        with self._lock:
            self._evict_expired(now)

            if operation_id in self._records:
                rec = self._records[operation_id]
                logger.warning(
                    "Duplicate execution blocked: operation '%s' already %s (registered at %s).",
                    operation_id, rec.get("status"), rec.get("started_at")
                )
                return False

            self._records[operation_id] = {
                "status": "IN_FLIGHT",
                "started_at": now,
                "expires_at": now + ttl,
                "result": None,
            }
            return True

    def complete(self, operation_id: str, result: Optional[Any] = None) -> None:
        """Marks an operation as completed, caching the result within the TTL."""
        with self._lock:
            if operation_id in self._records:
                self._records[operation_id]["status"] = "COMPLETED"
                self._records[operation_id]["result"] = result
                self._records[operation_id]["completed_at"] = time.time()

    def release(self, operation_id: str) -> None:
        """Explicitly releases an operation ID (e.g. upon failure to allow retry)."""
        with self._lock:
            self._records.pop(operation_id, None)

    def is_known(self, operation_id: str) -> bool:
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            return operation_id in self._records

    def _evict_expired(self, now: float) -> None:
        expired = [oid for oid, rec in self._records.items() if now > rec["expires_at"]]
        for oid in expired:
            del self._records[oid]


# =====================================================================
# 5. OPERATION-AWARE RETRY & TIMEOUT POLICY
# =====================================================================

class ReliabilityRetryPolicy:
    """
    Explicit, operation-aware retry policy.
    Enforces core invariant:
      - Read-only queries allow bounded retries on transient transport errors.
      - State-changing / privileged operations have ZERO automatic retries
        when execution status is uncertain (Fail-Safe over Guess).
    """

    @classmethod
    def execute(
        cls,
        func: Callable[[], T],
        is_read_only: bool = True,
        max_retries: int = 2,
        timeout_sec: float = 3.0,
        backoff_sec: float = 0.05,
        operation_name: str = "operation",
    ) -> T:
        start_time = time.monotonic()
        attempts = 0
        allowed_retries = max_retries if is_read_only else 0

        while True:
            attempts += 1
            elapsed = time.monotonic() - start_time
            if elapsed > timeout_sec:
                raise TimeoutExceededError(
                    f"Operation '{operation_name}' exceeded timeout of {timeout_sec}s (elapsed: {round(elapsed, 3)}s)."
                )

            try:
                return func()
            except (TimeoutError, AdapterTimeoutError) as e:
                if attempts > allowed_retries:
                    if not is_read_only:
                        logger.error(
                            "Fail-Safe Stop: State-changing operation '%s' timed out. "
                            "Zero automatic retries permitted on uncertain state.", operation_name
                        )
                    raise TimeoutExceededError(
                        f"Operation '{operation_name}' timed out after {attempts} attempt(s): {e}"
                    ) from e
                time.sleep(backoff_sec * attempts)

            except (TransportFailureError, MalformedResponseError) as e:
                if attempts > allowed_retries:
                    raise ReliabilityError(
                        f"Operation '{operation_name}' failed after {attempts} attempt(s): {e}",
                        category=ReliabilityCategory.COMMUNICATION,
                        original_exception=e,
                    ) from e
                time.sleep(backoff_sec * attempts)

            except Exception as e:
                # Any non-communication error fails immediately without blind retries
                raise


# =====================================================================
# 6. GLOBAL ERROR BOUNDARY
# =====================================================================

class ReliabilityBoundary:
    """
    Top-level structured error boundary protecting application execution paths.
    Catches unhandled exceptions, maps them to canonical ReliabilityCategories,
    ensures resource cleanup, and prevents silent state corruption.
    """

    def __init__(
        self,
        boundary_name: str,
        subsystem: Optional[SubsystemType] = None,
        on_error: Optional[Callable[[ReliabilityIncident], None]] = None,
        rethrow: bool = True,
        default_return: Optional[Any] = None,
    ):
        self.boundary_name = boundary_name
        self.subsystem = subsystem
        self.on_error = on_error
        self.rethrow = rethrow
        self.default_return = default_return
        self.incident: Optional[ReliabilityIncident] = None

    def __enter__(self) -> "ReliabilityBoundary":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_val is None:
            return True

        category = self._classify_exception(exc_val)
        incident = ReliabilityIncident(
            incident_id=f"inc_{uuid.uuid4().hex[:8]}",
            category=category,
            message=str(exc_val) or f"Unhandled {exc_type.__name__}",
            subsystem=self.subsystem,
            timestamp=time.time(),
            recoverable=(category != ReliabilityCategory.FATAL),
            details={
                "boundary": self.boundary_name,
                "exception_type": exc_type.__name__,
            },
        )
        self.incident = incident

        logger.error(
            "ReliabilityBoundary [%s] intercepted %s error: %s",
            self.boundary_name, category.value, exc_val, exc_info=(category == ReliabilityCategory.FATAL)
        )

        if self.on_error:
            try:
                self.on_error(incident)
            except Exception as e:
                logger.warning("Error callback failed in boundary '%s': %s", self.boundary_name, e)

        if self.rethrow:
            # Re-raise as structured ReliabilityError if not already one
            if isinstance(exc_val, ReliabilityError):
                return False
            raise ReliabilityError(
                f"[{self.boundary_name}] {str(exc_val)}",
                category=category,
                subsystem=self.subsystem,
                recoverable=incident.recoverable,
                original_exception=exc_val,
            ) from exc_val

        # Suppress exception and use default return if rethrow is False
        return True

    @staticmethod
    def _classify_exception(exc: BaseException) -> ReliabilityCategory:
        """Deterministically maps any exception to its proper reliability category."""
        if isinstance(exc, (TimeoutError, AdapterTimeoutError, TransportFailureError, MalformedResponseError)):
            return ReliabilityCategory.COMMUNICATION
        if isinstance(exc, (SecurityError, AuthorizationDeniedError)):
            return ReliabilityCategory.SECURITY
        if isinstance(exc, (PersistenceError, StorageBackendError)):
            return ReliabilityCategory.PERSISTENCE
        if isinstance(exc, (ValueError, KeyError)):
            return ReliabilityCategory.VALIDATION
        if isinstance(exc, (AssertionError, TypeError, AttributeError, NotImplementedError)):
            return ReliabilityCategory.DEVELOPER
        if isinstance(exc, (MemoryError, SystemExit, KeyboardInterrupt)):
            return ReliabilityCategory.FATAL
        return ReliabilityCategory.OPERATIONAL


def reliability_boundary(
    boundary_name: str,
    subsystem: Optional[SubsystemType] = None,
    rethrow: bool = True,
    default_return: Optional[Any] = None,
) -> Callable:
    """Decorator syntax wrapping functions in a ReliabilityBoundary."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with ReliabilityBoundary(
                boundary_name=boundary_name,
                subsystem=subsystem,
                rethrow=rethrow,
                default_return=default_return,
            ):
                return func(*args, **kwargs)
            return default_return
        return wrapper
    return decorator


# =====================================================================
# 7. RUNTIME HEALTH & OBSERVABILITY ENGINE
# =====================================================================

class SystemHealthMonitor:
    """
    Centralized health and runtime observability monitor.
    Tracks subsystem statuses independently and calculates holistic platform health.
    
    Invariant: System health describes INFRASTRUCTURE state, NEVER vehicle defects.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._subsystem_health: Dict[SubsystemType, Tuple[SystemHealthStatus, str, float]] = {
            SubsystemType.ADAPTER: (SystemHealthStatus.HEALTHY, "Initialized", time.time()),
            SubsystemType.PERSISTENCE: (SystemHealthStatus.HEALTHY, "Initialized", time.time()),
            SubsystemType.SECURITY: (SystemHealthStatus.HEALTHY, "Initialized", time.time()),
            SubsystemType.SESSION: (SystemHealthStatus.HEALTHY, "Initialized", time.time()),
            SubsystemType.WORKFLOW: (SystemHealthStatus.HEALTHY, "Initialized", time.time()),
        }
        self._incidents: BoundedRingBuffer[ReliabilityIncident] = BoundedRingBuffer(capacity=500)

    def report_subsystem(
        self,
        subsystem: SubsystemType,
        status: SystemHealthStatus,
        message: str = "",
    ) -> None:
        """Updates health status for a specific subsystem."""
        with self._lock:
            self._subsystem_health[subsystem] = (status, message, time.time())
            if status in (SystemHealthStatus.DEGRADED, SystemHealthStatus.FAILED):
                self._incidents.append(
                    ReliabilityIncident(
                        incident_id=f"inc_{uuid.uuid4().hex[:8]}",
                        category=ReliabilityCategory.OPERATIONAL,
                        message=message or f"Subsystem {subsystem.value} entered {status.value}",
                        subsystem=subsystem,
                        timestamp=time.time(),
                        recoverable=(status != SystemHealthStatus.FAILED),
                    )
                )

    def get_subsystem_health(self, subsystem: SubsystemType) -> Tuple[SystemHealthStatus, str, float]:
        with self._lock:
            return self._subsystem_health.get(subsystem, (SystemHealthStatus.FAILED, "Unknown subsystem", 0.0))

    def get_overall_health(self) -> Dict[str, Any]:
        """Calculates holistic system health from subsystem states."""
        with self._lock:
            statuses = [item[0] for item in self._subsystem_health.values()]

            if any(s == SystemHealthStatus.FAILED for s in statuses):
                overall = SystemHealthStatus.FAILED
            elif any(s == SystemHealthStatus.DISCONNECTED for s in statuses):
                overall = SystemHealthStatus.DISCONNECTED
            elif any(s in (SystemHealthStatus.DEGRADED, SystemHealthStatus.RECOVERING) for s in statuses):
                overall = SystemHealthStatus.DEGRADED
            else:
                overall = SystemHealthStatus.HEALTHY

            return {
                "overall_status": overall.value,
                "subsystems": {
                    sub.value: {
                        "status": info[0].value,
                        "message": info[1],
                        "updated_at": round(info[2], 3),
                    }
                    for sub, info in self._subsystem_health.items()
                },
                "total_incidents_recorded": len(self._incidents),
                "timestamp": round(time.time(), 3),
            }

    def get_recent_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [inc.to_dict() for inc in list(self._incidents)[-limit:]]


# =====================================================================
# 8. GRACEFUL SHUTDOWN & RESOURCE CLEANUP COORDINATOR
# =====================================================================

class ShutdownCoordinator:
    """
    Coordinates clean, non-destructive application shutdown.
    Ensures that adapters are disconnected, persistence is closed, and
    locks are released without sending destructive commands to the vehicle.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._state = ShutdownState.RUNNING
        self._cleanups: List[Tuple[str, Callable[[], None]]] = []
        self._shutdown_time: Optional[float] = None

    @property
    def state(self) -> ShutdownState:
        with self._lock:
            return self._state

    def is_shutting_down(self) -> bool:
        with self._lock:
            return self._state in (ShutdownState.SHUTTING_DOWN, ShutdownState.TERMINATED)

    def register_cleanup(self, resource_name: str, cleanup_callable: Callable[[], None]) -> None:
        """Registers a cleanup action to be invoked during shutdown (LIFO order)."""
        with self._lock:
            self._cleanups.append((resource_name, cleanup_callable))

    def require_running(self) -> None:
        """Enforces that the application is not currently shutting down."""
        if self.is_shutting_down():
            raise ShutdownInProgressError()

    def shutdown(self, timeout_sec: float = 5.0) -> Dict[str, Any]:
        """
        Executes controlled shutdown in deterministic order:
          1. Sets state to SHUTTING_DOWN (rejects new operations).
          2. Runs registered cleanups in reverse order (LIFO).
          3. Transitions state to TERMINATED.
        """
        with self._lock:
            if self._state == ShutdownState.TERMINATED:
                return {"status": "ALREADY_TERMINATED", "cleanups_executed": 0}

            self._state = ShutdownState.SHUTTING_DOWN
            self._shutdown_time = time.time()
            logger.info("Graceful shutdown initiated. Executing %d cleanups...", len(self._cleanups))

            results: List[Dict[str, Any]] = []
            # Execute in LIFO order
            for name, cleanup_fn in reversed(self._cleanups):
                try:
                    cleanup_fn()
                    results.append({"resource": name, "status": "OK"})
                except Exception as e:
                    logger.warning("Cleanup error on resource '%s': %s", name, e)
                    results.append({"resource": name, "status": "ERROR", "error": str(e)})

            self._state = ShutdownState.TERMINATED
            self._cleanups.clear()
            logger.info("Graceful shutdown complete.")

            return {
                "status": "TERMINATED",
                "cleanups_executed": len(results),
                "details": results,
                "completed_at": round(time.time(), 3),
            }


# =====================================================================
# 9. MULTI-ECU FAILURE ISOLATION COORDINATOR
# =====================================================================

class MultiECUFailureIsolation:
    """
    Ensures failures in one ECU (timeout, missing response, electrical defect)
    do NOT cascade to invalidate data acquired from healthy ECUs.
    Preserves G-4/G-5 multi-ECU isolation boundaries.
    """

    @staticmethod
    def execute_multi_target(
        targets: List[str],
        operation: Callable[[str], T],
    ) -> Dict[str, Union[T, ReliabilityError]]:
        """
        Executes an operation across multiple ECU targets safely.
        If ECM times out, TCM and BCM continue executing normally.
        """
        results: Dict[str, Union[T, ReliabilityError]] = {}
        for target in targets:
            try:
                results[target] = operation(target)
            except Exception as e:
                logger.warning("Operation on ECU '%s' failed safely: %s", target, e)
                results[target] = ReliabilityError(
                    f"ECU '{target}' communication error: {e}",
                    category=ReliabilityCategory.COMMUNICATION,
                    subsystem=SubsystemType.TRANSPORT,
                    recoverable=True,
                    original_exception=e,
                )
        return results


# =====================================================================
# 10. CRASH RECONCILIATION COORDINATOR
# =====================================================================

class CrashReconciliationCoordinator:
    """
    Coordinates application and diagnostic session reconciliation after an abnormal exit.
    
    CRITICAL INVARIANTS:
    1. Interrupted != Completed: Unclosed sessions are marked INTERRUPTED, never fabricated as CLOSED.
    2. Zero Autonomous Resumes: Recovery NEVER executes ECU communication, test steps, or actuator drives.
    """

    @classmethod
    def reconcile_on_startup(
        cls,
        user_session_manager: UserSessionManager,
        health_monitor: Optional[SystemHealthMonitor] = None,
    ) -> Dict[str, Any]:
        """
        Scans persisted storage on startup and reconciles abandoned sessions.
        """
        reconciled_app_sessions = user_session_manager.recover_interrupted_sessions()

        if health_monitor:
            if reconciled_app_sessions:
                health_monitor.report_subsystem(
                    SubsystemType.SESSION,
                    SystemHealthStatus.DEGRADED,
                    f"Recovered {len(reconciled_app_sessions)} interrupted session(s) from prior crash."
                )
            else:
                health_monitor.report_subsystem(
                    SubsystemType.SESSION,
                    SystemHealthStatus.HEALTHY,
                    "No interrupted sessions found."
                )

        return {
            "reconciled_application_session_ids": reconciled_app_sessions,
            "count": len(reconciled_app_sessions),
            "reconciled_at": round(time.time(), 3),
            "autonomous_ecu_communication": False,
        }
