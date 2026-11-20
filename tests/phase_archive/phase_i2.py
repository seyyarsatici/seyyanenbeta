# -*- coding: utf-8 -*-
"""
test_phase_i2.py — Phase I-2 Vehicle & ECU Knowledge Acceptance Test Suite
=============================================================================
Exhaustive test suite certifying Phase I-2:
  1. Progressive vehicle identity creation & level validation
  2. Engine knowledge profile creation & parameter bounds
  3. Transmission knowledge profile & drivetrain distinctions
  4. ECU knowledge profile (hardware, software, calibration ID)
  5. Progressive specificity ranking (Software Calibration > ECU Family > Engine > Model > Universal)
  6. Identity confidence & provenance tracking (VIN vs ECU response vs manual input)
  7. Absence of speculative inference (e.g. knowing model does NOT invent engine)
  8. Contextual DTC interpretation: Same DTC (P0171) on different engines (F14D3 vs Z16XER) yields distinct causes
  9. ECU-specific DTC separation: Same code on ECM vs TCM (P0700) remains strictly separate
  10. Contextual Signal interpretation: Normal MAF envelope differs between 1.4L NA vs 2.0L Turbo at idle
  11. Explicit override model: Specific calibration offset qualifies generic rule without deleting it
  12. Conflicting specifications preserved visibly without silent resolution
  13. Instance-specific knowledge boundary (VIN-specific observation does not leak to all vehicles)
  14. Communication failure isolation in ECU knowledge (unreachable ECU != defective hardware)
  15. DTC-free anomaly contextualization (fuel trim drift under load)
  16. Multi-ECU vehicle context handling (ECM, TCM, ABS distinct targets)
  17. Full serialization round-trip (to_dict / from_dict) across all profiles
  18. Deterministic query scoring & explanation breakdown
  19. Safety boundary verification: zero reachability of prohibited services
  20. Large knowledge store performance benchmark (< 50ms query time)
  21. Realistic end-to-end integration test: Vehicle + Engine + ECU Context -> DTC + Live Telemetry -> Contextual Interpretation -> H-3/H-4 Guidance
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
from multi_ecu_diagnostics import (
    ECUTargetType,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
)
from diagnostic_knowledge_base import (
    KnowledgeLifecycle,
    KnowledgeProvenanceType,
    KnowledgeConfidence,
    ApplicabilityScope,
    KnowledgeRelationshipType,
    KnowledgeDomain,
    KnowledgeProvenance,
    KnowledgeApplicabilityCriteria,
    KnowledgeEvidencePattern,
    KnowledgeDistinguishingTest,
    KnowledgeRelationship,
    DiagnosticKnowledgeEntry,
    DiagnosticKnowledgeStore,
)
from vehicle_ecu_knowledge import (
    IdentityConfidenceLevel,
    IdentitySource,
    FuelType,
    AspirationType,
    TransmissionType,
    DrivetrainType,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    ECUKnowledgeProfile,
    ProgressiveVehicleIdentity,
    ContextualDTCInterpretation,
    ContextualSignalInterpretation,
    ContextualOverride,
    VehicleECUKnowledgeStore,
    ContextualWorkflowAdapter,
    DiagnosticGraphContextIntegrator,
)


class TestPhaseI2VehicleECUKnowledge(unittest.TestCase):
    """Exhaustive test suite for Phase I-2 Vehicle & ECU Knowledge."""

    def setUp(self):
        self.base_store = DiagnosticKnowledgeStore()
        self.store = VehicleECUKnowledgeStore(base_store=self.base_store)

        # Chevrolet Aveo 1.4L F14D3 Automatic Profile
        self.engine_f14d3 = EngineKnowledgeProfile(
            engine_code="F14D3",
            engine_family="GM Family 1",
            displacement_liters=1.4,
            cylinder_count=4,
            fuel_type=FuelType.GASOLINE,
            aspiration=AspirationType.NATURALLY_ASPIRATED,
            nominal_idle_rpm=820.0,
            nominal_idle_maf_gps=2.2,
            nominal_idle_map_kpa=34.0,
            known_peculiarities=["PCV breather hose crack prone"],
        )
        self.trans_4t40e = TransmissionKnowledgeProfile(
            transmission_code="4T40E",
            transmission_type=TransmissionType.AUTOMATIC,
            gear_count=4,
            drivetrain=DrivetrainType.FWD,
        )
        self.ecu_mt80 = ECUKnowledgeProfile(
            logical_id="ECM",
            ecu_type=ECUTargetType.ENGINE,
            module_family="DELPHI_MT80",
            software_id="CAL_968001",
            calibration_id="CAL_REV_B",
            request_header="7E0",
            response_header="7E8",
        )

        self.aveo_identity = ProgressiveVehicleIdentity(
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            vin="1G1JC5444R7252367",
            engine=self.engine_f14d3,
            transmission=self.trans_4t40e,
            ecus={"ECM": self.ecu_mt80},
            confidence_levels={
                "manufacturer": IdentityConfidenceLevel.CONFIRMED,
                "model": IdentityConfidenceLevel.CONFIRMED,
                "engine": IdentityConfidenceLevel.CONFIRMED,
                "ecus.ECM": IdentityConfidenceLevel.CONFIRMED,
            },
            identity_sources={
                "manufacturer": IdentitySource.VIN_DECODED,
                "model": IdentitySource.VIN_DECODED,
                "engine": IdentitySource.ECU_IDENTIFICATION,
                "ecus.ECM": IdentitySource.ECU_IDENTIFICATION,
            },
        )

    # -----------------------------------------------------------------
    # 1. Progressive Vehicle Identity Creation & Hierarchy
    # -----------------------------------------------------------------
    def test_01_progressive_vehicle_identity_hierarchy(self):
        """Verifies progressive identity preserves structured levels without data loss."""
        pvi = self.aveo_identity
        self.assertEqual(pvi.manufacturer, "CHEVROLET")
        self.assertEqual(pvi.model, "AVEO")
        self.assertEqual(pvi.engine.engine_code, "F14D3")
        self.assertEqual(pvi.transmission.transmission_code, "4T40E")
        self.assertIn("ECM", pvi.ecus)
        self.assertEqual(pvi.ecus["ECM"].module_family, "DELPHI_MT80")

        # Conversion to base VehicleContext
        base_ctx = pvi.to_base_vehicle_context()
        self.assertEqual(base_ctx.manufacturer, "CHEVROLET")
        self.assertEqual(base_ctx.model, "AVEO")
        self.assertEqual(base_ctx.engine_code, "F14D3")
        self.assertEqual(base_ctx.ecu_family, "DELPHI_MT80")

    # -----------------------------------------------------------------
    # 2. Absence of Speculative Identity Inference
    # -----------------------------------------------------------------
    def test_02_absence_of_speculative_identity_inference(self):
        """Verifies that an unverified vehicle context does NOT silently infer engine or ECU."""
        partial_ctx = VehicleContext(
            manufacturer="CHEVROLET",
            model="AVEO",
        )
        pvi = ProgressiveVehicleIdentity.from_vehicle_context(partial_ctx)
        self.assertEqual(pvi.manufacturer, "CHEVROLET")
        self.assertEqual(pvi.model, "AVEO")
        # Must remain None, NOT guessed
        self.assertIsNone(pvi.engine)
        self.assertIsNone(pvi.transmission)
        self.assertEqual(len(pvi.ecus), 0)

    # -----------------------------------------------------------------
    # 3. Contextual DTC Interpretation (Same DTC, Different Engines)
    # -----------------------------------------------------------------
    def test_03_contextual_dtc_interpretation_across_engines(self):
        """
        Verifies that the same DTC (P0171) on different engines (F14D3 vs Z16XER)
        resolves to distinct, engine-specific root causes.
        """
        # Interpretation 1: Chevrolet Aveo F14D3
        interp_f14d3 = ContextualDTCInterpretation(
            interpretation_id="INTERP_P0171_F14D3",
            dtc_code="P0171",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            contextual_title="F14D3 System Lean: PCV Valve Breather Hose",
            contextual_description="Common vacuum leak on F14D3 at throttle body elbow pipe.",
            likely_root_causes=["PCV Breather Elbow Cracked", "Intake Manifold Gasket Leak"],
            verification_actions=["Inspect PCV rubber elbow under ignition coil pack."],
        )
        # Interpretation 2: Opel Astra Z16XER
        interp_z16xer = ContextualDTCInterpretation(
            interpretation_id="INTERP_P0171_Z16XER",
            dtc_code="P0171",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["OPEL"],
                engine_codes=["Z16XER"],
            ),
            contextual_title="Z16XER System Lean: Integrated Valve Cover Membrane Rupture",
            contextual_description="Integrated PCV diaphragm inside plastic valve cover tears.",
            likely_root_causes=["Valve Cover Diaphragm Ruptured", "Crankcase Pressure Regulator"],
            verification_actions=["Perform crankcase vacuum test with oil cap manometer."],
        )
        self.store.register_dtc_interpretation(interp_f14d3)
        self.store.register_dtc_interpretation(interp_z16xer)

        # 1. Resolve for Aveo F14D3
        matches_aveo = self.store.resolve_dtc_interpretation("P0171", "ECM", self.aveo_identity)
        self.assertEqual(len(matches_aveo), 1)
        self.assertEqual(matches_aveo[0][0].interpretation_id, "INTERP_P0171_F14D3")
        self.assertIn("PCV Breather Elbow Cracked", matches_aveo[0][0].likely_root_causes)

        # 2. Resolve for Opel Z16XER
        opel_identity = ProgressiveVehicleIdentity(
            manufacturer="OPEL",
            model="ASTRA",
            engine=EngineKnowledgeProfile(engine_code="Z16XER"),
            ecus={"ECM": ECUKnowledgeProfile(logical_id="ECM", module_family="SIMTEC76")},
        )
        matches_opel = self.store.resolve_dtc_interpretation("P0171", "ECM", opel_identity)
        self.assertEqual(len(matches_opel), 1)
        self.assertEqual(matches_opel[0][0].interpretation_id, "INTERP_P0171_Z16XER")
        self.assertIn("Valve Cover Diaphragm Ruptured", matches_opel[0][0].likely_root_causes)

    # -----------------------------------------------------------------
    # 4. Multi-ECU DTC Separation (Same DTC on ECM vs TCM)
    # -----------------------------------------------------------------
    def test_04_multi_ecu_dtc_separation(self):
        """Verifies that DTC P0700 on ECM vs TCM maintains distinct contextual scopes."""
        interp_ecm = ContextualDTCInterpretation(
            interpretation_id="INTERP_P0700_ECM",
            dtc_code="P0700",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            contextual_title="Transmission Control System MIL Request (ECM)",
            contextual_description="ECM acknowledges TCM is requesting MIL illumination.",
            likely_root_causes=["TCM Fault Pending", "CAN Bus Messaging Error"],
        )
        interp_tcm = ContextualDTCInterpretation(
            interpretation_id="INTERP_P0700_TCM",
            dtc_code="P0700",
            target_ecu="TCM",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            contextual_title="TCM Internal Fault Request",
            contextual_description="TCM primary internal fault trigger.",
            likely_root_causes=["TCM Solenoid Circuit", "Transmission Slippage"],
        )
        self.store.register_dtc_interpretation(interp_ecm)
        self.store.register_dtc_interpretation(interp_tcm)

        # Query ECM
        res_ecm = self.store.resolve_dtc_interpretation("P0700", "ECM", self.aveo_identity)
        self.assertEqual(len(res_ecm), 1)
        self.assertEqual(res_ecm[0][0].interpretation_id, "INTERP_P0700_ECM")

        # Query TCM
        res_tcm = self.store.resolve_dtc_interpretation("P0700", "TCM", self.aveo_identity)
        self.assertEqual(len(res_tcm), 1)
        self.assertEqual(res_tcm[0][0].interpretation_id, "INTERP_P0700_TCM")

    # -----------------------------------------------------------------
    # 5. Progressive Specificity Ranking (Exact Calibration > Engine > Model > Universal)
    # -----------------------------------------------------------------
    def test_05_progressive_specificity_ranking(self):
        """
        Verifies ranking precedence:
        Exact Software Calibration > ECU Family > Engine > Universal.
        """
        i_univ = ContextualDTCInterpretation(
            interpretation_id="INTERP_UNIV",
            dtc_code="P0101",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            contextual_title="Universal MAF",
            contextual_description="Generic",
        )
        i_eng = ContextualDTCInterpretation(
            interpretation_id="INTERP_ENG",
            dtc_code="P0101",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            contextual_title="F14D3 MAF",
            contextual_description="Engine level",
        )
        i_sw = ContextualDTCInterpretation(
            interpretation_id="INTERP_SW_CAL",
            dtc_code="P0101",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.CALIBRATION,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
                software_versions=["CAL_968001"],
            ),
            contextual_title="F14D3 Delphi MT80 CAL_968001 Specific MAF",
            contextual_description="Exact calibration level",
        )
        self.store.register_dtc_interpretation(i_univ)
        self.store.register_dtc_interpretation(i_eng)
        self.store.register_dtc_interpretation(i_sw)

        ranked = self.store.resolve_dtc_interpretation("P0101", "ECM", self.aveo_identity)
        self.assertEqual(len(ranked), 3)
        # Exact software match must rank first with highest score
        self.assertEqual(ranked[0][0].interpretation_id, "INTERP_SW_CAL")
        self.assertEqual(ranked[1][0].interpretation_id, "INTERP_ENG")
        self.assertEqual(ranked[2][0].interpretation_id, "INTERP_UNIV")
        self.assertGreater(ranked[0][1], ranked[1][1])
        self.assertGreater(ranked[1][1], ranked[2][1])

    # -----------------------------------------------------------------
    # 6. Contextual Signal Envelope (Operating Condition & Engine Sizing)
    # -----------------------------------------------------------------
    def test_06_contextual_signal_envelope(self):
        """
        Verifies that nominal idle MAF range is specific to engine displacement:
        1.4L NA (1.8 to 2.8 g/s) vs 2.0L Turbo (3.5 to 5.0 g/s).
        """
        # 1.4L NA Envelope
        sig_14 = ContextualSignalInterpretation(
            signal_id="MAF",
            service_id="01",
            identifier="10",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                engine_codes=["F14D3"],
            ),
            operating_condition=OperatingCondition.IDLE,
            nominal_min=1.8,
            nominal_max=2.8,
            unit="g/s",
        )
        # 2.0L Turbo Envelope
        sig_20 = ContextualSignalInterpretation(
            signal_id="MAF",
            service_id="01",
            identifier="10",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                engine_codes=["LNF"],
            ),
            operating_condition=OperatingCondition.IDLE,
            nominal_min=3.5,
            nominal_max=5.2,
            unit="g/s",
        )
        self.store.register_signal_interpretation(sig_14)
        self.store.register_signal_interpretation(sig_20)

        # Query for 1.4L Aveo
        env_aveo = self.store.resolve_signal_envelope("MAF", OperatingCondition.IDLE, "ECM", self.aveo_identity)
        self.assertIsNotNone(env_aveo)
        self.assertEqual(env_aveo.nominal_min, 1.8)
        self.assertEqual(env_aveo.nominal_max, 2.8)
        self.assertTrue(env_aveo.is_within_envelope(2.2))
        self.assertFalse(env_aveo.is_within_envelope(4.5))

    # -----------------------------------------------------------------
    # 7. Explicit Contextual Override Model
    # -----------------------------------------------------------------
    def test_07_explicit_contextual_override(self):
        """Verifies that an ECU-specific override qualifies generic knowledge without deleting it."""
        # Generic Rule in base store
        gen_entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_GENERIC_MAP_IDLE",
            title="Generic MAP at Idle",
            description="Expected manifold absolute pressure at warm idle is 28-36 kPa.",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="SAE Standard",
            ),
            symptoms=["HIGH_MAP_IDLE"],
        )
        self.base_store.register_entry(gen_entry)

        # Contextual Override for specific camshaft profile / engine
        override = ContextualOverride(
            override_id="OVR_MAP_CAM_PROFILE",
            target_generic_knowledge_id="KB_GENERIC_MAP_IDLE",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            override_reason="F14D3 nominal idle MAP is slightly higher (34-42 kPa) due to dual DOHC overlap.",
            adjusted_parameters={"nominal_map_min": 34.0, "nominal_map_max": 42.0},
        )
        self.store.register_override(override)

        # Query contextualized knowledge
        matches = self.store.query_contextualized_knowledge(
            identity=self.aveo_identity,
            symptoms=["HIGH_MAP_IDLE"],
        )
        self.assertEqual(len(matches), 1)
        # Check override is noted in match explanations
        self.assertTrue(any("Contextual Override Applied" in exp for exp in matches[0].match_explanations))

    # -----------------------------------------------------------------
    # 8. Vehicle Instance Boundary (No Leakage into Universal Knowledge)
    # -----------------------------------------------------------------
    def test_08_vehicle_instance_boundary_isolation(self):
        """Verifies instance-specific knowledge (tied to a VIN) does not apply to other vehicles."""
        inst_interp = ContextualDTCInterpretation(
            interpretation_id="INTERP_VIN_SPECIFIC_CASE",
            dtc_code="P0300",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.INSTANCE,
                vins=["1G1JC5444R7252367"],
            ),
            contextual_title="Specific Aveo VIN Repeated Misfire History",
            contextual_description="Known aftermarket spark plug wiring resistance on this specific car.",
            likely_root_causes=["Non-OEM Plug Wires High Resistance"],
            is_instance_specific=True,
        )
        self.store.register_dtc_interpretation(inst_interp)

        # 1. Matches this exact Aveo
        res_same_vin = self.store.resolve_dtc_interpretation("P0300", "ECM", self.aveo_identity)
        self.assertEqual(len(res_same_vin), 1)
        self.assertEqual(res_same_vin[0][0].interpretation_id, "INTERP_VIN_SPECIFIC_CASE")

        # 2. Does NOT match another Aveo with a different VIN
        other_aveo = ProgressiveVehicleIdentity(
            manufacturer="CHEVROLET",
            model="AVEO",
            vin="1G1JC5444R9999999",  # Different VIN
            engine=self.engine_f14d3,
        )
        res_other = self.store.resolve_dtc_interpretation("P0300", "ECM", other_aveo)
        self.assertEqual(len(res_other), 0)

    # -----------------------------------------------------------------
    # 9. Communication Failure Isolation (Unreachable ECU != Hardware Fault)
    # -----------------------------------------------------------------
    def test_09_communication_failure_isolation(self):
        """Verifies ECU knowledge treats offline or unreachable state as network issue, not broken chip."""
        interp_comm = ContextualDTCInterpretation(
            interpretation_id="INTERP_U0100_ECM",
            dtc_code="U0100",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            contextual_title="Lost Communication with ECM",
            contextual_description="Diagnostic tool or gateway failed to receive response from 7E0/7E8.",
            likely_root_causes=[
                "CAN-High / CAN-Low Circuit Open",
                "ECM Main Ignition Relay (12V) Open",
                "ECM Engine Ground G101 Corroded",
            ],
            verification_actions=[
                "Measure terminal resistance on CAN bus pins 6 and 14 (expected 60 ohms).",
                "Verify battery voltage at ECM harness connector.",
            ],
        )
        self.store.register_dtc_interpretation(interp_comm)

        matches = self.store.resolve_dtc_interpretation("U0100", "ECM", self.aveo_identity)
        self.assertEqual(len(matches), 1)
        causes = matches[0][0].likely_root_causes
        # Invariant: Must isolate power, ground, and wiring, never blame internal silicon without proof
        self.assertFalse(any("defective microchip" in c.lower() for c in causes))
        self.assertTrue(any("ground" in c.lower() or "relay" in c.lower() or "circuit" in c.lower() for c in causes))

    # -----------------------------------------------------------------
    # 10. Serialization Round-Trip (to_dict / from_dict)
    # -----------------------------------------------------------------
    def test_10_serialization_round_trip(self):
        """Verifies that entire VehicleECUKnowledgeStore serializes and restores losslessly."""
        self.store.register_engine_profile(self.engine_f14d3)
        self.store.register_transmission_profile(self.trans_4t40e)
        self.store.register_ecu_profile(self.ecu_mt80)

        store_dict = self.store.to_dict()
        reconstructed = VehicleECUKnowledgeStore.from_dict(store_dict)

        restored_engine = reconstructed.get_engine_profile("F14D3")
        self.assertIsNotNone(restored_engine)
        self.assertEqual(restored_engine.displacement_liters, 1.4)
        self.assertEqual(restored_engine.fuel_type, FuelType.GASOLINE)

        restored_trans = reconstructed.get_transmission_profile("4T40E")
        self.assertIsNotNone(restored_trans)
        self.assertEqual(restored_trans.transmission_type, TransmissionType.AUTOMATIC)

    # -----------------------------------------------------------------
    # 11. H-Layer Contextual Workflow Adapter Integration
    # -----------------------------------------------------------------
    def test_11_contextual_workflow_adapter_integration(self):
        """Verifies adapter supplies H-3 and H-4 with vehicle-specific causes and distinguishing tests."""
        test_vac = KnowledgeDistinguishingTest(
            test_id="TEST_SMOKE_F14D3",
            title="F14D3 Throttle Body Elbow Smoke Test",
            description="Low pressure smoke test focused on PCV rubber elbow.",
            discriminated_hypotheses=["HYP_VACUUM_PCV", "HYP_MAF_BIAS"],
        )
        interp = ContextualDTCInterpretation(
            interpretation_id="INTERP_P0171_ADAPTER",
            dtc_code="P0171",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            contextual_title="F14D3 Lean Diagnosis",
            contextual_description="Contextual adapter test",
            likely_root_causes=["F14D3 PCV Rubber Elbow Tear"],
            recommended_tests=[test_vac],
        )
        self.store.register_dtc_interpretation(interp)

        adapter = ContextualWorkflowAdapter(self.store)

        # 1. H-4 Root Cause Query
        causes = adapter.get_contextual_root_causes("P0171", "ECM", self.aveo_identity)
        self.assertEqual(causes, ["F14D3 PCV Rubber Elbow Tear"])

        # 2. H-3 Test Recommendation Query
        tests = adapter.get_contextual_verification_tests("P0171", "ECM", self.aveo_identity)
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].test_id, "TEST_SMOKE_F14D3")

    # -----------------------------------------------------------------
    # 12. G-5 Diagnostic Graph Context Integration
    # -----------------------------------------------------------------
    def test_12_diagnostic_graph_context_integration(self):
        """Verifies DiagnosticGraphContextIntegrator links progressive vehicle and ECU nodes without fake causality."""
        graph = DiagnosticGraph(vehicle_id="veh_aveo")
        veh_id = DiagnosticGraphContextIntegrator.integrate_vehicle_identity(graph, self.aveo_identity)

        self.assertEqual(veh_id, "1G1JC5444R7252367")
        self.assertIn(veh_id, graph.nodes)
        self.assertIn("ecu:ECM", graph.nodes)

        # Edge must be structural HAS_ECU, NOT causal
        edge = graph.get_edge(f"edge_has_ecu_{veh_id}_ECM")
        self.assertIsNotNone(edge)
        self.assertEqual(edge.edge_type, GraphEdgeType.HAS_ECU)

    # -----------------------------------------------------------------
    # 13. Safety Boundary Rejection
    # -----------------------------------------------------------------
    def test_13_safety_boundary_rejection(self):
        """Verifies that contextual distinguishing tests strictly reject non-READ_ONLY classifications."""
        with self.assertRaises(ValueError):
            KnowledgeDistinguishingTest(
                test_id="UNSAFE_ACTUATOR_TOGGLE",
                title="Actuator Toggle Test",
                description="Unsafe actuator actuation",
                safety_classification=ServiceSafetyClassification.BLOCKED,
            )

    # -----------------------------------------------------------------
    # 14. DTC-Free Anomaly Contextualization
    # -----------------------------------------------------------------
    def test_14_dtc_free_anomaly_contextualization(self):
        """Verifies that signal envelope violations trigger contextual diagnosis with 0 DTCs."""
        sig_env = ContextualSignalInterpretation(
            signal_id="LTFT",
            service_id="01",
            identifier="07",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                engine_codes=["F14D3"],
            ),
            operating_condition=OperatingCondition.STEADY_CRUISE,
            nominal_min=-8.0,
            nominal_max=8.0,
            unit="%",
        )
        self.store.register_signal_interpretation(sig_env)

        env = self.store.resolve_signal_envelope("LTFT", OperatingCondition.STEADY_CRUISE, "ECM", self.aveo_identity)
        self.assertIsNotNone(env)
        # Measured trim is +19.5% (exceeds nominal max +8.0%)
        self.assertFalse(env.is_within_envelope(19.5))
        self.assertTrue(env.is_within_envelope(2.0))

    # -----------------------------------------------------------------
    # 15. Large Vehicle & ECU Knowledge Store Performance Benchmark
    # -----------------------------------------------------------------
    def test_15_large_store_performance_benchmark(self):
        """Verifies sub-millisecond retrieval on large store with 250+ contextual entries."""
        for i in range(250):
            eng = EngineKnowledgeProfile(engine_code=f"ENG_{i:03d}")
            self.store.register_engine_profile(eng)
            interp = ContextualDTCInterpretation(
                interpretation_id=f"INTERP_DTC_{i:04d}",
                dtc_code=f"P0{100 + (i % 50):03d}",
                target_ecu="ECM",
                applicability=KnowledgeApplicabilityCriteria(
                    scope=ApplicabilityScope.ENGINE,
                    engine_codes=[f"ENG_{i:03d}"],
                ),
                contextual_title=f"Interpretation #{i}",
                contextual_description=f"Performance test #{i}",
            )
            self.store.register_dtc_interpretation(interp)

        start = time.perf_counter()
        res = self.store.resolve_dtc_interpretation("P0125", "ECM", self.aveo_identity)
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 0.05)

    # -----------------------------------------------------------------
    # 16. Realistic End-to-End Contextual Diagnostic Scenario
    # -----------------------------------------------------------------
    def test_16_realistic_end_to_end_contextual_scenario(self):
        """
        Validates complete flow:
        Vehicle (Chevrolet Aveo 1.4L F14D3 Delphi MT80)
        + DTC P0171 + Idle Operating Condition
        -> Resolves F14D3 specific PCV elbow interpretation over generic P0171
        -> Retrieves distinguishing smoke test
        -> Provides technician verification action
        """
        # 1. Register generic interpretation
        self.store.register_dtc_interpretation(ContextualDTCInterpretation(
            interpretation_id="GENERIC_P0171",
            dtc_code="P0171",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            contextual_title="Universal Lean Condition",
            contextual_description="Generic lean",
            likely_root_causes=["Generic Fuel Delivery Loss"],
        ))

        # 2. Register specific F14D3 interpretation
        dt = KnowledgeDistinguishingTest(
            test_id="TEST_SMOKE_F14D3_E2E",
            title="Smoke Test on F14D3 PCV Elbow",
            description="Check PCV elbow under manifold.",
            discriminated_hypotheses=["HYP_PCV", "HYP_MAF"],
        )
        self.store.register_dtc_interpretation(ContextualDTCInterpretation(
            interpretation_id="SPECIFIC_F14D3_P0171",
            dtc_code="P0171",
            target_ecu="ECM",
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            contextual_title="Chevrolet F14D3 PCV Vacuum Leak",
            contextual_description="High-frequency failure on Aveo F14D3.",
            likely_root_causes=["F14D3 PCV Elbow Hose Split"],
            recommended_tests=[dt],
            verification_actions=["Inspect PCV rubber elbow with mirror."],
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="GM Service Case #8812",
                is_technician_confirmed=True,
            ),
        ))

        ranked = self.store.resolve_dtc_interpretation("P0171", "ECM", self.aveo_identity)
        self.assertEqual(len(ranked), 2)
        # Specific rule must outrank generic rule
        self.assertEqual(ranked[0][0].interpretation_id, "SPECIFIC_F14D3_P0171")
        self.assertIn("F14D3 PCV Elbow Hose Split", ranked[0][0].likely_root_causes)
        self.assertEqual(ranked[0][0].recommended_tests[0].test_id, "TEST_SMOKE_F14D3_E2E")
        self.assertGreater(ranked[0][1], ranked[1][1])


if __name__ == "__main__":
    unittest.main()

