# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase H-4: Automated Root-Cause Analysis Engine
=============================================================================
This module implements Phase H-4 of the Seyyanen diagnostic platform.
It integrates accumulated diagnostic evidence, anomalies, hypotheses, and
test outcomes from Phases G-3, G-5, H-1, H-2, and H-3 into an explainable,
evidence-backed automated root-cause assessment.

Core Architectural Invariants:
  1. CORRELATION != CAUSATION:
     Never infers causality solely from co-occurrence, shared timestamps,
     DTC presence, or graph adjacency. Causal confidence requires mechanistic
     consistency, temporal precedence, cross-sensor agreement, and targeted
     discriminating test results.
  2. DTCS ARE EVIDENCE, NOT PROOF:
     DTCs support hypotheses, but sensor physics, live telemetry, and direct
     contradictions take precedence over static trouble codes. DTC-free root
     causes are fully supported.
  3. COMMUNICATION FAULT != COMPONENT FAILURE:
     An unreachable ECU or bus timeout is strictly classified as an unresolved
     communication/network issue, never as a defective physical component
     without independent physical evidence.
  4. PRIMARY VS CONTRIBUTING VS SECONDARY CLASSIFICATION:
     Explicitly distinguishes primary root causes from contributing factors,
     secondary symptoms (e.g. misfire secondary to severe lean condition), and
     correlated observations.
  5. DETERMINISTIC & EXPLAINABLE REASONING:
     100% deterministic offline scoring and causal reasoning trace. Produces
     transparent technician-readable explanations and machine-readable score
     decompositions. Zero LLM dependency in the decision loop.
  6. BOUNDEDNESS & SAFETY:
     Zero actuator tests (0x2F), zero writes (0x2E), zero programming (0x34/36/37),
     zero security bypass (0x27), zero DTC clear (Mode 04/14), zero autonomous
     repair. All reasoning is strictly analytical over bounded candidate sets.
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
    ProcedureState,
    StepExecutionMode,
    StepPriority,
    ObservationResultType,
    ProcedureOutcome,
    DiagnosticStep,
    DiagnosticProcedureContext,
    DiagnosticProcedure,
)
from automated_test_sequencer import (
    SequenceState,
    StepEligibility,
    SequenceEventType,
    SequenceResult,
    DiagnosticSequence,
)
from evidence_driven_test_selector import (
    DiagnosticTestCandidate,
    TestSelectionContext,
    TestSelectionDecision,
    UncertaintyResolutionType,
)

logger = logging.getLogger(__name__)


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class RootCauseCandidateStatus(str, enum.Enum):
    """Lifecycle status of an evaluated root-cause candidate."""
    POSSIBLE = "POSSIBLE"
    PLAUSIBLE = "PLAUSIBLE"
    LEADING = "LEADING"
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    UNRESOLVED = "UNRESOLVED"
    WEAKENED = "WEAKENED"
    RULED_OUT = "RULED_OUT"


class CausalBasis(str, enum.Enum):
    """Underlying basis justifying a causal attribution."""
    DIRECT_MECHANISTIC_EVIDENCE = "DIRECT_MECHANISTIC_EVIDENCE"
    REPEATED_TEMPORAL_EVIDENCE = "REPEATED_TEMPORAL_EVIDENCE"
    CONTROLLED_OBSERVATIONAL_SUPPORT = "CONTROLLED_OBSERVATIONAL_SUPPORT"
    CROSS_SENSOR_CONSISTENCY = "CROSS_SENSOR_CONSISTENCY"
    CROSS_ECU_CONSISTENCY = "CROSS_ECU_CONSISTENCY"
    HYPOTHESIS_TEST_SUPPORT = "HYPOTHESIS_TEST_SUPPORT"
    INDIRECT_EVIDENCE = "INDIRECT_EVIDENCE"
    CORRELATIONAL_ONLY = "CORRELATIONAL_ONLY"
    INSUFFICIENT = "INSUFFICIENT"
    CONFIRMED = "CONFIRMED"


class CausalRole(str, enum.Enum):
    """Diagnostic role of a candidate within the causal chain."""
    PRIMARY_ROOT_CAUSE = "PRIMARY_ROOT_CAUSE"
    CONTRIBUTING_FACTOR = "CONTRIBUTING_FACTOR"
    SECONDARY_EFFECT = "SECONDARY_EFFECT"
    CORRELATED_OBSERVATION = "CORRELATED_OBSERVATION"
    UNRELATED_FINDING = "UNRELATED_FINDING"
    COMMUNICATION_ARTIFACT = "COMMUNICATION_ARTIFACT"
    SYMPTOM = "SYMPTOM"
    DOWNSTREAM_CONSEQUENCE = "DOWNSTREAM_CONSEQUENCE"
    UNKNOWN = "UNKNOWN"


class RootCauseCertaintyLevel(str, enum.Enum):
    """Calibrated certainty level of root cause determination."""
    CONFIRMED = "CONFIRMED"            # Physical test or direct observation confirmed
    HIGH_CERTAINTY = "HIGH_CERTAINTY"  # Multiple independent sensors + targeted tests agree
    MODERATE_CERTAINTY = "MODERATE_CERTAINTY"  # Strong evidence but minor alternatives remain
    LOW_CERTAINTY = "LOW_CERTAINTY"    # Correlational or single sensor only
    INCONCLUSIVE = "INCONCLUSIVE"      # Insufficient evidence or conflicting findings


class AnalysisConclusionState(str, enum.Enum):
    """Structured conclusion reached at the completion of root cause analysis."""
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    ROOT_CAUSE_STRONGLY_SUPPORTED = "ROOT_CAUSE_STRONGLY_SUPPORTED"
    LEADING_CANDIDATE_ONLY = "LEADING_CANDIDATE_ONLY"
    MULTIPLE_PLAUSIBLE_CAUSES = "MULTIPLE_PLAUSIBLE_CAUSES"
    CONFLICTED_EVIDENCE = "CONFLICTED_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    COMMUNICATION_ISSUE_UNRESOLVED = "COMMUNICATION_ISSUE_UNRESOLVED"
    REQUIRES_MANUAL_VERIFICATION = "REQUIRES_MANUAL_VERIFICATION"
    NO_CONFIDENT_ROOT_CAUSE = "NO_CONFIDENT_ROOT_CAUSE"


# =====================================================================
# 2. EVIDENCE & CANDIDATE MODELS
# =====================================================================

@dataclass
class CauseEvidenceReference:
    """
    Structured reference to an underlying evidence item with de-duplication fingerprint.
    Prevents double-counting identical physical observations.
    """
    evidence_id: str
    source_type: str                   # "G3_EVIDENCE", "H2_TEST_RESULT", "ANOMALY", "DTC"
    signals: List[str] = field(default_factory=list)
    target_ecu: str = "ECM"
    quality: SignalQuality = SignalQuality.GOOD
    is_direct: bool = True
    weight: float = 1.0
    summary: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint representing the underlying physical observation."""
        sigs = ",".join(sorted(s.upper() for s in self.signals))
        return f"{self.target_ecu.upper()}:{sigs}:{self.summary[:30]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "signals": list(self.signals),
            "target_ecu": self.target_ecu,
            "quality": self.quality.value,
            "is_direct": self.is_direct,
            "weight": round(self.weight, 2),
            "summary": self.summary,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CauseEvidenceReference":
        return cls(
            evidence_id=data["evidence_id"],
            source_type=data["source_type"],
            signals=data.get("signals", []),
            target_ecu=data.get("target_ecu", "ECM"),
            quality=SignalQuality(data.get("quality", "GOOD")),
            is_direct=bool(data.get("is_direct", True)),
            weight=float(data.get("weight", 1.0)),
            summary=data.get("summary", ""),
            provenance=data.get("provenance", {}),
        )


@dataclass
class RootCauseCandidate:
    """
    Evaluated root-cause candidate with transparent score decomposition,
    supporting/contradicting evidence, causal basis, and reasoning trace.
    """
    candidate_id: str
    title: str
    description: str
    affected_ecu: str
    affected_component: Optional[str] = None
    category: str = "AIR_FUEL"
    causal_role: CausalRole = CausalRole.PRIMARY_ROOT_CAUSE
    status: RootCauseCandidateStatus = RootCauseCandidateStatus.POSSIBLE
    causal_basis: CausalBasis = CausalBasis.CORRELATIONAL_ONLY
    source_hypotheses: List[str] = field(default_factory=list)
    source_dtcs: List[str] = field(default_factory=list)
    supporting_evidence: List[CauseEvidenceReference] = field(default_factory=list)
    contradicting_evidence: List[CauseEvidenceReference] = field(default_factory=list)
    supporting_test_results: List[Dict[str, Any]] = field(default_factory=list)
    contradicting_test_results: List[Dict[str, Any]] = field(default_factory=list)
    confidence_score: float = 0.0
    causal_confidence: float = 0.0

    # Score breakdown components
    support_score: float = 0.0
    contradiction_score: float = 0.0
    test_confirmation_score: float = 0.0
    cross_sensor_score: float = 0.0
    cross_ecu_score: float = 0.0
    quality_penalty: float = 0.0

    reasoning_trace: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "description": self.description,
            "affected_ecu": self.affected_ecu,
            "affected_component": self.affected_component,
            "category": self.category,
            "causal_role": self.causal_role.value,
            "status": self.status.value,
            "causal_basis": self.causal_basis.value,
            "source_hypotheses": list(self.source_hypotheses),
            "source_dtcs": list(self.source_dtcs),
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "contradicting_evidence": [e.to_dict() for e in self.contradicting_evidence],
            "supporting_test_results": list(self.supporting_test_results),
            "contradicting_test_results": list(self.contradicting_test_results),
            "confidence_score": round(self.confidence_score, 3),
            "causal_confidence": round(self.causal_confidence, 3),
            "score_breakdown": {
                "support_score": round(self.support_score, 3),
                "contradiction_score": round(self.contradiction_score, 3),
                "test_confirmation_score": round(self.test_confirmation_score, 3),
                "cross_sensor_score": round(self.cross_sensor_score, 3),
                "cross_ecu_score": round(self.cross_ecu_score, 3),
                "quality_penalty": round(self.quality_penalty, 3),
            },
            "reasoning_trace": list(self.reasoning_trace),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseCandidate":
        breakdown = data.get("score_breakdown", {})
        return cls(
            candidate_id=data["candidate_id"],
            title=data["title"],
            description=data["description"],
            affected_ecu=data["affected_ecu"],
            affected_component=data.get("affected_component"),
            category=data.get("category", "AIR_FUEL"),
            causal_role=CausalRole(data.get("causal_role", "PRIMARY_ROOT_CAUSE")),
            status=RootCauseCandidateStatus(data.get("status", "POSSIBLE")),
            causal_basis=CausalBasis(data.get("causal_basis", "CORRELATIONAL_ONLY")),
            source_hypotheses=data.get("source_hypotheses", []),
            source_dtcs=data.get("source_dtcs", []),
            supporting_evidence=[CauseEvidenceReference.from_dict(e) for e in data.get("supporting_evidence", [])],
            contradicting_evidence=[CauseEvidenceReference.from_dict(e) for e in data.get("contradicting_evidence", [])],
            supporting_test_results=data.get("supporting_test_results", []),
            contradicting_test_results=data.get("contradicting_test_results", []),
            confidence_score=float(data.get("confidence_score", 0.0)),
            causal_confidence=float(data.get("causal_confidence", 0.0)),
            support_score=float(breakdown.get("support_score", 0.0)),
            contradiction_score=float(breakdown.get("contradiction_score", 0.0)),
            test_confirmation_score=float(breakdown.get("test_confirmation_score", 0.0)),
            cross_sensor_score=float(breakdown.get("cross_sensor_score", 0.0)),
            cross_ecu_score=float(breakdown.get("cross_ecu_score", 0.0)),
            quality_penalty=float(breakdown.get("quality_penalty", 0.0)),
            reasoning_trace=data.get("reasoning_trace", []),
            provenance=data.get("provenance", {}),
        )


@dataclass
class RootCauseConclusion:
    """Structured summary conclusion of the root-cause assessment."""
    conclusion_state: AnalysisConclusionState
    primary_candidate_id: Optional[str]
    certainty_level: RootCauseCertaintyLevel
    summary_text: str
    recommended_final_verification: Optional[str] = None
    technician_override: Optional[Dict[str, Any]] = None
    post_repair_verification: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conclusion_state": self.conclusion_state.value,
            "primary_candidate_id": self.primary_candidate_id,
            "certainty_level": self.certainty_level.value,
            "summary_text": self.summary_text,
            "recommended_final_verification": self.recommended_final_verification,
            "technician_override": self.technician_override,
            "post_repair_verification": self.post_repair_verification,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseConclusion":
        return cls(
            conclusion_state=AnalysisConclusionState(data["conclusion_state"]),
            primary_candidate_id=data.get("primary_candidate_id"),
            certainty_level=RootCauseCertaintyLevel(data.get("certainty_level", "INCONCLUSIVE")),
            summary_text=data.get("summary_text", ""),
            recommended_final_verification=data.get("recommended_final_verification"),
            technician_override=data.get("technician_override"),
            post_repair_verification=data.get("post_repair_verification"),
        )


@dataclass
class RootCauseAnalysisContext:
    """Diagnostic environment and evidence context consumed by H-4."""
    vehicle_id: str
    session_id: str
    hypotheses: List[FaultHypothesis] = field(default_factory=list)
    active_evidence: List[FaultEvidence] = field(default_factory=list)
    completed_test_results: List[SequenceResult] = field(default_factory=list)
    selection_decisions: List[TestSelectionDecision] = field(default_factory=list)
    available_ecus: List[str] = field(default_factory=list)
    unreachable_ecus: List[str] = field(default_factory=list)
    operating_condition: str = "UNKNOWN"
    diagnostic_graph: Optional[DiagnosticGraph] = None
    technician_inputs: List[Dict[str, Any]] = field(default_factory=list)
    vehicle_context: Optional[VehicleContext] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RootCauseAnalysis:
    """
    Root serializable container for a complete Phase H-4 Root-Cause Analysis.
    Preserves primary candidate, alternative candidates, contributing factors,
    ruled-out candidates, conclusion, and reasoning trace.
    """
    analysis_id: str
    vehicle_id: str
    session_id: str
    timestamp: float
    primary_candidate: Optional[RootCauseCandidate]
    alternative_candidates: List[RootCauseCandidate] = field(default_factory=list)
    contributing_factors: List[RootCauseCandidate] = field(default_factory=list)
    ruled_out_candidates: List[RootCauseCandidate] = field(default_factory=list)
    conclusion: Optional[RootCauseConclusion] = None
    reasoning_trace: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "vehicle_id": self.vehicle_id,
            "session_id": self.session_id,
            "timestamp": round(self.timestamp, 3),
            "primary_candidate": self.primary_candidate.to_dict() if self.primary_candidate else None,
            "alternative_candidates": [c.to_dict() for c in self.alternative_candidates],
            "contributing_factors": [c.to_dict() for c in self.contributing_factors],
            "ruled_out_candidates": [c.to_dict() for c in self.ruled_out_candidates],
            "conclusion": self.conclusion.to_dict() if self.conclusion else None,
            "reasoning_trace": list(self.reasoning_trace),
            "provenance": self.provenance,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseAnalysis":
        prim = RootCauseCandidate.from_dict(data["primary_candidate"]) if data.get("primary_candidate") else None
        alts = [RootCauseCandidate.from_dict(c) for c in data.get("alternative_candidates", [])]
        contrib = [RootCauseCandidate.from_dict(c) for c in data.get("contributing_factors", [])]
        ruled = [RootCauseCandidate.from_dict(c) for c in data.get("ruled_out_candidates", [])]
        conc = RootCauseConclusion.from_dict(data["conclusion"]) if data.get("conclusion") else None

        return cls(
            analysis_id=data["analysis_id"],
            vehicle_id=data["vehicle_id"],
            session_id=data["session_id"],
            timestamp=float(data.get("timestamp", time.time())),
            primary_candidate=prim,
            alternative_candidates=alts,
            contributing_factors=contrib,
            ruled_out_candidates=ruled,
            conclusion=conc,
            reasoning_trace=data.get("reasoning_trace", []),
            provenance=data.get("provenance", {}),
            version=data.get("version", "1.0.0"),
        )


# =====================================================================
# 3. AUTOMATED ROOT-CAUSE ANALYZER ENGINE
# =====================================================================

class AutomatedRootCauseAnalyzer:
    """
    Deterministic causal reasoning and evidence integration engine.
    Analyzes hypotheses, multi-ECU telemetry, discriminating test outcomes,
    and contradictions to produce a structured root-cause assessment.
    """

    def __init__(
        self,
        max_candidates: int = 25,
        max_causal_depth: int = 5,
        max_evidence_traversal: int = 100,
    ):
        self.max_candidates = max_candidates
        self.max_causal_depth = max_causal_depth
        self.max_evidence_traversal = max_evidence_traversal

    # -----------------------------------------------------------------
    # A. Candidate Generation from Hypotheses & Evidence
    # -----------------------------------------------------------------

    def generate_candidates(
        self,
        context: RootCauseAnalysisContext,
    ) -> List[RootCauseCandidate]:
        """
        Derives root-cause candidates from G-3 FaultHypotheses and active evidence.
        Does NOT invent untrusted workshop pinouts or arbitrary text causes.
        """
        candidates: List[RootCauseCandidate] = []
        seen_fingerprints: Set[str] = set()

        # 1. Candidate generation from G-3 Hypotheses
        for hyp in context.hypotheses:
            # Determine canonical component and ECU
            ecu = "ECM"
            if hyp.affected_system in ("TRANSMISSION", "TCM"):
                ecu = "TCM"
            elif hyp.affected_system in ("BRAKE", "ABS", "WHEEL_SPEED"):
                ecu = "ABS"
            elif hyp.affected_system in ("CAN_BUS", "NETWORK"):
                ecu = "NETWORK"

            # Primary component extraction if available
            comp = None
            if hyp.possible_root_causes:
                comp = hyp.possible_root_causes[0]
            elif "MAF" in hyp.title.upper():
                comp = "MAF_SENSOR"
            elif "MAP" in hyp.title.upper():
                comp = "MAP_SENSOR"
            elif "VACUUM" in hyp.title.upper():
                comp = "INTAKE_MANIFOLD_SEAL"
            elif "THERMOSTAT" in hyp.title.upper():
                comp = "ENGINE_THERMOSTAT"

            # De-duplicate evidence to prevent double counting
            supp_refs: List[CauseEvidenceReference] = []
            for ev in hyp.supporting_evidence[:self.max_evidence_traversal]:
                ref = CauseEvidenceReference(
                    evidence_id=ev.evidence_id,
                    source_type="G3_FAULT_EVIDENCE",
                    signals=list(ev.signals),
                    target_ecu=ecu,
                    quality=ev.quality,
                    is_direct=True,
                    weight=min(1.0, ev.confidence_score),
                    summary=ev.observed_behavior,
                )
                if ref.fingerprint not in seen_fingerprints:
                    seen_fingerprints.add(ref.fingerprint)
                    supp_refs.append(ref)

            contra_refs: List[CauseEvidenceReference] = []
            for ev in hyp.contradicting_evidence[:self.max_evidence_traversal]:
                ref = CauseEvidenceReference(
                    evidence_id=ev.evidence_id,
                    source_type="G3_CONTRADICTION",
                    signals=list(ev.signals),
                    target_ecu=ecu,
                    quality=ev.quality,
                    is_direct=True,
                    weight=min(1.0, ev.confidence_score),
                    summary=ev.observed_behavior,
                )
                if ref.fingerprint not in seen_fingerprints:
                    seen_fingerprints.add(ref.fingerprint)
                    contra_refs.append(ref)

            # Link test results from H-2
            supp_tests: List[Dict[str, Any]] = []
            contra_tests: List[Dict[str, Any]] = []
            for tr in context.completed_test_results:
                matched_step = False
                if hyp.recommended_test_reference and tr.step_id in hyp.recommended_test_reference:
                    matched_step = True
                elif any(sig in tr.observed_values for sig in [s for r in supp_refs for s in r.signals]):
                    matched_step = True

                if matched_step:
                    if tr.actual_outcome in (ObservationResultType.NORMAL, ObservationResultType.MEASURED_VALUE):
                        supp_tests.append({"step_id": tr.step_id, "outcome": tr.actual_outcome.value})
                    elif tr.actual_outcome == ObservationResultType.ABNORMAL:
                        contra_tests.append({"step_id": tr.step_id, "outcome": tr.actual_outcome.value})

            cand = RootCauseCandidate(
                candidate_id=f"rc_{hyp.hypothesis_id}",
                title=hyp.title,
                description=f"Root cause candidate derived from hypothesis {hyp.hypothesis_id}: {hyp.title}",
                affected_ecu=ecu,
                affected_component=comp,
                category=hyp.category,
                source_hypotheses=[hyp.hypothesis_id],
                source_dtcs=list(hyp.dtc_associations),
                supporting_evidence=supp_refs,
                contradicting_evidence=contra_refs,
                supporting_test_results=supp_tests,
                contradicting_test_results=contra_tests,
                provenance={"source_hypothesis": hyp.hypothesis_id, "dtcs": hyp.dtc_associations},
            )
            candidates.append(cand)

        # 2. Check for Communication Failures (Protect against false module replacement)
        for unreach_ecu in context.unreachable_ecus:
            cand_comm = RootCauseCandidate(
                candidate_id=f"rc_comm_{unreach_ecu}",
                title=f"Diagnostic Communication Loss with {unreach_ecu}",
                description=f"{unreach_ecu} is unresponsive to diagnostic bus requests. Bus physical layer or power supply requires inspection.",
                affected_ecu=unreach_ecu,
                affected_component="CAN_TRANSCEIVER_OR_WIRING",
                category="NETWORK",
                causal_role=CausalRole.PRIMARY_ROOT_CAUSE,
                status=RootCauseCandidateStatus.UNRESOLVED,
                causal_basis=CausalBasis.DIRECT_MECHANISTIC_EVIDENCE,
                supporting_evidence=[
                    CauseEvidenceReference(
                        evidence_id=f"ev_unreach_{unreach_ecu}",
                        source_type="BUS_TIMEOUT",
                        target_ecu=unreach_ecu,
                        quality=SignalQuality.ERROR,
                        summary=f"{unreach_ecu} timed out / unreachable.",
                    )
                ],
                provenance={"unreachable_ecu": unreach_ecu},
            )
            candidates.append(cand_comm)

        return candidates[:self.max_candidates]

    # -----------------------------------------------------------------
    # B. Causal Scoring & Evidence Decomposition
    # -----------------------------------------------------------------

    def score_candidate(
        self,
        candidate: RootCauseCandidate,
        context: RootCauseAnalysisContext,
    ) -> None:
        """
        Evaluates candidate causal confidence, support/contradiction balance,
        cross-sensor consistency, and causal basis.
        """
        candidate.reasoning_trace.clear()

        # Step 1: Communication Failure Protection
        if "COMMUNICATION" in candidate.category.upper() or candidate.affected_ecu in context.unreachable_ecus:
            candidate.causal_role = CausalRole.PRIMARY_ROOT_CAUSE
            candidate.causal_basis = CausalBasis.DIRECT_MECHANISTIC_EVIDENCE
            candidate.status = RootCauseCandidateStatus.UNRESOLVED
            candidate.confidence_score = 0.5
            candidate.causal_confidence = 0.4
            candidate.reasoning_trace.append(
                f"ECU '{candidate.affected_ecu}' is unreachable on diagnostic bus. Classified as communication issue, NOT verified internal component defect."
            )
            return

        # Step 2: Calculate Support Score
        support = 0.0
        unique_signals: Set[str] = set()
        for ev in candidate.supporting_evidence:
            w = ev.weight
            if ev.quality in (SignalQuality.SUSPECT, SignalQuality.STALE):
                w *= 0.5
                candidate.quality_penalty += 0.2
            support += w
            unique_signals.update(ev.signals)

        # Step 3: Calculate Contradiction Score
        contradiction = 0.0
        for ev in candidate.contradicting_evidence:
            contradiction += ev.weight * 1.5  # Contradictions are heavily penalized

        # Step 4: Test Confirmation Score from H-2/H-3
        test_score = 0.0
        for tr in context.completed_test_results:
            # Check if this test was designed to confirm or discriminate this candidate
            for dec in context.selection_decisions:
                if dec.selected_candidate and dec.selected_candidate.originating_step_id == tr.step_id:
                    if candidate.source_hypotheses and any(h in dec.target_hypotheses for h in candidate.source_hypotheses):
                        if tr.actual_outcome in (ObservationResultType.NORMAL, ObservationResultType.MEASURED_VALUE):
                            test_score += 1.2
                            candidate.reasoning_trace.append(f"Targeted test '{tr.step_id}' returned positive confirmation.")
                        elif tr.actual_outcome == ObservationResultType.ABNORMAL:
                            contradiction += 1.5
                            candidate.reasoning_trace.append(f"Targeted test '{tr.step_id}' returned abnormal/contradictory result.")

        # Step 5: Cross-Sensor Consistency
        cross_sensor = 0.0
        if len(unique_signals) >= 3:
            cross_sensor = 0.6
            candidate.reasoning_trace.append(f"Strong cross-sensor consistency across {len(unique_signals)} signals: {', '.join(unique_signals)}.")
        elif len(unique_signals) == 2:
            cross_sensor = 0.3

        # Step 6: Cross-ECU Consistency
        cross_ecu = 0.0
        if context.diagnostic_graph and len(context.available_ecus) > 1:
            ecu_node = make_ecu_node_id(candidate.affected_ecu)
            if ecu_node in context.diagnostic_graph.nodes:
                cross_ecu = 0.2

        # Step 7: Check Secondary / Cascade Effects
        # Example: Misfire (P0300) when a severe air/fuel leak (P0171) is present
        if "MISFIRE" in candidate.title.upper() or "P0300" in candidate.source_dtcs:
            for other_hyp in context.hypotheses:
                if "LEAN" in other_hyp.title.upper() or "P0171" in other_hyp.dtc_associations:
                    candidate.causal_role = CausalRole.SECONDARY_EFFECT
                    candidate.reasoning_trace.append("Misfire tendency recognized as secondary consequence of severe air/fuel imbalance.")
                    break

        # Step 8: Calculate Calibrated Confidence
        raw_confidence = (support + test_score + cross_sensor + cross_ecu) - (contradiction + candidate.quality_penalty)
        # Normalize to 0.0 - 1.0
        normalized_conf = max(0.0, min(1.0, raw_confidence / max(1.0, (support + 2.0))))

        # Step 9: Determine Causal Basis & Causal Confidence
        # Central invariant: Correlation alone cannot produce high causal confidence
        if test_score > 0 and cross_sensor > 0:
            causal_basis = CausalBasis.HYPOTHESIS_TEST_SUPPORT
            causal_conf = normalized_conf
        elif cross_sensor > 0:
            causal_basis = CausalBasis.CROSS_SENSOR_CONSISTENCY
            causal_conf = min(0.75, normalized_conf)
        elif len(candidate.supporting_evidence) > 0 and not candidate.source_dtcs:
            causal_basis = CausalBasis.CONTROLLED_OBSERVATIONAL_SUPPORT
            causal_conf = min(0.70, normalized_conf)
        elif candidate.source_dtcs and len(candidate.supporting_evidence) == 0:
            causal_basis = CausalBasis.CORRELATIONAL_ONLY
            causal_conf = min(0.40, normalized_conf)
            candidate.reasoning_trace.append("Candidate supported solely by DTC correlation; causal confidence capped at 0.40.")
        else:
            causal_basis = CausalBasis.INDIRECT_EVIDENCE
            causal_conf = min(0.50, normalized_conf)

        # Store component breakdown
        candidate.support_score = support
        candidate.contradiction_score = contradiction
        candidate.test_confirmation_score = test_score
        candidate.cross_sensor_score = cross_sensor
        candidate.cross_ecu_score = cross_ecu
        candidate.confidence_score = normalized_conf
        candidate.causal_confidence = causal_conf
        candidate.causal_basis = causal_basis

        # Step 10: Assign Status
        if contradiction > support and contradiction > 1.0:
            candidate.status = RootCauseCandidateStatus.RULED_OUT
        elif contradiction > 0.5:
            candidate.status = RootCauseCandidateStatus.WEAKENED
        elif causal_conf >= 0.85:
            candidate.status = RootCauseCandidateStatus.STRONGLY_SUPPORTED
        elif causal_conf >= 0.65:
            candidate.status = RootCauseCandidateStatus.LEADING
        elif causal_conf >= 0.45:
            candidate.status = RootCauseCandidateStatus.PLAUSIBLE
        else:
            candidate.status = RootCauseCandidateStatus.POSSIBLE

    # -----------------------------------------------------------------
    # C. Root-Cause Analysis & Decision Synthesis
    # -----------------------------------------------------------------

    def analyze_root_cause(
        self,
        context: RootCauseAnalysisContext,
    ) -> RootCauseAnalysis:
        """
        Executes complete root-cause analysis over the context.
        Ranks candidates, separates primary from secondary causes, resolves
        contradictions, and generates an explainable conclusion.
        """
        analysis_id = f"rca_{uuid.uuid4().hex[:12]}"
        now = time.time()
        trace: List[str] = []

        # 1. Generate and Score Candidates
        candidates = self.generate_candidates(context)
        trace.append(f"Generated {len(candidates)} root-cause candidates from diagnostic context.")

        for c in candidates:
            self.score_candidate(c, context)

        # 2. Sort and Categorize Candidates
        # Order by causal_confidence descending, then candidate_id
        candidates.sort(key=lambda c: (-round(c.causal_confidence, 4), -round(c.confidence_score, 4), c.candidate_id))

        primary: Optional[RootCauseCandidate] = None
        alternatives: List[RootCauseCandidate] = []
        contributing: List[RootCauseCandidate] = []
        ruled_out: List[RootCauseCandidate] = []

        for c in candidates:
            if c.status == RootCauseCandidateStatus.RULED_OUT:
                ruled_out.append(c)
            elif c.causal_role in (CausalRole.SECONDARY_EFFECT, CausalRole.CONTRIBUTING_FACTOR):
                contributing.append(c)
            elif primary is None:
                primary = c
            else:
                alternatives.append(c)

        # 3. Formulate Conclusion State & Certainty
        conclusion_state: AnalysisConclusionState
        certainty: RootCauseCertaintyLevel
        summary: str
        verification: Optional[str] = None

        # Check for communication failure primacy
        if primary and "COMMUNICATION" in primary.category.upper():
            conclusion_state = AnalysisConclusionState.COMMUNICATION_ISSUE_UNRESOLVED
            certainty = RootCauseCertaintyLevel.INCONCLUSIVE
            summary = (
                f"Diagnostic communication with ECU '{primary.affected_ecu}' is lost or unverified. "
                f"Diagnostic physical layer, power supply, and CAN bus harness must be inspected before component diagnosis."
            )
            verification = f"Verify power, ground, and CAN termination resistance at {primary.affected_ecu} connector."

        elif primary and len(alternatives) > 0 and abs(primary.causal_confidence - alternatives[0].causal_confidence) < 0.08:
            # Competing hypotheses have essentially equal support
            conclusion_state = AnalysisConclusionState.MULTIPLE_PLAUSIBLE_CAUSES
            certainty = RootCauseCertaintyLevel.MODERATE_CERTAINTY
            summary = (
                f"Multiple plausible causes remain: '{primary.title}' (confidence {primary.causal_confidence:.2f}) and "
                f"'{alternatives[0].title}' (confidence {alternatives[0].causal_confidence:.2f}). Direct discriminating test recommended."
            )
            verification = f"Execute discrimination test between {primary.title} and {alternatives[0].title}."

        elif not primary or primary.causal_confidence < 0.3:
            conclusion_state = AnalysisConclusionState.NO_CONFIDENT_ROOT_CAUSE
            certainty = RootCauseCertaintyLevel.INCONCLUSIVE
            summary = "Current evidence is insufficient to confidently establish a root cause. Further diagnostic testing required."
            verification = "Perform targeted data acquisition under load conditions."

        elif primary.contradiction_score > 0.8:
            conclusion_state = AnalysisConclusionState.CONFLICTED_EVIDENCE
            certainty = RootCauseCertaintyLevel.LOW_CERTAINTY
            summary = (
                f"Evidence for '{primary.title}' contains significant physical contradictions. "
                f"Cannot establish high certainty until contradictory readings are resolved."
            )
            verification = "Perform direct physical inspection to resolve conflicting sensor telemetry."

        elif primary.causal_confidence >= 0.85:
            conclusion_state = AnalysisConclusionState.ROOT_CAUSE_STRONGLY_SUPPORTED
            certainty = RootCauseCertaintyLevel.HIGH_CERTAINTY
            summary = (
                f"Root cause '{primary.title}' is strongly supported by {primary.causal_basis.value} "
                f"across {len(primary.supporting_evidence)} evidence records."
            )
            verification = f"Visually confirm physical integrity of {primary.affected_component or primary.title} before repair."

        else:
            conclusion_state = AnalysisConclusionState.LEADING_CANDIDATE_ONLY
            certainty = RootCauseCertaintyLevel.MODERATE_CERTAINTY
            summary = f"Leading candidate is '{primary.title}' based on {primary.causal_basis.value}."
            verification = f"Verify physical signals on {primary.affected_ecu}."

        # 4. Check for Technician Input Override
        tech_override = None
        for ti in context.technician_inputs:
            if ti.get("type") == "TECHNICIAN_CONFIRMATION" and primary:
                if ti.get("target_candidate") == primary.candidate_id:
                    primary.status = RootCauseCandidateStatus.STRONGLY_SUPPORTED
                    certainty = RootCauseCertaintyLevel.CONFIRMED
                    summary = f"Technician confirmed root cause: {primary.title}."
                    tech_override = ti
            elif ti.get("type") == "TECHNICIAN_REJECTION" and primary:
                if ti.get("target_candidate") == primary.candidate_id:
                    primary.status = RootCauseCandidateStatus.RULED_OUT
                    ruled_out.append(primary)
                    primary = alternatives.pop(0) if alternatives else None
                    summary = f"Technician ruled out previous candidate. Re-evaluating alternatives."
                    tech_override = ti

        # 5. Check for Post-Repair Verification
        post_repair = None
        for ti in context.technician_inputs:
            if ti.get("type") == "POST_REPAIR_VERIFICATION":
                post_repair = ti
                summary += f" Post-repair verification recorded: {ti.get('details', 'Component replaced')}."

        conclusion = RootCauseConclusion(
            conclusion_state=conclusion_state,
            primary_candidate_id=primary.candidate_id if primary else None,
            certainty_level=certainty,
            summary_text=summary,
            recommended_final_verification=verification,
            technician_override=tech_override,
            post_repair_verification=post_repair,
        )

        trace.append(f"Synthesized conclusion: {conclusion_state.value} (Certainty: {certainty.value}).")

        # 6. Update G-5 DiagnosticGraph with Causal Relationships
        if context.diagnostic_graph and primary:
            self._update_graph_with_root_cause(context.diagnostic_graph, primary, context)

        return RootCauseAnalysis(
            analysis_id=analysis_id,
            vehicle_id=context.vehicle_id,
            session_id=context.session_id,
            timestamp=now,
            primary_candidate=primary,
            alternative_candidates=alternatives,
            contributing_factors=contributing,
            ruled_out_candidates=ruled_out,
            conclusion=conclusion,
            reasoning_trace=trace,
            provenance={"analyzer_version": "1.0.0", "hypothesis_count": len(context.hypotheses)},
        )

    # -----------------------------------------------------------------
    # D. Graph Integration Helper
    # -----------------------------------------------------------------

    def _update_graph_with_root_cause(
        self,
        graph: DiagnosticGraph,
        candidate: RootCauseCandidate,
        context: RootCauseAnalysisContext,
    ) -> None:
        """
        Integrates root-cause findings into the existing G-5 diagnostic graph.
        Does NOT create a duplicate graph.
        """
        try:
            cause_node_id = f"cause:{context.session_id}:{candidate.candidate_id}"
            node = GraphNode(
                node_id=cause_node_id,
                node_type=GraphNodeType.HYPOTHESIS,
                label=f"Root Cause: {candidate.title}",
                properties={
                    "causal_role": candidate.causal_role.value,
                    "causal_basis": candidate.causal_basis.value,
                    "causal_confidence": candidate.causal_confidence,
                    "status": candidate.status.value,
                },
            )
            graph.add_node(node)

            # Link to affected ECU
            ecu_node = make_ecu_node_id(candidate.affected_ecu)
            if ecu_node in graph.nodes:
                edge = GraphEdge(
                    edge_id=f"edge:{cause_node_id}:{ecu_node}",
                    source_id=cause_node_id,
                    target_id=ecu_node,
                    edge_type=GraphEdgeType.SUPPORTS_HYPOTHESIS,
                    properties={"causal_role": candidate.causal_role.value},
                )
                graph.add_edge(edge)
        except Exception as e:
            logger.warning(f"Could not update graph with root-cause candidate: {e}")
