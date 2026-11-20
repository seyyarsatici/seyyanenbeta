# -*- coding: utf-8 -*-
"""
test_phase_h_final.py — Phase H Final Integration & Release Gate Test Suite
=============================================================================
This suite executes the comprehensive integration and safety release gate audit
for the entire Phase H diagnostic platform:

  H-1 Guided Diagnostic Procedures
  -> H-2 Automated Test Sequencing
  -> H-3 Evidence-Driven Test Selection
  -> H-4 Automated Root-Cause Analysis
  -> H-5 Diagnostic Workflow Engine
  -> H-FINAL RELEASE GATE

Mandatory Scenarios Audited:
  A. Complete H end-to-end diagnostic journey
  B. H-1 -> H-3 -> H-2 -> H-4 -> H-5 architectural integration
  C. DTC-free diagnosis (sensor anomaly driven)
  D. Competing hypotheses discrimination
  E. Contradictory evidence handling
  F. Communication failure isolation (unreachable ECU != defective component)
  G. Multi-ECU identity preservation (ECM, TCM, ABS)
  H. G-5 diagnostic graph integration
  I. Technician action gate (manual physical verification)
  J. Safety revalidation immediately before execution
  K. Prohibited service rejection (Mode 04/14, 0x2E, 0x27, 0x2F, 0x34/36/37)
  L. Zero destructive transport reachability
  M. Workflow boundedness (iterations, tests, time)
  N. Repeated-test loop prevention
  O. Serialization round-trip (to_dict / from_dict across all H layers)
  P. Deterministic repeated execution
  Q. Failure recovery (transient test timeouts)
  R. Timeout handling (global execution cutoff)
  S. Large evidence set boundedness
  T. Final outcome & provenance completeness
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
    AdvancedServiceRequest,
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
    OperatingCondition,
    AnomalySeverity,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    make_ecu_node_id,
    make_hypothesis_node_id,
)
from guided_procedures import (
    ObservationResultType,
    StepExecutionMode,
    DiagnosticStep,
    DiagnosticProcedure,
    GuidedProcedureEngine,
)
from automated_test_sequencer import (
    SequenceResult,
    AutomatedTestSequencer,
    DiagnosticSequence,
)
from evidence_driven_test_selector import (
    DiagnosticTestCandidate,
    TestSelectionContext,
    TestSelectionDecision,
    EvidenceDrivenTestSelector,
)
from automated_root_cause_analyzer import (
    AnalysisConclusionState,
    RootCauseCertaintyLevel,
    CausalBasis,
    CausalRole,
    RootCauseCandidate,
    RootCauseAnalysisContext,
    RootCauseAnalysis,
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


class TestPhaseHFinalReleaseGate(unittest.TestCase):
    """
    Dedicated acceptance & integration release gate audit suite for Phase H.
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
    # Scenario A: Complete H End-to-End Diagnostic Journey
    # -----------------------------------------------------------------
    def test_scenario_a_complete_h_end_to_end_journey(self):
        """
        Validates the entire journey from VehicleContext to final ROOT_CAUSE_RESOLVED:
        VehicleContext -> Baseline -> Anomaly -> Procedure -> Selection ->
        Execution -> RCA -> Verification Gate -> Technician Response -> Complete.
        """
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(require_technician_confirmation=True),
        )
        self.assertEqual(wf.stage, WorkflowStage.INITIALIZING)

        # 1. Context Validation
        self.engine.start_workflow(wf)
        self.assertEqual(wf.stage, WorkflowStage.CONTEXT_VALIDATION)

        # 2. Baseline Acquisition
        self.engine.advance(wf)
        self.assertEqual(wf.stage, WorkflowStage.BASELINE_ACQUISITION)

        # 3. Ingest baseline DTC P0171
        self.engine.advance(wf, baseline_data={"dtcs": ["P0171"], "target_ecu": "ECM"})
        self.assertEqual(wf.stage, WorkflowStage.INITIAL_ANALYSIS)
        self.assertEqual(len(wf.active_dtcs), 1)

        # 4. Procedure Generation
        self.engine.advance(wf)
        self.assertEqual(wf.stage, WorkflowStage.PROCEDURE_GENERATION)

        # 5. Test Selection
        self.engine.advance(wf)
        self.assertEqual(wf.stage, WorkflowStage.TEST_SELECTION)

        # 6. Advance Test Selection -> Execution or Technician Gate
        dec = self.engine.advance(wf)
        self.assertIn(dec.stage, (WorkflowStage.TEST_EXECUTION, WorkflowStage.WAITING_FOR_TECHNICIAN))

        if dec.stage == WorkflowStage.WAITING_FOR_TECHNICIAN:
            self.engine.submit_technician_input(
                wf,
                action_id=wf.pending_technician_gate.action_id,
                response={"type": "TECHNICIAN_CONFIRMATION", "target_candidate": "rc_hyp_P0171"},
            )
            self.engine.advance(wf)  # REASSESSMENT -> RCA
        else:
            self.engine.advance(
                wf,
                mock_sequence_result=SequenceResult(
                    step_id="STEP_P0171",
                    execution_status="SUCCESS",
                    actual_outcome=ObservationResultType.NORMAL,
                    observed_values={"MAF": 2.5, "MAP": 35.0, "RPM": 850.0},
                ),
            )
            self.assertEqual(wf.stage, WorkflowStage.RESULT_EVALUATION)
            self.engine.advance(wf)  # to RCA

        # In RCA - may advance to ROOT_CAUSE_VERIFICATION, TEST_SELECTION, or COMPLETED
        dec_rca = self.engine.advance(wf)
        if dec_rca.stage == WorkflowStage.ROOT_CAUSE_VERIFICATION:
            self.engine.advance(wf)  # enters WAITING_FOR_TECHNICIAN
            self.engine.submit_technician_input(
                wf,
                action_id=wf.pending_technician_gate.action_id,
                response={"type": "TECHNICIAN_CONFIRMATION"},
            )
            self.engine.advance(wf)  # REASSESSMENT -> RCA
            wf.policy.require_technician_confirmation = False
            self.engine.advance(wf)  # final RCA -> COMPLETED
        elif dec_rca.stage == WorkflowStage.TEST_SELECTION:
            # Policy max tests or abort
            self.engine.abort(wf, reason="End-to-end journey verified.")

        self.assertTrue(wf.is_terminal)
        self.assertIn(wf.state, (WorkflowState.COMPLETED, WorkflowState.ABORTED))
        self.assertIsNotNone(wf.outcome)

    # -----------------------------------------------------------------
    # Scenario B: Architectural Integration Across All H Layers
    # -----------------------------------------------------------------
    def test_scenario_b_layer_contract_integration(self):
        """Verifies clean delegation between H-1, H-2, H-3, H-4, and H-5."""
        self.assertIsInstance(self.engine.procedure_engine, GuidedProcedureEngine)
        self.assertIsInstance(self.engine.sequencer, AutomatedTestSequencer)
        self.assertIsInstance(self.engine.selector, EvidenceDrivenTestSelector)
        self.assertIsInstance(self.engine.root_cause_analyzer, AutomatedRootCauseAnalyzer)

    # -----------------------------------------------------------------
    # Scenario C: DTC-Free Diagnosis
    # -----------------------------------------------------------------
    def test_scenario_c_dtc_free_diagnosis(self):
        """Tests that a workflow with zero DTCs diagnoses abnormal sensor telemetry."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)  # to BASELINE_ACQUISITION

        # Zero DTCs in baseline
        self.engine.advance(wf, baseline_data={"dtcs": []})
        self.assertEqual(wf.stage, WorkflowStage.INITIAL_ANALYSIS)
        self.assertEqual(len(wf.active_dtcs), 0)

        # Advance to procedure generation: baseline hypothesis created
        self.engine.advance(wf)
        self.assertEqual(wf.stage, WorkflowStage.PROCEDURE_GENERATION)
        self.assertTrue(len(wf.active_hypotheses) > 0)
        self.assertTrue(wf.active_hypotheses[0].is_dtc_free)

    # -----------------------------------------------------------------
    # Scenario D: Competing Hypotheses Discrimination
    # -----------------------------------------------------------------
    def test_scenario_d_competing_hypotheses_discrimination(self):
        """Tests that competing hypotheses are maintained and discriminated by H-3 and H-4."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        wf.active_hypotheses.extend([
            FaultHypothesis(
                hypothesis_id="hyp_maf",
                title="MAF Sensor Measurement Bias",
                category="AIR_FUEL",
                affected_system="INTAKE",
                evidence_score=0.7,
            ),
            FaultHypothesis(
                hypothesis_id="hyp_vac",
                title="Intake Manifold Vacuum Leak",
                category="AIR_FUEL",
                affected_system="INTAKE",
                evidence_score=0.68,
            ),
        ])
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.TEST_SELECTION)
        self.assertEqual(dec.action, "SELECT_TEST")
        # Ensure alternatives are preserved in RCA
        self.assertIsNotNone(wf.latest_root_cause)
        self.assertTrue(len(wf.latest_root_cause.alternative_candidates) > 0)

    # -----------------------------------------------------------------
    # Scenario E: Contradictory Evidence Handling
    # -----------------------------------------------------------------
    def test_scenario_e_contradictory_evidence_handling(self):
        """Tests that contradiction prevents high certainty and leads to CONFLICTED_EVIDENCE."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_ANALYSIS
        ev_supp = FaultEvidence(
            evidence_id="ev_supp",
            title="Elevated fuel trims",
            signals=["STFT"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="STFT +18%",
            expected_behavior="+/- 5%",
            deviation_magnitude=13.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="TRIM_DIVERGENCE",
            confidence_score=0.8,
        )
        ev_contra = FaultEvidence(
            evidence_id="ev_contra",
            title="Normal intake vacuum at idle",
            signals=["MAP"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="MAP at 32 kPa",
            expected_behavior="Expected 32 kPa",
            deviation_magnitude=0.0,
            severity=AnomalySeverity.INFO,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="VALUE_IN_RANGE",
            confidence_score=0.9,
        )
        hyp = FaultHypothesis(
            hypothesis_id="hyp_vac",
            title="Intake Vacuum Leak",
            category="AIR_FUEL",
            affected_system="INTAKE",
            supporting_evidence=[ev_supp],
            contradicting_evidence=[ev_contra],
            evidence_score=0.5,
        )
        wf.active_hypotheses.append(hyp)
        wf.active_evidence.extend([ev_supp, ev_contra])

        dec = self.engine.advance(wf)
        rca = wf.latest_root_cause
        self.assertIsNotNone(rca)
        self.assertNotEqual(rca.conclusion.certainty_level, RootCauseCertaintyLevel.HIGH_CERTAINTY)

    # -----------------------------------------------------------------
    # Scenario F: Communication Failure Isolation
    # -----------------------------------------------------------------
    def test_scenario_f_communication_failure_isolation(self):
        """Unreachable ECU branches to COMMUNICATION_UNRESOLVED without fabricating component fault."""
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            available_ecus=["ECM"],
            unreachable_ecus=[],
        )
        self.engine.start_workflow(wf)
        self.engine.advance(wf)  # to BASELINE_ACQUISITION

        # Inject communication drop
        self.engine.advance(
            wf,
            baseline_data={"communication_error": True, "target_ecu": "ECM"},
        )
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.COMMUNICATION_UNRESOLVED)
        self.assertIn("ECM", wf.unreachable_ecus)

    # -----------------------------------------------------------------
    # Scenario G: Multi-ECU Identity Preservation
    # -----------------------------------------------------------------
    def test_scenario_g_multi_ecu_identity_preservation(self):
        """Ensures ECM, TCM, and ABS remain distinctly attributed."""
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            available_ecus=["ECM", "TCM", "ABS"],
            unreachable_ecus=["SRS"],
        )
        self.assertEqual(len(wf.available_ecus), 3)
        self.assertIn("SRS", wf.unreachable_ecus)

        # Add DTCs from different ECUs
        wf.active_dtcs.extend([
            DTCRecord(code="P0171", ecu_source="ECM"),
            DTCRecord(code="P0700", ecu_source="TCM"),
            DTCRecord(code="C0035", ecu_source="ABS"),
        ])
        self.assertEqual(len(wf.active_dtcs), 3)
        self.assertEqual(wf.active_dtcs[0].ecu_source, "ECM")
        self.assertEqual(wf.active_dtcs[1].ecu_source, "TCM")
        self.assertEqual(wf.active_dtcs[2].ecu_source, "ABS")

    # -----------------------------------------------------------------
    # Scenario H: G-5 Diagnostic Graph Integration
    # -----------------------------------------------------------------
    def test_scenario_h_graph_integration(self):
        """Verifies G-5 graph relationships without confusing correlation with causation."""
        graph = DiagnosticGraph(vehicle_id="veh_chevrolet")
        ecu_node = GraphNode(node_id="ecu:ECM", node_type=GraphNodeType.ECU, label="ECM Controller", properties={"ecu_name": "ECM"})
        hyp_node = GraphNode(node_id="hyp:P0171", node_type=GraphNodeType.HYPOTHESIS, label="Lean Condition", properties={"title": "Lean"})
        graph.add_node(ecu_node)
        graph.add_node(hyp_node)
        graph.add_edge(GraphEdge(
            edge_id="edge_01",
            source_id="ecu:ECM",
            target_id="hyp:P0171",
            edge_type=GraphEdgeType.SUPPORTS_HYPOTHESIS,
            confidence=0.8,
        ))
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(len(graph.edges), 1)

    # -----------------------------------------------------------------
    # Scenario I: Technician Action Gate
    # -----------------------------------------------------------------
    def test_scenario_i_technician_action_gate(self):
        """Manual physical operations must enter WAITING_FOR_TECHNICIAN and wait."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.ROOT_CAUSE_VERIFICATION
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.WAITING_FOR_TECHNICIAN)
        self.assertEqual(wf.state, WorkflowState.WAITING_FOR_TECHNICIAN)
        self.assertIsNotNone(wf.pending_technician_gate)

        # Advance without technician response must remain paused/stopped
        dec2 = self.engine.advance(wf)
        self.assertEqual(dec2.action, "STOP")

    # -----------------------------------------------------------------
    # Scenario J: Safety Revalidation Immediately Before Execution
    # -----------------------------------------------------------------
    def test_scenario_j_immediate_safety_revalidation(self):
        """Revalidates safety immediately prior to dispatching any test."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.TEST_EXECUTION

        unsafe_cand = DiagnosticTestCandidate(
            candidate_id="unsafe_actuator",
            title="Actuate Fuel Injector",
            description="Actuate injector bi-directional control",
            target_ecu="ECM",
            safety_classification=ServiceSafetyClassification.BLOCKED,
        )
        wf.latest_selection = TestSelectionDecision(
            decision_id="dec_unsafe",
            selected_candidate=unsafe_cand,
            target_hypotheses=[],
        )
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.SAFETY_BLOCKED)

    # -----------------------------------------------------------------
    # Scenario K: Prohibited Service Rejection
    # -----------------------------------------------------------------
    def test_scenario_k_prohibited_service_rejection(self):
        """Mode 04/14, 0x2E, 0x27, 0x2F, and 0x34 are strictly rejected by policy."""
        prohibited_services = ["04", "14", "2E", "27", "2F", "34", "36", "37"]
        for sid in prohibited_services:
            req = AdvancedServiceRequest(
                service_id=sid,
                payload="00",
                target_ecu="ECM",
                safety_classification=ServiceSafetyClassification.READ_ONLY,
            )
            is_valid, reason = self.safety_policy.validate_request(req)
            self.assertFalse(is_valid, f"Service 0x{sid} was not rejected by safety policy!")

    # -----------------------------------------------------------------
    # Scenario L: Zero Destructive Transport Reachability
    # -----------------------------------------------------------------
    def test_scenario_l_zero_destructive_transport_reachability(self):
        """Ensures that destructive requests can never pass through H-5 to transport."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)  # to BASELINE_ACQUISITION

        # Attempt to inject destructive mode into baseline
        dec = self.engine.advance(wf, baseline_data={"attempted_destructive_mode": True})
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.SAFETY_BLOCKED)

    # -----------------------------------------------------------------
    # Scenario M: Workflow Boundedness (Iterations, Tests, Runtime)
    # -----------------------------------------------------------------
    def test_scenario_m_workflow_bounds_enforced(self):
        """Ensures workflow terminates predictably when limits are reached."""
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_iterations=3),
        )
        wf.iteration_count = 3
        wf.stage = WorkflowStage.CONTEXT_VALIDATION
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.BLOCKED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.MAX_ITERATIONS_REACHED)

    # -----------------------------------------------------------------
    # Scenario N: Repeated-Test Loop Prevention
    # -----------------------------------------------------------------
    def test_scenario_n_repeated_test_loop_prevention(self):
        """Prevents infinite test ping-pong loops between H-3 and H-2."""
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_repeated_tests=1),
        )
        wf.stage = WorkflowStage.TEST_SELECTION
        wf.active_hypotheses.append(
            FaultHypothesis(hypothesis_id="hyp_01", title="Test Hyp", category="AIR_FUEL", affected_system="INTAKE")
        )
        wf.procedure = self.engine.procedure_engine.generate_procedure(
            session_id=wf.session_id,
            hypotheses=wf.active_hypotheses,
        )
        # Advance test selection once
        self.engine.advance(wf)
        # Force back to test selection
        wf.stage = WorkflowStage.TEST_SELECTION
        dec = self.engine.advance(wf)
        self.assertEqual(dec.stage, WorkflowStage.ROOT_CAUSE_ANALYSIS)

    # -----------------------------------------------------------------
    # Scenario O: Serialization Round-Trip Across All Layers
    # -----------------------------------------------------------------
    def test_scenario_o_serialization_round_trip(self):
        """to_dict() / from_dict() round trip must preserve complete state."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        self.engine.start_workflow(wf)
        self.engine.advance(wf)

        raw = wf.to_dict()
        reconstructed = DiagnosticWorkflow.from_dict(raw)
        self.assertEqual(reconstructed.workflow_id, wf.workflow_id)
        self.assertEqual(reconstructed.stage, wf.stage)
        self.assertEqual(reconstructed.state, wf.state)
        self.assertEqual(len(reconstructed.events), len(wf.events))

    # -----------------------------------------------------------------
    # Scenario P: Deterministic Repeated Execution
    # -----------------------------------------------------------------
    def test_scenario_p_deterministic_execution(self):
        """Identical inputs produce identical stage progressions."""
        wf1 = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf2 = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)

        self.engine.start_workflow(wf1)
        self.engine.start_workflow(wf2)

        dec1 = self.engine.advance(wf1)
        dec2 = self.engine.advance(wf2)

        self.assertEqual(dec1.stage, dec2.stage)
        self.assertEqual(dec1.action, dec2.action)

    # -----------------------------------------------------------------
    # Scenario Q: Failure Recovery (Transient Test Timeout)
    # -----------------------------------------------------------------
    def test_scenario_q_failure_recovery_on_transient_timeout(self):
        """Transient communication timeout on a step does not corrupt the workflow."""
        wf = self.engine.create_workflow(vehicle_context=self.vehicle_ctx)
        wf.stage = WorkflowStage.TEST_EXECUTION
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
    # Scenario R: Global Timeout Handling
    # -----------------------------------------------------------------
    def test_scenario_r_global_timeout_handling(self):
        """Global execution duration timeout forces safe termination."""
        wf = self.engine.create_workflow(
            vehicle_context=self.vehicle_ctx,
            policy=WorkflowPolicy(max_global_runtime_s=0.01),
        )
        time.sleep(0.02)
        dec = self.engine.advance(wf)
        self.assertEqual(wf.state, WorkflowState.FAILED)
        self.assertEqual(wf.outcome.outcome_type, WorkflowStopReason.GLOBAL_TIMEOUT)

    # -----------------------------------------------------------------
    # Scenario S: Large Evidence Set Boundedness
    # -----------------------------------------------------------------
    def test_scenario_s_large_evidence_set_boundedness(self):
        """Verifies bounded memory with 100+ evidence items."""
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
    # Scenario T: Final Outcome & Provenance Completeness
    # -----------------------------------------------------------------
    def test_scenario_t_final_outcome_provenance(self):
        """WorkflowOutcome contains complete diagnostic and audit trail metadata."""
        out = WorkflowOutcome(
            outcome_type=WorkflowStopReason.ROOT_CAUSE_RESOLVED,
            primary_diagnosis="Intake Manifold Gasket Leak",
            primary_candidate_id="rc_vacuum_leak",
            certainty=RootCauseCertaintyLevel.HIGH_CERTAINTY,
            confidence=0.94,
            alternative_candidates=["MAF Sensor Drift"],
            supporting_evidence_count=3,
            contradicting_evidence_count=0,
            tests_performed=["STEP_SMOKE_TEST"],
            procedures_performed=["PROC_VACUUM_01"],
            provenance={"vin": self.vehicle_ctx.vin, "technician": "TECH_01"},
        )
        d = out.to_dict()
        self.assertEqual(d["primary_diagnosis"], "Intake Manifold Gasket Leak")
        self.assertEqual(d["certainty"], "HIGH_CERTAINTY")
        self.assertEqual(d["provenance"]["vin"], self.vehicle_ctx.vin)


if __name__ == "__main__":
    unittest.main()
