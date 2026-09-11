# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase H-2: Automated Test Sequencing Engine
=============================================================================
This module implements Phase H-2 of the Seyyanen diagnostic platform.
It transforms H-1 guided diagnostic procedures into a deterministic,
machine-managed diagnostic test sequence state machine.

Core Architectural Invariants:
  1. SEQUENCING & ORCHESTRATION, NOT AUTONOMOUS REPAIR:
     Determines what test/observation to perform next, when prerequisites are
     satisfied, what result should be recorded, and which branch should follow.
     Does NOT perform autonomous root-cause reasoning (H-4), does NOT repair,
     and does NOT exert unrestricted ECU control.
  2. STRICT READ-ONLY & SAFE TEST CATEGORIES:
     Permits ONLY:
       - INFORMATIONAL
       - OBSERVATIONAL
       - MEASUREMENT
       - CONTROLLED_READ_ONLY_ACQUISITION (bounded PIDs/DIDs via G-1 / G-2)
     STRICTLY BLOCKS:
       - Actuator tests (0x2F)
       - ECU writes (0x2E)
       - Coding & programming (0x34/36/37)
       - Security access (0x27)
       - DTC clearing (Mode 04 / 14)
       - Destructive resets / arbitrary control routines
  3. IMMEDIATE SAFETY REVALIDATION & DRIFT PROTECTION:
     Every step is revalidated against ServiceSafetyPolicy IMMEDIATELY prior
     to dispatch. If policy or context has changed to revoke permission, the
     action is rejected and the sequence enters BLOCKED.
  4. SEPARATION OF DEFINITION VS EXECUTION STATE:
     DiagnosticProcedure (H-1) defines what should be tested and why.
     DiagnosticSequence (H-2) captures the runtime execution state and events.
     Executing a sequence NEVER mutates the underlying DiagnosticProcedure.
  5. DETERMINISTIC & EXPLAINABLE:
     100% deterministic offline state transitions, branch evaluation, and loop
     protection. Zero LLM dependency in the decision loop.
  6. BOUNDED ACQUISITION & EXECUTION:
     Strict limits on maximum sequence steps, branch revisits, retry counts,
     acquisition durations, samples, payloads, and step/global timeouts.
  7. MULTI-ECU ISOLATION:
     Multi-ECU steps are strictly addressed to their target ECUs. Transport
     responses are correlated strictly to the requesting ECU and step. Failure
     on one ECU does not corrupt another ECU's state.
  8. PERSISTENCE & REPRODUCIBILITY:
     Full to_dict() / from_dict() round-trip serialization. Identical inputs
     produce identical sequence progression.
=============================================================================
"""

from __future__ import annotations

import collections
import copy
import enum
import hashlib
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

# Integration imports from C, D, E, F, G, and H-1 layers
from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    STATUS_VALID,
    STATUS_NRC,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NO_DATA,
    STATUS_DID_MISMATCH,
    STATUS_EMPTY_RESPONSE,
)
from advanced_ecu_services import (
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    DiagnosticSessionContext,
    DiagnosticTransactionManager,
    ECUTargetContext,
    SessionType,
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    STATUS_TRANSACTION_BLOCKED,
    STATUS_TRANSACTION_CANCELLED,
    STATUS_UNEXPECTED_RESPONSE,
    STATUS_RESPONSE_MISMATCH,
    STATUS_PARSE_ERROR,
    CANONICAL_NRC_MAP,
)
from extended_did import (
    VehicleContext,
    StructuredDiagnosticEvidence,
    IdentifierNamespace,
    DataDecoder,
)
from advanced_fault_analysis import (
    DataSourceType,
    SignalQuality,
    OperatingCondition,
    AnomalySeverity,
    AnomalyType,
    HypothesisConfidence,
    FaultEvidence,
    FaultHypothesis,
    AnalysisResult,
    DTCRecord,
)
from multi_ecu_diagnostics import (
    ECUTarget,
    MultiECUDTCRecord,
    MultiECUScanResult,
    ECUScanRecord,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    make_vehicle_node_id,
    make_ecu_node_id,
    make_dtc_node_id,
    make_signal_node_id,
    make_hypothesis_node_id,
    make_evidence_node_id,
)
from guided_procedures import (
    ProcedureError,
    ProcedureStateError,
    ProcedureSafetyError,
    UnsupportedActionError,
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
)

logger = logging.getLogger(__name__)


# =====================================================================
# 1. EXCEPTIONS
# =====================================================================

class SequencerError(Exception):
    """Base exception for automated test sequencing errors."""
    pass


class SequenceStateError(SequencerError):
    """Raised when an illegal sequence state transition is attempted."""
    pass


class SequenceSafetyError(SequencerError):
    """Raised when an operation violates sequencing or vehicle safety invariants."""
    pass


class SequenceTimeoutError(SequencerError):
    """Raised when a step or global sequence timeout expires."""
    pass


class SequenceLoopError(SequencerError):
    """Raised when an infinite procedure or branch loop is detected."""
    pass


class TechnicianValidationError(SequencerError):
    """Raised when technician observation input fails validation."""
    pass


# =====================================================================
# 2. TAXONOMY & ENUMERATIONS
# =====================================================================

class SequenceState(str, enum.Enum):
    """Deterministic lifecycle states of a DiagnosticSequence."""
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_PRECONDITION = "WAITING_FOR_PRECONDITION"
    WAITING_FOR_DATA = "WAITING_FOR_DATA"
    WAITING_FOR_TECHNICIAN = "WAITING_FOR_TECHNICIAN"
    EXECUTING = "EXECUTING"
    EVALUATING = "EVALUATING"
    BRANCHING = "BRANCHING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class StepEligibility(str, enum.Enum):
    """Evaluation outcome determining if a step can execute."""
    ELIGIBLE = "ELIGIBLE"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    INVALID = "INVALID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


class SequenceEventType(str, enum.Enum):
    """Structured event taxonomy for sequence observability."""
    STATE_TRANSITION = "STATE_TRANSITION"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_BLOCKED = "STEP_BLOCKED"
    STEP_FAILED = "STEP_FAILED"
    STEP_RETRY = "STEP_RETRY"
    BRANCH_EVALUATED = "BRANCH_EVALUATED"
    TECHNICIAN_INPUT_REQUESTED = "TECHNICIAN_INPUT_REQUESTED"
    TECHNICIAN_INPUT_RECEIVED = "TECHNICIAN_INPUT_RECEIVED"
    SAFETY_CHECK_PASSED = "SAFETY_CHECK_PASSED"
    SAFETY_CHECK_FAILED = "SAFETY_CHECK_FAILED"
    PRECONDITION_CHECK = "PRECONDITION_CHECK"
    LOOP_DETECTED = "LOOP_DETECTED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class PreconditionStatus(str, enum.Enum):
    """Status of precondition verification."""
    SATISFIED = "SATISFIED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    UNSATISFIED = "UNSATISFIED"
    STALE_DATA = "STALE_DATA"
    ECU_UNREACHABLE = "ECU_UNREACHABLE"


# Prohibited service IDs across all sequencing operations
PROHIBITED_SERVICES = frozenset({
    "04", "4", "14",    # Clear DTCs / Reset Emission Data
    "2E",               # WriteDataByIdentifier
    "27",               # SecurityAccess
    "2F",               # InputOutputControlByIdentifier (Actuator tests)
    "34",               # RequestDownload (Flashing)
    "35",               # RequestUpload
    "36",               # TransferData
    "37",               # RequestTransferExit
    "3D",               # WriteMemoryByAddress
})


# =====================================================================
# 3. POLICIES & DESCRIPTORS
# =====================================================================

@dataclass
class SequenceExecutionPolicy:
    """
    Bounds, timeouts, and execution constraints governing a sequence.
    Guarantees that execution cannot spin in infinite loops or unbounded acquisitions.
    """
    max_sequence_steps: int = 50
    max_branch_revisits: int = 3
    max_retries_per_step: int = 2
    step_timeout_s: float = 30.0
    global_timeout_s: float = 600.0
    max_history_entries: int = 100
    allow_stale_data: bool = False
    data_freshness_window_s: float = 60.0
    max_acquisition_duration_s: float = 10.0
    max_acquisition_samples: int = 100
    max_acquisition_payload_bytes: int = 4096
    max_requested_identifiers: int = 10

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_sequence_steps": self.max_sequence_steps,
            "max_branch_revisits": self.max_branch_revisits,
            "max_retries_per_step": self.max_retries_per_step,
            "step_timeout_s": self.step_timeout_s,
            "global_timeout_s": self.global_timeout_s,
            "max_history_entries": self.max_history_entries,
            "allow_stale_data": self.allow_stale_data,
            "data_freshness_window_s": self.data_freshness_window_s,
            "max_acquisition_duration_s": self.max_acquisition_duration_s,
            "max_acquisition_samples": self.max_acquisition_samples,
            "max_acquisition_payload_bytes": self.max_acquisition_payload_bytes,
            "max_requested_identifiers": self.max_requested_identifiers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SequenceExecutionPolicy":
        return cls(
            max_sequence_steps=int(data.get("max_sequence_steps", 50)),
            max_branch_revisits=int(data.get("max_branch_revisits", 3)),
            max_retries_per_step=int(data.get("max_retries_per_step", 2)),
            step_timeout_s=float(data.get("step_timeout_s", 30.0)),
            global_timeout_s=float(data.get("global_timeout_s", 600.0)),
            max_history_entries=int(data.get("max_history_entries", 100)),
            allow_stale_data=bool(data.get("allow_stale_data", False)),
            data_freshness_window_s=float(data.get("data_freshness_window_s", 60.0)),
            max_acquisition_duration_s=float(data.get("max_acquisition_duration_s", 10.0)),
            max_acquisition_samples=int(data.get("max_acquisition_samples", 100)),
            max_acquisition_payload_bytes=int(data.get("max_acquisition_payload_bytes", 4096)),
            max_requested_identifiers=int(data.get("max_requested_identifiers", 10)),
        )


@dataclass
class SequenceActionDescriptor:
    """
    Adapter-level declaration of read-only acquisition parameters for a test step.
    Strictly bounded; rejects unbounded or prohibited actions before dispatch.
    """
    target_ecu: str
    service_id: str                      # e.g. "22" (DID) or "01" (PID) or "09" or "19"
    identifier: str                      # e.g. "F190", "010C", "1640"
    timeout_s: float = 2.0
    max_retries: int = 1
    expected_response_type: str = "HEX"
    acquisition_duration_s: float = 1.0
    max_samples: int = 10
    required_quality: SignalQuality = SignalQuality.GOOD
    required_operating_condition: Optional[str] = None
    header: Optional[str] = None

    def __post_init__(self):
        self.service_id = str(self.service_id).strip().upper()
        self.identifier = str(self.identifier).strip().upper()
        if self.service_id in PROHIBITED_SERVICES:
            raise SequenceSafetyError(
                f"Action descriptor requests prohibited service 0x{self.service_id}."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_ecu": self.target_ecu,
            "service_id": self.service_id,
            "identifier": self.identifier,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "expected_response_type": self.expected_response_type,
            "acquisition_duration_s": self.acquisition_duration_s,
            "max_samples": self.max_samples,
            "required_quality": self.required_quality.value,
            "required_operating_condition": self.required_operating_condition,
            "header": self.header,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SequenceActionDescriptor":
        return cls(
            target_ecu=data["target_ecu"],
            service_id=data["service_id"],
            identifier=data["identifier"],
            timeout_s=float(data.get("timeout_s", 2.0)),
            max_retries=int(data.get("max_retries", 1)),
            expected_response_type=data.get("expected_response_type", "HEX"),
            acquisition_duration_s=float(data.get("acquisition_duration_s", 1.0)),
            max_samples=int(data.get("max_samples", 10)),
            required_quality=SignalQuality(data.get("required_quality", "GOOD")),
            required_operating_condition=data.get("required_operating_condition"),
            header=data.get("header"),
        )


# =====================================================================
# 4. EVENTS & RESULTS
# =====================================================================

@dataclass
class SequenceEvent:
    """
    Structured, inspectable record of an event or state transition during sequencing.
    """
    event_id: str
    timestamp: float
    sequence_id: str
    step_id: Optional[str]
    previous_state: Optional[str]
    new_state: Optional[str]
    event_type: SequenceEventType
    reason: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": round(self.timestamp, 3),
            "sequence_id": self.sequence_id,
            "step_id": self.step_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "event_type": self.event_type.value,
            "reason": self.reason,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SequenceEvent":
        return cls(
            event_id=data["event_id"],
            timestamp=data["timestamp"],
            sequence_id=data["sequence_id"],
            step_id=data.get("step_id"),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            event_type=SequenceEventType(data["event_type"]),
            reason=data.get("reason", ""),
            provenance=data.get("provenance", {}),
        )


@dataclass
class SequenceResult:
    """
    Structured outcome of a step execution evaluated by the sequencer.
    Contains observed values, evidence references, data quality, and branch decision.
    Does NOT invent root cause reasoning.
    """
    step_id: str
    execution_status: str                   # e.g. "SUCCESS", "TIMEOUT", "NRC", "ERROR", "BLOCKED"
    observed_values: Dict[str, Any] = field(default_factory=dict)
    evidence_references: List[str] = field(default_factory=list)
    data_quality: SignalQuality = SignalQuality.GOOD
    expected_outcome: Optional[str] = None
    actual_outcome: ObservationResultType = ObservationResultType.NORMAL
    branch_decision: Optional[str] = None    # Target step ID or terminal outcome value
    hypothesis_impact: Dict[str, float] = field(default_factory=dict) # hypothesis_id -> confidence delta
    provenance: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    error_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "execution_status": self.execution_status,
            "observed_values": self.observed_values,
            "evidence_references": self.evidence_references,
            "data_quality": self.data_quality.value,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome.value,
            "branch_decision": self.branch_decision,
            "hypothesis_impact": self.hypothesis_impact,
            "provenance": self.provenance,
            "timestamp": round(self.timestamp, 3),
            "error_state": self.error_state,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SequenceResult":
        return cls(
            step_id=data["step_id"],
            execution_status=data["execution_status"],
            observed_values=data.get("observed_values", {}),
            evidence_references=data.get("evidence_references", []),
            data_quality=SignalQuality(data.get("data_quality", "GOOD")),
            expected_outcome=data.get("expected_outcome"),
            actual_outcome=ObservationResultType(data.get("actual_outcome", "NORMAL")),
            branch_decision=data.get("branch_decision"),
            hypothesis_impact=data.get("hypothesis_impact", {}),
            provenance=data.get("provenance", {}),
            timestamp=data.get("timestamp", time.time()),
            error_state=data.get("error_state"),
        )


@dataclass
class SequenceStepExecution:
    """
    Execution trace for an individual step within a DiagnosticSequence.
    """
    step_id: str
    attempt_count: int = 0
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = "PENDING"
    adapter_used: Optional[str] = None
    result: Optional[SequenceResult] = None
    raw_evidence_ids: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "attempt_count": self.attempt_count,
            "started_at": round(self.started_at, 3) if self.started_at else 0.0,
            "completed_at": round(self.completed_at, 3) if self.completed_at else 0.0,
            "status": self.status,
            "adapter_used": self.adapter_used,
            "result": self.result.to_dict() if self.result else None,
            "raw_evidence_ids": self.raw_evidence_ids,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SequenceStepExecution":
        res_data = data.get("result")
        return cls(
            step_id=data["step_id"],
            attempt_count=data.get("attempt_count", 0),
            started_at=data.get("started_at", 0.0),
            completed_at=data.get("completed_at", 0.0),
            status=data.get("status", "PENDING"),
            adapter_used=data.get("adapter_used"),
            result=SequenceResult.from_dict(res_data) if res_data else None,
            raw_evidence_ids=data.get("raw_evidence_ids", []),
            error_message=data.get("error_message"),
        )


# =====================================================================
# 5. DIAGNOSTIC SEQUENCE ROOT MODEL
# =====================================================================

@dataclass
class DiagnosticSequence:
    """
    Deterministic, machine-managed execution state container for a DiagnosticProcedure.
    Separates runtime execution state from the immutable procedure definition.
    """
    sequence_id: str
    procedure_id: str
    vehicle_id: str
    session_id: str
    current_step_id: Optional[str] = None
    execution_state: SequenceState = SequenceState.CREATED
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    blocked_steps: List[str] = field(default_factory=list)
    step_executions: Dict[str, SequenceStepExecution] = field(default_factory=dict)
    sequence_history: List[Dict[str, Any]] = field(default_factory=list)
    active_branch_id: Optional[str] = None
    safety_status: str = "SECURE_READ_ONLY"
    policy: SequenceExecutionPolicy = field(default_factory=SequenceExecutionPolicy)
    events: List[SequenceEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    provenance: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    # Branch and loop tracking
    step_visit_counts: Dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    branch_visit_counts: Dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    final_outcome: Optional[ProcedureOutcome] = None
    termination_reason: Optional[str] = None

    # Deterministic Lifecycle State Transitions
    VALID_TRANSITIONS: ClassVar[Dict[SequenceState, Set[SequenceState]]] = {
        SequenceState.CREATED: {SequenceState.READY, SequenceState.ABORTED, SequenceState.FAILED},
        SequenceState.READY: {
            SequenceState.RUNNING,
            SequenceState.WAITING_FOR_PRECONDITION,
            SequenceState.WAITING_FOR_DATA,
            SequenceState.WAITING_FOR_TECHNICIAN,
            SequenceState.BLOCKED,
            SequenceState.ABORTED,
            SequenceState.FAILED,
        },
        SequenceState.RUNNING: {
            SequenceState.WAITING_FOR_PRECONDITION,
            SequenceState.WAITING_FOR_DATA,
            SequenceState.WAITING_FOR_TECHNICIAN,
            SequenceState.EXECUTING,
            SequenceState.BLOCKED,
            SequenceState.COMPLETED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.WAITING_FOR_PRECONDITION: {
            SequenceState.RUNNING,
            SequenceState.EXECUTING,
            SequenceState.BLOCKED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.WAITING_FOR_DATA: {
            SequenceState.RUNNING,
            SequenceState.EXECUTING,
            SequenceState.BLOCKED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.WAITING_FOR_TECHNICIAN: {
            SequenceState.EVALUATING,
            SequenceState.RUNNING,
            SequenceState.BLOCKED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.EXECUTING: {
            SequenceState.EVALUATING,
            SequenceState.RUNNING,
            SequenceState.BLOCKED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.EVALUATING: {
            SequenceState.BRANCHING,
            SequenceState.RUNNING,
            SequenceState.COMPLETED,
            SequenceState.BLOCKED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.BRANCHING: {
            SequenceState.RUNNING,
            SequenceState.COMPLETED,
            SequenceState.BLOCKED,
            SequenceState.FAILED,
            SequenceState.ABORTED,
        },
        SequenceState.BLOCKED: {SequenceState.ABORTED},
        SequenceState.COMPLETED: set(),
        SequenceState.FAILED: set(),
        SequenceState.ABORTED: set(),
    }

    def transition_to(self, new_state: SequenceState, reason: str = "", step_id: Optional[str] = None) -> SequenceEvent:
        """
        Transitions sequence execution lifecycle.
        Enforces deterministic transition rules; rejects invalid transitions with SequenceStateError.
        Emits and records a structured SequenceEvent.
        """
        allowed = self.VALID_TRANSITIONS.get(self.execution_state, set())
        if new_state not in allowed:
            raise SequenceStateError(
                f"Invalid sequence state transition: cannot move from '{self.execution_state.value}' "
                f"to '{new_state.value}'. Allowed transitions: {[s.value for s in allowed]}"
            )

        prev_state = self.execution_state.value
        self.execution_state = new_state
        self.updated_at = time.time()

        evt = SequenceEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=self.updated_at,
            sequence_id=self.sequence_id,
            step_id=step_id or self.current_step_id,
            previous_state=prev_state,
            new_state=new_state.value,
            event_type=SequenceEventType.STATE_TRANSITION,
            reason=reason,
            provenance={"sequence_version": self.version},
        )
        self.events.append(evt)

        # Enforce bounded history
        if len(self.sequence_history) >= self.policy.max_history_entries:
            self.sequence_history.pop(0)

        self.sequence_history.append({
            "event_id": evt.event_id,
            "timestamp": round(evt.timestamp, 3),
            "previous_state": prev_state,
            "new_state": new_state.value,
            "step_id": evt.step_id,
            "reason": reason,
        })
        return evt

    def record_event(
        self,
        event_type: SequenceEventType,
        reason: str = "",
        step_id: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> SequenceEvent:
        """Records an operational sequence event without changing the state machine state."""
        evt = SequenceEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            sequence_id=self.sequence_id,
            step_id=step_id or self.current_step_id,
            previous_state=self.execution_state.value,
            new_state=self.execution_state.value,
            event_type=event_type,
            reason=reason,
            provenance=provenance or {},
        )
        self.events.append(evt)
        return evt

    @property
    def is_terminal(self) -> bool:
        return self.execution_state in (SequenceState.COMPLETED, SequenceState.FAILED, SequenceState.ABORTED, SequenceState.BLOCKED)

    # -----------------------------------------------------------------
    # Serialization (to_dict / from_dict)
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "procedure_id": self.procedure_id,
            "vehicle_id": self.vehicle_id,
            "session_id": self.session_id,
            "current_step_id": self.current_step_id,
            "execution_state": self.execution_state.value,
            "completed_steps": list(self.completed_steps),
            "pending_steps": list(self.pending_steps),
            "blocked_steps": list(self.blocked_steps),
            "step_executions": {k: v.to_dict() for k, v in self.step_executions.items()},
            "sequence_history": list(self.sequence_history),
            "active_branch_id": self.active_branch_id,
            "safety_status": self.safety_status,
            "policy": self.policy.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "created_at": round(self.created_at, 3),
            "updated_at": round(self.updated_at, 3),
            "provenance": self.provenance,
            "version": self.version,
            "step_visit_counts": dict(self.step_visit_counts),
            "branch_visit_counts": dict(self.branch_visit_counts),
            "final_outcome": self.final_outcome.value if self.final_outcome else None,
            "termination_reason": self.termination_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticSequence":
        step_execs = {
            k: SequenceStepExecution.from_dict(v)
            for k, v in data.get("step_executions", {}).items()
        }
        policy_data = data.get("policy", {})
        policy = SequenceExecutionPolicy.from_dict(policy_data) if policy_data else SequenceExecutionPolicy()
        events = [SequenceEvent.from_dict(e) for e in data.get("events", [])]

        term_out = data.get("final_outcome")
        final_outcome = ProcedureOutcome(term_out) if term_out else None

        seq = cls(
            sequence_id=data["sequence_id"],
            procedure_id=data["procedure_id"],
            vehicle_id=data["vehicle_id"],
            session_id=data["session_id"],
            current_step_id=data.get("current_step_id"),
            execution_state=SequenceState(data.get("execution_state", "CREATED")),
            completed_steps=data.get("completed_steps", []),
            pending_steps=data.get("pending_steps", []),
            blocked_steps=data.get("blocked_steps", []),
            step_executions=step_execs,
            sequence_history=data.get("sequence_history", []),
            active_branch_id=data.get("active_branch_id"),
            safety_status=data.get("safety_status", "SECURE_READ_ONLY"),
            policy=policy,
            events=events,
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            provenance=data.get("provenance", {}),
            version=data.get("version", "1.0.0"),
            final_outcome=final_outcome,
            termination_reason=data.get("termination_reason"),
        )
        for k, v in data.get("step_visit_counts", {}).items():
            seq.step_visit_counts[k] = int(v)
        for k, v in data.get("branch_visit_counts", {}).items():
            seq.branch_visit_counts[k] = int(v)
        return seq


# =====================================================================
# 6. EXECUTION ADAPTER INTERFACES
# =====================================================================

class TestExecutionAdapter:
    """
    Abstract adapter boundary between sequence orchestration and actual
    diagnostic operations. The sequencer never directly talks to raw serial
    ports, MockSerial, or UI widgets.
    """
    def execute(
        self,
        step: DiagnosticStep,
        descriptor: Optional[SequenceActionDescriptor],
        sequence: DiagnosticSequence,
    ) -> SequenceResult:
        raise NotImplementedError("TestExecutionAdapter.execute must be implemented by subclasses.")

    def is_available(self, target_ecu: str) -> bool:
        return True


class ReadOnlyAcquisitionAdapter(TestExecutionAdapter):
    """
    Executes bounded, read-only PID/DID acquisitions via existing G-1 DiagnosticTransactionManager
    and G-2 DataDecoder without creating a redundant transport layer.
    """
    def __init__(
        self,
        txn_manager: Optional[DiagnosticTransactionManager] = None,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
    ):
        self.txn_manager = txn_manager
        self.safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)

    def is_available(self, target_ecu: str) -> bool:
        if self.txn_manager and hasattr(self.txn_manager, "is_worker_alive"):
            return self.txn_manager.is_worker_alive()
        return True

    def execute(
        self,
        step: DiagnosticStep,
        descriptor: Optional[SequenceActionDescriptor],
        sequence: DiagnosticSequence,
    ) -> SequenceResult:
        # Enforce bounded acquisition constraints
        if not descriptor:
            return SequenceResult(
                step_id=step.step_id,
                execution_status="NO_DESCRIPTOR",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state="ReadOnlyAcquisitionAdapter requires a valid SequenceActionDescriptor.",
            )

        # Enforce bounds
        if descriptor.service_id in PROHIBITED_SERVICES:
            return SequenceResult(
                step_id=step.step_id,
                execution_status="BLOCKED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=f"Prohibited service 0x{descriptor.service_id} rejected by adapter.",
            )

        if descriptor.acquisition_duration_s > sequence.policy.max_acquisition_duration_s:
            return SequenceResult(
                step_id=step.step_id,
                execution_status="BOUNDS_EXCEEDED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=(
                    f"Requested duration {descriptor.acquisition_duration_s}s exceeds maximum allowed "
                    f"{sequence.policy.max_acquisition_duration_s}s."
                ),
            )

        if descriptor.max_samples > sequence.policy.max_acquisition_samples:
            return SequenceResult(
                step_id=step.step_id,
                execution_status="BOUNDS_EXCEEDED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=(
                    f"Requested samples {descriptor.max_samples} exceeds maximum allowed "
                    f"{sequence.policy.max_acquisition_samples}."
                ),
            )

        # Build G-1 request
        req = AdvancedServiceRequest(
            service_id=descriptor.service_id,
            payload=descriptor.identifier,
            header=descriptor.header or ("7E0" if "ENGINE" in descriptor.target_ecu.upper() or "ECM" in descriptor.target_ecu.upper() else "7E1"),
            target_ecu=descriptor.target_ecu,
            timeout=min(descriptor.timeout_s, sequence.policy.step_timeout_s),
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )

        # Immediate safety gate verification
        safe, reason = self.safety_policy.validate_request(req)
        if not safe:
            return SequenceResult(
                step_id=step.step_id,
                execution_status="SAFETY_BLOCKED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=f"Immediate safety gate blocked request: {reason}",
            )

        # Dispatch through G-1 transaction manager if present
        if self.txn_manager:
            resp = self.txn_manager.execute_transaction(req)
            if resp.is_positive:
                actual = ObservationResultType.NORMAL
                observed_val = {"raw_payload": resp.raw_payload_hex or "", "parsed": resp.parsed_payload}
                # Check expected observation if defined
                if step.expected_observation and resp.parsed_payload is not None:
                    try:
                        num_val = float(resp.parsed_payload)
                        if step.expected_observation.min_value is not None and num_val < step.expected_observation.min_value:
                            actual = ObservationResultType.ABNORMAL
                        elif step.expected_observation.max_value is not None and num_val > step.expected_observation.max_value:
                            actual = ObservationResultType.ABNORMAL
                    except (ValueError, TypeError):
                        pass

                return SequenceResult(
                    step_id=step.step_id,
                    execution_status="SUCCESS",
                    observed_values=observed_val,
                    evidence_references=[f"txn_{resp.transaction_id}"],
                    data_quality=SignalQuality.GOOD,
                    actual_outcome=actual,
                    provenance={"response_service_id": resp.response_service_id, "header": req.header},
                )
            else:
                return SequenceResult(
                    step_id=step.step_id,
                    execution_status=resp.response_status or "ERROR",
                    evidence_references=[f"txn_{resp.transaction_id}"],
                    data_quality=SignalQuality.ERROR,
                    actual_outcome=ObservationResultType.COMMUNICATION_FAILURE if resp.response_status in (STATUS_TIMEOUT, STATUS_NO_CONNECTION, STATUS_SERIAL_ERROR) else ObservationResultType.ABNORMAL,
                    error_state=f"ECU responded with status: {resp.response_status} (NRC: {resp.nrc_code})",
                )

        # Fallback simulation if transaction manager is offline
        return SequenceResult(
            step_id=step.step_id,
            execution_status="SUCCESS",
            observed_values={"identifier": descriptor.identifier, "simulated": True},
            data_quality=SignalQuality.GOOD,
            actual_outcome=ObservationResultType.NORMAL,
            provenance={"mode": "SIMULATED_READ_ONLY"},
        )


class TechnicianObservationAdapter(TestExecutionAdapter):
    """
    Handles technician-driven observational and measurement steps.
    Validates technician input against strict constraints and prevents malformed data entry.
    """
    def execute(
        self,
        step: DiagnosticStep,
        descriptor: Optional[SequenceActionDescriptor],
        sequence: DiagnosticSequence,
    ) -> SequenceResult:
        # If the step already has a validated technician observation attached, convert to SequenceResult
        if step.technician_observation:
            obs = step.technician_observation
            return SequenceResult(
                step_id=step.step_id,
                execution_status="SUCCESS",
                observed_values={
                    "result_type": obs.result_type.value,
                    "measured_value": obs.measured_value,
                    "unit": obs.unit,
                    "notes": obs.notes,
                },
                evidence_references=[f"obs_{obs.observation_id}"],
                data_quality=SignalQuality.GOOD,
                actual_outcome=obs.result_type,
                provenance={"technician_id": obs.technician_id, "timestamp": obs.timestamp},
            )

        # Otherwise, sequence must wait for technician input
        return SequenceResult(
            step_id=step.step_id,
            execution_status="WAITING_FOR_TECHNICIAN",
            actual_outcome=ObservationResultType.NOT_TESTED,
            error_state="Step requires technician observation or manual measurement.",
        )

    def validate_technician_input(
        self,
        step: DiagnosticStep,
        result_type: ObservationResultType,
        measured_value: Optional[float] = None,
        unit: Optional[str] = None,
        notes: str = "",
        technician_id: Optional[str] = None,
    ) -> TechnicianObservation:
        """
        Validates technician input.
        Rejects malformed input, missing units on measurements, or invalid numeric values.
        """
        if not isinstance(result_type, ObservationResultType):
            try:
                result_type = ObservationResultType(str(result_type).upper())
            except ValueError:
                raise TechnicianValidationError(f"Invalid observation result type: '{result_type}'.")

        # If step is MEASUREMENT, measured_value is required
        if step.execution_mode == StepExecutionMode.MEASUREMENT:
            if measured_value is None:
                raise TechnicianValidationError(
                    f"Step '{step.step_id}' is a MEASUREMENT step and requires a numeric measured_value."
                )
            try:
                measured_value = float(measured_value)
            except (ValueError, TypeError):
                raise TechnicianValidationError(
                    f"Invalid measured_value '{measured_value}': must be a valid float."
                )
            if math.isnan(measured_value) or math.isinf(measured_value):
                raise TechnicianValidationError("measured_value cannot be NaN or Infinite.")

            # If expected observation defines a unit, verify matching unit
            if step.expected_observation and step.expected_observation.unit:
                if not unit or unit.strip().upper() != step.expected_observation.unit.strip().upper():
                    raise TechnicianValidationError(
                        f"Measurement requires unit '{step.expected_observation.unit}', got '{unit}'."
                    )

        # Validate numeric bounds if trusted range is provided
        if measured_value is not None and step.expected_observation and step.expected_observation.trusted_source:
            # Automatic classification if technician provided MEASURED_VALUE
            if result_type == ObservationResultType.MEASURED_VALUE:
                if step.expected_observation.min_value is not None and measured_value < step.expected_observation.min_value:
                    result_type = ObservationResultType.ABNORMAL
                elif step.expected_observation.max_value is not None and measured_value > step.expected_observation.max_value:
                    result_type = ObservationResultType.ABNORMAL
                else:
                    result_type = ObservationResultType.NORMAL

        obs = TechnicianObservation(
            observation_id=f"obs_{uuid.uuid4().hex[:10]}",
            step_id=step.step_id,
            result_type=result_type,
            measured_value=measured_value,
            unit=unit,
            notes=notes,
            technician_id=technician_id or "TECH_USER",
            timestamp=time.time(),
        )
        return obs


class MockTestExecutionAdapter(TestExecutionAdapter):
    """
    Configurable, deterministic test mock adapter for testing all sequencing scenarios:
    success, timeouts, NRCs, unreachable ECUs, malformed responses, delayed responses,
    and multi-ECU routing.
    """
    def __init__(self):
        self.step_behaviors: Dict[str, Dict[str, Any]] = {}
        self.ecu_availability: Dict[str, bool] = {}
        self.execution_log: List[Dict[str, Any]] = []

    def configure_step(
        self,
        step_id: str,
        status: str = "SUCCESS",
        actual_outcome: ObservationResultType = ObservationResultType.NORMAL,
        observed_values: Optional[Dict[str, Any]] = None,
        delay_s: float = 0.0,
        nrc_code: Optional[str] = None,
        fail_attempts: int = 0,
        unreachable_ecu: bool = False,
    ):
        self.step_behaviors[step_id] = {
            "status": status,
            "actual_outcome": actual_outcome,
            "observed_values": observed_values or {},
            "delay_s": delay_s,
            "nrc_code": nrc_code,
            "fail_attempts": fail_attempts,
            "attempts_so_far": 0,
            "unreachable_ecu": unreachable_ecu,
        }

    def set_ecu_available(self, ecu_id: str, available: bool):
        self.ecu_availability[ecu_id] = available

    def is_available(self, target_ecu: str) -> bool:
        return self.ecu_availability.get(target_ecu, True)

    def execute(
        self,
        step: DiagnosticStep,
        descriptor: Optional[SequenceActionDescriptor],
        sequence: DiagnosticSequence,
    ) -> SequenceResult:
        self.execution_log.append({
            "step_id": step.step_id,
            "target_ecu": step.target_ecu,
            "timestamp": time.time(),
        })

        # Check ECU reachability
        if not self.is_available(step.target_ecu):
            return SequenceResult(
                step_id=step.step_id,
                execution_status="ECU_UNREACHABLE",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                error_state=f"Target ECU '{step.target_ecu}' is unreachable.",
            )

        behavior = self.step_behaviors.get(step.step_id, {})
        if behavior.get("unreachable_ecu", False):
            return SequenceResult(
                step_id=step.step_id,
                execution_status="ECU_UNREACHABLE",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                error_state=f"Target ECU '{step.target_ecu}' is unreachable.",
            )

        # Simulated delay
        delay = behavior.get("delay_s", 0.0)
        if delay > 0:
            time.sleep(min(delay, 0.05))

        # Check retry simulation
        fail_attempts = behavior.get("fail_attempts", 0)
        attempts_so_far = behavior.get("attempts_so_far", 0)
        if attempts_so_far < fail_attempts:
            behavior["attempts_so_far"] = attempts_so_far + 1
            return SequenceResult(
                step_id=step.step_id,
                execution_status="TIMEOUT",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                error_state="Simulated transient communication timeout.",
            )

        status = behavior.get("status", "SUCCESS")
        actual = behavior.get("actual_outcome", ObservationResultType.NORMAL)
        vals = behavior.get("observed_values", {})
        nrc = behavior.get("nrc_code")

        if status == "NRC":
            return SequenceResult(
                step_id=step.step_id,
                execution_status="NRC",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.ABNORMAL,
                error_state=f"Negative Response Code 0x{nrc or '22'}",
            )
        elif status == "TIMEOUT":
            return SequenceResult(
                step_id=step.step_id,
                execution_status="TIMEOUT",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                error_state="Simulated ECU timeout.",
            )
        elif status == "MALFORMED":
            return SequenceResult(
                step_id=step.step_id,
                execution_status="MALFORMED_RESPONSE",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state="Received malformed payload from ECU.",
            )

        return SequenceResult(
            step_id=step.step_id,
            execution_status="SUCCESS",
            observed_values=vals,
            evidence_references=[f"mock_{step.step_id}"],
            data_quality=SignalQuality.GOOD,
            actual_outcome=actual,
            provenance={"mock": True},
        )


# =====================================================================
# 7. PRECONDITION ENGINE
# =====================================================================

class PreconditionEngine:
    """
    Evaluates prerequisites for diagnostic steps without inventing thresholds
    or autonomously controlling vehicle systems.
    """
    def __init__(self, data_freshness_window_s: float = 60.0, allow_stale_data: bool = False):
        self.data_freshness_window_s = data_freshness_window_s
        self.allow_stale_data = allow_stale_data

    def evaluate_precondition(
        self,
        precondition: DiagnosticPrecondition,
        context: DiagnosticProcedureContext,
        sequence: DiagnosticSequence,
        current_signals: Optional[Dict[str, Any]] = None,
        signal_timestamps: Optional[Dict[str, float]] = None,
    ) -> Tuple[PreconditionStatus, str]:
        """
        Evaluates a single precondition against context, sequence state, and signal data.
        """
        now = time.time()
        current_signals = current_signals or {}
        signal_timestamps = signal_timestamps or {}

        # 1. Prerequisite step completion check
        if precondition.prerequisite_step_id:
            if precondition.prerequisite_step_id not in sequence.completed_steps:
                return (
                    PreconditionStatus.UNSATISFIED,
                    f"Prerequisite step '{precondition.prerequisite_step_id}' has not been completed.",
                )

        # 2. ECU reachability check
        if precondition.required_ecu_id:
            if precondition.required_ecu_id in context.unreachable_ecus:
                return (
                    PreconditionStatus.ECU_UNREACHABLE,
                    f"Required ECU '{precondition.required_ecu_id}' is unreachable.",
                )
            if context.available_ecus and precondition.required_ecu_id not in context.available_ecus:
                return (
                    PreconditionStatus.ECU_UNREACHABLE,
                    f"Required ECU '{precondition.required_ecu_id}' is not in available ECUs list.",
                )

        # 3. Operating condition check
        if precondition.required_operating_condition:
            req_cond = precondition.required_operating_condition.strip().upper()
            ctx_cond = (context.operating_condition or "").strip().upper()
            if req_cond != "UNKNOWN" and ctx_cond != req_cond:
                # Does not autonomously drive or alter vehicle state!
                return (
                    PreconditionStatus.PENDING_CONFIRMATION,
                    f"Operating condition mismatch: requires '{req_cond}', current is '{ctx_cond}'. Technician confirmation required.",
                )

        # 4. Required signals and freshness check
        if precondition.required_signals:
            for sig in precondition.required_signals:
                if sig not in current_signals:
                    return (
                        PreconditionStatus.UNSATISFIED,
                        f"Required signal '{sig}' is not available in current diagnostic dataset.",
                    )
                # Check freshness
                ts = signal_timestamps.get(sig)
                if ts is not None and not self.allow_stale_data:
                    age = now - ts
                    if age > self.data_freshness_window_s:
                        return (
                            PreconditionStatus.STALE_DATA,
                            f"Signal '{sig}' data is stale (age: {age:.1f}s, max allowed: {self.data_freshness_window_s}s).",
                        )

        return PreconditionStatus.SATISFIED, "Precondition satisfied."

    def evaluate_step_preconditions(
        self,
        step: DiagnosticStep,
        context: DiagnosticProcedureContext,
        sequence: DiagnosticSequence,
        current_signals: Optional[Dict[str, Any]] = None,
        signal_timestamps: Optional[Dict[str, float]] = None,
    ) -> Tuple[bool, PreconditionStatus, str]:
        """
        Evaluates all preconditions for a step. Returns (all_satisfied, worst_status, reason).
        """
        if not step.preconditions:
            return True, PreconditionStatus.SATISFIED, "No preconditions required."

        for prec in step.preconditions:
            status, reason = self.evaluate_precondition(
                prec, context, sequence, current_signals, signal_timestamps
            )
            prec.evaluated = True
            if status == PreconditionStatus.SATISFIED:
                prec.satisfied = True
                prec.failure_reason = None
            else:
                prec.satisfied = False
                prec.failure_reason = reason
                return False, status, reason

        return True, PreconditionStatus.SATISFIED, "All preconditions satisfied."


# =====================================================================
# 8. AUTOMATED TEST SEQUENCER ENGINE
# =====================================================================

class AutomatedTestSequencer:
    """
    Deterministic, machine-managed orchestrator for diagnostic test sequences.
    Answers:
      'Given the current diagnostic procedure, evidence, hypotheses, prerequisites,
       vehicle/ECU state, and safety constraints, what is the next valid test/observation
       to perform, when can it be performed, what result should be recorded, and which
       branch should follow?'
    """

    def __init__(
        self,
        execution_policy: Optional[SequenceExecutionPolicy] = None,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
        read_only_adapter: Optional[TestExecutionAdapter] = None,
        technician_adapter: Optional[TechnicianObservationAdapter] = None,
        diagnostic_graph: Optional[DiagnosticGraph] = None,
    ):
        self.policy = execution_policy or SequenceExecutionPolicy()
        self.safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)
        self.read_only_adapter = read_only_adapter or ReadOnlyAcquisitionAdapter(safety_policy=self.safety_policy)
        self.technician_adapter = technician_adapter or TechnicianObservationAdapter()
        self.diagnostic_graph = diagnostic_graph
        self.precondition_engine = PreconditionEngine(
            data_freshness_window_s=self.policy.data_freshness_window_s,
            allow_stale_data=self.policy.allow_stale_data,
        )

    # -----------------------------------------------------------------
    # A. Sequence Creation from H-1 Procedure
    # -----------------------------------------------------------------

    def create_sequence(
        self,
        procedure: DiagnosticProcedure,
        session_id: Optional[str] = None,
    ) -> DiagnosticSequence:
        """
        Creates a new DiagnosticSequence from a valid H-1 DiagnosticProcedure.
        Does NOT mutate the original procedure.
        Rejects invalid or malformed procedures.
        """
        if not procedure or not isinstance(procedure, DiagnosticProcedure):
            raise SequencerError("Invalid procedure: must provide a non-null DiagnosticProcedure instance.")

        if not procedure.procedure_id or not procedure.procedure_id.strip():
            raise SequencerError("Invalid procedure: missing procedure_id.")

        if not procedure.steps:
            raise SequencerError(f"Procedure '{procedure.procedure_id}' contains no diagnostic steps.")

        # Validate step order
        first_step_id = procedure.current_step_id or (procedure.step_sequence[0] if procedure.step_sequence else None)
        if not first_step_id or first_step_id not in procedure.steps:
            raise SequencerError(f"Procedure '{procedure.procedure_id}' has an invalid initial step.")

        seq_id = f"seq_{uuid.uuid4().hex[:12]}"
        actual_session = session_id or procedure.context.session_id or f"sess_{uuid.uuid4().hex[:8]}"

        pending = list(procedure.step_sequence)
        blocked = [sid for sid, s in procedure.steps.items() if s.is_blocked]

        sequence = DiagnosticSequence(
            sequence_id=seq_id,
            procedure_id=procedure.procedure_id,
            vehicle_id=procedure.context.vehicle_id,
            session_id=actual_session,
            current_step_id=first_step_id,
            execution_state=SequenceState.CREATED,
            completed_steps=[],
            pending_steps=pending,
            blocked_steps=blocked,
            policy=copy.deepcopy(self.policy),
            provenance={
                "created_by": "AutomatedTestSequencer",
                "procedure_title": procedure.title,
                "procedure_created_at": procedure.created_at,
            },
        )

        sequence.transition_to(SequenceState.READY, reason="Sequence initialized from DiagnosticProcedure.")
        return sequence

    # -----------------------------------------------------------------
    # B. Step Eligibility Evaluation
    # -----------------------------------------------------------------

    def evaluate_step_eligibility(
        self,
        sequence: DiagnosticSequence,
        procedure: DiagnosticProcedure,
        step_id: str,
        current_signals: Optional[Dict[str, Any]] = None,
        signal_timestamps: Optional[Dict[str, float]] = None,
    ) -> Tuple[StepEligibility, str]:
        """
        Evaluates whether a step is eligible to execute right now.
        Checks:
          - Step existence
          - Prior completion
          - Prior blocking
          - Execution mode safety (rejects ACTIVE_DIAGNOSTIC)
          - ECU reachability
          - Preconditions
          - Safety policy revalidation
        """
        step = procedure.steps.get(step_id)
        if not step:
            return StepEligibility.INVALID, f"Step '{step_id}' does not exist in procedure."

        # Already completed?
        if step_id in sequence.completed_steps:
            return StepEligibility.ALREADY_COMPLETED, f"Step '{step_id}' has already been completed."

        # Blocked in procedure?
        if step.is_blocked or step_id in sequence.blocked_steps:
            return StepEligibility.BLOCKED, f"Step '{step_id}' is marked as blocked: {step.blocking_reason or 'No reason'}."

        # Prohibited execution mode?
        if step.execution_mode == StepExecutionMode.ACTIVE_DIAGNOSTIC:
            return StepEligibility.SAFETY_BLOCKED, f"Step '{step_id}' requests ACTIVE_DIAGNOSTIC which is strictly prohibited."

        # Immediate safety policy check on step
        if step.safety_classification != ServiceSafetyClassification.READ_ONLY:
            return StepEligibility.SAFETY_BLOCKED, (
                f"Step '{step_id}' safety classification '{step.safety_classification.value}' is not READ_ONLY."
            )

        # Target ECU reachability
        if step.target_ecu in procedure.context.unreachable_ecus:
            return StepEligibility.WAITING, f"Target ECU '{step.target_ecu}' is unreachable."

        # Evaluate preconditions
        prec_ok, prec_status, prec_reason = self.precondition_engine.evaluate_step_preconditions(
            step, procedure.context, sequence, current_signals, signal_timestamps
        )
        if not prec_ok:
            if prec_status == PreconditionStatus.PENDING_CONFIRMATION:
                return StepEligibility.WAITING, f"Precondition waiting: {prec_reason}"
            elif prec_status == PreconditionStatus.STALE_DATA:
                return StepEligibility.INSUFFICIENT_DATA, f"Precondition stale data: {prec_reason}"
            elif prec_status == PreconditionStatus.ECU_UNREACHABLE:
                return StepEligibility.BLOCKED, f"Precondition ECU unreachable: {prec_reason}"
            else:
                return StepEligibility.WAITING, f"Precondition not satisfied: {prec_reason}"

        return StepEligibility.ELIGIBLE, "Step is eligible for execution."

    # -----------------------------------------------------------------
    # C. Immediate Safety Gate & Safety Drift Protection
    # -----------------------------------------------------------------

    def validate_safety_before_dispatch(
        self,
        step: DiagnosticStep,
        descriptor: Optional[SequenceActionDescriptor],
    ) -> Tuple[bool, str]:
        """
        Enforces safety immediately before transport dispatch.
        Protects against safety drift: re-verifies even if previously approved.
        """
        # 1. Mode check
        if step.execution_mode == StepExecutionMode.ACTIVE_DIAGNOSTIC:
            return False, "ACTIVE_DIAGNOSTIC is strictly prohibited in H-2."

        # 2. Classification check
        if step.safety_classification != ServiceSafetyClassification.READ_ONLY:
            return False, f"Non-READ_ONLY classification '{step.safety_classification.value}' prohibited."

        # 3. Descriptor service check
        if descriptor:
            norm_sid = (descriptor.service_id or "").strip().upper()
            if norm_sid in PROHIBITED_SERVICES:
                return False, f"Prohibited service 0x{norm_sid} (write/actuation/programming/clear) rejected."

            # Verify through G-1 safety policy
            req = AdvancedServiceRequest(
                service_id=descriptor.service_id,
                payload=descriptor.identifier,
                target_ecu=descriptor.target_ecu,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
            )
            safe, reason = self.safety_policy.validate_request(req)
            if not safe:
                return False, f"G-1 Safety Policy rejected request: {reason}"

        return True, "Safety check passed."

    # -----------------------------------------------------------------
    # D. Step Execution Orchestration
    # -----------------------------------------------------------------

    def execute_current_step(
        self,
        sequence: DiagnosticSequence,
        procedure: DiagnosticProcedure,
        descriptor: Optional[SequenceActionDescriptor] = None,
        technician_input: Optional[Dict[str, Any]] = None,
        current_signals: Optional[Dict[str, Any]] = None,
        signal_timestamps: Optional[Dict[str, float]] = None,
    ) -> SequenceResult:
        """
        Orchestrates execution of sequence's current step.
        Enforces:
          - Sequence state lifecycle
          - Step eligibility
          - Safety revalidation immediately before execution
          - Bounded retries
          - Deterministic branch evaluation
          - Loop protection
        """
        if sequence.is_terminal:
            raise SequenceStateError(f"Cannot execute step: sequence is in terminal state '{sequence.execution_state.value}'.")

        step_id = sequence.current_step_id
        if not step_id:
            sequence.transition_to(SequenceState.COMPLETED, reason="No more steps to execute.")
            return SequenceResult(
                step_id="NONE",
                execution_status="COMPLETED",
                actual_outcome=ObservationResultType.NORMAL,
            )

        step = procedure.steps.get(step_id)
        if not step:
            sequence.transition_to(SequenceState.FAILED, reason=f"Current step '{step_id}' not found in procedure.")
            raise SequencerError(f"Step '{step_id}' does not exist in procedure.")

        # Track step visits & check loop protection
        sequence.step_visit_counts[step_id] += 1
        if len(sequence.completed_steps) >= sequence.policy.max_sequence_steps:
            sequence.transition_to(SequenceState.BLOCKED, reason="Maximum sequence steps exceeded (loop protection).")
            sequence.record_event(
                SequenceEventType.LOOP_DETECTED,
                reason=f"Exceeded max_sequence_steps ({sequence.policy.max_sequence_steps}).",
                step_id=step_id,
            )
            return SequenceResult(
                step_id=step_id,
                execution_status="LOOP_BLOCKED",
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state="Maximum sequence steps exceeded.",
            )

        # Step Execution Record
        step_exec = sequence.step_executions.get(step_id)
        if not step_exec:
            step_exec = SequenceStepExecution(step_id=step_id, started_at=time.time())
            sequence.step_executions[step_id] = step_exec

        step_exec.attempt_count += 1

        # Check global timeout
        if (time.time() - sequence.created_at) > sequence.policy.global_timeout_s:
            sequence.transition_to(SequenceState.FAILED, reason="Global sequence execution timeout expired.")
            sequence.record_event(SequenceEventType.TIMEOUT, reason="Global timeout expired.", step_id=step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="TIMEOUT",
                data_quality=SignalQuality.ERROR,
                actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                error_state="Global sequence execution timeout expired.",
            )

        # 1. Evaluate Step Eligibility
        eligibility, elig_reason = self.evaluate_step_eligibility(
            sequence, procedure, step_id, current_signals, signal_timestamps
        )

        if eligibility == StepEligibility.ALREADY_COMPLETED:
            # Advance to next available step in sequence
            next_step_id = self._find_next_pending_step(sequence, procedure)
            sequence.current_step_id = next_step_id
            if not next_step_id:
                sequence.transition_to(SequenceState.COMPLETED, reason="All steps completed.")
            return SequenceResult(
                step_id=step_id,
                execution_status="ALREADY_COMPLETED",
                actual_outcome=ObservationResultType.NORMAL,
            )

        if eligibility == StepEligibility.SAFETY_BLOCKED:
            sequence.transition_to(SequenceState.BLOCKED, reason=f"Step safety blocked: {elig_reason}", step_id=step_id)
            sequence.record_event(SequenceEventType.SAFETY_CHECK_FAILED, reason=elig_reason, step_id=step_id)
            if step_id not in sequence.blocked_steps:
                sequence.blocked_steps.append(step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="SAFETY_BLOCKED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=elig_reason,
            )

        if eligibility == StepEligibility.WAITING:
            sequence.transition_to(SequenceState.WAITING_FOR_PRECONDITION, reason=elig_reason, step_id=step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="WAITING_FOR_PRECONDITION",
                data_quality=SignalQuality.SUSPECT,
                actual_outcome=ObservationResultType.NOT_TESTED,
                error_state=elig_reason,
            )

        if eligibility == StepEligibility.INSUFFICIENT_DATA:
            sequence.transition_to(SequenceState.WAITING_FOR_DATA, reason=elig_reason, step_id=step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="INSUFFICIENT_DATA",
                data_quality=SignalQuality.STALE,
                actual_outcome=ObservationResultType.NOT_TESTED,
                error_state=elig_reason,
            )

        if eligibility == StepEligibility.BLOCKED:
            sequence.transition_to(SequenceState.BLOCKED, reason=elig_reason, step_id=step_id)
            if step_id not in sequence.blocked_steps:
                sequence.blocked_steps.append(step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="BLOCKED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=elig_reason,
            )

        # 2. Immediate Safety Gate Verification before dispatch (Safety Drift Protection)
        safe, safety_reason = self.validate_safety_before_dispatch(step, descriptor)
        if not safe:
            sequence.transition_to(SequenceState.BLOCKED, reason=safety_reason, step_id=step_id)
            sequence.record_event(SequenceEventType.SAFETY_CHECK_FAILED, reason=safety_reason, step_id=step_id)
            if step_id not in sequence.blocked_steps:
                sequence.blocked_steps.append(step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="SAFETY_BLOCKED",
                data_quality=SignalQuality.INVALID,
                actual_outcome=ObservationResultType.UNKNOWN,
                error_state=safety_reason,
            )

        sequence.record_event(SequenceEventType.SAFETY_CHECK_PASSED, reason="Safety revalidated before dispatch.", step_id=step_id)

        # 3. Transition to RUNNING / EXECUTING
        if sequence.execution_state != SequenceState.RUNNING:
            sequence.transition_to(SequenceState.RUNNING, reason=f"Executing step {step_id}.", step_id=step_id)

        sequence.record_event(SequenceEventType.STEP_STARTED, reason=f"Attempt {step_exec.attempt_count}", step_id=step_id)

        # 4. Select Adapter & Execute
        result: SequenceResult
        if step.execution_mode in (StepExecutionMode.OBSERVATIONAL, StepExecutionMode.MEASUREMENT, StepExecutionMode.INFORMATIONAL):
            # Check if technician input was supplied or if manual input is required
            if technician_input is not None:
                sequence.transition_to(SequenceState.WAITING_FOR_TECHNICIAN, reason="Processing technician input.", step_id=step_id)
                try:
                    obs = self.technician_adapter.validate_technician_input(
                        step=step,
                        result_type=technician_input.get("result_type", ObservationResultType.NORMAL),
                        measured_value=technician_input.get("measured_value"),
                        unit=technician_input.get("unit"),
                        notes=technician_input.get("notes", ""),
                        technician_id=technician_input.get("technician_id"),
                    )
                    # Attach validated observation to a step copy/result
                    step_exec.adapter_used = "TechnicianObservationAdapter"
                    sequence.record_event(
                        SequenceEventType.TECHNICIAN_INPUT_RECEIVED,
                        reason=f"Validated observation {obs.result_type.value}",
                        step_id=step_id,
                    )
                    sequence.transition_to(SequenceState.EVALUATING, reason="Evaluating technician observation.", step_id=step_id)
                    result = SequenceResult(
                        step_id=step_id,
                        execution_status="SUCCESS",
                        observed_values={
                            "result_type": obs.result_type.value,
                            "measured_value": obs.measured_value,
                            "unit": obs.unit,
                        },
                        evidence_references=[f"obs_{obs.observation_id}"],
                        data_quality=SignalQuality.GOOD,
                        actual_outcome=obs.result_type,
                        provenance={"technician_id": obs.technician_id, "timestamp": obs.timestamp},
                    )
                except TechnicianValidationError as e:
                    sequence.record_event(SequenceEventType.STEP_FAILED, reason=str(e), step_id=step_id)
                    raise
            elif descriptor:
                # Controlled read-only acquisition for observational step
                sequence.transition_to(SequenceState.EXECUTING, reason="Executing read-only acquisition.", step_id=step_id)
                step_exec.adapter_used = "ReadOnlyAcquisitionAdapter"
                result = self.read_only_adapter.execute(step, descriptor, sequence)
                sequence.transition_to(SequenceState.EVALUATING, reason="Evaluating acquisition outcome.", step_id=step_id)
            else:
                # Waiting for technician input
                sequence.transition_to(SequenceState.WAITING_FOR_TECHNICIAN, reason="Waiting for technician action.", step_id=step_id)
                sequence.record_event(SequenceEventType.TECHNICIAN_INPUT_REQUESTED, reason=step.technician_instruction, step_id=step_id)
                return SequenceResult(
                    step_id=step_id,
                    execution_status="WAITING_FOR_TECHNICIAN",
                    data_quality=SignalQuality.SUSPECT,
                    actual_outcome=ObservationResultType.NOT_TESTED,
                    error_state="Step waiting for technician observation input.",
                )
        else:
            # Unsupported execution mode
            sequence.transition_to(SequenceState.BLOCKED, reason=f"Unsupported mode {step.execution_mode.value}", step_id=step_id)
            return SequenceResult(
                step_id=step_id,
                execution_status="UNSUPPORTED_MODE",
                actual_outcome=ObservationResultType.UNKNOWN,
            )

        # 5. Handle Retry on Transient Communication Failure
        if result.execution_status in ("TIMEOUT", "NRC", STATUS_TIMEOUT, STATUS_NRC, STATUS_SERIAL_ERROR):
            step_exec.result = result
            step_exec.status = result.execution_status
            if step_exec.attempt_count <= sequence.policy.max_retries_per_step:
                sequence.record_event(
                    SequenceEventType.STEP_RETRY,
                    reason=f"Transient failure ({result.execution_status}), retrying (attempt {step_exec.attempt_count}/{sequence.policy.max_retries_per_step}).",
                    step_id=step_id,
                )
                sequence.transition_to(SequenceState.RUNNING, reason="Retrying step.", step_id=step_id)
                return result

        # 6. Branch Evaluation & Progression
        sequence.transition_to(SequenceState.BRANCHING, reason="Evaluating procedure branches.", step_id=step_id)
        next_step_id, term_outcome = self.evaluate_branches(step, result.actual_outcome, sequence)

        result.branch_decision = next_step_id or (term_outcome.value if term_outcome else None)
        step_exec.completed_at = time.time()
        step_exec.result = result
        step_exec.status = result.execution_status

        # Update sequence lists
        if step_id not in sequence.completed_steps:
            sequence.completed_steps.append(step_id)
        if step_id in sequence.pending_steps:
            sequence.pending_steps.remove(step_id)

        sequence.record_event(
            SequenceEventType.STEP_COMPLETED,
            reason=f"Step completed with outcome '{result.actual_outcome.value}'.",
            step_id=step_id,
        )

        # 7. Update Graph with Execution Event
        if self.diagnostic_graph:
            self._update_graph_with_result(sequence, step, result)

        # 8. Check Termination or Advance
        if term_outcome:
            sequence.final_outcome = term_outcome
            sequence.termination_reason = f"Branch terminated with outcome '{term_outcome.value}'."
            sequence.transition_to(SequenceState.COMPLETED, reason=sequence.termination_reason, step_id=step_id)
        elif next_step_id:
            sequence.current_step_id = next_step_id
            sequence.transition_to(SequenceState.RUNNING, reason=f"Advancing to step '{next_step_id}'.", step_id=next_step_id)
        else:
            # Check if any more pending steps exist
            next_pending = self._find_next_pending_step(sequence, procedure)
            if next_pending:
                sequence.current_step_id = next_pending
                sequence.transition_to(SequenceState.RUNNING, reason=f"Advancing to next pending step '{next_pending}'.", step_id=next_pending)
            else:
                sequence.final_outcome = ProcedureOutcome.ALL_STEPS_COMPLETED if hasattr(ProcedureOutcome, "ALL_STEPS_COMPLETED") else ProcedureOutcome.HYPOTHESIS_SUPPORTED
                sequence.termination_reason = "All procedure steps completed."
                sequence.transition_to(SequenceState.COMPLETED, reason=sequence.termination_reason, step_id=step_id)

        return result

    # -----------------------------------------------------------------
    # E. Deterministic Branch Selection & Ambiguity Handling
    # -----------------------------------------------------------------

    def evaluate_branches(
        self,
        step: DiagnosticStep,
        actual_outcome: ObservationResultType,
        sequence: DiagnosticSequence,
    ) -> Tuple[Optional[str], Optional[ProcedureOutcome]]:
        """
        Matches actual outcome against step's branches deterministically.
        Handles:
          - Multiple matching branches (deterministic priority vs explicit ambiguity error)
          - Branch visit count tracking and loop detection
          - Clean fallback if no branch matches
        """
        matching_branches = [
            b for b in step.branches
            if b.condition_outcome == actual_outcome
        ]

        if not matching_branches:
            # Fallback check: look for generic UNKNOWN or ABNORMAL if specific wasn't matched
            fallback_matches = [
                b for b in step.branches
                if b.condition_outcome == ObservationResultType.UNKNOWN
            ]
            if fallback_matches:
                matching_branches = fallback_matches

        if not matching_branches:
            sequence.record_event(
                SequenceEventType.BRANCH_EVALUATED,
                reason=f"No matching branch found for outcome '{actual_outcome.value}'. Proceeding to next sequence step.",
                step_id=step.step_id,
            )
            return None, None

        selected_branch: DiagnosticBranch
        if len(matching_branches) == 1:
            selected_branch = matching_branches[0]
        else:
            # Deterministic resolution: sort by confidence adjustment descending, then branch_id
            matching_branches.sort(
                key=lambda b: (-b.confidence_adjustment, b.branch_id)
            )
            selected_branch = matching_branches[0]
            sequence.record_event(
                SequenceEventType.BRANCH_EVALUATED,
                reason=f"Multiple branches matched outcome '{actual_outcome.value}'; deterministically selected branch '{selected_branch.branch_id}'.",
                step_id=step.step_id,
            )

        sequence.active_branch_id = selected_branch.branch_id
        sequence.branch_visit_counts[selected_branch.branch_id] += 1

        # Check loop protection on branch revisits
        if sequence.branch_visit_counts[selected_branch.branch_id] > sequence.policy.max_branch_revisits:
            sequence.record_event(
                SequenceEventType.LOOP_DETECTED,
                reason=f"Branch '{selected_branch.branch_id}' revisited {sequence.branch_visit_counts[selected_branch.branch_id]} times (max: {sequence.policy.max_branch_revisits}).",
                step_id=step.step_id,
            )
            raise SequenceLoopError(
                f"Loop detected: branch '{selected_branch.branch_id}' exceeded max_branch_revisits ({sequence.policy.max_branch_revisits})."
            )

        sequence.record_event(
            SequenceEventType.BRANCH_EVALUATED,
            reason=f"Selected branch '{selected_branch.branch_id}' -> target '{selected_branch.target_step_id or selected_branch.terminal_outcome}'.",
            step_id=step.step_id,
        )

        return selected_branch.target_step_id, selected_branch.terminal_outcome

    # -----------------------------------------------------------------
    # F. Cancellation / Abort
    # -----------------------------------------------------------------

    def cancel_sequence(self, sequence: DiagnosticSequence, reason: str = "User cancelled sequence.") -> None:
        """
        Safely cancels an active sequence.
        Preserves all completed evidence, stops future dispatches, and records event.
        """
        if sequence.is_terminal:
            return

        sequence.termination_reason = reason
        sequence.transition_to(SequenceState.ABORTED, reason=reason)
        sequence.record_event(SequenceEventType.CANCELLED, reason=reason)

    # -----------------------------------------------------------------
    # G. Helpers & Graph Integration
    # -----------------------------------------------------------------

    def _find_next_pending_step(
        self,
        sequence: DiagnosticSequence,
        procedure: DiagnosticProcedure,
    ) -> Optional[str]:
        """Finds the next uncompleted step according to procedure.step_sequence."""
        for sid in procedure.step_sequence:
            if sid not in sequence.completed_steps and sid not in sequence.blocked_steps:
                return sid
        return None

    def _update_graph_with_result(
        self,
        sequence: DiagnosticSequence,
        step: DiagnosticStep,
        result: SequenceResult,
    ) -> None:
        """
        Integrates sequence execution events into the existing G-5 diagnostic graph.
        Does not create duplicate graph representations.
        """
        if not self.diagnostic_graph:
            return

        try:
            obs_node_id = f"obs:{sequence.sequence_id}:{step.step_id}"
            obs_label = f"Test Result: {step.title} ({result.actual_outcome.value})"
            
            node = GraphNode(
                node_id=obs_node_id,
                node_type=GraphNodeType.OBSERVATION,
                label=obs_label,
                properties={
                    "ecu_id": step.target_ecu,
                    "sequence_id": sequence.sequence_id,
                    "step_id": step.step_id,
                    "outcome": result.actual_outcome.value,
                    "status": result.execution_status,
                    "quality": result.data_quality.value,
                    "timestamp": result.timestamp,
                },
            )
            self.diagnostic_graph.add_node(node)

            # Link observation to target ECU node if ECU node exists
            ecu_node_id = make_ecu_node_id(step.target_ecu)
            if ecu_node_id in self.diagnostic_graph.nodes:
                edge = GraphEdge(
                    edge_id=f"edge:{ecu_node_id}:{obs_node_id}",
                    source_node_id=ecu_node_id,
                    target_node_id=obs_node_id,
                    edge_type=GraphEdgeType.OBSERVES,
                    properties={"step_id": step.step_id},
                )
                self.diagnostic_graph.add_edge(edge)

        except Exception as e:
            logger.warning(f"Failed to update diagnostic graph with sequence result: {e}")
