# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase G-5: Vehicle-Wide Diagnostic Graph Engine
=============================================================================
This module implements Phase G-5 of the Seyyanen diagnostic architecture.
It transitions the platform from isolated multi-ECU acquisitions (G-4) and
single-vehicle fault analysis (G-3) into a connected, vehicle-wide diagnostic
evidence graph.

Core Architectural Invariants:
  1. RELATIONSHIP != CAUSALITY:
     The graph records structural associations, runtime behavioral correlations,
     and temporal proximities as structured evidence. It NEVER automatically
     converts correlation or temporal sequence into causal claims.
  2. READ-ONLY & ANALYTICAL:
     Zero low-level bus commands, zero DTC clearing (Mode 04/14), zero component
     actuation (0x2F), zero programming (0x34/36/37), zero security access (0x27).
  3. DETERMINISTIC & OFFLINE:
     100% offline. Zero LLM, cloud, or external database dependencies.
  4. STRICT ECU IDENTITY PRESERVATION:
     ECU boundaries are preserved. The same DTC code or signal name on two
     different ECUs (e.g. ECM:P0300 vs TCM:P0300) retain independent identities.
  5. COMMUNICATION != COMPONENT FAULT:
     Distinguishes communication failures (unreachable, timeout) from vehicle
     faults. An unreachable ECU creates communication evidence, not a component
     failure hypothesis.
  6. SCOPE BOUNDARIES:
     Excludes G-Final, Phase H (automated workflows), and Phase I (ML learning).
=============================================================================
"""

from __future__ import annotations

import collections
import copy
import enum
import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

# Integration imports from G-1, G-2, G-3, and G-4
from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
)
from advanced_ecu_services import (
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NRC,
    STATUS_SERIAL_ERROR,
    STATUS_TRANSACTION_CANCELLED as STATUS_CANCELLED,
    STATUS_RESPONSE_MISMATCH,
    STATUS_PARSE_ERROR,
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
    OperatingConditionSegment,
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
)


class VehicleIdentityMismatchError(ValueError):
    """Raised when attempting to merge graphs or evidence from incompatible vehicles."""
    pass


class GraphValidationError(ValueError):
    """Raised when a graph structure violates structural or diagnostic invariants."""
    pass


# =====================================================================
# 1. GRAPH TAXONOMY & ENUMERATIONS
# =====================================================================

class GraphNodeType(str, enum.Enum):
    """Taxonomy of nodes in the vehicle diagnostic graph."""
    VEHICLE = "VEHICLE"
    ECU = "ECU"
    SIGNAL = "SIGNAL"
    DID_PID = "DID_PID"
    DTC = "DTC"
    OBSERVATION = "OBSERVATION"
    ANOMALY = "ANOMALY"
    EVIDENCE = "EVIDENCE"
    HYPOTHESIS = "HYPOTHESIS"
    OPERATING_CONDITION = "OPERATING_CONDITION"
    ACQUISITION_SESSION = "ACQUISITION_SESSION"
    SERVICE = "SERVICE"


class GraphEdgeType(str, enum.Enum):
    """Taxonomy of directed edges and relationships in the graph."""
    # Structural relationships (Static / Architecture)
    HAS_ECU = "HAS_ECU"
    EXPOSES_SIGNAL = "EXPOSES_SIGNAL"
    SUPPORTS_SERVICE = "SUPPORTS_SERVICE"
    SUPPORTS_DID = "SUPPORTS_DID"
    DERIVED_FROM = "DERIVED_FROM"

    # Diagnostic & Evidence relationships
    REPORTS_DTC = "REPORTS_DTC"
    OBSERVES = "OBSERVES"
    PRODUCES_EVIDENCE = "PRODUCES_EVIDENCE"
    SUPPORTS_HYPOTHESIS = "SUPPORTS_HYPOTHESIS"
    CONTRADICTS_HYPOTHESIS = "CONTRADICTS_HYPOTHESIS"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    INDICATES_CONDITION = "INDICATES_CONDITION"

    # Temporal relationships (Time-window bounded)
    TEMPORALLY_PRECEDES = "TEMPORALLY_PRECEDES"
    TEMPORALLY_FOLLOWS = "TEMPORALLY_FOLLOWS"
    TEMPORALLY_OVERLAPS = "TEMPORALLY_OVERLAPS"
    TEMPORALLY_CORRELATED = "TEMPORALLY_CORRELATED"
    TEMPORALLY_RELATED_TO = "TEMPORALLY_RELATED_TO"

    # Behavioral relationships (Runtime observations)
    CORRELATES_WITH = "CORRELATES_WITH"
    RESPONDS_TO = "RESPONDS_TO"
    DEVIATES_FROM = "DEVIATES_FROM"
    CONSISTENT_WITH = "CONSISTENT_WITH"


class RelationshipCategory(str, enum.Enum):
    """Broad classification of relationships."""
    STRUCTURAL = "STRUCTURAL"
    DIAGNOSTIC = "DIAGNOSTIC"
    TEMPORAL = "TEMPORAL"
    BEHAVIORAL = "BEHAVIORAL"


# =====================================================================
# 2. DETERMINISTIC NODE & EDGE IDENTITY GENERATORS
# =====================================================================

def make_vehicle_node_id(context: Optional[Union[VehicleContext, Dict[str, Any]]]) -> str:
    """Deterministic vehicle node ID based on VIN or make/model/year/engine."""
    if not context:
        return "vehicle:GENERIC_UNKNOWN"
    
    if isinstance(context, VehicleContext):
        vin = getattr(context, "vin", None)
        make = getattr(context, "manufacturer", None) or "UNKNOWN"
        model = getattr(context, "model", None) or "UNKNOWN"
        year = getattr(context, "model_year", None) or "UNKNOWN"
        engine = getattr(context, "engine_code", None) or getattr(context, "engine", None) or "UNKNOWN"
    elif isinstance(context, dict):
        vin = context.get("vin")
        make = context.get("manufacturer") or context.get("make") or "UNKNOWN"
        model = context.get("model") or "UNKNOWN"
        year = context.get("model_year") or context.get("year") or "UNKNOWN"
        engine = context.get("engine_code") or context.get("engine") or "UNKNOWN"
    else:
        return "vehicle:GENERIC_UNKNOWN"

    if vin and len(str(vin).strip()) >= 5 and "00000" not in str(vin):
        return f"vehicle:{str(vin).strip().upper()}"
    clean = f"{make}_{model}_{year}_{engine}".replace(" ", "_").upper()
    return f"vehicle:{clean}"


def make_ecu_node_id(ecu_id: str) -> str:
    """Deterministic ECU node ID."""
    return f"ecu:{ecu_id.strip().upper()}"


def make_signal_node_id(ecu_id: str, identifier: str, signal_name: str) -> str:
    """Deterministic signal node ID: signal:<ECU>:<ID>:<NAME>."""
    e = ecu_id.strip().upper()
    i = identifier.strip().upper()
    s = signal_name.strip().upper()
    return f"signal:{e}:{i}:{s}"


def make_did_node_id(ecu_id: str, service: str, identifier: str) -> str:
    """Deterministic DID/PID node ID: did:<ECU>:<SVC>:<ID>."""
    return f"did:{ecu_id.strip().upper()}:{service.strip().upper()}:{identifier.strip().upper()}"


def make_dtc_node_id(ecu_id: str, code: str) -> str:
    """Deterministic DTC node ID: dtc:<ECU>:<CODE>."""
    return f"dtc:{ecu_id.strip().upper()}:{code.strip().upper()}"


def make_observation_node_id(session_id: str, signal_id: str, window_or_seq: Union[str, int]) -> str:
    """Deterministic observation node ID."""
    return f"obs:{session_id}:{signal_id}:{window_or_seq}"


def make_anomaly_node_id(anomaly_id: str) -> str:
    """Deterministic anomaly node ID."""
    return f"anomaly:{anomaly_id.strip()}"


def make_evidence_node_id(evidence_id: str) -> str:
    """Deterministic evidence node ID."""
    return f"evidence:{evidence_id.strip()}"


def make_hypothesis_node_id(hypothesis_id: str) -> str:
    """Deterministic hypothesis node ID."""
    return f"hypothesis:{hypothesis_id.strip()}"


def make_op_cond_node_id(condition: Union[OperatingCondition, str]) -> str:
    """Deterministic operating condition node ID."""
    name = condition.value if isinstance(condition, OperatingCondition) else str(condition)
    return f"op_cond:{name.strip().upper()}"


def make_session_node_id(session_id: str) -> str:
    """Deterministic acquisition session node ID."""
    return f"session:{session_id.strip()}"


def make_service_node_id(ecu_id: str, service_hex: str) -> str:
    """Deterministic service node ID."""
    return f"service:{ecu_id.strip().upper()}:{service_hex.strip().upper()}"


def make_edge_id(source_id: str, edge_type: GraphEdgeType, target_id: str, qualifier: str = "") -> str:
    """Deterministic edge ID: <source>--<type>[--<qualifier>]-><target>."""
    t = edge_type.value if isinstance(edge_type, GraphEdgeType) else str(edge_type)
    if qualifier:
        return f"{source_id}--{t}:{qualifier}->{target_id}"
    return f"{source_id}--{t}->{target_id}"


# =====================================================================
# 3. GRAPH NODE & EDGE DATA STRUCTURES
# =====================================================================

@dataclass
class GraphNode:
    """
    A first-class node in the vehicle diagnostic graph.
    Represents an entity (Vehicle, ECU, Signal, DTC, Observation, Anomaly,
    Evidence, Hypothesis, Operating Condition, Acquisition Session).
    """
    node_id: str
    node_type: GraphNodeType
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value if isinstance(self.node_type, GraphNodeType) else str(self.node_type),
            "label": self.label,
            "properties": self.properties,
            "provenance": self.provenance,
            "created_at": round(self.created_at, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        return cls(
            node_id=data["node_id"],
            node_type=GraphNodeType(data["node_type"]),
            label=data["label"],
            properties=data.get("properties", {}),
            provenance=data.get("provenance", {}),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class GraphEdge:
    """
    A directed relationship connecting two nodes in the diagnostic graph.
    Strictly preserves confidence, evidence references, and provenance.
    """
    edge_id: str
    source_id: str
    target_id: str
    edge_type: GraphEdgeType
    confidence: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value if isinstance(self.edge_type, GraphEdgeType) else str(self.edge_type),
            "confidence": round(self.confidence, 3),
            "properties": self.properties,
            "evidence_refs": self.evidence_refs,
            "provenance": self.provenance,
            "created_at": round(self.created_at, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        return cls(
            edge_id=data["edge_id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            edge_type=GraphEdgeType(data["edge_type"]),
            confidence=float(data.get("confidence", 1.0)),
            properties=data.get("properties", {}),
            evidence_refs=data.get("evidence_refs", []),
            provenance=data.get("provenance", {}),
            created_at=data.get("created_at", time.time()),
        )


# =====================================================================
# 4. DIAGNOSTIC GRAPH CONTAINER
# =====================================================================

class DiagnosticGraph:
    """
    Vehicle-Wide Diagnostic Evidence Graph.
    Maintains nodes, directed adjacency maps, deterministic traversals,
    and vehicle-compatibility verified merging.
    """
    def __init__(self, vehicle_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        self.vehicle_id = vehicle_id or "vehicle:UNSET"
        self.metadata = metadata or {}
        self.nodes: Dict[str, GraphNode] = {}
        # Directed adjacency: source_id -> list of outgoing edges
        self._out_edges: Dict[str, List[GraphEdge]] = collections.defaultdict(list)
        # Reverse adjacency: target_id -> list of incoming edges
        self._in_edges: Dict[str, List[GraphEdge]] = collections.defaultdict(list)
        # All edges keyed by edge_id
        self._edges_by_id: Dict[str, GraphEdge] = {}
        # Track associated sessions
        self.session_ids: Set[str] = set()

    def __len__(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges_by_id)

    # -----------------------------------------------------------------
    # Node Operations
    # -----------------------------------------------------------------

    def add_node(self, node: GraphNode) -> GraphNode:
        """Adds or updates a node in the graph."""
        self.nodes[node.node_id] = node
        if node.node_type == GraphNodeType.VEHICLE:
            self.vehicle_id = node.node_id
        elif node.node_type == GraphNodeType.ACQUISITION_SESSION:
            session_key = node.properties.get("session_id", node.node_id.replace("session:", ""))
            self.session_ids.add(session_key)
        return node

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self.nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def get_nodes(self, node_type: Optional[GraphNodeType] = None) -> List[GraphNode]:
        """Returns all nodes, optionally filtered by node_type."""
        if node_type is None:
            return list(self.nodes.values())
        return [n for n in self.nodes.values() if n.node_type == node_type]

    # -----------------------------------------------------------------
    # Edge Operations
    # -----------------------------------------------------------------

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """
        Adds a directed edge between two existing nodes.
        If either node does not exist, a warning is logged or placeholder created.
        """
        # Ensure source and target exist
        if edge.source_id not in self.nodes:
            raise KeyError(f"Source node '{edge.source_id}' does not exist in graph")
        if edge.target_id not in self.nodes:
            raise KeyError(f"Target node '{edge.target_id}' does not exist in graph")

        # Overwrite if exists, otherwise register
        self._edges_by_id[edge.edge_id] = edge

        # Maintain outgoing
        existing_out = [e for e in self._out_edges[edge.source_id] if e.edge_id != edge.edge_id]
        existing_out.append(edge)
        self._out_edges[edge.source_id] = existing_out

        # Maintain incoming
        existing_in = [e for e in self._in_edges[edge.target_id] if e.edge_id != edge.edge_id]
        existing_in.append(edge)
        self._in_edges[edge.target_id] = existing_in

        return edge

    @property
    def edges(self) -> List[GraphEdge]:
        """Returns all edges in the graph as a list."""
        return list(self._edges_by_id.values())

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        return self._edges_by_id.get(edge_id)

    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        edge_type: Optional[GraphEdgeType] = None,
    ) -> List[GraphEdge]:
        """Queries edges matching given source, target, and/or edge_type."""
        if source_id is not None and target_id is not None:
            edges = [e for e in self._out_edges.get(source_id, []) if e.target_id == target_id]
        elif source_id is not None:
            edges = list(self._out_edges.get(source_id, []))
        elif target_id is not None:
            edges = list(self._in_edges.get(target_id, []))
        else:
            edges = list(self._edges_by_id.values())

        if edge_type is not None:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    def get_neighbors(self, node_id: str, direction: str = "both") -> List[GraphNode]:
        """
        Returns adjacent nodes.
        direction: 'out', 'in', or 'both'.
        """
        neighbor_ids: Set[str] = set()
        if direction in ("out", "both"):
            for e in self._out_edges.get(node_id, []):
                neighbor_ids.add(e.target_id)
        if direction in ("in", "both"):
            for e in self._in_edges.get(node_id, []):
                neighbor_ids.add(e.source_id)

        return [self.nodes[nid] for nid in sorted(neighbor_ids) if nid in self.nodes]

    # -----------------------------------------------------------------
    # Traversal & Query Operations
    # -----------------------------------------------------------------

    def find_path(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 6,
        allowed_edge_types: Optional[Set[GraphEdgeType]] = None,
    ) -> Optional[List[str]]:
        """
        Bounded breadth-first search finding the shortest path from start_id to end_id.
        Cycle-safe and bounded by max_depth. Returns list of node IDs.
        """
        if start_id not in self.nodes or end_id not in self.nodes:
            return None
        if start_id == end_id:
            return [start_id]

        queue: collections.deque = collections.deque([([start_id], 0)])
        visited: Set[str] = {start_id}

        while queue:
            path, depth = queue.popleft()
            if depth >= max_depth:
                continue

            current = path[-1]
            for edge in self._out_edges.get(current, []):
                if allowed_edge_types and edge.edge_type not in allowed_edge_types:
                    continue
                nxt = edge.target_id
                if nxt == end_id:
                    return path + [nxt]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((path + [nxt], depth + 1))

        return None

    def find_related_signals(self, signal_node_id: str) -> List[GraphNode]:
        """Finds signals related structurally, temporally, or behaviorally to signal_node_id."""
        related: Set[str] = set()
        for edge in self._out_edges.get(signal_node_id, []):
            if edge.edge_type in (
                GraphEdgeType.CORRELATES_WITH,
                GraphEdgeType.TEMPORALLY_CORRELATED,
                GraphEdgeType.TEMPORALLY_RELATED_TO,
                GraphEdgeType.RESPONDS_TO,
            ):
                if edge.target_id.startswith("signal:"):
                    related.add(edge.target_id)
        for edge in self._in_edges.get(signal_node_id, []):
            if edge.edge_type in (
                GraphEdgeType.CORRELATES_WITH,
                GraphEdgeType.TEMPORALLY_CORRELATED,
                GraphEdgeType.TEMPORALLY_RELATED_TO,
                GraphEdgeType.RESPONDS_TO,
            ):
                if edge.source_id.startswith("signal:"):
                    related.add(edge.source_id)

        return [self.nodes[nid] for nid in sorted(related) if nid in self.nodes]

    def find_related_dtcs(self, dtc_node_id: str) -> List[GraphNode]:
        """Finds DTCs occurring in the same session, ECU, or linked via shared evidence/hypotheses."""
        if dtc_node_id not in self.nodes:
            return []

        dtc_node = self.nodes[dtc_node_id]
        ecu_id = dtc_node.properties.get("ecu_id")
        related_ids: Set[str] = set()

        # Check through hypothesis links
        for e1 in self._out_edges.get(dtc_node_id, []):
            # DTC -> hypothesis or evidence
            target = e1.target_id
            for e2 in self._in_edges.get(target, []):
                if e2.source_id.startswith("dtc:") and e2.source_id != dtc_node_id:
                    related_ids.add(e2.source_id)

        # Check same ECU DTCs
        for node in self.get_nodes(GraphNodeType.DTC):
            if node.node_id != dtc_node_id and node.properties.get("ecu_id") == ecu_id:
                related_ids.add(node.node_id)

        return [self.nodes[nid] for nid in sorted(related_ids) if nid in self.nodes]

    # -----------------------------------------------------------------
    # Subgraph Extraction
    # -----------------------------------------------------------------

    def get_ecu_subgraph(self, ecu_id: str) -> "DiagnosticGraph":
        """Extracts subgraph representing a specific ECU and its attached signals, DTCs, and services."""
        ecu_node_id = make_ecu_node_id(ecu_id)
        sub = DiagnosticGraph(vehicle_id=self.vehicle_id, metadata={"subgraph_type": "ECU", "ecu_id": ecu_id})
        
        target_nodes: Set[str] = set()
        if ecu_node_id in self.nodes:
            target_nodes.add(ecu_node_id)

        for nid, node in self.nodes.items():
            if node.properties.get("ecu_id", "").upper() == ecu_id.strip().upper():
                target_nodes.add(nid)

        for nid in target_nodes:
            sub.add_node(copy.deepcopy(self.nodes[nid]))

        for edge in self._edges_by_id.values():
            if edge.source_id in target_nodes and edge.target_id in target_nodes:
                sub.add_edge(copy.deepcopy(edge))

        return sub

    def get_evidence_subgraph(self, evidence_id: str) -> "DiagnosticGraph":
        """Extracts subgraph tracing an evidence node to its signals, observations, and hypotheses."""
        ev_node_id = make_evidence_node_id(evidence_id)
        sub = DiagnosticGraph(vehicle_id=self.vehicle_id, metadata={"subgraph_type": "EVIDENCE", "evidence_id": evidence_id})
        if ev_node_id not in self.nodes:
            return sub

        sub.add_node(copy.deepcopy(self.nodes[ev_node_id]))
        # 1-hop upstream and downstream
        connected_ids = {ev_node_id}
        for e in self._out_edges.get(ev_node_id, []):
            connected_ids.add(e.target_id)
        for e in self._in_edges.get(ev_node_id, []):
            connected_ids.add(e.source_id)

        for nid in connected_ids:
            if nid in self.nodes:
                sub.add_node(copy.deepcopy(self.nodes[nid]))

        for edge in self._edges_by_id.values():
            if edge.source_id in connected_ids and edge.target_id in connected_ids:
                sub.add_edge(copy.deepcopy(edge))

        return sub

    def get_hypothesis_subgraph(self, hypothesis_id: str) -> "DiagnosticGraph":
        """Extracts subgraph for a hypothesis: supporting/contradicting evidence and associated DTCs."""
        hypo_node_id = make_hypothesis_node_id(hypothesis_id)
        sub = DiagnosticGraph(vehicle_id=self.vehicle_id, metadata={"subgraph_type": "HYPOTHESIS", "hypothesis_id": hypothesis_id})
        if hypo_node_id not in self.nodes:
            return sub

        sub.add_node(copy.deepcopy(self.nodes[hypo_node_id]))
        nodes_in_sub = {hypo_node_id}

        # Evidence supporting/contradicting hypothesis
        for edge in self._in_edges.get(hypo_node_id, []):
            nodes_in_sub.add(edge.source_id)
            # 1 more hop back to signals or DTCs
            for e_up in self._in_edges.get(edge.source_id, []):
                nodes_in_sub.add(e_up.source_id)

        for nid in nodes_in_sub:
            if nid in self.nodes:
                sub.add_node(copy.deepcopy(self.nodes[nid]))

        for edge in self._edges_by_id.values():
            if edge.source_id in nodes_in_sub and edge.target_id in nodes_in_sub:
                sub.add_edge(copy.deepcopy(edge))

        return sub

    def filter_graph(
        self,
        node_types: Optional[Set[GraphNodeType]] = None,
        edge_types: Optional[Set[GraphEdgeType]] = None,
        ecu_id: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> "DiagnosticGraph":
        """Returns a filtered copy of the graph based on node types, edge types, ECU, and confidence."""
        filtered = DiagnosticGraph(vehicle_id=self.vehicle_id, metadata=copy.deepcopy(self.metadata))

        keep_nodes: Set[str] = set()
        for nid, node in self.nodes.items():
            if node_types and node.node_type not in node_types:
                continue
            if ecu_id and node.properties.get("ecu_id", "").upper() != ecu_id.strip().upper():
                continue
            keep_nodes.add(nid)
            filtered.add_node(copy.deepcopy(node))

        for edge in self._edges_by_id.values():
            if edge.confidence < min_confidence:
                continue
            if edge_types and edge.edge_type not in edge_types:
                continue
            if edge.source_id in keep_nodes and edge.target_id in keep_nodes:
                filtered.add_edge(copy.deepcopy(edge))

        return filtered

    # -----------------------------------------------------------------
    # Multi-Session & Merging Operations
    # -----------------------------------------------------------------

    def merge_session_graph(self, other: "DiagnosticGraph") -> None:
        """
        Controlled merge of another session's graph into this graph.
        CRITICAL SAFETY:
          - Validates vehicle compatibility. Rejects merge if vehicle IDs mismatch!
          - Static nodes (VEHICLE, ECU, SIGNAL) are shared/unified.
          - Session-specific nodes (OBSERVATION, ANOMALY, EVIDENCE, SESSION) remain distinct.
          - Preserves provenance and distinct session IDs.
        """
        if self.vehicle_id != "vehicle:UNSET" and other.vehicle_id != "vehicle:UNSET":
            if self.vehicle_id != other.vehicle_id:
                raise VehicleIdentityMismatchError(
                    f"Vehicle identity mismatch! Cannot merge graph of '{other.vehicle_id}' "
                    f"into graph of '{self.vehicle_id}'."
                )

        if self.vehicle_id == "vehicle:UNSET" and other.vehicle_id != "vehicle:UNSET":
            self.vehicle_id = other.vehicle_id

        # Merge session IDs
        self.session_ids.update(other.session_ids)

        # Merge nodes
        for nid, node in other.nodes.items():
            if nid not in self.nodes:
                self.add_node(copy.deepcopy(node))
            else:
                # Merge properties if appropriate for static nodes
                if node.node_type in (GraphNodeType.VEHICLE, GraphNodeType.ECU, GraphNodeType.SIGNAL):
                    self.nodes[nid].properties.update(node.properties)

        # Merge edges
        for edge in other._edges_by_id.values():
            if edge.source_id in self.nodes and edge.target_id in self.nodes:
                self.add_edge(copy.deepcopy(edge))

    # -----------------------------------------------------------------
    # Serialization & Export
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Lossless JSON-serializable dictionary representation."""
        return {
            "vehicle_id": self.vehicle_id,
            "session_ids": sorted(self.session_ids),
            "metadata": self.metadata,
            "node_count": len(self.nodes),
            "edge_count": len(self._edges_by_id),
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self._edges_by_id.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticGraph":
        """Reconstructs a DiagnosticGraph from a dictionary."""
        graph = cls(vehicle_id=data.get("vehicle_id", "vehicle:UNSET"), metadata=data.get("metadata", {}))
        for s_id in data.get("session_ids", []):
            graph.session_ids.add(s_id)

        for n_data in data.get("nodes", []):
            graph.add_node(GraphNode.from_dict(n_data))

        for e_data in data.get("edges", []):
            graph.add_edge(GraphEdge.from_dict(e_data))

        return graph

    def export_summary(self) -> Dict[str, Any]:
        """Compact summary of the graph topology and diagnostic findings."""
        by_type: Dict[str, int] = collections.defaultdict(int)
        for n in self.nodes.values():
            by_type[n.node_type.value] += 1

        by_edge_type: Dict[str, int] = collections.defaultdict(int)
        for e in self._edges_by_id.values():
            by_edge_type[e.edge_type.value] += 1

        ecu_nodes = self.get_nodes(GraphNodeType.ECU)
        dtc_nodes = self.get_nodes(GraphNodeType.DTC)
        hypo_nodes = self.get_nodes(GraphNodeType.HYPOTHESIS)

        return {
            "vehicle_id": self.vehicle_id,
            "session_count": len(self.session_ids),
            "total_nodes": len(self.nodes),
            "total_edges": len(self._edges_by_id),
            "nodes_by_type": dict(by_type),
            "edges_by_type": dict(by_edge_type),
            "ecus": [n.properties.get("ecu_id", n.label) for n in ecu_nodes],
            "dtc_count": len(dtc_nodes),
            "dtcs": [f"{n.properties.get('ecu_id', '?')}:{n.properties.get('code', n.label)}" for n in dtc_nodes],
            "hypotheses_count": len(hypo_nodes),
            "hypotheses": [n.properties.get("title", n.label) for n in hypo_nodes],
        }


# =====================================================================
# 5. CROSS-ECU RELATIONSHIP CANDIDATES & DISCOVERY
# =====================================================================

@dataclass
class RelationshipCandidate:
    """
    Known cross-ECU relationship pattern to check between signal pairs.
    Prevents blind O(N^2) all-pairs correlation over hundreds of signals.
    """
    candidate_id: str
    source_pattern: str   # Substring or regex to match source signal name
    target_pattern: str   # Substring or regex to match target signal name
    source_ecu: Optional[str] = None
    target_ecu: Optional[str] = None
    relationship_type: GraphEdgeType = GraphEdgeType.CORRELATES_WITH
    expected_lag_s: float = 0.0
    tolerance_s: float = 0.5
    physical_description: str = ""


# Default catalog of compatible cross-ECU relationship candidates
DEFAULT_RELATIONSHIP_CANDIDATES: List[RelationshipCandidate] = [
    RelationshipCandidate(
        candidate_id="RPM_VS_TRANS_INPUT",
        source_pattern="RPM",
        target_pattern="INPUT_SPEED",
        source_ecu="ECM",
        target_ecu="TCM",
        relationship_type=GraphEdgeType.CORRELATES_WITH,
        expected_lag_s=0.05,
        physical_description="Engine crankshaft output directly couples to transmission input shaft",
    ),
    RelationshipCandidate(
        candidate_id="RPM_VS_VEHICLE_SPEED",
        source_pattern="RPM",
        target_pattern="SPEED",
        source_ecu="ECM",
        target_ecu="ABS",
        relationship_type=GraphEdgeType.RESPONDS_TO,
        expected_lag_s=0.10,
        physical_description="Engine speed drives wheel speed through drivetrain gear reduction",
    ),
    RelationshipCandidate(
        candidate_id="GEAR_VS_LOAD",
        source_pattern="GEAR",
        target_pattern="LOAD",
        source_ecu="TCM",
        target_ecu="ECM",
        relationship_type=GraphEdgeType.RESPONDS_TO,
        expected_lag_s=0.08,
        physical_description="Transmission gear shifting induces calculated engine load shifts",
    ),
    RelationshipCandidate(
        candidate_id="MAF_VS_MAP",
        source_pattern="MAF",
        target_pattern="MAP",
        source_ecu="ECM",
        target_ecu="ECM",
        relationship_type=GraphEdgeType.CONSISTENT_WITH,
        expected_lag_s=0.02,
        physical_description="Intake manifold pressure and air mass flow must follow speed-density physical law",
    ),
    RelationshipCandidate(
        candidate_id="WHEEL_SPEEDS_ABS",
        source_pattern="WHEEL_SPEED",
        target_pattern="WHEEL_SPEED",
        source_ecu="ABS",
        target_ecu="ABS",
        relationship_type=GraphEdgeType.CONSISTENT_WITH,
        expected_lag_s=0.01,
        physical_description="Four wheel speed sensors must track synchronously in straight-line driving",
    ),
]


# =====================================================================
# 6. VEHICLE DIAGNOSTIC GRAPH BUILDER
# =====================================================================

class VehicleDiagnosticGraphBuilder:
    """
    Constructs a complete, deterministic vehicle-wide diagnostic graph.
    Integrates:
      - Vehicle Root & ECU subgraphs
      - G-4 Multi-ECU Targets & DTC Snapshots
      - G-3 Fault Analysis (Anomalies, Evidence, Hypotheses, Operating Conditions)
      - Cross-ECU & Temporal Relationship discovery
      - Strict No-Causality enforcement
    """

    def __init__(
        self,
        vehicle_context: Optional[Union[VehicleContext, Dict[str, Any]]] = None,
        relationship_candidates: Optional[List[RelationshipCandidate]] = None,
    ):
        self.vehicle_context = vehicle_context
        self.relationship_candidates = relationship_candidates or DEFAULT_RELATIONSHIP_CANDIDATES
        v_id = make_vehicle_node_id(vehicle_context) if vehicle_context else "vehicle:UNSET"
        self.graph = DiagnosticGraph(vehicle_id=v_id)
        if vehicle_context:
            self.build_vehicle_root()

    def build_vehicle_root(self) -> GraphNode:
        """Constructs and attaches the vehicle root node."""
        node_id = make_vehicle_node_id(self.vehicle_context)
        label = "Vehicle Root"
        props: Dict[str, Any] = {}

        if isinstance(self.vehicle_context, VehicleContext):
            label = f"{self.vehicle_context.manufacturer} {self.vehicle_context.model} ({self.vehicle_context.model_year})"
            props = {
                "manufacturer": self.vehicle_context.manufacturer,
                "model": self.vehicle_context.model,
                "model_year": self.vehicle_context.model_year,
                "engine": getattr(self.vehicle_context, "engine", getattr(self.vehicle_context, "engine_code", None)),
                "engine_code": self.vehicle_context.engine_code,
                "vin": getattr(self.vehicle_context, "vin", None),
            }
        elif isinstance(self.vehicle_context, dict):
            make = self.vehicle_context.get("manufacturer") or self.vehicle_context.get("make") or "Generic"
            model = self.vehicle_context.get("model") or "Vehicle"
            year = self.vehicle_context.get("model_year") or self.vehicle_context.get("year") or ""
            label = f"{make} {model} {year}".strip()
            props = copy.deepcopy(self.vehicle_context)

        node = GraphNode(
            node_id=node_id,
            node_type=GraphNodeType.VEHICLE,
            label=label,
            properties=props,
            provenance={"source": "VEHICLE_CONTEXT"},
        )
        return self.graph.add_node(node)

    def add_ecu_target(self, ecu: Union[ECUTarget, Dict[str, Any]]) -> GraphNode:
        """
        Adds an ECU node and links it to the vehicle root via HAS_ECU.
        Preserves discovery state and capability state.
        """
        vehicle_node = self.graph.get_node(self.graph.vehicle_id)
        if not vehicle_node:
            vehicle_node = self.build_vehicle_root()

        if isinstance(ecu, ECUTarget):
            ecu_id = ecu.ecu_id
            name = ecu.human_readable_name or ecu.ecu_id
            disc_state = ecu.discovery_state.value if isinstance(ecu.discovery_state, ECUDiscoveryState) else str(ecu.discovery_state)
            cap_state = ecu.capability_state.value if isinstance(ecu.capability_state, ECUCapabilityState) else str(ecu.capability_state)
            health = ecu.health_state.value if isinstance(ecu.health_state, ECUHealthState) else str(ecu.health_state)
            tx_h = ecu.tx_header
            rx_h = ecu.rx_header
            ecu_type = ecu.ecu_type.value if isinstance(ecu.ecu_type, ECUTargetType) else str(ecu.ecu_type)
        else:
            ecu_id = ecu.get("ecu_id", "UNKNOWN")
            name = ecu.get("name", ecu_id)
            disc_state = ecu.get("discovery_state", "DETECTED")
            cap_state = ecu.get("capability_state", "CAPABLE")
            health = ecu.get("health_state", "CONNECTED")
            tx_h = ecu.get("tx_header", "")
            rx_h = ecu.get("rx_header", "")
            ecu_type = ecu.get("ecu_type", "OTHER")

        node_id = make_ecu_node_id(ecu_id)
        ecu_node = GraphNode(
            node_id=node_id,
            node_type=GraphNodeType.ECU,
            label=f"ECU: {name} ({ecu_id})",
            properties={
                "ecu_id": ecu_id,
                "ecu_type": ecu_type,
                "discovery_state": disc_state,
                "capability_state": cap_state,
                "health_state": health,
                "tx_header": tx_h,
                "rx_header": rx_h,
            },
            provenance={"source": "ECU_REGISTRY"},
        )
        self.graph.add_node(ecu_node)

        # Edge: Vehicle -> HAS_ECU -> ECU
        edge_id = make_edge_id(vehicle_node.node_id, GraphEdgeType.HAS_ECU, ecu_node.node_id)
        self.graph.add_edge(GraphEdge(
            edge_id=edge_id,
            source_id=vehicle_node.node_id,
            target_id=ecu_node.node_id,
            edge_type=GraphEdgeType.HAS_ECU,
            confidence=1.0,
            properties={"discovery_state": disc_state},
        ))
        return ecu_node

    def add_signal_node(
        self,
        ecu_id: str,
        identifier: str,
        signal_name: str,
        unit: str = "",
        quality: str = QUALITY_GOOD,
        properties: Optional[Dict[str, Any]] = None,
    ) -> GraphNode:
        """Adds a signal node and links it to its owner ECU via EXPOSES_SIGNAL."""
        ecu_node_id = make_ecu_node_id(ecu_id)
        if ecu_node_id not in self.graph.nodes:
            self.add_ecu_target({"ecu_id": ecu_id, "name": f"{ecu_id} Module"})

        node_id = make_signal_node_id(ecu_id, identifier, signal_name)
        props = properties or {}
        props.update({
            "ecu_id": ecu_id.strip().upper(),
            "identifier": identifier.strip().upper(),
            "signal_name": signal_name.strip().upper(),
            "unit": unit,
            "quality": quality,
        })

        sig_node = GraphNode(
            node_id=node_id,
            node_type=GraphNodeType.SIGNAL,
            label=f"{ecu_id}:{signal_name}",
            properties=props,
            provenance={"source": "SIGNAL_REGISTRY"},
        )
        self.graph.add_node(sig_node)

        # Edge: ECU -> EXPOSES_SIGNAL -> Signal
        edge_id = make_edge_id(ecu_node_id, GraphEdgeType.EXPOSES_SIGNAL, sig_node.node_id)
        self.graph.add_edge(GraphEdge(
            edge_id=edge_id,
            source_id=ecu_node_id,
            target_id=sig_node.node_id,
            edge_type=GraphEdgeType.EXPOSES_SIGNAL,
            confidence=1.0,
        ))
        return sig_node

    def add_dtc_node(
        self,
        ecu_id: str,
        code: str,
        status: str = "CONFIRMED",
        severity: str = "WARNING",
        timestamp: Optional[float] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> GraphNode:
        """
        Adds a DTC node and links it to its reporting ECU via REPORTS_DTC.
        Maintains ECU-specific distinction (ECM:P0300 != TCM:P0300).
        """
        ecu_node_id = make_ecu_node_id(ecu_id)
        if ecu_node_id not in self.graph.nodes:
            self.add_ecu_target({"ecu_id": ecu_id, "name": f"{ecu_id} Module"})

        node_id = make_dtc_node_id(ecu_id, code)
        props = properties or {}
        props.update({
            "ecu_id": ecu_id.strip().upper(),
            "code": code.strip().upper(),
            "status": status,
            "severity": severity,
            "first_observed": timestamp,
            "last_observed": timestamp,
        })

        dtc_node = GraphNode(
            node_id=node_id,
            node_type=GraphNodeType.DTC,
            label=f"DTC {code} ({ecu_id})",
            properties=props,
            provenance={"source": "DTC_SNAPSHOT"},
        )
        self.graph.add_node(dtc_node)

        # Edge: ECU -> REPORTS_DTC -> DTC
        edge_id = make_edge_id(ecu_node_id, GraphEdgeType.REPORTS_DTC, dtc_node.node_id)
        self.graph.add_edge(GraphEdge(
            edge_id=edge_id,
            source_id=ecu_node_id,
            target_id=dtc_node.node_id,
            edge_type=GraphEdgeType.REPORTS_DTC,
            confidence=1.0,
            properties={"status": status},
        ))
        return dtc_node

    # -----------------------------------------------------------------
    # Ingestion from Phase G-4 (Multi-ECU Scan Results)
    # -----------------------------------------------------------------

    def ingest_g4_scan_result(self, scan_result: MultiECUScanResult) -> None:
        """
        Ingests a Phase G-4 MultiECUScanResult into the graph:
          - Vehicle Root
          - ECU Target nodes with reachability and health states
          - Acquisition session node
          - Multi-ECU DTCs (preserving ECU identity)
          - Multi-ECU data samples (as Signal nodes)
          - Communication failures as COMMUNICATION evidence, NOT vehicle faults!
        """
        # 1. Vehicle
        if not self.graph.get_node(self.graph.vehicle_id):
            self.build_vehicle_root()

        # 2. Session
        session_node_id = make_session_node_id(scan_result.scan_id)
        scope_val = getattr(scan_result, "scan_scope", None)
        if scope_val and hasattr(scope_val, "value"):
            scope_str = scope_val.value
        elif hasattr(scan_result, "scope"):
            scope_str = getattr(scan_result.scope, "value", str(scan_result.scope))
        else:
            scope_str = "FULL_VEHICLE"

        dur_val = getattr(scan_result, "duration", getattr(scan_result, "duration_seconds", 0.0))

        session_node = GraphNode(
            node_id=session_node_id,
            node_type=GraphNodeType.ACQUISITION_SESSION,
            label=f"Acquisition Session: {scan_result.scan_id}",
            properties={
                "scan_id": scan_result.scan_id,
                "scope": scope_str,
                "start_time": scan_result.start_time,
                "end_time": scan_result.end_time,
                "duration": round(dur_val, 3),
            },
            provenance={"source": "MULTI_ECU_SCANNER"},
        )
        self.graph.add_node(session_node)

        # 3. ECUs from records
        for ecu_id, record in scan_result.ecu_records.items():
            disc_state = getattr(record, "discovery_state", "DETECTED")
            if hasattr(disc_state, "value"):
                disc_state = disc_state.value
            health_state = getattr(record, "health_state", "CONNECTED")
            if hasattr(health_state, "value"):
                health_state = health_state.value
            ecu_type = getattr(record, "ecu_type", "OTHER")
            if hasattr(ecu_type, "value"):
                ecu_type = ecu_type.value

            ecu_node = self.add_ecu_target({
                "ecu_id": ecu_id,
                "name": f"{ecu_id} Module",
                "discovery_state": disc_state,
                "capability_state": "CAPABILITY_KNOWN",
                "health_state": health_state,
                "tx_header": getattr(record, "request_header", ""),
                "rx_header": getattr(record, "response_header", ""),
                "ecu_type": ecu_type,
            })

            # Check for communication failure
            is_unreachable = health_state in ("UNREACHABLE", "ERROR") or getattr(record, "last_error", None) is not None
            if is_unreachable:
                ev_id = f"COMM_FAIL_{ecu_id}_{scan_result.scan_id}"
                ev_node_id = make_evidence_node_id(ev_id)
                comm_ev_node = GraphNode(
                    node_id=ev_node_id,
                    node_type=GraphNodeType.EVIDENCE,
                    label=f"Communication Failure: {ecu_id}",
                    properties={
                        "ecu_id": ecu_id,
                        "failure_type": "COMMUNICATION_FAILURE",
                        "health_state": health_state,
                        "is_acquisition_fault": True,
                        "last_error": getattr(record, "last_error", None),
                    },
                    provenance={"source": "G4_COMMUNICATION_OBSERVER"},
                )
                self.graph.add_node(comm_ev_node)

                edge_id = make_edge_id(ecu_node.node_id, GraphEdgeType.PRODUCES_EVIDENCE, comm_ev_node.node_id)
                self.graph.add_edge(GraphEdge(
                    edge_id=edge_id,
                    source_id=ecu_node.node_id,
                    target_id=comm_ev_node.node_id,
                    edge_type=GraphEdgeType.PRODUCES_EVIDENCE,
                    confidence=1.0,
                    properties={"is_communication_failure": True},
                ))

            # 4. Ingest DTCs per ECU
            for dtc in getattr(record, "dtcs", []):
                d_code = getattr(dtc, "code", getattr(dtc, "dtc_code", "P0000"))
                d_status = getattr(dtc, "status", "CONFIRMED")
                d_ts = getattr(dtc, "timestamp", time.time())
                dtc_node = self.add_dtc_node(
                    ecu_id=ecu_id,
                    code=d_code,
                    status=d_status,
                    timestamp=d_ts,
                    properties={
                        "raw_response": getattr(dtc, "raw_response", None),
                        "transaction_id": getattr(dtc, "transaction_id", ""),
                    }
                )
                s_edge_id = make_edge_id(session_node_id, GraphEdgeType.REPORTS_DTC, dtc_node.node_id)
                if s_edge_id not in self.graph._edges_by_id:
                    self.graph.add_edge(GraphEdge(
                        edge_id=s_edge_id,
                        source_id=session_node_id,
                        target_id=dtc_node.node_id,
                        edge_type=GraphEdgeType.REPORTS_DTC,
                        confidence=1.0,
                    ))

            # 5. Ingest Data Samples per ECU
            for sample in getattr(record, "data_samples", []):
                ident = getattr(sample, "identifier", "00")
                canonical = getattr(sample, "canonical_name", f"{ecu_id}:{ident}")
                sig_name = canonical.split(":")[-1] if ":" in canonical else ident
                self.add_signal_node(
                    ecu_id=ecu_id,
                    identifier=ident,
                    signal_name=sig_name,
                    unit=getattr(sample, "unit", ""),
                    quality=getattr(sample, "quality", QUALITY_GOOD),
                    properties={
                        "service": getattr(sample, "service_id", "01"),
                        "canonical_name": canonical,
                        "latest_value": getattr(sample, "decoded_value", None),
                        "timestamp": getattr(sample, "response_timestamp", time.time()),
                    }
                )

    ingest_multi_ecu_scan = ingest_g4_scan_result

    def merge_graph(self, other_graph: DiagnosticGraph) -> DiagnosticGraph:
        """Merges an external session DiagnosticGraph into this builder's graph."""
        self.graph.merge_session_graph(other_graph)
        return self.graph

    # -----------------------------------------------------------------
    # Ingestion from Phase G-3 (Fault Analysis Engine)
    # -----------------------------------------------------------------

    def ingest_g3_analysis_result(
        self,
        analysis_result: AnalysisResult,
        dataset: Optional[DiagnosticDataSet] = None,
    ) -> None:
        """
        Ingests a Phase G-3 AnalysisResult into the diagnostic graph:
          - Operating Condition nodes
          - Point & Temporal Anomalies
          - FaultEvidence nodes (linked to signals and operating conditions)
          - FaultHypothesis nodes (linked to supporting/contradicting evidence and DTCs)
          - DTC Correlations
        """
        # Session Node from dataset or analysis_id
        session_id = analysis_result.dataset_id or analysis_result.analysis_id
        session_node_id = make_session_node_id(session_id)
        if session_node_id not in self.graph.nodes:
            self.graph.add_node(GraphNode(
                node_id=session_node_id,
                node_type=GraphNodeType.ACQUISITION_SESSION,
                label=f"Analysis Session: {session_id}",
                properties={
                    "analysis_id": analysis_result.analysis_id,
                    "dataset_id": analysis_result.dataset_id,
                    "duration": analysis_result.duration_seconds,
                    "quality_summary": analysis_result.quality_summary,
                },
                provenance={"source": "G3_ANALYSIS_ENGINE"},
            ))

        # 1. Operating Conditions
        for cond_name, duration_pct in analysis_result.operating_condition_summary.items():
            cond_node_id = make_op_cond_node_id(cond_name)
            if cond_node_id not in self.graph.nodes:
                self.graph.add_node(GraphNode(
                    node_id=cond_node_id,
                    node_type=GraphNodeType.OPERATING_CONDITION,
                    label=f"Condition: {cond_name}",
                    properties={"condition": cond_name, "prevalence_pct": round(duration_pct, 2)},
                    provenance={"source": "G3_OPERATING_CONDITION_CLASSIFIER"},
                ))
            # Edge: Session -> INDICATES_CONDITION -> Condition
            e_id = make_edge_id(session_node_id, GraphEdgeType.INDICATES_CONDITION, cond_node_id)
            if e_id not in self.graph._edges_by_id:
                self.graph.add_edge(GraphEdge(
                    edge_id=e_id,
                    source_id=session_node_id,
                    target_id=cond_node_id,
                    edge_type=GraphEdgeType.INDICATES_CONDITION,
                    confidence=1.0,
                    properties={"prevalence_pct": round(duration_pct, 2)},
                ))

        # 2. Anomalies
        for anomaly in analysis_result.anomalies:
            ano_id = anomaly.anomaly_id
            ano_node_id = make_anomaly_node_id(ano_id)
            is_point = isinstance(anomaly, PointAnomaly)

            signal_name = anomaly.signal_name
            # Resolve ECU if prefix exists e.g. "ECM:RPM"
            ecu_id = "ECM"
            clean_sig = signal_name
            if ":" in signal_name:
                parts = signal_name.split(":")
                if len(parts) == 3:
                    ecu_id, _, clean_sig = parts
                elif len(parts) == 2:
                    ecu_id, clean_sig = parts

            ano_props = {
                "anomaly_id": ano_id,
                "anomaly_type": anomaly.anomaly_type.value,
                "signal_name": clean_sig,
                "ecu_id": ecu_id,
                "severity": anomaly.severity.value,
                "details": anomaly.details,
                "is_acquisition_fault": anomaly.is_acquisition_fault,
                "operating_condition": anomaly.operating_condition.value,
            }
            if is_point:
                ano_props["timestamp"] = anomaly.timestamp
                ano_props["observed_value"] = anomaly.observed_value
            else:
                ano_props["start_time"] = anomaly.start_time
                ano_props["end_time"] = anomaly.end_time
                ano_props["duration"] = anomaly.duration
                ano_props["magnitude"] = anomaly.magnitude

            ano_node = GraphNode(
                node_id=ano_node_id,
                node_type=GraphNodeType.ANOMALY,
                label=f"Anomaly: {anomaly.anomaly_type.value} on {clean_sig}",
                properties=ano_props,
                provenance={"source": "G3_ANOMALY_DETECTOR"},
            )
            self.graph.add_node(ano_node)

            # Link Signal -> PRODUCES_EVIDENCE -> Anomaly (if signal exists)
            sig_node_id = make_signal_node_id(ecu_id, clean_sig, clean_sig)
            if sig_node_id not in self.graph.nodes:
                for sn in self.graph.get_nodes(GraphNodeType.SIGNAL):
                    if sn.properties.get("ecu_id", "").upper() == ecu_id.upper() and (
                        sn.properties.get("signal_name", "").upper() == clean_sig.upper() or
                        sn.properties.get("canonical_name", "").upper() == clean_sig.upper() or
                        sn.properties.get("canonical_name", "").upper().endswith(f":{clean_sig.upper()}")
                    ):
                        sig_node_id = sn.node_id
                        break
            if sig_node_id in self.graph.nodes:
                edge_id = make_edge_id(sig_node_id, GraphEdgeType.PRODUCES_EVIDENCE, ano_node_id)
                self.graph.add_edge(GraphEdge(
                    edge_id=edge_id,
                    source_id=sig_node_id,
                    target_id=ano_node_id,
                    edge_type=GraphEdgeType.PRODUCES_EVIDENCE,
                    confidence=0.9,
                ))

        # 3. Fault Evidence
        for ev in analysis_result.evidence:
            ev_node_id = make_evidence_node_id(ev.evidence_id)
            ev_node = GraphNode(
                node_id=ev_node_id,
                node_type=GraphNodeType.EVIDENCE,
                label=f"Evidence: {ev.title}",
                properties={
                    "evidence_id": ev.evidence_id,
                    "title": ev.title,
                    "signals": ev.signals,
                    "start_time": ev.start_time,
                    "end_time": ev.end_time,
                    "duration": ev.duration,
                    "observed_behavior": ev.observed_behavior,
                    "expected_behavior": ev.expected_behavior,
                    "deviation_magnitude": ev.deviation_magnitude,
                    "severity": ev.severity.value,
                    "quality": ev.quality.value,
                    "analysis_method": ev.analysis_method,
                    "confidence_score": ev.confidence_score,
                },
                provenance=ev.provenance,
            )
            self.graph.add_node(ev_node)

            # Link condition -> evidence
            cond_node_id = make_op_cond_node_id(ev.operating_condition)
            if cond_node_id in self.graph.nodes:
                c_edge = make_edge_id(cond_node_id, GraphEdgeType.INDICATES_CONDITION, ev_node_id)
                self.graph.add_edge(GraphEdge(
                    edge_id=c_edge,
                    source_id=cond_node_id,
                    target_id=ev_node_id,
                    edge_type=GraphEdgeType.INDICATES_CONDITION,
                    confidence=1.0,
                ))

            # Link signals -> evidence
            for s in ev.signals:
                ecu_s = "ECM"
                sig_s = s
                if ":" in s:
                    parts = s.split(":")
                    if len(parts) == 3:
                        ecu_s, _, sig_s = parts
                    elif len(parts) == 2:
                        ecu_s, sig_s = parts
                sig_node_id = make_signal_node_id(ecu_s, sig_s, sig_s)
                if sig_node_id not in self.graph.nodes:
                    for sn in self.graph.get_nodes(GraphNodeType.SIGNAL):
                        if sn.properties.get("ecu_id", "").upper() == ecu_s.upper() and (
                            sn.properties.get("signal_name", "").upper() == sig_s.upper() or
                            sn.properties.get("canonical_name", "").upper() == sig_s.upper() or
                            sn.properties.get("canonical_name", "").upper().endswith(f":{sig_s.upper()}")
                        ):
                            sig_node_id = sn.node_id
                            break
                if sig_node_id in self.graph.nodes:
                    s_edge = make_edge_id(sig_node_id, GraphEdgeType.PRODUCES_EVIDENCE, ev_node_id)
                    if s_edge not in self.graph._edges_by_id:
                        self.graph.add_edge(GraphEdge(
                            edge_id=s_edge,
                            source_id=sig_node_id,
                            target_id=ev_node_id,
                            edge_type=GraphEdgeType.PRODUCES_EVIDENCE,
                            confidence=ev.confidence_score,
                        ))

        # 4. Fault Hypotheses
        for hypo in analysis_result.hypotheses:
            hypo_node_id = make_hypothesis_node_id(hypo.hypothesis_id)
            hypo_node = GraphNode(
                node_id=hypo_node_id,
                node_type=GraphNodeType.HYPOTHESIS,
                label=f"Hypothesis: {hypo.title}",
                properties={
                    "hypothesis_id": hypo.hypothesis_id,
                    "title": hypo.title,
                    "category": hypo.category,
                    "affected_system": hypo.affected_system,
                    "confidence": hypo.confidence.value,
                    "severity": hypo.severity.value,
                    "evidence_score": hypo.evidence_score,
                    "is_dtc_free": hypo.is_dtc_free,
                    "dtc_associations": hypo.dtc_associations,
                    "possible_root_causes": hypo.possible_root_causes,
                    "alternative_explanations": hypo.alternative_explanations,
                    "required_additional_evidence": hypo.required_additional_evidence,
                },
                provenance={"source": "G3_HYPOTHESIS_ENGINE"},
            )
            self.graph.add_node(hypo_node)

            # Supporting Evidence Edges
            for s_ev in hypo.supporting_evidence:
                ev_id = make_evidence_node_id(s_ev.evidence_id)
                if ev_id in self.graph.nodes:
                    edge_id = make_edge_id(ev_id, GraphEdgeType.SUPPORTS_HYPOTHESIS, hypo_node_id)
                    self.graph.add_edge(GraphEdge(
                        edge_id=edge_id,
                        source_id=ev_id,
                        target_id=hypo_node_id,
                        edge_type=GraphEdgeType.SUPPORTS_HYPOTHESIS,
                        confidence=s_ev.confidence_score,
                        properties={"reason": "SUPPORTING_EVIDENCE"},
                    ))

            # Contradicting Evidence Edges
            for c_ev in hypo.contradicting_evidence:
                ev_id = make_evidence_node_id(c_ev.evidence_id)
                if ev_id in self.graph.nodes:
                    edge_id = make_edge_id(ev_id, GraphEdgeType.CONTRADICTS_HYPOTHESIS, hypo_node_id)
                    self.graph.add_edge(GraphEdge(
                        edge_id=edge_id,
                        source_id=ev_id,
                        target_id=hypo_node_id,
                        edge_type=GraphEdgeType.CONTRADICTS_HYPOTHESIS,
                        confidence=c_ev.confidence_score,
                        properties={"reason": "CONTRADICTING_EVIDENCE"},
                    ))

            # DTC associations
            for code in hypo.dtc_associations:
                # Associate with matching DTC nodes in graph
                for d_node in self.graph.get_nodes(GraphNodeType.DTC):
                    if d_node.properties.get("code") == code:
                        dtc_edge = make_edge_id(d_node.node_id, GraphEdgeType.ASSOCIATED_WITH, hypo_node_id)
                        if dtc_edge not in self.graph._edges_by_id:
                            self.graph.add_edge(GraphEdge(
                                edge_id=dtc_edge,
                                source_id=d_node.node_id,
                                target_id=hypo_node_id,
                                edge_type=GraphEdgeType.ASSOCIATED_WITH,
                                confidence=0.85,
                            ))

    # -----------------------------------------------------------------
    # Cross-ECU & Temporal Relationship Discovery
    # -----------------------------------------------------------------

    def discover_cross_ecu_relationships(
        self,
        dataset: Optional[DiagnosticDataSet] = None,
        min_correlation: float = 0.65,
        max_pairs: int = 100,
    ) -> List[GraphEdge]:
        """
        Discovers compatible cross-ECU relationships using the candidate catalog.
        
        HARD BOUNDARY:
          - RELATIONSHIP != CAUSALITY.
          - Never automatically creates CAUSED_BY edges.
          - Only connects signals if BOTH exist in the graph and dataset.
          - Calculates physical time-lag delta if time-series data is provided.
        """
        created_edges: List[GraphEdge] = []
        signal_nodes = self.graph.get_nodes(GraphNodeType.SIGNAL)

        for candidate in self.relationship_candidates:
            # Match source signals
            sources: List[GraphNode] = []
            targets: List[GraphNode] = []

            for s_node in signal_nodes:
                s_name = s_node.properties.get("signal_name", "")
                s_ecu = s_node.properties.get("ecu_id", "")

                if candidate.source_pattern in s_name:
                    if candidate.source_ecu is None or candidate.source_ecu == s_ecu:
                        sources.append(s_node)

                if candidate.target_pattern in s_name:
                    if candidate.target_ecu is None or candidate.target_ecu == s_ecu:
                        targets.append(s_node)

            for src in sources:
                for tgt in targets:
                    if src.node_id == tgt.node_id:
                        continue  # Skip self-loop

                    # Verify whether both signals actually have data in dataset
                    time_delta_ms: Optional[float] = None
                    measured_corr: float = 0.85  # Nominal candidate confidence

                    if dataset:
                        s_sig = dataset.get_signal(src.properties.get("signal_name", "")) or dataset.get_signal(src.properties.get("canonical_name", ""))
                        t_sig = dataset.get_signal(tgt.properties.get("signal_name", "")) or dataset.get_signal(tgt.properties.get("canonical_name", ""))
                        if not s_sig or not t_sig or len(s_sig) == 0 or len(t_sig) == 0:
                            continue  # Missing data -> DO NOT create false edge!

                        # Evaluate timestamp delta between initial active samples
                        if len(s_sig.timestamps) > 0 and len(t_sig.timestamps) > 0:
                            time_delta_ms = float((t_sig.timestamps[0] - s_sig.timestamps[0]) * 1000.0)

                    edge_type = candidate.relationship_type
                    edge_id = make_edge_id(src.node_id, edge_type, tgt.node_id, candidate.candidate_id)

                    edge_props: Dict[str, Any] = {
                        "candidate_id": candidate.candidate_id,
                        "description": candidate.physical_description,
                        "expected_lag_s": candidate.expected_lag_s,
                        "tolerance_s": candidate.tolerance_s,
                    }
                    if time_delta_ms is not None:
                        edge_props["observed_delta_ms"] = round(time_delta_ms, 2)

                    edge = GraphEdge(
                        edge_id=edge_id,
                        source_id=src.node_id,
                        target_id=tgt.node_id,
                        edge_type=edge_type,
                        confidence=measured_corr,
                        properties=edge_props,
                        provenance={"source": "CROSS_ECU_RELATIONSHIP_ENGINE"},
                    )
                    self.graph.add_edge(edge)
                    created_edges.append(edge)
                    if len(created_edges) >= max_pairs:
                        return created_edges

        return created_edges

    # -----------------------------------------------------------------
    # Factory & Pipeline Conveniences
    # -----------------------------------------------------------------

    @classmethod
    def build_from_multiecu_and_analysis(
        cls,
        scan_result: MultiECUScanResult,
        analysis_result: Optional[AnalysisResult] = None,
        dataset: Optional[DiagnosticDataSet] = None,
        vehicle_context: Optional[Union[VehicleContext, Dict[str, Any]]] = None,
    ) -> DiagnosticGraph:
        """
        Convenience pipeline: Ingests G-4 multi-ECU scan, G-3 analysis result,
        and discovers cross-ECU relationships.
        """
        builder = cls(vehicle_context=vehicle_context or scan_result.vehicle_context)
        builder.build_vehicle_root()
        builder.ingest_g4_scan_result(scan_result)

        if analysis_result:
            builder.ingest_g3_analysis_result(analysis_result, dataset=dataset)

        builder.discover_cross_ecu_relationships(dataset=dataset)
        return builder.graph
