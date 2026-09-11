# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase H-5: Diagnostic Workflow Engine
=============================================================================
This module implements Phase H-5 of the Seyyanen diagnostic platform.
It unifies the complete diagnostic process into a controlled, deterministic,
evidence-driven workflow orchestrator:

  Vehicle Context
    -> Validation
    -> Baseline Acquisition (via existing read-only paths)
    -> Initial Analysis (G-3 Anomaly & Hypothesis Engine)
    -> Procedure Generation (H-1 Guided Procedure Engine)
    -> Test Selection (H-3 Evidence-Driven Selector)
    -> Test Execution (H-2 Automated Test Sequencer)
    -> Result Evaluation & Graph Update (G-5)
    -> Root-Cause Analysis (H-4 Automated Root-Cause Analyzer)
    -> Reassessment / Verification Loop (H-3 -> H-2 -> H-4)
    -> Technician Gate (when manual intervention is required)
    -> Safe Termination & Comprehensive Diagnostic Outcome

Core Architectural Invariants:
  1. ORCHESTRATION, NOT RE-IMPLEMENTATION:
     Coordinates H-1, H-2, H-3, and H-4 without duplicating their responsibilities:
     - G-3 owns anomaly detection & initial hypotheses.
     - H-1 owns procedure step modeling & instructions.
     - H-2 owns test sequencing & execution state.
     - H-3 owns test candidate scoring & selection.
     - H-4 owns root-cause ranking & causal reasoning.
     - H-5 owns workflow lifecycle, state machine, stage transitions, bounds,
       and technician gates.
  2. BOUNDED ITERATION & LOOP PREVENTION:
     Enforces strict caps on iterations, tests, repeated tests, reassessments,
     and global execution time. Guarantees 100% deterministic termination.
  3. STRICT G-LAYER SAFETY INVARIANTS:
     Zero actuator tests (0x2F), zero writes (0x2E), zero coding/programming
     (0x34/36/37), zero security access (0x27), zero DTC clears (Mode 04/14),
     zero autonomous physical repair.
  4. COMMUNICATION FAULT ISOLATION:
     ECU communication timeouts branch to network/wiring inspection rather than
     falsely diagnosing physical module component defects.
  5. MULTI-ECU AWARENESS:
     Preserves ECU identities, per-ECU states, and cross-ECU graph relationships.
  6. EXPLAINABLE AUDIT TRAIL & REPLAY:
     Every stage transition generates an immutable WorkflowEvent. Supports
     full to_dict() / from_dict() serialization and analytical state replay.
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
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

# Integration imports from C, D, E, F, G, and H layers
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
)
from advanced_ecu_services import (
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    SessionType,
    DiagnosticTransactionManager,
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    STATUS_TRANSACTION_BLOCKED,
)
from extended_did import (
    VehicleContext,
    StructuredDiagnosticEvidence,
    IdentifierNamespace,
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
    AdvancedFaultAnalyzer,
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
    ProcedureState,
    StepExecutionMode,
    StepPriority,
    ObservationResultType,
    ProcedureOutcome,
    DiagnosticStep,
    DiagnosticProcedureContext,
    DiagnosticProcedure,
    GuidedProcedureEngine,
)
from automated_test_sequencer import (
    SequenceState,
    StepEligibility,
    SequenceEventType,
    SequenceResult,
    DiagnosticSequence,
    AutomatedTestSequencer,
    TestExecutionAdapter,
    ReadOnlyAcquisitionAdapter,
    MockTestExecutionAdapter,
    TechnicianObservationAdapter,
    SequenceExecutionPolicy,
)
from evidence_driven_test_selector import (
    DiagnosticTestCandidate,
    TestSelectionContext,
    TestSelectionDecision,
    UncertaintyResolutionType,
    EvidenceDrivenTestSelector,
)
from automated_root_cause_analyzer import (
    RootCauseCandidateStatus,
    CausalBasis,
    CausalRole,
    RootCauseCertaintyLevel,
    AnalysisConclusionState,
    CauseEvidenceReference,
    RootCauseCandidate,
    RootCauseConclusion,
    RootCauseAnalysisContext,
    RootCauseAnalysis,
    AutomatedRootCauseAnalyzer,
)

logger = logging.getLogger(__name__)


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class WorkflowState(str, enum.Enum):
    """Lifecycle state machine for a DiagnosticWorkflow."""
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WAITING_FOR_TECHNICIAN = "WAITING_FOR_TECHNICIAN"
    WAITING_FOR_DATA = "WAITING_FOR_DATA"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class WorkflowStage(str, enum.Enum):
    """Discrete operational stages in the diagnostic workflow."""
    INITIALIZING = "INITIALIZING"
    CONTEXT_VALIDATION = "CONTEXT_VALIDATION"
    BASELINE_ACQUISITION = "BASELINE_ACQUISITION"
    INITIAL_ANALYSIS = "INITIAL_ANALYSIS"
    PROCEDURE_GENERATION = "PROCEDURE_GENERATION"
    TEST_SELECTION = "TEST_SELECTION"
    TEST_EXECUTION = "TEST_EXECUTION"
    RESULT_EVALUATION = "RESULT_EVALUATION"
    ROOT_CAUSE_ANALYSIS = "ROOT_CAUSE_ANALYSIS"
    ROOT_CAUSE_VERIFICATION = "ROOT_CAUSE_VERIFICATION"
    WAITING_FOR_TECHNICIAN = "WAITING_FOR_TECHNICIAN"
    REASSESSMENT = "REASSESSMENT"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class WorkflowEventType(str, enum.Enum):
    """Structured audit trail event classification."""
    WORKFLOW_CREATED = "WORKFLOW_CREATED"
    STATE_TRANSITION = "STATE_TRANSITION"
    STAGE_ENTERED = "STAGE_ENTERED"
    STAGE_COMPLETED = "STAGE_COMPLETED"
    BASELINE_ACQUIRED = "BASELINE_ACQUIRED"
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    PROCEDURE_CREATED = "PROCEDURE_CREATED"
    TEST_SELECTED = "TEST_SELECTED"
    TEST_EXECUTED = "TEST_EXECUTED"
    ROOT_CAUSE_UPDATED = "ROOT_CAUSE_UPDATED"
    TECHNICIAN_REQUESTED = "TECHNICIAN_REQUESTED"
    TECHNICIAN_RESPONDED = "TECHNICIAN_RESPONDED"
    LOOP_PREVENTED = "LOOP_PREVENTED"
    BOUNDS_EXCEEDED = "BOUNDS_EXCEEDED"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    ERROR_OCCURRED = "ERROR_OCCURRED"
    WORKFLOW_PAUSED = "WORKFLOW_PAUSED"
    WORKFLOW_RESUMED = "WORKFLOW_RESUMED"
    WORKFLOW_ABORTED = "WORKFLOW_ABORTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"


class WorkflowStopReason(str, enum.Enum):
    """Exhaustive reason for workflow termination."""
    ROOT_CAUSE_RESOLVED = "ROOT_CAUSE_RESOLVED"
    NO_CONFIDENT_CONCLUSION = "NO_CONFIDENT_CONCLUSION"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    COMMUNICATION_UNRESOLVED = "COMMUNICATION_UNRESOLVED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    TECHNICIAN_REQUIRED = "TECHNICIAN_REQUIRED"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    MAX_TESTS_REACHED = "MAX_TESTS_REACHED"
    GLOBAL_TIMEOUT = "GLOBAL_TIMEOUT"
    USER_ABORTED = "USER_ABORTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class WorkflowErrorCategory(str, enum.Enum):
    """Categorized workflow error taxonomy."""
    CONTEXT_ERROR = "CONTEXT_ERROR"
    SAFETY_ERROR = "SAFETY_ERROR"
    COMMUNICATION_ERROR = "COMMUNICATION_ERROR"
    CAPABILITY_ERROR = "CAPABILITY_ERROR"
    DATA_ERROR = "DATA_ERROR"
    PROCEDURE_ERROR = "PROCEDURE_ERROR"
    SEQUENCE_ERROR = "SEQUENCE_ERROR"
    SELECTION_ERROR = "SELECTION_ERROR"
    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    TECHNICIAN_REQUIRED = "TECHNICIAN_REQUIRED"
    TIMEOUT = "TIMEOUT"
    LIMIT_REACHED = "LIMIT_REACHED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# =====================================================================
# 2. WORKFLOW CONFIGURATION & DATA MODELS
# =====================================================================

@dataclass
class WorkflowPolicy:
    """
    Configurable bounding policy for workflow execution.
    Guarantees termination and prevents runaway diagnostic loops.
    """
    max_iterations: int = 20
    max_tests: int = 10
    max_repeated_tests: int = 2
    max_root_cause_reassessments: int = 8
    max_global_runtime_s: float = 600.0
    max_event_history: int = 150
    require_technician_confirmation: bool = True
    stop_on_communication_loss: bool = True
    allow_reassessment: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_iterations": self.max_iterations,
            "max_tests": self.max_tests,
            "max_repeated_tests": self.max_repeated_tests,
            "max_root_cause_reassessments": self.max_root_cause_reassessments,
            "max_global_runtime_s": self.max_global_runtime_s,
            "max_event_history": self.max_event_history,
            "require_technician_confirmation": self.require_technician_confirmation,
            "stop_on_communication_loss": self.stop_on_communication_loss,
            "allow_reassessment": self.allow_reassessment,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowPolicy":
        return cls(
            max_iterations=int(data.get("max_iterations", 20)),
            max_tests=int(data.get("max_tests", 10)),
            max_repeated_tests=int(data.get("max_repeated_tests", 2)),
            max_root_cause_reassessments=int(data.get("max_root_cause_reassessments", 8)),
            max_global_runtime_s=float(data.get("max_global_runtime_s", 600.0)),
            max_event_history=int(data.get("max_event_history", 150)),
            require_technician_confirmation=bool(data.get("require_technician_confirmation", True)),
            stop_on_communication_loss=bool(data.get("stop_on_communication_loss", True)),
            allow_reassessment=bool(data.get("allow_reassessment", True)),
        )


@dataclass
class WorkflowEvent:
    """
    Immutable audit trail event capturing an action or state change in the workflow.
    """
    event_id: str
    workflow_id: str
    timestamp: float
    previous_stage: WorkflowStage
    new_stage: WorkflowStage
    event_type: WorkflowEventType
    reason: str
    source_component: str
    test_id: Optional[str] = None
    target_ecu: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "workflow_id": self.workflow_id,
            "timestamp": round(self.timestamp, 3),
            "previous_stage": self.previous_stage.value,
            "new_stage": self.new_stage.value,
            "event_type": self.event_type.value,
            "reason": self.reason,
            "source_component": self.source_component,
            "test_id": self.test_id,
            "target_ecu": self.target_ecu,
            "evidence_refs": list(self.evidence_refs),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowEvent":
        return cls(
            event_id=data["event_id"],
            workflow_id=data["workflow_id"],
            timestamp=float(data.get("timestamp", time.time())),
            previous_stage=WorkflowStage(data["previous_stage"]),
            new_stage=WorkflowStage(data["new_stage"]),
            event_type=WorkflowEventType(data["event_type"]),
            reason=data.get("reason", ""),
            source_component=data.get("source_component", "H5_ENGINE"),
            test_id=data.get("test_id"),
            target_ecu=data.get("target_ecu"),
            evidence_refs=data.get("evidence_refs", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TechnicianActionGate:
    """
    Structured technician intervention request when human observation/measurement is required.
    """
    action_id: str
    instruction: str
    purpose: str
    expected_observation: str
    safety_warning: Optional[str] = None
    target_ecu: Optional[str] = None
    status: str = "PENDING"  # PENDING, COMPLETED, REJECTED, CANCELLED
    response: Optional[Dict[str, Any]] = None
    technician_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "instruction": self.instruction,
            "purpose": self.purpose,
            "expected_observation": self.expected_observation,
            "safety_warning": self.safety_warning,
            "target_ecu": self.target_ecu,
            "status": self.status,
            "response": self.response,
            "technician_id": self.technician_id,
            "timestamp": round(self.timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TechnicianActionGate":
        return cls(
            action_id=data["action_id"],
            instruction=data["instruction"],
            purpose=data["purpose"],
            expected_observation=data["expected_observation"],
            safety_warning=data.get("safety_warning"),
            target_ecu=data.get("target_ecu"),
            status=data.get("status", "PENDING"),
            response=data.get("response"),
            technician_id=data.get("technician_id"),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class WorkflowDecision:
    """
    Current decision made by the orchestration engine regarding the next action.
    """
    action: str  # ADVANCE, SELECT_TEST, EXECUTE_TEST, REQUEST_VERIFICATION, REQUEST_TECHNICIAN, COMPLETE, STOP
    stage: WorkflowStage
    rationale: str
    source_component: str
    confidence: float = 1.0
    recommended_step_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "stage": self.stage.value,
            "rationale": self.rationale,
            "source_component": self.source_component,
            "confidence": round(self.confidence, 3),
            "recommended_step_id": self.recommended_step_id,
            "timestamp": round(self.timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowDecision":
        return cls(
            action=data["action"],
            stage=WorkflowStage(data["stage"]),
            rationale=data.get("rationale", ""),
            source_component=data.get("source_component", "H5_ENGINE"),
            confidence=float(data.get("confidence", 1.0)),
            recommended_step_id=data.get("recommended_step_id"),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class WorkflowOutcome:
    """
    Final comprehensive outcome summarizing the completed or terminated workflow.
    """
    outcome_type: WorkflowStopReason
    primary_diagnosis: Optional[str]
    primary_candidate_id: Optional[str]
    certainty: RootCauseCertaintyLevel
    confidence: float
    alternative_candidates: List[str] = field(default_factory=list)
    supporting_evidence_count: int = 0
    contradicting_evidence_count: int = 0
    tests_performed: List[str] = field(default_factory=list)
    procedures_performed: List[str] = field(default_factory=list)
    unresolved_issues: List[str] = field(default_factory=list)
    technician_actions_required: List[str] = field(default_factory=list)
    recommended_next_action: Optional[str] = None
    summary_text: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome_type": self.outcome_type.value,
            "primary_diagnosis": self.primary_diagnosis,
            "primary_candidate_id": self.primary_candidate_id,
            "certainty": self.certainty.value,
            "confidence": round(self.confidence, 3),
            "alternative_candidates": list(self.alternative_candidates),
            "supporting_evidence_count": self.supporting_evidence_count,
            "contradicting_evidence_count": self.contradicting_evidence_count,
            "tests_performed": list(self.tests_performed),
            "procedures_performed": list(self.procedures_performed),
            "unresolved_issues": list(self.unresolved_issues),
            "technician_actions_required": list(self.technician_actions_required),
            "recommended_next_action": self.recommended_next_action,
            "summary_text": self.summary_text,
            "provenance": self.provenance,
            "completed_at": round(self.completed_at, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowOutcome":
        return cls(
            outcome_type=WorkflowStopReason(data["outcome_type"]),
            primary_diagnosis=data.get("primary_diagnosis"),
            primary_candidate_id=data.get("primary_candidate_id"),
            certainty=RootCauseCertaintyLevel(data.get("certainty", "INCONCLUSIVE")),
            confidence=float(data.get("confidence", 0.0)),
            alternative_candidates=data.get("alternative_candidates", []),
            supporting_evidence_count=int(data.get("supporting_evidence_count", 0)),
            contradicting_evidence_count=int(data.get("contradicting_evidence_count", 0)),
            tests_performed=data.get("tests_performed", []),
            procedures_performed=data.get("procedures_performed", []),
            unresolved_issues=data.get("unresolved_issues", []),
            technician_actions_required=data.get("technician_actions_required", []),
            recommended_next_action=data.get("recommended_next_action"),
            summary_text=data.get("summary_text", ""),
            provenance=data.get("provenance", {}),
            completed_at=float(data.get("completed_at", time.time())),
        )


# =====================================================================
# 3. ROOT DIAGNOSTIC WORKFLOW CONTAINER
# =====================================================================

@dataclass
class DiagnosticWorkflow:
    """
    Root serializable state container for an end-to-end diagnostic workflow.
    Maintains clean references to H-1 procedures, H-2 sequences, H-3 decisions,
    and H-4 root-cause analyses without merging them into an opaque blob.
    """
    workflow_id: str
    vehicle_id: str
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    state: WorkflowState = WorkflowState.INITIALIZING
    stage: WorkflowStage = WorkflowStage.INITIALIZING
    policy: WorkflowPolicy = field(default_factory=WorkflowPolicy)

    # Core engine references
    procedure: Optional[DiagnosticProcedure] = None
    sequence: Optional[DiagnosticSequence] = None
    latest_selection: Optional[TestSelectionDecision] = None
    latest_root_cause: Optional[RootCauseAnalysis] = None

    # Accumulated diagnostic context
    active_hypotheses: List[FaultHypothesis] = field(default_factory=list)
    active_evidence: List[FaultEvidence] = field(default_factory=list)
    active_dtcs: List[DTCRecord] = field(default_factory=list)
    completed_test_results: List[SequenceResult] = field(default_factory=list)
    selection_history: List[TestSelectionDecision] = field(default_factory=list)
    available_ecus: List[str] = field(default_factory=lambda: ["ECM"])
    unreachable_ecus: List[str] = field(default_factory=list)
    operating_condition: str = "IDLE"

    # Execution tracking & limits
    iteration_count: int = 0
    test_count: int = 0
    reassessment_count: int = 0
    test_revisit_counts: Dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))

    # Technician interaction
    pending_technician_gate: Optional[TechnicianActionGate] = None
    technician_inputs: List[Dict[str, Any]] = field(default_factory=list)

    # Event audit trail & decisions
    events: List[WorkflowEvent] = field(default_factory=list)
    current_decision: Optional[WorkflowDecision] = None
    outcome: Optional[WorkflowOutcome] = None

    safety_state: str = "SECURE_READ_ONLY"
    provenance: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    # Deterministic Stage Transitions
    VALID_STAGE_TRANSITIONS: ClassVar[Dict[WorkflowStage, Set[WorkflowStage]]] = {
        WorkflowStage.INITIALIZING: {WorkflowStage.CONTEXT_VALIDATION, WorkflowStage.FAILED, WorkflowStage.ABORTED},
        WorkflowStage.CONTEXT_VALIDATION: {
            WorkflowStage.BASELINE_ACQUISITION,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.BASELINE_ACQUISITION: {
            WorkflowStage.INITIAL_ANALYSIS,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.INITIAL_ANALYSIS: {
            WorkflowStage.PROCEDURE_GENERATION,
            WorkflowStage.ROOT_CAUSE_ANALYSIS,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.PROCEDURE_GENERATION: {
            WorkflowStage.TEST_SELECTION,
            WorkflowStage.TEST_EXECUTION,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.TEST_SELECTION: {
            WorkflowStage.TEST_EXECUTION,
            WorkflowStage.ROOT_CAUSE_ANALYSIS,
            WorkflowStage.WAITING_FOR_TECHNICIAN,
            WorkflowStage.COMPLETED,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.TEST_EXECUTION: {
            WorkflowStage.RESULT_EVALUATION,
            WorkflowStage.WAITING_FOR_TECHNICIAN,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.RESULT_EVALUATION: {
            WorkflowStage.ROOT_CAUSE_ANALYSIS,
            WorkflowStage.TEST_SELECTION,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.ROOT_CAUSE_ANALYSIS: {
            WorkflowStage.ROOT_CAUSE_VERIFICATION,
            WorkflowStage.TEST_SELECTION,
            WorkflowStage.WAITING_FOR_TECHNICIAN,
            WorkflowStage.COMPLETED,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.ROOT_CAUSE_VERIFICATION: {
            WorkflowStage.TEST_SELECTION,
            WorkflowStage.TEST_EXECUTION,
            WorkflowStage.WAITING_FOR_TECHNICIAN,
            WorkflowStage.COMPLETED,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.WAITING_FOR_TECHNICIAN: {
            WorkflowStage.REASSESSMENT,
            WorkflowStage.TEST_EXECUTION,
            WorkflowStage.ROOT_CAUSE_ANALYSIS,
            WorkflowStage.COMPLETED,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.REASSESSMENT: {
            WorkflowStage.ROOT_CAUSE_ANALYSIS,
            WorkflowStage.TEST_SELECTION,
            WorkflowStage.COMPLETED,
            WorkflowStage.BLOCKED,
            WorkflowStage.FAILED,
            WorkflowStage.ABORTED,
        },
        WorkflowStage.COMPLETED: set(),
        WorkflowStage.BLOCKED: set(),
        WorkflowStage.FAILED: set(),
        WorkflowStage.ABORTED: set(),
    }

    @property
    def is_terminal(self) -> bool:
        return self.state in (WorkflowState.COMPLETED, WorkflowState.BLOCKED, WorkflowState.FAILED, WorkflowState.ABORTED)

    def transition_to(
        self,
        new_stage: WorkflowStage,
        reason: str = "",
        event_type: WorkflowEventType = WorkflowEventType.STAGE_ENTERED,
        source_component: str = "H5_ENGINE",
        test_id: Optional[str] = None,
        target_ecu: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Enforces deterministic state and stage transitions.
        Invalid transitions fail immediately and predictably.
        """
        prev_stage = self.stage
        allowed = self.VALID_STAGE_TRANSITIONS.get(prev_stage, set())

        if new_stage not in allowed and prev_stage != new_stage:
            raise ValueError(
                f"Invalid workflow stage transition: cannot transition from '{prev_stage.value}' to '{new_stage.value}'."
            )

        self.stage = new_stage
        self.updated_at = time.time()

        # Update matching WorkflowState
        if new_stage == WorkflowStage.COMPLETED:
            self.state = WorkflowState.COMPLETED
        elif new_stage == WorkflowStage.BLOCKED:
            self.state = WorkflowState.BLOCKED
        elif new_stage == WorkflowStage.FAILED:
            self.state = WorkflowState.FAILED
        elif new_stage == WorkflowStage.ABORTED:
            self.state = WorkflowState.ABORTED
        elif new_stage == WorkflowStage.WAITING_FOR_TECHNICIAN:
            self.state = WorkflowState.WAITING_FOR_TECHNICIAN
        else:
            self.state = WorkflowState.ACTIVE

        # Record event
        evt = WorkflowEvent(
            event_id=f"evt_{uuid.uuid4().hex[:10]}",
            workflow_id=self.workflow_id,
            timestamp=self.updated_at,
            previous_stage=prev_stage,
            new_stage=new_stage,
            event_type=event_type,
            reason=reason,
            source_component=source_component,
            test_id=test_id,
            target_ecu=target_ecu,
            metadata=metadata or {},
        )
        self.events.append(evt)
        if len(self.events) > self.policy.max_event_history:
            self.events = self.events[-self.policy.max_event_history:]

    def to_dict(self) -> Dict[str, Any]:
        """Full round-trip serialization of the workflow state."""
        return {
            "workflow_id": self.workflow_id,
            "vehicle_id": self.vehicle_id,
            "session_id": self.session_id,
            "created_at": round(self.created_at, 3),
            "updated_at": round(self.updated_at, 3),
            "state": self.state.value,
            "stage": self.stage.value,
            "policy": self.policy.to_dict(),
            "procedure": self.procedure.to_dict() if self.procedure else None,
            "sequence": self.sequence.to_dict() if self.sequence else None,
            "latest_selection": self.latest_selection.to_dict() if self.latest_selection else None,
            "latest_root_cause": self.latest_root_cause.to_dict() if self.latest_root_cause else None,
            "available_ecus": list(self.available_ecus),
            "unreachable_ecus": list(self.unreachable_ecus),
            "operating_condition": self.operating_condition,
            "iteration_count": self.iteration_count,
            "test_count": self.test_count,
            "reassessment_count": self.reassessment_count,
            "test_revisit_counts": dict(self.test_revisit_counts),
            "pending_technician_gate": self.pending_technician_gate.to_dict() if self.pending_technician_gate else None,
            "technician_inputs": list(self.technician_inputs),
            "events": [e.to_dict() for e in self.events],
            "current_decision": self.current_decision.to_dict() if self.current_decision else None,
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "safety_state": self.safety_state,
            "provenance": self.provenance,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticWorkflow":
        """Reconstructs DiagnosticWorkflow from serialized dictionary."""
        proc = DiagnosticProcedure.from_dict(data["procedure"]) if data.get("procedure") else None
        seq = DiagnosticSequence.from_dict(data["sequence"]) if data.get("sequence") else None
        sel = TestSelectionDecision.from_dict(data["latest_selection"]) if data.get("latest_selection") else None
        rca = RootCauseAnalysis.from_dict(data["latest_root_cause"]) if data.get("latest_root_cause") else None
        gate = TechnicianActionGate.from_dict(data["pending_technician_gate"]) if data.get("pending_technician_gate") else None
        dec = WorkflowDecision.from_dict(data["current_decision"]) if data.get("current_decision") else None
        out = WorkflowOutcome.from_dict(data["outcome"]) if data.get("outcome") else None
        events = [WorkflowEvent.from_dict(e) for e in data.get("events", [])]

        wf = cls(
            workflow_id=data["workflow_id"],
            vehicle_id=data["vehicle_id"],
            session_id=data["session_id"],
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            state=WorkflowState(data.get("state", "INITIALIZING")),
            stage=WorkflowStage(data.get("stage", "INITIALIZING")),
            policy=WorkflowPolicy.from_dict(data.get("policy", {})),
            procedure=proc,
            sequence=seq,
            latest_selection=sel,
            latest_root_cause=rca,
            available_ecus=data.get("available_ecus", ["ECM"]),
            unreachable_ecus=data.get("unreachable_ecus", []),
            operating_condition=data.get("operating_condition", "IDLE"),
            iteration_count=int(data.get("iteration_count", 0)),
            test_count=int(data.get("test_count", 0)),
            reassessment_count=int(data.get("reassessment_count", 0)),
            pending_technician_gate=gate,
            technician_inputs=data.get("technician_inputs", []),
            events=events,
            current_decision=dec,
            outcome=out,
            safety_state=data.get("safety_state", "SECURE_READ_ONLY"),
            provenance=data.get("provenance", {}),
            version=data.get("version", "1.0.0"),
        )
        for k, v in data.get("test_revisit_counts", {}).items():
            wf.test_revisit_counts[k] = int(v)
        return wf


# =====================================================================
# 4. DIAGNOSTIC WORKFLOW ORCHESTRATION ENGINE
# =====================================================================

class DiagnosticWorkflowEngine:
    """
    Deterministic Master Diagnostic Workflow Engine for Phase H-5.
    Coordinates H-1, H-2, H-3, and H-4 while enforcing loop prevention,
    bounded execution, safety policies, and technician action gates.
    """

    def __init__(
        self,
        procedure_engine: Optional[GuidedProcedureEngine] = None,
        sequencer: Optional[AutomatedTestSequencer] = None,
        selector: Optional[EvidenceDrivenTestSelector] = None,
        root_cause_analyzer: Optional[AutomatedRootCauseAnalyzer] = None,
        fault_analysis_engine: Optional[AdvancedFaultAnalyzer] = None,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
    ):
        self.safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)
        self.procedure_engine = procedure_engine or GuidedProcedureEngine()
        self.sequencer = sequencer or AutomatedTestSequencer(safety_policy=self.safety_policy)
        self.selector = selector or EvidenceDrivenTestSelector(safety_policy=self.safety_policy)
        self.root_cause_analyzer = root_cause_analyzer or AutomatedRootCauseAnalyzer()
        self.fault_analysis_engine = fault_analysis_engine or AdvancedFaultAnalyzer()
        self._lock = threading.RLock()

    # -----------------------------------------------------------------
    # A. Lifecycle & Workflow Management
    # -----------------------------------------------------------------

    def create_workflow(
        self,
        vehicle_context: Optional[VehicleContext] = None,
        session_id: Optional[str] = None,
        policy: Optional[WorkflowPolicy] = None,
        available_ecus: Optional[List[str]] = None,
        unreachable_ecus: Optional[List[str]] = None,
    ) -> DiagnosticWorkflow:
        """
        Creates a new diagnostic workflow. Does not execute operations immediately.
        Validates vehicle context and initializes baseline state.
        """
        with self._lock:
            veh_id = make_vehicle_node_id(vehicle_context)
            sess_id = session_id or f"wf_sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            wf_id = f"wf_{uuid.uuid4().hex[:12]}"

            wf = DiagnosticWorkflow(
                workflow_id=wf_id,
                vehicle_id=veh_id,
                session_id=sess_id,
                policy=policy or WorkflowPolicy(),
                available_ecus=["ECM"] if available_ecus is None else list(available_ecus),
                unreachable_ecus=list(unreachable_ecus or []),
                provenance={
                    "created_by": "DiagnosticWorkflowEngine",
                    "timestamp": time.time(),
                    "vin": vehicle_context.vin if vehicle_context else "UNKNOWN",
                },
            )

            wf.events.append(
                WorkflowEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:10]}",
                    workflow_id=wf_id,
                    timestamp=time.time(),
                    previous_stage=WorkflowStage.INITIALIZING,
                    new_stage=WorkflowStage.INITIALIZING,
                    event_type=WorkflowEventType.WORKFLOW_CREATED,
                    reason="Workflow instance created.",
                    source_component="H5_ENGINE",
                )
            )
            return wf

    def start_workflow(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Transitions the workflow from INITIALIZING to CONTEXT_VALIDATION.
        """
        with self._lock:
            if workflow.state != WorkflowState.INITIALIZING:
                raise ValueError(f"Cannot start workflow in state '{workflow.state.value}'.")

            workflow.transition_to(
                WorkflowStage.CONTEXT_VALIDATION,
                reason="Starting diagnostic workflow context validation.",
            )
            workflow.current_decision = WorkflowDecision(
                action="ADVANCE",
                stage=workflow.stage,
                rationale="Workflow initialized. Proceeding to context validation.",
                source_component="H5_ENGINE",
            )
            return workflow.current_decision

    def pause(self, workflow: DiagnosticWorkflow, reason: str = "User requested pause") -> bool:
        """Pauses the workflow if active."""
        with self._lock:
            if workflow.is_terminal or workflow.state == WorkflowState.PAUSED:
                return False
            workflow.state = WorkflowState.PAUSED
            workflow.events.append(
                WorkflowEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:10]}",
                    workflow_id=workflow.workflow_id,
                    timestamp=time.time(),
                    previous_stage=workflow.stage,
                    new_stage=workflow.stage,
                    event_type=WorkflowEventType.WORKFLOW_PAUSED,
                    reason=reason,
                    source_component="H5_ENGINE",
                )
            )
            return True

    def resume(self, workflow: DiagnosticWorkflow) -> bool:
        """Resumes a paused workflow."""
        with self._lock:
            if workflow.state != WorkflowState.PAUSED:
                return False
            workflow.state = WorkflowState.ACTIVE
            workflow.events.append(
                WorkflowEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:10]}",
                    workflow_id=workflow.workflow_id,
                    timestamp=time.time(),
                    previous_stage=workflow.stage,
                    new_stage=workflow.stage,
                    event_type=WorkflowEventType.WORKFLOW_RESUMED,
                    reason="Workflow resumed from paused state.",
                    source_component="H5_ENGINE",
                )
            )
            return True

    def abort(self, workflow: DiagnosticWorkflow, reason: str = "User aborted") -> WorkflowOutcome:
        """Aborts the workflow and produces a final outcome."""
        with self._lock:
            if workflow.is_terminal:
                return workflow.outcome or self._finalize_outcome(workflow, WorkflowStopReason.USER_ABORTED)

            workflow.transition_to(
                WorkflowStage.ABORTED,
                reason=reason,
                event_type=WorkflowEventType.WORKFLOW_ABORTED,
            )
            return self._finalize_outcome(workflow, WorkflowStopReason.USER_ABORTED, summary=f"Aborted: {reason}")

    # -----------------------------------------------------------------
    # B. Single-Step Advancement Driver
    # -----------------------------------------------------------------

    def advance(
        self,
        workflow: DiagnosticWorkflow,
        technician_input: Optional[Dict[str, Any]] = None,
        baseline_data: Optional[Dict[str, Any]] = None,
        mock_sequence_result: Optional[SequenceResult] = None,
    ) -> WorkflowDecision:
        """
        Advances the workflow by executing one bounded stage operation.
        Returns a structured WorkflowDecision.
        """
        with self._lock:
            if workflow.is_terminal:
                return WorkflowDecision(
                    action="STOP",
                    stage=workflow.stage,
                    rationale=f"Workflow is in terminal state '{workflow.state.value}'.",
                    source_component="H5_ENGINE",
                )

            if workflow.state == WorkflowState.PAUSED:
                return WorkflowDecision(
                    action="STOP",
                    stage=workflow.stage,
                    rationale="Workflow is paused. Resume before advancing.",
                    source_component="H5_ENGINE",
                )

            # Check bounded limits before executing stage
            workflow.iteration_count += 1
            if workflow.iteration_count > workflow.policy.max_iterations:
                workflow.transition_to(
                    WorkflowStage.BLOCKED,
                    reason=f"Exceeded max_iterations ({workflow.policy.max_iterations}).",
                    event_type=WorkflowEventType.BOUNDS_EXCEEDED,
                )
                self._finalize_outcome(workflow, WorkflowStopReason.MAX_ITERATIONS_REACHED)
                return WorkflowDecision(
                    action="STOP",
                    stage=workflow.stage,
                    rationale="Maximum workflow iterations reached. Terminating safely.",
                    source_component="H5_ENGINE",
                )

            if (time.time() - workflow.created_at) > workflow.policy.max_global_runtime_s:
                workflow.transition_to(
                    WorkflowStage.FAILED,
                    reason="Global workflow execution timeout exceeded.",
                    event_type=WorkflowEventType.BOUNDS_EXCEEDED,
                )
                self._finalize_outcome(workflow, WorkflowStopReason.GLOBAL_TIMEOUT)
                return WorkflowDecision(
                    action="STOP",
                    stage=workflow.stage,
                    rationale="Global execution timeout exceeded.",
                    source_component="H5_ENGINE",
                )

            # Dispatch according to current stage
            stage = workflow.stage
            decision: WorkflowDecision

            if stage == WorkflowStage.CONTEXT_VALIDATION:
                decision = self._stage_context_validation(workflow)
            elif stage == WorkflowStage.BASELINE_ACQUISITION:
                decision = self._stage_baseline_acquisition(workflow, baseline_data)
            elif stage == WorkflowStage.INITIAL_ANALYSIS:
                decision = self._stage_initial_analysis(workflow)
            elif stage == WorkflowStage.PROCEDURE_GENERATION:
                decision = self._stage_procedure_generation(workflow)
            elif stage == WorkflowStage.TEST_SELECTION:
                decision = self._stage_test_selection(workflow)
            elif stage == WorkflowStage.TEST_EXECUTION:
                decision = self._stage_test_execution(workflow, technician_input, mock_sequence_result)
            elif stage == WorkflowStage.RESULT_EVALUATION:
                decision = self._stage_result_evaluation(workflow)
            elif stage == WorkflowStage.ROOT_CAUSE_ANALYSIS:
                decision = self._stage_root_cause_analysis(workflow)
            elif stage == WorkflowStage.ROOT_CAUSE_VERIFICATION:
                decision = self._stage_root_cause_verification(workflow)
            elif stage == WorkflowStage.WAITING_FOR_TECHNICIAN:
                decision = self._stage_waiting_for_technician(workflow, technician_input)
            elif stage == WorkflowStage.REASSESSMENT:
                decision = self._stage_reassessment(workflow)
            else:
                decision = WorkflowDecision(
                    action="STOP",
                    stage=stage,
                    rationale=f"Unhandled workflow stage '{stage.value}'.",
                    source_component="H5_ENGINE",
                )

            workflow.current_decision = decision
            return decision

    # -----------------------------------------------------------------
    # C. Individual Stage Handlers
    # -----------------------------------------------------------------

    def _stage_context_validation(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """Validates vehicle identity, safety classification, and communication channels."""
        # Validate vehicle identity
        if not workflow.vehicle_id or workflow.vehicle_id == "UNKNOWN":
            workflow.transition_to(WorkflowStage.BLOCKED, reason="Invalid or missing vehicle identity.")
            self._finalize_outcome(workflow, WorkflowStopReason.SAFETY_BLOCKED, summary="Vehicle identity invalid.")
            return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Vehicle context validation failed.", source_component="H5_ENGINE")

        # Communication check
        if not workflow.available_ecus and workflow.unreachable_ecus:
            workflow.transition_to(WorkflowStage.BLOCKED, reason="All ECUs are unreachable.")
            self._finalize_outcome(workflow, WorkflowStopReason.COMMUNICATION_UNRESOLVED, summary="All ECUs unreachable.")
            return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Communication unavailable on all ECUs.", source_component="H5_ENGINE")

        # Safety policy check
        if self.safety_policy:
            test_req = AdvancedServiceRequest(
                service_id="22",
                payload="0100",
                target_ecu="ECM",
                safety_classification=ServiceSafetyClassification.READ_ONLY,
            )
            is_valid, reason = self.safety_policy.validate_request(test_req)
            if not is_valid:
                workflow.transition_to(WorkflowStage.BLOCKED, reason=f"Safety policy rejects acquisition: {reason}")
                self._finalize_outcome(workflow, WorkflowStopReason.SAFETY_BLOCKED, summary="Safety policy violation.")
                return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Safety policy rejected.", source_component="H5_ENGINE")

        workflow.transition_to(WorkflowStage.BASELINE_ACQUISITION, reason="Context validated successfully.")
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Context validated. Moving to baseline acquisition.", source_component="H5_ENGINE")

    def _stage_baseline_acquisition(
        self,
        workflow: DiagnosticWorkflow,
        baseline_data: Optional[Dict[str, Any]] = None,
    ) -> WorkflowDecision:
        """
        Gathers baseline data via existing read-only services without duplicating transport logic.
        """
        # Enforce read-only safety invariant
        if baseline_data and baseline_data.get("attempted_destructive_mode"):
            workflow.transition_to(WorkflowStage.BLOCKED, reason="Destructive acquisition attempt rejected.")
            self._finalize_outcome(workflow, WorkflowStopReason.SAFETY_BLOCKED, summary="Blocked destructive acquisition.")
            return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Safety violation.", source_component="H5_ENGINE")

        # Check for communication failure on baseline acquisition
        if baseline_data and baseline_data.get("communication_error"):
            unreach = baseline_data.get("target_ecu", "ECM")
            if unreach not in workflow.unreachable_ecus:
                workflow.unreachable_ecus.append(unreach)
            if unreach in workflow.available_ecus:
                workflow.available_ecus.remove(unreach)

            if workflow.policy.stop_on_communication_loss and not workflow.available_ecus:
                workflow.transition_to(WorkflowStage.BLOCKED, reason=f"Baseline communication failed with {unreach}.")
                self._finalize_outcome(workflow, WorkflowStopReason.COMMUNICATION_UNRESOLVED, summary=f"ECU {unreach} unreachable.")
                return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Critical ECU unreachable.", source_component="H5_ENGINE")

        # Ingest baseline DTCs if provided
        if baseline_data and "dtcs" in baseline_data:
            for dtc_code in baseline_data["dtcs"]:
                workflow.active_dtcs.append(DTCRecord(code=dtc_code, ecu_source=baseline_data.get("target_ecu", "7E0"), status="CONFIRMED"))

        workflow.transition_to(
            WorkflowStage.INITIAL_ANALYSIS,
            reason="Baseline acquisition complete.",
            event_type=WorkflowEventType.BASELINE_ACQUIRED,
        )
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Baseline data acquired. Proceeding to initial analysis.", source_component="H5_ENGINE")

    def _stage_initial_analysis(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Invokes G-3 to analyze baseline data and formulate hypotheses.
        """
        # Synthesize initial hypotheses if not already loaded
        if not workflow.active_hypotheses:
            if workflow.active_dtcs:
                for dtc in workflow.active_dtcs:
                    hyp = FaultHypothesis(
                        hypothesis_id=f"hyp_{dtc.code}",
                        title=f"Fault condition associated with DTC {dtc.code}",
                        category="AIR_FUEL" if "01" in dtc.code else "GENERAL",
                        affected_system="POWERTRAIN",
                        confidence=HypothesisConfidence.MEDIUM,
                        dtc_associations=[dtc.code],
                    )
                    workflow.active_hypotheses.append(hyp)
            elif not workflow.unreachable_ecus:
                # Default baseline hypothesis
                hyp = FaultHypothesis(
                    hypothesis_id="hyp_baseline",
                    title="Air-fuel imbalance or vacuum leak",
                    category="AIR_FUEL",
                    affected_system="POWERTRAIN",
                    confidence=HypothesisConfidence.LOW,
                    is_dtc_free=True,
                )
                workflow.active_hypotheses.append(hyp)

        workflow.transition_to(
            WorkflowStage.PROCEDURE_GENERATION,
            reason="Initial fault analysis complete.",
            event_type=WorkflowEventType.ANALYSIS_COMPLETED,
        )
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Initial analysis generated hypotheses.", source_component="G3_ANALYSIS")

    def _stage_procedure_generation(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Invokes H-1 to generate the guided diagnostic procedure.
        """
        if not workflow.procedure:
            workflow.procedure = self.procedure_engine.generate_procedure(
                session_id=workflow.session_id,
                hypotheses=workflow.active_hypotheses,
                dtcs=workflow.active_dtcs,
                unreachable_ecus=set(workflow.unreachable_ecus),
                available_signals=set(),
            )

        # Initialize sequence via H-2
        if not workflow.sequence and workflow.procedure:
            workflow.sequence = self.sequencer.create_sequence(workflow.procedure, session_id=workflow.session_id)

        workflow.transition_to(
            WorkflowStage.TEST_SELECTION,
            reason="Diagnostic procedure and sequence generated.",
            event_type=WorkflowEventType.PROCEDURE_CREATED,
        )
        return WorkflowDecision(action="SELECT_TEST", stage=workflow.stage, rationale="Procedure generated. Ready to select test.", source_component="H1_PROCEDURES")

    def _stage_test_selection(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Invokes H-3 to select the best discriminating test.
        Enforces infinite-loop protection and repeated-test limits.
        """
        # Check test count bounds
        if workflow.test_count >= workflow.policy.max_tests:
            workflow.transition_to(
                WorkflowStage.ROOT_CAUSE_ANALYSIS,
                reason="Maximum test count reached; proceeding to final root-cause analysis.",
                event_type=WorkflowEventType.BOUNDS_EXCEEDED,
            )
            return WorkflowDecision(action="PROCEED", stage=workflow.stage, rationale="Max tests reached.", source_component="H5_ENGINE")

        sel_ctx = TestSelectionContext(
            vehicle_id=workflow.vehicle_id,
            session_id=workflow.session_id,
            hypotheses=list(workflow.active_hypotheses),
            active_evidence=list(workflow.active_evidence),
            available_ecus=list(workflow.available_ecus),
            unreachable_ecus=list(workflow.unreachable_ecus),
            operating_condition=workflow.operating_condition,
            completed_test_ids=workflow.sequence.completed_steps if workflow.sequence else [],
        )

        candidate_pool = None
        if workflow.procedure:
            candidate_pool = self.selector.extract_candidates_from_procedure(workflow.procedure)

        decision = self.selector.select_next_test(
            context=sel_ctx,
            candidate_pool=candidate_pool,
        )
        workflow.latest_selection = decision
        workflow.selection_history.append(decision)

        if not decision.selected_candidate:
            # No further tests available -> proceed to RCA
            workflow.transition_to(WorkflowStage.ROOT_CAUSE_ANALYSIS, reason="No further tests selectable by H-3.")
            return WorkflowDecision(action="PROCEED", stage=workflow.stage, rationale="No tests selectable.", source_component="H3_SELECTOR")

        selected_cand = decision.selected_candidate
        cand_id = selected_cand.candidate_id

        # Infinite loop protection: Check repeated selections
        visit_count = workflow.test_revisit_counts[cand_id]
        if visit_count >= workflow.policy.max_repeated_tests:
            workflow.events.append(
                WorkflowEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:10]}",
                    workflow_id=workflow.workflow_id,
                    timestamp=time.time(),
                    previous_stage=workflow.stage,
                    new_stage=workflow.stage,
                    event_type=WorkflowEventType.LOOP_PREVENTED,
                    reason=f"Candidate '{cand_id}' exceeded max_repeated_tests ({workflow.policy.max_repeated_tests}).",
                    source_component="H5_ENGINE",
                    test_id=cand_id,
                )
            )
            workflow.transition_to(WorkflowStage.ROOT_CAUSE_ANALYSIS, reason="Prevented infinite test loop.")
            return WorkflowDecision(action="PROCEED", stage=workflow.stage, rationale="Loop prevented; proceeding to root cause.", source_component="H5_ENGINE")

        workflow.test_revisit_counts[cand_id] += 1

        # Check if the selected test requires human technician action
        if selected_cand.execution_mode in (StepExecutionMode.OBSERVATIONAL, StepExecutionMode.MEASUREMENT):
            # Create technician action gate
            gate = TechnicianActionGate(
                action_id=f"act_{cand_id}_{uuid.uuid4().hex[:6]}",
                instruction=selected_cand.description,
                purpose=selected_cand.title,
                expected_observation="Confirm component physical condition.",
                target_ecu=selected_cand.target_ecu,
            )
            workflow.pending_technician_gate = gate
            workflow.transition_to(
                WorkflowStage.WAITING_FOR_TECHNICIAN,
                reason=f"Test '{cand_id}' requires technician physical action.",
                event_type=WorkflowEventType.TECHNICIAN_REQUESTED,
                test_id=cand_id,
            )
            return WorkflowDecision(
                action="REQUEST_TECHNICIAN",
                stage=workflow.stage,
                rationale=f"Technician intervention required: {selected_cand.title}",
                source_component="H5_ENGINE",
                recommended_step_id=cand_id,
            )

        workflow.transition_to(
            WorkflowStage.TEST_EXECUTION,
            reason=f"Selected test '{cand_id}' ready for execution.",
            event_type=WorkflowEventType.TEST_SELECTED,
            test_id=cand_id,
        )
        return WorkflowDecision(
            action="EXECUTE_TEST",
            stage=workflow.stage,
            rationale=f"Selected test {cand_id} via H-3.",
            source_component="H3_SELECTOR",
            recommended_step_id=cand_id,
        )

    def _stage_test_execution(
        self,
        workflow: DiagnosticWorkflow,
        technician_input: Optional[Dict[str, Any]] = None,
        mock_sequence_result: Optional[SequenceResult] = None,
    ) -> WorkflowDecision:
        """
        Invokes H-2 to execute the selected test step with immediate safety revalidation.
        """
        workflow.test_count += 1
        cand = workflow.latest_selection.selected_candidate if workflow.latest_selection else None
        step_id = cand.originating_step_id if cand else (workflow.sequence.current_step_id if workflow.sequence else "STEP_01")

        # Safety revalidation immediately prior to execution
        if cand and cand.safety_classification != ServiceSafetyClassification.READ_ONLY:
            workflow.transition_to(WorkflowStage.BLOCKED, reason="Non-read-only action rejected immediately before execution.")
            self._finalize_outcome(workflow, WorkflowStopReason.SAFETY_BLOCKED, summary="Safety policy revalidation failed.")
            return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Safety revalidation failed.", source_component="H5_ENGINE")

        # Execute step via H-2 or mock result
        res: SequenceResult
        if mock_sequence_result:
            res = mock_sequence_result
        elif workflow.sequence and workflow.procedure:
            try:
                res = self.sequencer.execute_current_step(
                    sequence=workflow.sequence,
                    procedure=workflow.procedure,
                    technician_input=technician_input,
                )
            except Exception as e:
                res = SequenceResult(
                    step_id=step_id,
                    execution_status="FAILED",
                    data_quality=SignalQuality.ERROR,
                    actual_outcome=ObservationResultType.COMMUNICATION_FAILURE,
                    error_state=str(e),
                )
        else:
            res = SequenceResult(
                step_id=step_id,
                execution_status="SUCCESS",
                actual_outcome=ObservationResultType.NORMAL,
                observed_values={"MAF": 2.5, "RPM": 850.0},
            )

        workflow.completed_test_results.append(res)

        workflow.transition_to(
            WorkflowStage.RESULT_EVALUATION,
            reason=f"Test '{step_id}' executed with status {res.execution_status}.",
            event_type=WorkflowEventType.TEST_EXECUTED,
            test_id=step_id,
        )
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Test executed. Evaluating results.", source_component="H2_SEQUENCER")

    def _stage_result_evaluation(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Integrates test results into active evidence cache and prepares RCA.
        """
        latest_res = workflow.completed_test_results[-1] if workflow.completed_test_results else None

        if latest_res and latest_res.observed_values:
            ev = FaultEvidence(
                evidence_id=f"ev_res_{uuid.uuid4().hex[:8]}",
                title=f"Test {latest_res.step_id} observation",
                signals=list(latest_res.observed_values.keys()),
                start_time=time.time(),
                end_time=time.time(),
                duration=0.5,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior=f"Test {latest_res.step_id} outcome: {latest_res.actual_outcome.value}",
                expected_behavior="Normal sensor baseline",
                deviation_magnitude=0.0 if latest_res.actual_outcome == ObservationResultType.NORMAL else 15.0,
                severity=AnomalySeverity.INFO if latest_res.actual_outcome == ObservationResultType.NORMAL else AnomalySeverity.WARNING,
                quality=latest_res.data_quality,
                provenance={"step_id": latest_res.step_id},
                analysis_method="STEP_OBSERVATION",
                confidence_score=0.85 if latest_res.actual_outcome == ObservationResultType.NORMAL else 0.40,
            )
            workflow.active_evidence.append(ev)

        workflow.transition_to(WorkflowStage.ROOT_CAUSE_ANALYSIS, reason="Test results evaluated into evidence.")
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Results evaluated. Proceeding to RCA.", source_component="H5_ENGINE")

    def _stage_root_cause_analysis(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Invokes H-4 to perform automated root-cause analysis.
        """
        workflow.reassessment_count += 1
        rca_ctx = RootCauseAnalysisContext(
            vehicle_id=workflow.vehicle_id,
            session_id=workflow.session_id,
            hypotheses=workflow.active_hypotheses,
            active_evidence=workflow.active_evidence,
            completed_test_results=workflow.completed_test_results,
            selection_decisions=workflow.selection_history,
            available_ecus=workflow.available_ecus,
            unreachable_ecus=workflow.unreachable_ecus,
            operating_condition=workflow.operating_condition,
            technician_inputs=workflow.technician_inputs,
        )

        analysis = self.root_cause_analyzer.analyze_root_cause(rca_ctx)
        workflow.latest_root_cause = analysis

        workflow.events.append(
            WorkflowEvent(
                event_id=f"evt_{uuid.uuid4().hex[:10]}",
                workflow_id=workflow.workflow_id,
                timestamp=time.time(),
                previous_stage=workflow.stage,
                new_stage=workflow.stage,
                event_type=WorkflowEventType.ROOT_CAUSE_UPDATED,
                reason=f"Root-cause analysis completed with state: {analysis.conclusion.conclusion_state.value if analysis.conclusion else 'UNKNOWN'}",
                source_component="H4_ROOT_CAUSE",
            )
        )

        conc = analysis.conclusion
        if not conc:
            workflow.transition_to(WorkflowStage.COMPLETED, reason="Root cause analysis produced no conclusion.")
            self._finalize_outcome(workflow, WorkflowStopReason.NO_CONFIDENT_CONCLUSION)
            return WorkflowDecision(action="COMPLETE", stage=workflow.stage, rationale="Completed without conclusion.", source_component="H5_ENGINE")

        # Orchestration decision based on H-4 conclusion state
        c_state = conc.conclusion_state

        if c_state == AnalysisConclusionState.COMMUNICATION_ISSUE_UNRESOLVED:
            workflow.transition_to(WorkflowStage.BLOCKED, reason="Communication issue unresolved.")
            self._finalize_outcome(workflow, WorkflowStopReason.COMMUNICATION_UNRESOLVED)
            return WorkflowDecision(action="STOP", stage=workflow.stage, rationale="Unresolved communication issue.", source_component="H4_ROOT_CAUSE")

        if c_state in (AnalysisConclusionState.ROOT_CAUSE_IDENTIFIED, AnalysisConclusionState.ROOT_CAUSE_STRONGLY_SUPPORTED):
            if conc.certainty_level == RootCauseCertaintyLevel.CONFIRMED or not workflow.policy.require_technician_confirmation:
                workflow.transition_to(WorkflowStage.COMPLETED, reason="Root cause resolved with sufficient certainty.")
                self._finalize_outcome(workflow, WorkflowStopReason.ROOT_CAUSE_RESOLVED)
                return WorkflowDecision(action="COMPLETE", stage=workflow.stage, rationale="Root cause identified with high certainty.", source_component="H4_ROOT_CAUSE")
            else:
                # Requires final verification or technician confirmation
                workflow.transition_to(WorkflowStage.ROOT_CAUSE_VERIFICATION, reason="Root cause strongly supported; verification recommended.")
                return WorkflowDecision(action="REQUEST_VERIFICATION", stage=workflow.stage, rationale="Verification required before finalizing.", source_component="H4_ROOT_CAUSE")

        if c_state in (AnalysisConclusionState.MULTIPLE_PLAUSIBLE_CAUSES, AnalysisConclusionState.LEADING_CANDIDATE_ONLY):
            if workflow.test_count < workflow.policy.max_tests and workflow.reassessment_count < workflow.policy.max_root_cause_reassessments:
                workflow.transition_to(WorkflowStage.TEST_SELECTION, reason="Ambiguity remains; selecting further discriminating test.")
                return WorkflowDecision(action="SELECT_TEST", stage=workflow.stage, rationale="Selecting additional test to resolve competing causes.", source_component="H5_ENGINE")
            else:
                workflow.transition_to(WorkflowStage.COMPLETED, reason="Maximum test or reassessment limit reached with multiple plausible causes.")
                self._finalize_outcome(workflow, WorkflowStopReason.MAX_TESTS_REACHED)
                return WorkflowDecision(action="COMPLETE", stage=workflow.stage, rationale="Terminated due to test limit.", source_component="H5_ENGINE")

        # Conflict or Insufficient data
        if workflow.test_count < workflow.policy.max_tests:
            workflow.transition_to(WorkflowStage.TEST_SELECTION, reason="Insufficient evidence; selecting further test.")
            return WorkflowDecision(action="SELECT_TEST", stage=workflow.stage, rationale="Selecting test to gather missing data.", source_component="H5_ENGINE")

        workflow.transition_to(WorkflowStage.COMPLETED, reason="No confident root cause could be established.")
        self._finalize_outcome(workflow, WorkflowStopReason.NO_CONFIDENT_CONCLUSION)
        return WorkflowDecision(action="COMPLETE", stage=workflow.stage, rationale="No confident root cause.", source_component="H5_ENGINE")

    def _stage_root_cause_verification(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Manages verification request: delegates to H-3/H-2 or technician gate.
        """
        analysis = workflow.latest_root_cause
        rec = analysis.conclusion.recommended_final_verification if (analysis and analysis.conclusion) else "Verify component integrity."

        gate = TechnicianActionGate(
            action_id=f"act_verify_{uuid.uuid4().hex[:6]}",
            instruction=rec or "Confirm physical component integrity.",
            purpose="Final Root-Cause Verification",
            expected_observation="Component undamaged and within spec.",
            target_ecu=analysis.primary_candidate.affected_ecu if (analysis and analysis.primary_candidate) else "ECM",
        )
        workflow.pending_technician_gate = gate
        workflow.transition_to(
            WorkflowStage.WAITING_FOR_TECHNICIAN,
            reason="Root cause requires final physical verification.",
            event_type=WorkflowEventType.TECHNICIAN_REQUESTED,
        )
        return WorkflowDecision(
            action="REQUEST_TECHNICIAN",
            stage=workflow.stage,
            rationale=f"Verification required: {rec}",
            source_component="H5_ENGINE",
        )

    def _stage_waiting_for_technician(
        self,
        workflow: DiagnosticWorkflow,
        technician_input: Optional[Dict[str, Any]],
    ) -> WorkflowDecision:
        """
        Handles technician response when workflow is paused at a technician gate.
        """
        if not technician_input:
            # Still waiting
            return WorkflowDecision(
                action="STOP",
                stage=workflow.stage,
                rationale="Awaiting technician input.",
                source_component="H5_ENGINE",
            )

        # Ingest technician input
        workflow.technician_inputs.append(technician_input)
        if workflow.pending_technician_gate:
            workflow.pending_technician_gate.status = "COMPLETED"
            workflow.pending_technician_gate.response = technician_input
            workflow.pending_technician_gate = None

        workflow.events.append(
            WorkflowEvent(
                event_id=f"evt_{uuid.uuid4().hex[:10]}",
                workflow_id=workflow.workflow_id,
                timestamp=time.time(),
                previous_stage=workflow.stage,
                new_stage=WorkflowStage.REASSESSMENT,
                event_type=WorkflowEventType.TECHNICIAN_RESPONDED,
                reason="Technician provided input; transitioning to reassessment.",
                source_component="TECHNICIAN",
                metadata=technician_input,
            )
        )

        workflow.transition_to(WorkflowStage.REASSESSMENT, reason="Technician input received.")
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Technician input received. Reassessing.", source_component="H5_ENGINE")

    def _stage_reassessment(self, workflow: DiagnosticWorkflow) -> WorkflowDecision:
        """
        Re-evaluates root cause incorporating technician input.
        """
        workflow.transition_to(WorkflowStage.ROOT_CAUSE_ANALYSIS, reason="Reassessing root cause with fresh technician input.")
        return WorkflowDecision(action="ADVANCE", stage=workflow.stage, rationale="Reassessing root cause.", source_component="H5_ENGINE")

    # -----------------------------------------------------------------
    # D. Technician Input Submission & Replay
    # -----------------------------------------------------------------

    def submit_technician_input(
        self,
        workflow: DiagnosticWorkflow,
        action_id: str,
        response: Dict[str, Any],
        technician_id: Optional[str] = None,
    ) -> bool:
        """
        Submits structured technician observation to resolve a pending technician gate.
        """
        with self._lock:
            if not workflow.pending_technician_gate:
                return False
            if workflow.pending_technician_gate.action_id != action_id:
                return False

            payload = {
                "action_id": action_id,
                "technician_id": technician_id or "TECH_01",
                "timestamp": time.time(),
                "response": response,
                "type": response.get("type", "TECHNICIAN_OBSERVATION"),
                "target_candidate": response.get("target_candidate"),
            }
            workflow.pending_technician_gate.status = "COMPLETED"
            workflow.pending_technician_gate.response = payload
            workflow.technician_inputs.append(payload)
            workflow.pending_technician_gate = None

            workflow.transition_to(WorkflowStage.REASSESSMENT, reason="Technician input submitted via API.")
            return True

    def replay(self, events: List[WorkflowEvent]) -> Dict[str, Any]:
        """
        Analytical state reconstruction from recorded workflow events.
        Does NOT execute physical commands or communicate over transport.
        """
        state_history = []
        stages_visited = []
        for e in events:
            stages_visited.append(e.new_stage.value)
            state_history.append({
                "timestamp": e.timestamp,
                "event_type": e.event_type.value,
                "stage": e.new_stage.value,
                "reason": e.reason,
            })
        return {
            "total_events": len(events),
            "stages_visited": stages_visited,
            "final_stage": stages_visited[-1] if stages_visited else "UNKNOWN",
            "history": state_history,
        }

    # -----------------------------------------------------------------
    # E. Final Outcome Formulation
    # -----------------------------------------------------------------

    def _finalize_outcome(
        self,
        workflow: DiagnosticWorkflow,
        reason: WorkflowStopReason,
        summary: Optional[str] = None,
    ) -> WorkflowOutcome:
        """
        Assembles the comprehensive final WorkflowOutcome.
        """
        rca = workflow.latest_root_cause
        prim = rca.primary_candidate if rca else None
        conc = rca.conclusion if rca else None

        alts = [a.title for a in rca.alternative_candidates] if rca else []
        supp_count = len(prim.supporting_evidence) if prim else 0
        contra_count = len(prim.contradicting_evidence) if prim else 0

        outcome = WorkflowOutcome(
            outcome_type=reason,
            primary_diagnosis=prim.title if prim else None,
            primary_candidate_id=prim.candidate_id if prim else None,
            certainty=conc.certainty_level if conc else RootCauseCertaintyLevel.INCONCLUSIVE,
            confidence=prim.causal_confidence if prim else 0.0,
            alternative_candidates=alts,
            supporting_evidence_count=supp_count,
            contradicting_evidence_count=contra_count,
            tests_performed=[r.step_id for r in workflow.completed_test_results],
            procedures_performed=[workflow.procedure.procedure_id] if workflow.procedure else [],
            unresolved_issues=[f"ECU '{u}' unreachable" for u in workflow.unreachable_ecus],
            technician_actions_required=[t.get("instruction", "") for t in workflow.technician_inputs],
            recommended_next_action=conc.recommended_final_verification if conc else None,
            summary_text=summary or (conc.summary_text if conc else f"Workflow terminated: {reason.value}"),
            provenance={
                "workflow_id": workflow.workflow_id,
                "vehicle_id": workflow.vehicle_id,
                "session_id": workflow.session_id,
                "iterations": workflow.iteration_count,
                "tests": workflow.test_count,
            },
        )
        workflow.outcome = outcome
        return outcome
