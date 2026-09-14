# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase L-2: Dynamic Operating Reference and Context-Aware Expected Behavior
=============================================================================
This module implements Phase L-2 of the Seyyanen diagnostic architecture.
It connects live vehicle operating context with expected physical behavior,
answering:
  "Given this specific vehicle, engine, ECU, and operating condition,
   is this observation behaving plausibly?"
rather than:
  "Is this number inside one universal range?"

Strict Architectural Invariants:
  1. CONTEXT-AWARE EXPECTATIONS:
     Expected behavior is conditioned on vehicle model, engine, ECU, and
     operating state. Universal fabricated tables are strictly prohibited.
  2. STRICT PROVENANCE SEPARATION:
     OEM specifications != engineering models != vehicle baselines !=
     technician-confirmed baselines != heuristic inferences != unknown.
  3. NO FABRICATED NUMBERS:
     If no authoritative source or physically justified model exists,
     return UNKNOWN_EXPECTATION. Never manufacture precision.
  4. MISSING & STALE CONTEXT SAFETY:
     Missing context -> INSUFFICIENT_CONTEXT (unknown is not failure).
     Stale context -> STALE_CONTEXT (never used as current ground truth).
     Contradictory context -> CONTRADICTORY_CONTEXT.
  5. BASELINE CONTAMINATION PROTECTION:
     Vehicle baselines are never updated during known fault periods,
     invalid/stale/implausible samples, or communication dropouts.
  6. EVIDENCE IS NOT DIAGNOSIS:
     L-2 produces structured ContextualDeviationEvidence.
     D/H/I layers remain the sole authority for reasoning, test selection,
     and root cause determination.
  7. DTC-FREE ANOMALY SUPPORT:
     Deviations and relationship anomalies produce valid diagnostic evidence
     even when DTC count == 0.
  8. PRESERVATION OF CONTRADICTORY EVIDENCE:
     Contradictory observations are preserved with full fidelity without
     smoothing, averaging, or artificial reconciliation.
  9. STRICT READ-ONLY SAFETY:
     L-2 never authorizes ECU writes, coding, actuation (0x2F), SecurityAccess
     (0x27), or DTC clearing (0x04/0x14).
=============================================================================
"""

from __future__ import annotations

import collections
import copy
import enum
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Integration imports from C, D, K, and L-1 layers
from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    PHYSICS_PLAUSIBLE,
    PHYSICS_IMPLAUSIBLE_HIGH,
    PHYSICS_IMPLAUSIBLE_LOW,
    PHYSICS_UNKNOWN,
    TEMPORAL_PLAUSIBLE,
    TEMPORAL_SUSPECT,
    TEMPORAL_UNKNOWN,
    CORRELATION_COHERENT,
    CORRELATION_INCONSISTENT,
    CORRELATION_UNKNOWN,
    ENVELOPE_NORMAL,
    ENVELOPE_OUT_OF_RANGE_HIGH,
    ENVELOPE_OUT_OF_RANGE_LOW,
    ENVELOPE_UNKNOWN,
    derive_quality_from_status,
)
from extended_did import (
    VehicleContext,
    VehicleApplicability,
    ApplicabilityResult,
    DefinitionTrustLevel,
    StructuredDiagnosticEvidence,
    DataProvenance,
    DecodedField,
)
from vehicle_ecu_knowledge import (
    VehicleModelDefinition,
    VehicleInstanceContext,
    ECUKnowledgeProfile,
    DiagnosticIdentifierKnowledge,
    VehicleECUKnowledgeStore,
    KnowledgeProvenance,
    KnowledgeProvenanceType,
)

logger = logging.getLogger("seyyanen.dynamic_operating_reference")


# =====================================================================
# 1. ENUMS & TAXONOMIES
# =====================================================================

class OperatingState(str, enum.Enum):
    """Deterministic, evidence-derived operating states of the vehicle/powertrain."""
    ENGINE_OFF = "ENGINE_OFF"
    CRANKING = "CRANKING"
    COLD_START = "COLD_START"
    WARMING = "WARMING"
    WARM_IDLE = "WARM_IDLE"
    IDLE = "IDLE"
    PART_LOAD = "PART_LOAD"
    HIGH_LOAD = "HIGH_LOAD"
    DECELERATION = "DECELERATION"
    STEADY_CRUISE = "STEADY_CRUISE"
    TRANSIENT = "TRANSIENT"
    UNKNOWN_STATE = "UNKNOWN_STATE"


class VariableQuality(str, enum.Enum):
    """Quality classification of a context variable."""
    KNOWN_VALID = "KNOWN_VALID"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    INVALID = "INVALID"
    IMPLAUSIBLE = "IMPLAUSIBLE"


class ExpectationModelType(str, enum.Enum):
    """Taxonomy of expected behavior models."""
    FIXED_RANGE = "FIXED_RANGE"
    CONTEXT_DEPENDENT_RANGE = "CONTEXT_DEPENDENT_RANGE"
    RELATIONSHIP_EXPECTATION = "RELATIONSHIP_EXPECTATION"
    TEMPORAL_EXPECTATION = "TEMPORAL_EXPECTATION"
    DYNAMIC_RESPONSE = "DYNAMIC_RESPONSE"
    UNAVAILABLE_UNKNOWN = "UNAVAILABLE_UNKNOWN"


class ExpectationProvenanceType(str, enum.Enum):
    """Authoritative pedigree for expected behavior definitions."""
    OEM_SPECIFICATION = "OEM_SPECIFICATION"
    ENGINEERING_DERIVED = "ENGINEERING_DERIVED"
    VEHICLE_OBSERVED_BASELINE = "VEHICLE_OBSERVED_BASELINE"
    TECHNICIAN_CONFIRMED = "TECHNICIAN_CONFIRMED"
    HEURISTIC_INFERENCE = "HEURISTIC_INFERENCE"
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"


class ExpectationStatus(str, enum.Enum):
    """Evaluation verdict for an observation against expected behavior."""
    EXPECTED_CONFORMANT = "EXPECTED_CONFORMANT"
    DEVIATION = "DEVIATION"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    STALE_CONTEXT = "STALE_CONTEXT"
    CONTRADICTORY_CONTEXT = "CONTRADICTORY_CONTEXT"
    UNKNOWN_EXPECTATION = "UNKNOWN_EXPECTATION"
    INVALID_SAMPLE = "INVALID_SAMPLE"


class EvidenceStrength(str, enum.Enum):
    """Interpretable, calibrated strength of contextual evidence."""
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class EvidencePolarity(str, enum.Enum):
    """Diagnostic direction of the evidence."""
    SUPPORTING = "SUPPORTING"       # Supports normal operation / refutes fault
    CONTRADICTING = "CONTRADICTING" # Supports fault / refutes normal operation
    INSUFFICIENT = "INSUFFICIENT"   # Cannot determine due to missing/stale context


# =====================================================================
# 2. OPERATING CONTEXT DATA STRUCTURES
# =====================================================================

@dataclass
class OperatingContextVariable:
    """Represents a single measured or derived variable in the operating context."""
    name: str
    value: Optional[float]
    unit: str = ""
    timestamp: float = field(default_factory=time.time)
    quality: VariableQuality = VariableQuality.UNKNOWN
    source_ecu: str = "ECM"
    confidence: float = 1.0

    @property
    def is_usable(self) -> bool:
        """Only KNOWN_VALID values may be used for confident expectation evaluation."""
        return self.quality == VariableQuality.KNOWN_VALID and self.value is not None

    def is_fresh(self, max_age: float = 2.0, current_time: Optional[float] = None) -> bool:
        if current_time is None:
            current_time = time.time()
        return (current_time - self.timestamp) <= max_age


@dataclass
class OperatingContext:
    """
    Structured, timestamped snapshot of vehicle operating conditions.
    Supports comprehensive powertrain and vehicle telemetry without requiring
    all variables to be present. Unknown remains strictly unknown.
    """
    timestamp: float = field(default_factory=time.time)
    vehicle_instance_id: Optional[str] = None
    primary_ecu: str = "ECM"
    variables: Dict[str, OperatingContextVariable] = field(default_factory=dict)
    operating_state: OperatingState = OperatingState.UNKNOWN_STATE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def set_variable(
        self,
        name: str,
        value: Optional[float],
        unit: str = "",
        timestamp: Optional[float] = None,
        quality: Optional[VariableQuality] = None,
        source_ecu: str = "ECM",
    ) -> None:
        """Adds or updates a context variable with strict quality classification."""
        clean_name = name.strip().upper()
        ts = timestamp if timestamp is not None else self.timestamp

        if value is None or (isinstance(value, float) and math.isnan(value)):
            qual = VariableQuality.UNKNOWN
            val = None
        elif quality is not None:
            qual = quality
            val = float(value)
        else:
            qual = VariableQuality.KNOWN_VALID
            val = float(value)

        self.variables[clean_name] = OperatingContextVariable(
            name=clean_name,
            value=val,
            unit=unit,
            timestamp=ts,
            quality=qual,
            source_ecu=source_ecu,
        )

    def get_variable(self, name: str) -> Optional[OperatingContextVariable]:
        """Retrieves variable by case-insensitive name."""
        return self.variables.get(name.strip().upper())

    def get_value(self, name: str) -> Optional[float]:
        """Returns physical value if variable exists and is usable; else None."""
        var = self.get_variable(name)
        if var and var.is_usable:
            return var.value
        return None

    def check_completeness(self, required_names: List[str]) -> Tuple[bool, List[str]]:
        """
        Checks whether all required variables are present and usable.
        Returns (is_complete, list_of_missing_names).
        """
        missing = []
        for name in required_names:
            var = self.get_variable(name)
            if var is None or not var.is_usable:
                missing.append(name.strip().upper())
        return (len(missing) == 0, missing)

    def check_freshness(self, required_names: List[str], max_age: float = 2.0) -> Tuple[bool, List[str]]:
        """
        Checks whether required variables are fresh relative to snapshot timestamp.
        Returns (is_fresh, list_of_stale_names).
        """
        stale = []
        for name in required_names:
            var = self.get_variable(name)
            if var is not None and not var.is_fresh(max_age=max_age, current_time=self.timestamp):
                stale.append(name.strip().upper())
        return (len(stale) == 0, stale)

    def detect_contradictions(self) -> List[str]:
        """
        Evaluates physical consistency across available context variables.
        Returns explainable list of contradictions detected.
        """
        contradictions: List[str] = []
        rpm = self.get_value("RPM")
        speed = self.get_value("SPEED") or self.get_value("VEHICLE_SPEED")
        tps = self.get_value("TPS") or self.get_value("THROTTLE")
        map_val = self.get_value("MAP")
        load = self.get_value("LOAD") or self.get_value("ENGINE_LOAD")

        # Contradiction 1: Engine standstill while vehicle moving at speed
        if rpm is not None and speed is not None:
            if rpm < 50 and speed > 15.0:
                contradictions.append(f"Engine standstill (RPM={rpm}) while vehicle moving at speed ({speed} km/h)")

        # Contradiction 2: High throttle with closed/zero MAP
        if tps is not None and map_val is not None:
            if tps > 80.0 and map_val < 25.0:
                contradictions.append(f"Wide open throttle (TPS={tps}%) with extremely low intake pressure (MAP={map_val} kPa)")

        # Contradiction 3: Zero RPM with high engine load
        if rpm is not None and load is not None:
            if rpm < 50 and load > 20.0:
                contradictions.append(f"Engine off (RPM={rpm}) with reported engine load ({load}%)")

        return contradictions

    def classify_operating_state(self) -> OperatingState:
        """
        Deterministically derives engine operating state from available context.
        Strictly returns UNKNOWN_STATE when critical context is missing.
        """
        rpm = self.get_value("RPM")
        speed = self.get_value("SPEED") or self.get_value("VEHICLE_SPEED")
        tps = self.get_value("TPS") or self.get_value("THROTTLE")
        ect = self.get_value("ECT") or self.get_value("COOLANT_TEMP")
        load = self.get_value("LOAD") or self.get_value("ENGINE_LOAD")

        if rpm is None:
            self.operating_state = OperatingState.UNKNOWN_STATE
            return OperatingState.UNKNOWN_STATE

        # 1. Engine Off
        if rpm < 50.0:
            self.operating_state = OperatingState.ENGINE_OFF
            return OperatingState.ENGINE_OFF

        # 2. Cranking
        if 50.0 <= rpm < 450.0:
            self.operating_state = OperatingState.CRANKING
            return OperatingState.CRANKING

        # Engine is running (RPM >= 450)
        # 3. Cold Start / Warming
        if ect is not None:
            if ect < 45.0:
                # If near idle speed and not moving
                if (speed is None or speed < 3.0) and (tps is None or tps < 5.0):
                    self.operating_state = OperatingState.COLD_START
                    return OperatingState.COLD_START
            elif 45.0 <= ect < 75.0:
                self.operating_state = OperatingState.WARMING
                return OperatingState.WARMING

        # 4. Idle / Warm Idle
        is_stationary = speed is None or speed < 3.0
        is_throttle_closed = tps is None or tps < 3.0
        if is_stationary and is_throttle_closed and 500.0 <= rpm <= 1050.0:
            if ect is not None and ect >= 75.0:
                self.operating_state = OperatingState.WARM_IDLE
                return OperatingState.WARM_IDLE
            self.operating_state = OperatingState.IDLE
            return OperatingState.IDLE

        # 5. Deceleration (Fuel cutoff / overrun)
        if speed is not None and speed > 20.0 and is_throttle_closed and rpm > 1200.0:
            self.operating_state = OperatingState.DECELERATION
            return OperatingState.DECELERATION

        # 6. High Load
        if load is not None and load > 75.0:
            self.operating_state = OperatingState.HIGH_LOAD
            return OperatingState.HIGH_LOAD

        # 7. Steady Cruise vs Part Load
        if speed is not None and speed > 40.0 and (tps is not None and 5.0 <= tps <= 40.0):
            if load is not None and 15.0 <= load <= 50.0:
                self.operating_state = OperatingState.STEADY_CRUISE
                return OperatingState.STEADY_CRUISE

        # 8. Part Load fallback
        if rpm >= 1050.0:
            self.operating_state = OperatingState.PART_LOAD
            return OperatingState.PART_LOAD

        self.operating_state = OperatingState.UNKNOWN_STATE
        return OperatingState.UNKNOWN_STATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "vehicle_instance_id": self.vehicle_instance_id,
            "primary_ecu": self.primary_ecu,
            "operating_state": self.operating_state.value,
            "variables": {
                k: {
                    "value": v.value,
                    "unit": v.unit,
                    "timestamp": v.timestamp,
                    "quality": v.quality.value,
                    "source_ecu": v.source_ecu,
                }
                for k, v in self.variables.items()
            },
            "metadata": dict(self.metadata),
        }


# =====================================================================
# 3. STRUCTURED EVIDENCE OUTPUT MODEL
# =====================================================================

@dataclass
class ContextualDeviationEvidence:
    """
    Authoritative structured evidence output produced by Phase L-2.
    Strictly encapsulates actual measurement, operating context snapshot,
    expected behavior model used, deviation, and calibrated evidence polarity.
    Never declares a component defective; provides evidence to D/H/I layers.
    """
    evidence_id: str
    signal_id: str
    actual_value: Optional[float]
    expected_range: Optional[Tuple[float, float]]
    deviation: Optional[float]
    status: ExpectationStatus
    model_id: str
    model_type: ExpectationModelType
    provenance: ExpectationProvenanceType
    strength: EvidenceStrength
    polarity: EvidencePolarity
    context_snapshot: Dict[str, Any]
    operating_state: OperatingState
    timestamp: float = field(default_factory=time.time)
    vehicle_instance_id: Optional[str] = None
    target_ecu: str = "ECM"
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_anomalous(self) -> bool:
        """True if observation deviated significantly from expected behavior."""
        return self.status == ExpectationStatus.DEVIATION and self.polarity == EvidencePolarity.CONTRADICTING

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "signal_id": self.signal_id,
            "actual_value": self.actual_value,
            "expected_range": list(self.expected_range) if self.expected_range else None,
            "deviation": round(self.deviation, 4) if self.deviation is not None else None,
            "status": self.status.value,
            "model_id": self.model_id,
            "model_type": self.model_type.value,
            "provenance": self.provenance.value,
            "strength": self.strength.value,
            "polarity": self.polarity.value,
            "operating_state": self.operating_state.value,
            "timestamp": self.timestamp,
            "vehicle_instance_id": self.vehicle_instance_id,
            "target_ecu": self.target_ecu,
            "reason": self.reason,
            "context_snapshot": self.context_snapshot,
            "metadata": dict(self.metadata),
        }

    def to_c_layer_evidence_status(self) -> str:
        """Translates to existing C/D-layer EVIDENCE constants."""
        if self.polarity == EvidencePolarity.SUPPORTING:
            return "SUPPORTED"
        elif self.polarity == EvidencePolarity.CONTRADICTING:
            return "CONTRADICTED"
        return "UNKNOWN"

    def to_reasoning_evidence_contribution(self) -> Any:
        """Translates contextual deviation into an authoritative I-5 ReasoningEvidenceContribution."""
        from advanced_reasoning_layer import ReasoningEvidenceContribution, EvidenceDirection, SignalQuality, KnowledgeConfidence

        # Map direction
        direction = EvidenceDirection.SUPPORTS if self.polarity == EvidencePolarity.SUPPORTING else (
            EvidenceDirection.CONTRADICTS if self.polarity == EvidencePolarity.CONTRADICTING else EvidenceDirection.NEUTRAL
        )

        # Map weight from strength
        weight_map = {
            EvidenceStrength.WEAK: 0.5,
            EvidenceStrength.MODERATE: 1.0,
            EvidenceStrength.STRONG: 1.5,
        }
        weight = weight_map.get(self.strength, 1.0)

        # Map confidence
        conf = KnowledgeConfidence.HIGH if self.provenance == ExpectationProvenanceType.OEM_SPECIFICATION else KnowledgeConfidence.MEDIUM

        return ReasoningEvidenceContribution(
            contribution_id=self.evidence_id,
            source="L2_DYNAMIC_EXPECTATION",
            evidence_type="DYNAMIC_DEVIATION" if self.status == ExpectationStatus.DEVIATION else "DYNAMIC_CONFORMANCE",
            value_summary=self.reason,
            quality=SignalQuality.GOOD if self.status != ExpectationStatus.INVALID_SAMPLE else SignalQuality.INVALID,
            direction=direction,
            weight=weight,
            confidence=conf,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL if self.provenance == ExpectationProvenanceType.OEM_SPECIFICATION else KnowledgeProvenanceType.DERIVED_HEURISTIC,
                source_reference=self.model_id,
            ),
        )

    def to_structured_diagnostic_evidence(self) -> Any:
        """Translates to C/D-layer StructuredDiagnosticEvidence for legacy pipeline compatibility."""
        from extended_did import DiagnosticDataDefinition, IdentifierNamespace, DecodedField, DataProvenance, DefinitionTrustLevel, ApplicabilityResult

        dummy_def = DiagnosticDataDefinition(
            definition_id=self.model_id,
            identifier=self.signal_id,
            ecu_target=self.target_ecu,
            service_id="01",
            name=self.signal_id,
            namespace=IdentifierNamespace.STANDARD_OBD_PID,
        )

        return StructuredDiagnosticEvidence(
            definition=dummy_def,
            raw_response=None,
            raw_value=self.actual_value,
            decoded_value=self.actual_value,
            fields={
                "deviation": DecodedField(
                    field_name="deviation",
                    raw_value=self.deviation,
                    decoded_value=self.deviation,
                    unit="",
                    is_valid=(self.status != ExpectationStatus.INVALID_SAMPLE),
                )
            },
            unit=self.metadata.get("unit", ""),
            quality=QUALITY_GOOD if self.polarity == EvidencePolarity.SUPPORTING else QUALITY_SUSPECT,
            is_valid=(self.status != ExpectationStatus.INVALID_SAMPLE),
            status=STATUS_VALID,
            provenance=DataProvenance(
                source_ecu=self.target_ecu,
                identifier=self.signal_id,
                service_id="01",
                request_timestamp=self.timestamp,
                response_timestamp=self.timestamp,
                elapsed_time=0.0,
                transaction_id=self.evidence_id,
                definition_id=self.model_id,
                definition_version="1",
                trust_level=DefinitionTrustLevel.OEM_DOCUMENTED if self.provenance == ExpectationProvenanceType.OEM_SPECIFICATION else DefinitionTrustLevel.VERIFIED_TESTED,
                applicability=ApplicabilityResult.CONFIRMED_APPLICABLE,
            ),
        )


# =====================================================================
# 4. EXPECTED BEHAVIOR MODEL ABSTRACTIONS
# =====================================================================

class ExpectedBehaviorModel:
    """
    Abstract base class for deterministic, context-aware expectation models.
    Guarantees explainable evaluation and immutable provenance tracking.
    """
    def __init__(
        self,
        model_id: str,
        signal_id: str,
        model_type: ExpectationModelType,
        provenance: ExpectationProvenanceType,
        applicability: Optional[VehicleApplicability] = None,
        target_ecu: str = "ECM",
        schema_version: int = 1,
        description: str = "",
    ):
        self.model_id = model_id
        self.signal_id = signal_id.strip().upper()
        self.model_type = model_type
        self.provenance = provenance
        self.applicability = applicability or VehicleApplicability()
        self.target_ecu = target_ecu.strip().upper()
        self.schema_version = schema_version
        self.description = description

    def evaluate(
        self,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None, # [(timestamp, value), ...]
    ) -> ContextualDeviationEvidence:
        """
        Evaluates observation against expected behavior given operating context.
        Subclasses implement exact physical or relationship logic.
        """
        raise NotImplementedError("Subclasses must implement evaluate()")


# ---------------------------------------------------------------------
# Model A: Fixed Authoritative Range
# ---------------------------------------------------------------------
class FixedRangeExpectationModel(ExpectedBehaviorModel):
    """
    Authoritative static physical envelope (e.g. thermostat operating range).
    Only valid when explicitly supported by OEM/standards documentation.
    """
    def __init__(
        self,
        model_id: str,
        signal_id: str,
        min_value: float,
        max_value: float,
        unit: str,
        provenance: ExpectationProvenanceType = ExpectationProvenanceType.OEM_SPECIFICATION,
        applicability: Optional[VehicleApplicability] = None,
        target_ecu: str = "ECM",
        description: str = "",
    ):
        super().__init__(
            model_id=model_id,
            signal_id=signal_id,
            model_type=ExpectationModelType.FIXED_RANGE,
            provenance=provenance,
            applicability=applicability,
            target_ecu=target_ecu,
            description=description,
        )
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        self.unit = unit

    def evaluate(
        self,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None,
    ) -> ContextualDeviationEvidence:
        ev_id = f"ev_{uuid.uuid4().hex[:8]}"

        if actual_value is None or math.isnan(actual_value):
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=None,
                expected_range=(self.min_value, self.max_value),
                deviation=None,
                status=ExpectationStatus.INVALID_SAMPLE,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason="Sample value is missing or NaN",
            )

        in_range = self.min_value <= actual_value <= self.max_value
        deviation = 0.0
        if actual_value < self.min_value:
            deviation = actual_value - self.min_value
        elif actual_value > self.max_value:
            deviation = actual_value - self.max_value

        status = ExpectationStatus.EXPECTED_CONFORMANT if in_range else ExpectationStatus.DEVIATION
        polarity = EvidencePolarity.SUPPORTING if in_range else EvidencePolarity.CONTRADICTING
        strength = EvidenceStrength.STRONG if abs(deviation) > (self.max_value - self.min_value) * 0.2 else EvidenceStrength.MODERATE

        reason = (
            f"{self.signal_id} {actual_value} {self.unit} within fixed envelope [{self.min_value}, {self.max_value}]"
            if in_range else
            f"{self.signal_id} {actual_value} {self.unit} outside fixed envelope [{self.min_value}, {self.max_value}] (deviation: {deviation:.2f})"
        )

        return ContextualDeviationEvidence(
            evidence_id=ev_id,
            signal_id=self.signal_id,
            actual_value=actual_value,
            expected_range=(self.min_value, self.max_value),
            deviation=deviation,
            status=status,
            model_id=self.model_id,
            model_type=self.model_type,
            provenance=self.provenance,
            strength=strength,
            polarity=polarity,
            context_snapshot=context.to_dict()["variables"],
            operating_state=context.operating_state,
            timestamp=context.timestamp,
            vehicle_instance_id=context.vehicle_instance_id,
            target_ecu=self.target_ecu,
            reason=reason,
        )


# ---------------------------------------------------------------------
# Model B: Context-Dependent Range
# ---------------------------------------------------------------------
class ContextDependentRangeModel(ExpectedBehaviorModel):
    """
    Expected behavior conditioned dynamically on multiple operating variables
    (e.g., MAP expected bounds change with RPM, load, throttle, and engine state).
    """
    def __init__(
        self,
        model_id: str,
        signal_id: str,
        required_context_variables: List[str],
        range_evaluator: Callable[[OperatingContext], Optional[Tuple[float, float]]],
        unit: str,
        provenance: ExpectationProvenanceType = ExpectationProvenanceType.ENGINEERING_DERIVED,
        applicability: Optional[VehicleApplicability] = None,
        target_ecu: str = "ECM",
        max_context_age: float = 2.0,
        description: str = "",
    ):
        super().__init__(
            model_id=model_id,
            signal_id=signal_id,
            model_type=ExpectationModelType.CONTEXT_DEPENDENT_RANGE,
            provenance=provenance,
            applicability=applicability,
            target_ecu=target_ecu,
            description=description,
        )
        self.required_context_variables = [v.strip().upper() for v in required_context_variables]
        self.range_evaluator = range_evaluator
        self.unit = unit
        self.max_context_age = max_context_age

    def evaluate(
        self,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None,
    ) -> ContextualDeviationEvidence:
        ev_id = f"ev_{uuid.uuid4().hex[:8]}"

        # 1. Verify context completeness
        is_complete, missing = context.check_completeness(self.required_context_variables)
        if not is_complete:
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.INSUFFICIENT_CONTEXT,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason=f"Insufficient context: missing required variables {missing}",
            )

        # 2. Verify context freshness
        is_fresh, stale = context.check_freshness(self.required_context_variables, max_age=self.max_context_age)
        if not is_fresh:
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.STALE_CONTEXT,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason=f"Stale context: variables {stale} exceed maximum age {self.max_context_age}s",
            )

        # 3. Check for contradictory context
        contradictions = context.detect_contradictions()
        if contradictions:
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.CONTRADICTORY_CONTEXT,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason=f"Contradictory context detected: {'; '.join(contradictions)}",
            )

        if actual_value is None or math.isnan(actual_value):
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=None,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.INVALID_SAMPLE,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason="Sample value is missing or NaN",
            )

        # 4. Evaluate dynamic range for current context
        bounds = self.range_evaluator(context)
        if bounds is None:
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.UNKNOWN_EXPECTATION,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason="Dynamic model could not establish expectation for current operating point",
            )

        min_val, max_val = bounds
        in_range = min_val <= actual_value <= max_val
        deviation = 0.0
        if actual_value < min_val:
            deviation = actual_value - min_val
        elif actual_value > max_val:
            deviation = actual_value - max_val

        status = ExpectationStatus.EXPECTED_CONFORMANT if in_range else ExpectationStatus.DEVIATION
        polarity = EvidencePolarity.SUPPORTING if in_range else EvidencePolarity.CONTRADICTING
        span = max(1.0, max_val - min_val)
        rel_dev = abs(deviation) / span
        strength = EvidenceStrength.STRONG if rel_dev > 0.4 else (EvidenceStrength.MODERATE if rel_dev > 0.15 else EvidenceStrength.WEAK)

        reason = (
            f"{self.signal_id} {actual_value} {self.unit} matches expected range [{min_val:.1f}, {max_val:.1f}] in state {context.operating_state.value}"
            if in_range else
            f"{self.signal_id} {actual_value} {self.unit} deviates from expected range [{min_val:.1f}, {max_val:.1f}] in state {context.operating_state.value} (deviation: {deviation:.2f})"
        )

        return ContextualDeviationEvidence(
            evidence_id=ev_id,
            signal_id=self.signal_id,
            actual_value=actual_value,
            expected_range=(min_val, max_val),
            deviation=deviation,
            status=status,
            model_id=self.model_id,
            model_type=self.model_type,
            provenance=self.provenance,
            strength=strength,
            polarity=polarity,
            context_snapshot=context.to_dict()["variables"],
            operating_state=context.operating_state,
            timestamp=context.timestamp,
            vehicle_instance_id=context.vehicle_instance_id,
            target_ecu=self.target_ecu,
            reason=reason,
        )


# ---------------------------------------------------------------------
# Model C: Relationship-Based Expectation
# ---------------------------------------------------------------------
class RelationshipExpectationModel(ExpectedBehaviorModel):
    """
    Evaluates physical consistency and correlation between related signals
    (e.g., MAF vs RPM*LOAD, Throttle vs MAP, Lambda vs Fuel Trims).
    """
    def __init__(
        self,
        model_id: str,
        signal_id: str,
        related_signal_id: str,
        relationship_check: Callable[[float, float, OperatingContext], Tuple[bool, float, str]],
        provenance: ExpectationProvenanceType = ExpectationProvenanceType.ENGINEERING_DERIVED,
        applicability: Optional[VehicleApplicability] = None,
        target_ecu: str = "ECM",
        description: str = "",
    ):
        super().__init__(
            model_id=model_id,
            signal_id=signal_id,
            model_type=ExpectationModelType.RELATIONSHIP_EXPECTATION,
            provenance=provenance,
            applicability=applicability,
            target_ecu=target_ecu,
            description=description,
        )
        self.related_signal_id = related_signal_id.strip().upper()
        self.relationship_check = relationship_check

    def evaluate(
        self,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None,
    ) -> ContextualDeviationEvidence:
        ev_id = f"ev_{uuid.uuid4().hex[:8]}"

        if actual_value is None or math.isnan(actual_value):
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=None,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.INVALID_SAMPLE,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason="Primary signal sample value is missing or NaN",
            )

        related_var = context.get_variable(self.related_signal_id)
        if related_var is None or not related_var.is_usable:
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.INSUFFICIENT_CONTEXT,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason=f"Related signal {self.related_signal_id} is missing or unusable in operating context",
            )

        # Check freshness of related variable
        if not related_var.is_fresh(max_age=2.0, current_time=context.timestamp):
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.STALE_CONTEXT,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason=f"Related signal {self.related_signal_id} is stale relative to primary observation",
            )

        is_coherent, dev_metric, reason_text = self.relationship_check(actual_value, related_var.value, context)

        status = ExpectationStatus.EXPECTED_CONFORMANT if is_coherent else ExpectationStatus.DEVIATION
        polarity = EvidencePolarity.SUPPORTING if is_coherent else EvidencePolarity.CONTRADICTING
        strength = EvidenceStrength.STRONG if abs(dev_metric) > 0.3 else EvidenceStrength.MODERATE

        return ContextualDeviationEvidence(
            evidence_id=ev_id,
            signal_id=self.signal_id,
            actual_value=actual_value,
            expected_range=None,
            deviation=dev_metric,
            status=status,
            model_id=self.model_id,
            model_type=self.model_type,
            provenance=self.provenance,
            strength=strength,
            polarity=polarity,
            context_snapshot=context.to_dict()["variables"],
            operating_state=context.operating_state,
            timestamp=context.timestamp,
            vehicle_instance_id=context.vehicle_instance_id,
            target_ecu=self.target_ecu,
            reason=reason_text,
        )


# ---------------------------------------------------------------------
# Model D: Temporal Expectation
# ---------------------------------------------------------------------
class TemporalExpectationModel(ExpectedBehaviorModel):
    """
    Evaluates signal rate-of-change, monotonic warm-up behavior, and stuck/frozen signals.
    Requires chronological sample history [(timestamp, value), ...].
    """
    def __init__(
        self,
        model_id: str,
        signal_id: str,
        max_rate_of_change_per_s: Optional[float] = None,
        min_rate_of_change_per_s: Optional[float] = None,
        max_frozen_duration_s: Optional[float] = None,
        require_monotonic_increase: bool = False,
        unit: str = "",
        provenance: ExpectationProvenanceType = ExpectationProvenanceType.ENGINEERING_DERIVED,
        applicability: Optional[VehicleApplicability] = None,
        target_ecu: str = "ECM",
        description: str = "",
    ):
        super().__init__(
            model_id=model_id,
            signal_id=signal_id,
            model_type=ExpectationModelType.TEMPORAL_EXPECTATION,
            provenance=provenance,
            applicability=applicability,
            target_ecu=target_ecu,
            description=description,
        )
        self.max_rate_of_change_per_s = max_rate_of_change_per_s
        self.min_rate_of_change_per_s = min_rate_of_change_per_s
        self.max_frozen_duration_s = max_frozen_duration_s
        self.require_monotonic_increase = require_monotonic_increase
        self.unit = unit

    def evaluate(
        self,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None,
    ) -> ContextualDeviationEvidence:
        ev_id = f"ev_{uuid.uuid4().hex[:8]}"

        if actual_value is None or math.isnan(actual_value):
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=None,
                expected_range=None,
                deviation=None,
                status=ExpectationStatus.INVALID_SAMPLE,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason="Sample value is missing or NaN",
            )

        if not history or len(history) < 2:
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=None,
                deviation=0.0,
                status=ExpectationStatus.INSUFFICIENT_CONTEXT,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.WEAK,
                polarity=EvidencePolarity.INSUFFICIENT,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason="Insufficient historical samples for temporal evaluation",
            )

        # 1. Rate of change check against previous sample
        prev_ts, prev_val = history[-2]
        curr_ts = context.timestamp
        dt = max(0.001, curr_ts - prev_ts)
        rate = abs(actual_value - prev_val) / dt

        if self.max_rate_of_change_per_s is not None and rate > self.max_rate_of_change_per_s:
            dev = rate - self.max_rate_of_change_per_s
            return ContextualDeviationEvidence(
                evidence_id=ev_id,
                signal_id=self.signal_id,
                actual_value=actual_value,
                expected_range=(0.0, self.max_rate_of_change_per_s),
                deviation=dev,
                status=ExpectationStatus.DEVIATION,
                model_id=self.model_id,
                model_type=self.model_type,
                provenance=self.provenance,
                strength=EvidenceStrength.STRONG,
                polarity=EvidencePolarity.CONTRADICTING,
                context_snapshot=context.to_dict()["variables"],
                operating_state=context.operating_state,
                timestamp=context.timestamp,
                vehicle_instance_id=context.vehicle_instance_id,
                target_ecu=self.target_ecu,
                reason=f"{self.signal_id} rate of change {rate:.2f} {self.unit}/s exceeds max allowed {self.max_rate_of_change_per_s} {self.unit}/s",
            )

        # 2. Frozen signal check
        if self.max_frozen_duration_s is not None:
            # Check how long value has remained identical to within epsilon
            frozen_start = curr_ts
            for ts, val in reversed(history):
                if abs(val - actual_value) > 1e-4:
                    break
                frozen_start = ts
            frozen_dur = curr_ts - frozen_start
            if frozen_dur >= self.max_frozen_duration_s:
                return ContextualDeviationEvidence(
                    evidence_id=ev_id,
                    signal_id=self.signal_id,
                    actual_value=actual_value,
                    expected_range=None,
                    deviation=frozen_dur,
                    status=ExpectationStatus.DEVIATION,
                    model_id=self.model_id,
                    model_type=self.model_type,
                    provenance=self.provenance,
                    strength=EvidenceStrength.MODERATE,
                    polarity=EvidencePolarity.CONTRADICTING,
                    context_snapshot=context.to_dict()["variables"],
                    operating_state=context.operating_state,
                    timestamp=context.timestamp,
                    vehicle_instance_id=context.vehicle_instance_id,
                    target_ecu=self.target_ecu,
                    reason=f"{self.signal_id} signal frozen at {actual_value} for {frozen_dur:.1f}s (threshold: {self.max_frozen_duration_s}s)",
                )

        # 3. Monotonic increase during warm-up check
        if self.require_monotonic_increase and context.operating_state in (OperatingState.COLD_START, OperatingState.WARMING):
            if actual_value < prev_val - 2.0: # Allow 2.0C noise/thermostat opening dip
                dev = prev_val - actual_value
                return ContextualDeviationEvidence(
                    evidence_id=ev_id,
                    signal_id=self.signal_id,
                    actual_value=actual_value,
                    expected_range=(prev_val, prev_val + 50.0),
                    deviation=dev,
                    status=ExpectationStatus.DEVIATION,
                    model_id=self.model_id,
                    model_type=self.model_type,
                    provenance=self.provenance,
                    strength=EvidenceStrength.MODERATE,
                    polarity=EvidencePolarity.CONTRADICTING,
                    context_snapshot=context.to_dict()["variables"],
                    operating_state=context.operating_state,
                    timestamp=context.timestamp,
                    vehicle_instance_id=context.vehicle_instance_id,
                    target_ecu=self.target_ecu,
                    reason=f"{self.signal_id} dropped unexpectedly from {prev_val} to {actual_value} during warm-up",
                )

        return ContextualDeviationEvidence(
            evidence_id=ev_id,
            signal_id=self.signal_id,
            actual_value=actual_value,
            expected_range=None,
            deviation=0.0,
            status=ExpectationStatus.EXPECTED_CONFORMANT,
            model_id=self.model_id,
            model_type=self.model_type,
            provenance=self.provenance,
            strength=EvidenceStrength.WEAK,
            polarity=EvidencePolarity.SUPPORTING,
            context_snapshot=context.to_dict()["variables"],
            operating_state=context.operating_state,
            timestamp=context.timestamp,
            vehicle_instance_id=context.vehicle_instance_id,
            target_ecu=self.target_ecu,
            reason=f"{self.signal_id} temporal behavior conformant (rate: {rate:.2f} {self.unit}/s)",
        )


# ---------------------------------------------------------------------
# Model E: Unavailable / Unknown Expectation
# ---------------------------------------------------------------------
class UnavailableExpectationModel(ExpectedBehaviorModel):
    """
    Authoritatively represents the absence of an expected behavior definition.
    Guarantees no fabricated precision or guessed ranges.
    """
    def __init__(
        self,
        model_id: str,
        signal_id: str,
        target_ecu: str = "ECM",
        description: str = "No authoritative expectation available",
    ):
        super().__init__(
            model_id=model_id,
            signal_id=signal_id,
            model_type=ExpectationModelType.UNAVAILABLE_UNKNOWN,
            provenance=ExpectationProvenanceType.UNKNOWN_PROVENANCE,
            target_ecu=target_ecu,
            description=description,
        )

    def evaluate(
        self,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None,
    ) -> ContextualDeviationEvidence:
        return ContextualDeviationEvidence(
            evidence_id=f"ev_{uuid.uuid4().hex[:8]}",
            signal_id=self.signal_id,
            actual_value=actual_value,
            expected_range=None,
            deviation=None,
            status=ExpectationStatus.UNKNOWN_EXPECTATION,
            model_id=self.model_id,
            model_type=self.model_type,
            provenance=self.provenance,
            strength=EvidenceStrength.WEAK,
            polarity=EvidencePolarity.INSUFFICIENT,
            context_snapshot=context.to_dict()["variables"],
            operating_state=context.operating_state,
            timestamp=context.timestamp,
            vehicle_instance_id=context.vehicle_instance_id,
            target_ecu=self.target_ecu,
            reason=f"No authoritative reference exists for {self.signal_id} in current context",
        )


# =====================================================================
# 5. VEHICLE OBSERVED BASELINE & CONTAMINATION PROTECTION
# =====================================================================

@dataclass
class VehicleObservedBaseline:
    """
    Represents an empirical baseline learned exclusively from a specific vehicle instance.
    Never universalized to other vehicles; guarded against contamination.
    """
    vehicle_instance_id: str
    signal_id: str
    operating_state: OperatingState
    mean_value: float
    std_dev: float
    min_observed: float
    max_observed: float
    sample_count: int
    time_range: Tuple[float, float]
    provenance: ExpectationProvenanceType = ExpectationProvenanceType.VEHICLE_OBSERVED_BASELINE
    is_technician_confirmed: bool = False
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def plausible_bounds(self) -> Tuple[float, float]:
        """Returns 3-sigma statistical envelope bounded by physical observations."""
        margin = max(self.std_dev * 3.0, (self.max_observed - self.min_observed) * 0.1)
        return (self.mean_value - margin, self.mean_value + margin)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_instance_id": self.vehicle_instance_id,
            "signal_id": self.signal_id,
            "operating_state": self.operating_state.value,
            "mean_value": round(self.mean_value, 4),
            "std_dev": round(self.std_dev, 4),
            "min_observed": round(self.min_observed, 4),
            "max_observed": round(self.max_observed, 4),
            "sample_count": self.sample_count,
            "time_range": list(self.time_range),
            "provenance": self.provenance.value,
            "is_technician_confirmed": self.is_technician_confirmed,
            "version": self.version,
            "metadata": dict(self.metadata),
        }


class BaselineContaminationGuard:
    """
    Enforces strict physical and diagnostic filters before allowing any live observation
    to update or contribute to a vehicle instance's learned baseline.
    """
    @classmethod
    def can_ingest_sample(
        cls,
        value: Optional[float],
        quality: VariableQuality,
        status: str,
        is_fault_period_active: bool,
        active_dtcs: List[str],
        is_context_contradictory: bool,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether a sample is admissible to the vehicle baseline.
        Returns (is_admissible, rejection_reason).
        """
        if is_fault_period_active:
            return False, "Rejected: active vehicle fault period"
        if active_dtcs:
            return False, f"Rejected: active DTCs present ({active_dtcs})"
        if status != STATUS_VALID:
            return False, f"Rejected: invalid communication status '{status}'"
        if quality != VariableQuality.KNOWN_VALID:
            return False, f"Rejected: non-valid sample quality '{quality.value}'"
        if value is None or math.isnan(value):
            return False, "Rejected: missing or NaN value"
        if is_context_contradictory:
            return False, "Rejected: contradictory operating context"
        return True, "Admissible"


# =====================================================================
# 6. DYNAMIC OPERATING REFERENCE ENGINE
# =====================================================================

class DynamicOperatingReferenceEngine:
    """
    Authoritative Phase L-2 Engine.
    Resolves models through the L-1 knowledge hierarchy, manages baselines,
    evaluates live observations against context, and produces structured evidence.
    """
    def __init__(
        self,
        knowledge_store: Optional[VehicleECUKnowledgeStore] = None,
    ):
        self.knowledge_store = knowledge_store or VehicleECUKnowledgeStore()
        self._models: Dict[str, List[ExpectedBehaviorModel]] = collections.defaultdict(list)
        self._baselines: Dict[str, VehicleObservedBaseline] = {} # key: f"{instance_id}:{signal_id}:{state}"
        self._lock = threading.RLock()

        # Wire built-in authoritative engineering models for standard signals
        self._initialize_standard_models()

    def _baseline_key(self, instance_id: str, signal_id: str, state: OperatingState) -> str:
        return f"{instance_id.strip()}:{signal_id.strip().upper()}:{state.value}"

    def register_model(self, model: ExpectedBehaviorModel) -> None:
        """Registers an expected behavior model with thread safety."""
        with self._lock:
            self._models[model.signal_id.upper()].append(model)

    def register_baseline(self, baseline: VehicleObservedBaseline) -> None:
        """Registers a vehicle-specific observed baseline."""
        with self._lock:
            key = self._baseline_key(baseline.vehicle_instance_id, baseline.signal_id, baseline.operating_state)
            self._baselines[key] = baseline

    def get_baseline(
        self,
        instance_id: str,
        signal_id: str,
        state: OperatingState,
    ) -> Optional[VehicleObservedBaseline]:
        """Retrieves vehicle baseline if available."""
        with self._lock:
            key = self._baseline_key(instance_id, signal_id, state)
            return self._baselines.get(key)

    def resolve_model(
        self,
        signal_id: str,
        target_ecu: str = "ECM",
        vehicle_context: Optional[VehicleContext] = None,
        vehicle_instance_id: Optional[str] = None,
    ) -> Optional[ExpectedBehaviorModel]:
        """
        Resolves the most specific expectation model matching the vehicle hierarchy.
        Exact instance baseline > Specific ECU/Engine model > Vehicle family > Generic.
        """
        with self._lock:
            sig = signal_id.strip().upper()
            ecu = target_ecu.strip().upper()
            candidates = self._models.get(sig, [])

            matching = [
                m for m in candidates
                if m.target_ecu == ecu or m.target_ecu == "GENERIC"
            ]
            if not matching:
                return None

            # Specificity scoring matching L-1
            best_model = None
            best_score = -1.0

            for m in matching:
                app_res = m.applicability.evaluate(vehicle_context)
                if app_res == ApplicabilityResult.NOT_APPLICABLE:
                    continue

                score = 10.0 # Base generic score
                if app_res == ApplicabilityResult.CONFIRMED_APPLICABLE:
                    score += 40.0
                    if not m.applicability._is_universal():
                        score += 30.0 # Specific OEM / vehicle rule bonus
                elif app_res == ApplicabilityResult.LIKELY_APPLICABLE:
                    score += 20.0
                    if not m.applicability._is_universal():
                        score += 15.0

                if m.target_ecu == ecu:
                    score += 15.0

                if score > best_score:
                    best_score = score
                    best_model = m

            return best_model

    def evaluate_observation(
        self,
        signal_id: str,
        actual_value: Optional[float],
        context: OperatingContext,
        history: Optional[List[Tuple[float, float]]] = None,
        target_ecu: str = "ECM",
        vehicle_context: Optional[VehicleContext] = None,
    ) -> ContextualDeviationEvidence:
        """
        Core evaluation entry point.
        Evaluates physical observation against context-aware models or learned baselines.
        """
        sig = signal_id.strip().upper()
        ecu = target_ecu.strip().upper()

        # 1. First check if a vehicle-specific baseline exists for this instance and state
        if context.vehicle_instance_id:
            baseline = self.get_baseline(context.vehicle_instance_id, sig, context.operating_state)
            if baseline is not None:
                # Use vehicle-specific baseline as context model
                min_val, max_val = baseline.plausible_bounds
                in_range = actual_value is not None and (min_val <= actual_value <= max_val)
                dev = 0.0
                if actual_value is not None:
                    if actual_value < min_val:
                        dev = actual_value - min_val
                    elif actual_value > max_val:
                        dev = actual_value - max_val

                status = ExpectationStatus.EXPECTED_CONFORMANT if in_range else ExpectationStatus.DEVIATION
                polarity = EvidencePolarity.SUPPORTING if in_range else EvidencePolarity.CONTRADICTING
                prov = (
                    ExpectationProvenanceType.TECHNICIAN_CONFIRMED
                    if baseline.is_technician_confirmed else
                    ExpectationProvenanceType.VEHICLE_OBSERVED_BASELINE
                )

                reason = (
                    f"{sig} {actual_value} conforms to vehicle instance {context.vehicle_instance_id} baseline [{min_val:.1f}, {max_val:.1f}] in state {context.operating_state.value}"
                    if in_range else
                    f"{sig} {actual_value} deviates from vehicle instance {context.vehicle_instance_id} baseline [{min_val:.1f}, {max_val:.1f}] (deviation: {dev:.2f})"
                )

                return ContextualDeviationEvidence(
                    evidence_id=f"ev_{uuid.uuid4().hex[:8]}",
                    signal_id=sig,
                    actual_value=actual_value,
                    expected_range=(min_val, max_val),
                    deviation=dev,
                    status=status,
                    model_id=f"baseline_{context.vehicle_instance_id}_{sig}",
                    model_type=ExpectationModelType.CONTEXT_DEPENDENT_RANGE,
                    provenance=prov,
                    strength=EvidenceStrength.STRONG if abs(dev) > 0.3 * (max_val - min_val) else EvidenceStrength.MODERATE,
                    polarity=polarity,
                    context_snapshot=context.to_dict()["variables"],
                    operating_state=context.operating_state,
                    timestamp=context.timestamp,
                    vehicle_instance_id=context.vehicle_instance_id,
                    target_ecu=ecu,
                    reason=reason,
                )

        # 2. Resolve authoritative expectation model
        model = self.resolve_model(sig, target_ecu=ecu, vehicle_context=vehicle_context)
        if model is None:
            # Truthfully return UNKNOWN_EXPECTATION; never fabricate numbers
            unk_model = UnavailableExpectationModel(
                model_id=f"unk_{sig}",
                signal_id=sig,
                target_ecu=ecu,
            )
            return unk_model.evaluate(actual_value, context, history=history)

        return model.evaluate(actual_value, context, history=history)

    def _initialize_standard_models(self) -> None:
        """
        Initializes authoritative physical models for standard powertrain parameters.
        All models have strict, verifiable physical justification and explicit provenance.
        """
        # Model 1: Engine Coolant Temperature (Thermostat Operating Envelope)
        # Authoritative SAE/OEM specification: Standard passenger vehicle operating temp 80°C - 105°C
        ect_model = FixedRangeExpectationModel(
            model_id="OEM_SPEC_ECT_WARM_OPERATING",
            signal_id="ECT",
            min_value=75.0,
            max_value=110.0,
            unit="°C",
            provenance=ExpectationProvenanceType.OEM_SPECIFICATION,
            description="Authoritative operating temperature envelope for fully warm liquid-cooled ICE",
        )
        self.register_model(ect_model)

        # Model 2: Dynamic Intake Manifold Pressure (MAP)
        # Conditioned on RPM, Throttle, and Operating State
        def map_evaluator(ctx: OperatingContext) -> Optional[Tuple[float, float]]:
            st = ctx.operating_state
            tps = ctx.get_value("TPS") or ctx.get_value("THROTTLE")
            if st == OperatingState.ENGINE_OFF:
                # Engine off: MAP should equal barometric pressure (~95 to 105 kPa at sea level)
                return (90.0, 105.0)
            elif st in (OperatingState.IDLE, OperatingState.WARM_IDLE):
                # Idle: high manifold vacuum (low absolute pressure: 25 to 45 kPa for naturally aspirated)
                return (24.0, 48.0)
            elif st == OperatingState.DECELERATION:
                # Decel overrun: highest manifold vacuum (15 to 30 kPa)
                return (15.0, 32.0)
            elif st == OperatingState.HIGH_LOAD:
                # Wide open throttle / high load: near atmospheric or boosted (85 to 110+ kPa)
                return (80.0, 115.0)
            elif st == OperatingState.PART_LOAD:
                # Part load cruising
                return (35.0, 80.0)
            return None

        map_model = ContextDependentRangeModel(
            model_id="ENG_DERIVED_MAP_DYNAMIC_ENVELOPE",
            signal_id="MAP",
            required_context_variables=["RPM"],
            range_evaluator=map_evaluator,
            unit="kPa",
            provenance=ExpectationProvenanceType.ENGINEERING_DERIVED,
            description="Context-conditioned intake manifold absolute pressure expectations",
        )
        self.register_model(map_model)

        # Model 3: MAF vs Engine Load Cross-Sensor Relationship
        # In naturally aspirated engines, MAF roughly scales with (RPM * Load / 100)
        def maf_load_check(maf_val: float, load_val: float, ctx: OperatingContext) -> Tuple[bool, float, str]:
            rpm = ctx.get_value("RPM")
            if rpm is None or rpm < 400:
                return True, 0.0, "Engine off or cranking; MAF-Load check bypassed"

            # Check if MAF is 0 while load is reported high (>30%)
            if maf_val < 0.5 and load_val > 30.0:
                return False, -1.0, f"MAF shows zero flow ({maf_val} g/s) while engine load is high ({load_val}%)"

            # Check if load is 0 while MAF shows substantial flow (>20 g/s)
            if load_val < 2.0 and maf_val > 25.0:
                return False, 1.0, f"Engine load reports 0% while MAF shows significant flow ({maf_val} g/s)"

            return True, 0.0, f"MAF ({maf_val} g/s) coherent with Engine Load ({load_val}%)"

        maf_rel_model = RelationshipExpectationModel(
            model_id="ENG_DERIVED_MAF_LOAD_CORRELATION",
            signal_id="MAF",
            related_signal_id="LOAD",
            relationship_check=maf_load_check,
            provenance=ExpectationProvenanceType.ENGINEERING_DERIVED,
            description="Cross-sensor plausibility between Mass Air Flow and Calculated Engine Load",
        )
        self.register_model(maf_rel_model)

        # Model 4: Engine Speed (RPM) vs Vehicle Speed Standstill Correlation
        def rpm_speed_check(speed_val: float, rpm_val: float, ctx: OperatingContext) -> Tuple[bool, float, str]:
            if rpm_val < 50.0 and speed_val > 15.0:
                return False, speed_val, f"Vehicle moving at {speed_val} km/h while engine speed is 0 RPM"
            return True, 0.0, f"Vehicle speed {speed_val} km/h coherent with engine RPM {rpm_val}"

        speed_rpm_model = RelationshipExpectationModel(
            model_id="ENG_DERIVED_SPEED_RPM_CORRELATION",
            signal_id="SPEED",
            related_signal_id="RPM",
            relationship_check=rpm_speed_check,
            provenance=ExpectationProvenanceType.ENGINEERING_DERIVED,
            description="Plausibility check between vehicle road speed and engine rotation",
        )
        self.register_model(speed_rpm_model)

        # Model 5: ECT Warm-Up Monotonicity and Rate Limit
        ect_temporal_model = TemporalExpectationModel(
            model_id="ENG_DERIVED_ECT_TEMPORAL_MONITOR",
            signal_id="ECT",
            max_rate_of_change_per_s=5.0,     # >5°C per second is physical sensor spike
            max_frozen_duration_s=300.0,      # >5 minutes frozen at non-ambient is suspect
            require_monotonic_increase=True,  # During warm-up phase
            unit="°C",
            provenance=ExpectationProvenanceType.ENGINEERING_DERIVED,
            description="Temporal rate-of-change and monotonicity monitor for coolant temperature",
        )
        self.register_model(ect_temporal_model)
