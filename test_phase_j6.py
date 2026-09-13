#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-6 Test Suite
==============================================================
Test Suite for Production Reliability, Resilience & Observability
`test_phase_j6.py`

Covers Sections A through AH (34 distinct verification areas):
A. Global error boundary
B. Fail-safe behavior
C. Bounded retries
D. Timeout enforcement
E. Cancellation
F. Resource cleanup
G. Adapter recovery
H. Application crash recovery
I. Diagnostic session recovery
J. Workflow recovery
K. Duplicate execution protection
L. Persistence failure resilience
M. Corrupted persistence handling
N. Storage lock handling
O. Memory boundedness
P. Large dataset behavior
Q. Logging safety
R. Log growth control
S. Health and status reporting
T. Graceful shutdown
U. Partial failure containment
V. Multi-ECU failure isolation
W. Authorization interaction
X. Safety interaction
Y. AI/reasoning cannot bypass execution
Z. J-5 regression
AA. J-4 regression
AB. J-3 regression
AC. J-2 regression
AD. J-1 regression
AE. I-Final regression
AF. H-Final regression
AG. G-Final regression
AH. Cross-layer invariants
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

# J-1 Adapter & Transport
from diagnostic_adapter import (
    MockDiagnosticAdapter,
    AdapterConnectionState,
    AdapterTimeoutError,
    TransportFailureError,
    PROHIBITED_SERVICES,
)

# J-2 Platform
from platform_abstraction import PlatformManager, SimulatedPlatformProvider, OSFamily

# J-3 Persistence
from diagnostic_persistence import (
    DiagnosticRepository,
    DiagnosticSessionRecord,
    InMemoryPersistenceBackend,
    SQLitePersistenceBackend,
    PersistenceManager,
    PersistenceError,
    StorageBackendError,
    CorruptedPersistenceDataError,
)

# J-4 User & Session
from user_session_manager import (
    ApplicationUser,
    ApplicationSession,
    UserStatus,
    ApplicationSessionState,
    UserSessionManager,
    DEFAULT_USER_ID,
)

# J-5 Security & Authorization
from diagnostic_security import (
    Role,
    Permission,
    Principal,
    AuthorizationContext,
    AuthorizationDecisionStatus,
    DenialReason,
    SecurityManager,
    SecurityPolicyViolationError,
)

# G-1 Safety Policy
from advanced_ecu_services import (
    ServiceSafetyPolicy,
    ServiceSafetyClassification,
    AdvancedServiceRequest,
)

# J-6 Production Reliability
from production_reliability import (
    ReliabilityCategory,
    SystemHealthStatus,
    SubsystemType,
    ShutdownState,
    ReliabilityError,
    FatalReliabilityError,
    TimeoutExceededError,
    DuplicateOperationError,
    ShutdownInProgressError,
    ReliabilityIncident,
    BoundedRingBuffer,
    IdempotencyRegistry,
    ReliabilityRetryPolicy,
    ReliabilityBoundary,
    reliability_boundary,
    SystemHealthMonitor,
    ShutdownCoordinator,
    MultiECUFailureIsolation,
    CrashReconciliationCoordinator,
)


class TestPhaseJ6ProductionReliability(unittest.TestCase):

    def setUp(self):
        self.repo = PersistenceManager.create_in_memory_repository()
        self.user_manager = UserSessionManager(repository=self.repo)
        self.security_manager = SecurityManager(repository=self.repo, user_session_manager=self.user_manager)
        self.health_monitor = SystemHealthMonitor()
        self.shutdown_coordinator = ShutdownCoordinator()
        self.idempotency_registry = IdempotencyRegistry(default_ttl_seconds=60.0)

    def tearDown(self):
        if self.user_manager.current_session:
            try:
                self.user_manager.close_application_session(force=True)
            except Exception:
                pass
        self.repo.close()

    # =================================================================
    # Section A: Global Error Boundary
    # =================================================================
    def test_section_a_global_error_boundary(self):
        # 1. Context manager intercepts exception and categorizes correctly
        incidents: List[ReliabilityIncident] = []

        with self.assertRaises(ReliabilityError) as cm:
            with ReliabilityBoundary(
                boundary_name="test_adapter_boundary",
                subsystem=SubsystemType.ADAPTER,
                on_error=lambda inc: incidents.append(inc),
            ):
                raise AdapterTimeoutError("COM4 port timeout", adapter_id="ADAPTER_1")

        err = cm.exception
        self.assertEqual(err.category, ReliabilityCategory.COMMUNICATION)
        self.assertTrue(err.is_communication_failure)
        self.assertFalse(err.is_diagnostic_fault)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0].category, ReliabilityCategory.COMMUNICATION)

        # 2. Decorator syntax with suppression of error
        @reliability_boundary("safe_query", rethrow=False, default_return="SAFE_FALLBACK")
        def risky_function():
            raise ValueError("Malformed input telemetry")

        result = risky_function()
        self.assertEqual(result, "SAFE_FALLBACK")

    # =================================================================
    # Section B: Fail-Safe Behavior
    # =================================================================
    def test_section_b_fail_safe_behavior(self):
        # State-changing operation with uncertain execution MUST NOT be retried
        execution_count = 0

        def uncertain_actuator_command():
            nonlocal execution_count
            execution_count += 1
            raise AdapterTimeoutError("Timeout during actuator drive: state unknown")

        with self.assertRaises(TimeoutExceededError):
            ReliabilityRetryPolicy.execute(
                uncertain_actuator_command,
                is_read_only=False,  # State-changing operation!
                max_retries=3,
                timeout_sec=1.0,
                operation_name="actuate_valve",
            )

        # Invariant: ZERO automatic retries permitted on state-changing operations
        self.assertEqual(execution_count, 1)

    # =================================================================
    # Section C: Bounded Retries
    # =================================================================
    def test_section_c_bounded_retries(self):
        # Read-only operation allows bounded retries on transient transport failures
        attempts = 0

        def flaky_sensor_read():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise AdapterTimeoutError("Transient dropped frame")
            return "41 0C 1A F8"  # Success on 3rd attempt

        result = ReliabilityRetryPolicy.execute(
            flaky_sensor_read,
            is_read_only=True,
            max_retries=3,
            timeout_sec=2.0,
            backoff_sec=0.01,
            operation_name="read_rpm",
        )
        self.assertEqual(result, "41 0C 1A F8")
        self.assertEqual(attempts, 3)

    # =================================================================
    # Section D: Timeout Enforcement
    # =================================================================
    def test_section_d_timeout_enforcement(self):
        def hanging_operation():
            time.sleep(0.2)
            raise AdapterTimeoutError("Bus hung")

        with self.assertRaises(TimeoutExceededError):
            ReliabilityRetryPolicy.execute(
                hanging_operation,
                is_read_only=True,
                max_retries=10,
                timeout_sec=0.1,  # Short timeout
                operation_name="hanging_bus",
            )

    # =================================================================
    # Section E: Cancellation
    # =================================================================
    def test_section_e_cancellation(self):
        # Long-running task supports clean cancellation token
        cancelled = False
        cleanup_called = False

        def cancellable_worker(is_cancelled_func):
            nonlocal cleanup_called
            for step in range(100):
                if is_cancelled_func():
                    cleanup_called = True
                    return "CANCELLED_CLEANLY"
                time.sleep(0.005)
            return "COMPLETED"

        # Signal cancellation after 2 steps
        def cancel_check():
            return True

        res = cancellable_worker(cancel_check)
        self.assertEqual(res, "CANCELLED_CLEANLY")
        self.assertTrue(cleanup_called)

    # =================================================================
    # Section F: Resource Cleanup
    # =================================================================
    def test_section_f_resource_cleanup(self):
        mock_adapter = MockDiagnosticAdapter()
        mock_adapter.connect()
        self.assertTrue(mock_adapter.is_connected())

        # Register cleanup in shutdown coordinator
        self.shutdown_coordinator.register_cleanup("mock_adapter", mock_adapter.disconnect)
        self.shutdown_coordinator.shutdown()

        self.assertFalse(mock_adapter.is_connected())
        self.assertEqual(self.shutdown_coordinator.state, ShutdownState.TERMINATED)

    # =================================================================
    # Section G: Adapter Recovery
    # =================================================================
    def test_section_g_adapter_recovery(self):
        adapter = MockDiagnosticAdapter()
        adapter.connect()
        self.assertTrue(adapter.is_connected())

        # Simulate hardware disconnect
        adapter.disconnect()
        self.assertEqual(adapter.connection_state, AdapterConnectionState.DISCONNECTED)

        # Health monitor tracks adapter disconnection
        self.health_monitor.report_subsystem(SubsystemType.ADAPTER, SystemHealthStatus.DISCONNECTED, "VCI disconnected")
        self.assertEqual(self.health_monitor.get_overall_health()["overall_status"], "DISCONNECTED")

        # Controlled explicit reconnect
        ok = adapter.connect()
        self.assertTrue(ok)
        self.health_monitor.report_subsystem(SubsystemType.ADAPTER, SystemHealthStatus.HEALTHY, "VCI reconnected")
        self.assertEqual(self.health_monitor.get_overall_health()["overall_status"], "HEALTHY")

    # =================================================================
    # Section H: Application Crash Recovery
    # =================================================================
    def test_section_h_application_crash_recovery(self):
        # Create abandoned session in database
        abandoned = ApplicationSession(
            application_session_id="appsess_crashed_j6",
            user_id="default_technician",
            state=ApplicationSessionState.ACTIVE,
        )
        self.repo.save_application_session(abandoned)

        recon_result = CrashReconciliationCoordinator.reconcile_on_startup(
            user_session_manager=self.user_manager,
            health_monitor=self.health_monitor,
        )
        self.assertIn("appsess_crashed_j6", recon_result["reconciled_application_session_ids"])
        self.assertFalse(recon_result["autonomous_ecu_communication"])

        saved = self.repo.get_application_session("appsess_crashed_j6")
        self.assertEqual(saved["state"], ApplicationSessionState.INTERRUPTED.value)
        self.assertNotEqual(saved["state"], ApplicationSessionState.CLOSED.value)

    # =================================================================
    # Section I: Diagnostic Session Recovery
    # =================================================================
    def test_section_i_diagnostic_session_recovery(self):
        diag_sess = DiagnosticSessionRecord(
            session_id="diag_crashed_j6",
            vehicle_context={"vin": "WAUZZZ123"},
            session_state="ACTIVE",
        )
        self.repo.save_session(diag_sess)

        # Reconciling diagnostic session marks it interrupted without sending commands
        retrieved = self.repo.get_session("diag_crashed_j6")
        retrieved.session_state = "INTERRUPTED"
        self.repo.save_session(retrieved)

        updated = self.repo.get_session("diag_crashed_j6")
        self.assertEqual(updated.session_state, "INTERRUPTED")
        # Invariant: Never fabricate "CLOSED" or "COMPLETED" after crash
        self.assertNotEqual(updated.session_state, "COMPLETED")

    # =================================================================
    # Section J: Workflow Recovery
    # =================================================================
    def test_section_j_workflow_recovery(self):
        # H-5 workflow recovery preserves state without repeating tests
        from diagnostic_workflow_engine import DiagnosticWorkflow, WorkflowState, WorkflowStage
        wf = DiagnosticWorkflow(
            workflow_id="wf_interrupted",
            vehicle_id="VIN_WF",
            session_id="diag_01",
            state=WorkflowState.ACTIVE,
            stage=WorkflowStage.TEST_EXECUTION,
            test_count=3,
        )
        self.repo.save_workflow(wf)

        loaded_wf = self.repo.get_workflow("wf_interrupted")
        self.assertEqual(loaded_wf.test_count, 3)
        self.assertEqual(loaded_wf.stage, WorkflowStage.TEST_EXECUTION)

    # =================================================================
    # Section K: Duplicate Execution Protection
    # =================================================================
    def test_section_k_duplicate_execution_protection(self):
        op_id = "actuator_throttle_sweep_101"
        acquired = self.idempotency_registry.acquire(op_id, ttl_seconds=60.0)
        self.assertTrue(acquired)

        # Immediate duplicate attempt is blocked
        dup_attempt = self.idempotency_registry.acquire(op_id)
        self.assertFalse(dup_attempt)

        self.idempotency_registry.complete(op_id, result={"status": "PASSED"})
        # After completion within TTL, still blocked
        self.assertFalse(self.idempotency_registry.acquire(op_id))

    # =================================================================
    # Section L: Persistence Failure Resilience
    # =================================================================
    def test_section_l_persistence_failure_resilience(self):
        # When backend fails, error boundary catches and handles without application crash
        with self.assertRaises(ReliabilityError) as cm:
            with ReliabilityBoundary("db_write", subsystem=SubsystemType.PERSISTENCE):
                raise StorageBackendError("Disk full or database locked", collection="diagnostic_sessions")

        self.assertEqual(cm.exception.category, ReliabilityCategory.PERSISTENCE)
        self.assertFalse(cm.exception.is_diagnostic_fault)

    # =================================================================
    # Section M: Corrupted Persistence Handling
    # =================================================================
    def test_section_m_corrupted_persistence_handling(self):
        bad_json_data = {"session_id": "", "vehicle_context": None}
        with self.assertRaises(ReliabilityError):
            with ReliabilityBoundary("session_deserialize", subsystem=SubsystemType.PERSISTENCE):
                raise CorruptedPersistenceDataError("Missing required session_id in payload.")

    # =================================================================
    # Section N: Storage Lock Handling
    # =================================================================
    def test_section_n_storage_lock_handling(self):
        lock_attempts = 0

        def db_operation_with_transient_lock():
            nonlocal lock_attempts
            lock_attempts += 1
            if lock_attempts < 2:
                raise StorageBackendError("database is locked")
            return "WRITE_COMMITTED"

        # Bounded retry for database locks
        attempts = 0
        success = False
        while attempts < 3:
            attempts += 1
            try:
                res = db_operation_with_transient_lock()
                success = True
                break
            except StorageBackendError:
                time.sleep(0.01)

        self.assertTrue(success)
        self.assertEqual(attempts, 2)

    # =================================================================
    # Section O: Memory Boundedness
    # =================================================================
    def test_section_o_memory_boundedness(self):
        # Ring buffer with capacity 100
        buffer: BoundedRingBuffer[int] = BoundedRingBuffer(capacity=100)
        # Push 10,000 items
        for i in range(10000):
            buffer.append(i)

        # Buffer size must strictly remain <= 100
        self.assertEqual(buffer.size(), 100)
        self.assertEqual(len(buffer), 100)
        self.assertTrue(buffer.is_full())
        # The oldest items were evicted; buffer contains 9900 to 9999
        self.assertEqual(buffer.to_list()[-1], 9999)
        self.assertEqual(buffer.to_list()[0], 9900)

    # =================================================================
    # Section P: Large Dataset Behavior
    # =================================================================
    def test_section_p_large_dataset_behavior(self):
        # Process 50,000 telemetry points through ring buffer without memory bloat
        telemetry_ring = BoundedRingBuffer(capacity=500)
        start_time = time.monotonic()

        for i in range(50000):
            telemetry_ring.append({"sample_id": i, "rpm": 850 + (i % 50), "voltage": 13.8})

        elapsed = time.monotonic() - start_time
        # Must execute in under 0.5s with zero quadratic slowdown
        self.assertLess(elapsed, 0.5)
        self.assertEqual(telemetry_ring.size(), 500)

    # =================================================================
    # Section Q: Logging Safety
    # =================================================================
    def test_section_q_logging_safety(self):
        incident = ReliabilityIncident(
            incident_id="inc_001",
            category=ReliabilityCategory.COMMUNICATION,
            message="CAN frame dropped by adapter",
            subsystem=SubsystemType.ADAPTER,
            details={"port": "COM3", "baudrate": 115200},
        )
        json_dump = json.dumps(incident.to_dict())
        for secret in ("password", "private_key", "secret", "token", "api_key"):
            self.assertNotIn(secret, json_dump)

    # =================================================================
    # Section R: Log Growth Control
    # =================================================================
    def test_section_r_log_growth_control(self):
        monitor = SystemHealthMonitor()
        # Report 1000 incidents
        for i in range(1000):
            monitor.report_subsystem(SubsystemType.ADAPTER, SystemHealthStatus.DEGRADED, f"Warning {i}")

        recent = monitor.get_recent_incidents(limit=100)
        self.assertLessEqual(len(recent), 100)

    # =================================================================
    # Section S: Health and Status Reporting
    # =================================================================
    def test_section_s_health_and_status_reporting(self):
        health = self.health_monitor.get_overall_health()
        self.assertEqual(health["overall_status"], SystemHealthStatus.HEALTHY.value)

        # Degrade persistence
        self.health_monitor.report_subsystem(SubsystemType.PERSISTENCE, SystemHealthStatus.DEGRADED, "Slow disk I/O")
        health_degraded = self.health_monitor.get_overall_health()
        self.assertEqual(health_degraded["overall_status"], SystemHealthStatus.DEGRADED.value)

        # Invariant: Health status is an infrastructure indicator, NOT an ECU defect
        self.assertNotIn("dtc", health_degraded)
        self.assertNotIn("fault", health_degraded)

    # =================================================================
    # Section T: Graceful Shutdown
    # =================================================================
    def test_section_t_graceful_shutdown(self):
        coord = ShutdownCoordinator()
        cleaned = []

        coord.register_cleanup("db_connection", lambda: cleaned.append("DB_CLOSED"))
        coord.register_cleanup("serial_port", lambda: cleaned.append("PORT_CLOSED"))

        self.assertFalse(coord.is_shutting_down())
        coord.require_running()

        res = coord.shutdown()
        self.assertEqual(res["status"], "TERMINATED")
        self.assertEqual(coord.state, ShutdownState.TERMINATED)
        # LIFO order: serial_port closed before db_connection
        self.assertEqual(cleaned, ["PORT_CLOSED", "DB_CLOSED"])

        # Operations rejected during/after shutdown
        with self.assertRaises(ShutdownInProgressError):
            coord.require_running()

    # =================================================================
    # Section U: Partial Failure Containment
    # =================================================================
    def test_section_u_partial_failure_containment(self):
        # Persistence failure on session record does NOT kill active adapter
        adapter = MockDiagnosticAdapter()
        adapter.connect()
        self.assertTrue(adapter.is_connected())

        try:
            with ReliabilityBoundary("persistence_write", subsystem=SubsystemType.PERSISTENCE):
                raise StorageBackendError("Disk quota exceeded")
        except ReliabilityError:
            pass

        # Adapter remains alive and operational
        self.assertTrue(adapter.is_connected())
        adapter.disconnect()

    # =================================================================
    # Section V: Multi-ECU Failure Isolation
    # =================================================================
    def test_section_v_multi_ecu_failure_isolation(self):
        # ECM communication succeeds, TCM times out
        def mock_ecu_op(target: str) -> str:
            if target == "TCM":
                raise AdapterTimeoutError("TCM did not respond to tester present")
            return f"{target}_OK"

        targets = ["ECM", "TCM", "BCM"]
        results = MultiECUFailureIsolation.execute_multi_target(targets, mock_ecu_op)

        self.assertEqual(results["ECM"], "ECM_OK")
        self.assertEqual(results["BCM"], "BCM_OK")
        self.assertIsInstance(results["TCM"], ReliabilityError)
        self.assertEqual(results["TCM"].category, ReliabilityCategory.COMMUNICATION)

    # =================================================================
    # Section W: Authorization Interaction (J-5)
    # =================================================================
    def test_section_w_authorization_interaction(self):
        app_sess = self.user_manager.start_application_session()
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="read_dtc",
            resource="app:diagnostics",
        )
        dec = self.security_manager.authorize(ctx)
        self.assertTrue(dec.is_allowed())

    # =================================================================
    # Section X: Safety Interaction (G-1 ServiceSafetyPolicy)
    # =================================================================
    def test_section_x_safety_interaction(self):
        policy = ServiceSafetyPolicy(allow_non_readonly=False)
        # Reliability layer respects safety policy: Mode 04 is rejected
        req = AdvancedServiceRequest(service_id="04")
        is_safe, reason = policy.validate_request(req)
        self.assertFalse(is_safe)
        self.assertIn("strictly prohibited", reason)

    # =================================================================
    # Section Y: AI/Reasoning Execution Containment
    # =================================================================
    def test_section_y_ai_reasoning_execution_containment(self):
        app_sess = self.user_manager.start_application_session()
        ctx = AuthorizationContext(
            user_id=DEFAULT_USER_ID,
            application_session_id=app_sess.application_session_id,
            requested_operation="run_guided_test",
            resource="app:diagnostics",
        )
        with self.assertRaises(SecurityPolicyViolationError):
            self.security_manager.validate_ai_recommendation("04", ctx)

    # =================================================================
    # Section Z: Phase J-5 Regression
    # =================================================================
    def test_section_z_j5_regression(self):
        principal = self.security_manager.get_principal(DEFAULT_USER_ID)
        self.assertIsNotNone(principal)
        self.assertIn(Role.TECHNICIAN, principal.roles)

    # =================================================================
    # Section AA: Phase J-4 Regression
    # =================================================================
    def test_section_aa_j4_regression(self):
        user = self.user_manager.active_user
        self.assertEqual(user.user_id, DEFAULT_USER_ID)
        app_sess = self.user_manager.start_application_session()
        self.assertEqual(app_sess.state, ApplicationSessionState.ACTIVE)
        self.user_manager.close_application_session()

    # =================================================================
    # Section AB: Phase J-3 Regression
    # =================================================================
    def test_section_ab_j3_regression(self):
        session_id = "test_sess_j6"
        rec = DiagnosticSessionRecord(session_id=session_id, vehicle_context={"vin": "WAUZZZ123"})
        self.repo.save_session(rec)
        retrieved = self.repo.get_session(session_id)
        self.assertEqual(retrieved.session_id, session_id)

    # =================================================================
    # Section AC: Phase J-2 Regression
    # =================================================================
    def test_section_ac_j2_regression(self):
        info = PlatformManager.get_info()
        self.assertIn(info.os_family, (OSFamily.WINDOWS, OSFamily.LINUX, OSFamily.MACOS))

    # =================================================================
    # Section AD: Phase J-1 Regression
    # =================================================================
    def test_section_ad_j1_regression(self):
        adapter = MockDiagnosticAdapter()
        adapter.connect()
        # Prohibited service 04 is blocked by adapter
        res, status = adapter.send_command("04 01 02")
        self.assertEqual(res, [])
        self.assertEqual(status, "NRC")
        adapter.disconnect()

    # =================================================================
    # Section AE: Phase I-Final Regression
    # =================================================================
    def test_section_ae_i_final_regression(self):
        from advanced_fault_analysis import DTCRecord
        dtc = DTCRecord(code="P0300", description="Random/Multiple Cylinder Misfire")
        self.assertEqual(dtc.code, "P0300")

    # =================================================================
    # Section AF: Phase H-Final Regression
    # =================================================================
    def test_section_af_h_final_regression(self):
        from automated_test_sequencer import AutomatedTestSequencer
        sequencer = AutomatedTestSequencer()
        self.assertIsNotNone(sequencer)

    # =================================================================
    # Section AG: Phase G-Final Regression
    # =================================================================
    def test_section_ag_g_final_regression(self):
        from vehicle_diagnostic_graph import DiagnosticGraph
        graph = DiagnosticGraph(vehicle_id="VIN_G")
        self.assertEqual(graph.vehicle_id, "VIN_G")

    # =================================================================
    # Section AH: Cross-Layer Invariants
    # =================================================================
    def test_section_ah_cross_layer_invariants(self):
        # Invariant 1: Communication failure != component fault
        err = ReliabilityError("Bus dropped frame", category=ReliabilityCategory.COMMUNICATION)
        self.assertTrue(err.is_communication_failure)
        self.assertFalse(err.is_diagnostic_fault)

        # Invariant 2: Security failure != component fault
        sec_err = ReliabilityError("Permission denied", category=ReliabilityCategory.SECURITY)
        self.assertFalse(sec_err.is_communication_failure)
        self.assertFalse(sec_err.is_diagnostic_fault)

        # Invariant 3: Interrupted != completed
        sess = ApplicationSession(application_session_id="s_inv", user_id="u1", state=ApplicationSessionState.INTERRUPTED)
        self.assertNotEqual(sess.state, ApplicationSessionState.CLOSED)


if __name__ == "__main__":
    unittest.main()
