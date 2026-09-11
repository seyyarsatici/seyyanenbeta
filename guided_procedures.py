# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase H-1: Guided Diagnostic Procedures Foundation
=============================================================================
This module implements Phase H-1 of the Seyyanen diagnostic platform.
It transforms the platform from an evidence, hypothesis, and graph analysis
system (G-1 through G-5) into a deterministic, evidence-driven guided procedure
engine for automotive technicians.

Core Architectural Invariants:
  1. GUIDED, NOT AUTONOMOUS:
     Recommends and sequences diagnostic steps with full rationale, but does
     NOT autonomously execute destructive tests, actuator tests, programming,
     coding, ECU writes, or unsafe procedures.
  2. EXECUTION MODES RESTRICTED IN H-1:
     Permits INFORMATIONAL, OBSERVATIONAL, and MEASUREMENT steps.
     ACTIVE_DIAGNOSTIC is represented for future phases but is strictly
     BLOCKED / NON-EXECUTABLE in H-1.
  3. STRICT G SAFETY REUSE:
     Mode 04/14 DTC clear, 0x2E (Write), 0x27 (Security), 0x2F (Actuation),
     and 0x34/36/37 (Programming) are strictly prohibited and rejected.
  4. DETERMINISTIC & EXPLAINABLE:
     100% deterministic offline step prioritization and branch selection.
     Every step exposes clear technician-facing instructions and why it was
     chosen without internal graph/code jargon.
  5. HYPOTHESIS & GRAPH AWARE:
     Consumes G-3 hypotheses (primary and competing), operating conditions,
     anomalies, and G-5 vehicle diagnostic graph relationships.
  6. COMMUNICATION != COMPONENT FAULT:
     Unreachable ECUs branch into communication/power/bus diagnosis rather
     than falsely recommending component replacement.
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
from typing import Any, Callable, ClassVar, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

# Integration imports from C, D, E, F, G layers
from advanced_ecu_services import (
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    SessionType,
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
    PointAnomaly,
    TemporalAnomaly,
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


class ProcedureError(Exception):
    """Base exception for guided diagnostic procedure errors."""
    pass


class ProcedureStateError(ProcedureError):
    """Raised when an invalid procedure lifecycle transition is attempted."""
    pass


class ProcedureSafetyError(ProcedureError):
    """Raised when a procedure step violates safety invariants."""
    pass


class UnsupportedActionError(ProcedureError):
    """Raised when an unsupported active action or workshop procedure is requested."""
    pass


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class ProcedureState(str, enum.Enum):
    """Lifecycle state machine for a guided diagnostic procedure."""
    DRAFT = "DRAFT"
    READY = "READY"
    ACTIVE = "ACTIVE"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class StepExecutionMode(str, enum.Enum):
    """Execution mode of an individual diagnostic step."""
    INFORMATIONAL = "INFORMATIONAL"      # Review existing evidence, DTC, historical context
    OBSERVATIONAL = "OBSERVATIONAL"      # Inspect live data, observe operating condition, visual check
    MEASUREMENT = "MEASUREMENT"          # Measure physical quantity with multimeter/tool
    ACTIVE_DIAGNOSTIC = "ACTIVE_DIAGNOSTIC"  # Actuator test, bi-directional control (BLOCKED in H-1)


class StepPriority(str, enum.Enum):
    """Diagnostic priority classification of a step."""
    MANDATORY = "MANDATORY"
    RECOMMENDED = "RECOMMENDED"
    OPTIONAL = "OPTIONAL"
    INFORMATIONAL = "INFORMATIONAL"


class ObservationResultType(str, enum.Enum):
    """Structured outcomes recorded by a technician during procedure execution."""
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"
    NOT_PRESENT = "NOT_PRESENT"
    INTERMITTENT = "INTERMITTENT"
    UNKNOWN = "UNKNOWN"
    NOT_TESTED = "NOT_TESTED"
    MEASURED_VALUE = "MEASURED_VALUE"
    COMMUNICATION_FAILURE = "COMMUNICATION_FAILURE"


class ProcedureOutcome(str, enum.Enum):
    """Structured conclusion reached at procedure termination."""
    HYPOTHESIS_SUPPORTED = "HYPOTHESIS_SUPPORTED"
    HYPOTHESIS_WEAKENED = "HYPOTHESIS_WEAKENED"
    HYPOTHESES_DISCRIMINATED = "HYPOTHESES_DISCRIMINATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    COMMUNICATION_PROBLEM = "COMMUNICATION_PROBLEM"
    NO_CONFIDENT_CONCLUSION = "NO_CONFIDENT_CONCLUSION"
    REQUIRES_MANUAL_TEST = "REQUIRES_MANUAL_TEST"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


class StopConditionType(str, enum.Enum):
    """Reasons for deterministic termination of a diagnostic procedure."""
    HYPOTHESIS_RESOLVED = "HYPOTHESIS_RESOLVED"
    ALL_STEPS_COMPLETED = "ALL_STEPS_COMPLETED"
    SAFETY_RESTRICTION = "SAFETY_RESTRICTION"
    COMMUNICATION_FAULT = "COMMUNICATION_FAULT"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"
    PREREQUISITE_FAILED = "PREREQUISITE_FAILED"
    VEHICLE_MISMATCH = "VEHICLE_MISMATCH"


# =====================================================================
# 2. DATA STRUCTURES & SUBORDINATE MODELS
# =====================================================================

@dataclass
class DiagnosticPrecondition:
    """
    Prerequisites required before a diagnostic step can be safely performed.
    """
    description: str
    required_ecu_id: Optional[str] = None
    required_operating_condition: Optional[str] = None
    required_signals: List[str] = field(default_factory=list)
    prerequisite_step_id: Optional[str] = None
    evaluated: bool = False
    satisfied: bool = False
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "required_ecu_id": self.required_ecu_id,
            "required_operating_condition": self.required_operating_condition,
            "required_signals": self.required_signals,
            "prerequisite_step_id": self.prerequisite_step_id,
            "evaluated": self.evaluated,
            "satisfied": self.satisfied,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticPrecondition":
        return cls(
            description=data["description"],
            required_ecu_id=data.get("required_ecu_id"),
            required_operating_condition=data.get("required_operating_condition"),
            required_signals=data.get("required_signals", []),
            prerequisite_step_id=data.get("prerequisite_step_id"),
            evaluated=data.get("evaluated", False),
            satisfied=data.get("satisfied", False),
            failure_reason=data.get("failure_reason"),
        )


@dataclass
class DiagnosticExpectedObservation:
    """
    Concrete expected observation for a step.
    Strictly avoids fabricating unverified factory pinouts or exact voltages.
    """
    description: str
    signal_name: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: Optional[str] = None
    expected_state: Optional[str] = None
    relationship_description: Optional[str] = None
    trusted_source: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "signal_name": self.signal_name,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "unit": self.unit,
            "expected_state": self.expected_state,
            "relationship_description": self.relationship_description,
            "trusted_source": self.trusted_source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticExpectedObservation":
        return cls(
            description=data["description"],
            signal_name=data.get("signal_name"),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            unit=data.get("unit"),
            expected_state=data.get("expected_state"),
            relationship_description=data.get("relationship_description"),
            trusted_source=data.get("trusted_source", True),
        )


@dataclass
class DiagnosticBranch:
    """
    Conditional branch mapping an observation outcome to a next step or terminal outcome.
    """
    branch_id: str
    condition_outcome: ObservationResultType
    target_step_id: Optional[str] = None
    terminal_outcome: Optional[ProcedureOutcome] = None
    confidence_adjustment: float = 0.0
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "condition_outcome": self.condition_outcome.value,
            "target_step_id": self.target_step_id,
            "terminal_outcome": self.terminal_outcome.value if self.terminal_outcome else None,
            "confidence_adjustment": round(self.confidence_adjustment, 2),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticBranch":
        term = data.get("terminal_outcome")
        return cls(
            branch_id=data["branch_id"],
            condition_outcome=ObservationResultType(data["condition_outcome"]),
            target_step_id=data.get("target_step_id"),
            terminal_outcome=ProcedureOutcome(term) if term else None,
            confidence_adjustment=float(data.get("confidence_adjustment", 0.0)),
            rationale=data.get("rationale", ""),
        )


@dataclass
class DiagnosticStopCondition:
    """
    Explicit condition that causes a diagnostic procedure to safely terminate.
    """
    condition_type: StopConditionType
    description: str
    terminal_outcome: ProcedureOutcome
    is_triggered: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition_type": self.condition_type.value,
            "description": self.description,
            "terminal_outcome": self.terminal_outcome.value,
            "is_triggered": self.is_triggered,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticStopCondition":
        return cls(
            condition_type=StopConditionType(data["condition_type"]),
            description=data["description"],
            terminal_outcome=ProcedureOutcome(data["terminal_outcome"]),
            is_triggered=data.get("is_triggered", False),
        )


@dataclass
class TechnicianObservation:
    """
    Structured record of observation, measurement, or verification provided by the technician.
    """
    observation_id: str
    step_id: str
    result_type: ObservationResultType
    measured_value: Optional[float] = None
    unit: Optional[str] = None
    notes: str = ""
    technician_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "step_id": self.step_id,
            "result_type": self.result_type.value,
            "measured_value": self.measured_value,
            "unit": self.unit,
            "notes": self.notes,
            "technician_id": self.technician_id,
            "timestamp": round(self.timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TechnicianObservation":
        return cls(
            observation_id=data["observation_id"],
            step_id=data["step_id"],
            result_type=ObservationResultType(data["result_type"]),
            measured_value=data.get("measured_value"),
            unit=data.get("unit"),
            notes=data.get("notes", ""),
            technician_id=data.get("technician_id"),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class DiagnosticStep:
    """
    An individual structured diagnostic step in a guided procedure.
    """
    step_id: str
    sequence: int
    title: str
    technician_instruction: str
    purpose: str
    rationale: str
    target_ecu: str
    required_evidence_ids: List[str] = field(default_factory=list)
    preconditions: List[DiagnosticPrecondition] = field(default_factory=list)
    expected_observation: Optional[DiagnosticExpectedObservation] = None
    possible_outcomes: List[ObservationResultType] = field(default_factory=list)
    branches: List[DiagnosticBranch] = field(default_factory=list)
    estimated_time_minutes: Optional[int] = 5
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    execution_mode: StepExecutionMode = StepExecutionMode.OBSERVATIONAL
    priority: StepPriority = StepPriority.RECOMMENDED
    provenance: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8
    is_blocked: bool = False
    blocking_reason: Optional[str] = None
    is_data_insufficient: bool = False
    missing_data_details: Optional[str] = None
    technician_observation: Optional[TechnicianObservation] = None
    completed: bool = False
    target_hypotheses: List[str] = field(default_factory=list)
    discriminated_hypotheses: List[str] = field(default_factory=list)
    priority_score: float = 0.0
    priority_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence": self.sequence,
            "title": self.title,
            "technician_instruction": self.technician_instruction,
            "purpose": self.purpose,
            "rationale": self.rationale,
            "target_ecu": self.target_ecu,
            "required_evidence_ids": self.required_evidence_ids,
            "preconditions": [p.to_dict() for p in self.preconditions],
            "expected_observation": self.expected_observation.to_dict() if self.expected_observation else None,
            "possible_outcomes": [o.value for o in self.possible_outcomes],
            "branches": [b.to_dict() for b in self.branches],
            "estimated_time_minutes": self.estimated_time_minutes,
            "safety_classification": self.safety_classification.value,
            "execution_mode": self.execution_mode.value,
            "priority": self.priority.value,
            "provenance": self.provenance,
            "confidence": round(self.confidence, 2),
            "is_blocked": self.is_blocked,
            "blocking_reason": self.blocking_reason,
            "is_data_insufficient": self.is_data_insufficient,
            "missing_data_details": self.missing_data_details,
            "technician_observation": self.technician_observation.to_dict() if self.technician_observation else None,
            "completed": self.completed,
            "target_hypotheses": self.target_hypotheses,
            "discriminated_hypotheses": self.discriminated_hypotheses,
            "priority_score": round(self.priority_score, 2),
            "priority_reason": self.priority_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticStep":
        obs_data = data.get("expected_observation")
        tech_data = data.get("technician_observation")
        return cls(
            step_id=data["step_id"],
            sequence=data["sequence"],
            title=data["title"],
            technician_instruction=data["technician_instruction"],
            purpose=data["purpose"],
            rationale=data["rationale"],
            target_ecu=data["target_ecu"],
            required_evidence_ids=data.get("required_evidence_ids", []),
            preconditions=[DiagnosticPrecondition.from_dict(p) for p in data.get("preconditions", [])],
            expected_observation=DiagnosticExpectedObservation.from_dict(obs_data) if obs_data else None,
            possible_outcomes=[ObservationResultType(o) for o in data.get("possible_outcomes", [])],
            branches=[DiagnosticBranch.from_dict(b) for b in data.get("branches", [])],
            estimated_time_minutes=data.get("estimated_time_minutes", 5),
            safety_classification=ServiceSafetyClassification(data.get("safety_classification", "READ_ONLY")),
            execution_mode=StepExecutionMode(data.get("execution_mode", "OBSERVATIONAL")),
            priority=StepPriority(data.get("priority", "RECOMMENDED")),
            provenance=data.get("provenance", {}),
            confidence=float(data.get("confidence", 0.8)),
            is_blocked=data.get("is_blocked", False),
            blocking_reason=data.get("blocking_reason"),
            is_data_insufficient=data.get("is_data_insufficient", False),
            missing_data_details=data.get("missing_data_details"),
            technician_observation=TechnicianObservation.from_dict(tech_data) if tech_data else None,
            completed=data.get("completed", False),
            target_hypotheses=data.get("target_hypotheses", []),
            discriminated_hypotheses=data.get("discriminated_hypotheses", []),
            priority_score=float(data.get("priority_score", 0.0)),
            priority_reason=data.get("priority_reason", ""),
        )


@dataclass
class DiagnosticProcedureContext:
    """Vehicle and environmental context governing procedure execution."""
    vehicle_id: str
    session_id: str
    vehicle_context: Optional[VehicleContext] = None
    available_ecus: List[str] = field(default_factory=list)
    unreachable_ecus: List[str] = field(default_factory=list)
    operating_condition: str = "UNKNOWN"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "session_id": self.session_id,
            "vehicle_context": {
                "manufacturer": self.vehicle_context.manufacturer if self.vehicle_context else None,
                "model": self.vehicle_context.model if self.vehicle_context else None,
                "model_year": self.vehicle_context.model_year if self.vehicle_context else None,
                "engine_code": self.vehicle_context.engine_code if self.vehicle_context else None,
            } if self.vehicle_context else None,
            "available_ecus": self.available_ecus,
            "unreachable_ecus": self.unreachable_ecus,
            "operating_condition": self.operating_condition,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticProcedureContext":
        vc_data = data.get("vehicle_context")
        vc = None
        if vc_data:
            vc = VehicleContext(
                manufacturer=vc_data.get("manufacturer") or "UNKNOWN",
                model=vc_data.get("model") or "UNKNOWN",
                model_year=vc_data.get("model_year") or "UNKNOWN",
                engine_code=vc_data.get("engine_code") or "UNKNOWN",
            )
        return cls(
            vehicle_id=data["vehicle_id"],
            session_id=data["session_id"],
            vehicle_context=vc,
            available_ecus=data.get("available_ecus", []),
            unreachable_ecus=data.get("unreachable_ecus", []),
            operating_condition=data.get("operating_condition", "UNKNOWN"),
            metadata=data.get("metadata", {}),
        )


# =====================================================================
# 3. DIAGNOSTIC PROCEDURE ROOT MODEL
# =====================================================================

@dataclass
class DiagnosticProcedure:
    """
    Root serializable container for a complete guided diagnostic procedure.
    Maintains ordered steps, state machine lifecycle, branching transitions,
    provenance, and structured outcomes.
    """
    procedure_id: str
    context: DiagnosticProcedureContext
    title: str
    objective: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    triggering_dtcs: List[str] = field(default_factory=list)
    triggering_hypotheses: List[str] = field(default_factory=list)
    triggering_anomalies: List[str] = field(default_factory=list)
    target_ecus: List[str] = field(default_factory=list)
    steps: Dict[str, DiagnosticStep] = field(default_factory=dict)
    step_sequence: List[str] = field(default_factory=list)
    current_step_id: Optional[str] = None
    state: ProcedureState = ProcedureState.DRAFT
    final_outcome: Optional[ProcedureOutcome] = None
    stop_conditions: List[DiagnosticStopCondition] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    confidence: float = 0.8
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -----------------------------------------------------------------
    # State Machine & Lifecycle Transitions
    # -----------------------------------------------------------------

    VALID_TRANSITIONS: ClassVar[Dict[ProcedureState, Set[ProcedureState]]] = {
        ProcedureState.DRAFT: {ProcedureState.READY, ProcedureState.ABORTED},
        ProcedureState.READY: {ProcedureState.ACTIVE, ProcedureState.BLOCKED, ProcedureState.ABORTED},
        ProcedureState.ACTIVE: {
            ProcedureState.WAITING_FOR_INPUT,
            ProcedureState.BLOCKED,
            ProcedureState.COMPLETED,
            ProcedureState.FAILED,
            ProcedureState.ABORTED,
        },
        ProcedureState.WAITING_FOR_INPUT: {
            ProcedureState.ACTIVE,
            ProcedureState.BLOCKED,
            ProcedureState.COMPLETED,
            ProcedureState.FAILED,
            ProcedureState.ABORTED,
        },
        ProcedureState.BLOCKED: {ProcedureState.ABORTED},
        ProcedureState.COMPLETED: set(),
        ProcedureState.FAILED: set(),
        ProcedureState.ABORTED: set(),
    }

    def transition_to(self, new_state: ProcedureState, reason: str = "") -> None:
        """
        Transitions procedure lifecycle state.
        Raises ProcedureStateError on invalid transition.
        """
        allowed = self.VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise ProcedureStateError(
                f"Invalid procedure state transition: cannot transition from '{self.state.value}' "
                f"to '{new_state.value}'. Allowed: {[s.value for s in allowed]}"
            )
        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()
        if reason:
            self.metadata.setdefault("state_transition_history", []).append({
                "from": old_state.value,
                "to": new_state.value,
                "reason": reason,
                "timestamp": round(self.updated_at, 3),
            })

    # -----------------------------------------------------------------
    # Step Operations
    # -----------------------------------------------------------------

    def add_step(self, step: DiagnosticStep) -> None:
        """Adds a structured step to the procedure."""
        self.steps[step.step_id] = step
        if step.step_id not in self.step_sequence:
            self.step_sequence.append(step.step_id)
        if step.target_ecu not in self.target_ecus:
            self.target_ecus.append(step.target_ecu)
        if self.current_step_id is None and not step.is_blocked:
            self.current_step_id = step.step_id
        self.updated_at = time.time()

    def get_current_step(self) -> Optional[DiagnosticStep]:
        """Returns the currently active step for technician review."""
        if self.current_step_id:
            return self.steps.get(self.current_step_id)
        return None

    @property
    def is_completed(self) -> bool:
        return self.state in (ProcedureState.COMPLETED, ProcedureState.FAILED, ProcedureState.ABORTED, ProcedureState.BLOCKED)

    @property
    def total_steps(self) -> int:
        return len(self.step_sequence)

    @property
    def completed_steps_count(self) -> int:
        return sum(1 for s in self.steps.values() if s.completed)

    # -----------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "context": self.context.to_dict(),
            "title": self.title,
            "objective": self.objective,
            "created_at": round(self.created_at, 3),
            "updated_at": round(self.updated_at, 3),
            "triggering_dtcs": self.triggering_dtcs,
            "triggering_hypotheses": self.triggering_hypotheses,
            "triggering_anomalies": self.triggering_anomalies,
            "target_ecus": self.target_ecus,
            "steps": {sid: step.to_dict() for sid, step in self.steps.items()},
            "step_sequence": self.step_sequence,
            "current_step_id": self.current_step_id,
            "state": self.state.value,
            "final_outcome": self.final_outcome.value if self.final_outcome else None,
            "stop_conditions": [sc.to_dict() for sc in self.stop_conditions],
            "provenance": self.provenance,
            "safety_classification": self.safety_classification.value,
            "confidence": round(self.confidence, 2),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticProcedure":
        ctx = DiagnosticProcedureContext.from_dict(data["context"])
        steps = {sid: DiagnosticStep.from_dict(sd) for sid, sd in data.get("steps", {}).items()}
        term = data.get("final_outcome")
        return cls(
            procedure_id=data["procedure_id"],
            context=ctx,
            title=data["title"],
            objective=data["objective"],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            triggering_dtcs=data.get("triggering_dtcs", []),
            triggering_hypotheses=data.get("triggering_hypotheses", []),
            triggering_anomalies=data.get("triggering_anomalies", []),
            target_ecus=data.get("target_ecus", []),
            steps=steps,
            step_sequence=data.get("step_sequence", list(steps.keys())),
            current_step_id=data.get("current_step_id"),
            state=ProcedureState(data.get("state", "DRAFT")),
            final_outcome=ProcedureOutcome(term) if term else None,
            stop_conditions=[DiagnosticStopCondition.from_dict(sc) for sc in data.get("stop_conditions", [])],
            provenance=data.get("provenance", {}),
            safety_classification=ServiceSafetyClassification(data.get("safety_classification", "READ_ONLY")),
            confidence=float(data.get("confidence", 0.8)),
            metadata=data.get("metadata", {}),
        )


# =====================================================================
# 4. DETERMINISTIC PRIORITIZATION & INFORMATION GAIN
# =====================================================================

class StepPrioritizer:
    """
    Deterministic scoring and ranking engine for diagnostic procedure steps.
    Weights discriminative information gain, hypothesis confidence,
    safety, cost/time efficiency, and prerequisite readiness.
    """
    def __init__(
        self,
        weight_discrimination: float = 0.35,
        weight_confidence: float = 0.25,
        weight_safety: float = 0.20,
        weight_cost: float = 0.10,
        weight_prerequisites: float = 0.10,
    ):
        self.w_disc = weight_discrimination
        self.w_conf = weight_confidence
        self.w_safe = weight_safety
        self.w_cost = weight_cost
        self.w_prereq = weight_prerequisites

    def score_step(
        self,
        step: DiagnosticStep,
        hypotheses: List[FaultHypothesis],
        available_signals: Set[str],
        unreachable_ecus: Set[str],
    ) -> Tuple[float, str]:
        """
        Calculates a deterministic 0.0 - 1.0 priority score and explainable rationale.
        """
        reasons = []

        # 1. Discrimination value (information gain)
        disc_score = 0.5
        if len(step.discriminated_hypotheses) >= 2:
            disc_score = 1.0
            reasons.append(f"Distinguishes between competing hypotheses: {step.discriminated_hypotheses}")
        elif len(step.discriminated_hypotheses) == 1:
            disc_score = 0.75
            reasons.append(f"Directly tests hypothesis: {step.discriminated_hypotheses[0]}")
        else:
            disc_score = 0.4
            reasons.append("General observational check")

        # 2. Target hypothesis confidence
        conf_score = step.confidence
        reasons.append(f"Evidence confidence: {round(conf_score, 2)}")

        # 3. Safety score
        if step.is_blocked:
            safe_score = 0.0
            reasons.append(f"Blocked by safety policy: {step.blocking_reason}")
        elif step.safety_classification == ServiceSafetyClassification.READ_ONLY:
            safe_score = 1.0
            reasons.append("Strictly non-destructive read-only check")
        else:
            safe_score = 0.5

        # 4. Cost / Time efficiency (lower time = higher score)
        est_time = step.estimated_time_minutes or 10
        cost_score = max(0.1, 1.0 - (est_time / 30.0))
        reasons.append(f"Estimated duration: {est_time} min")

        # 5. Prerequisite readiness
        if step.target_ecu in unreachable_ecus:
            prereq_score = 0.0
            reasons.append(f"Target ECU '{step.target_ecu}' is currently unreachable")
        else:
            unmet = [s for s in step.required_evidence_ids if s not in available_signals]
            if not unmet:
                prereq_score = 1.0
                reasons.append("All prerequisites available")
            else:
                prereq_score = 0.5
                reasons.append(f"Requires acquisition of signals: {unmet}")

        total_score = (
            self.w_disc * disc_score
            + self.w_conf * conf_score
            + self.w_safe * safe_score
            + self.w_cost * cost_score
            + self.w_prereq * prereq_score
        )
        total_score = max(0.0, min(1.0, total_score))
        return total_score, "; ".join(reasons)


# =====================================================================
# 5. GUIDED PROCEDURE ENGINE
# =====================================================================

class GuidedProcedureEngine:
    """
    Phase H-1 Procedure Planning and Guided-Decision Engine.
    Synthesizes DTCs, G-3 hypotheses, anomalies, G-4 multi-ECU scans,
    and G-5 diagnostic graphs into deterministic guided procedures.
    """
    FORBIDDEN_MODES = {"04", "4", "14"}
    FORBIDDEN_SERVICES = {"2E", "27", "2F", "34", "35", "36", "37", "3D"}

    def __init__(self, prioritizer: Optional[StepPrioritizer] = None):
        self.prioritizer = prioritizer or StepPrioritizer()
        self.safety_policy = ServiceSafetyPolicy(allow_non_readonly=False)

    # -----------------------------------------------------------------
    # Procedure Construction Entry Points
    # -----------------------------------------------------------------

    def generate_procedure(
        self,
        vehicle_context: Optional[VehicleContext] = None,
        session_id: Optional[str] = None,
        hypotheses: Optional[List[FaultHypothesis]] = None,
        dtcs: Optional[List[Union[DTCRecord, MultiECUDTCRecord]]] = None,
        anomalies: Optional[List[Union[PointAnomaly, TemporalAnomaly]]] = None,
        graph: Optional[DiagnosticGraph] = None,
        multi_ecu_result: Optional[MultiECUScanResult] = None,
        available_signals: Optional[Set[str]] = None,
        unreachable_ecus: Optional[Set[str]] = None,
    ) -> DiagnosticProcedure:
        """
        Main factory method constructing a deterministic guided procedure.
        Capable of operating with or without DTCs, single or multiple hypotheses,
        graph relationships, or communication anomalies.
        """
        sess_id = session_id or f"PROC-SESS-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        veh_id = make_vehicle_node_id(vehicle_context)

        # 1. Resolve Available ECUs and Transport Health
        avail_ecus = set()
        unreach_ecus = set(unreachable_ecus or [])

        if multi_ecu_result:
            for ecu_id, rec in multi_ecu_result.ecu_records.items():
                if rec.health_state.value == "ACTIVE":
                    avail_ecus.add(ecu_id)
                elif rec.health_state.value in ("UNREACHABLE", "TIMEOUT"):
                    unreach_ecus.add(ecu_id)

        if not avail_ecus:
            avail_ecus.add("ECM")  # Default baseline target

        # Extract known signals
        signals_present = set(available_signals or [])
        if graph:
            for node in graph.get_nodes(GraphNodeType.SIGNAL):
                sig_name = node.properties.get("signal_name", "")
                if sig_name:
                    signals_present.add(sig_name)

        # Build context container
        proc_ctx = DiagnosticProcedureContext(
            vehicle_id=veh_id,
            session_id=sess_id,
            vehicle_context=vehicle_context,
            available_ecus=sorted(list(avail_ecus)),
            unreachable_ecus=sorted(list(unreach_ecus)),
            operating_condition="NORMAL",
        )

        proc_id = f"PROC-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        dtc_strings = self._normalize_dtc_strings(dtcs)
        hyp_list = list(hypotheses or [])
        anom_list = list(anomalies or [])

        procedure = DiagnosticProcedure(
            procedure_id=proc_id,
            context=proc_ctx,
            title="Guided Diagnostic Procedure",
            objective="Systematic evidence-driven diagnostic investigation",
            created_at=time.time(),
            updated_at=time.time(),
            triggering_dtcs=dtc_strings,
            triggering_hypotheses=[h.hypothesis_id for h in hyp_list],
            triggering_anomalies=[a.anomaly_id for a in anom_list],
            target_ecus=sorted(list(avail_ecus.union(unreach_ecus))),
            state=ProcedureState.DRAFT,
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            confidence=0.85,
        )

        # Standard Stop Conditions
        procedure.stop_conditions.extend([
            DiagnosticStopCondition(
                condition_type=StopConditionType.HYPOTHESIS_RESOLVED,
                description="Hypothesis confidence resolved above threshold",
                terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
            ),
            DiagnosticStopCondition(
                condition_type=StopConditionType.ALL_STEPS_COMPLETED,
                description="All diagnostic steps in procedure executed",
                terminal_outcome=ProcedureOutcome.NO_CONFIDENT_CONCLUSION,
            ),
            DiagnosticStopCondition(
                condition_type=StopConditionType.SAFETY_RESTRICTION,
                description="Hazardous or blocked action encountered",
                terminal_outcome=ProcedureOutcome.SAFETY_BLOCKED,
            ),
            DiagnosticStopCondition(
                condition_type=StopConditionType.COMMUNICATION_FAULT,
                description="Diagnostic communication lost with target ECU",
                terminal_outcome=ProcedureOutcome.COMMUNICATION_PROBLEM,
            ),
        ])

        # 2. Route Procedure Generation by Trigger Type
        candidate_steps: List[DiagnosticStep] = []

        # Scenario A: Communication Failures take precedence
        if unreach_ecus:
            comm_steps = self._generate_communication_steps(unreach_ecus, sess_id)
            candidate_steps.extend(comm_steps)

        # Scenario B: Multiple Competing Hypotheses
        if len(hyp_list) >= 2:
            disc_steps = self._generate_hypothesis_discrimination_steps(hyp_list, graph, signals_present, sess_id)
            candidate_steps.extend(disc_steps)
        elif len(hyp_list) == 1:
            # Single hypothesis
            single_steps = self._generate_single_hypothesis_steps(hyp_list[0], graph, signals_present, sess_id)
            candidate_steps.extend(single_steps)

        # Scenario C: DTC-driven Steps (if no hypothesis or to supplement)
        if dtcs and not hyp_list:
            dtc_steps = self._generate_dtc_driven_steps(dtcs, graph, sess_id)
            candidate_steps.extend(dtc_steps)

        # Scenario D: DTC-free Anomaly Steps (no DTCs, no formal hypothesis)
        if anom_list and not hyp_list and not dtcs:
            anom_steps = self._generate_anomaly_driven_steps(anom_list, sess_id)
            candidate_steps.extend(anom_steps)

        # Scenario E: Graph-Aware Correlation Steps
        if graph and not candidate_steps:
            graph_steps = self._generate_graph_correlation_steps(graph, sess_id)
            candidate_steps.extend(graph_steps)

        # Fallback if empty
        if not candidate_steps:
            candidate_steps.append(self._create_fallback_step(sess_id))

        # 3. Apply Deterministic Prioritization and Bounding
        # Bounded generation: cap max candidate steps at 20
        candidate_steps = candidate_steps[:20]

        for step in candidate_steps:
            score, reason = self.prioritizer.score_step(step, hyp_list, signals_present, unreach_ecus)
            step.priority_score = score
            step.priority_reason = reason

        # Sort descending by priority_score, preserving stable deterministic ordering
        candidate_steps.sort(key=lambda s: (-s.priority_score, s.sequence, s.step_id))

        # Re-index sequences
        for idx, step in enumerate(candidate_steps, start=1):
            step.sequence = idx
            procedure.add_step(step)

        # 4. Chain Sequential Default Branches
        self._link_default_branches(procedure)

        # Set title and objective based on primary trigger
        if hyp_list:
            procedure.title = f"Diagnostic Procedure: {hyp_list[0].title}"
            procedure.objective = f"Systematic verification of '{hyp_list[0].title}' and related conditions"
        elif dtc_strings:
            procedure.title = f"Diagnostic Procedure for DTC {', '.join(dtc_strings[:3])}"
            procedure.objective = f"Investigate root cause of reported trouble code(s): {', '.join(dtc_strings)}"
        elif anom_list:
            procedure.title = f"Diagnostic Procedure for Sensor Anomaly: {anom_list[0].signal_name}"
            procedure.objective = f"Investigate abnormal behavior detected on {anom_list[0].signal_name}"

        # Finalize to READY state
        procedure.transition_to(ProcedureState.READY, reason="Procedure generation completed and verified safe")
        return procedure

    # -----------------------------------------------------------------
    # Step Generation Generators
    # -----------------------------------------------------------------

    def _generate_communication_steps(self, unreach_ecus: Set[str], session_id: str) -> List[DiagnosticStep]:
        """
        Generates guided steps for unreachable ECUs.
        Strict Invariant: NEVER recommends component replacement for a communication problem.
        """
        steps = []
        for ecu in sorted(list(unreach_ecus)):
            step_id = f"STEP-COMM-{ecu}-01"
            step = DiagnosticStep(
                step_id=step_id,
                sequence=1,
                title=f"Verify {ecu} Communication & Power Supply",
                technician_instruction=(
                    f"Check power feed, ground connections, and CAN bus termination at the {ecu} harness connector. "
                    f"Verify whether {ecu} wakes up with ignition ON before interpreting any {ecu}-related DTCs."
                ),
                purpose=f"Isolate transport/communication failure from physical vehicle module defect on {ecu}.",
                rationale=(
                    f"Acquisition layer reported {ecu} is unreachable/timed out. "
                    f"Diagnostic evidence cannot be safely acquired until communication is restored."
                ),
                target_ecu=ecu,
                possible_outcomes=[
                    ObservationResultType.NORMAL,
                    ObservationResultType.COMMUNICATION_FAILURE,
                    ObservationResultType.ABNORMAL,
                ],
                branches=[
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-COMM-FAIL",
                        condition_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                        terminal_outcome=ProcedureOutcome.COMMUNICATION_PROBLEM,
                        rationale=f"Persistent communication loss confirmed on {ecu}. Cease vehicle-fault reasoning.",
                    ),
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-COMM-RESTORED",
                        condition_outcome=ObservationResultType.NORMAL,
                        target_step_id=None,  # Will link to next step
                        confidence_adjustment=0.2,
                        rationale=f"{ecu} communication restored. Proceed with diagnostic scanning.",
                    ),
                ],
                execution_mode=StepExecutionMode.OBSERVATIONAL,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
                priority=StepPriority.MANDATORY,
                provenance={
                    "rule": "RULE_COMMUNICATION_ISOLATION",
                    "target_ecu": ecu,
                    "session_id": session_id,
                },
                confidence=0.95,
            )
            steps.append(step)
        return steps

    def _generate_hypothesis_discrimination_steps(
        self,
        hypotheses: List[FaultHypothesis],
        graph: Optional[DiagnosticGraph],
        signals_present: Set[str],
        session_id: str,
    ) -> List[DiagnosticStep]:
        """
        Generates steps specifically designed to discriminate between competing hypotheses.
        """
        steps = []
        h1 = hypotheses[0]
        h2 = hypotheses[1]

        # Case: Airflow vs Vacuum Leak discrimination
        h1_text = (h1.title + " " + h1.category).lower()
        h2_text = (h2.title + " " + h2.category).lower()

        if ("maf" in h1_text or "maf" in h2_text) and ("leak" in h1_text or "leak" in h2_text or "fuel" in h2_text):
            step_id = "STEP-DISC-MAF-VS-VACUUM"
            step = DiagnosticStep(
                step_id=step_id,
                sequence=1,
                title="Discriminate Airflow Sensor Bias vs. Intake Air Leak",
                technician_instruction=(
                    "Observe Short Term Fuel Trim (STFT) and Long Term Fuel Trim (LTFT) at warm idle, "
                    "then raise engine speed to 2500 RPM under no load and observe trim response."
                ),
                purpose=(
                    "Distinguish unmetered air leak (vacuum leak) from MAF sensor scaling bias. "
                    "Vacuum leaks typically show positive trim at idle that improves at higher RPM; "
                    "MAF under-reporting worsens or persists as airflow increases."
                ),
                rationale=(
                    f"G-3 identified competing hypotheses: '{h1.title}' vs. '{h2.title}'. "
                    f"Safe observational trim comparison directly discriminates between these possibilities."
                ),
                target_ecu="ECM",
                required_evidence_ids=["STFT", "LTFT", "RPM"],
                expected_observation=DiagnosticExpectedObservation(
                    description="Fuel trims normalize near 0% under healthy conditions; vacuum leaks improve at 2500 RPM.",
                    relationship_description="STFT + LTFT > +15% at idle decreasing to < +5% at 2500 RPM indicates vacuum leak.",
                ),
                possible_outcomes=[
                    ObservationResultType.NORMAL,
                    ObservationResultType.ABNORMAL,
                    ObservationResultType.MEASURED_VALUE,
                ],
                branches=[
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-TRIMS-IDLE-HIGH",
                        condition_outcome=ObservationResultType.ABNORMAL,
                        terminal_outcome=ProcedureOutcome.HYPOTHESES_DISCRIMINATED,
                        confidence_adjustment=0.4,
                        rationale="Positive trim elevated at idle and normalizing at speed confirms intake leak over sensor bias.",
                    ),
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-TRIMS-NORMAL",
                        condition_outcome=ObservationResultType.NORMAL,
                        terminal_outcome=ProcedureOutcome.HYPOTHESIS_WEAKENED,
                        confidence_adjustment=-0.3,
                        rationale="Fuel trims within normal bounds contradict major intake air leak or gross MAF error.",
                    ),
                ],
                execution_mode=StepExecutionMode.OBSERVATIONAL,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
                priority=StepPriority.MANDATORY,
                target_hypotheses=[h1.hypothesis_id, h2.hypothesis_id],
                discriminated_hypotheses=[h1.hypothesis_id, h2.hypothesis_id],
                provenance={
                    "rule": "RULE_DISCRIMINATE_AIRFLOW_LEAK",
                    "hypotheses": [h1.hypothesis_id, h2.hypothesis_id],
                    "session_id": session_id,
                },
                confidence=0.90,
            )
            steps.append(step)

        # Add single hypothesis verification steps for each hypothesis
        for hyp in hypotheses[:2]:
            steps.extend(self._generate_single_hypothesis_steps(hyp, graph, signals_present, session_id))

        return steps

    def _generate_single_hypothesis_steps(
        self,
        hyp: FaultHypothesis,
        graph: Optional[DiagnosticGraph],
        signals_present: Set[str],
        session_id: str,
    ) -> List[DiagnosticStep]:
        """
        Generates observational/measurement steps supporting or verifying a G-3 hypothesis.
        """
        steps = []
        target_ecu = "ECM"
        for dtc in hyp.dtc_associations:
            if ":" in dtc:
                target_ecu = dtc.split(":")[0]
                break

        # Step 1: Review Evidence & Operating Conditions
        cond_str = ", ".join(c.value for c in hyp.operating_conditions) or "General Operation"
        step1_id = f"STEP-{hyp.hypothesis_id[:12]}-REV"
        step1 = DiagnosticStep(
            step_id=step1_id,
            sequence=len(steps) + 1,
            title=f"Review Operating Condition & Sensor Data for {hyp.title}",
            technician_instruction=(
                f"Verify live sensor behavior under operating condition '{cond_str}'. "
                f"Check whether signals {hyp.required_additional_evidence or ['Primary sensors']} "
                f"exhibit the reported anomalies."
            ),
            purpose=f"Confirm repeatability of the evidence supporting hypothesis '{hyp.title}'.",
            rationale=(
                f"Phase G-3 detected evidence with score {round(hyp.evidence_score, 2)} "
                f"and confidence {hyp.confidence.value}. Observational verification under matching conditions is required."
            ),
            target_ecu=target_ecu,
            required_evidence_ids=hyp.required_additional_evidence,
            expected_observation=DiagnosticExpectedObservation(
                description=f"Sensors operate within normal bounds without erratic transitions under {cond_str}."
            ),
            possible_outcomes=[
                ObservationResultType.NORMAL,
                ObservationResultType.ABNORMAL,
                ObservationResultType.INTERMITTENT,
            ],
            branches=[
                DiagnosticBranch(
                    branch_id=f"BR-{step1_id}-ABN",
                    condition_outcome=ObservationResultType.ABNORMAL,
                    confidence_adjustment=0.25,
                    rationale=f"Anomaly repeated under {cond_str}. Hypothesis '{hyp.title}' strongly supported.",
                ),
                DiagnosticBranch(
                    branch_id=f"BR-{step1_id}-NORM",
                    condition_outcome=ObservationResultType.NORMAL,
                    confidence_adjustment=-0.25,
                    rationale=f"Sensor behavior normal under {cond_str}. Hypothesis '{hyp.title}' weakened.",
                ),
            ],
            execution_mode=StepExecutionMode.OBSERVATIONAL,
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            priority=StepPriority.RECOMMENDED,
            target_hypotheses=[hyp.hypothesis_id],
            discriminated_hypotheses=[hyp.hypothesis_id],
            provenance={
                "rule": "RULE_HYPOTHESIS_OBSERVATION",
                "hypothesis_id": hyp.hypothesis_id,
                "session_id": session_id,
            },
            confidence=0.85,
        )
        steps.append(step1)

        # Step 2: Physical Inspection according to workshop procedure
        step2_id = f"STEP-{hyp.hypothesis_id[:12]}-INSP"
        step2 = DiagnosticStep(
            step_id=step2_id,
            sequence=len(steps) + 1,
            title=f"Physical & Visual Inspection for {hyp.affected_system}",
            technician_instruction=(
                f"Perform physical visual inspection of harness, connectors, and components in the {hyp.affected_system} "
                f"according to the approved workshop procedure. Check for chafing, oil intrusion, or loose pins."
            ),
            purpose=f"Inspect physical integrity of {hyp.affected_system} components.",
            rationale="Eliminate physical harness, vacuum, or mechanical defects before component replacement.",
            target_ecu=target_ecu,
            possible_outcomes=[
                ObservationResultType.NORMAL,
                ObservationResultType.ABNORMAL,
                ObservationResultType.NOT_TESTED,
            ],
            branches=[
                DiagnosticBranch(
                    branch_id=f"BR-{step2_id}-PHYS-DEFECT",
                    condition_outcome=ObservationResultType.ABNORMAL,
                    terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                    confidence_adjustment=0.5,
                    rationale="Visible physical harness or mechanical defect confirmed.",
                ),
                DiagnosticBranch(
                    branch_id=f"BR-{step2_id}-PHYS-OK",
                    condition_outcome=ObservationResultType.NORMAL,
                    target_step_id=None,
                    confidence_adjustment=0.0,
                    rationale="Harness and physical components intact.",
                ),
            ],
            execution_mode=StepExecutionMode.OBSERVATIONAL,
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            priority=StepPriority.RECOMMENDED,
            target_hypotheses=[hyp.hypothesis_id],
            provenance={
                "rule": "RULE_WORKSHOP_PHYSICAL_INSPECTION",
                "hypothesis_id": hyp.hypothesis_id,
                "session_id": session_id,
            },
            confidence=0.80,
        )
        steps.append(step2)
        return steps

    def _generate_dtc_driven_steps(
        self,
        dtcs: List[Union[DTCRecord, MultiECUDTCRecord]],
        graph: Optional[DiagnosticGraph],
        session_id: str,
    ) -> List[DiagnosticStep]:
        """
        Generates diagnostic steps guided by reported DTCs.
        Preserves distinct ECU targets for identical DTC codes across ECUs.
        """
        steps = []
        for idx, dtc_item in enumerate(dtcs[:5], start=1):
            if isinstance(dtc_item, MultiECUDTCRecord):
                code = dtc_item.code
                ecu_id = dtc_item.ecu_id
                desc = dtc_item.description or "Reported Trouble Code"
            elif isinstance(dtc_item, DTCRecord):
                code = dtc_item.code
                ecu_id = dtc_item.ecu_source or "ECM"
                desc = dtc_item.description or "Reported Trouble Code"
            else:
                code = str(dtc_item)
                ecu_id = "ECM"
                desc = "Diagnostic Trouble Code"

            step_id = f"STEP-DTC-{ecu_id}-{code}"
            step = DiagnosticStep(
                step_id=step_id,
                sequence=idx,
                title=f"Investigate DTC {code} on {ecu_id}",
                technician_instruction=(
                    f"Review freeze frame data for DTC {code} on {ecu_id}. "
                    f"Perform circuit checks for {code} ({desc}) according to the manufacturer workshop manual."
                ),
                purpose=f"Validate electrical and operational conditions present when {ecu_id} set DTC {code}.",
                rationale=f"DTC {code} was reported by {ecu_id}. Freeze frame context pinpoints failure conditions.",
                target_ecu=ecu_id,
                possible_outcomes=[
                    ObservationResultType.NORMAL,
                    ObservationResultType.ABNORMAL,
                    ObservationResultType.NOT_PRESENT,
                ],
                branches=[
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-CONFIRMED",
                        condition_outcome=ObservationResultType.ABNORMAL,
                        terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                        confidence_adjustment=0.3,
                        rationale=f"Fault condition active and confirmed on {ecu_id}.",
                    ),
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-NOT-PRESENT",
                        condition_outcome=ObservationResultType.NOT_PRESENT,
                        terminal_outcome=ProcedureOutcome.INSUFFICIENT_EVIDENCE,
                        confidence_adjustment=-0.2,
                        rationale=f"DTC {code} not currently reproduced or active on {ecu_id}.",
                    ),
                ],
                execution_mode=StepExecutionMode.INFORMATIONAL,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
                priority=StepPriority.MANDATORY,
                provenance={
                    "rule": "RULE_DTC_INVESTIGATION",
                    "dtc": f"{ecu_id}:{code}",
                    "session_id": session_id,
                },
                confidence=0.85,
            )
            steps.append(step)
        return steps

    def _generate_anomaly_driven_steps(
        self,
        anomalies: List[Union[PointAnomaly, TemporalAnomaly]],
        session_id: str,
    ) -> List[DiagnosticStep]:
        """
        Generates guided steps for DTC-free anomalies.
        """
        steps = []
        for idx, anom in enumerate(anomalies[:3], start=1):
            sig_name = anom.signal_name
            op_cond = anom.operating_condition.value if hasattr(anom.operating_condition, "value") else str(anom.operating_condition)
            step_id = f"STEP-ANOM-{sig_name}-{idx}"

            step = DiagnosticStep(
                step_id=step_id,
                sequence=idx,
                title=f"Investigate Signal Anomaly on {sig_name}",
                technician_instruction=(
                    f"Connect diagnostic monitor and observe signal '{sig_name}' under '{op_cond}'. "
                    f"Check for intermittent drops, excessive noise, or plausibility deviation."
                ),
                purpose=f"Verify unflagged sensor anomaly on {sig_name} without an active DTC.",
                rationale=(
                    f"G-3 time-series analysis detected {anom.anomaly_type.value if hasattr(anom.anomaly_type, 'value') else anom.anomaly_type} "
                    f"on {sig_name} during {op_cond}."
                ),
                target_ecu="ECM",
                required_evidence_ids=[sig_name],
                possible_outcomes=[
                    ObservationResultType.NORMAL,
                    ObservationResultType.ABNORMAL,
                    ObservationResultType.INTERMITTENT,
                ],
                branches=[
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-ANOM-CONFIRMED",
                        condition_outcome=ObservationResultType.ABNORMAL,
                        terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                        confidence_adjustment=0.35,
                        rationale=f"Anomaly on {sig_name} independently verified by technician.",
                    ),
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-ANOM-TRANSIENT",
                        condition_outcome=ObservationResultType.NORMAL,
                        terminal_outcome=ProcedureOutcome.INSUFFICIENT_EVIDENCE,
                        confidence_adjustment=-0.2,
                        rationale=f"Signal {sig_name} observed normal; anomaly may have been transient.",
                    ),
                ],
                execution_mode=StepExecutionMode.OBSERVATIONAL,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
                priority=StepPriority.RECOMMENDED,
                provenance={
                    "rule": "RULE_DTC_FREE_ANOMALY",
                    "anomaly_id": anom.anomaly_id,
                    "session_id": session_id,
                },
                confidence=0.80,
            )
            steps.append(step)
        return steps

    def _generate_graph_correlation_steps(
        self,
        graph: DiagnosticGraph,
        session_id: str,
    ) -> List[DiagnosticStep]:
        """
        Extracts cross-ECU or correlation relationships from G-5 graph.
        """
        steps = []
        corr_edges = [
            e for e in graph._edges_by_id.values()
            if e.edge_type in (GraphEdgeType.CORRELATES_WITH, GraphEdgeType.DEVIATES_FROM)
        ]
        for idx, edge in enumerate(corr_edges[:2], start=1):
            src_node = graph.get_node(edge.source_id)
            tgt_node = graph.get_node(edge.target_id)
            src_name = src_node.label if src_node else edge.source_id
            tgt_name = tgt_node.label if tgt_node else edge.target_id

            step_id = f"STEP-GRAPH-REL-{idx}"
            step = DiagnosticStep(
                step_id=step_id,
                sequence=idx,
                title=f"Verify Relationship: {src_name} vs. {tgt_name}",
                technician_instruction=(
                    f"Observe co-variation between {src_name} and {tgt_name} during controlled drive cycle. "
                    f"Check whether {src_name} responds consistently to changes in {tgt_name}."
                ),
                purpose=f"Validate runtime behavioral correlation discovered in diagnostic graph.",
                rationale=f"G-5 diagnostic graph identified relationship '{edge.edge_type.value}' with confidence {edge.confidence}.",
                target_ecu="ECM",
                required_evidence_ids=[src_name, tgt_name],
                possible_outcomes=[
                    ObservationResultType.NORMAL,
                    ObservationResultType.ABNORMAL,
                ],
                branches=[
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-CORR-OK",
                        condition_outcome=ObservationResultType.NORMAL,
                        terminal_outcome=ProcedureOutcome.HYPOTHESES_DISCRIMINATED,
                        rationale="Signals correlate coherently.",
                    ),
                    DiagnosticBranch(
                        branch_id=f"BR-{step_id}-CORR-FAIL",
                        condition_outcome=ObservationResultType.ABNORMAL,
                        terminal_outcome=ProcedureOutcome.HYPOTHESIS_SUPPORTED,
                        rationale="Persistent deviation between related signals confirmed.",
                    ),
                ],
                execution_mode=StepExecutionMode.OBSERVATIONAL,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
                priority=StepPriority.RECOMMENDED,
                provenance={
                    "rule": "RULE_GRAPH_RELATIONSHIP",
                    "edge_id": edge.edge_id,
                    "session_id": session_id,
                },
                confidence=edge.confidence,
            )
            steps.append(step)
        return steps

    def _create_fallback_step(self, session_id: str) -> DiagnosticStep:
        """Fallback baseline inspection step."""
        return DiagnosticStep(
            step_id="STEP-GEN-HEALTH-01",
            sequence=1,
            title="General Diagnostic Health Scan",
            technician_instruction="Perform a full vehicle diagnostic scan and check for stored DTCs across all available ECUs.",
            purpose="Establish baseline electronic system health.",
            rationale="No specific anomaly or DTC provided for focused procedure generation.",
            target_ecu="ECM",
            possible_outcomes=[ObservationResultType.NORMAL, ObservationResultType.ABNORMAL],
            branches=[
                DiagnosticBranch(
                    branch_id="BR-GEN-NORM",
                    condition_outcome=ObservationResultType.NORMAL,
                    terminal_outcome=ProcedureOutcome.NO_CONFIDENT_CONCLUSION,
                    rationale="All systems normal.",
                ),
                DiagnosticBranch(
                    branch_id="BR-GEN-ABN",
                    condition_outcome=ObservationResultType.ABNORMAL,
                    terminal_outcome=ProcedureOutcome.REQUIRES_MANUAL_TEST,
                    rationale="Anomalies detected requiring manual test.",
                ),
            ],
            execution_mode=StepExecutionMode.INFORMATIONAL,
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            priority=StepPriority.INFORMATIONAL,
            provenance={"rule": "RULE_BASELINE_HEALTH", "session_id": session_id},
            confidence=0.70,
        )

    def _link_default_branches(self, procedure: DiagnosticProcedure) -> None:
        """Links consecutive steps when a branch doesn't have an explicit target."""
        seq = procedure.step_sequence
        for i, sid in enumerate(seq):
            step = procedure.steps[sid]
            next_sid = seq[i + 1] if i + 1 < len(seq) else None
            for br in step.branches:
                if br.target_step_id is None and br.terminal_outcome is None and next_sid:
                    br.target_step_id = next_sid

    def _normalize_dtc_strings(self, dtcs: Optional[List[Any]]) -> List[str]:
        """Extracts standard DTC string representations."""
        if not dtcs:
            return []
        res = []
        for d in dtcs:
            if isinstance(d, MultiECUDTCRecord):
                res.append(f"{d.ecu_id}:{d.code}")
            elif isinstance(d, DTCRecord):
                res.append(f"{d.ecu_source or 'ECM'}:{d.code}")
            else:
                res.append(str(d))
        return res

    # -----------------------------------------------------------------
    # Procedure Stepping & Observation Processing
    # -----------------------------------------------------------------

    def record_step_observation(
        self,
        procedure: DiagnosticProcedure,
        step_id: str,
        result_type: ObservationResultType,
        measured_value: Optional[float] = None,
        unit: Optional[str] = None,
        notes: str = "",
        technician_id: Optional[str] = None,
    ) -> DiagnosticProcedure:
        """
        Records a technician observation on the active step and deterministically
        evaluates branching rules, confidence updates, and stop conditions.
        """
        if procedure.is_completed:
            raise ProcedureStateError(f"Cannot record observation on terminated procedure '{procedure.procedure_id}' ({procedure.state.value})")

        if step_id not in procedure.steps:
            raise ValueError(f"Step '{step_id}' does not exist in procedure '{procedure.procedure_id}'")

        step = procedure.steps[step_id]

        if step.is_blocked:
            raise ProcedureSafetyError(f"Cannot record observation on blocked step '{step_id}': {step.blocking_reason}")

        # Record observation
        obs = TechnicianObservation(
            observation_id=f"OBS-{int(time.time())}-{uuid.uuid4().hex[:6]}",
            step_id=step_id,
            result_type=result_type,
            measured_value=measured_value,
            unit=unit,
            notes=notes,
            technician_id=technician_id,
            timestamp=time.time(),
        )
        step.technician_observation = obs
        step.completed = True
        procedure.updated_at = time.time()

        # Evaluate branches matching result_type
        matched_branch = None
        for br in step.branches:
            if br.condition_outcome == result_type:
                matched_branch = br
                break

        if matched_branch:
            # Adjust procedure confidence
            procedure.confidence = max(0.0, min(1.0, procedure.confidence + matched_branch.confidence_adjustment))

            # Terminal branch
            if matched_branch.terminal_outcome:
                procedure.final_outcome = matched_branch.terminal_outcome
                if matched_branch.terminal_outcome == ProcedureOutcome.SAFETY_BLOCKED:
                    procedure.transition_to(ProcedureState.BLOCKED, reason=matched_branch.rationale)
                elif matched_branch.terminal_outcome == ProcedureOutcome.COMMUNICATION_PROBLEM:
                    procedure.transition_to(ProcedureState.COMPLETED, reason=matched_branch.rationale)
                else:
                    procedure.transition_to(ProcedureState.COMPLETED, reason=matched_branch.rationale)
                return procedure

            # Transition to target step
            if matched_branch.target_step_id:
                procedure.current_step_id = matched_branch.target_step_id
                return procedure

        # If no explicit target branch, advance to next step in sequence
        curr_idx = procedure.step_sequence.index(step_id)
        if curr_idx + 1 < len(procedure.step_sequence):
            procedure.current_step_id = procedure.step_sequence[curr_idx + 1]
        else:
            # Reached end of sequence
            procedure.current_step_id = None
            procedure.final_outcome = ProcedureOutcome.HYPOTHESIS_SUPPORTED if result_type == ObservationResultType.ABNORMAL else ProcedureOutcome.NO_CONFIDENT_CONCLUSION
            procedure.transition_to(ProcedureState.COMPLETED, reason="All procedure steps completed")

        return procedure

    # -----------------------------------------------------------------
    # Safety Validation Guardrails
    # -----------------------------------------------------------------

    def validate_safety(self, step: DiagnosticStep) -> Tuple[bool, Optional[str]]:
        """
        Enforces Phase H-1 safety invariants.
        Mode 04/14, 0x2E, 0x27, 0x2F, 0x34/36/37 and ACTIVE_DIAGNOSTIC are strictly prohibited.
        """
        # Hard execution mode check
        if step.execution_mode == StepExecutionMode.ACTIVE_DIAGNOSTIC:
            return False, "ACTIVE_DIAGNOSTIC mode is blocked in Phase H-1. Perform manual workshop test."

        # Safety classification check
        if step.safety_classification not in (ServiceSafetyClassification.READ_ONLY,):
            return False, f"Safety classification '{step.safety_classification.value}' is prohibited in H-1 (READ_ONLY required)."

        # Check instruction text for illegal dangerous commands
        text = (step.technician_instruction + " " + step.purpose).upper()
        for forbidden in ("MODE 04", "MODE 4", "MODE 14", "CLEAR DTCS", "0X2F", "ACTUATOR TEST", "PROGRAMMING"):
            if forbidden in text and "DO NOT" not in text and "MANUAL" not in text:
                return False, f"Step contains prohibited operation: '{forbidden}'."

        return True, None
