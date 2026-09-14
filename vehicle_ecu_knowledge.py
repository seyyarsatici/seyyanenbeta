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
import struct
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
    DataType,
    ByteOrder,
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


class VehicleVerificationState(str, enum.Enum):
    """Progressive vehicle identification verification state."""
    UNKNOWN = "UNKNOWN"                          # No identifying information established
    PARTIAL = "PARTIAL"                          # Passive CAN headers or partial fragments observed
    IDENTIFIED = "IDENTIFIED"                    # Model selected by technician or VIN positively decoded
    VERIFIED = "VERIFIED"                        # Hardware/calibration positively verified against physical ECU


class ResolutionStatus(str, enum.Enum):
    """Outcome of diagnostic identifier knowledge resolution."""
    RESOLVED_EXACT_INSTANCE = "RESOLVED_EXACT_INSTANCE"  # Tier 1: Verified instance-specific definition
    RESOLVED_VEHICLE_ECU = "RESOLVED_VEHICLE_ECU"        # Tier 2: Exact vehicle-model + ECU calibration definition
    RESOLVED_VEHICLE_FAMILY = "RESOLVED_VEHICLE_FAMILY"  # Tier 3: Vehicle make/model + ECU family definition
    RESOLVED_GENERIC_STANDARD = "RESOLVED_GENERIC_STANDARD" # Tier 4: Generic protocol standard (SAE J1979)
    KNOWLEDGE_CONFLICT = "KNOWLEDGE_CONFLICT"            # Conflicting definitions at equal specificity
    UNKNOWN_IDENTIFIER = "UNKNOWN_IDENTIFIER"            # Tier 5: No matching definition found


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
# 3b. VEHICLE MODEL & INSTANCE CONTEXT FOUNDATION (PHASE L-1)
# =====================================================================

@dataclass
class VehicleModelDefinition:
    """
    Catalog definition of a vehicle model / platform.
    Represents make, model, generation, platform, and standard factory equipment.
    Does NOT represent an individual physical car (VehicleInstanceContext).
    """
    model_id: str                                # e.g. "VW_GOLF_V_16_FSI", "GM_AVEO_T250_14"
    make: str                                    # e.g. "Volkswagen", "Chevrolet"
    model: str                                   # e.g. "Golf", "Aveo"
    generation: Optional[str] = None             # e.g. "V", "T250"
    platform: Optional[str] = None               # e.g. "PQ35", "T200"
    model_years: List[int] = field(default_factory=list)
    market_region: Optional[str] = None          # e.g. "EUROPE", "GLOBAL"
    engine_code: Optional[str] = None            # e.g. "BAG", "F14D3"
    engine: Optional[EngineKnowledgeProfile] = None
    transmission: Optional[TransmissionKnowledgeProfile] = None
    expected_ecus: Dict[str, ECUKnowledgeProfile] = field(default_factory=dict)
    provenance: KnowledgeProvenance = field(default_factory=lambda: KnowledgeProvenance(
        source_type=KnowledgeProvenanceType.OEM_MANUAL,
        source_reference="OEM Vehicle Catalog Specification",
    ))
    schema_version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "make": self.make,
            "model": self.model,
            "generation": self.generation,
            "platform": self.platform,
            "model_years": list(self.model_years),
            "market_region": self.market_region,
            "engine_code": self.engine_code,
            "engine": self.engine.to_dict() if self.engine else None,
            "transmission": self.transmission.to_dict() if self.transmission else None,
            "expected_ecus": {k: v.to_dict() for k, v in self.expected_ecus.items()},
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else {},
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VehicleModelDefinition":
        eng_data = data.get("engine")
        trans_data = data.get("transmission")
        ecus_dict = {}
        for k, v in data.get("expected_ecus", {}).items():
            ecus_dict[k] = ECUKnowledgeProfile.from_dict(v)
        prov_data = data.get("provenance", {})
        raw_ver = data.get("schema_version", 1)
        schema_ver = int(raw_ver) if str(raw_ver).isdigit() else 1

        return cls(
            model_id=data["model_id"],
            make=data.get("make", ""),
            model=data.get("model", ""),
            generation=data.get("generation"),
            platform=data.get("platform"),
            model_years=list(data.get("model_years", [])),
            market_region=data.get("market_region"),
            engine_code=data.get("engine_code"),
            engine=EngineKnowledgeProfile.from_dict(eng_data) if eng_data else None,
            transmission=TransmissionKnowledgeProfile.from_dict(trans_data) if trans_data else None,
            expected_ecus=ecus_dict,
            provenance=KnowledgeProvenance.from_dict(prov_data) if prov_data else KnowledgeProvenance(source_type=KnowledgeProvenanceType.OEM_MANUAL),
            schema_version=schema_ver,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class VehicleInstanceContext:
    """
    Authoritative representation of a specific, physical vehicle connected to Seyyanen.
    Carries VIN, observed physical ECUs, calibration readings, and session history.
    Strictly isolated from generic vehicle catalog models (VehicleModelDefinition).
    """
    instance_id: str                             # Unique instance UUID/identifier
    vin: Optional[str] = None                    # 17-character VIN where available
    model_definition_id: Optional[str] = None    # Reference to catalog VehicleModelDefinition if matched
    verification_state: VehicleVerificationState = VehicleVerificationState.UNKNOWN
    observed_ecus: Dict[str, ECUKnowledgeProfile] = field(default_factory=dict)
    technician_confirmations: Dict[str, Any] = field(default_factory=dict)
    associated_sessions: List[str] = field(default_factory=list)
    identity_sources: Dict[str, IdentitySource] = field(default_factory=dict)
    confidence_levels: Dict[str, IdentityConfidenceLevel] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    schema_version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_evidence(
        self,
        evidence_type: str,
        value: Any,
        source: IdentitySource,
        confidence: IdentityConfidenceLevel,
    ) -> VehicleVerificationState:
        """
        Incorporates identification evidence and deterministically advances verification state.
        Never fabricates complete identity from partial or unverified observations.
        """
        self.metadata[evidence_type] = value
        self.identity_sources[evidence_type] = source
        self.confidence_levels[evidence_type] = confidence
        self.updated_at = time.time()

        if evidence_type == "vin" and value:
            self.vin = str(value).strip().upper()

        if evidence_type == "model_definition_id" and value:
            self.model_definition_id = str(value).strip()

        # Deterministic state progression
        has_vin = bool(self.vin and len(self.vin) >= 11)
        has_model = bool(self.model_definition_id)
        is_tech_confirmed = any(
            c == IdentityConfidenceLevel.CONFIRMED or s == IdentitySource.MANUAL_USER_INPUT
            for c, s in zip(self.confidence_levels.values(), self.identity_sources.values())
        )
        has_ecu_verified = any(
            c == IdentityConfidenceLevel.CONFIRMED for c in self.confidence_levels.values()
        )

        if (has_vin and has_ecu_verified) or is_tech_confirmed:
            self.verification_state = VehicleVerificationState.VERIFIED
        elif has_vin or has_model:
            self.verification_state = VehicleVerificationState.IDENTIFIED
        elif self.metadata:
            self.verification_state = VehicleVerificationState.PARTIAL
        else:
            self.verification_state = VehicleVerificationState.UNKNOWN

        return self.verification_state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "vin": self.vin,
            "model_definition_id": self.model_definition_id,
            "verification_state": self.verification_state.value,
            "observed_ecus": {k: v.to_dict() for k, v in self.observed_ecus.items()},
            "technician_confirmations": dict(self.technician_confirmations),
            "associated_sessions": list(self.associated_sessions),
            "identity_sources": {k: v.value for k, v in self.identity_sources.items()},
            "confidence_levels": {k: v.value for k, v in self.confidence_levels.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VehicleInstanceContext":
        ecus_dict = {}
        for k, v in data.get("observed_ecus", {}).items():
            ecus_dict[k] = ECUKnowledgeProfile.from_dict(v)
        raw_ver = data.get("schema_version", 1)
        schema_ver = int(raw_ver) if str(raw_ver).isdigit() else 1

        return cls(
            instance_id=data["instance_id"],
            vin=data.get("vin"),
            model_definition_id=data.get("model_definition_id"),
            verification_state=VehicleVerificationState(data.get("verification_state", "UNKNOWN")),
            observed_ecus=ecus_dict,
            technician_confirmations=dict(data.get("technician_confirmations", {})),
            associated_sessions=list(data.get("associated_sessions", [])),
            identity_sources={k: IdentitySource(v) for k, v in data.get("identity_sources", {}).items()},
            confidence_levels={k: IdentityConfidenceLevel(v) for k, v in data.get("confidence_levels", {}).items()},
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            schema_version=schema_ver,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class DiagnosticIdentifierKnowledge:
    """
    Authoritative knowledge definition for a diagnostic parameter, DID, PID, or signal.
    Captures exact physical scaling, unit, data type, bit layout, and context applicability.
    Guarantees single-pass deterministic decoding without double-scaling.
    """
    identifier: str                              # e.g. "010C", "010D", "221155"
    service_id: str = "01"                       # e.g. "01", "22", "21"
    name: str = ""                               # e.g. "Engine Speed", "Engine Coolant Temperature"
    description: str = ""
    data_type: DataType = DataType.UINT16
    unit: str = ""
    scaling: float = 1.0
    offset: float = 0.0
    byte_order: ByteOrder = ByteOrder.BIG_ENDIAN
    bit_length: Optional[int] = None
    bit_mask: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    target_ecu: str = "GENERIC"                  # Scope: "GENERIC", "ECM", "TCM", "ABS", etc.
    applicability: VehicleApplicability = field(default_factory=VehicleApplicability)
    provenance: KnowledgeProvenance = field(default_factory=lambda: KnowledgeProvenance(
        source_type=KnowledgeProvenanceType.VALIDATED_PROCEDURE,
        source_reference="SAE J1979",
    ))
    trust_level: DefinitionTrustLevel = DefinitionTrustLevel.STANDARD
    schema_version: int = 1
    instance_id: Optional[str] = None            # Set only if definition is bound to a specific vehicle instance!
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_key(self) -> str:
        """Returns ECU-aware canonical key e.g. 'ECM:010C'."""
        return f"{self.target_ecu.upper()}:{self.identifier.upper()}"

    def decode_physical_value(self, raw_bytes: Union[bytes, bytearray, List[int]]) -> Optional[float]:
        """
        Deterministically decodes raw payload bytes into physical engineering value
        applying byte order, sign, scaling, and offset in a single pass.
        Never applies scaling twice. Returns None if bytes are invalid or insufficient.
        """
        if raw_bytes is None:
            return None
        if isinstance(raw_bytes, (list, bytearray)):
            raw_bytes = bytes(raw_bytes)
        if not isinstance(raw_bytes, bytes) or len(raw_bytes) == 0:
            return None

        fmt_prefix = ">" if self.byte_order == ByteOrder.BIG_ENDIAN else "<"
        unscaled = 0.0

        try:
            if self.data_type == DataType.UINT8:
                if len(raw_bytes) < 1:
                    return None
                unscaled = float(raw_bytes[0])
            elif self.data_type == DataType.INT8:
                if len(raw_bytes) < 1:
                    return None
                unscaled = float(struct.unpack(">b", raw_bytes[:1])[0])
            elif self.data_type == DataType.UINT16:
                if len(raw_bytes) < 2:
                    return None
                unscaled = float(struct.unpack(f"{fmt_prefix}H", raw_bytes[:2])[0])
            elif self.data_type == DataType.INT16:
                if len(raw_bytes) < 2:
                    return None
                unscaled = float(struct.unpack(f"{fmt_prefix}h", raw_bytes[:2])[0])
            elif self.data_type == DataType.UINT24:
                if len(raw_bytes) < 3:
                    return None
                if self.byte_order == ByteOrder.BIG_ENDIAN:
                    raw_int = (raw_bytes[0] << 16) | (raw_bytes[1] << 8) | raw_bytes[2]
                else:
                    raw_int = raw_bytes[0] | (raw_bytes[1] << 8) | (raw_bytes[2] << 16)
                unscaled = float(raw_int)
            elif self.data_type == DataType.UINT32:
                if len(raw_bytes) < 4:
                    return None
                unscaled = float(struct.unpack(f"{fmt_prefix}I", raw_bytes[:4])[0])
            elif self.data_type == DataType.INT32:
                if len(raw_bytes) < 4:
                    return None
                unscaled = float(struct.unpack(f"{fmt_prefix}i", raw_bytes[:4])[0])
            elif self.data_type == DataType.FLOAT32:
                if len(raw_bytes) < 4:
                    return None
                unscaled = float(struct.unpack(f"{fmt_prefix}f", raw_bytes[:4])[0])
            elif self.data_type == DataType.BOOLEAN:
                if len(raw_bytes) < 1:
                    return None
                unscaled = 1.0 if raw_bytes[0] != 0 else 0.0
            elif self.data_type in (DataType.BITFIELD, DataType.ENUMERATION):
                if len(raw_bytes) < 1:
                    return None
                unscaled = float(raw_bytes[0])
            else:
                unscaled = float(raw_bytes[0])

            # Apply bitmask if defined
            if self.bit_mask is not None:
                unscaled = float(int(unscaled) & int(self.bit_mask))

            # Single-pass deterministic scaling
            physical_value = unscaled * self.scaling + self.offset
            return physical_value
        except Exception as e:
            logger.debug(f"Exception during physical value decoding for {self.identifier}: {e}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "service_id": self.service_id,
            "name": self.name,
            "description": self.description,
            "data_type": self.data_type.value,
            "unit": self.unit,
            "scaling": self.scaling,
            "offset": self.offset,
            "byte_order": self.byte_order.value,
            "bit_length": self.bit_length,
            "bit_mask": self.bit_mask,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "target_ecu": self.target_ecu,
            "applicability": {
                "manufacturers": self.applicability.manufacturers,
                "models": self.applicability.models,
                "model_years": self.applicability.model_years,
                "engine_codes": self.applicability.engine_codes,
                "transmission_types": self.applicability.transmission_types,
                "ecu_families": self.applicability.ecu_families,
                "software_versions": self.applicability.software_versions,
            },
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else {},
            "trust_level": self.trust_level.value,
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticIdentifierKnowledge":
        app_data = data.get("applicability", {})
        prov_data = data.get("provenance", {})
        return cls(
            identifier=data["identifier"],
            service_id=data.get("service_id", "01"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            data_type=DataType(data.get("data_type", "UINT16")),
            unit=data.get("unit", ""),
            scaling=float(data.get("scaling", 1.0)),
            offset=float(data.get("offset", 0.0)),
            byte_order=ByteOrder(data.get("byte_order", "BIG_ENDIAN")),
            bit_length=data.get("bit_length"),
            bit_mask=data.get("bit_mask"),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            target_ecu=data.get("target_ecu", "GENERIC"),
            applicability=VehicleApplicability(
                manufacturers=app_data.get("manufacturers"),
                models=app_data.get("models"),
                model_years=app_data.get("model_years"),
                engine_codes=app_data.get("engine_codes"),
                transmission_types=app_data.get("transmission_types"),
                ecu_families=app_data.get("ecu_families"),
                software_versions=app_data.get("software_versions"),
            ),
            provenance=KnowledgeProvenance.from_dict(prov_data) if prov_data else KnowledgeProvenance(source_type=KnowledgeProvenanceType.VALIDATED_PROCEDURE),
            trust_level=DefinitionTrustLevel(data.get("trust_level", "STANDARD")),
            schema_version=int(data.get("schema_version", 1)) if str(data.get("schema_version", "1")).isdigit() else 1,
            instance_id=data.get("instance_id"),
            metadata=dict(data.get("metadata", {})),
        )


# Backward-compatible alias
DiagnosticIdentifierDefinition = DiagnosticIdentifierKnowledge


@dataclass
class KnowledgeConflictRecord:
    """
    Explicit record of contradictory knowledge definitions from multiple sources.
    Retains all conflicting definitions with full provenance without arbitrarily picking a winner.
    """
    conflict_id: str
    identifier: str
    target_ecu: str
    definitions: List[DiagnosticIdentifierKnowledge]
    conflicting_fields: List[str]
    detected_at: float = field(default_factory=time.time)
    status: str = "KNOWLEDGE_CONFLICT"
    resolution_notes: str = "Conflict explicitly preserved; no arbitrary winner chosen."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "identifier": self.identifier,
            "target_ecu": self.target_ecu,
            "definitions": [d.to_dict() for d in self.definitions],
            "conflicting_fields": list(self.conflicting_fields),
            "detected_at": self.detected_at,
            "status": self.status,
            "resolution_notes": self.resolution_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeConflictRecord":
        return cls(
            conflict_id=data["conflict_id"],
            identifier=data["identifier"],
            target_ecu=data.get("target_ecu", "GENERIC"),
            definitions=[DiagnosticIdentifierKnowledge.from_dict(d) for d in data.get("definitions", [])],
            conflicting_fields=data.get("conflicting_fields", []),
            detected_at=data.get("detected_at", time.time()),
            status=data.get("status", "KNOWLEDGE_CONFLICT"),
            resolution_notes=data.get("resolution_notes", ""),
        )


@dataclass
class ResolutionResult:
    """Deterministic result of diagnostic identifier knowledge resolution."""
    definition: Optional[DiagnosticIdentifierKnowledge] = None
    status: ResolutionStatus = ResolutionStatus.UNKNOWN_IDENTIFIER
    conflict_record: Optional[KnowledgeConflictRecord] = None
    specificity_score: float = 0.0
    explanation: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.definition is not None and self.status in (
            ResolutionStatus.RESOLVED_EXACT_INSTANCE,
            ResolutionStatus.RESOLVED_VEHICLE_ECU,
            ResolutionStatus.RESOLVED_VEHICLE_FAMILY,
            ResolutionStatus.RESOLVED_GENERIC_STANDARD,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "definition": self.definition.to_dict() if self.definition else None,
            "conflict_record": self.conflict_record.to_dict() if self.conflict_record else None,
            "specificity_score": round(self.specificity_score, 2),
            "explanation": self.explanation,
        }


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
        # Vehicle Models & Instances (Phase L-1)
        self._vehicle_models: Dict[str, VehicleModelDefinition] = {}
        self._vehicle_instances: Dict[str, VehicleInstanceContext] = {}
        # Diagnostic Identifier Knowledge (Phase L-1)
        self._identifier_definitions: List[DiagnosticIdentifierKnowledge] = []
        self._identifier_index: Dict[str, List[DiagnosticIdentifierKnowledge]] = collections.defaultdict(list)
        self._conflicts: List[KnowledgeConflictRecord] = []

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
    # A2. Vehicle Model, Instance & Identifier Knowledge Registration (Phase L-1)
    # -----------------------------------------------------------------

    def register_vehicle_model(self, model: VehicleModelDefinition) -> None:
        """Registers a catalog vehicle model definition."""
        self._vehicle_models[model.model_id.strip().upper()] = model

    def get_vehicle_model(self, model_id: str) -> Optional[VehicleModelDefinition]:
        """Retrieves a catalog vehicle model definition by model_id."""
        return self._vehicle_models.get(model_id.strip().upper())

    def list_vehicle_models(self) -> List[VehicleModelDefinition]:
        """Returns all registered vehicle model definitions."""
        return list(self._vehicle_models.values())

    def register_vehicle_instance(self, instance: VehicleInstanceContext) -> None:
        """Registers a physical vehicle instance context."""
        self._vehicle_instances[instance.instance_id.strip()] = instance

    def get_vehicle_instance(self, instance_id: str) -> Optional[VehicleInstanceContext]:
        """Retrieves a physical vehicle instance by instance_id."""
        return self._vehicle_instances.get(instance_id.strip())

    def list_vehicle_instances(self) -> List[VehicleInstanceContext]:
        """Returns all registered vehicle instances."""
        return list(self._vehicle_instances.values())

    def register_identifier_definition(self, definition: DiagnosticIdentifierKnowledge) -> None:
        """Registers a diagnostic identifier knowledge definition."""
        self._identifier_definitions.append(definition)
        self._identifier_index[definition.identifier.strip().upper()].append(definition)

    def get_identifier_definitions(
        self,
        identifier: str,
        target_ecu: Optional[str] = None,
    ) -> List[DiagnosticIdentifierKnowledge]:
        """Returns all definitions matching identifier, optionally filtered by target_ecu."""
        ident = identifier.strip().upper()
        candidates = self._identifier_index.get(ident, [])
        if target_ecu:
            ecu = target_ecu.strip().upper()
            return [c for c in candidates if c.target_ecu.upper() in ("GENERIC", ecu)]
        return list(candidates)

    def get_conflicts(self) -> List[KnowledgeConflictRecord]:
        """Returns all recorded knowledge conflict records."""
        return list(self._conflicts)

    def get_operating_reference_engine(self) -> Any:
        """Returns or lazily creates the Phase L-2 DynamicOperatingReferenceEngine."""
        if not hasattr(self, "_operating_reference_engine") or self._operating_reference_engine is None:
            from dynamic_operating_reference import DynamicOperatingReferenceEngine
            self._operating_reference_engine = DynamicOperatingReferenceEngine(knowledge_store=self)
        return self._operating_reference_engine

    def resolve_identifier(
        self,
        identifier: str,
        target_ecu: str = "GENERIC",
        vehicle_instance: Optional[VehicleInstanceContext] = None,
        vehicle_context: Optional[VehicleContext] = None,
        service_id: Optional[str] = None,
    ) -> ResolutionResult:
        """
        Deterministically resolves the most specific applicable DiagnosticIdentifierKnowledge
        following the authoritative 5-tier precedence hierarchy:
          Tier 1: Exact vehicle-instance definition (bound to vehicle_instance.instance_id)
          Tier 2: Exact vehicle-model + specific ECU calibration/software
          Tier 3: Vehicle make/model + ECU-family definition
          Tier 4: Generic protocol/standard definition (SAE J1979 / universal)
          Tier 5: Unknown definition
        
        If multiple definitions conflict at the highest applicable tier, explicitly returns
        ResolutionStatus.KNOWLEDGE_CONFLICT with a KnowledgeConflictRecord, preserving all
        conflicting definitions and provenance without arbitrarily fabricating a winner.
        """
        clean_ident = identifier.strip().upper()
        clean_ecu = target_ecu.strip().upper() if target_ecu else "GENERIC"
        clean_srv = service_id.strip() if service_id else None

        # Build effective vehicle context if instance is provided but context is not
        effective_ctx = vehicle_context
        if effective_ctx is None and vehicle_instance is not None and vehicle_instance.model_definition_id:
            model_def = self.get_vehicle_model(vehicle_instance.model_definition_id)
            if model_def:
                effective_ctx = VehicleContext(
                    manufacturer=model_def.make,
                    model=model_def.model,
                    model_year=model_def.model_years[0] if model_def.model_years else None,
                    engine_code=model_def.engine_code,
                    vin=vehicle_instance.vin,
                )

        all_candidates = self._identifier_index.get(clean_ident, [])
        if clean_srv:
            all_candidates = [c for c in all_candidates if c.service_id == clean_srv]

        tier_1: List[DiagnosticIdentifierKnowledge] = []
        tier_2: List[DiagnosticIdentifierKnowledge] = []
        tier_3: List[DiagnosticIdentifierKnowledge] = []
        tier_4: List[DiagnosticIdentifierKnowledge] = []

        for cand in all_candidates:
            # ECU scope check: candidate must match target_ecu or be GENERIC
            cand_ecu = cand.target_ecu.strip().upper()
            if cand_ecu != "GENERIC" and cand_ecu != clean_ecu:
                continue

            # Tier 1: Instance-specific definition
            if cand.instance_id is not None:
                if (
                    vehicle_instance is not None
                    and cand.instance_id == vehicle_instance.instance_id
                ):
                    tier_1.append(cand)
                # Instance-bound definition never leaks to other instances or generic tiers
                continue

            # Evaluate applicability against vehicle context
            app_res = cand.applicability.evaluate(effective_ctx)
            if app_res == ApplicabilityResult.NOT_APPLICABLE:
                continue

            # Check Tier 2 vs Tier 3 vs Tier 4:
            # Tier 2 requires ECU software/calibration match or specific engine code match
            is_tier_2 = False
            if effective_ctx:
                if cand.applicability.software_versions and effective_ctx.software_id:
                    if effective_ctx.software_id.upper() in [s.upper() for s in cand.applicability.software_versions]:
                        is_tier_2 = True
                if cand.applicability.engine_codes and effective_ctx.engine_code:
                    if effective_ctx.engine_code.upper() in [e.upper() for e in cand.applicability.engine_codes]:
                        is_tier_2 = True
                if cand.applicability.ecu_families and effective_ctx.ecu_family:
                    if effective_ctx.ecu_family.upper() in [f.upper() for f in cand.applicability.ecu_families]:
                        is_tier_2 = True

            if is_tier_2:
                tier_2.append(cand)
            elif (
                cand.applicability.software_versions
                or cand.applicability.engine_codes
                or cand.applicability.ecu_families
            ):
                # Candidate requires specific software/engine/ECU attributes not matched by context;
                # cannot match as general make/model definition
                pass
            elif not cand.applicability._is_universal():
                # Specific vehicle/model/manufacturer applicability (Tier 3)
                if app_res in (ApplicabilityResult.CONFIRMED_APPLICABLE, ApplicabilityResult.LIKELY_APPLICABLE):
                    tier_3.append(cand)
            else:
                # Universal / Generic (Tier 4)
                tier_4.append(cand)

        # In Tier 3, prefer CONFIRMED_APPLICABLE over LIKELY_APPLICABLE
        if tier_3:
            confirmed_3 = [
                c for c in tier_3
                if c.applicability.evaluate(effective_ctx) == ApplicabilityResult.CONFIRMED_APPLICABLE
            ]
            if confirmed_3:
                tier_3 = confirmed_3

        # In Tier 4, if there are exact target_ecu matches and GENERIC fallbacks, prefer exact target_ecu
        if tier_4:
            exact_ecu_cands = [c for c in tier_4 if c.target_ecu.strip().upper() == clean_ecu]
            if exact_ecu_cands:
                tier_4 = exact_ecu_cands

        # Select highest applicable tier
        tier_candidates: List[DiagnosticIdentifierKnowledge] = []
        status: ResolutionStatus = ResolutionStatus.UNKNOWN_IDENTIFIER
        base_score = 0.0

        if tier_1:
            tier_candidates = tier_1
            status = ResolutionStatus.RESOLVED_EXACT_INSTANCE
            base_score = 100.0
        elif tier_2:
            tier_candidates = tier_2
            status = ResolutionStatus.RESOLVED_VEHICLE_ECU
            base_score = 50.0
        elif tier_3:
            tier_candidates = tier_3
            status = ResolutionStatus.RESOLVED_VEHICLE_FAMILY
            base_score = 25.0
        elif tier_4:
            tier_candidates = tier_4
            status = ResolutionStatus.RESOLVED_GENERIC_STANDARD
            base_score = 10.0
        else:
            return ResolutionResult(
                definition=None,
                status=ResolutionStatus.UNKNOWN_IDENTIFIER,
                specificity_score=0.0,
                explanation=f"Identifier {clean_ident} on ECU {clean_ecu} is not defined in knowledge base",
            )

        # Check for conflicts within the winning tier
        if len(tier_candidates) == 1:
            winner = tier_candidates[0]
            return ResolutionResult(
                definition=winner,
                status=status,
                specificity_score=base_score,
                explanation=f"Resolved via {status.value} (target_ecu={winner.target_ecu})",
            )

        # Multiple candidates in winning tier: verify semantic harmony
        c0 = tier_candidates[0]
        conflicts: List[str] = []
        for ci in tier_candidates[1:]:
            if abs(ci.scaling - c0.scaling) > 1e-6:
                conflicts.append("scaling")
            if abs(ci.offset - c0.offset) > 1e-6:
                conflicts.append("offset")
            if ci.unit.strip().upper() != c0.unit.strip().upper():
                conflicts.append("unit")
            if ci.data_type != c0.data_type:
                conflicts.append("data_type")
            if ci.name.strip().upper() != c0.name.strip().upper():
                conflicts.append("name")

        if conflicts:
            conflict_rec = KnowledgeConflictRecord(
                conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                identifier=clean_ident,
                target_ecu=clean_ecu,
                definitions=tier_candidates,
                conflicting_fields=sorted(list(set(conflicts))),
                status="KNOWLEDGE_CONFLICT",
            )
            self._conflicts.append(conflict_rec)
            return ResolutionResult(
                definition=None,
                status=ResolutionStatus.KNOWLEDGE_CONFLICT,
                conflict_record=conflict_rec,
                specificity_score=base_score,
                explanation=f"Conflicting definitions in {status.value} tier on fields: {', '.join(sorted(list(set(conflicts))))}",
            )

        # Harmonious candidates in tier: return first deterministic candidate
        return ResolutionResult(
            definition=c0,
            status=status,
            specificity_score=base_score,
            explanation=f"Multiple harmonious definitions resolved in {status.value}",
        )

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
            "vehicle_models": {k: v.to_dict() for k, v in self._vehicle_models.items()},
            "vehicle_instances": {k: v.to_dict() for k, v in self._vehicle_instances.items()},
            "identifier_definitions": [d.to_dict() for d in self._identifier_definitions],
            "conflicts": [c.to_dict() for c in self._conflicts],
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

        for mod_data in data.get("vehicle_models", {}).values():
            store.register_vehicle_model(VehicleModelDefinition.from_dict(mod_data))

        for inst_data in data.get("vehicle_instances", {}).values():
            store.register_vehicle_instance(VehicleInstanceContext.from_dict(inst_data))

        for def_data in data.get("identifier_definitions", []):
            store.register_identifier_definition(DiagnosticIdentifierKnowledge.from_dict(def_data))

        for conf_data in data.get("conflicts", []):
            store._conflicts.append(KnowledgeConflictRecord.from_dict(conf_data))

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
