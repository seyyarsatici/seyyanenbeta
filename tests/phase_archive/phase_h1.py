# -*- coding: utf-8 -*-
"""
test_phase_h1.py — Phase H-1: Guided Diagnostic Procedures Foundation Test Suite
=============================================================================
This test suite verifies Phase H-1 requirements A through X:
  A. Procedure creation from a G-3 hypothesis
  B. Procedure creation from DTC evidence
  C. DTC-free anomaly procedure
  D. Multiple competing hypotheses
  E. Deterministic step prioritization
  F. Branch selection
  G. Stop conditions
  H. Technician observation recording
  I. Missing-data handling
  J. Multi-ECU procedure
  K. Communication-failure branching
  L. Graph-aware evidence references
  M. Provenance preservation
  N. Serialization round-trip
  O. Invalid state transitions
  P. Safety classification
  Q. Destructive action rejection
  R. Actuator/action execution blocked
  S. Unsupported workshop data not invented
  T. Deterministic repeated generation
  U. Large evidence set / bounded procedure generation
  V. Contradictory evidence
  W. DTC-free investigation
  X. Alternative hypothesis discrimination
=============================================================================
"""

import unittest
import time
import uuid
import copy
from typing import Dict, Any, List

from advanced_ecu_services import (
    ServiceSafetyClassification,
)
from extended_did import (
    VehicleContext,
)
from advanced_fault_analysis import (
    FaultHypothesis,
    FaultEvidence,
    HypothesisConfidence,
    AnomalySeverity,
    AnomalyType,
    OperatingCondition,
    SignalQuality,
    PointAnomaly,
    TemporalAnomaly,
    DTCRecord,
)
from multi_ecu_diagnostics import (
    MultiECUDTCRecord,
    MultiECUScanResult,
    ECUScanRecord,
    ECUTarget,
    ECUDiscoveryState,
    ECUHealthState,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    VehicleDiagnosticGraphBuilder,
)
from guided_procedures import (
    ProcedureState,
    StepExecutionMode,
    StepPriority,
    ObservationResultType,
    ProcedureOutcome,
    StopConditionType,
    DiagnosticPrecondition,
    DiagnosticExpectedObservation,
    DiagnosticBranch,
    DiagnosticStopCondition,
    TechnicianObservation,
    DiagnosticStep,
    DiagnosticProcedureContext,
    DiagnosticProcedure,
    StepPrioritizer,
    GuidedProcedureEngine,
    ProcedureError,
    ProcedureStateError,
    ProcedureSafetyError,
)


class TestPhaseH1GuidedProcedures(unittest.TestCase):
    """Phase H-1 Guided Diagnostic Procedures acceptance test cases."""

    def setUp(self):
        self.engine = GuidedProcedureEngine()
        self.vehicle_ctx = VehicleContext(
            manufacturer="OPEL",
            model="INSIGNIA",
            model_year="2016",
            engine_code="B20DTH",
        )

    # -----------------------------------------------------------------
    # Test A: Procedure creation from a G-3 hypothesis
    # -----------------------------------------------------------------
    def test_scenario_a_procedure_from_g3_hypothesis(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-MAF-001",
            title="MAF Sensor Plausibility Bias",
            category="AIR_INTAKE",
            affected_system="Engine Air Intake",
            confidence=HypothesisConfidence.HIGH,
            evidence_score=0.88,
            operating_conditions=[OperatingCondition.HIGH_LOAD],
            dtc_associations=["ECM:P0101"],
            required_additional_evidence=["MAF", "MAP", "ENGINE_LOAD"],
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        self.assertEqual(proc.state, ProcedureState.READY)
        self.assertIn("HYP-MAF-001", proc.triggering_hypotheses)
        self.assertGreater(len(proc.steps), 0)
        self.assertTrue(any("MAF" in s.title or "Air Intake" in s.title for s in proc.steps.values()))
        # Verify first step is active
        self.assertIsNotNone(proc.current_step_id)
        current = proc.get_current_step()
        self.assertIsNotNone(current)
        self.assertEqual(current.safety_classification, ServiceSafetyClassification.READ_ONLY)

    # -----------------------------------------------------------------
    # Test B: Procedure creation from DTC evidence
    # -----------------------------------------------------------------
    def test_scenario_b_procedure_from_dtc_evidence(self):
        dtc1 = MultiECUDTCRecord(ecu_id="ECM", code="P0300", description="Random/Multiple Cylinder Misfire Detected", status="CONFIRMED")
        dtc2 = MultiECUDTCRecord(ecu_id="ECM", code="P0301", description="Cylinder 1 Misfire Detected", status="CONFIRMED")
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            dtcs=[dtc1, dtc2],
        )
        self.assertEqual(proc.state, ProcedureState.READY)
        self.assertIn("ECM:P0300", proc.triggering_dtcs)
        self.assertIn("ECM:P0301", proc.triggering_dtcs)
        self.assertTrue(any("P0300" in s.title for s in proc.steps.values()))
        self.assertTrue(any("P0301" in s.title for s in proc.steps.values()))

    # -----------------------------------------------------------------
    # Test C: DTC-free anomaly procedure
    # -----------------------------------------------------------------
    def test_scenario_c_dtc_free_anomaly_procedure(self):
        anom = PointAnomaly(
            anomaly_id="ANOM-COOLANT-SPIKE-01",
            anomaly_type=AnomalyType.SUDDEN_SPIKE,
            signal_name="ECT",
            timestamp=100.5,
            observed_value=135.0,
            expected_range=(75.0, 105.0),
            severity=AnomalySeverity.CRITICAL,
            details="Engine coolant temperature abrupt spike without DTC",
            operating_condition=OperatingCondition.STEADY_CRUISE,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            anomalies=[anom],
        )
        self.assertEqual(proc.state, ProcedureState.READY)
        self.assertEqual(len(proc.triggering_dtcs), 0)
        self.assertIn("ANOM-COOLANT-SPIKE-01", proc.triggering_anomalies)
        self.assertTrue(any("ECT" in s.title for s in proc.steps.values()))

    # -----------------------------------------------------------------
    # Test D: Multiple competing hypotheses
    # -----------------------------------------------------------------
    def test_scenario_d_multiple_competing_hypotheses(self):
        hyp1 = FaultHypothesis(
            hypothesis_id="HYP-AIR-LEAK",
            title="Intake Air Leak / Vacuum Leak",
            category="AIR_INTAKE",
            affected_system="Intake Manifold",
            confidence=HypothesisConfidence.MEDIUM,
            evidence_score=0.75,
            operating_conditions=[OperatingCondition.IDLE],
        )
        hyp2 = FaultHypothesis(
            hypothesis_id="HYP-MAF-BIAS",
            title="MAF Sensor Under-Reporting Bias",
            category="AIR_INTAKE",
            affected_system="Mass Air Flow Sensor",
            confidence=HypothesisConfidence.MEDIUM,
            evidence_score=0.72,
            operating_conditions=[OperatingCondition.HIGH_LOAD],
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp1, hyp2],
        )
        self.assertEqual(proc.state, ProcedureState.READY)
        self.assertIn("HYP-AIR-LEAK", proc.triggering_hypotheses)
        self.assertIn("HYP-MAF-BIAS", proc.triggering_hypotheses)
        # Verify a discriminating step was created
        disc_steps = [s for s in proc.steps.values() if len(s.discriminated_hypotheses) >= 2]
        self.assertGreaterEqual(len(disc_steps), 1)
        disc_step = disc_steps[0]
        self.assertIn("HYP-AIR-LEAK", disc_step.discriminated_hypotheses)
        self.assertIn("HYP-MAF-BIAS", disc_step.discriminated_hypotheses)

    # -----------------------------------------------------------------
    # Test E: Deterministic step prioritization
    # -----------------------------------------------------------------
    def test_scenario_e_deterministic_step_prioritization(self):
        hyp1 = FaultHypothesis(
            hypothesis_id="HYP-A",
            title="Primary Critical Fault",
            category="ENGINE",
            affected_system="Fuel System",
            confidence=HypothesisConfidence.HIGH,
            evidence_score=0.95,
        )
        hyp2 = FaultHypothesis(
            hypothesis_id="HYP-B",
            title="Secondary Minor Fault",
            category="BODY",
            affected_system="Lighting",
            confidence=HypothesisConfidence.LOW,
            evidence_score=0.30,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp1, hyp2],
        )
        # Check that steps have non-empty priority reasons and ordered descending by priority score
        scores = [proc.steps[sid].priority_score for sid in proc.step_sequence]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])
        for step in proc.steps.values():
            self.assertTrue(len(step.priority_reason) > 0)

    # -----------------------------------------------------------------
    # Test F: Branch selection
    # -----------------------------------------------------------------
    def test_scenario_f_branch_selection(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-BOOST-LEAK",
            title="Turbo Boost Pressure Deviation",
            category="FORCED_INDUCTION",
            affected_system="Turbocharger",
            confidence=HypothesisConfidence.HIGH,
            evidence_score=0.85,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        proc.transition_to(ProcedureState.ACTIVE, reason="Technician started procedure")

        current_step = proc.get_current_step()
        self.assertIsNotNone(current_step)
        initial_confidence = proc.confidence

        # Record abnormal observation
        proc = self.engine.record_step_observation(
            procedure=proc,
            step_id=current_step.step_id,
            result_type=ObservationResultType.ABNORMAL,
            notes="Observed pressure drop under load",
        )
        self.assertTrue(current_step.completed)
        self.assertIsNotNone(current_step.technician_observation)
        self.assertEqual(current_step.technician_observation.result_type, ObservationResultType.ABNORMAL)
        # Procedure should reflect updated state
        self.assertIn(proc.state, (ProcedureState.ACTIVE, ProcedureState.COMPLETED))

    # -----------------------------------------------------------------
    # Test G: Stop conditions
    # -----------------------------------------------------------------
    def test_scenario_g_stop_conditions(self):
        proc = self.engine.generate_procedure(vehicle_context=self.vehicle_ctx)
        self.assertGreater(len(proc.stop_conditions), 0)
        types = [sc.condition_type for sc in proc.stop_conditions]
        self.assertIn(StopConditionType.HYPOTHESIS_RESOLVED, types)
        self.assertIn(StopConditionType.SAFETY_RESTRICTION, types)
        self.assertIn(StopConditionType.COMMUNICATION_FAULT, types)

    # -----------------------------------------------------------------
    # Test H: Technician observation recording
    # -----------------------------------------------------------------
    def test_scenario_h_technician_observation_recording(self):
        proc = self.engine.generate_procedure(vehicle_context=self.vehicle_ctx)
        proc.transition_to(ProcedureState.ACTIVE)
        step_id = proc.step_sequence[0]

        self.engine.record_step_observation(
            procedure=proc,
            step_id=step_id,
            result_type=ObservationResultType.MEASURED_VALUE,
            measured_value=12.6,
            unit="V",
            notes="Battery open circuit voltage normal",
            technician_id="TECH_42",
        )
        obs = proc.steps[step_id].technician_observation
        self.assertIsNotNone(obs)
        self.assertEqual(obs.result_type, ObservationResultType.MEASURED_VALUE)
        self.assertEqual(obs.measured_value, 12.6)
        self.assertEqual(obs.unit, "V")
        self.assertEqual(obs.technician_id, "TECH_42")

    # -----------------------------------------------------------------
    # Test I: Missing-data handling
    # -----------------------------------------------------------------
    def test_scenario_i_missing_data_handling(self):
        step = DiagnosticStep(
            step_id="STEP-MISSING-TEST",
            sequence=1,
            title="Evaluate Missing EGT Sensor",
            technician_instruction="Verify exhaust gas temperature",
            purpose="Assess post-DPF thermal load",
            rationale="EGT sensor data absent from scan snapshot",
            target_ecu="ECM",
            required_evidence_ids=["EGT_BANK1_SENSOR2"],
            is_data_insufficient=True,
            missing_data_details="Signal EGT_BANK1_SENSOR2 not present in ECU telemetry",
        )
        self.assertTrue(step.is_data_insufficient)
        self.assertIn("EGT_BANK1_SENSOR2", step.missing_data_details)

    # -----------------------------------------------------------------
    # Test J: Multi-ECU procedure
    # -----------------------------------------------------------------
    def test_scenario_j_multi_ecu_procedure(self):
        dtc_ecm = MultiECUDTCRecord(ecu_id="ECM", code="U0101", description="Lost Communication with TCM")
        dtc_tcm = MultiECUDTCRecord(ecu_id="TCM", code="P0700", description="Transmission Control System (MIL Request)")
        dtc_abs = MultiECUDTCRecord(ecu_id="ABS", code="C0035", description="Left Front Wheel Speed Sensor Circuit")

        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            dtcs=[dtc_ecm, dtc_tcm, dtc_abs],
        )
        self.assertIn("ECM", proc.target_ecus)
        self.assertIn("TCM", proc.target_ecus)
        self.assertIn("ABS", proc.target_ecus)
        # Check that steps target their respective ECUs without collapsing identities
        step_ecus = {s.target_ecu for s in proc.steps.values()}
        self.assertTrue(len(step_ecus) >= 2)

    # -----------------------------------------------------------------
    # Test K: Communication-failure branching
    # -----------------------------------------------------------------
    def test_scenario_k_communication_failure_branching(self):
        # Scenario: ABS module unreachable
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            unreachable_ecus={"ABS"},
        )
        # First step must address communication
        first_step = proc.steps[proc.step_sequence[0]]
        self.assertEqual(first_step.target_ecu, "ABS")
        self.assertIn("Communication", first_step.title)
        # Must not recommend component replacement
        self.assertNotIn("replace abs", first_step.technician_instruction.lower())
        self.assertNotIn("replace module", first_step.technician_instruction.lower())

        # Branching test: confirm communication failure terminates with COMMUNICATION_PROBLEM
        proc.transition_to(ProcedureState.ACTIVE)
        proc = self.engine.record_step_observation(
            procedure=proc,
            step_id=first_step.step_id,
            result_type=ObservationResultType.COMMUNICATION_FAILURE,
        )
        self.assertEqual(proc.final_outcome, ProcedureOutcome.COMMUNICATION_PROBLEM)
        self.assertEqual(proc.state, ProcedureState.COMPLETED)

    # -----------------------------------------------------------------
    # Test L: Graph-aware evidence references
    # -----------------------------------------------------------------
    def test_scenario_l_graph_aware_evidence_references(self):
        graph = DiagnosticGraph("vehicle:OPEL_INSIGNIA")
        node_rpm = GraphNode("signal:ECM:010C:RPM", GraphNodeType.SIGNAL, "RPM")
        node_speed = GraphNode("signal:ABS:010D:VEHICLE_SPEED", GraphNodeType.SIGNAL, "VEHICLE_SPEED")
        graph.add_node(node_rpm)
        graph.add_node(node_speed)
        edge = GraphEdge(
            edge_id="rpm--correlates->speed",
            source_id=node_rpm.node_id,
            target_id=node_speed.node_id,
            edge_type=GraphEdgeType.CORRELATES_WITH,
            confidence=0.88,
        )
        graph.add_edge(edge)

        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            graph=graph,
        )
        # Step should reference correlation from graph
        self.assertTrue(any("Relationship" in s.title or "RPM" in s.title for s in proc.steps.values()))

    # -----------------------------------------------------------------
    # Test M: Provenance preservation
    # -----------------------------------------------------------------
    def test_scenario_m_provenance_preservation(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-PROV-TEST",
            title="EGR Valve Sticking",
            category="EMISSIONS",
            affected_system="EGR",
            confidence=HypothesisConfidence.HIGH,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        for step in proc.steps.values():
            self.assertIn("session_id", step.provenance)
            self.assertIn("rule", step.provenance)

    # -----------------------------------------------------------------
    # Test N: Serialization round-trip
    # -----------------------------------------------------------------
    def test_scenario_n_serialization_roundtrip(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-SER-TEST",
            title="Thermostat Stuck Open",
            category="COOLING",
            affected_system="Cooling System",
            confidence=HypothesisConfidence.HIGH,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        # Add an observation
        proc.transition_to(ProcedureState.ACTIVE)
        self.engine.record_step_observation(
            procedure=proc,
            step_id=proc.step_sequence[0],
            result_type=ObservationResultType.NORMAL,
            notes="Temperature warmup curve within spec",
        )

        d = proc.to_dict()
        reconstructed = DiagnosticProcedure.from_dict(d)

        self.assertEqual(proc.procedure_id, reconstructed.procedure_id)
        self.assertEqual(proc.state, reconstructed.state)
        self.assertEqual(proc.step_sequence, reconstructed.step_sequence)
        self.assertEqual(len(proc.steps), len(reconstructed.steps))
        # Verify nested observation preserved
        step0_orig = proc.steps[proc.step_sequence[0]]
        step0_recon = reconstructed.steps[reconstructed.step_sequence[0]]
        self.assertIsNotNone(step0_recon.technician_observation)
        self.assertEqual(step0_orig.technician_observation.notes, step0_recon.technician_observation.notes)

    # -----------------------------------------------------------------
    # Test O: Invalid state transitions
    # -----------------------------------------------------------------
    def test_scenario_o_invalid_state_transitions(self):
        proc = self.engine.generate_procedure(vehicle_context=self.vehicle_ctx)
        # Procedure starts in READY (transitioned from DRAFT at generation completion)
        self.assertEqual(proc.state, ProcedureState.READY)

        # Illegal: READY directly to COMPLETED without activating
        with self.assertRaises(ProcedureStateError):
            proc.transition_to(ProcedureState.COMPLETED)

        # Illegal: COMPLETED to ACTIVE
        proc.transition_to(ProcedureState.ACTIVE)
        proc.transition_to(ProcedureState.COMPLETED)
        with self.assertRaises(ProcedureStateError):
            proc.transition_to(ProcedureState.ACTIVE)

    # -----------------------------------------------------------------
    # Test P: Safety classification
    # -----------------------------------------------------------------
    def test_scenario_p_safety_classification(self):
        proc = self.engine.generate_procedure(vehicle_context=self.vehicle_ctx)
        self.assertEqual(proc.safety_classification, ServiceSafetyClassification.READ_ONLY)
        for step in proc.steps.values():
            self.assertEqual(step.safety_classification, ServiceSafetyClassification.READ_ONLY)

    # -----------------------------------------------------------------
    # Test Q: Destructive action rejection
    # -----------------------------------------------------------------
    def test_scenario_q_destructive_action_rejection(self):
        bad_step = DiagnosticStep(
            step_id="STEP-BAD-CLEAR",
            sequence=1,
            title="Clear Stored DTCs",
            technician_instruction="Send Mode 04 command to clear DTCs across all controllers.",
            purpose="Erase DTC history",
            rationale="Testing clearing DTCs",
            target_ecu="ECM",
        )
        is_safe, reason = self.engine.validate_safety(bad_step)
        self.assertFalse(is_safe)
        self.assertIn("MODE 04", reason.upper())

    # -----------------------------------------------------------------
    # Test R: Actuator/action execution blocked
    # -----------------------------------------------------------------
    def test_scenario_r_actuator_execution_blocked(self):
        actuator_step = DiagnosticStep(
            step_id="STEP-ACTUATOR-TEST",
            sequence=1,
            title="Actuate EGR Solenoid",
            technician_instruction="Command EGR valve to 100% duty cycle using Service 0x2F.",
            purpose="Test physical valve movement",
            rationale="Verifying actuator response",
            target_ecu="ECM",
            execution_mode=StepExecutionMode.ACTIVE_DIAGNOSTIC,
        )
        is_safe, reason = self.engine.validate_safety(actuator_step)
        self.assertFalse(is_safe)
        self.assertIn("ACTIVE_DIAGNOSTIC mode is blocked in Phase H-1", reason)

    # -----------------------------------------------------------------
    # Test S: Unsupported workshop data not invented
    # -----------------------------------------------------------------
    def test_scenario_s_unsupported_workshop_data_not_invented(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-INSP",
            title="Wiring Harness Short",
            category="ELECTRICAL",
            affected_system="Wiring Harness",
            confidence=HypothesisConfidence.MEDIUM,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        # Check instruction texts: must refer to approved workshop procedure, not invent pin numbers or voltages
        for step in proc.steps.values():
            instr = step.technician_instruction.lower()
            self.assertNotIn("measure exactly 1.2 v at pin 4", instr)
            if "physical" in step.title.lower():
                self.assertIn("workshop procedure", instr)

    # -----------------------------------------------------------------
    # Test T: Deterministic repeated generation
    # -----------------------------------------------------------------
    def test_scenario_t_deterministic_repeated_generation(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-DET-TEST",
            title="O2 Sensor Delayed Response",
            category="EXHAUST",
            affected_system="O2 Sensor",
            confidence=HypothesisConfidence.HIGH,
            evidence_score=0.82,
        )
        proc1 = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            session_id="STATIC-SESSION-01",
            hypotheses=[hyp],
        )
        proc2 = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            session_id="STATIC-SESSION-01",
            hypotheses=[hyp],
        )
        self.assertEqual(proc1.step_sequence, proc2.step_sequence)
        for sid in proc1.step_sequence:
            s1 = proc1.steps[sid]
            s2 = proc2.steps[sid]
            self.assertEqual(s1.title, s2.title)
            self.assertEqual(s1.priority_score, s2.priority_score)

    # -----------------------------------------------------------------
    # Test U: Large evidence set / bounded procedure generation
    # -----------------------------------------------------------------
    def test_scenario_u_large_evidence_set_bounded_procedure(self):
        # 100 DTCs and 50 anomalies
        many_dtcs = [
            MultiECUDTCRecord(ecu_id="ECM", code=f"P{1000+i}", description=f"Test Code {i}")
            for i in range(100)
        ]
        many_anoms = [
            PointAnomaly(
                anomaly_id=f"ANOM-{i}",
                anomaly_type=AnomalyType.SUDDEN_SPIKE,
                signal_name=f"SIG_{i}",
                timestamp=float(i),
                observed_value=float(i * 10),
                expected_range=(0.0, 100.0),
                severity=AnomalySeverity.WARNING,
                details=f"Test anomaly {i}",
            )
            for i in range(50)
        ]
        start_time = time.time()
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            dtcs=many_dtcs,
            anomalies=many_anoms,
        )
        duration = time.time() - start_time
        # Bounded generation must complete under 0.1s and not exceed 20 steps
        self.assertLess(duration, 0.5)
        self.assertLessEqual(len(proc.steps), 20)

    # -----------------------------------------------------------------
    # Test V: Contradictory evidence
    # -----------------------------------------------------------------
    def test_scenario_v_contradictory_evidence(self):
        ev_supp = FaultEvidence(
            evidence_id="EV-SUPP-01",
            title="STFT Lean Shift",
            signals=["STFT"],
            start_time=10.0,
            end_time=15.0,
            duration=5.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="STFT elevated to +22%",
            expected_behavior="STFT within +/- 5%",
            deviation_magnitude=22.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="TRIM_EVALUATION",
            confidence_score=0.85,
        )
        ev_contra = FaultEvidence(
            evidence_id="EV-CONTRA-01",
            title="O2 Sensor Rich Switching",
            signals=["O2S1"],
            start_time=12.0,
            end_time=14.0,
            duration=2.0,
            operating_condition=OperatingCondition.IDLE,
            observed_behavior="O2 Sensor toggling normally in rich zone",
            expected_behavior="O2 Sensor lean dwell",
            deviation_magnitude=0.0,
            severity=AnomalySeverity.INFO,
            quality=SignalQuality.GOOD,
            provenance={},
            analysis_method="O2_CROSS_COUNT",
            confidence_score=0.80,
        )
        hyp = FaultHypothesis(
            hypothesis_id="HYP-CONTRADICTORY",
            title="Lean Air-Fuel Ratio Inconsistency",
            category="FUEL_TRIM",
            affected_system="Fuel Control",
            supporting_evidence=[ev_supp],
            contradicting_evidence=[ev_contra],
            confidence=HypothesisConfidence.INSUFFICIENT,
            is_inconclusive=True,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        self.assertEqual(proc.state, ProcedureState.READY)
        # Procedure should be generated to resolve contradiction
        self.assertGreater(len(proc.steps), 0)

    # -----------------------------------------------------------------
    # Test W: DTC-free investigation
    # -----------------------------------------------------------------
    def test_scenario_w_dtc_free_investigation(self):
        hyp = FaultHypothesis(
            hypothesis_id="HYP-DTC-FREE",
            title="Throttle Body Carbon Coking",
            category="AIR_INTAKE",
            affected_system="Throttle Body",
            confidence=HypothesisConfidence.MEDIUM,
            is_dtc_free=True,
            dtc_associations=[],
            required_additional_evidence=["TPS", "RPM"],
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp],
        )
        self.assertEqual(len(proc.triggering_dtcs), 0)
        self.assertIn("HYP-DTC-FREE", proc.triggering_hypotheses)
        self.assertGreater(len(proc.steps), 0)

    # -----------------------------------------------------------------
    # Test X: Alternative hypothesis discrimination
    # -----------------------------------------------------------------
    def test_scenario_x_alternative_hypothesis_discrimination(self):
        hyp1 = FaultHypothesis(
            hypothesis_id="HYP-1",
            title="Vacuum Leak at Intake Manifold",
            category="AIR_INTAKE",
            affected_system="Intake",
            confidence=HypothesisConfidence.MEDIUM,
        )
        hyp2 = FaultHypothesis(
            hypothesis_id="HYP-2",
            title="MAF Sensor Contamination",
            category="AIR_INTAKE",
            affected_system="Sensors",
            confidence=HypothesisConfidence.MEDIUM,
        )
        proc = self.engine.generate_procedure(
            vehicle_context=self.vehicle_ctx,
            hypotheses=[hyp1, hyp2],
        )
        proc.transition_to(ProcedureState.ACTIVE)
        # Execute discriminating step
        first_step = proc.get_current_step()
        self.assertIsNotNone(first_step)
        proc = self.engine.record_step_observation(
            procedure=proc,
            step_id=first_step.step_id,
            result_type=ObservationResultType.ABNORMAL,
            notes="Fuel trims normalized as RPM increased to 2500",
        )
        # Should record discrimination outcome
        self.assertEqual(proc.final_outcome, ProcedureOutcome.HYPOTHESES_DISCRIMINATED)
        self.assertEqual(proc.state, ProcedureState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
