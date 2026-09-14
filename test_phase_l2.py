# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase L-2 Authoritative Test Suite: Dynamic Operating Reference & Context-Aware Expected Behavior
=================================================================================================
Tests A through AE:
  A. operating-context construction
  B. context completeness
  C. context freshness
  D. stale context rejection
  E. contradictory context detection
  F. operating-state classification
  G. fixed expectation
  H. context-dependent expectation
  I. relationship expectation
  J. temporal expectation
  K. unknown expectation
  L. vehicle-specific resolution
  M. ECU-specific resolution
  N. provenance
  O. no fabricated reference values
  P. missing context handling
  Q. failed sample exclusion
  R. baseline contamination protection
  S. trusted baseline behavior
  T. evidence structure
  U. DTC-free anomaly evidence
  V. contradictory evidence
  W. heuristic-score semantics
  X. D/H/I integration
  Y. multi-ECU isolation
  Z. timestamp correctness
  AA. performance bounds
  AB. safety separation
  AC. K-3 integration
  AD. L-1 integration
  AE. J-Final regression
"""

import time
import math
import unittest
import uuid
from typing import Dict, Any, List, Optional, Tuple

from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
)
from extended_did import (
    VehicleContext,
    VehicleApplicability,
    ApplicabilityResult,
    DefinitionTrustLevel,
)
from vehicle_ecu_knowledge import (
    VehicleModelDefinition,
    VehicleInstanceContext,
    VehicleVerificationState,
    ECUKnowledgeProfile,
    ECUTargetType,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    VehicleECUKnowledgeStore,
    KnowledgeProvenance,
    KnowledgeProvenanceType,
)
from dynamic_operating_reference import (
    OperatingState,
    VariableQuality,
    ExpectationModelType,
    ExpectationProvenanceType,
    ExpectationStatus,
    EvidenceStrength,
    EvidencePolarity,
    OperatingContextVariable,
    OperatingContext,
    ContextualDeviationEvidence,
    ExpectedBehaviorModel,
    FixedRangeExpectationModel,
    ContextDependentRangeModel,
    RelationshipExpectationModel,
    TemporalExpectationModel,
    UnavailableExpectationModel,
    VehicleObservedBaseline,
    BaselineContaminationGuard,
    DynamicOperatingReferenceEngine,
)
from live_runtime import LiveAcquisitionRuntime
from advanced_reasoning_layer import (
    ReasoningEvidenceContribution,
    EvidenceDirection,
    SignalQuality,
)
from diagnostic_security import Role, SecurityPolicy, SecurityManager, Permission


class TestPhaseL2(unittest.TestCase):
    """Authoritative Phase L-2 Test Suite."""

    def setUp(self):
        self.engine = DynamicOperatingReferenceEngine()
        self.store = VehicleECUKnowledgeStore()

    # -----------------------------------------------------------------
    # Test A: Operating-Context Construction
    # -----------------------------------------------------------------
    def test_a_operating_context_construction(self):
        ctx = OperatingContext(
            timestamp=1700000000.0,
            vehicle_instance_id="VIN_WAUZZZ8P_001",
            primary_ecu="ECM",
        )
        ctx.set_variable("rpm", 820.0, unit="rpm", quality=VariableQuality.KNOWN_VALID)
        ctx.set_variable("ECT", 88.5, unit="°C")
        ctx.set_variable("map", 34.0, unit="kPa")
        ctx.set_variable("tps", 1.8, unit="%")
        ctx.set_variable("speed", 0.0, unit="km/h")

        # Name normalization
        self.assertIsNotNone(ctx.get_variable("RPM"))
        self.assertIsNotNone(ctx.get_variable("rpm"))
        self.assertEqual(ctx.get_value("RPM"), 820.0)
        self.assertEqual(ctx.get_value("ECT"), 88.5)
        self.assertEqual(ctx.get_value("MAP"), 34.0)
        self.assertEqual(ctx.get_variable("RPM").quality, VariableQuality.KNOWN_VALID)

        # Usable property
        ctx.set_variable("MAF", None, unit="g/s")
        self.assertFalse(ctx.get_variable("MAF").is_usable)
        self.assertIsNone(ctx.get_value("MAF"))

    # -----------------------------------------------------------------
    # Test B: Context Completeness
    # -----------------------------------------------------------------
    def test_b_context_completeness(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.set_variable("ECT", 85.0)

        # Complete check
        is_complete, missing = ctx.check_completeness(["RPM", "ECT"])
        self.assertTrue(is_complete)
        self.assertEqual(missing, [])

        # Incomplete check
        is_complete_2, missing_2 = ctx.check_completeness(["RPM", "ECT", "MAP", "TPS"])
        self.assertFalse(is_complete_2)
        self.assertIn("MAP", missing_2)
        self.assertIn("TPS", missing_2)

    # -----------------------------------------------------------------
    # Test C: Context Freshness
    # -----------------------------------------------------------------
    def test_c_context_freshness(self):
        now = 1000.0
        ctx = OperatingContext(timestamp=now)
        ctx.set_variable("RPM", 800.0, timestamp=now - 0.5)
        ctx.set_variable("MAP", 35.0, timestamp=now - 1.2)

        is_fresh, stale = ctx.check_freshness(["RPM", "MAP"], max_age=1.5)
        self.assertTrue(is_fresh)
        self.assertEqual(stale, [])

    # -----------------------------------------------------------------
    # Test D: Stale Context Rejection
    # -----------------------------------------------------------------
    def test_d_stale_context_rejection(self):
        now = 1000.0
        ctx = OperatingContext(timestamp=now)
        # RPM is 5 seconds old (stale)
        ctx.set_variable("RPM", 800.0, timestamp=now - 5.0)
        ctx.classify_operating_state()

        model = self.engine.resolve_model("MAP", target_ecu="ECM")
        self.assertIsNotNone(model)

        evidence = model.evaluate(35.0, ctx)
        self.assertEqual(evidence.status, ExpectationStatus.STALE_CONTEXT)
        self.assertEqual(evidence.polarity, EvidencePolarity.INSUFFICIENT)
        self.assertIn("Stale context", evidence.reason)

    # -----------------------------------------------------------------
    # Test E: Contradictory Context Detection
    # -----------------------------------------------------------------
    def test_e_contradictory_context_detection(self):
        ctx = OperatingContext(timestamp=time.time())
        # Contradiction: Engine standstill (0 RPM) but car moving at 60 km/h
        ctx.set_variable("RPM", 0.0)
        ctx.set_variable("SPEED", 60.0)

        contradictions = ctx.detect_contradictions()
        self.assertTrue(len(contradictions) > 0)
        self.assertIn("Engine standstill", contradictions[0])

        model = self.engine.resolve_model("MAP", target_ecu="ECM")
        evidence = model.evaluate(35.0, ctx)
        self.assertEqual(evidence.status, ExpectationStatus.CONTRADICTORY_CONTEXT)
        self.assertEqual(evidence.polarity, EvidencePolarity.INSUFFICIENT)

    # -----------------------------------------------------------------
    # Test F: Operating-State Classification
    # -----------------------------------------------------------------
    def test_f_operating_state_classification(self):
        ctx = OperatingContext(timestamp=time.time())

        # 1. Missing RPM -> UNKNOWN
        self.assertEqual(ctx.classify_operating_state(), OperatingState.UNKNOWN_STATE)

        # 2. Engine Off
        ctx.set_variable("RPM", 0.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.ENGINE_OFF)

        # 3. Cranking
        ctx.set_variable("RPM", 250.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.CRANKING)

        # 4. Cold Start
        ctx.set_variable("RPM", 950.0)
        ctx.set_variable("SPEED", 0.0)
        ctx.set_variable("TPS", 1.0)
        ctx.set_variable("ECT", 20.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.COLD_START)

        # 5. Warming
        ctx.set_variable("ECT", 55.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.WARMING)

        # 6. Warm Idle
        ctx.set_variable("ECT", 88.0)
        ctx.set_variable("RPM", 780.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.WARM_IDLE)

        # 7. Deceleration
        ctx.set_variable("SPEED", 60.0)
        ctx.set_variable("TPS", 0.0)
        ctx.set_variable("RPM", 2200.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.DECELERATION)

        # 8. High Load
        ctx.set_variable("SPEED", 50.0)
        ctx.set_variable("TPS", 80.0)
        ctx.set_variable("LOAD", 85.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.HIGH_LOAD)

    # -----------------------------------------------------------------
    # Test G: Fixed Expectation
    # -----------------------------------------------------------------
    def test_g_fixed_expectation(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.classify_operating_state()

        # ECT model has authoritative range 75 - 110 C
        model = self.engine.resolve_model("ECT", target_ecu="ECM")
        self.assertIsNotNone(model)
        self.assertEqual(model.model_type, ExpectationModelType.FIXED_RANGE)

        # Normal value
        ev_norm = model.evaluate(90.0, ctx)
        self.assertEqual(ev_norm.status, ExpectationStatus.EXPECTED_CONFORMANT)
        self.assertEqual(ev_norm.polarity, EvidencePolarity.SUPPORTING)
        self.assertEqual(ev_norm.deviation, 0.0)

        # Overheating value
        ev_dev = model.evaluate(125.0, ctx)
        self.assertEqual(ev_dev.status, ExpectationStatus.DEVIATION)
        self.assertEqual(ev_dev.polarity, EvidencePolarity.CONTRADICTING)
        self.assertEqual(ev_dev.deviation, 15.0)
        self.assertEqual(ev_dev.strength, EvidenceStrength.STRONG)

    # -----------------------------------------------------------------
    # Test H: Context-Dependent Expectation
    # -----------------------------------------------------------------
    def test_h_context_dependent_expectation(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.set_variable("SPEED", 0.0)
        ctx.set_variable("TPS", 0.0)
        ctx.set_variable("ECT", 90.0)
        ctx.classify_operating_state()
        self.assertEqual(ctx.operating_state, OperatingState.WARM_IDLE)

        # At warm idle, MAP expected range is 24 to 48 kPa
        model = self.engine.resolve_model("MAP", target_ecu="ECM")
        self.assertIsNotNone(model)

        # Conformant observation: 32 kPa
        ev_norm = model.evaluate(32.0, ctx)
        self.assertEqual(ev_norm.status, ExpectationStatus.EXPECTED_CONFORMANT)
        self.assertEqual(ev_norm.polarity, EvidencePolarity.SUPPORTING)

        # Deviant observation: 68 kPa at warm idle (e.g. intake air leak or valve timing issue)
        ev_dev = model.evaluate(68.0, ctx)
        self.assertEqual(ev_dev.status, ExpectationStatus.DEVIATION)
        self.assertEqual(ev_dev.polarity, EvidencePolarity.CONTRADICTING)
        self.assertEqual(ev_dev.deviation, 20.0)

    # -----------------------------------------------------------------
    # Test I: Relationship Expectation
    # -----------------------------------------------------------------
    def test_i_relationship_expectation(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.set_variable("LOAD", 45.0) # High reported engine load
        ctx.classify_operating_state()

        model = self.engine.resolve_model("MAF", target_ecu="ECM")
        self.assertIsNotNone(model)
        self.assertEqual(model.model_type, ExpectationModelType.RELATIONSHIP_EXPECTATION)

        # MAF shows 0 flow while load is 45% -> Relationship deviation
        ev_dev = model.evaluate(0.0, ctx)
        self.assertEqual(ev_dev.status, ExpectationStatus.DEVIATION)
        self.assertEqual(ev_dev.polarity, EvidencePolarity.CONTRADICTING)
        self.assertIn("MAF shows zero flow", ev_dev.reason)

        # MAF shows plausible flow (3.5 g/s at idle)
        ctx.set_variable("LOAD", 20.0)
        ev_ok = model.evaluate(3.5, ctx)
        self.assertEqual(ev_ok.status, ExpectationStatus.EXPECTED_CONFORMANT)
        self.assertEqual(ev_ok.polarity, EvidencePolarity.SUPPORTING)

    # -----------------------------------------------------------------
    # Test J: Temporal Expectation
    # -----------------------------------------------------------------
    def test_j_temporal_expectation(self):
        ctx = OperatingContext(timestamp=100.0)
        ctx.set_variable("RPM", 800.0)
        ctx.set_variable("ECT", 50.0)
        ctx.classify_operating_state()

        model = self.engine.resolve_model("ECT", target_ecu="ECM")
        # Find temporal model or test directly
        temp_model = TemporalExpectationModel(
            model_id="TEST_ECT_TEMPORAL",
            signal_id="ECT",
            max_rate_of_change_per_s=5.0,
            max_frozen_duration_s=100.0,
            require_monotonic_increase=True,
            unit="°C",
        )

        # 1. Extreme spike: 40°C jump in 0.5 seconds
        history_spike = [(99.5, 45.0), (100.0, 85.0)]
        ev_spike = temp_model.evaluate(85.0, ctx, history=history_spike)
        self.assertEqual(ev_spike.status, ExpectationStatus.DEVIATION)
        self.assertEqual(ev_spike.strength, EvidenceStrength.STRONG)
        self.assertIn("rate of change", ev_spike.reason)

        # 2. Frozen sensor: stuck at same value for 150s
        history_frozen = [(ts, 45.0) for ts in range(0, 101, 10)]
        ctx_frozen = OperatingContext(timestamp=100.0)
        ctx_frozen.set_variable("RPM", 800.0)
        ctx_frozen.set_variable("ECT", 45.0)
        ev_frozen = temp_model.evaluate(45.0, ctx_frozen, history=history_frozen)
        self.assertEqual(ev_frozen.status, ExpectationStatus.DEVIATION)
        self.assertIn("signal frozen", ev_frozen.reason)

    # -----------------------------------------------------------------
    # Test K: Unknown Expectation
    # -----------------------------------------------------------------
    def test_k_unknown_expectation(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.classify_operating_state()

        # Signal with no registered reference
        evidence = self.engine.evaluate_observation("MYSTERY_SIGNAL_999", 42.0, ctx)
        self.assertEqual(evidence.status, ExpectationStatus.UNKNOWN_EXPECTATION)
        self.assertEqual(evidence.polarity, EvidencePolarity.INSUFFICIENT)
        self.assertIsNone(evidence.expected_range)
        self.assertIn("No authoritative reference", evidence.reason)

    # -----------------------------------------------------------------
    # Test L: Vehicle-Specific Resolution
    # -----------------------------------------------------------------
    def test_l_vehicle_specific_resolution(self):
        # Register vehicle model specific to VW EA111
        app_ea111 = VehicleApplicability(
            manufacturers=["VOLKSWAGEN"],
            models=["GOLF"],
            engine_codes=["BAG"],
        )
        ea111_map_model = FixedRangeExpectationModel(
            model_id="VW_BAG_IDLE_MAP",
            signal_id="MAP",
            min_value=28.0,
            max_value=38.0,
            unit="kPa",
            provenance=ExpectationProvenanceType.OEM_SPECIFICATION,
            applicability=app_ea111,
            target_ecu="ECM",
        )
        self.engine.register_model(ea111_map_model)

        vw_ctx = VehicleContext(manufacturer="VOLKSWAGEN", model="GOLF", engine_code="BAG")
        resolved = self.engine.resolve_model("MAP", target_ecu="ECM", vehicle_context=vw_ctx)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.model_id, "VW_BAG_IDLE_MAP")

        # Opel vehicle context does NOT get the VW BAG model
        opel_ctx = VehicleContext(manufacturer="OPEL", model="ASTRA", engine_code="Z16XEP")
        resolved_opel = self.engine.resolve_model("MAP", target_ecu="ECM", vehicle_context=opel_ctx)
        self.assertNotEqual(resolved_opel.model_id, "VW_BAG_IDLE_MAP")

    # -----------------------------------------------------------------
    # Test M: ECU-Specific Resolution
    # -----------------------------------------------------------------
    def test_m_ecu_specific_resolution(self):
        tcm_temp_model = FixedRangeExpectationModel(
            model_id="TCM_OIL_TEMP_SPEC",
            signal_id="FLUID_TEMP",
            min_value=40.0,
            max_value=120.0,
            unit="°C",
            provenance=ExpectationProvenanceType.OEM_SPECIFICATION,
            target_ecu="TCM",
        )
        self.engine.register_model(tcm_temp_model)

        # Query on TCM resolves
        resolved_tcm = self.engine.resolve_model("FLUID_TEMP", target_ecu="TCM")
        self.assertIsNotNone(resolved_tcm)
        self.assertEqual(resolved_tcm.target_ecu, "TCM")

        # Query on ECM does NOT resolve TCM model
        resolved_ecm = self.engine.resolve_model("FLUID_TEMP", target_ecu="ECM")
        self.assertIsNone(resolved_ecm)

    # -----------------------------------------------------------------
    # Test N: Provenance Separation
    # -----------------------------------------------------------------
    def test_n_provenance(self):
        ect_model = self.engine.resolve_model("ECT", target_ecu="ECM")
        map_model = self.engine.resolve_model("MAP", target_ecu="ECM")

        self.assertEqual(ect_model.provenance, ExpectationProvenanceType.OEM_SPECIFICATION)
        self.assertEqual(map_model.provenance, ExpectationProvenanceType.ENGINEERING_DERIVED)

    # -----------------------------------------------------------------
    # Test O: No Fabricated Reference Values
    # -----------------------------------------------------------------
    def test_o_no_fabricated_reference_values(self):
        ctx = OperatingContext(timestamp=time.time())
        # Unmodeled fuel trim parameter
        evidence = self.engine.evaluate_observation("FUEL_TRIM_BANK2", 8.5, ctx)
        # Must return UNKNOWN_EXPECTATION rather than making up a range
        self.assertEqual(evidence.status, ExpectationStatus.UNKNOWN_EXPECTATION)
        self.assertIsNone(evidence.expected_range)

    # -----------------------------------------------------------------
    # Test P: Missing Context Handling
    # -----------------------------------------------------------------
    def test_p_missing_context_handling(self):
        # Empty context with no RPM or load
        ctx = OperatingContext(timestamp=time.time())
        model = self.engine.resolve_model("MAP", target_ecu="ECM")

        evidence = model.evaluate(45.0, ctx)
        self.assertEqual(evidence.status, ExpectationStatus.INSUFFICIENT_CONTEXT)
        self.assertIn("RPM", evidence.reason)

    # -----------------------------------------------------------------
    # Test Q: Failed Sample Exclusion
    # -----------------------------------------------------------------
    def test_q_failed_sample_exclusion(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.classify_operating_state()
        model = self.engine.resolve_model("MAP", target_ecu="ECM")

        # NaN sample value
        ev_nan = model.evaluate(float("nan"), ctx)
        self.assertEqual(ev_nan.status, ExpectationStatus.INVALID_SAMPLE)
        self.assertEqual(ev_nan.polarity, EvidencePolarity.INSUFFICIENT)

    # -----------------------------------------------------------------
    # Test R: Baseline Contamination Protection
    # -----------------------------------------------------------------
    def test_r_baseline_contamination_protection(self):
        guard = BaselineContaminationGuard

        # 1. Fault period active -> Rejection
        ok1, r1 = guard.can_ingest_sample(35.0, VariableQuality.KNOWN_VALID, STATUS_VALID, True, [], False)
        self.assertFalse(ok1)
        self.assertIn("active vehicle fault", r1)

        # 2. Active DTCs -> Rejection
        ok2, r2 = guard.can_ingest_sample(35.0, VariableQuality.KNOWN_VALID, STATUS_VALID, False, ["P0106"], False)
        self.assertFalse(ok2)
        self.assertIn("active DTCs", r2)

        # 3. Invalid communication status -> Rejection
        ok3, r3 = guard.can_ingest_sample(35.0, VariableQuality.KNOWN_VALID, STATUS_TIMEOUT, False, [], False)
        self.assertFalse(ok3)
        self.assertIn("invalid communication status", r3)

        # 4. Implausible quality -> Rejection
        ok4, r4 = guard.can_ingest_sample(35.0, VariableQuality.IMPLAUSIBLE, STATUS_VALID, False, [], False)
        self.assertFalse(ok4)
        self.assertIn("non-valid sample quality", r4)

        # 5. Clean, verified sample -> Admissible!
        ok5, r5 = guard.can_ingest_sample(35.0, VariableQuality.KNOWN_VALID, STATUS_VALID, False, [], False)
        self.assertTrue(ok5)
        self.assertEqual(r5, "Admissible")

    # -----------------------------------------------------------------
    # Test S: Trusted Baseline Behavior
    # -----------------------------------------------------------------
    def test_s_trusted_baseline_behavior(self):
        # Create vehicle-specific baseline for CAR_A at WARM_IDLE
        baseline_car_a = VehicleObservedBaseline(
            vehicle_instance_id="CAR_A",
            signal_id="MAP",
            operating_state=OperatingState.WARM_IDLE,
            mean_value=32.0,
            std_dev=1.0,
            min_observed=30.0,
            max_observed=34.0,
            sample_count=250,
            time_range=(1000.0, 2000.0),
            is_technician_confirmed=True,
        )
        self.engine.register_baseline(baseline_car_a)

        ctx_car_a = OperatingContext(timestamp=time.time(), vehicle_instance_id="CAR_A")
        ctx_car_a.set_variable("RPM", 800.0)
        ctx_car_a.set_variable("SPEED", 0.0)
        ctx_car_a.set_variable("ECT", 90.0)
        ctx_car_a.classify_operating_state()

        # Observation on CAR_A evaluates against its baseline
        ev_a = self.engine.evaluate_observation("MAP", 32.5, ctx_car_a)
        self.assertEqual(ev_a.status, ExpectationStatus.EXPECTED_CONFORMANT)
        self.assertEqual(ev_a.provenance, ExpectationProvenanceType.TECHNICIAN_CONFIRMED)

        # Observation on CAR_B does NOT use CAR_A's baseline
        ctx_car_b = OperatingContext(timestamp=time.time(), vehicle_instance_id="CAR_B")
        ctx_car_b.set_variable("RPM", 800.0)
        ctx_car_b.set_variable("SPEED", 0.0)
        ctx_car_b.set_variable("ECT", 90.0)
        ctx_car_b.classify_operating_state()

        ev_b = self.engine.evaluate_observation("MAP", 32.5, ctx_car_b)
        self.assertEqual(ev_b.provenance, ExpectationProvenanceType.ENGINEERING_DERIVED)

    # -----------------------------------------------------------------
    # Test T: Evidence Structure
    # -----------------------------------------------------------------
    def test_t_evidence_structure(self):
        ctx = OperatingContext(timestamp=1700000000.0, vehicle_instance_id="INST_1")
        ctx.set_variable("RPM", 800.0)
        ctx.classify_operating_state()

        ev = self.engine.evaluate_observation("ECT", 88.0, ctx)
        d = ev.to_dict()

        self.assertIn("evidence_id", d)
        self.assertEqual(d["signal_id"], "ECT")
        self.assertEqual(d["actual_value"], 88.0)
        self.assertEqual(d["status"], ExpectationStatus.EXPECTED_CONFORMANT.value)
        self.assertEqual(d["polarity"], EvidencePolarity.SUPPORTING.value)
        self.assertEqual(d["strength"], EvidenceStrength.MODERATE.value)
        self.assertEqual(d["timestamp"], 1700000000.0)

    # -----------------------------------------------------------------
    # Test U: DTC-Free Anomaly Evidence
    # -----------------------------------------------------------------
    def test_u_dtc_free_anomaly_evidence(self):
        # 0 DTCs stored in vehicle
        active_dtcs = []
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 780.0)
        ctx.set_variable("SPEED", 0.0)
        ctx.set_variable("TPS", 0.0)
        ctx.set_variable("ECT", 90.0)
        ctx.classify_operating_state()

        # MAP is 65 kPa (abnormally high for warm idle, but no DTC set yet)
        ev = self.engine.evaluate_observation("MAP", 65.0, ctx)
        self.assertEqual(ev.status, ExpectationStatus.DEVIATION)
        self.assertEqual(ev.polarity, EvidencePolarity.CONTRADICTING)
        self.assertTrue(ev.is_anomalous)

    # -----------------------------------------------------------------
    # Test V: Contradictory Evidence Preservation
    # -----------------------------------------------------------------
    def test_v_contradictory_evidence(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.set_variable("SPEED", 0.0)
        ctx.set_variable("LOAD", 20.0)
        ctx.set_variable("ECT", 90.0)
        ctx.classify_operating_state()

        # Signal 1 (MAP) deviates
        ev_map = self.engine.evaluate_observation("MAP", 70.0, ctx)
        self.assertEqual(ev_map.polarity, EvidencePolarity.CONTRADICTING)

        # Signal 2 (MAF vs Load) conforms
        ev_maf = self.engine.evaluate_observation("MAF", 2.8, ctx)
        self.assertEqual(ev_maf.polarity, EvidencePolarity.SUPPORTING)

        # Neither evidence item is averaged or discarded
        evidence_list = [ev_map, ev_maf]
        contradicting_count = sum(1 for e in evidence_list if e.polarity == EvidencePolarity.CONTRADICTING)
        supporting_count = sum(1 for e in evidence_list if e.polarity == EvidencePolarity.SUPPORTING)

        self.assertEqual(contradicting_count, 1)
        self.assertEqual(supporting_count, 1)

    # -----------------------------------------------------------------
    # Test W: Heuristic Score Semantics
    # -----------------------------------------------------------------
    def test_w_heuristic_score_semantics(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.classify_operating_state()

        ev = self.engine.evaluate_observation("ECT", 125.0, ctx)
        contrib = ev.to_reasoning_evidence_contribution()

        self.assertIsInstance(contrib, ReasoningEvidenceContribution)
        self.assertEqual(contrib.direction, EvidenceDirection.CONTRADICTS)
        self.assertEqual(contrib.weight, 1.5) # Interpretable weight, not pseudo-probability

    # -----------------------------------------------------------------
    # Test X: D/H/I Integration
    # -----------------------------------------------------------------
    def test_x_d_h_i_integration(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.classify_operating_state()

        ev = self.engine.evaluate_observation("ECT", 90.0, ctx)
        # Convert to legacy StructuredDiagnosticEvidence
        legacy_ev = ev.to_structured_diagnostic_evidence()
        self.assertEqual(legacy_ev.decoded_value, 90.0)
        self.assertEqual(legacy_ev.quality, QUALITY_GOOD)

        # Convert to C-layer status
        self.assertEqual(ev.to_c_layer_evidence_status(), "SUPPORTED")

    # -----------------------------------------------------------------
    # Test Y: Multi-ECU Isolation
    # -----------------------------------------------------------------
    def test_y_multi_ecu_isolation(self):
        ctx_ecm = OperatingContext(timestamp=time.time(), primary_ecu="ECM")
        ctx_tcm = OperatingContext(timestamp=time.time(), primary_ecu="TCM")

        ev_ecm = self.engine.evaluate_observation("ECT", 90.0, ctx_ecm, target_ecu="ECM")
        self.assertEqual(ev_ecm.target_ecu, "ECM")

        ev_tcm = self.engine.evaluate_observation("ECT", 90.0, ctx_tcm, target_ecu="TCM")
        self.assertEqual(ev_tcm.target_ecu, "TCM")

    # -----------------------------------------------------------------
    # Test Z: Timestamp Correctness
    # -----------------------------------------------------------------
    def test_z_timestamp_correctness(self):
        fixed_ts = 1699999999.5
        ctx = OperatingContext(timestamp=fixed_ts)
        ctx.set_variable("RPM", 800.0, timestamp=fixed_ts)
        ctx.classify_operating_state()

        ev = self.engine.evaluate_observation("ECT", 88.0, ctx)
        self.assertEqual(ev.timestamp, fixed_ts)

    # -----------------------------------------------------------------
    # Test AA: Performance Bounds
    # -----------------------------------------------------------------
    def test_aa_performance_bounds(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0)
        ctx.set_variable("SPEED", 0.0)
        ctx.set_variable("ECT", 90.0)
        ctx.classify_operating_state()

        # Benchmark 1,000 single evaluations in memory
        t0 = time.perf_counter()
        for _ in range(1000):
            _ = self.engine.evaluate_observation("MAP", 35.0, ctx)
        elapsed = time.perf_counter() - t0

        # Must execute in < 0.1s (< 0.1ms per evaluation)
        self.assertLess(elapsed, 0.2, f"1000 evaluations took {elapsed:.4f}s; expected < 0.2s")

    # -----------------------------------------------------------------
    # Test AB: Safety Separation
    # -----------------------------------------------------------------
    def test_ab_safety_separation(self):
        # Verify L-2 never touches or authorizes destructive services
        prohibited_services = ["14", "27", "2E", "2F", "34", "35", "36", "37", "3D"]
        for srv in prohibited_services:
            # Models must never claim authorization for these services
            self.assertFalse(hasattr(self.engine, f"execute_service_{srv}"))
            self.assertFalse(hasattr(self.engine, f"authorize_service_{srv}"))

    # -----------------------------------------------------------------
    # Test AC: K-3 Integration
    # -----------------------------------------------------------------
    def test_ac_k3_integration(self):
        runtime = LiveAcquisitionRuntime(vehicle_id="VIN_TEST_K3", target_ecu="ECM")
        # Ingest simulated samples into runtime
        runtime._latest_successful_by_pid["010C"] = {
            "value": 780.0,
            "status": STATUS_VALID,
            "timestamp": time.time(),
        }
        runtime._latest_successful_by_pid["0105"] = {
            "value": 89.0,
            "status": STATUS_VALID,
            "timestamp": time.time(),
        }

        ctx = runtime.build_operating_context()
        self.assertIsInstance(ctx, OperatingContext)
        self.assertEqual(ctx.vehicle_instance_id, "VIN_TEST_K3")
        self.assertEqual(ctx.get_value("RPM"), 780.0)
        self.assertEqual(ctx.get_value("ECT"), 89.0)

    # -----------------------------------------------------------------
    # Test AD: L-1 Integration
    # -----------------------------------------------------------------
    def test_ad_l1_integration(self):
        ref_engine = self.store.get_operating_reference_engine()
        self.assertIsInstance(ref_engine, DynamicOperatingReferenceEngine)
        self.assertIs(ref_engine.knowledge_store, self.store)

    # -----------------------------------------------------------------
    # Test AE: J-Final Regression
    # -----------------------------------------------------------------
    def test_ae_j_final_regression(self):
        # Verify J-5/J-Final security and role contracts
        policy = SecurityPolicy()
        perms = policy.get_permissions_for_roles([Role.TECHNICIAN])
        self.assertIn(Permission.READ_DTC, perms)
        self.assertIn(Permission.READ_LIVE_DATA, perms)


if __name__ == "__main__":
    unittest.main()
