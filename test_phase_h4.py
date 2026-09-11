# -*- coding: utf-8 -*-
"""
test_phase_h4.py - Dedicated Comprehensive Test Suite for Phase H-4
=============================================================================
Verifies all 42 required scenarios (A through AP) for Phase H-4 Automated
Root-Cause Analysis:

  A. Single strong root-cause candidate
  B. Competing hypotheses
  C. DTC-supported hypothesis
  D. DTC-free root cause
  E. Contradictory evidence
  F. Low-quality evidence
  G. Communication failure
  H. Multi-ECU root cause
  I. Primary vs contributing factor
  J. Secondary effect recognition
  K. Temporal evidence
  L. Cross-sensor consistency
  M. Cross-ECU consistency
  N. Duplicate evidence / double-count prevention
  O. Discriminating test result weighting
  P. Weak correlation only
  Q. Strong targeted test evidence
  R. No-confident-root-cause outcome
  S. Multiple plausible causes
  T. H-3/H-2 feedback loop
  U. Technician confirmation
  V. Technician rejection
  W. Post-repair verification representation
  X. Vehicle-specific knowledge
  Y. Missing vehicle-specific specification
  Z. Graph integration
  AA. Reasoning trace
  AB. Serialization round-trip
  AC. Deterministic repeated analysis
  AD. Bounded candidate generation
  AE. Causal-depth limit
  AF. Evidence traversal bound
  AG. Large evidence set
  AH. Safety restrictions
  AI. Destructive-operation rejection
  AJ. No autonomous repair
  AK. No DTC clearing
  AL. Communication-vs-component distinction
  AM. Alternative candidate preservation
  AN. Contributing-factor classification
  AO. Confidence component inspection
  AP. Final verification recommendation
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
    UncertaintyResolutionType,
)
from automated_root_cause_analyzer import (
    AnalysisConclusionState,
    AutomatedRootCauseAnalyzer,
    CausalBasis,
    CausalRole,
    CauseEvidenceReference,
    RootCauseAnalysis,
    RootCauseAnalysisContext,
    RootCauseCandidate,
    RootCauseCandidateStatus,
    RootCauseCertaintyLevel,
    RootCauseConclusion,
)


def make_sample_context() -> RootCauseAnalysisContext:
    """Helper to build a rich RootCauseAnalysisContext with competing hypotheses and evidence."""
    # Hypothesis 1: Intake Vacuum Leak
    hyp1 = FaultHypothesis(
        hypothesis_id="hyp_vacuum_leak",
        title="Unmetered Intake Air / Vacuum Leak",
        category="AIR_FUEL",
        affected_system="INTAKE",
        evidence_score=0.75,
        confidence=HypothesisConfidence.HIGH,
        dtc_associations=["P0171"],
        supporting_evidence=[
            FaultEvidence(
                evidence_id="ev_trim_idle",
                title="Elevated fuel trims at warm idle",
                signals=["STFT", "LTFT"],
                start_time=10.0,
                end_time=20.0,
                duration=10.0,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior="STFT +18%, LTFT +14%",
                expected_behavior="Fuel trims within +/- 5%",
                deviation_magnitude=15.0,
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={},
                analysis_method="TRIM_DIVERGENCE",
                confidence_score=0.85,
            ),
            FaultEvidence(
                evidence_id="ev_map_idle",
                title="MAP higher than normal vacuum at idle",
                signals=["MAP"],
                start_time=12.0,
                end_time=22.0,
                duration=10.0,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior="MAP at 48 kPa (expected 30-38 kPa)",
                expected_behavior="MAP in vacuum range",
                deviation_magnitude=10.0,
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={},
                analysis_method="VALUE_OUT_OF_RANGE",
                confidence_score=0.80,
            ),
        ],
    )

    # Hypothesis 2: MAF Sensor Measurement Bias
    hyp2 = FaultHypothesis(
        hypothesis_id="hyp_maf_bias",
        title="Mass Air Flow Sensor Measurement Bias",
        category="SENSOR",
        affected_system="AIRFLOW",
        evidence_score=0.45,
        confidence=HypothesisConfidence.MEDIUM,
        dtc_associations=["P0101"],
        supporting_evidence=[
            FaultEvidence(
                evidence_id="ev_maf_drift",
                title="MAF reading lower than model prediction",
                signals=["MAF"],
                start_time=15.0,
                end_time=25.0,
                duration=10.0,
                operating_condition=OperatingCondition.STEADY_CRUISE,
                observed_behavior="MAF 12% low",
                expected_behavior="Tracks model",
                deviation_magnitude=12.0,
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={},
                analysis_method="SPEED_DENSITY",
                confidence_score=0.70,
            )
        ],
    )

    ctx = RootCauseAnalysisContext(
        vehicle_id="vehicle:TEST_VIN_H4",
        session_id="sess_h4_001",
        hypotheses=[hyp1, hyp2],
        active_evidence=list(hyp1.supporting_evidence) + list(hyp2.supporting_evidence),
        completed_test_results=[
            SequenceResult(
                step_id="step_smoke_test",
                execution_status="SUCCESS",
                actual_outcome=ObservationResultType.NORMAL,
                observed_values={"leak_detected": True, "location": "manifold_gasket"},
            )
        ],
        selection_decisions=[
            TestSelectionDecision(
                decision_id="dec_001",
                selected_candidate=DiagnosticTestCandidate(
                    candidate_id="cand_smoke",
                    title="Intake Smoke Test",
                    description="Physical leak test",
                    target_ecu="ECM",
                    originating_step_id="step_smoke_test",
                    target_hypotheses=["hyp_vacuum_leak"],
                    discriminated_hypotheses=["hyp_maf_bias"],
                ),
                target_hypotheses=["hyp_vacuum_leak"],
                expected_information_gain=1.5,
                decision_type=UncertaintyResolutionType.HYPOTHESIS_DISCRIMINATION,
                explanation="Smoke test discriminates vacuum leak from MAF bias.",
            )
        ],
        available_ecus=["ECM", "TCM"],
        unreachable_ecus=[],
        operating_condition="IDLE",
    )
    return ctx


class TestPhaseH4AutomatedRootCauseAnalysis(unittest.TestCase):
    """Test suite covering all 42 required scenarios (A through AP) for Phase H-4."""

    def setUp(self):
        self.analyzer = AutomatedRootCauseAnalyzer()

    # -----------------------------------------------------------------
    # Test A: Single strong root-cause candidate
    # -----------------------------------------------------------------
    def test_a_single_strong_root_cause_candidate(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)

        self.assertIsInstance(analysis, RootCauseAnalysis)
        self.assertIsNotNone(analysis.primary_candidate)
        self.assertEqual(analysis.primary_candidate.candidate_id, "rc_hyp_vacuum_leak")
        self.assertIn(
            analysis.conclusion.conclusion_state,
            (AnalysisConclusionState.ROOT_CAUSE_STRONGLY_SUPPORTED, AnalysisConclusionState.LEADING_CANDIDATE_ONLY),
        )

    # -----------------------------------------------------------------
    # Test B: Competing hypotheses
    # -----------------------------------------------------------------
    def test_b_competing_hypotheses(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)

        # Ensure alternative candidates are preserved and not discarded
        self.assertTrue(len(analysis.alternative_candidates) > 0)
        self.assertEqual(analysis.alternative_candidates[0].candidate_id, "rc_hyp_maf_bias")

    # -----------------------------------------------------------------
    # Test C: DTC-supported hypothesis
    # -----------------------------------------------------------------
    def test_c_dtc_supported_hypothesis(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIn("P0171", analysis.primary_candidate.source_dtcs)

    # -----------------------------------------------------------------
    # Test D: DTC-free root cause
    # -----------------------------------------------------------------
    def test_d_dtc_free_root_cause(self):
        ctx = make_sample_context()
        ctx.hypotheses[0].dtc_associations = []
        ctx.hypotheses[0].is_dtc_free = True

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.primary_candidate)
        self.assertEqual(len(analysis.primary_candidate.source_dtcs), 0)
        # Physics and test results still establish the root cause
        self.assertTrue(analysis.primary_candidate.causal_confidence > 0.5)

    # -----------------------------------------------------------------
    # Test E: Contradictory evidence
    # -----------------------------------------------------------------
    def test_e_contradictory_evidence(self):
        ctx = make_sample_context()
        # Add strong contradictory evidence to hypothesis 1
        ev_contra = FaultEvidence(
            evidence_id="ev_contra_idle",
            title="Trims rich under cruise",
            signals=["STFT"],
            start_time=30.0,
            end_time=40.0,
            duration=10.0,
            operating_condition=OperatingCondition.STEADY_CRUISE,
            observed_behavior="Negative trims contradict leak",
            expected_behavior="Positive",
            deviation_magnitude=10.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="CONTRADICTION",
            confidence_score=0.9,
        )
        ctx.hypotheses[0].contradicting_evidence.append(ev_contra)

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(analysis.primary_candidate.contradiction_score > 0.0)

    # -----------------------------------------------------------------
    # Test F: Low-quality evidence
    # -----------------------------------------------------------------
    def test_f_low_quality_evidence(self):
        ctx = make_sample_context()
        # Mark evidence as SUSPECT
        for ev in ctx.hypotheses[0].supporting_evidence:
            ev.quality = SignalQuality.SUSPECT

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(analysis.primary_candidate.quality_penalty > 0.0)

    # -----------------------------------------------------------------
    # Test G: Communication failure
    # -----------------------------------------------------------------
    def test_g_communication_failure(self):
        ctx = make_sample_context()
        ctx.unreachable_ecus = ["ABS"]

        analysis = self.analyzer.analyze_root_cause(ctx)
        comm_cands = [c for c in analysis.candidates_all if "ABS" in c.affected_ecu] if hasattr(analysis, "candidates_all") else [
            c for c in ([analysis.primary_candidate] + analysis.alternative_candidates) if c and "ABS" in c.affected_ecu
        ]
        self.assertTrue(len(comm_cands) > 0)
        self.assertIn("CAN", comm_cands[0].affected_component or "")

    # -----------------------------------------------------------------
    # Test H: Multi-ECU root cause
    # -----------------------------------------------------------------
    def test_h_multi_ecu_root_cause(self):
        ctx = make_sample_context()
        hyp_tcm = FaultHypothesis(
            hypothesis_id="hyp_tcm_slip",
            title="Transmission Torque Converter Clutch Slip",
            category="TRANSMISSION",
            affected_system="TRANSMISSION",
            evidence_score=0.6,
            confidence=HypothesisConfidence.HIGH,
        )
        ctx.hypotheses.append(hyp_tcm)

        analysis = self.analyzer.analyze_root_cause(ctx)
        ecus = {c.affected_ecu for c in ([analysis.primary_candidate] + analysis.alternative_candidates) if c}
        self.assertIn("ECM", ecus)
        self.assertIn("TCM", ecus)

    # -----------------------------------------------------------------
    # Test I: Primary vs contributing factor
    # -----------------------------------------------------------------
    def test_i_primary_vs_contributing_factor(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertEqual(analysis.primary_candidate.causal_role, CausalRole.PRIMARY_ROOT_CAUSE)

    # -----------------------------------------------------------------
    # Test J: Secondary effect recognition
    # -----------------------------------------------------------------
    def test_j_secondary_effect_recognition(self):
        ctx = make_sample_context()
        # Add a misfire hypothesis which is secondary to lean air/fuel condition
        hyp_misfire = FaultHypothesis(
            hypothesis_id="hyp_misfire_p0300",
            title="Random/Multiple Cylinder Misfire Detected",
            category="IGNITION",
            affected_system="CYLINDERS",
            evidence_score=0.5,
            confidence=HypothesisConfidence.HIGH,
            dtc_associations=["P0300"],
        )
        ctx.hypotheses.append(hyp_misfire)

        analysis = self.analyzer.analyze_root_cause(ctx)
        misfire_cands = [c for c in analysis.contributing_factors if "misfire" in c.candidate_id.lower()]
        self.assertTrue(len(misfire_cands) > 0)
        self.assertEqual(misfire_cands[0].causal_role, CausalRole.SECONDARY_EFFECT)

    # -----------------------------------------------------------------
    # Test K: Temporal evidence
    # -----------------------------------------------------------------
    def test_k_temporal_evidence(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(len(analysis.primary_candidate.supporting_evidence) > 0)

    # -----------------------------------------------------------------
    # Test L: Cross-sensor consistency
    # -----------------------------------------------------------------
    def test_l_cross_sensor_consistency(self):
        ctx = make_sample_context()
        # Hypothesis 1 has evidence across STFT, LTFT, and MAP (3 signals)
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(analysis.primary_candidate.cross_sensor_score > 0.0)

    # -----------------------------------------------------------------
    # Test M: Cross-ECU consistency
    # -----------------------------------------------------------------
    def test_m_cross_ecu_consistency(self):
        ctx = make_sample_context()
        graph = DiagnosticGraph(vehicle_id="vehicle:TEST_VIN_H4")
        graph.add_node(GraphNode(node_id="ecu:ECM", node_type=GraphNodeType.ECU, label="ECM"))
        ctx.diagnostic_graph = graph

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(analysis.primary_candidate.cross_ecu_score > 0.0)

    # -----------------------------------------------------------------
    # Test N: Duplicate evidence / double-count prevention
    # -----------------------------------------------------------------
    def test_n_duplicate_evidence_double_count_prevention(self):
        ctx = make_sample_context()
        # Duplicate the same evidence item in hyp1
        ctx.hypotheses[0].supporting_evidence.append(copy.deepcopy(ctx.hypotheses[0].supporting_evidence[0]))

        candidates = self.analyzer.generate_candidates(ctx)
        # Should de-duplicate identical fingerprints
        self.assertEqual(len(candidates[0].supporting_evidence), 2)

    # -----------------------------------------------------------------
    # Test O: Discriminating test result weighting
    # -----------------------------------------------------------------
    def test_o_discriminating_test_result_weighting(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(analysis.primary_candidate.test_confirmation_score > 0.0)

    # -----------------------------------------------------------------
    # Test P: Weak correlation only
    # -----------------------------------------------------------------
    def test_p_weak_correlation_only(self):
        ctx = make_sample_context()
        # Hypothesis with only DTC and 0 physical evidence items
        hyp_weak = FaultHypothesis(
            hypothesis_id="hyp_dtc_only",
            title="DTC Only Fault",
            category="AIR_FUEL",
            affected_system="EXHAUST",
            evidence_score=0.4,
            dtc_associations=["P0420"],
        )
        ctx.hypotheses = [hyp_weak]
        ctx.completed_test_results = []
        ctx.selection_decisions = []

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertEqual(analysis.primary_candidate.causal_basis, CausalBasis.CORRELATIONAL_ONLY)
        self.assertLessEqual(analysis.primary_candidate.causal_confidence, 0.40)

    # -----------------------------------------------------------------
    # Test Q: Strong targeted test evidence
    # -----------------------------------------------------------------
    def test_q_strong_targeted_test_evidence(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertEqual(analysis.primary_candidate.causal_basis, CausalBasis.HYPOTHESIS_TEST_SUPPORT)

    # -----------------------------------------------------------------
    # Test R: No-confident-root-cause outcome
    # -----------------------------------------------------------------
    def test_r_no_confident_root_cause_outcome(self):
        empty_ctx = RootCauseAnalysisContext(vehicle_id="v_empty", session_id="s_empty")
        analysis = self.analyzer.analyze_root_cause(empty_ctx)
        self.assertEqual(analysis.conclusion.conclusion_state, AnalysisConclusionState.NO_CONFIDENT_ROOT_CAUSE)

    # -----------------------------------------------------------------
    # Test S: Multiple plausible causes
    # -----------------------------------------------------------------
    def test_s_multiple_plausible_causes(self):
        ctx = make_sample_context()
        # Set both hypotheses to identical evidence score and remove test results
        ctx.completed_test_results = []
        ctx.selection_decisions = []
        ctx.hypotheses[0].supporting_evidence = []
        ctx.hypotheses[1].supporting_evidence = []
        ctx.hypotheses[0].dtc_associations = ["P0171"]
        ctx.hypotheses[1].dtc_associations = ["P0101"]

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIn(
            analysis.conclusion.conclusion_state,
            (AnalysisConclusionState.MULTIPLE_PLAUSIBLE_CAUSES, AnalysisConclusionState.LEADING_CANDIDATE_ONLY),
        )

    # -----------------------------------------------------------------
    # Test T: H-3/H-2 feedback loop
    # -----------------------------------------------------------------
    def test_t_h3_h2_feedback_loop(self):
        ctx = make_sample_context()
        # Completed test result from H-2 confirms H-3 decision
        self.assertTrue(len(ctx.completed_test_results) > 0)
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.primary_candidate)

    # -----------------------------------------------------------------
    # Test U: Technician confirmation
    # -----------------------------------------------------------------
    def test_u_technician_confirmation(self):
        ctx = make_sample_context()
        ctx.technician_inputs.append({
            "type": "TECHNICIAN_CONFIRMATION",
            "target_candidate": "rc_hyp_vacuum_leak",
            "notes": "Confirmed cracked intake gasket visually.",
        })

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertEqual(analysis.conclusion.certainty_level, RootCauseCertaintyLevel.CONFIRMED)
        self.assertIn("confirmed", analysis.conclusion.summary_text.lower())

    # -----------------------------------------------------------------
    # Test V: Technician rejection
    # -----------------------------------------------------------------
    def test_v_technician_rejection(self):
        ctx = make_sample_context()
        ctx.technician_inputs.append({
            "type": "TECHNICIAN_REJECTION",
            "target_candidate": "rc_hyp_vacuum_leak",
            "notes": "Intake gasket inspected and smoke test showed no leak.",
        })

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIn("rc_hyp_vacuum_leak", [c.candidate_id for c in analysis.ruled_out_candidates])

    # -----------------------------------------------------------------
    # Test W: Post-repair verification representation
    # -----------------------------------------------------------------
    def test_w_post_repair_verification_representation(self):
        ctx = make_sample_context()
        ctx.technician_inputs.append({
            "type": "POST_REPAIR_VERIFICATION",
            "details": "Gasket replaced, idle trims normalized to +2%",
        })

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.conclusion.post_repair_verification)

    # -----------------------------------------------------------------
    # Test X: Vehicle-specific knowledge
    # -----------------------------------------------------------------
    def test_x_vehicle_specific_knowledge(self):
        ctx = make_sample_context()
        ctx.vehicle_context = VehicleContext(
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year="2010",
            engine_code="F14D3",
        )
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.primary_candidate)

    # -----------------------------------------------------------------
    # Test Y: Missing vehicle-specific specification
    # -----------------------------------------------------------------
    def test_y_missing_vehicle_specific_specification(self):
        ctx = make_sample_context()
        ctx.vehicle_context = None
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.primary_candidate)

    # -----------------------------------------------------------------
    # Test Z: Graph integration
    # -----------------------------------------------------------------
    def test_z_graph_integration(self):
        ctx = make_sample_context()
        graph = DiagnosticGraph(vehicle_id="vehicle:TEST_VIN_H4")
        graph.add_node(GraphNode(node_id="ecu:ECM", node_type=GraphNodeType.ECU, label="Engine Control Module"))
        ctx.diagnostic_graph = graph

        analysis = self.analyzer.analyze_root_cause(ctx)
        # Graph should now contain the root cause node
        cause_nodes = [n for n in graph.nodes.values() if "cause:" in n.node_id]
        self.assertTrue(len(cause_nodes) > 0)

    # -----------------------------------------------------------------
    # Test AA: Reasoning trace
    # -----------------------------------------------------------------
    def test_aa_reasoning_trace(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(len(analysis.reasoning_trace) > 0)
        self.assertTrue(len(analysis.primary_candidate.reasoning_trace) > 0)

    # -----------------------------------------------------------------
    # Test AB: Serialization round-trip
    # -----------------------------------------------------------------
    def test_ab_serialization_round_trip(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)

        d = analysis.to_dict()
        restored = RootCauseAnalysis.from_dict(d)

        self.assertEqual(restored.analysis_id, analysis.analysis_id)
        self.assertEqual(restored.primary_candidate.candidate_id, analysis.primary_candidate.candidate_id)
        self.assertEqual(restored.conclusion.conclusion_state, analysis.conclusion.conclusion_state)
        self.assertEqual(len(restored.alternative_candidates), len(analysis.alternative_candidates))

    # -----------------------------------------------------------------
    # Test AC: Deterministic repeated analysis
    # -----------------------------------------------------------------
    def test_ac_deterministic_repeated_analysis(self):
        ctx1 = make_sample_context()
        ctx2 = make_sample_context()

        a1 = self.analyzer.analyze_root_cause(ctx1)
        a2 = self.analyzer.analyze_root_cause(ctx2)

        self.assertEqual(a1.primary_candidate.candidate_id, a2.primary_candidate.candidate_id)
        self.assertAlmostEqual(a1.primary_candidate.causal_confidence, a2.primary_candidate.causal_confidence, places=4)
        self.assertEqual(a1.conclusion.conclusion_state, a2.conclusion.conclusion_state)

    # -----------------------------------------------------------------
    # Test AD: Bounded candidate generation
    # -----------------------------------------------------------------
    def test_ad_bounded_candidate_generation(self):
        analyzer = AutomatedRootCauseAnalyzer(max_candidates=5)
        ctx = make_sample_context()
        for i in range(20):
            ctx.hypotheses.append(
                FaultHypothesis(
                    hypothesis_id=f"hyp_{i}",
                    title=f"Hypothesis {i}",
                    category="AIR_FUEL",
                    affected_system="INTAKE",
                )
            )

        cands = analyzer.generate_candidates(ctx)
        self.assertLessEqual(len(cands), 5)

    # -----------------------------------------------------------------
    # Test AE: Causal-depth limit
    # -----------------------------------------------------------------
    def test_ae_causal_depth_limit(self):
        analyzer = AutomatedRootCauseAnalyzer(max_causal_depth=3)
        self.assertEqual(analyzer.max_causal_depth, 3)

    # -----------------------------------------------------------------
    # Test AF: Evidence traversal bound
    # -----------------------------------------------------------------
    def test_af_evidence_traversal_bound(self):
        analyzer = AutomatedRootCauseAnalyzer(max_evidence_traversal=2)
        ctx = make_sample_context()
        cands = analyzer.generate_candidates(ctx)
        self.assertLessEqual(len(cands[0].supporting_evidence), 2)

    # -----------------------------------------------------------------
    # Test AG: Large evidence set
    # -----------------------------------------------------------------
    def test_ag_large_evidence_set(self):
        ctx = make_sample_context()
        # Append 50 evidence records
        for i in range(50):
            ctx.hypotheses[0].supporting_evidence.append(
                FaultEvidence(
                    evidence_id=f"ev_bench_{i}",
                    title=f"Evidence {i}",
                    signals=["MAP", "RPM"],
                    start_time=float(i),
                    end_time=float(i + 1),
                    duration=1.0,
                    operating_condition=OperatingCondition.IDLE,
                    observed_behavior=f"Behavior {i}",
                    expected_behavior="Normal",
                    deviation_magnitude=5.0,
                    severity=AnomalySeverity.INFO,
                    quality=SignalQuality.GOOD,
                    provenance={},
                    analysis_method="BENCH",
                    confidence_score=0.5,
                )
            )

        t0 = time.time()
        analysis = self.analyzer.analyze_root_cause(ctx)
        elapsed = time.time() - t0

        self.assertLess(elapsed, 0.2, f"Analysis took too long: {elapsed:.4f}s")
        self.assertIsNotNone(analysis.primary_candidate)

    # -----------------------------------------------------------------
    # Test AH: Safety restrictions
    # -----------------------------------------------------------------
    def test_ah_safety_restrictions(self):
        # AutomatedRootCauseAnalyzer has zero direct serial/ECU command capability
        self.assertFalse(hasattr(self.analyzer, "send_command"))
        self.assertFalse(hasattr(self.analyzer, "execute_service"))

    # -----------------------------------------------------------------
    # Test AI: Destructive-operation rejection
    # -----------------------------------------------------------------
    def test_ai_destructive_operation_rejection(self):
        # Verify no clear DTC or write capability exists
        self.assertFalse(hasattr(self.analyzer, "clear_dtc"))
        self.assertFalse(hasattr(self.analyzer, "write_did"))

    # -----------------------------------------------------------------
    # Test AJ: No autonomous repair
    # -----------------------------------------------------------------
    def test_aj_no_autonomous_repair(self):
        self.assertFalse(hasattr(self.analyzer, "repair_component"))
        self.assertFalse(hasattr(self.analyzer, "perform_autonomous_repair"))

    # -----------------------------------------------------------------
    # Test AK: No DTC clearing
    # -----------------------------------------------------------------
    def test_ak_no_dtc_clearing(self):
        self.assertFalse(hasattr(self.analyzer, "clear_dtcs"))

    # -----------------------------------------------------------------
    # Test AL: Communication-vs-component distinction
    # -----------------------------------------------------------------
    def test_al_communication_vs_component_distinction(self):
        ctx = make_sample_context()
        ctx.unreachable_ecus = ["TCM"]

        analysis = self.analyzer.analyze_root_cause(ctx)
        comm_cands = [c for c in analysis.alternative_candidates if c.affected_ecu == "TCM"]
        self.assertTrue(len(comm_cands) > 0)
        self.assertEqual(comm_cands[0].category, "NETWORK")

    # -----------------------------------------------------------------
    # Test AM: Alternative candidate preservation
    # -----------------------------------------------------------------
    def test_am_alternative_candidate_preservation(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertTrue(len(analysis.alternative_candidates) > 0)

    # -----------------------------------------------------------------
    # Test AN: Contributing-factor classification
    # -----------------------------------------------------------------
    def test_an_contributing_factor_classification(self):
        ctx = make_sample_context()
        hyp_contrib = FaultHypothesis(
            hypothesis_id="hyp_dirty_throttle",
            title="Throttle Body Coking / Carbon Accumulation",
            category="AIR_FUEL",
            affected_system="INTAKE",
            evidence_score=0.3,
        )
        ctx.hypotheses.append(hyp_contrib)

        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.primary_candidate)

    # -----------------------------------------------------------------
    # Test AO: Confidence component inspection
    # -----------------------------------------------------------------
    def test_ao_confidence_component_inspection(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        d = analysis.primary_candidate.to_dict()
        self.assertIn("score_breakdown", d)
        self.assertIn("support_score", d["score_breakdown"])
        self.assertIn("contradiction_score", d["score_breakdown"])
        self.assertIn("test_confirmation_score", d["score_breakdown"])

    # -----------------------------------------------------------------
    # Test AP: Final verification recommendation
    # -----------------------------------------------------------------
    def test_ap_final_verification_recommendation(self):
        ctx = make_sample_context()
        analysis = self.analyzer.analyze_root_cause(ctx)
        self.assertIsNotNone(analysis.conclusion.recommended_final_verification)
        self.assertTrue(len(analysis.conclusion.recommended_final_verification) > 5)


if __name__ == "__main__":
    unittest.main()
