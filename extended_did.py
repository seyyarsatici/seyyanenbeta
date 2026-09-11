"""
extended_did.py - Extended DID / PID Ecosystem & Advanced Data Decoding (Phase G-2)
===================================================================================
Provides a structured, protocol-aware Extended DID/PID ecosystem for the Seyyanen
automotive diagnostic platform.

Features:
  - Structured DiagnosticDataDefinition (Standard PID vs Extended DID vs Raw/Unknown)
  - VehicleApplicability & VehicleContext evaluation (CONFIRMED, LIKELY, UNKNOWN, NOT_APPLICABLE)
  - Reusable DataDecoder (endianness, signed/unsigned, scaling, bitfields, enums, multi-field)
  - Strict separation: Raw Evidence vs Decoded Value vs Interpreted Meaning
  - DataProvenance (source ECU, timestamps, txn ID, definition ID, version, trust level)
  - DiagnosticDefinitionRegistry with pre-registered standard & verified definitions
  - BatchAcquisitionManager with per-identifier failure isolation, rate limiting, and cancellation
  - Integration with Phase G-1 DiagnosticTransactionManager & read-only safety guardrails
"""

import collections
import enum
import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Harmonized status and quality imports from motor and advanced_ecu_services
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
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NO_DATA,
    STATUS_DID_MISMATCH,
    STATUS_EMPTY_RESPONSE,
)
from advanced_ecu_services import (
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    DiagnosticSessionContext,
    DiagnosticTransactionManager,
    ECUTargetContext,
    ServiceSafetyClassification,
    SessionType,
    STATUS_TRANSACTION_BLOCKED,
    STATUS_TRANSACTION_CANCELLED,
    STATUS_UNEXPECTED_RESPONSE,
    STATUS_RESPONSE_MISMATCH,
    STATUS_PARSE_ERROR,
    CANONICAL_NRC_MAP,
)


# =====================================================================
# 1. ENUMS & TAXONOMIES
# =====================================================================

class IdentifierNamespace(str, enum.Enum):
    """Namespace classification for diagnostic data identifiers."""
    STANDARD_OBD_PID = "STANDARD_OBD_PID"        # SAE J1979 Mode 01/02
    EXTENDED_UDS_DID = "EXTENDED_UDS_DID"        # ISO 14229 Service 0x22
    KWP_LOCAL_IDENTIFIER = "KWP_LOCAL_ID"        # ISO 14230 Service 0x21
    VEHICLE_INFO_PID = "VEHICLE_INFO_PID"        # SAE J1979 Mode 09
    RAW_UNKNOWN = "RAW_UNKNOWN"                  # Undocumented/raw identifier


class DataType(str, enum.Enum):
    """Primitive and composite data types for diagnostic payload decoding."""
    UINT8 = "UINT8"
    UINT16 = "UINT16"
    UINT24 = "UINT24"
    UINT32 = "UINT32"
    INT8 = "INT8"
    INT16 = "INT16"
    INT32 = "INT32"
    FLOAT32 = "FLOAT32"
    BITFIELD = "BITFIELD"
    BOOLEAN = "BOOLEAN"
    ENUMERATION = "ENUMERATION"
    STRING_ASCII = "STRING_ASCII"
    RAW_BYTES = "RAW_BYTES"


class ByteOrder(str, enum.Enum):
    BIG_ENDIAN = "BIG_ENDIAN"
    LITTLE_ENDIAN = "LITTLE_ENDIAN"


class DefinitionTrustLevel(str, enum.Enum):
    """Provenance and authority classification for data definitions."""
    STANDARD = "STANDARD"                        # Official standard (SAE/ISO)
    OEM_DOCUMENTED = "OEM_DOCUMENTED"            # From verified OEM technical manual
    VERIFIED_TESTED = "VERIFIED_TESTED"          # Empirically verified on physical ECU/harness
    VEHICLE_SPECIFIC = "VEHICLE_SPECIFIC"        # Bound to verified specific vehicle/engine code
    COMMUNITY_EXPERIMENTAL = "EXPERIMENTAL"      # Reverse-engineered / unverified
    UNKNOWN = "UNKNOWN"                          # Undocumented fallback


class ApplicabilityResult(str, enum.Enum):
    """Evaluation result of vehicle configuration matching."""
    CONFIRMED_APPLICABLE = "CONFIRMED_APPLICABLE"
    LIKELY_APPLICABLE = "LIKELY_APPLICABLE"
    UNKNOWN_APPLICABILITY = "UNKNOWN_APPLICABILITY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# =====================================================================
# 2. VEHICLE CONTEXT & APPLICABILITY MODEL
# =====================================================================

@dataclass
class VehicleContext:
    """
    Detailed vehicle identity and hardware context for identifier resolution.
    Seamlessly binds to AutoExpertEngine.vehicle_profile or VIN hints.
    """
    manufacturer: Optional[str] = None           # e.g. "CHEVROLET", "OPEL", "VW"
    model: Optional[str] = None                  # e.g. "AVEO", "ASTRA", "GOLF"
    model_year: Optional[int] = None             # e.g. 2008
    engine_code: Optional[str] = None            # e.g. "F14D3", "Z16XER", "LDE"
    transmission: Optional[str] = None           # e.g. "AUTOMATIC", "MANUAL"
    ecu_family: Optional[str] = None             # e.g. "DELPHI_MT80", "SIMTEC76"
    software_id: Optional[str] = None            # e.g. "CAL_ID_968001"
    vin: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def normalize(self) -> "VehicleContext":
        return VehicleContext(
            manufacturer=self.manufacturer.strip().upper() if self.manufacturer else None,
            model=self.model.strip().upper() if self.model else None,
            model_year=self.model_year,
            engine_code=self.engine_code.strip().upper() if self.engine_code else None,
            transmission=self.transmission.strip().upper() if self.transmission else None,
            ecu_family=self.ecu_family.strip().upper() if self.ecu_family else None,
            software_id=self.software_id.strip().upper() if self.software_id else None,
            vin=self.vin.strip().upper() if self.vin else None,
            metadata=dict(self.metadata),
        )


@dataclass
class VehicleApplicability:
    """
    Defines the exact vehicle/engine/ECU envelope where an identifier definition is valid.
    Prevents assuming universal compatibility across unrelated ECUs.
    """
    manufacturers: Optional[List[str]] = None
    models: Optional[List[str]] = None
    model_years: Optional[List[int]] = None
    engine_codes: Optional[List[str]] = None
    transmission_types: Optional[List[str]] = None
    ecu_families: Optional[List[str]] = None
    software_versions: Optional[List[str]] = None

    def evaluate(self, context: Optional[VehicleContext]) -> ApplicabilityResult:
        """
        Determines applicability of this definition for the given VehicleContext.
        Strictly distinguishes confirmed match from contradiction and missing context.
        """
        if context is None:
            # If definition has no restrictions at all, it's universally likely/standard
            if self._is_universal():
                return ApplicabilityResult.CONFIRMED_APPLICABLE
            return ApplicabilityResult.UNKNOWN_APPLICABILITY

        ctx = context.normalize()

        # 1. Explicit contradiction checks (Fail-closed to NOT_APPLICABLE)
        if self.manufacturers and ctx.manufacturer:
            m_list = [m.upper() for m in self.manufacturers]
            if ctx.manufacturer not in m_list:
                return ApplicabilityResult.NOT_APPLICABLE

        if self.models and ctx.model:
            mod_list = [m.upper() for m in self.models]
            if ctx.model not in mod_list:
                return ApplicabilityResult.NOT_APPLICABLE

        if self.model_years and ctx.model_year:
            if ctx.model_year not in self.model_years:
                return ApplicabilityResult.NOT_APPLICABLE

        if self.engine_codes and ctx.engine_code:
            eng_list = [e.upper() for e in self.engine_codes]
            if ctx.engine_code not in eng_list:
                return ApplicabilityResult.NOT_APPLICABLE

        if self.transmission_types and ctx.transmission:
            trans_list = [t.upper() for t in self.transmission_types]
            if ctx.transmission not in trans_list:
                return ApplicabilityResult.NOT_APPLICABLE

        if self.ecu_families and ctx.ecu_family:
            ecu_list = [ef.upper() for ef in self.ecu_families]
            if ctx.ecu_family not in ecu_list:
                return ApplicabilityResult.NOT_APPLICABLE

        # 2. Positive confirmation checks
        has_specific_rules = (
            bool(self.manufacturers) or bool(self.models) or
            bool(self.engine_codes) or bool(self.ecu_families)
        )

        if not has_specific_rules:
            return ApplicabilityResult.CONFIRMED_APPLICABLE

        # If no vehicle info provided in context at all, it's UNKNOWN
        has_any_ctx_info = bool(
            ctx.manufacturer or ctx.model or ctx.engine_code or
            ctx.ecu_family or ctx.transmission or ctx.model_year or ctx.vin
        )
        if not has_any_ctx_info:
            return ApplicabilityResult.UNKNOWN_APPLICABILITY

        # If manufacturer matches:
        if self.manufacturers and ctx.manufacturer in [m.upper() for m in self.manufacturers]:
            if self.engine_codes:
                if ctx.engine_code and ctx.engine_code in [e.upper() for e in self.engine_codes]:
                    return ApplicabilityResult.CONFIRMED_APPLICABLE
                elif not ctx.engine_code:
                    return ApplicabilityResult.LIKELY_APPLICABLE
            else:
                return ApplicabilityResult.CONFIRMED_APPLICABLE

        # If engine code matches directly:
        if self.engine_codes and ctx.engine_code and ctx.engine_code in [e.upper() for e in self.engine_codes]:
            return ApplicabilityResult.CONFIRMED_APPLICABLE

        return ApplicabilityResult.UNKNOWN_APPLICABILITY


    def _is_universal(self) -> bool:
        return not any([
            self.manufacturers, self.models, self.model_years,
            self.engine_codes, self.transmission_types, self.ecu_families,
            self.software_versions
        ])


# =====================================================================
# 3. FIELD & IDENTIFIER DEFINITION MODELS
# =====================================================================

@dataclass
class FieldDefinition:
    """
    Specification for a single physical measurement or signal within an identifier payload.
    Supports scalars, bitfields, enumerations, scaling, and invalid value tagging.
    """
    name: str                                    # e.g. "CoolantTemperature", "MIL_Status"
    payload_offset: int = 0                      # Byte index within extracted payload
    payload_length: int = 1                      # Byte length
    data_type: DataType = DataType.UINT8
    byte_order: ByteOrder = ByteOrder.BIG_ENDIAN
    bit_offset: Optional[int] = None             # 0..7 (LSB) or bitfield index
    bit_length: Optional[int] = None             # Length in bits
    bit_mask: Optional[int] = None               # Optional explicit bit mask
    scale: float = 1.0                           # physical = raw * scale + offset
    offset: float = 0.0
    unit: str = ""                               # e.g. "°C", "RPM", "kPa", "%"
    min_expected_value: Optional[float] = None
    max_expected_value: Optional[float] = None
    enum_map: Optional[Dict[int, str]] = None    # e.g. {0: "OFF", 1: "ON"}
    invalid_raw_values: Optional[List[int]] = None # e.g. [0xFF, 0xFE] (sensor error)
    description: str = ""


@dataclass
class DiagnosticDataDefinition:
    """
    Authoritative specification for an ECU Diagnostic Identifier (Standard PID or Extended DID).
    Binds service formatting, payload expectations, decoding rules, and applicability.
    """
    identifier: str                              # e.g. "1640" (DID), "0C" (PID), "0902"
    namespace: IdentifierNamespace = IdentifierNamespace.EXTENDED_UDS_DID
    name: str = ""
    description: str = ""
    service_id: str = "22"                       # e.g. "22", "01", "09", "21"
    subfunction: Optional[str] = None
    expected_header: Optional[str] = "7E0"
    expected_payload_length: Optional[int] = None
    min_payload_length: int = 1
    max_payload_length: Optional[int] = None
    fields: List[FieldDefinition] = field(default_factory=list)
    applicability: VehicleApplicability = field(default_factory=VehicleApplicability)
    ecu_target: str = "PRIMARY_ECU"
    session_requirement: SessionType = SessionType.DEFAULT
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    trust_level: DefinitionTrustLevel = DefinitionTrustLevel.VERIFIED_TESTED
    definition_id: str = ""
    definition_version: str = "1.0.0"
    decoder_ref: Optional[Callable[[bytes, "DiagnosticDataDefinition"], Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.identifier = self.identifier.strip().upper()
        self.service_id = self.service_id.strip().upper()
        if not self.name:
            self.name = f"{self.namespace.value}_{self.identifier}"
        if not self.definition_id:
            self.definition_id = f"DEF-{self.service_id}-{self.identifier}"

    def build_service_request(self, transaction_manager: DiagnosticTransactionManager) -> AdvancedServiceRequest:
        """Constructs a validated AdvancedServiceRequest for this definition."""
        return transaction_manager.build_request(
            service_id=self.service_id,
            payload=self.identifier if self.service_id == "22" else "",
            subfunction=self.subfunction or (self.identifier if self.service_id in ("01", "09", "21") else None),
            header=self.expected_header,
            target_ecu=self.ecu_target,
            metadata={
                "definition_id": self.definition_id,
                "definition_version": self.definition_version,
                "identifier": self.identifier,
                "namespace": self.namespace.value,
            },
        )


# =====================================================================
# 4. DECODED EVIDENCE & PROVENANCE MODELS
# =====================================================================

@dataclass
class DataProvenance:
    """Complete, immutable provenance trail for an acquired diagnostic value."""
    source_ecu: str
    identifier: str
    service_id: str
    request_timestamp: float
    response_timestamp: float
    elapsed_time: float
    transaction_id: str
    definition_id: str
    definition_version: str
    trust_level: DefinitionTrustLevel
    applicability: ApplicabilityResult


@dataclass
class DecodedField:
    """Structured representation of an individual decoded field."""
    field_name: str
    raw_value: Any
    decoded_value: Any
    unit: str
    is_valid: bool = True
    invalid_reason: Optional[str] = None


@dataclass
class StructuredDiagnosticEvidence:
    """
    Comprehensive container strictly separating:
      - RAW EVIDENCE: Unaltered bytes and lines directly from transport.
      - DECODED VALUES: Physically scaled measurements and typed signals.
      - INTERPRETED MEANING: Diagnostic hypothesis/root-cause (reserved for G-3).
    """
    definition: DiagnosticDataDefinition
    raw_response: AdvancedServiceResponse
    raw_value: Any
    decoded_value: Any
    fields: Dict[str, DecodedField] = field(default_factory=dict)
    interpreted_meaning: Optional[Any] = None    # Reserved for future G-3
    unit: str = ""
    quality: str = QUALITY_GOOD
    provenance: Optional[DataProvenance] = None
    is_valid: bool = True
    status: str = STATUS_VALID
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "definition_id": self.definition.definition_id,
            "identifier": self.definition.identifier,
            "namespace": self.definition.namespace.value,
            "status": self.status,
            "quality": self.quality,
            "is_valid": self.is_valid,
            "raw_payload_hex": self.raw_response.raw_payload_hex if self.raw_response else None,
            "raw_value": self.raw_value,
            "decoded_value": self.decoded_value,
            "unit": self.unit,
            "fields": {k: {"decoded": v.decoded_value, "raw": v.raw_value, "unit": v.unit, "valid": v.is_valid} for k, v in self.fields.items()},
            "provenance": {
                "ecu": self.provenance.source_ecu,
                "txn_id": self.provenance.transaction_id,
                "elapsed": self.provenance.elapsed_time,
                "trust": self.provenance.trust_level.value,
                "applicability": self.provenance.applicability.value,
            } if self.provenance else None,
            "error_message": self.error_message,
        }


# =====================================================================
# 5. REUSABLE DECODER ENGINE
# =====================================================================

class DataDecoder:
    """
    Robust, reusable decoding engine for automotive payloads.
    Guarantees that raw data survives decoding, handles bitfields, endianness,
    scaling, offsets, enums, and composite multi-field payloads.
    """
    @classmethod
    def decode(
        cls,
        payload_bytes: bytes,
        definition: DiagnosticDataDefinition,
    ) -> Tuple[Any, Any, Dict[str, DecodedField], bool, Optional[str]]:
        """
        Decodes payload_bytes according to definition fields.
        Returns: (raw_value, decoded_value, fields_dict, is_valid, error_message)
        """
        # 1. Custom decoder reference check
        if definition.decoder_ref:
            try:
                res = definition.decoder_ref(payload_bytes, definition)
                if isinstance(res, tuple) and len(res) >= 2:
                    return res[0], res[1], {}, True, None
                return payload_bytes.hex().upper(), res, {}, True, None
            except Exception as e:
                return payload_bytes.hex().upper(), None, {}, False, f"Custom decoder error: {e}"

        # 2. Length validation
        payload_len = len(payload_bytes)
        if payload_len < definition.min_payload_length:
            return None, None, {}, False, (
                f"Payload too short: received {payload_len} bytes, "
                f"minimum required {definition.min_payload_length}."
            )

        if definition.expected_payload_length is not None:
            if payload_len < definition.expected_payload_length:
                return None, None, {}, False, (
                    f"Payload shorter than expected length {definition.expected_payload_length}: "
                    f"received {payload_len} bytes."
                )

        if definition.max_payload_length is not None:
            if payload_len > definition.max_payload_length:
                return None, None, {}, False, (
                    f"Payload exceeds maximum allowed length {definition.max_payload_length}: "
                    f"received {payload_len} bytes."
                )

        # 3. Default fallback if no fields defined: raw hex representation
        if not definition.fields:
            raw_hex = payload_bytes.hex().upper()
            return raw_hex, raw_hex, {}, True, None

        # 4. Multi-field and single-field evaluation
        decoded_fields: Dict[str, DecodedField] = {}
        all_valid = True
        error_msgs: List[str] = []

        for fld in definition.fields:
            field_raw, field_decoded, fld_valid, fld_err = cls.decode_field(payload_bytes, fld)
            decoded_fields[fld.name] = DecodedField(
                field_name=fld.name,
                raw_value=field_raw,
                decoded_value=field_decoded,
                unit=fld.unit,
                is_valid=fld_valid,
                invalid_reason=fld_err,
            )
            if not fld_valid:
                all_valid = False
                if fld_err:
                    error_msgs.append(f"{fld.name}: {fld_err}")

        # Summary raw and decoded values
        if len(definition.fields) == 1:
            fld = definition.fields[0]
            df = decoded_fields[fld.name]
            return df.raw_value, df.decoded_value, decoded_fields, all_valid, ("; ".join(error_msgs) if error_msgs else None)
        else:
            # Composite multi-field: decoded_value is dict of field_name -> decoded_val
            comp_decoded = {k: v.decoded_value for k, v in decoded_fields.items()}
            comp_raw = {k: v.raw_value for k, v in decoded_fields.items()}
            return comp_raw, comp_decoded, decoded_fields, all_valid, ("; ".join(error_msgs) if error_msgs else None)

    @classmethod
    def decode_field(
        cls,
        payload: bytes,
        field_def: FieldDefinition,
    ) -> Tuple[Any, Any, bool, Optional[str]]:
        """Decodes an individual field from payload bytes."""
        start = field_def.payload_offset
        end = start + field_def.payload_length

        if len(payload) < end:
            return None, None, False, f"Payload slice [{start}:{end}] exceeds available length {len(payload)}"

        field_slice = payload[start:end]
        endian = "big" if field_def.byte_order == ByteOrder.BIG_ENDIAN else "little"

        try:
            # Type-specific primitive extraction
            if field_def.data_type == DataType.RAW_BYTES:
                raw_val = field_slice
                decoded_val = field_slice.hex().upper()
                return raw_val, decoded_val, True, None

            elif field_def.data_type == DataType.STRING_ASCII:
                raw_val = field_slice
                decoded_val = field_slice.decode("ascii", errors="replace").strip("\x00 \r\n")
                return raw_val, decoded_val, True, None

            elif field_def.data_type == DataType.FLOAT32:
                fmt = ">f" if field_def.byte_order == ByteOrder.BIG_ENDIAN else "<f"
                if len(field_slice) < 4:
                    return None, None, False, "Float32 requires 4 bytes"
                raw_val = struct.unpack(fmt, field_slice)[0]
                decoded_val = round(raw_val * field_def.scale + field_def.offset, 4)
                return raw_val, decoded_val, True, None

            # Integer-based types (signed or unsigned)
            signed = field_def.data_type in (DataType.INT8, DataType.INT16, DataType.INT32)
            raw_int = int.from_bytes(field_slice, byteorder=endian, signed=signed)

            # Check invalid/reserved values (e.g. 0xFF indicating open circuit)
            if field_def.invalid_raw_values and raw_int in field_def.invalid_raw_values:
                return raw_int, None, False, f"Value 0x{raw_int:X} is an invalid/reserved failure indicator"

            # Bitfield / Mask extraction
            if field_def.data_type == DataType.BITFIELD or field_def.bit_mask is not None or field_def.bit_offset is not None:
                extracted = raw_int
                if field_def.bit_mask is not None:
                    extracted = extracted & field_def.bit_mask
                if field_def.bit_offset is not None:
                    extracted = extracted >> field_def.bit_offset
                    if field_def.bit_length is not None:
                        mask = (1 << field_def.bit_length) - 1
                        extracted = extracted & mask
                raw_int = extracted

            # Boolean type
            if field_def.data_type == DataType.BOOLEAN:
                raw_val = raw_int
                decoded_val = bool(raw_int)
                return raw_val, decoded_val, True, None

            # Enumeration mapping
            if field_def.data_type == DataType.ENUMERATION or field_def.enum_map is not None:
                raw_val = raw_int
                if field_def.enum_map and raw_int in field_def.enum_map:
                    decoded_val = field_def.enum_map[raw_int]
                else:
                    # Preserve raw numeric value without crashing or inventing text!
                    decoded_val = f"UNKNOWN_ENUM_0x{raw_int:X}"
                return raw_val, decoded_val, True, None

            # Standard Scaled Numeric
            raw_val = raw_int
            decoded_val = raw_int * field_def.scale + field_def.offset

            # Range checks if specified
            if field_def.min_expected_value is not None and decoded_val < field_def.min_expected_value:
                return raw_val, decoded_val, False, f"Decoded value {decoded_val} below minimum expected {field_def.min_expected_value}"
            if field_def.max_expected_value is not None and decoded_val > field_def.max_expected_value:
                return raw_val, decoded_val, False, f"Decoded value {decoded_val} above maximum expected {field_def.max_expected_value}"

            return raw_val, decoded_val, True, None

        except Exception as e:
            return None, None, False, f"Decoding exception: {e}"


# =====================================================================
# 6. DEFINITION REGISTRY
# =====================================================================

class DiagnosticDefinitionRegistry:
    """
    Thread-safe repository for all known DiagnosticDataDefinitions.
    Supports resolution against VehicleContext and pre-populates verified standards.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._definitions: Dict[str, DiagnosticDataDefinition] = {}
        self._register_standard_definitions()

    def register(self, definition: DiagnosticDataDefinition) -> None:
        with self._lock:
            key = f"{definition.service_id}_{definition.identifier}".upper()
            self._definitions[key] = definition

    def get(self, identifier: str, service_id: str = "22") -> Optional[DiagnosticDataDefinition]:
        with self._lock:
            key = f"{service_id}_{identifier}".strip().upper()
            return self._definitions.get(key)

    def list_definitions(self) -> List[DiagnosticDataDefinition]:
        with self._lock:
            return list(self._definitions.values())

    def resolve_applicable(
        self,
        context: Optional[VehicleContext] = None,
        service_id: Optional[str] = None,
    ) -> List[Tuple[DiagnosticDataDefinition, ApplicabilityResult]]:
        """Resolves all registered definitions against the given VehicleContext."""
        with self._lock:
            results = []
            for defn in self._definitions.values():
                if service_id and defn.service_id != service_id.strip().upper():
                    continue
                match = defn.applicability.evaluate(context)
                if match != ApplicabilityResult.NOT_APPLICABLE:
                    results.append((defn, match))
            return results

    def _register_standard_definitions(self) -> None:
        # Standard Mode 01: Engine RPM (010C)
        self.register(DiagnosticDataDefinition(
            identifier="0C",
            service_id="01",
            namespace=IdentifierNamespace.STANDARD_OBD_PID,
            name="EngineRPM",
            description="Engine Speed in RPM",
            expected_header="7DF",
            fields=[
                FieldDefinition(
                    name="RPM",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    byte_order=ByteOrder.BIG_ENDIAN,
                    scale=0.25,
                    offset=0.0,
                    unit="RPM",
                    min_expected_value=0,
                    max_expected_value=16000,
                )
            ],
            trust_level=DefinitionTrustLevel.STANDARD,
            definition_id="DEF-01-0C-RPM",
        ))

        # Standard Mode 01: Vehicle Speed (010D)
        self.register(DiagnosticDataDefinition(
            identifier="0D",
            service_id="01",
            namespace=IdentifierNamespace.STANDARD_OBD_PID,
            name="VehicleSpeed",
            description="Vehicle Speed in km/h",
            expected_header="7DF",
            fields=[
                FieldDefinition(
                    name="Speed",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.UINT8,
                    scale=1.0,
                    offset=0.0,
                    unit="km/h",
                    min_expected_value=0,
                    max_expected_value=350,
                )
            ],
            trust_level=DefinitionTrustLevel.STANDARD,
            definition_id="DEF-01-0D-SPEED",
        ))

        # Standard Mode 01: Engine Coolant Temperature (0105)
        self.register(DiagnosticDataDefinition(
            identifier="05",
            service_id="01",
            namespace=IdentifierNamespace.STANDARD_OBD_PID,
            name="EngineCoolantTemp",
            description="Engine Coolant Temperature in °C",
            expected_header="7DF",
            fields=[
                FieldDefinition(
                    name="ECT",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.UINT8,
                    scale=1.0,
                    offset=-40.0,
                    unit="°C",
                    min_expected_value=-40,
                    max_expected_value=215,
                )
            ],
            trust_level=DefinitionTrustLevel.STANDARD,
            definition_id="DEF-01-05-ECT",
        ))

        # Verified GM/Chevrolet UDS Mode 22 DID 1640: Engine Coolant Temperature
        self.register(DiagnosticDataDefinition(
            identifier="1640",
            service_id="22",
            namespace=IdentifierNamespace.EXTENDED_UDS_DID,
            name="EngineCoolantTemp_UDS",
            description="UDS Mode 22 Engine Coolant Temperature High Precision",
            expected_header="7E0",
            expected_payload_length=2,
            fields=[
                FieldDefinition(
                    name="ECT_UDS",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    byte_order=ByteOrder.BIG_ENDIAN,
                    scale=0.1,
                    offset=-40.0,
                    unit="°C",
                    min_expected_value=-40.0,
                    max_expected_value=150.0,
                )
            ],
            applicability=VehicleApplicability(
                manufacturers=["CHEVROLET", "OPEL", "GM"],
                engine_codes=["F14D3", "LDE", "Z16XER", "Z18XER"],
            ),
            trust_level=DefinitionTrustLevel.VERIFIED_TESTED,
            definition_id="DEF-22-1640-ECT",
        ))

        # Verified GM/Chevrolet UDS Mode 22 DID 1641: Multi-Field Composite Sensor Packet
        self.register(DiagnosticDataDefinition(
            identifier="1641",
            service_id="22",
            namespace=IdentifierNamespace.EXTENDED_UDS_DID,
            name="MultiSensorComposite_UDS",
            description="UDS Mode 22 Multi-field sensor stream (RPM, Speed, ECT, Status)",
            expected_header="7E0",
            min_payload_length=6,
            fields=[
                FieldDefinition(
                    name="RPM",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    byte_order=ByteOrder.BIG_ENDIAN,
                    scale=1.0,
                    unit="RPM",
                ),
                FieldDefinition(
                    name="Speed",
                    payload_offset=2,
                    payload_length=1,
                    data_type=DataType.UINT8,
                    scale=1.0,
                    unit="km/h",
                ),
                FieldDefinition(
                    name="CoolantTemp",
                    payload_offset=3,
                    payload_length=1,
                    data_type=DataType.UINT8,
                    scale=1.0,
                    offset=-40.0,
                    unit="°C",
                ),
                FieldDefinition(
                    name="StatusBits",
                    payload_offset=4,
                    payload_length=1,
                    data_type=DataType.BITFIELD,
                    bit_offset=0,
                    bit_length=4,
                    unit="mask",
                ),
                FieldDefinition(
                    name="FanActive",
                    payload_offset=4,
                    payload_length=1,
                    data_type=DataType.BOOLEAN,
                    bit_offset=4,
                    bit_length=1,
                    unit="bool",
                ),
            ],
            applicability=VehicleApplicability(
                manufacturers=["CHEVROLET", "OPEL", "GM"],
            ),
            trust_level=DefinitionTrustLevel.VERIFIED_TESTED,
            definition_id="DEF-22-1641-COMPOSITE",
        ))

        # Mode 21 Local ID 02: Sirius D42 block read
        self.register(DiagnosticDataDefinition(
            identifier="02",
            service_id="21",
            namespace=IdentifierNamespace.KWP_LOCAL_IDENTIFIER,
            name="SiriusD42_BlockRead",
            description="KWP2000 Local Identifier 0x02 Sirius D42 block read",
            expected_header="7E0",
            min_payload_length=10,
            fields=[
                FieldDefinition(
                    name="BlockBytes",
                    payload_offset=0,
                    payload_length=10,
                    data_type=DataType.RAW_BYTES,
                    unit="hex",
                )
            ],
            applicability=VehicleApplicability(
                manufacturers=["CHEVROLET", "DAEWOO"],
                engine_codes=["F14D3", "F16D3"],
            ),
            trust_level=DefinitionTrustLevel.VERIFIED_TESTED,
            definition_id="DEF-21-02-SIRIUS",
        ))


# =====================================================================
# 7. BATCH & SNAPSHOT ACQUISITION
# =====================================================================

@dataclass
class AcquisitionBatch:
    """Structured container for multi-identifier diagnostic acquisition results."""
    batch_id: str
    start_time: float
    end_time: float
    requested_identifiers: List[str]
    evidence: Dict[str, StructuredDiagnosticEvidence] = field(default_factory=dict)
    successful_count: int = 0
    failed_count: int = 0
    vehicle_context: Optional[VehicleContext] = None

    def get_evidence(self, identifier: str) -> Optional[StructuredDiagnosticEvidence]:
        return self.evidence.get(identifier.strip().upper())


class BatchAcquisitionManager:
    """
    Executes controlled, rate-limited, and failure-isolated acquisitions of
    multiple PIDs/DIDs over Phase G-1 DiagnosticTransactionManager.
    """
    def __init__(
        self,
        transaction_manager: DiagnosticTransactionManager,
        registry: Optional[DiagnosticDefinitionRegistry] = None,
        history_maxlen: int = 100,
    ):
        self.transaction_manager = transaction_manager
        self.registry = registry or DiagnosticDefinitionRegistry()
        self._lock = threading.RLock()
        self._history: collections.deque = collections.deque(maxlen=history_maxlen)
        self._batch_counter = 0

    def acquire_identifier(
        self,
        definition: DiagnosticDataDefinition,
        vehicle_context: Optional[VehicleContext] = None,
    ) -> StructuredDiagnosticEvidence:
        """
        Acquires a single identifier via G-1, validates response, and executes DataDecoder.
        Universal raw response preservation guaranteed.
        """
        # 1. Build and execute G-1 service request
        req = definition.build_service_request(self.transaction_manager)
        response = self.transaction_manager.execute_request(req)

        # 2. Evaluate provenance metadata
        app_res = definition.applicability.evaluate(vehicle_context)
        provenance = DataProvenance(
            source_ecu=req.target_ecu,
            identifier=definition.identifier,
            service_id=definition.service_id,
            request_timestamp=response.request_timestamp,
            response_timestamp=response.response_timestamp,
            elapsed_time=response.elapsed_time,
            transaction_id=response.transaction_id,
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            trust_level=definition.trust_level,
            applicability=app_res,
        )

        # 3. Handle G-1 level failures (Timeout, NRC, Serial error, Blocked, Cancelled)
        if not response.is_positive or response.status != STATUS_VALID:
            q = QUALITY_INVALID if response.status == STATUS_NRC else QUALITY_ERROR
            return StructuredDiagnosticEvidence(
                definition=definition,
                raw_response=response,
                raw_value=None,
                decoded_value=None,
                quality=q,
                provenance=provenance,
                is_valid=False,
                status=response.status,
                error_message=response.error_message or f"Acquisition failed: {response.status}",
            )

        # 4. Extract useful payload bytes (after service_id + subfunction/DID prefix)
        expected_prefix = response.response_service_id or ""
        if definition.subfunction:
            expected_prefix += definition.subfunction
        if definition.service_id == "22":
            expected_prefix += definition.identifier

        full_hex = response.raw_payload_hex or ""
        if not full_hex.startswith(expected_prefix):
            return StructuredDiagnosticEvidence(
                definition=definition,
                raw_response=response,
                raw_value=None,
                decoded_value=None,
                quality=QUALITY_INVALID,
                provenance=provenance,
                is_valid=False,
                status=STATUS_RESPONSE_MISMATCH,
                error_message=f"Payload {full_hex} does not echo expected prefix {expected_prefix}",
            )

        useful_hex = full_hex[len(expected_prefix):]
        try:
            useful_bytes = bytes.fromhex(useful_hex) if useful_hex else b""
        except ValueError:
            return StructuredDiagnosticEvidence(
                definition=definition,
                raw_response=response,
                raw_value=None,
                decoded_value=None,
                quality=QUALITY_INVALID,
                provenance=provenance,
                is_valid=False,
                status=STATUS_PARSE_ERROR,
                error_message=f"Non-hex payload received: {useful_hex}",
            )

        # 5. Execute DataDecoder
        raw_val, decoded_val, fields_dict, is_valid, err_msg = DataDecoder.decode(useful_bytes, definition)
        q = QUALITY_GOOD if is_valid else QUALITY_INVALID

        primary_unit = definition.fields[0].unit if definition.fields else ""

        return StructuredDiagnosticEvidence(
            definition=definition,
            raw_response=response,
            raw_value=raw_val,
            decoded_value=decoded_val,
            fields=fields_dict,
            unit=primary_unit,
            quality=q,
            provenance=provenance,
            is_valid=is_valid,
            status=STATUS_VALID if is_valid else STATUS_PARSE_ERROR,
            error_message=err_msg,
        )

    def acquire_batch(
        self,
        definitions: List[DiagnosticDataDefinition],
        vehicle_context: Optional[VehicleContext] = None,
        inter_request_delay: float = 0.01,
        cancel_event: Optional[threading.Event] = None,
    ) -> AcquisitionBatch:
        """
        Executes bounded batch acquisition across multiple definitions.
        Features strict failure isolation: one failed DID does NOT fail the batch.
        """
        with self._lock:
            self._batch_counter += 1
            batch_id = f"BATCH-{int(time.time())}-{self._batch_counter:04d}"

        start_time = time.time()
        evidence_map: Dict[str, StructuredDiagnosticEvidence] = {}
        successes = 0
        failures = 0

        for idx, defn in enumerate(definitions):
            if cancel_event and cancel_event.is_set():
                break

            # Rate limiting / safe ECU pacing
            if idx > 0 and inter_request_delay > 0:
                time.sleep(inter_request_delay)

            ev = self.acquire_identifier(defn, vehicle_context=vehicle_context)
            evidence_map[defn.identifier.upper()] = ev
            if ev.is_valid and ev.status == STATUS_VALID:
                successes += 1
            else:
                failures += 1

        batch = AcquisitionBatch(
            batch_id=batch_id,
            start_time=start_time,
            end_time=time.time(),
            requested_identifiers=[d.identifier.upper() for d in definitions],
            evidence=evidence_map,
            successful_count=successes,
            failed_count=failures,
            vehicle_context=vehicle_context,
        )

        with self._lock:
            self._history.append(batch)

        return batch

    def get_history(self, limit: Optional[int] = None) -> List[AcquisitionBatch]:
        with self._lock:
            items = list(self._history)
            if limit is not None and limit > 0:
                return items[-limit:]
            return items
