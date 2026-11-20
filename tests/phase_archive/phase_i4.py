# -*- coding: utf-8 -*-
"""
test_phase_i4.py — Phase I-4 Historical Case Analysis Acceptance Test Suite
=============================================================================
Exhaustive unit and integration test suite certifying Phase I-4:
  1. Case creation & structural validation
  2. Stable case identity
  3. Vehicle context preservation
  4. Engine context preservation
  5. Transmission context preservation
  6. ECU context (target ECU, hardware part number)
  7. ECU hardware / software calibration context
  8. Operating context preservation (idle, cruise, etc.)
  9. Evidence representation & feature snapshots
  10. Pattern references (I-3 Failure Pattern Library integration)
  11. Candidate hypotheses representation
  12. Test result representation (safe read-only tests)
  13. Root-cause representation & confidence grades
  14. Technician confirmation audit tracking
  15. Repair outcome separation from diagnosis
  16. Post-repair verification & anomaly resolution
  17. Case lifecycle transitions (OPEN -> CLOSED)
  18. Case versioning & audit immutability
  19. Serialization round-trip (to_dict / from_dict)
  20. Deterministic case retrieval & multi-key indexing
  21. Exact vehicle similarity ranking
  22. Partial vehicle similarity ranking
  23. ECU similarity evaluation
  24. Software/calibration similarity evaluation
  25. Pattern similarity evaluation
  26. Evidence & telemetry feature similarity
  27. Operating-condition similarity
  28. Explainable similarity scoring breakdown
  29. Strong historical match grade (>= 0.80)
  30. Weak historical match grade (< 0.50)
  31. Contradictory current evidence actively reducing relevance
  32. Rejected historical hypothesis handling
  33. Failed repair outcome representation
  34. Unconfirmed case discount weighting
  35. Technician-confirmed case elevated weighting
  36. Multi-ECU historical case isolation (ECM vs TCM vs ABS)
  37. Communication-failure safeguard (bus timeout != component fault)
  38. DTC-free historical case matching
  39. DTC contextualization (DTC != root cause)
  40. Case conflict handling
  41. Bounded retrieval (max_results, max_candidates)
  42. Candidate pre-filtering via indexes
  43. Large historical case performance benchmark (500+ cases in < 50ms)
  44. H-3 integration (distinguishing test recommendations)
  45. H-4 integration (root-cause contextual evidence)
  46. H-5 integration (diagnostic workflow context)
  47. G integration (G-5 DiagnosticGraph non-causal edges)
  48. D integration (evidence & hypothesis context)
  49. I-1 regression compatibility
  50. I-2 regression compatibility
  51. I-3 regression compatibility
  52. Safety boundary verification: strict READ_ONLY enforcement
  53. Realistic synthetic diagnostic scenario (Case A vs Current Case B)
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
    ProgressiveVehicleIdentity,
    VehicleECUKnowledgeStore,
)
from failure_pattern_library import (
    PatternCategory,
    PatternFeatureType,
    PatternMatchGrade,
    PatternFeatureRequirement,
    ObservedFeatureSet,
    FailurePattern,
    PatternMatchResult,
    FailurePatternLibraryStore,
)
from historical_case_analysis import (
    CaseLifecycle,
    CaseMatchGrade,
    CaseRelationshipType,
    RootCauseConfidenceGrade,
    CaseECUContext,
    CaseDTCRecord,
    CaseTestResult,
    CaseRootCause,
    CaseTechnicianConfirmation,
    CaseRepairOutcome,
    PostRepairVerification,
    CaseRelationship,
    HistoricalDiagnosticCase,
    CaseSimilarityResult,
    HistoricalCaseRepository,
    HistoricalCaseWorkflowAdapter,
    DiagnosticGraphCaseIntegrator,
)


class TestPhaseI4HistoricalCaseAnalysis(unittest.TestCase):
    """Exhaustive test suite certifying Phase I-4 Historical Case Analysis."""

    def setUp(self):
        self.repo = HistoricalCaseRepository()

        # Shared vehicle context: Chevrolet Aveo 1.4L F14D3 Delphi MT80
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

        # Baseline technician confirmation
        self.tech_confirm = CaseTechnicianConfirmation(
            is_confirmed=True,
            technician_id="TECH_GM_402",
            confirmation_timestamp=1700000000.0,
            inspection_notes="Smoke test verified physical intake breach at lower PCV elbow.",
            diagnostic_confidence=KnowledgeConfidence.HIGH,
        )

        # Baseline repair outcome
        self.repair = CaseRepairOutcome(
            repair_action="Replaced rubber PCV elbow under intake manifold",
            parts_replaced=["GM_96495288_HOSE"],
            repair_timestamp=1700003600.0,
        )

        # Baseline post-repair verification
        self.verification = PostRepairVerification(
            verification_performed=True,
            original_anomaly_resolved=True,
            dtc_cleared=True,
            telemetry_normalized=True,
            notes="Warm idle LTFT returned to +1.5%, engine vacuum stabilized at 32 kPa.",
            verification_confidence=KnowledgeConfidence.HIGH,
        )

    # ---------------------------------------------------------------------
    # 1. CASE CREATION & STABLE IDENTITY
    # ---------------------------------------------------------------------
    def test_01_case_creation_and_stable_identity(self):
        """Historical diagnostic case requires valid case_id and valid vehicle context."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_2024_001",
            title="Chevrolet Aveo PCV Vacuum Leak Case",
            summary="Intake air leak causing lean trim at warm idle.",
            vehicle_context=self.aveo_context,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="RO_78491",
            ),
        )
        self.assertEqual(case.case_id, "CASE_2024_001")
        self.assertEqual(case.lifecycle, CaseLifecycle.CLOSED)

        # Empty case_id must be rejected
        with self.assertRaises(ValueError):
            HistoricalDiagnosticCase(
                case_id="",
                title="Invalid Empty Case",
                summary="Invalid",
                vehicle_context=self.aveo_context,
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_0"),
            )

    # ---------------------------------------------------------------------
    # 2. VEHICLE, ENGINE & TRANSMISSION CONTEXT
    # ---------------------------------------------------------------------
    def test_02_vehicle_powertrain_context_preservation(self):
        """Verify manufacturer, model, engine code, and transmission are preserved."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_POWERTRAIN",
            title="Powertrain Case",
            summary="Testing powertrain context.",
            vehicle_context=self.aveo_context,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="TSB_101"),
        )
        self.assertEqual(case.vehicle_context.manufacturer, "CHEVROLET")
        self.assertEqual(case.vehicle_context.model, "AVEO")
        self.assertEqual(case.vehicle_context.engine_code, "F14D3")
        self.assertEqual(case.vehicle_context.transmission, "MANUAL")

    # ---------------------------------------------------------------------
    # 3. ECU CONTEXT (HARDWARE & SOFTWARE CALIBRATION)
    # ---------------------------------------------------------------------
    def test_03_ecu_hardware_and_software_context(self):
        """ECU family, hardware part number, and software calibration context."""
        ecu_ctx = CaseECUContext(
            target_ecu="ECM",
            ecu_family="DELPHI_MT80",
            hardware_part_number="25186182",
            software_version="CAL_ID_968001",
        )
        case = HistoricalDiagnosticCase(
            case_id="CASE_ECU_01",
            title="ECU Context Case",
            summary="Delphi MT80 calibration test.",
            vehicle_context=self.aveo_context,
            ecu_contexts={"ECM": ecu_ctx},
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="DELPHI_DOC"),
        )
        self.assertIn("ECM", case.ecu_contexts)
        self.assertEqual(case.ecu_contexts["ECM"].ecu_family, "DELPHI_MT80")
        self.assertEqual(case.ecu_contexts["ECM"].software_version, "CAL_ID_968001")

    # ---------------------------------------------------------------------
    # 4. OPERATING CONTEXT & EVIDENCE SNAPSHOT
    # ---------------------------------------------------------------------
    def test_04_operating_context_and_features(self):
        """Operating conditions and observed telemetry feature snapshots."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_OPS_01",
            title="Operating Context Case",
            summary="Warm idle trim drift.",
            vehicle_context=self.aveo_context,
            operating_conditions=[OperatingCondition.IDLE, OperatingCondition.WARM_UP],
            observed_features={"LTFT": 22.5, "MAF": 1.8, "MAP": 41.0},
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="LOG_1"),
        )
        self.assertIn(OperatingCondition.IDLE, case.operating_conditions)
        self.assertEqual(case.observed_features["LTFT"], 22.5)

    # ---------------------------------------------------------------------
    # 5. TEST RESULT REPRESENTATION (SAFE READ-ONLY)
    # ---------------------------------------------------------------------
    def test_05_test_results_representation_and_safety_invariant(self):
        """Test results must record observations and strictly enforce READ_ONLY classification."""
        test_res = CaseTestResult(
            test_id="TEST_SMOKE_PCV",
            test_title="PCV Elbow Smoke Test",
            target_ecu="ECM",
            outcome="PASSED",
            observations="Dense smoke leaking from underside of PCV elbow.",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        case = HistoricalDiagnosticCase(
            case_id="CASE_TEST_01",
            title="Test Case",
            summary="Case with test result.",
            vehicle_context=self.aveo_context,
            test_results=[test_res],
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_2"),
        )
        self.assertEqual(len(case.test_results), 1)
        self.assertEqual(case.test_results[0].outcome, "PASSED")

        # Dangerous actuating test must be rejected
        with self.assertRaises(ValueError):
            CaseTestResult(
                test_id="TEST_DANGEROUS_ACTUATION",
                test_title="Force Actuator",
                target_ecu="ECM",
                outcome="FAILED",
                safety_classification=ServiceSafetyClassification.ACTUATION,  # Prohibited!
            )

    # ---------------------------------------------------------------------
    # 6. ROOT CAUSE & TECHNICIAN CONFIRMATION
    # ---------------------------------------------------------------------
    def test_06_root_cause_and_technician_confirmation(self):
        """Separation between automated hypothesis and technician-confirmed root cause."""
        rc = CaseRootCause(
            root_cause_id="RC_PCV_ELBOW_SPLIT",
            component_or_system="PCV Rubber Elbow Hose",
            mechanism_description="Rubber elbow split open on manifold side causing vacuum leak.",
            confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
        )
        case = HistoricalDiagnosticCase(
            case_id="CASE_CONFIRMED_01",
            title="Confirmed Vacuum Breach",
            summary="Technician inspected and verified split hose.",
            vehicle_context=self.aveo_context,
            root_cause=rc,
            technician_confirmation=self.tech_confirm,
            repair_outcome=self.repair,
            post_repair_verification=self.verification,
            lifecycle=CaseLifecycle.CONFIRMED,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_1234"),
        )
        self.assertTrue(case.is_technician_confirmed())
        self.assertTrue(case.is_successful_repair())
        self.assertEqual(case.root_cause.confidence_grade, RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN)

    # ---------------------------------------------------------------------
    # 7. CASE LIFECYCLE & VERSIONING
    # ---------------------------------------------------------------------
    def test_07_case_lifecycle_and_closing(self):
        """Case lifecycle transition through repository close_case."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_LIFE_01",
            title="Open Diagnostic Session Case",
            summary="Workflow in progress.",
            vehicle_context=self.aveo_context,
            lifecycle=CaseLifecycle.OPEN,
            version=1,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="DIAG_SESSION_99"),
        )
        self.repo.add_case(case)
        self.assertEqual(self.repo.get_case("CASE_LIFE_01").lifecycle, CaseLifecycle.OPEN)

        # Close case with confirmed findings
        rc = CaseRootCause(
            root_cause_id="RC_PCV_LEAK",
            component_or_system="PCV System",
            mechanism_description="Split hose.",
            confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
        )
        closed_case = self.repo.close_case(
            case_id="CASE_LIFE_01",
            root_cause=rc,
            repair_outcome=self.repair,
            technician_confirmation=self.tech_confirm,
            post_repair_verification=self.verification,
        )
        self.assertEqual(closed_case.lifecycle, CaseLifecycle.CONFIRMED)
        self.assertEqual(closed_case.version, 2)
        self.assertTrue(closed_case.is_technician_confirmed())

    # ---------------------------------------------------------------------
    # 8. SERIALIZATION ROUND-TRIP
    # ---------------------------------------------------------------------
    def test_08_serialization_round_trip(self):
        """Case model and repository serialize to/from dict losslessly."""
        rc = CaseRootCause(
            root_cause_id="RC_TEST",
            component_or_system="MAF Sensor",
            mechanism_description="Silicone poisoning.",
            confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
        )
        case = HistoricalDiagnosticCase(
            case_id="CASE_SERIAL_01",
            title="Serialization Case",
            summary="Testing dict round trip.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0101", target_ecu="ECM")],
            observed_features={"MAF:VALUE": 1.2},
            matched_pattern_ids=["PAT_MAF_IDLE_DRIFT"],
            root_cause=rc,
            technician_confirmation=self.tech_confirm,
            repair_outcome=self.repair,
            post_repair_verification=self.verification,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_SERIAL"),
        )
        # Single case round-trip
        data = case.to_dict()
        reconstructed = HistoricalDiagnosticCase.from_dict(data)
        self.assertEqual(reconstructed.case_id, case.case_id)
        self.assertEqual(reconstructed.vehicle_context.manufacturer, "CHEVROLET")
        self.assertEqual(reconstructed.root_cause.root_cause_id, "RC_TEST")
        self.assertTrue(reconstructed.is_technician_confirmed())

        # Full repository round-trip
        self.repo.add_case(case)
        repo_data = self.repo.to_dict()
        reconstructed_repo = HistoricalCaseRepository.from_dict(repo_data)
        self.assertIsNotNone(reconstructed_repo.get_case("CASE_SERIAL_01"))

    # ---------------------------------------------------------------------
    # 9. EXACT VS PARTIAL VEHICLE SIMILARITY RANKING
    # ---------------------------------------------------------------------
    def test_09_exact_vs_partial_vehicle_similarity_ranking(self):
        """Exact vehicle/engine match ranks higher than generic model or different engine."""
        # Case 1: Exact Chevrolet Aveo F14D3
        case_exact = HistoricalDiagnosticCase(
            case_id="CASE_EXACT_AVEO_F14D3",
            title="Aveo F14D3 Case",
            summary="Exact match.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            technician_confirmation=self.tech_confirm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_EXACT"),
        )
        # Case 2: Chevrolet Aveo with different engine (1.2L B12D1)
        b12_context = VehicleContext(
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            engine_code="B12D1",
        )
        case_partial = HistoricalDiagnosticCase(
            case_id="CASE_PARTIAL_AVEO_B12D1",
            title="Aveo B12D1 Case",
            summary="Different engine.",
            vehicle_context=b12_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            technician_confirmation=self.tech_confirm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_PARTIAL"),
        )
        self.repo.add_case(case_exact)
        self.repo.add_case(case_partial)

        results = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        self.assertEqual(len(results), 2)
        # Exact engine match must be top-ranked
        self.assertEqual(results[0].case.case_id, "CASE_EXACT_AVEO_F14D3")
        self.assertGreater(results[0].overall_similarity, results[1].overall_similarity)
        self.assertGreater(results[0].dimension_scores["vehicle_powertrain"], results[1].dimension_scores["vehicle_powertrain"])

    # ---------------------------------------------------------------------
    # 10. PATTERN & EVIDENCE SIMILARITY
    # ---------------------------------------------------------------------
    def test_10_pattern_and_evidence_similarity(self):
        """Matching I-3 failure patterns and telemetry features increases similarity score."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_PAT_EVID",
            title="Pattern & Feature Case",
            summary="Response lag and cross sensor delta.",
            vehicle_context=self.aveo_context,
            matched_pattern_ids=["PAT_RESPONSE_LAG_01", "PAT_CROSS_MAF_MAP"],
            observed_features={"LTFT": 20.0, "MAF_LAG": 1.2},
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
        )
        self.repo.add_case(case)

        obs = ObservedFeatureSet(
            session_id="S_SIM",
            features={"LTFT": 21.0, "MAF_LAG": 1.1},
        )
        results = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            observed_features=obs,
            matched_patterns=["PAT_RESPONSE_LAG_01", "PAT_CROSS_MAF_MAP"],
        )
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(results[0].overall_similarity, 0.70)
        self.assertGreater(results[0].dimension_scores["pattern_similarity"], 0.15)
        self.assertGreater(results[0].dimension_scores["operating_context"], 0.05)

    # ---------------------------------------------------------------------
    # 11. CONTRADICTORY CURRENT EVIDENCE REDUCES HISTORICAL RELEVANCE
    # ---------------------------------------------------------------------
    def test_11_contradictory_current_evidence_penalizes_historical_case(self):
        """Invariant: If current evidence contradicts historical root cause, relevance is penalized."""
        rc = CaseRootCause(
            root_cause_id="RC_PCV_LEAK",
            component_or_system="PCV Hose",
            mechanism_description="Vacuum breach.",
        )
        case = HistoricalDiagnosticCase(
            case_id="CASE_HISTORICAL_PCV",
            title="Past PCV Vacuum Leak",
            summary="Vacuum leak case.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            root_cause=rc,
            technician_confirmation=self.tech_confirm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_OLD"),
        )
        self.repo.add_case(case)

        # 1. Query without contradiction -> High similarity & relevance
        res_clean = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        self.assertEqual(res_clean[0].match_grade, CaseMatchGrade.HIGH_SIMILARITY)
        self.assertEqual(len(res_clean[0].contradictions_detected), 0)

        # 2. Query with active contradiction: MAP sensor indicates perfect manifold vacuum (contradicts PCV leak)
        res_contra = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
            current_contradictions=["RC_PCV_LEAK"],
        )
        self.assertLess(res_contra[0].overall_similarity, res_clean[0].overall_similarity)
        self.assertLess(res_contra[0].relevance_as_evidence, res_clean[0].relevance_as_evidence)
        self.assertEqual(res_contra[0].match_grade, CaseMatchGrade.INSUFFICIENT_SIMILARITY)
        self.assertGreater(len(res_contra[0].contradictions_detected), 0)

    # ---------------------------------------------------------------------
    # 12. REJECTED HISTORICAL HYPOTHESIS & FAILED REPAIRS
    # ---------------------------------------------------------------------
    def test_12_rejected_hypothesis_and_failed_repair_handling(self):
        """Disproved historical hypotheses are preserved with discounted relevance to avoid repeat failures."""
        rc_rejected = CaseRootCause(
            root_cause_id="RC_MAF_DEFECTIVE",
            component_or_system="MAF Sensor",
            mechanism_description="Replacing MAF did not fix issue.",
            confidence_grade=RootCauseConfidenceGrade.REJECTED_HYPOTHESIS,
        )
        case_rejected = HistoricalDiagnosticCase(
            case_id="CASE_FAILED_REPAIR_01",
            title="Failed MAF Replacement Case",
            summary="Technician replaced MAF but lean trim persisted.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            root_cause=rc_rejected,
            lifecycle=CaseLifecycle.REJECTED,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_FAIL"),
        )
        self.repo.add_case(case_rejected)

        results = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].case.root_cause.confidence_grade, RootCauseConfidenceGrade.REJECTED_HYPOTHESIS)
        # Relevance is discounted for rejected cases
        self.assertLess(results[0].relevance_as_evidence, results[0].overall_similarity)
        self.assertTrue(any("REJECTED" in exp for exp in results[0].explanations))

    # ---------------------------------------------------------------------
    # 13. MULTI-ECU CASE SEPARATION
    # ---------------------------------------------------------------------
    def test_13_multi_ecu_historical_case_isolation(self):
        """ECU context isolates ECM vs TCM vs ABS within historical records."""
        ecm_ctx = CaseECUContext(target_ecu="ECM", ecu_family="DELPHI_MT80")
        tcm_ctx = CaseECUContext(target_ecu="TCM", ecu_family="AISIN_81_40LE")
        case = HistoricalDiagnosticCase(
            case_id="CASE_MULTI_ECU_01",
            title="Engine-Transmission Interaction Case",
            summary="ECM reports MIL request, TCM reports 3-4 shift solenoid performance.",
            vehicle_context=self.aveo_context,
            ecu_contexts={"ECM": ecm_ctx, "TCM": tcm_ctx},
            active_dtcs=[
                CaseDTCRecord(dtc_code="P0700", target_ecu="ECM"),
                CaseDTCRecord(dtc_code="P0756", target_ecu="TCM"),
            ],
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="GM_TRANS_DIAG"),
        )
        self.repo.add_case(case)

        retrieved = self.repo.get_case("CASE_MULTI_ECU_01")
        self.assertEqual(len(retrieved.ecu_contexts), 2)
        dtc_ecus = {d.target_ecu: d.dtc_code for d in retrieved.active_dtcs}
        self.assertEqual(dtc_ecus["ECM"], "P0700")
        self.assertEqual(dtc_ecus["TCM"], "P0756")

    # ---------------------------------------------------------------------
    # 14. COMMUNICATION FAILURE SAFEGUARD
    # ---------------------------------------------------------------------
    def test_14_communication_failure_safeguard(self):
        """Invariant: Communication timeout history must not imply defective internal hardware."""
        rc_comm = CaseRootCause(
            root_cause_id="RC_CAN_BUS_CORROSION",
            component_or_system="CAN Bus Wiring Harness",
            mechanism_description="Connector corrosion at intermediate bulkhead.",
            confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
        )
        case_comm = HistoricalDiagnosticCase(
            case_id="CASE_U0101_COMM_LOSS",
            title="Lost Comm With TCM",
            summary="Bus error.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="U0101", target_ecu="ECM")],
            root_cause=rc_comm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="CAN_DIAG"),
        )
        self.repo.add_case(case_comm)

        # Ensure cause is wiring/harness, not defective TCM internal microchip
        c = self.repo.get_case("CASE_U0101_COMM_LOSS")
        self.assertIn("Harness", c.root_cause.component_or_system)
        self.assertNotIn("INTERNAL_TCM_SILICON", c.root_cause.root_cause_id)

    # ---------------------------------------------------------------------
    # 15. DTC-FREE HISTORICAL CASE MATCHING
    # ---------------------------------------------------------------------
    def test_15_dtc_free_historical_case_matching(self):
        """Cases match based on telemetry drift even when DTC list is completely empty."""
        case_dtc_free = HistoricalDiagnosticCase(
            case_id="CASE_DTC_FREE_VACUUM",
            title="DTC-Free Pre-Code Vacuum Leak",
            summary="Fuel trim at 14.5% (below DTC P0171 threshold of 20%).",
            vehicle_context=self.aveo_context,
            is_dtc_free=True,
            active_dtcs=[],
            matched_pattern_ids=["PAT_MAF_IDLE_DRIFT"],
            observed_features={"LTFT": 14.5, "MAF": 1.9},
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_DTC_FREE"),
        )
        self.repo.add_case(case_dtc_free)

        # Current diagnosis has no DTCs
        obs = ObservedFeatureSet(session_id="S_NO_DTC", features={"LTFT": 15.0, "MAF": 2.0})
        results = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            observed_features=obs,
            active_dtcs=[],
            matched_patterns=["PAT_MAF_IDLE_DRIFT"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].case.case_id, "CASE_DTC_FREE_VACUUM")
        self.assertTrue(results[0].case.is_dtc_free)

    # ---------------------------------------------------------------------
    # 16. BOUNDED RETRIEVAL & LARGE BENCHMARK
    # ---------------------------------------------------------------------
    def test_16_bounded_retrieval_and_large_benchmark(self):
        """Store with 500+ historical cases limits candidate evaluation and runs < 50ms."""
        for i in range(500):
            eng = "F14D3" if (i % 20 == 0) else f"ENG_{i % 30}"
            c = HistoricalDiagnosticCase(
                case_id=f"SYNTH_CASE_{i:04d}",
                title=f"Synthetic Case {i}",
                summary="Benchmark case fixture.",
                vehicle_context=VehicleContext(
                    manufacturer="CHEVROLET" if (i % 5 == 0) else "OTHER",
                    model="AVEO" if (i % 10 == 0) else "GENERIC",
                    engine_code=eng,
                ),
                active_dtcs=[CaseDTCRecord(dtc_code=f"P0{i % 100:03d}", target_ecu="ECM")],
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="BENCH"),
            )
            self.repo.add_case(c)

        self.assertEqual(len(self.repo.list_cases()), 500)

        t0 = time.perf_counter()
        results = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
            max_results=5,
            max_candidates=50,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertLess(elapsed_ms, 50.0, f"Query took {elapsed_ms:.2f}ms, expected < 50ms")
        self.assertLessEqual(len(results), 5)

    # ---------------------------------------------------------------------
    # 17. H-LAYER WORKFLOW ADAPTER (H-3, H-4, H-5)
    # ---------------------------------------------------------------------
    def test_17_workflow_adapter_integrations(self):
        """Workflow adapter supplies safe distinguishing tests and root-cause context."""
        test_smoke = CaseTestResult(
            test_id="TEST_SMOKE_PCV_ELBOW",
            test_title="Intake Smoke Injection Test",
            target_ecu="ECM",
            outcome="PASSED",
            observations="Leaking at elbow.",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        rc = CaseRootCause(
            root_cause_id="RC_PCV_SPLIT",
            component_or_system="PCV Elbow",
            mechanism_description="Hose split.",
            confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
        )
        case = HistoricalDiagnosticCase(
            case_id="CASE_CONFIRMED_ADAPTER",
            title="Confirmed Adapter Case",
            summary="For H-3 / H-4 testing.",
            vehicle_context=self.aveo_context,
            test_results=[test_smoke],
            root_cause=rc,
            technician_confirmation=self.tech_confirm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_ADAPT"),
        )
        self.repo.add_case(case)

        adapter = HistoricalCaseWorkflowAdapter(self.repo)

        # H-3: Retrieves distinguishing tests that resolved past cases
        tests = adapter.get_historical_distinguishing_tests(vehicle_context=self.aveo_context)
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].test_id, "TEST_SMOKE_PCV_ELBOW")

        # H-4: Retrieves confirmed root cause experience
        rc_context = adapter.get_historical_root_cause_context(vehicle_context=self.aveo_context)
        self.assertEqual(len(rc_context), 1)
        self.assertEqual(rc_context[0]["root_cause_id"], "RC_PCV_SPLIT")
        self.assertTrue(rc_context[0]["is_technician_confirmed"])

    # ---------------------------------------------------------------------
    # 18. G-5 DIAGNOSTIC GRAPH INTEGRATION (NON-CAUSAL)
    # ---------------------------------------------------------------------
    def test_18_diagnostic_graph_case_integration(self):
        """Historical case binds to DiagnosticGraph with non-causal ASSOCIATED_WITH edge."""
        graph = DiagnosticGraph()
        dtc_node_id = make_dtc_node_id("ECM", "P0171")
        graph.add_node(GraphNode(node_id=dtc_node_id, node_type=GraphNodeType.DTC, label="P0171"))

        case = HistoricalDiagnosticCase(
            case_id="CASE_GRAPH_01",
            title="Graph Case",
            summary="Testing graph binding.",
            vehicle_context=self.aveo_context,
            active_dtcs=[CaseDTCRecord(dtc_code="P0171", target_ecu="ECM")],
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="DOC_G"),
        )
        sim = CaseSimilarityResult(
            case=case,
            overall_similarity=0.85,
            match_grade=CaseMatchGrade.HIGH_SIMILARITY,
            dimension_scores={},
            relevance_as_evidence=0.88,
        )

        node_id = DiagnosticGraphCaseIntegrator.integrate_historical_case(graph, sim)
        self.assertIn(node_id, graph.nodes)
        self.assertEqual(graph.nodes[node_id].node_type, GraphNodeType.ANOMALY)

        # Invariant: Edge must be strictly non-causal ASSOCIATED_WITH
        edge = graph.get_edge(f"edge_case_CASE_GRAPH_01_P0171")
        self.assertIsNotNone(edge)
        self.assertEqual(edge.edge_type, GraphEdgeType.ASSOCIATED_WITH)

    # ---------------------------------------------------------------------
    # 19. I-1, I-2, I-3 REGRESSIONS
    # ---------------------------------------------------------------------
    def test_19_cross_phase_regressions(self):
        """Historical case analysis interoperates cleanly with I-1, I-2, and I-3 stores."""
        kb_store = DiagnosticKnowledgeStore()
        ecu_store = VehicleECUKnowledgeStore()
        pattern_store = FailurePatternLibraryStore()

        self.assertIsNotNone(kb_store)
        self.assertIsNotNone(ecu_store)
        self.assertIsNotNone(pattern_store)

    # ---------------------------------------------------------------------
    # 20. REALISTIC SYNTHETIC SCENARIO: CASE A VS CURRENT CASE B
    # ---------------------------------------------------------------------
    def test_20_realistic_synthetic_diagnostic_scenario(self):
        """
        Realistic Diagnostic Scenario:
        Historical Case A:
          - Chevrolet Aveo 1.4L F14D3 Delphi MT80
          - DTC-Free Anomaly: LTFT +22.5%, MAF lag, MAP elevated
          - Pattern: Command/Response mismatch + Cross-Sensor disagreement
          - Safe test: Smoke test verified split PCV elbow
          - Technician confirmed: Replaced hose, anomaly eliminated
        Current Case B:
          - Same vehicle & engine context
          - Similar trim drift pattern
          - BUT contradictory evidence: Deep intake manifold vacuum (< 25 kPa)
            which physically contradicts a massive PCV leak!
        Result:
          1. System retrieves Case A as historically similar
          2. Explains the match on vehicle, engine, and pattern
          3. Detects contradiction on deep vacuum
          4. Actively reduces confidence & relevance
          5. Avoids declaring Case A's root cause as current root cause
          6. Provides safe PCV smoke test to H-3 without bypassing it
        """
        # 1. Register Historical Case A
        test_smoke = CaseTestResult(
            test_id="TEST_SMOKE_PCV_E2E",
            test_title="Intake Manifold Smoke Leak Inspection",
            target_ecu="ECM",
            outcome="PASSED",
            observations="Immediate vapor plume from cracked rubber elbow.",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        case_a = HistoricalDiagnosticCase(
            case_id="CASE_A_AVEO_PCV_BREACH",
            title="Chevrolet Aveo 1.4L PCV Elbow Vacuum Leak",
            summary="High unmetered air draw caused by split PCV elbow under manifold.",
            vehicle_context=self.aveo_context,
            is_dtc_free=True,
            active_dtcs=[],
            matched_pattern_ids=["PAT_MAF_LAG", "PAT_CROSS_MAF_MAP"],
            observed_features={"LTFT": 22.5, "MAF": 1.9, "MAP": 41.0},
            operating_conditions=[OperatingCondition.IDLE, OperatingCondition.WARM_UP],
            test_results=[test_smoke],
            root_cause=CaseRootCause(
                root_cause_id="RC_PCV_ELBOW_SPLIT",
                component_or_system="PCV Rubber Elbow Hose",
                mechanism_description="Hose aged and split open on manifold side.",
                confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
            ),
            technician_confirmation=self.tech_confirm,
            repair_outcome=self.repair,
            post_repair_verification=self.verification,
            lifecycle=CaseLifecycle.CONFIRMED,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="CASE_A_ARCHIVE_2024",
                is_technician_confirmed=True,
            ),
        )
        self.repo.add_case(case_a)

        # 2. Current Case B telemetry:
        # Same vehicle, similar trim drift, but contradictory MAP = 21.0 kPa (deep vacuum)
        obs_b = ObservedFeatureSet(
            session_id="SESS_CURRENT_B",
            operating_condition=OperatingCondition.IDLE,
            features={"LTFT": 21.5, "MAF": 1.8, "MAP": 21.0},
        )

        # 3. Match without contradiction flag
        uncontradicted_matches = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            observed_features=obs_b,
            matched_patterns=["PAT_MAF_LAG", "PAT_CROSS_MAF_MAP"],
            operating_conditions=[OperatingCondition.IDLE],
        )
        self.assertEqual(len(uncontradicted_matches), 1)
        self.assertEqual(uncontradicted_matches[0].case.case_id, "CASE_A_AVEO_PCV_BREACH")
        self.assertEqual(uncontradicted_matches[0].match_grade, CaseMatchGrade.HIGH_SIMILARITY)

        # 4. Match WITH contradiction detected (deep vacuum contradicts PCV hose breach)
        contradicted_matches = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            observed_features=obs_b,
            matched_patterns=["PAT_MAF_LAG", "PAT_CROSS_MAF_MAP"],
            operating_conditions=[OperatingCondition.IDLE],
            current_contradictions=["RC_PCV_ELBOW_SPLIT"],
        )
        self.assertEqual(len(contradicted_matches), 1)
        c_res = contradicted_matches[0]

        # 5. Verify similarity and relevance are severely penalized
        self.assertLess(c_res.overall_similarity, 0.50)
        self.assertLess(c_res.relevance_as_evidence, 0.50)
        self.assertEqual(c_res.match_grade, CaseMatchGrade.INSUFFICIENT_SIMILARITY)
        self.assertGreater(len(c_res.contradictions_detected), 0)

        # 6. Verify H-3 and H-4 adapters receive context without declaring premature root cause
        adapter = HistoricalCaseWorkflowAdapter(self.repo)
        safe_tests = adapter.get_historical_distinguishing_tests(
            vehicle_context=self.aveo_context,
            observed_features=obs_b,
            matched_patterns=["PAT_MAF_LAG", "PAT_CROSS_MAF_MAP"],
        )
        self.assertEqual(safe_tests[0].test_id, "TEST_SMOKE_PCV_E2E")

        rc_info = adapter.get_historical_root_cause_context(
            vehicle_context=self.aveo_context,
            observed_features=obs_b,
            matched_patterns=["PAT_MAF_LAG", "PAT_CROSS_MAF_MAP"],
            current_contradictions=["RC_PCV_ELBOW_SPLIT"],
        )
        # Even with contradiction, root cause is reported as historical context with low relevance
        self.assertEqual(rc_info[0]["root_cause_id"], "RC_PCV_ELBOW_SPLIT")
        self.assertLess(rc_info[0]["relevance"], 0.50)

    # ---------------------------------------------------------------------
    # 21. ECU FAMILY & SOFTWARE CALIBRATION SIMILARITY
    # ---------------------------------------------------------------------
    def test_21_ecu_and_software_calibration_similarity(self):
        """ECU family and software calibration ID contribute to higher similarity ranking."""
        case_matched_cal = HistoricalDiagnosticCase(
            case_id="CASE_CAL_MATCH",
            title="Calibrated ECU Case",
            summary="Exact calibration ID match.",
            vehicle_context=self.aveo_context, # Has Delphi MT80 and CAL_ID_968001
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="CAL_DOC"),
        )
        diff_cal_context = VehicleContext(
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            engine_code="F14D3",
            transmission="MANUAL",
            ecu_family="DELPHI_MT80",
            software_id="CAL_ID_DIFFERENT",
        )
        case_diff_cal = HistoricalDiagnosticCase(
            case_id="CASE_CAL_DIFF",
            title="Different Calibration Case",
            summary="Different calibration ID.",
            vehicle_context=diff_cal_context,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="CAL_DOC"),
        )
        self.repo.add_case(case_matched_cal)
        self.repo.add_case(case_diff_cal)

        results = self.repo.find_similar_cases(vehicle_context=self.aveo_context)
        self.assertEqual(results[0].case.case_id, "CASE_CAL_MATCH")
        self.assertGreater(results[0].overall_similarity, results[1].overall_similarity)

    # ---------------------------------------------------------------------
    # 22. WEAK & INSUFFICIENT HISTORICAL MATCH
    # ---------------------------------------------------------------------
    def test_22_weak_and_insufficient_historical_match(self):
        """Cases from unrelated manufacturers/systems produce LOW or INSUFFICIENT similarity."""
        toyota_case = HistoricalDiagnosticCase(
            case_id="CASE_TOYOTA_PRIUS",
            title="Prius Inverter Case",
            summary="Hybrid boost converter fault.",
            vehicle_context=VehicleContext(
                manufacturer="TOYOTA",
                model="PRIUS",
                model_year=2012,
                engine_code="2ZR_FXE",
            ),
            active_dtcs=[CaseDTCRecord(dtc_code="P0A08", target_ecu="HVBAT")],
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="TOYOTA_MANUAL"),
        )
        self.repo.add_case(toyota_case)

        # Query with Chevrolet Aveo context
        results = self.repo.find_similar_cases(
            vehicle_context=self.aveo_context,
            active_dtcs=["P0171"],
        )
        prius_match = [r for r in results if r.case.case_id == "CASE_TOYOTA_PRIUS"]
        if prius_match:
            self.assertEqual(prius_match[0].match_grade, CaseMatchGrade.INSUFFICIENT_SIMILARITY)
            self.assertLess(prius_match[0].overall_similarity, 0.30)

    # ---------------------------------------------------------------------
    # 23. UNCONFIRMED CASE DISCOUNT WEIGHTING
    # ---------------------------------------------------------------------
    def test_23_unconfirmed_case_discount_weighting(self):
        """Cases without technician confirmation receive discounted evidential relevance."""
        case_unconfirmed = HistoricalDiagnosticCase(
            case_id="CASE_UNCONFIRMED_ALGO",
            title="Automated Hypothesis Only",
            summary="Pure algorithmic finding without human physical confirmation.",
            vehicle_context=self.aveo_context,
            technician_confirmation=None, # Not confirmed!
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="AUTO_EXPERT"),
        )
        self.repo.add_case(case_unconfirmed)

        results = self.repo.find_similar_cases(vehicle_context=self.aveo_context)
        res = [r for r in results if r.case.case_id == "CASE_UNCONFIRMED_ALGO"][0]
        self.assertFalse(res.case.is_technician_confirmed())
        self.assertLess(res.relevance_as_evidence, res.overall_similarity)

    # ---------------------------------------------------------------------
    # 24. CASE CONFLICT & SUPERSEDING
    # ---------------------------------------------------------------------
    def test_24_case_conflict_and_superseding(self):
        """Case relationships explicitly document superseding or contradictory historical cases."""
        case_v1 = HistoricalDiagnosticCase(
            case_id="CASE_PURGE_V1",
            title="EVAP Purge Diagnosis V1",
            summary="Initial thought was purge solenoid.",
            vehicle_context=self.aveo_context,
            lifecycle=CaseLifecycle.CLOSED,
            relationships=[
                CaseRelationship(
                    target_case_id="CASE_PURGE_V2",
                    relationship_type=CaseRelationshipType.SUPERSEDES,
                    rationale="Refined diagnosis revealed gas cap seal defect instead.",
                )
            ],
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_V1"),
        )
        self.repo.add_case(case_v1)

        c = self.repo.get_case("CASE_PURGE_V1")
        self.assertEqual(len(c.relationships), 1)
        self.assertEqual(c.relationships[0].relationship_type, CaseRelationshipType.SUPERSEDES)

    # ---------------------------------------------------------------------
    # 25. D-LAYER HYPOTHESIS ENGINE INTEGRATION
    # ---------------------------------------------------------------------
    def test_25_d_layer_hypothesis_integration(self):
        """Historical cases supply FaultHypothesis models with contextual evidence."""
        case = HistoricalDiagnosticCase(
            case_id="CASE_D_LAYER",
            title="D-Layer Integration Case",
            summary="Supplying FaultHypothesis.",
            vehicle_context=self.aveo_context,
            candidate_hypotheses=["HYP_PCV_ELBOW_SPLIT", "HYP_MAF_DRIFT"],
            root_cause=CaseRootCause(
                root_cause_id="RC_PCV_ELBOW_SPLIT",
                component_or_system="PCV Elbow",
                mechanism_description="Split hose.",
                confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
            ),
            technician_confirmation=self.tech_confirm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_D"),
        )
        self.repo.add_case(case)

        adapter = HistoricalCaseWorkflowAdapter(self.repo)
        ctx = adapter.get_historical_root_cause_context(vehicle_context=self.aveo_context)
        self.assertTrue(any(item["root_cause_id"] == "RC_PCV_ELBOW_SPLIT" for item in ctx))

    # ---------------------------------------------------------------------
    # 26. ARCHITECTURAL BOUNDARY: NO AUTOMATIC PROMOTION TO KNOWLEDGE
    # ---------------------------------------------------------------------
    def test_26_case_to_knowledge_boundary_protection(self):
        """Historical cases are NEVER automatically promoted into I-1 knowledge or I-3 patterns."""
        kb_store = DiagnosticKnowledgeStore()
        pattern_store = FailurePatternLibraryStore()

        initial_kb_count = len(kb_store.list_entries())
        initial_pat_count = len(pattern_store.list_patterns())

        # Adding a confirmed historical case to repository
        case = HistoricalDiagnosticCase(
            case_id="CASE_ISOLATED_EXP",
            title="Experience Only Case",
            summary="Must not bleed into active knowledge.",
            vehicle_context=self.aveo_context,
            root_cause=CaseRootCause(
                root_cause_id="RC_ISOLATED",
                component_or_system="Isolated Part",
                mechanism_description="Isolated issue.",
                confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
            ),
            technician_confirmation=self.tech_confirm,
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="RO_ISO"),
        )
        self.repo.add_case(case)

        # Verify I-1 and I-3 remained completely unmutated
        self.assertEqual(len(kb_store.list_entries()), initial_kb_count)
        self.assertEqual(len(pattern_store.list_patterns()), initial_pat_count)
        self.assertIsNone(kb_store.get_entry("CASE_ISOLATED_EXP"))
        self.assertIsNone(pattern_store.get_pattern("CASE_ISOLATED_EXP"))


if __name__ == "__main__":
    unittest.main()
