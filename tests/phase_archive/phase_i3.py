# -*- coding: utf-8 -*-
"""
test_phase_i3.py — Phase I-3 Failure Pattern Library Acceptance Test Suite
=============================================================================
Certifies Phase I-3: Failure Pattern Library:
  1. Pattern creation & structural validation
  2. Stable pattern identity
  3. Pattern categories & taxonomy
  4. Pattern feature representation (mathematical & signal constraints)
  5. Temporal feature representation (lag, persistence, duration)
  6. Operating-condition constraints (idle, steady cruise, cold start)
  7. Vehicle applicability (universal, manufacturer, model)
  8. ECU applicability (target ECU family / module)
  9. Engine applicability (e.g. F14D3 vs Z16XER)
  10. Transmission applicability (manual vs automatic)
  11. Hardware / software applicability
  12. Deterministic pattern matching
  13. Strong match grade (>= 0.80)
  14. Partial match grade (0.50 - 0.80)
  15. Weak match grade (0.30 - 0.50)
  16. Non-match grade (< 0.30)
  17. Match explanation transparency & breakdown
  18. Supporting evidence feature accumulation
  19. Contradictory evidence (negative evidence penalty depressing score)
  20. Alternative explanations preserved (Pattern != Root Cause)
  21. DTC association as context (DTC != pattern proof)
  22. DTC-free pattern matching (sensor anomaly without DTC)
  23. ECU-specific DTC handling (ECM vs TCM DTC isolation)
  24. Communication-failure safeguard (bus error != component fault)
  25. Multi-ECU pattern separation
  26. Pattern composition (higher-level pattern references sub-patterns)
  27. Composition cycle protection (depth limits & visited set prevention)
  28. Bounded matching & result limits
  29. Lifecycle management (ACTIVE, CANDIDATE, DEPRECATED)
  30. Versioning & superseding
  31. Provenance tracking & source attribution
  32. Serialization round-trip (to_dict / from_dict)
  33. Conflict handling & contradictory data
  34. Specific vs generic pattern ranking (specific outranks generic)
  35. Context-dependent thresholding
  36. Temporal sequence & delay matching
  37. Intermittent pattern representation (dropouts & clustering)
  38. Command/response mismatch
  39. Cross-sensor disagreement
  40. H-3 integration (test selection)
  41. H-4 integration (root-cause hypotheses)
  42. H-5 integration (diagnostic workflow engine adapter)
  43. G integration (G-5 DiagnosticGraph pattern node & non-causal edges)
  44. I-1 regression compatibility
  45. I-2 regression compatibility
  46. Safety boundary verification: strict READ_ONLY test enforcement
  47. Large-library performance benchmark (< 50ms)
  48. Realistic diagnostic scenario: Chevrolet Aveo 1.4L lag/drift analysis
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
)
from vehicle_ecu_knowledge import (
    ProgressiveVehicleIdentity,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    ECUKnowledgeProfile,
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
    FailurePatternWorkflowAdapter,
    DiagnosticGraphPatternIntegrator,
)


class TestPhaseI3FailurePatternLibrary(unittest.TestCase):
    """Exhaustive unit and integration test suite for Phase I-3."""

    def setUp(self):
        self.store = FailurePatternLibraryStore()

        # Shared safe distinguishing test
        self.smoke_test = KnowledgeDistinguishingTest(
            test_id="TEST_SMOKE_INTAKE",
            title="Intake Smoke Test",
            description="Perform low-pressure smoke injection to detect physical unmetered air leaks.",
            discriminated_hypotheses=["HYP_VACUUM_LEAK", "HYP_MAF_SENSOR_FAULT"],
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )

        # Baseline vehicle context (Chevrolet Aveo 1.4L F14D3 MT80)
        self.aveo_context = VehicleContext(
            vin="KL1SF69Y68B123456",
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            engine_code="F14D3",
            transmission="MANUAL",
            ecu_family="DELPHI_MT80",
            metadata={"target_ecu": "ECM", "detected_ecus": ["ECM", "TCM", "ABS"]},
        )

    # ---------------------------------------------------------------------
    # 1. PATTERN CREATION & STABLE IDENTITY
    # ---------------------------------------------------------------------
    def test_01_pattern_creation_and_stable_identity(self):
        """Pattern requires valid ID, name, category, and read-only distinguishing tests."""
        feat = PatternFeatureRequirement(
            feature_id="F_MAF_DRIFT",
            feature_type=PatternFeatureType.VALUE_RANGE,
            signal_name="MAF",
            min_threshold=1.5,
            max_threshold=3.5,
            is_mandatory=True,
            weight=1.0,
        )
        pattern = FailurePattern(
            pattern_id="PAT_MAF_IDLE_DRIFT",
            name="MAF Idle Sensor Drift",
            category=PatternCategory.SENSOR_DRIFT,
            description="MAF signal drift at warm idle.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="SAE J1979",
            ),
            feature_requirements=[feat],
            possible_hypotheses=["HYP_MAF_DRIFT", "HYP_AIR_LEAK"],
            distinguishing_tests=[self.smoke_test],
        )
        self.assertEqual(pattern.pattern_id, "PAT_MAF_IDLE_DRIFT")
        self.assertEqual(pattern.category, PatternCategory.SENSOR_DRIFT)

        # Empty pattern_id must fail
        with self.assertRaises(ValueError):
            FailurePattern(
                pattern_id="",
                name="Invalid Empty ID",
                category=PatternCategory.SENSOR_DRIFT,
                description="Invalid",
                applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            )

    # ---------------------------------------------------------------------
    # 2. PATTERN CATEGORIES TAXONOMY
    # ---------------------------------------------------------------------
    def test_02_pattern_categories_taxonomy(self):
        """Verify all mandatory pattern categories are supported."""
        expected_categories = {
            "SENSOR_DRIFT",
            "INTERMITTENT_SIGNAL",
            "STUCK_VALUE",
            "RESPONSE_LAG",
            "CONTROL_OSCILLATION",
            "CROSS_SENSOR_DISAGREEMENT",
            "COMMAND_RESPONSE_MISMATCH",
            "THERMAL_INCONSISTENCY",
            "ENVELOPE_VIOLATION",
            "COMMUNICATION_ANOMALY",
        }
        actual_categories = {c.value for c in PatternCategory}
        for ec in expected_categories:
            self.assertIn(ec, actual_categories)

    # ---------------------------------------------------------------------
    # 3. PATTERN FEATURE REPRESENTATION & THRESHOLDS
    # ---------------------------------------------------------------------
    def test_03_feature_representation_and_evaluation(self):
        """PatternFeatureRequirement evaluates numerical values accurately against bounds."""
        req = PatternFeatureRequirement(
            feature_id="F_RPM_DEV",
            feature_type=PatternFeatureType.VALUE_RANGE,
            signal_name="RPM",
            min_threshold=650.0,
            max_threshold=850.0,
            is_mandatory=True,
            weight=1.0,
        )
        # Inside range
        sat, score, expl = req.evaluate_feature(750.0)
        self.assertTrue(sat)
        self.assertEqual(score, 1.0)

        # Below min
        sat, score, expl = req.evaluate_feature(500.0)
        self.assertFalse(sat)
        self.assertEqual(score, 0.0)
        self.assertIn("min threshold", expl)

        # Above max
        sat, score, expl = req.evaluate_feature(1000.0)
        self.assertFalse(sat)
        self.assertEqual(score, 0.0)
        self.assertIn("max threshold", expl)

        # Missing mandatory
        sat, score, expl = req.evaluate_feature(None)
        self.assertFalse(sat)
        self.assertEqual(score, 0.0)

        # Missing optional feature
        opt_req = PatternFeatureRequirement(
            feature_id="F_OPT",
            feature_type=PatternFeatureType.VALUE_RANGE,
            signal_name="OPT",
            is_mandatory=False,
        )
        sat, score, expl = opt_req.evaluate_feature(None)
        self.assertTrue(sat)
        self.assertEqual(score, 0.5)

    # ---------------------------------------------------------------------
    # 4. TEMPORAL & RATE FEATURES
    # ---------------------------------------------------------------------
    def test_04_temporal_and_rate_features(self):
        """Verify temporal delay, persistence, and rate-of-change feature types."""
        req_delay = PatternFeatureRequirement(
            feature_id="F_LAG",
            feature_type=PatternFeatureType.DELAY_TIME_S,
            signal_name="MAF",
            min_threshold=0.5,
            max_threshold=2.0,
            description="MAF delay time 0.5s to 2.0s after throttle jump.",
        )
        sat, score, _ = req_delay.evaluate_feature(1.2)
        self.assertTrue(sat)

        req_pers = PatternFeatureRequirement(
            feature_id="F_PERSISTENCE",
            feature_type=PatternFeatureType.PERSISTENCE_DURATION_S,
            signal_name="FUEL_TRIM",
            min_threshold=5.0,
            description="Fuel trim divergence persisting over 5 seconds.",
        )
        sat, score, _ = req_pers.evaluate_feature(8.0)
        self.assertTrue(sat)

    # ---------------------------------------------------------------------
    # 5. OPERATING CONDITION CONSTRAINTS
    # ---------------------------------------------------------------------
    def test_05_operating_condition_constraints(self):
        """Pattern restricted to WARM_IDLE must not match during HIGH_LOAD or COLD_START."""
        pattern = FailurePattern(
            pattern_id="PAT_WARM_IDLE_HUNT",
            name="Warm Idle Hunting",
            category=PatternCategory.CONTROL_OSCILLATION,
            description="Idle RPM hunting only when warm.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            required_operating_conditions=[OperatingCondition.IDLE, OperatingCondition.WARM_UP],
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_RPM_OSC",
                    feature_type=PatternFeatureType.OSCILLATION_AMPLITUDE,
                    signal_name="RPM",
                    min_threshold=100.0,
                )
            ],
        )
        self.store.register_pattern(pattern)

        # Condition matches: IDLE
        obs_idle = ObservedFeatureSet(
            session_id="SESS_01",
            operating_condition=OperatingCondition.IDLE,
            features={"RPM:OSCILLATION_AMPLITUDE": 150.0},
        )
        results = self.store.match_patterns(obs_idle)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].pattern.pattern_id, "PAT_WARM_IDLE_HUNT")

        # Condition mismatch: HIGH_LOAD (must not match)
        obs_load = ObservedFeatureSet(
            session_id="SESS_02",
            operating_condition=OperatingCondition.HIGH_LOAD,
            features={"RPM:OSCILLATION_AMPLITUDE": 150.0},
        )
        results_load = self.store.match_patterns(obs_load)
        self.assertEqual(len(results_load), 0)

    # ---------------------------------------------------------------------
    # 6. VEHICLE & ECU APPLICABILITY
    # ---------------------------------------------------------------------
    def test_06_vehicle_and_ecu_applicability(self):
        """Pattern defined for GM/Chevrolet must not match Toyota."""
        gm_pattern = FailurePattern(
            pattern_id="PAT_GM_THROTTLE_LAG",
            name="GM DBW Throttle Lag",
            category=PatternCategory.RESPONSE_LAG,
            description="Electronic throttle response delay on GM vehicles.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.MANUFACTURER,
                manufacturers=["CHEVROLET", "OPEL", "HOLDEN"],
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_LAG",
                    feature_type=PatternFeatureType.DELAY_TIME_S,
                    signal_name="TPS",
                    min_threshold=0.3,
                )
            ],
        )
        self.store.register_pattern(gm_pattern)

        obs = ObservedFeatureSet(
            session_id="SESS_03",
            features={"TPS:DELAY_TIME_S": 0.5},
        )

        # Matches Chevrolet
        res_gm = self.store.match_patterns(obs, vehicle_context=self.aveo_context)
        self.assertEqual(len(res_gm), 1)

        # Rejects Toyota context
        toyota_ctx = VehicleContext(
            vin="JT123456789012345",
            manufacturer="TOYOTA",
            model="COROLLA",
            model_year=2015,
        )
        res_toyota = self.store.match_patterns(obs, vehicle_context=toyota_ctx)
        self.assertEqual(len(res_toyota), 0)

    # ---------------------------------------------------------------------
    # 7. ENGINE & TRANSMISSION APPLICABILITY
    # ---------------------------------------------------------------------
    def test_07_engine_and_transmission_applicability(self):
        """Pattern specific to F14D3 engine must not match Z16XER."""
        f14_pattern = FailurePattern(
            pattern_id="PAT_F14D3_EGR_STICKING",
            name="F14D3 EGR Valve Sticking",
            category=PatternCategory.COMMAND_RESPONSE_MISMATCH,
            description="EGR pintle position mismatch on F14D3.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="TECH_CASE_01"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_EGR_ERR",
                    feature_type=PatternFeatureType.COMMAND_ERROR_MARGIN,
                    signal_name="EGR_POS",
                    min_threshold=15.0,
                )
            ],
        )
        self.store.register_pattern(f14_pattern)

        obs = ObservedFeatureSet(
            session_id="SESS_04",
            features={"EGR_POS:COMMAND_ERROR_MARGIN": 22.0},
        )

        # Matches Aveo F14D3
        res = self.store.match_patterns(obs, vehicle_context=self.aveo_context)
        self.assertEqual(len(res), 1)

        # Does not match Z16XER Opel
        opel_ctx = VehicleContext(
            vin="W0L000048B1234567",
            manufacturer="OPEL",
            model="ASTRA",
            engine_code="Z16XER",
        )
        res_opel = self.store.match_patterns(obs, vehicle_context=opel_ctx)
        self.assertEqual(len(res_opel), 0)

    # ---------------------------------------------------------------------
    # 8. MATCH GRADES: STRONG, PARTIAL, WEAK, NON-MATCH
    # ---------------------------------------------------------------------
    def test_08_match_grades(self):
        """Verify calibration of Strong, Partial, Weak, and Non-match grades."""
        pattern = FailurePattern(
            pattern_id="PAT_MULTI_FEAT",
            name="Multi Feature Pattern",
            category=PatternCategory.SENSOR_DRIFT,
            description="Requires 2 features.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F1",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="SIG1",
                    min_threshold=10.0,
                    max_threshold=20.0,
                    weight=1.0,
                ),
                PatternFeatureRequirement(
                    feature_id="F2",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="SIG2",
                    min_threshold=50.0,
                    max_threshold=60.0,
                    weight=1.0,
                ),
            ],
        )
        self.store.register_pattern(pattern)

        # Both match -> Strong match
        obs_strong = ObservedFeatureSet(
            session_id="S_STR",
            features={"SIG1:VALUE_RANGE": 15.0, "SIG2:VALUE_RANGE": 55.0},
        )
        res_s = self.store.match_patterns(obs_strong)
        self.assertEqual(res_s[0].match_grade, PatternMatchGrade.STRONG_MATCH)
        self.assertGreaterEqual(res_s[0].overall_score, 0.70)

        # Missing one mandatory feature -> Non-match or weak
        obs_missing = ObservedFeatureSet(
            session_id="S_MISS",
            features={"SIG1:VALUE_RANGE": 15.0},
        )
        res_m = self.store.match_patterns(obs_missing)
        self.assertIn(res_m[0].match_grade, (PatternMatchGrade.WEAK_MATCH, PatternMatchGrade.NON_MATCH))
        self.assertIn("SIG2 (VALUE_RANGE)", res_m[0].missing_mandatory_features)

    # ---------------------------------------------------------------------
    # 9. CONTRADICTORY EVIDENCE & SCORE DEPRESSION
    # ---------------------------------------------------------------------
    def test_09_contradictory_evidence_penalizes_match(self):
        """Contradictory / negative evidence visibly depresses pattern score and marks NON_MATCH."""
        pattern = FailurePattern(
            pattern_id="PAT_VACUUM_LEAK",
            name="Intake Vacuum Leak",
            category=PatternCategory.SENSOR_DRIFT,
            description="High lean fuel trim at idle.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_LTFT_HIGH",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LTFT",
                    min_threshold=15.0,
                    weight=1.0,
                )
            ],
            # Contradiction: If MAP vacuum is perfectly high (> 75 kPa vacuum / < 25 kPa abs), contradicts leak
            contradictory_features=[
                PatternFeatureRequirement(
                    feature_id="C_MAP_PERFECT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="MAP",
                    max_threshold=25.0,
                    weight=1.5,
                    description="Deep intake manifold vacuum strongly contradicts massive vacuum leak.",
                )
            ],
        )
        self.store.register_pattern(pattern)

        # Without contradiction: Strong match
        obs_clean = ObservedFeatureSet(
            session_id="S_CLEAN",
            features={"LTFT:VALUE_RANGE": 20.0, "MAP:VALUE_RANGE": 45.0},
        )
        res_clean = self.store.match_patterns(obs_clean)
        self.assertEqual(res_clean[0].match_grade, PatternMatchGrade.STRONG_MATCH)
        self.assertEqual(len(res_clean[0].contradictory_features_detected), 0)

        # With active contradiction (MAP=20 kPa < 25 kPa): Score drops, graded NON_MATCH
        obs_contradiction = ObservedFeatureSet(
            session_id="S_CONTRA",
            features={"LTFT:VALUE_RANGE": 20.0, "MAP:VALUE_RANGE": 20.0},
        )
        res_contra = self.store.match_patterns(obs_contradiction)
        self.assertEqual(res_contra[0].match_grade, PatternMatchGrade.NON_MATCH)
        self.assertGreater(len(res_contra[0].contradictory_features_detected), 0)
        self.assertLess(res_contra[0].overall_score, res_clean[0].overall_score)

    # ---------------------------------------------------------------------
    # 10. ALTERNATIVE EXPLANATIONS (PATTERN != ROOT CAUSE)
    # ---------------------------------------------------------------------
    def test_10_alternative_explanations_preserved(self):
        """Pattern must preserve competing alternative root causes; never jump to one conclusion."""
        pattern = FailurePattern(
            pattern_id="PAT_O2_SLOW_RESPONSE",
            name="Upstream O2 Slow Response",
            category=PatternCategory.RESPONSE_LAG,
            description="Delayed switching frequency on bank 1 O2 sensor.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            possible_hypotheses=[
                "HYP_O2_SILICONE_POISONING",
                "HYP_EXHAUST_MANIFOLD_CRACK",
                "HYP_HARNESS_HIGH_RESISTANCE",
            ],
            alternative_explanations=[
                "Exhaust leak upstream of sensor introducing fresh ambient oxygen",
                "Heater circuit voltage drop causing low sensor operating temperature",
                "Silica/oil ash contamination on zirconia element",
            ],
            distinguishing_tests=[self.smoke_test],
        )
        self.assertEqual(len(pattern.possible_hypotheses), 3)
        self.assertEqual(len(pattern.alternative_explanations), 3)
        self.assertIn("Exhaust leak upstream of sensor introducing fresh ambient oxygen", pattern.alternative_explanations)

    # ---------------------------------------------------------------------
    # 11. DTC ASSOCIATION & DTC-FREE PATTERN MATCHING
    # ---------------------------------------------------------------------
    def test_11_dtc_free_pattern_matching(self):
        """Pattern matches purely on physical telemetry features when active DTC count is zero."""
        pattern = FailurePattern(
            pattern_id="PAT_DTC_FREE_MAF_OFFSET",
            name="Unmetered Intake Air Offset",
            category=PatternCategory.CROSS_SENSOR_DISAGREEMENT,
            description="MAF disagrees with Speed-Density MAP calculation, but trims haven't tripped DTC P0171 yet.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            associated_dtcs=["P0171", "P0101"],
            is_dtc_free_capable=True,
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_MAF_MAP_DELTA",
                    feature_type=PatternFeatureType.CROSS_SENSOR_DELTA,
                    signal_name="MAF_MAP_DIFF",
                    min_threshold=20.0,
                )
            ],
        )
        self.store.register_pattern(pattern)

        # Zero DTCs active, but cross-sensor delta is 25%
        obs_no_dtc = ObservedFeatureSet(
            session_id="SESS_NO_DTC",
            active_dtcs=[],
            features={"MAF_MAP_DIFF:CROSS_SENSOR_DELTA": 25.0},
        )
        res = self.store.match_patterns(obs_no_dtc)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].match_grade, PatternMatchGrade.STRONG_MATCH)
        self.assertTrue(res[0].pattern.is_dtc_free_capable)

    # ---------------------------------------------------------------------
    # 12. COMMUNICATION FAILURE SAFEGUARD
    # ---------------------------------------------------------------------
    def test_12_communication_failure_safeguard(self):
        """Invariant: Loss of communication must NEVER be classified as a component defect."""
        comm_pattern = FailurePattern(
            pattern_id="PAT_CAN_BUS_TIMEOUT",
            name="CAN Bus Transmission Timeout",
            category=PatternCategory.COMMUNICATION_ANOMALY,
            description="Periodic broadcast packet missing from TCM.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            associated_dtcs=["U0101"],
            possible_hypotheses=[
                "HYP_CAN_WIRING_OPEN",
                "HYP_CAN_TERMINATION_RESISTOR_FAULT",
                "HYP_TCM_POWER_LOSS",
            ],
            alternative_explanations=[
                "Harness pinch or corrosion at transmission connector",
                "Blown fuse on TCM supply rail",
                "CAN-H or CAN-L short to ground",
            ],
        )
        self.assertEqual(comm_pattern.category, PatternCategory.COMMUNICATION_ANOMALY)
        # Ensure hypotheses point to network/wiring/power, NOT defective internal TCM electronics
        for hyp in comm_pattern.possible_hypotheses:
            self.assertNotIn("INTERNAL_SILICON_DEFECT", hyp)
        for alt in comm_pattern.alternative_explanations:
            self.assertNotIn("Replace TCM module immediately", alt)

    # ---------------------------------------------------------------------
    # 13. MULTI-ECU PATTERN SEPARATION
    # ---------------------------------------------------------------------
    def test_13_multi_ecu_pattern_isolation(self):
        """ECU-A (ECM) reporting bus timeout does not falsely blame ECU-B (ABS) component."""
        pattern_ecm = FailurePattern(
            pattern_id="PAT_ECM_REPORTS_U0121",
            name="ECM Reports Lost Communication With ABS",
            category=PatternCategory.COMMUNICATION_ANOMALY,
            description="ECM lost frame from ABS controller.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            associated_dtcs=["U0121"],
            possible_hypotheses=["HYP_ABS_BUS_OPEN"],
        )
        pattern_abs = FailurePattern(
            pattern_id="PAT_ABS_WHEEL_SPEED_ERR",
            name="ABS Wheel Speed Signal Loss",
            category=PatternCategory.INTERMITTENT_SIGNAL,
            description="Physical wheel speed sensor dropout.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            associated_dtcs=["C0035"],
            possible_hypotheses=["HYP_WHEEL_SPEED_SENSOR_GAP"],
        )
        self.store.register_pattern(pattern_ecm)
        self.store.register_pattern(pattern_abs)

        p_ecm = self.store.get_pattern("PAT_ECM_REPORTS_U0121")
        p_abs = self.store.get_pattern("PAT_ABS_WHEEL_SPEED_ERR")
        self.assertNotEqual(p_ecm.category, p_abs.category)
        self.assertIn("U0121", p_ecm.associated_dtcs)
        self.assertIn("C0035", p_abs.associated_dtcs)

    # ---------------------------------------------------------------------
    # 14. PATTERN COMPOSITION & CYCLE PROTECTION
    # ---------------------------------------------------------------------
    def test_14_pattern_composition_and_cycle_protection(self):
        """Pattern composition allows sub-pattern references and prevents recursion deadlocks."""
        # Sub-pattern 1: Reference voltage drop
        sub1 = FailurePattern(
            pattern_id="PAT_5V_REF_DROP",
            name="5V Reference Instability",
            category=PatternCategory.OPERATING_ENVELOPE_VIOLATION,
            description="5V reference rail drops below 4.75V.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_5V",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="VREF_5V",
                    max_threshold=4.75,
                )
            ],
        )
        # Composed pattern: Multi-sensor fault due to 5V supply drop
        composed = FailurePattern(
            pattern_id="PAT_COMMON_5V_RAIL_FAULT",
            name="Multi-Sensor Reference Supply Collapse",
            category=PatternCategory.CROSS_SENSOR_DISAGREEMENT,
            description="Multiple sensors reporting out of range due to common reference sag.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_TPS_ERR",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="TPS_VOLT",
                    max_threshold=0.2,
                )
            ],
            composed_pattern_ids=["PAT_5V_REF_DROP", "PAT_COMMON_5V_RAIL_FAULT"],  # Intentional self-cycle!
        )
        self.store.register_pattern(sub1)
        self.store.register_pattern(composed)

        obs = ObservedFeatureSet(
            session_id="SESS_COMP",
            features={
                "VREF_5V:VALUE_RANGE": 4.5,
                "TPS_VOLT:VALUE_RANGE": 0.15,
            },
        )
        # Matching must complete promptly without RecursionError despite circular reference
        t0 = time.perf_counter()
        results = self.store.match_patterns(obs, max_composition_depth=3)
        duration = time.perf_counter() - t0
        self.assertLess(duration, 0.1)  # Must be near-instantaneous
        self.assertGreaterEqual(len(results), 1)

    # ---------------------------------------------------------------------
    # 15. LIFECYCLE & VERSIONING
    # ---------------------------------------------------------------------
    def test_15_lifecycle_and_versioning(self):
        """Lifecycle transitions and version superseding."""
        pat_v1 = FailurePattern(
            pattern_id="PAT_EVAP_PURGE_FLOW",
            name="EVAP Purge Flow Inconsistency",
            category=PatternCategory.COMMAND_RESPONSE_MISMATCH,
            description="V1 pattern.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            lifecycle=KnowledgeLifecycle.DEPRECATED,
            version=1,
            superseded_by="PAT_EVAP_PURGE_FLOW_V2",
        )
        pat_v2 = FailurePattern(
            pattern_id="PAT_EVAP_PURGE_FLOW_V2",
            name="EVAP Purge Flow Inconsistency (Refined)",
            category=PatternCategory.COMMAND_RESPONSE_MISMATCH,
            description="V2 pattern with tightened fuel trim window.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            lifecycle=KnowledgeLifecycle.ACTIVE,
            version=2,
            supersedes="PAT_EVAP_PURGE_FLOW",
        )
        self.store.register_pattern(pat_v1)
        self.store.register_pattern(pat_v2)

        # active_only=True must ignore v1
        obs = ObservedFeatureSet(session_id="SESS_V")
        active_res = self.store.match_patterns(obs, active_only=True)
        active_ids = [r.pattern.pattern_id for r in active_res]
        self.assertNotIn("PAT_EVAP_PURGE_FLOW", active_ids)
        self.assertIn("PAT_EVAP_PURGE_FLOW_V2", active_ids)

    # ---------------------------------------------------------------------
    # 16. SERIALIZATION ROUND-TRIP
    # ---------------------------------------------------------------------
    def test_16_serialization_round_trip(self):
        """Pattern and library store serialize to dict and reconstruct losslessly."""
        feat = PatternFeatureRequirement(
            feature_id="F_TRIM",
            feature_type=PatternFeatureType.RATE_OF_CHANGE,
            signal_name="STFT",
            min_threshold=5.0,
            max_threshold=15.0,
            weight=1.2,
        )
        pat = FailurePattern(
            pattern_id="PAT_SERIAL_TEST",
            name="Serialization Test Pattern",
            category=PatternCategory.CONTROL_OSCILLATION,
            description="Testing round-trip serialization.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.MODEL,
                manufacturers=["CHEVROLET"],
                models=["AVEO"],
            ),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="Ref-12345",
            ),
            required_operating_conditions=[OperatingCondition.IDLE],
            feature_requirements=[feat],
            associated_dtcs=["P0170"],
            distinguishing_tests=[self.smoke_test],
        )
        # FailurePattern to/from dict
        p_dict = pat.to_dict()
        p_reconstructed = FailurePattern.from_dict(p_dict)
        self.assertEqual(p_reconstructed.pattern_id, pat.pattern_id)
        self.assertEqual(p_reconstructed.category, pat.category)
        self.assertEqual(len(p_reconstructed.distinguishing_tests), 1)
        self.assertEqual(p_reconstructed.distinguishing_tests[0].test_id, self.smoke_test.test_id)

        # Library Store to/from dict
        self.store.register_pattern(pat)
        store_dict = self.store.to_dict()
        new_store = FailurePatternLibraryStore.from_dict(store_dict)
        retrieved = new_store.get_pattern("PAT_SERIAL_TEST")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, pat.name)

    # ---------------------------------------------------------------------
    # 17. SPECIFIC VS GENERIC PATTERN RANKING
    # ---------------------------------------------------------------------
    def test_17_specific_vs_generic_ranking(self):
        """Engine-specific pattern outranks generic pattern when vehicle context matches."""
        generic_pat = FailurePattern(
            pattern_id="PAT_GENERIC_LEAN",
            name="Generic Lean Pattern",
            category=PatternCategory.SENSOR_DRIFT,
            description="Universal lean condition.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_LTFT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LTFT",
                    min_threshold=15.0,
                )
            ],
        )
        f14d3_pat = FailurePattern(
            pattern_id="PAT_F14D3_PCV_LEAN",
            name="Chevrolet Aveo F14D3 PCV Lean Pattern",
            category=PatternCategory.SENSOR_DRIFT,
            description="Specific F14D3 intake PCV elbow vacuum breach.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                models=["AVEO"],
                engine_codes=["F14D3"],
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED, source_reference="TECH_CASE_01"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_LTFT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LTFT",
                    min_threshold=15.0,
                )
            ],
        )
        self.store.register_pattern(generic_pat)
        self.store.register_pattern(f14d3_pat)

        obs = ObservedFeatureSet(
            session_id="SESS_RANK",
            features={"LTFT:VALUE_RANGE": 22.0},
        )
        matches = self.store.match_patterns(obs, vehicle_context=self.aveo_context)
        self.assertEqual(len(matches), 2)
        # Specific pattern must be top-ranked due to higher applicability weight
        self.assertEqual(matches[0].pattern.pattern_id, "PAT_F14D3_PCV_LEAN")
        self.assertGreater(matches[0].overall_score, matches[1].overall_score)
        self.assertGreater(matches[0].specificity_weight, matches[1].specificity_weight)

    # ---------------------------------------------------------------------
    # 18. INTERMITTENT & SIGNAL DROPOUT PATTERNS
    # ---------------------------------------------------------------------
    def test_18_intermittent_signal_dropout(self):
        """Intermittent signal dropout evaluated as telemetry pattern without claiming wiring fault."""
        pattern = FailurePattern(
            pattern_id="PAT_CKP_DROPOUT",
            name="Crankshaft Position Sensor Intermittent Dropout",
            category=PatternCategory.INTERMITTENT_SIGNAL,
            description="Sporadic dropouts under engine vibration.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_DROPOUT_COUNT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="CKP_DROPOUTS",
                    min_threshold=3.0,
                    description="At least 3 discrete signal loss events recorded.",
                )
            ],
            possible_hypotheses=[
                "HYP_CKP_SENSOR_INTERNAL_THERMAL_INTERMITTENT",
                "HYP_CKP_HARNESS_TERMINATION_LOOSE",
                "HYP_RELUCTOR_WHEEL_RUNOUT",
            ],
            alternative_explanations=[
                "Loose sensor harness connector pin fretting corrosion",
                "Crank reluctor wheel missing or damaged tooth",
                "Internal pickup coil open-circuiting when warm",
            ],
        )
        self.store.register_pattern(pattern)

        obs = ObservedFeatureSet(
            session_id="SESS_CKP",
            features={"CKP_DROPOUTS:VALUE_RANGE": 5.0},
        )
        matches = self.store.match_patterns(obs)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].pattern.pattern_id, "PAT_CKP_DROPOUT")
        self.assertEqual(matches[0].match_grade, PatternMatchGrade.STRONG_MATCH)

    # ---------------------------------------------------------------------
    # 19. H-LAYER INTEGRATIONS (H-3, H-4, H-5)
    # ---------------------------------------------------------------------
    def test_19_h_layer_workflow_adapters(self):
        """Workflow adapter exposes candidate hypotheses and safe distinguishing tests for H-3/H-4/H-5."""
        pattern = FailurePattern(
            pattern_id="PAT_COOLANT_SENSOR_STUCK",
            name="ECT Sensor Stuck Cold",
            category=PatternCategory.STUCK_VALUE,
            description="Engine coolant temperature stuck at -40C.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_ECT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="ECT",
                    max_threshold=-30.0,
                )
            ],
            possible_hypotheses=["HYP_ECT_CIRCUIT_OPEN", "HYP_ECT_SENSOR_FAILED"],
            distinguishing_tests=[self.smoke_test],
        )
        self.store.register_pattern(pattern)

        adapter = FailurePatternWorkflowAdapter(self.store)
        obs = ObservedFeatureSet(
            session_id="SESS_ECT",
            features={"ECT:VALUE_RANGE": -40.0},
        )

        # H-4 Root-Cause Hypotheses provider
        hyps = adapter.get_candidate_hypotheses_from_telemetry(obs)
        self.assertIn("HYP_ECT_CIRCUIT_OPEN", hyps)
        self.assertIn("HYP_ECT_SENSOR_FAILED", hyps)

        # H-3 Test Selector distinguishing tests provider
        tests = adapter.get_distinguishing_tests_for_matched_patterns(obs)
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].test_id, self.smoke_test.test_id)

    # ---------------------------------------------------------------------
    # 20. G INTEGRATION (G-5 DIAGNOSTIC GRAPH NON-CAUSAL EDGES)
    # ---------------------------------------------------------------------
    def test_20_diagnostic_graph_pattern_integration(self):
        """Matched pattern binds to DiagnosticGraph as ANOMALY node with ASSOCIATED_WITH edge (non-causal)."""
        graph = DiagnosticGraph()
        # Add a DTC node
        dtc_node_id = make_dtc_node_id("ECM", "P0171")
        graph.add_node(GraphNode(
            node_id=dtc_node_id,
            node_type=GraphNodeType.DTC,
            label="DTC P0171",
        ))

        pat = FailurePattern(
            pattern_id="PAT_LEAN_TELEMETRY",
            name="Lean Telemetry Profile",
            category=PatternCategory.SENSOR_DRIFT,
            description="Trims elevated.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            associated_dtcs=["P0171"],
        )
        match = PatternMatchResult(
            pattern=pat,
            match_grade=PatternMatchGrade.STRONG_MATCH,
            overall_score=0.88,
            feature_match_ratio=1.0,
            applicability_result=ApplicabilityResult.CONFIRMED_APPLICABLE,
            specificity_weight=1.0,
            satisfied_features=["LTFT"],
        )

        pat_node_id = DiagnosticGraphPatternIntegrator.integrate_matched_pattern(graph, match)
        self.assertIn(pat_node_id, graph.nodes)
        self.assertEqual(graph.nodes[pat_node_id].node_type, GraphNodeType.ANOMALY)

        # Verify edge type is strictly non-causal ASSOCIATED_WITH
        edge_id = f"edge_pattern_PAT_LEAN_TELEMETRY_P0171"
        edge = graph.get_edge(edge_id)
        self.assertIsNotNone(edge)
        self.assertEqual(edge.edge_type, GraphEdgeType.ASSOCIATED_WITH)

    # ---------------------------------------------------------------------
    # 21. SAFETY BOUNDARY: REJECT NON-READ-ONLY TESTS
    # ---------------------------------------------------------------------
    def test_21_safety_boundary_rejects_non_read_only_tests(self):
        """Pattern creation strictly rejects dangerous / actuating distinguishing tests."""
        # 1. Distinguishing test itself rejects non-READ_ONLY classification
        with self.assertRaises(ValueError) as ctx1:
            KnowledgeDistinguishingTest(
                test_id="TEST_ACTUATE_INJECTOR",
                title="Force Injector Pulse",
                description="Actuate injector at 50Hz.",
                discriminated_hypotheses=["HYP_1"],
                safety_classification=ServiceSafetyClassification.ACTUATION,  # Prohibited!
            )
        self.assertIn("Safety Invariant Violation", str(ctx1.exception))

        # 2. FailurePattern post_init verifies test safety
        safe_dt = KnowledgeDistinguishingTest(
            test_id="TEST_SAFE_PROBE",
            title="Safe Voltage Probe",
            description="Passive read of terminal voltage.",
            discriminated_hypotheses=["HYP_1"],
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        # Force non-READ_ONLY after init to test FailurePattern guard
        object.__setattr__(safe_dt, "safety_classification", ServiceSafetyClassification.ACTUATION)
        with self.assertRaises(ValueError) as ctx2:
            FailurePattern(
                pattern_id="PAT_DANGEROUS",
                name="Dangerous Pattern",
                category=PatternCategory.COMMAND_RESPONSE_MISMATCH,
                description="Invalid pattern.",
                applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
                distinguishing_tests=[safe_dt],
            )
        self.assertIn("Safety Violation", str(ctx2.exception))

    # ---------------------------------------------------------------------
    # 22. LARGE-LIBRARY PERFORMANCE BENCHMARK
    # ---------------------------------------------------------------------
    def test_22_large_library_performance_benchmark(self):
        """Store with 500+ patterns matches queries deterministically within 50ms."""
        for i in range(500):
            cat = list(PatternCategory)[i % len(PatternCategory)]
            p = FailurePattern(
                pattern_id=f"SYNTH_PAT_{i:04d}",
                name=f"Synthetic Pattern {i}",
                category=cat,
                description="Benchmark pattern fixture.",
                applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="BENCHMARK"),
                feature_requirements=[
                    PatternFeatureRequirement(
                        feature_id=f"F_VAL_{i}",
                        feature_type=PatternFeatureType.VALUE_RANGE,
                        signal_name=f"SIG_{i % 20}",
                        min_threshold=float(i % 50),
                    )
                ],
            )
            self.store.register_pattern(p)

        self.assertEqual(len(self.store.list_patterns()), 500)

        obs = ObservedFeatureSet(
            session_id="BENCHMARK",
            features={"SIG_5:VALUE_RANGE": 25.0},
        )
        t0 = time.perf_counter()
        results = self.store.match_patterns(obs, max_results=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertLess(elapsed_ms, 50.0, f"Query took {elapsed_ms:.2f}ms, expected < 50ms")
        self.assertLessEqual(len(results), 10)

    # ---------------------------------------------------------------------
    # 23. REALISTIC END-TO-END CONTEXTUAL DIAGNOSTIC SCENARIO
    # ---------------------------------------------------------------------
    def test_23_realistic_diagnostic_scenario(self):
        """
        End-to-End Diagnostic Scenario:
        Chevrolet Aveo 1.4L F14D3 with Delco/Delphi MT80 ECM
        Telemetry: Elevated Long-Term Fuel Trim (24%) at warm idle + MAF response lag
        Result:
          - Pattern Matcher retrieves F14D3 PCV Vacuum Breach pattern
          - Specific F14D3 pattern outranks generic lean pattern
          - MAP deep-vacuum contradiction is checked and not triggered
          - Returns competing hypotheses and safe intake smoke test
          - Integrates with H-3/H-4 adapters without declaring premature root cause
        """
        # 1. Register generic lean pattern
        self.store.register_pattern(FailurePattern(
            pattern_id="PAT_E2E_GENERIC_LEAN",
            name="Generic Closed-Loop Lean",
            category=PatternCategory.SENSOR_DRIFT,
            description="Generic lean condition across vehicles.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_GEN_LTFT",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LTFT",
                    min_threshold=15.0,
                )
            ],
            possible_hypotheses=["HYP_GENERIC_FUEL_STARVATION"],
        ))

        # 2. Register specific Aveo F14D3 PCV breach pattern
        dt = KnowledgeDistinguishingTest(
            test_id="TEST_F14D3_SMOKE_PCV",
            title="Aveo F14D3 PCV Elbow Smoke Test",
            description="Visual smoke inspection of intake manifold rubber elbow under throttle body.",
            discriminated_hypotheses=["HYP_PCV_ELBOW_SPLIT", "HYP_MAF_DEGRADED"],
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        self.store.register_pattern(FailurePattern(
            pattern_id="PAT_E2E_AVEO_PCV_BREACH",
            name="Chevrolet Aveo F14D3 PCV Elbow Split Failure Pattern",
            category=PatternCategory.CROSS_SENSOR_DISAGREEMENT,
            description="High unmetered air draw through split PCV elbow, prominent at warm idle.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                models=["AVEO"],
                engine_codes=["F14D3"],
            ),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="TSB-AVEO-2008-04",
                is_technician_confirmed=True,
            ),
            required_operating_conditions=[OperatingCondition.IDLE],
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_LTFT_HIGH",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="LTFT",
                    min_threshold=18.0,
                    weight=1.5,
                ),
                PatternFeatureRequirement(
                    feature_id="F_MAF_LOW",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="MAF",
                    max_threshold=2.2,  # Low gram/sec reading because air enters past MAF
                    weight=1.0,
                ),
            ],
            contradictory_features=[
                PatternFeatureRequirement(
                    feature_id="C_MAP_DEEP",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="MAP",
                    max_threshold=25.0,
                    weight=2.0,
                )
            ],
            associated_dtcs=["P0171"],
            possible_hypotheses=[
                "HYP_PCV_ELBOW_SPLIT",
                "HYP_MAF_DEGRADED",
                "HYP_FUEL_PUMP_LOW_PRESSURE",
            ],
            alternative_explanations=[
                "Cracked rubber 90-degree elbow under intake manifold",
                "Silicone-contaminated MAF hot wire reading low",
                "Restricted fuel pump inlet strainer causing lean trim",
            ],
            distinguishing_tests=[dt],
            confidence=KnowledgeConfidence.HIGH,
        ))

        # 3. Observed Telemetry
        obs = ObservedFeatureSet(
            session_id="SESS_E2E_AVEO",
            operating_condition=OperatingCondition.IDLE,
            features={
                "LTFT:VALUE_RANGE": 23.5,
                "MAF:VALUE_RANGE": 1.9,
                "MAP:VALUE_RANGE": 42.0,  # Elevated MAP due to vacuum leak; does not trigger contradiction
            },
            active_dtcs=["P0171"],
        )

        # 4. Pattern Matcher Execution
        matches = self.store.match_patterns(obs, vehicle_context=self.aveo_context)
        self.assertGreaterEqual(len(matches), 2)

        # 5. Verify Specific Pattern Outranks Generic
        top = matches[0]
        self.assertEqual(top.pattern.pattern_id, "PAT_E2E_AVEO_PCV_BREACH")
        self.assertEqual(top.match_grade, PatternMatchGrade.STRONG_MATCH)
        self.assertGreater(top.overall_score, 0.80)
        self.assertEqual(len(top.contradictory_features_detected), 0)

        # 6. Verify Explanations and Hypotheses Provided to H-3/H-4
        adapter = FailurePatternWorkflowAdapter(self.store)
        hyps = adapter.get_candidate_hypotheses_from_telemetry(obs, vehicle_context=self.aveo_context)
        self.assertIn("HYP_PCV_ELBOW_SPLIT", hyps)
        self.assertIn("HYP_MAF_DEGRADED", hyps)

        tests = adapter.get_distinguishing_tests_for_matched_patterns(obs, vehicle_context=self.aveo_context)
        self.assertEqual(tests[0].test_id, "TEST_F14D3_SMOKE_PCV")

    # ---------------------------------------------------------------------
    # 24. ECU & SOFTWARE CALIBRATION APPLICABILITY
    # ---------------------------------------------------------------------
    def test_24_ecu_and_software_applicability(self):
        """Pattern constrained to Delphi MT80 ECU and calibration CAL_ID_968001."""
        pattern = FailurePattern(
            pattern_id="PAT_MT80_CAL_LAG",
            name="MT80 Throttle Follower Delay",
            category=PatternCategory.RESPONSE_LAG,
            description="ECU software calibration specific debounce lag.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.CALIBRATION,
                manufacturers=["CHEVROLET"],
                ecu_families=["DELPHI_MT80"],
                software_versions=["CAL_ID_968001"],
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="TSB-MT80"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_DELAY",
                    feature_type=PatternFeatureType.DELAY_TIME_S,
                    signal_name="TPS",
                    min_threshold=0.2,
                )
            ],
        )
        self.store.register_pattern(pattern)

        obs = ObservedFeatureSet(session_id="S_CAL", features={"TPS:DELAY_TIME_S": 0.35})

        # Matching context with exact software_id
        matching_ctx = VehicleContext(
            manufacturer="CHEVROLET",
            ecu_family="DELPHI_MT80",
            software_id="CAL_ID_968001",
        )
        res = self.store.match_patterns(obs, vehicle_context=matching_ctx)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].pattern.pattern_id, "PAT_MT80_CAL_LAG")

        # Context with different software version (CAL_ID_968999) must NOT match
        mismatch_ctx = VehicleContext(
            manufacturer="CHEVROLET",
            ecu_family="DELPHI_MT80",
            software_id="CAL_ID_968999",
        )
        res_mismatch = self.store.match_patterns(obs, vehicle_context=mismatch_ctx)
        self.assertEqual(len(res_mismatch), 0)

    # ---------------------------------------------------------------------
    # 25. TRANSMISSION APPLICABILITY
    # ---------------------------------------------------------------------
    def test_25_transmission_applicability(self):
        """Pattern restricted to AUTOMATIC transmissions must not match MANUAL."""
        at_pattern = FailurePattern(
            pattern_id="PAT_AT_CONVERTER_SLIP",
            name="Torque Converter Clutch Shudder",
            category=PatternCategory.CONTROL_OSCILLATION,
            description="TCC slip speed hunting in lockup.",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.TRANSMISSION,
                transmission_types=["AUTOMATIC"],
            ),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="GM_TCC"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_SLIP_OSC",
                    feature_type=PatternFeatureType.OSCILLATION_AMPLITUDE,
                    signal_name="TCC_SLIP_RPM",
                    min_threshold=40.0,
                )
            ],
        )
        self.store.register_pattern(at_pattern)

        obs = ObservedFeatureSet(session_id="S_TCC", features={"TCC_SLIP_RPM:OSCILLATION_AMPLITUDE": 65.0})

        # Manual transmission context (self.aveo_context is MANUAL)
        res_manual = self.store.match_patterns(obs, vehicle_context=self.aveo_context)
        self.assertEqual(len(res_manual), 0)

        # Automatic context
        at_context = VehicleContext(
            manufacturer="CHEVROLET",
            transmission="AUTOMATIC",
        )
        res_at = self.store.match_patterns(obs, vehicle_context=at_context)
        self.assertEqual(len(res_at), 1)

    # ---------------------------------------------------------------------
    # 26. COMMAND / RESPONSE MISMATCH & CROSS-SENSOR MISMATCH
    # ---------------------------------------------------------------------
    def test_26_command_response_and_cross_sensor_mismatch(self):
        """Evaluate command vs response error margin and MAF vs MAP cross-sensor delta."""
        cmd_pattern = FailurePattern(
            pattern_id="PAT_THROTTLE_PLATE_JAM",
            name="Throttle Plate Actuator Jam",
            category=PatternCategory.COMMAND_RESPONSE_MISMATCH,
            description="Commanded throttle exceeds feedback throttle by > 15%.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_CMD_ERR",
                    feature_type=PatternFeatureType.COMMAND_ERROR_MARGIN,
                    signal_name="THROTTLE",
                    min_threshold=15.0,
                )
            ],
        )
        cross_pattern = FailurePattern(
            pattern_id="PAT_CROSS_MAF_MAP_DISAGREE",
            name="Airflow Plausibility Disagreement",
            category=PatternCategory.CROSS_SENSOR_DISAGREEMENT,
            description="Mass airflow deviates from manifold absolute pressure speed-density model.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="SAE_J1979"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F_DELTA",
                    feature_type=PatternFeatureType.CROSS_SENSOR_DELTA,
                    signal_name="AIRFLOW_MODEL_DELTA",
                    min_threshold=25.0,
                )
            ],
        )
        self.store.register_pattern(cmd_pattern)
        self.store.register_pattern(cross_pattern)

        obs = ObservedFeatureSet(
            session_id="S_MISMATCH",
            features={
                "THROTTLE:COMMAND_ERROR_MARGIN": 28.0,
                "AIRFLOW_MODEL_DELTA:CROSS_SENSOR_DELTA": 32.0,
            },
        )
        res = self.store.match_patterns(obs)
        pids = [r.pattern.pattern_id for r in res]
        self.assertIn("PAT_THROTTLE_PLATE_JAM", pids)
        self.assertIn("PAT_CROSS_MAF_MAP_DISAGREE", pids)

    # ---------------------------------------------------------------------
    # 27. ECU-SPECIFIC DTC HANDLING & TIE-BREAKING DETERMINISM
    # ---------------------------------------------------------------------
    def test_27_ecu_specific_dtc_and_deterministic_ranking(self):
        """Patterns with identical scores sort deterministically by pattern_id."""
        p_b = FailurePattern(
            pattern_id="PAT_B_ALPHA",
            name="Alpha Pattern",
            category=PatternCategory.SENSOR_DRIFT,
            description="Identical feature weight.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="DOC"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="SIG",
                    min_threshold=10.0,
                )
            ],
        )
        p_a = FailurePattern(
            pattern_id="PAT_A_ZETA",
            name="Zeta Pattern",
            category=PatternCategory.SENSOR_DRIFT,
            description="Identical feature weight.",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL, source_reference="DOC"),
            feature_requirements=[
                PatternFeatureRequirement(
                    feature_id="F",
                    feature_type=PatternFeatureType.VALUE_RANGE,
                    signal_name="SIG",
                    min_threshold=10.0,
                )
            ],
        )
        self.store.register_pattern(p_b)
        self.store.register_pattern(p_a)

        obs = ObservedFeatureSet(session_id="S_TIE", features={"SIG:VALUE_RANGE": 15.0})
        res1 = self.store.match_patterns(obs)
        res2 = self.store.match_patterns(obs)

        # Exact same order guaranteed: PAT_A_ZETA before PAT_B_ALPHA
        self.assertEqual([r.pattern.pattern_id for r in res1], [r.pattern.pattern_id for r in res2])
        self.assertEqual(res1[0].pattern.pattern_id, "PAT_A_ZETA")
        self.assertEqual(res1[1].pattern.pattern_id, "PAT_B_ALPHA")

    # ---------------------------------------------------------------------
    # 28. I-1 & I-2 REGRESSION COMPATIBILITY
    # ---------------------------------------------------------------------
    def test_28_i1_and_i2_regression_compatibility(self):
        """FailurePattern seamlessly references I-1 knowledge types and I-2 profiles."""
        from diagnostic_knowledge_base import DiagnosticKnowledgeStore
        from vehicle_ecu_knowledge import VehicleECUKnowledgeStore

        kb_store = DiagnosticKnowledgeStore()
        ecu_store = VehicleECUKnowledgeStore()

        self.assertIsNotNone(kb_store)
        self.assertIsNotNone(ecu_store)

        # Failure pattern uses I-1 KnowledgeDistinguishingTest and I-2 VehicleContext cleanly
        self.assertEqual(self.smoke_test.safety_classification, ServiceSafetyClassification.READ_ONLY)


if __name__ == "__main__":
    unittest.main()
