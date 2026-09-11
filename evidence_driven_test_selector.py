# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase H-3: Evidence-Driven Test Selection Engine
=============================================================================
This module implements Phase H-3 of the Seyyanen diagnostic platform.
It transforms the diagnostic system from "execute the predefined procedure"
into "determine which available diagnostic test provides the most useful
evidence for resolving the current uncertainty."

Core Architectural Invariants:
  1. SELECTION & UNCERTAINTY REDUCTION, NOT AUTONOMOUS REPAIR:
     Selects the best next test based on competing hypotheses, supporting/
     contradicting evidence, test discriminative power, feasibility, and safety.
     Does NOT perform autonomous root-cause reasoning (H-4), does NOT repair,
     and does NOT exert unrestricted ECU control.
  2. STRICT READ-ONLY & SAFE TEST SELECTION:
     Selects ONLY safe read-only acquisitions (PIDs, DIDs, DTCs) or manual
     technician verifications (visual observation, physical measurement).
     STRICTLY REJECTS & MARKS SAFETY_BLOCKED:
       - Actuator tests (0x2F)
       - ECU writes (0x2E)
       - Coding & programming (0x34/36/37)
       - Security access (0x27)
       - DTC clearing (Mode 04 / 14)
       - Destructive resets / arbitrary control routines
  3. DETERMINISTIC & EXPLAINABLE RANKING:
     100% deterministic heuristic scoring:
       Score = (DISCRIMINATIVE_POWER * RELEVANCE * QUALITY * FEASIBILITY * SAFETY) / COST
     Produces human-readable technician explanations and machine-readable score
     breakdowns. Zero LLM dependency in the decision loop.
  4. CLOSED DIAGNOSTIC INFORMATION LOOP:
     Vehicle Data -> G-3 Hypotheses -> H-1 Candidate Steps -> H-3 Test Selection
     -> H-2 Execution -> New Evidence -> H-3 Recalculate Selection.
  5. MULTI-ECU ISOLATION & GRAPH AWARENESS:
     Maintains distinct ECU identities and leverages G-5 vehicle diagnostic graph
     structural and behavioral relationships without duplicating graph data.
  6. BOUNDEDNESS & PERFORMANCE:
     Explicit caps on candidate counts, evaluation depth, and caching. Never
     enumerates combinatorial diagnostic explosions or full raw telemetry loops.
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

# Integration imports from C, D, E, F, G, H-1, and H-2 layers
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
    AdvancedServiceRequest,
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
from automated_test_sequencer import (
    SequenceState,
    StepEligibility,
    SequenceEventType,
    PreconditionStatus,
    SequenceExecutionPolicy,
    SequenceActionDescriptor,
    SequenceEvent,
    SequenceResult,
    SequenceStepExecution,
    DiagnosticSequence,
    TestExecutionAdapter,
    ReadOnlyAcquisitionAdapter,
    TechnicianObservationAdapter,
    MockTestExecutionAdapter,
    PreconditionEngine,
    AutomatedTestSequencer,
    PROHIBITED_SERVICES,
)

logger = logging.getLogger(__name__)


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class TestFeasibilityStatus(str, enum.Enum):
    """Feasibility state of a candidate diagnostic test."""
    FEASIBLE = "FEASIBLE"
    ECU_UNAVAILABLE = "ECU_UNAVAILABLE"
    MISSING_PREREQUISITES = "MISSING_PREREQUISITES"
    LOW_DATA_QUALITY = "LOW_DATA_QUALITY"
    OPERATING_CONDITION_UNAVAILABLE = "OPERATING_CONDITION_UNAVAILABLE"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    ALREADY_PERFORMED = "ALREADY_PERFORMED"
    REDUNDANT = "REDUNDANT"
    UNSUPPORTED = "UNSUPPORTED"


class UncertaintyResolutionType(str, enum.Enum):
    """Categorizes the primary goal of the selected test."""
    HYPOTHESIS_DISCRIMINATION = "HYPOTHESIS_DISCRIMINATION"  # Distinguish competing hypotheses
    CONFIRMATION_TEST = "CONFIRMATION_TEST"                  # Confirm dominant high-confidence hypothesis
    DISCONFIRMATION_TEST = "DISCONFIRMATION_TEST"            # Challenge/eliminate hypothesis
    QUALITY_IMPROVEMENT = "QUALITY_IMPROVEMENT"              # Acquire fresh/reliable data
    BROAD_EXPLORATION = "BROAD_EXPLORATION"                  # Initial exploration when confidence is low


# =====================================================================
# 2. DATA STRUCTURES & CANDIDATE MODEL
# =====================================================================

@dataclass
class DiagnosticExpectedOutcome:
    """
    Structured potential outcome of a candidate test and its impact on hypotheses.
    Does not invent statistical probabilities; specifies explicit deterministic impact.
    """
    outcome_id: str
    observation_type: ObservationResultType
    supported_hypothesis_ids: List[str] = field(default_factory=list)
    weakened_hypothesis_ids: List[str] = field(default_factory=list)
    confidence_delta: float = 0.0
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "observation_type": self.observation_type.value,
            "supported_hypothesis_ids": list(self.supported_hypothesis_ids),
            "weakened_hypothesis_ids": list(self.weakened_hypothesis_ids),
            "confidence_delta": round(self.confidence_delta, 2),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticExpectedOutcome":
        return cls(
            outcome_id=data["outcome_id"],
            observation_type=ObservationResultType(data["observation_type"]),
            supported_hypothesis_ids=data.get("supported_hypothesis_ids", []),
            weakened_hypothesis_ids=data.get("weakened_hypothesis_ids", []),
            confidence_delta=float(data.get("confidence_delta", 0.0)),
            rationale=data.get("rationale", ""),
        )


@dataclass
class DiagnosticTestCandidate:
    """
    Structured candidate diagnostic test evaluated by the H-3 selection engine.
    Wraps an executable test step, preconditions, expected outcomes, and requirements.
    """
    candidate_id: str
    title: str
    description: str
    target_ecu: str
    execution_mode: StepExecutionMode = StepExecutionMode.OBSERVATIONAL
    originating_procedure_id: Optional[str] = None
    originating_step_id: Optional[str] = None
    prerequisites: List[DiagnosticPrecondition] = field(default_factory=list)
    required_signals: List[str] = field(default_factory=list)
    required_identifiers: List[str] = field(default_factory=list)
    expected_outcomes: List[DiagnosticExpectedOutcome] = field(default_factory=list)
    target_hypotheses: List[str] = field(default_factory=list)
    discriminated_hypotheses: List[str] = field(default_factory=list)
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    service_id: Optional[str] = None
    identifier: Optional[str] = None
    estimated_duration_s: float = 10.0
    estimated_effort_cost: float = 1.0  # 1.0 = fast electronic read, 3.0 = visual, 5.0 = multimeter
    required_operating_condition: Optional[str] = None
    required_data_quality: SignalQuality = SignalQuality.GOOD
    feasibility_status: TestFeasibilityStatus = TestFeasibilityStatus.FEASIBLE
    rejection_reason: Optional[str] = None
    is_repeatable: bool = False
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "description": self.description,
            "target_ecu": self.target_ecu,
            "execution_mode": self.execution_mode.value,
            "originating_procedure_id": self.originating_procedure_id,
            "originating_step_id": self.originating_step_id,
            "prerequisites": [p.to_dict() for p in self.prerequisites],
            "required_signals": list(self.required_signals),
            "required_identifiers": list(self.required_identifiers),
            "expected_outcomes": [o.to_dict() for o in self.expected_outcomes],
            "target_hypotheses": list(self.target_hypotheses),
            "discriminated_hypotheses": list(self.discriminated_hypotheses),
            "safety_classification": self.safety_classification.value,
            "service_id": self.service_id,
            "identifier": self.identifier,
            "estimated_duration_s": round(self.estimated_duration_s, 1),
            "estimated_effort_cost": round(self.estimated_effort_cost, 2),
            "required_operating_condition": self.required_operating_condition,
            "required_data_quality": self.required_data_quality.value,
            "feasibility_status": self.feasibility_status.value,
            "rejection_reason": self.rejection_reason,
            "is_repeatable": self.is_repeatable,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticTestCandidate":
        return cls(
            candidate_id=data["candidate_id"],
            title=data["title"],
            description=data["description"],
            target_ecu=data["target_ecu"],
            execution_mode=StepExecutionMode(data.get("execution_mode", "OBSERVATIONAL")),
            originating_procedure_id=data.get("originating_procedure_id"),
            originating_step_id=data.get("originating_step_id"),
            prerequisites=[DiagnosticPrecondition.from_dict(p) for p in data.get("prerequisites", [])],
            required_signals=data.get("required_signals", []),
            required_identifiers=data.get("required_identifiers", []),
            expected_outcomes=[DiagnosticExpectedOutcome.from_dict(o) for o in data.get("expected_outcomes", [])],
            target_hypotheses=data.get("target_hypotheses", []),
            discriminated_hypotheses=data.get("discriminated_hypotheses", []),
            safety_classification=ServiceSafetyClassification(data.get("safety_classification", "READ_ONLY")),
            service_id=data.get("service_id"),
            identifier=data.get("identifier"),
            estimated_duration_s=float(data.get("estimated_duration_s", 10.0)),
            estimated_effort_cost=float(data.get("estimated_effort_cost", 1.0)),
            required_operating_condition=data.get("required_operating_condition"),
            required_data_quality=SignalQuality(data.get("required_data_quality", "GOOD")),
            feasibility_status=TestFeasibilityStatus(data.get("feasibility_status", "FEASIBLE")),
            rejection_reason=data.get("rejection_reason"),
            is_repeatable=bool(data.get("is_repeatable", False)),
            provenance=data.get("provenance", {}),
        )

    def to_h2_step_and_descriptor(self) -> Tuple[DiagnosticStep, Optional[SequenceActionDescriptor]]:
        """Converts this candidate into an H-1 DiagnosticStep and H-2 SequenceActionDescriptor."""
        branches = []
        for eo in self.expected_outcomes:
            branches.append(
                DiagnosticBranch(
                    branch_id=f"br_{eo.outcome_id}",
                    condition_outcome=eo.observation_type,
                    confidence_adjustment=eo.confidence_delta,
                    rationale=eo.rationale,
                )
            )

        step = DiagnosticStep(
            step_id=self.originating_step_id or self.candidate_id,
            sequence=1,
            title=self.title,
            technician_instruction=self.description,
            purpose=f"Test targeting hypotheses: {', '.join(self.target_hypotheses) or 'None'}",
            rationale=f"Discriminates hypotheses: {', '.join(self.discriminated_hypotheses) or 'None'}",
            target_ecu=self.target_ecu,
            execution_mode=self.execution_mode,
            preconditions=copy.deepcopy(self.prerequisites),
            branches=branches,
            safety_classification=self.safety_classification,
            target_hypotheses=list(self.target_hypotheses),
            discriminated_hypotheses=list(self.discriminated_hypotheses),
            provenance=self.provenance,
        )

        desc = None
        if self.service_id and self.identifier:
            desc = SequenceActionDescriptor(
                target_ecu=self.target_ecu,
                service_id=self.service_id,
                identifier=self.identifier,
                timeout_s=min(self.estimated_duration_s, 5.0),
                required_operating_condition=self.required_operating_condition,
            )

        return step, desc


@dataclass
class TestSelectionContext:
    """
    Environmental and diagnostic context consumed by the H-3 selection engine.
    Ingests active hypotheses, supporting/contradicting evidence, signal quality,
    ECU availability, and test execution history.
    """
    vehicle_id: str
    session_id: str
    hypotheses: List[FaultHypothesis] = field(default_factory=list)
    active_evidence: List[FaultEvidence] = field(default_factory=list)
    available_ecus: List[str] = field(default_factory=list)
    unreachable_ecus: List[str] = field(default_factory=list)
    operating_condition: str = "UNKNOWN"
    completed_test_ids: List[str] = field(default_factory=list)
    test_history: List[Dict[str, Any]] = field(default_factory=list)  # {test_id, outcome, quality, timestamp, op_cond}
    signal_cache: Dict[str, Any] = field(default_factory=dict)
    signal_qualities: Dict[str, SignalQuality] = field(default_factory=dict)
    signal_timestamps: Dict[str, float] = field(default_factory=dict)
    diagnostic_graph: Optional[DiagnosticGraph] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def primary_hypothesis(self) -> Optional[FaultHypothesis]:
        if not self.hypotheses:
            return None
        # Sort by evidence score descending
        return sorted(self.hypotheses, key=lambda h: h.evidence_score, reverse=True)[0]

    @property
    def competing_hypotheses(self) -> List[FaultHypothesis]:
        if len(self.hypotheses) <= 1:
            return []
        sorted_h = sorted(self.hypotheses, key=lambda h: h.evidence_score, reverse=True)
        return sorted_h[1:]


@dataclass
class TestSelectionScore:
    """
    Inspectable, machine-readable score components for a candidate test.
    Deterministic heuristic formula:
      Score = (DISCRIMINATION * RELEVANCE * QUALITY * FEASIBILITY * SAFETY) / (COST * REDUNDANCY)
    """
    total_score: float = 0.0
    discrimination_score: float = 0.0
    evidence_relevance_score: float = 0.0
    quality_score: float = 1.0
    feasibility_score: float = 1.0
    safety_multiplier: float = 1.0
    cost_penalty: float = 1.0
    redundancy_penalty: float = 1.0
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_score": round(self.total_score, 4),
            "discrimination_score": round(self.discrimination_score, 3),
            "evidence_relevance_score": round(self.evidence_relevance_score, 3),
            "quality_score": round(self.quality_score, 3),
            "feasibility_score": round(self.feasibility_score, 3),
            "safety_multiplier": round(self.safety_multiplier, 1),
            "cost_penalty": round(self.cost_penalty, 2),
            "redundancy_penalty": round(self.redundancy_penalty, 2),
            "explanation": self.explanation,
        }


@dataclass
class TestSelectionDecision:
    """
    Complete structured decision record produced by H-3.
    Contains the selected test, ranked candidate list, rejected candidates,
    provenance, and technician-facing explanation.
    """
    decision_id: str
    selected_candidate: Optional[DiagnosticTestCandidate]
    ranked_candidates: List[Tuple[DiagnosticTestCandidate, TestSelectionScore]] = field(default_factory=list)
    rejected_candidates: List[Tuple[DiagnosticTestCandidate, str]] = field(default_factory=list)
    target_hypotheses: List[str] = field(default_factory=list)
    expected_information_gain: float = 0.0
    decision_type: UncertaintyResolutionType = UncertaintyResolutionType.HYPOTHESIS_DISCRIMINATION
    explanation: str = ""
    timestamp: float = field(default_factory=time.time)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "selected_candidate_id": self.selected_candidate.candidate_id if self.selected_candidate else None,
            "selected_candidate": self.selected_candidate.to_dict() if self.selected_candidate else None,
            "ranked_candidates": [
                {"candidate": c.to_dict(), "score": s.to_dict()} for c, s in self.ranked_candidates
            ],
            "rejected_candidates": [
                {"candidate_id": c.candidate_id, "title": c.title, "reason": reason}
                for c, reason in self.rejected_candidates
            ],
            "target_hypotheses": list(self.target_hypotheses),
            "expected_information_gain": round(self.expected_information_gain, 3),
            "decision_type": self.decision_type.value,
            "explanation": self.explanation,
            "timestamp": round(self.timestamp, 3),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestSelectionDecision":
        sel_cand = None
        if data.get("selected_candidate"):
            sel_cand = DiagnosticTestCandidate.from_dict(data["selected_candidate"])

        ranked = []
        for item in data.get("ranked_candidates", []):
            cand = DiagnosticTestCandidate.from_dict(item["candidate"])
            sc_data = item["score"]
            score = TestSelectionScore(
                total_score=float(sc_data.get("total_score", 0.0)),
                discrimination_score=float(sc_data.get("discrimination_score", 0.0)),
                evidence_relevance_score=float(sc_data.get("evidence_relevance_score", 0.0)),
                quality_score=float(sc_data.get("quality_score", 1.0)),
                feasibility_score=float(sc_data.get("feasibility_score", 1.0)),
                safety_multiplier=float(sc_data.get("safety_multiplier", 1.0)),
                cost_penalty=float(sc_data.get("cost_penalty", 1.0)),
                redundancy_penalty=float(sc_data.get("redundancy_penalty", 1.0)),
                explanation=sc_data.get("explanation", ""),
            )
            ranked.append((cand, score))

        rejected = []
        for item in data.get("rejected_candidates", []):
            # Lightweight reconstruct of candidate for inspection
            c = DiagnosticTestCandidate(
                candidate_id=item["candidate_id"],
                title=item.get("title", ""),
                description="",
                target_ecu="UNKNOWN",
            )
            rejected.append((c, item.get("reason", "")))

        return cls(
            decision_id=data["decision_id"],
            selected_candidate=sel_cand,
            ranked_candidates=ranked,
            rejected_candidates=rejected,
            target_hypotheses=data.get("target_hypotheses", []),
            expected_information_gain=float(data.get("expected_information_gain", 0.0)),
            decision_type=UncertaintyResolutionType(data.get("decision_type", "HYPOTHESIS_DISCRIMINATION")),
            explanation=data.get("explanation", ""),
            timestamp=float(data.get("timestamp", time.time())),
            provenance=data.get("provenance", {}),
        )


# =====================================================================
# 3. EVIDENCE-DRIVEN TEST SELECTOR ENGINE
# =====================================================================

class EvidenceDrivenTestSelector:
    """
    Deterministic decision engine that selects the best next diagnostic test
    to resolve current uncertainty across competing hypotheses, evidence,
    safety, quality, and feasibility.
    """

    def __init__(
        self,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
        max_candidates: int = 50,
        data_freshness_window_s: float = 60.0,
    ):
        self.safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)
        self.max_candidates = max_candidates
        self.data_freshness_window_s = data_freshness_window_s

    # -----------------------------------------------------------------
    # A. Candidate Ingestion & Extraction
    # -----------------------------------------------------------------

    def extract_candidates_from_procedure(
        self,
        procedure: DiagnosticProcedure,
    ) -> List[DiagnosticTestCandidate]:
        """Extracts DiagnosticTestCandidate models from an H-1 DiagnosticProcedure."""
        candidates: List[DiagnosticTestCandidate] = []
        for step_id, step in procedure.steps.items():
            expected_outcomes: List[DiagnosticExpectedOutcome] = []
            for b in step.branches:
                eo = DiagnosticExpectedOutcome(
                    outcome_id=b.branch_id,
                    observation_type=b.condition_outcome,
                    supported_hypothesis_ids=list(step.target_hypotheses) if b.confidence_adjustment > 0 else [],
                    weakened_hypothesis_ids=list(step.discriminated_hypotheses) if b.confidence_adjustment > 0 else (list(step.target_hypotheses) if b.confidence_adjustment < 0 else []),
                    confidence_delta=b.confidence_adjustment,
                    rationale=b.rationale,
                )
                expected_outcomes.append(eo)

            cost = 1.0
            if step.execution_mode == StepExecutionMode.OBSERVATIONAL:
                cost = 2.0
            elif step.execution_mode == StepExecutionMode.MEASUREMENT:
                cost = 4.0

            cand = DiagnosticTestCandidate(
                candidate_id=f"cand_{step.step_id}",
                title=step.title,
                description=step.technician_instruction,
                target_ecu=step.target_ecu,
                execution_mode=step.execution_mode,
                originating_procedure_id=procedure.procedure_id,
                originating_step_id=step.step_id,
                prerequisites=copy.deepcopy(step.preconditions),
                expected_outcomes=expected_outcomes,
                target_hypotheses=list(step.target_hypotheses),
                discriminated_hypotheses=list(step.discriminated_hypotheses),
                safety_classification=step.safety_classification,
                estimated_duration_s=float(step.estimated_time_minutes or 5) * 60.0,
                estimated_effort_cost=cost,
                provenance={"procedure_id": procedure.procedure_id, "step_id": step.step_id},
            )
            candidates.append(cand)
        return candidates

    def generate_candidates_from_hypotheses(
        self,
        hypotheses: List[FaultHypothesis],
        context: Optional[TestSelectionContext] = None,
    ) -> List[DiagnosticTestCandidate]:
        """
        Generates candidate tests directly from G-3 FaultHypotheses when no static procedure is supplied.
        Does NOT invent untrusted workshop pinouts; generates bounded sensor/DTC verification candidates.
        """
        candidates: List[DiagnosticTestCandidate] = []
        for hyp in hypotheses:
            # DTC-specific verification test
            for dtc in hyp.dtc_associations:
                cand_dtc = DiagnosticTestCandidate(
                    candidate_id=f"cand_dtc_{dtc}_{hyp.hypothesis_id[:8]}",
                    title=f"Verify Active Status and Freeze Frame for DTC {dtc}",
                    description=f"Read DTC {dtc} status and associated freeze frame records to verify occurrence conditions.",
                    target_ecu="ECM",
                    execution_mode=StepExecutionMode.INFORMATIONAL,
                    service_id="03",
                    identifier=dtc,
                    target_hypotheses=[hyp.hypothesis_id],
                    estimated_duration_s=2.0,
                    estimated_effort_cost=1.0,
                    expected_outcomes=[
                        DiagnosticExpectedOutcome(
                            outcome_id="dtc_active",
                            observation_type=ObservationResultType.NORMAL,
                            supported_hypothesis_ids=[hyp.hypothesis_id],
                            confidence_delta=0.2,
                            rationale=f"DTC {dtc} confirmed active in ECU memory.",
                        ),
                        DiagnosticExpectedOutcome(
                            outcome_id="dtc_not_active",
                            observation_type=ObservationResultType.NOT_PRESENT,
                            weakened_hypothesis_ids=[hyp.hypothesis_id],
                            confidence_delta=-0.3,
                            rationale=f"DTC {dtc} not present in ECU memory.",
                        ),
                    ],
                    provenance={"source": "hypothesis_dtc", "hypothesis_id": hyp.hypothesis_id, "dtc": dtc},
                )
                candidates.append(cand_dtc)

            # Signal verification tests from supporting/contradicting evidence
            all_evidence = list(hyp.supporting_evidence) + list(hyp.contradicting_evidence)
            seen_signals = set()
            for ev in all_evidence:
                for sig in ev.signals:
                    if sig in seen_signals:
                        continue
                    seen_signals.add(sig)
                    cand_sig = DiagnosticTestCandidate(
                        candidate_id=f"cand_sig_{sig}_{hyp.hypothesis_id[:8]}",
                        title=f"Live Telemetry Acquisition: {sig}",
                        description=f"Acquire live data for signal '{sig}' during steady operational conditions.",
                        target_ecu="ECM",
                        execution_mode=StepExecutionMode.OBSERVATIONAL,
                        service_id="01",
                        identifier=sig,
                        required_signals=[sig],
                        target_hypotheses=[hyp.hypothesis_id],
                        required_operating_condition=ev.operating_condition.value if ev.operating_condition != OperatingCondition.UNKNOWN else None,
                        estimated_duration_s=5.0,
                        estimated_effort_cost=1.2,
                        expected_outcomes=[
                            DiagnosticExpectedOutcome(
                                outcome_id=f"{sig}_coherent",
                                observation_type=ObservationResultType.NORMAL,
                                weakened_hypothesis_ids=[hyp.hypothesis_id],
                                confidence_delta=-0.25,
                                rationale=f"Signal {sig} is normal and coherent.",
                            ),
                            DiagnosticExpectedOutcome(
                                outcome_id=f"{sig}_abnormal",
                                observation_type=ObservationResultType.ABNORMAL,
                                supported_hypothesis_ids=[hyp.hypothesis_id],
                                confidence_delta=0.35,
                                rationale=f"Signal {sig} exhibits anomaly supporting {hyp.title}.",
                            ),
                        ],
                        provenance={"source": "fault_evidence", "evidence_id": ev.evidence_id, "signal": sig},
                    )
                    candidates.append(cand_sig)

        return candidates

    # -----------------------------------------------------------------
    # B. Feasibility & Safety Evaluation
    # -----------------------------------------------------------------

    def evaluate_candidate_feasibility(
        self,
        candidate: DiagnosticTestCandidate,
        context: TestSelectionContext,
    ) -> Tuple[TestFeasibilityStatus, Optional[str]]:
        """
        Evaluates whether a candidate test is physically, electronically, and logically feasible right now.
        Enforces strict safety, ECU reachability, preconditions, operating conditions, and history.
        """
        # 1. Strict Safety Check (Safety Dominance)
        if candidate.safety_classification != ServiceSafetyClassification.READ_ONLY:
            return TestFeasibilityStatus.SAFETY_BLOCKED, (
                f"Safety violation: classification '{candidate.safety_classification.value}' is not READ_ONLY."
            )

        if candidate.service_id and candidate.service_id.strip().upper() in PROHIBITED_SERVICES:
            return TestFeasibilityStatus.SAFETY_BLOCKED, (
                f"Safety violation: service 0x{candidate.service_id} is prohibited."
            )

        if candidate.execution_mode == StepExecutionMode.ACTIVE_DIAGNOSTIC:
            return TestFeasibilityStatus.SAFETY_BLOCKED, "ACTIVE_DIAGNOSTIC is strictly prohibited."

        # Verify through G-1 safety policy
        if candidate.service_id:
            req = AdvancedServiceRequest(
                service_id=candidate.service_id,
                payload=candidate.identifier or "",
                target_ecu=candidate.target_ecu,
                safety_classification=ServiceSafetyClassification.READ_ONLY,
            )
            safe, reason = self.safety_policy.validate_request(req)
            if not safe:
                return TestFeasibilityStatus.SAFETY_BLOCKED, f"Safety policy blocked request: {reason}"

        # 2. ECU Availability Check
        if candidate.target_ecu in context.unreachable_ecus:
            return TestFeasibilityStatus.ECU_UNAVAILABLE, (
                f"Target ECU '{candidate.target_ecu}' is currently unreachable."
            )

        if context.available_ecus and candidate.target_ecu not in context.available_ecus:
            return TestFeasibilityStatus.ECU_UNAVAILABLE, (
                f"Target ECU '{candidate.target_ecu}' is not in available ECUs list."
            )

        # 3. Already Performed Check (Test History)
        if candidate.candidate_id in context.completed_test_ids or (
            candidate.originating_step_id and candidate.originating_step_id in context.completed_test_ids
        ):
            if not candidate.is_repeatable:
                return TestFeasibilityStatus.ALREADY_PERFORMED, (
                    f"Test '{candidate.candidate_id}' has already been performed successfully."
                )

        # 4. Operating Condition Check
        if candidate.required_operating_condition:
            req_cond = candidate.required_operating_condition.strip().upper()
            curr_cond = context.operating_condition.strip().upper()
            if req_cond != "UNKNOWN" and curr_cond != "UNKNOWN" and req_cond != curr_cond:
                return TestFeasibilityStatus.OPERATING_CONDITION_UNAVAILABLE, (
                    f"Operating condition mismatch: requires '{req_cond}', current is '{curr_cond}'."
                )

        # 5. Signal Data Quality Check
        if candidate.required_signals:
            for sig in candidate.required_signals:
                if sig in context.signal_qualities:
                    q = context.signal_qualities[sig]
                    if q in (SignalQuality.INVALID, SignalQuality.ERROR):
                        return TestFeasibilityStatus.LOW_DATA_QUALITY, (
                            f"Signal '{sig}' data quality is {q.value}."
                        )
                # Check freshness
                if sig in context.signal_timestamps:
                    age = time.time() - context.signal_timestamps[sig]
                    if age > self.data_freshness_window_s and candidate.required_data_quality == SignalQuality.GOOD:
                        return TestFeasibilityStatus.LOW_DATA_QUALITY, (
                            f"Signal '{sig}' data is stale (age: {age:.1f}s)."
                        )

        return TestFeasibilityStatus.FEASIBLE, None

    # -----------------------------------------------------------------
    # C. Deterministic Discriminative Scoring
    # -----------------------------------------------------------------

    def score_candidate(
        self,
        candidate: DiagnosticTestCandidate,
        context: TestSelectionContext,
    ) -> TestSelectionScore:
        """
        Calculates deterministic discriminative score for a candidate test.
        Formula:
          Score = (DISCRIMINATION * RELEVANCE * QUALITY * FEASIBILITY * SAFETY) / (COST * REDUNDANCY)
        """
        # Step 1: Feasibility and Safety Gate
        status, reason = self.evaluate_candidate_feasibility(candidate, context)
        candidate.feasibility_status = status
        candidate.rejection_reason = reason

        if status == TestFeasibilityStatus.SAFETY_BLOCKED:
            return TestSelectionScore(
                total_score=0.0,
                safety_multiplier=0.0,
                explanation=f"Safety blocked: {reason}",
            )

        if status in (
            TestFeasibilityStatus.ECU_UNAVAILABLE,
            TestFeasibilityStatus.MISSING_PREREQUISITES,
            TestFeasibilityStatus.ALREADY_PERFORMED,
            TestFeasibilityStatus.OPERATING_CONDITION_UNAVAILABLE,
        ):
            return TestSelectionScore(
                total_score=0.0,
                feasibility_score=0.0,
                explanation=f"Infeasible: {reason}",
            )

        # Step 2: Discriminative Power Calculation
        # A test is highly discriminative if it supports one hypothesis while weakening another.
        discrimination_score = 0.5  # baseline
        affected_hypotheses = set(candidate.target_hypotheses) | set(candidate.discriminated_hypotheses)

        competing_ids = {h.hypothesis_id for h in context.competing_hypotheses}
        primary_id = context.primary_hypothesis.hypothesis_id if context.primary_hypothesis else None

        for outcome in candidate.expected_outcomes:
            supp = set(outcome.supported_hypothesis_ids)
            weak = set(outcome.weakened_hypothesis_ids)
            affected_hypotheses.update(supp | weak)

            # High discriminative bonus if outcome separates primary from competing
            if primary_id and primary_id in supp and any(c in weak for c in competing_ids):
                discrimination_score += 1.5
            elif primary_id and primary_id in weak and any(c in supp for c in competing_ids):
                discrimination_score += 1.5
            elif len(supp) > 0 and len(weak) > 0:
                discrimination_score += 0.8

        # Bonus if candidate explicitly declares discriminated hypotheses
        if candidate.discriminated_hypotheses:
            discrimination_score += 0.5 * len(candidate.discriminated_hypotheses)

        # Step 3: Evidence Relevance & Contradiction Resolution
        relevance_score = 1.0
        # Check if candidate investigates existing contradictory evidence
        for ev in context.active_evidence:
            if ev.contradicting_observations and any(s in candidate.required_signals for s in ev.signals):
                relevance_score += 1.2  # high priority to resolve contradictions

        # Boost if candidate addresses primary hypothesis
        if primary_id and primary_id in candidate.target_hypotheses:
            relevance_score += 0.8

        # Cross-ECU discrimination boost via G-5 DiagnosticGraph
        if context.diagnostic_graph and len(context.available_ecus) > 1:
            # Check if this candidate involves an ECU that has structural edges to other ECUs
            ecu_node = make_ecu_node_id(candidate.target_ecu)
            if ecu_node in context.diagnostic_graph.nodes:
                relevance_score += 0.3

        # Step 4: Quality Score
        quality_score = 1.0
        if candidate.required_signals:
            for sig in candidate.required_signals:
                q = context.signal_qualities.get(sig, SignalQuality.GOOD)
                if q == SignalQuality.SUSPECT:
                    quality_score *= 0.7
                elif q == SignalQuality.STALE:
                    quality_score *= 0.5

        # Step 5: Feasibility Score
        feasibility_score = 1.0
        if status == TestFeasibilityStatus.LOW_DATA_QUALITY:
            feasibility_score = 0.3

        # Step 6: Cost Penalty (duration and effort)
        # Bounded effort cost: 1.0 (electronic read) to 5.0 (multimeter probe)
        effort = max(1.0, min(candidate.estimated_effort_cost, 10.0))
        duration_factor = 1.0 + (min(candidate.estimated_duration_s, 300.0) / 60.0) * 0.2
        cost_penalty = effort * duration_factor

        # Step 7: Redundancy Penalty
        redundancy_penalty = 1.0
        for th in context.test_history:
            if th.get("target_ecu") == candidate.target_ecu and th.get("signal") in candidate.required_signals:
                if th.get("operating_condition") == context.operating_condition:
                    redundancy_penalty += 1.5

        # Calculate Total Deterministic Score
        numerator = (
            discrimination_score
            * relevance_score
            * quality_score
            * feasibility_score
            * 1.0  # safety is verified 1.0
        )
        denominator = cost_penalty * redundancy_penalty
        total_score = numerator / max(0.1, denominator)

        explanation = (
            f"Discrimination: {discrimination_score:.2f}, Relevance: {relevance_score:.2f}, "
            f"Quality: {quality_score:.2f}, Cost: {cost_penalty:.2f}, Redundancy: {redundancy_penalty:.2f}"
        )

        return TestSelectionScore(
            total_score=total_score,
            discrimination_score=discrimination_score,
            evidence_relevance_score=relevance_score,
            quality_score=quality_score,
            feasibility_score=feasibility_score,
            safety_multiplier=1.0,
            cost_penalty=cost_penalty,
            redundancy_penalty=redundancy_penalty,
            explanation=explanation,
        )

    # -----------------------------------------------------------------
    # D. Selection Decision & Deterministic Tie-Breaking
    # -----------------------------------------------------------------

    def select_next_test(
        self,
        context: TestSelectionContext,
        candidate_pool: Optional[List[DiagnosticTestCandidate]] = None,
    ) -> TestSelectionDecision:
        """
        Evaluates candidate tests and selects the single best next diagnostic test.
        Deterministic tie-breaking:
          1. Safety status
          2. Feasibility status
          3. Total score (discriminative power)
          4. Lower cost
          5. Fewer manual technician requirements
          6. Stable candidate_id lexicographical order
        """
        # Step 1: Gather Candidates
        candidates = list(candidate_pool or [])
        if not candidates:
            # Generate from hypotheses if pool empty
            candidates = self.generate_candidates_from_hypotheses(context.hypotheses, context)

        # Enforce maximum candidate bound
        if len(candidates) > self.max_candidates:
            candidates = candidates[:self.max_candidates]

        ranked_candidates: List[Tuple[DiagnosticTestCandidate, TestSelectionScore]] = []
        rejected_candidates: List[Tuple[DiagnosticTestCandidate, str]] = []

        # Step 2: Score All Candidates
        for cand in candidates:
            score = self.score_candidate(cand, context)
            if cand.feasibility_status == TestFeasibilityStatus.FEASIBLE and score.total_score > 0.0:
                ranked_candidates.append((cand, score))
            else:
                rejected_candidates.append((cand, cand.rejection_reason or cand.feasibility_status.value))

        # Step 3: Deterministic Sorting & Tie-Breaking
        def tie_break_key(item: Tuple[DiagnosticTestCandidate, TestSelectionScore]):
            c, s = item
            # Sort keys:
            # 1. total_score descending
            # 2. discrimination_score descending
            # 3. effort_cost ascending (lower effort preferred)
            # 4. execution_mode (INFORMATIONAL/OBSERVATIONAL preferred over MEASUREMENT)
            # 5. candidate_id ascending (stable lexicographical tie-break)
            mode_weight = 0 if c.execution_mode != StepExecutionMode.MEASUREMENT else 1
            return (
                -round(s.total_score, 5),
                -round(s.discrimination_score, 3),
                round(c.estimated_effort_cost, 2),
                mode_weight,
                c.candidate_id,
            )

        ranked_candidates.sort(key=tie_break_key)

        # Step 4: Determine Decision Type & Build Result
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        now = time.time()

        if not ranked_candidates:
            # No feasible test available
            reason = "No candidate test is feasible or safe under current vehicle/ECU conditions."
            if rejected_candidates:
                reasons_set = {r for _, r in rejected_candidates}
                reason = f"All {len(rejected_candidates)} candidate tests rejected: {'; '.join(reasons_set)}."

            return TestSelectionDecision(
                decision_id=decision_id,
                selected_candidate=None,
                ranked_candidates=[],
                rejected_candidates=rejected_candidates,
                target_hypotheses=[h.hypothesis_id for h in context.hypotheses],
                expected_information_gain=0.0,
                decision_type=UncertaintyResolutionType.BROAD_EXPLORATION,
                explanation=f"NO_FEASIBLE_TEST: {reason}",
                timestamp=now,
                provenance={"rule": "no_feasible_test_found", "context_session": context.session_id},
            )

        selected_candidate, best_score = ranked_candidates[0]

        # Classify decision type based on context uncertainty
        decision_type = UncertaintyResolutionType.HYPOTHESIS_DISCRIMINATION
        if context.primary_hypothesis:
            if not context.competing_hypotheses:
                decision_type = UncertaintyResolutionType.CONFIRMATION_TEST
            elif context.primary_hypothesis.evidence_score >= 0.9 and all(h.evidence_score < 0.4 for h in context.competing_hypotheses):
                decision_type = UncertaintyResolutionType.CONFIRMATION_TEST
            else:
                decision_type = UncertaintyResolutionType.HYPOTHESIS_DISCRIMINATION
        elif not context.hypotheses:
            decision_type = UncertaintyResolutionType.BROAD_EXPLORATION

        # Build technician explanation
        technician_explanation = self._build_technician_explanation(
            selected_candidate, best_score, context, len(ranked_candidates)
        )

        return TestSelectionDecision(
            decision_id=decision_id,
            selected_candidate=selected_candidate,
            ranked_candidates=ranked_candidates,
            rejected_candidates=rejected_candidates,
            target_hypotheses=list(selected_candidate.target_hypotheses),
            expected_information_gain=best_score.discrimination_score,
            decision_type=decision_type,
            explanation=technician_explanation,
            timestamp=now,
            provenance={
                "selector_version": "1.0.0",
                "candidate_count": len(candidates),
                "feasible_count": len(ranked_candidates),
                "rejected_count": len(rejected_candidates),
                "top_score": best_score.total_score,
            },
        )

    # -----------------------------------------------------------------
    # E. Closed Feedback Loop Integration
    # -----------------------------------------------------------------

    def consume_test_result(
        self,
        context: TestSelectionContext,
        candidate: DiagnosticTestCandidate,
        result: SequenceResult,
    ) -> None:
        """
        Consumes the execution outcome from H-2 and updates the diagnostic selection context.
        Closes the diagnostic feedback loop.
        Does NOT rewrite original G-3 analytical models; updates active context test history.
        """
        # 1. Update completed tests list
        if candidate.candidate_id not in context.completed_test_ids:
            context.completed_test_ids.append(candidate.candidate_id)
        if candidate.originating_step_id and candidate.originating_step_id not in context.completed_test_ids:
            context.completed_test_ids.append(candidate.originating_step_id)

        # 2. Append to test history
        context.test_history.append({
            "candidate_id": candidate.candidate_id,
            "target_ecu": candidate.target_ecu,
            "signals": list(candidate.required_signals),
            "execution_status": result.execution_status,
            "actual_outcome": result.actual_outcome.value,
            "observed_values": dict(result.observed_values),
            "operating_condition": context.operating_condition,
            "timestamp": result.timestamp,
        })

        # 3. Match expected outcome to update hypothesis confidence deltas
        for eo in candidate.expected_outcomes:
            if eo.observation_type == result.actual_outcome:
                for hyp_id in eo.supported_hypothesis_ids:
                    for h in context.hypotheses:
                        if h.hypothesis_id == hyp_id:
                            h.evidence_score = round(min(1.0, h.evidence_score + eo.confidence_delta), 3)
                for hyp_id in eo.weakened_hypothesis_ids:
                    for h in context.hypotheses:
                        if h.hypothesis_id == hyp_id:
                            h.evidence_score = round(max(0.0, h.evidence_score - eo.confidence_delta), 3)

    # -----------------------------------------------------------------
    # F. Explanation Generator
    # -----------------------------------------------------------------

    def _build_technician_explanation(
        self,
        candidate: DiagnosticTestCandidate,
        score: TestSelectionScore,
        context: TestSelectionContext,
        total_feasible: int,
    ) -> str:
        """Generates a clear, jargon-free technician-facing explanation."""
        disc_text = ""
        if candidate.discriminated_hypotheses:
            disc_text = f" It directly discriminates between competing hypotheses ({', '.join(candidate.discriminated_hypotheses)})."
        elif candidate.target_hypotheses:
            disc_text = f" It provides high-relevance evidence for hypothesis '{candidate.target_hypotheses[0]}'."

        effort_desc = "electronic read-only query" if candidate.estimated_effort_cost <= 1.5 else (
            "visual inspection" if candidate.estimated_effort_cost <= 3.0 else "physical measurement"
        )

        return (
            f"Selected '{candidate.title}' on {candidate.target_ecu} as the optimal next test out of {total_feasible} "
            f"evaluated candidates.{disc_text} Feasibility is verified, data quality is reliable, and the test requires "
            f"only a low-effort {effort_desc} (~{int(candidate.estimated_duration_s)}s)."
        )
