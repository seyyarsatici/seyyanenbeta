# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase I-4: Historical Case Analysis Subsystem
=============================================================================
This module implements Phase I-4 of the Seyyanen diagnostic architecture.
It establishes a structured, empirical Historical Case Analysis layer that
allows Seyyanen to evaluate previous diagnostic cases as contextual evidence
and operational experience when analyzing new vehicle faults.

Strict Architectural Invariants:
  1. HISTORICAL CASES ARE EVIDENCE, NOT PROOF:
     A past successful repair never guarantees the same root cause in the
     current vehicle. History guides investigation; it does not replace current data.
  2. DTC != ROOT CAUSE & PATTERN != ROOT CAUSE:
     Codes and failure patterns remain empirical clues, not defective components.
  3. CONTRADICTORY EVIDENCE DOMINANCE:
     If current vehicle evidence contradicts a past case's confirmed root cause,
     the historical case's relevance is actively penalized and downgraded.
  4. COMMUNICATION FAULT != COMPONENT FAILURE:
     Past bus timeouts or lost frames are strictly isolated as network/power issues,
     never as evidence of internal defective electronics.
  5. NO AUTOMATIC KNOWLEDGE PROMOTION:
     Cases remain cases. They are never automatically promoted into active
     I-1 knowledge base entries or I-3 failure patterns without controlled validation.
  6. NO UNCONTROLLED FLEET LEARNING OR MACHINE LEARNING:
     Zero model retraining pipelines, zero unsupervised statistical fleet generalization.
  7. STRICTLY READ-ONLY SAFETY GATING:
     I-4 is strictly an analytical experience layer; zero diagnostic actuation,
     DID writing, programming session entry, or DTC clearing.
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

# Integration imports from C, D, G, H, I-1, I-2, and I-3 layers
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
)
from vehicle_ecu_knowledge import (
    ProgressiveVehicleIdentity,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    ECUKnowledgeProfile,
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

logger = logging.getLogger("seyyanen.historical_case_analysis")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class CaseLifecycle(str, enum.Enum):
    """Lifecycle state of a historical diagnostic case."""
    OPEN = "OPEN"                                  # Active ongoing diagnosis
    ANALYZED = "ANALYZED"                          # Analysis complete, hypothesis formed
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"  # Awaiting technician verification
    CONFIRMED = "CONFIRMED"                        # Technician confirmed root cause & repair
    REJECTED = "REJECTED"                          # Investigated and rejected / disproved
    CLOSED = "CLOSED"                              # Completed and archived case
    ARCHIVED = "ARCHIVED"                          # Long-term historical record


class CaseMatchGrade(str, enum.Enum):
    """Calibrated match quality grade of a historical case similarity evaluation."""
    HIGH_SIMILARITY = "HIGH_SIMILARITY"            # Score >= 0.80, exact/high context match
    MODERATE_SIMILARITY = "MODERATE_SIMILARITY"    # 0.50 <= Score < 0.80
    LOW_SIMILARITY = "LOW_SIMILARITY"              # 0.30 <= Score < 0.50
    INSUFFICIENT_SIMILARITY = "INSUFFICIENT_SIMILARITY" # Score < 0.30 or contradiction


class CaseRelationshipType(str, enum.Enum):
    """Explicit relationship between historical diagnostic cases."""
    SIMILAR_TO = "SIMILAR_TO"                      # General contextual similarity
    SUPERSEDES = "SUPERSEDES"                      # Corrected version replacing older case
    CONTRADICTS = "CONTRADICTS"                    # Conflicting diagnostic findings
    VALIDATES = "VALIDATES"                        # Confirms findings of another case
    DISPROVES = "DISPROVES"                        # Disproves hypothesis in another case
    RELATED_TO = "RELATED_TO"                      # Common vehicle / system association


class RootCauseConfidenceGrade(str, enum.Enum):
    """Degree of validation of the identified root cause."""
    CONFIRMED_TECHNICIAN = "CONFIRMED_TECHNICIAN"  # Physically inspected, verified, repaired
    PROBABLE_DIAGNOSIS = "PROBABLE_DIAGNOSIS"      # Strong diagnostic evidence, unconfirmed
    UNCONFIRMED_HYPOTHESIS = "UNCONFIRMED_HYPOTHESIS" # Candidate explanation only
    REJECTED_HYPOTHESIS = "REJECTED_HYPOTHESIS"    # Tested and disproved hypothesis


# =====================================================================
# 2. HISTORICAL CASE DATA MODELS
# =====================================================================

@dataclass
class CaseECUContext:
    """ECU identity, calibration, and hardware context in a historical case."""
    target_ecu: str                                # e.g. "ECM", "TCM", "ABS"
    ecu_family: Optional[str] = None               # e.g. "DELPHI_MT80", "SIMTEC76"
    hardware_part_number: Optional[str] = None     # e.g. "25186182"
    software_version: Optional[str] = None         # e.g. "CAL_ID_968001"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_ecu": self.target_ecu,
            "ecu_family": self.ecu_family,
            "hardware_part_number": self.hardware_part_number,
            "software_version": self.software_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseECUContext":
        return cls(
            target_ecu=data["target_ecu"],
            ecu_family=data.get("ecu_family"),
            hardware_part_number=data.get("hardware_part_number"),
            software_version=data.get("software_version"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class CaseDTCRecord:
    """Historical DTC record with target ECU context."""
    dtc_code: str
    target_ecu: str
    status: Optional[str] = "CONFIRMED"
    freeze_frame: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dtc_code": self.dtc_code,
            "target_ecu": self.target_ecu,
            "status": self.status,
            "freeze_frame": dict(self.freeze_frame),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseDTCRecord":
        return cls(
            dtc_code=data["dtc_code"],
            target_ecu=data.get("target_ecu", "ECM"),
            status=data.get("status", "CONFIRMED"),
            freeze_frame=dict(data.get("freeze_frame", {})),
        )


@dataclass
class CaseTestResult:
    """Recorded diagnostic test performed during a historical case."""
    test_id: str
    test_title: str
    target_ecu: str
    outcome: str                                   # "PASSED", "FAILED", "INCONCLUSIVE"
    observations: str = ""
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY

    def __post_init__(self):
        # Strict safety invariant: Historical test records must preserve read-only constraint
        if self.safety_classification != ServiceSafetyClassification.READ_ONLY:
            raise ValueError(
                f"Safety Violation: Historical test result '{self.test_id}' must have "
                f"safety_classification READ_ONLY."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "test_title": self.test_title,
            "target_ecu": self.target_ecu,
            "outcome": self.outcome,
            "observations": self.observations,
            "safety_classification": self.safety_classification.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseTestResult":
        return cls(
            test_id=data["test_id"],
            test_title=data["test_title"],
            target_ecu=data.get("target_ecu", "ECM"),
            outcome=data.get("outcome", "INCONCLUSIVE"),
            observations=data.get("observations", ""),
            safety_classification=ServiceSafetyClassification(data.get("safety_classification", "READ_ONLY")),
        )


@dataclass
class CaseRootCause:
    """Confirmed or investigated root cause of a historical case."""
    root_cause_id: str
    component_or_system: str
    mechanism_description: str
    confidence_grade: RootCauseConfidenceGrade = RootCauseConfidenceGrade.PROBABLE_DIAGNOSIS
    affected_ecu: str = "ECM"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_cause_id": self.root_cause_id,
            "component_or_system": self.component_or_system,
            "mechanism_description": self.mechanism_description,
            "confidence_grade": self.confidence_grade.value,
            "affected_ecu": self.affected_ecu,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseRootCause":
        return cls(
            root_cause_id=data["root_cause_id"],
            component_or_system=data["component_or_system"],
            mechanism_description=data.get("mechanism_description", ""),
            confidence_grade=RootCauseConfidenceGrade(data.get("confidence_grade", "PROBABLE_DIAGNOSIS")),
            affected_ecu=data.get("affected_ecu", "ECM"),
        )


@dataclass
class CaseTechnicianConfirmation:
    """Audit record of physical technician inspection and diagnosis confirmation."""
    is_confirmed: bool
    technician_id: str
    confirmation_timestamp: float = field(default_factory=time.time)
    inspection_notes: str = ""
    diagnostic_confidence: KnowledgeConfidence = KnowledgeConfidence.HIGH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_confirmed": self.is_confirmed,
            "technician_id": self.technician_id,
            "confirmation_timestamp": round(self.confirmation_timestamp, 3),
            "inspection_notes": self.inspection_notes,
            "diagnostic_confidence": self.diagnostic_confidence.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseTechnicianConfirmation":
        return cls(
            is_confirmed=bool(data["is_confirmed"]),
            technician_id=data["technician_id"],
            confirmation_timestamp=float(data.get("confirmation_timestamp", time.time())),
            inspection_notes=data.get("inspection_notes", ""),
            diagnostic_confidence=KnowledgeConfidence(data.get("diagnostic_confidence", "HIGH")),
        )


@dataclass
class CaseRepairOutcome:
    """Action taken and physical parts replaced during repair."""
    repair_action: str
    parts_replaced: List[str] = field(default_factory=list)
    repair_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repair_action": self.repair_action,
            "parts_replaced": list(self.parts_replaced),
            "repair_timestamp": round(self.repair_timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseRepairOutcome":
        return cls(
            repair_action=data["repair_action"],
            parts_replaced=list(data.get("parts_replaced", [])),
            repair_timestamp=float(data.get("repair_timestamp", time.time())),
        )


@dataclass
class PostRepairVerification:
    """Verification record confirming whether the repair resolved the problem."""
    verification_performed: bool
    original_anomaly_resolved: bool
    dtc_cleared: bool
    telemetry_normalized: bool
    notes: str = ""
    verification_confidence: KnowledgeConfidence = KnowledgeConfidence.HIGH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verification_performed": self.verification_performed,
            "original_anomaly_resolved": self.original_anomaly_resolved,
            "dtc_cleared": self.dtc_cleared,
            "telemetry_normalized": self.telemetry_normalized,
            "notes": self.notes,
            "verification_confidence": self.verification_confidence.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostRepairVerification":
        return cls(
            verification_performed=bool(data["verification_performed"]),
            original_anomaly_resolved=bool(data["original_anomaly_resolved"]),
            dtc_cleared=bool(data["dtc_cleared"]),
            telemetry_normalized=bool(data["telemetry_normalized"]),
            notes=data.get("notes", ""),
            verification_confidence=KnowledgeConfidence(data.get("verification_confidence", "HIGH")),
        )


@dataclass
class CaseRelationship:
    """Documented relationship between historical cases."""
    target_case_id: str
    relationship_type: CaseRelationshipType
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_case_id": self.target_case_id,
            "relationship_type": self.relationship_type.value,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseRelationship":
        return cls(
            target_case_id=data["target_case_id"],
            relationship_type=CaseRelationshipType(data["relationship_type"]),
            rationale=data.get("rationale", ""),
        )


# =====================================================================
# 3. PRIMARY HISTORICAL CASE ENTITY
# =====================================================================

@dataclass
class HistoricalDiagnosticCase:
    """
    Structured record of a completed or investigated diagnostic case.
    Preserves context, evidence, hypotheses, tests, root causes, technician
    confirmations, repair outcomes, and post-repair verifications.
    """
    case_id: str
    title: str
    summary: str
    vehicle_context: VehicleContext
    provenance: KnowledgeProvenance
    ecu_contexts: Dict[str, CaseECUContext] = field(default_factory=dict)
    operating_conditions: List[OperatingCondition] = field(default_factory=list)
    active_dtcs: List[CaseDTCRecord] = field(default_factory=list)
    observed_features: Dict[str, float] = field(default_factory=dict)
    matched_pattern_ids: List[str] = field(default_factory=list)
    candidate_hypotheses: List[str] = field(default_factory=list)
    test_results: List[CaseTestResult] = field(default_factory=list)
    root_cause: Optional[CaseRootCause] = None
    technician_confirmation: Optional[CaseTechnicianConfirmation] = None
    repair_outcome: Optional[CaseRepairOutcome] = None
    post_repair_verification: Optional[PostRepairVerification] = None
    relationships: List[CaseRelationship] = field(default_factory=list)
    lifecycle: CaseLifecycle = CaseLifecycle.CLOSED
    version: int = 1
    is_dtc_free: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.case_id or not str(self.case_id).strip():
            raise ValueError("Historical diagnostic case must have a valid non-empty case_id.")
        # Safety invariant: Ensure all test results are READ_ONLY
        for tr in self.test_results:
            if tr.safety_classification != ServiceSafetyClassification.READ_ONLY:
                raise ValueError(
                    f"Safety Violation: Historical test result '{tr.test_id}' in case "
                    f"'{self.case_id}' must be READ_ONLY."
                )

    def is_technician_confirmed(self) -> bool:
        """Returns True if case was confirmed by a physical technician inspection."""
        return (
            self.technician_confirmation is not None
            and self.technician_confirmation.is_confirmed
        )

    def is_successful_repair(self) -> bool:
        """Returns True if case repair was verified and original anomaly resolved."""
        return (
            self.post_repair_verification is not None
            and self.post_repair_verification.verification_performed
            and self.post_repair_verification.original_anomaly_resolved
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "summary": self.summary,
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
            "active_dtcs": [d.to_dict() for d in self.active_dtcs],
            "observed_features": dict(self.observed_features),
            "matched_pattern_ids": list(self.matched_pattern_ids),
            "candidate_hypotheses": list(self.candidate_hypotheses),
            "test_results": [tr.to_dict() for tr in self.test_results],
            "root_cause": self.root_cause.to_dict() if self.root_cause else None,
            "technician_confirmation": self.technician_confirmation.to_dict() if self.technician_confirmation else None,
            "repair_outcome": self.repair_outcome.to_dict() if self.repair_outcome else None,
            "post_repair_verification": self.post_repair_verification.to_dict() if self.post_repair_verification else None,
            "relationships": [r.to_dict() for r in self.relationships],
            "lifecycle": self.lifecycle.value,
            "version": self.version,
            "is_dtc_free": self.is_dtc_free,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoricalDiagnosticCase":
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
            case_id=data["case_id"],
            title=data["title"],
            summary=data.get("summary", ""),
            vehicle_context=vc,
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            ecu_contexts={k: CaseECUContext.from_dict(v) for k, v in data.get("ecu_contexts", {}).items()},
            operating_conditions=[OperatingCondition(oc) for oc in data.get("operating_conditions", [])],
            active_dtcs=[CaseDTCRecord.from_dict(d) for d in data.get("active_dtcs", [])],
            observed_features=dict(data.get("observed_features", {})),
            matched_pattern_ids=list(data.get("matched_pattern_ids", [])),
            candidate_hypotheses=list(data.get("candidate_hypotheses", [])),
            test_results=[CaseTestResult.from_dict(tr) for tr in data.get("test_results", [])],
            root_cause=CaseRootCause.from_dict(data["root_cause"]) if data.get("root_cause") else None,
            technician_confirmation=CaseTechnicianConfirmation.from_dict(data["technician_confirmation"]) if data.get("technician_confirmation") else None,
            repair_outcome=CaseRepairOutcome.from_dict(data["repair_outcome"]) if data.get("repair_outcome") else None,
            post_repair_verification=PostRepairVerification.from_dict(data["post_repair_verification"]) if data.get("post_repair_verification") else None,
            relationships=[CaseRelationship.from_dict(r) for r in data.get("relationships", [])],
            lifecycle=CaseLifecycle(data.get("lifecycle", "CLOSED")),
            version=int(data.get("version", 1)),
            is_dtc_free=bool(data.get("is_dtc_free", False)),
            metadata=dict(data.get("metadata", {})),
        )


# =====================================================================
# 4. CASE SIMILARITY RESULT & EXPLAINABILITY
# =====================================================================

@dataclass
class CaseSimilarityResult:
    """
    Transparent, explainable similarity match between a historical case and
    the current diagnostic context.
    """
    case: HistoricalDiagnosticCase
    overall_similarity: float                      # 0.0 to 1.0
    match_grade: CaseMatchGrade
    dimension_scores: Dict[str, float]             # Decomposed score by dimension
    common_evidence: List[str] = field(default_factory=list)
    divergent_evidence: List[str] = field(default_factory=list)
    contradictions_detected: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)
    relevance_as_evidence: float = 0.0             # Weighted relevance for reasoning

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "case_title": self.case.title,
            "overall_similarity": round(self.overall_similarity, 3),
            "match_grade": self.match_grade.value,
            "dimension_scores": {k: round(v, 3) for k, v in self.dimension_scores.items()},
            "common_evidence": list(self.common_evidence),
            "divergent_evidence": list(self.divergent_evidence),
            "contradictions_detected": list(self.contradictions_detected),
            "explanations": list(self.explanations),
            "relevance_as_evidence": round(self.relevance_as_evidence, 3),
            "is_technician_confirmed": self.case.is_technician_confirmed(),
            "root_cause": self.case.root_cause.to_dict() if self.case.root_cause else None,
            "repair_outcome": self.case.repair_outcome.to_dict() if self.case.repair_outcome else None,
        }


# =====================================================================
# 5. HISTORICAL CASE REPOSITORY & SIMILARITY ENGINE
# =====================================================================

class HistoricalCaseRepository:
    """
    Deterministic repository and similarity matcher for Historical Diagnostic Cases.
    Supports candidate pre-filtering, multi-dimensional scoring, contradiction
    downgrading, and bounded queries.
    """

    def __init__(self):
        self._cases: Dict[str, HistoricalDiagnosticCase] = {}
        # Multi-key indexes for bounded candidate pre-filtering
        self._manufacturer_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._engine_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._ecu_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._dtc_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._pattern_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._lifecycle_index: Dict[CaseLifecycle, Set[str]] = collections.defaultdict(set)

    def add_case(self, case: HistoricalDiagnosticCase) -> None:
        """Registers a case in the repository and updates multi-key indexes."""
        cid = case.case_id
        if cid in self._cases:
            self._remove_from_indexes(cid)

        self._cases[cid] = case

        # Update Manufacturer Index
        if case.vehicle_context.manufacturer:
            self._manufacturer_index[case.vehicle_context.manufacturer.strip().upper()].add(cid)

        # Update Engine Index
        if case.vehicle_context.engine_code:
            self._engine_index[case.vehicle_context.engine_code.strip().upper()].add(cid)

        # Update ECU Index
        if case.vehicle_context.ecu_family:
            self._ecu_index[case.vehicle_context.ecu_family.strip().upper()].add(cid)
        for ecu_ctx in case.ecu_contexts.values():
            if ecu_ctx.ecu_family:
                self._ecu_index[ecu_ctx.ecu_family.strip().upper()].add(cid)

        # Update DTC Index
        for dtc in case.active_dtcs:
            self._dtc_index[dtc.dtc_code.strip().upper()].add(cid)

        # Update Pattern Index
        for pat_id in case.matched_pattern_ids:
            self._pattern_index[pat_id.strip()].add(cid)

        # Update Lifecycle Index
        self._lifecycle_index[case.lifecycle].add(cid)

    def get_case(self, case_id: str) -> Optional[HistoricalDiagnosticCase]:
        return self._cases.get(case_id)

    def update_case(self, case: HistoricalDiagnosticCase) -> None:
        """Updates an existing case in place while maintaining indexes."""
        self.add_case(case)

    def close_case(
        self,
        case_id: str,
        root_cause: CaseRootCause,
        repair_outcome: CaseRepairOutcome,
        technician_confirmation: CaseTechnicianConfirmation,
        post_repair_verification: Optional[PostRepairVerification] = None,
    ) -> HistoricalDiagnosticCase:
        """Marks a case as CONFIRMED and CLOSED with complete audit data."""
        case = self._cases.get(case_id)
        if not case:
            raise KeyError(f"Case '{case_id}' not found in repository.")

        case.root_cause = root_cause
        case.repair_outcome = repair_outcome
        case.technician_confirmation = technician_confirmation
        case.post_repair_verification = post_repair_verification
        case.lifecycle = CaseLifecycle.CONFIRMED if technician_confirmation.is_confirmed else CaseLifecycle.CLOSED
        case.version += 1

        self.update_case(case)
        return case

    def list_cases(
        self,
        lifecycle: Optional[CaseLifecycle] = None,
    ) -> List[HistoricalDiagnosticCase]:
        res = list(self._cases.values())
        if lifecycle:
            res = [c for c in res if c.lifecycle == lifecycle]
        return res

    def find_similar_cases(
        self,
        vehicle_context: Optional[VehicleContext] = None,
        observed_features: Optional[ObservedFeatureSet] = None,
        active_dtcs: Optional[List[str]] = None,
        matched_patterns: Optional[List[str]] = None,
        operating_conditions: Optional[List[OperatingCondition]] = None,
        current_contradictions: Optional[List[str]] = None,
        max_results: int = 10,
        max_candidates: int = 100,
    ) -> List[CaseSimilarityResult]:
        """
        Deterministic, multi-dimensional historical case similarity engine.
        Evaluates:
          1. Vehicle identity (manufacturer, model, engine, transmission)
          2. ECU family & software calibration
          3. Operating conditions
          4. Matched failure patterns (I-3 integration)
          5. Active DTCs (ECU-isolated)
          6. Telemetry features
          7. Technician confirmation bonus
          8. Contradictory evidence penalty (actively reduces score & relevance)
        """
        candidate_ids = self._prefilter_candidates(
            vehicle_context=vehicle_context,
            active_dtcs=active_dtcs,
            matched_patterns=matched_patterns,
            max_candidates=max_candidates,
        )

        results: List[CaseSimilarityResult] = []

        curr_dtc_set = {d.strip().upper() for d in (active_dtcs or [])}
        curr_pat_set = set(matched_patterns or [])
        curr_cond_set = set(operating_conditions or [])
        curr_contra_set = set(current_contradictions or [])

        curr_features = observed_features.features if observed_features else {}

        for cid in candidate_ids:
            case = self._cases[cid]
            scores: Dict[str, float] = {}
            common_ev: List[str] = []
            divergent_ev: List[str] = []
            contradictions: List[str] = []
            explanations: List[str] = []

            # -------------------------------------------------------------
            # 1. Vehicle & Powertrain Similarity (Max 0.40)
            # -------------------------------------------------------------
            veh_score = 0.0
            if vehicle_context and case.vehicle_context:
                cv = vehicle_context
                hv = case.vehicle_context

                # Manufacturer
                if cv.manufacturer and hv.manufacturer:
                    if cv.manufacturer.strip().upper() == hv.manufacturer.strip().upper():
                        veh_score += 0.12
                        common_ev.append(f"Manufacturer: {cv.manufacturer}")
                    else:
                        divergent_ev.append(f"Manufacturer mismatch ({cv.manufacturer} vs {hv.manufacturer})")

                # Model
                if cv.model and hv.model:
                    if cv.model.strip().upper() == hv.model.strip().upper():
                        veh_score += 0.12
                        common_ev.append(f"Model: {cv.model}")
                    else:
                        divergent_ev.append(f"Model mismatch ({cv.model} vs {hv.model})")

                # Engine
                if cv.engine_code and hv.engine_code:
                    if cv.engine_code.strip().upper() == hv.engine_code.strip().upper():
                        veh_score += 0.18
                        common_ev.append(f"Engine: {cv.engine_code}")
                    else:
                        divergent_ev.append(f"Engine mismatch ({cv.engine_code} vs {hv.engine_code})")

                # Transmission
                if cv.transmission and hv.transmission:
                    if cv.transmission.strip().upper() == hv.transmission.strip().upper():
                        veh_score += 0.05
                        common_ev.append(f"Transmission: {cv.transmission}")

                # ECU Family & Software Calibration
                if cv.ecu_family and hv.ecu_family:
                    if cv.ecu_family.strip().upper() == hv.ecu_family.strip().upper():
                        veh_score += 0.08
                        common_ev.append(f"ECU Family: {cv.ecu_family}")
                        if cv.software_id and hv.software_id:
                            if cv.software_id.strip().upper() == hv.software_id.strip().upper():
                                veh_score += 0.05
                                common_ev.append(f"Calibration ID: {cv.software_id}")

            scores["vehicle_powertrain"] = min(0.60, veh_score)

            # -------------------------------------------------------------
            # 2. Pattern Similarity (Max 0.20)
            # -------------------------------------------------------------
            pat_score = 0.0
            hist_pats = set(case.matched_pattern_ids)
            if curr_pat_set and hist_pats:
                intersect = curr_pat_set.intersection(hist_pats)
                if intersect:
                    ratio = len(intersect) / max(len(curr_pat_set), len(hist_pats))
                    pat_score = ratio * 0.20
                    for p in intersect:
                        common_ev.append(f"Matched Pattern: {p}")
            scores["pattern_similarity"] = pat_score

            # -------------------------------------------------------------
            # 3. DTC Similarity (Max 0.20)
            # -------------------------------------------------------------
            dtc_score = 0.0
            hist_dtc_set = {d.dtc_code.strip().upper() for d in case.active_dtcs}
            if curr_dtc_set and hist_dtc_set:
                intersect_dtc = curr_dtc_set.intersection(hist_dtc_set)
                if intersect_dtc:
                    dtc_score = (len(intersect_dtc) / max(len(curr_dtc_set), len(hist_dtc_set))) * 0.20
                    for d in intersect_dtc:
                        common_ev.append(f"DTC: {d}")
            elif not curr_dtc_set and case.is_dtc_free:
                # Both cases are DTC-free telemetry anomalies
                dtc_score = 0.20
                common_ev.append("DTC-free diagnostic scenario")
            scores["dtc_similarity"] = dtc_score

            # -------------------------------------------------------------
            # 4. Operating Conditions & Telemetry Features (Max 0.20)
            # -------------------------------------------------------------
            context_score = 0.0
            hist_cond_set = set(case.operating_conditions)
            if curr_cond_set and hist_cond_set:
                cond_intersect = curr_cond_set.intersection(hist_cond_set)
                if cond_intersect:
                    context_score += 0.08
                    for c in cond_intersect:
                        common_ev.append(f"Condition: {c.value}")

            # Feature value correlation
            if curr_features and case.observed_features:
                shared_keys = set(curr_features.keys()).intersection(set(case.observed_features.keys()))
                if shared_keys:
                    match_count = 0
                    for k in shared_keys:
                        v1 = curr_features[k]
                        v2 = case.observed_features[k]
                        # Within 20% relative tolerance
                        if abs(v1 - v2) <= (max(abs(v1), abs(v2)) * 0.25 + 0.1):
                            match_count += 1
                    feature_ratio = match_count / len(shared_keys)
                    context_score += (feature_ratio * 0.12)
                    common_ev.append(f"Telemetry feature match ratio: {feature_ratio:.2f}")

            scores["operating_context"] = min(0.20, context_score)

            # -------------------------------------------------------------
            # 5. Raw Similarity Computation (Bounded [0.0, 1.0])
            # -------------------------------------------------------------
            raw_similarity = min(1.0, sum(scores.values()))

            # -------------------------------------------------------------
            # 6. Contradiction Evaluation (Negative Evidence Penalty)
            # -------------------------------------------------------------
            contra_penalty = 0.0
            if case.root_cause and case.root_cause.root_cause_id in curr_contra_set:
                contra_penalty += 0.55
                contradictions.append(
                    f"Current telemetry actively contradicts historical root cause '{case.root_cause.root_cause_id}'."
                )

            # Also check if case had rejected hypothesis matching current hypothesis
            if case.root_cause and case.root_cause.confidence_grade == RootCauseConfidenceGrade.REJECTED_HYPOTHESIS:
                explanations.append(f"Note: Case '{case.case_id}' recorded a REJECTED hypothesis.")

            final_similarity = max(0.0, min(1.0, raw_similarity - contra_penalty))

            # -------------------------------------------------------------
            # 7. Relevance As Evidence Calculation
            # -------------------------------------------------------------
            # Technician-confirmed outcome and successful repair elevate evidential weight
            relevance = final_similarity
            if contradictions:
                relevance *= 0.30
                explanations.append("Severely discounted relevance: Contradicted by current evidence.")
            elif case.is_technician_confirmed():
                relevance *= 1.25
                explanations.append("Elevated relevance: Technician-confirmed physical diagnosis.")
            elif case.lifecycle == CaseLifecycle.REJECTED:
                relevance *= 0.60
                explanations.append("Discounted relevance: Rejected historical hypothesis.")
            else:
                relevance *= 0.85
                explanations.append("Moderate relevance: Unconfirmed automated diagnostic finding.")

            relevance = max(0.0, min(1.0, relevance))

            # -------------------------------------------------------------
            # 8. Determine Match Grade
            # -------------------------------------------------------------
            if contradictions or final_similarity < 0.30:
                grade = CaseMatchGrade.INSUFFICIENT_SIMILARITY
            elif final_similarity >= 0.80:
                grade = CaseMatchGrade.HIGH_SIMILARITY
            elif final_similarity >= 0.50:
                grade = CaseMatchGrade.MODERATE_SIMILARITY
            else:
                grade = CaseMatchGrade.LOW_SIMILARITY

            explanations.append(
                f"Similarity: {final_similarity:.2f} (Grade: {grade.value}, Relevance: {relevance:.2f})"
            )

            result = CaseSimilarityResult(
                case=case,
                overall_similarity=final_similarity,
                match_grade=grade,
                dimension_scores=scores,
                common_evidence=common_ev,
                divergent_evidence=divergent_ev,
                contradictions_detected=contradictions,
                explanations=explanations,
                relevance_as_evidence=relevance,
            )
            results.append(result)

        # Deterministic sorting: highest relevance descending, then similarity, then case_id
        results.sort(key=lambda r: (-r.relevance_as_evidence, -r.overall_similarity, r.case.case_id))
        return results[:max_results]

    def _prefilter_candidates(
        self,
        vehicle_context: Optional[VehicleContext],
        active_dtcs: Optional[List[str]],
        matched_patterns: Optional[List[str]],
        max_candidates: int,
    ) -> Set[str]:
        """Pre-filters candidate cases via indexes to bound similarity calculations."""
        candidates: Set[str] = set()

        # Engine index
        if vehicle_context and vehicle_context.engine_code:
            eng_cands = self._engine_index.get(vehicle_context.engine_code.strip().upper(), set())
            candidates.update(eng_cands)

        # Manufacturer index
        if vehicle_context and vehicle_context.manufacturer:
            mfg_cands = self._manufacturer_index.get(vehicle_context.manufacturer.strip().upper(), set())
            candidates.update(mfg_cands)

        # DTC index
        if active_dtcs:
            for dtc in active_dtcs:
                candidates.update(self._dtc_index.get(dtc.strip().upper(), set()))

        # Pattern index
        if matched_patterns:
            for pat in matched_patterns:
                candidates.update(self._pattern_index.get(pat.strip(), set()))

        # Fallback: if candidate set is empty and repository is small, check all
        if not candidates:
            candidates = set(self._cases.keys())

        # Bound candidates
        if len(candidates) > max_candidates:
            candidates = set(sorted(list(candidates))[:max_candidates])

        return candidates

    def _remove_from_indexes(self, case_id: str) -> None:
        """Cleans multi-key indexes before replacing a case."""
        case = self._cases.get(case_id)
        if not case:
            return
        if case.vehicle_context.manufacturer:
            self._manufacturer_index[case.vehicle_context.manufacturer.strip().upper()].discard(case_id)
        if case.vehicle_context.engine_code:
            self._engine_index[case.vehicle_context.engine_code.strip().upper()].discard(case_id)
        if case.vehicle_context.ecu_family:
            self._ecu_index[case.vehicle_context.ecu_family.strip().upper()].discard(case_id)
        for ecu_ctx in case.ecu_contexts.values():
            if ecu_ctx.ecu_family:
                self._ecu_index[ecu_ctx.ecu_family.strip().upper()].discard(case_id)
        for dtc in case.active_dtcs:
            self._dtc_index[dtc.dtc_code.strip().upper()].discard(case_id)
        for pat in case.matched_pattern_ids:
            self._pattern_index[pat.strip()].discard(case_id)
        self._lifecycle_index[case.lifecycle].discard(case_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cases": [c.to_dict() for c in self._cases.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoricalCaseRepository":
        repo = cls()
        for c_dict in data.get("cases", []):
            case = HistoricalDiagnosticCase.from_dict(c_dict)
            repo.add_case(case)
        return repo


# =====================================================================
# 6. WORKFLOW & GRAPH ADAPTERS
# =====================================================================

class HistoricalCaseWorkflowAdapter:
    """
    Adapter supplying H-3 (Test Selection), H-4 (Root-Cause Analysis),
    and H-5 (Diagnostic Workflow Engine) with historical case experience.
    """

    def __init__(self, repository: HistoricalCaseRepository):
        self.repository = repository

    def get_historical_distinguishing_tests(
        self,
        vehicle_context: Optional[VehicleContext] = None,
        observed_features: Optional[ObservedFeatureSet] = None,
        matched_patterns: Optional[List[str]] = None,
    ) -> List[CaseTestResult]:
        """
        Supplies H-3 Evidence-Driven Test Selector with safe distinguishing tests
        that successfully resolved similar confirmed historical cases.
        """
        similar = self.repository.find_similar_cases(
            vehicle_context=vehicle_context,
            observed_features=observed_features,
            matched_patterns=matched_patterns,
            max_results=5,
        )
        recommended_tests: List[CaseTestResult] = []
        seen_test_ids: Set[str] = set()

        for sim in similar:
            if sim.match_grade in (CaseMatchGrade.HIGH_SIMILARITY, CaseMatchGrade.MODERATE_SIMILARITY):
                for tr in sim.case.test_results:
                    if tr.outcome == "PASSED" and tr.test_id not in seen_test_ids:
                        recommended_tests.append(tr)
                        seen_test_ids.add(tr.test_id)

        return recommended_tests

    def get_historical_root_cause_context(
        self,
        vehicle_context: Optional[VehicleContext] = None,
        observed_features: Optional[ObservedFeatureSet] = None,
        active_dtcs: Optional[List[str]] = None,
        matched_patterns: Optional[List[str]] = None,
        current_contradictions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Supplies H-4 Root-Cause Analyzer with historical confirmed outcomes
        as contextual evidence (never as unquestioned proof).
        """
        similar = self.repository.find_similar_cases(
            vehicle_context=vehicle_context,
            observed_features=observed_features,
            active_dtcs=active_dtcs,
            matched_patterns=matched_patterns,
            current_contradictions=current_contradictions,
            max_results=5,
        )
        context_items: List[Dict[str, Any]] = []
        for sim in similar:
            if sim.case.root_cause:
                context_items.append({
                    "case_id": sim.case.case_id,
                    "root_cause_id": sim.case.root_cause.root_cause_id,
                    "component": sim.case.root_cause.component_or_system,
                    "mechanism": sim.case.root_cause.mechanism_description,
                    "is_technician_confirmed": sim.case.is_technician_confirmed(),
                    "similarity": sim.overall_similarity,
                    "relevance": sim.relevance_as_evidence,
                    "match_grade": sim.match_grade.value,
                    "explanations": sim.explanations,
                })
        return context_items


class DiagnosticGraphCaseIntegrator:
    """
    Binds historical cases to the G-5 DiagnosticGraph.
    Strictly preserves invariant: RELATIONSHIP != CAUSALITY.
    """

    @staticmethod
    def integrate_historical_case(
        graph: DiagnosticGraph,
        sim_result: CaseSimilarityResult,
    ) -> str:
        case = sim_result.case
        node_id = f"historical_case:{case.case_id}"
        node = GraphNode(
            node_id=node_id,
            node_type=GraphNodeType.ANOMALY,
            label=f"Historical Case: {case.title} ({sim_result.match_grade.value})",
            properties={
                "similarity": sim_result.overall_similarity,
                "relevance": sim_result.relevance_as_evidence,
                "is_confirmed": case.is_technician_confirmed(),
                "root_cause": case.root_cause.component_or_system if case.root_cause else "None",
            },
            provenance={"source": "HISTORICAL_CASE_REPOSITORY"},
        )
        graph.add_node(node)

        # Connect to associated DTCs in graph with strictly non-causal edge
        for dtc in case.active_dtcs:
            dtc_node_id = make_dtc_node_id(dtc.target_ecu, dtc.dtc_code)
            if dtc_node_id in graph.nodes:
                graph.add_edge(GraphEdge(
                    edge_id=f"edge_case_{case.case_id}_{dtc.dtc_code}",
                    source_id=node_id,
                    target_id=dtc_node_id,
                    edge_type=GraphEdgeType.ASSOCIATED_WITH,
                    confidence=sim_result.relevance_as_evidence,
                    provenance={"source": "HISTORICAL_CASE_ANALYSIS"},
                ))

        return node_id
