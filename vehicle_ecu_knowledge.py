# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase I-2: Vehicle & ECU Knowledge Subsystem
=============================================================================
This module implements Phase I-2 of the Seyyanen diagnostic architecture.
It builds upon Phase I-1 (Diagnostic Knowledge Base) by establishing structured,
context-aware vehicle, engine, transmission, and ECU knowledge.

Diagnostic meaning depends on the specific vehicle and ECU configuration:
  - The same DTC, PID, DID, or sensor reading can represent different fault
    mechanisms, normal operating envelopes, or root causes depending on:
    Manufacturer -> Model -> Generation -> Engine -> Transmission -> ECU Family -> Calibration.

Strict Architectural Invariants:
  1. PROGRESSIVE IDENTITY & UNCERTAINTY PRESERVATION:
     Never silently infers a more specific vehicle or ECU identity than the
     available evidence supports. Distinguishes KNOWN, CONFIRMED, and INFERRED.
  2. CONTEXTUAL MEANING != PROOF:
     DTCs, sensor readings, and anomaly patterns remain evidence. DTC is NOT root cause.
  3. COMMUNICATION FAULT != COMPONENT FAILURE:
     Unreachable ECUs or bus timeouts are strictly classified as network/wiring/power
     issues, never as internal electronic defects without direct physical proof.
  4. VEHICLE INSTANCE BOUNDARY:
     Instance-specific findings (e.g. bound to a specific VIN) must never leak
     into universal model-wide knowledge without explicit validation.
  5. EXPLICIT OVERRIDES & EXCEPTION MODEL:
     A vehicle-specific or ECU-specific exception can qualify or override generic
     automotive knowledge without mutating or deleting the generic rule.
  6. SAFETY GATED:
     All vehicle/ECU knowledge remains strictly advisory. Zero autonomous
     execution of destructive UDS/OBD services or direct transport frame dispatching.
  7. 100% DETERMINISTIC & BOUNDED:
     Specificity ranking, lookup, conflict detection, and inheritance resolution
     are completely deterministic.
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

# Integration imports from C, D, G, H, and I-1 layers
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
from multi_ecu_diagnostics import (
    ECUTarget,
    ECUTargetType,
    ECUDiscoveryState,
    ECUCapabilityState,
    ECUHealthState,
    MultiECUVehicleContext,
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
    KnowledgeMatchResult,
    DiagnosticKnowledgeStore,
)

logger = logging.getLogger("seyyanen.vehicle_ecu_knowledge")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class IdentityConfidenceLevel(str, enum.Enum):
    """Calibrated confidence level of a vehicle or ECU identity attribute."""
    CONFIRMED = "CONFIRMED"          # Confirmed by physical ECU response or authoritative VIN
    KNOWN = "KNOWN"                  # Positively identified via standard profile/manual entry
    INFERRED = "INFERRED"            # Inferred from telemetry signals or broadcast headers
    UNKNOWN = "UNKNOWN"              # Not identified / unverified


class IdentitySource(str, enum.Enum):
    """Provenance source of identity information."""
    VIN_DECODED = "VIN_DECODED"                    # Mode 09 or UDS VIN parsing
    ECU_IDENTIFICATION = "ECU_IDENTIFICATION"      # UDS Service 0x22 DID F187/F190/F189
    BROADCAST_HEADER = "BROADCAST_HEADER"          # Passive CAN bus message header
    MANUAL_USER_INPUT = "MANUAL_USER_INPUT"        # Entered by technician
    SYSTEM_INFERRED = "SYSTEM_INFERRED"            # Signal pattern inference
    IMPORTED_SPECIFICATION = "IMPORTED_SPEC"       # Technical database or profile import


class FuelType(str, enum.Enum):
    """Engine fuel classification."""
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    HYBRID = "HYBRID"
    PLUG_IN_HYBRID = "PHEV"
    BATTERY_ELECTRIC = "BEV"
    FLEX_FUEL = "FLEX_FUEL"
    CNG_LPG = "CNG_LPG"
    UNKNOWN = "UNKNOWN"


class AspirationType(str, enum.Enum):
    """Engine intake aspiration classification."""
    NATURALLY_ASPIRATED = "NATURALLY_ASPIRATED"
    TURBOCHARGED = "TURBOCHARGED"
    SUPERCHARGED = "SUPERCHARGED"
    TWIN_TURBO = "TWIN_TURBO"
    UNKNOWN = "UNKNOWN"


class TransmissionType(str, enum.Enum):
    """Driveline transmission classification."""
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"
    AUTOMATED_MANUAL = "AUTOMATED_MANUAL"
    CVT = "CVT"
    DUAL_CLUTCH = "DUAL_CLUTCH"
    DIRECT_DRIVE = "DIRECT_DRIVE"  # EV Single-speed
    UNKNOWN = "UNKNOWN"


class DrivetrainType(str, enum.Enum):
    """Vehicle drivetrain layout."""
    FWD = "FWD"
    RWD = "RWD"
    AWD = "AWD"
    FOUR_WD = "4WD"
    UNKNOWN = "UNKNOWN"


# =====================================================================
# 2. STRUCTURED DOMAIN KNOWLEDGE MODELS
# =====================================================================

@dataclass
class EngineKnowledgeProfile:
    """
    Structured domain knowledge representing an internal combustion engine or powertrain unit.
    Captures displacement, nominal operating parameters, and known diagnostic characteristics.
    """
    engine_code: str                             # e.g. "F14D3", "Z16XER", "LDE"
    engine_family: Optional[str] = None          # e.g. "GM Family 1", "Ecotec"
    displacement_liters: Optional[float] = None  # e.g. 1.4, 1.6, 2.0
    cylinder_count: int = 4
    fuel_type: FuelType = FuelType.GASOLINE
    aspiration: AspirationType = AspirationType.NATURALLY_ASPIRATED
    nominal_idle_rpm: float = 800.0
    nominal_idle_maf_gps: Optional[float] = None # e.g. 2.2 g/s for 1.4L NA
    nominal_idle_map_kpa: Optional[float] = None # e.g. 32.0 kPa
    has_variable_valve_timing: bool = False
    has_direct_injection: bool = False
    known_peculiarities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine_code": self.engine_code,
            "engine_family": self.engine_family,
            "displacement_liters": self.displacement_liters,
            "cylinder_count": self.cylinder_count,
            "fuel_type": self.fuel_type.value,
            "aspiration": self.aspiration.value,
            "nominal_idle_rpm": self.nominal_idle_rpm,
            "nominal_idle_maf_gps": self.nominal_idle_maf_gps,
            "nominal_idle_map_kpa": self.nominal_idle_map_kpa,
            "has_variable_valve_timing": self.has_variable_valve_timing,
            "has_direct_injection": self.has_direct_injection,
            "known_peculiarities": list(self.known_peculiarities),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineKnowledgeProfile":
        return cls(
            engine_code=data["engine_code"],
            engine_family=data.get("engine_family"),
            displacement_liters=data.get("displacement_liters"),
            cylinder_count=data.get("cylinder_count", 4),
            fuel_type=FuelType(data.get("fuel_type", "GASOLINE")),
            aspiration=AspirationType(data.get("aspiration", "NATURALLY_ASPIRATED")),
            nominal_idle_rpm=float(data.get("nominal_idle_rpm", 800.0)),
            nominal_idle_maf_gps=data.get("nominal_idle_maf_gps"),
            nominal_idle_map_kpa=data.get("nominal_idle_map_kpa"),
            has_variable_valve_timing=bool(data.get("has_variable_valve_timing", False)),
            has_direct_injection=bool(data.get("has_direct_injection", False)),
            known_peculiarities=data.get("known_peculiarities", []),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class TransmissionKnowledgeProfile:
    """
    Structured domain knowledge representing a transmission / gearbox system.
    """
    transmission_code: str                       # e.g. "4T40E", "M20", "DSI-6"
    transmission_type: TransmissionType = TransmissionType.AUTOMATIC
    gear_count: int = 5
    drivetrain: DrivetrainType = DrivetrainType.FWD
    has_torque_converter: bool = True
    supports_tcc_lockup: bool = True
    known_peculiarities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transmission_code": self.transmission_code,
            "transmission_type": self.transmission_type.value,
            "gear_count": self.gear_count,
            "drivetrain": self.drivetrain.value,
            "has_torque_converter": self.has_torque_converter,
            "supports_tcc_lockup": self.supports_tcc_lockup,
            "known_peculiarities": list(self.known_peculiarities),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransmissionKnowledgeProfile":
        return cls(
            transmission_code=data["transmission_code"],
            transmission_type=TransmissionType(data.get("transmission_type", "AUTOMATIC")),
            gear_count=data.get("gear_count", 5),
            drivetrain=DrivetrainType(data.get("drivetrain", "FWD")),
            has_torque_converter=bool(data.get("has_torque_converter", True)),
            supports_tcc_lockup=bool(data.get("supports_tcc_lockup", True)),
            known_peculiarities=data.get("known_peculiarities", []),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ECUKnowledgeProfile:
    """
    Structured domain knowledge representing an Electronic Control Unit.
    Tracks hardware revision, software version, calibration IDs, and network headers.
    """
    logical_id: str                              # e.g. "ECM", "TCM", "ABS", "BCM"
    ecu_type: ECUTargetType = ECUTargetType.ENGINE
    module_family: Optional[str] = None          # e.g. "DELPHI_MT80", "SIMTEC76", "BOSCH_MED17"
    hardware_id: Optional[str] = None            # e.g. "HW_96800112"
    software_id: Optional[str] = None            # e.g. "SW_96800223"
    calibration_id: Optional[str] = None         # e.g. "CAL_280194"
    request_header: str = "7E0"
    response_header: str = "7E8"
    protocol: str = "ISO_15765_4_CAN_11BIT"
    supported_services: Set[str] = field(default_factory=set)
    supported_dids: Set[str] = field(default_factory=set)
    supported_pids: Set[str] = field(default_factory=set)
    known_quirks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logical_id": self.logical_id,
            "ecu_type": self.ecu_type.value,
            "module_family": self.module_family,
            "hardware_id": self.hardware_id,
            "software_id": self.software_id,
            "calibration_id": self.calibration_id,
            "request_header": self.request_header,
            "response_header": self.response_header,
            "protocol": self.protocol,
            "supported_services": sorted(list(self.supported_services)),
            "supported_dids": sorted(list(self.supported_dids)),
            "supported_pids": sorted(list(self.supported_pids)),
            "known_quirks": list(self.known_quirks),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ECUKnowledgeProfile":
        return cls(
            logical_id=data["logical_id"],
            ecu_type=ECUTargetType(data.get("ecu_type", "ENGINE")),
            module_family=data.get("module_family"),
            hardware_id=data.get("hardware_id"),
            software_id=data.get("software_id"),
            calibration_id=data.get("calibration_id"),
            request_header=data.get("request_header", "7E0"),
            response_header=data.get("response_header", "7E8"),
            protocol=data.get("protocol", "ISO_15765_4_CAN_11BIT"),
            supported_services=set(data.get("supported_services", [])),
            supported_dids=set(data.get("supported_dids", [])),
            supported_pids=set(data.get("supported_pids", [])),
            known_quirks=data.get("known_quirks", []),
            metadata=dict(data.get("metadata", {})),
        )


# =====================================================================
# 3. PROGRESSIVE VEHICLE IDENTITY MODEL
# =====================================================================

@dataclass
class ProgressiveVehicleIdentity:
    """
    Progressive vehicle identity hierarchy.
    Enforces that uncertainty is strictly preserved without silent over-specification.
    Wraps and enriches existing VehicleContext and MultiECUVehicleContext.
    """
    # Level 1: Manufacturer / Brand
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    # Level 2: Model & Generation
    model: Optional[str] = None
    generation: Optional[str] = None             # e.g. "T250", "Astra-H"
    platform: Optional[str] = None               # e.g. "GM_DELTA", "GM_T200"
    # Level 3: Model Year / Range
    model_year: Optional[int] = None
    production_range: Optional[str] = None       # e.g. "2006-2011"
    market_region: Optional[str] = None          # e.g. "EUROPE", "NORTH_AMERICA"
    # Level 4: Engine Profile
    engine: Optional[EngineKnowledgeProfile] = None
    # Level 5: Transmission Profile
    transmission: Optional[TransmissionKnowledgeProfile] = None
    # Level 6: ECU Profiles (mapped by logical_id e.g. "ECM", "TCM")
    ecus: Dict[str, ECUKnowledgeProfile] = field(default_factory=dict)
    # Level 7: Vehicle Instance (VIN & instance-specific markers)
    vin: Optional[str] = None
    is_instance_specific: bool = False
    # Identity confidence and provenance tracking
    confidence_levels: Dict[str, IdentityConfidenceLevel] = field(default_factory=dict)
    identity_sources: Dict[str, IdentitySource] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_base_vehicle_context(self) -> VehicleContext:
        """Converts to existing standard VehicleContext model."""
        ecm = self.ecus.get("ECM")
        return VehicleContext(
            manufacturer=self.manufacturer,
            model=self.model,
            model_year=self.model_year,
            engine_code=self.engine.engine_code if self.engine else None,
            transmission=self.transmission.transmission_type.value if self.transmission else None,
            ecu_family=ecm.module_family if ecm else None,
            software_id=ecm.software_id if ecm else None,
            vin=self.vin,
            metadata=dict(self.metadata),
        )

    @classmethod
    def from_vehicle_context(
        cls,
        ctx: VehicleContext,
        source: IdentitySource = IdentitySource.MANUAL_USER_INPUT,
        confidence: IdentityConfidenceLevel = IdentityConfidenceLevel.KNOWN,
    ) -> "ProgressiveVehicleIdentity":
        """Instantiates progressive identity from existing VehicleContext without losing data."""
        pvi = cls(
            manufacturer=ctx.manufacturer,
            model=ctx.model,
            model_year=ctx.model_year,
            vin=ctx.vin,
            is_instance_specific=bool(ctx.vin and len(str(ctx.vin).strip()) >= 11),
        )
        if ctx.engine_code:
            pvi.engine = EngineKnowledgeProfile(engine_code=ctx.engine_code)
            pvi.confidence_levels["engine"] = confidence
            pvi.identity_sources["engine"] = source

        if ctx.transmission:
            pvi.transmission = TransmissionKnowledgeProfile(
                transmission_code=ctx.transmission,
                transmission_type=TransmissionType(ctx.transmission) if ctx.transmission in TransmissionType._value2member_map_ else TransmissionType.UNKNOWN,
            )
            pvi.confidence_levels["transmission"] = confidence
            pvi.identity_sources["transmission"] = source

        if ctx.ecu_family or ctx.software_id:
            ecm = ECUKnowledgeProfile(
                logical_id="ECM",
                ecu_type=ECUTargetType.ENGINE,
                module_family=ctx.ecu_family,
                software_id=ctx.software_id,
            )
            pvi.ecus["ECM"] = ecm
            pvi.confidence_levels["ecus.ECM"] = confidence
            pvi.identity_sources["ecus.ECM"] = source

        if ctx.manufacturer:
            pvi.confidence_levels["manufacturer"] = confidence
            pvi.identity_sources["manufacturer"] = source
        if ctx.model:
            pvi.confidence_levels["model"] = confidence
            pvi.identity_sources["model"] = source
        if ctx.model_year:
            pvi.confidence_levels["model_year"] = confidence
            pvi.identity_sources["model_year"] = source
        if ctx.vin:
            pvi.confidence_levels["vin"] = confidence
            pvi.identity_sources["vin"] = source

        return pvi

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manufacturer": self.manufacturer,
            "brand": self.brand,
            "model": self.model,
            "generation": self.generation,
            "platform": self.platform,
            "model_year": self.model_year,
            "production_range": self.production_range,
            "market_region": self.market_region,
            "engine": self.engine.to_dict() if self.engine else None,
            "transmission": self.transmission.to_dict() if self.transmission else None,
            "ecus": {k: v.to_dict() for k, v in self.ecus.items()},
            "vin": self.vin,
            "is_instance_specific": self.is_instance_specific,
            "confidence_levels": {k: v.value for k, v in self.confidence_levels.items()},
            "identity_sources": {k: v.value for k, v in self.identity_sources.items()},
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProgressiveVehicleIdentity":
        engine_data = data.get("engine")
        trans_data = data.get("transmission")
        ecus_dict = {}
        for k, v in data.get("ecus", {}).items():
            ecus_dict[k] = ECUKnowledgeProfile.from_dict(v)

        return cls(
            manufacturer=data.get("manufacturer"),
            brand=data.get("brand"),
            model=data.get("model"),
            generation=data.get("generation"),
            platform=data.get("platform"),
            model_year=data.get("model_year"),
            production_range=data.get("production_range"),
            market_region=data.get("market_region"),
            engine=EngineKnowledgeProfile.from_dict(engine_data) if engine_data else None,
            transmission=TransmissionKnowledgeProfile.from_dict(trans_data) if trans_data else None,
            ecus=ecus_dict,
            vin=data.get("vin"),
            is_instance_specific=bool(data.get("is_instance_specific", False)),
            confidence_levels={k: IdentityConfidenceLevel(v) for k, v in data.get("confidence_levels", {}).items()},
            identity_sources={k: IdentitySource(v) for k, v in data.get("identity_sources", {}).items()},
            metadata=dict(data.get("metadata", {})),
        )


# =====================================================================
# 4. CONTEXTUAL DIAGNOSTIC SPECIFICATIONS
# =====================================================================

@dataclass
class ContextualDTCInterpretation:
    """
    Context-aware DTC interpretation.
    Captures how the meaning, root cause candidates, and verification actions
    of a specific trouble code vary by vehicle, engine, or ECU calibration.
    """
    interpretation_id: str
    dtc_code: str
    target_ecu: str                              # e.g. "ECM", "TCM", "ABS"
    applicability: KnowledgeApplicabilityCriteria
    contextual_title: str
    contextual_description: str
    likely_root_causes: List[str] = field(default_factory=list)
    secondary_effects: List[str] = field(default_factory=list)
    recommended_tests: List[KnowledgeDistinguishingTest] = field(default_factory=list)
    verification_actions: List[str] = field(default_factory=list)
    provenance: KnowledgeProvenance = field(default_factory=lambda: KnowledgeProvenance(
        source_type=KnowledgeProvenanceType.OEM_MANUAL,
        source_reference="OEM Service Manual",
    ))
    is_instance_specific: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interpretation_id": self.interpretation_id,
            "dtc_code": self.dtc_code,
            "target_ecu": self.target_ecu,
            "applicability": self.applicability.to_dict(),
            "contextual_title": self.contextual_title,
            "contextual_description": self.contextual_description,
            "likely_root_causes": list(self.likely_root_causes),
            "secondary_effects": list(self.secondary_effects),
            "recommended_tests": [rt.to_dict() for rt in self.recommended_tests],
            "verification_actions": list(self.verification_actions),
            "provenance": self.provenance.to_dict(),
            "is_instance_specific": self.is_instance_specific,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextualDTCInterpretation":
        return cls(
            interpretation_id=data["interpretation_id"],
            dtc_code=data["dtc_code"],
            target_ecu=data.get("target_ecu", "ECM"),
            applicability=KnowledgeApplicabilityCriteria.from_dict(data["applicability"]),
            contextual_title=data["contextual_title"],
            contextual_description=data["contextual_description"],
            likely_root_causes=data.get("likely_root_causes", []),
            secondary_effects=data.get("secondary_effects", []),
            recommended_tests=[KnowledgeDistinguishingTest.from_dict(rt) for rt in data.get("recommended_tests", [])],
            verification_actions=data.get("verification_actions", []),
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            is_instance_specific=bool(data.get("is_instance_specific", False)),
        )


@dataclass
class ContextualSignalInterpretation:
    """
    Context-aware parameter/signal interpretation.
    Defines nominal operational envelopes, valid units, and scale interpretations
    for a PID/DID signal specific to an engine or ECU configuration.
    """
    signal_id: str                               # e.g. "MAF", "MAP", "RPM", "ECT"
    service_id: str                              # e.g. "01", "22"
    identifier: str                              # e.g. "10", "1640"
    target_ecu: str                              # e.g. "ECM"
    applicability: KnowledgeApplicabilityCriteria
    operating_condition: OperatingCondition
    nominal_min: float
    nominal_max: float
    unit: str
    rationale: str = ""

    def is_within_envelope(self, value: float) -> bool:
        """Evaluates whether measured physical value falls within nominal envelope."""
        return self.nominal_min <= value <= self.nominal_max

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "service_id": self.service_id,
            "identifier": self.identifier,
            "target_ecu": self.target_ecu,
            "applicability": self.applicability.to_dict(),
            "operating_condition": self.operating_condition.value,
            "nominal_min": self.nominal_min,
            "nominal_max": self.nominal_max,
            "unit": self.unit,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextualSignalInterpretation":
        return cls(
            signal_id=data["signal_id"],
            service_id=data["service_id"],
            identifier=data["identifier"],
            target_ecu=data.get("target_ecu", "ECM"),
            applicability=KnowledgeApplicabilityCriteria.from_dict(data["applicability"]),
            operating_condition=OperatingCondition(data["operating_condition"]),
            nominal_min=float(data["nominal_min"]),
            nominal_max=float(data["nominal_max"]),
            unit=data.get("unit", ""),
            rationale=data.get("rationale", ""),
        )


@dataclass
class ContextualOverride:
    """
    Explicit vehicle- or ECU-specific qualification/override.
    Allows a specific rule to qualify or offset generic knowledge without deleting it.
    """
    override_id: str
    target_generic_knowledge_id: str
    applicability: KnowledgeApplicabilityCriteria
    override_reason: str
    adjusted_parameters: Dict[str, Any] = field(default_factory=dict)
    provenance: KnowledgeProvenance = field(default_factory=lambda: KnowledgeProvenance(
        source_type=KnowledgeProvenanceType.TECHNICAL_SERVICE_BULLETIN,
        source_reference="TSB Update",
    ))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "override_id": self.override_id,
            "target_generic_knowledge_id": self.target_generic_knowledge_id,
            "applicability": self.applicability.to_dict(),
            "override_reason": self.override_reason,
            "adjusted_parameters": dict(self.adjusted_parameters),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextualOverride":
        return cls(
            override_id=data["override_id"],
            target_generic_knowledge_id=data["target_generic_knowledge_id"],
            applicability=KnowledgeApplicabilityCriteria.from_dict(data["applicability"]),
            override_reason=data.get("override_reason", ""),
            adjusted_parameters=dict(data.get("adjusted_parameters", {})),
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
        )


# =====================================================================
# 5. VEHICLE & ECU KNOWLEDGE STORE & RESOLUTION ENGINE
# =====================================================================

class VehicleECUKnowledgeStore:
    """
    Specialized store for Vehicle, Engine, Transmission, and ECU contextual knowledge.
    Integrates directly with I-1 DiagnosticKnowledgeStore.
    Provides deterministic specificity ranking:
      Exact Calibration (Score +10) > ECU Family (+6) > Engine (+4) >
      Transmission (+3) > Model/Gen (+2) > Manufacturer (+1) > Universal (+0).
    """

    def __init__(self, base_store: Optional[DiagnosticKnowledgeStore] = None):
        self.base_store = base_store or DiagnosticKnowledgeStore()
        # Profiles
        self._engines: Dict[str, EngineKnowledgeProfile] = {}
        self._transmissions: Dict[str, TransmissionKnowledgeProfile] = {}
        self._ecus: Dict[str, ECUKnowledgeProfile] = {}
        # Contextual Interpretations
        self._dtc_interpretations: List[ContextualDTCInterpretation] = []
        self._signal_interpretations: List[ContextualSignalInterpretation] = []
        self._overrides: List[ContextualOverride] = []
        # Multi-key indexes
        self._dtc_index: Dict[str, List[ContextualDTCInterpretation]] = collections.defaultdict(list)
        self._signal_index: Dict[str, List[ContextualSignalInterpretation]] = collections.defaultdict(list)

    # -----------------------------------------------------------------
    # A. Profile Registration
    # -----------------------------------------------------------------

    def register_engine_profile(self, profile: EngineKnowledgeProfile) -> None:
        self._engines[profile.engine_code.strip().upper()] = profile

    def get_engine_profile(self, engine_code: str) -> Optional[EngineKnowledgeProfile]:
        return self._engines.get(engine_code.strip().upper())

    def register_transmission_profile(self, profile: TransmissionKnowledgeProfile) -> None:
        self._transmissions[profile.transmission_code.strip().upper()] = profile

    def get_transmission_profile(self, transmission_code: str) -> Optional[TransmissionKnowledgeProfile]:
        return self._transmissions.get(transmission_code.strip().upper())

    def register_ecu_profile(self, profile: ECUKnowledgeProfile) -> None:
        key = f"{profile.logical_id}:{profile.module_family or 'GENERIC'}:{profile.software_id or 'DEFAULT'}".upper()
        self._ecus[key] = profile

    def register_dtc_interpretation(self, interpretation: ContextualDTCInterpretation) -> None:
        self._dtc_interpretations.append(interpretation)
        self._dtc_index[interpretation.dtc_code.strip().upper()].append(interpretation)

    def register_signal_interpretation(self, interpretation: ContextualSignalInterpretation) -> None:
        self._signal_interpretations.append(interpretation)
        self._signal_index[interpretation.signal_id.strip().upper()].append(interpretation)

    def register_override(self, override: ContextualOverride) -> None:
        self._overrides.append(override)

    # -----------------------------------------------------------------
    # B. Contextual Query & Specificity Resolution
    # -----------------------------------------------------------------

    def resolve_dtc_interpretation(
        self,
        dtc_code: str,
        target_ecu: str = "ECM",
        identity: Optional[ProgressiveVehicleIdentity] = None,
    ) -> List[Tuple[ContextualDTCInterpretation, float, str]]:
        """
        Resolves applicable DTC interpretations ranked by vehicle/ECU specificity.
        Returns list of (ContextualDTCInterpretation, specificity_score, match_explanation).
        """
        code = dtc_code.strip().upper()
        ecu = target_ecu.strip().upper()
        candidates = self._dtc_index.get(code, [])

        results: List[Tuple[ContextualDTCInterpretation, float, str]] = []
        base_ctx = identity.to_base_vehicle_context() if identity else None

        for cand in candidates:
            if cand.target_ecu.strip().upper() != ecu:
                continue

            app_res, spec_weight = cand.applicability.evaluate(base_ctx)
            if app_res == ApplicabilityResult.NOT_APPLICABLE:
                continue

            # Additional specificity bonus for ECU software/hardware matches
            spec_score = spec_weight
            explanation_parts = [f"DTC {code} on {ecu}"]

            if identity and identity.ecus.get(ecu):
                ecu_prof = identity.ecus[ecu]
                if cand.applicability.software_versions and ecu_prof.software_id:
                    if ecu_prof.software_id.upper() in [s.upper() for s in cand.applicability.software_versions]:
                        spec_score += 10.0
                        explanation_parts.append(f"Exact Software Match: {ecu_prof.software_id}")

                if cand.applicability.ecu_families and ecu_prof.module_family:
                    if ecu_prof.module_family.upper() in [f.upper() for f in cand.applicability.ecu_families]:
                        spec_score += 6.0
                        explanation_parts.append(f"ECU Family Match: {ecu_prof.module_family}")

            if identity and identity.engine and cand.applicability.engine_codes:
                if identity.engine.engine_code.upper() in [e.upper() for e in cand.applicability.engine_codes]:
                    spec_score += 4.0
                    explanation_parts.append(f"Engine Match: {identity.engine.engine_code}")

            if cand.provenance.is_technician_confirmed:
                spec_score += 2.0
                explanation_parts.append("Technician Confirmed (+2.0)")

            results.append((cand, spec_score, "; ".join(explanation_parts)))

        # Deterministic sorting by specificity score descending, tie-break by interpretation_id
        results.sort(key=lambda r: (-r[1], r[0].interpretation_id))
        return results

    def resolve_signal_envelope(
        self,
        signal_id: str,
        operating_condition: OperatingCondition,
        target_ecu: str = "ECM",
        identity: Optional[ProgressiveVehicleIdentity] = None,
    ) -> Optional[ContextualSignalInterpretation]:
        """
        Retrieves the most specific nominal signal envelope for the given vehicle context.
        """
        sig = signal_id.strip().upper()
        ecu = target_ecu.strip().upper()
        candidates = self._signal_index.get(sig, [])

        best_match: Optional[ContextualSignalInterpretation] = None
        highest_score: float = -1.0
        base_ctx = identity.to_base_vehicle_context() if identity else None

        for cand in candidates:
            if cand.target_ecu.strip().upper() != ecu:
                continue
            if cand.operating_condition != operating_condition:
                continue

            app_res, spec_weight = cand.applicability.evaluate(base_ctx)
            if app_res == ApplicabilityResult.NOT_APPLICABLE:
                continue

            if spec_weight > highest_score:
                highest_score = spec_weight
                best_match = cand

        return best_match

    def query_contextualized_knowledge(
        self,
        identity: Optional[ProgressiveVehicleIdentity] = None,
        dtcs: Optional[List[str]] = None,
        symptoms: Optional[List[str]] = None,
        operating_condition: Optional[OperatingCondition] = None,
        max_results: int = 15,
    ) -> List[KnowledgeMatchResult]:
        """
        Queries base I-1 DiagnosticKnowledgeStore with contextual specificity boosts,
        override evaluations, and progressive vehicle identity filtering.
        """
        base_ctx = identity.to_base_vehicle_context() if identity else None
        base_matches = self.base_store.query_knowledge(
            vehicle_context=base_ctx,
            dtcs=dtcs,
            symptoms=symptoms,
            max_results=max_results * 2,
        )

        contextual_results: List[KnowledgeMatchResult] = []

        for m in base_matches:
            # Check for applicable overrides
            score_boost = 0.0
            override_applied = False

            for ovr in self._overrides:
                if ovr.target_generic_knowledge_id == m.entry.knowledge_id:
                    app_res, _ = ovr.applicability.evaluate(base_ctx)
                    if app_res == ApplicabilityResult.CONFIRMED_APPLICABLE:
                        m.match_explanations.append(f"Contextual Override Applied: {ovr.override_reason}")
                        score_boost += 3.0
                        override_applied = True

            # Check operating condition agreement
            if operating_condition:
                for ep in m.entry.evidence_patterns:
                    if operating_condition in ep.operating_conditions:
                        score_boost += 2.0
                        m.match_explanations.append(f"Matched Operating Condition: {operating_condition.value}")
                        break

            m.total_score += score_boost
            contextual_results.append(m)

        # Deterministic sort
        contextual_results.sort(key=lambda r: (-r.total_score, r.entry.knowledge_id))
        return contextual_results[:max_results]

    def to_dict(self) -> Dict[str, Any]:
        """Serializes entire Vehicle/ECU Knowledge Store to deterministic dictionary."""
        return {
            "engines": {k: v.to_dict() for k, v in self._engines.items()},
            "transmissions": {k: v.to_dict() for k, v in self._transmissions.items()},
            "ecus": {k: v.to_dict() for k, v in self._ecus.items()},
            "dtc_interpretations": [di.to_dict() for di in self._dtc_interpretations],
            "signal_interpretations": [si.to_dict() for si in self._signal_interpretations],
            "overrides": [ov.to_dict() for ov in self._overrides],
            "base_store": self.base_store.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VehicleECUKnowledgeStore":
        """Reconstructs store from serialized representation."""
        base_store = DiagnosticKnowledgeStore.from_dict(data.get("base_store", {}))
        store = cls(base_store=base_store)

        for eng_data in data.get("engines", {}).values():
            store.register_engine_profile(EngineKnowledgeProfile.from_dict(eng_data))

        for trans_data in data.get("transmissions", {}).values():
            store.register_transmission_profile(TransmissionKnowledgeProfile.from_dict(trans_data))

        for ecu_data in data.get("ecus", {}).values():
            store.register_ecu_profile(ECUKnowledgeProfile.from_dict(ecu_data))

        for di_data in data.get("dtc_interpretations", []):
            store.register_dtc_interpretation(ContextualDTCInterpretation.from_dict(di_data))

        for si_data in data.get("signal_interpretations", []):
            store.register_signal_interpretation(ContextualSignalInterpretation.from_dict(si_data))

        for ov_data in data.get("overrides", []):
            store.register_override(ContextualOverride.from_dict(ov_data))

        return store


# =====================================================================
# 6. H-LAYER & G-5 INTEGRATIONS
# =====================================================================

class ContextualWorkflowAdapter:
    """
    Adapter allowing H-3 (Test Selection), H-4 (Root-Cause Analysis),
    and H-5 (Diagnostic Workflow Engine) to consume vehicle/ECU knowledge.
    """

    def __init__(self, store: VehicleECUKnowledgeStore):
        self.store = store

    def get_contextual_root_causes(
        self,
        dtc_code: str,
        target_ecu: str = "ECM",
        identity: Optional[ProgressiveVehicleIdentity] = None,
    ) -> List[str]:
        """Provides H-4 with vehicle-specific root causes for a DTC."""
        interps = self.store.resolve_dtc_interpretation(
            dtc_code=dtc_code,
            target_ecu=target_ecu,
            identity=identity,
        )
        if interps:
            # Return causes from the most specific interpretation
            return list(interps[0][0].likely_root_causes)
        return []

    def get_contextual_verification_tests(
        self,
        dtc_code: str,
        target_ecu: str = "ECM",
        identity: Optional[ProgressiveVehicleIdentity] = None,
    ) -> List[KnowledgeDistinguishingTest]:
        """Provides H-3 with vehicle-specific distinguishing tests."""
        interps = self.store.resolve_dtc_interpretation(
            dtc_code=dtc_code,
            target_ecu=target_ecu,
            identity=identity,
        )
        if interps:
            return list(interps[0][0].recommended_tests)
        return []


class DiagnosticGraphContextIntegrator:
    """
    Binds Vehicle and ECU progressive profiles to G-5 DiagnosticGraph nodes.
    Strictly preserves the invariant: RELATIONSHIP != CAUSALITY.
    """

    @staticmethod
    def integrate_vehicle_identity(
        graph: DiagnosticGraph,
        identity: ProgressiveVehicleIdentity,
    ) -> str:
        """Adds structured vehicle and ECU nodes to graph without creating fake causal links."""
        veh_id = identity.vin if (identity.vin and len(identity.vin) >= 11) else f"vehicle:{identity.manufacturer}_{identity.model}"
        veh_node = GraphNode(
            node_id=veh_id,
            node_type=GraphNodeType.VEHICLE,
            label=f"{identity.manufacturer} {identity.model} ({identity.model_year or 'N/A'})",
            properties={
                "manufacturer": identity.manufacturer,
                "model": identity.model,
                "model_year": identity.model_year,
                "engine_code": identity.engine.engine_code if identity.engine else None,
                "is_instance_specific": identity.is_instance_specific,
            },
            provenance={"source": "PROGRESSIVE_VEHICLE_IDENTITY"},
        )
        graph.add_node(veh_node)

        # Add target ECU nodes
        for ecu_id, ecu_prof in identity.ecus.items():
            ecu_node_id = make_ecu_node_id(ecu_id)
            ecu_node = GraphNode(
                node_id=ecu_node_id,
                node_type=GraphNodeType.ECU,
                label=f"{ecu_prof.logical_id} ({ecu_prof.module_family or 'Generic'})",
                properties=ecu_prof.to_dict(),
                provenance={"source": "ECU_KNOWLEDGE_PROFILE"},
            )
            graph.add_node(ecu_node)

            # Link vehicle to ECU
            graph.add_edge(GraphEdge(
                edge_id=f"edge_has_ecu_{veh_id}_{ecu_id}",
                source_id=veh_id,
                target_id=ecu_node_id,
                edge_type=GraphEdgeType.HAS_ECU,
                confidence=1.0,
                provenance={"source": "VEHICLE_ECU_KNOWLEDGE"},
            ))

        return veh_id
