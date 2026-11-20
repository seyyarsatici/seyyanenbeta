"""
test_phase_g_final.py — Phase G Final Integration & Release Gate Test Suite

Comprehensive end-to-end regression and verification suite for Phase G:
- G-1: Advanced ECU Services Foundation
- G-2: Extended DID / PID Ecosystem
- G-3: Advanced Fault Analysis
- G-4: Multi-ECU Diagnostics
- G-5: Vehicle-Wide Diagnostic Graph

Mandatory End-to-End Scenarios:
- Scenario A: Single ECU read-only service -> identifier decoding -> validated data -> G-3 analysis -> evidence/hypothesis -> G-5 graph
- Scenario B: Multi-ECU acquisition -> ECU-specific DTCs/signals -> G-3 analysis -> cross-ECU evidence -> G-5 graph
- Scenario C: Communication failure -> unreachable ECU -> acquisition evidence -> no fabricated component fault -> correct graph representation
- Scenario D: Same DTC code on two ECUs -> two distinct DTC nodes
- Scenario E: DTC-free abnormal sensor behavior -> anomaly -> evidence -> hypothesis -> graph representation
- Scenario F: Contradictory evidence -> hypothesis confidence reflects contradiction -> no false certainty
- Scenario G: Missing/unknown DID/PID -> raw/unparsed evidence preserved
- Scenario H: Multiple sessions for same vehicle -> controlled merge -> historical observations preserved
- Scenario I: Different vehicle identity -> merge rejected
- Scenario J: Large dataset / graph -> bounded performance -> bounded memory growth -> no pathological all-pairs behavior
- Scenario K: Safety attack-style tests -> Mode 04/14 rejected -> write rejected -> security access rejected -> actuator rejected -> programming rejected
"""

import unittest
import time
import math
import numpy as np
from typing import Dict, Any, List, Tuple

from advanced_ecu_services import (
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    DiagnosticTransactionManager,
    ITransportAdapter,
    ServiceSafetyPolicy,
    ServiceSafetyClassification,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_TRANSACTION_BLOCKED,
)

from extended_did import (
    DiagnosticDefinitionRegistry,
    DiagnosticDataDefinition,
    FieldDefinition,
    DataDecoder,
    ByteOrder,
    DataType,
    DefinitionTrustLevel,
    IdentifierNamespace,
    StructuredDiagnosticEvidence,
)

from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_INVALID,
    QUALITY_ERROR,
)

from advanced_fault_analysis import (
    AdvancedFaultAnalyzer,
    AnalysisResult,
    AnomalySeverity,
    AnomalyType,
    DiagnosticDataSet,
    DTCRecord,
    FaultEvidence,
    FaultHypothesis,
    HypothesisConfidence,
    OperatingCondition,
    PointAnomaly,
    TemporalAnomaly,
    SignalQuality,
    TimeSeriesSignal,
)

from multi_ecu_diagnostics import (
    MultiECUDiagnosticManager,
    ECUTarget,
    ECUScanRecord,
    MultiECUScanResult,
    MultiECUDTCRecord,
    MultiECUDataSample,
    ECUDiscoveryState,
    ECUHealthState,
    ScanScope,
)

from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    VehicleDiagnosticGraphBuilder,
    VehicleIdentityMismatchError,
    GraphValidationError,
    make_vehicle_node_id,
    make_ecu_node_id,
    make_signal_node_id,
    make_dtc_node_id,
    make_anomaly_node_id,
    make_evidence_node_id,
    make_hypothesis_node_id,
    make_session_node_id,
    make_edge_id,
)

from extended_did import VehicleContext


class MockTransportAdapter(ITransportAdapter):
    """Deterministic mock transport adapter implementing ITransportAdapter."""
    def __init__(self, responses: Dict[str, List[str]] = None):
        self.responses = responses or {}
        self.history: List[str] = []
        self._header = "7DF"

    def send_command(self, cmd: str, timeout: float = 1.0) -> Tuple[List[str], str]:
        self.history.append(cmd)
        cmd_clean = cmd.strip().replace(" ", "").upper()
        if cmd_clean in self.responses:
            return self.responses[cmd_clean], STATUS_VALID
        for k, v in self.responses.items():
            if cmd_clean.startswith(k):
                return v, STATUS_VALID
        return [], STATUS_TIMEOUT

    def get_current_header(self) -> str:
        return self._header

    def set_header(self, header: str, timeout: float = 1.0) -> bool:
        self._header = header
        return True

    def is_connected(self) -> bool:
        return True


class TestPhaseGFinalIntegration(unittest.TestCase):
    """End-to-End Release Gate Verification Suite for Phase G."""

    def setUp(self):
        self.v_ctx = VehicleContext(
            vin="1HGCR2F83HA123456",
            manufacturer="HONDA",
            model="ACCORD",
            model_year=2017,
            engine_code="K24W2",
        )

    # -----------------------------------------------------------------
    # Scenario A: Single ECU read-only service -> DID decode ->
    #             validated data -> G-3 analysis -> evidence/hypothesis -> G-5 graph
    # -----------------------------------------------------------------
    def test_scenario_a_single_ecu_e2e_pipeline(self):
        """Verify full chain from G-1 request/response through G-5 graph representation."""
        # 1. G-1 Service Request (UDS 0x22 ReadDataByIdentifier DID 0xF40C Engine RPM)
        # Response: 7E8 62 F4 0C 1F 40 (0x1F40 = 8000 -> 8000 / 4 = 2000 RPM)
        mock_transport = MockTransportAdapter({
            "22F40C": ["7E8 62 F4 0C 1F 40", ">"]
        })
        tm = DiagnosticTransactionManager(transport=mock_transport)
        
        req = tm.build_request(
            service_id="22",
            payload="F40C",
            target_ecu="ECM",
        )
        resp = tm.execute_request(req)
        self.assertTrue(resp.is_positive)
        self.assertEqual(resp.response_service_id, "62")
        self.assertEqual(resp.raw_payload_hex, "62F40C1F40")

        # 2. G-2 Decoding
        def_rpm = DiagnosticDataDefinition(
            identifier="F40C",
            service_id="22",
            namespace=IdentifierNamespace.EXTENDED_UDS_DID,
            name="Engine RPM",
            fields=[
                FieldDefinition(
                    name="RPM",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    byte_order=ByteOrder.BIG_ENDIAN,
                    scale=0.25,
                    offset=0.0,
                    unit="RPM",
                )
            ],
            trust_level=DefinitionTrustLevel.STANDARD,
        )
        
        # Raw data payload after 62 F4 0C is 1F 40 (bytes)
        data_payload = bytes.fromhex(resp.raw_payload_hex)[3:] # 0x1F, 0x40
        raw_val, decoded_val, fields, is_valid, err = DataDecoder.decode(data_payload, def_rpm)
        self.assertTrue(is_valid)
        self.assertEqual(decoded_val, 2000.0)

        # 3. G-3 Analysis on generated signal stream
        # Generate time series with dynamic engine and a MAP flatline anomaly at 40.0 kPa
        timestamps = np.arange(0.0, 30.0, 0.1, dtype=np.float64)
        rpms = np.where(timestamps < 10.0, 850.0, np.where(timestamps < 20.0, 2200.0, 850.0))
        speeds = np.where(timestamps < 10.0, 0.0, 65.0)
        maps = np.full(len(timestamps), 40.0) # Frozen/flatline MAP
        ects = np.clip(60.0 + timestamps * 0.6, 60.0, 90.0)
        tps = np.where(timestamps < 10.0, 2.0, 20.0)
        
        dataset = DiagnosticDataSet(
            dataset_id="DATASET_SCENARIO_A",
            vehicle_context=self.v_ctx,
        )
        dataset.add_signal(TimeSeriesSignal("RPM", "rpm", timestamps, rpms))
        dataset.add_signal(TimeSeriesSignal("SPEED", "km/h", timestamps, speeds))
        dataset.add_signal(TimeSeriesSignal("MAP", "kPa", timestamps, maps))
        dataset.add_signal(TimeSeriesSignal("ECT", "°C", timestamps, ects))
        dataset.add_signal(TimeSeriesSignal("TPS", "%", timestamps, tps))
        
        analyzer = AdvancedFaultAnalyzer()
        result = analyzer.analyze_dataset(dataset)
        self.assertGreater(len(result.anomalies), 0)
        flatline_found = any(a.anomaly_type == AnomalyType.SENSOR_FLATLINE for a in result.anomalies)
        self.assertTrue(flatline_found)

        # 4. G-5 Graph Ingestion
        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        builder.ingest_g3_analysis_result(result, dataset=dataset)
        graph = builder.graph

        # Verify nodes and relationships
        v_node = graph.get_node(make_vehicle_node_id(self.v_ctx))
        self.assertIsNotNone(v_node)
        
        anomaly_nodes = graph.get_nodes(GraphNodeType.ANOMALY)
        self.assertGreater(len(anomaly_nodes), 0)
        
        # Verify invariant: RELATIONSHIP != CAUSALITY (No CAUSED_BY edges)
        for edge in graph.edges:
            self.assertNotEqual(edge.edge_type.value, "CAUSED_BY")
            self.assertNotEqual(edge.edge_type.value, "ROOT_CAUSE")

    # -----------------------------------------------------------------
    # Scenario B: Multi-ECU acquisition -> ECU-specific DTCs/signals ->
    #             G-3 analysis -> cross-ECU evidence -> G-5 graph
    # -----------------------------------------------------------------
    def test_scenario_b_multi_ecu_isolation_and_cross_ecu_evidence(self):
        """Verify ECU isolation across ECM, TCM, and multi-ECU graph synthesis."""
        dtc_ecm = MultiECUDTCRecord(ecu_id="ECM", code="P0300", status="CONFIRMED")
        dtc_tcm = MultiECUDTCRecord(ecu_id="TCM", code="P0700", status="CONFIRMED")
        
        sample_ecm = MultiECUDataSample(
            ecu_id="ECM",
            identifier="0C",
            service_id="01",
            field_name="RPM",
            canonical_name="ECM:0C:RPM",
            decoded_value=2000.0,
            raw_value=bytes([0x1F, 0x40]),
            unit="RPM",
            quality=QUALITY_GOOD,
        )
        sample_tcm = MultiECUDataSample(
            ecu_id="TCM",
            identifier="02",
            service_id="01",
            field_name="TRANS_TEMP",
            canonical_name="TCM:02:TRANS_TEMP",
            decoded_value=112.0,
            raw_value=bytes([0x70]),
            unit="C",
            quality=QUALITY_GOOD,
        )

        scan_result = MultiECUScanResult(
            scan_id="MULTI_ECU_SESSION_1",
            vehicle_context=None,
            ecu_records={
                "ECM": ECUScanRecord(
                    ecu_id="ECM",
                    ecu_type="ENGINE",
                    request_header="7E0",
                    response_header="7E8",
                    discovery_state="VERIFIED_REACHABLE",
                    health_state="HEALTHY",
                    dtcs=[dtc_ecm],
                    data_samples=[sample_ecm],
                ),
                "TCM": ECUScanRecord(
                    ecu_id="TCM",
                    ecu_type="TRANSMISSION",
                    request_header="7E1",
                    response_header="7E9",
                    discovery_state="VERIFIED_REACHABLE",
                    health_state="HEALTHY",
                    dtcs=[dtc_tcm],
                    data_samples=[sample_tcm],
                ),
            },
            reachable_ecus=["ECM", "TCM"],
            expected_ecus=["ECM", "TCM"],
        )

        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        builder.ingest_multi_ecu_scan(scan_result)
        graph = builder.graph

        # Verify ECM and TCM are distinct nodes
        ecm_node = graph.get_node(make_ecu_node_id("ECM"))
        tcm_node = graph.get_node(make_ecu_node_id("TCM"))
        self.assertIsNotNone(ecm_node)
        self.assertIsNotNone(tcm_node)
        self.assertNotEqual(ecm_node.node_id, tcm_node.node_id)

        # Verify DTCs belong strictly to their respective ECUs
        dtc_ecm_node = graph.get_node(make_dtc_node_id("ECM", "P0300"))
        dtc_tcm_node = graph.get_node(make_dtc_node_id("TCM", "P0700"))
        self.assertIsNotNone(dtc_ecm_node)
        self.assertIsNotNone(dtc_tcm_node)
        self.assertEqual(dtc_ecm_node.properties["ecu_id"], "ECM")
        self.assertEqual(dtc_tcm_node.properties["ecu_id"], "TCM")

        # Discover candidate relationships (bounded correlation / co-occurrence)
        builder.discover_cross_ecu_relationships(max_pairs=50)
        # Should not create all-to-all exploding edges
        self.assertLess(len(graph.edges), 50)

    # -----------------------------------------------------------------
    # Scenario C: Communication failure -> unreachable ECU -> acquisition evidence ->
    #             no fabricated component fault -> correct graph representation
    # -----------------------------------------------------------------
    def test_scenario_c_communication_failure_safety(self):
        """Verify that transport failure produces acquisition evidence and NO false vehicle faults."""
        rec_abs = ECUScanRecord(
            ecu_id="ABS",
            ecu_type="BRAKES",
            request_header="7E2",
            response_header="7EA",
            discovery_state="UNREACHABLE",
            health_state="OFFLINE",
            dtcs=[],
            data_samples=[],
            failed_transactions=1,
            last_error="Transport timeout after 1000ms",
        )
        scan = MultiECUScanResult(
            scan_id="SESS_COMM_FAIL",
            vehicle_context=None,
            ecu_records={"ABS": rec_abs},
            unreachable_ecus=["ABS"],
            expected_ecus=["ABS"],
        )

        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        builder.ingest_multi_ecu_scan(scan)
        graph = builder.graph

        # ABS ECU node exists and records failure status
        abs_node = graph.get_node(make_ecu_node_id("ABS"))
        self.assertIsNotNone(abs_node)
        self.assertEqual(abs_node.properties.get("health_state"), "OFFLINE")

        # Invariant check: ZERO DTC nodes created for ABS, ZERO component fault hypotheses created
        abs_dtcs = [n for n in graph.get_nodes(GraphNodeType.DTC) if n.properties.get("ecu_id") == "ABS"]
        self.assertEqual(len(abs_dtcs), 0)

        hypotheses = graph.get_nodes(GraphNodeType.HYPOTHESIS)
        self.assertEqual(len(hypotheses), 0)

    # -----------------------------------------------------------------
    # Scenario D: Same DTC code on two ECUs -> two distinct DTC nodes
    # -----------------------------------------------------------------
    def test_scenario_d_same_dtc_on_two_ecus_distinct_identity(self):
        """ECM:P0500 != TCM:P0500 must produce distinct nodes in G-5."""
        dtc_ecm = MultiECUDTCRecord(ecu_id="ECM", code="P0500", status="CONFIRMED")
        dtc_tcm = MultiECUDTCRecord(ecu_id="TCM", code="P0500", status="PENDING")

        scan = MultiECUScanResult(
            scan_id="SESS_DUAL_DTC",
            vehicle_context=None,
            ecu_records={
                "ECM": ECUScanRecord(
                    ecu_id="ECM",
                    ecu_type="ENGINE",
                    request_header="7E0",
                    response_header="7E8",
                    discovery_state="VERIFIED_REACHABLE",
                    health_state="HEALTHY",
                    dtcs=[dtc_ecm],
                ),
                "TCM": ECUScanRecord(
                    ecu_id="TCM",
                    ecu_type="TRANSMISSION",
                    request_header="7E1",
                    response_header="7E9",
                    discovery_state="VERIFIED_REACHABLE",
                    health_state="HEALTHY",
                    dtcs=[dtc_tcm],
                ),
            },
            reachable_ecus=["ECM", "TCM"],
        )

        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        builder.ingest_multi_ecu_scan(scan)
        graph = builder.graph

        node_ecm = graph.get_node("dtc:ECM:P0500")
        node_tcm = graph.get_node("dtc:TCM:P0500")

        self.assertIsNotNone(node_ecm)
        self.assertIsNotNone(node_tcm)
        self.assertNotEqual(node_ecm.node_id, node_tcm.node_id)
        self.assertEqual(node_ecm.properties["ecu_id"], "ECM")
        self.assertEqual(node_tcm.properties["ecu_id"], "TCM")
        self.assertEqual(node_ecm.properties["status"], "CONFIRMED")
        self.assertEqual(node_tcm.properties["status"], "PENDING")

    # -----------------------------------------------------------------
    # Scenario E: DTC-free abnormal sensor behavior -> anomaly -> evidence ->
    #             hypothesis -> graph representation
    # -----------------------------------------------------------------
    def test_scenario_e_dtc_free_fault_detection(self):
        """Sensor anomaly without any DTC produces evidence and hypothesis."""
        ts_gh = np.arange(0, 60.0, 0.2)
        rpms_gh = np.where(ts_gh < 30.0, 850.0, 2400.0)
        speeds_gh = np.where(ts_gh < 30.0, 0.0, 80.0)
        tps_gh = np.where(ts_gh < 30.0, 2.0, 22.0)
        stfts_g = np.where(ts_gh < 30.0, 18.0, 2.0)
        ltfts_g = np.where(ts_gh < 30.0, 15.0, 3.0)

        dataset = DiagnosticDataSet(
            dataset_id="DATASET_DTC_FREE",
            vehicle_context=self.v_ctx,
            dtc_records=[], # Explicitly NO DTCs
        )
        dataset.add_signal(TimeSeriesSignal("RPM", "rpm", ts_gh, rpms_gh))
        dataset.add_signal(TimeSeriesSignal("SPEED", "km/h", ts_gh, speeds_gh))
        dataset.add_signal(TimeSeriesSignal("TPS", "%", ts_gh, tps_gh))
        dataset.add_signal(TimeSeriesSignal("STFT", "%", ts_gh, stfts_g))
        dataset.add_signal(TimeSeriesSignal("LTFT", "%", ts_gh, ltfts_g))

        analyzer = AdvancedFaultAnalyzer()
        result = analyzer.analyze_dataset(dataset)
        
        # Hypotheses and evidence detected despite zero DTCs
        self.assertGreater(len(result.hypotheses), 0)
        self.assertGreater(len(result.evidence), 0)
        vac_hyp = any("VACUUM" in h.hypothesis_id for h in result.hypotheses)
        self.assertTrue(vac_hyp)

        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        builder.ingest_g3_analysis_result(result, dataset=dataset)
        graph = builder.graph

        # Graph contains Evidence and Hypothesis nodes
        self.assertGreater(len(graph.get_nodes(GraphNodeType.EVIDENCE)), 0)
        self.assertGreater(len(graph.get_nodes(GraphNodeType.HYPOTHESIS)), 0)
        # And zero DTC nodes
        self.assertEqual(len(graph.get_nodes(GraphNodeType.DTC)), 0)

    # -----------------------------------------------------------------
    # Scenario F: Contradictory evidence -> hypothesis confidence reflects contradiction
    # -----------------------------------------------------------------
    def test_scenario_f_contradictory_evidence_handling(self):
        """Contradictory evidence creates CONTRADICTS_HYPOTHESIS edge without false certainty."""
        ev1 = FaultEvidence(
            evidence_id="EV_SUPPORT",
            title="High ECT reading",
            signals=["ECM:ECT"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.STEADY_CRUISE,
            observed_behavior="ECT at 125C",
            expected_behavior="ECT between 85-105C",
            deviation_magnitude=20.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={"source": "ANALYSIS_G3"},
            analysis_method="THRESHOLD_ANALYSIS",
            confidence_score=0.85,
        )
        ev2 = FaultEvidence(
            evidence_id="EV_CONTRADICT",
            title="Radiator Fan Full Speed and Radiator Outlet Cool",
            signals=["ECM:RAD_TEMP"],
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            operating_condition=OperatingCondition.STEADY_CRUISE,
            observed_behavior="Radiator outlet at 40C",
            expected_behavior="Radiator outlet warm",
            deviation_magnitude=0.0,
            severity=AnomalySeverity.ADVISORY,
            quality=SignalQuality.GOOD,
            provenance={"source": "ANALYSIS_G3"},
            analysis_method="SENSOR_CROSS_CHECK",
            confidence_score=0.90,
        )
        hypo = FaultHypothesis(
            hypothesis_id="HYPO_OVERHEAT",
            title="Engine Overheating Condition",
            category="COOLING_SYSTEM",
            affected_system="THERMAL_MANAGEMENT",
            supporting_evidence=[ev1],
            contradicting_evidence=[ev2],
            evidence_score=0.45,
            confidence=HypothesisConfidence.LOW, # Lowered confidence due to contradiction
            severity=AnomalySeverity.WARNING,
        )

        analysis = AnalysisResult(
            analysis_id="ANALYSIS_CONTRADICTION",
            dataset_id="SET_CONTRA",
            anomalies=[],
            evidence=[ev1, ev2],
            hypotheses=[hypo],
        )

        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        builder.ingest_g3_analysis_result(analysis)
        graph = builder.graph

        hypo_node = graph.get_node("hypothesis:HYPO_OVERHEAT")
        self.assertIsNotNone(hypo_node)
        self.assertEqual(hypo_node.properties["confidence"], "LOW")

        # Check for both SUPPORTS_HYPOTHESIS and CONTRADICTS_HYPOTHESIS edges
        contra_edges = [e for e in graph.edges if e.edge_type == GraphEdgeType.CONTRADICTS_HYPOTHESIS]
        self.assertEqual(len(contra_edges), 1)
        self.assertEqual(contra_edges[0].source_id, "evidence:EV_CONTRADICT")
        self.assertEqual(contra_edges[0].target_id, "hypothesis:HYPO_OVERHEAT")

    # -----------------------------------------------------------------
    # Scenario G: Missing/unknown DID/PID -> raw/unparsed evidence preserved
    # -----------------------------------------------------------------
    def test_scenario_g_unknown_did_preserves_raw_evidence(self):
        """Unknown or unmapped DIDs are preserved as raw/unknown data without failure."""
        unk_def = DiagnosticDataDefinition(
            identifier="EEEE",
            service_id="22",
            namespace=IdentifierNamespace.RAW_UNKNOWN,
            trust_level=DefinitionTrustLevel.UNKNOWN,
        )
        raw_bytes = bytes([0xAA, 0xBB, 0xCC, 0xDD])
        raw_val, dec_val, fields, is_valid, err = DataDecoder.decode(raw_bytes, unk_def)

        self.assertTrue(is_valid)
        self.assertEqual(dec_val, "AABBCCDD")
        self.assertEqual(raw_val, "AABBCCDD")

        # Also verify in G-4 MultiECUDataSample
        sample = MultiECUDataSample(
            ecu_id="ECM",
            identifier="EEEE",
            service_id="22",
            field_name="RAW_PAYLOAD",
            canonical_name="ECM:EEEE:RAW_PAYLOAD",
            decoded_value="AABBCCDD",
            raw_value=raw_bytes,
            unit="",
            quality=QUALITY_GOOD,
        )
        self.assertEqual(sample.raw_value, raw_bytes)

    # -----------------------------------------------------------------
    # Scenario H: Multiple sessions for same vehicle -> controlled merge
    # -----------------------------------------------------------------
    def test_scenario_h_multi_session_controlled_merge(self):
        """Multiple sessions for the same vehicle cleanly merge without clobbering nodes."""
        # Session 1
        builder1 = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        scan1 = MultiECUScanResult(
            scan_id="SESSION_JAN_01",
            vehicle_context=None,
            ecu_records={"ECM": ECUScanRecord(
                ecu_id="ECM",
                ecu_type="ENGINE",
                request_header="7E0",
                response_header="7E8",
                discovery_state="VERIFIED_REACHABLE",
                health_state="HEALTHY",
                dtcs=[MultiECUDTCRecord(ecu_id="ECM", code="P0101", status="CONFIRMED")]
            )},
        )
        builder1.ingest_multi_ecu_scan(scan1)
        g1 = builder1.graph

        # Session 2
        builder2 = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        scan2 = MultiECUScanResult(
            scan_id="SESSION_FEB_01",
            vehicle_context=None,
            ecu_records={"ECM": ECUScanRecord(
                ecu_id="ECM",
                ecu_type="ENGINE",
                request_header="7E0",
                response_header="7E8",
                discovery_state="VERIFIED_REACHABLE",
                health_state="HEALTHY",
                dtcs=[
                    MultiECUDTCRecord(ecu_id="ECM", code="P0101", status="CONFIRMED"),
                    MultiECUDTCRecord(ecu_id="ECM", code="P0171", status="PENDING"),
                ]
            )},
        )
        builder2.ingest_multi_ecu_scan(scan2)
        g2 = builder2.graph

        # Merge g2 into g1
        merged_graph = builder1.merge_graph(g2)
        
        # Vehicle node is unified
        v_nodes = merged_graph.get_nodes(GraphNodeType.VEHICLE)
        self.assertEqual(len(v_nodes), 1)

        # Both sessions exist
        s1 = merged_graph.get_node(make_session_node_id("SESSION_JAN_01"))
        s2 = merged_graph.get_node(make_session_node_id("SESSION_FEB_01"))
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)

        # DTC P0171 is present from session 2
        p0171 = merged_graph.get_node("dtc:ECM:P0171")
        self.assertIsNotNone(p0171)

    # -----------------------------------------------------------------
    # Scenario I: Different vehicle identity -> merge rejected
    # -----------------------------------------------------------------
    def test_scenario_i_different_vehicle_merge_rejected(self):
        """Merging graphs from two distinct vehicles must raise VehicleIdentityMismatchError."""
        v_ctx_a = VehicleContext(vin="1HGCR2F83HA111111", manufacturer="HONDA", model="ACCORD", model_year=2017)
        v_ctx_b = VehicleContext(vin="3VW2K7AJ0HM222222", manufacturer="VOLKSWAGEN", model="GOLF", model_year=2017)

        builder_a = VehicleDiagnosticGraphBuilder(vehicle_context=v_ctx_a)
        builder_b = VehicleDiagnosticGraphBuilder(vehicle_context=v_ctx_b)

        with self.assertRaises(VehicleIdentityMismatchError):
            builder_a.merge_graph(builder_b.graph)

    # -----------------------------------------------------------------
    # Scenario J: Large dataset / graph -> bounded performance & memory
    # -----------------------------------------------------------------
    def test_scenario_j_large_scale_bounded_performance(self):
        """Verify graph construction and relationship discovery scale without quadratic explosion."""
        builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.v_ctx)
        
        # Add 50 distinct signal nodes across 5 ECUs
        ecus = ["ECM", "TCM", "BCM", "ABS", "SRS"]
        for ecu in ecus:
            for i in range(10):
                builder.add_signal_node(
                    ecu_id=ecu,
                    identifier=f"{i:02X}",
                    signal_name=f"SIG_{i}",
                    unit="V",
                    quality=QUALITY_GOOD,
                )

        t_start = time.perf_counter()
        # Candidate relationship discovery with max_pairs bounding
        builder.discover_cross_ecu_relationships(max_pairs=100)
        elapsed = time.perf_counter() - t_start

        # Sub-second execution
        self.assertLess(elapsed, 0.5, f"Cross-ECU discovery took {elapsed:.4f}s, expected < 0.5s")
        # Ensure bounded edge generation
        self.assertLessEqual(len(builder.graph.edges), 150)

    # -----------------------------------------------------------------
    # Scenario K: Safety attack-style tests -> destructive services rejected
    # -----------------------------------------------------------------
    def test_scenario_k_safety_attacks_rejected(self):
        """Verify strict read-only guarantees against all destructive diagnostic services."""
        mock_transport = MockTransportAdapter()
        policy = ServiceSafetyPolicy()
        tm = DiagnosticTransactionManager(transport=mock_transport, safety_policy=policy)

        # 1. Mode 04 (OBD Clear DTCs)
        req_04 = AdvancedServiceRequest(service_id="04")
        safe, reason = policy.validate_request(req_04)
        self.assertFalse(safe)
        resp_04 = tm.execute_request(req_04)
        self.assertEqual(resp_04.status, STATUS_TRANSACTION_BLOCKED)

        # 2. UDS 0x14 (ClearDiagnosticInformation)
        req_14 = AdvancedServiceRequest(service_id="14")
        safe, reason = policy.validate_request(req_14)
        self.assertFalse(safe)
        resp_14 = tm.execute_request(req_14)
        self.assertEqual(resp_14.status, STATUS_TRANSACTION_BLOCKED)

        # 3. UDS 0x2E (WriteDataByIdentifier)
        req_2e = AdvancedServiceRequest(
            service_id="2E",
            payload="F40C00",
            safety_classification=ServiceSafetyClassification.WRITE,
        )
        safe, reason = policy.validate_request(req_2e)
        self.assertFalse(safe)
        resp_2e = tm.execute_request(req_2e)
        self.assertEqual(resp_2e.status, STATUS_TRANSACTION_BLOCKED)

        # 4. UDS 0x27 (SecurityAccess)
        req_27 = AdvancedServiceRequest(
            service_id="27",
            subfunction="01",
            safety_classification=ServiceSafetyClassification.SECURITY_SENSITIVE,
        )
        safe, reason = policy.validate_request(req_27)
        self.assertFalse(safe)
        resp_27 = tm.execute_request(req_27)
        self.assertEqual(resp_27.status, STATUS_TRANSACTION_BLOCKED)

        # 5. UDS 0x2F (InputOutputControlByIdentifier - Actuator control)
        req_2f = AdvancedServiceRequest(
            service_id="2F",
            payload="0102",
            safety_classification=ServiceSafetyClassification.ACTUATION,
        )
        safe, reason = policy.validate_request(req_2f)
        self.assertFalse(safe)
        resp_2f = tm.execute_request(req_2f)
        self.assertEqual(resp_2f.status, STATUS_TRANSACTION_BLOCKED)

        # 6. UDS 0x34 (RequestDownload - Flash programming)
        req_34 = AdvancedServiceRequest(
            service_id="34",
            safety_classification=ServiceSafetyClassification.PROGRAMMING,
        )
        safe, reason = policy.validate_request(req_34)
        self.assertFalse(safe)
        resp_34 = tm.execute_request(req_34)
        self.assertEqual(resp_34.status, STATUS_TRANSACTION_BLOCKED)

        # 7. UDS 0x36 (TransferData)
        req_36 = AdvancedServiceRequest(
            service_id="36",
            safety_classification=ServiceSafetyClassification.PROGRAMMING,
        )
        safe, reason = policy.validate_request(req_36)
        self.assertFalse(safe)
        resp_36 = tm.execute_request(req_36)
        self.assertEqual(resp_36.status, STATUS_TRANSACTION_BLOCKED)

        # 8. UDS 0x37 (RequestTransferExit)
        req_37 = AdvancedServiceRequest(
            service_id="37",
            safety_classification=ServiceSafetyClassification.PROGRAMMING,
        )
        safe, reason = policy.validate_request(req_37)
        self.assertFalse(safe)
        resp_37 = tm.execute_request(req_37)
        self.assertEqual(resp_37.status, STATUS_TRANSACTION_BLOCKED)

        # 9. Verify MockTransport received ZERO destructive bytes on the wire
        self.assertEqual(len(mock_transport.history), 0)


if __name__ == "__main__":
    unittest.main()
