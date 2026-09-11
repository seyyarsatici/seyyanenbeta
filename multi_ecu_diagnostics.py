# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase G-4: Multi-ECU Diagnostics
=============================================================================
This module implements Phase G-4 of the Seyyanen diagnostic architecture.
It expands Seyyanen from single-ECU diagnostics into a controlled, robust,
multi-ECU diagnostic system.

Features:
  - Structured ECU Target Model with explicit Discovery & Capability States
    (EXPECTED, DETECTED, VERIFIED_REACHABLE, UNSUPPORTED, UNKNOWN).
  - Multi-ECU Vehicle Context representing multiple addressable ECUs.
  - Multi-ECU Transaction Routing with CAN header management, guaranteed
    restoration, and cross-ECU response contamination rejection.
  - Serialized Acquisition Scheduling over physical transport with bounded
    retries, rate limiting, and per-ECU failure isolation.
  - Per-ECU Circuit Breaker preventing offline ECUs from starving active ECUs.
  - Multi-ECU DTC Acquisition with ECU-specific identity (F-4 compatible).
  - Multi-ECU Data Acquisition preserving accurate asynchronous timestamps
    and canonical signal naming (ECU:IDENTIFIER:FIELD).
  - Multi-ECU Scan Result & Health Reporting with coverage analysis.
  - Direct conversion to Phase G-3 DiagnosticDataSet for downstream analytics.

Strict Architectural Invariants:
  - READ-ONLY: Prohibits Mode 04, Service 0x14, 0x2E, 0x2F, 0x34, 0x36, 0x27.
  - ZERO CAUSAL GRAPH: Vehicle-wide causal graphs belong strictly to G-5.
  - ZERO AUTOMATED WORKFLOWS: Automated guided procedures belong to Phase H.
  - OFFLINE / DETERMINISTIC: Zero external network or LLM dependency.
=============================================================================
"""

from __future__ import annotations

import collections
import enum
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np

# Reusable quality and status constants from Phase C / G-1 / G-2 / G-3
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
    ITransportAdapter,
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    ServiceRetryPolicy,
    SessionType,
    STATUS_TRANSACTION_BLOCKED,
    STATUS_TRANSACTION_CANCELLED,
    STATUS_UNEXPECTED_RESPONSE,
    STATUS_RESPONSE_MISMATCH,
    STATUS_PARSE_ERROR,
    CANONICAL_NRC_MAP,
)
from extended_did import (
    ApplicabilityResult,
    ByteOrder,
    DataDecoder,
    DataProvenance,
    DataType,
    DecodedField,
    DefinitionTrustLevel,
    DiagnosticDataDefinition,
    DiagnosticDefinitionRegistry,
    FieldDefinition,
    IdentifierNamespace,
    StructuredDiagnosticEvidence,
    VehicleApplicability,
    VehicleContext,
)
from live_dtc_lifecycle import (
    DTCObservationSnapshot,
    DTC_REGEX,
)
from advanced_fault_analysis import (
    DataSourceType,
    DiagnosticDataSet,
    DTCRecord,
    SignalQuality,
    TimeSeriesSignal,
)

logger = logging.getLogger("seyyanen.multi_ecu")


# =====================================================================
# 1. TAXONOMY & ENUMERATIONS
# =====================================================================

class ECUTargetType(str, enum.Enum):
    """Functional classification of an electronic control unit."""
    ENGINE = "ENGINE"                      # ECM / PCM
    TRANSMISSION = "TRANSMISSION"          # TCM
    BRAKES = "BRAKES"                      # ABS / ESP / ESC
    AIRBAG = "AIRBAG"                      # SRS / RCM
    BODY = "BODY"                          # BCM / CEM
    STEERING = "STEERING"                  # EPS / PSCM
    INSTRUMENT_CLUSTER = "INSTRUMENT_CLUSTER" # IC / IPC
    CLIMATE = "CLIMATE"                    # HVAC / EATC
    GATEWAY = "GATEWAY"                    # GW / CGW
    GENERIC = "GENERIC"


class ECUDiscoveryState(str, enum.Enum):
    """
    Discovery and existence verification state of an ECU target.
    Prevents assuming an ECU exists merely because it is common on a vehicle.
    """
    EXPECTED = "EXPECTED"                  # Specified in vehicle configuration/profile
    DETECTED = "DETECTED"                  # Observed via broadcast or probe activity
    VERIFIED_REACHABLE = "VERIFIED_REACHABLE" # Positively responded to diagnostic command
    UNSUPPORTED = "UNSUPPORTED"            # Probed and explicitly rejected or inactive
    UNKNOWN = "UNKNOWN"                    # Unverified / not yet probed


class ECUCapabilityState(str, enum.Enum):
    """Operational capability state of an ECU target."""
    UNKNOWN = "UNKNOWN"
    DISCOVERED = "DISCOVERED"
    REACHABLE = "REACHABLE"
    CAPABILITY_KNOWN = "CAPABILITY_KNOWN"
    LIMITED = "LIMITED"
    UNSUPPORTED = "UNSUPPORTED"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


class ECUHealthState(str, enum.Enum):
    """
    Health and communication status of an ECU.
    Strictly distinguishes communication status from vehicle physical DTC faults.
    """
    CONNECTED = "CONNECTED"                # Active and responding normally
    DEGRADED = "DEGRADED"                  # Intermittent timeouts or high error rate
    UNREACHABLE = "UNREACHABLE"            # Consistently timing out or no connection
    UNSUPPORTED = "UNSUPPORTED"            # Module not present or rejected
    ERROR = "ERROR"                        # Transport or severe protocol error
    UNKNOWN = "UNKNOWN"


class ScanScope(str, enum.Enum):
    """Scope of a diagnostic vehicle scan."""
    FULL_VEHICLE = "FULL_VEHICLE"
    PARTIAL = "PARTIAL"
    SINGLE_ECU = "SINGLE_ECU"


# =====================================================================
# 2. ECU TARGET & MULTI-ECU CONTEXT MODELS
# =====================================================================

@dataclass
class ECUTarget:
    """
    Authoritative representation of an addressable ECU target on the vehicle network.
    Maintains independent addressing, capabilities, sessions, and failure isolation.
    """
    logical_id: str                              # e.g. "ECM", "TCM", "ABS", "SRS"
    ecu_type: ECUTargetType                      # e.g. ECUTargetType.ENGINE
    human_readable_name: str = ""                # e.g. "Engine Control Module"
    module_family: Optional[str] = None          # e.g. "DELPHI_MT80", "BOSCH_ME7"
    network_bus: str = "CAN_HS"                  # e.g. "CAN_HS", "CAN_MS", "K_LINE"
    request_header: str = "7E0"                  # Transmission CAN ID (e.g. "7E0")
    response_header: str = "7E8"                 # Expected Receive CAN ID (e.g. "7E8")
    protocol: str = "ISO_15765_4_CAN_11BIT"
    discovery_state: ECUDiscoveryState = ECUDiscoveryState.UNKNOWN
    capability_state: ECUCapabilityState = ECUCapabilityState.UNKNOWN
    health_state: ECUHealthState = ECUHealthState.UNKNOWN
    current_session: SessionType = SessionType.DEFAULT
    supported_services: Set[str] = field(default_factory=set)
    supported_identifiers: Set[str] = field(default_factory=set)
    unsupported_identifiers: Set[str] = field(default_factory=set)
    failure_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    circuit_breaker_open: bool = False
    priority: int = 100                          # Higher number = higher priority
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.logical_id = self.logical_id.strip().upper()
        self.request_header = self.request_header.strip().upper()
        self.response_header = self.response_header.strip().upper()
        if not self.human_readable_name:
            self.human_readable_name = f"{self.logical_id} ({self.ecu_type.value})"

    def mark_success(self) -> None:
        """Records a successful transaction and resets consecutive failures."""
        self.success_count += 1
        self.consecutive_failures = 0
        self.circuit_breaker_open = False
        self.discovery_state = ECUDiscoveryState.VERIFIED_REACHABLE
        self.health_state = ECUHealthState.CONNECTED

    def mark_failure(self, max_consecutive_failures: int = 3) -> None:
        """Records a failed transaction and evaluates circuit breaker status."""
        self.failure_count += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= max_consecutive_failures:
            self.circuit_breaker_open = True
            self.health_state = ECUHealthState.UNREACHABLE
        elif self.consecutive_failures > 1:
            self.health_state = ECUHealthState.DEGRADED

    def reset_state(self) -> None:
        """Resets dynamic tracking counters and circuit breakers."""
        self.failure_count = 0
        self.success_count = 0
        self.consecutive_failures = 0
        self.circuit_breaker_open = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logical_id": self.logical_id,
            "ecu_type": self.ecu_type.value,
            "human_readable_name": self.human_readable_name,
            "module_family": self.module_family,
            "network_bus": self.network_bus,
            "request_header": self.request_header,
            "response_header": self.response_header,
            "protocol": self.protocol,
            "discovery_state": self.discovery_state.value,
            "capability_state": self.capability_state.value,
            "health_state": self.health_state.value,
            "current_session": self.current_session.value,
            "supported_services": sorted(list(self.supported_services)),
            "supported_identifiers": sorted(list(self.supported_identifiers)),
            "unsupported_identifiers": sorted(list(self.unsupported_identifiers)),
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "circuit_breaker_open": self.circuit_breaker_open,
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }


@dataclass
class MultiECUVehicleContext:
    """
    Multi-ECU vehicle context containing vehicle hardware profile and
    an inventory of addressable ECU targets.
    """
    base_context: Optional[VehicleContext] = None
    ecus: Dict[str, ECUTarget] = field(default_factory=dict)
    gateway_routing: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_ecu(self, ecu: ECUTarget) -> None:
        self.ecus[ecu.logical_id.upper()] = ecu

    def get_ecu(self, logical_id: str) -> Optional[ECUTarget]:
        return self.ecus.get(logical_id.strip().upper())

    def list_ecus(self) -> List[ECUTarget]:
        return list(self.ecus.values())

    def get_reachable_ecus(self) -> List[ECUTarget]:
        return [e for e in self.ecus.values() if e.discovery_state == ECUDiscoveryState.VERIFIED_REACHABLE]

    def get_expected_ecus(self) -> List[ECUTarget]:
        return [e for e in self.ecus.values() if e.discovery_state in (ECUDiscoveryState.EXPECTED, ECUDiscoveryState.VERIFIED_REACHABLE)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_profile": self.base_context.to_dict() if (self.base_context and hasattr(self.base_context, "to_dict")) else None,
            "ecus": {k: v.to_dict() for k, v in self.ecus.items()},
            "gateway_routing": self.gateway_routing,
            "metadata": dict(self.metadata),
        }


# =====================================================================
# 3. MULTI-ECU TRANSACTION ROUTING & RESPONSE VALIDATION
# =====================================================================

class MultiECURouter:
    """
    Routes diagnostic transactions to specific ECU targets.
    Manages transport headers, serializes physical transmission,
    and enforces strict response-to-target matching to prevent
    cross-ECU contamination.
    """
    def __init__(self, transaction_manager: DiagnosticTransactionManager):
        self.transaction_manager = transaction_manager
        self._lock = threading.RLock()

    def execute_for_target(
        self,
        target: ECUTarget,
        service_id: str,
        payload: str = "",
        subfunction: Optional[str] = None,
        timeout: Optional[float] = None,
        retry_policy: Optional[ServiceRetryPolicy] = None,
        session_requirement: SessionType = SessionType.DEFAULT,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AdvancedServiceResponse:
        """
        Executes a diagnostic service request targeted explicitly to an ECU.
        Guarantees CAN header switching and restoration, and checks response matching.
        """
        # 1. Circuit breaker check
        if target.circuit_breaker_open:
            req = self.transaction_manager.build_request(
                service_id=service_id,
                payload=payload,
                subfunction=subfunction,
                header=target.request_header,
                target_ecu=target.logical_id,
                timeout=timeout,
                retry_policy=retry_policy,
                metadata=metadata,
            )
            return AdvancedServiceResponse(
                transaction_id=req.transaction_id,
                request=req,
                target_ecu=target.logical_id,
                header=target.request_header,
                status=STATUS_TIMEOUT,
                error_message=f"Circuit breaker is OPEN for ECU {target.logical_id}; skipping request.",
            )

        # 2. Session requirement check (safe fail-closed: do not silently switch sessions)
        if session_requirement != SessionType.DEFAULT and target.current_session != session_requirement:
            req = self.transaction_manager.build_request(
                service_id=service_id,
                payload=payload,
                subfunction=subfunction,
                header=target.request_header,
                target_ecu=target.logical_id,
                timeout=timeout,
                retry_policy=retry_policy,
                metadata=metadata,
            )
            return AdvancedServiceResponse(
                transaction_id=req.transaction_id,
                request=req,
                target_ecu=target.logical_id,
                header=target.request_header,
                status=STATUS_TRANSACTION_BLOCKED,
                error_message=f"ECU {target.logical_id} requires session {session_requirement.value}, but active session is {target.current_session.value}.",
            )

        # 3. Build validated request with explicit ECU target and header
        req = self.transaction_manager.build_request(
            service_id=service_id,
            payload=payload,
            subfunction=subfunction,
            header=target.request_header,
            target_ecu=target.logical_id,
            timeout=timeout,
            retry_policy=retry_policy,
            metadata=metadata,
        )

        # 4. Execute transaction through G-1 transaction manager (thread-safe, header restored)
        with self._lock:
            resp = self.transaction_manager.execute_request(req)

        # 5. Validate ECU Response Matching (prevent cross-ECU response contamination)
        # Check if the response actually originated from this ECU's response CAN ID
        if resp.is_positive and resp.raw_lines:
            wrong_ecu_detected = False
            for line in resp.raw_lines:
                clean_l = line.strip().upper().replace(" ", "")
                # If the line starts with a 3-digit CAN ID that does NOT match target.response_header:
                for cand_hdr in ("7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF"):
                    if clean_l.startswith(cand_hdr) and cand_hdr != target.response_header:
                        wrong_ecu_detected = True
                        break
                if wrong_ecu_detected:
                    break

            if wrong_ecu_detected:
                resp.is_positive = False
                resp.status = STATUS_RESPONSE_MISMATCH
                resp.error_message = (
                    f"Response CAN header mismatch for {target.logical_id}: "
                    f"expected {target.response_header} but received response from another ECU."
                )
                target.mark_failure()
                return resp

        # 6. Update target health & statistics
        if resp.is_positive and resp.status == STATUS_VALID:
            target.mark_success()
        elif resp.status in (STATUS_TIMEOUT, STATUS_SERIAL_ERROR, STATUS_NO_CONNECTION):
            target.mark_failure()
        elif resp.status == STATUS_NRC:
            # An NRC means the ECU IS reachable and responding, but rejected the specific service/DID
            target.discovery_state = ECUDiscoveryState.VERIFIED_REACHABLE
            target.health_state = ECUHealthState.CONNECTED

        return resp


# =====================================================================
# 4. CONTROLLED ACQUISITION SCHEDULER & FAILURE ISOLATION
# =====================================================================

@dataclass
class ScheduledECUTask:
    """Unit of work for the multi-ECU scheduler."""
    target: ECUTarget
    service_id: str
    payload: str = ""
    subfunction: Optional[str] = None
    timeout: Optional[float] = None
    retry_policy: Optional[ServiceRetryPolicy] = None
    session_requirement: SessionType = SessionType.DEFAULT
    callback: Optional[Callable[[AdvancedServiceResponse], None]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: int = 100


class MultiECUScheduler:
    """
    Serializes diagnostic transactions over the physical transport layer
    while managing logical multi-ECU concurrency, prioritization, bounded retries,
    per-ECU failure isolation, and circuit breakers.
    """
    def __init__(self, router: MultiECURouter, max_retries: int = 2):
        self.router = router
        self.max_retries = max_retries
        self._lock = threading.RLock()
        self._is_cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self._is_cancelled = True

    def reset_cancellation(self) -> None:
        with self._lock:
            self._is_cancelled = False

    def execute_batch(
        self,
        tasks: List[ScheduledECUTask],
        abort_on_ecu_failure: bool = False,
    ) -> List[Tuple[ScheduledECUTask, AdvancedServiceResponse]]:
        """
        Executes a sequence of multi-ECU tasks sorted by priority.
        Ensures that a failure on ECU A (e.g. ABS timeout) never invalidates
        or aborts execution on other ECUs unless abort_on_ecu_failure is True.
        """
        # Sort tasks descending by priority
        sorted_tasks = sorted(tasks, key=lambda t: t.priority, reverse=True)
        results: List[Tuple[ScheduledECUTask, AdvancedServiceResponse]] = []

        for task in sorted_tasks:
            with self._lock:
                if self._is_cancelled:
                    # Cancelled task
                    req = self.router.transaction_manager.build_request(
                        service_id=task.service_id,
                        payload=task.payload,
                        subfunction=task.subfunction,
                        header=task.target.request_header,
                        target_ecu=task.target.logical_id,
                    )
                    resp = AdvancedServiceResponse(
                        transaction_id=req.transaction_id,
                        request=req,
                        target_ecu=task.target.logical_id,
                        header=task.target.request_header,
                        status=STATUS_TRANSACTION_CANCELLED,
                        error_message="Batch execution was cancelled.",
                    )
                    results.append((task, resp))
                    if task.callback:
                        task.callback(resp)
                    continue

            # Execute transaction for target
            resp = self.router.execute_for_target(
                target=task.target,
                service_id=task.service_id,
                payload=task.payload,
                subfunction=task.subfunction,
                timeout=task.timeout,
                retry_policy=task.retry_policy,
                session_requirement=task.session_requirement,
                metadata=task.metadata,
            )

            results.append((task, resp))
            if task.callback:
                try:
                    task.callback(resp)
                except Exception as cb_err:
                    logger.warning("Error in task callback for %s: %s", task.target.logical_id, cb_err)

            if abort_on_ecu_failure and not resp.is_positive:
                break

        return results


# =====================================================================
# 5. MULTI-ECU DATA & DTC MODELS
# =====================================================================

@dataclass
class MultiECUDTCRecord:
    """
    Representation of an active or stored DTC tied to a specific ECU target.
    Prevents merging identical DTC codes across different ECUs.
    """
    ecu_id: str                                  # e.g. "ECM", "TCM", "ABS"
    code: str                                    # e.g. "P0300", "P0700", "C0035"
    status: str = "CONFIRMED"
    description: Optional[str] = None
    raw_response: Any = None
    timestamp: float = field(default_factory=time.time)
    transaction_id: str = ""
    freeze_frame: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ecu_id": self.ecu_id,
            "code": self.code,
            "status": self.status,
            "description": self.description,
            "timestamp": self.timestamp,
            "transaction_id": self.transaction_id,
            "freeze_frame": dict(self.freeze_frame),
        }

    def to_f4_snapshot(self) -> DTCObservationSnapshot:
        """Converts to an F-4 compatible DTCObservationSnapshot."""
        return DTCObservationSnapshot(
            timestamp=self.timestamp,
            status=STATUS_VALID,
            codes=[self.code],
            source=self.ecu_id,
            raw_response=self.raw_response,
        )


@dataclass
class MultiECUDataSample:
    """
    Normalized multi-ECU data sample preserving exact timestamps,
    canonical signal identity, and full provenance.
    """
    ecu_id: str                                  # e.g. "ECM"
    identifier: str                              # e.g. "05", "1640"
    service_id: str                              # e.g. "01", "22"
    field_name: str                              # e.g. "ECT", "Speed"
    canonical_name: str                          # e.g. "ECM:05:ECT"
    decoded_value: Any                           # Physically scaled measurement
    raw_value: Any                               # Raw numeric/bytes
    unit: str                                    # e.g. "°C", "km/h"
    quality: str = QUALITY_GOOD
    request_timestamp: float = 0.0
    response_timestamp: float = 0.0
    elapsed_time: float = 0.0
    transaction_id: str = ""
    definition_id: str = ""
    trust_level: str = "STANDARD"
    is_valid: bool = True
    error_message: Optional[str] = None
    provenance: Optional[DataProvenance] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ecu_id": self.ecu_id,
            "identifier": self.identifier,
            "service_id": self.service_id,
            "field_name": self.field_name,
            "canonical_name": self.canonical_name,
            "decoded_value": self.decoded_value,
            "raw_value": self.raw_value,
            "unit": self.unit,
            "quality": self.quality,
            "request_timestamp": self.request_timestamp,
            "response_timestamp": self.response_timestamp,
            "elapsed_time": self.elapsed_time,
            "transaction_id": self.transaction_id,
            "definition_id": self.definition_id,
            "trust_level": self.trust_level,
            "is_valid": self.is_valid,
            "error_message": self.error_message,
        }


@dataclass
class ECUScanRecord:
    """Per-ECU diagnostics and telemetry collected during a scan."""
    ecu_id: str
    ecu_type: str
    request_header: str
    response_header: str
    discovery_state: str
    health_state: str
    dtcs: List[MultiECUDTCRecord] = field(default_factory=list)
    data_samples: List[MultiECUDataSample] = field(default_factory=list)
    successful_transactions: int = 0
    failed_transactions: int = 0
    last_error: Optional[str] = None
    response_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ecu_id": self.ecu_id,
            "ecu_type": self.ecu_type,
            "request_header": self.request_header,
            "response_header": self.response_header,
            "discovery_state": self.discovery_state,
            "health_state": self.health_state,
            "dtc_count": len(self.dtcs),
            "dtcs": [d.to_dict() for d in self.dtcs],
            "data_sample_count": len(self.data_samples),
            "data_samples": [s.to_dict() for s in self.data_samples],
            "successful_transactions": self.successful_transactions,
            "failed_transactions": self.failed_transactions,
            "last_error": self.last_error,
            "response_time_ms": self.response_time_ms,
        }


@dataclass
class MultiECUScanResult:
    """
    Top-level structured result of a multi-ECU vehicle scan.
    Provides per-ECU results, DTC snapshots, health states, and coverage metrics.
    """
    scan_id: str
    vehicle_context: Optional[MultiECUVehicleContext]
    scan_scope: ScanScope = ScanScope.FULL_VEHICLE
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    ecu_records: Dict[str, ECUScanRecord] = field(default_factory=dict)
    expected_ecus: List[str] = field(default_factory=list)
    detected_ecus: List[str] = field(default_factory=list)
    reachable_ecus: List[str] = field(default_factory=list)
    unreachable_ecus: List[str] = field(default_factory=list)
    unsupported_ecus: List[str] = field(default_factory=list)
    total_transactions: int = 0
    successful_transactions: int = 0
    failed_transactions: int = 0
    warnings: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def get_ecu_dtcs(self, ecu_id: str) -> List[MultiECUDTCRecord]:
        rec = self.ecu_records.get(ecu_id.strip().upper())
        return rec.dtcs if rec else []

    def get_all_dtcs(self) -> List[MultiECUDTCRecord]:
        all_d = []
        for rec in self.ecu_records.values():
            all_d.extend(rec.dtcs)
        return all_d

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "vehicle_context": self.vehicle_context.to_dict() if self.vehicle_context else None,
            "scan_scope": self.scan_scope.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "expected_ecus": self.expected_ecus,
            "detected_ecus": self.detected_ecus,
            "reachable_ecus": self.reachable_ecus,
            "unreachable_ecus": self.unreachable_ecus,
            "unsupported_ecus": self.unsupported_ecus,
            "coverage_metrics": {
                "expected_count": len(self.expected_ecus),
                "detected_count": len(self.detected_ecus),
                "reachable_count": len(self.reachable_ecus),
                "reachable_pct": (len(self.reachable_ecus) / len(self.expected_ecus) * 100.0) if self.expected_ecus else 0.0,
                "total_transactions": self.total_transactions,
                "successful_transactions": self.successful_transactions,
                "failed_transactions": self.failed_transactions,
                "success_rate_pct": (self.successful_transactions / self.total_transactions * 100.0) if self.total_transactions > 0 else 0.0,
            },
            "ecu_records": {k: v.to_dict() for k, v in self.ecu_records.items()},
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }

    def to_g3_dataset(self) -> DiagnosticDataSet:
        """
        Translates multi-ECU scan results into a Phase G-3 DiagnosticDataSet.
        Preserves source ECU for every signal and DTC record.
        """
        dataset = DiagnosticDataSet(
            dataset_id=f"G3-FROM-{self.scan_id}",
            vehicle_context=self.vehicle_context.base_context if self.vehicle_context else None,
            session_start_time=self.start_time,
            session_end_time=self.end_time,
            metadata={
                "source_scan_id": self.scan_id,
                "reachable_ecus": self.reachable_ecus,
                "scope": self.scan_scope.value,
            },
        )

        # 1. Populate DTC records with explicit ECU sources
        for dtc in self.get_all_dtcs():
            dataset.dtc_records.append(
                DTCRecord(
                    code=dtc.code,
                    status=dtc.status,
                    first_timestamp=dtc.timestamp,
                    last_timestamp=dtc.timestamp,
                    ecu_source=dtc.ecu_id,
                    description=dtc.description,
                    freeze_frame=dtc.freeze_frame,
                )
            )

        # 2. Group data samples by canonical name and convert to TimeSeriesSignal
        samples_by_sig: Dict[str, List[MultiECUDataSample]] = collections.defaultdict(list)
        for rec in self.ecu_records.values():
            for sample in rec.data_samples:
                if sample.is_valid and sample.decoded_value is not None:
                    samples_by_sig[sample.canonical_name].append(sample)

        for sig_name, samples in samples_by_sig.items():
            # Sort by timestamp
            samples.sort(key=lambda s: s.response_timestamp)
            ts_arr = np.array([s.response_timestamp for s in samples], dtype=np.float64)
            val_arr = np.array([float(s.decoded_value) for s in samples], dtype=np.float64)
            raw_arr = np.array([str(s.raw_value) for s in samples], dtype=object)
            qual_arr = np.array([s.quality for s in samples], dtype=object)
            src_arr = np.array([DataSourceType.MEASURED.value for _ in samples], dtype=object)

            ref_sample = samples[0]
            dataset.add_signal(
                TimeSeriesSignal(
                    signal_name=sig_name,
                    unit=ref_sample.unit,
                    timestamps=ts_arr,
                    values=val_arr,
                    raw_values=raw_arr,
                    qualities=qual_arr,
                    source_types=src_arr,
                    ecu_source=ref_sample.ecu_id,
                    definition_id=ref_sample.definition_id,
                )
            )

        return dataset


# =====================================================================
# 6. MULTI-ECU DIAGNOSTIC MANAGER (PUBLIC FACADE)
# =====================================================================

class MultiECUDiagnosticManager:
    """
    Public management facade for Multi-ECU diagnostics in the Seyyanen platform.
    Coordinates ECU registration, controlled discovery, reachability verification,
    serialized acquisition scheduling, DTC collection, and G-3 integration.
    """
    def __init__(
        self,
        transaction_manager: DiagnosticTransactionManager,
        definition_registry: Optional[DiagnosticDefinitionRegistry] = None,
        vehicle_context: Optional[MultiECUVehicleContext] = None,
        max_retries: int = 2,
    ):
        self.transaction_manager = transaction_manager
        self.definition_registry = definition_registry or DiagnosticDefinitionRegistry()
        self.router = MultiECURouter(self.transaction_manager)
        self.scheduler = MultiECUScheduler(self.router, max_retries=max_retries)
        self._lock = threading.RLock()
        self._scan_counter = 0

        # Initialize multi-ECU context
        if vehicle_context:
            self.context = vehicle_context
        else:
            self.context = MultiECUVehicleContext()
            self._register_default_ecus()

    def _register_default_ecus(self) -> None:
        """Pre-registers standard automotive ECU targets with standard CAN IDs."""
        # 1. Engine Control Module (ECM/PCM)
        self.register_ecu(ECUTarget(
            logical_id="ECM",
            ecu_type=ECUTargetType.ENGINE,
            human_readable_name="Engine Control Module",
            request_header="7E0",
            response_header="7E8",
            priority=100,
            discovery_state=ECUDiscoveryState.EXPECTED,
        ))

        # 2. Transmission Control Module (TCM)
        self.register_ecu(ECUTarget(
            logical_id="TCM",
            ecu_type=ECUTargetType.TRANSMISSION,
            human_readable_name="Transmission Control Module",
            request_header="7E1",
            response_header="7E9",
            priority=90,
            discovery_state=ECUDiscoveryState.EXPECTED,
        ))

        # 3. Anti-lock Braking System (ABS / ESP)
        self.register_ecu(ECUTarget(
            logical_id="ABS",
            ecu_type=ECUTargetType.BRAKES,
            human_readable_name="Anti-lock Braking System / ESP",
            request_header="7E2",
            response_header="7EA",
            priority=80,
            discovery_state=ECUDiscoveryState.EXPECTED,
        ))

        # 4. Supplemental Restraint System (SRS / Airbag)
        self.register_ecu(ECUTarget(
            logical_id="SRS",
            ecu_type=ECUTargetType.AIRBAG,
            human_readable_name="Supplemental Restraint System (Airbag)",
            request_header="7E3",
            response_header="7EB",
            priority=70,
            discovery_state=ECUDiscoveryState.EXPECTED,
        ))

        # 5. Body Control Module (BCM)
        self.register_ecu(ECUTarget(
            logical_id="BCM",
            ecu_type=ECUTargetType.BODY,
            human_readable_name="Body Control Module",
            request_header="7E4",
            response_header="7EC",
            priority=50,
            discovery_state=ECUDiscoveryState.EXPECTED,
        ))

    def register_ecu(self, ecu: ECUTarget) -> None:
        """Registers or updates an ECU target in the multi-ECU context."""
        with self._lock:
            self.context.add_ecu(ecu)

    def get_ecu(self, logical_id: str) -> Optional[ECUTarget]:
        return self.context.get_ecu(logical_id)

    def list_ecus(self) -> List[ECUTarget]:
        return self.context.list_ecus()

    def check_ecu_reachability(self, target: Union[str, ECUTarget], timeout: float = 1.0) -> bool:
        """
        Sends a lightweight diagnostic query (Mode 01 PID 00 or Tester Present)
        to verify that the ECU target is physically reachable on the bus.
        """
        ecu = self.get_ecu(target) if isinstance(target, str) else target
        if not ecu:
            return False

        # Query Mode 01 PID 00 with ECU target header
        resp = self.router.execute_for_target(
            target=ecu,
            service_id="01",
            payload="",
            subfunction="00",
            timeout=timeout,
        )

        if resp.is_positive and resp.status == STATUS_VALID:
            ecu.discovery_state = ECUDiscoveryState.VERIFIED_REACHABLE
            ecu.health_state = ECUHealthState.CONNECTED
            return True
        elif resp.status == STATUS_NRC:
            # An NRC also proves the ECU is on the bus and communicating
            ecu.discovery_state = ECUDiscoveryState.VERIFIED_REACHABLE
            ecu.health_state = ECUHealthState.CONNECTED
            return True
        else:
            ecu.health_state = ECUHealthState.UNREACHABLE
            return False

    def discover_ecus(self, candidates: Optional[List[str]] = None, timeout: float = 1.0) -> Dict[str, ECUDiscoveryState]:
        """
        Controlled ECU discovery across known candidate targets.
        Strictly distinguishes EXPECTED vs DETECTED vs VERIFIED_REACHABLE vs UNSUPPORTED.
        """
        results: Dict[str, ECUDiscoveryState] = {}
        target_ecus = [self.get_ecu(c) for c in candidates] if candidates else self.list_ecus()
        target_ecus = [e for e in target_ecus if e is not None]

        for ecu in target_ecus:
            is_reachable = self.check_ecu_reachability(ecu, timeout=timeout)
            if is_reachable:
                results[ecu.logical_id] = ECUDiscoveryState.VERIFIED_REACHABLE
            elif ecu.consecutive_failures > 0:
                results[ecu.logical_id] = ECUDiscoveryState.UNSUPPORTED
            else:
                results[ecu.logical_id] = ecu.discovery_state

        return results

    def get_ecu_dtc_snapshot(self, target: Union[str, ECUTarget], timeout: float = 2.0) -> List[MultiECUDTCRecord]:
        """
        Queries Mode 03 / Confirmed DTCs for an individual ECU.
        Preserves ECU identity, parses DTCs, and records raw responses.
        """
        ecu = self.get_ecu(target) if isinstance(target, str) else target
        if not ecu:
            return []

        resp = self.router.execute_for_target(
            target=ecu,
            service_id="03",
            timeout=timeout,
        )

        dtcs: List[MultiECUDTCRecord] = []
        if not resp.is_positive or resp.status != STATUS_VALID or not resp.raw_lines:
            return dtcs

        # Parse Mode 03 response lines (43 XX YY ZZ ...)
        # Combine lines and look for 43 positive response
        combined = "".join(resp.raw_lines).replace(" ", "").upper()
        # Remove CAN headers if present
        for h in (ecu.response_header, "7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF"):
            combined = combined.replace(h, "")

        idx_43 = combined.find("43")
        if idx_43 >= 0:
            payload_hex = combined[idx_43 + 2:]
            # If payload starts with count byte (e.g. 01 for 1 DTC), strip it
            if len(payload_hex) >= 2:
                try:
                    count_byte = int(payload_hex[:2], 16)
                    # Standard OBD returns count byte then 2-byte DTC pairs
                    remaining_hex = payload_hex[2:]
                except ValueError:
                    remaining_hex = payload_hex
            else:
                remaining_hex = payload_hex

            # Parse 2-byte (4 hex chars) DTC codes
            for i in range(0, len(remaining_hex), 4):
                chunk = remaining_hex[i:i+4]
                if len(chunk) == 4 and chunk != "0000":
                    code = self._decode_standard_dtc(chunk)
                    if code and DTC_REGEX.match(code):
                        dtcs.append(
                            MultiECUDTCRecord(
                                ecu_id=ecu.logical_id,
                                code=code,
                                status="CONFIRMED",
                                raw_response=chunk,
                                timestamp=resp.response_timestamp or time.time(),
                                transaction_id=resp.transaction_id,
                            )
                        )

        return dtcs

    def _decode_standard_dtc(self, hex_4: str) -> Optional[str]:
        """Decodes standard 2-byte OBD DTC hex chunk into canonical P/C/B/U code."""
        try:
            val = int(hex_4, 16)
            first_nibble = (val >> 12) & 0x0F
            char_map = {0: "P0", 1: "P1", 2: "P2", 3: "P3",
                        4: "C0", 5: "C1", 6: "C2", 7: "C3",
                        8: "B0", 9: "B1", 10: "B2", 11: "B3",
                        12: "U0", 13: "U1", 14: "U2", 15: "U3"}
            prefix = char_map.get(first_nibble, "P0")
            return f"{prefix}{hex_4[1:]}"
        except Exception:
            return None

    def get_multi_ecu_dtc_snapshot(self, targets: Optional[List[str]] = None) -> Dict[str, List[MultiECUDTCRecord]]:
        """Queries DTC snapshots across multiple ECU targets."""
        target_ecus = [self.get_ecu(t) for t in targets] if targets else self.list_ecus()
        target_ecus = [e for e in target_ecus if e is not None]

        results: Dict[str, List[MultiECUDTCRecord]] = {}
        for ecu in target_ecus:
            results[ecu.logical_id] = self.get_ecu_dtc_snapshot(ecu)

        return results

    def acquire_multi_ecu_snapshot(
        self,
        identifiers_map: Optional[Dict[str, List[str]]] = None,
    ) -> List[MultiECUDataSample]:
        """
        Acquires data samples across multiple ECUs using G-2 definitions.
        identifiers_map: { "ECM": ["0C", "0D", "05"], "TCM": ["0D", "1640"] }
        """
        samples: List[MultiECUDataSample] = []
        if not identifiers_map:
            # Default minimal standard set
            identifiers_map = {
                "ECM": ["0C", "0D", "05"],
                "TCM": ["0D"],
            }

        tasks: List[ScheduledECUTask] = []
        for ecu_id, id_list in identifiers_map.items():
            ecu = self.get_ecu(ecu_id)
            if not ecu:
                continue

            for ident in id_list:
                clean_ident = ident.strip().upper()
                # Look up definition in G-2 registry
                defn = self.definition_registry.get(clean_ident, "01") or self.definition_registry.get(clean_ident, "22")
                if not defn:
                    matches = [d for d in self.definition_registry.list_definitions() if d.identifier == clean_ident]
                    defn = matches[0] if matches else None

                service_id = defn.service_id if defn else ("22" if len(clean_ident) > 2 else "01")
                subfunction = defn.subfunction if (defn and defn.subfunction) else (clean_ident if service_id in ("01", "09", "21") else None)
                payload = clean_ident if service_id == "22" else ""

                tasks.append(
                    ScheduledECUTask(
                        target=ecu,
                        service_id=service_id,
                        payload=payload,
                        subfunction=subfunction,
                        timeout=1.5,
                        priority=ecu.priority,
                        metadata={"identifier": ident, "definition": defn},
                    )
                )

        batch_results = self.scheduler.execute_batch(tasks)

        for task, resp in batch_results:
            defn = task.metadata.get("definition")
            ident = task.metadata.get("identifier", task.payload or task.subfunction or "")
            ecu_id = task.target.logical_id

            if resp.is_positive and resp.status == STATUS_VALID:
                # Decode using G-2 DataDecoder if definition available
                if defn:
                    # Extract payload hex
                    exp_prefix = resp.response_service_id or ""
                    if defn.subfunction:
                        exp_prefix += defn.subfunction
                    elif defn.service_id in ("01", "09", "21"):
                        exp_prefix += defn.identifier
                    elif defn.service_id == "22":
                        exp_prefix += defn.identifier

                    full_hex = resp.raw_payload_hex or ""
                    useful_hex = full_hex[len(exp_prefix):] if full_hex.startswith(exp_prefix) else full_hex
                    useful_bytes = bytes.fromhex(useful_hex) if useful_hex else b""

                    raw_v, dec_v, fields_dict, is_valid, err = DataDecoder.decode(useful_bytes, defn)
                    unit = defn.fields[0].unit if defn.fields else ""
                    canonical_name = f"{ecu_id}:{ident}:{defn.fields[0].name}" if defn.fields else f"{ecu_id}:{ident}"

                    samples.append(
                        MultiECUDataSample(
                            ecu_id=ecu_id,
                            identifier=ident,
                            service_id=defn.service_id,
                            field_name=defn.fields[0].name if defn.fields else ident,
                            canonical_name=canonical_name,
                            decoded_value=dec_v,
                            raw_value=raw_v,
                            unit=unit,
                            quality=QUALITY_GOOD if is_valid else QUALITY_INVALID,
                            request_timestamp=resp.request_timestamp,
                            response_timestamp=resp.response_timestamp,
                            elapsed_time=resp.elapsed_time,
                            transaction_id=resp.transaction_id,
                            definition_id=defn.definition_id,
                            trust_level=defn.trust_level.value,
                            is_valid=is_valid,
                            error_message=err,
                        )
                    )
                else:
                    # Generic raw measurement sample
                    val = None
                    try:
                        if resp.raw_payload_hex:
                            val = int(resp.raw_payload_hex, 16)
                    except ValueError:
                        pass

                    samples.append(
                        MultiECUDataSample(
                            ecu_id=ecu_id,
                            identifier=ident,
                            service_id=task.service_id,
                            field_name=ident,
                            canonical_name=f"{ecu_id}:{ident}",
                            decoded_value=val,
                            raw_value=resp.raw_payload_hex,
                            unit="",
                            quality=QUALITY_GOOD if val is not None else QUALITY_SUSPECT,
                            request_timestamp=resp.request_timestamp,
                            response_timestamp=resp.response_timestamp,
                            elapsed_time=resp.elapsed_time,
                            transaction_id=resp.transaction_id,
                            definition_id=f"DEF-GENERIC-{ident}",
                            trust_level="UNKNOWN",
                            is_valid=val is not None,
                        )
                    )
            else:
                # Failed sample preservation
                samples.append(
                    MultiECUDataSample(
                        ecu_id=ecu_id,
                        identifier=ident,
                        service_id=task.service_id,
                        field_name=ident,
                        canonical_name=f"{ecu_id}:{ident}",
                        decoded_value=None,
                        raw_value=None,
                        unit="",
                        quality=QUALITY_ERROR if resp.status == STATUS_TIMEOUT else QUALITY_INVALID,
                        request_timestamp=resp.request_timestamp,
                        response_timestamp=resp.response_timestamp,
                        elapsed_time=resp.elapsed_time,
                        transaction_id=resp.transaction_id,
                        definition_id=defn.definition_id if defn else f"DEF-{ident}",
                        trust_level="UNKNOWN",
                        is_valid=False,
                        error_message=resp.error_message or resp.status,
                    )
                )

        return samples

    def scan_vehicle(
        self,
        targets: Optional[List[str]] = None,
        include_dtcs: bool = True,
        include_data: bool = True,
        custom_identifiers: Optional[Dict[str, List[str]]] = None,
    ) -> MultiECUScanResult:
        """
        Comprehensive multi-ECU vehicle scan.
        Resolves ECU targets, checks reachability, collects DTCs and data snapshots,
        and constructs a unified MultiECUScanResult.
        """
        with self._lock:
            self._scan_counter += 1
            scan_id = f"SCAN-{int(time.time())}-{self._scan_counter:04d}"

        start_time = time.time()
        start_mono = time.monotonic()

        target_ecus = [self.get_ecu(t) for t in targets] if targets else self.list_ecus()
        target_ecus = [e for e in target_ecus if e is not None]

        scope = ScanScope.SINGLE_ECU if len(target_ecus) == 1 else (ScanScope.PARTIAL if targets else ScanScope.FULL_VEHICLE)

        res = MultiECUScanResult(
            scan_id=scan_id,
            vehicle_context=self.context,
            scan_scope=scope,
            start_time=start_time,
            expected_ecus=[e.logical_id for e in target_ecus],
        )

        for ecu in target_ecus:
            t_ecu_start = time.monotonic()
            is_reachable = self.check_ecu_reachability(ecu, timeout=1.0)
            res.total_transactions += 1

            if is_reachable:
                res.detected_ecus.append(ecu.logical_id)
                res.reachable_ecus.append(ecu.logical_id)
                res.successful_transactions += 1
            else:
                res.unreachable_ecus.append(ecu.logical_id)
                res.failed_transactions += 1

            rec = ECUScanRecord(
                ecu_id=ecu.logical_id,
                ecu_type=ecu.ecu_type.value,
                request_header=ecu.request_header,
                response_header=ecu.response_header,
                discovery_state=ecu.discovery_state.value,
                health_state=ecu.health_state.value,
            )

            # If reachable, acquire DTCs
            if is_reachable and include_dtcs:
                try:
                    ecu_dtcs = self.get_ecu_dtc_snapshot(ecu)
                    rec.dtcs = ecu_dtcs
                    res.total_transactions += 1
                    res.successful_transactions += 1
                except Exception as dtc_err:
                    rec.failed_transactions += 1
                    res.failed_transactions += 1
                    rec.last_error = f"DTC acquisition failed: {dtc_err}"
                    res.warnings.append(f"DTC query error on {ecu.logical_id}: {dtc_err}")

            # If reachable, acquire Data Samples
            if is_reachable and include_data:
                id_map = custom_identifiers if custom_identifiers else {ecu.logical_id: ["0C", "0D", "05"]}
                if ecu.logical_id in id_map:
                    try:
                        ecu_samples = self.acquire_multi_ecu_snapshot({ecu.logical_id: id_map[ecu.logical_id]})
                        rec.data_samples = ecu_samples
                        res.total_transactions += len(id_map[ecu.logical_id])
                        succ = sum(1 for s in ecu_samples if s.is_valid)
                        res.successful_transactions += succ
                        res.failed_transactions += (len(ecu_samples) - succ)
                    except Exception as data_err:
                        rec.last_error = f"Data acquisition failed: {data_err}"
                        res.warnings.append(f"Data query error on {ecu.logical_id}: {data_err}")

            rec.response_time_ms = round((time.monotonic() - t_ecu_start) * 1000.0, 2)
            res.ecu_records[ecu.logical_id] = rec

        end_time = time.time()
        res.end_time = end_time
        res.duration = round(time.monotonic() - start_mono, 3)

        return res

    def scan_ecu(self, ecu_id: str, include_dtcs: bool = True, include_data: bool = True) -> MultiECUScanResult:
        """Convenience method to scan a single ECU target."""
        return self.scan_vehicle(targets=[ecu_id], include_dtcs=include_dtcs, include_data=include_data)

    def cancel_scan(self) -> None:
        """Cancels an active scan or acquisition batch."""
        self.scheduler.cancel()
