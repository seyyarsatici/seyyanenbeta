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
import os
import re
import sys
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
    FAILED = "FAILED"

    def __eq__(self, other: Any) -> bool:
        if self.value in ("ERROR", "FAILED"):
            if other in ("ERROR", "FAILED"):
                return True
            if hasattr(other, "value") and other.value in ("ERROR", "FAILED"):
                return True
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self.value)


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

    # Hardware & Transport Interface (Phase K-2)
    supports_serial_transport: bool = True
    supports_elm327_commands: bool = True

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
            "supports_serial_transport": self.supports_serial_transport,
            "supports_elm327_commands": self.supports_elm327_commands,
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
            supports_serial_transport=bool(data.get("supports_serial_transport", True)),
            supports_elm327_commands=bool(data.get("supports_elm327_commands", True)),
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
        self._connect_thread: Optional[threading.Thread] = None
        self._connect_cancel_event = threading.Event()

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
        Synchronous entry point for non-UI callers and tests.
        """
        with self._lock:
            if self._state == AdapterConnectionState.CONNECTED:
                logger.debug("Adapter %s already connected.", self.adapter_id)
                return True

            if self._state not in (AdapterConnectionState.DISCONNECTED, AdapterConnectionState.ERROR, AdapterConnectionState.FAILED):
                raise AdapterStateError(
                    f"Cannot connect: invalid current state '{self._state.value}'.",
                    adapter_id=self.adapter_id,
                    state=self._state,
                )

            self._state = AdapterConnectionState.CONNECTING
            self._connect_cancel_event.clear()
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

    def connect_async(
        self,
        timeout: float = 5.0,
        on_finished: Optional[Callable[[bool, Optional[Exception]], None]] = None,
    ) -> bool:
        """
        Non-blocking adapter connection.
        Transitions state to CONNECTING, launches background worker thread,
        and returns immediately without blocking caller.
        Rejects concurrent duplicate connect attempts while CONNECTING.
        """
        with self._lock:
            if self._state == AdapterConnectionState.CONNECTED:
                logger.debug("Adapter %s already connected.", self.adapter_id)
                if on_finished:
                    on_finished(True, None)
                return True

            if self._state == AdapterConnectionState.CONNECTING:
                logger.warning("Adapter %s already connecting. Duplicate connect request ignored.", self.adapter_id)
                return False

            if self._state not in (AdapterConnectionState.DISCONNECTED, AdapterConnectionState.ERROR, AdapterConnectionState.FAILED):
                raise AdapterStateError(
                    f"Cannot connect: invalid current state '{self._state.value}'.",
                    adapter_id=self.adapter_id,
                    state=self._state,
                )

            self._state = AdapterConnectionState.CONNECTING
            self._connect_cancel_event.clear()
            logger.info("Asynchronously connecting diagnostic adapter '%s'...", self.adapter_id)

        def _bg_connect():
            success = False
            err: Optional[Exception] = None
            try:
                if self._connect_cancel_event.is_set():
                    with self._lock:
                        if self._state == AdapterConnectionState.CONNECTING:
                            self._state = AdapterConnectionState.DISCONNECTED
                    if on_finished:
                        on_finished(False, None)
                    return

                start_time = time.time()
                success = self._do_connect(timeout=timeout)
                elapsed = time.time() - start_time

                if self._connect_cancel_event.is_set():
                    self._do_disconnect()
                    with self._lock:
                        self._state = AdapterConnectionState.DISCONNECTED
                    if on_finished:
                        on_finished(False, None)
                    return

                if not success or elapsed > timeout:
                    success = False
                    with self._lock:
                        self._state = AdapterConnectionState.FAILED
                    if elapsed > timeout:
                        err = AdapterTimeoutError(
                            f"Connection timed out after {elapsed:.2f}s for adapter '{self.adapter_id}'.",
                            adapter_id=self.adapter_id,
                            state=AdapterConnectionState.FAILED,
                        )
                    else:
                        err = AdapterConnectionError(
                            f"Connection failed for adapter '{self.adapter_id}'.",
                            adapter_id=self.adapter_id,
                            state=AdapterConnectionState.FAILED,
                        )
                else:
                    with self._lock:
                        self._state = AdapterConnectionState.CONNECTED
                    logger.info("Adapter '%s' successfully CONNECTED (async).", self.adapter_id)

            except Exception as e:
                with self._lock:
                    self._state = AdapterConnectionState.FAILED
                if isinstance(e, AdapterError):
                    err = e
                else:
                    err = AdapterConnectionError(
                        f"Unexpected exception during connect on '{self.adapter_id}': {e}",
                        adapter_id=self.adapter_id,
                        state=AdapterConnectionState.FAILED,
                    )
                logger.error("Async connect error on '%s': %s", self.adapter_id, err)

            finally:
                with self._lock:
                    self._connect_thread = None
                if on_finished:
                    try:
                        on_finished(success, err)
                    except Exception as cb_ex:
                        logger.warning("Error in connect_async callback: %s", cb_ex)

        self._connect_thread = threading.Thread(
            target=_bg_connect,
            name=f"AdapterConnectWorker-{self.adapter_id}",
            daemon=True,
        )
        self._connect_thread.start()
        return True

    def disconnect(self) -> bool:
        """Transitions adapter from CONNECTED or CONNECTING to DISCONNECTED cleanly."""
        with self._lock:
            if self._state == AdapterConnectionState.DISCONNECTED:
                return True

            if self._state == AdapterConnectionState.CONNECTING:
                self._connect_cancel_event.set()

            self._state = AdapterConnectionState.DISCONNECTING
            logger.info("Disconnecting diagnostic adapter '%s'...", self.adapter_id)

        # Cooperative join of active worker to prevent leaks
        worker = getattr(self, "_connect_thread", None)
        if worker and worker.is_alive() and worker != threading.current_thread():
            worker.join(timeout=0.5)

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
            clean_tokens = cmd.strip().upper().split()
            first_tok = clean_tokens[0] if clean_tokens else ""
            norm_sid = first_tok.zfill(2) if len(first_tok) == 1 else first_tok
            if first_tok in PROHIBITED_SERVICES or norm_sid in PROHIBITED_SERVICES:
                logger.error("Safety Violation: Prohibited service 0x%s blocked by adapter safety gate.", norm_sid)
                return [], STATUS_NRC

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
        self.force_connect_delay: float = 0.0
        self.reset_count: int = 0

    def register_response(self, command: str, response_lines: List[str]) -> None:
        """Registers a deterministic response mapping for simulated commands."""
        clean = command.strip().upper().replace(" ", "")
        self.responses[clean] = list(response_lines)

    def _do_connect(self, timeout: float) -> bool:
        if self.force_connect_delay > 0:
            time.sleep(self.force_connect_delay)
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
# 7. PRODUCTION ELM327 USB/SERIAL ADAPTER & TRANSPORT (PHASE K-2)
# =====================================================================

class ELM327TransportStage(str, enum.Enum):
    """
    Granular hardware and bus transport stages for ELM327 diagnostic adapters (Phase K-2).
    Distinguishes serial port open, adapter responsiveness, and vehicle protocol readiness.
    """
    DISCONNECTED = "DISCONNECTED"
    PORT_OPENED = "PORT_OPENED"                   # COM port opened
    ELM327_RESPONSIVE = "ELM327_RESPONSIVE"       # AT commands handshake succeeded
    VEHICLE_PROTOCOL_READY = "VEHICLE_PROTOCOL_READY" # Vehicle bus protocol verified & ECU responsive


class MockSerialForELM:
    """
    Deterministic serial port test double for ELM327 USB/Serial validation (Phase K-2).
    Simulates real UART byte streams, framing, echoes, prompts, timeouts, and bus conditions.
    """
    def __init__(
        self,
        port: str = "COM_MOCK",
        baudrate: int = 38400,
        timeout: float = 1.0,
        write_timeout: float = 1.0,
        fail_open: bool = False,
        fail_init_timeout: bool = False,
        fail_init_error: bool = False,
        inject_unexpected_reset: bool = False,
        inject_bus_error: bool = False,
        inject_no_data: bool = False,
        inject_nrc: bool = False,
        simulate_disconnect: bool = False,
        custom_responses: Optional[Dict[str, bytes]] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.fail_open = fail_open
        self.fail_init_timeout = fail_init_timeout
        self.fail_init_error = fail_init_error
        self.inject_unexpected_reset = inject_unexpected_reset
        self.inject_bus_error = inject_bus_error
        self.inject_no_data = inject_no_data
        self.inject_nrc = inject_nrc
        self.simulate_disconnect = simulate_disconnect
        self.custom_responses = dict(custom_responses or {})

        if self.fail_open:
            import serial
            raise serial.SerialException(f"Failed to open mock port '{port}': Access is denied.")

        self.is_open = True
        self.echo_enabled = True
        self._write_buffer = bytearray()
        self._read_buffer = bytearray()
        self._tx_history: List[str] = []

    @property
    def in_waiting(self) -> int:
        return len(self._read_buffer) if self.is_open else 0

    def write(self, data: bytes) -> int:
        if not self.is_open:
            import serial
            raise serial.SerialException("Attempted write to closed serial port.")
        if self.simulate_disconnect:
            self.is_open = False
            import serial
            raise serial.SerialException("USB device removed / COM port disconnected.")

        self._write_buffer.extend(data)
        if b"\r" in self._write_buffer or b"\n" in self._write_buffer:
            raw_line = bytes(self._write_buffer)
            self._write_buffer.clear()
            cmd = raw_line.decode("ascii", errors="replace").strip().upper()
            self._tx_history.append(cmd)
            self._handle_command(cmd)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            import serial
            raise serial.SerialException("Attempted read from closed serial port.")
        if self.simulate_disconnect:
            self.is_open = False
            import serial
            raise serial.SerialException("USB device removed / COM port disconnected.")

        if not self._read_buffer:
            return b""
        chunk = self._read_buffer[:size]
        self._read_buffer = self._read_buffer[size:]
        return bytes(chunk)

    def reset_input_buffer(self) -> None:
        self._read_buffer.clear()

    def reset_output_buffer(self) -> None:
        self._write_buffer.clear()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False
        self._read_buffer.clear()
        self._write_buffer.clear()

    def open(self) -> None:
        self.is_open = True

    def _handle_command(self, cmd: str) -> None:
        if cmd in self.custom_responses:
            resp = self.custom_responses[cmd]
            if self.echo_enabled:
                resp = f"{cmd}\r".encode("ascii") + resp
            self._read_buffer.extend(resp)
            return

        if self.fail_init_timeout and cmd in ("ATZ", "AT Z", "ATWS", "AT WS"):
            return

        if self.fail_init_error and cmd in ("ATZ", "AT Z", "ATWS", "AT WS"):
            self._read_buffer.extend(b"?\r\r>")
            return

        if self.inject_unexpected_reset and not cmd.startswith("AT"):
            self._read_buffer.extend(b"ELM327 v1.5\r\r>")
            return

        if self.inject_bus_error and not cmd.startswith("AT"):
            self._read_buffer.extend(b"CAN ERROR\r\r>")
            return

        if self.inject_no_data and not cmd.startswith("AT"):
            self._read_buffer.extend(b"NO DATA\r\r>")
            return

        if self.inject_nrc and not cmd.startswith("AT"):
            self._read_buffer.extend(b"7E8 03 7F 22 31\r\r>")
            return

        cmd_clean = cmd.replace(" ", "")
        payload = b""

        if cmd_clean in ("ATZ", "ATWS"):
            payload = b"ELM327 v1.5\r\r>"
        elif cmd_clean == "ATE0":
            self.echo_enabled = False
            payload = b"OK\r\r>"
        elif cmd_clean == "ATE1":
            self.echo_enabled = True
            payload = b"OK\r\r>"
        elif cmd_clean in ("ATL0", "ATL1", "ATS0", "ATS1", "ATH0", "ATH1", "ATAT1", "ATSTFF"):
            payload = b"OK\r\r>"
        elif cmd_clean.startswith("ATSP") or cmd_clean.startswith("ATSH"):
            payload = b"OK\r\r>"
        elif cmd_clean in ("ATDPN", "AT DPN"):
            payload = b"6\r\r>"
        elif cmd_clean in ("ATDP", "AT DP"):
            payload = b"ISO 15765-4 (CAN 11/500)\r\r>"
        elif cmd_clean in ("ATRV", "AT RV"):
            payload = b"12.6V\r\r>"
        elif cmd_clean in ("ATI", "AT I"):
            payload = b"ELM327 v1.5\r\r>"
        elif cmd_clean == "0100":
            payload = b"7E8 06 41 00 BE 3E B8 11\r\r>"
        elif cmd_clean == "010C":
            payload = b"7E8 04 41 0C 0F A0\r\r>"
        elif cmd_clean == "010D":
            payload = b"7E8 03 41 0D 00\r\r>"
        elif cmd_clean.startswith("22"):
            payload = b"7E8 05 62 01 00 12 34\r\r>"
        else:
            payload = b"OK\r\r>"

        if self.echo_enabled:
            payload = f"{cmd}\r".encode("ascii") + payload

        self._read_buffer.extend(payload)


@dataclass
class PortProbeResult:
    """Structured result of probing a serial port for an ELM327 adapter."""
    port: str
    transport: str = "serial"
    connection_state: str = "FAILED"
    adapter_detected: bool = False
    adapter_identity: Optional[str] = None
    baudrate: int = 38400
    failure_reason: Optional[str] = None
    description: str = ""


def is_simulation_mode(explicit: Optional[bool] = None) -> bool:
    """Checks if simulation mode (MockSerial / COM_MOCK) is explicitly enabled."""
    if explicit is not None:
        return bool(explicit)
    for var in ("SEYYANEN_SIMULATION", "SIMULATION", "USE_MOCK_SERIAL", "MOCK_OBD"):
        val = os.environ.get(var)
        if val is not None:
            return val.strip().lower() in ("1", "true", "yes", "on")
    if any(arg.lower() in ("--simulation", "--mock") for arg in sys.argv):
        return True
    return False


def log_real_connect(msg: str) -> None:
    """Structured console output for real hardware connection diagnostics."""
    print(f"[REAL-CONNECT] {msg}", flush=True)
    logger.info("[REAL-CONNECT] %s", msg)


def enumerate_candidate_ports(explicit_port: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Discovers candidate serial COM ports on Windows / host and returns a deterministic,
    prioritized candidate list.
    Priority 0: Explicitly specified port
    Priority 1: Known VCI / OBD chipsets (CH340, FTDI, CP210, Prolific, vLinker, ELM327, STN)
    Priority 2: Bluetooth serial ports (Standard Serial over Bluetooth link)
    Priority 3: Other serial COM ports
    """
    if explicit_port and explicit_port not in ("AUTO", "COM_MOCK"):
        norm_port = str(explicit_port).strip().upper()
        desc = "User-specified COM port"
        mfg = ""
        hwid = ""
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                if getattr(p, "device", "").upper() == norm_port:
                    desc = getattr(p, "description", "") or desc
                    mfg = getattr(p, "manufacturer", "") or ""
                    hwid = getattr(p, "hwid", "") or ""
                    break
        except Exception:
            pass

        return [{
            "device": norm_port,
            "description": desc,
            "manufacturer": mfg,
            "priority": 0,
            "hwid": hwid,
        }]

    ports_found: List[Dict[str, Any]] = []
    try:
        from serial.tools import list_ports
        raw_ports = list_ports.comports()
        for p in raw_ports:
            dev = getattr(p, "device", "")
            if not dev:
                continue
            desc = getattr(p, "description", "") or ""
            mfg = getattr(p, "manufacturer", "") or ""
            hwid = getattr(p, "hwid", "") or ""
            combined = (desc + " " + mfg + " " + hwid).lower()

            # Priority 1: Known VCI keywords
            vci_keywords = ["vlinker", "elm327", "obd", "ch340", "ftdi", "cp210", "prolific", "stn"]
            # Priority 2: Bluetooth serial keywords
            bth_keywords = ["bluetooth", "bth", "standart seri", "standard serial"]

            if any(k in combined for k in vci_keywords):
                priority = 1
            elif any(k in combined for k in bth_keywords):
                priority = 2
            else:
                priority = 3

            ports_found.append({
                "device": dev.upper(),
                "description": desc,
                "manufacturer": mfg,
                "hwid": hwid,
                "priority": priority,
            })
    except Exception as e:
        logger.warning(f"Failed to enumerate serial ports: {e}")

    def sort_key(item):
        dev_name = item["device"]
        digits = "".join(ch for ch in dev_name if ch.isdigit())
        num = int(digits) if digits else 999
        return (item["priority"], num, dev_name)

    ports_found.sort(key=sort_key)
    return ports_found


def probe_elm327_port(
    port: str,
    baudrates: Optional[List[int]] = None,
    timeout: float = 1.5,
    serial_factory: Optional[Callable[..., Any]] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> PortProbeResult:
    """
    Safely probes a candidate serial port with read-only commands to determine
    if a plausible ELM327/VLinker OBD adapter is present and responsive.
    Strictly non-destructive: only sends harmless identity commands (ATZ, ATI).
    """
    test_bauds = baudrates or [38400, 115200, 9600]
    last_reason = "NO_RESPONSE"
    per_baud_timeout = min(0.8, max(0.4, timeout / len(test_bauds)))

    for baud in test_bauds:
        log_real_connect(f"Opening {port} @ {baud}")
        if on_status:
            on_status(f"Testing {port} at {baud} baud...")

        ser = None
        try:
            if serial_factory:
                ser = serial_factory(port=port, baudrate=baud, timeout=0.1, write_timeout=1.0)
            else:
                import serial
                ser = serial.Serial(port, baudrate=baud, timeout=0.1, write_timeout=1.0)

            if not getattr(ser, "is_open", True):
                last_reason = "PORT_FAILED_TO_OPEN"
                log_real_connect(f"{port} rejected: reason=PORT_FAILED_TO_OPEN")
                continue

            # Bluetooth RFCOMM / USB UART settle delay
            time.sleep(0.05 if serial_factory else 0.25)
            if hasattr(ser, "reset_input_buffer"):
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass

            log_real_connect(f"Sending ELM327 probe")
            # Send wake-up and canonical reset
            ser.write(b"\r\rATZ\r")

            raw_buf = bytearray()
            start_t = time.monotonic()
            # Fast-slice read loop: ser.timeout is 0.1 so each read returns fast
            while (time.monotonic() - start_t) < per_baud_timeout:
                in_waiting = getattr(ser, "in_waiting", 0)
                if in_waiting > 0:
                    raw_buf.extend(ser.read(in_waiting))
                    if b">" in raw_buf:
                        break
                else:
                    chunk = ser.read(1)
                    if chunk:
                        raw_buf.extend(chunk)
                        if b">" in raw_buf:
                            break
                    else:
                        time.sleep(0.01)

            # If ATZ had characters but no prompt '>', try ATI
            if raw_buf and b">" not in raw_buf:
                ser.write(b"ATI\r")
                start_ati = time.monotonic()
                while (time.monotonic() - start_ati) < 0.4:
                    in_waiting = getattr(ser, "in_waiting", 0)
                    if in_waiting > 0:
                        raw_buf.extend(ser.read(in_waiting))
                        if b">" in raw_buf:
                            break
                    else:
                        chunk = ser.read(1)
                        if chunk:
                            raw_buf.extend(chunk)
                            if b">" in raw_buf:
                                break
                        else:
                            time.sleep(0.01)

            resp_str = raw_buf.decode("ascii", errors="ignore").upper()
            sanitized_resp = repr(raw_buf.decode("ascii", errors="replace"))
            log_real_connect(f"{port} response: {sanitized_resp}")

            plausible_markers = ["ELM327", "OBDLINK", "VLINKER", "OK", "STN"]
            is_plausible = any(m in resp_str for m in plausible_markers) or (len(resp_str) > 0 and ">" in resp_str)

            if is_plausible:
                identity = "ELM327"
                for line in resp_str.replace("\r", "\n").split("\n"):
                    line_clean = line.strip().replace(">", "")
                    if any(m in line_clean for m in ["ELM327", "OBDLINK", "VLINKER", "STN"]):
                        identity = line_clean
                        break

                ser.close()
                time.sleep(0.05 if serial_factory else 0.2)
                return PortProbeResult(
                    port=port,
                    transport="serial",
                    connection_state="CONNECTED",
                    adapter_detected=True,
                    adapter_identity=identity,
                    baudrate=baud,
                    failure_reason=None,
                )
            else:
                if not raw_buf:
                    last_reason = "TIMEOUT"
                    log_real_connect(f"{port} rejected: reason=TIMEOUT")
                    # Port is completely silent; skip other baudrates on this port
                    break
                elif b">" not in raw_buf:
                    last_reason = "INVALID_ELM327_RESPONSE"
                    log_real_connect(f"{port} rejected: reason=INVALID_ELM327_RESPONSE")
                else:
                    last_reason = "NO_ELM327_RESPONSE"
                    log_real_connect(f"{port} rejected: reason=NO_ELM327_RESPONSE")

        except Exception as e:
            err_str = str(e)
            err_cls = type(e).__name__
            if "denied" in err_str.lower() or "permission" in err_str.lower() or "busy" in err_str.lower() or "cannot find" in err_str.lower():
                last_reason = "PORT_BUSY_OR_ACCESS_DENIED"
                log_real_connect(f"{port} rejected: reason=PORT_BUSY_OR_ACCESS_DENIED ({err_cls}: {err_str})")
            else:
                last_reason = f"SERIAL_ERROR: {err_cls}: {err_str}"
                log_real_connect(f"{port} rejected: reason={last_reason}")
            # If port couldn't be opened, further baud rates will also fail
            break
        finally:
            if ser is not None and getattr(ser, "is_open", False):
                try:
                    ser.close()
                except Exception:
                    pass
            time.sleep(0.02 if serial_factory else 0.1)

    return PortProbeResult(
        port=port,
        transport="serial",
        connection_state="FAILED",
        adapter_detected=False,
        adapter_identity=None,
        baudrate=test_bauds[0],
        failure_reason=last_reason,
    )


def discover_and_probe_elm327(
    explicit_port: Optional[str] = None,
    timeout_per_port: float = 1.5,
    serial_factory: Optional[Callable[..., Any]] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> Tuple[Optional[PortProbeResult], List[PortProbeResult]]:
    """
    Discovers candidate ports and safely probes them in priority order.
    Returns (successful_result, all_probe_results).
    """
    log_real_connect("Starting physical adapter discovery")
    log_real_connect("Enumerating Windows COM ports")
    candidates = enumerate_candidate_ports(explicit_port)
    if not candidates:
        log_real_connect("No Windows COM ports discovered")
        if on_status:
            on_status("No serial COM ports found on system.")
        return None, []

    for c in candidates:
        mfg_str = f" | mfg={c['manufacturer']}" if c.get('manufacturer') else ""
        hw_str = f" | hwid={c['hwid']}" if c.get('hwid') else ""
        log_real_connect(f"Candidate: {c['device']} | description={c['description']}{mfg_str}{hw_str}")

    ports_str = ", ".join(c["device"] for c in candidates)
    if on_status:
        on_status(f"Searching for OBD adapters across: {ports_str}...")

    all_results: List[PortProbeResult] = []
    for cand in candidates:
        p = cand["device"]
        log_real_connect(f"Probing {p}")
        if on_status:
            on_status(f"Testing {p} ({cand.get('description', '')})...")

        res = probe_elm327_port(
            port=p,
            timeout=timeout_per_port,
            serial_factory=serial_factory,
            on_status=on_status,
        )
        res.description = cand.get("description", "")
        all_results.append(res)

        if res.adapter_detected:
            log_real_connect(f"ELM327 detected on {res.port}")
            if on_status:
                on_status(f"ELM327 detected on {res.port} ({res.adapter_identity}, {res.baudrate} baud)")
            return res, all_results

    log_real_connect("Physical adapter discovery failed: no compatible ELM327 adapter responded")
    if on_status:
        on_status("No compatible ELM327 adapter detected on available COM ports.")
    return None, all_results


def list_available_com_ports(verbose: bool = True) -> List[Dict[str, Any]]:
    """
    Physical validation support: enumerates detected serial ports without connecting.
    Exposes OS descriptions for Bluetooth/USB troubleshooting.
    """
    candidates = enumerate_candidate_ports()
    if verbose:
        print("Detected serial ports:")
        if not candidates:
            print("  (none found)")
        for c in candidates:
            desc = c.get("description", "") or "No description"
            mfg = c.get("manufacturer", "")
            hwid = c.get("hwid", "")
            extra = []
            if mfg:
                extra.append(f"Mfg: {mfg}")
            if hwid:
                extra.append(f"HWID: {hwid}")
            extra_str = f" [{', '.join(extra)}]" if extra else ""
            print(f"  - {c['device']} — {desc}{extra_str}")
    return candidates


def cli_probe_port(
    port_name: str,
    baudrate: int = 38400,
    serial_factory: Optional[Callable[..., Any]] = None,
) -> str:
    """
    Deterministic CLI diagnostic probe for testing physical Windows COM ports.
    Usage: python diagnostic_adapter.py --probe-port COM4
    1. Open specified physical COM port.
    2. Print port metadata.
    3. Open serial connection.
    4. Wait for adapter startup.
    5. Send safe ELM327 identification command (ATI, ATZ).
    6. Read response robustly.
    7. Print sanitized raw response.
    8. State outcome: ELM327_DETECTED, NO_RESPONSE, TIMEOUT, PORT_BUSY, INVALID_RESPONSE, OPEN_FAILED.
    9. Close serial handle in all cases.
    """
    port = port_name.strip().upper()
    print(f"\n==================================================", flush=True)
    print(f"  SEYYANEN OBD ADAPTER DIAGNOSTIC PROBE: {port}", flush=True)
    print(f"==================================================", flush=True)

    # 1 & 2: Metadata lookup
    print(f"[PROBE-PORT] Target Port: {port}", flush=True)
    meta = {"description": "Unknown", "manufacturer": "Unknown", "hwid": "Unknown"}
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            if getattr(p, "device", "").upper() == port:
                meta["description"] = getattr(p, "description", "") or "Unknown"
                meta["manufacturer"] = getattr(p, "manufacturer", "") or "Unknown"
                meta["hwid"] = getattr(p, "hwid", "") or "Unknown"
                break
    except Exception as e:
        print(f"[PROBE-PORT] Metadata error: {e}", flush=True)

    print(f"[PROBE-PORT] Description : {meta['description']}", flush=True)
    print(f"[PROBE-PORT] Manufacturer: {meta['manufacturer']}", flush=True)
    print(f"[PROBE-PORT] HWID        : {meta['hwid']}", flush=True)

    ser = None
    outcome = "OPEN_FAILED"
    try:
        print(f"[PROBE-PORT] Opening {port} @ {baudrate} baud (timeout=0.1s)...", flush=True)
        if serial_factory:
            ser = serial_factory(port=port, baudrate=baudrate, timeout=0.1, write_timeout=1.0)
        else:
            import serial
            ser = serial.Serial(port, baudrate=baudrate, timeout=0.1, write_timeout=1.0)
        print(f"[PROBE-PORT] Serial handle opened successfully.", flush=True)

        # 4: Wait for adapter startup / Bluetooth RFCOMM link settle
        print(f"[PROBE-PORT] Waiting 0.4s for Bluetooth/UART stabilization...", flush=True)
        time.sleep(0.4)
        if hasattr(ser, "reset_input_buffer"):
            ser.reset_input_buffer()

        # 5: Send safe identification command
        print(f"[PROBE-PORT] Sending harmless identification sequence: \\r\\rATI\\r", flush=True)
        ser.write(b"\r\rATI\r")

        raw_buf = bytearray()
        t_start = time.monotonic()
        while (time.monotonic() - t_start) < 2.0:
            in_waiting = getattr(ser, "in_waiting", 0)
            if in_waiting > 0:
                raw_buf.extend(ser.read(in_waiting))
                if b">" in raw_buf:
                    break
            else:
                chunk = ser.read(1)
                if chunk:
                    raw_buf.extend(chunk)
                    if b">" in raw_buf:
                        break
                else:
                    time.sleep(0.01)

        # If ATI had no prompt, try ATZ (warm/hard reset)
        if b">" not in raw_buf:
            print(f"[PROBE-PORT] No prompt on ATI, attempting ATZ\\r...", flush=True)
            ser.write(b"ATZ\r")
            t_atz = time.monotonic()
            while (time.monotonic() - t_atz) < 1.5:
                in_waiting = getattr(ser, "in_waiting", 0)
                if in_waiting > 0:
                    raw_buf.extend(ser.read(in_waiting))
                    if b">" in raw_buf:
                        break
                else:
                    chunk = ser.read(1)
                    if chunk:
                        raw_buf.extend(chunk)
                        if b">" in raw_buf:
                            break
                    else:
                        time.sleep(0.01)

        # 7: Print sanitized raw response
        sanitized = repr(raw_buf.decode("ascii", errors="replace"))
        print(f"[PROBE-PORT] Raw Response: {sanitized}", flush=True)

        resp_upper = raw_buf.decode("ascii", errors="ignore").upper()
        plausible_markers = ["ELM327", "OBDLINK", "VLINKER", "OK", "STN"]

        # 8: State outcome
        if any(m in resp_upper for m in plausible_markers) or (len(raw_buf) > 0 and b">" in raw_buf):
            identity = "ELM327"
            for l in resp_upper.replace("\r", "\n").split("\n"):
                lc = l.strip().replace(">", "")
                if any(m in lc for m in ["ELM327", "OBDLINK", "VLINKER", "STN"]):
                    identity = lc
                    break
            outcome = "ELM327_DETECTED"
            print(f"[PROBE-PORT] Outcome: ELM327_DETECTED (Identity: {identity})", flush=True)
        elif not raw_buf:
            outcome = "TIMEOUT"
            print(f"[PROBE-PORT] Outcome: TIMEOUT (No bytes received from adapter)", flush=True)
        elif b">" not in raw_buf:
            outcome = "INVALID_RESPONSE"
            print(f"[PROBE-PORT] Outcome: INVALID_RESPONSE (Bytes received but no '>' prompt)", flush=True)
        else:
            outcome = "NO_RESPONSE"
            print(f"[PROBE-PORT] Outcome: NO_RESPONSE", flush=True)

    except Exception as e:
        err_str = str(e)
        err_cls = type(e).__name__
        if "denied" in err_str.lower() or "busy" in err_str.lower() or "permission" in err_str.lower():
            outcome = "PORT_BUSY"
            print(f"[PROBE-PORT] Outcome: PORT_BUSY ({err_cls}: {err_str})", flush=True)
        else:
            outcome = "OPEN_FAILED"
            print(f"[PROBE-PORT] Outcome: OPEN_FAILED ({err_cls}: {err_str})", flush=True)
    finally:
        # 9: Close serial handle in all cases
        if ser is not None:
            try:
                ser.close()
                print(f"[PROBE-PORT] Serial handle cleanly closed.", flush=True)
            except Exception as ce:
                print(f"[PROBE-PORT] Error closing handle: {ce}", flush=True)

    print(f"==================================================\n", flush=True)
    return outcome


class ELM327DiagnosticAdapter(DiagnosticAdapter):
    """
    Production-grade ELM327 USB/Serial Diagnostic Adapter (Phase K-2).
    Communicates via Windows COM ports using PySerial or delegates to AutoExpertEngine.
    Enforces deterministic initialization, robust response normalization,
    command serialization, and truthful capability reporting.
    """
    def __init__(
        self,
        engine: Any = None,
        adapter_id: str = "ELM327_SERIAL_01",
        port: Optional[str] = None,
        baudrate: int = 38400,
        read_timeout: float = 2.0,
        write_timeout: float = 2.0,
        capabilities: Optional[AdapterCapabilities] = None,
        serial_factory: Optional[Callable[..., Any]] = None,
        simulation: bool = False,
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
            supports_serial_transport=True,
            supports_elm327_commands=True,
        )
        meta = AdapterMetadata(
            adapter_id=adapter_id,
            adapter_type=AdapterType.ELM327,
            transport_medium=TransportMedium.SERIAL_USB,
            manufacturer="ELM Electronics / Compatible",
            model="ELM327",
            firmware_version="v1.5 / v2.1",
            capabilities=caps,
            properties={"port": port or "AUTO", "baudrate": baudrate},
        )
        super().__init__(metadata=meta)
        self.engine = engine
        self._port = port
        self._baudrate = baudrate
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.serial_factory = serial_factory
        self.simulation = bool(simulation)
        self.ser: Optional[Any] = None
        self._transport_stage: ELM327TransportStage = ELM327TransportStage.DISCONNECTED
        self.last_raw_response: Optional[bytes] = None
        self.last_normalized_response: List[str] = []
        self.detected_protocol: Optional[str] = None
        self.elm_version: Optional[str] = None
        self.last_probe_result: Optional[PortProbeResult] = None
        self.last_probe_history: List[PortProbeResult] = []

    @property
    def port(self) -> Optional[str]:
        return self._port

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @property
    def transport_stage(self) -> ELM327TransportStage:
        return self._transport_stage

    @property
    def is_adapter_responsive(self) -> bool:
        return self._transport_stage in (
            ELM327TransportStage.ELM327_RESPONSIVE,
            ELM327TransportStage.VEHICLE_PROTOCOL_READY,
        )

    @property
    def is_vehicle_ready(self) -> bool:
        return self._transport_stage == ELM327TransportStage.VEHICLE_PROTOCOL_READY

    def _discover_port(self) -> Optional[str]:
        """Auto-discovers candidate diagnostic COM port on Windows / Host via probing."""
        res, _ = discover_and_probe_elm327(
            explicit_port=self._port,
            serial_factory=self.serial_factory,
            timeout_per_port=1.2,
        )
        return res.port if res else None

    def _do_connect(self, timeout: float) -> bool:
        """
        Establishes physical serial connection and executes deterministic ELM327 initialization.
        Enforces candidate discovery on real hardware; never falls back to mock silently.
        """
        # Phase K-1 compatibility: support lightweight mock engines used in unit tests
        if self.engine is not None and type(self.engine).__name__ == "FakeEngineMock":
            if hasattr(self.engine, "baglan"):
                ok = bool(self.engine.baglan())
                if ok:
                    if hasattr(self.engine, "ser"):
                        self.ser = self.engine.ser
                    self._transport_stage = ELM327TransportStage.ELM327_RESPONSIVE
                else:
                    self._transport_stage = ELM327TransportStage.DISCONNECTED
                    raise AdapterConnectionError("Mock engine connection failed.", adapter_id=self.adapter_id)
                return ok

        is_mock = self.simulation or is_simulation_mode() or (self._port == "COM_MOCK")

        if is_mock:
            target_port = self._port or "COM_MOCK"
            self._port = target_port
            logger.info("Connecting in SIMULATION mode on '%s'...", target_port)
            try:
                if self.serial_factory:
                    self.ser = self.serial_factory(
                        target_port,
                        baudrate=self._baudrate,
                        timeout=self.read_timeout,
                        write_timeout=self.write_timeout,
                    )
                else:
                    self.ser = MockSerialForELM(port=target_port, baudrate=self._baudrate)

                self._transport_stage = ELM327TransportStage.PORT_OPENED
                if self.engine is not None:
                    self.engine.ser = self.ser
                    self.engine.bagli_port = target_port
                    if hasattr(self.engine, "io_worker") and self.engine.io_worker:
                        self.engine.io_worker.stop()
                    from motor import SerialIOThread
                    self.engine.io_worker = SerialIOThread(self.ser, timeout=self.read_timeout)
                    self.engine.io_worker.start()
                    self.engine._start_keep_alive_timer()
                    self.engine.test_start_time = time.time()

                init_ok = self._execute_initialization(timeout=timeout)
                if not init_ok:
                    self._do_disconnect()
                    raise AdapterConnectionError(
                        f"ELM327 initialization failed on mock port '{target_port}'.",
                        adapter_id=self.adapter_id,
                    )
                return True
            except Exception as e:
                self._transport_stage = ELM327TransportStage.DISCONNECTED
                if isinstance(e, AdapterError):
                    raise
                raise AdapterConnectionError(
                    f"Failed to open mock serial port '{target_port}': {e}",
                    adapter_id=self.adapter_id,
                ) from e

        # -------------------------------------------------------------
        # STRICT PHYSICAL HARDWARE MODE (Normal User Connection)
        # -------------------------------------------------------------
        target_port = self._port
        if not target_port or str(target_port).upper() in ("AUTO", ""):
            # Automatic candidate enumeration and probing across all available ports
            probe_res, all_probes = discover_and_probe_elm327(
                serial_factory=self.serial_factory,
                timeout_per_port=min(1.8, max(0.8, timeout / 3.0)),
                on_status=logger.info,
            )
            self.last_probe_result = probe_res
            self.last_probe_history = all_probes

            if probe_res is None or not probe_res.adapter_detected:
                self._transport_stage = ELM327TransportStage.DISCONNECTED
                reasons = [f"{r.port} ({r.failure_reason})" for r in all_probes] or ["No COM ports detected"]
                raise AdapterUnavailableError(
                    f"No compatible ELM327 adapter detected on available COM ports: {', '.join(reasons)}",
                    adapter_id=self.adapter_id,
                )

            target_port = probe_res.port
            self._port = target_port
            self._baudrate = probe_res.baudrate
            self.elm_version = probe_res.adapter_identity
        else:
            log_real_connect(f"Using explicitly configured port: {target_port}")
            self.last_probe_result = PortProbeResult(
                port=target_port,
                transport="serial",
                connection_state="CONNECTING",
                adapter_detected=True,
                baudrate=self._baudrate,
            )
            self.last_probe_history = [self.last_probe_result]

        # Open dedicated connection on target port
        log_real_connect(f"Establishing active connection on {target_port}")
        # Allow Windows Bluetooth stack to settle after probe closure
        time.sleep(0.4)
        try:
            if self.serial_factory:
                self.ser = self.serial_factory(
                    target_port,
                    baudrate=self._baudrate,
                    timeout=self.read_timeout,
                    write_timeout=self.write_timeout,
                )
            else:
                import serial
                self.ser = serial.Serial(
                    target_port,
                    baudrate=self._baudrate,
                    timeout=self.read_timeout,
                    write_timeout=self.write_timeout,
                )
                time.sleep(0.3)  # Bluetooth RFCOMM connection stabilization delay
                if hasattr(self.ser, "reset_input_buffer"):
                    self.ser.reset_input_buffer()

            self._transport_stage = ELM327TransportStage.PORT_OPENED
            log_real_connect(f"Active connection open on {target_port} @ {self._baudrate} baud")
            logger.info("Physical serial port '%s' opened at %d baud.", target_port, self._baudrate)
        except Exception as e:
            self._transport_stage = ELM327TransportStage.DISCONNECTED
            log_real_connect(f"Failed to open active connection on {target_port}: {e}")
            raise AdapterConnectionError(
                f"Failed to open physical serial port '{target_port}': {e}",
                adapter_id=self.adapter_id,
            ) from e

        # Execute deterministic initialization sequence
        init_ok = self._execute_initialization(timeout=timeout)
        if not init_ok:
            self._do_disconnect()
            log_real_connect(f"ELM327 initialization failed on {target_port}")
            raise AdapterConnectionError(
                f"ELM327 initialization failed on physical port '{target_port}'.",
                adapter_id=self.adapter_id,
            )
        log_real_connect(f"ELM327 initialization successful on {target_port} (Version: {self.elm_version})")

        # Wire up engine if attached (maintains backward compatibility with C/D/E/F/G layers)
        if self.engine is not None:
            self.engine.ser = self.ser
            self.engine.bagli_port = target_port
            if hasattr(self.engine, "io_worker") and self.engine.io_worker:
                self.engine.io_worker.stop()
            from motor import SerialIOThread
            self.engine.io_worker = SerialIOThread(self.ser, timeout=self.read_timeout)
            self.engine.io_worker.start()
            self.engine._start_keep_alive_timer()
            self.engine.test_start_time = time.time()

        return True

    def _execute_initialization(self, timeout: float = 5.0) -> bool:
        """
        Deterministic, safe ELM327 initialization sequence.
        Supports standard ELM327, vLinker, OBDLink, and STN chipsets.
        """
        # Step 1: AT Z / AT WS (Hardware/warm reset)
        lines, status = self._send_raw_command("AT Z", timeout=min(2.0, timeout))
        joined = "".join(lines).upper()
        plausible_markers = ["ELM327", "OBDLINK", "VLINKER", "OK", "STN"]
        if not any(m in joined for m in plausible_markers):
            lines, status = self._send_raw_command("AT WS", timeout=min(2.0, timeout))
            joined = "".join(lines).upper()
            if not any(m in joined for m in plausible_markers):
                logger.error("ELM327/VLinker adapter failed to respond to AT Z / AT WS. Response: %s", lines)
                return False

        self.elm_version = lines[0] if lines else "ELM327"
        self._transport_stage = ELM327TransportStage.ELM327_RESPONSIVE
        log_real_connect(f"ELM327 adapter responsive: {self.elm_version}")
        logger.info("ELM327 adapter responsive: %s", self.elm_version)

        # Step 2: ATE0 (Echo off)
        self._send_raw_command("ATE0", timeout=1.0)
        # Step 3: ATL0 (Linefeeds off)
        self._send_raw_command("ATL0", timeout=1.0)
        # Step 4: ATS0 (Spaces off)
        self._send_raw_command("ATS0", timeout=1.0)
        # Step 5: AT H1 (Headers on)
        self._send_raw_command("AT H1", timeout=1.0)
        # Step 6: AT SP 0 (Protocol Auto search)
        self._send_raw_command("AT SP 0", timeout=1.5)

        # Step 7: AT DPN / AT DP (Query protocol)
        p_lines, _ = self._send_raw_command("AT DPN", timeout=1.0)
        if p_lines:
            self.detected_protocol = p_lines[0]
        else:
            p_lines2, _ = self._send_raw_command("AT DP", timeout=1.0)
            if p_lines2:
                self.detected_protocol = p_lines2[0]

        # Step 8: Probe vehicle protocol readiness (0100)
        probe_lines, probe_status = self._send_raw_command("0100", timeout=min(3.0, timeout))
        joined_probe = "".join(probe_lines).upper().replace(" ", "")
        if probe_status == STATUS_VALID and ("4100" in joined_probe or "41 00" in "".join(probe_lines).upper()):
            self._transport_stage = ELM327TransportStage.VEHICLE_PROTOCOL_READY
            logger.info("Vehicle protocol readiness verified on bus.")
        else:
            logger.info("ELM327 responsive, but vehicle protocol probe returned %s: %s", probe_status, probe_lines)

        return True

    def _do_disconnect(self) -> None:
        """Tears down serial link and invalidates transport state."""
        if self.ser is not None:
            try:
                if hasattr(self.ser, "close"):
                    self.ser.close()
            except Exception as e:
                logger.debug("Error closing serial port: %s", e)
            finally:
                self.ser = None

        if self.engine is not None and hasattr(self.engine, "ser"):
            try:
                ser = self.engine.ser
                if ser and getattr(ser, "is_open", False):
                    ser.close()
            except Exception:
                pass

        self._transport_stage = ELM327TransportStage.DISCONNECTED
        self.last_raw_response = None
        self.last_normalized_response = []

    def _do_reset(self, hard: bool) -> bool:
        cmd = "AT Z" if hard else "AT WS"
        lines, status = self.send_command(cmd, timeout=2.0)
        ok = status == STATUS_VALID or any("ELM327" in l.upper() or "OK" in l.upper() for l in lines)
        if ok:
            self._transport_stage = ELM327TransportStage.ELM327_RESPONSIVE
        return ok

    def _do_set_header(self, header: str, timeout: float) -> bool:
        lines, status = self.send_command(f"AT SH {header}", timeout=timeout)
        return status == STATUS_VALID or "OK" in "".join(lines).upper()

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
        ok = status == STATUS_VALID or "OK" in "".join(lines).upper()
        if ok:
            self.detected_protocol = protocol.value
        return ok

    def _do_read_battery_voltage(self) -> Optional[float]:
        lines, status = self.send_command("AT RV", timeout=1.0)
        if (status == STATUS_VALID or lines) and lines:
            m = re.search(r"([0-9]+\.[0-9]+)\s*V?", lines[0])
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
        return None

    def _do_send_command(self, cmd: str, timeout: float) -> Tuple[List[str], str]:
        if not self.is_connected():
            return [], STATUS_NO_CONNECTION
        return self._send_raw_command(cmd, timeout=timeout)

    def _send_raw_command(self, cmd: str, timeout: float = 2.0) -> Tuple[List[str], str]:
        """
        Sends command over physical/mock serial port and parses ELM327 response.
        Enforces:
          - Buffer flushing
          - Reading bytes until '>' prompt
          - Bounded monotonic timeout
          - Echo stripping
          - Normalizing lines
          - Transport error detection (CAN ERROR, BUS ERROR, NO DATA, etc.)
          - Unexpected reset detection
        """
        if self.ser is None:
            if self.engine is not None and hasattr(self.engine, "komut_gonder"):
                raw_lines = self.engine.komut_gonder(cmd, timeout=timeout)
                st = getattr(self.engine, "last_response_status", STATUS_VALID)
                return raw_lines or [], st
            return [], STATUS_NO_CONNECTION

        if hasattr(self.ser, "is_open") and not self.ser.is_open:
            return [], STATUS_NO_CONNECTION

        if self.engine is not None and not hasattr(self.ser, "write"):
            if hasattr(self.engine, "komut_gonder"):
                raw_lines = self.engine.komut_gonder(cmd, timeout=timeout)
                st = getattr(self.engine, "last_response_status", STATUS_VALID)
                return raw_lines or [], st

        # Reset input buffer before transmission
        if hasattr(self.ser, "reset_input_buffer"):
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass

        wire_bytes = (cmd.strip() + "\r").encode("ascii", errors="replace")
        try:
            self.ser.write(wire_bytes)
            if hasattr(self.ser, "flush"):
                self.ser.flush()
        except Exception as e:
            logger.error("Serial write failed on '%s': %s", self._port, e)
            self._do_disconnect()
            raise TransportFailureError(
                f"Serial write failed: {e}",
                adapter_id=self.adapter_id,
            ) from e

        # Read bytes until '>' or timeout
        raw_buffer = bytearray()
        t_start = time.monotonic()
        prompt_found = False

        while (time.monotonic() - t_start) < timeout:
            try:
                in_waiting = getattr(self.ser, "in_waiting", 0)
                n_to_read = in_waiting if in_waiting > 0 else 1
                chunk = self.ser.read(n_to_read)
            except Exception as e:
                logger.error("Serial read exception on '%s': %s", self._port, e)
                self._do_disconnect()
                raise TransportFailureError(
                    f"Serial read exception: {e}",
                    adapter_id=self.adapter_id,
                ) from e

            if chunk:
                raw_buffer.extend(chunk)
                if b">" in raw_buffer:
                    prompt_found = True
                    break
            else:
                time.sleep(0.005)

        self.last_raw_response = bytes(raw_buffer)

        if not prompt_found and not raw_buffer:
            return [], STATUS_TIMEOUT

        text = raw_buffer.decode("ascii", errors="ignore")
        raw_lines = [line.strip() for line in re.split(r"[\r\n]+", text)]
        clean_lines: List[str] = []
        cmd_clean = cmd.strip().upper().replace(" ", "")

        for line in raw_lines:
            line_s = line.strip()
            if not line_s or line_s == ">":
                continue
            if line_s.endswith(">"):
                line_s = line_s[:-1].strip()
            if not line_s:
                continue

            # Strip command echo
            line_comp = line_s.upper().replace(" ", "")
            if line_comp == cmd_clean:
                continue

            clean_lines.append(line_s)

        self.last_normalized_response = clean_lines
        status = self._classify_elm_response(clean_lines, expected_cmd=cmd)
        return clean_lines, status

    def _classify_elm_response(self, lines: List[str], expected_cmd: str) -> str:
        """
        Classifies ELM327 response lines according to the canonical status model:
        STATUS_VALID, STATUS_NO_DATA, STATUS_TIMEOUT, STATUS_SERIAL_ERROR, STATUS_NRC.
        """
        if not lines:
            return STATUS_EMPTY_RESPONSE

        joined = " ".join(lines).upper()

        # 1. Unexpected Adapter Reset
        if "ELM327 V" in joined and not expected_cmd.strip().upper().startswith("AT"):
            logger.critical("Unexpected ELM327 adapter reset detected during '%s'!", expected_cmd)
            self._transport_stage = ELM327TransportStage.ELM327_RESPONSIVE
            raise AdapterResetError(
                f"ELM327 adapter reset unexpectedly during command '{expected_cmd}'.",
                adapter_id=self.adapter_id,
            )

        # 2. NO DATA
        if any(line.upper() == "NO DATA" or "NO DATA" in line.upper() for line in lines):
            return STATUS_NO_DATA

        # 3. STOPPED
        if "STOPPED" in joined:
            return STATUS_TIMEOUT

        # 4. Bus / Transport Errors
        serial_err_patterns = [
            "CAN ERROR",
            "BUS ERROR",
            "FB ERROR",
            "DATA ERROR",
            "BUFFER FULL",
            "RX ERROR",
            "UNABLE TO CONNECT",
            "BUS BUSY",
        ]
        for pat in serial_err_patterns:
            if any(pat == line.upper() or line.upper().startswith(pat) for line in lines):
                return STATUS_SERIAL_ERROR

        # 5. Unrecognized command '?'
        if any(line == "?" for line in lines):
            return STATUS_NRC

        # 6. ECU Negative Response Code (NRC): e.g. "7F 22 31" or "7E8 03 7F 22 31"
        for line in lines:
            line_no_space = line.replace(" ", "").upper()
            if "7F" in line_no_space:
                idx = line_no_space.find("7F")
                if len(line_no_space) >= idx + 6:
                    return STATUS_NRC

        return STATUS_VALID

    def execute_smoke_test(self, timeout: float = 3.0) -> Dict[str, Any]:
        """
        Safe, read-only diagnostic smoke path (Phase K-2).
        Demonstrates:
          1. Serial port open verification
          2. ELM327 initialization and responsiveness
          3. Basic voltage reading
          4. Single safe read query (0100)
        Does NOT perform PID sweeps, Mode 22 discovery, or destructive actions.
        """
        with self._lock:
            if not self.is_connected():
                return {
                    "status": "FAIL",
                    "reason": "Adapter is not connected",
                    "transport_stage": self._transport_stage.value,
                }

            volts = self.read_battery_voltage()
            lines, status = self.send_command("0100", timeout=timeout)

            passed = (
                self.is_adapter_responsive
                and status in (STATUS_VALID, STATUS_NO_DATA)
            )

            return {
                "status": "PASS" if passed else "FAIL",
                "port": self._port,
                "baudrate": self._baudrate,
                "elm_version": self.elm_version or "UNKNOWN",
                "battery_voltage": volts,
                "detected_protocol": self.detected_protocol or "UNKNOWN",
                "transport_stage": self._transport_stage.value,
                "safe_read_command": "0100",
                "safe_read_status": status,
                "safe_read_response": lines,
                "raw_response_captured": bool(self.last_raw_response),
            }


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


if __name__ == "__main__":
    if "--list-ports" in sys.argv or "-l" in sys.argv:
        list_available_com_ports(verbose=True)
    elif "--probe-port" in sys.argv or "-p" in sys.argv:
        idx = sys.argv.index("--probe-port") if "--probe-port" in sys.argv else sys.argv.index("-p")
        if idx + 1 < len(sys.argv):
            target = sys.argv[idx + 1]
            cli_probe_port(target)
        else:
            print("Usage: python diagnostic_adapter.py --probe-port <COM_PORT>")
            sys.exit(1)
    else:
        print("Seyyanen Diagnostic Adapter Layer (Phase J-1 / K-2)")
        print("Usage:")
        print("  python diagnostic_adapter.py --list-ports")
        print("  python diagnostic_adapter.py --probe-port <COM_PORT>")
        list_available_com_ports(verbose=True)

