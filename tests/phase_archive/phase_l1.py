# -*- coding: utf-8 -*-
"""
test_phase_l1.py - Comprehensive Validation Suite for Phase L-1
=============================================================================
Validates Phase L-1: Vehicle and ECU Knowledge Foundation in Seyyanen.

Tests covered:
  A. Vehicle model creation
  B. Vehicle instance identity separation
  C. Unknown vehicle handling
  D. Partial vehicle identity
  E. Verified vehicle context
  F. ECU identity creation
  G. Multi-ECU separation
  H. ECU-specific namespace (ECM:1640 vs TCM:1640)
  I. Generic vs ECU-specific definition resolution
  J. Exact vehicle-specific precedence
  K. Deterministic resolution
  L. Conflicting knowledge sources (KNOWLEDGE_CONFLICT)
  M. Provenance preservation
  N. Unknown definition behavior
  O. Identifier unit/scaling representation
  P. No double-scaling verification
  Q. Protocol/transport separation
  R. Historical versioning
  S. J-3 persistence integration
  T. Vehicle identity persistence
  U. ECU identity persistence
  V. D/H/I context integration
  W. Safety separation (read-only enforcement)
  X. Regression against K-1 / K-2 / K-3
  Y. Relevant J-Final regressions
  Z. Relevant C->I pipeline regressions
=============================================================================
"""

import copy
import struct
import time
import unittest
import uuid
from typing import Any, Dict, List, Optional

from vehicle_ecu_knowledge import (
    VehicleModelDefinition,
    VehicleInstanceContext,
    VehicleVerificationState,
    ResolutionStatus,
    ResolutionResult,
    DiagnosticIdentifierKnowledge,
    DiagnosticIdentifierDefinition,
    KnowledgeConflictRecord,
    VehicleECUKnowledgeStore,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    ECUKnowledgeProfile,
    ProgressiveVehicleIdentity,
    IdentityConfidenceLevel,
    IdentitySource,
    FuelType,
    AspirationType,
    TransmissionType,
    DrivetrainType,
    ContextualWorkflowAdapter,
)
from extended_did import (
    VehicleContext,
    VehicleApplicability,
    ApplicabilityResult,
    DefinitionTrustLevel,
    IdentifierNamespace,
    DataType,
    ByteOrder,
    DiagnosticDataDefinition,
    FieldDefinition,
)
from multi_ecu_diagnostics import (
    ECUTarget,
    ECUTargetType,
    ECUDiscoveryState,
    ECUCapabilityState,
    ECUHealthState,
    MultiECUVehicleContext,
)
from diagnostic_knowledge_base import (
    KnowledgeProvenance,
    KnowledgeProvenanceType,
    KnowledgeConfidence,
)
from diagnostic_persistence import (
    DiagnosticRepository,
    SQLitePersistenceBackend,
)
from diagnostic_security import (
    Role,
    Permission,
    Principal,
    AuthorizationContext,
    SecurityManager,
)


class TestPhaseL1VehicleECUKnowledge(unittest.TestCase):
    """Authoritative test suite for Phase L-1 Vehicle and ECU Knowledge Foundation."""

    def setUp(self):
        self.store = VehicleECUKnowledgeStore()

    # -----------------------------------------------------------------
    # Test A: Vehicle Model Creation
    # -----------------------------------------------------------------
    def test_a_vehicle_model_creation(self):
        engine = EngineKnowledgeProfile(
            engine_code="BAG",
            engine_family="EA111",
            displacement_liters=1.6,
            cylinder_count=4,
            fuel_type=FuelType.GASOLINE,
            aspiration=AspirationType.NATURALLY_ASPIRATED,
            nominal_idle_rpm=720.0,
        )
        trans = TransmissionKnowledgeProfile(
            transmission_code="MQ250",
            transmission_type=TransmissionType.MANUAL,
            gear_count=6,
            drivetrain=DrivetrainType.FWD,
        )
        ecm = ECUKnowledgeProfile(
            logical_id="ECM",
            ecu_type=ECUTargetType.ENGINE,
            module_family="BOSCH_MED9.5.10",
            request_header="7E0",
            response_header="7E8",
            protocol="ISO_15765_4_CAN_11BIT",
        )
        model = VehicleModelDefinition(
            model_id="VW_GOLF_V_16_FSI",
            make="Volkswagen",
            model="Golf",
            generation="V",
            platform="PQ35",
            model_years=[2003, 2004, 2005, 2006, 2007, 2008],
            market_region="EUROPE",
            engine_code="BAG",
            engine=engine,
            transmission=trans,
            expected_ecus={"ECM": ecm},
        )
        self.store.register_vehicle_model(model)
        retrieved = self.store.get_vehicle_model("VW_GOLF_V_16_FSI")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.make, "Volkswagen")
        self.assertEqual(retrieved.model, "Golf")
        self.assertEqual(retrieved.engine.engine_code, "BAG")
        self.assertIn(2005, retrieved.model_years)
        # Verify serialization roundtrip
        m_dict = model.to_dict()
        reconstructed = VehicleModelDefinition.from_dict(m_dict)
        self.assertEqual(reconstructed.model_id, model.model_id)
        self.assertEqual(reconstructed.expected_ecus["ECM"].module_family, "BOSCH_MED9.5.10")

    # -----------------------------------------------------------------
    # Test B: Vehicle Instance Identity Separation
    # -----------------------------------------------------------------
    def test_b_vehicle_instance_identity_separation(self):
        inst_1 = VehicleInstanceContext(
            instance_id="inst_car_alpha",
            vin="WVWZZZ1KZ6P111111",
            model_definition_id="VW_GOLF_V_16_FSI",
            technician_confirmations={"air_filter_replaced": True},
        )
        inst_2 = VehicleInstanceContext(
            instance_id="inst_car_beta",
            vin="WVWZZZ1KZ6P222222",
            model_definition_id="VW_GOLF_V_16_FSI",
            technician_confirmations={"timing_chain_checked": True},
        )
        self.store.register_vehicle_instance(inst_1)
        self.store.register_vehicle_instance(inst_2)

        # Confirm strict separation: two cars of same model do not share identity
        ret_1 = self.store.get_vehicle_instance("inst_car_alpha")
        ret_2 = self.store.get_vehicle_instance("inst_car_beta")
        self.assertNotEqual(ret_1.instance_id, ret_2.instance_id)
        self.assertNotEqual(ret_1.vin, ret_2.vin)
        self.assertIn("air_filter_replaced", ret_1.technician_confirmations)
        self.assertNotIn("air_filter_replaced", ret_2.technician_confirmations)

    # -----------------------------------------------------------------
    # Test C: Unknown Vehicle Handling
    # -----------------------------------------------------------------
    def test_c_unknown_vehicle_handling(self):
        inst = VehicleInstanceContext(instance_id="inst_empty")
        self.assertEqual(inst.verification_state, VehicleVerificationState.UNKNOWN)
        self.assertIsNone(inst.vin)
        self.assertIsNone(inst.model_definition_id)
        self.assertEqual(len(inst.observed_ecus), 0)

    # -----------------------------------------------------------------
    # Test D: Partial Vehicle Identity
    # -----------------------------------------------------------------
    def test_d_partial_vehicle_identity(self):
        inst = VehicleInstanceContext(instance_id="inst_partial")
        # Observation of bus broadcast headers only
        state = inst.update_evidence(
            evidence_type="broadcast_headers",
            value=["7E8", "7E9"],
            source=IdentitySource.BROADCAST_HEADER,
            confidence=IdentityConfidenceLevel.INFERRED,
        )
        self.assertEqual(state, VehicleVerificationState.PARTIAL)
        self.assertEqual(inst.verification_state, VehicleVerificationState.PARTIAL)

    # -----------------------------------------------------------------
    # Test E: Verified Vehicle Context
    # -----------------------------------------------------------------
    def test_e_verified_vehicle_context(self):
        inst = VehicleInstanceContext(instance_id="inst_verified")
        inst.update_evidence(
            evidence_type="vin",
            value="KL1TD56678B123456",
            source=IdentitySource.VIN_DECODED,
            confidence=IdentityConfidenceLevel.CONFIRMED,
        )
        inst.update_evidence(
            evidence_type="ecu_calibration",
            value="CAL_96800112",
            source=IdentitySource.ECU_IDENTIFICATION,
            confidence=IdentityConfidenceLevel.CONFIRMED,
        )
        self.assertEqual(inst.verification_state, VehicleVerificationState.VERIFIED)

    # -----------------------------------------------------------------
    # Test F: ECU Identity Creation
    # -----------------------------------------------------------------
    def test_f_ecu_identity_creation(self):
        ecu = ECUKnowledgeProfile(
            logical_id="ECM",
            ecu_type=ECUTargetType.ENGINE,
            module_family="DELPHI_MT80",
            hardware_id="HW_25181234",
            software_id="SW_28019455",
            request_header="7E0",
            response_header="7E8",
            protocol="ISO_15765_4_CAN_11BIT",
            supported_services={"01", "09", "22"},
        )
        self.store.register_ecu_profile(ecu)
        self.assertEqual(ecu.logical_id, "ECM")
        self.assertEqual(ecu.request_header, "7E0")
        self.assertIn("22", ecu.supported_services)

    # -----------------------------------------------------------------
    # Test G: Multi-ECU Separation
    # -----------------------------------------------------------------
    def test_g_multi_ecu_separation(self):
        ecm = ECUKnowledgeProfile(
            logical_id="ECM",
            ecu_type=ECUTargetType.ENGINE,
            request_header="7E0",
            response_header="7E8",
        )
        tcm = ECUKnowledgeProfile(
            logical_id="TCM",
            ecu_type=ECUTargetType.TRANSMISSION,
            request_header="7E1",
            response_header="7E9",
        )
        self.store.register_ecu_profile(ecm)
        self.store.register_ecu_profile(tcm)
        self.assertNotEqual(ecm.request_header, tcm.request_header)
        self.assertNotEqual(ecm.response_header, tcm.response_header)

    # -----------------------------------------------------------------
    # Test H: ECU-Specific Namespace (ECM:1640 vs TCM:1640)
    # -----------------------------------------------------------------
    def test_h_ecu_specific_namespace(self):
        def_ecm = DiagnosticIdentifierKnowledge(
            identifier="1640",
            service_id="22",
            name="Engine Coolant Temperature",
            data_type=DataType.INT16,
            unit="°C",
            scaling=0.1,
            target_ecu="ECM",
        )
        def_tcm = DiagnosticIdentifierKnowledge(
            identifier="1640",
            service_id="22",
            name="Transmission Sump Temperature",
            data_type=DataType.INT16,
            unit="°C",
            scaling=0.1,
            target_ecu="TCM",
        )
        self.store.register_identifier_definition(def_ecm)
        self.store.register_identifier_definition(def_tcm)

        self.assertEqual(def_ecm.canonical_key, "ECM:1640")
        self.assertEqual(def_tcm.canonical_key, "TCM:1640")

        # Resolve for ECM
        res_ecm = self.store.resolve_identifier("1640", target_ecu="ECM")
        self.assertTrue(res_ecm.is_resolved)
        self.assertEqual(res_ecm.definition.name, "Engine Coolant Temperature")

        # Resolve for TCM
        res_tcm = self.store.resolve_identifier("1640", target_ecu="TCM")
        self.assertTrue(res_tcm.is_resolved)
        self.assertEqual(res_tcm.definition.name, "Transmission Sump Temperature")

    # -----------------------------------------------------------------
    # Test I: Generic vs ECU-Specific Definition Resolution
    # -----------------------------------------------------------------
    def test_i_generic_vs_ecu_specific_resolution(self):
        generic_rpm = DiagnosticIdentifierKnowledge(
            identifier="010C",
            service_id="01",
            name="Engine RPM (SAE Standard)",
            data_type=DataType.UINT16,
            unit="rpm",
            scaling=0.25,
            target_ecu="GENERIC",
            trust_level=DefinitionTrustLevel.STANDARD,
        )
        tcm_rpm = DiagnosticIdentifierKnowledge(
            identifier="010C",
            service_id="01",
            name="Turbine Input Speed",
            data_type=DataType.UINT16,
            unit="rpm",
            scaling=0.5,
            target_ecu="TCM",
            applicability=VehicleApplicability(manufacturers=["OPEL"]),
        )
        self.store.register_identifier_definition(generic_rpm)
        self.store.register_identifier_definition(tcm_rpm)

        ctx_opel = VehicleContext(manufacturer="OPEL", model="ASTRA")
        # Target ECM -> should get generic
        res_ecm = self.store.resolve_identifier("010C", target_ecu="ECM", vehicle_context=ctx_opel)
        self.assertTrue(res_ecm.is_resolved)
        self.assertEqual(res_ecm.definition.name, "Engine RPM (SAE Standard)")
        self.assertEqual(res_ecm.status, ResolutionStatus.RESOLVED_GENERIC_STANDARD)

        # Target TCM -> should get specific Turbine Input Speed
        res_tcm = self.store.resolve_identifier("010C", target_ecu="TCM", vehicle_context=ctx_opel)
        self.assertTrue(res_tcm.is_resolved)
        self.assertEqual(res_tcm.definition.name, "Turbine Input Speed")
        self.assertEqual(res_tcm.status, ResolutionStatus.RESOLVED_VEHICLE_FAMILY)

    # -----------------------------------------------------------------
    # Test J: Exact Vehicle-Specific Precedence
    # -----------------------------------------------------------------
    def test_j_exact_vehicle_specific_precedence(self):
        # Tier 4: Generic
        d4 = DiagnosticIdentifierKnowledge(
            identifier="2210",
            service_id="22",
            name="Generic Sensor 2210",
            target_ecu="ECM",
            trust_level=DefinitionTrustLevel.STANDARD,
        )
        # Tier 3: Make/Model
        d3 = DiagnosticIdentifierKnowledge(
            identifier="2210",
            service_id="22",
            name="Chevrolet Aveo Sensor 2210",
            target_ecu="ECM",
            applicability=VehicleApplicability(manufacturers=["CHEVROLET"], models=["AVEO"]),
        )
        # Tier 2: Specific engine / software calibration
        d2 = DiagnosticIdentifierKnowledge(
            identifier="2210",
            service_id="22",
            name="Chevrolet Aveo F14D3 Delphi MT80 Sensor 2210",
            target_ecu="ECM",
            applicability=VehicleApplicability(
                manufacturers=["CHEVROLET"],
                models=["AVEO"],
                engine_codes=["F14D3"],
                software_versions=["SW_28019455"],
            ),
        )
        # Tier 1: Exact physical vehicle instance override
        d1 = DiagnosticIdentifierKnowledge(
            identifier="2210",
            service_id="22",
            name="Custom Tuned Instance Sensor 2210",
            target_ecu="ECM",
            instance_id="inst_special_car",
        )
        self.store.register_identifier_definition(d4)
        self.store.register_identifier_definition(d3)
        self.store.register_identifier_definition(d2)
        self.store.register_identifier_definition(d1)

        ctx_generic = VehicleContext(manufacturer="FIAT")
        res4 = self.store.resolve_identifier("2210", target_ecu="ECM", vehicle_context=ctx_generic)
        self.assertEqual(res4.status, ResolutionStatus.RESOLVED_GENERIC_STANDARD)
        self.assertEqual(res4.definition.name, "Generic Sensor 2210")

        ctx_aveo = VehicleContext(manufacturer="CHEVROLET", model="AVEO")
        res3 = self.store.resolve_identifier("2210", target_ecu="ECM", vehicle_context=ctx_aveo)
        self.assertEqual(res3.status, ResolutionStatus.RESOLVED_VEHICLE_FAMILY)
        self.assertEqual(res3.definition.name, "Chevrolet Aveo Sensor 2210")

        ctx_f14d3 = VehicleContext(
            manufacturer="CHEVROLET",
            model="AVEO",
            engine_code="F14D3",
            software_id="SW_28019455",
        )
        res2 = self.store.resolve_identifier("2210", target_ecu="ECM", vehicle_context=ctx_f14d3)
        self.assertEqual(res2.status, ResolutionStatus.RESOLVED_VEHICLE_ECU)
        self.assertEqual(res2.definition.name, "Chevrolet Aveo F14D3 Delphi MT80 Sensor 2210")

        inst_special = VehicleInstanceContext(instance_id="inst_special_car")
        res1 = self.store.resolve_identifier(
            "2210",
            target_ecu="ECM",
            vehicle_instance=inst_special,
            vehicle_context=ctx_f14d3,
        )
        self.assertEqual(res1.status, ResolutionStatus.RESOLVED_EXACT_INSTANCE)
        self.assertEqual(res1.definition.name, "Custom Tuned Instance Sensor 2210")

    # -----------------------------------------------------------------
    # Test K: Deterministic Resolution
    # -----------------------------------------------------------------
    def test_k_deterministic_resolution(self):
        d_gen = DiagnosticIdentifierKnowledge(
            identifier="0105",
            service_id="01",
            name="Engine Coolant Temp",
            scaling=1.0,
            offset=-40.0,
            target_ecu="GENERIC",
            trust_level=DefinitionTrustLevel.STANDARD,
        )
        self.store.register_identifier_definition(d_gen)

        for _ in range(50):
            res = self.store.resolve_identifier("0105", target_ecu="ECM")
            self.assertEqual(res.status, ResolutionStatus.RESOLVED_GENERIC_STANDARD)
            self.assertEqual(res.definition.offset, -40.0)

    # -----------------------------------------------------------------
    # Test L: Conflicting Knowledge Sources (KNOWLEDGE_CONFLICT)
    # -----------------------------------------------------------------
    def test_l_conflicting_knowledge_sources(self):
        source_a = DiagnosticIdentifierKnowledge(
            identifier="2299",
            service_id="22",
            name="Exhaust Gas Temperature Pre-Cat",
            unit="°C",
            scaling=0.1,
            target_ecu="ECM",
            applicability=VehicleApplicability(manufacturers=["VW"], models=["GOLF"]),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="Workshop Manual 2005",
            ),
        )
        source_b = DiagnosticIdentifierKnowledge(
            identifier="2299",
            service_id="22",
            name="Oil Sump Temperature",
            unit="°F",
            scaling=0.2,
            target_ecu="ECM",
            applicability=VehicleApplicability(manufacturers=["VW"], models=["GOLF"]),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.FIELD_OBSERVATION,
                source_reference="Forum Calibration Log",
            ),
        )
        self.store.register_identifier_definition(source_a)
        self.store.register_identifier_definition(source_b)

        ctx_vw = VehicleContext(manufacturer="VW", model="GOLF")
        res = self.store.resolve_identifier("2299", target_ecu="ECM", vehicle_context=ctx_vw)

        # MUST be classified as KNOWLEDGE_CONFLICT; no arbitrary winner picked
        self.assertEqual(res.status, ResolutionStatus.KNOWLEDGE_CONFLICT)
        self.assertIsNone(res.definition)
        self.assertIsNotNone(res.conflict_record)
        self.assertEqual(res.conflict_record.identifier, "2299")
        self.assertIn("scaling", res.conflict_record.conflicting_fields)
        self.assertIn("unit", res.conflict_record.conflicting_fields)
        self.assertIn("name", res.conflict_record.conflicting_fields)
        self.assertEqual(len(res.conflict_record.definitions), 2)

    # -----------------------------------------------------------------
    # Test M: Provenance Preservation
    # -----------------------------------------------------------------
    def test_m_provenance_preservation(self):
        prov = KnowledgeProvenance(
            source_type=KnowledgeProvenanceType.OEM_MANUAL,
            source_reference="ISO 15031-5 Annex B",
            author="SAE Committee",
        )
        defn = DiagnosticIdentifierKnowledge(
            identifier="010C",
            service_id="01",
            name="RPM",
            provenance=prov,
        )
        self.assertEqual(defn.provenance.source_type, KnowledgeProvenanceType.OEM_MANUAL)
        self.assertEqual(defn.provenance.source_reference, "ISO 15031-5 Annex B")
        # Roundtrip dict
        d_dict = defn.to_dict()
        reconstructed = DiagnosticIdentifierKnowledge.from_dict(d_dict)
        self.assertEqual(reconstructed.provenance.source_reference, "ISO 15031-5 Annex B")

    # -----------------------------------------------------------------
    # Test N: Unknown Definition Behavior
    # -----------------------------------------------------------------
    def test_n_unknown_definition_behavior(self):
        res = self.store.resolve_identifier("FFEE", target_ecu="ECM")
        self.assertEqual(res.status, ResolutionStatus.UNKNOWN_IDENTIFIER)
        self.assertIsNone(res.definition)
        self.assertFalse(res.is_resolved)

    # -----------------------------------------------------------------
    # Test O: Identifier Unit/Scaling Representation
    # -----------------------------------------------------------------
    def test_o_identifier_unit_scaling_representation(self):
        rpm_def = DiagnosticIdentifierKnowledge(
            identifier="010C",
            service_id="01",
            name="Engine Speed",
            data_type=DataType.UINT16,
            byte_order=ByteOrder.BIG_ENDIAN,
            unit="rpm",
            scaling=0.25,
            offset=0.0,
        )
        # 0x1F40 = 8000 -> 8000 * 0.25 = 2000.0 RPM
        raw = bytes([0x1F, 0x40])
        val = rpm_def.decode_physical_value(raw)
        self.assertEqual(val, 2000.0)

        # Negative temperature: INT8, scale=1.0, offset=-40.0
        ect_def = DiagnosticIdentifierKnowledge(
            identifier="0105",
            service_id="01",
            name="Engine Coolant Temp",
            data_type=DataType.UINT8,
            unit="°C",
            scaling=1.0,
            offset=-40.0,
        )
        # raw 0x40 = 64 -> 64 - 40 = 24.0 °C
        val_ect = ect_def.decode_physical_value(bytes([0x40]))
        self.assertEqual(val_ect, 24.0)

    # -----------------------------------------------------------------
    # Test P: No Double-Scaling Verification
    # -----------------------------------------------------------------
    def test_p_no_double_scaling(self):
        rpm_def = DiagnosticIdentifierKnowledge(
            identifier="010C",
            service_id="01",
            name="Engine Speed",
            data_type=DataType.UINT16,
            byte_order=ByteOrder.BIG_ENDIAN,
            unit="rpm",
            scaling=0.25,
            offset=0.0,
        )
        raw = bytes([0x1F, 0x40])
        # Call multiple times: result must remain exactly 2000.0 (never 500.0 or 125.0)
        for _ in range(10):
            val = rpm_def.decode_physical_value(raw)
            self.assertEqual(val, 2000.0)

    # -----------------------------------------------------------------
    # Test Q: Protocol / Transport Separation
    # -----------------------------------------------------------------
    def test_q_protocol_transport_separation(self):
        ecu = ECUKnowledgeProfile(
            logical_id="ECM",
            protocol="ISO_15765_4_CAN_11BIT",
        )
        # Verify that protocol is purely vehicle-level diagnostic framing, not hardware-dependent
        self.assertIn("CAN", ecu.protocol)
        self.assertNotIn("ELM327", ecu.protocol)
        self.assertNotIn("J2534", ecu.protocol)

    # -----------------------------------------------------------------
    # Test R: Historical Versioning
    # -----------------------------------------------------------------
    def test_r_historical_versioning(self):
        defn_v1 = DiagnosticIdentifierKnowledge(
            identifier="010C",
            schema_version=1,
            name="Engine RPM V1",
        )
        defn_v2 = DiagnosticIdentifierKnowledge(
            identifier="010C",
            schema_version=2,
            name="Engine RPM V2",
        )
        self.assertEqual(defn_v1.schema_version, 1)
        self.assertEqual(defn_v2.schema_version, 2)

    # -----------------------------------------------------------------
    # Test S: J-3 Persistence Integration
    # -----------------------------------------------------------------
    def test_s_j3_persistence_integration(self):
        backend = SQLitePersistenceBackend(":memory:")
        backend.initialize()
        repo = DiagnosticRepository(backend=backend)

        model = VehicleModelDefinition(
            model_id="TEST_MODEL_1",
            make="Opel",
            model="Corsa",
            engine_code="A14XER",
        )
        mid = repo.save_vehicle_model(model)
        self.assertEqual(mid, "TEST_MODEL_1")

        loaded = repo.get_vehicle_model("TEST_MODEL_1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.make, "Opel")
        self.assertEqual(loaded.engine_code, "A14XER")

    # -----------------------------------------------------------------
    # Test T: Vehicle Identity Persistence
    # -----------------------------------------------------------------
    def test_t_vehicle_identity_persistence(self):
        backend = SQLitePersistenceBackend(":memory:")
        backend.initialize()
        repo = DiagnosticRepository(backend=backend)

        inst = VehicleInstanceContext(
            instance_id="inst_persisted_car",
            vin="W0L0SDL6894123456",
            model_definition_id="TEST_MODEL_1",
            verification_state=VehicleVerificationState.VERIFIED,
        )
        repo.save_vehicle_instance(inst)
        loaded = repo.get_vehicle_instance("inst_persisted_car")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.vin, "W0L0SDL6894123456")
        self.assertEqual(loaded.verification_state, VehicleVerificationState.VERIFIED)

    # -----------------------------------------------------------------
    # Test U: ECU Identity Persistence
    # -----------------------------------------------------------------
    def test_u_ecu_identity_persistence(self):
        backend = SQLitePersistenceBackend(":memory:")
        backend.initialize()
        repo = DiagnosticRepository(backend=backend)

        inst = VehicleInstanceContext(
            instance_id="inst_with_ecus",
            observed_ecus={
                "ECM": ECUKnowledgeProfile(
                    logical_id="ECM",
                    module_family="DELPHI_MT80",
                    hardware_id="HW_96800112",
                )
            },
        )
        repo.save_vehicle_instance(inst)
        loaded = repo.get_vehicle_instance("inst_with_ecus")
        self.assertIn("ECM", loaded.observed_ecus)
        self.assertEqual(loaded.observed_ecus["ECM"].module_family, "DELPHI_MT80")

    # -----------------------------------------------------------------
    # Test V: D/H/I Context Integration
    # -----------------------------------------------------------------
    def test_v_d_h_i_context_integration(self):
        adapter = ContextualWorkflowAdapter(self.store)
        causes = adapter.get_contextual_root_causes("P0101", target_ecu="ECM")
        # In absence of overrides, returns empty list without error
        self.assertIsInstance(causes, list)

    # -----------------------------------------------------------------
    # Test W: Safety Separation (Read-Only Enforcement)
    # -----------------------------------------------------------------
    def test_w_safety_separation(self):
        # ECU profile advertises service 0x14 (Clear DTCs)
        ecu = ECUKnowledgeProfile(
            logical_id="ECM",
            supported_services={"01", "14", "22"},
        )
        self.store.register_ecu_profile(ecu)
        # Knowledge says ECU supports 0x14, but destructive service is strictly prohibited
        from diagnostic_adapter import PROHIBITED_SERVICES
        self.assertIn("14", PROHIBITED_SERVICES)
        self.assertIn("14", ecu.supported_services)

    # -----------------------------------------------------------------
    # Test X: Regression Against K-1 / K-2 / K-3
    # -----------------------------------------------------------------
    def test_x_regression_k1_k2_k3(self):
        # Verify K-1, K-2, K-3 types can coexist with L-1 models
        from diagnostic_adapter import (
            DiagnosticAdapter,
            ELM327DiagnosticAdapter,
            AdapterCapabilities,
        )
        from live_runtime import (
            LiveAcquisitionRuntime,
            LIVE_IDLE,
            LIVE_STOPPED,
        )
        adapter = ELM327DiagnosticAdapter()
        self.assertIsNotNone(adapter.capabilities)
        runtime = LiveAcquisitionRuntime(engine=None, adapter=adapter)
        self.assertIn(runtime.get_state(), (LIVE_IDLE, LIVE_STOPPED))

    # -----------------------------------------------------------------
    # Test Y: Relevant J-Final Regressions
    # -----------------------------------------------------------------
    def test_y_regression_j_final(self):
        from user_session_manager import UserSessionManager
        backend = SQLitePersistenceBackend(":memory:")
        backend.initialize()
        repo = DiagnosticRepository(backend=backend)
        user_mgr = UserSessionManager(repository=repo)
        sec_mgr = SecurityManager(repository=repo, user_session_manager=user_mgr)
        self.assertIsNotNone(sec_mgr.policy)
        tech_perms = sec_mgr.policy.get_permissions_for_roles([Role.TECHNICIAN])
        self.assertIn(Permission.READ_DTC, tech_perms)
        repo.close()

    # -----------------------------------------------------------------
    # Test Z: Relevant C->I Pipeline Regressions
    # -----------------------------------------------------------------
    def test_z_regression_c_to_i_pipeline(self):
        # Verify that DiagnosticDataDefinition converts to DiagnosticIdentifierKnowledge
        ddd = DiagnosticDataDefinition(
            identifier="010C",
            service_id="01",
            name="Engine Speed",
            fields=[
                FieldDefinition(
                    name="RPM",
                    data_type=DataType.UINT16,
                    scale=0.25,
                    unit="rpm",
                )
            ],
            applicability=VehicleApplicability(manufacturers=["OPEL"]),
        )
        dik = ddd.to_identifier_knowledge()
        self.assertEqual(dik.identifier, "010C")
        self.assertEqual(dik.scaling, 0.25)
        self.assertEqual(dik.unit, "rpm")
        self.store.register_identifier_definition(dik)

        ctx = VehicleContext(manufacturer="OPEL")
        res = self.store.resolve_identifier("010C", target_ecu="ECM", vehicle_context=ctx)
        self.assertTrue(res.is_resolved)
        self.assertEqual(res.definition.scaling, 0.25)


if __name__ == "__main__":
    unittest.main()
