#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-5
===================================================
Security & Permissions Architecture
`diagnostic_security.py`

Architectural Role:
    User / Client Request
        ↓
    J-5 Authorization Gate (Security & Permissions)
        ↓
    G-1 / J-1 Diagnostic Safety Gate (ServiceSafetyPolicy)
        ↓
    H-2 / H-5 Workflow Constraints
        ↓
    J-1 Adapter & VCI Abstraction
        ↓
    Vehicle / ECU Physical Transport

Strict Architectural Invariants:
1.  Authentication / Identity != Authorization: J-4 owns identity/lifecycle; J-5 determines permissions.
2.  Authorization != Diagnostic Safety: User permission NEVER replaces or weakens diagnostic safety.
3.  Double-Gate Requirement: Dangerous/diagnostic operations require BOTH Authorization PASS and Safety PASS.
4.  Default Deny: Unknown operations, unknown permissions, unknown roles, or missing context evaluate to DENY.
5.  Resource Scoping & Isolation: Authority for vehicle A / session A does not authorize vehicle B / session B.
6.  Session Binding & User Switch Invalidation: Privileged authorizations are bound to active session; user switch invalidates context.
7.  Restart Never Auto-Authorizes: System restart restores J-4 identity, but NEVER persists or auto-restores active privileged authority.
8.  Security Failure != Diagnostic Failure: Permission denials are security events, NEVER ECU defects or component faults.
9.  AI / Reasoning Layer Containment: I-1 through I-5 recommendations are untrusted inputs; they cannot execute directly or bypass gates.
10. Admin Boundary: ADMIN role manages users and configuration; ADMIN does NOT grant permission to bypass diagnostic safety.
11. Privacy & Secrets: No hardcoded secrets, tokens, credentials, or API keys; no secrets in logs or reports.
12. Persistence Authority: All security audit events route through the canonical J-3 DiagnosticRepository.
"""

from __future__ import annotations

import copy
import enum
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# J-3 Persistence Architecture Integration
from diagnostic_persistence import (
    DiagnosticRepository,
    PersistenceManager,
    PersistenceError,
    RecordNotFoundError,
    UnsupportedSchemaVersionError,
)

# J-4 User & Session Management Integration
from user_session_manager import (
    ApplicationUser,
    ApplicationSession,
    UserStatus,
    UserSessionManager,
    DEFAULT_USER_ID,
)

# G-1 Advanced ECU Services & Safety Integration
from advanced_ecu_services import (
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    AdvancedServiceRequest,
)

logger = logging.getLogger("seyyanen.security")

CURRENT_J5_SECURITY_POLICY_VERSION = 1


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class Role(str, enum.Enum):
    """
    Minimal, structured diagnostic role taxonomy.
    Roles are non-overlapping collections of capabilities.
    """
    VIEWER = "VIEWER"                          # Read-only observation, telemetry, DTC viewing
    TECHNICIAN = "TECHNICIAN"                  # Standard diagnostics, guided tests, acquisitions
    ADVANCED_TECHNICIAN = "ADVANCED_TECHNICIAN"# Advanced services, actuator tests, DTC clear
    ADMIN = "ADMIN"                            # User management, configuration, security policy


class Permission(str, enum.Enum):
    """
    Granular permissions governing automotive diagnostic and platform operations.
    """
    VIEW_DIAGNOSTIC_DATA = "VIEW_DIAGNOSTIC_DATA"
    START_DIAGNOSTIC_SESSION = "START_DIAGNOSTIC_SESSION"
    READ_DTC = "READ_DTC"
    READ_LIVE_DATA = "READ_LIVE_DATA"
    RUN_READ_ONLY_TEST = "RUN_READ_ONLY_TEST"
    RUN_GUIDED_TEST = "RUN_GUIDED_TEST"
    RUN_ADVANCED_SERVICE = "RUN_ADVANCED_SERVICE"
    RUN_ACTUATOR_TEST = "RUN_ACTUATOR_TEST"
    WRITE_ECU = "WRITE_ECU"
    CLEAR_DTC = "CLEAR_DTC"
    MODIFY_CONFIGURATION = "MODIFY_CONFIGURATION"
    MANAGE_USERS = "MANAGE_USERS"
    MANAGE_SECURITY_POLICY = "MANAGE_SECURITY_POLICY"
    EXPORT_DIAGNOSTIC_REPORT = "EXPORT_DIAGNOSTIC_REPORT"


class OperationCategory(str, enum.Enum):
    """Classification of diagnostic and system operations by potential risk."""
    READ_ONLY = "READ_ONLY"                    # Passive reading (PIDs, DTCs, contexts)
    DIAGNOSTIC_ACTION = "DIAGNOSTIC_ACTION"    # Controlled non-destructive execution (tests)
    PRIVILEGED = "PRIVILEGED"                  # State-altering operations (clear DTC, user management)
    HIGHLY_PRIVILEGED = "HIGHLY_PRIVILEGED"    # Hardware write, ECU coding, calibration change


class AuthorizationDecisionStatus(str, enum.Enum):
    """Binary decision outcomes for authorization evaluation."""
    ALLOW = "ALLOW"
    DENY = "DENY"


class DenialReason(str, enum.Enum):
    """Granular, explainable reasons for authorization denial."""
    ALLOWED = "ALLOWED"
    NO_AUTH_CONTEXT = "NO_AUTH_CONTEXT"
    UNKNOWN_USER = "UNKNOWN_USER"
    INACTIVE_USER = "INACTIVE_USER"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    RESOURCE_SCOPE_MISMATCH = "RESOURCE_SCOPE_MISMATCH"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    SAFETY_POLICY_DENIED = "SAFETY_POLICY_DENIED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    STALE_AUTHORIZATION = "STALE_AUTHORIZATION"
    MALFORMED_INPUT = "MALFORMED_INPUT"
    UNTRUSTED_AI_COMMAND = "UNTRUSTED_AI_COMMAND"


class SecurityAuditEventType(str, enum.Enum):
    """Structured security audit trail event classifications."""
    AUTHORIZATION_ALLOWED = "AUTHORIZATION_ALLOWED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    PRIVILEGED_OPERATION_REQUESTED = "PRIVILEGED_OPERATION_REQUESTED"
    PRIVILEGED_OPERATION_BLOCKED = "PRIVILEGED_OPERATION_BLOCKED"
    USER_ROLE_ASSIGNED = "USER_ROLE_ASSIGNED"
    SECURITY_POLICY_CHANGED = "SECURITY_POLICY_CHANGED"


# =====================================================================
# 2. STRUCTURED SECURITY ERROR MODEL
# =====================================================================

class SecurityError(Exception):
    """
    Base exception for all J-5 security and permission anomalies.
    Enforces strict invariant:
      - is_security_error = True
      - is_communication_failure = False
      - is_diagnostic_fault = False
    A permission rejection or security violation is NEVER a vehicle ECU defect.
    """
    def __init__(
        self,
        message: str,
        principal_id: Optional[str] = None,
        operation: Optional[str] = None,
        resource: Optional[str] = None,
        reason: DenialReason = DenialReason.MALFORMED_INPUT,
    ):
        super().__init__(message)
        self.message = message
        self.principal_id = principal_id
        self.operation = operation
        self.resource = resource
        self.reason = reason
        self.is_security_error = True
        self.is_communication_failure = False
        self.is_diagnostic_fault = False
        self.timestamp = time.time()

    def __str__(self) -> str:
        ctx = []
        if self.principal_id:
            ctx.append(f"user:{self.principal_id}")
        if self.operation:
            ctx.append(f"op:{self.operation}")
        if self.resource:
            ctx.append(f"res:{self.resource}")
        ctx_str = f" [{', '.join(ctx)}]" if ctx else ""
        return f"[{self.__class__.__name__}]{ctx_str} ({self.reason.value}) {self.message}"


class AuthorizationDeniedError(SecurityError):
    """Requested operation was explicitly denied by security policy."""
    pass


class InvalidSecurityContextError(SecurityError):
    """Authorization context is missing, expired, malformed, or session-mismatched."""
    pass


class SecurityPolicyViolationError(SecurityError):
    """Attempted an unsafe action violating security invariants (e.g. untrusted AI execution)."""
    pass


# =====================================================================
# 3. STRUCTURED DOMAIN MODELS
# =====================================================================

@dataclass
class Principal:
    """
    Represents an authorized user identity with assigned diagnostic roles.
    Integrates with J-4 ApplicationUser without duplicating user lifecycle.
    """
    user_id: str
    roles: List[Role] = field(default_factory=lambda: [Role.VIEWER])
    is_active: bool = True
    assigned_at: float = field(default_factory=time.time)
    assigned_by: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_J5_SECURITY_POLICY_VERSION

    def has_role(self, role: Union[Role, str]) -> bool:
        r = Role(role) if isinstance(role, str) else role
        return r in self.roles

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "roles": [r.value for r in self.roles],
            "is_active": self.is_active,
            "assigned_at": round(self.assigned_at, 3),
            "assigned_by": self.assigned_by,
            "metadata": copy.deepcopy(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Principal":
        roles = [Role(r) for r in data.get("roles", [Role.VIEWER.value])]
        return cls(
            user_id=str(data["user_id"]),
            roles=roles,
            is_active=bool(data.get("is_active", True)),
            assigned_at=float(data.get("assigned_at", time.time())),
            assigned_by=str(data.get("assigned_by", "system")),
            metadata=dict(data.get("metadata", {})),
            schema_version=int(data.get("schema_version", CURRENT_J5_SECURITY_POLICY_VERSION)),
        )


@dataclass
class AuthorizationContext:
    """
    Structured context required to make an authorization decision.
    Binds the operation to active session, target vehicle, and ECU resources.
    """
    user_id: str
    application_session_id: str
    requested_operation: str
    resource: str                                  # e.g. "vehicle:WAUZZZ123", "ecu:ECM", "app:diagnostics"
    diagnostic_session_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    ecu_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:8]}")
    roles: Optional[List[Role]] = None             # Optional override; resolved from Principal if None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.user_id or not str(self.user_id).strip():
            raise InvalidSecurityContextError("AuthorizationContext must have a non-empty user_id.")
        if not self.application_session_id or not str(self.application_session_id).strip():
            raise InvalidSecurityContextError("AuthorizationContext must have a non-empty application_session_id.")
        if not self.requested_operation or not str(self.requested_operation).strip():
            raise InvalidSecurityContextError("AuthorizationContext must have a non-empty requested_operation.")
        if not self.resource or not str(self.resource).strip():
            raise InvalidSecurityContextError("AuthorizationContext must have a non-empty resource.")


@dataclass
class AuthorizationDecision:
    """
    Deterministic, explainable authorization evaluation outcome.
    """
    status: AuthorizationDecisionStatus
    reason: DenialReason
    permission_evaluated: Optional[Permission] = None
    principal_id: str = ""
    resource: str = ""
    operation: str = ""
    policy_version: int = CURRENT_J5_SECURITY_POLICY_VERSION
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def is_allowed(self) -> bool:
        return self.status == AuthorizationDecisionStatus.ALLOW

    def require_allowed(self) -> None:
        """Helper to assert allowance; raises AuthorizationDeniedError on denial."""
        if not self.is_allowed():
            raise AuthorizationDeniedError(
                f"Operation '{self.operation}' on resource '{self.resource}' was denied: {self.reason.value}.",
                principal_id=self.principal_id,
                operation=self.operation,
                resource=self.resource,
                reason=self.reason,
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason.value,
            "permission_evaluated": self.permission_evaluated.value if self.permission_evaluated else None,
            "principal_id": self.principal_id,
            "resource": self.resource,
            "operation": self.operation,
            "policy_version": self.policy_version,
            "timestamp": round(self.timestamp, 3),
            "details": copy.deepcopy(self.details),
        }


@dataclass
class SecurityAuditEvent:
    """
    Structured, bounded audit event for security and authorization decisions.
    Preserves audit trails without storing credentials, tokens, or personal secrets.
    """
    event_id: str
    event_type: SecurityAuditEventType
    principal_id: str
    application_session_id: str
    operation: str
    resource: str
    decision: AuthorizationDecisionStatus
    reason: DenialReason
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_J5_SECURITY_POLICY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "principal_id": self.principal_id,
            "application_session_id": self.application_session_id,
            "operation": self.operation,
            "resource": self.resource,
            "decision": self.decision.value,
            "reason": self.reason.value,
            "timestamp": round(self.timestamp, 3),
            "details": copy.deepcopy(self.details),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityAuditEvent":
        schema_ver = int(data.get("schema_version", CURRENT_J5_SECURITY_POLICY_VERSION))
        if schema_ver > CURRENT_J5_SECURITY_POLICY_VERSION:
            raise UnsupportedSchemaVersionError(
                f"SecurityAuditEvent schema version {schema_ver} exceeds maximum supported {CURRENT_J5_SECURITY_POLICY_VERSION}.",
                collection="security_audit_events",
                record_id=data.get("event_id"),
            )
        return cls(
            event_id=str(data["event_id"]),
            event_type=SecurityAuditEventType(data["event_type"]),
            principal_id=str(data["principal_id"]),
            application_session_id=str(data.get("application_session_id", "")),
            operation=str(data.get("operation", "")),
            resource=str(data.get("resource", "")),
            decision=AuthorizationDecisionStatus(data["decision"]),
            reason=DenialReason(data.get("reason", DenialReason.ALLOWED.value)),
            timestamp=float(data.get("timestamp", time.time())),
            details=dict(data.get("details", {})),
            schema_version=schema_ver,
        )


# =====================================================================
# 4. CANONICAL SECURITY POLICY ENGINE
# =====================================================================

class SecurityPolicy:
    """
    Authoritative, versioned Security Policy defining role-to-permission
    mappings and operation classification for automotive diagnostics.
    Enforces strict DEFAULT DENY.
    """

    def __init__(self, policy_version: int = CURRENT_J5_SECURITY_POLICY_VERSION):
        self.policy_version = policy_version

        # Role-to-Permissions Mapping
        self._role_permissions: Dict[Role, Set[Permission]] = {
            Role.VIEWER: {
                Permission.VIEW_DIAGNOSTIC_DATA,
                Permission.READ_DTC,
                Permission.READ_LIVE_DATA,
                Permission.EXPORT_DIAGNOSTIC_REPORT,
            },
            Role.TECHNICIAN: {
                Permission.VIEW_DIAGNOSTIC_DATA,
                Permission.READ_DTC,
                Permission.READ_LIVE_DATA,
                Permission.EXPORT_DIAGNOSTIC_REPORT,
                Permission.START_DIAGNOSTIC_SESSION,
                Permission.RUN_READ_ONLY_TEST,
                Permission.RUN_GUIDED_TEST,
            },
            Role.ADVANCED_TECHNICIAN: {
                Permission.VIEW_DIAGNOSTIC_DATA,
                Permission.READ_DTC,
                Permission.READ_LIVE_DATA,
                Permission.EXPORT_DIAGNOSTIC_REPORT,
                Permission.START_DIAGNOSTIC_SESSION,
                Permission.RUN_READ_ONLY_TEST,
                Permission.RUN_GUIDED_TEST,
                Permission.RUN_ADVANCED_SERVICE,
                Permission.RUN_ACTUATOR_TEST,
                Permission.CLEAR_DTC,
            },
            Role.ADMIN: {
                Permission.VIEW_DIAGNOSTIC_DATA,
                Permission.READ_DTC,
                Permission.READ_LIVE_DATA,
                Permission.EXPORT_DIAGNOSTIC_REPORT,
                Permission.START_DIAGNOSTIC_SESSION,
                Permission.RUN_READ_ONLY_TEST,
                Permission.RUN_GUIDED_TEST,
                Permission.RUN_ADVANCED_SERVICE,
                Permission.RUN_ACTUATOR_TEST,
                Permission.CLEAR_DTC,
                Permission.MODIFY_CONFIGURATION,
                Permission.MANAGE_USERS,
                Permission.MANAGE_SECURITY_POLICY,
            },
        }

        # Canonical Operations Mapping
        self._operation_permissions: Dict[str, Permission] = {
            "view_diagnostic_data": Permission.VIEW_DIAGNOSTIC_DATA,
            "read_dtc": Permission.READ_DTC,
            "read_live_data": Permission.READ_LIVE_DATA,
            "read_pid": Permission.READ_LIVE_DATA,
            "read_did": Permission.READ_LIVE_DATA,
            "export_diagnostic_report": Permission.EXPORT_DIAGNOSTIC_REPORT,
            "start_diagnostic_session": Permission.START_DIAGNOSTIC_SESSION,
            "run_read_only_test": Permission.RUN_READ_ONLY_TEST,
            "run_guided_test": Permission.RUN_GUIDED_TEST,
            "run_advanced_service": Permission.RUN_ADVANCED_SERVICE,
            "run_actuator_test": Permission.RUN_ACTUATOR_TEST,
            "clear_dtc": Permission.CLEAR_DTC,
            "write_ecu": Permission.WRITE_ECU,
            "modify_configuration": Permission.MODIFY_CONFIGURATION,
            "manage_users": Permission.MANAGE_USERS,
            "manage_security_policy": Permission.MANAGE_SECURITY_POLICY,
        }

        # Operation Risk Categories
        self._operation_categories: Dict[str, OperationCategory] = {
            "view_diagnostic_data": OperationCategory.READ_ONLY,
            "read_dtc": OperationCategory.READ_ONLY,
            "read_live_data": OperationCategory.READ_ONLY,
            "read_pid": OperationCategory.READ_ONLY,
            "read_did": OperationCategory.READ_ONLY,
            "export_diagnostic_report": OperationCategory.READ_ONLY,
            "start_diagnostic_session": OperationCategory.DIAGNOSTIC_ACTION,
            "run_read_only_test": OperationCategory.DIAGNOSTIC_ACTION,
            "run_guided_test": OperationCategory.DIAGNOSTIC_ACTION,
            "run_advanced_service": OperationCategory.DIAGNOSTIC_ACTION,
            "run_actuator_test": OperationCategory.PRIVILEGED,
            "clear_dtc": OperationCategory.PRIVILEGED,
            "write_ecu": OperationCategory.HIGHLY_PRIVILEGED,
            "modify_configuration": OperationCategory.PRIVILEGED,
            "manage_users": OperationCategory.PRIVILEGED,
            "manage_security_policy": OperationCategory.PRIVILEGED,
        }

    def get_permission_for_operation(self, operation: str) -> Optional[Permission]:
        norm = operation.strip().lower()
        return self._operation_permissions.get(norm)

    def get_category_for_operation(self, operation: str) -> Optional[OperationCategory]:
        norm = operation.strip().lower()
        return self._operation_categories.get(norm)

    def get_permissions_for_roles(self, roles: List[Role]) -> Set[Permission]:
        perms: Set[Permission] = set()
        for r in roles:
            perms.update(self._role_permissions.get(r, set()))
        return perms

    def is_privileged_operation(self, operation: str) -> bool:
        cat = self.get_category_for_operation(operation)
        return cat in (OperationCategory.PRIVILEGED, OperationCategory.HIGHLY_PRIVILEGED)


# =====================================================================
# 5. SECURITY & AUTHORIZATION MANAGER (CANONICAL FACADE)
# =====================================================================

class SecurityManager:
    """
    Primary Security and Authorization Management Facade for Seyyanen.
    
    Coordinates:
    - Principal role management and persistence.
    - Deterministic authorization evaluation with Default Deny.
    - Resource scoping (Vehicle / ECU / Session boundaries).
    - Double-Gate validation pairing J-5 Authorization with G-1/J-1 Diagnostic Safety.
    - AI recommendation containment and untrusted input rejection.
    - Invalidation on user switching and restart.
    - Structured security audit logging via J-3 persistence.
    """

    def __init__(
        self,
        repository: Optional[DiagnosticRepository] = None,
        user_session_manager: Optional[UserSessionManager] = None,
        policy: Optional[SecurityPolicy] = None,
    ):
        self._repository = repository or PersistenceManager.get_repository()
        self._user_session_manager = user_session_manager
        self._policy = policy or SecurityPolicy()
        self._lock = threading.RLock()
        self._principals: Dict[str, Principal] = {}
        self._invalidated_sessions: Set[str] = set()
        self._initialize_default_principals()

    @property
    def policy(self) -> SecurityPolicy:
        return self._policy

    @property
    def repository(self) -> DiagnosticRepository:
        return self._repository

    # -----------------------------------------------------------------
    # A. Principal & Role Management
    # -----------------------------------------------------------------

    def _initialize_default_principals(self) -> None:
        """Initializes default local technician and system admin principals."""
        with self._lock:
            # Default technician from J-4 gets TECHNICIAN role
            if DEFAULT_USER_ID not in self._principals:
                self._principals[DEFAULT_USER_ID] = Principal(
                    user_id=DEFAULT_USER_ID,
                    roles=[Role.TECHNICIAN],
                    assigned_by="system_default",
                    metadata={"is_default_local_principal": True},
                )

    def get_principal(self, user_id: str) -> Optional[Principal]:
        """Retrieves principal by user_id."""
        with self._lock:
            # If not in cache, try fetching J-4 user to ensure existence
            if user_id not in self._principals:
                if self._user_session_manager:
                    u = self._user_session_manager.get_user(user_id)
                    if u:
                        # New user defaults to VIEWER role
                        self._principals[user_id] = Principal(
                            user_id=user_id,
                            roles=[Role.VIEWER],
                            is_active=(u.status == UserStatus.ACTIVE),
                            assigned_by="auto_provision_viewer",
                        )
            return self._principals.get(user_id)

    def assign_role(
        self,
        user_id: str,
        role: Union[Role, str],
        authorized_by: str,
        application_session_id: str = "security_admin",
    ) -> Principal:
        """
        Assigns a diagnostic role to a user.
        Requires ADMIN authority from authorized_by.
        """
        with self._lock:
            role_enum = Role(role) if isinstance(role, str) else role

            # Validate authorized_by has MANAGE_USERS permission
            if authorized_by not in ("system", "system_bootstrap", "system_default"):
                auth_principal = self.get_principal(authorized_by)
                if not auth_principal or not auth_principal.is_active:
                    raise AuthorizationDeniedError(
                        f"Assigning role requires an active administrator principal, got '{authorized_by}'.",
                        principal_id=authorized_by,
                        reason=DenialReason.UNKNOWN_USER,
                    )

                auth_perms = self._policy.get_permissions_for_roles(auth_principal.roles)
                if Permission.MANAGE_USERS not in auth_perms:
                    raise AuthorizationDeniedError(
                        f"Principal '{authorized_by}' lacks permission MANAGE_USERS to assign roles.",
                        principal_id=authorized_by,
                        reason=DenialReason.INSUFFICIENT_ROLE,
                    )

            principal = self.get_principal(user_id)
            if not principal:
                principal = Principal(user_id=user_id, roles=[role_enum], assigned_by=authorized_by)
                self._principals[user_id] = principal
            else:
                if role_enum not in principal.roles:
                    principal.roles.append(role_enum)
                principal.assigned_at = time.time()
                principal.assigned_by = authorized_by

            self._record_audit_event(
                event_type=SecurityAuditEventType.USER_ROLE_ASSIGNED,
                principal_id=authorized_by,
                application_session_id=application_session_id,
                operation="assign_role",
                resource=f"user:{user_id}",
                decision=AuthorizationDecisionStatus.ALLOW,
                reason=DenialReason.ALLOWED,
                details={"target_user": user_id, "assigned_role": role_enum.value},
            )
            logger.info("Assigned role %s to user '%s' by '%s'.", role_enum.value, user_id, authorized_by)
            return principal

    # -----------------------------------------------------------------
    # B. Core Authorization Gate
    # -----------------------------------------------------------------

    def authorize(self, context: Optional[AuthorizationContext]) -> AuthorizationDecision:
        """
        Evaluates whether an operation is permitted within the given AuthorizationContext.
        Enforces DEFAULT DENY, input validation, role checks, resource scoping,
        and session binding.
        """
        with self._lock:
            # 1. Missing context check
            if context is None:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.NO_AUTH_CONTEXT,
                    details={"error": "AuthorizationContext is None"},
                )
                self._record_decision_audit(decision, context)
                return decision

            # 2. Input validation
            if not context.user_id or not context.requested_operation or not context.resource:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.MALFORMED_INPUT,
                    principal_id=context.user_id or "unknown",
                    resource=context.resource or "unknown",
                    operation=context.requested_operation or "unknown",
                    details={"error": "Malformed or empty context fields"},
                )
                self._record_decision_audit(decision, context)
                return decision

            norm_op = context.requested_operation.strip().lower()

            # 3. Unknown operation check (Default Deny)
            required_perm = self._policy.get_permission_for_operation(norm_op)
            if not required_perm:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.UNKNOWN_OPERATION,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                    details={"operation": context.requested_operation},
                )
                self._record_decision_audit(decision, context)
                return decision

            # 4. Session invalidation check
            if context.application_session_id in self._invalidated_sessions:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.STALE_AUTHORIZATION,
                    permission_evaluated=required_perm,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                    details={"session_id": context.application_session_id, "state": "invalidated"},
                )
                self._record_decision_audit(decision, context)
                return decision

            # 5. Principal resolution and active status check
            principal = self.get_principal(context.user_id)
            if not principal:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.UNKNOWN_USER,
                    permission_evaluated=required_perm,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                )
                self._record_decision_audit(decision, context)
                return decision

            if not principal.is_active:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.INACTIVE_USER,
                    permission_evaluated=required_perm,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                )
                self._record_decision_audit(decision, context)
                return decision

            # 6. J-4 User and Active Session validation
            if self._user_session_manager:
                active_user = self._user_session_manager.active_user
                curr_sess = self._user_session_manager.current_session

                # If an active user exists, verify identity matches context
                if active_user and active_user.user_id != context.user_id:
                    decision = AuthorizationDecision(
                        status=AuthorizationDecisionStatus.DENY,
                        reason=DenialReason.SESSION_MISMATCH,
                        permission_evaluated=required_perm,
                        principal_id=context.user_id,
                        resource=context.resource,
                        operation=context.requested_operation,
                        details={"expected_user": active_user.user_id, "context_user": context.user_id},
                    )
                    self._record_decision_audit(decision, context)
                    return decision

                # If an active application session exists, verify session ID matches context
                if curr_sess and curr_sess.application_session_id != context.application_session_id:
                    decision = AuthorizationDecision(
                        status=AuthorizationDecisionStatus.DENY,
                        reason=DenialReason.SESSION_MISMATCH,
                        permission_evaluated=required_perm,
                        principal_id=context.user_id,
                        resource=context.resource,
                        operation=context.requested_operation,
                        details={
                            "expected_session": curr_sess.application_session_id,
                            "context_session": context.application_session_id,
                        },
                    )
                    self._record_decision_audit(decision, context)
                    return decision

            # 7. Resource scoping & Vehicle/ECU isolation validation
            is_valid_scope, scope_err = self._validate_resource_scope(context)
            if not is_valid_scope:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.RESOURCE_SCOPE_MISMATCH,
                    permission_evaluated=required_perm,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                    details={"error": scope_err},
                )
                self._record_decision_audit(decision, context)
                return decision

            # 8. Role and Permission resolution
            effective_roles = context.roles if context.roles is not None else principal.roles
            granted_perms = self._policy.get_permissions_for_roles(effective_roles)

            if required_perm not in granted_perms:
                decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.INSUFFICIENT_ROLE,
                    permission_evaluated=required_perm,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                    details={
                        "required_permission": required_perm.value,
                        "effective_roles": [r.value for r in effective_roles],
                    },
                )
                self._record_decision_audit(decision, context)
                return decision

            # 9. Successful Authorization ALLOW
            decision = AuthorizationDecision(
                status=AuthorizationDecisionStatus.ALLOW,
                reason=DenialReason.ALLOWED,
                permission_evaluated=required_perm,
                principal_id=context.user_id,
                resource=context.resource,
                operation=context.requested_operation,
                policy_version=self._policy.policy_version,
                details={"effective_roles": [r.value for r in effective_roles]},
            )
            self._record_decision_audit(decision, context)
            return decision

    # -----------------------------------------------------------------
    # C. Double-Gate: Security + Diagnostic Safety
    # -----------------------------------------------------------------

    def authorize_diagnostic_operation(
        self,
        context: AuthorizationContext,
        service_request: Optional[AdvancedServiceRequest] = None,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
    ) -> AuthorizationDecision:
        """
        Double-Gate Authoritative Evaluation.
        Enforces:
          Gate 1: J-5 Authorization Gate (User, Role, Permission, Resource Scope).
          Gate 2: G-1/J-1 Diagnostic Safety Gate (ServiceSafetyPolicy, Prohibited Services).
        
        Invariant: BOTH gates must pass independently. Authorization can NEVER
        override or weaken Diagnostic Safety.
        """
        # --- GATE 1: Authorization Evaluation ---
        auth_decision = self.authorize(context)
        if not auth_decision.is_allowed():
            return auth_decision

        # --- GATE 2: Diagnostic Safety Evaluation ---
        if service_request is not None:
            active_safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)
            is_safe, safety_reason = active_safety_policy.validate_request(service_request)

            if not is_safe:
                logger.warning(
                    "Safety Gate Violation: Operation '%s' authorized by J-5 but BLOCKED by Diagnostic Safety Policy: %s",
                    context.requested_operation, safety_reason
                )
                denied_decision = AuthorizationDecision(
                    status=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.SAFETY_POLICY_DENIED,
                    permission_evaluated=auth_decision.permission_evaluated,
                    principal_id=context.user_id,
                    resource=context.resource,
                    operation=context.requested_operation,
                    details={
                        "gate": "DIAGNOSTIC_SAFETY_POLICY",
                        "safety_classification": service_request.safety_classification.value,
                        "service_id": service_request.service_id,
                        "rejection_reason": safety_reason,
                    },
                )
                self._record_audit_event(
                    event_type=SecurityAuditEventType.PRIVILEGED_OPERATION_BLOCKED,
                    principal_id=context.user_id,
                    application_session_id=context.application_session_id,
                    operation=context.requested_operation,
                    resource=context.resource,
                    decision=AuthorizationDecisionStatus.DENY,
                    reason=DenialReason.SAFETY_POLICY_DENIED,
                    details={"safety_rejection": safety_reason},
                )
                return denied_decision

        # Both gates passed
        return auth_decision

    # -----------------------------------------------------------------
    # D. Untrusted AI / Reasoning Input Containment
    # -----------------------------------------------------------------

    def validate_ai_recommendation(
        self,
        recommendation: Any,
        context: AuthorizationContext,
    ) -> Tuple[bool, Optional[str], Optional[AuthorizationDecision]]:
        """
        Verifies an AI recommendation before allowing execution.
        Invariants:
          1. AI outputs are untrusted input.
          2. AI output cannot be a raw string command (e.g. Mode 04 / 2E).
          3. AI recommendation must map to a structured test candidate.
        """
        # Disallow raw hex/service commands directly from AI
        if isinstance(recommendation, str):
            clean = recommendation.strip().upper().replace(" ", "")
            # Mode 04, UDS write/programming hex patterns
            if clean in ("04", "14", "2E", "27", "2F", "34", "35", "36", "37") or clean.startswith(("2E", "2F", "34")):
                raise SecurityPolicyViolationError(
                    f"Security Violation: AI output '{recommendation}' attempted raw diagnostic command dispatch.",
                    principal_id=context.user_id,
                    operation=context.requested_operation,
                    resource=context.resource,
                    reason=DenialReason.UNTRUSTED_AI_COMMAND,
                )

        decision = self.authorize(context)
        if not decision.is_allowed():
            return False, f"AI recommendation blocked by authorization: {decision.reason.value}", decision

        return True, None, decision

    # -----------------------------------------------------------------
    # E. Session Invalidation & User Switching
    # -----------------------------------------------------------------

    def invalidate_session(self, session_id: str) -> None:
        """Marks an application session invalid, revoking any active context."""
        with self._lock:
            self._invalidated_sessions.add(session_id)
            logger.info("Security context for session '%s' invalidated.", session_id)

    def handle_user_switched(self, previous_user_id: str, new_user_id: str, session_id: str) -> None:
        """
        Called on J-4 user switch: invalidates prior user's contextual grants
        to ensure no silent transfer of privileges occurs.
        """
        with self._lock:
            self.invalidate_session(session_id)
            self._record_audit_event(
                event_type=SecurityAuditEventType.SECURITY_POLICY_CHANGED,
                principal_id=new_user_id,
                application_session_id=session_id,
                operation="user_switch_invalidation",
                resource=f"session:{session_id}",
                decision=AuthorizationDecisionStatus.ALLOW,
                reason=DenialReason.ALLOWED,
                details={"previous_user": previous_user_id, "new_user": new_user_id},
            )

    # -----------------------------------------------------------------
    # F. Resource Scope Validation
    # -----------------------------------------------------------------

    def _validate_resource_scope(self, context: AuthorizationContext) -> Tuple[bool, Optional[str]]:
        """
        Enforces vehicle and ECU isolation.
        Ensures permissions for vehicle A cannot be executed on vehicle B.
        """
        res = context.resource
        if res.startswith("vehicle:"):
            target_vin = res.split(":", 1)[1].strip()
            if context.vehicle_id and context.vehicle_id != target_vin:
                return False, f"Context vehicle_id '{context.vehicle_id}' does not match resource '{target_vin}'"

        elif res.startswith("ecu:"):
            target_ecu = res.split(":", 1)[1].strip()
            if context.ecu_id and context.ecu_id != target_ecu:
                return False, f"Context ecu_id '{context.ecu_id}' does not match resource '{target_ecu}'"

        elif res.startswith("session:"):
            target_sess = res.split(":", 1)[1].strip()
            if context.diagnostic_session_id and context.diagnostic_session_id != target_sess:
                return False, f"Context diagnostic_session_id '{context.diagnostic_session_id}' does not match resource '{target_sess}'"

        return True, None

    # -----------------------------------------------------------------
    # G. Security Audit Trail Persistence
    # -----------------------------------------------------------------

    def _record_decision_audit(
        self,
        decision: AuthorizationDecision,
        context: Optional[AuthorizationContext],
    ) -> None:
        """Emits an audit event for every authorization decision."""
        sess_id = context.application_session_id if context else "no_session"
        event_type = (
            SecurityAuditEventType.AUTHORIZATION_ALLOWED
            if decision.is_allowed()
            else SecurityAuditEventType.AUTHORIZATION_DENIED
        )
        self._record_audit_event(
            event_type=event_type,
            principal_id=decision.principal_id,
            application_session_id=sess_id,
            operation=decision.operation,
            resource=decision.resource,
            decision=decision.status,
            reason=decision.reason,
            details=decision.details,
        )

    def _record_audit_event(
        self,
        event_type: SecurityAuditEventType,
        principal_id: str,
        application_session_id: str,
        operation: str,
        resource: str,
        decision: AuthorizationDecisionStatus,
        reason: DenialReason,
        details: Dict[str, Any],
    ) -> SecurityAuditEvent:
        """Internal writer to persist SecurityAuditEvent via J-3 repository."""
        event = SecurityAuditEvent(
            event_id=f"sec_audit_{uuid.uuid4().hex[:10]}",
            event_type=event_type,
            principal_id=principal_id,
            application_session_id=application_session_id,
            operation=operation,
            resource=resource,
            decision=decision,
            reason=reason,
            timestamp=time.time(),
            details=details,
        )
        try:
            self._repository.save_security_audit_event(event)
        except Exception as e:
            logger.warning("Failed to persist security audit event %s: %s", event_type.value, e)
        return event
