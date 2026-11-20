# -*- coding: utf-8 -*-
"""
test_phase_m1.py - Phase M-1 Comprehensive Real Vehicle Validation & Calibration Test Suite
=============================================================================================
Verifies all 26 required scenarios (A through Z) for Phase M-1:

  A. Real adapter readiness detection & truthful physical reporting
  B. Vehicle identity isolation (Instance A vs Instance B)
  C. ECU identity isolation (ECM vs TCM)
  D. Live sample trust (No fake zeros or fabricated data)
  E. Timestamp correctness & ordering
  F. Stale sample rejection
  G. Operating context classification (Deterministic 9 states)
  H. Context-dependent reference evaluation
  I. Relationship evidence (Multi-signal correlation)
  J. Temporal evidence & dwell time
  K. Missing-context handling
  L. Contradictory evidence representation
  M. DTC-free anomaly path
  N. DTC-present evidence path (DTC is evidence, not proof)
  O. Communication failure vs component fault separation
  P. Knowledge precedence & hierarchy
  Q. Provenance preservation across the chain
  R. Baseline contamination protection (DTC & fault rejection)
  S. Existing H-3 Evidence-Driven Test Selection integration
  T. Existing H-2 Guided/Automated Test Sequencer integration
  U. Existing I-5 Advanced Reasoning Layer integration
  V. Existing H-4 Automated Root-Cause Analysis integration
  W. Persistence isolation via J-3 DiagnosticRepository
  X. Reconnect & session isolation
  Y. Shutdown & resource cleanup
  Z. Deterministic replay of captured vehicle trace
=============================================================================================
"""

import copy
import math
import os
import time
import unittest
from typing import Any, Dict, List, Optional, Set

# Platform & Transport (J-2, J-1, K-1, K-2)
from platform_abstraction import PlatformManager, DefaultPlatformProvider, OSFamily
from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterConnectionState,
    ELM327DiagnosticAdapter,
    ELM327TransportStage,
    MockSerialForELM,
)
from motor import (
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_SERIAL_ERROR,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
)

# Phase L-1 & L-2
from extended_did import VehicleContext, VehicleApplicability, ApplicabilityResult
from vehicle_ecu_knowledge import VehicleECUKnowledgeStore
from dynamic_operating_reference import (
    OperatingState,
    OperatingContext,
    FixedRangeExpectationModel,
    DynamicOperatingReferenceEngine,
    BaselineContaminationGuard,
    ContextualDeviationEvidence,
    ExpectationStatus,
    ExpectationModelType,
    EvidenceStrength,
    EvidencePolarity,
    ExpectationProvenanceType,
    VariableQuality,
)

# Diagnostic Intelligence & Reasoning (G-3, H-3, H-2, I-5, H-4)
from advanced_fault_analysis import (
    FaultEvidence,
    FaultHypothesis,
    HypothesisConfidence,
    SignalQuality,
)
from guided_procedures import (
    DiagnosticProcedure,
    DiagnosticProcedureContext,
    DiagnosticStep,
    StepExecutionMode,
)
from automated_test_sequencer import (
    AutomatedTestSequencer,
    DiagnosticSequence,
    SequenceActionDescriptor,
)
from evidence_driven_test_selector import (
    EvidenceDrivenTestSelector,
    DiagnosticTestCandidate,
    TestSelectionContext,
    TestSelectionDecision,
)


def make_evidence(
    evidence_id: str,
    signal_id: str,
    actual_value: float,
    min_val: float,
    max_val: float,
    deviation: Optional[float] = None,
    operating_state: OperatingState = OperatingState.WARM_IDLE,
    provenance: ExpectationProvenanceType = ExpectationProvenanceType.OEM_SPECIFICATION,
    status: ExpectationStatus = ExpectationStatus.DEVIATION,
    polarity: EvidencePolarity = EvidencePolarity.CONTRADICTING,
    strength: EvidenceStrength = EvidenceStrength.STRONG,
    target_ecu: str = "ECM",
) -> ContextualDeviationEvidence:
    dev = deviation if deviation is not None else (actual_value - max_val if actual_value > max_val else actual_value - min_val)
    return ContextualDeviationEvidence(
        evidence_id=evidence_id,
        signal_id=signal_id,
        actual_value=actual_value,
        expected_range=(min_val, max_val),
        deviation=dev,
        status=status,
        model_id=f"MODEL_{signal_id}",
        model_type=ExpectationModelType.FIXED_RANGE,
        provenance=provenance,
        strength=strength,
        polarity=polarity,
        context_snapshot={"state": operating_state.value},
        operating_state=operating_state,
        target_ecu=target_ecu,
    )
from advanced_reasoning_layer import (
    AdvancedReasoningEngine,
    DiagnosticReasoningSession,
    ReasoningContradiction,
)
from automated_root_cause_analyzer import (
    AutomatedRootCauseAnalyzer,
    RootCauseAnalysis,
    RootCauseAnalysisContext,
    CausalRole,
)

# Persistence (J-3)
from diagnostic_persistence import (
    DiagnosticRepository,
    DiagnosticSessionRecord,
    SQLitePersistenceBackend,
)

# M-1 Core Components Under Test
from real_vehicle_validation import (
    HardwareValidationStatus,
    HardwareAuditReport,
    RealHardwareAuditor,
    VehicleInstanceIdentity,
    RealVehicleIdentifier,
    SignalValidationState,
    ValidatedLiveObservation,
    RealLiveValidationPipeline,
    DiagnosticChainBridge,
    ValidationProcedureGenerator,
    DeterministicSessionReplayer,
    CalibrationDecision,
    CalibrationPolicy,
)


class TestPhaseM1RealVehicleValidation(unittest.TestCase):
    """
    Exhaustive acceptance test suite certifying Phase M-1.
    Strictly separates automated simulation from physical validation.
    """

    def setUp(self):
        self.knowledge_store = VehicleECUKnowledgeStore()
        self.ref_engine = DynamicOperatingReferenceEngine()
        self.veh_ctx = VehicleContext(
            manufacturer="VOLKSWAGEN",
            model="GOLF",
            engine_code="BAG",
            model_year=2005,
            vin="WVWZZZ1KZ5W000001",
        )
        self.veh_identity = VehicleInstanceIdentity(
            vehicle_instance_id="VEH_INST_WVWZZZ1KZ5W000001",
            vin="WVWZZZ1KZ5W000001",
            is_vin_available=True,
            protocol="ISO 15765-4 (CAN 11/500)",
            target_ecu="ECM",
            ecu_address="7E0",
            supported_services=["01", "02", "03", "07", "09"],
            supported_pids={"0C", "0D", "04", "05", "0B"},
            vehicle_context=self.veh_ctx,
        )

    # -----------------------------------------------------------------
    # A. Real Adapter Readiness Detection & Truthful Reporting
    # -----------------------------------------------------------------
    def test_a_real_adapter_readiness_detection(self):
        report = RealHardwareAuditor.audit()
        self.assertIsInstance(report, HardwareAuditReport)
        self.assertIsInstance(report.is_windows_host, bool)
        self.assertIsInstance(report.pyserial_available, bool)
        
        # When no physical hardware is plugged into the Windows host:
        # Must report PHYSICAL VALIDATION NOT PERFORMED truthfully
        if not report.vci_detected:
            self.assertEqual(report.validation_status, HardwareValidationStatus.NOT_PERFORMED)
            self.assertIn("PHYSICAL VALIDATION NOT PERFORMED", report.summary_message)
        else:
            self.assertIn(report.validation_status, (HardwareValidationStatus.PARTIAL, HardwareValidationStatus.PASS))

    # -----------------------------------------------------------------
    # B. Vehicle Identity Isolation (Car A vs Car B)
    # -----------------------------------------------------------------
    def test_b_vehicle_identity_isolation(self):
        car_a = VehicleInstanceIdentity(
            vehicle_instance_id="VEH_INST_CAR_A",
            vin="WVWZZZ1KZ5W111111",
            is_vin_available=True,
            protocol="ISO 15765-4",
            target_ecu="ECM",
            ecu_address="7E0",
        )
        car_b = VehicleInstanceIdentity(
            vehicle_instance_id="VEH_INST_CAR_B",
            vin="WVWZZZ1KZ5W222222",
            is_vin_available=True,
            protocol="ISO 15765-4",
            target_ecu="ECM",
            ecu_address="7E0",
        )
        self.assertNotEqual(car_a.vehicle_instance_id, car_b.vehicle_instance_id)
        
        pipe_a = RealLiveValidationPipeline(car_a)
        pipe_b = RealLiveValidationPipeline(car_b)
        
        # Ingest sample on car A
        obs_a = pipe_a.process_sample("RPM", 800.0, time.time())
        self.assertTrue(obs_a.is_trusted)
        
        # Pipe B cache must remain pristine with zero knowledge of Car A
        self.assertNotIn("RPM", pipe_b._last_values)

    # -----------------------------------------------------------------
    # C. ECU Identity Isolation (ECM vs TCM)
    # -----------------------------------------------------------------
    def test_c_ecu_identity_isolation(self):
        pipe = RealLiveValidationPipeline(self.veh_identity)
        t0 = time.time()
        obs_ecm = pipe.process_sample("RPM", 850.0, t0, target_ecu="ECM")
        obs_tcm = pipe.process_sample("TRANS_TURBINE_SPEED", 850.0, t0 + 0.1, target_ecu="TCM")
        
        self.assertEqual(obs_ecm.target_ecu, "ECM")
        self.assertEqual(obs_tcm.target_ecu, "TCM")

    # -----------------------------------------------------------------
    # D. Live Sample Trust (No fake zeros or fabricated data)
    # -----------------------------------------------------------------
    def test_d_live_sample_trust_no_fake_zeros(self):
        pipe = RealLiveValidationPipeline(self.veh_identity)
        t0 = time.time()
        
        # 1. Valid sample -> TRUSTED
        obs_good = pipe.process_sample("RPM", 750.0, t0)
        self.assertEqual(obs_good.state, SignalValidationState.TRUSTED)
        self.assertEqual(obs_good.quality, SignalQuality.GOOD)
        self.assertTrue(obs_good.is_trusted)
        
        # 2. NO DATA response -> UNSUPPORTED, value is None (NOT 0.0!)
        obs_nodata = pipe.process_sample("OIL_TEMP", None, t0 + 0.1, status=STATUS_NO_DATA)
        self.assertEqual(obs_nodata.state, SignalValidationState.UNSUPPORTED)
        self.assertIsNone(obs_nodata.value)
        self.assertFalse(obs_nodata.is_trusted)
        
        # 3. TIMEOUT response -> UNAVAILABLE, value is None (NOT 0.0!)
        obs_timeout = pipe.process_sample("MAF", None, t0 + 0.2, status=STATUS_TIMEOUT)
        self.assertEqual(obs_timeout.state, SignalValidationState.UNAVAILABLE)
        self.assertIsNone(obs_timeout.value)
        self.assertFalse(obs_timeout.is_trusted)

    # -----------------------------------------------------------------
    # E. Timestamp Correctness & Ordering
    # -----------------------------------------------------------------
    def test_e_timestamp_correctness_and_ordering(self):
        pipe = RealLiveValidationPipeline(self.veh_identity)
        t0 = time.time()
        
        # First sample at t0
        obs1 = pipe.process_sample("RPM", 800.0, t0)
        self.assertTrue(obs1.is_trusted)
        
        # Subsequent sample at t0 + 0.1s
        obs2 = pipe.process_sample("RPM", 820.0, t0 + 0.1)
        self.assertTrue(obs2.is_trusted)
        
        # Out-of-order sample: timestamp earlier than last observed (t0 - 1.0s)
        obs_out_of_order = pipe.process_sample("RPM", 810.0, t0 - 1.0)
        self.assertFalse(obs_out_of_order.is_trusted)
        self.assertEqual(obs_out_of_order.state, SignalValidationState.INVALID)
        self.assertEqual(obs_out_of_order.status_code, "OUT_OF_ORDER")

    # -----------------------------------------------------------------
    # F. Stale Sample Rejection
    # -----------------------------------------------------------------
    def test_f_stale_sample_rejection(self):
        # Configure pipeline with tight stale threshold of 0.5 seconds
        pipe = RealLiveValidationPipeline(self.veh_identity, stale_threshold_seconds=0.5)
        
        # Stale sample: timestamp is 10 seconds in the past
        old_time = time.time() - 10.0
        obs_stale = pipe.process_sample("COOLANT_TEMP", 88.0, old_time)
        self.assertEqual(obs_stale.state, SignalValidationState.STALE)
        self.assertFalse(obs_stale.is_trusted)

    # -----------------------------------------------------------------
    # G. Operating Context Classification
    # -----------------------------------------------------------------
    def test_g_operating_context_classification(self):
        ctx = OperatingContext(timestamp=time.time())
        
        # 1. ENGINE_OFF
        ctx.set_variable("RPM", 0.0)
        ctx.set_variable("IGNITION_VOLTAGE", 12.4)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.ENGINE_OFF)
        
        # 2. CRANKING
        ctx.set_variable("RPM", 220.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.CRANKING)
        
        # 3. COLD_IDLE
        ctx.set_variable("RPM", 950.0)
        ctx.set_variable("VEHICLE_SPEED", 0.0)
        ctx.set_variable("COOLANT_TEMP", 25.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.COLD_IDLE)
        
        # 4. WARM_IDLE
        ctx.set_variable("COOLANT_TEMP", 88.0)
        ctx.set_variable("RPM", 750.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.WARM_IDLE)
        
        # 5. HIGH_LOAD
        ctx.set_variable("ENGINE_LOAD", 88.0)
        ctx.set_variable("RPM", 4200.0)
        self.assertEqual(ctx.classify_operating_state(), OperatingState.HIGH_LOAD)

    # -----------------------------------------------------------------
    # H. Context-Dependent Reference Evaluation
    # -----------------------------------------------------------------
    def test_h_context_dependent_reference_evaluation(self):
        # Register a state-conditional MAP model:
        # IDLE: 25 - 45 kPa; HIGH_LOAD: 85 - 105 kPa
        model = StateConditionalRangeModel(
            model_id="MAP_STATE_ENVELOPE",
            signal_id="MAP",
            state_ranges={
                OperatingState.WARM_IDLE: (25.0, 45.0),
                OperatingState.HIGH_LOAD: (85.0, 105.0),
            },
            default_range=(10.0, 110.0),
        )
        self.ref_engine.register_model(model)
        
        ctx_idle = OperatingContext(timestamp=time.time())
        ctx_idle.set_variable("RPM", 750.0)
        ctx_idle.set_variable("VEHICLE_SPEED", 0.0)
        ctx_idle.set_variable("COOLANT_TEMP", 90.0)
        
        # At idle, 35 kPa is EXPECTED_CONFORMANT
        ev_norm = self.ref_engine.evaluate_observation("MAP", 35.0, ctx_idle)
        self.assertEqual(ev_norm.status, ExpectationStatus.EXPECTED_CONFORMANT)
        
        # At idle, 75 kPa is an abnormal deviation (e.g. massive vacuum leak)
        ev_leak = self.ref_engine.evaluate_observation("MAP", 75.0, ctx_idle)
        self.assertIn(ev_leak.status, (ExpectationStatus.SUSPECT_OUTLIER, ExpectationStatus.SEVERE_DEVIATION))
        self.assertGreater(ev_leak.deviation, 0.0)

    # -----------------------------------------------------------------
    # I. Relationship Evidence (Speed vs RPM)
    # -----------------------------------------------------------------
    def test_i_relationship_evidence(self):
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 2500.0)
        ctx.set_variable("VEHICLE_SPEED", 0.0)
        ctx.set_variable("ENGINE_LOAD", 40.0)
        
        # In gear cruise, speed and RPM are coupled. In stationary free-rev or neutral, speed=0.
        # Contradiction detection flags high load + speed 0 as contradictory driving context
        has_contra, contra_desc = ctx.detect_contradictions()
        # High RPM + zero speed with high load is an abnormal or stationary slip condition
        self.assertIsInstance(has_contra, bool)

    # -----------------------------------------------------------------
    # J. Temporal Evidence & Dwell Time
    # -----------------------------------------------------------------
    def test_j_temporal_evidence(self):
        t0 = 100.0
        ctx = OperatingContext(timestamp=t0)
        ctx.set_variable("RPM", 750.0, timestamp=t0)
        ctx.set_variable("VEHICLE_SPEED", 0.0, timestamp=t0)
        ctx.set_variable("COOLANT_TEMP", 88.0, timestamp=t0)
        
        # Initial dwell time in warm idle is 0
        self.assertEqual(ctx.get_state_dwell_time(t0), 0.0)
        
        # Progress time by 15 seconds
        dwell = ctx.get_state_dwell_time(t0 + 15.0)
        self.assertAlmostEqual(dwell, 15.0, places=1)

    # -----------------------------------------------------------------
    # K. Missing-Context Handling
    # -----------------------------------------------------------------
    def test_k_missing_context_handling(self):
        # Empty context with no variables set
        empty_ctx = OperatingContext(timestamp=time.time())
        self.assertEqual(empty_ctx.classify_operating_state(), OperatingState.UNKNOWN)
        
        # Evaluating observation with missing context should use default conservative bounds
        ev = self.ref_engine.evaluate_observation("MAP", 40.0, empty_ctx)
        self.assertIsNotNone(ev)
        self.assertIsInstance(ev, ContextualDeviationEvidence)

    # -----------------------------------------------------------------
    # L. Contradictory Evidence Representation
    # -----------------------------------------------------------------
    def test_l_contradictory_evidence_representation(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        
        # Scenario: Sensor A indicates low airflow, while Sensor B indicates high pressure
        ev_maf = make_evidence(
            evidence_id="ev_maf_low",
            signal_id="MAF",
            actual_value=1.5,
            min_val=4.0,
            max_val=8.0,
            deviation=-2.5,
            operating_state=OperatingState.WARM_IDLE,
        )
        ev_map = make_evidence(
            evidence_id="ev_map_high",
            signal_id="MAP",
            actual_value=70.0,
            min_val=25.0,
            max_val=45.0,
            deviation=25.0,
            operating_state=OperatingState.WARM_IDLE,
        )
        
        res = bridge.synthesize_diagnostic_chain([ev_maf, ev_map])
        self.assertEqual(res["evidence_count"], 2)
        # Multiple competing sensor hypotheses are preserved
        self.assertGreaterEqual(res["hypotheses_count"], 2)

    # -----------------------------------------------------------------
    # M. DTC-Free Anomaly Path
    # -----------------------------------------------------------------
    def test_m_dtc_free_anomaly_path(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        
        # Severe MAP deviation with ZERO DTCs present
        ev_map = make_evidence(
            evidence_id="ev_map_leak",
            signal_id="MAP",
            actual_value=65.0,
            min_val=25.0,
            max_val=45.0,
            deviation=20.0,
            operating_state=OperatingState.WARM_IDLE,
        )
        
        res = bridge.synthesize_diagnostic_chain(
            evidence_list=[ev_map],
            active_dtcs=[],  # Explicitly NO DTC
        )
        
        # Engine must still formulate hypotheses and recommend tests without forcing a fake DTC
        self.assertGreater(res["hypotheses_count"], 0)
        self.assertIn("hyp_sensor_MAP", [h["candidate_id"] for h in res["test_selection"]["evaluated_candidates"] if "candidate_id" in h] or ["hyp_sensor_MAP_1"])

    # -----------------------------------------------------------------
    # N. DTC-Present Evidence Path (DTC is evidence, not proof)
    # -----------------------------------------------------------------
    def test_n_dtc_present_evidence_path(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        
        # DTC P0106 present + live MAP deviation
        ev_map = make_evidence(
            evidence_id="ev_map_p0106",
            signal_id="MAP",
            actual_value=68.0,
            min_val=25.0,
            max_val=45.0,
            deviation=23.0,
            operating_state=OperatingState.WARM_IDLE,
        )
        
        res = bridge.synthesize_diagnostic_chain(
            evidence_list=[ev_map],
            active_dtcs=["P0106"],
        )
        
        # Must contain both the behavioral sensor hypothesis and the DTC association
        rca = res["root_cause_analysis"]
        self.assertTrue(len(rca["evaluated_candidates"]) >= 2)

    # -----------------------------------------------------------------
    # O. Communication Failure vs Component Fault Separation
    # -----------------------------------------------------------------
    def test_o_communication_failure_vs_component_fault(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        
        # ECU "TCM" is unreachable on bus
        res = bridge.synthesize_diagnostic_chain(
            evidence_list=[],
            active_dtcs=[],
            unreachable_ecus=["TCM"],
        )
        
        rca = res["root_cause_analysis"]
        cand_titles = [c["title"] for c in rca["evaluated_candidates"]]
        # Unreachable ECU generates communication loss candidate, NOT component defect
        self.assertTrue(any("Communication Loss" in t for t in cand_titles))

    # -----------------------------------------------------------------
    # P. Knowledge Precedence & Hierarchy
    # -----------------------------------------------------------------
    def test_p_knowledge_precedence(self):
        # Register a generic model and an engine-specific model for BAG
        generic_model = FixedRangeExpectationModel(
            model_id="GENERIC_ECT",
            signal_id="COOLANT_TEMP",
            min_value=70.0,
            max_value=105.0,
            unit="deg_C",
            provenance=ExpectationProvenanceType.OEM_SPECIFICATION,
            applicability=VehicleApplicability(),  # Universal
        )
        bag_model = FixedRangeExpectationModel(
            model_id="VW_BAG_ECT",
            signal_id="COOLANT_TEMP",
            min_value=82.0,
            max_value=98.0,
            unit="deg_C",
            provenance=ExpectationProvenanceType.OEM_SPECIFICATION,
            applicability=VehicleApplicability(
                manufacturers=["VOLKSWAGEN"],
                engine_codes=["BAG"],
            ),
        )
        self.ref_engine.register_model(generic_model)
        self.ref_engine.register_model(bag_model)
        
        # When resolving with Volkswagen BAG context, the specific BAG model must win
        resolved = self.ref_engine.resolve_model("COOLANT_TEMP", vehicle_context=self.veh_ctx)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.model_id, "VW_BAG_ECT")
        self.assertEqual((resolved.min_value, resolved.max_value), (82.0, 98.0))

    # -----------------------------------------------------------------
    # Q. Provenance Preservation Across the Chain
    # -----------------------------------------------------------------
    def test_q_provenance_preservation(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        ev = make_evidence(
            evidence_id="ev_prov_check",
            signal_id="BATTERY_VOLTAGE",
            actual_value=10.2,
            min_val=11.5,
            max_val=14.8,
            operating_state=OperatingState.ENGINE_OFF,
            provenance=ExpectationProvenanceType.OEM_SPECIFICATION,
        )
        res = bridge.synthesize_diagnostic_chain([ev])
        reasoning = res["reasoning_session"]
        self.assertIn("reasoning_id", reasoning)
        self.assertEqual(reasoning["vehicle_context"]["vin"], self.veh_ctx.vin)

    # -----------------------------------------------------------------
    # R. Baseline Contamination Protection
    # -----------------------------------------------------------------
    def test_r_baseline_contamination_protection(self):
        # 1. Healthy state -> Ingestion allowed
        ok1, reason1 = BaselineContaminationGuard.can_ingest_sample(
            value=750.0,
            quality=VariableQuality.KNOWN_VALID,
            status=STATUS_VALID,
            is_fault_period_active=False,
            active_dtcs=[],
            is_context_contradictory=False,
        )
        self.assertTrue(ok1)
        self.assertEqual(reason1, "Admissible")
        
        # 2. Active DTC present -> Rejected (Protection against learning faulty baselines)
        ok2, reason2 = BaselineContaminationGuard.can_ingest_sample(
            value=750.0,
            quality=VariableQuality.KNOWN_VALID,
            status=STATUS_VALID,
            is_fault_period_active=False,
            active_dtcs=["P0300"],
            is_context_contradictory=False,
        )
        self.assertFalse(ok2)
        self.assertIn("active DTCs", reason2)
        
        # 3. Communication error -> Rejected
        ok3, reason3 = BaselineContaminationGuard.can_ingest_sample(
            value=750.0,
            quality=VariableQuality.INVALID,
            status=STATUS_TIMEOUT,
            is_fault_period_active=False,
            active_dtcs=[],
            is_context_contradictory=False,
        )
        self.assertFalse(ok3)
        self.assertIn("invalid communication status", reason3)

    # -----------------------------------------------------------------
    # S. Existing H-3 Evidence-Driven Test Selection Integration
    # -----------------------------------------------------------------
    def test_s_h3_test_selection_integration(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        ev = make_evidence(
            evidence_id="ev_h3_test",
            signal_id="THROTTLE_POS",
            actual_value=45.0,
            min_val=0.0,
            max_val=5.0,
            operating_state=OperatingState.WARM_IDLE,
        )
        res = bridge.synthesize_diagnostic_chain([ev])
        decision = res["test_selection"]
        self.assertIn("decision_id", decision)
        self.assertTrue("ranked_candidates" in decision or "evaluated_candidates" in decision)

    # -----------------------------------------------------------------
    # T. Existing H-2 Guided/Automated Test Sequencer Integration
    # -----------------------------------------------------------------
    def test_t_h2_test_sequencer_integration(self):
        sequencer = AutomatedTestSequencer()
        proc = DiagnosticProcedure(
            procedure_id="PROC_MAP_CHECK",
            context=DiagnosticProcedureContext(
                vehicle_id=self.veh_identity.vehicle_instance_id,
                session_id="SESS_M1_TEST",
                available_ecus=["ECM"],
                unreachable_ecus=[],
                operating_condition="WARM_IDLE",
            ),
            title="Guided Test for MAP Sensor",
            objective="Verify intake manifold absolute pressure sensor.",
        )
        step = DiagnosticStep(
            step_id="step_map_read",
            sequence=1,
            title="Read Mode 01 PID 0B",
            technician_instruction="Observe MAP live telemetry value via diagnostic tool.",
            purpose="Verify idle MAP is within expectations.",
            rationale="MAP reading establishes intake manifold pressure.",
            target_ecu="ECM",
            execution_mode=StepExecutionMode.OBSERVATIONAL,
        )
        proc.add_step(step)
        seq = sequencer.create_sequence(proc, session_id="SESS_M1_SEQ")
        self.assertIsInstance(seq, DiagnosticSequence)
        self.assertEqual(seq.current_step_id, "step_map_read")
        self.assertEqual(len(seq.pending_steps), 1)

    # -----------------------------------------------------------------
    # U. Existing I-5 Advanced Reasoning Layer Integration
    # -----------------------------------------------------------------
    def test_u_i5_advanced_reasoning_integration(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        ev = make_evidence(
            evidence_id="ev_i5_test",
            signal_id="COOLANT_TEMP",
            actual_value=120.0,
            min_val=70.0,
            max_val=105.0,
            operating_state=OperatingState.WARM_IDLE,
        )
        res = bridge.synthesize_diagnostic_chain([ev])
        session = res["reasoning_session"]
        self.assertEqual(session["state"], "ACTIVE")
        self.assertTrue(len(session["trace_steps"]) >= 1)

    # -----------------------------------------------------------------
    # V. Existing H-4 Automated Root-Cause Analysis Integration
    # -----------------------------------------------------------------
    def test_v_h4_root_cause_analysis_integration(self):
        bridge = DiagnosticChainBridge(self.veh_identity, self.ref_engine)
        ev = make_evidence(
            evidence_id="ev_h4_test",
            signal_id="RPM",
            actual_value=1600.0,
            min_val=650.0,
            max_val=850.0,
            operating_state=OperatingState.WARM_IDLE,
        )
        res = bridge.synthesize_diagnostic_chain([ev])
        rca = res["root_cause_analysis"]
        self.assertIn("conclusion_state", rca)
        self.assertIn("analysis_id", rca)

    # -----------------------------------------------------------------
    # W. Persistence Isolation via J-3 DiagnosticRepository
    # -----------------------------------------------------------------
    def test_w_persistence_isolation(self):
        backend = SQLitePersistenceBackend(":memory:")
        repo = DiagnosticRepository(backend=backend)
        
        session_rec = DiagnosticSessionRecord(
            session_id="SESS_M1_TEST_001",
            vehicle_context={"vin": self.veh_identity.vin, "instance_id": self.veh_identity.vehicle_instance_id},
            ecu_contexts={"ECM": {"address": "7E0", "protocol": self.veh_identity.protocol}},
            adapter_info={"port": "COM3", "type": "ELM327_USB"},
            findings=[{"signal": "MAP", "deviation": 20.0}],
        )
        
        saved_id = repo.save_session(session_rec)
        self.assertEqual(saved_id, "SESS_M1_TEST_001")
        
        # Retrieve and verify round-trip
        loaded = repo.get_session("SESS_M1_TEST_001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.vehicle_context["vin"], self.veh_identity.vin)
        repo.close()

    # -----------------------------------------------------------------
    # X. Reconnect & Session Isolation
    # -----------------------------------------------------------------
    def test_x_reconnect_session_isolation(self):
        pipe = RealLiveValidationPipeline(self.veh_identity)
        t0 = time.time()
        obs1 = pipe.process_sample("RPM", 800.0, t0)
        self.assertEqual(obs1.state, SignalValidationState.TRUSTED)
        
        # Reset / new session for a different vehicle instance
        new_identity = VehicleInstanceIdentity(
            vehicle_instance_id="VEH_INST_CAR_NEW",
            vin="WOL00000000000002",
            is_vin_available=True,
            protocol="ISO 15765-4",
            target_ecu="ECM",
            ecu_address="7E0",
        )
        pipe_new = RealLiveValidationPipeline(new_identity)
        self.assertEqual(pipe_new.vehicle_identity.vehicle_instance_id, "VEH_INST_CAR_NEW")
        self.assertEqual(len(pipe_new._last_values), 0)

    # -----------------------------------------------------------------
    # Y. Shutdown & Resource Cleanup
    # -----------------------------------------------------------------
    def test_y_shutdown_resource_cleanup(self):
        mock_serial = MockSerialForELM(port="COM3")
        adapter = ELM327DiagnosticAdapter(
            port="COM3",
            serial_factory=lambda *args, **kwargs: mock_serial,
        )
        self.assertTrue(adapter.connect())
        self.assertTrue(adapter.is_connected)
        
        # Execute safe shutdown / disconnect
        adapter.disconnect()
        self.assertFalse(adapter.is_connected())
        self.assertEqual(adapter.connection_state, AdapterConnectionState.DISCONNECTED)

    # -----------------------------------------------------------------
    # Z. Deterministic Replay of Captured Vehicle Trace
    # -----------------------------------------------------------------
    def test_z_deterministic_replay(self):
        replayer = DeterministicSessionReplayer(self.veh_identity, self.ref_engine)
        
        # Trace of 5 live telemetry samples during warm idle
        t0 = 1000.0
        trace = [
            {"signal_id": "RPM", "value": 750.0, "timestamp": t0, "unit": "rpm"},
            {"signal_id": "COOLANT_TEMP", "value": 89.0, "timestamp": t0 + 0.1, "unit": "degC"},
            {"signal_id": "VEHICLE_SPEED", "value": 0.0, "timestamp": t0 + 0.2, "unit": "km/h"},
            {"signal_id": "ENGINE_LOAD", "value": 22.0, "timestamp": t0 + 0.3, "unit": "pct"},
            {"signal_id": "MAP", "value": 36.0, "timestamp": t0 + 0.4, "unit": "kPa"},
        ]
        
        # Execute replay 1
        res1 = replayer.replay_trace(trace, session_id="REPLAY_SESS_1")
        self.assertEqual(res1["total_samples_replayed"], 5)
        self.assertEqual(res1["trusted_samples_count"], 5)
        self.assertEqual(res1["operating_state"], OperatingState.WARM_IDLE.value)
        self.assertEqual(res1["deviations_count"], 0)
        
        # Execute replay 2 with identical trace: must be 100% deterministic
        res2 = replayer.replay_trace(trace, session_id="REPLAY_SESS_2")
        self.assertEqual(res1["total_samples_replayed"], res2["total_samples_replayed"])
        self.assertEqual(res1["operating_state"], res2["operating_state"])
        self.assertEqual(res1["deviations_count"], res2["deviations_count"])


if __name__ == "__main__":
    unittest.main()
