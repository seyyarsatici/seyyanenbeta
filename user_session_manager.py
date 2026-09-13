#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-4
===================================================
User & Session Management Layer
`user_session_manager.py`

Architectural Role:
    Application Users / Operators (Human)
        ↓
    Application Runtime Sessions (Process / Instance)
        ↓
    Diagnostic Sessions (Phase J-3: DiagnosticSessionRecord)
        ↓
    Workflow Sessions (Phase H-5: DiagnosticWorkflow)
        ↓
    Vehicle & ECU Instances (Phases C → I Domain Context)

Strict Architectural Invariants:
1.  ApplicationUser != ApplicationSession: A user is an operator; a session is a runtime instance.
2.  ApplicationSession != DiagnosticSession: An app session may create multiple vehicle diagnostic sessions.
3.  DiagnosticSession != WorkflowSession: Diagnostic sessions hold diagnostic data; H-5 holds workflow state.
4.  User Identity != Vehicle Identity: User identity must NEVER be used to infer vehicle, ECU, DTC, or diagnosis.
5.  User Identity is NEVER Diagnostic Evidence: Operator identity does not prove vehicle defects.
6.  User Observations != Machine Findings: Technician notes are attributed to users, not fabricated as machine telemetry.
7.  Active Diagnostic Session Lock: User switching or session close must not silently alter an active diagnostic session.
8.  Interrupted != Completed: Unclosed sessions after crash/restart are marked INTERRUPTED, never fabricated as CLOSED.
9.  Recovery Never Communicates: Session recovery never sends ECU frames, tests actuators, or executes workflows.
10. J-4 is NOT J-5: No passwords, tokens, roles, permissions, or access-control schemes (reserved for J-5).
11. Privacy by Design: Minimal data only; zero personal tracking, GPS history, or unnecessary telemetry.
12. J-3 Persistence Authority: All user and session models serialize through the canonical J-3 repository.
"""

from __future__ import annotations

import copy
import enum
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union

# J-2 Platform Abstraction Integration
from platform_abstraction import PlatformManager

# J-3 Persistence Architecture Integration
from diagnostic_persistence import (
    DiagnosticRepository,
    PersistenceManager,
    PersistenceError,
    RecordNotFoundError,
    UnsupportedSchemaVersionError,
    CorruptedPersistenceDataError,
    CURRENT_SCHEMA_VERSION,
)

logger = logging.getLogger("seyyanen.user_session")

CURRENT_J4_SCHEMA_VERSION = 1
DEFAULT_USER_ID = "local_technician"
DEFAULT_USER_DISPLAY_NAME = "Local Technician"


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class UserStatus(str, enum.Enum):
    """Lifecycle status of an ApplicationUser."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationSessionState(str, enum.Enum):
    """Lifecycle states of an ApplicationSession."""
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class SessionAuditEventType(str, enum.Enum):
    """Structured audit trail event types for user and session lifecycle."""
    USER_CREATED = "USER_CREATED"
    USER_SELECTED = "USER_SELECTED"
    USER_SWITCHED = "USER_SWITCHED"
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_PAUSED = "APPLICATION_PAUSED"
    APPLICATION_RESUMED = "APPLICATION_RESUMED"
    APPLICATION_CLOSED = "APPLICATION_CLOSED"
    APPLICATION_INTERRUPTED = "APPLICATION_INTERRUPTED"
    DIAGNOSTIC_SESSION_LINKED = "DIAGNOSTIC_SESSION_LINKED"
    DIAGNOSTIC_SESSION_DETACHED = "DIAGNOSTIC_SESSION_DETACHED"
    DIAGNOSTIC_SESSION_CLOSED = "DIAGNOSTIC_SESSION_CLOSED"


# =====================================================================
# 2. STRUCTURED ERROR MODEL
# =====================================================================

class UserSessionError(Exception):
    """
    Base exception for all J-4 user and session management operations.
    Enforces invariant: User/session errors are application layer errors,
    NEVER vehicle ECU defects (is_communication_failure=False).
    """
    def __init__(self, message: str, user_id: Optional[str] = None, session_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.user_id = user_id
        self.session_id = session_id
        self.is_persistence_error = False
        self.is_communication_failure = False
        self.timestamp = time.time()

    def __str__(self) -> str:
        ctx = []
        if self.user_id:
            ctx.append(f"user:{self.user_id}")
        if self.session_id:
            ctx.append(f"session:{self.session_id}")
        ctx_str = f" [{', '.join(ctx)}]" if ctx else ""
        return f"[{self.__class__.__name__}]{ctx_str} {self.message}"


class UserNotFoundError(UserSessionError):
    """Specified user ID does not exist."""
    pass


class DuplicateUserError(UserSessionError):
    """Attempted to create a user with an existing user ID."""
    pass


class InvalidSessionStateTransitionError(UserSessionError):
    """Illegal state machine transition attempted on ApplicationSession."""
    pass


class ActiveDiagnosticSessionLockError(UserSessionError):
    """User switch or session termination blocked because a diagnostic session is active."""
    pass


class SessionRecoveryError(UserSessionError):
    """Error during crash recovery or interrupted session reconciliation."""
    pass


# =====================================================================
# 3. STRUCTURED DOMAIN MODELS
# =====================================================================

@dataclass
class ApplicationUser:
    """
    Minimal, structured application user / operator identity.
    Represents the human technician using Seyyanen.
    Note: Passwords, credentials, and roles are strictly deferred to Phase J-5.
    """
    user_id: str
    display_name: str
    status: UserStatus = UserStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_J4_SCHEMA_VERSION

    def __post_init__(self):
        if not self.user_id or not str(self.user_id).strip():
            raise UserSessionError("ApplicationUser must have a non-empty user_id.")
        if not self.display_name or not str(self.display_name).strip():
            raise UserSessionError("ApplicationUser must have a non-empty display_name.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "created_at": round(self.created_at, 3),
            "updated_at": round(self.updated_at, 3),
            "metadata": copy.deepcopy(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApplicationUser":
        schema_ver = int(data.get("schema_version", CURRENT_J4_SCHEMA_VERSION))
        if schema_ver > CURRENT_J4_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"ApplicationUser schema version {schema_ver} exceeds maximum supported {CURRENT_J4_SCHEMA_VERSION}.",
                collection="application_users",
                record_id=data.get("user_id"),
            )
        status_val = data.get("status", UserStatus.ACTIVE.value)
        status = UserStatus(status_val) if isinstance(status_val, str) else status_val
        return cls(
            user_id=str(data["user_id"]),
            display_name=str(data["display_name"]),
            status=status,
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            metadata=dict(data.get("metadata", {})),
            schema_version=schema_ver,
        )


@dataclass
class ApplicationSession:
    """
    Structured runtime application session representing one active or past process instance.
    Maintains links to diagnostic sessions created during this runtime, platform context,
    and lifecycle states without conflating application runtime with diagnostic operations.
    """
    application_session_id: str
    user_id: str
    state: ApplicationSessionState = ApplicationSessionState.CREATED
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    last_activity_time: float = field(default_factory=time.time)
    platform_context: Dict[str, Any] = field(default_factory=dict)
    app_version: str = "1.0.0"
    diagnostic_session_ids: List[str] = field(default_factory=list)
    active_diagnostic_session_id: Optional[str] = None
    adapter_info: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_J4_SCHEMA_VERSION

    # Deterministic Lifecycle State Machine Transitions
    VALID_TRANSITIONS: Dict[ApplicationSessionState, Set[ApplicationSessionState]] = field(
        default_factory=lambda: {
            ApplicationSessionState.CREATED: {
                ApplicationSessionState.ACTIVE,
                ApplicationSessionState.FAILED,
                ApplicationSessionState.INTERRUPTED,
            },
            ApplicationSessionState.ACTIVE: {
                ApplicationSessionState.PAUSED,
                ApplicationSessionState.CLOSED,
                ApplicationSessionState.FAILED,
                ApplicationSessionState.INTERRUPTED,
            },
            ApplicationSessionState.PAUSED: {
                ApplicationSessionState.ACTIVE,
                ApplicationSessionState.CLOSED,
                ApplicationSessionState.FAILED,
                ApplicationSessionState.INTERRUPTED,
            },
            ApplicationSessionState.CLOSED: set(),       # Terminal
            ApplicationSessionState.INTERRUPTED: set(),  # Terminal
            ApplicationSessionState.FAILED: set(),       # Terminal
        },
        init=False,
        repr=False,
    )

    def __post_init__(self):
        if not self.application_session_id or not str(self.application_session_id).strip():
            raise UserSessionError("ApplicationSession must have a non-empty application_session_id.")
        if not self.user_id or not str(self.user_id).strip():
            raise UserSessionError("ApplicationSession must have a non-empty user_id.")

    def can_transition_to(self, target_state: ApplicationSessionState) -> bool:
        """Determines if the state transition from current state to target_state is legal."""
        valid_targets = self.VALID_TRANSITIONS.get(self.state, set())
        return target_state in valid_targets

    def transition_to(self, target_state: ApplicationSessionState, reason: str = "") -> None:
        """Executes a deterministic state machine transition, raising on illegal transitions."""
        if not self.can_transition_to(target_state):
            raise InvalidSessionStateTransitionError(
                f"Cannot transition ApplicationSession '{self.application_session_id}' "
                f"from {self.state.value} to {target_state.value}. Reason: {reason or 'Illegal transition'}",
                user_id=self.user_id,
                session_id=self.application_session_id,
            )
        old_state = self.state
        self.state = target_state
        now = time.time()
        self.last_activity_time = now
        if target_state in {ApplicationSessionState.CLOSED, ApplicationSessionState.INTERRUPTED, ApplicationSessionState.FAILED}:
            if self.end_time is None:
                self.end_time = now
        logger.info(
            "ApplicationSession '%s' state transition: %s -> %s (reason: %s)",
            self.application_session_id, old_state.value, target_state.value, reason or "None"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "application_session_id": self.application_session_id,
            "user_id": self.user_id,
            "state": self.state.value,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3) if self.end_time is not None else None,
            "last_activity_time": round(self.last_activity_time, 3),
            "platform_context": copy.deepcopy(self.platform_context),
            "app_version": self.app_version,
            "diagnostic_session_ids": list(self.diagnostic_session_ids),
            "active_diagnostic_session_id": self.active_diagnostic_session_id,
            "adapter_info": copy.deepcopy(self.adapter_info),
            "metadata": copy.deepcopy(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApplicationSession":
        schema_ver = int(data.get("schema_version", CURRENT_J4_SCHEMA_VERSION))
        if schema_ver > CURRENT_J4_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"ApplicationSession schema version {schema_ver} exceeds maximum supported {CURRENT_J4_SCHEMA_VERSION}.",
                collection="application_sessions",
                record_id=data.get("application_session_id"),
            )
        state_val = data.get("state", ApplicationSessionState.CREATED.value)
        state = ApplicationSessionState(state_val) if isinstance(state_val, str) else state_val
        return cls(
            application_session_id=str(data["application_session_id"]),
            user_id=str(data["user_id"]),
            state=state,
            start_time=float(data.get("start_time", time.time())),
            end_time=float(data["end_time"]) if data.get("end_time") is not None else None,
            last_activity_time=float(data.get("last_activity_time", time.time())),
            platform_context=dict(data.get("platform_context", {})),
            app_version=str(data.get("app_version", "1.0.0")),
            diagnostic_session_ids=list(data.get("diagnostic_session_ids", [])),
            active_diagnostic_session_id=data.get("active_diagnostic_session_id"),
            adapter_info=dict(data.get("adapter_info", {})),
            metadata=dict(data.get("metadata", {})),
            schema_version=schema_ver,
        )


@dataclass
class SessionAuditEvent:
    """
    Structured, bounded audit event for session and user operations.
    Preserves auditability without logging fine-grained internal operations.
    """
    event_id: str
    application_session_id: str
    user_id: str
    event_type: SessionAuditEventType
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_J4_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "application_session_id": self.application_session_id,
            "user_id": self.user_id,
            "event_type": self.event_type.value,
            "timestamp": round(self.timestamp, 3),
            "details": copy.deepcopy(self.details),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionAuditEvent":
        schema_ver = int(data.get("schema_version", CURRENT_J4_SCHEMA_VERSION))
        if schema_ver > CURRENT_J4_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"SessionAuditEvent schema version {schema_ver} exceeds maximum supported {CURRENT_J4_SCHEMA_VERSION}.",
                collection="session_audit_events",
                record_id=data.get("event_id"),
            )
        event_type_val = data.get("event_type", SessionAuditEventType.APPLICATION_STARTED.value)
        event_type = SessionAuditEventType(event_type_val) if isinstance(event_type_val, str) else event_type_val
        return cls(
            event_id=str(data["event_id"]),
            application_session_id=str(data["application_session_id"]),
            user_id=str(data["user_id"]),
            event_type=event_type,
            timestamp=float(data.get("timestamp", time.time())),
            details=dict(data.get("details", {})),
            schema_version=schema_ver,
        )


# =====================================================================
# 4. USER & SESSION MANAGEMENT FACADE
# =====================================================================

class UserSessionManager:
    """
    Primary User and Application Session Management Facade for Seyyanen.
    
    Coordinates:
    - User registration, active-user selection, and deterministic user switching.
    - Application runtime session lifecycle (start, pause, resume, close).
    - Diagnostic session linking and detachment.
    - Active diagnostic session locking to prevent accidental ownership transfers.
    - Post-crash session recovery marking unclosed sessions as INTERRUPTED.
    - Structured audit trail preservation via J-3 persistence.
    """

    def __init__(self, repository: Optional[DiagnosticRepository] = None):
        self._repository = repository or PersistenceManager.get_repository()
        self._lock = threading.RLock()
        self._active_user: Optional[ApplicationUser] = None
        self._current_session: Optional[ApplicationSession] = None
        self._ensure_default_user()

    @property
    def repository(self) -> DiagnosticRepository:
        return self._repository

    @property
    def active_user(self) -> Optional[ApplicationUser]:
        with self._lock:
            return self._active_user

    @property
    def current_session(self) -> Optional[ApplicationSession]:
        with self._lock:
            return self._current_session

    # -----------------------------------------------------------------
    # A. User Management
    # -----------------------------------------------------------------

    def _ensure_default_user(self) -> ApplicationUser:
        """Ensures the standard local default user exists for immediate offline use."""
        with self._lock:
            existing = self.get_user(DEFAULT_USER_ID)
            if existing:
                if self._active_user is None:
                    self._active_user = existing
                return existing

            default_user = ApplicationUser(
                user_id=DEFAULT_USER_ID,
                display_name=DEFAULT_USER_DISPLAY_NAME,
                status=UserStatus.ACTIVE,
                metadata={"is_default_local_user": True},
            )
            self._repository.save_user(default_user)
            self._active_user = default_user
            logger.info("Default local user '%s' initialized.", DEFAULT_USER_ID)
            return default_user

    def create_user(
        self,
        display_name: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApplicationUser:
        """Creates and persists a new local application user."""
        with self._lock:
            uid = user_id or f"user_{uuid.uuid4().hex[:8]}"
            if self.get_user(uid) is not None:
                raise DuplicateUserError(f"User ID '{uid}' already exists.", user_id=uid)

            user = ApplicationUser(
                user_id=uid,
                display_name=display_name,
                status=UserStatus.ACTIVE,
                created_at=time.time(),
                updated_at=time.time(),
                metadata=metadata or {},
            )
            self._repository.save_user(user)

            # Record audit event
            curr_sess_id = self._current_session.application_session_id if self._current_session else "bootstrap"
            self._record_audit_event(
                event_type=SessionAuditEventType.USER_CREATED,
                user_id=uid,
                session_id=curr_sess_id,
                details={"display_name": display_name},
            )
            logger.info("Created ApplicationUser '%s' (%s).", uid, display_name)
            return user

    def get_user(self, user_id: str) -> Optional[ApplicationUser]:
        """Retrieves a user by unique identifier."""
        with self._lock:
            raw = self._repository.get_user(user_id)
            if not raw:
                return None
            return ApplicationUser.from_dict(raw)

    def list_users(self, status: Optional[UserStatus] = None) -> List[ApplicationUser]:
        """Lists all registered application users with optional status filter."""
        with self._lock:
            status_str = status.value if status else None
            raw_list = self._repository.list_users(status=status_str)
            return [ApplicationUser.from_dict(d) for d in raw_list]

    def select_active_user(self, user_id: str) -> ApplicationUser:
        """Sets the active user if no application session is currently running."""
        with self._lock:
            user = self.get_user(user_id)
            if not user:
                raise UserNotFoundError(f"Cannot select user '{user_id}': user not found.", user_id=user_id)
            if user.status != UserStatus.ACTIVE:
                raise UserSessionError(f"Cannot select user '{user_id}': status is {user.status.value}.", user_id=user_id)

            prev_user_id = self._active_user.user_id if self._active_user else None
            self._active_user = user

            curr_sess_id = self._current_session.application_session_id if self._current_session else "no_session"
            self._record_audit_event(
                event_type=SessionAuditEventType.USER_SELECTED,
                user_id=user_id,
                session_id=curr_sess_id,
                details={"previous_user_id": prev_user_id},
            )
            return user

    def switch_user(self, new_user_id: str, force: bool = False) -> ApplicationUser:
        """
        Switches the active user during runtime with active diagnostic session locking.
        If a diagnostic session is active and force is False, raises ActiveDiagnosticSessionLockError.
        """
        with self._lock:
            if self._active_user and self._active_user.user_id == new_user_id:
                return self._active_user

            new_user = self.get_user(new_user_id)
            if not new_user:
                raise UserNotFoundError(f"Cannot switch to user '{new_user_id}': user not found.", user_id=new_user_id)
            if new_user.status != UserStatus.ACTIVE:
                raise UserSessionError(f"Cannot switch to inactive user '{new_user_id}'.", user_id=new_user_id)

            # Check for active diagnostic session lock
            if self._current_session and self._current_session.active_diagnostic_session_id:
                active_diag_id = self._current_session.active_diagnostic_session_id
                if not force:
                    raise ActiveDiagnosticSessionLockError(
                        f"Cannot switch user to '{new_user_id}' while diagnostic session "
                        f"'{active_diag_id}' is active. Detach or close the diagnostic session first, "
                        f"or specify force=True.",
                        user_id=self._active_user.user_id if self._active_user else None,
                        session_id=self._current_session.application_session_id,
                    )
                else:
                    # Explicit detachment policy under force
                    self.detach_diagnostic_session(active_diag_id, reason="User switch forced detachment")

            old_user_id = self._active_user.user_id if self._active_user else "none"
            self._active_user = new_user

            # If an application session is currently running, associate the new user
            curr_sess_id = "no_session"
            if self._current_session:
                self._current_session.user_id = new_user_id
                self._current_session.last_activity_time = time.time()
                self._repository.save_application_session(self._current_session)
                curr_sess_id = self._current_session.application_session_id

            self._record_audit_event(
                event_type=SessionAuditEventType.USER_SWITCHED,
                user_id=new_user_id,
                session_id=curr_sess_id,
                details={"previous_user_id": old_user_id, "forced": force},
            )
            logger.info("Switched active user from '%s' to '%s'.", old_user_id, new_user_id)
            return new_user

    # -----------------------------------------------------------------
    # B. Application Session Lifecycle
    # -----------------------------------------------------------------

    def start_application_session(
        self,
        app_version: str = "1.0.0",
        adapter_info: Optional[Dict[str, Any]] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ApplicationSession:
        """
        Starts a new runtime application session instance.
        Transitions state from CREATED to ACTIVE and records platform context.
        """
        with self._lock:
            if self._active_user is None:
                self._ensure_default_user()

            assert self._active_user is not None

            # Get J-2 platform context
            platform_info = PlatformManager.get_info()
            platform_context = platform_info.to_dict()

            session_id = f"appsess_{uuid.uuid4().hex[:12]}"
            session = ApplicationSession(
                application_session_id=session_id,
                user_id=self._active_user.user_id,
                state=ApplicationSessionState.CREATED,
                start_time=time.time(),
                last_activity_time=time.time(),
                platform_context=platform_context,
                app_version=app_version,
                adapter_info=adapter_info or {},
                metadata=session_metadata or {},
            )

            # Deterministic transition to ACTIVE
            session.transition_to(ApplicationSessionState.ACTIVE, reason="Session initialized and started")
            self._repository.save_application_session(session)
            self._current_session = session

            self._record_audit_event(
                event_type=SessionAuditEventType.APPLICATION_STARTED,
                user_id=self._active_user.user_id,
                session_id=session_id,
                details={"app_version": app_version, "os_family": platform_info.os_family.value},
            )
            logger.info("Started ApplicationSession '%s' for user '%s'.", session_id, self._active_user.user_id)
            return session

    def pause_application_session(self, reason: str = "") -> ApplicationSession:
        """Pauses the active application session."""
        with self._lock:
            if not self._current_session:
                raise UserSessionError("No application session is currently running.")

            self._current_session.transition_to(ApplicationSessionState.PAUSED, reason=reason or "User requested pause")
            self._repository.save_application_session(self._current_session)

            self._record_audit_event(
                event_type=SessionAuditEventType.APPLICATION_PAUSED,
                user_id=self._current_session.user_id,
                session_id=self._current_session.application_session_id,
                details={"reason": reason},
            )
            return self._current_session

    def resume_application_session(self) -> ApplicationSession:
        """Resumes a paused application session."""
        with self._lock:
            if not self._current_session:
                raise UserSessionError("No application session is currently running.")

            self._current_session.transition_to(ApplicationSessionState.ACTIVE, reason="Session resumed")
            self._repository.save_application_session(self._current_session)

            self._record_audit_event(
                event_type=SessionAuditEventType.APPLICATION_RESUMED,
                user_id=self._current_session.user_id,
                session_id=self._current_session.application_session_id,
                details={},
            )
            return self._current_session

    def close_application_session(self, force: bool = False, reason: str = "") -> ApplicationSession:
        """
        Closes the active application session.
        Enforces active diagnostic session lock if a diagnostic session is attached.
        """
        with self._lock:
            if not self._current_session:
                raise UserSessionError("No application session is currently running.")

            if self._current_session.active_diagnostic_session_id:
                active_diag_id = self._current_session.active_diagnostic_session_id
                if not force:
                    raise ActiveDiagnosticSessionLockError(
                        f"Cannot close application session while diagnostic session "
                        f"'{active_diag_id}' is active. Detach or close diagnostic session first, "
                        f"or specify force=True.",
                        user_id=self._current_session.user_id,
                        session_id=self._current_session.application_session_id,
                    )
                else:
                    self.detach_diagnostic_session(active_diag_id, reason="Application session closing forced detachment")

            self._current_session.transition_to(ApplicationSessionState.CLOSED, reason=reason or "Session closed cleanly")
            self._repository.save_application_session(self._current_session)

            closed_session = self._current_session
            self._record_audit_event(
                event_type=SessionAuditEventType.APPLICATION_CLOSED,
                user_id=closed_session.user_id,
                session_id=closed_session.application_session_id,
                details={"reason": reason, "forced": force},
            )
            self._current_session = None
            logger.info("Closed ApplicationSession '%s'.", closed_session.application_session_id)
            return closed_session

    # -----------------------------------------------------------------
    # C. Diagnostic Session Linking & Workflow Association
    # -----------------------------------------------------------------

    def link_diagnostic_session(self, diagnostic_session_id: str, set_as_active: bool = True) -> None:
        """
        Associates a diagnostic session with the current application session.
        Maintains separation: ApplicationSession != DiagnosticSession.
        """
        with self._lock:
            if not self._current_session:
                raise UserSessionError("Cannot link diagnostic session: no application session is currently running.")

            if diagnostic_session_id not in self._current_session.diagnostic_session_ids:
                self._current_session.diagnostic_session_ids.append(diagnostic_session_id)

            if set_as_active:
                self._current_session.active_diagnostic_session_id = diagnostic_session_id

            self._current_session.last_activity_time = time.time()
            self._repository.save_application_session(self._current_session)

            # Associate application session and user ID into persisted DiagnosticSessionRecord if present
            diag_record = self._repository.get_session(diagnostic_session_id)
            if diag_record:
                diag_record.application_session_id = self._current_session.application_session_id
                diag_record.user_id = self._current_session.user_id
                self._repository.save_session(diag_record)

            self._record_audit_event(
                event_type=SessionAuditEventType.DIAGNOSTIC_SESSION_LINKED,
                user_id=self._current_session.user_id,
                session_id=self._current_session.application_session_id,
                details={"diagnostic_session_id": diagnostic_session_id, "set_as_active": set_as_active},
            )

    def detach_diagnostic_session(self, diagnostic_session_id: str, reason: str = "") -> None:
        """Detaches a diagnostic session from being actively locked to the application session."""
        with self._lock:
            if not self._current_session:
                return

            if self._current_session.active_diagnostic_session_id == diagnostic_session_id:
                self._current_session.active_diagnostic_session_id = None
                self._current_session.last_activity_time = time.time()
                self._repository.save_application_session(self._current_session)

                self._record_audit_event(
                    event_type=SessionAuditEventType.DIAGNOSTIC_SESSION_DETACHED,
                    user_id=self._current_session.user_id,
                    session_id=self._current_session.application_session_id,
                    details={"diagnostic_session_id": diagnostic_session_id, "reason": reason},
                )

    def close_diagnostic_session(self, diagnostic_session_id: str, reason: str = "") -> None:
        """Records completion or closure of a diagnostic session."""
        with self._lock:
            self.detach_diagnostic_session(diagnostic_session_id, reason=reason or "Diagnostic session completed")
            curr_sess_id = self._current_session.application_session_id if self._current_session else "no_session"
            uid = self._active_user.user_id if self._active_user else "unknown"
            self._record_audit_event(
                event_type=SessionAuditEventType.DIAGNOSTIC_SESSION_CLOSED,
                user_id=uid,
                session_id=curr_sess_id,
                details={"diagnostic_session_id": diagnostic_session_id, "reason": reason},
            )

    # -----------------------------------------------------------------
    # D. Crash Recovery & Interrupted Sessions
    # -----------------------------------------------------------------

    def recover_interrupted_sessions(self) -> List[str]:
        """
        Scans persisted storage for unclosed sessions (CREATED, ACTIVE, PAUSED)
        from previous runs and transitions them to INTERRUPTED.
        
        CRITICAL SAFETY INVARIANT:
        Recovery NEVER automatically communicates with any ECU, NEVER starts tests,
        and NEVER dispatches commands to the vehicle.
        """
        with self._lock:
            interrupted_ids: List[str] = []
            all_sessions = self._repository.list_application_sessions(limit=10000)
            now = time.time()

            current_id = self._current_session.application_session_id if self._current_session else None

            for sess_data in all_sessions:
                sid = sess_data.get("application_session_id")
                state_str = sess_data.get("state")
                if sid == current_id:
                    continue  # Do not mark our own currently running session

                if state_str in {
                    ApplicationSessionState.CREATED.value,
                    ApplicationSessionState.ACTIVE.value,
                    ApplicationSessionState.PAUSED.value,
                }:
                    sess = ApplicationSession.from_dict(sess_data)
                    sess.transition_to(
                        ApplicationSessionState.INTERRUPTED,
                        reason="Reconciled on application restart; abnormal termination identified",
                    )
                    self._repository.save_application_session(sess)
                    interrupted_ids.append(sess.application_session_id)

                    self._record_audit_event(
                        event_type=SessionAuditEventType.APPLICATION_INTERRUPTED,
                        user_id=sess.user_id,
                        session_id=sess.application_session_id,
                        details={
                            "previous_state": state_str,
                            "recovery_timestamp": round(now, 3),
                            "action": "Session marked INTERRUPTED without ECU communication",
                        },
                    )

            logger.info("Recovered %d interrupted session(s): %s", len(interrupted_ids), interrupted_ids)
            return interrupted_ids

    # -----------------------------------------------------------------
    # E. Technician Observations & Report Integration
    # -----------------------------------------------------------------

    def attribute_technician_observation(
        self,
        observation_text: str,
        target_ecu: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Creates a structured technician observation record attributed to the active user.
        Preserves strict distinction: User Observation != Machine-Generated Finding.
        """
        with self._lock:
            if not self._active_user:
                self._ensure_default_user()

            assert self._active_user is not None

            return {
                "observation_id": f"obs_{uuid.uuid4().hex[:8]}",
                "user_id": self._active_user.user_id,
                "display_name": self._active_user.display_name,
                "application_session_id": self._current_session.application_session_id if self._current_session else None,
                "target_ecu": target_ecu,
                "observation_text": observation_text,
                "is_technician_observation": True,
                "is_machine_finding": False,
                "recorded_at": time.time(),
                "details": details or {},
            }

    def generate_report_session_metadata(
        self,
        diagnostic_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Provides metadata for diagnostic reports including operator, session,
        platform context, and timestamps without altering diagnostic findings.
        """
        with self._lock:
            user_id = self._active_user.user_id if self._active_user else DEFAULT_USER_ID
            display_name = self._active_user.display_name if self._active_user else DEFAULT_USER_DISPLAY_NAME
            app_session_id = self._current_session.application_session_id if self._current_session else None
            app_version = self._current_session.app_version if self._current_session else "1.0.0"

            return {
                "operator_user_id": user_id,
                "operator_display_name": display_name,
                "application_session_id": app_session_id,
                "diagnostic_session_id": diagnostic_session_id,
                "app_version": app_version,
                "platform": PlatformManager.get_info().os_family.value,
                "generated_at": round(time.time(), 3),
            }

    # -----------------------------------------------------------------
    # F. Internal Audit Event Recording
    # -----------------------------------------------------------------

    def _record_audit_event(
        self,
        event_type: SessionAuditEventType,
        user_id: str,
        session_id: str,
        details: Dict[str, Any],
    ) -> SessionAuditEvent:
        """Internal helper to write a structured SessionAuditEvent to storage."""
        event = SessionAuditEvent(
            event_id=f"audit_{uuid.uuid4().hex[:10]}",
            application_session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            timestamp=time.time(),
            details=details,
        )
        try:
            self._repository.save_audit_event(event)
        except Exception as e:
            logger.warning("Failed to persist audit event %s: %s", event_type.value, e)
        return event
