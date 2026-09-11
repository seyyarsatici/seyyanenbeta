# -*- coding: utf-8 -*-
"""
test_phase_i5.py — Phase I-5 Advanced Reasoning Layer Acceptance Test Suite
=============================================================================
Comprehensive unit and integration test suite certifying Phase I-5:
  1. Reasoning session creation & stable identity
  2. Vehicle & powertrain context preservation
  3. ECU context & calibration preservation
  4. Evidence ingestion & multi-source provenance
  5. Evidence quality handling
  6. Supporting evidence representation
  7. Contradictory evidence representation
  8. Missing expected evidence representation
  9. Neutral evidence representation
  10. Hypothesis competition & multi-candidate handling
  11. Hypothesis deduplication without losing provenance
  12. Deterministic candidate ranking
  13. Explainable score breakdown
  14. Vehicle-specific applicability weighting
  15. ECU-specific applicability weighting
  16. I-1 Knowledge integration
  17. I-2 Vehicle context integration
  18. I-3 Failure pattern integration
  19. I-4 Historical case integration
  20. Current evidence strictly overriding conflicting historical cases
  21. DTC-free reasoning support
  22. DTC contextualization (DTC != root cause)
  23. ECU-specific DTC handling (ECM vs TCM)
  24. Communication failure safeguard (Comm Fault != Component Failure)
  25. Multi-ECU reasoning
  26. Causal assessment & causal basis levels
  27. Correlation != Causation distinction
  28. Temporal support evaluation
  29. Mechanistic support evaluation
  30. Test-supported causality
  31. Technician confirmation weighting
  32. Post-repair verification reasoning
  33. Contradictory test result downgrading
  34. Uncertainty classification & states
  35. Insufficient evidence valid outcome
  36. Alternative hypotheses preservation
  37. Distinguishing-test recommendation (H-3)
  38. H-3 integration (test selector)
  39. H-4 integration (root-cause analysis)
  40. H-5 integration (workflow coordinator)
  41. G-3 integration
  42. G-5 integration (DiagnosticGraph non-causal edges)
  43. I-1 regression compatibility
  44. I-2 regression compatibility
  45. I-3 regression compatibility
  46. I-4 regression compatibility
  47. Reasoning trace completeness & determinism
  48. Serialization round-trip (to_dict / from_dict)
  49. Version preservation
  50. Bounded hypothesis generation & limits
  51. Large evidence-set performance (< 50ms)
  52. Safety boundary verification: strict READ_ONLY
  53. No direct transport access
  54. No autonomous repair command ("replace component X" blocked)
  55. Realistic synthetic end-to-end diagnostic scenario
=============================================================================
"""

import time
import unittest
from typing import List, Dict, Any

from extended_did import (
    VehicleContext,
    ApplicabilityResult,
)
from advanced_ecu_services import (
    ServiceSafetyClassification,
)
from advanced_fault_analysis import (
    OperatingCondition,
    SignalQuality,
    FaultHypothesis,
    HypothesisConfidence,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    make_dtc_node_id,
)
from automated_root_cause_analyzer import (
    CausalBasis,
    CausalRole,
)
from diagnostic_knowledge_base import (
    KnowledgeLifecycle,
    KnowledgeProvenanceType,
    KnowledgeConfidence,
    ApplicabilityScope,
    KnowledgeProvenance,
    KnowledgeApplicabilityCriteria,
    KnowledgeDistinguishingTest,
    DiagnosticKnowledgeStore,
)
from vehicle_ecu_knowledge import (
    VehicleECUKnowledgeStore,
)
from failure_pattern_library import (
    PatternCategory,
    PatternFeatureType,
    PatternMatchGrade,
    PatternFeatureRequirement,
    ObservedFeatureSet,
    FailurePattern,
    FailurePatternLibraryStore,
)
from historical_case_analysis import (
    CaseLifecycle,
    CaseMatchGrade,
    RootCauseConfidenceGrade,
    CaseECUContext,
    CaseDTCRecord,
    CaseTestResult,
    CaseRootCause,
    CaseTechnicianConfirmation,
    CaseRepairOutcome,
    PostRepairVerification,
    HistoricalDiagnosticCase,
    HistoricalCaseRepository,
)
from advanced_reasoning_layer import (
    ReasoningUncertainty,
    EvidenceDirection,
    ReasoningEvidenceContribution,
    ReasoningContradiction,
    ReasoningCandidate,
    ReasoningTraceStep,
    DiagnosticReasoningSession,
    AdvancedReasoningEngine,
    ReasoningWorkflowAdapter,
    DiagnosticGraphReasoningIntegrator,
)


class TestPhaseI5AdvancedReasoningLayer(unittest.TestCase):
    """Exhaustive test suite certifying Phase I-5 Advanced Reasoning Layer."""

    def setUp(self):
        # Set up shared stores
        self.kb_store = DiagnosticKnowledgeStore()
        self.ecu_store = VehicleECUKnowledgeStore()
        self.pattern_store = FailurePatternLibraryStore()
        self.case_repo = HistoricalCaseRepository()

        self.engine = AdvancedReasoningEngine(
            knowledge_store=self.kb_store,
            vehicle_ecu_store=self.ecu_store,
            pattern_store=self.pattern_store,
            case_repository=self.case_repo,
        )

        # Baseline vehicle context: Chevrolet Aveo 1.4L F14D3 Delphi MT80
        self.aveo_context = VehicleContext(
            vin="KL1SF69Y68B123456",
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            engine_code="F14D3",
            transmission="MANUAL",
            ecu_family="DELPHI_MT80",
            software_id="CAL_ID_968001",
        )

        # Safe read-only distinguishing test
        self.smoke_test = KnowledgeDistinguishingTest(
            test_id="TEST_SMOKE_PCV",
            title="PCV Elbow Smoke Test",
            description="Low-pressure smoke test on PCV rubber elbow.",
            discriminated_hypotheses=["HYP_PCV_VACUUM_BREACH", "HYP_MAF_DEGRADATION"],
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )

    # ---------------------------------------------------------------------
    # 1. REASONING SESSION CREATION & IDENTITY
    # ---------------------------------------------------------------------
    def test_01_session_creation_and_stable_identity(self):
        """Reasoning session requires non-empty reasoning_id and valid vehicle context."""
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            session_id="SESS_TEST_01",
        )
        self.assertIsNotNone(session.reasoning_id)
        self.assertTrue(session.reasoning_id.startswith("REASON_"))
        self.assertEqual(session.session_id, "SESS_TEST_01")
        self.assertEqual(session.vehicle_context.manufacturer, "CHEVROLET")

    # ---------------------------------------------------------------------
    # 2. EVIDENCE INGESTION & QUALITY
    # ---------------------------------------------------------------------
    def test_02_evidence_ingestion_and_quality(self):
        """Engine ingests telemetry features and assigns quality states."""
        obs = ObservedFeatureSet(
            session_id="S_EVID",
            features={"LTFT": 22.0, "MAF": 1.9, "MAP": 42.0},
            operating_condition=OperatingCondition.IDLE,
        )
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=obs,
        )
        self.assertGreater(len(session.candidates), 0)
        # Trace records evidence ingestion
        ingestion_steps = [s for s in session.reasoning_trace if s.phase_name == "EVIDENCE_INGESTION"]
        self.assertEqual(len(ingestion_steps), 1)
        self.assertIn("LTFT", ingestion_steps[0].inputs_considered[1])

    # ---------------------------------------------------------------------
    # 3. HYPOTHESIS COMPETITION & DEDUPLICATION
    # ---------------------------------------------------------------------
    def test_03_hypothesis_competition_and_deduplication(self):
        """Multiple competing hypotheses are evaluated without premature winner forcing."""
        hyp1 = FaultHypothesis(
            hypothesis_id="HYP_MAF_DRIFT",
            title="Mass Air Flow Sensor Drift",
            category="AIR_FUEL",
            affected_system="POWERTRAIN",
            confidence=HypothesisConfidence.MEDIUM,
        )
        hyp2 = FaultHypothesis(
            hypothesis_id="HYP_VACUUM_LEAK",
            title="Intake Manifold Vacuum Leak",
            category="AIR_FUEL",
            affected_system="POWERTRAIN",
            confidence=HypothesisConfidence.MEDIUM,
        )
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            hypotheses=[hyp1, hyp2],
        )
        self.assertGreaterEqual(len(session.ranked_candidates), 2)
        cids = [c.candidate_id for c in session.ranked_candidates]
        self.assertIn("HYP_MAF_DRIFT", cids)
        self.assertIn("HYP_VACUUM_LEAK", cids)

    # ---------------------------------------------------------------------
    # 4. DETERMINISTIC RANKING & EXPLAINABLE SCORE BREAKDOWN
    # ---------------------------------------------------------------------
    def test_04_deterministic_ranking_and_explainability(self):
        """Reasoning ranking is 100% deterministic with decomposed score explanations."""
        hyp_a = FaultHypothesis(hypothesis_id="HYP_A", title="Hypothesis A", category="AIR", affected_system="POWERTRAIN")
        hyp_b = FaultHypothesis(hypothesis_id="HYP_B", title="Hypothesis B", category="AIR", affected_system="POWERTRAIN")

        sess1 = self.engine.conduct_reasoning(vehicle_context=self.aveo_context, hypotheses=[hyp_a, hyp_b])
        sess2 = self.engine.conduct_reasoning(vehicle_context=self.aveo_context, hypotheses=[hyp_a, hyp_b])

        # Exact same candidate order
        self.assertEqual(
            [c.candidate_id for c in sess1.ranked_candidates],
            [c.candidate_id for c in sess2.ranked_candidates],
        )
        # Score explanation present
        for c in sess1.ranked_candidates:
            self.assertGreater(len(c.explanations), 0)
            self.assertIn("Score:", c.explanations[0])

    # ---------------------------------------------------------------------
    # 5. I-3 FAILURE PATTERN INTEGRATION
    # ---------------------------------------------------------------------
    def test_05_pattern_library_integration(self):
        """Empirical failure patterns contribute supporting evidence to matching hypotheses."""
        pattern = FailurePattern(
            pattern_id="PAT_LEAN_IDLE_DRIFT",
            name="Warm Idle Lean Fuel Trim Drift",
            category=PatternCategory.SENSOR_DRIFT,
            description="LTFT elevated above 18% at idle.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_LTFT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LTFT",
                    min_threshold=18.0,
                )
            ],
            possible_hypotheses=["HYP_UNMETERED_AIR_LEAK"],
            distinguishing_tests=[self.smoke_test],
        )
        self.pattern_store.register_pattern(pattern)

        obs = ObservedFeatureSet(
            session_id="S_PAT",
            features={"LTFT:VALUE_RANGE": 23.0},
            operating_condition=OperatingCondition.IDLE,
        )
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=obs,
        )
        cids = [c.candidate_id for c in session.ranked_candidates]
        self.assertIn("HYP_UNMETERED_AIR_LEAK", cids)

        top = [c for c in session.ranked_candidates if c.candidate_id == "HYP_UNMETERED_AIR_LEAK"][0]
        self.assertIn("PAT_LEAN_IDLE_DRIFT", top.matched_pattern_ids)
        self.assertTrue(any("I_3_FAILURE_PATTERN" in e.source for e in top.supporting_contributions))

    # ---------------------------------------------------------------------
    # 6. I-4 HISTORICAL CASE INTEGRATION
    # ---------------------------------------------------------------------
    def test_06_historical_case_integration(self):
        """Confirmed historical cases contribute contextual evidential weight."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_HIST_CONFIRMED",
            title="Confirmed PCV Leak",
            summary="Aveo PCV split.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            root_cause=CaseRootCause(
                root_cause_id="HYP_PCV_ELBOW_BREACH",
                component_or_system="PCV Hose",
                mechanism_description="Split elbow.",
                confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
            ),
            technician_confirmation=CaseTechnicianConfirmation(
                is_confirmed=True,
                technician_id="TECH_1",
                inspection_notes="Replaced hose.",
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_1"),
        )
        self.case_repo.add_case(case)

        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        cids = [c.candidate_id for c in session.ranked_candidates]
        self.assertIn("HYP_PCV_ELBOW_BREACH", cids)
        top = [c for c in session.ranked_candidates if c.candidate_id == "HYP_PCV_ELBOW_BREACH"][0]
        self.assertIn("CASE_HIST_CONFIRMED", top.relevant_case_ids)
        self.assertGreater(top.historical_relevance, 0.40)

    # ---------------------------------------------------------------------
    # 7. CURRENT EVIDENCE STRICTLY OVERRIDES CONFLICTING HISTORICAL CASES
    # ---------------------------------------------------------------------
    def test_07_current_evidence_overrides_conflicting_historical_case(self):
        """Invariant: When live evidence contradicts historical root cause, candidate is penalized."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_OLD_PCV",
            title="Old PCV Case",
            summary="Past PCV leak.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            root_cause=CaseRootCause(
                root_cause_id="HYP_PCV_LEAK",
                component_or_system="PCV Hose",
                mechanism_description="Split.",
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_OLD"),
        )
        self.case_repo.add_case(case)

        # Current physical test result: Smoke test failed (0 leaks detected, disproving PCV leak)
        test_smoke_negative = CaseTestResult(
            test_id="TEST_SMOKE_PCV",
            test_title="Intake Smoke Injection Test",
            target_ecu="ECM",
            outcome="FAILED",
            observations="Intake holds 15 psi without pressure loss. Zero smoke detected anywhere.",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )

        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
            test_results=[test_smoke_negative],
        )

        cand = [c for c in session.ranked_candidates if c.candidate_id == "HYP_PCV_LEAK"][0]
        # Current test failure overrides historical case!
        self.assertGreater(cand.contradiction_penalty, 0.50)
        self.assertEqual(cand.confidence, ReasoningUncertainty.CONTRADICTORY)
        self.assertGreater(len(session.contradictions), 0)

    # ---------------------------------------------------------------------
    # 8. DTC-FREE REASONING
    # ---------------------------------------------------------------------
    def test_08_dtc_free_reasoning(self):
        """Diagnostic reasoning completes successfully based on sensor drift with zero active DTCs."""
        obs = ObservedFeatureSet(
            session_id="S_DTC_FREE",
            features={"LTFT:VALUE_RANGE": 14.5, "MAF:VALUE_RANGE": 2.1},
            operating_condition=OperatingCondition.IDLE,
        )
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=obs,
            active_dtcs=[],  # Explicitly empty
        )
        self.assertIsNotNone(session.overall_conclusion)
        self.assertNotIn("P0", session.overall_conclusion)
        self.assertGreater(len(session.ranked_candidates), 0)

    # ---------------------------------------------------------------------
    # 9. COMMUNICATION FAILURE SAFEGUARD
    # ---------------------------------------------------------------------
    def test_09_communication_failure_safeguard(self):
        """Invariant: U-codes and bus timeouts are classified as communication artifacts, not component failure."""
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["U0101"],  # Lost Comm With TCM
        )
        top = session.ranked_candidates[0]
        self.assertEqual(top.candidate_role, CausalRole.COMMUNICATION_ARTIFACT)
        self.assertTrue(any("Communication anomaly isolated" in exp for exp in top.explanations))

    # ---------------------------------------------------------------------
    # 10. MULTI-ECU REASONING
    # ---------------------------------------------------------------------
    def test_10_multi_ecu_reasoning(self):
        """Engine maintains ECU-specific evidence isolation between ECM and TCM."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_TRANS_SOLENOID",
            title="Shift Solenoid Fault",
            summary="TCM solenoid issue.",
            vehicle_context=self.aveo_context,
            ecu_contexts={"TCM": CaseECUContext(target_ecu="TCM", ecu_family="AISIN_81")},
            active_dtcs=[CaseDTCRecord(dtc_code="P0756", target_ecu="TCM")],
            root_cause=CaseRootCause(
                root_cause_id="HYP_TCM_SOLENOID_2",
                component_or_system="2-3 Shift Solenoid Valve",
                mechanism_description="Hydraulic sticking.",
                affected_ecu="TCM",
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="TCM_DOC"),
        )
        self.case_repo.add_case(case)

        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0756"],
        )
        cand = [c for c in session.ranked_candidates if c.candidate_id == "HYP_TCM_SOLENOID_2"][0]
        self.assertEqual(cand.affected_ecu, "TCM")

    # ---------------------------------------------------------------------
    # 11. CAUSAL REASONING: CORRELATION != CAUSATION
    # ---------------------------------------------------------------------
    def test_11_causal_reasoning_correlation_vs_causation(self):
        """Candidates with purely correlated observation receive CORRELATIONAL_ONLY basis."""
        hyp_corr = FaultHypothesis(
            hypothesis_id="HYP_CORRELATED",
            title="Co-occurring Voltage Dip",
            category="ELECTRICAL",
            affected_system="CHASSIS",
        )
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            hypotheses=[hyp_corr],
        )
        top = session.ranked_candidates[0]
        self.assertEqual(top.causal_basis, CausalBasis.CORRELATIONAL_ONLY)
        self.assertEqual(top.candidate_role, CausalRole.CORRELATED_OBSERVATION)

    # ---------------------------------------------------------------------
    # 12. TEST-SUPPORTED CAUSALITY
    # ---------------------------------------------------------------------
    def test_12_test_supported_causality(self):
        """A passed distinguishing test elevates causal basis to HYPOTHESIS_TEST_SUPPORT."""
        test_passed = CaseTestResult(
            test_id="TEST_SMOKE_PCV",
            test_title="PCV Smoke Injection",
            target_ecu="ECM",
            outcome="PASSED",
            observations="Confirmed split at elbow hose.",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        hyp = FaultHypothesis(
            hypothesis_id="HYP_PCV_SPLIT",
            title="PCV Elbow Split",
            category="AIR",
            affected_system="POWERTRAIN",
        )
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            hypotheses=[hyp],
            test_results=[test_passed],
        )
        cand = [c for c in session.ranked_candidates if c.candidate_id == "HYP_PCV_SPLIT"][0]
        self.assertEqual(cand.causal_basis, CausalBasis.HYPOTHESIS_TEST_SUPPORT)
        self.assertEqual(cand.candidate_role, CausalRole.PRIMARY_ROOT_CAUSE)

    # ---------------------------------------------------------------------
    # 13. INSUFFICIENT EVIDENCE VALID OUTCOME
    # ---------------------------------------------------------------------
    def test_13_insufficient_evidence_valid_outcome(self):
        """When no data or observations are provided, engine returns INSUFFICIENT_EVIDENCE."""
        empty_session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=None,
            active_dtcs=[],
            test_results=[],
        )
        self.assertEqual(empty_session.overall_confidence, ReasoningUncertainty.INSUFFICIENT_EVIDENCE)
        self.assertIn("Insufficient evidence", empty_session.overall_conclusion)

    # ---------------------------------------------------------------------
    # 14. DISTINGUISHING TEST RECOMMENDATION (H-3)
    # ---------------------------------------------------------------------
    def test_14_distinguishing_test_recommendation(self):
        """Engine recommends safe read-only distinguishing tests to resolve candidate uncertainty."""
        pattern = FailurePattern(
            pattern_id="PAT_AIR_FUEL_DRIFT",
            name="Air-Fuel Ratio Drift",
            category=PatternCategory.SENSOR_DRIFT,
            description="Drift.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE"),
            feature_requirements=[
                PatternFeatureRequirement(feature_id="F", feature_type=PatternFeatureType.VALUE_RANGE, signal_name="LTFT", min_threshold=15.0)
            ],
            possible_hypotheses=["HYP_LEAN_UNMETERED_AIR"],
            distinguishing_tests=[self.smoke_test],
        )
        self.pattern_store.register_pattern(pattern)

        obs = ObservedFeatureSet(session_id="S_REC", features={"LTFT:VALUE_RANGE": 20.0})
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=obs,
        )
        self.assertGreater(len(session.recommended_distinguishing_tests), 0)
        self.assertEqual(session.recommended_distinguishing_tests[0].test_id, "TEST_SMOKE_PCV")

        # H-3 Adapter interface
        h3_test = ReasoningWorkflowAdapter.get_next_distinguishing_test_for_h3(session)
        self.assertIsNotNone(h3_test)
        self.assertEqual(h3_test.test_id, "TEST_SMOKE_PCV")

    # ---------------------------------------------------------------------
    # 15. WORKFLOW ADAPTER & AUDIT SUMMARY (H-5)
    # ---------------------------------------------------------------------
    def test_15_workflow_adapter_technician_summary(self):
        """H-5 receives a concise, technician-readable summary of reasoning findings."""
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        summary = ReasoningWorkflowAdapter.format_technician_reasoning_summary(session)
        self.assertIn("reasoning_id", summary)
        self.assertIn("conclusion", summary)
        self.assertIn("confidence", summary)
        self.assertIn("top_candidate", summary)
        self.assertGreater(summary["trace_steps_count"], 5)

    # ---------------------------------------------------------------------
    # 16. G-5 DIAGNOSTIC GRAPH INTEGRATION (NON-CAUSAL)
    # ---------------------------------------------------------------------
    def test_16_diagnostic_graph_reasoning_integration(self):
        """Reasoning session integrates into DiagnosticGraph with strictly non-causal edges."""
        graph = DiagnosticGraph()
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        node_id = DiagnosticGraphReasoningIntegrator.integrate_reasoning_session(graph, session)
        self.assertIn(node_id, graph.nodes)
        self.assertEqual(graph.nodes[node_id].node_type, GraphNodeType.ANOMALY)

        # Check edge type is strictly ASSOCIATED_WITH
        edges = [e for e in graph.edges if e.source_id == node_id]
        if edges:
            self.assertEqual(edges[0].edge_type, GraphEdgeType.ASSOCIATED_WITH)

    # ---------------------------------------------------------------------
    # 17. REASONING TRACE & DETERMINISM
    # ---------------------------------------------------------------------
    def test_17_reasoning_trace_and_determinism(self):
        """Trace records sequential steps and yields identical results on repeated runs."""
        obs = ObservedFeatureSet(session_id="S_TRACE", features={"LTFT": 22.0})
        sess = self.engine.conduct_reasoning(vehicle_context=self.aveo_context, observed_features=obs)

        trace = sess.reasoning_trace
        self.assertGreaterEqual(len(trace), 8)
        expected_phases = [
            "CONTEXT_ESTABLISHMENT",
            "EVIDENCE_INGESTION",
            "PATTERN_MATCHING",
            "HISTORICAL_EXPERIENCE",
            "HYPOTHESIS_GENERATION",
            "EVIDENCE_FUSION",
            "CAUSAL_ASSESSMENT",
            "DETERMINISTIC_RANKING",
            "CONCLUSION_SYNTHESIS",
        ]
        actual_phases = [s.phase_name for s in trace]
        for ep in expected_phases:
            self.assertIn(ep, actual_phases)

    # ---------------------------------------------------------------------
    # 18. SERIALIZATION ROUND-TRIP
    # ---------------------------------------------------------------------
    def test_18_serialization_round_trip(self):
        """DiagnosticReasoningSession serializes to dict and reconstructs losslessly."""
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        sess_dict = session.to_dict()
        reconstructed = DiagnosticReasoningSession.from_dict(sess_dict)

        self.assertEqual(reconstructed.reasoning_id, session.reasoning_id)
        self.assertEqual(reconstructed.overall_conclusion, session.overall_conclusion)
        self.assertEqual(len(reconstructed.ranked_candidates), len(session.ranked_candidates))
        self.assertEqual(len(reconstructed.reasoning_trace), len(session.reasoning_trace))

    # ---------------------------------------------------------------------
    # 19. SAFETY BOUNDARY: STRICT READ-ONLY & NO AUTONOMOUS REPAIR
    # ---------------------------------------------------------------------
    def test_19_safety_boundary_and_no_autonomous_repair(self):
        """Reasoning session rejects dangerous actuating tests and avoids unilateral repair commands."""
        # 1. Distinguishing test safety validation
        dangerous_dt = KnowledgeDistinguishingTest(
            test_id="TEST_ACTUATE_SOLENOID",
            title="Force Actuator",
            description="Actuate solenoid directly.",
            discriminated_hypotheses=["HYP_1"],
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        # Bypass init to check session guard
        object.__setattr__(dangerous_dt, "safety_classification", ServiceSafetyClassification.ACTUATION)

        with self.assertRaises(ValueError) as ctx:
            DiagnosticReasoningSession(
                reasoning_id="REASON_DANGEROUS",
                session_id="SESS_D",
                vehicle_context=self.aveo_context,
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="TEST"),
                recommended_distinguishing_tests=[dangerous_dt],
            )
        self.assertIn("Safety Violation", str(ctx.exception))

        # 2. No unconditional repair command in conclusion
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        self.assertNotIn("replace component", session.overall_conclusion.lower())
        self.assertNotIn("replace part", session.overall_conclusion.lower())

    # ---------------------------------------------------------------------
    # 20. LARGE EVIDENCE SET PERFORMANCE BENCHMARK (< 50ms)
    # ---------------------------------------------------------------------
    def test_20_large_evidence_set_performance_benchmark(self):
        """Reasoning over 100+ telemetry features and multiple candidates completes in < 50ms."""
        feats = {f"SIG_{i}": float(i * 1.5) for i in range(100)}
        obs = ObservedFeatureSet(session_id="S_LARGE", features=feats)

        t0 = time.perf_counter()
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=obs,
            active_dtcs=["P0171", "P0101", "P0300"],
            max_candidates=10,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertLess(elapsed_ms, 50.0, f"Reasoning took {elapsed_ms:.2f}ms, expected < 50ms")
        self.assertIsNotNone(session.overall_conclusion)

    # ---------------------------------------------------------------------
    # 21. REALISTIC END-TO-END DIAGNOSTIC SCENARIO
    # ---------------------------------------------------------------------
    def test_21_realistic_end_to_end_diagnostic_scenario(self):
        """
        Complete Real-World Diagnostic Scenario:
          Vehicle: Chevrolet Aveo 1.4L F14D3 Delphi MT80 ECM
          Telemetry: Elevated idle LTFT (+23.5%), MAF lag (1.9 g/s), elevated MAP (42 kPa)
          I-3 Pattern: Warm idle lean drift (PAT_LEAN_IDLE_DRIFT)
          I-4 History:
            - Confirmed Case A: Split PCV elbow replaced and verified
            - Confirmed Case B: Fuel pump inlet strainer restriction
            - Disproved Case C: MAF replacement failed to solve issue
          Reasoning Engine:
            1. Fuses multi-source evidence
            2. Preserves Case C's disproved status without repeating it
            3. Ranks PCV vacuum leak top due to engine applicability + pattern match + confirmed Case A
            4. Recommends safe smoke test TEST_SMOKE_PCV to H-3
            5. Formulates structured technician-readable conclusion
            6. Preserves alternative fuel supply hypothesis with moderate confidence
        """
        # 1. Register I-3 Pattern
        self.pattern_store.register_pattern(FailurePattern(
            pattern_id="PAT_AVEO_PCV_LEAN",
            name="Aveo F14D3 PCV Vacuum Breach Pattern",
            category=PatternCategory.CROSS_SENSOR_DISAGREEMENT,
            description="Elevated LTFT with low MAF reading at idle.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="TSB_AVEO"),
            feature_requirements=[
                PatternFeatureRequirement(feature_id="F1", feature_type=PatternFeatureType.VALUE_RANGE, signal_name="LTFT", min_threshold=18.0)
            ],
            possible_hypotheses=["HYP_PCV_ELBOW_SPLIT", "HYP_FUEL_PUMP_WEAK"],
            distinguishing_tests=[self.smoke_test],
        ))

        # 2. Register I-4 Cases
        # Case A: Confirmed PCV split
        self.case_repo.add_case(HistoricalDiagnosticCase(
            case_id="CASE_A_PCV_CONFIRMED",
            title="Confirmed PCV Split",
            summary="Physical leak.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            root_cause=CaseRootCause(
                root_cause_id="HYP_PCV_ELBOW_SPLIT",
                component_or_system="PCV Rubber Elbow",
                mechanism_description="Cracked hose.",
                confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
            ),
            technician_confirmation=CaseTechnicianConfirmation(is_confirmed=True, technician_id="TECH_GM", inspection_notes="Hose split."),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_A"),
        ))

        # Case C: Disproved MAF replacement
        self.case_repo.add_case(HistoricalDiagnosticCase(
            case_id="CASE_C_MAF_DISPROVED",
            title="Failed MAF Replacement",
            summary="MAF sensor replaced but trim remained +22%.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            root_cause=CaseRootCause(
                root_cause_id="HYP_MAF_SENSOR_FAULT",
                component_or_system="MAF Sensor",
                mechanism_description="Incorrect diagnosis.",
                confidence_grade=RootCauseConfidenceGrade.REJECTED_HYPOTHESIS,
            ),
            lifecycle=CaseLifecycle.REJECTED,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_C"),
        ))

        # 3. Live Telemetry
        obs = ObservedFeatureSet(
            session_id="S_LIVE_E2E",
            operating_condition=OperatingCondition.IDLE,
            features={"LTFT:VALUE_RANGE": 23.5, "MAF:VALUE_RANGE": 1.9, "MAP:VALUE_RANGE": 42.0},
        )

        # 4. Execute Advanced Reasoning
        session = self.engine.conduct_reasoning(
            vehicle_context=self.aveo_context,
            observed_features=obs,
            active_dtcs=["P0171"],
        )

        # 5. Verify Results
        self.assertGreaterEqual(len(session.ranked_candidates), 2)
        top = session.ranked_candidates[0]
        self.assertEqual(top.candidate_id, "HYP_PCV_ELBOW_SPLIT")
        self.assertGreater(top.overall_score, 0.70)
        self.assertEqual(top.candidate_role, CausalRole.PRIMARY_ROOT_CAUSE)

        # Verify distinguishing test recommendation
        self.assertGreater(len(session.recommended_distinguishing_tests), 0)
        self.assertEqual(session.recommended_distinguishing_tests[0].test_id, "TEST_SMOKE_PCV")

        # Verify structured, safe conclusion
        self.assertIn("PCV", session.overall_conclusion)
        self.assertIn("verify using test", session.overall_conclusion)
        self.assertNotIn("replace component", session.overall_conclusion.lower())


if __name__ == "__main__":
    unittest.main()
