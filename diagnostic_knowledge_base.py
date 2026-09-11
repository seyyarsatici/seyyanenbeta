# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase I-1: Diagnostic Knowledge Base Subsystem
=============================================================================
This module implements Phase I-1 of the Seyyanen diagnostic architecture.
It establishes a structured, evidence-oriented automotive diagnostic knowledge
base layer that enables vehicle/ECU knowledge retrieval, failure-pattern
referencing, and causal reasoning support across Phases H and I.

Strict Architectural Invariants:
  1. EVIDENCE != PROOF:
     DTCs, sensor readings, and anomaly patterns are diagnostic evidence,
     never instant proof of root cause or part replacement.
  2. CORRELATION != CAUSATION:
     Graph relationships or co-occurring symptoms represent associations,
     never causality unless explicitly verified and grounded in physics.
  3. COMMUNICATION FAULT != COMPONENT FAILURE:
     Unreachable ECUs or bus timeouts are classified as network/wiring/power
     issues, never as internal electronic hardware defects without direct proof.
  4. VEHICLE SPECIFICITY IS FIRST-CLASS:
     Universal rules, manufacturer rules, engine-specific rules, and ECU-specific
     rules are explicitly segregated. Specificity matching is deterministic.
  5. PROVENANCE & TECHNICIAN CONFIRMATION:
     Every entry tracks source provenance, lifecycle state, version, and whether
     it has been technician-confirmed or system-derived.
  6. SAFETY GATED:
     Knowledge entries can recommend verification concepts or observational tests,
     but can NEVER autonomously authorize destructive services (Mode 04/14,
     0x2E writes, 0x27 security access, 0x2F actuator controls, 0x34/36/37).
  7. 100% DETERMINISTIC & BOUNDED:
     Lookup, ranking, specificity scoring, and relationship traversal are
     completely deterministic and protected against cyclic recursion.
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

# Integration imports from existing C through H layers
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
)
from advanced_fault_analysis import (
    DataSourceType,
    SignalQuality,
    OperatingCondition,
    AnomalySeverity,
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
    make_hypothesis_node_id,
    make_evidence_node_id,
)

logger = logging.getLogger("seyyanen.knowledge_base")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class KnowledgeLifecycle(str, enum.Enum):
    """Lifecycle state machine for a diagnostic knowledge entry."""
    DRAFT = "DRAFT"                  # Authored or generated, awaiting review
    CANDIDATE = "CANDIDATE"          # Under technical verification
    VALIDATED = "VALIDATED"          # Empirically or technically verified
    ACTIVE = "ACTIVE"                # Approved and actively used in diagnostics
    DEPRECATED = "DEPRECATED"        # Superseded by newer knowledge entry
    REJECTED = "REJECTED"            # Refuted or found inaccurate


class KnowledgeProvenanceType(str, enum.Enum):
    """Authoritative source classification for knowledge provenance."""
    OEM_MANUAL = "OEM_MANUAL"                      # Official OEM service manual
    TECHNICAL_SERVICE_BULLETIN = "TSB"             # OEM Technical Service Bulletin
    TECHNICIAN_CONFIRMED = "TECHNICIAN_CONFIRMED"  # Physically confirmed by qualified technician
    VALIDATED_PROCEDURE = "VALIDATED_PROCEDURE"    # Standard verified workshop procedure
    SYSTEM_DERIVED = "SYSTEM_DERIVED"              # Derived from diagnostic case evidence
    FIELD_OBSERVATION = "FIELD_OBSERVATION"        # Field workshop observation
    MANUAL_AUTHORING = "MANUAL_AUTHORING"          # Expert engineer manual entry


class KnowledgeConfidence(str, enum.Enum):
    """Calibrated confidence level of the diagnostic knowledge."""
    CONFIRMED = "CONFIRMED"          # Confirmed by physical measurement/OEM spec
    HIGH = "HIGH"                    # Strongly supported across multiple vehicles
    MODERATE = "MODERATE"            # Plausible and supported by evidence patterns
    LOW = "LOW"                      # Preliminary or single-vehicle observation
    PROVISIONAL = "PROVISIONAL"      # Unverified working hypothesis


class ApplicabilityScope(str, enum.Enum):
    """Granularity of vehicle/hardware applicability."""
    UNIVERSAL = "UNIVERSAL"          # General automotive physics (e.g. stoichiometric ratio)
    MANUFACTURER = "MANUFACTURER"    # Brand-wide protocol/behavior
    MODEL = "MODEL"                  # Vehicle model-specific
    GENERATION = "GENERATION"        # Model generation or platform-specific
    ENGINE = "ENGINE"                # Specific engine code (e.g. F14D3, Z16XER)
    TRANSMISSION = "TRANSMISSION"    # Specific transmission
    ECU_FAMILY = "ECU_FAMILY"        # Specific ECU family/hardware (e.g. Delphi MT80)
    CALIBRATION = "CALIBRATION"      # Exact software/calibration version
    INSTANCE = "INSTANCE"            # Specific VIN / vehicle instance


class KnowledgeRelationshipType(str, enum.Enum):
    """Relationship between diagnostic knowledge entries."""
    RELATED_TO = "RELATED_TO"                      # General association
    SUPPORTS = "SUPPORTS"                          # Evidential support
    CONTRADICTS = "CONTRADICTS"                    # Conflicting pattern/finding
    REFINES = "REFINES"                            # More specific version of parent knowledge
    SUPERSEDES = "SUPERSEDES"                      # Newer version replacing older
    DERIVED_FROM = "DERIVED_FROM"                  # Originating source
    APPLIES_TO = "APPLIES_TO"                      # Component or system binding
    DISTINGUISHES = "DISTINGUISHES"                # Differentiates between competing causes
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION" # Needs physical check before action
    CAUSES = "CAUSES"                              # Mechanistic causal link (strictly grounded)


class KnowledgeDomain(str, enum.Enum):
    """Functional automotive domain."""
    POWERTRAIN = "POWERTRAIN"
    FUEL_AIR = "FUEL_AIR"
    IGNITION = "IGNITION"
    EXHAUST_EMISSIONS = "EXHAUST_EMISSIONS"
    ELECTRICAL_NETWORK = "ELECTRICAL_NETWORK"
    CHASSIS_BRAKES = "CHASSIS_BRAKES"
    BODY_SECURITY = "BODY_SECURITY"
    THERMAL_MANAGEMENT = "THERMAL_MANAGEMENT"
    TRANSMISSION_DRIVELINE = "TRANSMISSION_DRIVELINE"
    COMMUNICATION_BUS = "COMMUNICATION_BUS"


# =====================================================================
# 2. FOUNDATIONAL DATA MODELS
# =====================================================================

@dataclass
class KnowledgeProvenance:
    """Structured audit trail and origin record for a knowledge entry."""
    source_type: KnowledgeProvenanceType
    source_reference: str
    author: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    review_notes: Optional[str] = None
    is_technician_confirmed: bool = False
    technician_id: Optional[str] = None
    confirmation_timestamp: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type.value,
            "source_reference": self.source_reference,
            "author": self.author,
            "created_at": round(self.created_at, 3),
            "updated_at": round(self.updated_at, 3),
            "review_notes": self.review_notes,
            "is_technician_confirmed": self.is_technician_confirmed,
            "technician_id": self.technician_id,
            "confirmation_timestamp": round(self.confirmation_timestamp, 3) if self.confirmation_timestamp else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeProvenance":
        return cls(
            source_type=KnowledgeProvenanceType(data.get("source_type", "MANUAL_AUTHORING")),
            source_reference=data.get("source_reference", "UNKNOWN"),
            author=data.get("author"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            review_notes=data.get("review_notes"),
            is_technician_confirmed=bool(data.get("is_technician_confirmed", False)),
            technician_id=data.get("technician_id"),
            confirmation_timestamp=float(data["confirmation_timestamp"]) if data.get("confirmation_timestamp") else None,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class KnowledgeApplicabilityCriteria:
    """
    Explicit vehicle, hardware, and calibration envelope.
    Enforces deterministic applicability evaluation and prevents silent broadening.
    """
    scope: ApplicabilityScope = ApplicabilityScope.UNIVERSAL
    manufacturers: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    model_years: List[int] = field(default_factory=list)
    engine_codes: List[str] = field(default_factory=list)
    transmission_types: List[str] = field(default_factory=list)
    ecu_families: List[str] = field(default_factory=list)
    target_ecus: List[str] = field(default_factory=list)
    software_versions: List[str] = field(default_factory=list)
    vins: List[str] = field(default_factory=list)

    def evaluate(self, context: Optional[VehicleContext]) -> Tuple[ApplicabilityResult, float]:
        """
        Evaluates applicability and calculates specificity score.
        Returns (ApplicabilityResult, specificity_weight).
        """
        if self.scope == ApplicabilityScope.UNIVERSAL and not any([
            self.manufacturers, self.models, self.model_years,
            self.engine_codes, self.transmission_types, self.ecu_families,
            self.software_versions, self.vins
        ]):
            return ApplicabilityResult.CONFIRMED_APPLICABLE, 1.0

        if context is None:
            return ApplicabilityResult.UNKNOWN_APPLICABILITY, 0.0

        ctx = context.normalize()

        # 1. Negative contradiction checks (Fail-closed)
        if self.vins and ctx.vin:
            if ctx.vin not in [v.upper() for v in self.vins]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.manufacturers and ctx.manufacturer:
            if ctx.manufacturer not in [m.upper() for m in self.manufacturers]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.models and ctx.model:
            if ctx.model not in [m.upper() for m in self.models]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.model_years and ctx.model_year:
            if ctx.model_year not in self.model_years:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.engine_codes and ctx.engine_code:
            if ctx.engine_code not in [e.upper() for e in self.engine_codes]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.transmission_types and ctx.transmission:
            if ctx.transmission not in [t.upper() for t in self.transmission_types]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.ecu_families and ctx.ecu_family:
            if ctx.ecu_family not in [ef.upper() for ef in self.ecu_families]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        if self.software_versions and ctx.software_id:
            if ctx.software_id not in [sv.upper() for sv in self.software_versions]:
                return ApplicabilityResult.NOT_APPLICABLE, 0.0

        # 2. Specificity scoring based on match depth
        specificity = 1.0
        confirmed_matches = 0
        required_matches = 0

        if self.vins:
            required_matches += 1
            if ctx.vin and ctx.vin in [v.upper() for v in self.vins]:
                confirmed_matches += 1
                specificity += 10.0

        if self.software_versions:
            required_matches += 1
            if ctx.software_id and ctx.software_id in [sv.upper() for sv in self.software_versions]:
                confirmed_matches += 1
                specificity += 6.0

        if self.ecu_families:
            required_matches += 1
            if ctx.ecu_family and ctx.ecu_family in [ef.upper() for ef in self.ecu_families]:
                confirmed_matches += 1
                specificity += 5.0

        if self.engine_codes:
            required_matches += 1
            if ctx.engine_code and ctx.engine_code in [e.upper() for e in self.engine_codes]:
                confirmed_matches += 1
                specificity += 4.0

        if self.models:
            required_matches += 1
            if ctx.model and ctx.model in [m.upper() for m in self.models]:
                confirmed_matches += 1
                specificity += 3.0

        if self.model_years:
            required_matches += 1
            if ctx.model_year and ctx.model_year in self.model_years:
                confirmed_matches += 1
                specificity += 2.0

        if self.manufacturers:
            required_matches += 1
            if ctx.manufacturer and ctx.manufacturer in [m.upper() for m in self.manufacturers]:
                confirmed_matches += 1
                specificity += 1.5

        if required_matches == 0:
            return ApplicabilityResult.CONFIRMED_APPLICABLE, 1.0

        if confirmed_matches == required_matches:
            return ApplicabilityResult.CONFIRMED_APPLICABLE, specificity
        elif confirmed_matches > 0:
            return ApplicabilityResult.LIKELY_APPLICABLE, specificity * 0.8
        else:
            return ApplicabilityResult.UNKNOWN_APPLICABILITY, 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope.value,
            "manufacturers": list(self.manufacturers),
            "models": list(self.models),
            "model_years": list(self.model_years),
            "engine_codes": list(self.engine_codes),
            "transmission_types": list(self.transmission_types),
            "ecu_families": list(self.ecu_families),
            "target_ecus": list(self.target_ecus),
            "software_versions": list(self.software_versions),
            "vins": list(self.vins),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeApplicabilityCriteria":
        return cls(
            scope=ApplicabilityScope(data.get("scope", "UNIVERSAL")),
            manufacturers=data.get("manufacturers", []),
            models=data.get("models", []),
            model_years=data.get("model_years", []),
            engine_codes=data.get("engine_codes", []),
            transmission_types=data.get("transmission_types", []),
            ecu_families=data.get("ecu_families", []),
            target_ecus=data.get("target_ecus", []),
            software_versions=data.get("software_versions", []),
            vins=data.get("vins", []),
        )


@dataclass
class KnowledgeEvidencePattern:
    """
    Pattern description for reusable signal observations or telemetry criteria.
    Describes conditions such as: 'At warm idle, MAF < 1.8 g/s with positive trim'.
    """
    pattern_id: str
    name: str
    signals: List[str]
    operating_conditions: List[OperatingCondition] = field(default_factory=list)
    condition_description: str = ""
    expected_direction: Optional[str] = None   # "HIGH", "LOW", "ERRATIC", "STUCK"
    deviation_threshold: Optional[float] = None
    unit: Optional[str] = None
    is_supporting: bool = True
    weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "signals": list(self.signals),
            "operating_conditions": [oc.value for oc in self.operating_conditions],
            "condition_description": self.condition_description,
            "expected_direction": self.expected_direction,
            "deviation_threshold": self.deviation_threshold,
            "unit": self.unit,
            "is_supporting": self.is_supporting,
            "weight": round(self.weight, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeEvidencePattern":
        return cls(
            pattern_id=data["pattern_id"],
            name=data["name"],
            signals=data.get("signals", []),
            operating_conditions=[OperatingCondition(oc) for oc in data.get("operating_conditions", [])],
            condition_description=data.get("condition_description", ""),
            expected_direction=data.get("expected_direction"),
            deviation_threshold=float(data["deviation_threshold"]) if data.get("deviation_threshold") is not None else None,
            unit=data.get("unit"),
            is_supporting=bool(data.get("is_supporting", True)),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass
class KnowledgeDistinguishingTest:
    """
    Represents a safe diagnostic test recommended to discriminate between competing hypotheses.
    Strictly enforces READ_ONLY safety classification.
    """
    test_id: str
    title: str
    description: str
    target_hypotheses: List[str] = field(default_factory=list)
    discriminated_hypotheses: List[str] = field(default_factory=list)
    execution_mode: str = "OBSERVATIONAL"
    target_ecu: str = "ECM"
    required_signals: List[str] = field(default_factory=list)
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    expected_outcome_description: str = ""

    def __post_init__(self):
        # Enforce safety invariant: Knowledge tests must be READ_ONLY
        if self.safety_classification != ServiceSafetyClassification.READ_ONLY:
            raise ValueError(
                f"Safety Invariant Violation: KnowledgeDistinguishingTest '{self.test_id}' "
                f"cannot have non-read-only safety classification '{self.safety_classification}'."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "title": self.title,
            "description": self.description,
            "target_hypotheses": list(self.target_hypotheses),
            "discriminated_hypotheses": list(self.discriminated_hypotheses),
            "execution_mode": self.execution_mode,
            "target_ecu": self.target_ecu,
            "required_signals": list(self.required_signals),
            "safety_classification": self.safety_classification.value,
            "expected_outcome_description": self.expected_outcome_description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeDistinguishingTest":
        return cls(
            test_id=data["test_id"],
            title=data["title"],
            description=data.get("description", ""),
            target_hypotheses=data.get("target_hypotheses", []),
            discriminated_hypotheses=data.get("discriminated_hypotheses", []),
            execution_mode=data.get("execution_mode", "OBSERVATIONAL"),
            target_ecu=data.get("target_ecu", "ECM"),
            required_signals=data.get("required_signals", []),
            safety_classification=ServiceSafetyClassification(data.get("safety_classification", "READ_ONLY")),
            expected_outcome_description=data.get("expected_outcome_description", ""),
        )


@dataclass
class KnowledgeRelationship:
    """Directed, typed relationship between two diagnostic knowledge entries."""
    source_id: str
    target_id: str
    relationship_type: KnowledgeRelationshipType
    confidence: float = 1.0
    rationale: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship_type": self.relationship_type.value,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "created_at": round(self.created_at, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeRelationship":
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relationship_type=KnowledgeRelationshipType(data["relationship_type"]),
            confidence=float(data.get("confidence", 1.0)),
            rationale=data.get("rationale", ""),
            created_at=float(data.get("created_at", time.time())),
        )


# =====================================================================
# 3. DIAGNOSTIC KNOWLEDGE ENTRY
# =====================================================================

@dataclass
class DiagnosticKnowledgeEntry:
    """
    Primary, first-class Diagnostic Knowledge Entity in Phase I-1.
    Preserves provenance, version, applicability, and evidential associations.
    """
    knowledge_id: str
    title: str
    description: str
    domain: KnowledgeDomain
    applicability: KnowledgeApplicabilityCriteria
    provenance: KnowledgeProvenance
    version: int = 1
    lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE
    confidence: KnowledgeConfidence = KnowledgeConfidence.MODERATE
    dtc_associations: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)
    evidence_patterns: List[KnowledgeEvidencePattern] = field(default_factory=list)
    possible_causes: List[str] = field(default_factory=list)
    contradicting_patterns: List[KnowledgeEvidencePattern] = field(default_factory=list)
    distinguishing_tests: List[KnowledgeDistinguishingTest] = field(default_factory=list)
    verification_actions: List[str] = field(default_factory=list)
    relationships: List[KnowledgeRelationship] = field(default_factory=list)
    superseded_by: Optional[str] = None
    supersedes: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    is_dtc_free_capable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.knowledge_id or not str(self.knowledge_id).strip():
            raise ValueError("Knowledge entry must have a non-empty knowledge_id.")
        if self.version < 1:
            raise ValueError(f"Knowledge version must be positive integer >= 1 (got {self.version}).")

    def create_new_version(
        self,
        new_version_id: str,
        updated_title: Optional[str] = None,
        updated_description: Optional[str] = None,
        change_reason: str = "",
        provenance: Optional[KnowledgeProvenance] = None,
    ) -> "DiagnosticKnowledgeEntry":
        """
        Creates a versioned descendant of this entry, setting supersedes and deprecating self.
        """
        new_entry = copy.deepcopy(self)
        new_entry.knowledge_id = new_version_id
        new_entry.version = self.version + 1
        new_entry.supersedes = self.knowledge_id
        new_entry.superseded_by = None
        new_entry.lifecycle = KnowledgeLifecycle.ACTIVE
        if updated_title:
            new_entry.title = updated_title
        if updated_description:
            new_entry.description = updated_description
        if provenance:
            new_entry.provenance = provenance
        else:
            new_entry.provenance.updated_at = time.time()
            new_entry.provenance.review_notes = change_reason

        # Mark self as superseded and deprecated
        self.superseded_by = new_version_id
        self.lifecycle = KnowledgeLifecycle.DEPRECATED

        # Record relationship
        rel = KnowledgeRelationship(
            source_id=new_version_id,
            target_id=self.knowledge_id,
            relationship_type=KnowledgeRelationshipType.SUPERSEDES,
            rationale=change_reason or "Superseded by new version",
        )
        new_entry.relationships.append(rel)
        return new_entry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "title": self.title,
            "description": self.description,
            "domain": self.domain.value,
            "applicability": self.applicability.to_dict(),
            "provenance": self.provenance.to_dict(),
            "version": self.version,
            "lifecycle": self.lifecycle.value,
            "confidence": self.confidence.value,
            "dtc_associations": list(self.dtc_associations),
            "symptoms": list(self.symptoms),
            "evidence_patterns": [ep.to_dict() for ep in self.evidence_patterns],
            "possible_causes": list(self.possible_causes),
            "contradicting_patterns": [cp.to_dict() for cp in self.contradicting_patterns],
            "distinguishing_tests": [dt.to_dict() for dt in self.distinguishing_tests],
            "verification_actions": list(self.verification_actions),
            "relationships": [rel.to_dict() for rel in self.relationships],
            "superseded_by": self.superseded_by,
            "supersedes": self.supersedes,
            "tags": list(self.tags),
            "is_dtc_free_capable": self.is_dtc_free_capable,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticKnowledgeEntry":
        return cls(
            knowledge_id=data["knowledge_id"],
            title=data["title"],
            description=data.get("description", ""),
            domain=KnowledgeDomain(data.get("domain", "POWERTRAIN")),
            applicability=KnowledgeApplicabilityCriteria.from_dict(data["applicability"]),
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            version=int(data.get("version", 1)),
            lifecycle=KnowledgeLifecycle(data.get("lifecycle", "ACTIVE")),
            confidence=KnowledgeConfidence(data.get("confidence", "MODERATE")),
            dtc_associations=data.get("dtc_associations", []),
            symptoms=data.get("symptoms", []),
            evidence_patterns=[KnowledgeEvidencePattern.from_dict(ep) for ep in data.get("evidence_patterns", [])],
            possible_causes=data.get("possible_causes", []),
            contradicting_patterns=[KnowledgeEvidencePattern.from_dict(cp) for cp in data.get("contradicting_patterns", [])],
            distinguishing_tests=[KnowledgeDistinguishingTest.from_dict(dt) for dt in data.get("distinguishing_tests", [])],
            verification_actions=data.get("verification_actions", []),
            relationships=[KnowledgeRelationship.from_dict(rel) for rel in data.get("relationships", [])],
            superseded_by=data.get("superseded_by"),
            supersedes=data.get("supersedes"),
            tags=data.get("tags", []),
            is_dtc_free_capable=bool(data.get("is_dtc_free_capable", True)),
            metadata=dict(data.get("metadata", {})),
        )


# =====================================================================
# 4. KNOWLEDGE RETRIEVAL & QUERY MATCH RESULT
# =====================================================================

@dataclass
class KnowledgeMatchResult:
    """
    Detailed, explainable result of matching a knowledge entry against diagnostic context.
    Strictly explains *why* the entry matched.
    """
    entry: DiagnosticKnowledgeEntry
    total_score: float
    applicability_result: ApplicabilityResult
    specificity_score: float
    dtc_score: float
    symptom_score: float
    evidence_score: float
    provenance_score: float
    match_explanations: List[str] = field(default_factory=list)
    has_conflicts: bool = False
    conflict_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "knowledge_id": self.entry.knowledge_id,
            "title": self.entry.title,
            "total_score": round(self.total_score, 3),
            "applicability_result": self.applicability_result.value,
            "specificity_score": round(self.specificity_score, 2),
            "dtc_score": round(self.dtc_score, 2),
            "symptom_score": round(self.symptom_score, 2),
            "evidence_score": round(self.evidence_score, 2),
            "provenance_score": round(self.provenance_score, 2),
            "match_explanations": list(self.match_explanations),
            "has_conflicts": self.has_conflicts,
            "conflict_notes": list(self.conflict_notes),
        }


# =====================================================================
# 5. DIAGNOSTIC KNOWLEDGE STORE & QUERY ENGINE
# =====================================================================

class DiagnosticKnowledgeStore:
    """
    Foundational Diagnostic Knowledge Store & Query Engine for Phase I-1.
    Maintains fast multi-key indexes, deterministic specificity-ranked matching,
    cycle-safe relationship traversal, and safe serialization.
    """

    def __init__(self):
        self._entries: Dict[str, DiagnosticKnowledgeEntry] = {}
        # Multi-key lookup indexes
        self._dtc_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._symptom_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._manufacturer_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._engine_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._domain_index: Dict[KnowledgeDomain, Set[str]] = collections.defaultdict(set)
        self._lifecycle_index: Dict[KnowledgeLifecycle, Set[str]] = collections.defaultdict(set)

    def register_entry(self, entry: DiagnosticKnowledgeEntry) -> None:
        """
        Registers or updates a knowledge entry in the store.
        Rebuilds secondary index entries deterministically.
        """
        k_id = entry.knowledge_id
        if k_id in self._entries:
            self._remove_from_indexes(k_id)

        self._entries[k_id] = entry

        # Update DTC Index
        for dtc in entry.dtc_associations:
            self._dtc_index[dtc.strip().upper()].add(k_id)

        # Update Symptom Index
        for sym in entry.symptoms:
            self._symptom_index[sym.strip().upper()].add(k_id)

        # Update Vehicle Indexes
        for m in entry.applicability.manufacturers:
            self._manufacturer_index[m.strip().upper()].add(k_id)

        for eng in entry.applicability.engine_codes:
            self._engine_index[eng.strip().upper()].add(k_id)

        # Update Domain & Lifecycle Indexes
        self._domain_index[entry.domain].add(k_id)
        self._lifecycle_index[entry.lifecycle].add(k_id)

    def get_entry(self, knowledge_id: str) -> Optional[DiagnosticKnowledgeEntry]:
        """Retrieves entry by stable knowledge ID."""
        return self._entries.get(knowledge_id)

    def list_entries(
        self,
        lifecycle: Optional[KnowledgeLifecycle] = None,
        domain: Optional[KnowledgeDomain] = None,
    ) -> List[DiagnosticKnowledgeEntry]:
        """Lists entries filtered by optional lifecycle and domain."""
        res = list(self._entries.values())
        if lifecycle:
            res = [e for e in res if e.lifecycle == lifecycle]
        if domain:
            res = [e for e in res if e.domain == domain]
        return res

    def deprecate_entry(self, knowledge_id: str, reason: str = "") -> bool:
        """Transitions an entry to DEPRECATED lifecycle state."""
        entry = self._entries.get(knowledge_id)
        if not entry:
            return False
        old_life = entry.lifecycle
        entry.lifecycle = KnowledgeLifecycle.DEPRECATED
        entry.provenance.updated_at = time.time()
        if reason:
            entry.provenance.review_notes = reason
        self._lifecycle_index[old_life].discard(knowledge_id)
        self._lifecycle_index[KnowledgeLifecycle.DEPRECATED].add(knowledge_id)
        return True

    def query_knowledge(
        self,
        vehicle_context: Optional[VehicleContext] = None,
        dtcs: Optional[List[str]] = None,
        symptoms: Optional[List[str]] = None,
        domain: Optional[KnowledgeDomain] = None,
        active_only: bool = True,
        max_results: int = 15,
    ) -> List[KnowledgeMatchResult]:
        """
        Deterministic, explainable knowledge retrieval engine.
        Evaluates applicability, evidential matches, symptoms, and provenance.
        Ranks results deterministically without external LLM dependencies.
        """
        norm_dtcs = [d.strip().upper() for d in (dtcs or [])]
        norm_syms = [s.strip().upper() for s in (symptoms or [])]

        candidate_ids: Set[str] = set()

        # Gather candidates via index intersections / unions
        if norm_dtcs:
            for d in norm_dtcs:
                candidate_ids.update(self._dtc_index.get(d, set()))

        if norm_syms:
            for s in norm_syms:
                candidate_ids.update(self._symptom_index.get(s, set()))

        # If no DTC or symptom query given, search across applicable entries
        if not candidate_ids:
            candidate_ids = set(self._entries.keys())

        match_results: List[KnowledgeMatchResult] = []

        for cid in candidate_ids:
            entry = self._entries[cid]

            if active_only and entry.lifecycle != KnowledgeLifecycle.ACTIVE:
                continue

            if domain and entry.domain != domain:
                continue

            # 1. Applicability Evaluation
            app_result, specificity = entry.applicability.evaluate(vehicle_context)
            if app_result == ApplicabilityResult.NOT_APPLICABLE:
                continue  # Contradicts vehicle context; reject immediately

            explanations: List[str] = []
            dtc_score = 0.0
            symptom_score = 0.0
            evidence_score = 0.0
            provenance_score = 1.0

            # 2. DTC Match Evaluation
            matched_dtcs = set(entry.dtc_associations).intersection(norm_dtcs)
            if matched_dtcs:
                dtc_score = len(matched_dtcs) * 3.0
                explanations.append(f"Matched DTCs: {list(matched_dtcs)}")
            elif norm_dtcs and not entry.is_dtc_free_capable:
                # Entry requires DTCs but none matched
                continue

            # 3. Symptom Match Evaluation
            matched_syms = set([s.upper() for s in entry.symptoms]).intersection(norm_syms)
            if matched_syms:
                symptom_score = len(matched_syms) * 2.5
                explanations.append(f"Matched Symptoms: {list(matched_syms)}")

            # 4. Specificity Explanation
            if specificity > 1.0:
                explanations.append(
                    f"Vehicle Specificity Match: {entry.applicability.scope.value} (Weight: {specificity:.1f})"
                )
            else:
                explanations.append("Universal / General Automotive Applicability")

            # 5. Provenance Scoring
            if entry.provenance.is_technician_confirmed:
                provenance_score += 2.0
                explanations.append("Technician Confirmed Provenance (+2.0)")
            elif entry.provenance.source_type == KnowledgeProvenanceType.OEM_MANUAL:
                provenance_score += 1.5
                explanations.append("OEM Service Manual Provenance (+1.5)")

            # Total score calculation
            total_score = (specificity * 2.0) + dtc_score + symptom_score + evidence_score + provenance_score

            result = KnowledgeMatchResult(
                entry=entry,
                total_score=total_score,
                applicability_result=app_result,
                specificity_score=specificity,
                dtc_score=dtc_score,
                symptom_score=symptom_score,
                evidence_score=evidence_score,
                provenance_score=provenance_score,
                match_explanations=explanations,
            )
            match_results.append(result)

        # Detect conflicts among matched candidates
        self._detect_candidate_conflicts(match_results)

        # Deterministic sorting: highest total_score first, tie-break by knowledge_id
        match_results.sort(key=lambda r: (-r.total_score, r.entry.knowledge_id))

        return match_results[:max_results]

    def get_related_entries(
        self,
        knowledge_id: str,
        max_depth: int = 2,
        visited: Optional[Set[str]] = None,
    ) -> List[Tuple[DiagnosticKnowledgeEntry, KnowledgeRelationshipType, int]]:
        """
        Traverses relationships in a bounded, cycle-protected manner.
        Returns list of (DiagnosticKnowledgeEntry, relationship_type, depth).
        """
        if visited is None:
            visited = set()

        visited.add(knowledge_id)
        results: List[Tuple[DiagnosticKnowledgeEntry, KnowledgeRelationshipType, int]] = []

        entry = self._entries.get(knowledge_id)
        if not entry or max_depth <= 0:
            return results

        for rel in entry.relationships:
            target_id = rel.target_id
            if target_id not in visited and target_id in self._entries:
                target_entry = self._entries[target_id]
                results.append((target_entry, rel.relationship_type, 1))
                if max_depth > 1:
                    child_results = self.get_related_entries(
                        target_id,
                        max_depth=max_depth - 1,
                        visited=visited,
                    )
                    for centry, crel_type, cdepth in child_results:
                        results.append((centry, crel_type, cdepth + 1))

        return results

    def _detect_candidate_conflicts(self, candidates: List[KnowledgeMatchResult]) -> None:
        """Identifies explicit contradictions between matching candidates."""
        for i, c1 in enumerate(candidates):
            for c2 in candidates[i + 1:]:
                # Check for explicit CONTRADICTS relationship in either direction
                for rel in c1.entry.relationships:
                    if rel.target_id == c2.entry.knowledge_id and rel.relationship_type == KnowledgeRelationshipType.CONTRADICTS:
                        c1.has_conflicts = True
                        c2.has_conflicts = True
                        c1.conflict_notes.append(f"Contradicts candidate '{c2.entry.knowledge_id}': {rel.rationale}")
                        c2.conflict_notes.append(f"Contradicted by candidate '{c1.entry.knowledge_id}': {rel.rationale}")

                for rel in c2.entry.relationships:
                    if rel.target_id == c1.entry.knowledge_id and rel.relationship_type == KnowledgeRelationshipType.CONTRADICTS:
                        c1.has_conflicts = True
                        c2.has_conflicts = True
                        c2.conflict_notes.append(f"Contradicts candidate '{c1.entry.knowledge_id}': {rel.rationale}")
                        c1.conflict_notes.append(f"Contradicted by candidate '{c2.entry.knowledge_id}': {rel.rationale}")

    def _remove_from_indexes(self, knowledge_id: str) -> None:
        """Internal helper to clean up indexes before updating an entry."""
        entry = self._entries.get(knowledge_id)
        if not entry:
            return

        for dtc in entry.dtc_associations:
            self._dtc_index[dtc.strip().upper()].discard(knowledge_id)

        for sym in entry.symptoms:
            self._symptom_index[sym.strip().upper()].discard(knowledge_id)

        for m in entry.applicability.manufacturers:
            self._manufacturer_index[m.strip().upper()].discard(knowledge_id)

        for eng in entry.applicability.engine_codes:
            self._engine_index[eng.strip().upper()].discard(knowledge_id)

        self._domain_index[entry.domain].discard(knowledge_id)
        self._lifecycle_index[entry.lifecycle].discard(knowledge_id)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes entire knowledge base to deterministic dictionary."""
        return {
            "entries": [entry.to_dict() for entry in self._entries.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticKnowledgeStore":
        """Reconstructs store from serialized representation."""
        store = cls()
        for e_dict in data.get("entries", []):
            entry = DiagnosticKnowledgeEntry.from_dict(e_dict)
            store.register_entry(entry)
        return store


# =====================================================================
# 6. H-LAYER ADAPTERS & G-5 INTEGRATION
# =====================================================================

class KnowledgeWorkflowAdapter:
    """
    Clean, non-invasive adapter enabling Phases H-3, H-4, and H-5 to query
    the Diagnostic Knowledge Base without tight coupling.
    """

    def __init__(self, store: DiagnosticKnowledgeStore):
        self.store = store

    def get_discriminating_tests_for_hypotheses(
        self,
        vehicle_context: Optional[VehicleContext],
        hypothesis_ids: List[str],
    ) -> List[KnowledgeDistinguishingTest]:
        """
        Provides H-3 Evidence-Driven Test Selector with relevant, safe tests
        that discriminate between competing active hypotheses.
        """
        results: List[KnowledgeDistinguishingTest] = []
        matches = self.store.query_knowledge(vehicle_context=vehicle_context, active_only=True)

        for m in matches:
            for dt in m.entry.distinguishing_tests:
                # Check if this test discriminates any of the active hypotheses
                if any(h in dt.discriminated_hypotheses for h in hypothesis_ids):
                    results.append(dt)
        return results

    def get_verification_actions_for_candidate(
        self,
        vehicle_context: Optional[VehicleContext],
        candidate_cause: str,
    ) -> List[str]:
        """
        Provides H-4 / H-5 with recommended technician physical verification
        actions for a leading root-cause candidate.
        """
        matches = self.store.query_knowledge(vehicle_context=vehicle_context, active_only=True)
        actions: List[str] = []
        for m in matches:
            if candidate_cause in m.entry.possible_causes:
                actions.extend(m.entry.verification_actions)
        return list(dict.fromkeys(actions))  # Deduplicate preserving order


class DiagnosticGraphKnowledgeIntegrator:
    """
    Binds Diagnostic Knowledge entries to G-5 DiagnosticGraph nodes and edges.
    Strictly preserves the invariant: RELATIONSHIP != CAUSALITY.
    """

    @staticmethod
    def integrate_knowledge_entry(
        graph: DiagnosticGraph,
        entry: DiagnosticKnowledgeEntry,
    ) -> None:
        """
        Creates or updates a graph node for the knowledge entry and links it
        to associated DTCs, systems, and related entries.
        """
        k_node_id = f"knowledge:{entry.knowledge_id}"
        k_node = GraphNode(
            node_id=k_node_id,
            node_type=GraphNodeType.EVIDENCE,  # Grounded as structured evidential knowledge
            label=f"KB: {entry.title}",
            properties={
                "domain": entry.domain.value,
                "version": entry.version,
                "lifecycle": entry.lifecycle.value,
                "confidence": entry.confidence.value,
                "is_technician_confirmed": entry.provenance.is_technician_confirmed,
            },
            provenance=entry.provenance.to_dict(),
        )
        graph.add_node(k_node)

        # Connect to DTC nodes if they exist in the graph
        for dtc in entry.dtc_associations:
            dtc_node_id = make_dtc_node_id("ECM", dtc)
            if dtc_node_id in graph.nodes:
                graph.add_edge(GraphEdge(
                    edge_id=f"edge_kb_{entry.knowledge_id}_{dtc}",
                    source_id=k_node_id,
                    target_id=dtc_node_id,
                    edge_type=GraphEdgeType.ASSOCIATED_WITH,
                    confidence=0.9,
                    provenance={"source": "KNOWLEDGE_BASE"},
                ))
