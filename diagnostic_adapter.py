#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-1
===================================================
Hardware & Diagnostic Adapter Abstraction Layer
`diagnostic_adapter.py`

Architectural Role:
    Diagnostic Intelligence (Phases C -> I)
        ↓
    Diagnostic Transport / Adapter Abstraction (Phase J-1)
        ↓
    Concrete Adapter / VCI Implementation (ELM327, J2534, Mock)
        ↓
    Physical Communication (Serial, Bluetooth, Wi-Fi, Direct Driver)

Invariants Enforced:
1. Protocol != Adapter (ELM327 is an adapter; ISO 15765 / CAN / UDS are protocols).
2. Explicit Adapter Capabilities (No silent assumptions; unsupported features fail closed).
3. Communication Failure != Component Failure (Adapter errors are communication events).
4. Authoritative Safety Policy (No adapter may bypass G-1/H-2 safety or prohibited services).
5. Lossless Backward Compatibility (DiagnosticAdapter fully satisfies ITransportAdapter).
6. Deterministic Lifecycle & Thread-Safe Time-Bounded Execution.
"""

from __future__ import annotations

import abc
import enum
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Import backward-compatible constants and interfaces from advanced_ecu_services
from advanced_ecu_services import (
    ITransportAdapter,
    ServiceSafetyPolicy,
    ServiceSafetyClassification,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    STATUS_EMPTY_RESPONSE,
)

logger = logging.getLogger("seyyanen.diagnostic_adapter")

# Prohibited Services universally blocked by Phase G-1 / H-2 / J-1
PROHIBITED_SERVICES: Set[str] = {
    "04", "4",     # Mode 04: Clear DTCs
    "14",          # UDS 0x14: Clear Diagnostic Information
    "2E",          # UDS 0x2E: Write Data By Identifier
    "27",          # UDS 0x27: Security Access
    "2F",          # UDS 0x2F: InputOutput Control By Identifier (Actuator Drive)
    "34",          # UDS 0x34: Request Download
    "35",          # UDS 0x35: Request Upload
    "36",          # UDS 0x36: Transfer Data
    "37",          # UDS 0x37: Request Transfer Exit
    "3D",          # UDS 0x3D: Write Memory By Address
}


# =====================================================================
# 1. TAXONOMY & ENUMS
# =====================================================================

class AdapterConnectionState(str, enum.Enum):
    """Explicit connection lifecycle states of a diagnostic adapter."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTING = "DISCONNECTING"
    ERROR = "ERROR"


class AdapterType(str, enum.Enum):
    """Hardware and firmware architecture of the diagnostic adapter."""
    ELM327 = "ELM327"
    STN_OBD = "STN_OBD"             # STN11xx / STN21xx / OBDLink
    J2534_PASS_THRU = "J2534"       # SAE J2534 Pass-Thru VCI
    SOCKETCAN = "SOCKETCAN"         # Linux / Embedded SocketCAN controller
    MOCK_REFERENCE = "MOCK"         # Safe deterministic reference adapter
    CUSTOM = "CUSTOM"


class TransportMedium(str, enum.Enum):
    """Physical or virtual communication medium linking host to adapter."""
    SERIAL_USB = "SERIAL_USB"
    BLUETOOTH_SPP = "BLUETOOTH_SPP"
    BLUETOOTH_BLE = "BLUETOOTH_BLE"
    WIFI_TCP = "WIFI_TCP"
    DIRECT_DRIVER = "DIRECT_DRIVER"  # Operating system driver / DLL
    SIMULATED = "SIMULATED"


class DiagnosticProtocol(str, enum.Enum):
    """
    Diagnostic protocol independent of adapter hardware.
    Adapters configure these protocols; adapters are NOT protocols.
    """
    AUTO = "AUTO"
    ISO_15765_4_CAN_11_500 = "ISO_15765_4_CAN_11_500"
    ISO_15765_4_CAN_29_500 = "ISO_15765_4_CAN_29_500"
    ISO_15765_4_CAN_11_250 = "ISO_15765_4_CAN_11_250"
    ISO_15765_4_CAN_29_250 = "ISO_15765_4_CAN_29_250"
    ISO_14230_4_KWP_FAST = "ISO_14230_4_KWP_FAST"
    ISO_14230_4_KWP_5BAUD = "ISO_14230_4_KWP_5BAUD"
    ISO_9141_2 = "ISO_9141_2"
    SAE_J1850_PWM = "SAE_J1850_PWM"
    SAE_J1850_VPW = "SAE_J1850_VPW"
    RAW_CAN = "RAW_CAN"
    UNKNOWN = "UNKNOWN"


# =====================================================================
# 2. STRUCTURED CAPABILITY MODEL
# =====================================================================

@dataclass(frozen=True)
class AdapterCapabilities:
    """
    Structured, explicit capability declaration for a diagnostic adapter.
    Upper layers query these capabilities rather than guessing hardware behavior.
    """
    # Protocol Support
    supports_iso15765_can: bool = True
    supports_can_11bit: bool = True
    supports_can_29bit: bool = True
    supports_iso14230_kwp: bool = False
    supports_iso9141: bool = False
    supports_j1850: bool = False

    # Advanced CAN & Bus Topologies
    supports_raw_can: bool = False
    supports_extended_addressing: bool = False
    supports_multi_channel: bool = False
    channel_count: int = 1

    # Configuration & Control
    supports_variable_baudrate: bool = False
    supports_timing_adjustment: bool = False
    supports_voltage_reading: bool = False
    supports_hardware_reset: bool = True
    supports_filter_mask_configuration: bool = False

    # Diagnostic Standards
    supports_obd2_standard: bool = True
    supports_uds_diagnostics: bool = True

    # Safety & Authority
    is_read_only_enforced: bool = True
    supports_privileged_services: bool = False

    def has_capability(self, capability_name: str) -> bool:
        """Determines if a named capability is supported."""
        return bool(getattr(self, capability_name, False))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supports_iso15765_can": self.supports_iso15765_can,
            "supports_can_11bit": self.supports_can_11bit,
            "supports_can_29bit": self.supports_can_29bit,
            "supports_iso14230_kwp": self.supports_iso14230_kwp,
            "supports_iso9141": self.supports_iso9141,
            "supports_j1850": self.supports_j1850,
            "supports_raw_can": self.supports_raw_can,
            "supports_extended_addressing": self.supports_extended_addressing,
            "supports_multi_channel": self.supports_multi_channel,
            "channel_count": self.channel_count,
            "supports_variable_baudrate": self.supports_variable_baudrate,
            "supports_timing_adjustment": self.supports_timing_adjustment,
            "supports_voltage_reading": self.supports_voltage_reading,
            "supports_hardware_reset": self.supports_hardware_reset,
            "supports_filter_mask_configuration": self.supports_filter_mask_configuration,
            "supports_obd2_standard": self.supports_obd2_standard,
            "supports_uds_diagnostics": self.supports_uds_diagnostics,
            "is_read_only_enforced": self.is_read_only_enforced,
            "supports_privileged_services": self.supports_privileged_services,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdapterCapabilities":
        return cls(
            supports_iso15765_can=bool(data.get("supports_iso15765_can", True)),
            supports_can_11bit=bool(data.get("supports_can_11bit", True)),
            supports_can_29bit=bool(data.get("supports_can_29bit", True)),
            supports_iso14230_kwp=bool(data.get("supports_iso14230_kwp", False)),
            supports_iso9141=bool(data.get("supports_iso9141", False)),
            supports_j1850=bool(data.get("supports_j1850", False)),
            supports_raw_can=bool(data.get("supports_raw_can", False)),
            supports_extended_addressing=bool(data.get("supports_extended_addressing", False)),
            supports_multi_channel=bool(data.get("supports_multi_channel", False)),
            channel_count=int(data.get("channel_count", 1)),
            supports_variable_baudrate=bool(data.get("supports_variable_baudrate", False)),
            supports_timing_adjustment=bool(data.get("supports_timing_adjustment", False)),
            supports_voltage_reading=bool(data.get("supports_voltage_reading", False)),
            supports_hardware_reset=bool(data.get("supports_hardware_reset", True)),
            supports_filter_mask_configuration=bool(data.get("supports_filter_mask_configuration", False)),
            supports_obd2_standard=bool(data.get("supports_obd2_standard", True)),
            supports_uds_diagnostics=bool(data.get("supports_uds_diagnostics", True)),
            is_read_only_enforced=bool(data.get("is_read_only_enforced", True)),
            supports_privileged_services=bool(data.get("supports_privileged_services", False)),
        )


# =====================================================================
# 3. STRUCTURED ADAPTER METADATA
# =====================================================================

@dataclass
class AdapterMetadata:
    """Immutable or negotiated metadata describing the connected adapter."""
    adapter_id: str
    adapter_type: AdapterType
    transport_medium: TransportMedium
    manufacturer: str = "UNKNOWN"
    model: str = "UNKNOWN"
    firmware_version: str = "UNKNOWN"
    hardware_version: str = "UNKNOWN"
    serial_number: Optional[str] = None
    max_payload_bytes: int = 4095
    driver_version: Optional[str] = None
    capabilities: AdapterCapabilities = field(default_factory=AdapterCapabilities)
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_type": self.adapter_type.value,
            "transport_medium": self.transport_medium.value,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "firmware_version": self.firmware_version,
            "hardware_version": self.hardware_version,
            "serial_number": self.serial_number,
            "max_payload_bytes": self.max_payload_bytes,
            "driver_version": self.driver_version,
            "capabilities": self.capabilities.to_dict(),
            "properties": dict(self.properties),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdapterMetadata":
        return cls(
            adapter_id=data["adapter_id"],
            adapter_type=AdapterType(data["adapter_type"]),
            transport_medium=TransportMedium(data["transport_medium"]),
            manufacturer=data.get("manufacturer", "UNKNOWN"),
            model=data.get("model", "UNKNOWN"),
            firmware_version=data.get("firmware_version", "UNKNOWN"),
            hardware_version=data.get("hardware_version", "UNKNOWN"),
            serial_number=data.get("serial_number"),
            max_payload_bytes=int(data.get("max_payload_bytes", 4095)),
            driver_version=data.get("driver_version"),
            capabilities=AdapterCapabilities.from_dict(data.get("capabilities", {})),
            properties=dict(data.get("properties", {})),
        )


# =====================================================================
# 4. STRUCTURED ERROR MODEL (COMMUNICATION != COMPONENT FAILURE)
# =====================================================================

class AdapterError(Exception):
    """
    Base exception for all diagnostic adapter and transport anomalies.
    Invariant: is_communication_failure=True indicates the anomaly is a
    physical or transport error, NEVER a vehicle ECU component defect.
    """
    def __init__(self, message: str, adapter_id: str = "UNKNOWN", state: Optional[AdapterConnectionState] = None):
        super().__init__(message)
        self.message = message
        self.adapter_id = adapter_id
        self.state = state
        self.is_communication_failure = True
        self.timestamp = time.time()

    def __str__(self) -> str:
        return f"[{self.__class__.__name__}] (Adapter: {self.adapter_id}, State: {self.state}) {self.message}"


class AdapterUnavailableError(AdapterError):
    """Adapter physical port, device handle, or interface hardware not found."""
    pass


class AdapterConnectionError(AdapterError):
    """Failed to establish or authenticate communication link with adapter."""
    pass


class AdapterTimeoutError(AdapterError):
    """Adapter communication or response deadline expired."""
    pass


class UnsupportedCapabilityError(AdapterError):
    """Requested operation or protocol is not supported by adapter capability set."""
    def __init__(self, capability: str, adapter_id: str = "UNKNOWN"):
        super().__init__(f"Adapter '{adapter_id}' lacks required capability: '{capability}'.", adapter_id=adapter_id)
        self.capability = capability


class ProtocolConfigurationError(AdapterError):
    """Failed to negotiate, select, or configure protocol timing on adapter."""
    pass


class MalformedResponseError(AdapterError):
    """Received corrupted framing, parity error, or unparseable ASCII/binary."""
    pass


class TransportFailureError(AdapterError):
    """Underlying physical bus disconnected, bus-off, or I/O failure."""
    pass


class AdapterResetError(AdapterError):
    """Software or hardware reset command failed to restore adapter to baseline."""
    pass


class AdapterStateError(AdapterError):
    """Invalid operation attempted in current adapter lifecycle state."""
    pass


class AdapterSafetyViolationError(AdapterError):
    """Attempted to dispatch a prohibited, destructive, or privileged service."""
    pass


# =====================================================================
# 5. CANONICAL ADAPTER INTERFACE
# =====================================================================

class DiagnosticAdapter(ITransportAdapter, abc.ABC):
    """
    Authoritative Canonical Interface for all Diagnostic Adapters in Seyyanen.
    Extends ITransportAdapter to ensure 100% backward compatibility with
    DiagnosticTransactionManager and MultiECUDiagnosticManager.
    """
    def __init__(
        self,
        metadata: AdapterMetadata,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
    ):
        self._metadata = metadata
        self._safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)
        self._state: AdapterConnectionState = AdapterConnectionState.DISCONNECTED
        self._active_protocol: DiagnosticProtocol = DiagnosticProtocol.AUTO
        self._current_header: str = "7DF"
        self._lock = threading.RLock()
        self._history: List[str] = []

    # -----------------------------------------------------------------
    # Metadata & Capability Introspection
    # -----------------------------------------------------------------

    @property
    def metadata(self) -> AdapterMetadata:
        """Returns immutable metadata describing this adapter."""
        return self._metadata

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Returns structured capability declaration for this adapter."""
        return self._metadata.capabilities

    @property
    def adapter_id(self) -> str:
        return self._metadata.adapter_id

    @property
    def adapter_type(self) -> AdapterType:
        return self._metadata.adapter_type

    @property
    def connection_state(self) -> AdapterConnectionState:
        with self._lock:
            return self._state

    @property
    def active_protocol(self) -> DiagnosticProtocol:
        with self._lock:
            return self._active_protocol

    @property
    def safety_policy(self) -> ServiceSafetyPolicy:
        return self._safety_policy

    def require_capability(self, capability_name: str) -> None:
        """
        Enforces that this adapter possesses the given capability.
        Raises UnsupportedCapabilityError if missing (fail-closed).
        """
        if not self.capabilities.has_capability(capability_name):
            raise UnsupportedCapabilityError(capability_name, self.adapter_id)

    # -----------------------------------------------------------------
    # Lifecycle Management
    # -----------------------------------------------------------------

    def connect(self, timeout: float = 5.0) -> bool:
        """
        Transitions adapter from DISCONNECTED to CONNECTED.
        Thread-safe, state-validated, and time-bounded.
        """
        with self._lock:
            if self._state == AdapterConnectionState.CONNECTED:
                logger.debug("Adapter %s already connected.", self.adapter_id)
                return True

            if self._state not in (AdapterConnectionState.DISCONNECTED, AdapterConnectionState.ERROR):
                raise AdapterStateError(
                    f"Cannot connect: invalid current state '{self._state.value}'.",
                    adapter_id=self.adapter_id,
                    state=self._state,
                )

            self._state = AdapterConnectionState.CONNECTING
            logger.info("Connecting diagnostic adapter '%s'...", self.adapter_id)

        start_time = time.time()
        try:
            success = self._do_connect(timeout=timeout)
            if not success or (time.time() - start_time) > timeout:
                with self._lock:
                    self._state = AdapterConnectionState.ERROR
                raise AdapterConnectionError(
                    f"Connection timed out or failed for adapter '{self.adapter_id}'.",
                    adapter_id=self.adapter_id,
                    state=AdapterConnectionState.ERROR,
                )

            with self._lock:
                self._state = AdapterConnectionState.CONNECTED
            logger.info("Adapter '%s' successfully CONNECTED.", self.adapter_id)
            return True

        except Exception as e:
            with self._lock:
                self._state = AdapterConnectionState.ERROR
            if isinstance(e, AdapterError):
                raise
            raise AdapterConnectionError(
                f"Unexpected exception during connect on '{self.adapter_id}': {e}",
                adapter_id=self.adapter_id,
                state=AdapterConnectionState.ERROR,
            ) from e

    def disconnect(self) -> bool:
        """Transitions adapter from CONNECTED to DISCONNECTED cleanly."""
        with self._lock:
            if self._state == AdapterConnectionState.DISCONNECTED:
                return True

            self._state = AdapterConnectionState.DISCONNECTING
            logger.info("Disconnecting diagnostic adapter '%s'...", self.adapter_id)

        try:
            self._do_disconnect()
        finally:
            with self._lock:
                self._state = AdapterConnectionState.DISCONNECTED
            logger.info("Adapter '%s' DISCONNECTED.", self.adapter_id)
        return True

    def is_connected(self) -> bool:
        """ITransportAdapter compatibility method."""
        with self._lock:
            return self._state == AdapterConnectionState.CONNECTED

    def reset(self, hard: bool = False) -> bool:
        """
        Resets adapter hardware/firmware to baseline default state.
        Fails closed if unsupported.
        """
        self.require_capability("supports_hardware_reset")
        with self._lock:
            if not self.is_connected():
                raise AdapterStateError("Cannot reset adapter: not connected.", adapter_id=self.adapter_id)
        return self._do_reset(hard=hard)

    # -----------------------------------------------------------------
    # Protocol & Header Management
    # -----------------------------------------------------------------

    def set_protocol(self, protocol: DiagnosticProtocol, timeout: float = 2.0) -> bool:
        """Configures the active diagnostic protocol on the adapter."""
        with self._lock:
            if not self.is_connected():
                raise AdapterStateError("Cannot set protocol while disconnected.", adapter_id=self.adapter_id)

        # Capability validation
        if protocol in (DiagnosticProtocol.ISO_15765_4_CAN_11_500, DiagnosticProtocol.ISO_15765_4_CAN_11_250):
            self.require_capability("supports_can_11bit")
        elif protocol in (DiagnosticProtocol.ISO_15765_4_CAN_29_500, DiagnosticProtocol.ISO_15765_4_CAN_29_250):
            self.require_capability("supports_can_29bit")
        elif protocol in (DiagnosticProtocol.ISO_14230_4_KWP_FAST, DiagnosticProtocol.ISO_14230_4_KWP_5BAUD):
            self.require_capability("supports_iso14230_kwp")
        elif protocol == DiagnosticProtocol.ISO_9141_2:
            self.require_capability("supports_iso9141")
        elif protocol in (DiagnosticProtocol.SAE_J1850_PWM, DiagnosticProtocol.SAE_J1850_VPW):
            self.require_capability("supports_j1850")
        elif protocol == DiagnosticProtocol.RAW_CAN:
            self.require_capability("supports_raw_can")

        ok = self._do_set_protocol(protocol, timeout=timeout)
        if ok:
            with self._lock:
                self._active_protocol = protocol
        return ok

    def get_current_header(self) -> str:
        """ITransportAdapter compatibility method."""
        with self._lock:
            return self._current_header

    def set_header(self, header: str, timeout: float = 1.0) -> bool:
        """ITransportAdapter compatibility method."""
        with self._lock:
            if not self.is_connected():
                raise AdapterStateError("Cannot set header while disconnected.", adapter_id=self.adapter_id)
            clean = header.strip().upper()
            ok = self._do_set_header(clean, timeout=timeout)
            if ok:
                self._current_header = clean
            return ok

    def read_battery_voltage(self) -> Optional[float]:
        """Reads vehicle battery voltage if supported by adapter."""
        if not self.capabilities.supports_voltage_reading:
            return None
        with self._lock:
            if not self.is_connected():
                return None
        return self._do_read_battery_voltage()

    # -----------------------------------------------------------------
    # Diagnostic Command Dispatch & Safety Gating
    # -----------------------------------------------------------------

    def send_command(self, cmd: str, timeout: float = 1.0) -> Tuple[List[str], str]:
        """
        Authoritative Command Transmission.
        Satisfies ITransportAdapter.send_command.
        Enforces:
          1. Connection state verification.
          2. Immediate safety validation: Prohibited services (04, 14, 2E, 27, 2F, 34-37) fail closed.
          3. Exception to structured communication status mapping.
        """
        with self._lock:
            if not self.is_connected():
                return [], STATUS_NO_CONNECTION

            # Safety Dual-Gate Check
            clean_cmd = cmd.strip().upper().replace(" ", "")
            sid_match = re.match(r"^([0-9A-F]{2})", clean_cmd)
            if sid_match:
                sid = sid_match.group(1)
                if sid in PROHIBITED_SERVICES:
                    logger.error("Safety Violation: Prohibited service 0x%s blocked by adapter safety gate.", sid)
                    return [], STATUS_NRC

        try:
            with self._lock:
                self._history.append(cmd)
            return self._do_send_command(cmd, timeout=timeout)

        except AdapterTimeoutError:
            return [], STATUS_TIMEOUT
        except MalformedResponseError:
            return [], STATUS_SERIAL_ERROR
        except TransportFailureError:
            with self._lock:
                self._state = AdapterConnectionState.ERROR
            return [], STATUS_SERIAL_ERROR
        except Exception as e:
            logger.exception("Unexpected error in send_command on adapter '%s': %s", self.adapter_id, e)
            return [], STATUS_SERIAL_ERROR

    # -----------------------------------------------------------------
    # Abstract Extension Points
    # -----------------------------------------------------------------

    @abc.abstractmethod
    def _do_connect(self, timeout: float) -> bool:
        """Subclass implementation of physical connection establishment."""
        pass

    @abc.abstractmethod
    def _do_disconnect(self) -> None:
        """Subclass implementation of physical connection teardown."""
        pass

    @abc.abstractmethod
    def _do_send_command(self, cmd: str, timeout: float) -> Tuple[List[str], str]:
        """Subclass implementation of command sending."""
        pass

    def _do_reset(self, hard: bool) -> bool:
        """Optional subclass override for hardware/software reset."""
        return True

    def _do_set_protocol(self, protocol: DiagnosticProtocol, timeout: float) -> bool:
        """Optional subclass override for protocol configuration."""
        return True

    def _do_set_header(self, header: str, timeout: float) -> bool:
        """Optional subclass override for header configuration."""
        return True

    def _do_read_battery_voltage(self) -> Optional[float]:
        """Optional subclass override for reading voltage."""
        return None


# =====================================================================
# 6. SAFE REFERENCE / MOCK ADAPTER
# =====================================================================

class MockDiagnosticAdapter(DiagnosticAdapter):
    """
    Deterministic, offline, pure in-memory Reference Diagnostic Adapter.
    Enables reproducible unit, integration, and cross-layer testing without
    physical hardware, serial ports, or risk of vehicle damage.
    """
    def __init__(
        self,
        adapter_id: str = "MOCK_REF_01",
        capabilities: Optional[AdapterCapabilities] = None,
        responses: Optional[Dict[str, List[str]]] = None,
        simulated_voltage: float = 12.6,
    ):
        caps = capabilities or AdapterCapabilities(
            supports_iso15765_can=True,
            supports_can_11bit=True,
            supports_can_29bit=True,
            supports_iso14230_kwp=True,
            supports_iso9141=True,
            supports_voltage_reading=True,
            supports_hardware_reset=True,
            supports_uds_diagnostics=True,
        )
        meta = AdapterMetadata(
            adapter_id=adapter_id,
            adapter_type=AdapterType.MOCK_REFERENCE,
            transport_medium=TransportMedium.SIMULATED,
            manufacturer="Seyyanen Reference Lab",
            model="Virtual-VCI-2026",
            firmware_version="v2.5.0-mock",
            hardware_version="revB",
            capabilities=caps,
        )
        super().__init__(metadata=meta)
        self.responses: Dict[str, List[str]] = dict(responses or {})
        self.simulated_voltage = simulated_voltage

        # Fault Injection Knobs
        self.force_timeout: bool = False
        self.force_malformed: bool = False
        self.force_transport_error: bool = False
        self.force_connect_failure: bool = False
        self.reset_count: int = 0

    def register_response(self, command: str, response_lines: List[str]) -> None:
        """Registers a deterministic response mapping for simulated commands."""
        clean = command.strip().upper().replace(" ", "")
        self.responses[clean] = list(response_lines)

    def _do_connect(self, timeout: float) -> bool:
        if self.force_connect_failure:
            return False
        return True

    def _do_disconnect(self) -> None:
        pass

    def _do_reset(self, hard: bool) -> bool:
        self.reset_count += 1
        self._current_header = "7DF"
        self._active_protocol = DiagnosticProtocol.AUTO
        return True

    def _do_set_protocol(self, protocol: DiagnosticProtocol, timeout: float) -> bool:
        return True

    def _do_set_header(self, header: str, timeout: float) -> bool:
        return True

    def _do_read_battery_voltage(self) -> Optional[float]:
        return self.simulated_voltage

    def _do_send_command(self, cmd: str, timeout: float) -> Tuple[List[str], str]:
        if self.force_timeout:
            raise AdapterTimeoutError(f"Simulated timeout on command '{cmd}'.", adapter_id=self.adapter_id)

        if self.force_transport_error:
            raise TransportFailureError(f"Simulated transport disconnect on command '{cmd}'.", adapter_id=self.adapter_id)

        if self.force_malformed:
            raise MalformedResponseError(f"Simulated framing corruption on command '{cmd}'.", adapter_id=self.adapter_id)

        clean = cmd.strip().upper().replace(" ", "")

        # Direct response lookup
        if clean in self.responses:
            return self.responses[clean], STATUS_VALID

        # Prefix response lookup
        for k, v in self.responses.items():
            if clean.startswith(k):
                return v, STATUS_VALID

        # Default ELM-style responses for common AT commands
        if clean.startswith("AT"):
            if clean in ("ATZ", "ATWS"):
                return ["ELM327 v1.5"], STATUS_VALID
            if clean == "ATRV":
                return [f"{self.simulated_voltage:.1f}V"], STATUS_VALID
            if clean.startswith("ATSH"):
                return ["OK"], STATUS_VALID
            if clean.startswith("ATSP"):
                return ["OK"], STATUS_VALID
            return ["OK"], STATUS_VALID

        return [], STATUS_NO_DATA


# =====================================================================
# 7. PRODUCTION ELM327 ADAPTER BOUNDARY
# =====================================================================

class ELM327DiagnosticAdapter(DiagnosticAdapter):
    """
    Production-oriented ELM327 & STN Adapter Integration.
    Wraps AutoExpertEngine or Serial communication without exposing ELM internals
    to higher diagnostic reasoning layers.
    """
    def __init__(
        self,
        engine: Any = None,
        adapter_id: str = "ELM327_SERIAL_01",
        port: str = "COM_MOCK",
        baudrate: int = 38400,
        capabilities: Optional[AdapterCapabilities] = None,
    ):
        caps = capabilities or AdapterCapabilities(
            supports_iso15765_can=True,
            supports_can_11bit=True,
            supports_can_29bit=True,
            supports_iso14230_kwp=True,
            supports_iso9141=True,
            supports_j1850=True,
            supports_raw_can=False,           # ELM327 lacks raw unbuffered CAN streaming
            supports_multi_channel=False,     # Single physical channel
            supports_extended_addressing=False,
            supports_voltage_reading=True,    # ATRV command
            supports_hardware_reset=True,     # ATZ command
            supports_uds_diagnostics=True,
        )
        meta = AdapterMetadata(
            adapter_id=adapter_id,
            adapter_type=AdapterType.ELM327,
            transport_medium=TransportMedium.SERIAL_USB,
            manufacturer="ELM Electronics / Compatible",
            model="ELM327",
            firmware_version="v1.5 / v2.1",
            capabilities=caps,
            properties={"port": port, "baudrate": baudrate},
        )
        super().__init__(metadata=meta)
        self.engine = engine
        self.port = port
        self.baudrate = baudrate

    def _do_connect(self, timeout: float) -> bool:
        if self.engine and hasattr(self.engine, "ser"):
            ser = self.engine.ser
            return bool(ser and getattr(ser, "is_open", False))
        return True

    def _do_disconnect(self) -> None:
        if self.engine and hasattr(self.engine, "ser"):
            ser = self.engine.ser
            if ser and getattr(ser, "is_open", False):
                try:
                    ser.close()
                except Exception:
                    pass

    def _do_reset(self, hard: bool) -> bool:
        if not self.engine:
            return True
        cmd = "AT Z" if hard else "AT WS"
        lines, status = self.send_command(cmd, timeout=2.0)
        return status == STATUS_VALID

    def _do_set_header(self, header: str, timeout: float) -> bool:
        if not self.engine:
            return True
        lines, status = self.send_command(f"AT SH {header}", timeout=timeout)
        return status == STATUS_VALID or "OK" in "".join(lines)

    def _do_set_protocol(self, protocol: DiagnosticProtocol, timeout: float) -> bool:
        proto_map = {
            DiagnosticProtocol.AUTO: "0",
            DiagnosticProtocol.ISO_15765_4_CAN_11_500: "6",
            DiagnosticProtocol.ISO_15765_4_CAN_29_500: "7",
            DiagnosticProtocol.ISO_15765_4_CAN_11_250: "8",
            DiagnosticProtocol.ISO_15765_4_CAN_29_250: "9",
            DiagnosticProtocol.ISO_14230_4_KWP_FAST: "5",
            DiagnosticProtocol.ISO_9141_2: "3",
        }
        at_num = proto_map.get(protocol)
        if not at_num:
            return False
        lines, status = self.send_command(f"AT SP {at_num}", timeout=timeout)
        return status == STATUS_VALID or "OK" in "".join(lines)

    def _do_read_battery_voltage(self) -> Optional[float]:
        lines, status = self.send_command("AT RV", timeout=1.0)
        if status == STATUS_VALID and lines:
            m = re.search(r"([0-9]+\.[0-9]+)\s*V?", lines[0])
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
        return None

    def _do_send_command(self, cmd: str, timeout: float) -> Tuple[List[str], str]:
        if not self.engine:
            return [], STATUS_NO_CONNECTION
        if hasattr(self.engine, "send_command"):
            return self.engine.send_command(cmd, timeout=timeout)
        elif hasattr(self.engine, "komut_gonder"):
            raw_lines = self.engine.komut_gonder(cmd, timeout=timeout)
            status = getattr(self.engine, "last_response_status", STATUS_VALID)
            return raw_lines or [], status
        return [], STATUS_NO_CONNECTION


# =====================================================================
# 8. J2534 / ADVANCED VCI PREPARATION INTERFACE
# =====================================================================

class J2534DiagnosticAdapter(DiagnosticAdapter):
    """
    Extensibility Placeholder for High-End SAE J2534 Pass-Thru Devices.
    Models multi-channel, high-throughput, raw CAN capabilities without
    implementing vendor-specific Windows DLL wrappers ahead of schedule.
    """
    def __init__(
        self,
        adapter_id: str = "J2534_VCI_01",
        device_name: str = "Generic J2534 Device",
        dll_path: Optional[str] = None,
        capabilities: Optional[AdapterCapabilities] = None,
    ):
        caps = capabilities or AdapterCapabilities(
            supports_iso15765_can=True,
            supports_can_11bit=True,
            supports_can_29bit=True,
            supports_iso14230_kwp=True,
            supports_iso9141=True,
            supports_j1850=True,
            supports_raw_can=True,                 # Full raw CAN streaming
            supports_extended_addressing=True,
            supports_multi_channel=True,           # Dual-channel CAN
            channel_count=2,
            supports_variable_baudrate=True,
            supports_timing_adjustment=True,
            supports_voltage_reading=True,
            supports_hardware_reset=True,
            supports_filter_mask_configuration=True,
            supports_uds_diagnostics=True,
        )
        meta = AdapterMetadata(
            adapter_id=adapter_id,
            adapter_type=AdapterType.J2534_PASS_THRU,
            transport_medium=TransportMedium.DIRECT_DRIVER,
            manufacturer="SAE J2534 Device Vendor",
            model=device_name,
            firmware_version="J2534-v04.04",
            driver_version=dll_path or "PassThru32.dll",
            capabilities=caps,
        )
        super().__init__(metadata=meta)

    def _do_connect(self, timeout: float) -> bool:
        # Phase J-1 models capability; driver loading deferred to future J2534 module
        return True

    def _do_disconnect(self) -> None:
        pass

    def _do_send_command(self, cmd: str, timeout: float) -> Tuple[List[str], str]:
        # Reference implementation for J2534 command framing
        return ["J2534_ECHO: " + cmd], STATUS_VALID


# =====================================================================
# 9. ADAPTER REGISTRY & DISCOVERY FACTORY
# =====================================================================

class AdapterRegistry:
    """
    Central, Extensible Factory & Discovery Registry for Diagnostic Adapters.
    Prevents hard-coded adapter type checks and enables dynamic driver registration.
    """
    _factories: Dict[AdapterType, Callable[..., DiagnosticAdapter]] = {}
    _lock = threading.RLock()

    @classmethod
    def register_factory(
        cls,
        adapter_type: AdapterType,
        factory: Callable[..., DiagnosticAdapter],
        override: bool = False,
    ) -> None:
        """Registers a factory callable for creating adapter instances."""
        with cls._lock:
            if adapter_type in cls._factories and not override:
                raise ValueError(f"Factory for adapter type '{adapter_type.value}' is already registered.")
            cls._factories[adapter_type] = factory
            logger.info("Registered adapter factory for '%s'.", adapter_type.value)

    @classmethod
    def create_adapter(cls, adapter_type: AdapterType, **kwargs) -> DiagnosticAdapter:
        """Instantiates an adapter of the specified type with arguments."""
        with cls._lock:
            factory = cls._factories.get(adapter_type)
            if not factory:
                raise KeyError(f"No factory registered for adapter type '{adapter_type.value}'.")
            return factory(**kwargs)

    @classmethod
    def list_supported_types(cls) -> List[AdapterType]:
        """Lists all registered adapter types."""
        with cls._lock:
            return sorted(list(cls._factories.keys()), key=lambda x: x.value)

    @classmethod
    def find_adapters_with_capabilities(cls, **required_capabilities: bool) -> List[AdapterType]:
        """
        Queries registered adapter types that satisfy the required capabilities.
        Example: find_adapters_with_capabilities(supports_raw_can=True)
        """
        matching: List[AdapterType] = []
        with cls._lock:
            for atype, factory in cls._factories.items():
                try:
                    # Probe capabilities using a transient instance
                    inst = factory(adapter_id=f"PROBE_{atype.value}")
                    caps = inst.capabilities
                    meets_all = True
                    for cap_name, req_val in required_capabilities.items():
                        if getattr(caps, cap_name, None) != req_val:
                            meets_all = False
                            break
                    if meets_all:
                        matching.append(atype)
                except Exception:
                    continue
        return matching


# Register standard built-in adapter factories
AdapterRegistry.register_factory(AdapterType.MOCK_REFERENCE, lambda **kw: MockDiagnosticAdapter(**kw), override=True)
AdapterRegistry.register_factory(AdapterType.ELM327, lambda **kw: ELM327DiagnosticAdapter(**kw), override=True)
AdapterRegistry.register_factory(AdapterType.J2534_PASS_THRU, lambda **kw: J2534DiagnosticAdapter(**kw), override=True)
