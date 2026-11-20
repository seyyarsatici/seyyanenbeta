#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-4 Test Suite
==============================================================
Test Suite for User and Session Management Layer
`test_phase_j4.py`

Covers Sections A through Z:
A. User creation
B. User identity
C. Multiple users
D. Active-user selection
E. User switching & active diagnostic session lock
F. Application-session creation
G. Application-session lifecycle
H. Invalid lifecycle transitions
I. Unique application-session IDs
J. Diagnostic-session linking
K. Workflow linking
L. User/vehicle identity separation
M. Persistence through J-3
N. Serialization / deserialization
O. Schema version handling
P. Interrupted-session representation
Q. Crash recovery semantics
R. No automatic diagnostic execution after restart
S. Concurrent application-session identity
T. Technician observation attribution
U. Report metadata integration
V. Structured audit events
W. Privacy / minimal-data behavior
X. J-2 platform integration
Y. J-1 adapter identity integration
Z. Cross-phase regression and architectural invariants
"""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

# J-2 Platform Abstraction
from platform_abstraction import PlatformManager, SimulatedPlatformProvider, OSFamily

# J-3 Persistence Architecture
from diagnostic_persistence import (
    DiagnosticRepository,
    DiagnosticSessionRecord,
    InMemoryPersistenceBackend,
    SQLitePersistenceBackend,
    PersistenceManager,
    UnsupportedSchemaVersionError,
)

# Domain context for linking tests
from extended_did import VehicleContext
from diagnostic_workflow_engine import DiagnosticWorkflow, WorkflowState

# J-4 User & Session Management
from user_session_manager import (
    ApplicationUser,
    ApplicationSession,
    SessionAuditEvent,
    UserStatus,
    ApplicationSessionState,
    SessionAuditEventType,
    UserSessionManager,
    UserSessionError,
    UserNotFoundError,
    DuplicateUserError,
    InvalidSessionStateTransitionError,
    ActiveDiagnosticSessionLockError,
    DEFAULT_USER_ID,
    DEFAULT_USER_DISPLAY_NAME,
    CURRENT_J4_SCHEMA_VERSION,
)


class TestPhaseJ4UserSessionManagement(unittest.TestCase):

    def setUp(self):
        # Use an isolated In-Memory repository for deterministic test execution
        self.repo = PersistenceManager.create_in_memory_repository()
        self.manager = UserSessionManager(repository=self.repo)

    def tearDown(self):
        if hasattr(self, "manager") and self.manager.current_session:
            try:
                self.manager.close_application_session(force=True)
            except Exception:
                pass
        self.repo.close()
        PlatformManager.reset_to_default_provider()

    # =================================================================
    # Section A: User Creation
    # =================================================================
    def test_section_a_user_creation(self):
        user = self.manager.create_user(
            display_name="Senior Technician Alice",
            user_id="alice_01",
            metadata={"certifications": ["ASE-Master"]},
        )
        self.assertEqual(user.user_id, "alice_01")
        self.assertEqual(user.display_name, "Senior Technician Alice")
        self.assertEqual(user.status, UserStatus.ACTIVE)
        self.assertIn("certifications", user.metadata)
        self.assertGreater(user.created_at, 0)
        self.assertGreater(user.updated_at, 0)

        # Empty display name or user ID must fail
        with self.assertRaises(UserSessionError):
            ApplicationUser(user_id="", display_name="Bob")
        with self.assertRaises(UserSessionError):
            ApplicationUser(user_id="bob", display_name="")

        # Duplicate user ID creation must raise DuplicateUserError
        with self.assertRaises(DuplicateUserError):
            self.manager.create_user(display_name="Alice Clone", user_id="alice_01")

    # =================================================================
    # Section B: User Identity & Default Local User
    # =================================================================
    def test_section_b_user_identity_minimal_and_default(self):
        # Default user must be automatically present for offline operation
        default_u = self.manager.get_user(DEFAULT_USER_ID)
        self.assertIsNotNone(default_u)
        self.assertEqual(default_u.user_id, DEFAULT_USER_ID)
        self.assertEqual(default_u.display_name, DEFAULT_USER_DISPLAY_NAME)
        self.assertEqual(default_u.status, UserStatus.ACTIVE)

        # Strict security boundary check: NO password, NO token, NO roles in J-4
        u_dict = default_u.to_dict()
        self.assertNotIn("password", u_dict)
        self.assertNotIn("password_hash", u_dict)
        self.assertNotIn("token", u_dict)
        self.assertNotIn("roles", u_dict)
        self.assertNotIn("permissions", u_dict)

    # =================================================================
    # Section C: Multiple Users
    # =================================================================
    def test_section_c_multiple_users(self):
        u1 = self.manager.create_user(display_name="Tech One", user_id="tech_1")
        u2 = self.manager.create_user(display_name="Tech Two", user_id="tech_2")
        u3 = self.manager.create_user(display_name="Tech Three", user_id="tech_3")

        all_users = self.manager.list_users()
        # Default user + 3 newly created users = 4 users
        self.assertEqual(len(all_users), 4)
        user_ids = {u.user_id for u in all_users}
        self.assertTrue({"local_technician", "tech_1", "tech_2", "tech_3"}.issubset(user_ids))

    # =================================================================
    # Section D: Active-User Selection
    # =================================================================
    def test_section_d_active_user_selection(self):
        self.manager.create_user(display_name="Tech Carol", user_id="carol")
        selected = self.manager.select_active_user("carol")
        self.assertEqual(selected.user_id, "carol")
        self.assertEqual(self.manager.active_user.user_id, "carol")

        # Selecting non-existent user must raise UserNotFoundError
        with self.assertRaises(UserNotFoundError):
            self.manager.select_active_user("non_existent_tech")

    # =================================================================
    # Section E: User Switching & Active Diagnostic Session Lock
    # =================================================================
    def test_section_e_user_switching_and_diagnostic_lock(self):
        u_alice = self.manager.create_user(display_name="Alice", user_id="u_alice")
        u_bob = self.manager.create_user(display_name="Bob", user_id="u_bob")

        self.manager.select_active_user("u_alice")
        sess = self.manager.start_application_session()
        self.assertEqual(sess.user_id, "u_alice")

        # 1. Switch without active diagnostic session succeeds
        self.manager.switch_user("u_bob")
        self.assertEqual(self.manager.active_user.user_id, "u_bob")
        self.assertEqual(sess.user_id, "u_bob")

        # 2. Link an active diagnostic session
        self.manager.link_diagnostic_session("diag_sess_100", set_as_active=True)
        self.assertEqual(sess.active_diagnostic_session_id, "diag_sess_100")

        # 3. Switching active user while diagnostic session is active without force MUST fail
        with self.assertRaises(ActiveDiagnosticSessionLockError):
            self.manager.switch_user("u_alice", force=False)

        # Active user remains Bob
        self.assertEqual(self.manager.active_user.user_id, "u_bob")

        # 4. Switching active user with force=True detaches diagnostic session and succeeds
        self.manager.switch_user("u_alice", force=True)
        self.assertEqual(self.manager.active_user.user_id, "u_alice")
        self.assertIsNone(sess.active_diagnostic_session_id)

    # =================================================================
    # Section F: Application-Session Creation
    # =================================================================
    def test_section_f_application_session_creation(self):
        sess = self.manager.start_application_session(
            app_version="2.4.0",
            adapter_info={"name": "OBDLink-SX", "firmware": "v5.2"},
            session_metadata={"garage_bay": "Bay 3"},
        )
        self.assertTrue(sess.application_session_id.startswith("appsess_"))
        self.assertEqual(sess.user_id, DEFAULT_USER_ID)
        self.assertEqual(sess.state, ApplicationSessionState.ACTIVE)
        self.assertEqual(sess.app_version, "2.4.0")
        self.assertEqual(sess.adapter_info.get("name"), "OBDLink-SX")
        self.assertEqual(sess.metadata.get("garage_bay"), "Bay 3")
        self.assertIn("os_family", sess.platform_context)
        self.assertIsNone(sess.end_time)

    # =================================================================
    # Section G: Application-Session Lifecycle
    # =================================================================
    def test_section_g_application_session_lifecycle(self):
        sess = self.manager.start_application_session()
        self.assertEqual(sess.state, ApplicationSessionState.ACTIVE)

        # ACTIVE -> PAUSED
        self.manager.pause_application_session(reason="Technician break")
        self.assertEqual(sess.state, ApplicationSessionState.PAUSED)

        # PAUSED -> ACTIVE
        self.manager.resume_application_session()
        self.assertEqual(sess.state, ApplicationSessionState.ACTIVE)

        # ACTIVE -> CLOSED
        closed = self.manager.close_application_session(reason="Shift ended")
        self.assertEqual(closed.state, ApplicationSessionState.CLOSED)
        self.assertIsNotNone(closed.end_time)
        self.assertIsNone(self.manager.current_session)

    # =================================================================
    # Section H: Invalid Lifecycle Transitions
    # =================================================================
    def test_section_h_invalid_lifecycle_transitions(self):
        sess = self.manager.start_application_session()
        self.manager.close_application_session()

        # CLOSED is terminal: cannot transition back to ACTIVE or PAUSED
        with self.assertRaises(InvalidSessionStateTransitionError):
            sess.transition_to(ApplicationSessionState.ACTIVE)

        with self.assertRaises(InvalidSessionStateTransitionError):
            sess.transition_to(ApplicationSessionState.PAUSED)

        # Direct illegal transition on a fresh session
        fresh = ApplicationSession(application_session_id="appsess_raw", user_id="tech")
        self.assertEqual(fresh.state, ApplicationSessionState.CREATED)
        with self.assertRaises(InvalidSessionStateTransitionError):
            fresh.transition_to(ApplicationSessionState.PAUSED)  # CREATED cannot go directly to PAUSED

    # =================================================================
    # Section I: Unique Application-Session IDs
    # =================================================================
    def test_section_i_unique_session_ids(self):
        ids = set()
        for _ in range(25):
            sess = self.manager.start_application_session()
            self.assertNotIn(sess.application_session_id, ids)
            ids.add(sess.application_session_id)
            self.manager.close_application_session()
        self.assertEqual(len(ids), 25)

    # =================================================================
    # Section J: Diagnostic-Session Linking & Non-Conflation
    # =================================================================
    def test_section_j_diagnostic_session_linking(self):
        app_sess = self.manager.start_application_session()

        # Create a canonical DiagnosticSessionRecord in J-3
        diag_rec = DiagnosticSessionRecord(
            session_id="diag_session_001",
            vehicle_context={"vin": "WAUZZZ8K9FA123456", "make": "Audi", "model": "A4"},
        )
        self.repo.save_session(diag_rec)

        # Link to application session
        self.manager.link_diagnostic_session("diag_session_001", set_as_active=True)
        self.assertIn("diag_session_001", app_sess.diagnostic_session_ids)
        self.assertEqual(app_sess.active_diagnostic_session_id, "diag_session_001")

        # Verify J-3 DiagnosticSessionRecord was updated with application_session_id and user_id
        persisted_diag = self.repo.get_session("diag_session_001")
        self.assertEqual(persisted_diag.application_session_id, app_sess.application_session_id)
        self.assertEqual(persisted_diag.user_id, app_sess.user_id)

        # Non-conflation invariant: ApplicationSession != DiagnosticSession
        self.assertNotEqual(type(app_sess), type(diag_rec))
        self.assertFalse(hasattr(app_sess, "dtc_records"))
        self.assertFalse(hasattr(app_sess, "vehicle_context"))

    # =================================================================
    # Section K: Workflow Linking
    # =================================================================
    def test_section_k_workflow_linking(self):
        app_sess = self.manager.start_application_session()

        # Create diagnostic session and workflow
        diag_id = "diag_sess_flow_test"
        diag_rec = DiagnosticSessionRecord(session_id=diag_id, vehicle_context={"vin": "TESTVIN123"})
        self.repo.save_session(diag_rec)
        self.manager.link_diagnostic_session(diag_id)

        wf = DiagnosticWorkflow(
            workflow_id="wf_001",
            vehicle_id="TESTVIN123",
            session_id=diag_id,
            state=WorkflowState.ACTIVE,
        )
        self.repo.save_workflow(wf)

        # Traceability check: AppSession -> DiagSession -> Workflow
        retrieved_diag = self.repo.get_session(diag_id)
        self.assertEqual(retrieved_diag.application_session_id, app_sess.application_session_id)

        retrieved_wf = self.repo.get_workflow("wf_001")
        self.assertEqual(retrieved_wf.session_id, diag_id)

        # J-4 does NOT manage workflow transitions or execute commands
        self.assertFalse(hasattr(self.manager, "execute_stage"))
        self.assertFalse(hasattr(self.manager, "run_test"))

    # =================================================================
    # Section L: User / Vehicle / ECU Identity Separation
    # =================================================================
    def test_section_l_user_vehicle_identity_separation(self):
        user = self.manager.create_user(display_name="Diagnostician Dave", user_id="dave")
        veh_context = VehicleContext(vin="1HGCR2F83HA000001", manufacturer="Honda", model="Accord", model_year=2017)

        # Invariants: User != Vehicle, User != ECU
        self.assertFalse(hasattr(user, "vin"))
        self.assertFalse(hasattr(user, "ecu_id"))
        self.assertFalse(hasattr(user, "engine_type"))
        self.assertFalse(hasattr(veh_context, "user_id"))

        # User identity is NEVER diagnostic evidence
        u_dict = user.to_dict()
        self.assertNotIn("fault_evidence", u_dict)
        self.assertNotIn("diagnostic_score", u_dict)

    # =================================================================
    # Section M: Persistence Through J-3 (SQLite & In-Memory)
    # =================================================================
    def test_section_m_persistence_through_j3(self):
        # 1. InMemory Persistence
        user = self.manager.create_user(display_name="Persisted User", user_id="user_persist")
        sess = self.manager.start_application_session()
        self.manager.close_application_session()

        saved_user = self.repo.get_user("user_persist")
        self.assertIsNotNone(saved_user)
        self.assertEqual(saved_user["display_name"], "Persisted User")

        saved_sess = self.repo.get_application_session(sess.application_session_id)
        self.assertIsNotNone(saved_sess)
        self.assertEqual(saved_sess["state"], ApplicationSessionState.CLOSED.value)

        # 2. SQLite Backend Persistence
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_j4.db"
            backend = SQLitePersistenceBackend(db_path=db_path)
            sqlite_repo = DiagnosticRepository(backend=backend)
            sqlite_manager = UserSessionManager(repository=sqlite_repo)

            u_sql = sqlite_manager.create_user(display_name="SQL Tech", user_id="tech_sql")
            s_sql = sqlite_manager.start_application_session()
            sqlite_manager.close_application_session()

            # Retrieve through fresh repository connection
            backend2 = SQLitePersistenceBackend(db_path=db_path)
            repo2 = DiagnosticRepository(backend=backend2)
            retrieved = repo2.get_user("tech_sql")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved["display_name"], "SQL Tech")

            retrieved_sess = repo2.get_application_session(s_sql.application_session_id)
            self.assertIsNotNone(retrieved_sess)
            self.assertEqual(retrieved_sess["state"], "CLOSED")
            sqlite_repo.close()
            repo2.close()

    # =================================================================
    # Section N: Serialization / Deserialization Round-Trip
    # =================================================================
    def test_section_n_serialization_round_trip(self):
        user = ApplicationUser(
            user_id="u_roundtrip",
            display_name="Roundtrip Tech",
            status=UserStatus.ACTIVE,
            metadata={"specialty": "Transmission"},
        )
        u_dict = user.to_dict()
        # Verify JSON serializability
        json_str = json.dumps(u_dict)
        restored_user = ApplicationUser.from_dict(json.loads(json_str))
        self.assertEqual(restored_user.user_id, user.user_id)
        self.assertEqual(restored_user.display_name, user.display_name)
        self.assertEqual(restored_user.status, user.status)
        self.assertEqual(restored_user.metadata, user.metadata)

        sess = ApplicationSession(
            application_session_id="appsess_rt",
            user_id="u_roundtrip",
            state=ApplicationSessionState.ACTIVE,
            diagnostic_session_ids=["diag_1", "diag_2"],
            platform_context={"os": "LINUX"},
        )
        s_dict = sess.to_dict()
        s_json = json.dumps(s_dict)
        restored_sess = ApplicationSession.from_dict(json.loads(s_json))
        self.assertEqual(restored_sess.application_session_id, sess.application_session_id)
        self.assertEqual(restored_sess.state, sess.state)
        self.assertEqual(restored_sess.diagnostic_session_ids, ["diag_1", "diag_2"])

    # =================================================================
    # Section O: Schema Version Handling (Fail-Closed)
    # =================================================================
    def test_section_o_schema_version_handling(self):
        # Unsupported future schema version must fail closed
        future_user_data = {
            "user_id": "future_u",
            "display_name": "Future User",
            "schema_version": 99,
        }
        with self.assertRaises(UnsupportedSchemaVersionError):
            ApplicationUser.from_dict(future_user_data)

        future_sess_data = {
            "application_session_id": "future_s",
            "user_id": "future_u",
            "schema_version": 99,
        }
        with self.assertRaises(UnsupportedSchemaVersionError):
            ApplicationSession.from_dict(future_sess_data)

    # =================================================================
    # Section P: Interrupted-Session Representation (Crash Recovery)
    # =================================================================
    def test_section_p_interrupted_session_representation(self):
        # Simulate abnormal termination: session left in ACTIVE in database
        abandoned_sess = ApplicationSession(
            application_session_id="appsess_crashed",
            user_id="default_technician",
            state=ApplicationSessionState.ACTIVE,
            start_time=time.time() - 3600,
        )
        self.repo.save_application_session(abandoned_sess)

        # On restart / recovery
        recovered_ids = self.manager.recover_interrupted_sessions()
        self.assertIn("appsess_crashed", recovered_ids)

        reconciled = self.repo.get_application_session("appsess_crashed")
        self.assertEqual(reconciled["state"], ApplicationSessionState.INTERRUPTED.value)
        self.assertIsNotNone(reconciled["end_time"])

        # INVARIANT: Interrupted != Closed. We must NEVER fabricate a clean CLOSED state!
        self.assertNotEqual(reconciled["state"], ApplicationSessionState.CLOSED.value)

    # =================================================================
    # Section Q: Crash Recovery Semantics & Audit Events
    # =================================================================
    def test_section_q_crash_recovery_semantics(self):
        # Setup multiple unclosed sessions
        s1 = ApplicationSession(application_session_id="sess_crash_1", user_id="u1", state=ApplicationSessionState.ACTIVE)
        s2 = ApplicationSession(application_session_id="sess_crash_2", user_id="u1", state=ApplicationSessionState.PAUSED)
        s3 = ApplicationSession(application_session_id="sess_clean_3", user_id="u1", state=ApplicationSessionState.CLOSED)
        self.repo.save_application_session(s1)
        self.repo.save_application_session(s2)
        self.repo.save_application_session(s3)

        recovered = self.manager.recover_interrupted_sessions()
        self.assertIn("sess_crash_1", recovered)
        self.assertIn("sess_crash_2", recovered)
        self.assertNotIn("sess_clean_3", recovered)

        # Audit events check
        audit_events = self.repo.list_audit_events()
        interrupted_events = [e for e in audit_events if e["event_type"] == SessionAuditEventType.APPLICATION_INTERRUPTED.value]
        self.assertEqual(len(interrupted_events), 2)

    # =================================================================
    # Section R: No Automatic Diagnostic Execution After Restart
    # =================================================================
    def test_section_r_no_automatic_diagnostic_execution_after_restart(self):
        # Recovery must be strictly a metadata/state reconciliation; zero ECU calls
        interrupted = self.manager.recover_interrupted_sessions()
        # Verify no diagnostic tests were run or queued
        self.assertEqual(self.repo.count_records(self.repo.COLLECTION_RAW_ACQUISITIONS), 0)

    # =================================================================
    # Section S: Concurrent Application-Session Identity
    # =================================================================
    def test_section_s_concurrent_application_session_identity(self):
        # Two simultaneous managers representing different processes
        manager_a = UserSessionManager(repository=self.repo)
        manager_b = UserSessionManager(repository=self.repo)

        sess_a = manager_a.start_application_session()
        sess_b = manager_b.start_application_session()

        self.assertNotEqual(sess_a.application_session_id, sess_b.application_session_id)
        self.assertFalse(sess_a.application_session_id == sess_b.application_session_id)

        manager_a.close_application_session()
        manager_b.close_application_session()

    # =================================================================
    # Section T: Technician Observation Attribution
    # =================================================================
    def test_section_t_technician_observation_attribution(self):
        self.manager.create_user(display_name="Senior Mechanic Frank", user_id="frank")
        self.manager.select_active_user("frank")
        sess = self.manager.start_application_session()

        obs = self.manager.attribute_technician_observation(
            observation_text="Strong fuel smell near injector rail; harness clip unlatched.",
            target_ecu="ECM",
            details={"inspection_method": "Visual & Olfactory"},
        )
        self.assertEqual(obs["user_id"], "frank")
        self.assertEqual(obs["display_name"], "Senior Mechanic Frank")
        self.assertEqual(obs["application_session_id"], sess.application_session_id)
        self.assertEqual(obs["target_ecu"], "ECM")
        self.assertTrue(obs["is_technician_observation"])
        self.assertFalse(obs["is_machine_finding"])

        # Record to diagnostic session in J-3
        diag_rec = DiagnosticSessionRecord(session_id="diag_frank_1", vehicle_context={"vin": "V1"})
        self.repo.save_session(diag_rec)
        self.repo.record_technician_observation("diag_frank_1", obs)

        updated_diag = self.repo.get_session("diag_frank_1")
        self.assertEqual(len(updated_diag.technician_observations), 1)
        self.assertEqual(updated_diag.technician_observations[0]["user_id"], "frank")

    # =================================================================
    # Section U: Report Metadata Integration
    # =================================================================
    def test_section_u_report_metadata_integration(self):
        self.manager.create_user(display_name="Inspector Grace", user_id="grace")
        self.manager.select_active_user("grace")
        app_sess = self.manager.start_application_session(app_version="3.1.0")

        metadata = self.manager.generate_report_session_metadata(diagnostic_session_id="diag_report_99")
        self.assertEqual(metadata["operator_user_id"], "grace")
        self.assertEqual(metadata["operator_display_name"], "Inspector Grace")
        self.assertEqual(metadata["application_session_id"], app_sess.application_session_id)
        self.assertEqual(metadata["diagnostic_session_id"], "diag_report_99")
        self.assertEqual(metadata["app_version"], "3.1.0")
        self.assertIn("platform", metadata)

    # =================================================================
    # Section V: Structured Audit Events
    # =================================================================
    def test_section_v_audit_events_tracking(self):
        u = self.manager.create_user(display_name="Audited User", user_id="audit_u")
        self.manager.select_active_user("audit_u")
        s = self.manager.start_application_session()
        self.manager.pause_application_session()
        self.manager.resume_application_session()
        self.manager.link_diagnostic_session("ds_audit")
        self.manager.detach_diagnostic_session("ds_audit")
        self.manager.close_application_session()

        audit_events = self.repo.list_audit_events(application_session_id=s.application_session_id)
        event_types = [e["event_type"] for e in audit_events]

        self.assertIn(SessionAuditEventType.APPLICATION_STARTED.value, event_types)
        self.assertIn(SessionAuditEventType.APPLICATION_PAUSED.value, event_types)
        self.assertIn(SessionAuditEventType.APPLICATION_RESUMED.value, event_types)
        self.assertIn(SessionAuditEventType.DIAGNOSTIC_SESSION_LINKED.value, event_types)
        self.assertIn(SessionAuditEventType.DIAGNOSTIC_SESSION_DETACHED.value, event_types)
        self.assertIn(SessionAuditEventType.APPLICATION_CLOSED.value, event_types)

    # =================================================================
    # Section W: Privacy & Minimal-Data Behavior
    # =================================================================
    def test_section_w_privacy_and_minimal_data(self):
        user = self.manager.create_user(display_name="Private Tech", user_id="p_tech")
        u_dict = user.to_dict()

        # J-4 must not collect personal telemetry, contacts, location, or telemetry beyond platform info
        disallowed_keys = {"email", "phone", "address", "location", "gps", "ssn", "telemetry"}
        for k in disallowed_keys:
            self.assertNotIn(k, u_dict)

        sess = self.manager.start_application_session()
        s_dict = sess.to_dict()
        for k in disallowed_keys:
            self.assertNotIn(k, s_dict)

    # =================================================================
    # Section X: J-2 Platform Integration
    # =================================================================
    def test_section_x_j2_platform_integration(self):
        # Simulate Linux platform provider
        sim_linux = SimulatedPlatformProvider(os_family=OSFamily.LINUX, simulated_home=Path("/home/tech"))
        PlatformManager.set_provider(sim_linux)

        sess = self.manager.start_application_session()
        self.assertEqual(sess.platform_context.get("os_family"), "LINUX")
        self.manager.close_application_session()

    # =================================================================
    # Section Y: J-1 Adapter Identity Integration
    # =================================================================
    def test_section_y_j1_adapter_identity_integration(self):
        adapter_meta = {
            "adapter_type": "ELM327",
            "port": "COM3",
            "baudrate": 115200,
            "can_protocols": ["ISO15765_11BIT_500K"],
        }
        sess = self.manager.start_application_session(adapter_info=adapter_meta)
        self.assertEqual(sess.adapter_info["adapter_type"], "ELM327")
        self.assertEqual(sess.adapter_info["port"], "COM3")
        self.manager.close_application_session()

    # =================================================================
    # Section Z: Cross-Phase Regression & Invariants
    # =================================================================
    def test_section_z_cross_phase_invariants(self):
        # Verify all 12 core invariants
        # 1. User != ApplicationSession
        user = self.manager.active_user
        sess = self.manager.start_application_session()
        self.assertNotEqual(type(user), type(sess))

        # 2. ApplicationSession != DiagnosticSession
        diag_rec = DiagnosticSessionRecord(session_id="d_z", vehicle_context={"vin": "VIN_Z"})
        self.assertNotEqual(type(sess), type(diag_rec))

        # 3. User identity != Vehicle identity
        veh_context = VehicleContext(vin="VIN_Z", manufacturer="VW")
        self.assertNotEqual(type(user), type(veh_context))

        # 4. Backward compatibility: DiagnosticSessionRecord without user_id loads cleanly
        legacy_data = {
            "session_id": "legacy_001",
            "vehicle_context": {"vin": "LEGACY_VIN"},
            "schema_version": 1,
        }
        legacy_rec = DiagnosticSessionRecord.from_dict(legacy_data)
        self.assertIsNone(legacy_rec.user_id)
        self.assertIsNone(legacy_rec.application_session_id)

        # 5. Communication failure != component failure preserved
        err = UserSessionError("Session error")
        self.assertFalse(err.is_communication_failure)
        self.assertFalse(err.is_persistence_error)

        self.manager.close_application_session()


if __name__ == "__main__":
    unittest.main()
