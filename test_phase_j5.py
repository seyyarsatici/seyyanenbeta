#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-5 Test Suite
==============================================================
Test Suite for Security & Permissions Architecture
`test_phase_j5.py`

Covers Sections A through AG:
A. Permission model
B. Role model
C. Default deny
D. Unknown permission
E. Unknown operation
F. Unknown user
G. Missing authorization context
H. Allowed read-only operation
I. Denied privileged operation
J. Role/permission mapping
K. Resource scoping
L. Vehicle/ECU isolation
M. Session binding
N. User switching invalidation
O. Restart/recovery authorization
P. Audit events
Q. Denial reasons
R. Safety + authorization double gate
S. Safety denial despite authorization
T. Authorization denial before transport
U. AI recommendation cannot execute directly
V. H-5 cannot self-elevate
W. H-2 integration
X. G-1 integration
Y. J-1 integration
Z. J-4 integration
AA. J-3 persistence integration
AB. Secret leakage tests
AC. Malformed authorization input
AD. Policy version handling
AE. Policy change authorization
AF. Concurrent application sessions
AG. Full cross-layer regression & invariants
"""

import copy
import json
import logging
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

# J-1 Adapter & VCI Abstraction
from diagnostic_adapter import (
    MockDiagnosticAdapter,
    DiagnosticProtocol,
    PROHIBITED_SERVICES,
)

# J-2 Platform Abstraction
from platform_abstraction import PlatformManager, SimulatedPlatformProvider, OSFamily

# J-3 Persistence Architecture
from diagnostic_persistence import (
    DiagnosticRepository,
    DiagnosticSessionRecord,
    InMemoryPersistenceBackend,
    SQLitePersistenceBackend,
    PersistenceManager,
)

# J-4 User & Session Management
from user_session_manager import (
    ApplicationUser,
    ApplicationSession,
    UserStatus,
    UserSessionManager,
    DEFAULT_USER_ID,
)

# G-1 Advanced ECU Services & Safety
from advanced_ecu_services import (
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    AdvancedServiceRequest,
)

# J-5 Security & Permissions
from diagnostic_security import (
    Role,
    Permission,
    OperationCategory,
    AuthorizationDecisionStatus,
    DenialReason,
    SecurityAuditEventType,
    Principal,
    AuthorizationContext,
    AuthorizationDecision,
    SecurityAuditEvent,
    SecurityPolicy,
    SecurityManager,
    SecurityError,
    AuthorizationDeniedError,
    InvalidSecurityContextError,
    SecurityPolicyViolationError,
    CURRENT_J5_SECURITY_POLICY_VERSION,
)


class TestPhaseJ5SecurityAndPermissions(unittest.TestCase):

    def setUp(self):
        # Isolated in-memory repository for deterministic testing
        self.repo = PersistenceManager.create_in_memory_repository()
        self.user_manager = UserSessionManager(repository=self.repo)
        self.security_manager = SecurityManager(
            repository=self.repo,
            user_session_manager=self.user_manager,
        )

    def tearDown(self):
        if self.user_manager.current_session:
            try:
                self.user_manager.close_application_session(force=True)
            except Exception:
                pass
        self.repo.close()

    # =================================================================
    # Section A: Permission Model
    # =================================================================
    def test_section_a_permission_model(self):
        perms = list(Permission)
        self.assertIn(Permission.READ_DTC, perms)
        self.assertIn(Permission.READ_LIVE_DATA, perms)
        self.assertIn(Permission.CLEAR_DTC, perms)
        self.assertIn(Permission.RUN_ACTUATOR_TEST, perms)
        self.assertIn(Permission.MANAGE_USERS, perms)
        self.assertIn(Permission.MANAGE_SECURITY_POLICY, perms)

        # Verify operation to permission mapping
        policy = self.security_manager.policy
        self.assertEqual(policy.get_permission_for_operation("read_dtc"), Permission.READ_DTC)
        self.assertEqual(policy.get_permission_for_operation("clear_dtc"), Permission.CLEAR_DTC)
        self.assertEqual(policy.get_permission_for_operation("manage_users"), Permission.MANAGE_USERS)

    # =================================================================
    # Section B: Role Model
    # =================================================================
    def test_section_b_role_model(self):
        roles = list(Role)
        self.assertEqual(len(roles), 4)
        self.assertIn(Role.VIEWER, roles)
        self.assertIn(Role.TECHNICIAN, roles)
        self.assertIn(Role.ADVANCED_TECHNICIAN, roles)
        self.assertIn(Role.ADMIN, roles)

    # =================================================================
    # Section C: Default Deny
    # =================================================================
    def test_section_c_default_deny_enforced(self):
        # An unregistered or unknown operation must default to DENY
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id="appsess_001",
            requested_operation="unregistered_bypass_op",
            resource="app:diagnostics",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.status, AuthorizationDecisionStatus.DENY)
        self.assertEqual(decision.reason, DenialReason.UNKNOWN_OPERATION)

    # =================================================================
    # Section D: Unknown Permission
    # =================================================================
    def test_section_d_unknown_permission(self):
        # If policy has no permission mapped for an operation, deny
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id="appsess_001",
            requested_operation="hack_ecu_firmware",
            resource="ecu:ECM",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.UNKNOWN_OPERATION)

    # =================================================================
    # Section E: Unknown Operation
    # =================================================================
    def test_section_e_unknown_operation(self):
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id="appsess_001",
            requested_operation="arbitrary_cmd_99",
            resource="vehicle:VIN1",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertEqual(decision.status, AuthorizationDecisionStatus.DENY)
        self.assertEqual(decision.reason, DenialReason.UNKNOWN_OPERATION)

    # =================================================================
    # Section F: Unknown User
    # =================================================================
    def test_section_f_unknown_user(self):
        # A user ID not registered in J-4 or J-5 must be denied
        ctx = AuthorizationContext(
            user_id="ghost_user_404",
            application_session_id="appsess_001",
            requested_operation="read_dtc",
            resource="vehicle:VIN1",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.UNKNOWN_USER)

    # =================================================================
    # Section G: Missing Authorization Context
    # =================================================================
    def test_section_g_missing_authorization_context(self):
        decision = self.security_manager.authorize(None)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.status, AuthorizationDecisionStatus.DENY)
        self.assertEqual(decision.reason, DenialReason.NO_AUTH_CONTEXT)

    # =================================================================
    # Section H: Allowed Read-Only Operation
    # =================================================================
    def test_section_h_allowed_read_only_operation(self):
        # VIEWER role can read DTC and read live data
        viewer_u = self.user_manager.create_user(display_name="Observer Olivia", user_id="olivia")
        self.user_manager.select_active_user("olivia")
        app_sess = self.user_manager.start_application_session()

        ctx = AuthorizationContext(
            user_id="olivia",
            application_session_id=app_sess.application_session_id,
            requested_operation="read_dtc",
            resource="vehicle:VIN_AUDI",
            vehicle_id="VIN_AUDI",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertTrue(decision.is_allowed())
        self.assertEqual(decision.status, AuthorizationDecisionStatus.ALLOW)
        self.assertEqual(decision.reason, DenialReason.ALLOWED)
        self.assertEqual(decision.permission_evaluated, Permission.READ_DTC)

    # =================================================================
    # Section I: Denied Privileged Operation for Insufficient Role
    # =================================================================
    def test_section_i_denied_privileged_operation(self):
        # VIEWER attempting clear_dtc or run_actuator_test must be DENIED
        viewer_u = self.user_manager.create_user(display_name="Guest Gary", user_id="gary")
        self.user_manager.select_active_user("gary")
        app_sess = self.user_manager.start_application_session()

        ctx = AuthorizationContext(
            user_id="gary",
            application_session_id=app_sess.application_session_id,
            requested_operation="clear_dtc",
            resource="vehicle:VIN_FORD",
            vehicle_id="VIN_FORD",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.status, AuthorizationDecisionStatus.DENY)
        self.assertEqual(decision.reason, DenialReason.INSUFFICIENT_ROLE)

    # =================================================================
    # Section J: Role/Permission Mapping
    # =================================================================
    def test_section_j_role_permission_mapping(self):
        # 1. TECHNICIAN can start diagnostic session and run guided test, but CANNOT manage users
        tech_u = self.user_manager.create_user(display_name="Tech Tom", user_id="tom")
        # System admin bootstraps Tom as TECHNICIAN
        self.security_manager.assign_role("tom", Role.TECHNICIAN, authorized_by="system_bootstrap")
        self.user_manager.select_active_user("tom")
        app_sess = self.user_manager.start_application_session()

        # Start session -> ALLOW
        ctx_sess = AuthorizationContext(
            user_id="tom",
            application_session_id=app_sess.application_session_id,
            requested_operation="start_diagnostic_session",
            resource="app:diagnostics",
        )
        self.assertTrue(self.security_manager.authorize(ctx_sess).is_allowed())

        # Manage users -> DENY (Requires ADMIN)
        ctx_admin = AuthorizationContext(
            user_id="tom",
            application_session_id=app_sess.application_session_id,
            requested_operation="manage_users",
            resource="app:security",
        )
        d_admin = self.security_manager.authorize(ctx_admin)
        self.assertFalse(d_admin.is_allowed())
        self.assertEqual(d_admin.reason, DenialReason.INSUFFICIENT_ROLE)

        # 2. Promote to ADMIN
        self.security_manager.assign_role("tom", Role.ADMIN, authorized_by="system_bootstrap")
        self.assertTrue(self.security_manager.authorize(ctx_admin).is_allowed())

    # =================================================================
    # Section K: Resource Scoping
    # =================================================================
    def test_section_k_resource_scoping(self):
        app_sess = self.user_manager.start_application_session()

        # Resource requires vehicle WAUZZZ123, but context supplies WAUZZZ999 -> MISMATCH
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="read_live_data",
            resource="vehicle:WAUZZZ123",
            vehicle_id="WAUZZZ999",  # Cross-vehicle mismatch!
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.RESOURCE_SCOPE_MISMATCH)

        # Matching vehicle -> ALLOW
        ctx_valid = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="read_live_data",
            resource="vehicle:WAUZZZ123",
            vehicle_id="WAUZZZ123",
        )
        self.assertTrue(self.security_manager.authorize(ctx_valid).is_allowed())

    # =================================================================
    # Section L: Vehicle/ECU Isolation
    # =================================================================
    def test_section_l_ecu_isolation(self):
        app_sess = self.user_manager.start_application_session()

        # Target resource is TCM, but context has ECM -> MISMATCH
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="read_dtc",
            resource="ecu:TCM",
            ecu_id="ECM",  # Cross-ECU mismatch!
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.RESOURCE_SCOPE_MISMATCH)

    # =================================================================
    # Section M: Session Binding
    # =================================================================
    def test_section_m_session_binding(self):
        app_sess = self.user_manager.start_application_session()

        # Context has mismatched application_session_id
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id="fake_foreign_session_id",
            requested_operation="read_dtc",
            resource="app:diagnostics",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.SESSION_MISMATCH)

    # =================================================================
    # Section N: User Switching Invalidation
    # =================================================================
    def test_section_n_user_switching_invalidation(self):
        u1 = self.user_manager.create_user(display_name="User One", user_id="user_1")
        u2 = self.user_manager.create_user(display_name="User Two", user_id="user_2")

        self.user_manager.select_active_user("user_1")
        app_sess = self.user_manager.start_application_session()

        # Explicitly hook security manager to user switch
        self.security_manager.handle_user_switched("user_1", "user_2", app_sess.application_session_id)

        # Attempt to authorize using the old invalidated session context
        ctx = AuthorizationContext(
            user_id="user_1",
            application_session_id=app_sess.application_session_id,
            requested_operation="read_dtc",
            resource="app:diagnostics",
        )
        decision = self.security_manager.authorize(ctx)
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.STALE_AUTHORIZATION)

    # =================================================================
    # Section O: Restart/Recovery Authorization
    # =================================================================
    def test_section_o_restart_recovery_requires_fresh_authorization(self):
        # Persisted state from prior sessions does not grant permanent privileged authorization
        # Fresh security manager instance simulating process restart
        fresh_sec_mgr = SecurityManager(repository=self.repo, user_session_manager=self.user_manager)

        # Re-attempting privileged operation requires active session and context
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id="old_recovered_session_id",
            requested_operation="clear_dtc",
            resource="vehicle:VIN1",
            vehicle_id="VIN1",
        )
        decision = fresh_sec_mgr.authorize(ctx)
        # Default technician role is TECHNICIAN, not ADVANCED_TECHNICIAN, so clear_dtc is DENIED
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.reason, DenialReason.INSUFFICIENT_ROLE)

    # =================================================================
    # Section P: Security Audit Events
    # =================================================================
    def test_section_p_security_audit_events_persisted(self):
        app_sess = self.user_manager.start_application_session()

        ctx_allow = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="read_dtc",
            resource="vehicle:VIN1",
            vehicle_id="VIN1",
        )
        self.security_manager.authorize(ctx_allow)

        ctx_deny = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="clear_dtc",
            resource="vehicle:VIN1",
            vehicle_id="VIN1",
        )
        self.security_manager.authorize(ctx_deny)

        events = self.repo.list_security_audit_events()
        event_types = [e["event_type"] for e in events]
        self.assertIn(SecurityAuditEventType.AUTHORIZATION_ALLOWED.value, event_types)
        self.assertIn(SecurityAuditEventType.AUTHORIZATION_DENIED.value, event_types)

    # =================================================================
    # Section Q: Granular Denial Reasons
    # =================================================================
    def test_section_q_granular_denial_reasons(self):
        # 1. NO_AUTH_CONTEXT
        self.assertEqual(self.security_manager.authorize(None).reason, DenialReason.NO_AUTH_CONTEXT)

        # 2. UNKNOWN_OPERATION
        ctx_op = AuthorizationContext(user_id=DEFAULT_USER_ID, application_session_id="s1", requested_operation="xyz", resource="r1")
        self.assertEqual(self.security_manager.authorize(ctx_op).reason, DenialReason.UNKNOWN_OPERATION)

        # 3. UNKNOWN_USER
        ctx_u = AuthorizationContext(user_id="nobody", application_session_id="s1", requested_operation="read_dtc", resource="r1")
        self.assertEqual(self.security_manager.authorize(ctx_u).reason, DenialReason.UNKNOWN_USER)

    # =================================================================
    # Section R: Double Gate: Security + Diagnostic Safety (Both Pass)
    # =================================================================
    def test_section_r_double_gate_allowed(self):
        app_sess = self.user_manager.start_application_session()

        # Advanced technician requesting advanced read service (e.g. Mode 22 DID read)
        self.security_manager.assign_role(DEFAULT_USER_ID, Role.ADVANCED_TECHNICIAN, authorized_by="system_bootstrap")

        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="run_advanced_service",
            resource="vehicle:VIN_CAN",
            vehicle_id="VIN_CAN",
        )

        req = AdvancedServiceRequest(
            service_id="22",
            payload="1640",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )

        safety_policy = ServiceSafetyPolicy(allow_non_readonly=False)
        decision = self.security_manager.authorize_diagnostic_operation(
            context=ctx,
            service_request=req,
            safety_policy=safety_policy,
        )
        self.assertTrue(decision.is_allowed())
        self.assertEqual(decision.status, AuthorizationDecisionStatus.ALLOW)

    # =================================================================
    # Section S: Safety Denial Despite Authorization Approval
    # =================================================================
    def test_section_s_safety_denial_despite_authorization(self):
        # Advanced technician is authorized by J-5 for CLEAR_DTC / Mode 04,
        # BUT G-1 ServiceSafetyPolicy strictly blocks destructive Mode 04!
        app_sess = self.user_manager.start_application_session()
        self.security_manager.assign_role(DEFAULT_USER_ID, Role.ADVANCED_TECHNICIAN, authorized_by="system_bootstrap")

        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="clear_dtc",
            resource="vehicle:VIN_VW",
            vehicle_id="VIN_VW",
        )

        destructive_req = AdvancedServiceRequest(
            service_id="04",  # Prohibited service!
            safety_classification=ServiceSafetyClassification.BLOCKED,
        )

        safety_policy = ServiceSafetyPolicy(allow_non_readonly=False)
        decision = self.security_manager.authorize_diagnostic_operation(
            context=ctx,
            service_request=destructive_req,
            safety_policy=safety_policy,
        )

        # Must be BLOCKED by safety gate despite technician role!
        self.assertFalse(decision.is_allowed())
        self.assertEqual(decision.status, AuthorizationDecisionStatus.DENY)
        self.assertEqual(decision.reason, DenialReason.SAFETY_POLICY_DENIED)
        self.assertIn("strictly prohibited", decision.details.get("rejection_reason", ""))

    # =================================================================
    # Section T: Authorization Denial Blocks Operation Before Transport
    # =================================================================
    def test_section_t_authorization_denial_blocks_before_transport(self):
        app_sess = self.user_manager.start_application_session()
        # VIEWER attempts an actuation test
        viewer_ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="run_actuator_test",
            resource="ecu:ECM",
            ecu_id="ECM",
            roles=[Role.VIEWER],  # Viewer role
        )

        # Adapter mock
        mock_adapter = MockDiagnosticAdapter(responses={"0100": "41 00 BE 3E B8 11"})
        mock_adapter.connect()

        # Gate check fails BEFORE send_command
        decision = self.security_manager.authorize(viewer_ctx)
        self.assertFalse(decision.is_allowed())

        # Enforce that no adapter send_command occurs
        if not decision.is_allowed():
            # Operation was blocked before transport
            pass
        else:
            mock_adapter.send_command("2F 01 03")

        # Mock adapter history must remain empty
        self.assertEqual(len(mock_adapter._history), 0)
        mock_adapter.disconnect()

    # =================================================================
    # Section U: Untrusted AI Recommendation Containment
    # =================================================================
    def test_section_u_untrusted_ai_recommendation_containment(self):
        app_sess = self.user_manager.start_application_session()
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="run_guided_test",
            resource="app:diagnostics",
        )

        # AI hallucinating or outputting a raw destructive command (e.g. Mode 04 / 2E / 34)
        malicious_ai_output = "04"
        with self.assertRaises(SecurityPolicyViolationError):
            self.security_manager.validate_ai_recommendation(malicious_ai_output, ctx)

        malicious_write = "2E 11 22 33"
        with self.assertRaises(SecurityPolicyViolationError):
            self.security_manager.validate_ai_recommendation(malicious_write, ctx)

    # =================================================================
    # Section V: Automated Workflow Cannot Self-Elevate
    # =================================================================
    def test_section_v_workflow_cannot_self_elevate(self):
        app_sess = self.user_manager.start_application_session()

        # Workflow executing under TECHNICIAN authority attempts to assign itself ADMIN role
        with self.assertRaises(AuthorizationDeniedError):
            self.security_manager.assign_role(
                user_id="workflow_runner",
                role=Role.ADMIN,
                authorized_by=DEFAULT_USER_ID,  # Default tech lacks MANAGE_USERS permission
            )

    # =================================================================
    # Section W: H-2 Test Sequencer Safety Integration
    # =================================================================
    def test_section_w_test_sequencer_authorization_check(self):
        app_sess = self.user_manager.start_application_session()
        # Guided test is permitted for TECHNICIAN
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="run_guided_test",
            resource="app:diagnostics",
        )
        self.assertTrue(self.security_manager.authorize(ctx).is_allowed())

    # =================================================================
    # Section X: G-1 Advanced ECU Services Safety Policy Integration
    # =================================================================
    def test_section_x_g1_advanced_services_integration(self):
        # Ensure G-1 ServiceSafetyPolicy works seamlessly with J-5
        policy = ServiceSafetyPolicy(allow_non_readonly=False)
        req_safe = AdvancedServiceRequest(service_id="22", payload="0100")
        is_ok, err = policy.validate_request(req_safe)
        self.assertTrue(is_ok)

        req_unsafe = AdvancedServiceRequest(service_id="2E", payload="0100AA")
        is_ok, err = policy.validate_request(req_unsafe)
        self.assertFalse(is_ok)

    # =================================================================
    # Section Y: J-1 Diagnostic Adapter Gating Integration
    # =================================================================
    def test_section_y_j1_adapter_gating_integration(self):
        # Direct attempt to send prohibited command via adapter fails closed
        adapter = MockDiagnosticAdapter()
        adapter.connect()
        from motor import STATUS_NRC
        for bad_sid in ("04", "14", "2E", "27", "2F", "34", "35", "36", "37", "3D"):
            res, status = adapter.send_command(f"{bad_sid} 01 02")
            self.assertEqual(res, [])
            self.assertEqual(status, STATUS_NRC)
        adapter.disconnect()

    # =================================================================
    # Section Z: J-4 User and Session Manager Integration
    # =================================================================
    def test_section_z_j4_integration(self):
        # User created in J-4 resolves automatically in J-5
        new_u = self.user_manager.create_user(display_name="Engineer Eric", user_id="eric")
        principal = self.security_manager.get_principal("eric")
        self.assertIsNotNone(principal)
        self.assertEqual(principal.user_id, "eric")
        self.assertIn(Role.VIEWER, principal.roles)

    # =================================================================
    # Section AA: J-3 Persistence Integration
    # =================================================================
    def test_section_aa_j3_persistence_roundtrip(self):
        # Save and query security audit event
        event = SecurityAuditEvent(
            event_id="sec_evt_101",
            event_type=SecurityAuditEventType.AUTHORIZATION_ALLOWED,
            principal_id="tech_01",
            application_session_id="appsess_01",
            operation="read_dtc",
            resource="vehicle:VIN1",
            decision=AuthorizationDecisionStatus.ALLOW,
            reason=DenialReason.ALLOWED,
        )
        eid = self.repo.save_security_audit_event(event)
        self.assertEqual(eid, "sec_evt_101")

        listed = self.repo.list_security_audit_events(principal_id="tech_01")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["event_id"], "sec_evt_101")
        self.assertEqual(listed[0]["decision"], "ALLOW")

    # =================================================================
    # Section AB: Secret Leakage Tests
    # =================================================================
    def test_section_ab_zero_secret_leakage(self):
        # Verify no secret keywords in serialized decision or audit event
        decision = AuthorizationDecision(
            status=AuthorizationDecisionStatus.DENY,
            reason=DenialReason.INSUFFICIENT_ROLE,
            principal_id="user_test",
            resource="res",
            operation="op",
        )
        dec_json = json.dumps(decision.to_dict())
        for secret_word in ("password", "secret", "private_key", "token", "api_key"):
            self.assertNotIn(secret_word, dec_json)

    # =================================================================
    # Section AC: Malformed Authorization Input
    # =================================================================
    def test_section_ac_malformed_authorization_input(self):
        with self.assertRaises(InvalidSecurityContextError):
            AuthorizationContext(user_id="", application_session_id="s1", requested_operation="op", resource="r")

        with self.assertRaises(InvalidSecurityContextError):
            AuthorizationContext(user_id="u", application_session_id="", requested_operation="op", resource="r")

        with self.assertRaises(InvalidSecurityContextError):
            AuthorizationContext(user_id="u", application_session_id="s", requested_operation="", resource="r")

    # =================================================================
    # Section AD: Policy Version Handling
    # =================================================================
    def test_section_ad_policy_version_handling(self):
        policy = self.security_manager.policy
        self.assertEqual(policy.policy_version, CURRENT_J5_SECURITY_POLICY_VERSION)

        app_sess = self.user_manager.start_application_session()
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="read_dtc",
            resource="app:diagnostics",
        )
        dec = self.security_manager.authorize(ctx)
        self.assertEqual(dec.policy_version, CURRENT_J5_SECURITY_POLICY_VERSION)

    # =================================================================
    # Section AE: Policy Change Authorization
    # =================================================================
    def test_section_ae_policy_change_authorization(self):
        # Technician attempting to assign roles is rejected
        tech_user = self.user_manager.create_user(display_name="Tech Only", user_id="tech_only")
        with self.assertRaises(AuthorizationDeniedError):
            self.security_manager.assign_role("tech_only", Role.ADMIN, authorized_by="tech_only")

    # =================================================================
    # Section AF: Concurrent Application Sessions
    # =================================================================
    def test_section_af_concurrent_application_sessions(self):
        # Two independent managers maintain isolated sessions
        mgr1 = UserSessionManager(repository=self.repo)
        mgr2 = UserSessionManager(repository=self.repo)

        s1 = mgr1.start_application_session()
        s2 = mgr2.start_application_session()

        sec_mgr1 = SecurityManager(repository=self.repo, user_session_manager=mgr1)
        sec_mgr2 = SecurityManager(repository=self.repo, user_session_manager=mgr2)

        ctx1 = AuthorizationContext(user_id=DEFAULT_USER_ID, application_session_id=s1.application_session_id, requested_operation="read_dtc", resource="app:diag")
        ctx2 = AuthorizationContext(user_id=DEFAULT_USER_ID, application_session_id=s2.application_session_id, requested_operation="read_dtc", resource="app:diag")

        self.assertTrue(sec_mgr1.authorize(ctx1).is_allowed())
        self.assertTrue(sec_mgr2.authorize(ctx2).is_allowed())

        # Cross-session usage is rejected
        ctx_cross = AuthorizationContext(user_id=DEFAULT_USER_ID, application_session_id=s2.application_session_id, requested_operation="read_dtc", resource="app:diag")
        self.assertFalse(sec_mgr1.authorize(ctx_cross).is_allowed())

        mgr1.close_application_session()
        mgr2.close_application_session()

    # =================================================================
    # Section AG: Cross-Layer Invariants
    # =================================================================
    def test_section_ag_cross_layer_invariants(self):
        # 1. Security failure != Component fault
        sec_err = SecurityError("Access Denied")
        self.assertTrue(sec_err.is_security_error)
        self.assertFalse(sec_err.is_communication_failure)
        self.assertFalse(sec_err.is_diagnostic_fault)

        # 2. Authorization cannot weaken diagnostic safety
        # Even ADMIN cannot run prohibited service 0x04
        self.security_manager.assign_role(DEFAULT_USER_ID, Role.ADMIN, authorized_by="system_bootstrap")
        app_sess = self.user_manager.start_application_session()

        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="clear_dtc",
            resource="vehicle:VIN_X",
            vehicle_id="VIN_X",
        )
        req = AdvancedServiceRequest(service_id="04")
        dec = self.security_manager.authorize_diagnostic_operation(
            context=ctx,
            service_request=req,
            safety_policy=ServiceSafetyPolicy(allow_non_readonly=False),
        )
        self.assertFalse(dec.is_allowed())
        self.assertEqual(dec.reason, DenialReason.SAFETY_POLICY_DENIED)


if __name__ == "__main__":
    unittest.main()
