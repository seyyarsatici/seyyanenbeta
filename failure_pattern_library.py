# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase I-3: Failure Pattern Library Subsystem
=============================================================================
This module implements Phase I-3 of the Seyyanen diagnostic architecture.
It establishes a structured, reusable Failure Pattern Library that allows
Seyyanen to represent and match empirical diagnostic patterns observed across
vehicle telemetry, signal features, and operating conditions.

Strict Architectural Invariants:
  1. PATTERN != ROOT CAUSE:
     Recognizing an empirical pattern (e.g. sensor response lag, trim divergence)
     is diagnostic evidence, never proof of part replacement.
  2. ALTERNATIVE EXPLANATIONS MUST BE PRESERVED:
     Every pattern represents multiple plausible hypotheses (e.g. sensor bias
     vs unmetered vacuum leak vs harness resistance).
  3. CONTRADICTORY & NEGATIVE EVIDENCE PRESERVATION:
     Positive feature matches must not mask strong contradictory evidence.
     Contradictory observations visibly depress pattern confidence.
  4. COMMUNICATION FAULT != COMPONENT FAILURE:
     Bus timeouts, dropouts, or packet losses are strictly classified as network
     or wiring issues, never as defective internal electronic components.
  5. DTC-FREE MATCHING CAPABILITY:
     Reusable failure patterns can match and guide diagnosis even when DTC count is zero.
  6. BOUNDED COMPOSITION & CYCLE PROTECTION:
     Patterns can compose with other patterns, strictly protected against cyclic
     recursion with depth limits.
  7. SAFETY GATED:
     All patterns and recommended distinguishing tests are strictly READ_ONLY.
     Zero autonomous actuation, writing, or programming.
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

# Integration imports from C, D, G, H, I-1, and I-2 layers
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
    KnowledgeEvidencePattern,
    KnowledgeDistinguishingTest,
    KnowledgeRelationship,
    DiagnosticKnowledgeEntry,
)
from vehicle_ecu_knowledge import (
    ProgressiveVehicleIdentity,
    EngineKnowledgeProfile,
    TransmissionKnowledgeProfile,
    ECUKnowledgeProfile,
)

logger = logging.getLogger("seyyanen.failure_pattern_library")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class PatternCategory(str, enum.Enum):
    """Categorical classification of reusable automotive failure patterns."""
    SENSOR_DRIFT = "SENSOR_DRIFT"                              # Persistent slow deviation from physical baseline
    INTERMITTENT_SIGNAL = "INTERMITTENT_SIGNAL"                # Sporadic dropouts, intermittent glitches
    STUCK_VALUE = "STUCK_VALUE"                                # Sensor flatline, unvarying reading under load
    RESPONSE_LAG = "RESPONSE_LAG"                              # Delayed follower response relative to driver transition
    CONTROL_OSCILLATION = "CONTROL_OSCILLATION"                # Unstable closed-loop hunting (e.g. idle RPM, O2 trim)
    CROSS_SENSOR_DISAGREEMENT = "CROSS_SENSOR_DISAGREEMENT"    # Plausibility conflict between correlated sensors (MAF vs MAP)
    COMMAND_RESPONSE_MISMATCH = "COMMAND_RESPONSE_MISMATCH"    # Actuator feedback disagrees with commanded state
    THERMAL_INCONSISTENCY = "THERMAL_INCONSISTENCY"            # Anomaly appearing only during cold start or warm-up
    OPERATING_ENVELOPE_VIOLATION = "ENVELOPE_VIOLATION"        # Signal exceeds physical capability of engine state
    COMMUNICATION_ANOMALY = "COMMUNICATION_ANOMALY"            # Bus timeout, lost frame, communication fault


class PatternFeatureType(str, enum.Enum):
    """Mathematical and temporal characteristics of telemetry features."""
    VALUE_RANGE = "VALUE_RANGE"                                # Physical min/max value bounds
    RATE_OF_CHANGE = "RATE_OF_CHANGE"                          # Derivative / slope / sudden gradient
    DELAY_TIME_S = "DELAY_TIME_S"                              # Measured time lag in seconds
    PERSISTENCE_DURATION_S = "PERSISTENCE_DURATION_S"          # Continuous duration of the abnormal condition
    OSCILLATION_AMPLITUDE = "OSCILLATION_AMPLITUDE"            # Peak-to-peak swing amplitude
    OSCILLATION_FREQUENCY_HZ = "OSCILLATION_FREQUENCY_HZ"      # Frequency of cyclic oscillation
    CROSS_SENSOR_DELTA = "CROSS_SENSOR_DELTA"                  # Numerical divergence between correlated signals
    COMMAND_ERROR_MARGIN = "COMMAND_ERROR_MARGIN"              # Absolute difference between target and actual


class PatternMatchGrade(str, enum.Enum):
    """Calibrated match quality grade of a pattern evaluation."""
    STRONG_MATCH = "STRONG_MATCH"          # Score >= 0.80, all mandatory features satisfied, no contradictions
    PARTIAL_MATCH = "PARTIAL_MATCH"        # 0.50 <= Score < 0.80, most features present
    WEAK_MATCH = "WEAK_MATCH"              # 0.30 <= Score < 0.50, low feature overlap
    NON_MATCH = "NON_MATCH"                # Score < 0.30 or contradictory features active


# =====================================================================
# 2. FEATURE REPRESENTATION & EXTRACTED OBSERVATIONS
# =====================================================================

@dataclass
class PatternFeatureRequirement:
    """
    Specification of an expected feature in vehicle telemetry or evidence.
    Defines thresholds, signal names, and whether the feature is mandatory.
    """
    feature_id: str
    feature_type: PatternFeatureType
    signal_name: str
    min_threshold: Optional[float] = None
    max_threshold: Optional[float] = None
    expected_direction: Optional[str] = None     # "HIGH", "LOW", "STUCK", "OSCILLATING"
    is_mandatory: bool = True
    weight: float = 1.0
    description: str = ""

    def evaluate_feature(self, observed_value: Optional[float]) -> Tuple[bool, float, str]:
        """
        Evaluates observed numerical value against this requirement.
        Returns (is_satisfied, match_score, explanation).
        """
        if observed_value is None:
            if self.is_mandatory:
                return False, 0.0, f"Mandatory feature '{self.signal_name}' missing."
            return True, 0.5, f"Optional feature '{self.signal_name}' omitted."

        # Min threshold check
        if self.min_threshold is not None and observed_value < self.min_threshold:
            return False, 0.0, f"{self.signal_name} value ({observed_value}) < min threshold ({self.min_threshold})."

        # Max threshold check
        if self.max_threshold is not None and observed_value > self.max_threshold:
            return False, 0.0, f"{self.signal_name} value ({observed_value}) > max threshold ({self.max_threshold})."

        return True, 1.0, f"{self.signal_name} value ({observed_value}) within required range."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "feature_type": self.feature_type.value,
            "signal_name": self.signal_name,
            "min_threshold": self.min_threshold,
            "max_threshold": self.max_threshold,
            "expected_direction": self.expected_direction,
            "is_mandatory": self.is_mandatory,
            "weight": round(self.weight, 2),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternFeatureRequirement":
        return cls(
            feature_id=data["feature_id"],
            feature_type=PatternFeatureType(data["feature_type"]),
            signal_name=data["signal_name"],
            min_threshold=float(data["min_threshold"]) if data.get("min_threshold") is not None else None,
            max_threshold=float(data["max_threshold"]) if data.get("max_threshold") is not None else None,
            expected_direction=data.get("expected_direction"),
            is_mandatory=bool(data.get("is_mandatory", True)),
            weight=float(data.get("weight", 1.0)),
            description=data.get("description", ""),
        )


@dataclass
class ObservedFeatureSet:
    """
    Extracted telemetry features and observations from live diagnosis or test session.
    Supplied to the pattern matcher for evaluation against library patterns.
    """
    session_id: str
    operating_condition: OperatingCondition = OperatingCondition.UNKNOWN
    features: Dict[str, float] = field(default_factory=dict)       # e.g. {"MAF:VALUE": 4.5, "MAF:LAG_S": 0.8}
    active_dtcs: List[str] = field(default_factory=list)
    active_anomalies: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def get_feature_value(self, signal_name: str, feature_type: PatternFeatureType) -> Optional[float]:
        """Retrieves numerical feature value by signal name and type."""
        key = f"{signal_name.strip().upper()}:{feature_type.value}"
        if key in self.features:
            return self.features[key]
        # Fallback to direct signal name if single scalar
        return self.features.get(signal_name.strip().upper())


# =====================================================================
# 3. FAILURE PATTERN MODEL
# =====================================================================

@dataclass
class FailurePattern:
    """
    Primary Failure Pattern Entity in Phase I-3.
    Represents a reusable empirical diagnostic pattern observed across telemetry,
    correlated signals, and operating conditions.
    """
    pattern_id: str
    name: str
    category: PatternCategory
    description: str
    applicability: KnowledgeApplicabilityCriteria
    provenance: KnowledgeProvenance
    required_operating_conditions: List[OperatingCondition] = field(default_factory=list)
    feature_requirements: List[PatternFeatureRequirement] = field(default_factory=list)
    contradictory_features: List[PatternFeatureRequirement] = field(default_factory=list)
    associated_dtcs: List[str] = field(default_factory=list)
    possible_hypotheses: List[str] = field(default_factory=list)
    alternative_explanations: List[str] = field(default_factory=list)
    distinguishing_tests: List[KnowledgeDistinguishingTest] = field(default_factory=list)
    composed_pattern_ids: List[str] = field(default_factory=list)
    is_dtc_free_capable: bool = True
    confidence: KnowledgeConfidence = KnowledgeConfidence.MODERATE
    lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE
    version: int = 1
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.pattern_id or not str(self.pattern_id).strip():
            raise ValueError("Failure pattern must have a valid non-empty pattern_id.")
        # Safety invariant: Ensure all distinguishing tests are READ_ONLY
        for dt in self.distinguishing_tests:
            if dt.safety_classification != ServiceSafetyClassification.READ_ONLY:
                raise ValueError(
                    f"Safety Violation: Distinguishing test '{dt.test_id}' in pattern "
                    f"'{self.pattern_id}' must be READ_ONLY."
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "applicability": self.applicability.to_dict(),
            "provenance": self.provenance.to_dict(),
            "required_operating_conditions": [oc.value for oc in self.required_operating_conditions],
            "feature_requirements": [fr.to_dict() for fr in self.feature_requirements],
            "contradictory_features": [cf.to_dict() for cf in self.contradictory_features],
            "associated_dtcs": list(self.associated_dtcs),
            "possible_hypotheses": list(self.possible_hypotheses),
            "alternative_explanations": list(self.alternative_explanations),
            "distinguishing_tests": [dt.to_dict() for dt in self.distinguishing_tests],
            "composed_pattern_ids": list(self.composed_pattern_ids),
            "is_dtc_free_capable": self.is_dtc_free_capable,
            "confidence": self.confidence.value,
            "lifecycle": self.lifecycle.value,
            "version": self.version,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailurePattern":
        return cls(
            pattern_id=data["pattern_id"],
            name=data["name"],
            category=PatternCategory(data["category"]),
            description=data.get("description", ""),
            applicability=KnowledgeApplicabilityCriteria.from_dict(data["applicability"]),
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            required_operating_conditions=[OperatingCondition(oc) for oc in data.get("required_operating_conditions", [])],
            feature_requirements=[PatternFeatureRequirement.from_dict(fr) for fr in data.get("feature_requirements", [])],
            contradictory_features=[PatternFeatureRequirement.from_dict(cf) for cf in data.get("contradictory_features", [])],
            associated_dtcs=data.get("associated_dtcs", []),
            possible_hypotheses=data.get("possible_hypotheses", []),
            alternative_explanations=data.get("alternative_explanations", []),
            distinguishing_tests=[KnowledgeDistinguishingTest.from_dict(dt) for dt in data.get("distinguishing_tests", [])],
            composed_pattern_ids=data.get("composed_pattern_ids", []),
            is_dtc_free_capable=bool(data.get("is_dtc_free_capable", True)),
            confidence=KnowledgeConfidence(data.get("confidence", "MODERATE")),
            lifecycle=KnowledgeLifecycle(data.get("lifecycle", "ACTIVE")),
            version=int(data.get("version", 1)),
            supersedes=data.get("supersedes"),
            superseded_by=data.get("superseded_by"),
            metadata=dict(data.get("metadata", {})),
        )


# =====================================================================
# 4. PATTERN MATCH RESULT & EXPLAINABILITY
# =====================================================================

@dataclass
class PatternMatchResult:
    """
    Detailed, transparent result of matching a FailurePattern against observed features.
    Provides complete explanation of matched, missing, and contradictory features.
    """
    pattern: FailurePattern
    match_grade: PatternMatchGrade
    overall_score: float
    feature_match_ratio: float
    applicability_result: ApplicabilityResult
    specificity_weight: float
    satisfied_features: List[str] = field(default_factory=list)
    missing_mandatory_features: List[str] = field(default_factory=list)
    contradictory_features_detected: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern.pattern_id,
            "pattern_name": self.pattern.name,
            "category": self.pattern.category.value,
            "match_grade": self.match_grade.value,
            "overall_score": round(self.overall_score, 3),
            "feature_match_ratio": round(self.feature_match_ratio, 2),
            "applicability_result": self.applicability_result.value,
            "specificity_weight": round(self.specificity_weight, 2),
            "satisfied_features": list(self.satisfied_features),
            "missing_mandatory_features": list(self.missing_mandatory_features),
            "contradictory_features_detected": list(self.contradictory_features_detected),
            "explanations": list(self.explanations),
            "alternative_explanations": list(self.pattern.alternative_explanations),
            "distinguishing_tests": [dt.to_dict() for dt in self.pattern.distinguishing_tests],
        }


# =====================================================================
# 5. FAILURE PATTERN LIBRARY STORE & MATCHER
# =====================================================================

class FailurePatternLibraryStore:
    """
    Deterministic storage, indexing, and matching engine for Failure Patterns.
    Enforces cycle-safe composition, negative evidence penalties, and vehicle/ECU specificity.
    """

    def __init__(self):
        self._patterns: Dict[str, FailurePattern] = {}
        # Multi-key indexes
        self._category_index: Dict[PatternCategory, Set[str]] = collections.defaultdict(set)
        self._dtc_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._engine_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._manufacturer_index: Dict[str, Set[str]] = collections.defaultdict(set)
        self._lifecycle_index: Dict[KnowledgeLifecycle, Set[str]] = collections.defaultdict(set)

    def register_pattern(self, pattern: FailurePattern) -> None:
        """Registers or updates a pattern in the library with clean index rebuilds."""
        pid = pattern.pattern_id
        if pid in self._patterns:
            self._remove_from_indexes(pid)

        self._patterns[pid] = pattern

        # Update Category Index
        self._category_index[pattern.category].add(pid)

        # Update DTC Index
        for dtc in pattern.associated_dtcs:
            self._dtc_index[dtc.strip().upper()].add(pid)

        # Update Vehicle Indexes
        for m in pattern.applicability.manufacturers:
            self._manufacturer_index[m.strip().upper()].add(pid)

        for eng in pattern.applicability.engine_codes:
            self._engine_index[eng.strip().upper()].add(pid)

        # Update Lifecycle Index
        self._lifecycle_index[pattern.lifecycle].add(pid)

    def get_pattern(self, pattern_id: str) -> Optional[FailurePattern]:
        return self._patterns.get(pattern_id)

    def list_patterns(
        self,
        category: Optional[PatternCategory] = None,
        lifecycle: Optional[KnowledgeLifecycle] = None,
    ) -> List[FailurePattern]:
        res = list(self._patterns.values())
        if category:
            res = [p for p in res if p.category == category]
        if lifecycle:
            res = [p for p in res if p.lifecycle == lifecycle]
        return res

    def match_patterns(
        self,
        observed_features: ObservedFeatureSet,
        vehicle_context: Optional[VehicleContext] = None,
        category: Optional[PatternCategory] = None,
        active_only: bool = True,
        max_results: int = 15,
        max_composition_depth: int = 2,
    ) -> List[PatternMatchResult]:
        """
        Deterministic, explainable pattern matcher.
        Evaluates applicability, required features, negative/contradictory evidence,
        and bounded pattern compositions.
        """
        candidate_ids = set(self._patterns.keys())
        if category:
            candidate_ids = candidate_ids.intersection(self._category_index.get(category, set()))

        match_results: List[PatternMatchResult] = []

        for pid in candidate_ids:
            pattern = self._patterns[pid]

            if active_only and pattern.lifecycle != KnowledgeLifecycle.ACTIVE:
                continue

            # 1. Applicability Evaluation
            app_res, spec_weight = pattern.applicability.evaluate(vehicle_context)
            if app_res == ApplicabilityResult.NOT_APPLICABLE:
                continue  # Contradicts vehicle context; fail-closed

            explanations: List[str] = []

            # 2. Operating Condition Check
            if pattern.required_operating_conditions and observed_features.operating_condition != OperatingCondition.UNKNOWN:
                if observed_features.operating_condition not in pattern.required_operating_conditions:
                    continue  # Required operating condition not met

            # 3. Evaluate Feature Requirements
            total_req_weight = 0.0
            earned_weight = 0.0
            satisfied_feats = []
            missing_mandatory = []

            for req in pattern.feature_requirements:
                total_req_weight += req.weight
                obs_val = observed_features.get_feature_value(req.signal_name, req.feature_type)
                sat, score, expl = req.evaluate_feature(obs_val)

                if sat:
                    earned_weight += (score * req.weight)
                    satisfied_feats.append(f"{req.signal_name} ({req.feature_type.value})")
                else:
                    if req.is_mandatory:
                        missing_mandatory.append(f"{req.signal_name} ({req.feature_type.value})")

            # 4. Evaluate Contradictory Features (Negative Evidence)
            contradictory_detected = []
            contradiction_penalty = 0.0

            for contra in pattern.contradictory_features:
                obs_val = observed_features.get_feature_value(contra.signal_name, contra.feature_type)
                if obs_val is not None:
                    # Check if contradictory condition is active
                    is_active, _, expl = contra.evaluate_feature(obs_val)
                    if is_active:
                        contradictory_detected.append(f"{contra.signal_name} ({expl})")
                        contradiction_penalty += (contra.weight * 0.4)

            # Calculate feature match ratio
            feature_ratio = (earned_weight / total_req_weight) if total_req_weight > 0 else 1.0

            # 5. Evaluate Composed Sub-Patterns (Bounded with cycle protection)
            composed_bonus = 0.0
            if pattern.composed_pattern_ids and max_composition_depth > 0:
                composed_bonus = self._evaluate_composed_patterns(
                    pattern.composed_pattern_ids,
                    observed_features,
                    vehicle_context,
                    depth=max_composition_depth - 1,
                    visited={pattern.pattern_id},
                )

            # Overall Score computation
            spec_bonus = min(spec_weight, 5.0) * 0.02
            comp_bonus = composed_bonus * 0.10
            base_score = (feature_ratio * 0.80) + spec_bonus + comp_bonus
            final_score = max(0.0, min(1.0, base_score - contradiction_penalty))

            # Determine Match Grade
            if missing_mandatory or contradictory_detected or final_score < 0.30:
                if final_score < 0.30:
                    grade = PatternMatchGrade.NON_MATCH
                elif contradictory_detected:
                    grade = PatternMatchGrade.NON_MATCH
                    explanations.append(f"Contradictory features active: {contradictory_detected}")
                else:
                    grade = PatternMatchGrade.WEAK_MATCH
                    explanations.append(f"Missing mandatory features: {missing_mandatory}")
            elif final_score >= 0.80:
                grade = PatternMatchGrade.STRONG_MATCH
                explanations.append(f"Strong match on features: {satisfied_feats}")
            elif final_score >= 0.50:
                grade = PatternMatchGrade.PARTIAL_MATCH
                explanations.append(f"Partial match on features: {satisfied_feats}")
            else:
                grade = PatternMatchGrade.WEAK_MATCH

            if spec_weight > 1.0:
                explanations.append(f"Vehicle Specificity Match: {pattern.applicability.scope.value} (Weight: {spec_weight:.1f})")

            match_result = PatternMatchResult(
                pattern=pattern,
                match_grade=grade,
                overall_score=final_score,
                feature_match_ratio=feature_ratio,
                applicability_result=app_res,
                specificity_weight=spec_weight,
                satisfied_features=satisfied_feats,
                missing_mandatory_features=missing_mandatory,
                contradictory_features_detected=contradictory_detected,
                explanations=explanations,
            )
            match_results.append(match_result)

        # Deterministic sorting: overall_score descending, tie-break by pattern_id
        match_results.sort(key=lambda r: (-r.overall_score, r.pattern.pattern_id))
        return match_results[:max_results]

    def _evaluate_composed_patterns(
        self,
        composed_ids: List[str],
        observed: ObservedFeatureSet,
        context: Optional[VehicleContext],
        depth: int,
        visited: Set[str],
    ) -> float:
        """Helper to evaluate sub-patterns recursively with bounded depth and cycle protection."""
        if depth <= 0:
            return 0.0

        scores = []
        for cid in composed_ids:
            if cid in visited or cid not in self._patterns:
                continue
            visited.add(cid)
            sub_pat = self._patterns[cid]
            # Simple feature ratio evaluation for sub-pattern
            sat_count = 0
            for req in sub_pat.feature_requirements:
                val = observed.get_feature_value(req.signal_name, req.feature_type)
                sat, _, _ = req.evaluate_feature(val)
                if sat:
                    sat_count += 1
            ratio = (sat_count / len(sub_pat.feature_requirements)) if sub_pat.feature_requirements else 1.0
            scores.append(ratio)

        return (sum(scores) / len(scores)) if scores else 0.0

    def _remove_from_indexes(self, pattern_id: str) -> None:
        """Cleans indexes before replacing a pattern."""
        p = self._patterns.get(pattern_id)
        if not p:
            return
        self._category_index[p.category].discard(pattern_id)
        for dtc in p.associated_dtcs:
            self._dtc_index[dtc.strip().upper()].discard(pattern_id)
        for m in p.applicability.manufacturers:
            self._manufacturer_index[m.strip().upper()].discard(pattern_id)
        for eng in p.applicability.engine_codes:
            self._engine_index[eng.strip().upper()].discard(pattern_id)
        self._lifecycle_index[p.lifecycle].discard(pattern_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patterns": [p.to_dict() for p in self._patterns.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailurePatternLibraryStore":
        store = cls()
        for p_dict in data.get("patterns", []):
            pat = FailurePattern.from_dict(p_dict)
            store.register_pattern(pat)
        return store


# =====================================================================
# 6. H-LAYER & G-5 INTEGRATIONS
# =====================================================================

class FailurePatternWorkflowAdapter:
    """
    Adapter allowing H-3 (Test Selection), H-4 (Root-Cause Analysis),
    and H-5 (Diagnostic Workflow Engine) to consume Failure Pattern matches.
    """

    def __init__(self, library_store: FailurePatternLibraryStore):
        self.library_store = library_store

    def get_candidate_hypotheses_from_telemetry(
        self,
        observed: ObservedFeatureSet,
        vehicle_context: Optional[VehicleContext] = None,
    ) -> List[str]:
        """Supplies H-4 Root-Cause Analyzer with hypotheses from matched patterns."""
        matches = self.library_store.match_patterns(
            observed_features=observed,
            vehicle_context=vehicle_context,
            active_only=True,
        )
        hypotheses: List[str] = []
        for m in matches:
            if m.match_grade in (PatternMatchGrade.STRONG_MATCH, PatternMatchGrade.PARTIAL_MATCH):
                hypotheses.extend(m.pattern.possible_hypotheses)
        return list(dict.fromkeys(hypotheses))

    def get_distinguishing_tests_for_matched_patterns(
        self,
        observed: ObservedFeatureSet,
        vehicle_context: Optional[VehicleContext] = None,
    ) -> List[KnowledgeDistinguishingTest]:
        """Supplies H-3 Evidence-Driven Test Selector with safe discriminating tests."""
        matches = self.library_store.match_patterns(
            observed_features=observed,
            vehicle_context=vehicle_context,
            active_only=True,
        )
        tests: List[KnowledgeDistinguishingTest] = []
        for m in matches:
            if m.match_grade in (PatternMatchGrade.STRONG_MATCH, PatternMatchGrade.PARTIAL_MATCH):
                tests.extend(m.pattern.distinguishing_tests)
        return tests


class DiagnosticGraphPatternIntegrator:
    """
    Binds matched failure patterns to G-5 DiagnosticGraph nodes.
    Preserves invariant: RELATIONSHIP != CAUSALITY.
    """

    @staticmethod
    def integrate_matched_pattern(
        graph: DiagnosticGraph,
        match: PatternMatchResult,
    ) -> str:
        pat_node_id = f"pattern:{match.pattern.pattern_id}"
        node = GraphNode(
            node_id=pat_node_id,
            node_type=GraphNodeType.ANOMALY,
            label=f"Pattern: {match.pattern.name} ({match.match_grade.value})",
            properties={
                "category": match.pattern.category.value,
                "score": match.overall_score,
                "grade": match.match_grade.value,
                "satisfied_features": match.satisfied_features,
            },
            provenance={"source": "FAILURE_PATTERN_LIBRARY"},
        )
        graph.add_node(node)

        # Link to associated DTCs if they exist in graph
        for dtc in match.pattern.associated_dtcs:
            dtc_id = make_dtc_node_id("ECM", dtc)
            if dtc_id in graph.nodes:
                graph.add_edge(GraphEdge(
                    edge_id=f"edge_pattern_{match.pattern.pattern_id}_{dtc}",
                    source_id=pat_node_id,
                    target_id=dtc_id,
                    edge_type=GraphEdgeType.ASSOCIATED_WITH,
                    confidence=match.overall_score,
                    provenance={"source": "PATTERN_MATCHER"},
                ))

        return pat_node_id
