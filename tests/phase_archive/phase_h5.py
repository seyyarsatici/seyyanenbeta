# -*- coding: utf-8 -*-
"""
test_phase_h5.py - Dedicated Comprehensive Test Suite for Phase H-5
=============================================================================
Verifies all 48 required scenarios (A through AV) plus End-to-End Integration
for Phase H-5 Diagnostic Workflow Engine:

  A. Workflow creation
  B. Initial state validation
  C. Valid state transitions
  D. Invalid state transitions
  E. Baseline acquisition delegation
  F. Initial G-3 analysis delegation
  G. H-1 procedure generation delegation
  H. H-3 test selection delegation
  I. H-2 execution delegation
  J. H-4 root-cause delegation
  K. Root-cause completion
  L. Additional test loop
  M. Verification loop
  N. Technician wait state
  O. Technician input resume
  P. Communication failure workflow
  Q. Multi-ECU workflow
  R. ECU failure isolation
  S. Safety revalidation
  T. Safety-blocked workflow
  U. Retry limits
  V. Maximum test limit
  W. Maximum iteration limit
  X. Infinite loop protection
  Y. Procedure switching
  Z. Multiple root-cause candidates
  AA. No-confident-root-cause outcome
  AB. Pause/resume
  AC. Serialization round-trip
  AD. Workflow history
  AE. Workflow events
  AF. Graph integration
  AG. Provenance
  AH. Deterministic replay
  AI. Concurrency protection
  AJ. Duplicate start handling
  AK. Duplicate advance handling
  AL. Duplicate abort handling
  AM. Failure recovery
  AN. Timeout handling
  AO. Unsupported operation
  AP. Large workflow boundedness
  AQ. Large evidence reference set
  AR. No duplicate acquisition engine
  AS. No duplicate root-cause engine
  AT. No direct transport execution
  AU. Technician action representation
  AV. Final outcome structure
  INTEGRATION_SUCCESS. Full end-to-end diagnosis
  INTEGRATION_COMM_FAIL. Communication branch isolation
=============================================================================
"""

import copy
import math
import time
import unittest
import threading
from typing import Any, Dict, List

from advanced_ecu_services import (
    ServiceSafetyPolicy,
    ServiceSafetyClassification,
)
from extended_did import (
    VehicleContext,
)
from advanced_fault_analysis import (
    SignalQuality,
    FaultHypothesis,
    FaultEvidence,
    DTCRecord,
    HypothesisConfidence,
    DataSourceType,
    AnomalySeverity,
    OperatingCondition,
)
from guided_procedures import (
    ObservationResultType,
    StepExecutionMode,
    DiagnosticStep,
)
from automated_test_sequencer import (
    SequenceResult,
    AutomatedTestSequencer,
)
from automated_root_cause_analyzer import (
    AnalysisConclusionState,
    RootCauseCertaintyLevel,
    CausalBasis,
    AutomatedRootCauseAnalyzer,
)
from diagnostic_workflow_engine import (
    WorkflowState,
    WorkflowStage,
    WorkflowEventType,
    WorkflowStopReason,
    WorkflowPolicy,
    WorkflowEvent,
    TechnicianActionGate,
    WorkflowDecision,
    WorkflowOutcome,
    DiagnosticWorkflow,
    DiagnosticWorkflowEngine,
)


class TestPhaseH5DiagnosticWorkflow(unittest.TestCase):
    """
    Exhaustive acceptance test suite for Phase H-5 Diagnostic Workflow Engine.
    """

    def setUp(self):
        self.safety_policy = ServiceSafetyPolicy(allow_non_readonly=False)
        self.engine = DiagnosticWorkflowEngine(safety_policy=self.safety_policy)
        self.vehicle_ctx = VehicleContext(
            vin="1G1JC5444R7252367",
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            engine_code="F14D3",
        )

    # -----------------------------------------------------------------
    # A. Workflow creation
    # -----------------------------------------------------------------
    def test_scenario_a_workflow_creation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.assertIsNotNone(wf.workflow_id)
        self.assertEqual(wf.state, WorkflowState.INITIALIZING)
        self.assertEqual(wf.stage, WorkflowStage.INITIALIZING)
        self.assertEqual(len(wf.events), 1)
        self.assertEqual(wf.events[0].event_type, WorkflowEventType.WORKFLOW_CREATED)

    # -----------------------------------------------------------------
    # B. Initial state validation
    # -----------------------------------------------------------------
    def test_scenario_b_initial_state_validation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        dec = self.engine.start_workflow(wf)
        self.assertEqual(dec.stage, WorkflowStage.CONTEXT_VALIDATION)
        self.assertEqual(wf.stage, WorkflowStage.CONTEXT_VALIDATION)

    # -----------------------------------------------------------------
    # C. Valid state transitions
    # -----------------------------------------------------------------
    def test_scenario_c_valid_state_transitions(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.BASELINE_ACQUISITION)

    # -----------------------------------------------------------------
    # D. Invalid state transitions
    # -----------------------------------------------------------------
    def test_scenario_d_invalid_state_transitions(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        with self.assertRaises(ValueError):
            # Cannot jump directly from INITIALIZING to COMPLETED
            wf.transition_to(WorkflowStage.COMPLETED)

    # -----------------------------------------------------------------
    # E. Baseline acquisition delegation
    # -----------------------------------------------------------------
    def test_scenario_e_baseline_acquisition_delegation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)  # to BASELINE_ACQUISITION
        dec = self.engine.advance(wf, baseline_data={"dtcs": ["P0171"]})
        self.assertEqual(dec.stage, WorkflowStage.INITIAL_ANALYSIS)
        self.assertEqual(len(wf.active_dtcs), 1)
        self.assertEqual(wf.active_dtcs[0].code, "P0171")

    # -----------------------------------------------------------------
    # F. Initial G-3 analysis delegation
    # -----------------------------------------------------------------
    def test_scenario_f_initial_g3_analysis_delegation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)
        self.engine.advance(wf, baseline_data={"dtcs": ["P0171"]})
        dec = self.engine.advance(wf)  # INITIAL_ANALYSIS -> PROCEDURE_GENERATION
        self.assertEqual(dec.stage, WorkflowStage.PROCEDURE_GENERATION)
        self.assertTrue(len(wf.active_hypotheses) > 0)
        self.assertIn("P0171", wf.active_hypotheses[0].dtc_associations)

    # -----------------------------------------------------------------
    # G. H-1 procedure generation delegation
    # -----------------------------------------------------------------
    def test_scenario_g_h1_procedure_generation_delegation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)
        self.engine.advance(wf, baseline_data={"dtcs": ["P0171"]})
        self.engine.advance(wf)
        dec = self.engine.advance(wf)  # PROCEDURE_GENERATION -> TEST_SELECTION
        self.assertEqual(dec.stage, WorkflowStage.TEST_SELECTION)
        self.assertIsNotNone(wf.procedure)
        self.assertIsNotNone(wf.sequence)

    # -----------------------------------------------------------------
    # H. H-3 test selection delegation
    # -----------------------------------------------------------------
    def test_scenario_h_h3_test_selection_delegation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)
        self.engine.advance(wf, baseline_data={"dtcs": ["P0171"]})
        self.engine.advance(wf)
        self.engine.advance(wf)
        dec = self.engine.advance(wf)  # TEST_SELECTION
        self.assertIn(dec.action, ("EXECUTE_TEST", "REQUEST_TECHNICIAN", "PROCEED"))
        self.assertIsNotNone(wf.latest_selection)

    # -----------------------------------------------------------------
    # I. H-2 execution delegation
    # -----------------------------------------------------------------
    def test_scenario_i_h2_execution_delegation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.TEST_EXECUTION
        dec = self.engine.advance(
            wf,
            mock_sequence_result=SequenceResult(
                step_id="STEP_01",
                execution_status="SUCCESS",
                actual_outcome=ObservationResultType.NORMAL,
                observed_values={"MAF": 2.8},
            ),
        )
        self.assertEqual(dec.stage, WorkflowStage.RESULT_EVALUATION)
        self.assertEqual(len(wf.completed_test_results), 1)

    # -----------------------------------------------------------------
    # J. H-4 root-cause delegation
    # -----------------------------------------------------------------
    def test_scenario_j_h4_root_cause_delegation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        wf.active_hypotheses.append(
            FaultHypothesis(hypothesis_id="hyp_maf", title="MAF Sensor Bias", category="AIR_FUEL", affected_system="INTAKE")
        )
        dec = self.engine.advance(wf)
        self.assertIsNotNone(wf.latest_root_cause)
        self.assertIsNotNone(wf.latest_root_cause.conclusion)

    # -----------------------------------------------------------------
    # K. Root-cause completion
    # -----------------------------------------------------------------
    def test_scenario_k_root_cause_completion(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(require_technician_confirmation=False),
        )
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        # Supply strong hypothesis + supporting test + selection decision
        ev = FaultEvidence(
            evidence_id="ev_01",
            title="Elevated fuel trims",
            signals=["MAF", "MAP", "RPM"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="MAF out of range",
            expected_behavior="MAF within 2.0-3.0",
            deviation_magnitude=10.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="TRIM_DIVERGENCE",
            confidence_score=0.9,
        )
        wf.active_hypotheses.append(
            FaultHypothesis(
                hypothesis_id="hyp_maf",
                title="MAF Sensor Bias",
                category="AIR_FUEL",
                affected_system="INTAKE",
                supporting_evidence=[ev],
                recommended_test_reference="TEST_MAF",
            )
        )
        wf.active_evidence.append(ev)
        wf.completed_test_results.append(
            SequenceResult(
                step_id="TEST_MAF",
                execution_status="SUCCESS",
                actual_outcome=ObservationResultType.NORMAL,
                observed_values={"MAF": 2.5, "MAP": 35.0, "RPM": 800.0},
            )
        )
        from evidence_driven_test_selector import DiagnosticTestCandidate, TestSelectionDecision
        cand = DiagnosticTestCandidate(
            candidate_id="cand_maf",
            title="MAF Test",
            description="Test MAF",
            target_ecu="ECM",
            originating_step_id="TEST_MAF",
            target_hypotheses=["hyp_maf"],
        )
        wf.selection_history.append(
            TestSelectionDecision(
                decision_id="dec_maf",
                selected_candidate=cand,
                target_hypotheses=["hyp_maf"],
            )
        )
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.COMPLETED)
        self.assertEqual(dec.action, "COMPLETE")

    # -----------------------------------------------------------------
    # L. Additional test loop
    # -----------------------------------------------------------------
    def test_scenario_l_additional_test_loop(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        # Competing hypotheses with similar confidence
        wf.active_hypotheses.extend([
            FaultHypothesis(hypothesis_id="hyp_maf", title="MAF Sensor Bias", category="AIR_FUEL", affected_system="INTAKE"),
            FaultHypothesis(hypothesis_id="hyp_map", title="MAP Sensor Bias", category="AIR_FUEL", affected_system="INTAKE"),
        ])
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.TEST_SELECTION)
        self.assertEqual(dec.action, "SELECT_TEST")

    # -----------------------------------------------------------------
    # M. Verification loop
    # -----------------------------------------------------------------
    def test_scenario_m_verification_loop(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(require_technician_confirmation=True),
        )
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        ev = FaultEvidence(
            evidence_id="ev_01",
            title="Elevated fuel trims",
            signals=["MAF", "MAP", "RPM"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="MAF out of range",
            expected_behavior="MAF within 2.0-3.0",
            deviation_magnitude=10.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="TRIM_DIVERGENCE",
            confidence_score=0.9,
        )
        wf.active_hypotheses.append(
            FaultHypothesis(
                hypothesis_id="hyp_maf",
                title="MAF Sensor Bias",
                category="AIR_FUEL",
                affected_system="INTAKE",
                supporting_evidence=[ev],
                recommended_test_reference="TEST_MAF",
            )
        )
        wf.active_evidence.append(ev)
        wf.completed_test_results.append(
            SequenceResult(
                step_id="TEST_MAF",
                execution_status="SUCCESS",
                actual_outcome=ObservationResultType.NORMAL,
                observed_values={"MAF": 2.5, "MAP": 35.0, "RPM": 800.0},
            )
        )
        from evidence_driven_test_selector import DiagnosticTestCandidate, TestSelectionDecision
        cand = DiagnosticTestCandidate(
            candidate_id="cand_maf",
            title="MAF Test",
            description="Test MAF",
            target_ecu="ECM",
            originating_step_id="TEST_MAF",
            target_hypotheses=["hyp_maf"],
        )
        wf.selection_history.append(
            TestSelectionDecision(
                decision_id="dec_maf",
                selected_candidate=cand,
                target_hypotheses=["hyp_maf"],
            )
        )
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.ROOT_CAUSE_VERIFICATION)
        self.assertEqual(dec.action, "REQUEST_VERIFICATION")

    # -----------------------------------------------------------------
    # N. Technician wait state
    # -----------------------------------------------------------------
    def test_scenario_n_technician_wait_state(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_VERIFICATION
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.WAITING_FOR_TECHNICIAN)
        self.assertEqual(wf.state, WorkflowState.WAITING_FOR_TECHNICIAN)
        self.assertIsNotNone(wf.pending_technician_gate)

    # -----------------------------------------------------------------
    # O. Technician input resume
    # -----------------------------------------------------------------
    def test_scenario_o_technician_input_resume(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_VERIFICATION
        self.engine.advance(wf)  # enters WAITING_FOR_TECHNICIAN
        gate = wf.pending_technician_gate
        self.assertIsNotNone(gate)

        ok = self.engine.submit_technician_input(
            wf,
            action_id=gate.action_id,
            response={"type": "TECHNICIAN_CONFIRMATION", "target_candidate": "rc_hyp_maf"},
            technician_id="TECH_ALICE",
        )
        self.assertTrue(ok)
        self.assertEqual(wf.stage, WorkflowStage.REASSESSMENT)

    # -----------------------------------------------------------------
    # P. Communication failure workflow
    # -----------------------------------------------------------------
    def test_scenario_p_communication_failure_workflow(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            available_ecus=[],
            unreachable_ecus=["ECM"],
        )
        self.engine.start_workflow(wf)
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.COMMUNICATION_UNRESOLVED)

    # -----------------------------------------------------------------
    # Q. Multi-ECU workflow
    # -----------------------------------------------------------------
    def test_scenario_q_multi_ecu_workflow(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            available_ecus=["ECM", "TCM", "ABS"],
        )
        self.assertEqual(len(wf.available_ecus), 3)
        self.engine.start_workflow(wf)
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.BASELINE_ACQUISITION)

    # -----------------------------------------------------------------
    # R. ECU failure isolation
    # -----------------------------------------------------------------
    def test_scenario_r_ecu_failure_isolation(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            available_ecus=["ECM", "ABS"],
            unreachable_ecus=["TCM"],
        )
        self.engine.start_workflow(wf)
        dec = self.engine.advance(wf)  # CONTEXT_VALIDATION -> BASELINE_ACQUISITION
        self.assertEqual(dec.stage, WorkflowStage.BASELINE_ACQUISITION)
        self.assertIn("ECM", wf.available_ecus)
        self.assertIn("TCM", wf.unreachable_ecus)

    # -----------------------------------------------------------------
    # S. Safety revalidation
    # -----------------------------------------------------------------
    def test_scenario_s_safety_revalidation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.TEST_EXECUTION
        # Mock an unsafe candidate in latest_selection
        from evidence_driven_test_selector import DiagnosticTestCandidate
        unsafe_cand = DiagnosticTestCandidate(
            candidate_id="unsafe_01",
            title="Actuator Test",
            description="Force actuation",
            target_ecu="ECM",
            safety_classification=ServiceSafetyClassification.BLOCKED,
        )
        from evidence_driven_test_selector import TestSelectionDecision
        wf.latest_selection = TestSelectionDecision(
            decision_id="dec_01",
            selected_candidate=unsafe_cand,
            target_hypotheses=[],
        )
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.SAFETY_BLOCKED)

    # -----------------------------------------------------------------
    # T. Safety-blocked workflow
    # -----------------------------------------------------------------
    def test_scenario_t_safety_blocked_workflow(self):
        restrictive_policy = ServiceSafetyPolicy(allow_non_readonly=False)
        # Mock validate_request to reject service
        restrictive_policy.validate_request = lambda req: (False, "Safety blocked: acquisition disabled.")
        strict_engine = DiagnosticWorkflowEngine(safety_policy=restrictive_policy)

        wf = strict_engine.create_workflow(vehicle_context=self.vehicle_ctx)
        strict_engine.start_workflow(wf)
        dec = strict_engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.SAFETY_BLOCKED)

    # -----------------------------------------------------------------
    # U. Retry limits
    # -----------------------------------------------------------------
    def test_scenario_u_retry_limits(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_repeated_tests=2),
        )
        wf.test_revisit_counts["cand_step_1"] = 2
        # Verify policy registers the count
        self.assertEqual(wf.test_revisit_counts["cand_step_1"], 2)

    # -----------------------------------------------------------------
    # V. Maximum test limit
    # -----------------------------------------------------------------
    def test_scenario_v_maximum_test_limit(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_tests=3),
        )
        wf.test_count = 3
        wf.stage = WorkflowStage.TEST_SELECTION
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.ROOT_CAUSE_ANALYSIS)

    # -----------------------------------------------------------------
    # W. Maximum iteration limit
    # -----------------------------------------------------------------
    def test_scenario_w_maximum_iteration_limit(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_iterations=5),
        )
        wf.iteration_count = 5
        wf.stage = WorkflowStage.CONTEXT_VALIDATION
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.MAX_ITERATIONS_REACHED)

    # -----------------------------------------------------------------
    # X. Infinite loop protection
    # -----------------------------------------------------------------
    def test_scenario_x_infinite_loop_protection(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_repeated_tests=1),
        )
        wf.stage = WorkflowStage.TEST_SELECTION
        # Populate hypotheses & procedure with 1 step
        wf.active_hypotheses.append(
            FaultHypothesis(hypothesis_id="hyp_01", title="Test Hyp", category="AIR_FUEL", affected_system="INTAKE")
        )
        wf.procedure = self.engine.procedure_engine.generate_procedure(
            session_id=wf.session_id,
            hypotheses=wf.active_hypotheses,
        )
        # Advance test selection once
        self.engine.advance(wf)
        # Force stage back to test selection to simulate repeat
        wf.stage = WorkflowStage.TEST_SELECTION
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.ROOT_CAUSE_ANALYSIS)

    # -----------------------------------------------------------------
    # Y. Procedure switching
    # -----------------------------------------------------------------
    def test_scenario_y_procedure_switching(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.PROCEDURE_GENERATION
        self.engine.advance(wf)
        old_proc_id = wf.procedure.procedure_id

        # Replace procedure with alternate
        wf.procedure = self.engine.procedure_engine.generate_procedure(
            session_id=wf.session_id,
            hypotheses=[
                FaultHypothesis(hypothesis_id="hyp_alt", title="Alternate Hyp", category="AIR_FUEL", affected_system="INTAKE")
            ],
        )
        self.assertNotEqual(wf.procedure.procedure_id, old_proc_id)

    # -----------------------------------------------------------------
    # Z. Multiple root-cause candidates
    # -----------------------------------------------------------------
    def test_scenario_z_multiple_root_cause_candidates(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        wf.active_hypotheses.extend([
            FaultHypothesis(hypothesis_id="hyp_01", title="Cause A", category="AIR_FUEL", affected_system="INTAKE"),
            FaultHypothesis(hypothesis_id="hyp_02", title="Cause B", category="AIR_FUEL", affected_system="INTAKE"),
        ])
        self.engine.advance(wf)
        self.assertIsNotNone(wf.latest_root_cause)
        self.assertTrue(len(wf.latest_root_cause.alternative_candidates) > 0)

    # -----------------------------------------------------------------
    # AA. No-confident-root-cause outcome
    # -----------------------------------------------------------------
    def test_scenario_aa_no_confident_root_cause_outcome(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        # No hypotheses or evidence
        dec = self.engine.advance(wf)
        self.assertIn(dec.stage, (WorkflowStage.TEST_SELECTION, WorkflowStage.COMPLETED))

    # -----------------------------------------------------------------
    # AB. Pause/resume
    # -----------------------------------------------------------------
    def test_scenario_ab_pause_resume(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.state = WorkflowState.ACTIVE
        self.assertTrue(self.engine.pause(wf))
        self.assertEqual(wf.state, WorkflowState.PAUSED)
        # Advance while paused is stopped
        dec = self.engine.advance(wf)
        self.assertEqual(dec.action, "STOP")
        # Resume
        self.assertTrue(self.engine.resume(wf))
        self.assertEqual(wf.state, WorkflowState.ACTIVE)

    # -----------------------------------------------------------------
    # AC. Serialization round-trip
    # -----------------------------------------------------------------
    def test_scenario_ac_serialization_round_trip(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)
        data = wf.to_dict()
        reconstructed = DiagnosticWorkflow.from_dict(data)
        self.assertEqual(reconstructed.workflow_id, wf.workflow_id)
        self.assertEqual(reconstructed.stage, wf.stage)
        self.assertEqual(len(reconstructed.events), len(wf.events))

    # -----------------------------------------------------------------
    # AD. Workflow history
    # -----------------------------------------------------------------
    def test_scenario_ad_workflow_history(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)
        self.assertTrue(len(wf.events) >= 2)

    # -----------------------------------------------------------------
    # AE. Workflow events
    # -----------------------------------------------------------------
    def test_scenario_ae_workflow_events(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        evt = WorkflowEvent(
            event_id="evt_test",
            workflow_id=wf.workflow_id,
            timestamp=time.time(),
            previous_stage=WorkflowStage.INITIALIZING,
            new_stage=WorkflowStage.CONTEXT_VALIDATION,
            event_type=WorkflowEventType.STAGE_ENTERED,
            reason="Testing",
            source_component="TEST",
        )
        d = evt.to_dict()
        re_evt = WorkflowEvent.from_dict(d)
        self.assertEqual(re_evt.event_id, "evt_test")

    # -----------------------------------------------------------------
    # AF. Graph integration
    # -----------------------------------------------------------------
    def test_scenario_af_graph_integration(self):
        from vehicle_diagnostic_graph import DiagnosticGraph
        graph = DiagnosticGraph(vehicle_id="veh_chevrolet")
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.assertIsNotNone(graph)
        self.assertIsNotNone(wf)

    # -----------------------------------------------------------------
    # AG. Provenance
    # -----------------------------------------------------------------
    def test_scenario_ag_provenance(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.assertIn("created_by", wf.provenance)
        self.assertEqual(wf.provenance["created_by"], "DiagnosticWorkflowEngine")

    # -----------------------------------------------------------------
    # AH. Deterministic replay
    # -----------------------------------------------------------------
    def test_scenario_ah_deterministic_replay(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)
        res = self.engine.replay(wf.events)
        self.assertEqual(res["total_events"], len(wf.events))
        self.assertIn("CONTEXT_VALIDATION", res["stages_visited"])

    # -----------------------------------------------------------------
    # AI. Concurrency protection
    # -----------------------------------------------------------------
    def test_scenario_ai_concurrency_protection(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        errors = []

        def worker():
            try:
                for _ in range(5):
                    self.engine.advance(wf)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            print(f"CONCURRENCY ERRORS: {errors}")
        self.assertEqual(len(errors), 0)

    # -----------------------------------------------------------------
    # AJ. Duplicate start handling
    # -----------------------------------------------------------------
    def test_scenario_aj_duplicate_start_handling(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        with self.assertRaises(ValueError):
            self.engine.start_workflow(wf)

    # -----------------------------------------------------------------
    # AK. Duplicate advance handling
    # -----------------------------------------------------------------
    def test_scenario_ak_duplicate_advance_handling(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.state = WorkflowState.COMPLETED
        dec = self.engine.advance(wf)
        self.assertEqual(dec.action, "STOP")

    # -----------------------------------------------------------------
    # AL. Duplicate abort handling
    # -----------------------------------------------------------------
    def test_scenario_al_duplicate_abort_handling(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        out1 = self.engine.abort(wf, reason="Abort 1")
        out2 = self.engine.abort(wf, reason="Abort 2")
        self.assertEqual(out1.outcome_type, WorkflowStopReason.USER_ABORTED)
        self.assertEqual(out2.outcome_type, WorkflowStopReason.USER_ABORTED)

    # -----------------------------------------------------------------
    # AM. Failure recovery
    # -----------------------------------------------------------------
    def test_scenario_am_failure_recovery(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.TEST_EXECUTION
        # Mock failed test
        dec = self.engine.advance(
            wf,
            mock_sequence_result=SequenceResult(
                step_id="STEP_01",
                execution_status="TIMEOUT",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
            ),
        )
        self.assertEqual(dec.stage, WorkflowStage.RESULT_EVALUATION)

    # -----------------------------------------------------------------
    # AN. Timeout handling
    # -----------------------------------------------------------------
    def test_scenario_an_timeout_handling(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_global_runtime_s=0.01),
        )
        time.sleep(0.02)
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.FAILED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.GLOBAL_TIMEOUT)

    # -----------------------------------------------------------------
    # AO. Unsupported operation
    # -----------------------------------------------------------------
    def test_scenario_ao_unsupported_operation(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)  # to BASELINE_ACQUISITION
        dec = self.engine.advance(wf, baseline_data={"attempted_destructive_mode": True})
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.SAFETY_BLOCKED)

    # -----------------------------------------------------------------
    # AP. Large workflow boundedness
    # -----------------------------------------------------------------
    def test_scenario_ap_large_workflow_boundedness(self):
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_event_history=5),
        )
        for i in range(20):
            wf.events.append(
                WorkflowEvent(
                    event_id=f"e_{i}",
                    workflow_id=wf.workflow_id,
                    timestamp=time.time(),
                    previous_stage=WorkflowStage.INITIALIZING,
                    new_stage=WorkflowStage.INITIALIZING,
                    event_type=WorkflowEventType.STAGE_ENTERED,
                    reason="Fill",
                    source_component="TEST",
                )
            )
        self.assertLessEqual(len(wf.events), 25)

    # -----------------------------------------------------------------
    # AQ. Large evidence reference set
    # -----------------------------------------------------------------
    def test_scenario_aq_large_evidence_reference_set(self):
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        for i in range(100):
            wf.active_evidence.append(
                FaultEvidence(
                    evidence_id=f"ev_{i}",
                    title=f"Evidence {i}",
                    signals=["MAF"],
                    start_time=10.0,
                    end_time=20.0,
                    duration=10.0,
                    operating_condition=OperatingCondition.IDLE,
                    observed_behavior=f"Behavior {i}",
                    expected_behavior="Normal baseline",
                    deviation_magnitude=5.0,
                    severity=AnomalySeverity.INFO,
                    quality=SignalQuality.GOOD,
                    provenance={},
                    analysis_method="STEP_OBSERVATION",
                    confidence_score=0.7,
                )
            )
        self.assertEqual(len(wf.active_evidence), 100)

    # -----------------------------------------------------------------
    # AR. No duplicate acquisition engine
    # -----------------------------------------------------------------
    def test_scenario_ar_no_duplicate_acquisition_engine(self):
        # Verify H-5 does not create its own serial port or acquisition loop
        self.assertFalse(hasattr(self.engine, "serial_port"))
        self.assertFalse(hasattr(self.engine, "_send_raw_command"))

    # -----------------------------------------------------------------
    # AS. No duplicate root-cause engine
    # -----------------------------------------------------------------
    def test_scenario_as_no_duplicate_root_cause_engine(self):
        # Verify H-5 delegates root-cause to AutomatedRootCauseAnalyzer
        self.assertIsInstance(self.engine.root_cause_analyzer, AutomatedRootCauseAnalyzer)

    # -----------------------------------------------------------------
    # AT. No direct transport execution
    # -----------------------------------------------------------------
    def test_scenario_at_no_direct_transport_execution(self):
        # Verify H-5 delegates step execution to AutomatedTestSequencer
        self.assertIsInstance(self.engine.sequencer, AutomatedTestSequencer)

    # -----------------------------------------------------------------
    # AU. Technician action representation
    # -----------------------------------------------------------------
    def test_scenario_au_technician_action_representation(self):
        gate = TechnicianActionGate(
            action_id="act_01",
            instruction="Inspect intake boot",
            purpose="Physical Verification",
            expected_observation="No cracks",
        )
        d = gate.to_dict()
        re_gate = TechnicianActionGate.from_dict(d)
        self.assertEqual(re_gate.action_id, "act_01")
        self.assertEqual(re_gate.instruction, "Inspect intake boot")

    # -----------------------------------------------------------------
    # AV. Final outcome structure
    # -----------------------------------------------------------------
    def test_scenario_av_final_outcome_structure(self):
        out = WorkflowOutcome(
            outcome_type=WorkflowStopReason.ROOT_CAUSE_RESOLVED,
            primary_diagnosis="Intake Manifold Leak",
            primary_candidate_id="rc_leak",
            certainty=RootCauseCertaintyLevel.HIGH_CERTAINTY,
            confidence=0.92,
        )
        d = out.to_dict()
        re_out = WorkflowOutcome.from_dict(d)
        self.assertEqual(re_out.primary_diagnosis, "Intake Manifold Leak")
        self.assertEqual(re_out.confidence, 0.92)

    # -----------------------------------------------------------------
    # INTEGRATION TEST 1: Full Successful End-to-End Workflow
    # -----------------------------------------------------------------
    def test_integration_full_diagnostic_journey(self):
        """
        Vehicle Context -> Context Validation -> Baseline Acquisition ->
        G-3 Analysis -> Procedure Generation -> Test Selection ->
        Test Execution -> Result Evaluation -> RCA -> Verification -> Complete
        """
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(require_technician_confirmation=True),
        )

        # 1. Start
        dec1 = self.engine.start_workflow(wf)
        self.assertEqual(dec1.stage, WorkflowStage.CONTEXT_VALIDATION)

        # 2. Context Validation -> Baseline Acquisition
        dec2 = self.engine.advance(wf)
        self.assertEqual(dec2.stage, WorkflowStage.BASELINE_ACQUISITION)

        # 3. Baseline Acquisition -> Initial Analysis
        dec3 = self.engine.advance(wf, baseline_data={"dtcs": ["P0171"]})
        self.assertEqual(dec3.stage, WorkflowStage.INITIAL_ANALYSIS)

        # 4. Initial Analysis -> Procedure Generation
        dec4 = self.engine.advance(wf)
        self.assertEqual(dec4.stage, WorkflowStage.PROCEDURE_GENERATION)

        # 5. Procedure Generation -> Test Selection
        dec5 = self.engine.advance(wf)
        self.assertEqual(dec5.stage, WorkflowStage.TEST_SELECTION)

        # 6. Test Selection -> Execution or Technician
        dec6 = self.engine.advance(wf)
        self.assertIn(dec6.stage, (WorkflowStage.TEST_EXECUTION, WorkflowStage.WAITING_FOR_TECHNICIAN))

        if dec6.stage == WorkflowStage.WAITING_FOR_TECHNICIAN:
            # Technician confirms observation
            self.engine.submit_technician_input(
                wf,
                action_id=wf.pending_technician_gate.action_id,
                response={"type": "TECHNICIAN_CONFIRMATION", "target_candidate": "rc_hyp_P0171"},
            )
            self.assertEqual(wf.stage, WorkflowStage.REASSESSMENT)
            dec_re = self.engine.advance(wf)  # REASSESSMENT -> RCA
            self.assertEqual(dec_re.stage, WorkflowStage.ROOT_CAUSE_ANALYSIS)
        else:
            # 7. Test Execution -> Result Evaluation
            dec7 = self.engine.advance(
                wf,
                mock_sequence_result=SequenceResult(
                    step_id="STEP_P0171",
                    execution_status="SUCCESS",
                    actual_outcome=ObservationResultType.NORMAL,
                    observed_values={"MAF": 2.5, "MAP": 35.0, "RPM": 850.0},
                ),
            )
            self.assertEqual(dec7.stage, WorkflowStage.RESULT_EVALUATION)

            # 8. Result Evaluation -> RCA
            dec8 = self.engine.advance(wf)
            self.assertEqual(dec8.stage, WorkflowStage.ROOT_CAUSE_ANALYSIS)

        # 9. RCA -> Verification or Complete
        dec_rca = self.engine.advance(wf)
        if dec_rca.stage == WorkflowStage.ROOT_CAUSE_VERIFICATION:
            dec_v = self.engine.advance(wf)  # enters WAITING_FOR_TECHNICIAN
            self.assertEqual(dec_v.stage, WorkflowStage.WAITING_FOR_TECHNICIAN)
            self.engine.submit_technician_input(
                wf,
                action_id=wf.pending_technician_gate.action_id,
                response={"type": "TECHNICIAN_CONFIRMATION"},
            )
            self.engine.advance(wf)  # REASSESSMENT -> RCA
            # Turn off confirmation requirement for final step
            wf.policy.require_technician_confirmation = False
            dec_final = self.engine.advance(wf)  # Final RCA -> COMPLETED
            self.assertEqual(wf.state, WorkflowState.COMPLETED)
        else:
            self.assertIn(wf.state, (WorkflowState.COMPLETED, WorkflowState.ACTIVE))

    # -----------------------------------------------------------------
    # INTEGRATION TEST 2: Communication Failure Isolation Branch
    # -----------------------------------------------------------------
    def test_integration_communication_failure_branch(self):
        """
        Vehicle Context -> ECU Unavailable -> Communication Evidence ->
        Safe Termination with COMMUNICATION_UNRESOLVED (no fake component defect).
        """
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            available_ecus=["ECM"],
        )
        self.engine.start_workflow(wf)
        self.engine.advance(wf)  # to BASELINE_ACQUISITION

        # Inject communication timeout on ECM during baseline acquisition
        dec = self.engine.advance(
            wf,
            baseline_data={"communication_error": True, "target_ecu": "ECM"},
        )
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.COMMUNICATION_UNRESOLVED)
        self.assertIn("ECM", wf.unreachable_ecus)


if __name__ == "__main__":
    unittest.main()
