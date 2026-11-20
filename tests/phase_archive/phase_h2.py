# -*- coding: utf-8 -*-
"""
test_phase_h2.py - Dedicated Comprehensive Test Suite for Phase H-2
=============================================================================
Verifies all 32 required scenarios (A through AF) for Phase H-2 Automated
Test Sequencing:

  A. Sequence creation from valid H-1 procedure
  B. Invalid procedure rejection
  C. Initial state transitions
  D. Step eligibility
  E. Precondition waiting
  F. ECU unavailable behavior
  G. Read-only acquisition execution
  H. DID/PID acquisition integration
  I. Structured result creation
  J. Branch selection
  K. Multiple matching branches / ambiguity
  L. Technician wait state
  M. Technician input validation
  N. Retry behavior
  O. Timeout behavior
  P. Loop detection
  Q. Maximum step protection
  R. Sequence cancellation
  S. Safety revalidation before execution
  T. Safety drift protection
  U. Destructive-action rejection
  V. Multi-ECU sequencing
  W. ECU response isolation
  X. Data freshness rejection
  Y. Contradictory outcome handling
  Z. Serialization round-trip
  AA. Deterministic repeated execution
  AB. Failure isolation
  AC. Graph execution-event integration
  AD. Bounded acquisition enforcement
  AE. Large procedure performance
  AF. No duplicate transport architecture
=============================================================================
"""

import copy
import math
import time
import unittest
from typing import Any, Dict, List

from advanced_ecu_services import (
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    DiagnosticSessionContext,
    DiagnosticTransactionManager,
    ECUTargetContext,
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    SessionType,
    STATUS_NRC,
    STATUS_TIMEOUT,
    STATUS_VALID,
)
from extended_did import (
    DataDecoder,
    DataType,
    DiagnosticDataDefinition,
    IdentifierNamespace,
    VehicleContext,
)
from advanced_fault_analysis import (
    SignalQuality,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    make_ecu_node_id,
    make_vehicle_node_id,
)
from guided_procedures import (
    DiagnosticBranch,
    DiagnosticExpectedObservation,
    DiagnosticPrecondition,
    DiagnosticProcedure,
    DiagnosticProcedureContext,
    DiagnosticStep,
    DiagnosticStopCondition,
    ObservationResultType,
    ProcedureOutcome,
    ProcedureState,
    StepExecutionMode,
    StepPriority,
    StopConditionType,
    TechnicianObservation,
)
from automated_test_sequencer import (
    AutomatedTestSequencer,
    DiagnosticSequence,
    MockTestExecutionAdapter,
    PreconditionEngine,
    PreconditionStatus,
    ReadOnlyAcquisitionAdapter,
    SequenceActionDescriptor,
    SequenceEvent,
    SequenceEventType,
    SequenceExecutionPolicy,
    SequenceLoopError,
    SequenceResult,
    SequenceSafetyError,
    SequenceState,
    SequenceStateError,
    SequenceStepExecution,
    SequenceTimeoutError,
    SequencerError,
    StepEligibility,
    TechnicianObservationAdapter,
    TechnicianValidationError,
)


def make_sample_procedure() -> DiagnosticProcedure:
    """Helper to build a valid, multi-step H-1 procedure for sequencing tests."""
    ctx = DiagnosticProcedureContext(
        vehicle_id="vehicle:TEST_VIN_123",
        session_id="sess_h2_test",
        available_ecus=["ECM", "TCM", "ABS"],
        unreachable_ecus=[],
        operating_condition="WARM_IDLE",
    )
    proc = DiagnosticProcedure(
        procedure_id="proc_boost_leak_001",
        context=ctx,
        title="Guided Test for Turbocharger Boost Leak",
        objective="Verify intake tract integrity and pressure sensor rationality.",
    )

    # Step 1: Read intake MAP sensor (ReadOnly acquisition)
    step1 = DiagnosticStep(
        step_id="step_read_map",
        sequence=1,
        title="Read Manifold Absolute Pressure at Idle",
        technician_instruction="Observe MAP live telemetry value via diagnostic tool.",
        purpose="Verify idle MAP is within atmospheric/vacuum expectations.",
        rationale="MAP reading at idle establishes baseline pressure.",
        target_ecu="ECM",
        execution_mode=StepExecutionMode.OBSERVATIONAL,
        priority=StepPriority.MANDATORY,
        preconditions=[
            DiagnosticPrecondition(
                description="Engine must be at warm idle",
                required_ecu_id="ECM",
                required_operating_condition="WARM_IDLE",
            )
        ],
        expected_observation=DiagnosticExpectedObservation(
            description="MAP should be between 25 and 45 kPa at idle",
            signal_name="MAP",
            min_value=25.0,
            max_value=45.0,
            unit="kPa",
            trusted_source=True,
        ),
        branches=[
            DiagnosticBranch(
                branch_id="br_map_normal",
                condition_outcome=ObservationResultType.NORMAL,
                target_step_id="step_visual_harness",
                confidence_adjustment=0.1,
                rationale="MAP is normal, proceed to visual check.",
            ),
            DiagnosticBranch(
                branch_id="br_map_abnormal",
                condition_outcome=ObservationResultType.ABNORMAL,
                target_step_id="step_smoke_test",
                confidence_adjustment=0.4,
                rationale="MAP is abnormal, jump directly to smoke test.",
            ),
            DiagnosticBranch(
                branch_id="br_map_comm_fail",
                condition_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                terminal_outcome=ProcedureOutcome.COMMUNICATION_PROBLEM,
                confidence_adjustment=-0.5,
                rationale="ECM lost communication during MAP read.",
            ),
        ],
    )

    # Step 2: Visual harness inspection (Technician observation)
    step2 = DiagnosticStep(
        step_id="step_visual_harness",
        sequence=2,
        title="Visual Inspection of MAP Sensor Wiring",
        technician_instruction="Inspect wiring harness and connector pins for corrosion or chafing.",
        purpose="Eliminate wiring and physical connector fault.",
        rationale="High vibration area often causes wire chafing.",
        target_ecu="ECM",
        execution_mode=StepExecutionMode.OBSERVATIONAL,
        priority=StepPriority.RECOMMENDED,
        branches=[
            DiagnosticBranch(
                branch_id="br_harness_ok",
                condition_outcome=ObservationResultType.NORMAL,
                target_step_id="step_measure_ref_v",
                confidence_adjustment=0.1,
                rationale="Wiring visually intact, proceed to 5V reference check.",
            ),
            DiagnosticBranch(
                branch_id="br_harness_damage",
                condition_outcome=ObservationResultType.ABNORMAL,
                terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                confidence_adjustment=0.5,
                rationale="Visible wiring damage confirms physical harness fault.",
            ),
        ],
    )

    # Step 3: Measure 5V reference (Technician measurement)
    step3 = DiagnosticStep(
        step_id="step_measure_ref_v",
        sequence=3,
        title="Measure 5V Reference Voltage at Sensor Harness",
        technician_instruction="Disconnect MAP connector and probe Pin 1 to ground with DMM.",
        purpose="Verify ECU 5V sensor power supply rail integrity.",
        rationale="Faulty 5V reference will bias all analog sensor readings.",
        target_ecu="ECM",
        execution_mode=StepExecutionMode.MEASUREMENT,
        priority=StepPriority.MANDATORY,
        expected_observation=DiagnosticExpectedObservation(
            description="5.0V +/- 0.2V",
            signal_name="REF_5V",
            min_value=4.8,
            max_value=5.2,
            unit="V",
            trusted_source=True,
        ),
        branches=[
            DiagnosticBranch(
                branch_id="br_ref_v_good",
                condition_outcome=ObservationResultType.NORMAL,
                terminal_outcome=ProcedureOutcome.HYPOTHESIS_WEAKENED,
                confidence_adjustment=-0.3,
                rationale="5V supply rail is healthy.",
            ),
            DiagnosticBranch(
                branch_id="br_ref_v_bad",
                condition_outcome=ObservationResultType.ABNORMAL,
                terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                confidence_adjustment=0.6,
                rationale="5V reference out of spec confirms supply circuit fault.",
            ),
        ],
    )

    # Step 4: Smoke test (Manual inspection step)
    step4 = DiagnosticStep(
        step_id="step_smoke_test",
        sequence=4,
        title="Intake Smoke Leak Test",
        technician_instruction="Inject pressurized smoke into intake tract at 5 PSI and inspect for plumes.",
        purpose="Pinpoint exact location of manifold or hose breach.",
        rationale="Physical smoke test reliably exposes leaks.",
        target_ecu="ECM",
        execution_mode=StepExecutionMode.OBSERVATIONAL,
        branches=[
            DiagnosticBranch(
                branch_id="br_smoke_leak_found",
                condition_outcome=ObservationResultType.ABNORMAL,
                terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                confidence_adjustment=0.7,
                rationale="Smoke leak observed confirms physical breach.",
            ),
            DiagnosticBranch(
                branch_id="br_smoke_no_leak",
                condition_outcome=ObservationResultType.NORMAL,
                terminal_outcome=ProcedureOutcome.HYPOTHESIS_WEAKENED,
                confidence_adjustment=-0.4,
                rationale="No smoke leak weakens boost leak hypothesis.",
            ),
        ],
    )

    proc.add_step(step1)
    proc.add_step(step2)
    proc.add_step(step3)
    proc.add_step(step4)
    proc.transition_to(ProcedureState.READY, reason="Procedure configured.")
    return proc


class TestPhaseH2AutomatedTestSequencing(unittest.TestCase):
    """Test suite covering all 32 required scenarios for Phase H-2."""

    def setUp(self):
        self.mock_adapter = MockTestExecutionAdapter()
        self.sequencer = AutomatedTestSequencer(
            read_only_adapter=self.mock_adapter,
        )

    # -----------------------------------------------------------------
    # Test A: Sequence creation from valid H-1 procedure
    # -----------------------------------------------------------------
    def test_a_sequence_creation_from_valid_procedure(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc, session_id="sess_h2_001")

        self.assertIsInstance(seq, DiagnosticSequence)
        self.assertEqual(seq.procedure_id, proc.procedure_id)
        self.assertEqual(seq.vehicle_id, proc.context.vehicle_id)
        self.assertEqual(seq.session_id, "sess_h2_001")
        self.assertEqual(seq.execution_state, SequenceState.READY)
        self.assertEqual(seq.current_step_id, "step_read_map")
        self.assertEqual(len(seq.pending_steps), 4)
        self.assertEqual(len(seq.completed_steps), 0)
        self.assertEqual(len(seq.events), 1)
        self.assertEqual(seq.events[0].event_type, SequenceEventType.STATE_TRANSITION)

    # -----------------------------------------------------------------
    # Test B: Invalid procedure rejection
    # -----------------------------------------------------------------
    def test_b_invalid_procedure_rejection(self):
        # 1. Null procedure
        with self.assertRaises(SequencerError):
            self.sequencer.create_sequence(None)  # type: ignore

        # 2. Procedure without steps
        ctx = DiagnosticProcedureContext(vehicle_id="veh1", session_id="s1")
        empty_proc = DiagnosticProcedure(procedure_id="proc_empty", context=ctx, title="Empty", objective="None")
        with self.assertRaises(SequencerError):
            self.sequencer.create_sequence(empty_proc)

        # 3. Procedure with blank ID
        empty_proc.procedure_id = "   "
        with self.assertRaises(SequencerError):
            self.sequencer.create_sequence(empty_proc)

    # -----------------------------------------------------------------
    # Test C: Initial state transitions
    # -----------------------------------------------------------------
    def test_c_initial_state_transitions(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        self.assertEqual(seq.execution_state, SequenceState.READY)

        # Transition READY -> RUNNING
        evt = seq.transition_to(SequenceState.RUNNING, reason="Starting sequence.")
        self.assertEqual(seq.execution_state, SequenceState.RUNNING)
        self.assertEqual(evt.previous_state, "READY")
        self.assertEqual(evt.new_state, "RUNNING")

        # Illegal transition RUNNING -> CREATED
        with self.assertRaises(SequenceStateError):
            seq.transition_to(SequenceState.CREATED)

    # -----------------------------------------------------------------
    # Test D: Step eligibility evaluation
    # -----------------------------------------------------------------
    def test_d_step_eligibility(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        # Step 1 is eligible
        elig, reason = self.sequencer.evaluate_step_eligibility(seq, proc, "step_read_map")
        self.assertEqual(elig, StepEligibility.ELIGIBLE)

        # Non-existent step
        elig, reason = self.sequencer.evaluate_step_eligibility(seq, proc, "non_existent")
        self.assertEqual(elig, StepEligibility.INVALID)

        # Completed step
        seq.completed_steps.append("step_read_map")
        elig, reason = self.sequencer.evaluate_step_eligibility(seq, proc, "step_read_map")
        self.assertEqual(elig, StepEligibility.ALREADY_COMPLETED)

    # -----------------------------------------------------------------
    # Test E: Precondition waiting
    # -----------------------------------------------------------------
    def test_e_precondition_waiting(self):
        proc = make_sample_procedure()
        # Change vehicle operating condition to COLD_START while step requires WARM_IDLE
        proc.context.operating_condition = "COLD_START"
        seq = self.sequencer.create_sequence(proc)

        res = self.sequencer.execute_current_step(seq, proc)
        self.assertEqual(seq.execution_state, SequenceState.WAITING_FOR_PRECONDITION)
        self.assertEqual(res.execution_status, "WAITING_FOR_PRECONDITION")
        self.assertIn("Operating condition mismatch", res.error_state or "")

    # -----------------------------------------------------------------
    # Test F: ECU unavailable behavior
    # -----------------------------------------------------------------
    def test_f_ecu_unavailable_behavior(self):
        proc = make_sample_procedure()
        # Mark ECM as unreachable
        proc.context.unreachable_ecus = ["ECM"]
        seq = self.sequencer.create_sequence(proc)

        res = self.sequencer.execute_current_step(seq, proc)
        self.assertEqual(res.execution_status, "WAITING_FOR_PRECONDITION")
        self.assertIn("ECM", res.error_state or "")

    # -----------------------------------------------------------------
    # Test G: Read-only acquisition execution
    # -----------------------------------------------------------------
    def test_g_read_only_acquisition_execution(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        self.mock_adapter.configure_step(
            step_id="step_read_map",
            status="SUCCESS",
            actual_outcome=ObservationResultType.NORMAL,
            observed_values={"MAP_kPa": 35.0},
        )
        desc = SequenceActionDescriptor(
            target_ecu="ECM",
            service_id="01",
            identifier="0B",
            timeout_s=1.0,
        )

        res = self.sequencer.execute_current_step(seq, proc, descriptor=desc)
        self.assertEqual(res.execution_status, "SUCCESS")
        self.assertEqual(res.actual_outcome, ObservationResultType.NORMAL)
        self.assertEqual(res.observed_values.get("MAP_kPa"), 35.0)
        # Advance to step_visual_harness as mapped by br_map_normal
        self.assertEqual(seq.current_step_id, "step_visual_harness")
        self.assertIn("step_read_map", seq.completed_steps)

    # -----------------------------------------------------------------
    # Test H: DID/PID acquisition integration
    # -----------------------------------------------------------------
    def test_h_did_pid_acquisition_integration(self):
        # Test real ReadOnlyAcquisitionAdapter logic
        adapter = ReadOnlyAcquisitionAdapter()
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        step = proc.steps["step_read_map"]

        desc = SequenceActionDescriptor(
            target_ecu="ECM",
            service_id="22",
            identifier="F190",
            timeout_s=2.0,
        )
        res = adapter.execute(step, desc, seq)
        self.assertEqual(res.execution_status, "SUCCESS")
        self.assertEqual(res.observed_values.get("identifier"), "F190")
        self.assertEqual(res.data_quality, SignalQuality.GOOD)

    # -----------------------------------------------------------------
    # Test I: Structured result creation
    # -----------------------------------------------------------------
    def test_i_structured_result_creation(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        self.mock_adapter.configure_step(
            step_id="step_read_map",
            status="SUCCESS",
            actual_outcome=ObservationResultType.ABNORMAL,
            observed_values={"MAP_kPa": 85.0},
        )
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")

        res = self.sequencer.execute_current_step(seq, proc, descriptor=desc)
        self.assertIsInstance(res, SequenceResult)
        self.assertEqual(res.step_id, "step_read_map")
        self.assertEqual(res.actual_outcome, ObservationResultType.ABNORMAL)
        self.assertEqual(res.branch_decision, "step_smoke_test")
        # Ensure result dict is JSON-serializable
        d = res.to_dict()
        self.assertEqual(d["actual_outcome"], "ABNORMAL")

    # -----------------------------------------------------------------
    # Test J: Branch selection
    # -----------------------------------------------------------------
    def test_j_branch_selection(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        # Outcome ABNORMAL should select br_map_abnormal -> step_smoke_test
        self.mock_adapter.configure_step(
            step_id="step_read_map",
            actual_outcome=ObservationResultType.ABNORMAL,
        )
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")
        self.sequencer.execute_current_step(seq, proc, descriptor=desc)

        self.assertEqual(seq.active_branch_id, "br_map_abnormal")
        self.assertEqual(seq.current_step_id, "step_smoke_test")

    # -----------------------------------------------------------------
    # Test K: Multiple matching branches / ambiguity
    # -----------------------------------------------------------------
    def test_k_multiple_matching_branches_ambiguity(self):
        proc = make_sample_procedure()
        step = proc.steps["step_read_map"]
        # Add a competing branch with lower confidence adjustment
        competing = DiagnosticBranch(
            branch_id="br_map_normal_low_conf",
            condition_outcome=ObservationResultType.NORMAL,
            target_step_id="step_measure_ref_v",
            confidence_adjustment=-0.2,
            rationale="Alternative lower priority branch.",
        )
        step.branches.append(competing)

        seq = self.sequencer.create_sequence(proc)
        target, term = self.sequencer.evaluate_branches(step, ObservationResultType.NORMAL, seq)

        # Deterministic resolution selects highest confidence adjustment ("br_map_normal" at +0.1)
        self.assertEqual(seq.active_branch_id, "br_map_normal")
        self.assertEqual(target, "step_visual_harness")

    # -----------------------------------------------------------------
    # Test L: Technician wait state
    # -----------------------------------------------------------------
    def test_l_technician_wait_state(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        # Advance directly to step 2 (visual harness)
        seq.current_step_id = "step_visual_harness"

        # Calling execute without technician input should enter WAITING_FOR_TECHNICIAN
        res = self.sequencer.execute_current_step(seq, proc)
        self.assertEqual(seq.execution_state, SequenceState.WAITING_FOR_TECHNICIAN)
        self.assertEqual(res.execution_status, "WAITING_FOR_TECHNICIAN")

    # -----------------------------------------------------------------
    # Test M: Technician input validation
    # -----------------------------------------------------------------
    def test_m_technician_input_validation(self):
        adapter = TechnicianObservationAdapter()
        proc = make_sample_procedure()
        measure_step = proc.steps["step_measure_ref_v"]  # Requires numeric float with unit 'V'

        # 1. Missing measured_value on measurement step
        with self.assertRaises(TechnicianValidationError):
            adapter.validate_technician_input(
                step=measure_step,
                result_type=ObservationResultType.MEASURED_VALUE,
                measured_value=None,
            )

        # 2. NaN value
        with self.assertRaises(TechnicianValidationError):
            adapter.validate_technician_input(
                step=measure_step,
                result_type=ObservationResultType.MEASURED_VALUE,
                measured_value=float("nan"),
            )

        # 3. Mismatched unit
        with self.assertRaises(TechnicianValidationError):
            adapter.validate_technician_input(
                step=measure_step,
                result_type=ObservationResultType.MEASURED_VALUE,
                measured_value=5.0,
                unit="PSI",
            )

        # 4. Valid input
        obs = adapter.validate_technician_input(
            step=measure_step,
            result_type=ObservationResultType.MEASURED_VALUE,
            measured_value=5.02,
            unit="V",
            notes="Probed pin 1.",
        )
        self.assertIsInstance(obs, TechnicianObservation)
        self.assertEqual(obs.result_type, ObservationResultType.NORMAL)  # 5.02 is between 4.8 and 5.2

    # -----------------------------------------------------------------
    # Test N: Retry behavior (bounded)
    # -----------------------------------------------------------------
    def test_n_retry_behavior(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        seq.policy.max_retries_per_step = 2

        # Configure mock to fail 1 time with timeout, then succeed
        self.mock_adapter.configure_step(
            step_id="step_read_map",
            status="SUCCESS",
            actual_outcome=ObservationResultType.NORMAL,
            fail_attempts=1,
        )
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")

        # Attempt 1: Transient timeout triggers retry event
        res1 = self.sequencer.execute_current_step(seq, proc, descriptor=desc)
        self.assertEqual(res1.execution_status, "TIMEOUT")
        retry_events = [e for e in seq.events if e.event_type == SequenceEventType.STEP_RETRY]
        self.assertEqual(len(retry_events), 1)

        # Attempt 2: Succeeds
        res2 = self.sequencer.execute_current_step(seq, proc, descriptor=desc)
        self.assertEqual(res2.execution_status, "SUCCESS")
        self.assertEqual(res2.actual_outcome, ObservationResultType.NORMAL)

    # -----------------------------------------------------------------
    # Test O: Timeout behavior
    # -----------------------------------------------------------------
    def test_o_timeout_behavior(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        # Force an expired global timeout
        seq.policy.global_timeout_s = 0.001
        time.sleep(0.01)

        res = self.sequencer.execute_current_step(seq, proc)
        self.assertEqual(seq.execution_state, SequenceState.FAILED)
        self.assertEqual(res.execution_status, "TIMEOUT")

    # -----------------------------------------------------------------
    # Test P: Loop detection
    # -----------------------------------------------------------------
    def test_p_loop_detection(self):
        proc = make_sample_procedure()
        step = proc.steps["step_read_map"]
        # Create a recursive branch that loops back to itself
        loop_branch = DiagnosticBranch(
            branch_id="br_loop",
            condition_outcome=ObservationResultType.NORMAL,
            target_step_id="step_read_map",
        )
        step.branches = [loop_branch]

        seq = self.sequencer.create_sequence(proc)
        seq.policy.max_branch_revisits = 2

        # Revisit branch 3 times
        self.sequencer.evaluate_branches(step, ObservationResultType.NORMAL, seq)
        self.sequencer.evaluate_branches(step, ObservationResultType.NORMAL, seq)

        # 3rd visit exceeds threshold (max=2)
        with self.assertRaises(SequenceLoopError):
            self.sequencer.evaluate_branches(step, ObservationResultType.NORMAL, seq)

    # -----------------------------------------------------------------
    # Test Q: Maximum step protection
    # -----------------------------------------------------------------
    def test_q_maximum_step_protection(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        seq.policy.max_sequence_steps = 3

        # Fake 3 completed steps
        seq.completed_steps = ["s1", "s2", "s3"]

        res = self.sequencer.execute_current_step(seq, proc)
        self.assertEqual(seq.execution_state, SequenceState.BLOCKED)
        self.assertEqual(res.execution_status, "LOOP_BLOCKED")

    # -----------------------------------------------------------------
    # Test R: Sequence cancellation
    # -----------------------------------------------------------------
    def test_r_sequence_cancellation(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        seq.transition_to(SequenceState.RUNNING, reason="Active.")

        self.sequencer.cancel_sequence(seq, reason="Technician pressed stop.")
        self.assertEqual(seq.execution_state, SequenceState.ABORTED)
        self.assertEqual(seq.termination_reason, "Technician pressed stop.")
        self.assertTrue(seq.is_terminal)

        # Cannot execute on aborted sequence
        with self.assertRaises(SequenceStateError):
            self.sequencer.execute_current_step(seq, proc)

    # -----------------------------------------------------------------
    # Test S: Safety revalidation before execution
    # -----------------------------------------------------------------
    def test_s_safety_revalidation_before_execution(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        # Manually alter step to ACTIVE_DIAGNOSTIC (safety violation)
        proc.steps["step_read_map"].execution_mode = StepExecutionMode.ACTIVE_DIAGNOSTIC

        res = self.sequencer.execute_current_step(seq, proc)
        self.assertEqual(seq.execution_state, SequenceState.BLOCKED)
        self.assertEqual(res.execution_status, "SAFETY_BLOCKED")
        self.assertIn("step_read_map", seq.blocked_steps)

    # -----------------------------------------------------------------
    # Test T: Safety drift protection
    # -----------------------------------------------------------------
    def test_t_safety_drift_protection(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        step = proc.steps["step_read_map"]

        # Action descriptor requests prohibited service 0x2E (Write)
        with self.assertRaises(SequenceSafetyError):
            SequenceActionDescriptor(target_ecu="ECM", service_id="2E", identifier="0101")

        # Even if descriptor was created safely, simulate dynamic safety policy revocation
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")
        strict_policy = ServiceSafetyPolicy(allow_non_readonly=False)
        strict_policy.validate_request = lambda req: (False, "Service revoked by policy drift.")  # type: ignore

        drift_sequencer = AutomatedTestSequencer(
            safety_policy=strict_policy,
            read_only_adapter=self.mock_adapter,
        )
        res = drift_sequencer.execute_current_step(seq, proc, descriptor=desc)
        self.assertEqual(seq.execution_state, SequenceState.BLOCKED)
        self.assertEqual(res.execution_status, "SAFETY_BLOCKED")
        self.assertIn("revoked", res.error_state or "")

    # -----------------------------------------------------------------
    # Test U: Destructive-action rejection
    # -----------------------------------------------------------------
    def test_u_destructive_action_rejection(self):
        for sid in ["04", "14", "2E", "27", "2F", "34", "36", "37"]:
            with self.assertRaises(SequenceSafetyError):
                SequenceActionDescriptor(target_ecu="ECM", service_id=sid, identifier="00")

    # -----------------------------------------------------------------
    # Test V: Multi-ECU sequencing
    # -----------------------------------------------------------------
    def test_v_multi_ecu_sequencing(self):
        proc = make_sample_procedure()
        # Add TCM and ABS steps
        tcm_step = DiagnosticStep(
            step_id="step_tcm_temp",
            sequence=5,
            title="Read Transmission Fluid Temperature",
            technician_instruction="Observe TFT PID.",
            purpose="Verify transmission fluid heat status.",
            rationale="TCM monitoring.",
            target_ecu="TCM",
            execution_mode=StepExecutionMode.OBSERVATIONAL,
        )
        proc.add_step(tcm_step)

        seq = self.sequencer.create_sequence(proc)
        seq.current_step_id = "step_tcm_temp"

        self.mock_adapter.configure_step(
            step_id="step_tcm_temp",
            status="SUCCESS",
            actual_outcome=ObservationResultType.NORMAL,
            observed_values={"TFT_C": 80.0},
        )
        desc = SequenceActionDescriptor(target_ecu="TCM", service_id="01", identifier="5C")
        res = self.sequencer.execute_current_step(seq, proc, descriptor=desc)

        self.assertEqual(res.step_id, "step_tcm_temp")
        self.assertEqual(res.execution_status, "SUCCESS")
        # Verify call in mock log preserved correct target ECU
        self.assertEqual(self.mock_adapter.execution_log[-1]["target_ecu"], "TCM")

    # -----------------------------------------------------------------
    # Test W: ECU response isolation
    # -----------------------------------------------------------------
    def test_w_ecu_response_isolation(self):
        # Ensure a failure on TCM does not mark ECM results as failed
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        # Step 1 on ECM succeeds
        self.mock_adapter.configure_step(step_id="step_read_map", status="SUCCESS")
        desc_ecm = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")
        res1 = self.sequencer.execute_current_step(seq, proc, descriptor=desc_ecm)
        self.assertEqual(res1.execution_status, "SUCCESS")

        # Step on TCM fails with unreachable
        tcm_step = DiagnosticStep(
            step_id="step_tcm_fail",
            sequence=5,
            title="Read TCM Data",
            technician_instruction="Read TCM.",
            purpose="TCM test.",
            rationale="TCM test.",
            target_ecu="TCM",
            execution_mode=StepExecutionMode.OBSERVATIONAL,
        )
        proc.add_step(tcm_step)
        seq.current_step_id = "step_tcm_fail"
        self.mock_adapter.set_ecu_available("TCM", False)

        desc_tcm = SequenceActionDescriptor(target_ecu="TCM", service_id="01", identifier="02")
        res2 = self.sequencer.execute_current_step(seq, proc, descriptor=desc_tcm)
        self.assertEqual(res2.execution_status, "ECU_UNREACHABLE")

        # ECM execution record remains pristine
        self.assertEqual(seq.step_executions["step_read_map"].status, "SUCCESS")

    # -----------------------------------------------------------------
    # Test X: Data freshness rejection
    # -----------------------------------------------------------------
    def test_x_data_freshness_rejection(self):
        engine = PreconditionEngine(data_freshness_window_s=5.0, allow_stale_data=False)
        prec = DiagnosticPrecondition(
            description="Fresh ECT required",
            required_signals=["ECT"],
        )
        ctx = DiagnosticProcedureContext(vehicle_id="veh", session_id="s")
        seq = DiagnosticSequence(sequence_id="sq", procedure_id="p", vehicle_id="v", session_id="s")

        # Signal older than 5.0 seconds
        stale_time = time.time() - 10.0
        status, reason = engine.evaluate_precondition(
            prec, ctx, seq,
            current_signals={"ECT": 90.0},
            signal_timestamps={"ECT": stale_time},
        )
        self.assertEqual(status, PreconditionStatus.STALE_DATA)
        self.assertIn("stale", reason.lower())

    # -----------------------------------------------------------------
    # Test Y: Contradictory outcome handling
    # -----------------------------------------------------------------
    def test_y_contradictory_outcome_handling(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        step = proc.steps["step_read_map"]

        # If actual outcome is INTERMITTENT and no branch exists for it,
        # engine records an event and safely falls through to next sequence step
        target, term = self.sequencer.evaluate_branches(step, ObservationResultType.INTERMITTENT, seq)
        self.assertIsNone(target)
        self.assertIsNone(term)
        branch_events = [e for e in seq.events if e.event_type == SequenceEventType.BRANCH_EVALUATED]
        self.assertTrue(len(branch_events) > 0)

    # -----------------------------------------------------------------
    # Test Z: Serialization round-trip
    # -----------------------------------------------------------------
    def test_z_serialization_round_trip(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        seq.transition_to(SequenceState.RUNNING, reason="Testing.")
        seq.completed_steps.append("step_read_map")
        seq.record_event(SequenceEventType.STEP_COMPLETED, reason="Step 1 complete.")

        d = seq.to_dict()
        restored = DiagnosticSequence.from_dict(d)

        self.assertEqual(restored.sequence_id, seq.sequence_id)
        self.assertEqual(restored.procedure_id, seq.procedure_id)
        self.assertEqual(restored.execution_state, SequenceState.RUNNING)
        self.assertEqual(restored.completed_steps, ["step_read_map"])
        self.assertEqual(len(restored.events), len(seq.events))

    # -----------------------------------------------------------------
    # Test AA: Deterministic repeated execution
    # -----------------------------------------------------------------
    def test_aa_deterministic_repeated_execution(self):
        proc1 = make_sample_procedure()
        proc2 = make_sample_procedure()

        seq1 = self.sequencer.create_sequence(proc1, session_id="sess_det")
        seq2 = self.sequencer.create_sequence(proc2, session_id="sess_det")

        self.assertEqual(seq1.current_step_id, seq2.current_step_id)
        self.assertEqual(seq1.pending_steps, seq2.pending_steps)

        self.mock_adapter.configure_step(step_id="step_read_map", actual_outcome=ObservationResultType.NORMAL)
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")

        res1 = self.sequencer.execute_current_step(seq1, proc1, descriptor=desc)
        res2 = self.sequencer.execute_current_step(seq2, proc2, descriptor=desc)

        self.assertEqual(res1.actual_outcome, res2.actual_outcome)
        self.assertEqual(res1.branch_decision, res2.branch_decision)
        self.assertEqual(seq1.current_step_id, seq2.current_step_id)

    # -----------------------------------------------------------------
    # Test AB: Failure isolation
    # -----------------------------------------------------------------
    def test_ab_failure_isolation(self):
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)

        # Step 1 fails with NRC
        self.mock_adapter.configure_step(
            step_id="step_read_map",
            status="NRC",
            nrc_code="22",
            actual_outcome=ObservationResultType.ABNORMAL,
        )
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")
        res = self.sequencer.execute_current_step(seq, proc, descriptor=desc)

        # Failure is captured cleanly in step execution without throwing unhandled exceptions
        self.assertEqual(res.execution_status, "NRC")
        self.assertIn("step_read_map", seq.step_executions)
        self.assertEqual(seq.step_executions["step_read_map"].result.error_state, "Negative Response Code 0x22")

    # -----------------------------------------------------------------
    # Test AC: Graph execution-event integration
    # -----------------------------------------------------------------
    def test_ac_graph_execution_event_integration(self):
        graph = DiagnosticGraph(vehicle_id="vehicle:TEST_VIN_123")
        graph.add_node(GraphNode(node_id="ecu:ECM", node_type=GraphNodeType.ECU, label="Engine Control Module"))

        graph_sequencer = AutomatedTestSequencer(
            read_only_adapter=self.mock_adapter,
            diagnostic_graph=graph,
        )
        proc = make_sample_procedure()
        seq = graph_sequencer.create_sequence(proc)

        self.mock_adapter.configure_step(step_id="step_read_map", actual_outcome=ObservationResultType.NORMAL)
        desc = SequenceActionDescriptor(target_ecu="ECM", service_id="01", identifier="0B")

        graph_sequencer.execute_current_step(seq, proc, descriptor=desc)

        # Graph should now contain the new observation node and edge
        obs_nodes = [n for n in graph.nodes.values() if n.node_type == GraphNodeType.OBSERVATION]
        self.assertEqual(len(obs_nodes), 1)
        self.assertIn("step_read_map", obs_nodes[0].node_id)
        self.assertEqual(obs_nodes[0].properties.get("outcome"), "NORMAL")

    # -----------------------------------------------------------------
    # Test AD: Bounded acquisition limits enforced
    # -----------------------------------------------------------------
    def test_ad_bounded_acquisition_limits(self):
        adapter = ReadOnlyAcquisitionAdapter()
        proc = make_sample_procedure()
        seq = self.sequencer.create_sequence(proc)
        seq.policy.max_acquisition_duration_s = 5.0
        step = proc.steps["step_read_map"]

        # Request exceeding max duration
        desc = SequenceActionDescriptor(
            target_ecu="ECM",
            service_id="22",
            identifier="F190",
            acquisition_duration_s=15.0,
        )
        res = adapter.execute(step, desc, seq)
        self.assertEqual(res.execution_status, "BOUNDS_EXCEEDED")
        self.assertIn("exceeds maximum allowed", res.error_state or "")

    # -----------------------------------------------------------------
    # Test AE: Large procedure performance
    # -----------------------------------------------------------------
    def test_ae_large_procedure_performance(self):
        ctx = DiagnosticProcedureContext(vehicle_id="veh_large", session_id="sess_large")
        large_proc = DiagnosticProcedure(procedure_id="proc_large", context=ctx, title="Large", objective="Perf")

        # Create 100 sequential steps
        for i in range(1, 101):
            s = DiagnosticStep(
                step_id=f"step_{i:03d}",
                sequence=i,
                title=f"Step {i}",
                technician_instruction=f"Instruction {i}",
                purpose=f"Purpose {i}",
                rationale=f"Rationale {i}",
                target_ecu="ECM",
                execution_mode=StepExecutionMode.OBSERVATIONAL,
            )
            large_proc.add_step(s)
        large_proc.transition_to(ProcedureState.READY)

        t0 = time.time()
        seq = self.sequencer.create_sequence(large_proc)
        t_create = time.time() - t0

        self.assertLess(t_create, 0.2, f"Sequence creation took too long: {t_create:.4f}s")
        self.assertEqual(len(seq.pending_steps), 100)

    # -----------------------------------------------------------------
    # Test AF: No duplicate transport architecture
    # -----------------------------------------------------------------
    def test_af_no_duplicate_transport_architecture(self):
        # Verify ReadOnlyAcquisitionAdapter delegates directly to DiagnosticTransactionManager
        adapter = ReadOnlyAcquisitionAdapter()
        self.assertTrue(hasattr(adapter, "txn_manager"))
        self.assertTrue(hasattr(adapter, "safety_policy"))
        # Ensures no raw serial or secondary MockSerial implementation in automated_test_sequencer
        import automated_test_sequencer
        self.assertFalse(hasattr(automated_test_sequencer, "MockSerial"))
        self.assertFalse(hasattr(automated_test_sequencer, "SerialIOThread"))


if __name__ == "__main__":
    unittest.main()
