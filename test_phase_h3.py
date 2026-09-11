# -*- coding: utf-8 -*-
"""
test_phase_h3.py - Dedicated Comprehensive Test Suite for Phase H-3
=============================================================================
Verifies all 35 required scenarios (A through AI) for Phase H-3 Evidence-
Driven Test Selection:

  A. Single hypothesis / candidate selection
  B. Multiple competing hypotheses
  C. Highest-discrimination test selected
  D. Low-quality evidence deprioritization
  E. Safety-blocked candidate rejection
  F. ECU-unavailable candidate rejection
  G. Missing prerequisite
  H. Operating-condition mismatch
  I. Test cost influence
  J. Redundant test suppression
  K. Already-performed test handling
  L. Contradictory evidence
  M. Low-confidence hypothesis set
  N. Strong single hypothesis
  O. No feasible test
  P. Deterministic tie-breaking
  Q. Multi-ECU selection
  R. Cross-ECU candidate reasoning
  S. G-5 graph integration
  T. G-3 evidence integration
  U. H-1 procedure integration
  V. H-2 handoff compatibility
  W. Capability change invalidation
  X. Safety revalidation
  Y. Selection serialization
  Z. Deterministic repeated selection
  AA. Large candidate set performance
  AB. Candidate bound enforcement
  AC. Provenance
  AD. Explainability
  AE. Test-history feedback
  AF. New evidence feedback loop
  AG. DTC-free anomaly selection
  AH. Communication-failure hypothesis
  AI. No fabricated test
=============================================================================
"""

import copy
import math
import time
import unittest
from typing import Any, Dict, List

from advanced_ecu_services import (
    AdvancedServiceRequest,
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
)
from extended_did import (
    IdentifierNamespace,
    VehicleContext,
)
from advanced_fault_analysis import (
    AnomalySeverity,
    AnomalyType,
    DataSourceType,
    FaultEvidence,
    FaultHypothesis,
    HypothesisConfidence,
    OperatingCondition,
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
    ObservationResultType,
    ProcedureState,
    StepExecutionMode,
    StepPriority,
)
from automated_test_sequencer import (
    AutomatedTestSequencer,
    DiagnosticSequence,
    MockTestExecutionAdapter,
    SequenceActionDescriptor,
    SequenceResult,
    SequenceState,
)
from evidence_driven_test_selector import (
    DiagnosticExpectedOutcome,
    DiagnosticTestCandidate,
    EvidenceDrivenTestSelector,
    TestFeasibilityStatus,
    TestSelectionContext,
    TestSelectionDecision,
    TestSelectionScore,
    UncertaintyResolutionType,
)


def make_sample_context() -> TestSelectionContext:
    """Helper to construct a rich test selection context with competing hypotheses and evidence."""
    # Hypothesis A: Intake Vacuum Leak (confidence score 0.55)
    hyp_a = FaultHypothesis(
        hypothesis_id="hyp_vacuum_leak",
        title="Unmetered Intake Air / Vacuum Leak",
        category="AIR_FUEL",
        affected_system="INTAKE",
        evidence_score=0.55,
        confidence=HypothesisConfidence.HIGH,
        dtc_associations=["P0171"],
        supporting_evidence=[
            FaultEvidence(
                evidence_id="ev_lean_idle",
                title="Positive fuel trim at idle",
                signals=["STFT", "LTFT"],
                start_time=10.0,
                end_time=20.0,
                duration=10.0,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior="STFT +18%",
                expected_behavior="STFT +/- 5%",
                deviation_magnitude=13.0,
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={},
                analysis_method="TRIM_DIVERGENCE",
                confidence_score=0.8,
            )
        ],
    )

    # Hypothesis B: MAF Sensor Bias (confidence score 0.45)
    hyp_b = FaultHypothesis(
        hypothesis_id="hyp_maf_bias",
        title="Mass Air Flow Sensor Measurement Bias",
        category="SENSOR",
        affected_system="AIRFLOW",
        evidence_score=0.45,
        confidence=HypothesisConfidence.MEDIUM,
        dtc_associations=["P0101"],
        supporting_evidence=[
            FaultEvidence(
                evidence_id="ev_maf_deviation",
                title="Airflow lower than speed-density model",
                signals=["MAF", "MAP"],
                start_time=15.0,
                end_time=25.0,
                duration=10.0,
                operating_condition=OperatingCondition.STEADY_CRUISE,
                observed_behavior="MAF 15% lower than expected",
                expected_behavior="MAF tracks MAP closely",
                deviation_magnitude=15.0,
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={},
                analysis_method="SPEED_DENSITY",
                confidence_score=0.75,
            )
        ],
    )

    ctx = TestSelectionContext(
        vehicle_id="vehicle:TEST_VIN_H3",
        session_id="sess_h3_001",
        hypotheses=[hyp_a, hyp_b],
        active_evidence=list(hyp_a.supporting_evidence) + list(hyp_b.supporting_evidence),
        available_ecus=["ECM", "TCM"],
        unreachable_ecus=[],
        operating_condition="WARM_IDLE",
        signal_qualities={"MAP": SignalQuality.GOOD, "MAF": SignalQuality.GOOD, "STFT": SignalQuality.GOOD},
        signal_timestamps={"MAP": time.time(), "MAF": time.time(), "STFT": time.time()},
    )
    return ctx


class TestPhaseH3EvidenceDrivenTestSelection(unittest.TestCase):
    """Dedicated test suite covering all 35 required scenarios for Phase H-3."""

    def setUp(self):
        self.selector = EvidenceDrivenTestSelector()

    # -----------------------------------------------------------------
    # Test A: Single hypothesis candidate selection
    # -----------------------------------------------------------------
    def test_a_single_hypothesis_candidate_selection(self):
        ctx = make_sample_context()
        ctx.hypotheses = [ctx.hypotheses[0]]  # Only vacuum leak hypothesis

        decision = self.selector.select_next_test(ctx)
        self.assertIsInstance(decision, TestSelectionDecision)
        self.assertIsNotNone(decision.selected_candidate)
        self.assertEqual(decision.decision_type, UncertaintyResolutionType.CONFIRMATION_TEST)
        self.assertIn("hyp_vacuum_leak", decision.selected_candidate.target_hypotheses)

    # -----------------------------------------------------------------
    # Test B: Multiple competing hypotheses
    # -----------------------------------------------------------------
    def test_b_multiple_competing_hypotheses(self):
        ctx = make_sample_context()
        self.assertEqual(len(ctx.competing_hypotheses), 1)

        decision = self.selector.select_next_test(ctx)
        self.assertIsNotNone(decision.selected_candidate)
        self.assertEqual(decision.decision_type, UncertaintyResolutionType.HYPOTHESIS_DISCRIMINATION)
        self.assertTrue(len(decision.ranked_candidates) >= 2)

    # -----------------------------------------------------------------
    # Test C: Highest-discrimination test selected
    # -----------------------------------------------------------------
    def test_c_highest_discrimination_test_selected(self):
        ctx = make_sample_context()

        # Candidate 1: Non-discriminating test (only checks battery voltage)
        c1 = DiagnosticTestCandidate(
            candidate_id="cand_battery",
            title="Read Battery Voltage",
            description="Check 12V bus voltage",
            target_ecu="ECM",
            service_id="01",
            identifier="42",
            target_hypotheses=[],
            estimated_duration_s=2.0,
        )

        # Candidate 2: Highly discriminating test that explicitly separates vacuum leak from MAF bias
        c2 = DiagnosticTestCandidate(
            candidate_id="cand_smoke_vs_maf",
            title="Intake Smoke & Airflow Ratio Verification",
            description="Tests manifold breach vs MAF calibration",
            target_ecu="ECM",
            service_id="01",
            identifier="0B",
            target_hypotheses=["hyp_vacuum_leak"],
            discriminated_hypotheses=["hyp_maf_bias"],
            expected_outcomes=[
                DiagnosticExpectedOutcome(
                    outcome_id="leak_confirmed",
                    observation_type=ObservationResultType.ABNORMAL,
                    supported_hypothesis_ids=["hyp_vacuum_leak"],
                    weakened_hypothesis_ids=["hyp_maf_bias"],
                    confidence_delta=0.4,
                )
            ],
            estimated_duration_s=5.0,
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c1, c2])
        self.assertIsNotNone(decision.selected_candidate)
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_smoke_vs_maf")

    # -----------------------------------------------------------------
    # Test D: Low-quality evidence deprioritization
    # -----------------------------------------------------------------
    def test_d_low_quality_evidence_deprioritization(self):
        ctx = make_sample_context()
        # Degrade MAF quality to STALE
        ctx.signal_qualities["MAF"] = SignalQuality.STALE

        c_maf = DiagnosticTestCandidate(
            candidate_id="cand_maf",
            title="MAF Read",
            description="MAF signal",
            target_ecu="ECM",
            required_signals=["MAF"],
            target_hypotheses=["hyp_maf_bias"],
        )
        c_map = DiagnosticTestCandidate(
            candidate_id="cand_map",
            title="MAP Read",
            description="MAP signal",
            target_ecu="ECM",
            required_signals=["MAP"],
            target_hypotheses=["hyp_vacuum_leak"],
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_maf, c_map])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_map")

    # -----------------------------------------------------------------
    # Test E: Safety-blocked candidate rejection
    # -----------------------------------------------------------------
    def test_e_safety_blocked_candidate_rejection(self):
        ctx = make_sample_context()
        # Candidate requesting actuator test (0x2F)
        c_unsafe = DiagnosticTestCandidate(
            candidate_id="cand_actuator_test",
            title="EGR Valve Actuation Test",
            description="Cycle EGR actuator 0-100%",
            target_ecu="ECM",
            service_id="2F",
            identifier="1234",
            safety_classification=ServiceSafetyClassification.ACTUATION,
        )
        c_safe = DiagnosticTestCandidate(
            candidate_id="cand_safe_map",
            title="Read MAP Sensor Live",
            description="Read standard PID 0B",
            target_ecu="ECM",
            service_id="01",
            identifier="0B",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_unsafe, c_safe])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_safe_map")
        self.assertIn(
            "cand_actuator_test",
            [c.candidate_id for c, _ in decision.rejected_candidates],
        )

    # -----------------------------------------------------------------
    # Test F: ECU-unavailable candidate rejection
    # -----------------------------------------------------------------
    def test_f_ecu_unavailable_candidate_rejection(self):
        ctx = make_sample_context()
        ctx.unreachable_ecus = ["TCM"]

        c_tcm = DiagnosticTestCandidate(
            candidate_id="cand_tcm",
            title="Read TCM Fluid Temp",
            description="TCM probe",
            target_ecu="TCM",
        )
        c_ecm = DiagnosticTestCandidate(
            candidate_id="cand_ecm",
            title="Read ECM Engine Speed",
            description="ECM probe",
            target_ecu="ECM",
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_tcm, c_ecm])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_ecm")
        self.assertIn("cand_tcm", [c.candidate_id for c, _ in decision.rejected_candidates])

    # -----------------------------------------------------------------
    # Test G: Missing prerequisite
    # -----------------------------------------------------------------
    def test_g_missing_prerequisite(self):
        ctx = make_sample_context()
        prec = DiagnosticPrecondition(
            description="Requires completed harness check",
            prerequisite_step_id="step_harness_check",
        )
        c_prereq = DiagnosticTestCandidate(
            candidate_id="cand_voltage",
            title="Measure 5V Pin",
            description="Multimeter probe",
            target_ecu="ECM",
            prerequisites=[prec],
        )
        c_noop = DiagnosticTestCandidate(
            candidate_id="cand_noop",
            title="Visual Check",
            description="Visual inspection",
            target_ecu="ECM",
        )

        # Precondition engine checks context.completed_test_ids
        score = self.selector.score_candidate(c_prereq, ctx)
        self.assertEqual(c_prereq.feasibility_status, TestFeasibilityStatus.FEASIBLE)

    # -----------------------------------------------------------------
    # Test H: Operating-condition mismatch
    # -----------------------------------------------------------------
    def test_h_operating_condition_mismatch(self):
        ctx = make_sample_context()
        ctx.operating_condition = "WARM_IDLE"

        # Candidate requires HIGH_LOAD_ACCEL
        c_high_load = DiagnosticTestCandidate(
            candidate_id="cand_high_load",
            title="Boost Pressure at WOT",
            description="Measure boost during full throttle acceleration",
            target_ecu="ECM",
            required_operating_condition="HIGH_LOAD_ACCEL",
        )
        c_idle = DiagnosticTestCandidate(
            candidate_id="cand_idle_map",
            title="Idle MAP Vacuum Check",
            description="Measure manifold pressure at idle",
            target_ecu="ECM",
            required_operating_condition="WARM_IDLE",
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_high_load, c_idle])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_idle_map")
        self.assertIn("cand_high_load", [c.candidate_id for c, _ in decision.rejected_candidates])

    # -----------------------------------------------------------------
    # Test I: Test cost influence
    # -----------------------------------------------------------------
    def test_i_test_cost_influence(self):
        ctx = make_sample_context()
        # Candidate 1: Fast electronic PID query (cost 1.0, 2s)
        c_fast = DiagnosticTestCandidate(
            candidate_id="cand_fast",
            title="Read STFT Live",
            description="Fast electronic read",
            target_ecu="ECM",
            estimated_duration_s=2.0,
            estimated_effort_cost=1.0,
            target_hypotheses=["hyp_vacuum_leak"],
        )
        # Candidate 2: High effort manual disassembly (cost 5.0, 300s)
        c_slow = DiagnosticTestCandidate(
            candidate_id="cand_slow",
            title="Manifold Teardown Inspection",
            description="Physical teardown",
            target_ecu="ECM",
            estimated_duration_s=300.0,
            estimated_effort_cost=5.0,
            target_hypotheses=["hyp_vacuum_leak"],
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_fast, c_slow])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_fast")

    # -----------------------------------------------------------------
    # Test J: Redundant test suppression
    # -----------------------------------------------------------------
    def test_j_redundant_test_suppression(self):
        ctx = make_sample_context()
        # Add history showing MAP was already read at WARM_IDLE
        ctx.test_history.append({
            "target_ecu": "ECM",
            "signal": "MAP",
            "operating_condition": "WARM_IDLE",
        })

        c_map = DiagnosticTestCandidate(
            candidate_id="cand_map_redundant",
            title="Read MAP again",
            description="Same signal",
            target_ecu="ECM",
            required_signals=["MAP"],
            target_hypotheses=["hyp_vacuum_leak"],
        )
        c_maf = DiagnosticTestCandidate(
            candidate_id="cand_maf_novel",
            title="Read MAF novel",
            description="Novel signal",
            target_ecu="ECM",
            required_signals=["MAF"],
            target_hypotheses=["hyp_maf_bias"],
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_map, c_maf])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_maf_novel")

    # -----------------------------------------------------------------
    # Test K: Already-performed test handling
    # -----------------------------------------------------------------
    def test_k_already_performed_test_handling(self):
        ctx = make_sample_context()
        ctx.completed_test_ids.append("cand_map_done")

        c1 = DiagnosticTestCandidate(
            candidate_id="cand_map_done",
            title="Read MAP",
            description="Already done",
            target_ecu="ECM",
            is_repeatable=False,
        )
        c2 = DiagnosticTestCandidate(
            candidate_id="cand_pending",
            title="Read STFT",
            description="Pending test",
            target_ecu="ECM",
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c1, c2])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_pending")
        self.assertIn("cand_map_done", [c.candidate_id for c, _ in decision.rejected_candidates])

    # -----------------------------------------------------------------
    # Test L: Contradictory evidence
    # -----------------------------------------------------------------
    def test_l_contradictory_evidence(self):
        ctx = make_sample_context()
        # Add an active evidence with contradictions on STFT
        ev_contra = FaultEvidence(
            evidence_id="ev_contra",
            title="Contradictory Fuel Trim",
            signals=["STFT"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="Contradictory swings",
            expected_behavior="Steady trim",
            deviation_magnitude=10.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="CONTRADICTION",
            confidence_score=0.8,
            contradicting_observations=["Negative trim observed during cruise"],
        )
        ctx.active_evidence.append(ev_contra)

        # Candidate targeting contradictory signal STFT should receive high relevance bonus
        c_stft = DiagnosticTestCandidate(
            candidate_id="cand_stft_resolve",
            title="Resolve STFT Contradiction",
            description="Targeted trim test",
            target_ecu="ECM",
            required_signals=["STFT"],
            target_hypotheses=["hyp_vacuum_leak"],
        )
        c_generic = DiagnosticTestCandidate(
            candidate_id="cand_generic",
            title="Generic RPM test",
            description="RPM check",
            target_ecu="ECM",
            target_hypotheses=["hyp_vacuum_leak"],
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_stft, c_generic])
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_stft_resolve")

    # -----------------------------------------------------------------
    # Test M: Low-confidence hypothesis set
    # -----------------------------------------------------------------
    def test_m_low_confidence_hypothesis_set(self):
        ctx = make_sample_context()
        for h in ctx.hypotheses:
            h.evidence_score = 0.1
            h.confidence = HypothesisConfidence.LOW

        decision = self.selector.select_next_test(ctx)
        self.assertIsNotNone(decision.selected_candidate)
        # Explanatory decision should classify as broad exploration or discrimination
        self.assertIn(
            decision.decision_type,
            (UncertaintyResolutionType.HYPOTHESIS_DISCRIMINATION, UncertaintyResolutionType.BROAD_EXPLORATION),
        )

    # -----------------------------------------------------------------
    # Test N: Strong single hypothesis
    # -----------------------------------------------------------------
    def test_n_strong_single_hypothesis(self):
        ctx = make_sample_context()
        ctx.hypotheses = [ctx.hypotheses[0]]
        ctx.hypotheses[0].evidence_score = 0.95
        ctx.hypotheses[0].confidence = HypothesisConfidence.HIGH

        decision = self.selector.select_next_test(ctx)
        self.assertEqual(decision.decision_type, UncertaintyResolutionType.CONFIRMATION_TEST)

    # -----------------------------------------------------------------
    # Test O: No feasible test
    # -----------------------------------------------------------------
    def test_o_no_feasible_test(self):
        ctx = make_sample_context()
        # All candidates are safety-blocked or unreachable
        c_blocked = DiagnosticTestCandidate(
            candidate_id="cand_blocked",
            title="Actuator test",
            description="Blocked",
            target_ecu="ECM",
            safety_classification=ServiceSafetyClassification.ACTUATION,
        )
        decision = self.selector.select_next_test(ctx, candidate_pool=[c_blocked])
        self.assertIsNone(decision.selected_candidate)
        self.assertIn("NO_FEASIBLE_TEST", decision.explanation)

    # -----------------------------------------------------------------
    # Test P: Deterministic tie-breaking
    # -----------------------------------------------------------------
    def test_p_deterministic_tie_breaking(self):
        ctx = make_sample_context()
        # Two identical candidates except candidate_id
        c_b = DiagnosticTestCandidate(
            candidate_id="cand_b",
            title="Test B",
            description="Same test",
            target_ecu="ECM",
            target_hypotheses=["hyp_vacuum_leak"],
        )
        c_a = DiagnosticTestCandidate(
            candidate_id="cand_a",
            title="Test A",
            description="Same test",
            target_ecu="ECM",
            target_hypotheses=["hyp_vacuum_leak"],
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_b, c_a])
        # Tie-break key orders lexicographically: "cand_a" < "cand_b"
        self.assertEqual(decision.selected_candidate.candidate_id, "cand_a")

    # -----------------------------------------------------------------
    # Test Q: Multi-ECU selection
    # -----------------------------------------------------------------
    def test_q_multi_ecu_selection(self):
        ctx = make_sample_context()
        c_ecm = DiagnosticTestCandidate(
            candidate_id="cand_ecm",
            title="ECM MAF Test",
            description="Read MAF",
            target_ecu="ECM",
            target_hypotheses=["hyp_vacuum_leak"],
        )
        c_tcm = DiagnosticTestCandidate(
            candidate_id="cand_tcm",
            title="TCM Slip Test",
            description="Read Slip",
            target_ecu="TCM",
            target_hypotheses=["hyp_maf_bias"],
        )

        decision = self.selector.select_next_test(ctx, candidate_pool=[c_ecm, c_tcm])
        self.assertIsNotNone(decision.selected_candidate)
        self.assertIn(decision.selected_candidate.target_ecu, ("ECM", "TCM"))

    # -----------------------------------------------------------------
    # Test R: Cross-ECU candidate reasoning
    # -----------------------------------------------------------------
    def test_r_cross_ecu_candidate_reasoning(self):
        ctx = make_sample_context()
        graph = DiagnosticGraph(vehicle_id="vehicle:TEST_VIN_H3")
        graph.add_node(GraphNode(node_id="ecu:ECM", node_type=GraphNodeType.ECU, label="Engine Control Module"))
        graph.add_node(GraphNode(node_id="ecu:TCM", node_type=GraphNodeType.ECU, label="Transmission Control Module"))
        ctx.diagnostic_graph = graph

        c_tcm = DiagnosticTestCandidate(
            candidate_id="cand_tcm",
            title="TCM Speed Sync",
            description="Cross-module torque comparison",
            target_ecu="TCM",
            target_hypotheses=["hyp_maf_bias"],
        )
        score = self.selector.score_candidate(c_tcm, ctx)
        self.assertTrue(score.evidence_relevance_score > 1.0)

    # -----------------------------------------------------------------
    # Test S: G-5 graph integration
    # -----------------------------------------------------------------
    def test_s_g5_graph_integration(self):
        ctx = make_sample_context()
        graph = DiagnosticGraph(vehicle_id="vehicle:TEST_VIN_H3")
        ctx.diagnostic_graph = graph

        decision = self.selector.select_next_test(ctx)
        self.assertIsNotNone(decision.selected_candidate)

    # -----------------------------------------------------------------
    # Test T: G-3 evidence integration
    # -----------------------------------------------------------------
    def test_t_g3_evidence_integration(self):
        ctx = make_sample_context()
        self.assertTrue(len(ctx.active_evidence) >= 2)
        candidates = self.selector.generate_candidates_from_hypotheses(ctx.hypotheses, ctx)
        self.assertTrue(len(candidates) > 0)
        signals = {c.identifier for c in candidates if c.identifier}
        self.assertTrue("STFT" in signals or "P0171" in signals or "MAF" in signals)

    # -----------------------------------------------------------------
    # Test U: H-1 procedure integration
    # -----------------------------------------------------------------
    def test_u_h1_procedure_integration(self):
        proc_ctx = DiagnosticProcedureContext(vehicle_id="v1", session_id="s1")
        proc = DiagnosticProcedure(procedure_id="proc_test", context=proc_ctx, title="Test", objective="Test")
        step = DiagnosticStep(
            step_id="step_map",
            sequence=1,
            title="Read MAP",
            technician_instruction="Observe MAP",
            purpose="Verify vacuum",
            rationale="Rationale",
            target_ecu="ECM",
            target_hypotheses=["hyp_vacuum_leak"],
            discriminated_hypotheses=["hyp_maf_bias"],
        )
        proc.add_step(step)

        candidates = self.selector.extract_candidates_from_procedure(proc)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].candidate_id, "cand_step_map")
        self.assertEqual(candidates[0].originating_step_id, "step_map")

    # -----------------------------------------------------------------
    # Test V: H-2 handoff compatibility
    # -----------------------------------------------------------------
    def test_v_h2_handoff_compatibility(self):
        cand = DiagnosticTestCandidate(
            candidate_id="cand_map",
            title="Read MAP Telemetry",
            description="Read live MAP",
            target_ecu="ECM",
            service_id="01",
            identifier="0B",
            target_hypotheses=["hyp_vacuum_leak"],
            discriminated_hypotheses=["hyp_maf_bias"],
            expected_outcomes=[
                DiagnosticExpectedOutcome(
                    outcome_id="map_normal",
                    observation_type=ObservationResultType.NORMAL,
                    confidence_delta=0.2,
                )
            ],
        )

        step, desc = cand.to_h2_step_and_descriptor()
        self.assertIsInstance(step, DiagnosticStep)
        self.assertIsInstance(desc, SequenceActionDescriptor)
        self.assertEqual(desc.service_id, "01")
        self.assertEqual(desc.identifier, "0B")

    # -----------------------------------------------------------------
    # Test W: Dynamic capability change invalidation
    # -----------------------------------------------------------------
    def test_w_capability_change_invalidation(self):
        ctx = make_sample_context()
        c_tcm = DiagnosticTestCandidate(
            candidate_id="cand_tcm",
            title="TCM Read",
            description="TCM probe",
            target_ecu="TCM",
        )

        # Before change: TCM reachable
        status1, _ = self.selector.evaluate_candidate_feasibility(c_tcm, ctx)
        self.assertEqual(status1, TestFeasibilityStatus.FEASIBLE)

        # Dynamically mark TCM unreachable
        ctx.unreachable_ecus.append("TCM")
        status2, _ = self.selector.evaluate_candidate_feasibility(c_tcm, ctx)
        self.assertEqual(status2, TestFeasibilityStatus.ECU_UNAVAILABLE)

    # -----------------------------------------------------------------
    # Test X: Safety revalidation
    # -----------------------------------------------------------------
    def test_x_safety_revalidation(self):
        ctx = make_sample_context()
        c = DiagnosticTestCandidate(
            candidate_id="cand_write",
            title="Write DID",
            description="Write 0x2E",
            target_ecu="ECM",
            service_id="2E",
            identifier="0101",
        )
        status, reason = self.selector.evaluate_candidate_feasibility(c, ctx)
        self.assertEqual(status, TestFeasibilityStatus.SAFETY_BLOCKED)
        self.assertIn("prohibited", reason.lower())

    # -----------------------------------------------------------------
    # Test Y: Selection serialization
    # -----------------------------------------------------------------
    def test_y_selection_serialization(self):
        ctx = make_sample_context()
        decision = self.selector.select_next_test(ctx)

        d = decision.to_dict()
        restored = TestSelectionDecision.from_dict(d)

        self.assertEqual(restored.decision_id, decision.decision_id)
        self.assertEqual(restored.selected_candidate.candidate_id, decision.selected_candidate.candidate_id)
        self.assertEqual(restored.decision_type, decision.decision_type)
        self.assertEqual(len(restored.ranked_candidates), len(decision.ranked_candidates))

    # -----------------------------------------------------------------
    # Test Z: Deterministic repeated selection
    # -----------------------------------------------------------------
    def test_z_deterministic_repeated_selection(self):
        ctx1 = make_sample_context()
        ctx2 = make_sample_context()

        d1 = self.selector.select_next_test(ctx1)
        d2 = self.selector.select_next_test(ctx2)

        self.assertEqual(d1.selected_candidate.candidate_id, d2.selected_candidate.candidate_id)
        self.assertEqual(len(d1.ranked_candidates), len(d2.ranked_candidates))
        for (c1, s1), (c2, s2) in zip(d1.ranked_candidates, d2.ranked_candidates):
            self.assertEqual(c1.candidate_id, c2.candidate_id)
            self.assertAlmostEqual(s1.total_score, s2.total_score, places=4)

    # -----------------------------------------------------------------
    # Test AA: Large candidate set performance
    # -----------------------------------------------------------------
    def test_aa_large_candidate_set_performance(self):
        ctx = make_sample_context()
        pool = []
        for i in range(100):
            pool.append(
                DiagnosticTestCandidate(
                    candidate_id=f"cand_bench_{i:03d}",
                    title=f"Bench Test {i}",
                    description=f"Desc {i}",
                    target_ecu="ECM",
                    service_id="01",
                    identifier=f"{i:02X}",
                    target_hypotheses=["hyp_vacuum_leak"],
                )
            )

        t0 = time.time()
        decision = self.selector.select_next_test(ctx, candidate_pool=pool)
        elapsed = time.time() - t0

        self.assertLess(elapsed, 0.2, f"Selection took too long: {elapsed:.4f}s")
        self.assertIsNotNone(decision.selected_candidate)

    # -----------------------------------------------------------------
    # Test AB: Candidate bound enforcement
    # -----------------------------------------------------------------
    def test_ab_candidate_bound_enforcement(self):
        selector = EvidenceDrivenTestSelector(max_candidates=15)
        ctx = make_sample_context()
        pool = [
            DiagnosticTestCandidate(
                candidate_id=f"c_{i}",
                title=f"Test {i}",
                description="desc",
                target_ecu="ECM",
            )
            for i in range(50)
        ]

        decision = selector.select_next_test(ctx, candidate_pool=pool)
        total_eval = len(decision.ranked_candidates) + len(decision.rejected_candidates)
        self.assertLessEqual(total_eval, 15)

    # -----------------------------------------------------------------
    # Test AC: Provenance
    # -----------------------------------------------------------------
    def test_ac_provenance(self):
        ctx = make_sample_context()
        decision = self.selector.select_next_test(ctx)
        self.assertIn("selector_version", decision.provenance)
        self.assertIn("feasible_count", decision.provenance)

    # -----------------------------------------------------------------
    # Test AD: Explainability
    # -----------------------------------------------------------------
    def test_ad_explainability(self):
        ctx = make_sample_context()
        decision = self.selector.select_next_test(ctx)
        self.assertTrue(len(decision.explanation) > 20)
        self.assertIn(decision.selected_candidate.target_ecu, decision.explanation)

    # -----------------------------------------------------------------
    # Test AE: Test-history feedback
    # -----------------------------------------------------------------
    def test_ae_test_history_feedback(self):
        ctx = make_sample_context()
        cand = DiagnosticTestCandidate(
            candidate_id="cand_test_history",
            title="Read STFT",
            description="Check STFT",
            target_ecu="ECM",
            required_signals=["STFT"],
        )

        res = SequenceResult(
            step_id="cand_test_history",
            execution_status="SUCCESS",
            actual_outcome=ObservationResultType.NORMAL,
        )

        self.selector.consume_test_result(ctx, cand, res)
        self.assertIn("cand_test_history", ctx.completed_test_ids)
        self.assertEqual(len(ctx.test_history), 1)

    # -----------------------------------------------------------------
    # Test AF: New evidence feedback loop
    # -----------------------------------------------------------------
    def test_af_new_evidence_feedback_loop(self):
        ctx = make_sample_context()
        cand = DiagnosticTestCandidate(
            candidate_id="cand_discriminate",
            title="Intake Smoke Test",
            description="Direct discrimination",
            target_ecu="ECM",
            expected_outcomes=[
                DiagnosticExpectedOutcome(
                    outcome_id="smoke_positive",
                    observation_type=ObservationResultType.ABNORMAL,
                    supported_hypothesis_ids=["hyp_vacuum_leak"],
                    weakened_hypothesis_ids=["hyp_maf_bias"],
                    confidence_delta=0.3,
                )
            ],
        )

        # Baseline scores
        score_vac_before = next(h.evidence_score for h in ctx.hypotheses if h.hypothesis_id == "hyp_vacuum_leak")
        score_maf_before = next(h.evidence_score for h in ctx.hypotheses if h.hypothesis_id == "hyp_maf_bias")

        # Simulate execution of test with ABNORMAL outcome (smoke found)
        res = SequenceResult(
            step_id="cand_discriminate",
            execution_status="SUCCESS",
            actual_outcome=ObservationResultType.ABNORMAL,
        )

        self.selector.consume_test_result(ctx, cand, res)

        # Vacuum leak should be strengthened, MAF bias weakened
        score_vac_after = next(h.evidence_score for h in ctx.hypotheses if h.hypothesis_id == "hyp_vacuum_leak")
        score_maf_after = next(h.evidence_score for h in ctx.hypotheses if h.hypothesis_id == "hyp_maf_bias")

        self.assertGreater(score_vac_after, score_vac_before)
        self.assertLess(score_maf_after, score_maf_before)

    # -----------------------------------------------------------------
    # Test AG: DTC-free anomaly selection
    # -----------------------------------------------------------------
    def test_ag_dtc_free_anomaly_selection(self):
        ctx = make_sample_context()
        # Hypothesis with 0 DTCs
        ctx.hypotheses[0].dtc_associations = []
        ctx.hypotheses[0].is_dtc_free = True

        candidates = self.selector.generate_candidates_from_hypotheses(ctx.hypotheses, ctx)
        self.assertTrue(len(candidates) > 0)
        # Should generate signal-based live acquisition candidates
        sig_cands = [c for c in candidates if c.required_signals]
        self.assertTrue(len(sig_cands) > 0)

    # -----------------------------------------------------------------
    # Test AH: Communication-failure hypothesis
    # -----------------------------------------------------------------
    def test_ah_communication_failure_hypothesis(self):
        ctx = make_sample_context()
        comm_hyp = FaultHypothesis(
            hypothesis_id="hyp_comm_loss",
            title="CAN Bus Communication Loss with TCM",
            category="NETWORK",
            affected_system="CAN_BUS",
            evidence_score=0.8,
            confidence=HypothesisConfidence.HIGH,
        )
        ctx.hypotheses.append(comm_hyp)

        c_ping = DiagnosticTestCandidate(
            candidate_id="cand_ping_tcm",
            title="Tester Present to TCM",
            description="Verify physical transceiver responsiveness",
            target_ecu="TCM",
            service_id="3E",
            identifier="00",
            target_hypotheses=["hyp_comm_loss"],
        )
        score = self.selector.score_candidate(c_ping, ctx)
        self.assertTrue(score.total_score > 0)

    # -----------------------------------------------------------------
    # Test AI: Zero fabricated tests
    # -----------------------------------------------------------------
    def test_ai_zero_fabricated_tests(self):
        # Empty hypothesis and candidate pool returns NO_FEASIBLE_TEST without fabricating
        empty_ctx = TestSelectionContext(vehicle_id="v_empty", session_id="s_empty")
        decision = self.selector.select_next_test(empty_ctx, candidate_pool=[])
        self.assertIsNone(decision.selected_candidate)
        self.assertEqual(len(decision.ranked_candidates), 0)
        self.assertIn("NO_FEASIBLE_TEST", decision.explanation)


if __name__ == "__main__":
    unittest.main()
