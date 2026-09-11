"""
advanced_ecu_services.py - Advanced ECU Services Foundation (Phase G-1)
========================================================================
Establishes the protocol-aware Advanced ECU Services foundation for the
Seyyanen automotive diagnostic platform.

Features:
  - Structured request (AdvancedServiceRequest) & response (AdvancedServiceResponse)
  - Strict read-only safety classification & policy (Zero destructive operations)
  - DiagnosticSessionContext & ECUTargetContext foundations
  - ServiceDescriptor & ServiceRegistry with pre-registered standard services
  - DiagnosticTransactionManager over existing AutoExpertEngine/SerialIOThread
  - Raw response preservation, positive matching, and explicit NRC classification
  - Thread-safe, bounded history and bounded, policy-driven retries
"""

import collections
import enum
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Canonical Status Constants (harmonized with motor.py)
STATUS_VALID = "VALID"
STATUS_NRC = "NRC"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_NO_CONNECTION = "NO_CONNECTION"
STATUS_WORKER_DOWN = "WORKER_DOWN"
STATUS_SERIAL_ERROR = "SERIAL_ERROR"
STATUS_NO_DATA = "NO_DATA"
STATUS_DID_MISMATCH = "DID_MISMATCH"
STATUS_EMPTY_RESPONSE = "EMPTY_RESPONSE"
STATUS_TRANSACTION_BLOCKED = "TRANSACTION_BLOCKED"
STATUS_TRANSACTION_CANCELLED = "TRANSACTION_CANCELLED"
STATUS_UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"
STATUS_RESPONSE_MISMATCH = "RESPONSE_MISMATCH"
STATUS_PARSE_ERROR = "PARSE_ERROR"

# Canonical NRC Taxonomy (harmonized with motor.py NRC_MAP)
CANONICAL_NRC_MAP: Dict[str, str] = {
    "10": "General Reject",
    "11": "Service Not Supported",
    "12": "Sub-Function Not Supported",
    "13": "Incorrect Message Length/Format",
    "21": "Busy Repeat Request",
    "22": "Conditions Not Correct",
    "24": "Request Sequence Error",
    "31": "Request Out of Range",
    "33": "Security Access Denied",
    "35": "Invalid Key",
    "36": "Exceeded Number Of Attempts",
    "37": "Required Time Delay Not Expired",
    "72": "General Programming Failure",
    "78": "Response Pending",
    "7E": "Sub-Function Not Supported In Active Session",
    "7F": "Service Not Supported In Active Session",
}



# =====================================================================
# 1. SAFETY CLASSIFICATION & POLICY
# =====================================================================

class ServiceSafetyClassification(str, enum.Enum):
    """
    Defines safety classification for ECU diagnostic services.
    Phase G-1 operates in strict READ_ONLY mode.
    """
    READ_ONLY = "READ_ONLY"
    POTENTIALLY_DESTRUCTIVE = "POTENTIALLY_DESTRUCTIVE"
    WRITE = "WRITE"
    ACTUATION = "ACTUATION"
    PROGRAMMING = "PROGRAMMING"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
    BLOCKED = "BLOCKED"


class ServiceSafetyPolicy:
    """
    Authoritative safety policy engine for Advanced ECU Services.
    Enforces that Phase G-1 permits ONLY READ_ONLY operations.
    """
    def __init__(self, allow_non_readonly: bool = False):
        self._allow_non_readonly = allow_non_readonly

    def validate_request(self, request: "AdvancedServiceRequest") -> Tuple[bool, Optional[str]]:
        """
        Validates whether a service request is safe to execute.
        Rejects any write, destructive, programming, or blocked service.
        """
        # Hard invariant: Mode 04 / Clear DTCs and destructive operations are universally blocked
        norm_sid = (request.service_id or "").strip().upper()
        if norm_sid in ("04", "4", "14"):
            return False, f"Mode {norm_sid} (Clear DTC / Reset) is strictly prohibited in G-1."

        # Hard invariant: Write, actuator, programming, download/upload, security bypass strictly prohibited
        if norm_sid in ("2E", "27", "2F", "34", "35", "36", "37", "3D"):
            if not self._allow_non_readonly:
                return False, f"Service 0x{norm_sid} (write/programming/actuation/security) is strictly prohibited."

        if request.safety_classification != ServiceSafetyClassification.READ_ONLY:
            if not self._allow_non_readonly:
                return False, (
                    f"Service '{request.service_id}' rejected by safety policy: "
                    f"classification '{request.safety_classification.value}' is not READ_ONLY."
                )


        return True, None


# =====================================================================
# 2. SESSION & TARGET CONTEXTS
# =====================================================================

class SessionType(str, enum.Enum):
    DEFAULT = "DEFAULT"                  # 0x01
    PROGRAMMING = "PROGRAMMING"          # 0x02
    EXTENDED = "EXTENDED"                # 0x03
    SAFETY_SYSTEM = "SAFETY_SYSTEM"      # 0x04


@dataclass
class DiagnosticSessionContext:
    """
    Represents ECU diagnostic session state.
    In G-1, this is descriptive and does NOT trigger automated transitions.
    """
    session_type: SessionType = SessionType.DEFAULT
    header: str = "7E0"
    is_active: bool = True
    established_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 300.0)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class ECUTargetContext:
    """
    Represents an ECU target context.
    In G-1, focuses on the primary diagnostic ECU; extensible to multi-ECU in G-4.
    """
    logical_name: str = "PRIMARY_ECU"
    ecu_type: str = "ENGINE"
    header: str = "7E0"
    protocol: str = "CAN_11BIT_500K"
    current_session: SessionType = SessionType.DEFAULT
    supported_capabilities: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# 3. RETRY POLICY
# =====================================================================

@dataclass
class ServiceRetryPolicy:
    """
    Configurable, bounded, policy-driven retry policy.
    Distinguishes transient transport errors and retryable NRCs from permanent failures.
    """
    max_attempts: int = 1
    backoff_sec: float = 0.1
    retry_on_timeout: bool = False
    retryable_nrcs: Tuple[str, ...] = ("21",)  # 0x21: Busy Repeat Request

    def should_retry(self, attempt: int, status: str, nrc: Optional[str] = None) -> bool:
        if attempt >= self.max_attempts:
            return False
        if status == STATUS_TIMEOUT and self.retry_on_timeout:
            return True
        if status == STATUS_NRC and nrc in self.retryable_nrcs:
            return True
        return False


# =====================================================================
# 4. REQUEST & RESPONSE MODELS
# =====================================================================

@dataclass
class AdvancedServiceRequest:
    """
    Structured representation of an Advanced ECU Service Request.
    Generic and protocol-aware (applicable to Mode 01, 09, 21, 22, 3E, etc.).
    """
    service_id: str                          # e.g. "22", "09", "10", "3E", "01"
    subfunction: Optional[str] = None        # e.g. "03" for session 10 03
    payload: str = ""                        # e.g. "1640" (DID) or hex payload
    header: Optional[str] = None             # Target CAN header (e.g. "7E0")
    target_ecu: str = "PRIMARY_ECU"
    expected_response_service_id: Optional[str] = None
    expected_response_subfunction: Optional[str] = None
    timeout: float = 2.0
    retry_policy: ServiceRetryPolicy = field(default_factory=ServiceRetryPolicy)
    session_requirement: SessionType = SessionType.DEFAULT
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    transaction_id: str = ""
    created_at: float = field(default_factory=time.monotonic)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.service_id = self.service_id.strip().upper()
        if self.subfunction:
            self.subfunction = self.subfunction.strip().upper()
        if self.payload:
            self.payload = self.payload.strip().replace(" ", "").upper()
        if self.header:
            self.header = self.header.strip().upper()

        # Derive expected positive response service ID if not provided (service_id + 0x40)
        if not self.expected_response_service_id:
            try:
                sid_int = int(self.service_id, 16)
                self.expected_response_service_id = f"{sid_int + 0x40:02X}"
            except ValueError:
                self.expected_response_service_id = None

    def to_command_string(self) -> str:
        """Constructs the raw OBD/UDS command string for serial transmission."""
        parts = [self.service_id]
        if self.subfunction:
            parts.append(self.subfunction)
        if self.payload:
            parts.append(self.payload)
        return "".join(parts)


@dataclass
class AdvancedServiceResponse:
    """
    Structured response and evidence container for an ECU transaction.
    CRITICAL: Preserves raw lines, raw bytes, and unparsed data.
    """
    transaction_id: str
    request: AdvancedServiceRequest
    is_positive: bool = False
    response_service_id: Optional[str] = None
    response_subfunction: Optional[str] = None
    raw_lines: List[str] = field(default_factory=list)
    raw_bytes: bytes = b""
    raw_payload_hex: Optional[str] = None
    parsed_payload: Optional[Any] = None
    target_ecu: str = "PRIMARY_ECU"
    header: Optional[str] = None
    status: str = STATUS_VALID
    nrc: Optional[str] = None
    nrc_description: Optional[str] = None
    is_nrc: bool = False
    is_timeout: bool = False
    is_transport_error: bool = False
    request_timestamp: float = 0.0
    response_timestamp: float = 0.0
    elapsed_time: float = 0.0
    session_context: Optional[DiagnosticSessionContext] = None
    parsing_status: str = "NO_PARSER"        # "PARSED", "NO_PARSER", "PARSER_ERROR", "UNPARSED"
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "service_id": self.request.service_id,
            "target_ecu": self.target_ecu,
            "header": self.header,
            "is_positive": self.is_positive,
            "status": self.status,
            "nrc": self.nrc,
            "nrc_description": self.nrc_description,
            "raw_lines": self.raw_lines,
            "raw_payload_hex": self.raw_payload_hex,
            "parsed_payload": self.parsed_payload,
            "parsing_status": self.parsing_status,
            "elapsed_time": self.elapsed_time,
            "error_message": self.error_message,
        }


# =====================================================================
# 5. SERVICE DESCRIPTOR & REGISTRY
# =====================================================================

@dataclass
class ServiceDescriptor:
    """Metadata describing a diagnostic service and its operational contracts."""
    service_id: str
    name: str
    supported_subfunctions: List[str] = field(default_factory=list)
    positive_response_id: Optional[str] = None
    default_timeout: float = 2.0
    default_retry_policy: ServiceRetryPolicy = field(default_factory=ServiceRetryPolicy)
    safety_classification: ServiceSafetyClassification = ServiceSafetyClassification.READ_ONLY
    session_requirement: SessionType = SessionType.DEFAULT
    parser: Optional[Callable[[bytes, str], Any]] = None
    description: str = ""

    def __post_init__(self):
        self.service_id = self.service_id.strip().upper()
        if not self.positive_response_id:
            try:
                sid_int = int(self.service_id, 16)
                self.positive_response_id = f"{sid_int + 0x40:02X}"
            except ValueError:
                pass


class ServiceRegistry:
    """
    Registry for diagnostic service descriptors.
    Pre-configured with standard read-only services; rejects or blocks destructive ones.
    """
    def __init__(self):
        self._services: Dict[str, ServiceDescriptor] = {}
        self._register_standard_services()

    def register(self, descriptor: ServiceDescriptor) -> None:
        self._services[descriptor.service_id.upper()] = descriptor

    def get(self, service_id: str) -> Optional[ServiceDescriptor]:
        return self._services.get(service_id.strip().upper())

    def list_services(self) -> List[ServiceDescriptor]:
        return list(self._services.values())

    def _register_standard_services(self) -> None:
        # Standard Read-Only Services
        self.register(ServiceDescriptor(
            service_id="01",
            name="ReadCurrentPowertrainDiagnosticData",
            description="OBD Mode 01 Live Sensor Stream",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="41",
            default_timeout=1.0,
        ))
        self.register(ServiceDescriptor(
            service_id="03",
            name="ReadDiagnosticTroubleCodes",
            description="OBD Mode 03 Confirmed Diagnostic Trouble Codes",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="43",
            default_timeout=2.0,
        ))
        self.register(ServiceDescriptor(
            service_id="09",
            name="ReadVehicleInformation",
            description="OBD Mode 09 Vehicle Identification and Calibration",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="49",
            default_timeout=2.0,
        ))
        self.register(ServiceDescriptor(
            service_id="10",
            name="DiagnosticSessionControl",
            description="UDS Service 0x10 Diagnostic Session Control (Read/Report)",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="50",
            default_timeout=2.0,
        ))
        self.register(ServiceDescriptor(
            service_id="21",
            name="ReadDataByLocalIdentifier",
            description="KWP2000 Service 0x21 Read Data By Local ID",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="61",
            default_timeout=2.0,
        ))
        self.register(ServiceDescriptor(
            service_id="22",
            name="ReadDataByIdentifier",
            description="UDS Service 0x22 Read Data By Identifier",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="62",
            default_timeout=2.0,
        ))
        self.register(ServiceDescriptor(
            service_id="3E",
            name="TesterPresent",
            description="UDS Service 0x3E Tester Present Keep-Alive",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            positive_response_id="7E",
            default_timeout=1.0,
        ))

        # Explicitly Blocked / Destructive Services (Safety Guardrail)
        self.register(ServiceDescriptor(
            service_id="04",
            name="ClearDiagnosticInformation",
            description="OBD Mode 04 Clear DTCs / Reset Emission Data (BLOCKED)",
            safety_classification=ServiceSafetyClassification.POTENTIALLY_DESTRUCTIVE,
            positive_response_id="44",
        ))
        self.register(ServiceDescriptor(
            service_id="14",
            name="ClearDiagnosticInformationUDS",
            description="UDS Service 0x14 Clear Diagnostic Information (BLOCKED)",
            safety_classification=ServiceSafetyClassification.POTENTIALLY_DESTRUCTIVE,
            positive_response_id="54",
        ))
        self.register(ServiceDescriptor(
            service_id="2E",
            name="WriteDataByIdentifier",
            description="UDS Service 0x2E Write Data By Identifier (BLOCKED)",
            safety_classification=ServiceSafetyClassification.WRITE,
            positive_response_id="6E",
        ))
        self.register(ServiceDescriptor(
            service_id="27",
            name="SecurityAccess",
            description="UDS Service 0x27 Security Access (BLOCKED)",
            safety_classification=ServiceSafetyClassification.SECURITY_SENSITIVE,
            positive_response_id="67",
        ))
        self.register(ServiceDescriptor(
            service_id="2F",
            name="InputOutputControlByIdentifier",
            description="UDS Service 0x2F Actuation / Output Control (BLOCKED)",
            safety_classification=ServiceSafetyClassification.ACTUATION,
            positive_response_id="6F",
        ))
        self.register(ServiceDescriptor(
            service_id="34",
            name="RequestDownload",
            description="UDS Service 0x34 Request Download (PROGRAMMING/BLOCKED)",
            safety_classification=ServiceSafetyClassification.PROGRAMMING,
            positive_response_id="74",
        ))
        self.register(ServiceDescriptor(
            service_id="36",
            name="TransferData",
            description="UDS Service 0x36 Transfer Data (PROGRAMMING/BLOCKED)",
            safety_classification=ServiceSafetyClassification.PROGRAMMING,
            positive_response_id="76",
        ))
        self.register(ServiceDescriptor(
            service_id="37",
            name="RequestTransferExit",
            description="UDS Service 0x37 Request Transfer Exit (PROGRAMMING/BLOCKED)",
            safety_classification=ServiceSafetyClassification.PROGRAMMING,
            positive_response_id="77",
        ))



# =====================================================================
# 6. TRANSPORT ADAPTER
# =====================================================================

class ITransportAdapter:
    """Interface for physical or simulated diagnostic transport."""
    def send_command(self, cmd: str, timeout: float = 1.0) -> Tuple[List[str], str]:
        raise NotImplementedError

    def get_current_header(self) -> str:
        raise NotImplementedError

    def set_header(self, header: str, timeout: float = 1.0) -> bool:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError


class EngineTransportAdapter(ITransportAdapter):
    """
    Authoritative transport adapter wrapping AutoExpertEngine.
    Reuses existing SerialIOThread and priority queue without duplicate workers.
    """
    def __init__(self, engine: Any):
        self.engine = engine

    def send_command(self, cmd: str, timeout: float = 1.0) -> Tuple[List[str], str]:
        if not self.engine:
            return [], STATUS_NO_CONNECTION
        raw_lines = self.engine.komut_gonder(cmd, timeout=timeout)
        status = getattr(self.engine, "last_response_status", STATUS_VALID)
        return raw_lines or [], status

    def get_current_header(self) -> str:
        if self.engine and hasattr(self.engine, "current_header"):
            return getattr(self.engine, "current_header", "7DF")
        return "7DF"

    def set_header(self, header: str, timeout: float = 1.0) -> bool:
        if not self.engine:
            return False
        header = header.strip().upper()
        self.engine.komut_gonder(f"AT SH {header}", timeout=timeout)
        self.engine.current_header = header
        return True

    def is_connected(self) -> bool:
        if not self.engine or not hasattr(self.engine, "ser"):
            return False
        ser = self.engine.ser
        return bool(ser and getattr(ser, "is_open", False))


# =====================================================================
# 7. DIAGNOSTIC TRANSACTION MANAGER
# =====================================================================

class DiagnosticTransactionManager:
    """
    Thread-safe transaction manager for executing Advanced ECU Service Requests.
    Enforces safety policies, manages headers with guaranteed restoration,
    preserves raw responses, and correlates positive/negative responses deterministically.
    """
    def __init__(
        self,
        transport: ITransportAdapter,
        registry: Optional[ServiceRegistry] = None,
        safety_policy: Optional[ServiceSafetyPolicy] = None,
        history_maxlen: int = 100,
    ):
        self.transport = transport
        self.registry = registry or ServiceRegistry()
        self.safety_policy = safety_policy or ServiceSafetyPolicy(allow_non_readonly=False)
        self._history_maxlen = history_maxlen

        self._lock = threading.RLock()
        self._tx_counter = 0
        self._cancelled_transactions: Set[str] = set()
        self._active_transactions: Set[str] = set()
        self._history: collections.deque = collections.deque(maxlen=history_maxlen)
        self._ecu_context = ECUTargetContext()
        self._session_context = DiagnosticSessionContext()

    @property
    def session_context(self) -> DiagnosticSessionContext:
        return self._session_context

    @property
    def ecu_context(self) -> ECUTargetContext:
        return self._ecu_context

    def generate_transaction_id(self) -> str:

        with self._lock:
            self._tx_counter += 1
            return f"TXN-{int(time.time())}-{self._tx_counter:04d}"

    def build_request(
        self,
        service_id: str,
        payload: str = "",
        subfunction: Optional[str] = None,
        header: Optional[str] = None,
        target_ecu: str = "PRIMARY_ECU",
        timeout: Optional[float] = None,
        retry_policy: Optional[ServiceRetryPolicy] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AdvancedServiceRequest:
        """Helper to construct an AdvancedServiceRequest leveraging the ServiceRegistry."""
        service_id = service_id.strip().upper()
        desc = self.registry.get(service_id)

        effective_timeout = timeout if timeout is not None else (desc.default_timeout if desc else 2.0)
        effective_retry = retry_policy or (desc.default_retry_policy if desc else ServiceRetryPolicy())
        effective_safety = desc.safety_classification if desc else ServiceSafetyClassification.READ_ONLY
        expected_pos = desc.positive_response_id if desc else None
        session_req = desc.session_requirement if desc else SessionType.DEFAULT

        return AdvancedServiceRequest(
            service_id=service_id,
            subfunction=subfunction,
            payload=payload,
            header=header or (self._ecu_context.header if self._ecu_context else "7E0"),
            target_ecu=target_ecu,
            expected_response_service_id=expected_pos,
            expected_response_subfunction=subfunction,
            timeout=effective_timeout,
            retry_policy=effective_retry,
            session_requirement=session_req,
            safety_classification=effective_safety,
            transaction_id=self.generate_transaction_id(),
            metadata=metadata or {},
        )

    def cancel_transaction(self, transaction_id: str) -> bool:
        """Cancels a transaction before execution or signals early cancellation."""
        with self._lock:
            self._cancelled_transactions.add(transaction_id)
            return True

    def execute_request(self, request: AdvancedServiceRequest) -> AdvancedServiceResponse:
        """
        Executes an advanced ECU service request through the transport layer.
        Thread-safe, bounded, policy-driven, and preserves all raw response data.
        """
        if not request.transaction_id:
            request.transaction_id = self.generate_transaction_id()

        start_wall = time.time()
        start_mono = time.monotonic()

        # 1. Check early cancellation
        with self._lock:
            if request.transaction_id in self._cancelled_transactions:
                res = AdvancedServiceResponse(
                    transaction_id=request.transaction_id,
                    request=request,
                    status=STATUS_TRANSACTION_CANCELLED,
                    request_timestamp=start_wall,
                    response_timestamp=time.time(),
                    elapsed_time=round(time.monotonic() - start_mono, 4),
                    error_message="Transaction was cancelled before execution.",
                )
                self._record_result(res)
                return res
            self._active_transactions.add(request.transaction_id)

        # 2. Safety policy pre-check (Fail-closed before wire)
        safe, reason = self.safety_policy.validate_request(request)
        if not safe:
            with self._lock:
                self._active_transactions.discard(request.transaction_id)
            res = AdvancedServiceResponse(
                transaction_id=request.transaction_id,
                request=request,
                status=STATUS_TRANSACTION_BLOCKED,
                request_timestamp=start_wall,
                response_timestamp=time.time(),
                elapsed_time=round(time.monotonic() - start_mono, 4),
                error_message=reason or "Blocked by safety policy.",
            )
            self._record_result(res)
            return res

        # 3. Serialize physical transmission through lock
        with self._lock:
            try:
                # Check cancellation again after acquiring lock
                if request.transaction_id in self._cancelled_transactions:
                    res = AdvancedServiceResponse(
                        transaction_id=request.transaction_id,
                        request=request,
                        status=STATUS_TRANSACTION_CANCELLED,
                        request_timestamp=start_wall,
                        response_timestamp=time.time(),
                        elapsed_time=round(time.monotonic() - start_mono, 4),
                        error_message="Transaction was cancelled while waiting for execution lock.",
                    )
                    return res

                # Header management & restoration
                initial_header = self.transport.get_current_header()
                target_header = request.header.strip().upper() if request.header else initial_header
                switched_header = False

                if target_header and target_header != initial_header:
                    self.transport.set_header(target_header, timeout=1.0)
                    switched_header = True

                try:
                    cmd_str = request.to_command_string()
                    attempt = 0
                    last_raw_lines: List[str] = []
                    last_transport_status = STATUS_VALID

                    while attempt < request.retry_policy.max_attempts:
                        attempt += 1
                        if request.transaction_id in self._cancelled_transactions:
                            last_transport_status = STATUS_TRANSACTION_CANCELLED
                            break

                        raw_lines, trans_status = self.transport.send_command(cmd_str, timeout=request.timeout)
                        last_raw_lines = raw_lines
                        last_transport_status = trans_status

                        # Analyze for immediate retry decision
                        nrc_code = self._extract_nrc(raw_lines, request.service_id)
                        if nrc_code:
                            last_transport_status = STATUS_NRC

                        if request.retry_policy.should_retry(attempt, last_transport_status, nrc_code):
                            time.sleep(request.retry_policy.backoff_sec)
                            continue
                        break

                    # Construct and process the result
                    res = self._process_transport_response(
                        request=request,
                        raw_lines=last_raw_lines,
                        transport_status=last_transport_status,
                        start_wall=start_wall,
                        start_mono=start_mono,
                        target_header=target_header,
                    )
                    return res

                finally:
                    # Guaranteed header restoration
                    if switched_header and self.transport.get_current_header() != initial_header:
                        self.transport.set_header(initial_header, timeout=1.0)

            finally:
                self._active_transactions.discard(request.transaction_id)
                self._cancelled_transactions.discard(request.transaction_id)

    def _process_transport_response(
        self,
        request: AdvancedServiceRequest,
        raw_lines: List[str],
        transport_status: str,
        start_wall: float,
        start_mono: float,
        target_header: str,
    ) -> AdvancedServiceResponse:
        """Processes and validates raw transport output into an AdvancedServiceResponse."""
        end_wall = time.time()
        elapsed = round(time.monotonic() - start_mono, 4)

        # Base response object (preserving raw evidence unconditionally)
        res = AdvancedServiceResponse(
            transaction_id=request.transaction_id,
            request=request,
            target_ecu=request.target_ecu,
            header=target_header,
            raw_lines=list(raw_lines),
            request_timestamp=start_wall,
            response_timestamp=end_wall,
            elapsed_time=elapsed,
            session_context=self._session_context,
            status=transport_status,
        )

        # 1. Handle Transport-level errors
        if transport_status == STATUS_TRANSACTION_CANCELLED:
            res.error_message = "Transaction cancelled."
            self._record_result(res)
            return res

        if transport_status in (STATUS_TIMEOUT, STATUS_NO_CONNECTION, STATUS_WORKER_DOWN, STATUS_SERIAL_ERROR):
            res.is_transport_error = True
            res.is_timeout = (transport_status == STATUS_TIMEOUT)
            res.error_message = f"Transport error: {transport_status}"
            self._record_result(res)
            return res

        if transport_status in (STATUS_NO_DATA, STATUS_EMPTY_RESPONSE) or not raw_lines:
            res.status = transport_status if transport_status != STATUS_VALID else STATUS_NO_DATA
            res.error_message = "ECU returned NO DATA or empty response."
            self._record_result(res)
            return res

        # 2. Check for UDS Negative Response (NRC 7F)
        nrc_code, nrc_sid = self._extract_nrc_and_sid(raw_lines, request.service_id)
        if nrc_code:
            res.is_positive = False
            res.is_nrc = True
            res.status = STATUS_NRC
            res.nrc = nrc_code
            res.response_service_id = "7F"
            res.nrc_description = CANONICAL_NRC_MAP.get(nrc_code, f"Negative Response 0x{nrc_code}")
            res.error_message = f"ECU Rejected with NRC 0x{nrc_code} ({res.nrc_description})"
            self._record_result(res)
            return res

        # 3. Assemble and extract contiguous payload hex
        reassembled_hex = self._reassemble_payload(raw_lines)
        res.raw_payload_hex = reassembled_hex

        try:
            res.raw_bytes = bytes.fromhex(reassembled_hex) if reassembled_hex else b""
        except ValueError:
            res.raw_bytes = b""

        # 4. Positive Response Matching
        expected_pos_sid = request.expected_response_service_id
        if not expected_pos_sid:
            try:
                expected_pos_sid = f"{int(request.service_id, 16) + 0x40:02X}"
            except ValueError:
                expected_pos_sid = None

        if not reassembled_hex:
            res.status = STATUS_EMPTY_RESPONSE
            res.error_message = "No payload received."
            self._record_result(res)
            return res

        # Verify response starts with positive response service identifier
        if expected_pos_sid and not reassembled_hex.startswith(expected_pos_sid):
            # Check if it was malformed, unexpected or mismatched
            if expected_pos_sid in reassembled_hex:
                res.status = STATUS_DID_MISMATCH
                res.error_message = f"Expected positive SID {expected_pos_sid} found, but not at frame start."
            else:
                res.status = STATUS_UNEXPECTED_RESPONSE
                res.error_message = f"Expected positive SID {expected_pos_sid}, received: {reassembled_hex[:8]}"
            self._record_result(res)
            return res

        # Check subfunction or DID match if applicable
        expected_prefix = expected_pos_sid
        if request.subfunction:
            expected_prefix += request.subfunction
        if request.service_id == "22" and request.payload:
            # Mode 22 echoes the 2-byte DID (e.g. 62 16 40)
            expected_prefix += request.payload

        if not reassembled_hex.startswith(expected_prefix):
            res.status = STATUS_RESPONSE_MISMATCH
            res.error_message = f"Response does not echo expected subfunction/DID prefix '{expected_prefix}'."
            self._record_result(res)
            return res

        # Positive match verified!
        res.is_positive = True
        res.status = STATUS_VALID
        res.response_service_id = expected_pos_sid
        res.response_subfunction = request.subfunction

        # Extract useful data bytes after prefix
        useful_hex = reassembled_hex[len(expected_prefix):]
        try:
            useful_bytes = bytes.fromhex(useful_hex) if useful_hex else b""
        except ValueError:
            res.is_positive = False
            res.status = STATUS_PARSE_ERROR
            res.error_message = f"Malformed non-hex payload received: '{useful_hex}'"
            self._record_result(res)
            return res

        # 5. Optional Parsing through ServiceRegistry descriptor
        desc = self.registry.get(request.service_id)
        if desc and desc.parser:
            try:
                res.parsed_payload = desc.parser(useful_bytes, useful_hex)
                res.parsing_status = "PARSED"
            except Exception as e:
                logging.warning(f"DiagnosticTransactionManager: Parser error for {request.service_id}: {e}")
                res.parsing_status = STATUS_PARSE_ERROR
                res.error_message = f"Parser exception: {e}"
        else:
            res.parsing_status = "NO_PARSER"
            res.parsed_payload = None

        self._record_result(res)
        return res

    def _extract_nrc_and_sid(self, raw_lines: List[str], expected_sid: str) -> Tuple[Optional[str], Optional[str]]:
        """Extracts NRC code and rejected SID from raw lines."""
        for line in raw_lines:
            clean = line.replace(" ", "").upper()
            # Look for 7F <SID> <NRC>
            match = re.search(r"7F([0-9A-F]{2})([0-9A-F]{2})", clean)
            if match:
                sid = match.group(1)
                nrc = match.group(2)
                return nrc, sid
        return None, None

    def _extract_nrc(self, raw_lines: List[str], expected_sid: str) -> Optional[str]:
        nrc, _ = self._extract_nrc_and_sid(raw_lines, expected_sid)
        return nrc

    def _reassemble_payload(self, raw_lines: List[str]) -> str:
        """
        Reassembles ISO-TP / OBD raw lines into a contiguous uppercase hex string.
        Strips CAN headers (7E8, 7E9, etc.) and ISO-TP sequence markers cleanly.
        """
        if not raw_lines:
            return ""

        # Filter out ELM327 prompts or status tokens
        raw_valid = [
            l.strip().upper() for l in raw_lines
            if l.strip() and not l.strip().startswith((">", "OK", "STOPPED", "SEARCHING", "BUS"))
        ]

        # Deduplicate consecutive identical lines (e.g. duplicate frames from adapter echo)
        valid_lines = []
        for l in raw_valid:
            if not valid_lines or l != valid_lines[-1]:
                valid_lines.append(l)

        if not valid_lines:
            return ""

        # Case 1: Single line response
        if len(valid_lines) == 1:
            clean = valid_lines[0].replace(" ", "")
            # Strip standard CAN diagnostic headers (7E8..7EF)
            for hdr in ("7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF", "7DF"):
                if clean.startswith(hdr):
                    clean = clean[len(hdr):]
                    break
            # Strip single-frame length byte if present (e.g. 7E8 03 41 0C 1A -> 03 41 0C 1A)
            if len(clean) >= 4:
                try:
                    pci_len = int(clean[:2], 16)
                    # If PCI length fits within remaining byte count, extract exactly pci_len bytes (stripping padding)
                    if 0 < pci_len * 2 <= len(clean[2:]):
                        clean = clean[2 : 2 + pci_len * 2]
                except ValueError:
                    pass
            return clean

        # Case 2: Multi-frame ISO-TP response
        # Lines typically look like: "7E8 10 0C 62 16 41 01 02", "7E8 21 03 04 05 06 07 08", "7E8 22 09"
        combined_payload = []
        for line in valid_lines:
            tokens = line.split()
            if not tokens:
                continue
            # If first token is CAN header (7E8 etc), skip it
            if tokens[0] in ("7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF"):
                tokens = tokens[1:]

            if not tokens:
                continue

            first_byte = tokens[0]
            if len(first_byte) == 2:
                # First Frame (1x xx)
                if first_byte.startswith("1"):
                    # tokens[0]=10, tokens[1]=0C (length), remainder is data
                    tokens = tokens[2:]
                # Consecutive Frame (2x)
                elif first_byte.startswith("2"):
                    # tokens[0]=21, remainder is data
                    tokens = tokens[1:]
                # Single Frame (0x)
                elif first_byte.startswith("0"):
                    tokens = tokens[1:]

            combined_payload.extend(tokens)

        return "".join(combined_payload).replace(" ", "").upper()

    def _record_result(self, response: AdvancedServiceResponse) -> None:
        """Stores the response in bounded history."""
        with self._lock:
            self._history.append(response)

    def get_transaction(self, transaction_id: str) -> Optional[AdvancedServiceResponse]:
        with self._lock:
            for item in self._history:
                if item.transaction_id == transaction_id:
                    return item
            return None

    def get_transaction_history(self, limit: Optional[int] = None) -> List[AdvancedServiceResponse]:
        with self._lock:
            items = list(self._history)
            if limit is not None and limit > 0:
                return items[-limit:]
            return items

    def get_active_transactions(self) -> List[str]:
        with self._lock:
            return list(self._active_transactions)

    def reset_history(self) -> None:
        with self._lock:
            self._history.clear()

    def get_ecu_context(self) -> ECUTargetContext:
        with self._lock:
            return self._ecu_context

    def get_session_context(self) -> DiagnosticSessionContext:
        with self._lock:
            return self._session_context

    def set_session_context(self, context: DiagnosticSessionContext) -> None:
        with self._lock:
            self._session_context = context

    def classify_service(self, service_id: str) -> ServiceSafetyClassification:
        desc = self.registry.get(service_id)
        if desc:
            return desc.safety_classification
        return ServiceSafetyClassification.READ_ONLY
