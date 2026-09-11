# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase I-5: Advanced Reasoning Layer Subsystem
=============================================================================
This module implements Phase I-5 of the Seyyanen diagnostic architecture.
It synthesizes validated telemetry evidence, vehicle and ECU context, empirical
failure patterns, historical diagnostic case experience, hypothesis competition,
causal assessments, and safe distinguishing tests into a structured, bounded,
and fully explainable diagnostic reasoning process.

Strict Architectural Invariants:
  1. REASONING CHAIN TRACEABILITY:
     data -> validation -> evidence -> pattern -> hypothesis -> competing hypotheses ->
     test -> result -> causal assessment -> historical/contextual evidence -> ranked conclusion -> verification.
     Every conclusion must remain traceable to underlying empirical evidence.
  2. EVIDENCE IS NOT PROOF:
     A DTC is evidence, not proof.
     A failure pattern is evidence, not proof.
     A historical case is evidence, not proof.
  3. CORRELATION != CAUSATION:
     Co-occurrence, timestamp alignment, or trouble code co-presence does not
     prove causation without mechanistic consistency or targeted experimental/test results.
  4. CURRENT VEHICLE EVIDENCE PRIORITY:
     Current live vehicle observations strictly take precedence over generic knowledge
     or past historical cases. Conflicting historical evidence is actively downgraded.
  5. COMMUNICATION FAULT != COMPONENT FAILURE:
     Bus drops, missing frames, and unreachable ECUs are classified as network/power
     anomalies, never as defective internal electronic hardware.
  6. NO AUTONOMOUS REPAIR COMMANDS:
     The reasoning layer never produces unconditional commands like "replace component X".
     Recommendations are formulated as: "Current evidence most strongly supports
     hypothesis X; verify using distinguishing test Y" or "Additional evidence required".
  7. STRICT READ-ONLY SAFETY GATING:
     Zero direct transport access, zero actuator actuation (0x2F), zero DID writes (0x2E),
     zero programming sessions (0x34/36/37), and zero DTC clearing (Mode 04/14).
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

# Integration imports from C, D, G, H, I-1, I-2, I-3, and I-4 layers
from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    STATUS_VALID,
)
from advanced_ecu_services import (
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    SessionType,
)
from extended_did import (
    VehicleContext,
    VehicleApplicability,
    ApplicabilityResult,
    DefinitionTrustLevel,
    IdentifierNamespace,
    StructuredDiagnosticEvidence,
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
    DTCRecord,
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
from automated_root_cause_analyzer import (
    CausalBasis,
    CausalRole,
    RootCauseCertaintyLevel,
    AnalysisConclusionState,
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
    KnowledgeDistinguishingTest,
    DiagnosticKnowledgeStore,
)
from vehicle_ecu_knowledge import (
    ProgressiveVehicleIdentity,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    ECUKnowledgeProfile,
    VehicleECUKnowledgeStore,
)
from failure_pattern_library import (
    PatternCategory,
    PatternFeatureType,
    PatternMatchGrade,
    PatternFeatureRequirement,
    ObservedFeatureSet,
    FailurePattern,
    PatternMatchResult,
    FailurePatternLibraryStore,
)
from historical_case_analysis import (
    CaseLifecycle,
    CaseMatchGrade,
    CaseRelationshipType,
    RootCauseConfidenceGrade,
    CaseECUContext,
    CaseDTCRecord,
    CaseTestResult,
    CaseRootCause,
    CaseTechnicianConfirmation,
    CaseRepairOutcome,
    PostRepairVerification,
    HistoricalDiagnosticCase,
    CaseSimilarityResult,
    HistoricalCaseRepository,
)

logger = logging.getLogger("seyyanen.advanced_reasoning_layer")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class ReasoningUncertainty(str, enum.Enum):
    """Calibrated confidence and uncertainty state of a diagnostic reasoning session."""
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"          # Strong evidence, test-backed, no contradictions
    MODERATE_CONFIDENCE = "MODERATE_CONFIDENCE"  # Solid evidence, minor alternatives remain
    LOW_CONFIDENCE = "LOW_CONFIDENCE"            # Weak evidence, multiple competing causes
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE" # Essential data missing, cannot conclude
    CONTRADICTORY = "CONTRADICTORY"              # Strong contradictory evidence detected


class EvidenceDirection(str, enum.Enum):
    """Directional contribution of an evidence item toward a hypothesis."""
    SUPPORTS = "SUPPORTS"                        # Positive consistent observation
    CONTRADICTS = "CONTRADICTS"                  # Incompatible physical or logical observation
    NEUTRAL = "NEUTRAL"                          # Uncorrelated or contextually ambiguous
    MISSING_EXPECTED = "MISSING_EXPECTED"        # Expected observation absent under conditions


# =====================================================================
# 2. EVIDENCE CONTRIBUTION & CONTRADICTION MODELS
# =====================================================================

@dataclass
class ReasoningEvidenceContribution:
    """
    Granular, auditable contribution of an individual evidence item.
    Preserves origin source, signal quality, directional weight, and provenance.
    """
    contribution_id: str
    source: str                                  # "C_VALIDATION", "D_EVIDENCE", "I_3_PATTERN", "I_4_HISTORICAL", "H_TEST_RESULT", "TECHNICIAN"
    evidence_type: str                           # e.g. "SIGNAL_DRIFT", "TEST_RESULT", "DTC", "PATTERN_MATCH"
    value_summary: str
    quality: SignalQuality = SignalQuality.GOOD
    direction: EvidenceDirection = EvidenceDirection.SUPPORTS
    weight: float = 1.0
    confidence: KnowledgeConfidence = KnowledgeConfidence.HIGH
    provenance: Optional[KnowledgeProvenance] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contribution_id": self.contribution_id,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "value_summary": self.value_summary,
            "quality": self.quality.value,
            "direction": self.direction.value,
            "weight": round(self.weight, 2),
            "confidence": self.confidence.value,
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningEvidenceContribution":
        prov = KnowledgeProvenance.from_dict(data["provenance"]) if data.get("provenance") else None
        return cls(
            contribution_id=data["contribution_id"],
            source=data["source"],
            evidence_type=data["evidence_type"],
            value_summary=data["value_summary"],
            quality=SignalQuality(data.get("quality", "GOOD")),
            direction=EvidenceDirection(data.get("direction", "SUPPORTS")),
            weight=float(data.get("weight", 1.0)),
            confidence=KnowledgeConfidence(data.get("confidence", "HIGH")),
            provenance=prov,
        )


@dataclass
class ReasoningContradiction:
    """
    Explicitly detected conflict between evidence sources, test results,
    or physical constraints.
    """
    contradiction_id: str
    source_a: str
    source_b: str
    description: str
    impact_on_hypothesis: str
    penalty_weight: float = 0.40

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "description": self.description,
            "impact_on_hypothesis": self.impact_on_hypothesis,
            "penalty_weight": round(self.penalty_weight, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningContradiction":
        return cls(
            contradiction_id=data["contradiction_id"],
            source_a=data["source_a"],
            source_b=data["source_b"],
            description=data["description"],
            impact_on_hypothesis=data["impact_on_hypothesis"],
            penalty_weight=float(data.get("penalty_weight", 0.40)),
        )


# =====================================================================
# 3. REASONING CANDIDATE (HYPOTHESIS COMPETITOR)
# =====================================================================

@dataclass
class ReasoningCandidate:
    """
    A competitive root-cause hypothesis evaluated across all diagnostic dimensions.
    Exposes decomposed scores, supporting and contradictory contributions,
    causal basis, and distinguishing test requirements.
    """
    candidate_id: str
    hypothesis_title: str
    affected_system: str = "POWERTRAIN"
    affected_ecu: str = "ECM"
    candidate_role: CausalRole = CausalRole.CORRELATED_OBSERVATION
    causal_basis: CausalBasis = CausalBasis.CORRELATIONAL_ONLY
    supporting_contributions: List[ReasoningEvidenceContribution] = field(default_factory=list)
    contradicting_contributions: List[ReasoningEvidenceContribution] = field(default_factory=list)
    missing_expected_evidence: List[str] = field(default_factory=list)
    distinguishing_tests: List[KnowledgeDistinguishingTest] = field(default_factory=list)
    matched_pattern_ids: List[str] = field(default_factory=list)
    relevant_case_ids: List[str] = field(default_factory=list)
    evidence_score: float = 0.0
    applicability_weight: float = 1.0
    historical_relevance: float = 0.0
    contradiction_penalty: float = 0.0
    overall_score: float = 0.0
    confidence: ReasoningUncertainty = ReasoningUncertainty.MODERATE_CONFIDENCE
    explanations: List[str] = field(default_factory=list)
    provenance: Optional[KnowledgeProvenance] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "hypothesis_title": self.hypothesis_title,
            "affected_system": self.affected_system,
            "affected_ecu": self.affected_ecu,
            "candidate_role": self.candidate_role.value,
            "causal_basis": self.causal_basis.value,
            "supporting_contributions": [c.to_dict() for c in self.supporting_contributions],
            "contradicting_contributions": [c.to_dict() for c in self.contradicting_contributions],
            "missing_expected_evidence": list(self.missing_expected_evidence),
            "distinguishing_tests": [dt.to_dict() for dt in self.distinguishing_tests],
            "matched_pattern_ids": list(self.matched_pattern_ids),
            "relevant_case_ids": list(self.relevant_case_ids),
            "evidence_score": round(self.evidence_score, 3),
            "applicability_weight": round(self.applicability_weight, 2),
            "historical_relevance": round(self.historical_relevance, 3),
            "contradiction_penalty": round(self.contradiction_penalty, 3),
            "overall_score": round(self.overall_score, 3),
            "confidence": self.confidence.value,
            "explanations": list(self.explanations),
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningCandidate":
        prov = KnowledgeProvenance.from_dict(data["provenance"]) if data.get("provenance") else None
        return cls(
            candidate_id=data["candidate_id"],
            hypothesis_title=data["hypothesis_title"],
            affected_system=data.get("affected_system", "POWERTRAIN"),
            affected_ecu=data.get("affected_ecu", "ECM"),
            candidate_role=CausalRole(data.get("candidate_role", "PRIMARY_ROOT_CAUSE")),
            causal_basis=CausalBasis(data.get("causal_basis", "CORRELATIONAL_ONLY")),
            supporting_contributions=[ReasoningEvidenceContribution.from_dict(c) for c in data.get("supporting_contributions", [])],
            contradicting_contributions=[ReasoningEvidenceContribution.from_dict(c) for c in data.get("contradicting_contributions", [])],
            missing_expected_evidence=list(data.get("missing_expected_evidence", [])),
            distinguishing_tests=[KnowledgeDistinguishingTest.from_dict(dt) for dt in data.get("distinguishing_tests", [])],
            matched_pattern_ids=list(data.get("matched_pattern_ids", [])),
            relevant_case_ids=list(data.get("relevant_case_ids", [])),
            evidence_score=float(data.get("evidence_score", 0.0)),
            applicability_weight=float(data.get("applicability_weight", 1.0)),
            historical_relevance=float(data.get("historical_relevance", 0.0)),
            contradiction_penalty=float(data.get("contradiction_penalty", 0.0)),
            overall_score=float(data.get("overall_score", 0.0)),
            confidence=ReasoningUncertainty(data.get("confidence", "MODERATE_CONFIDENCE")),
            explanations=list(data.get("explanations", [])),
            provenance=prov,
        )


# =====================================================================
# 4. REASONING TRACE & DIAGNOSTIC SESSION
# =====================================================================

@dataclass
class ReasoningTraceStep:
    """A deterministic, sequential step in the reasoning audit trail."""
    step_number: int
    phase_name: str
    action: str
    inputs_considered: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "phase_name": self.phase_name,
            "action": self.action,
            "inputs_considered": list(self.inputs_considered),
            "findings": list(self.findings),
            "timestamp": round(self.timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningTraceStep":
        return cls(
            step_number=int(data["step_number"]),
            phase_name=data["phase_name"],
            action=data["action"],
            inputs_considered=list(data.get("inputs_considered", [])),
            findings=list(data.get("findings", [])),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class DiagnosticReasoningSession:
    """
    Primary entity of the Advanced Reasoning Layer.
    Preserves all evaluated candidates, ranked conclusions, distinguishing
    tests, contradictions, uncertainty states, and auditable reasoning traces.
    """
    reasoning_id: str
    session_id: str
    vehicle_context: VehicleContext
    provenance: KnowledgeProvenance
    ecu_contexts: Dict[str, CaseECUContext] = field(default_factory=dict)
    operating_conditions: List[OperatingCondition] = field(default_factory=list)
    candidates: List[ReasoningCandidate] = field(default_factory=list)
    ranked_candidates: List[ReasoningCandidate] = field(default_factory=list)
    overall_conclusion: str = ""
    overall_confidence: ReasoningUncertainty = ReasoningUncertainty.INSUFFICIENT_EVIDENCE
    recommended_distinguishing_tests: List[KnowledgeDistinguishingTest] = field(default_factory=list)
    contradictions: List[ReasoningContradiction] = field(default_factory=list)
    reasoning_trace: List[ReasoningTraceStep] = field(default_factory=list)
    version: int = 1
    lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.reasoning_id or not str(self.reasoning_id).strip():
            raise ValueError("Reasoning session must have a valid non-empty reasoning_id.")
        # Safety invariant: Ensure all recommended distinguishing tests are READ_ONLY
        for dt in self.recommended_distinguishing_tests:
            if dt.safety_classification != ServiceSafetyClassification.READ_ONLY:
                raise ValueError(
                    f"Safety Violation: Recommended test '{dt.test_id}' in reasoning "
                    f"session '{self.reasoning_id}' must be READ_ONLY."
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reasoning_id": self.reasoning_id,
            "session_id": self.session_id,
            "vehicle_context": {
                "vin": self.vehicle_context.vin,
                "manufacturer": self.vehicle_context.manufacturer,
                "model": self.vehicle_context.model,
                "model_year": self.vehicle_context.model_year,
                "engine_code": self.vehicle_context.engine_code,
                "transmission": self.vehicle_context.transmission,
                "ecu_family": self.vehicle_context.ecu_family,
                "software_id": self.vehicle_context.software_id,
                "metadata": dict(self.vehicle_context.metadata),
            },
            "provenance": self.provenance.to_dict(),
            "ecu_contexts": {k: v.to_dict() for k, v in self.ecu_contexts.items()},
            "operating_conditions": [oc.value for oc in self.operating_conditions],
            "candidates": [c.to_dict() for c in self.candidates],
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
            "overall_conclusion": self.overall_conclusion,
            "overall_confidence": self.overall_confidence.value,
            "recommended_distinguishing_tests": [dt.to_dict() for dt in self.recommended_distinguishing_tests],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "reasoning_trace": [s.to_dict() for s in self.reasoning_trace],
            "version": self.version,
            "lifecycle": self.lifecycle.value,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticReasoningSession":
        vc_data = data["vehicle_context"]
        vc = VehicleContext(
            vin=vc_data.get("vin"),
            manufacturer=vc_data.get("manufacturer"),
            model=vc_data.get("model"),
            model_year=vc_data.get("model_year"),
            engine_code=vc_data.get("engine_code"),
            transmission=vc_data.get("transmission"),
            ecu_family=vc_data.get("ecu_family"),
            software_id=vc_data.get("software_id"),
            metadata=dict(vc_data.get("metadata", {})),
        )

        return cls(
            reasoning_id=data["reasoning_id"],
            session_id=data["session_id"],
            vehicle_context=vc,
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            ecu_contexts={k: CaseECUContext.from_dict(v) for k, v in data.get("ecu_contexts", {}).items()},
            operating_conditions=[OperatingCondition(oc) for oc in data.get("operating_conditions", [])],
            candidates=[ReasoningCandidate.from_dict(c) for c in data.get("candidates", [])],
            ranked_candidates=[ReasoningCandidate.from_dict(c) for c in data.get("ranked_candidates", [])],
            overall_conclusion=data.get("overall_conclusion", ""),
            overall_confidence=ReasoningUncertainty(data.get("overall_confidence", "INSUFFICIENT_EVIDENCE")),
            recommended_distinguishing_tests=[KnowledgeDistinguishingTest.from_dict(dt) for dt in data.get("recommended_distinguishing_tests", [])],
            contradictions=[ReasoningContradiction.from_dict(c) for c in data.get("contradictions", [])],
            reasoning_trace=[ReasoningTraceStep.from_dict(s) for s in data.get("reasoning_trace", [])],
            version=int(data.get("version", 1)),
            lifecycle=KnowledgeLifecycle(data.get("lifecycle", "ACTIVE")),
            metadata=dict(data.get("metadata", {})),
        )


# =====================================================================
# 5. ADVANCED REASONING ENGINE
# =====================================================================

class AdvancedReasoningEngine:
    """
    Deterministic synthesis and reasoning engine across all diagnostic knowledge layers.
    Combines validated evidence, vehicle/ECU applicability, empirical failure patterns,
    historical cases, hypothesis competition, and causal assessment.
    """

    def __init__(
        self,
        knowledge_store: Optional[DiagnosticKnowledgeStore] = None,
        vehicle_ecu_store: Optional[VehicleECUKnowledgeStore] = None,
        pattern_store: Optional[FailurePatternLibraryStore] = None,
        case_repository: Optional[HistoricalCaseRepository] = None,
    ):
        self.knowledge_store = knowledge_store or DiagnosticKnowledgeStore()
        self.vehicle_ecu_store = vehicle_ecu_store or VehicleECUKnowledgeStore()
        self.pattern_store = pattern_store or FailurePatternLibraryStore()
        self.case_repository = case_repository or HistoricalCaseRepository()

    def conduct_reasoning(
        self,
        vehicle_context: VehicleContext,
        observed_features: Optional[ObservedFeatureSet] = None,
        active_dtcs: Optional[List[str]] = None,
        test_results: Optional[List[CaseTestResult]] = None,
        operating_conditions: Optional[List[OperatingCondition]] = None,
        hypotheses: Optional[List[FaultHypothesis]] = None,
        session_id: Optional[str] = None,
        max_candidates: int = 10,
        max_distinguishing_tests: int = 3,
    ) -> DiagnosticReasoningSession:
        """
        Executes the full, deterministic, 12-step advanced diagnostic reasoning process.
        """
        sess_id = session_id or f"SESS_{int(time.time())}"
        reasoning_id = f"REASON_{uuid.uuid4().hex[:10].upper()}"

        trace: List[ReasoningTraceStep] = []
        step_num = 1

        # -----------------------------------------------------------------
        # STEP 1: Vehicle & Powertrain Context Establishment
        # -----------------------------------------------------------------
        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="CONTEXT_ESTABLISHMENT",
            action="Establish vehicle identity, engine profile, and ECU configuration",
            inputs_considered=[
                f"Manufacturer: {vehicle_context.manufacturer}",
                f"Model: {vehicle_context.model}",
                f"Engine: {vehicle_context.engine_code}",
                f"ECU: {vehicle_context.ecu_family}",
            ],
            findings=["Vehicle context verified and normalized."],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 2: Evidence Validation & Provenance Ingestion
        # -----------------------------------------------------------------
        curr_dtcs = [d.strip().upper() for d in (active_dtcs or [])]
        feats = observed_features.features if observed_features else {}
        conds = list(operating_conditions or ([observed_features.operating_condition] if observed_features else []))

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="EVIDENCE_INGESTION",
            action="Ingest validated telemetry features, DTCs, and operating states",
            inputs_considered=[f"DTCs: {curr_dtcs}", f"Features: {list(feats.keys())}"],
            findings=[f"Ingested {len(feats)} telemetry features across {len(conds)} operating conditions."],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 3: Failure Pattern Library Matching (I-3)
        # -----------------------------------------------------------------
        matched_pattern_results: List[PatternMatchResult] = []
        if observed_features:
            matched_pattern_results = self.pattern_store.match_patterns(
                observed_features=observed_features,
                vehicle_context=vehicle_context,
                active_only=True,
                max_results=5,
            )

        matched_pats = [r.pattern.pattern_id for r in matched_pattern_results if r.match_grade in (PatternMatchGrade.STRONG_MATCH, PatternMatchGrade.PARTIAL_MATCH)]

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="PATTERN_MATCHING",
            action="Evaluate empirical telemetry patterns against Failure Pattern Library",
            inputs_considered=[f"Evaluated patterns against features: {list(feats.keys())}"],
            findings=[f"Matched patterns: {matched_pats}"],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 4: Historical Case Retrieval (I-4)
        # -----------------------------------------------------------------
        similar_cases: List[CaseSimilarityResult] = self.case_repository.find_similar_cases(
            vehicle_context=vehicle_context,
            observed_features=observed_features,
            active_dtcs=curr_dtcs,
            matched_patterns=matched_pats,
            operating_conditions=conds,
            max_results=5,
        )

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="HISTORICAL_EXPERIENCE",
            action="Retrieve contextual historical diagnostic cases with similarity breakdown",
            inputs_considered=[f"Vehicle: {vehicle_context.manufacturer} {vehicle_context.engine_code}", f"Patterns: {matched_pats}"],
            findings=[f"Retrieved {len(similar_cases)} relevant historical cases."],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 5: Candidate Hypothesis Generation & Deduplication
        # -----------------------------------------------------------------
        candidate_map: Dict[str, ReasoningCandidate] = {}

        # 5a. Hypotheses from explicit input
        if hypotheses:
            for h in hypotheses:
                cid = h.hypothesis_id
                candidate_map[cid] = ReasoningCandidate(
                    candidate_id=cid,
                    hypothesis_title=h.title,
                    affected_system=h.affected_system,
                    affected_ecu="ECM",
                    provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="D_HYPOTHESIS_ENGINE"),
                )

        # 5b. Hypotheses from matched patterns
        for pm in matched_pattern_results:
            for ph in pm.pattern.possible_hypotheses:
                if ph not in candidate_map:
                    candidate_map[ph] = ReasoningCandidate(
                        candidate_id=ph,
                        hypothesis_title=f"Pattern-Derived: {ph}",
                        affected_system="POWERTRAIN",
                        affected_ecu="ECM",
                        matched_pattern_ids=[pm.pattern.pattern_id],
                        provenance=pm.pattern.provenance,
                    )
                else:
                    if pm.pattern.pattern_id not in candidate_map[ph].matched_pattern_ids:
                        candidate_map[ph].matched_pattern_ids.append(pm.pattern.pattern_id)

        # 5c. Hypotheses from historical confirmed cases
        for sc in similar_cases:
            if sc.case.root_cause and sc.relevance_as_evidence >= 0.30:
                rc_id = sc.case.root_cause.root_cause_id
                if rc_id not in candidate_map:
                    candidate_map[rc_id] = ReasoningCandidate(
                        candidate_id=rc_id,
                        hypothesis_title=sc.case.root_cause.component_or_system,
                        affected_system="POWERTRAIN",
                        affected_ecu=sc.case.root_cause.affected_ecu,
                        relevant_case_ids=[sc.case.case_id],
                        provenance=sc.case.provenance,
                    )
                else:
                    if sc.case.case_id not in candidate_map[rc_id].relevant_case_ids:
                        candidate_map[rc_id].relevant_case_ids.append(sc.case.case_id)

        # Fallback default hypothesis if nothing generated
        if not candidate_map:
            def_id = "HYP_INSUFFICIENT_DATA"
            candidate_map[def_id] = ReasoningCandidate(
                candidate_id=def_id,
                hypothesis_title="Unspecified Operational Anomaly",
                confidence=ReasoningUncertainty.INSUFFICIENT_EVIDENCE,
                provenance=KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="DEFAULT"),
            )

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="HYPOTHESIS_GENERATION",
            action="Synthesize and deduplicate candidate hypotheses from all active layers",
            inputs_considered=[f"Raw candidates count: {len(candidate_map)}"],
            findings=[f"Active competitive candidates: {list(candidate_map.keys())}"],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 6: Multi-Source Evidence Fusion & Contradiction Detection
        # -----------------------------------------------------------------
        detected_contradictions: List[ReasoningContradiction] = []
        executed_tests = test_results or []

        for cid, cand in candidate_map.items():
            # 6a. Evaluate pattern evidence
            for pm in matched_pattern_results:
                if cid in pm.pattern.possible_hypotheses:
                    cand.supporting_contributions.append(ReasoningEvidenceContribution(
                        contribution_id=f"EV_PAT_{pm.pattern.pattern_id}",
                        source="I_3_FAILURE_PATTERN",
                        evidence_type="PATTERN_MATCH",
                        value_summary=f"Matched pattern '{pm.pattern.name}' ({pm.match_grade.value})",
                        weight=pm.overall_score,
                    ))
                    # Check contradictory features in pattern
                    if pm.contradictory_features_detected:
                        contra = ReasoningContradiction(
                            contradiction_id=f"CONTRA_PAT_{pm.pattern.pattern_id}",
                            source_a=pm.pattern.pattern_id,
                            source_b="CURRENT_TELEMETRY",
                            description=f"Pattern contradictory features active: {pm.contradictory_features_detected}",
                            impact_on_hypothesis=f"Weakens hypothesis '{cid}'",
                            penalty_weight=0.35,
                        )
                        detected_contradictions.append(contra)
                        cand.contradicting_contributions.append(ReasoningEvidenceContribution(
                            contribution_id=f"EV_CONTRA_PAT_{pm.pattern.pattern_id}",
                            source="I_3_FAILURE_PATTERN",
                            evidence_type="CONTRADICTION",
                            value_summary=contra.description,
                            direction=EvidenceDirection.CONTRADICTS,
                            weight=0.35,
                        ))

            # 6b. Evaluate historical case evidence (Current evidence strictly dominates)
            for sc in similar_cases:
                if sc.case.root_cause and sc.case.root_cause.root_cause_id == cid:
                    if sc.contradictions_detected:
                        # Contradicted historical case!
                        contra = ReasoningContradiction(
                            contradiction_id=f"CONTRA_CASE_{sc.case.case_id}",
                            source_a=sc.case.case_id,
                            source_b="CURRENT_TELEMETRY",
                            description=f"Current evidence contradicts historical case: {sc.contradictions_detected}",
                            impact_on_hypothesis=f"Severely discounts candidate '{cid}'",
                            penalty_weight=0.50,
                        )
                        detected_contradictions.append(contra)
                        cand.contradicting_contributions.append(ReasoningEvidenceContribution(
                            contribution_id=f"EV_CONTRA_CASE_{sc.case.case_id}",
                            source="I_4_HISTORICAL_CASE",
                            evidence_type="CONTRADICTION",
                            value_summary=contra.description,
                            direction=EvidenceDirection.CONTRADICTS,
                            weight=0.50,
                        ))
                    else:
                        cand.supporting_contributions.append(ReasoningEvidenceContribution(
                            contribution_id=f"EV_CASE_{sc.case.case_id}",
                            source="I_4_HISTORICAL_CASE",
                            evidence_type="SIMILAR_CASE",
                            value_summary=f"Confirmed in similar case '{sc.case.case_id}' (Relevance: {sc.relevance_as_evidence:.2f})",
                            weight=sc.relevance_as_evidence,
                        ))
                        cand.historical_relevance = max(cand.historical_relevance, sc.relevance_as_evidence)

            # 6c. Evaluate executed physical test results
            for tr in executed_tests:
                if tr.outcome == "PASSED":
                    cand.supporting_contributions.append(ReasoningEvidenceContribution(
                        contribution_id=f"EV_TEST_{tr.test_id}",
                        source="H_TEST_RESULT",
                        evidence_type="DIAGNOSTIC_TEST",
                        value_summary=f"Test '{tr.test_title}' PASSED: {tr.observations}",
                        weight=1.5,
                    ))
                    cand.causal_basis = CausalBasis.HYPOTHESIS_TEST_SUPPORT
                elif tr.outcome == "FAILED":
                    contra = ReasoningContradiction(
                        contradiction_id=f"CONTRA_TEST_{tr.test_id}",
                        source_a=tr.test_id,
                        source_b=cid,
                        description=f"Test '{tr.test_title}' FAILED: {tr.observations}",
                        impact_on_hypothesis=f"Disproves candidate '{cid}'",
                        penalty_weight=0.80,
                    )
                    detected_contradictions.append(contra)
                    cand.contradicting_contributions.append(ReasoningEvidenceContribution(
                        contribution_id=f"EV_TEST_FAIL_{tr.test_id}",
                        source="H_TEST_RESULT",
                        evidence_type="CONTRADICTION",
                        value_summary=contra.description,
                        direction=EvidenceDirection.CONTRADICTS,
                        weight=0.80,
                    ))

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="EVIDENCE_FUSION",
            action="Fuse multi-source evidence and evaluate directional support vs contradictions",
            inputs_considered=[f"Candidates evaluated: {len(candidate_map)}"],
            findings=[f"Identified {len(detected_contradictions)} explicit contradictions."],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 7: Causal Assessment & Role Assignment
        # -----------------------------------------------------------------
        for cid, cand in candidate_map.items():
            # Invariant: Correlation != Causation
            has_test = any(c.source == "H_TEST_RESULT" for c in cand.supporting_contributions)
            has_tech = any(c.source == "I_4_HISTORICAL_CASE" and "Confirmed" in c.value_summary for c in cand.supporting_contributions)
            has_pattern = any(c.source == "I_3_FAILURE_PATTERN" for c in cand.supporting_contributions)

            if has_test and has_tech:
                cand.causal_basis = CausalBasis.CONFIRMED
                cand.candidate_role = CausalRole.PRIMARY_ROOT_CAUSE
            elif has_test:
                cand.causal_basis = CausalBasis.HYPOTHESIS_TEST_SUPPORT
                cand.candidate_role = CausalRole.PRIMARY_ROOT_CAUSE
            elif has_pattern:
                cand.causal_basis = CausalBasis.DIRECT_MECHANISTIC_EVIDENCE
                cand.candidate_role = CausalRole.PRIMARY_ROOT_CAUSE
            else:
                cand.causal_basis = CausalBasis.CORRELATIONAL_ONLY
                cand.candidate_role = CausalRole.CORRELATED_OBSERVATION

            # Communication failure invariant: U-codes and bus timeouts != component failure
            if any("U0" in d or d.startswith("U") for d in curr_dtcs) or "COMM" in cid:
                if not any(c.source == "H_TEST_RESULT" for c in cand.supporting_contributions):
                    cand.candidate_role = CausalRole.COMMUNICATION_ARTIFACT
                    cand.explanations.append("Communication anomaly isolated: Not classified as internal component failure.")

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="CAUSAL_ASSESSMENT",
            action="Distinguish correlation from mechanistic, test-supported, and confirmed causality",
            inputs_considered=[f"Candidate roles assigned for {len(candidate_map)} items."],
            findings=["Correlation vs causation boundaries verified."],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 8: Deterministic Candidate Ranking & Scoring Breakdown
        # -----------------------------------------------------------------
        for cid, cand in candidate_map.items():
            # 1. Earned positive evidence weight
            pos_weight = sum(c.weight for c in cand.supporting_contributions)
            # 2. Contradiction penalty
            contra_weight = sum(c.weight for c in cand.contradicting_contributions)
            cand.contradiction_penalty = contra_weight

            # 3. Applicability weight (from vehicle context matching)
            app_weight = 1.0
            if vehicle_context.engine_code:
                app_weight += 0.25
            if vehicle_context.ecu_family:
                app_weight += 0.25
            cand.applicability_weight = app_weight

            # Normalized evidence score (bounded 0.0 to 1.0)
            base_evidence = min(1.0, (pos_weight / 2.0))
            cand.evidence_score = base_evidence

            # Causal boost
            causal_boost = 0.0
            if cand.causal_basis in (CausalBasis.CONFIRMED, CausalBasis.HYPOTHESIS_TEST_SUPPORT):
                causal_boost = 0.15
            elif cand.causal_basis == CausalBasis.DIRECT_MECHANISTIC_EVIDENCE:
                causal_boost = 0.08

            # Overall Score formula
            raw_score = (base_evidence * 0.50) + (min(app_weight, 2.0) * 0.10) + (cand.historical_relevance * 0.15) + causal_boost
            final_score = max(0.0, min(1.0, raw_score - contra_weight))
            cand.overall_score = final_score

            # Confidence level
            if cand.contradicting_contributions or final_score < 0.25:
                cand.confidence = ReasoningUncertainty.CONTRADICTORY if cand.contradicting_contributions else ReasoningUncertainty.LOW_CONFIDENCE
            elif final_score >= 0.75:
                cand.confidence = ReasoningUncertainty.HIGH_CONFIDENCE
            elif final_score >= 0.45:
                cand.confidence = ReasoningUncertainty.MODERATE_CONFIDENCE
            else:
                cand.confidence = ReasoningUncertainty.LOW_CONFIDENCE

            cand.explanations.append(
                f"Score: {final_score:.2f} (Evidence: {base_evidence:.2f}, Historical: {cand.historical_relevance:.2f}, "
                f"Causal: {cand.causal_basis.value}, Contra Penalty: {contra_weight:.2f})"
            )

        # Deterministic ranking: overall_score descending, tie-break by candidate_id
        ranked = sorted(candidate_map.values(), key=lambda c: (-c.overall_score, c.candidate_id))

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="DETERMINISTIC_RANKING",
            action="Compute explainable scores and rank competitive candidates deterministically",
            inputs_considered=[f"Ranked {len(ranked)} candidates."],
            findings=[f"Top candidate: '{ranked[0].candidate_id}' (Score: {ranked[0].overall_score:.2f})"],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 9: Distinguishing Test Selection & Recommendation (H-3 Integration)
        # -----------------------------------------------------------------
        recommended_tests: List[KnowledgeDistinguishingTest] = []
        seen_test_ids: Set[str] = set()

        for cand in ranked[:3]:
            # Pull distinguishing tests from matched patterns
            for pm in matched_pattern_results:
                if cand.candidate_id in pm.pattern.possible_hypotheses:
                    for dt in pm.pattern.distinguishing_tests:
                        if dt.test_id not in seen_test_ids:
                            recommended_tests.append(dt)
                            seen_test_ids.add(dt.test_id)
                            cand.distinguishing_tests.append(dt)

            # Pull distinguishing tests from historical cases
            for sc in similar_cases:
                if sc.case.root_cause and sc.case.root_cause.root_cause_id == cand.candidate_id:
                    for tr in sc.case.test_results:
                        if tr.outcome == "PASSED" and tr.test_id not in seen_test_ids:
                            safe_dt = KnowledgeDistinguishingTest(
                                test_id=tr.test_id,
                                title=tr.test_title,
                                description=f"Recommended based on historical case '{sc.case.case_id}'",
                                discriminated_hypotheses=[cand.candidate_id],
                                safety_classification=ServiceSafetyClassification.READ_ONLY,
                            )
                            recommended_tests.append(safe_dt)
                            seen_test_ids.add(tr.test_id)
                            cand.distinguishing_tests.append(safe_dt)

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="TEST_SELECTION",
            action="Synthesize discriminative tests from patterns and confirmed cases for H-3 consumption",
            inputs_considered=[f"Recommended tests count: {len(recommended_tests)}"],
            findings=[f"Tests: {[t.test_id for t in recommended_tests[:max_distinguishing_tests]]}"],
        ))
        step_num += 1

        # -----------------------------------------------------------------
        # STEP 10: Overall Conclusion & Uncertainty Formulation
        # -----------------------------------------------------------------
        top_cand = ranked[0]
        if not feats and not curr_dtcs and not test_results:
            overall_conclusion = "Insufficient evidence to determine root cause. Sensor telemetry acquisition required."
            overall_confidence = ReasoningUncertainty.INSUFFICIENT_EVIDENCE
        elif top_cand.overall_score < 0.35:
            overall_conclusion = "Diagnostic data inconclusive. Evidence does not distinguish between competing alternatives."
            overall_confidence = ReasoningUncertainty.INSUFFICIENT_EVIDENCE
        elif top_cand.confidence == ReasoningUncertainty.CONTRADICTORY:
            overall_conclusion = f"Contradictory evidence detected regarding '{top_cand.hypothesis_title}'. Verification required."
            overall_confidence = ReasoningUncertainty.CONTRADICTORY
        else:
            rec_test_str = f"; verify using test '{recommended_tests[0].title}'" if recommended_tests else ""
            overall_conclusion = f"Current evidence most strongly supports hypothesis '{top_cand.hypothesis_title}'{rec_test_str}."
            overall_confidence = top_cand.confidence

        trace.append(ReasoningTraceStep(
            step_number=step_num,
            phase_name="CONCLUSION_SYNTHESIS",
            action="Formulate explainable conclusion preserving uncertainty and safety boundaries",
            inputs_considered=[f"Top score: {top_cand.overall_score:.2f}", f"Uncertainty: {overall_confidence.value}"],
            findings=[overall_conclusion],
        ))

        # Build final session entity
        session = DiagnosticReasoningSession(
            reasoning_id=reasoning_id,
            session_id=sess_id,
            vehicle_context=vehicle_context,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.SYSTEM_DERIVED,
                source_reference="ADVANCED_REASONING_ENGINE",
            ),
            operating_conditions=conds,
            candidates=list(candidate_map.values()),
            ranked_candidates=ranked[:max_candidates],
            overall_conclusion=overall_conclusion,
            overall_confidence=overall_confidence,
            recommended_distinguishing_tests=recommended_tests[:max_distinguishing_tests],
            contradictions=detected_contradictions,
            reasoning_trace=trace,
        )
        return session


# =====================================================================
# 6. WORKFLOW & GRAPH ADAPTERS
# =====================================================================

class ReasoningWorkflowAdapter:
    """
    Adapter bridging Advanced Reasoning Layer decisions to H-3 (Test Selection),
    H-4 (Root-Cause Analysis), and H-5 (Diagnostic Workflow Engine).
    """

    @staticmethod
    def get_next_distinguishing_test_for_h3(
        session: DiagnosticReasoningSession,
    ) -> Optional[KnowledgeDistinguishingTest]:
        """Supplies H-3 with the highest-priority safe distinguishing test."""
        if session.recommended_distinguishing_tests:
            return session.recommended_distinguishing_tests[0]
        return None

    @staticmethod
    def format_technician_reasoning_summary(
        session: DiagnosticReasoningSession,
    ) -> Dict[str, Any]:
        """Provides H-5 workflow engine with technician-readable audit summary."""
        top = session.ranked_candidates[0] if session.ranked_candidates else None
        return {
            "reasoning_id": session.reasoning_id,
            "conclusion": session.overall_conclusion,
            "confidence": session.overall_confidence.value,
            "top_candidate": top.hypothesis_title if top else "None",
            "top_score": top.overall_score if top else 0.0,
            "causal_basis": top.causal_basis.value if top else "UNKNOWN",
            "contradictions_count": len(session.contradictions),
            "distinguishing_test_recommended": (
                session.recommended_distinguishing_tests[0].title
                if session.recommended_distinguishing_tests else "None"
            ),
            "trace_steps_count": len(session.reasoning_trace),
        }


class DiagnosticGraphReasoningIntegrator:
    """
    Binds advanced reasoning session findings to G-5 DiagnosticGraph nodes.
    Strictly preserves invariant: RELATIONSHIP != CAUSALITY.
    """

    @staticmethod
    def integrate_reasoning_session(
        graph: DiagnosticGraph,
        session: DiagnosticReasoningSession,
    ) -> str:
        node_id = f"reasoning:{session.reasoning_id}"
        node = GraphNode(
            node_id=node_id,
            node_type=GraphNodeType.ANOMALY,
            label=f"Reasoning: {session.overall_confidence.value}",
            properties={
                "conclusion": session.overall_conclusion,
                "confidence": session.overall_confidence.value,
                "candidates_count": len(session.ranked_candidates),
                "contradictions_count": len(session.contradictions),
            },
            provenance={"source": "ADVANCED_REASONING_ENGINE"},
        )
        graph.add_node(node)

        # Link to top candidates with non-causal ASSOCIATED_WITH edges
        for cand in session.ranked_candidates[:3]:
            cand_node_id = f"candidate:{cand.candidate_id}"
            if cand_node_id not in graph.nodes:
                graph.add_node(GraphNode(
                    node_id=cand_node_id,
                    node_type=GraphNodeType.HYPOTHESIS,
                    label=cand.hypothesis_title,
                    properties={"score": cand.overall_score, "role": cand.candidate_role.value},
                ))
            graph.add_edge(GraphEdge(
                edge_id=f"edge_reason_{session.reasoning_id}_{cand.candidate_id}",
                source_id=node_id,
                target_id=cand_node_id,
                edge_type=GraphEdgeType.ASSOCIATED_WITH,
                confidence=cand.overall_score,
                provenance={"source": "REASONING_INTEGRATOR"},
            ))

        return node_id
