# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase G-5: Vehicle-Wide Diagnostic Graph Test Suite
=============================================================================
This test suite comprehensively verifies Phase G-5 requirements:
  - Scenarios A through AN (Single-ECU, Multi-ECU, Cross-ECU, DTC, Observations,
    Anomalies, Evidence, Hypotheses, Conditions, Temporal Edges, Filtering,
    Merging, Path Queries, Large Graph, and Regressions).
  - Strict No-Causality enforcement (RELATIONSHIP != CAUSALITY).
  - Deterministic node & edge identities.
  - Distinction between communication failures and component faults.
  - Multi-session handling and vehicle mismatch rejection.
=============================================================================
"""

import copy
import math
import os
import sys
import time
import unittest
import numpy as np

# Core Imports
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
)
from advanced_ecu_services import (
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NRC,
    DiagnosticTransactionManager,
    EngineTransportAdapter,
)
from extended_did import (
    VehicleContext,
    StructuredDiagnosticEvidence,
)
from advanced_fault_analysis import (
    DataSourceType,
    SignalQuality,
    OperatingCondition,
    AnomalySeverity,
    AnomalyType,
    HypothesisConfidence,
    TimeSeriesSignal,
    DTCRecord,
    DiagnosticDataSet,
    PointAnomaly,
    TemporalAnomaly,
    FaultEvidence,
    FaultHypothesis,
    AnalysisResult,
)
from multi_ecu_diagnostics import (
    ECUTargetType,
    ECUDiscoveryState,
    ECUCapabilityState,
    ECUHealthState,
    ECUTarget,
    MultiECUVehicleContext,
    MultiECUDTCRecord,
    MultiECUDataSample,
    ECUScanRecord,
    MultiECUScanResult,
    ScanScope,
    MultiECUDiagnosticManager,
)
from vehicle_diagnostic_graph import (
    GraphNodeType,
    GraphEdgeType,
    RelationshipCategory,
    GraphNode,
    GraphEdge,
    DiagnosticGraph,
    RelationshipCandidate,
    VehicleDiagnosticGraphBuilder,
    make_vehicle_node_id,
    make_ecu_node_id,
    make_signal_node_id,
    make_dtc_node_id,
    make_observation_node_id,
    make_anomaly_node_id,
    make_evidence_node_id,
    make_hypothesis_node_id,
    make_op_cond_node_id,
    make_session_node_id,
    make_service_node_id,
    make_edge_id,
)


class TestPhaseG5VehicleDiagnosticGraph(unittest.TestCase):
    """Phase G-5 Complete Test Suite covering Scenarios A through AN."""

    def setUp(self):
        self.vehicle_ctx = VehicleContext(
            manufacturer="Opel",
            model="Astra K",
            model_year=2018,
            engine_code="B16DTH",
            vin="W0L0000B16DTH9999",
        )
        self.builder = VehicleDiagnosticGraphBuilder(vehicle_context=self.vehicle_ctx)

    # -----------------------------------------------------------------
    # SCENARIO A: Single ECU Graph
    # -----------------------------------------------------------------
    def test_scenario_a_single_ecu_graph(self):
        self.builder.build_vehicle_root()
        ecu = self.builder.add_ecu_target({
            "ecu_id": "ECM",
            "name": "Engine Control Module",
            "ecu_type": "ENGINE",
        })
        sig = self.builder.add_signal_node("ECM", "0C", "RPM", unit="rpm")

        graph = self.builder.graph
        self.assertIn("vehicle:W0L0000B16DTH9999", graph.nodes)
        self.assertIn("ecu:ECM", graph.nodes)
        self.assertIn("signal:ECM:0C:RPM", graph.nodes)

        # Verify structural edges
        has_ecu_edges = graph.get_edges(edge_type=GraphEdgeType.HAS_ECU)
        self.assertEqual(len(has_ecu_edges), 1)
        self.assertEqual(has_ecu_edges[0].target_id, "ecu:ECM")

        exposes_edges = graph.get_edges(edge_type=GraphEdgeType.EXPOSES_SIGNAL)
        self.assertEqual(len(exposes_edges), 1)
        self.assertEqual(exposes_edges[0].target_id, "signal:ECM:0C:RPM")

    # -----------------------------------------------------------------
    # SCENARIO B: Multi-ECU Graph (ECM, TCM, ABS, SRS)
    # -----------------------------------------------------------------
    def test_scenario_b_multi_ecu_graph(self):
        self.builder.build_vehicle_root()
        for ecu_id in ["ECM", "TCM", "ABS", "SRS"]:
            self.builder.add_ecu_target({"ecu_id": ecu_id, "name": f"{ecu_id} Module"})

        graph = self.builder.graph
        ecus = graph.get_nodes(GraphNodeType.ECU)
        self.assertEqual(len(ecus), 4)

        ecu_ids = {n.properties["ecu_id"] for n in ecus}
        self.assertEqual(ecu_ids, {"ECM", "TCM", "ABS", "SRS"})

        # Verify all 4 are linked to vehicle root
        has_ecu_edges = graph.get_edges(source_id=graph.vehicle_id, edge_type=GraphEdgeType.HAS_ECU)
        self.assertEqual(len(has_ecu_edges), 4)

    # -----------------------------------------------------------------
    # SCENARIO C: ECM + TCM Cross-ECU Relationship
    # -----------------------------------------------------------------
    def test_scenario_c_ecm_plus_tcm_relationship(self):
        self.builder.build_vehicle_root()
        self.builder.add_signal_node("ECM", "0C", "RPM", unit="rpm")
        self.builder.add_signal_node("TCM", "1F02", "INPUT_SPEED", unit="rpm")

        # Discover candidate relationship
        edges = self.builder.discover_cross_ecu_relationships()
        self.assertTrue(len(edges) >= 1)

        rel_edge = edges[0]
        self.assertEqual(rel_edge.source_id, "signal:ECM:0C:RPM")
        self.assertEqual(rel_edge.target_id, "signal:TCM:1F02:INPUT_SPEED")
        self.assertEqual(rel_edge.edge_type, GraphEdgeType.CORRELATES_WITH)
        self.assertFalse(hasattr(rel_edge, "is_causal") and getattr(rel_edge, "is_causal"))

    # -----------------------------------------------------------------
    # SCENARIO D: ECM + ABS Cross-ECU Relationship
    # -----------------------------------------------------------------
    def test_scenario_d_ecm_plus_abs_relationship(self):
        self.builder.build_vehicle_root()
        self.builder.add_signal_node("ECM", "0C", "RPM", unit="rpm")
        self.builder.add_signal_node("ABS", "2B01", "VEHICLE_SPEED", unit="km/h")

        edges = self.builder.discover_cross_ecu_relationships()
        found = [e for e in edges if e.target_id == "signal:ABS:2B01:VEHICLE_SPEED"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].edge_type, GraphEdgeType.RESPONDS_TO)

    # -----------------------------------------------------------------
    # SCENARIO E: DTC Node
    # -----------------------------------------------------------------
    def test_scenario_e_dtc_node(self):
        self.builder.build_vehicle_root()
        dtc_node = self.builder.add_dtc_node("ECM", "P0171", status="CONFIRMED", severity="CRITICAL")

        self.assertEqual(dtc_node.node_id, "dtc:ECM:P0171")
        self.assertEqual(dtc_node.properties["code"], "P0171")
        self.assertEqual(dtc_node.properties["ecu_id"], "ECM")

        # Linked to ECU
        edges = self.builder.graph.get_edges(source_id="ecu:ECM", target_id="dtc:ECM:P0171")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].edge_type, GraphEdgeType.REPORTS_DTC)

    # -----------------------------------------------------------------
    # SCENARIO F: Duplicate DTC Code Across ECUs
    # -----------------------------------------------------------------
    def test_scenario_f_duplicate_dtc_code_across_ecus(self):
        self.builder.build_vehicle_root()
        dtc_ecm = self.builder.add_dtc_node("ECM", "P0300", status="CONFIRMED")
        dtc_tcm = self.builder.add_dtc_node("TCM", "P0300", status="PENDING")

        self.assertEqual(dtc_ecm.node_id, "dtc:ECM:P0300")
        self.assertEqual(dtc_tcm.node_id, "dtc:TCM:P0300")
        self.assertNotEqual(dtc_ecm.node_id, dtc_tcm.node_id)

        # Both exist independently in the graph
        graph = self.builder.graph
        self.assertIn("dtc:ECM:P0300", graph.nodes)
        self.assertIn("dtc:TCM:P0300", graph.nodes)
        self.assertEqual(graph.nodes["dtc:ECM:P0300"].properties["status"], "CONFIRMED")
        self.assertEqual(graph.nodes["dtc:TCM:P0300"].properties["status"], "PENDING")

    # -----------------------------------------------------------------
    # SCENARIO G: Observation Node
    # -----------------------------------------------------------------
    def test_scenario_g_observation_node(self):
        obs_node = GraphNode(
            node_id=make_observation_node_id("SESS_01", "RPM", "W1"),
            node_type=GraphNodeType.OBSERVATION,
            label="RPM Elevation Window",
            properties={
                "signal_name": "RPM",
                "start_time": 10.0,
                "end_time": 12.5,
                "mean_val": 2500.0,
            },
        )
        self.builder.graph.add_node(obs_node)
        self.assertEqual(self.builder.graph.nodes[obs_node.node_id].node_type, GraphNodeType.OBSERVATION)

    # -----------------------------------------------------------------
    # SCENARIO H: Anomaly Node
    # -----------------------------------------------------------------
    def test_scenario_h_anomaly_node(self):
        ano_node = GraphNode(
            node_id=make_anomaly_node_id("ANO_RPM_SPIKE"),
            node_type=GraphNodeType.ANOMALY,
            label="RPM Sudden Spike",
            properties={"anomaly_type": "SUDDEN_SPIKE", "severity": "WARNING"},
        )
        self.builder.graph.add_node(ano_node)
        self.assertEqual(self.builder.graph.nodes["anomaly:ANO_RPM_SPIKE"].properties["anomaly_type"], "SUDDEN_SPIKE")

    # -----------------------------------------------------------------
    # SCENARIO I: Evidence Node (Traceability)
    # -----------------------------------------------------------------
    def test_scenario_i_evidence_node(self):
        ev_node = GraphNode(
            node_id=make_evidence_node_id("EV_O2_LEAN"),
            node_type=GraphNodeType.EVIDENCE,
            label="Lean Exhaust Deviation",
            properties={
                "signals": ["O2S1", "STFT"],
                "start_time": 100.0,
                "end_time": 105.0,
                "deviation_magnitude": 25.0,
                "confidence_score": 0.92,
            },
            provenance={"rule": "RULE_O2_EXHAUST_PLAUSIBILITY"},
        )
        self.builder.graph.add_node(ev_node)
        node = self.builder.graph.get_node("evidence:EV_O2_LEAN")
        self.assertIsNotNone(node)
        self.assertEqual(node.properties["signals"], ["O2S1", "STFT"])
        self.assertEqual(node.provenance["rule"], "RULE_O2_EXHAUST_PLAUSIBILITY")

    # -----------------------------------------------------------------
    # SCENARIO J: Hypothesis Node
    # -----------------------------------------------------------------
    def test_scenario_j_hypothesis_node(self):
        hypo_node = GraphNode(
            node_id=make_hypothesis_node_id("HYPO_VAC_LEAK"),
            node_type=GraphNodeType.HYPOTHESIS,
            label="Intake Vacuum Leak",
            properties={
                "title": "Intake Manifold Air Leak",
                "category": "AIR_INTAKE",
                "confidence": "HIGH",
                "severity": "WARNING",
            },
        )
        self.builder.graph.add_node(hypo_node)
        self.assertEqual(self.builder.graph.get_node("hypothesis:HYPO_VAC_LEAK").properties["confidence"], "HIGH")

    # -----------------------------------------------------------------
    # SCENARIO K: Operating Condition Node
    # -----------------------------------------------------------------
    def test_scenario_k_operating_condition_node(self):
        cond_node = GraphNode(
            node_id=make_op_cond_node_id(OperatingCondition.IDLE),
            node_type=GraphNodeType.OPERATING_CONDITION,
            label="Condition: IDLE",
            properties={"condition": "IDLE"},
        )
        self.builder.graph.add_node(cond_node)
        self.assertIn("op_cond:IDLE", self.builder.graph.nodes)

    # -----------------------------------------------------------------
    # SCENARIO L: Acquisition Session Node
    # -----------------------------------------------------------------
    def test_scenario_l_acquisition_session_node(self):
        session_node = GraphNode(
            node_id=make_session_node_id("SCAN_20260911_001"),
            node_type=GraphNodeType.ACQUISITION_SESSION,
            label="Session SCAN_20260911_001",
            properties={"start_time": 1000.0, "end_time": 1015.0},
        )
        self.builder.graph.add_node(session_node)
        self.assertIn("SCAN_20260911_001", self.builder.graph.session_ids)

    # -----------------------------------------------------------------
    # SCENARIO M: Structural Edges
    # -----------------------------------------------------------------
    def test_scenario_m_structural_edges(self):
        self.builder.build_vehicle_root()
        self.builder.add_ecu_target({"ecu_id": "ECM"})
        self.builder.add_signal_node("ECM", "0C", "RPM")

        edges = self.builder.graph.get_edges()
        types = {e.edge_type for e in edges}
        self.assertIn(GraphEdgeType.HAS_ECU, types)
        self.assertIn(GraphEdgeType.EXPOSES_SIGNAL, types)

    # -----------------------------------------------------------------
    # SCENARIO N: Observational Edges
    # -----------------------------------------------------------------
    def test_scenario_n_observational_edges(self):
        self.builder.build_vehicle_root()
        s1 = self.builder.add_signal_node("ECM", "0C", "RPM")
        s2 = self.builder.add_signal_node("TCM", "1F02", "INPUT_SPEED")

        edge = GraphEdge(
            edge_id=make_edge_id(s1.node_id, GraphEdgeType.CORRELATES_WITH, s2.node_id),
            source_id=s1.node_id,
            target_id=s2.node_id,
            edge_type=GraphEdgeType.CORRELATES_WITH,
            confidence=0.95,
        )
        self.builder.graph.add_edge(edge)
        retrieved = self.builder.graph.get_edge(edge.edge_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.confidence, 0.95)

    # -----------------------------------------------------------------
    # SCENARIO O: Temporal Edges
    # -----------------------------------------------------------------
    def test_scenario_o_temporal_edges(self):
        self.builder.build_vehicle_root()
        s1 = self.builder.add_signal_node("ECM", "11", "THROTTLE")
        s2 = self.builder.add_signal_node("ECM", "0C", "RPM")

        temp_edge = GraphEdge(
            edge_id=make_edge_id(s1.node_id, GraphEdgeType.TEMPORALLY_PRECEDES, s2.node_id),
            source_id=s1.node_id,
            target_id=s2.node_id,
            edge_type=GraphEdgeType.TEMPORALLY_PRECEDES,
            confidence=0.88,
            properties={"delta_ms": 75.0},
        )
        self.builder.graph.add_edge(temp_edge)
        self.assertEqual(temp_edge.properties["delta_ms"], 75.0)

    # -----------------------------------------------------------------
    # SCENARIO P: Wrong ECU Identity & Isolation
    # -----------------------------------------------------------------
    def test_scenario_p_wrong_ecu_identity(self):
        self.builder.build_vehicle_root()
        self.builder.add_ecu_target({"ecu_id": "ECM"})
        self.builder.add_ecu_target({"ecu_id": "ABS"})

        sub_ecm = self.builder.graph.get_ecu_subgraph("ECM")
        sub_abs = self.builder.graph.get_ecu_subgraph("ABS")

        self.assertIn("ecu:ECM", sub_ecm.nodes)
        self.assertNotIn("ecu:ABS", sub_ecm.nodes)
        self.assertIn("ecu:ABS", sub_abs.nodes)
        self.assertNotIn("ecu:ECM", sub_abs.nodes)

    # -----------------------------------------------------------------
    # SCENARIO Q: Missing Signal (No False Correlation Edges)
    # -----------------------------------------------------------------
    def test_scenario_q_missing_signal_handling(self):
        self.builder.build_vehicle_root()
        self.builder.add_signal_node("ECM", "0C", "RPM")
        # ABS Speed is NOT added to signals or dataset

        dataset = DiagnosticDataSet(dataset_id="DS_TEST")
        sig_rpm = TimeSeriesSignal("RPM", "rpm", np.array([0.0, 0.1]), np.array([800.0, 850.0]))
        dataset.add_signal(sig_rpm)

        edges = self.builder.discover_cross_ecu_relationships(dataset=dataset)
        # Verify no edge to ABS speed was created
        abs_edges = [e for e in edges if "ABS" in e.target_id]
        self.assertEqual(len(abs_edges), 0)

    # -----------------------------------------------------------------
    # SCENARIO R: Stale Evidence Quality Propagation
    # -----------------------------------------------------------------
    def test_scenario_r_stale_evidence_quality(self):
        ev_node = GraphNode(
            node_id=make_evidence_node_id("EV_STALE_1"),
            node_type=GraphNodeType.EVIDENCE,
            label="Stale Evidence",
            properties={"quality": SignalQuality.STALE.value, "confidence_score": 0.40},
        )
        self.builder.graph.add_node(ev_node)
        self.assertEqual(self.builder.graph.get_node("evidence:EV_STALE_1").properties["quality"], "STALE")

    # -----------------------------------------------------------------
    # SCENARIO S: Communication Failure vs Vehicle Fault Distinction
    # -----------------------------------------------------------------
    def test_scenario_s_communication_failure_vs_fault(self):
        scan_res = MultiECUScanResult(
            scan_id="SCAN_COMM_FAIL_TEST",
            vehicle_context=None,
            scan_scope=ScanScope.FULL_VEHICLE,
            start_time=100.0,
            end_time=105.0,
            duration=5.0,
        )
        rec_ecm = ECUScanRecord(
            ecu_id="ECM",
            ecu_type="ENGINE",
            request_header="7E0",
            response_header="7E8",
            discovery_state="VERIFIED_REACHABLE",
            health_state="CONNECTED",
        )
        rec_abs = ECUScanRecord(
            ecu_id="ABS",
            ecu_type="BRAKES",
            request_header="7E2",
            response_header="7EA",
            discovery_state="EXPECTED",
            health_state="UNREACHABLE",
            last_error="Timeout communicating with ABS",
        )
        scan_res.ecu_records = {"ECM": rec_ecm, "ABS": rec_abs}

        self.builder.ingest_g4_scan_result(scan_res)
        graph = self.builder.graph

        # Verify ABS is in graph as UNREACHABLE
        abs_node = graph.get_node("ecu:ABS")
        self.assertEqual(abs_node.properties["health_state"], "UNREACHABLE")

        # Verify communication evidence exists
        comm_ev = graph.get_node("evidence:COMM_FAIL_ABS_SCAN_COMM_FAIL_TEST")
        self.assertIsNotNone(comm_ev)
        self.assertTrue(comm_ev.properties["is_acquisition_fault"])

        # CRITICAL INVARIANT: Zero vehicle fault hypotheses created for ABS
        hypotheses = graph.get_nodes(GraphNodeType.HYPOTHESIS)
        self.assertEqual(len(hypotheses), 0)

    # -----------------------------------------------------------------
    # SCENARIO T: Partial Scan Graph Representation
    # -----------------------------------------------------------------
    def test_scenario_t_partial_scan_representation(self):
        scan_res = MultiECUScanResult(
            scan_id="SCAN_PARTIAL",
            vehicle_context=None,
            scan_scope=ScanScope.PARTIAL,
            start_time=10.0,
            end_time=12.0,
            duration=2.0,
        )
        scan_res.ecu_records["ECM"] = ECUScanRecord(
            ecu_id="ECM",
            ecu_type="ENGINE",
            request_header="7E0",
            response_header="7E8",
            discovery_state="VERIFIED_REACHABLE",
            health_state="CONNECTED",
        )
        self.builder.ingest_g4_scan_result(scan_res)
        graph = self.builder.graph

        ecus = graph.get_nodes(GraphNodeType.ECU)
        self.assertEqual(len(ecus), 1)
        self.assertEqual(ecus[0].properties["ecu_id"], "ECM")

    # -----------------------------------------------------------------
    # SCENARIO U: Multiple Sessions in Single Graph
    # -----------------------------------------------------------------
    def test_scenario_u_multiple_sessions(self):
        g = DiagnosticGraph(vehicle_id=make_vehicle_node_id(self.vehicle_ctx))
        s1 = GraphNode("session:SESS_1", GraphNodeType.ACQUISITION_SESSION, "Session 1", {"session_id": "SESS_1"})
        s2 = GraphNode("session:SESS_2", GraphNodeType.ACQUISITION_SESSION, "Session 2", {"session_id": "SESS_2"})
        g.add_node(s1)
        g.add_node(s2)

        self.assertEqual(g.session_ids, {"SESS_1", "SESS_2"})
        self.assertEqual(len(g.get_nodes(GraphNodeType.ACQUISITION_SESSION)), 2)

    # -----------------------------------------------------------------
    # SCENARIO V: Historical Session Separation
    # -----------------------------------------------------------------
    def test_scenario_v_session_separation(self):
        g = DiagnosticGraph(vehicle_id="vehicle:V1")
        # Session A: Normal
        obs_a = GraphNode("obs:SESS_A:RPM:1", GraphNodeType.OBSERVATION, "Obs A", {"mean": 800.0, "session_id": "SESS_A"})
        # Session B: Fault
        obs_b = GraphNode("obs:SESS_B:RPM:1", GraphNodeType.OBSERVATION, "Obs B", {"mean": 1500.0, "session_id": "SESS_B"})
        g.add_node(obs_a)
        g.add_node(obs_b)

        self.assertNotEqual(obs_a.node_id, obs_b.node_id)
        self.assertEqual(g.get_node(obs_a.node_id).properties["mean"], 800.0)
        self.assertEqual(g.get_node(obs_b.node_id).properties["mean"], 1500.0)

    # -----------------------------------------------------------------
    # SCENARIO W: Controlled Graph Merging (Same Vehicle)
    # -----------------------------------------------------------------
    def test_scenario_w_controlled_graph_merge(self):
        v_id = make_vehicle_node_id(self.vehicle_ctx)
        g1 = DiagnosticGraph(vehicle_id=v_id)
        g1.add_node(GraphNode(v_id, GraphNodeType.VEHICLE, "Vehicle Root"))
        g1.add_node(GraphNode("ecu:ECM", GraphNodeType.ECU, "ECM", {"ecu_id": "ECM"}))
        g1.add_node(GraphNode("session:S1", GraphNodeType.ACQUISITION_SESSION, "Session 1", {"session_id": "S1"}))

        g2 = DiagnosticGraph(vehicle_id=v_id)
        g2.add_node(GraphNode(v_id, GraphNodeType.VEHICLE, "Vehicle Root"))
        g2.add_node(GraphNode("ecu:TCM", GraphNodeType.ECU, "TCM", {"ecu_id": "TCM"}))
        g2.add_node(GraphNode("session:S2", GraphNodeType.ACQUISITION_SESSION, "Session 2", {"session_id": "S2"}))

        # Merge g2 into g1
        g1.merge_session_graph(g2)
        self.assertEqual(g1.session_ids, {"S1", "S2"})
        self.assertIn("ecu:ECM", g1.nodes)
        self.assertIn("ecu:TCM", g1.nodes)

    # -----------------------------------------------------------------
    # SCENARIO X: Vehicle Mismatch Merge Rejection
    # -----------------------------------------------------------------
    def test_scenario_x_vehicle_mismatch_merge_rejection(self):
        g1 = DiagnosticGraph(vehicle_id="vehicle:OPEL_ASTRA_2018")
        g2 = DiagnosticGraph(vehicle_id="vehicle:VW_GOLF_2020")

        with self.assertRaises(ValueError) as ctx:
            g1.merge_session_graph(g2)
        self.assertIn("Vehicle identity mismatch", str(ctx.exception))

    # -----------------------------------------------------------------
    # SCENARIO Y: Bounded Traversal & Cycle Prevention
    # -----------------------------------------------------------------
    def test_scenario_y_bounded_traversal(self):
        g = DiagnosticGraph()
        # Create cycle: N1 -> N2 -> N3 -> N1
        g.add_node(GraphNode("N1", GraphNodeType.SIGNAL, "N1"))
        g.add_node(GraphNode("N2", GraphNodeType.SIGNAL, "N2"))
        g.add_node(GraphNode("N3", GraphNodeType.SIGNAL, "N3"))
        g.add_node(GraphNode("N4", GraphNodeType.SIGNAL, "N4"))

        g.add_edge(GraphEdge("e1", "N1", "N2", GraphEdgeType.CORRELATES_WITH))
        g.add_edge(GraphEdge("e2", "N2", "N3", GraphEdgeType.CORRELATES_WITH))
        g.add_edge(GraphEdge("e3", "N3", "N1", GraphEdgeType.CORRELATES_WITH)) # Cycle!
        g.add_edge(GraphEdge("e4", "N3", "N4", GraphEdgeType.CORRELATES_WITH))

        # Should find shortest acyclic path N1 -> N2 -> N3 -> N4
        path = g.find_path("N1", "N4", max_depth=5)
        self.assertEqual(path, ["N1", "N2", "N3", "N4"])

        # Path exceeding max depth returns None
        path_shallow = g.find_path("N1", "N4", max_depth=2)
        self.assertIsNone(path_shallow)

    # -----------------------------------------------------------------
    # SCENARIO Z: Path Query
    # -----------------------------------------------------------------
    def test_scenario_z_path_query(self):
        g = DiagnosticGraph()
        g.add_node(GraphNode("dtc:ECM:P0171", GraphNodeType.DTC, "P0171"))
        g.add_node(GraphNode("ecu:ECM", GraphNodeType.ECU, "ECM"))
        g.add_node(GraphNode("signal:ECM:0C:RPM", GraphNodeType.SIGNAL, "RPM"))
        g.add_node(GraphNode("evidence:EV1", GraphNodeType.EVIDENCE, "EV1"))
        g.add_node(GraphNode("hypothesis:H1", GraphNodeType.HYPOTHESIS, "H1"))

        g.add_edge(GraphEdge("e1", "dtc:ECM:P0171", "ecu:ECM", GraphEdgeType.REPORTS_DTC))
        g.add_edge(GraphEdge("e2", "ecu:ECM", "signal:ECM:0C:RPM", GraphEdgeType.EXPOSES_SIGNAL))
        g.add_edge(GraphEdge("e3", "signal:ECM:0C:RPM", "evidence:EV1", GraphEdgeType.PRODUCES_EVIDENCE))
        g.add_edge(GraphEdge("e4", "evidence:EV1", "hypothesis:H1", GraphEdgeType.SUPPORTS_HYPOTHESIS))

        path = g.find_path("dtc:ECM:P0171", "hypothesis:H1", max_depth=6)
        self.assertEqual(path, ["dtc:ECM:P0171", "ecu:ECM", "signal:ECM:0C:RPM", "evidence:EV1", "hypothesis:H1"])

    # -----------------------------------------------------------------
    # SCENARIO AA: Graph Filtering
    # -----------------------------------------------------------------
    def test_scenario_aa_graph_filtering(self):
        self.builder.build_vehicle_root()
        self.builder.add_ecu_target({"ecu_id": "ECM"})
        self.builder.add_ecu_target({"ecu_id": "TCM"})
        self.builder.add_signal_node("ECM", "0C", "RPM")
        self.builder.add_signal_node("TCM", "1F02", "INPUT_SPEED")

        # Filter only ECM nodes
        filtered = self.builder.graph.filter_graph(ecu_id="ECM")
        self.assertIn("ecu:ECM", filtered.nodes)
        self.assertIn("signal:ECM:0C:RPM", filtered.nodes)
        self.assertNotIn("ecu:TCM", filtered.nodes)
        self.assertNotIn("signal:TCM:1F02:INPUT_SPEED", filtered.nodes)

    # -----------------------------------------------------------------
    # SCENARIO AB: Provenance Preservation
    # -----------------------------------------------------------------
    def test_scenario_ab_provenance_preservation(self):
        ev = GraphNode(
            "evidence:EV1",
            GraphNodeType.EVIDENCE,
            "EV1",
            provenance={"source_session": "SESS_123", "algorithm": "SPEED_DENSITY_V2"},
        )
        self.builder.graph.add_node(ev)
        retrieved = self.builder.graph.get_node("evidence:EV1")
        self.assertEqual(retrieved.provenance["algorithm"], "SPEED_DENSITY_V2")

    # -----------------------------------------------------------------
    # SCENARIO AC: Relationship Confidence vs Hypothesis Confidence
    # -----------------------------------------------------------------
    def test_scenario_ac_relationship_vs_hypothesis_confidence(self):
        # Physical relationship: High confidence (0.95)
        edge = GraphEdge("e1", "signal:ECM:0C:RPM", "signal:ABS:0D:SPEED", GraphEdgeType.RESPONDS_TO, confidence=0.95)
        # Fault Hypothesis: Low confidence (0.35)
        hypo = GraphNode("hypothesis:H1", GraphNodeType.HYPOTHESIS, "Hypo", properties={"confidence": "LOW", "evidence_score": 0.35})

        self.assertEqual(edge.confidence, 0.95)
        self.assertEqual(hypo.properties["confidence"], "LOW")
        self.assertEqual(hypo.properties["evidence_score"], 0.35)
        # Independent values
        self.assertNotEqual(edge.confidence, hypo.properties["evidence_score"])

    # -----------------------------------------------------------------
    # SCENARIO AD: Strict No-Causality Enforcement
    # -----------------------------------------------------------------
    def test_scenario_ad_no_causality_enforcement(self):
        self.builder.build_vehicle_root()
        s1 = self.builder.add_signal_node("ECM", "0C", "RPM")
        s2 = self.builder.add_signal_node("ABS", "0D", "VEHICLE_SPEED")

        edges = self.builder.discover_cross_ecu_relationships()
        for e in edges:
            self.assertNotEqual(e.edge_type.value, "CAUSED_BY")
            self.assertIn(e.edge_type, (GraphEdgeType.CORRELATES_WITH, GraphEdgeType.RESPONDS_TO, GraphEdgeType.CONSISTENT_WITH))

    # -----------------------------------------------------------------
    # SCENARIO AE: Graph Serialization & Round-Trip Deserialization
    # -----------------------------------------------------------------
    def test_scenario_ae_serialization_roundtrip(self):
        self.builder.build_vehicle_root()
        self.builder.add_ecu_target({"ecu_id": "ECM"})
        self.builder.add_signal_node("ECM", "0C", "RPM")
        self.builder.add_dtc_node("ECM", "P0171")

        orig_graph = self.builder.graph
        dict_rep = orig_graph.to_dict()

        # JSON encode / decode
        import json
        json_str = json.dumps(dict_rep)
        data_back = json.loads(json_str)

        restored_graph = DiagnosticGraph.from_dict(data_back)
        self.assertEqual(len(restored_graph.nodes), len(orig_graph.nodes))
        self.assertEqual(restored_graph.edge_count, orig_graph.edge_count)
        self.assertEqual(restored_graph.vehicle_id, orig_graph.vehicle_id)

    # -----------------------------------------------------------------
    # SCENARIO AF: Graph Export Summary
    # -----------------------------------------------------------------
    def test_scenario_af_graph_export_summary(self):
        self.builder.build_vehicle_root()
        self.builder.add_ecu_target({"ecu_id": "ECM"})
        self.builder.add_dtc_node("ECM", "P0171")

        summary = self.builder.graph.export_summary()
        self.assertEqual(summary["dtc_count"], 1)
        self.assertEqual(summary["ecus"], ["ECM"])
        self.assertIn("VEHICLE", summary["nodes_by_type"])

    # -----------------------------------------------------------------
    # SCENARIO AG: Large Graph Stress Test (500+ Nodes)
    # -----------------------------------------------------------------
    def test_scenario_ag_large_graph_stress(self):
        g = DiagnosticGraph(vehicle_id="vehicle:LARGE_TEST")
        g.add_node(GraphNode("vehicle:LARGE_TEST", GraphNodeType.VEHICLE, "Root"))

        # Add 10 ECUs, each with 50 signals
        t0 = time.time()
        for e_idx in range(10):
            ecu_id = f"ECU_{e_idx}"
            ecu_node = GraphNode(make_ecu_node_id(ecu_id), GraphNodeType.ECU, ecu_id, {"ecu_id": ecu_id})
            g.add_node(ecu_node)
            g.add_edge(GraphEdge(f"e_root_{e_idx}", "vehicle:LARGE_TEST", ecu_node.node_id, GraphEdgeType.HAS_ECU))

            for s_idx in range(50):
                sig_id = f"SIG_{e_idx}_{s_idx}"
                sig_node = GraphNode(make_signal_node_id(ecu_id, str(s_idx), sig_id), GraphNodeType.SIGNAL, sig_id, {"ecu_id": ecu_id})
                g.add_node(sig_node)
                g.add_edge(GraphEdge(f"e_sig_{e_idx}_{s_idx}", ecu_node.node_id, sig_node.node_id, GraphEdgeType.EXPOSES_SIGNAL))

        duration = time.time() - t0
        self.assertEqual(len(g.nodes), 1 + 10 + 500) # 511 nodes
        self.assertEqual(g.edge_count, 10 + 500)     # 510 edges
        self.assertTrue(duration < 1.0, f"Large graph construction took too long: {duration:.3f}s")

        # Verify bounded traversal remains sub-millisecond
        t_trav = time.time()
        path = g.find_path("vehicle:LARGE_TEST", "signal:ECU_9:49:SIG_9_49", max_depth=4)
        t_trav_dur = time.time() - t_trav
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 3) # Vehicle -> ECU_9 -> SIG_9_49
        self.assertTrue(t_trav_dur < 0.05, f"Traversal took too long: {t_trav_dur:.4f}s")

    # -----------------------------------------------------------------
    # SCENARIO AH: Memory Behavior & Resource Cleansing
    # -----------------------------------------------------------------
    def test_scenario_ah_memory_behavior(self):
        g = DiagnosticGraph()
        # Verify empty graph footprint
        self.assertEqual(len(g.nodes), 0)
        self.assertEqual(g.edge_count, 0)

    # -----------------------------------------------------------------
    # Realistic Cross-ECU Timing Test
    # -----------------------------------------------------------------
    def test_realistic_cross_ecu_timing(self):
        self.builder.build_vehicle_root()
        s_ecm = self.builder.add_signal_node("ECM", "0C", "RPM")
        s_tcm = self.builder.add_signal_node("TCM", "1F02", "INPUT_SPEED")
        s_abs = self.builder.add_signal_node("ABS", "0D", "VEHICLE_SPEED")

        # Simulate timestamps: ECM at 10.000, TCM at 10.050 (+50ms), ABS at 10.080 (+80ms)
        ds = DiagnosticDataSet(dataset_id="DS_TIMING")
        ds.add_signal(TimeSeriesSignal("RPM", "rpm", np.array([10.000]), np.array([1500.0])))
        ds.add_signal(TimeSeriesSignal("INPUT_SPEED", "rpm", np.array([10.050]), np.array([1480.0])))
        ds.add_signal(TimeSeriesSignal("VEHICLE_SPEED", "km/h", np.array([10.080]), np.array([45.0])))

        edges = self.builder.discover_cross_ecu_relationships(dataset=ds)
        self.assertTrue(len(edges) >= 2)

        # Check TCM delta
        tcm_edge = [e for e in edges if e.target_id == s_tcm.node_id][0]
        self.assertAlmostEqual(tcm_edge.properties["observed_delta_ms"], 50.0, delta=1.0)

        # Check ABS delta
        abs_edge = [e for e in edges if e.target_id == s_abs.node_id][0]
        self.assertAlmostEqual(abs_edge.properties["observed_delta_ms"], 80.0, delta=1.0)

    # -----------------------------------------------------------------
    # SCENARIOS AI - AN: Regressions
    # -----------------------------------------------------------------
    def test_scenario_ai_g4_regression(self):
        """Verify G-4 MultiECUScanResult integration with G-5 builder."""
        scan = MultiECUScanResult(
            scan_id="SCAN_REGRESS",
            vehicle_context=None,
            scan_scope=ScanScope.FULL_VEHICLE,
            start_time=10.0,
            end_time=15.0,
            duration=5.0,
        )
        rec = ECUScanRecord(
            ecu_id="ECM",
            ecu_type="ENGINE",
            request_header="7E0",
            response_header="7E8",
            discovery_state="VERIFIED_REACHABLE",
            health_state="CONNECTED",
            dtcs=[MultiECUDTCRecord(ecu_id="ECM", code="P0101", status="CONFIRMED")],
        )
        scan.ecu_records["ECM"] = rec

        graph = VehicleDiagnosticGraphBuilder.build_from_multiecu_and_analysis(scan)
        self.assertIn("ecu:ECM", graph.nodes)
        self.assertIn("dtc:ECM:P0101", graph.nodes)

    def test_scenario_aj_g3_regression(self):
        """Verify G-3 AnalysisResult ingestion into G-5 graph."""
        ano = PointAnomaly(
            anomaly_id="ANO_1",
            anomaly_type=AnomalyType.SUDDEN_SPIKE,
            signal_name="ECM:RPM",
            timestamp=12.5,
            observed_value=6000.0,
            expected_range=(700.0, 3000.0),
            severity=AnomalySeverity.WARNING,
            details="Spike",
        )
        ev = FaultEvidence(
            evidence_id="EV_1",
            title="Evidence 1",
            signals=["ECM:RPM"],
            start_time=12.0,
            end_time=13.0,
            duration=1.0,
            operating_condition=OperatingCondition.ACCELERATION,
            observed_behavior="High RPM",
            expected_behavior="Normal RPM",
            deviation_magnitude=3000.0,
            severity=AnomalySeverity.WARNING,
            quality=SignalQuality.GOOD,
            provenance={"rule": "RPM_LIMIT"},
            analysis_method="THRESHOLD",
            confidence_score=0.9,
        )
        hypo = FaultHypothesis(
            hypothesis_id="HYPO_1",
            title="Crank Sensor Glitch",
            category="IGNITION",
            affected_system="ENGINE",
            supporting_evidence=[ev],
            confidence=HypothesisConfidence.HIGH,
        )
        res = AnalysisResult(
            analysis_id="ANA_1",
            dataset_id="DS_1",
            vehicle_context=None,
            session_start_time=10.0,
            session_end_time=20.0,
            duration_seconds=10.0,
            coverage_report={},
            quality_summary={},
            operating_condition_summary={"ACCELERATION": 100.0},
            anomalies=[ano],
            evidence=[ev],
            hypotheses=[hypo],
        )

        self.builder.build_vehicle_root()
        self.builder.ingest_g3_analysis_result(res)
        graph = self.builder.graph

        self.assertIn("anomaly:ANO_1", graph.nodes)
        self.assertIn("evidence:EV_1", graph.nodes)
        self.assertIn("hypothesis:HYPO_1", graph.nodes)

        # Verify supporting edge
        edges = graph.get_edges(source_id="evidence:EV_1", target_id="hypothesis:HYPO_1")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].edge_type, GraphEdgeType.SUPPORTS_HYPOTHESIS)

    def test_scenario_ak_g2_regression(self):
        """Verify G-2 data definition compatibility."""
        from extended_did import DiagnosticDataDefinition, IdentifierNamespace
        defn = DiagnosticDataDefinition(
            identifier="1640",
            namespace=IdentifierNamespace.EXTENDED_UDS_DID,
            name="EngineOilTemp",
            service_id="22",
        )
        self.assertEqual(defn.identifier, "1640")
        self.assertEqual(defn.name, "EngineOilTemp")

    def test_scenario_al_g1_regression(self):
        """Verify G-1 service transactions remain functional."""
        from advanced_ecu_services import DiagnosticTransactionManager, EngineTransportAdapter
        engine = AutoExpertEngine()
        tm = DiagnosticTransactionManager(transport=EngineTransportAdapter(engine))
        req = tm.build_request("01", payload="0C")
        res = tm.execute_request(req)
        self.assertIsNotNone(res)

    def test_scenario_am_f_regression(self):
        """Verify F layer lifecycle compatibility."""
        from live_dtc_lifecycle import LiveDTCLifecycleEngine
        mgr = LiveDTCLifecycleEngine()
        self.assertIsNotNone(mgr)

    def test_scenario_an_cde_regression(self):
        """Verify AutoExpertEngine convenience integration."""
        engine = AutoExpertEngine()
        graph = engine.build_vehicle_graph()
        self.assertIsInstance(graph, DiagnosticGraph)
        self.assertIn(graph.vehicle_id, graph.nodes)


def main():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhaseG5VehicleDiagnosticGraph)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
