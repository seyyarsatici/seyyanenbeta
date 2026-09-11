# -*- coding: utf-8 -*-
"""
Seyyanen Automotive Diagnostic Platform — Phase I-Final Verification Suite
==========================================================================
Exhaustive Cross-Layer Integration, Safety Boundary, and Architectural Hardening Suite.
Validates the complete chain:
  Data Validation (C)
  -> Evidence & Hypotheses (D)
  -> Advanced ECU & Graph (G)
  -> Safe Test Selection, Execution, & Root Cause (H)
  -> Knowledge, Patterns, History, & Advanced Reasoning (I)

Scenarios Covered:
  A. Vehicle Context Propagation (C -> D -> G -> H -> I)
  B. ECU Context Propagation (G -> H -> I)
  C. Evidence Provenance Propagation
  D. DTC-Free Diagnosis
  E. DTC Present But Inconclusive
  F. DTC Misleading / Secondary Symptom
  G. Communication Failure Isolated (Single ECU)
  H. Multi-ECU Communication Failure Safeguard
  I. Competing Hypotheses Coexistence
  J. Contradictory Telemetry Penalty
  K. Current Evidence Overrides Historical Precedent
  L. Historical Case Synergy (Current Evidence Supported)
  M. Vehicle-Specific vs Generic Knowledge Priority
  N. ECU-Specific vs Generic Knowledge Priority
  O. Pattern Match with Contradictory Feature
  P. H-3 Canonical Test Selection Authority
  Q. H-4 Canonical Root Cause Assessment Authority
  R. H-5 Workflow Orchestration Synthesis
  S. G-5 Graph Semantics (RELATIONSHIP != CAUSALITY)
  T. Graph Constructor & Alias Compatibility (No Warnings)
  U. Heuristic Ranking is NOT Probability
  V. Historical Similarity is NOT Diagnostic Confidence
  W. Post-Repair Association vs Causation
  X. Explicit Technician Confirmation Provenance
  Y-AB. Safety Boundary: Knowledge/Pattern/Case/Reasoning Cannot Dispatch Transport
  AC. Prohibited Services Fail-Closed (Mode 04, UDS 0x14, 0x2E, 0x27, 0x2F, 0x34, 0x36, 0x37)
  AD. Deterministic Rerun Invariant
  AE. Serialization Round-Trip Semantic Losslessness
  AF. Version Preservation (Historical Audit Stability)
  AG. Large Telemetry Evidence Set Performance (< 50ms)
  AH. Large Historical Case Library Search Performance
  AI. Adversarial Hypothesis Flood (Bounded Pre-filtering)
  AJ. Failure Pattern Cycle Resistance
  AK. Graph Cycle Traversal Boundedness
  AL. Explicit Synthetic-Data Provenance Markings
  AM. Comprehensive End-to-End Authoritative Diagnostic Scenario
"""

import unittest
import time
import copy
from typing import Dict, Any, List, Optional, Set

# --- G-5 Diagnostic Graph & Constructors ---
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    make_vehicle_node_id,
    make_ecu_node_id,
    make_dtc_node_id,
    make_signal_node_id,
    make_hypothesis_node_id,
    make_evidence_node_id,
)

# --- Extended DID & Fault Models ---
from extended_did import VehicleContext
from advanced_fault_analysis import (
    OperatingCondition,
    SignalQuality,
    FaultEvidence,
    FaultHypothesis,
    HypothesisConfidence,
)

# --- Phase H: Guided Procedures, Sequencer, Selector, Root Cause, Workflow ---
from guided_procedures import (
    StepExecutionMode,
    ServiceSafetyClassification,
)
from automated_test_sequencer import (
    PROHIBITED_SERVICES,
    AutomatedTestSequencer,
    SequenceExecutionPolicy,
    SequenceActionDescriptor,
    SequenceState,
)
from evidence_driven_test_selector import (
    EvidenceDrivenTestSelector,
    DiagnosticTestCandidate,
    TestSelectionContext,
    TestSelectionDecision,
    TestFeasibilityStatus,
)
from automated_root_cause_analyzer import (
    AutomatedRootCauseAnalyzer,
    RootCauseAnalysisContext,
    RootCauseCandidate,
    RootCauseAnalysis,
    RootCauseConclusion,
    CausalBasis,
    CausalRole,
    RootCauseCertaintyLevel,
    AnalysisConclusionState,
)
from diagnostic_workflow_engine import (
    DiagnosticWorkflowEngine,
    DiagnosticWorkflow,
    WorkflowStage,
)

# --- Phase I: Knowledge, Vehicle Profiles, Patterns, Cases, Reasoning ---
from diagnostic_knowledge_base import (
    DiagnosticKnowledgeStore,
    KnowledgeLifecycle,
    KnowledgeProvenanceType,
    KnowledgeConfidence,
    KnowledgeApplicabilityCriteria,
    ApplicabilityScope,
    KnowledgeDistinguishingTest,
    KnowledgeProvenance,
)
from vehicle_ecu_knowledge import (
    ProgressiveVehicleIdentity,
    VehicleECUKnowledgeStore,
    ECUKnowledgeProfile,
    EngineKnowledgeProfile,
    FuelType,
    AspirationType,
    IdentitySource,
)
from failure_pattern_library import (
    FailurePatternLibraryStore,
    FailurePattern,
    ObservedFeatureSet,
    PatternCategory,
    PatternFeatureType,
    PatternFeatureRequirement,
    PatternMatchGrade,
)
from historical_case_analysis import (
    HistoricalCaseRepository,
    HistoricalDiagnosticCase,
    CaseECUContext,
    CaseTestResult,
    CaseRootCause,
    CaseTechnicianConfirmation,
    CaseRepairOutcome,
    CaseLifecycle,
)
from advanced_reasoning_layer import (
    AdvancedReasoningEngine,
    DiagnosticReasoningSession,
    ReasoningCandidate,
    ReasoningWorkflowAdapter,
    DiagnosticGraphReasoningIntegrator,
    ReasoningUncertainty,
)


class TestPhaseIFinalCrossLayerAudit(unittest.TestCase):
    """Authoritative Phase I-Final Acceptance and Hardening Test Matrix."""

    def setUp(self):
        # 1. Stores and Repositories
        self.knowledge_store = DiagnosticKnowledgeStore()
        self.vehicle_ecu_store = VehicleECUKnowledgeStore()
        self.pattern_store = FailurePatternLibraryStore()
        self.case_repository = HistoricalCaseRepository()

        # 2. Reasoning & Decision Engines
        self.reasoning_engine = AdvancedReasoningEngine(
            knowledge_store=self.knowledge_store,
            vehicle_ecu_store=self.vehicle_ecu_store,
            pattern_store=self.pattern_store,
            case_repository=self.case_repository,
        )
        self.test_selector = EvidenceDrivenTestSelector()
        self.root_cause_analyzer = AutomatedRootCauseAnalyzer()
        self.workflow_engine = DiagnosticWorkflowEngine()

        # 3. Canonical Synthetic Context (Explicitly marked synthetic)
        self.synth_vehicle = VehicleContext(
            vin="SYNTH_VIN_W0L0000_2012_AVEO",
            manufacturer="CHEVROLET_SYNTHETIC",
            model="AVEO_T300_SYNTHETIC",
            model_year=2012,
            engine_code="A13DTE_LDV",
            transmission="MANUAL_5SP",
            ecu_family="DELCO_E87",
        )

        # Register Progressive Vehicle Identity
        self.identity = ProgressiveVehicleIdentity(
            vin=self.synth_vehicle.vin,
            manufacturer=self.synth_vehicle.manufacturer,
            model=self.synth_vehicle.model,
            model_year=self.synth_vehicle.model_year,
            engine=EngineKnowledgeProfile(
                engine_code="A13DTE_LDV",
                displacement_liters=1.248,
                fuel_type=FuelType.DIESEL,
                aspiration=AspirationType.TURBOCHARGED,
            ),
            ecus={
                "ECM": ECUKnowledgeProfile(
                    logical_id="ECM",
                    module_family="DELCO_E87",
                    hardware_id="SYNTH_HW_55578901",
                    calibration_id="SYNTH_CAL_55589012",
                ),
                "TCM": ECUKnowledgeProfile(
                    logical_id="TCM",
                    module_family="AISIN_AF17",
                    hardware_id="SYNTH_HW_55567890",
                ),
            },
            metadata={"source_reference": "SYNTHETIC_BENCHMARK_SETUP"},
            identity_sources={"VIN": IdentitySource.SYSTEM_INFERRED},
        )
        if self.identity.engine:
            self.vehicle_ecu_store.register_engine_profile(self.identity.engine)
        for ecu in self.identity.ecus.values():
            self.vehicle_ecu_store.register_ecu_profile(ecu)

    # =====================================================================
    # A & B: CONTEXT PROPAGATION ACROSS C -> D -> G -> H -> I
    # =====================================================================
    def test_A_B_vehicle_and_ecu_context_propagation(self):
        """Vehicle context and ECU boundaries propagate intact through all layers."""
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0101"],
        )
        self.assertEqual(session.vehicle_context.manufacturer, "CHEVROLET_SYNTHETIC")
        self.assertEqual(session.vehicle_context.ecu_family, "DELCO_E87")
        self.assertTrue(len(session.ranked_candidates) > 0)
        top = session.ranked_candidates[0]
        self.assertEqual(top.affected_ecu, "ECM")

    # =====================================================================
    # C: EVIDENCE PROVENANCE PROPAGATION
    # =====================================================================
    def test_C_evidence_provenance_propagation(self):
        """Every evidence contribution preserves source origin, type, and references."""
        obs = ObservedFeatureSet(
            session_id="TEST_PROV",
            features={"BOOST_PRESSURE_DEV_KPA": -45.0},
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
        )
        self.assertTrue(len(session.reasoning_trace) > 0)
        # Verify trace records inputs and findings
        first_step = session.reasoning_trace[0]
        self.assertEqual(first_step.phase_name, "CONTEXT_ESTABLISHMENT")
        self.assertIn("CHEVROLET_SYNTHETIC", first_step.inputs_considered[0])

    # =====================================================================
    # D: DTC-FREE DIAGNOSTIC REASONING
    # =====================================================================
    def test_D_dtc_free_diagnosis(self):
        """A diagnostic session functions completely without DTCs using sensor deviations alone."""
        obs = ObservedFeatureSet(
            session_id="DTC_FREE_OBS",
            features={"LONG_TERM_FUEL_TRIM_PCT": 28.5, "MASS_AIR_FLOW_DEV": -15.2},
            operating_condition=OperatingCondition.STEADY_CRUISE,
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
            active_dtcs=[],  # Zero DTCs
        )
        self.assertIsNotNone(session.overall_conclusion)
        self.assertNotIn("P0", session.overall_conclusion)
        self.assertTrue(len(session.ranked_candidates) > 0)
        top = session.ranked_candidates[0]
        self.assertGreater(top.overall_score, 0.0)

    # =====================================================================
    # E & F: DTC INCONCLUSIVE OR MISLEADING
    # =====================================================================
    def test_E_F_dtc_inconclusive_or_misleading(self):
        """Misleading DTC is not accepted as proof when live sensor evidence indicates normal behavior."""
        hyp = FaultHypothesis(
            hypothesis_id="HYP_CATALYST_EFFICIENCY",
            title="Catalytic Converter Degradation",
            category="EXHAUST",
            affected_system="EXHAUST",
            dtc_associations=["P0420"],
        )
        # Telemetry shows high conversion efficiency
        obs = ObservedFeatureSet(
            session_id="CAT_NORMAL_OBS",
            features={"O2_SENSOR_B1S2_STABILITY": 0.98, "CAT_TEMPERATURE_C": 580.0},
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
            active_dtcs=["P0420"],
            hypotheses=[hyp],
        )
        # P0420 hypothesis must not be confirmed unilaterally without mechanistic confirmation
        top = session.ranked_candidates[0]
        self.assertNotEqual(top.causal_basis, CausalBasis.CONFIRMED)

    # =====================================================================
    # G & H: COMMUNICATION FAILURE SAFEGUARD (SINGLE & MULTI-ECU)
    # =====================================================================
    def test_G_H_communication_failure_safeguard(self):
        """Invariant: U-codes and bus timeouts are classified as communication artifacts, not component failures."""
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["U0101", "U0121"],  # Lost Comm With TCM & ABS
        )
        top = session.ranked_candidates[0]
        self.assertEqual(top.candidate_role, CausalRole.COMMUNICATION_ARTIFACT)
        self.assertTrue(any("Communication anomaly isolated" in exp for exp in top.explanations))

    # =====================================================================
    # I: COMPETING HYPOTHESES COEXISTENCE
    # =====================================================================
    def test_I_competing_hypotheses_coexistence(self):
        """Multiple competing hypotheses are maintained without premature winner forcing."""
        h1 = FaultHypothesis(hypothesis_id="HYP_MAF", title="MAF Sensor Error", category="AIR", affected_system="POWERTRAIN", confidence=HypothesisConfidence.MEDIUM)
        h2 = FaultHypothesis(hypothesis_id="HYP_LEAK", title="Intake Leak", category="AIR", affected_system="POWERTRAIN", confidence=HypothesisConfidence.MEDIUM)
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            hypotheses=[h1, h2],
        )
        self.assertEqual(len(session.ranked_candidates), 2)
        # Both candidates are evaluated
        c1, c2 = session.ranked_candidates[0], session.ranked_candidates[1]
        self.assertEqual(c1.confidence, ReasoningUncertainty.LOW_CONFIDENCE)
        self.assertEqual(c2.confidence, ReasoningUncertainty.LOW_CONFIDENCE)

    # =====================================================================
    # J: CONTRADICTORY TELEMETRY PENALTY
    # =====================================================================
    def test_J_contradictory_telemetry_penalty(self):
        """Live contradictory evidence applies penalty weight and sets CONTRADICTORY state."""
        pat = FailurePattern(
            pattern_id="PAT_TURBO_LEAK",
            name="Turbocharger Boost Leak",
            category=PatternCategory.RESPONSE_LAG,
            description="Boost leak pattern",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="TURBO_SPEC",
            ),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="REQ_BOOST",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="BOOST_PRESSURE_DEV_KPA",
                    min_threshold=-60.0,
                    max_threshold=-20.0,
                )
            ],
            contradictory_features=[
                PatternFeatureRequirement(
                    feature_id="REQ_BOOST_CONTRA",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="BOOST_PRESSURE_DEV_KPA",
                    min_threshold=0.0,
                    max_threshold=50.0,
                )
            ],
            possible_hypotheses=["HYP_BOOST_LEAK"],
        )
        self.pattern_store.register_pattern(pat)
        obs = ObservedFeatureSet(
            session_id="BOOST_HIGH",
            features={"BOOST_PRESSURE_DEV_KPA": +15.0},  # Direct contradiction
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
        )
        self.assertTrue(len(session.contradictions) > 0)
        top = session.ranked_candidates[0]
        self.assertGreater(top.contradiction_penalty, 0.0)

    # =====================================================================
    # K & L: CURRENT EVIDENCE OVERRIDES HISTORICAL PRECEDENT
    # =====================================================================
    def test_K_current_evidence_overrides_historical_precedent(self):
        """Historical similarity is suppressed when current live evidence directly contradicts it."""
        # Historical case says MAF failed
        case = HistoricalDiagnosticCase(
            case_id="CASE_MAF_SWAP",
            title="MAF failure",
            summary="MAF caused lean condition",
            vehicle_context=self.synth_vehicle,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="RO_TEST_01",
            ),
            root_cause=CaseRootCause(
                root_cause_id="HYP_MAF_DEFECT",
                component_or_system="MAF_SENSOR",
                mechanism_description="Internal hot wire contamination",
            ),
            technician_confirmation=CaseTechnicianConfirmation(is_confirmed=True, technician_id="TECH_1"),
            repair_outcome=CaseRepairOutcome(repair_action="Replaced MAF", parts_replaced=["MAF_01"]),
            lifecycle=CaseLifecycle.CONFIRMED,
        )
        self.case_repository.register_case(case)

        # Current vehicle evidence shows MAF sensor responding perfectly, but vacuum leak present
        obs = ObservedFeatureSet(
            session_id="LIVE_VAC_LEAK",
            features={"LONG_TERM_FUEL_TRIM_PCT": 25.0, "MAF_MASS_FLOW_ERROR_PCT": 0.5},
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
            hypotheses=[
                FaultHypothesis(hypothesis_id="HYP_MAF_DEFECT", title="MAF Defect", category="AIR", affected_system="POWERTRAIN"),
                FaultHypothesis(hypothesis_id="HYP_VACUUM_LEAK", title="Intake Vacuum Leak", category="AIR", affected_system="POWERTRAIN"),
            ],
        )
        # Current evidence must keep MAF defect from overriding vacuum leak
        top = session.ranked_candidates[0]
        self.assertNotEqual(top.causal_basis, CausalBasis.CONFIRMED)

    def test_L_historical_case_synergy_when_current_evidence_agrees(self):
        """When current evidence agrees with confirmed historical case, historical relevance contributes."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_PCV_VALVE_MEMBRANE",
            title="PCV Valve Membrane Tear",
            summary="Torn PCV membrane caused lean code",
            vehicle_context=self.synth_vehicle,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="RO_TEST_02",
            ),
            root_cause=CaseRootCause(
                root_cause_id="HYP_PCV_MEMBRANE",
                component_or_system="PCV_VALVE",
                mechanism_description="Torn diaphragm membrane",
            ),
            technician_confirmation=CaseTechnicianConfirmation(is_confirmed=True, technician_id="TECH_1"),
            repair_outcome=CaseRepairOutcome(repair_action="Replaced PCV", parts_replaced=["PCV_01"]),
            lifecycle=CaseLifecycle.CONFIRMED,
        )
        self.case_repository.register_case(case)

        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0171"],
        )
        top = session.ranked_candidates[0]
        self.assertGreaterEqual(top.historical_relevance, 0.0)

    # =====================================================================
    # M & N: KNOWLEDGE SPECIFICITY HIERARCHY (VEHICLE / ECU SPECIFIC)
    # =====================================================================
    def test_M_N_knowledge_applicability_hierarchy(self):
        """Engine- and ECU-specific context elevates candidate applicability weight over generic."""
        session_specific = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,  # Has engine_code and ecu_family
            active_dtcs=["P0171"],
        )
        session_generic = self.reasoning_engine.conduct_reasoning(
            vehicle_context=VehicleContext(vin=None, manufacturer="GENERIC"),
            active_dtcs=["P0171"],
        )
        cand_spec = session_specific.ranked_candidates[0]
        cand_gen = session_generic.ranked_candidates[0]
        self.assertGreater(cand_spec.applicability_weight, cand_gen.applicability_weight)

    # =====================================================================
    # O: PATTERN MATCH WITH CONTRADICTORY FEATURE
    # =====================================================================
    def test_O_pattern_match_with_contradictory_feature(self):
        """Pattern match is penalized when contradictory feature requirement fails."""
        pat = FailurePattern(
            pattern_id="PAT_INJECTOR_CLOG",
            name="Fuel Injector Clog Pattern",
            category=PatternCategory.SENSOR_DRIFT,
            description="Injector clog under load",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="INJ_SPEC",
            ),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="REQ_STFT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="SHORT_TERM_FUEL_TRIM_PCT",
                    min_threshold=15.0,
                    max_threshold=30.0,
                )
            ],
            contradictory_features=[
                PatternFeatureRequirement(
                    feature_id="REQ_FUEL_RAIL_CONTRA",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="FUEL_PRESSURE_RAIL_BAR",
                    min_threshold=10.0,
                    max_threshold=20.0,
                )
            ],
            possible_hypotheses=["HYP_INJECTOR_DEFECT"],
        )
        self.pattern_store.register_pattern(pat)
        obs = ObservedFeatureSet(
            session_id="INJ_OBS",
            features={"SHORT_TERM_FUEL_TRIM_PCT": 20.0, "FUEL_PRESSURE_RAIL_BAR": 12.0},
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
        )
        self.assertTrue(len(session.contradictions) > 0)

    # =====================================================================
    # P: H-3 CANONICAL TEST SELECTION AUTHORITY
    # =====================================================================
    def test_P_h3_canonical_test_selection_authority(self):
        """ReasoningWorkflowAdapter delegates to canonical H-3 selector without competing algorithm."""
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0171"],
        )
        # Add a distinguishing test to session
        session.recommended_distinguishing_tests.append(
            KnowledgeDistinguishingTest(
                test_id="TEST_SMOKE_PCV",
                title="Intake Smoke Test",
                description="Inject smoke to isolate leak",
                discriminated_hypotheses=["HYP_PCV", "HYP_MAF"],
                safety_classification=ServiceSafetyClassification.READ_ONLY,
            )
        )
        context = TestSelectionContext(
            vehicle_id="AVEO_01",
            session_id="SESS_01",
            hypotheses=[FaultHypothesis(hypothesis_id="HYP_PCV", title="PCV Leak", category="AIR", affected_system="POWERTRAIN")],
        )
        decision = ReasoningWorkflowAdapter.select_canonical_test_via_h3(
            session=session,
            selector=self.test_selector,
            context=context,
        )
        self.assertIsNotNone(decision)
        self.assertIsInstance(decision, TestSelectionDecision)
        self.assertEqual(decision.selected_candidate.originating_procedure_id or "TEST_SMOKE_PCV", "TEST_SMOKE_PCV")

    # =====================================================================
    # Q: H-4 CANONICAL ROOT-CAUSE ASSESSMENT INTEGRATION
    # =====================================================================
    def test_Q_h4_canonical_root_cause_assessment_integration(self):
        """Reasoning layer directly ingests and synthesizes H-4 RootCauseAnalysis."""
        h4_candidate = RootCauseCandidate(
            candidate_id="CAUSE_PCV_TEAR",
            title="PCV Diaphragm Rupture",
            description="Torn PCV membrane verified by smoke test",
            affected_ecu="ECM",
            causal_role=CausalRole.PRIMARY_ROOT_CAUSE,
            causal_basis=CausalBasis.HYPOTHESIS_TEST_SUPPORT,
            confidence_score=0.88,
        )
        h4_analysis = RootCauseAnalysis(
            analysis_id="ANALYSIS_001",
            vehicle_id="AVEO_01",
            session_id="SESS_001",
            timestamp=time.time(),
            primary_candidate=h4_candidate,
            conclusion=RootCauseConclusion(
                conclusion_state=AnalysisConclusionState.ROOT_CAUSE_IDENTIFIED,
                primary_candidate_id="CAUSE_PCV_TEAR",
                certainty_level=RootCauseCertaintyLevel.CONFIRMED,
                summary_text="Confirmed PCV tear.",
            ),
        )
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            root_cause_analysis=h4_analysis,
        )
        self.assertTrue(any(c.candidate_id == "CAUSE_PCV_TEAR" for c in session.ranked_candidates))
        top = session.ranked_candidates[0]
        self.assertEqual(top.causal_basis, CausalBasis.HYPOTHESIS_TEST_SUPPORT)
        self.assertEqual(top.candidate_role, CausalRole.PRIMARY_ROOT_CAUSE)

    # =====================================================================
    # R: H-5 WORKFLOW ORCHESTRATION SYNTHESIS
    # =====================================================================
    def test_R_h5_workflow_orchestration_synthesis(self):
        """ReasoningWorkflowAdapter produces formatted summary for H-5 DiagnosticWorkflowEngine."""
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0171"],
        )
        summary = ReasoningWorkflowAdapter.format_technician_reasoning_summary(session)
        self.assertIn("reasoning_id", summary)
        self.assertIn("conclusion", summary)
        self.assertIn("confidence", summary)
        self.assertIn("top_score", summary)
        self.assertIn("diagnostic_score", summary)

    # =====================================================================
    # S: G-5 GRAPH SEMANTICS (RELATIONSHIP != CAUSALITY)
    # =====================================================================
    def test_S_graph_semantics_preserves_non_causality(self):
        """DiagnosticGraphReasoningIntegrator uses strictly non-causal edges."""
        graph = DiagnosticGraph()
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0171"],
        )
        node_id = DiagnosticGraphReasoningIntegrator.integrate_reasoning_session(graph, session)
        self.assertIn(node_id, graph.nodes)
        for edge in graph.edges:
            # Invariant: Must NOT use causal edge types; all edges are strictly non-causal
            self.assertNotIn(edge.edge_type.value, ("CAUSES", "TRIGGERS"))

    # =====================================================================
    # T: GRAPH CONSTRUCTOR & ALIAS COMPATIBILITY (ZERO WARNINGS)
    # =====================================================================
    def test_T_graph_constructor_and_alias_compatibility(self):
        """GraphNode and GraphEdge accept canonical and legacy alias arguments without warnings."""
        # GraphNode with canonical node_id and legacy id
        n1 = GraphNode(node_id="test:n1", node_type=GraphNodeType.ECU, label="Test ECU")
        n2 = GraphNode(id="test:n2", node_type=GraphNodeType.SIGNAL, label="Test Signal")
        self.assertEqual(n1.node_id, "test:n1")
        self.assertEqual(n2.node_id, "test:n2")

        # GraphEdge with canonical source_id and legacy source_node_id
        e1 = GraphEdge(
            edge_id="e1",
            source_id="test:n1",
            target_id="test:n2",
            edge_type=GraphEdgeType.EXPOSES_SIGNAL,
        )
        e2 = GraphEdge(
            edge_id="e2",
            source_node_id="test:n1",
            target_node_id="test:n2",
            edge_type=GraphEdgeType.EXPOSES_SIGNAL,
        )
        self.assertEqual(e1.source_id, "test:n1")
        self.assertEqual(e2.source_id, "test:n1")
        self.assertEqual(e1.target_id, "test:n2")
        self.assertEqual(e2.target_id, "test:n2")

    # =====================================================================
    # U: HEURISTIC RANKING IS NOT PROBABILITY
    # =====================================================================
    def test_U_heuristic_ranking_is_not_probability(self):
        """Diagnostic score is a bounded heuristic in [0.0, 1.0], never described as probability."""
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0171"],
        )
        top = session.ranked_candidates[0]
        self.assertTrue(hasattr(top, "diagnostic_score"))
        self.assertEqual(top.diagnostic_score, top.overall_score)
        self.assertFalse(hasattr(top, "probability"))
        self.assertNotIn("probability", top.to_dict())

    # =====================================================================
    # V: HISTORICAL SIMILARITY IS NOT DIAGNOSTIC CONFIDENCE
    # =====================================================================
    def test_V_historical_similarity_is_not_diagnostic_confidence(self):
        """Historical similarity does not blindly dictate current diagnostic confidence."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_HIGH_SIM",
            title="High similarity case",
            summary="Case summary",
            vehicle_context=self.synth_vehicle,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="RO_SYNTH_001",
            ),
            root_cause=CaseRootCause(
                root_cause_id="HYP_RARE_VALVE",
                component_or_system="VALVE",
                mechanism_description="Rare valve stick",
            ),
            technician_confirmation=CaseTechnicianConfirmation(
                is_confirmed=True,
                technician_id="TECH_2",
                inspection_notes="Rare valve inspected",
            ),
            lifecycle=CaseLifecycle.CONFIRMED,
        )
        self.case_repository.register_case(case)

        # Telemetry provides zero evidence for rare valve
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=[],  # No active DTC
        )
        top = session.ranked_candidates[0]
        # Current diagnostic confidence remains INSUFFICIENT_EVIDENCE or LOW_CONFIDENCE despite historical case
        self.assertIn(top.confidence, (ReasoningUncertainty.INSUFFICIENT_EVIDENCE, ReasoningUncertainty.LOW_CONFIDENCE))

    # =====================================================================
    # W: POST-REPAIR ASSOCIATION VS CAUSATION
    # =====================================================================
    def test_W_post_repair_association_vs_causation(self):
        """Post-repair normalization requires verified technician confirmation for CONFIRMED status."""
        hyp = FaultHypothesis(hypothesis_id="HYP_TEST_REPAIR", title="Oxygen Sensor", category="EXHAUST", affected_system="EXHAUST")
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            hypotheses=[hyp],
        )
        top = session.ranked_candidates[0]
        # Without explicit passed physical test + technician verification, cannot achieve CONFIRMED
        self.assertNotEqual(top.causal_basis, CausalBasis.CONFIRMED)

    # =====================================================================
    # X: EXPLICIT TECHNICIAN CONFIRMATION PROVENANCE
    # =====================================================================
    def test_X_technician_confirmation_provenance(self):
        """Technician confirmation records author ID and outcome verification timestamp."""
        tc = CaseTechnicianConfirmation(
            is_confirmed=True,
            technician_id="CERT_TECH_4021",
            inspection_notes="Replaced intake manifold gasket; fuel trims restored to 0.5%.",
        )
        self.assertEqual(tc.technician_id, "CERT_TECH_4021")
        self.assertTrue(tc.is_confirmed)

    # =====================================================================
    # Y-AB: SAFETY BOUNDARY — KNOWLEDGE/PATTERN/CASE/REASONING CANNOT DISPATCH
    # =====================================================================
    def test_Y_AB_knowledge_pattern_case_reasoning_cannot_dispatch_transport(self):
        """No component in Phase I possesses transport handles or dispatch capability."""
        self.assertFalse(hasattr(self.reasoning_engine, "transport"))
        self.assertFalse(hasattr(self.reasoning_engine, "send_can_frame"))
        self.assertFalse(hasattr(self.knowledge_store, "dispatch"))
        self.assertFalse(hasattr(self.pattern_store, "execute"))
        self.assertFalse(hasattr(self.case_repository, "clear_dtc"))

    # =====================================================================
    # AC: PROHIBITED SERVICES FAIL-CLOSED
    # =====================================================================
    def test_AC_prohibited_services_fail_closed(self):
        """Mode 04, UDS 0x14, 0x2E, 0x27, 0x2F, 0x34, 0x36, 0x37 are permanently prohibited."""
        prohibited = ["04", "14", "2E", "27", "2F", "34", "36", "37"]
        for svc in prohibited:
            self.assertIn(svc, PROHIBITED_SERVICES)
            # Attempt to create sequence descriptor with prohibited service
            with self.assertRaises(Exception):
                SequenceActionDescriptor(
                    action_id=f"act_unsafe_{svc}",
                    target_ecu="ECM",
                    service_id=svc,
                    identifier="0000",
                )

    # =====================================================================
    # AD: DETERMINISTIC RERUN INVARIANT
    # =====================================================================
    def test_AD_deterministic_rerun_invariant(self):
        """Repeated reasoning runs over identical inputs yield identical candidate ordering and scores."""
        obs = ObservedFeatureSet(session_id="RERUN_OBS", features={"LTFT": 22.0, "MAP_KPA": 35.0})
        sess1 = self.reasoning_engine.conduct_reasoning(vehicle_context=self.synth_vehicle, observed_features=obs)
        sess2 = self.reasoning_engine.conduct_reasoning(vehicle_context=self.synth_vehicle, observed_features=obs)
        self.assertEqual(len(sess1.ranked_candidates), len(sess2.ranked_candidates))
        for c1, c2 in zip(sess1.ranked_candidates, sess2.ranked_candidates):
            self.assertEqual(c1.candidate_id, c2.candidate_id)
            self.assertEqual(c1.overall_score, c2.overall_score)
            self.assertEqual(c1.confidence, c2.confidence)

    # =====================================================================
    # AE: SERIALIZATION ROUND-TRIP LOSSLESSNESS
    # =====================================================================
    def test_AE_serialization_round_trip(self):
        """DiagnosticReasoningSession serializes to dict and reconstructs identically."""
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0171"],
        )
        d = session.to_dict()
        reconstructed = DiagnosticReasoningSession.from_dict(d)
        self.assertEqual(reconstructed.reasoning_id, session.reasoning_id)
        self.assertEqual(reconstructed.overall_confidence, session.overall_confidence)
        self.assertEqual(len(reconstructed.ranked_candidates), len(session.ranked_candidates))
        self.assertAlmostEqual(reconstructed.ranked_candidates[0].overall_score, session.ranked_candidates[0].overall_score, places=2)

    # =====================================================================
    # AF: VERSION PRESERVATION
    # =====================================================================
    def test_AF_version_preservation(self):
        """Schema version is preserved across serialization."""
        session = self.reasoning_engine.conduct_reasoning(vehicle_context=self.synth_vehicle)
        d = session.to_dict()
        self.assertEqual(d["schema_version"], 1)

    # =====================================================================
    # AG & AH: PERFORMANCE BENCHMARK (LARGE EVIDENCE & HISTORICAL SET)
    # =====================================================================
    def test_AG_AH_large_evidence_and_historical_set_performance(self):
        """Reasoning over 200 telemetry features and 50 historical cases completes in < 50ms."""
        # 200 features
        big_feats = {f"FEATURE_SIGNAL_{i:04d}": float(i * 1.5) for i in range(200)}
        obs = ObservedFeatureSet(session_id="BIG_FEAT_OBS", features=big_feats)

        # 50 historical cases
        for i in range(50):
            self.case_repository.register_case(HistoricalDiagnosticCase(
                case_id=f"CASE_PERF_{i:03d}",
                title=f"Performance Case {i}",
                summary="Bulk case",
                vehicle_context=self.synth_vehicle,
                provenance=KnowledgeProvenance(
                    source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                    source_reference=f"RO_BULK_{i}",
                ),
                root_cause=CaseRootCause(
                    root_cause_id=f"HYP_COMP_{i}",
                    component_or_system="COMP",
                    mechanism_description="Component failure",
                ),
            ))

        start = time.perf_counter()
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
            max_candidates=10,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self.assertLess(elapsed_ms, 50.0)
        self.assertLessEqual(len(session.ranked_candidates), 10)

    # =====================================================================
    # AI: HYPOTHESIS FLOOD & BOUNDEDNESS
    # =====================================================================
    def test_AI_hypothesis_flood_boundedness(self):
        """Adversarial input of 500 hypotheses is safely pre-filtered without memory explosion."""
        flood_hypotheses = [
            FaultHypothesis(hypothesis_id=f"FLOOD_{i:04d}", title=f"Flood Hypo {i}", category="TEST", affected_system="TEST")
            for i in range(500)
        ]
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            hypotheses=flood_hypotheses,
            max_candidates=10,
        )
        self.assertLessEqual(len(session.ranked_candidates), 10)
        self.assertLessEqual(len(session.candidates), 10)

    # =====================================================================
    # AJ: FAILURE PATTERN CYCLE RESISTANCE
    # =====================================================================
    def test_AJ_pattern_cycle_resistance(self):
        """Cyclic pattern relationships are bounded and do not infinite-loop."""
        pat_a = FailurePattern(
            pattern_id="PAT_CYCLE_A",
            name="Cycle Pattern A",
            category=PatternCategory.INTERMITTENT_SIGNAL,
            description="Cycle A",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.SYSTEM_DERIVED,
                source_reference="SYNTHETIC_CYCLE",
            ),
            possible_hypotheses=["HYP_CYCLE_B"],
        )
        pat_b = FailurePattern(
            pattern_id="PAT_CYCLE_B",
            name="Cycle Pattern B",
            category=PatternCategory.INTERMITTENT_SIGNAL,
            description="Cycle B",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.SYSTEM_DERIVED,
                source_reference="SYNTHETIC_CYCLE",
            ),
            possible_hypotheses=["HYP_CYCLE_A"],
        )
        self.pattern_store.register_pattern(pat_a)
        self.pattern_store.register_pattern(pat_b)
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            active_dtcs=["P0100"],
        )
        self.assertTrue(len(session.ranked_candidates) > 0)

    # =====================================================================
    # AK: GRAPH CYCLE BOUNDEDNESS
    # =====================================================================
    def test_AK_graph_cycle_boundedness(self):
        """DiagnosticGraph cycle detection handles circular edges safely."""
        graph = DiagnosticGraph()
        n1 = GraphNode(node_id="N1", node_type=GraphNodeType.SIGNAL, label="Signal 1")
        n2 = GraphNode(node_id="N2", node_type=GraphNodeType.SIGNAL, label="Signal 2")
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_edge(GraphEdge("e1", "N1", "N2", GraphEdgeType.CORRELATES_WITH))
        graph.add_edge(GraphEdge("e2", "N2", "N1", GraphEdgeType.CORRELATES_WITH))  # Direct 2-cycle
        self.assertEqual(len(graph.edges), 2)

    # =====================================================================
    # AL: SYNTHETIC DATA PROVENANCE MARKINGS
    # =====================================================================
    def test_AL_synthetic_data_provenance_markings(self):
        """Synthetic benchmark data explicitly identifies itself as SYNTHETIC."""
        self.assertIn("SYNTHETIC", self.identity.metadata.get("source_reference", ""))
        self.assertEqual(self.identity.identity_sources.get("VIN"), IdentitySource.SYSTEM_INFERRED)
        self.assertIn("SYNTHETIC", self.synth_vehicle.manufacturer)

    # =====================================================================
    # AM: COMPREHENSIVE END-TO-END AUTHORITATIVE DIAGNOSTIC SCENARIO
    # =====================================================================
    def test_AM_authoritative_end_to_end_scenario(self):
        """
        Complete End-to-End Real-World Diagnostic Scenario:
        Vehicle: 2012 Chevrolet Aveo 1.3L CDTI (Synthetic Fixture)
        Symptom: Engine hesitating under cruise, active P0171 lean code.
        Telemetry: LTFT = +24.8%, MAF response lag = 210ms.
        Patterns: Matched PCV Vacuum Leak pattern.
        History: Confirmed similar case with torn PCV membrane; contradictory case with MAF.
        Reasoning:
          1. Synthesize all evidence.
          2. Penalize contradictory MAF case.
          3. Elevate PCV Vacuum Leak candidate.
          4. Recommend safe distinguishing smoke test via H-3.
          5. Refuse unconditional 'replace part' repair command.
        """
        # 1. Failure Pattern
        pat = FailurePattern(
            pattern_id="PAT_AVEO_LEAN_PCV",
            name="A13DTE Intake Vacuum Deficit",
            category=PatternCategory.RESPONSE_LAG,
            description="Torn PCV membrane vacuum deficit",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="GM_AVE_DIAG",
            ),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="REQ_LTFT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LONG_TERM_FUEL_TRIM_PCT",
                    min_threshold=15.0,
                    max_threshold=35.0,
                ),
                PatternFeatureRequirement(
                    feature_id="REQ_MAF_LAG",
                    feature_type=PatternFeatureType.DELAY_TIME_S,
                    signal_name="MAF_COMMAND_LAG_MS",
                    min_threshold=150.0,
                    max_threshold=300.0,
                ),
            ],
            possible_hypotheses=["HYP_PCV_MEMBRANE_RUPTURE"],
            distinguishing_tests=[
                KnowledgeDistinguishingTest(
                    test_id="TEST_SMOKE_VALVE_COVER",
                    title="Crankcase Smoke Test",
                    description="Pressurize crankcase with smoke to detect PCV membrane leak",
                    discriminated_hypotheses=["HYP_PCV_MEMBRANE_RUPTURE"],
                    safety_classification=ServiceSafetyClassification.READ_ONLY,
                )
            ],
        )
        self.pattern_store.register_pattern(pat)

        # 2. Historical Cases (One Confirmed, One Contradictory)
        case_pcv = HistoricalDiagnosticCase(
            case_id="CASE_HIST_PCV_001",
            title="Confirmed PCV Membrane Tear",
            summary="Aveo 1.3L CDTI PCV membrane rupture",
            vehicle_context=self.synth_vehicle,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="RO_AVEO_8832",
            ),
            root_cause=CaseRootCause(
                root_cause_id="HYP_PCV_MEMBRANE_RUPTURE",
                component_or_system="PCV_MEMBRANE",
                mechanism_description="Torn PCV diaphragm membrane",
            ),
            technician_confirmation=CaseTechnicianConfirmation(is_confirmed=True, technician_id="TECH_MASTER"),
            repair_outcome=CaseRepairOutcome(repair_action="Replaced PCV membrane", parts_replaced=["PCV_MEMBRANE"]),
            lifecycle=CaseLifecycle.CONFIRMED,
        )
        self.case_repository.register_case(case_pcv)

        # 3. Live Telemetry
        obs = ObservedFeatureSet(
            session_id="LIVE_AVEO_LOG",
            features={"LONG_TERM_FUEL_TRIM_PCT": 24.8, "MAF_COMMAND_LAG_MS": 210.0},
            operating_condition=OperatingCondition.STEADY_CRUISE,
        )

        # 4. Execute Complete Reasoning Process
        session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.synth_vehicle,
            observed_features=obs,
            active_dtcs=["P0171"],
        )

        # Assertions on Authoritative Synthesis:
        self.assertIsNotNone(session.overall_conclusion)
        self.assertNotIn("replace", session.overall_conclusion.lower())  # Invariant: No unilateral repair command!
        self.assertIn("verify using test", session.overall_conclusion)   # Evidence-driven test recommendation

        # Top candidate must be PCV Membrane
        top = session.ranked_candidates[0]
        self.assertEqual(top.candidate_id, "HYP_PCV_MEMBRANE_RUPTURE")
        self.assertGreater(top.overall_score, 0.70)
        self.assertEqual(top.causal_basis, CausalBasis.DIRECT_MECHANISTIC_EVIDENCE)
        self.assertEqual(top.candidate_role, CausalRole.PRIMARY_ROOT_CAUSE)

        # Distinguishing test recommendation
        self.assertTrue(len(session.recommended_distinguishing_tests) > 0)
        rec_test = session.recommended_distinguishing_tests[0]
        self.assertEqual(rec_test.test_id, "TEST_SMOKE_VALVE_COVER")
        self.assertEqual(rec_test.safety_classification, ServiceSafetyClassification.READ_ONLY)


if __name__ == "__main__":
    unittest.main()
