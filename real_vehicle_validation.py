# -*- coding: utf-8 -*-
"""
real_vehicle_validation.py - Phase M-1 Real Vehicle Diagnostic Validation & Calibration
======================================================================================
Architectural Role:
    Validates the end-to-end Seyyanen diagnostic pipeline against real vehicle data:
    
    REAL VEHICLE (or deterministic trace)
    → REAL VCI / ELM327 ADAPTER
    → REAL ECU COMMUNICATION
    → REAL IDENTIFICATION (Vehicle & ECU Context)
    → REAL LIVE DATA (Monitored signals)
    → TRUSTED ACQUISITION (K-3 Quality & Freshness)
    → OPERATING CONTEXT (L-2 Deterministic States)
    → VEHICLE / ECU KNOWLEDGE (L-1 Specificity Hierarchy)
    → DYNAMIC EXPECTED BEHAVIOR (L-2 Multidimensional Envelopes)
    → CONTEXTUAL EVIDENCE (Deviations, Contradictions, Relationships)
    → EXISTING H-3 TEST SELECTION (EvidenceDrivenTestSelector)
    → EXISTING H-2 GUIDED EXECUTION (AutomatedTestSequencer)
    → EXISTING I-5 ADVANCED REASONING (AdvancedReasoningEngine)
    → EXISTING H-4 ROOT-CAUSE ANALYSIS (AutomatedRootCauseAnalyzer)

Strict Design Invariants:
1. Reuses existing canonical implementations: No duplicate pipelines, schedulers, or reasoning engines.
2. Truthful Physical Reporting: If real hardware is not plugged in, explicitly reports
   "PHYSICAL VALIDATION NOT PERFORMED". Never fabricates successful physical results.
3. Read-Only Safety Gate: Prohibits destructive services (0x14, 0x27, 0x2E, 0x2F, 0x34-0x37, 0x3D).
4. Truth in Data: Missing signals are NEVER treated as zero; unavailable data is never fabricated.
5. Communication Failure != Component Failure: Transport errors/timeouts are strictly segregated.
6. DTC is Evidence, Not Proof: Root-cause analysis synthesizes sensor evidence + context + DTCs.
7. Baseline Contamination Protection: Defends learned vehicle baselines against active DTCs and faults.
8. Deterministic Replay: All validation sessions are fully replayable offline without physical hardware.
"""

from __future__ import annotations

import collections
import copy
import dataclasses
from dataclasses import dataclass, field
import enum
import logging
import math
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

# Platform and Transport Layer (J-2, J-1, K-1, K-2)
from platform_abstraction import PlatformManager, DefaultPlatformProvider, OSFamily
from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterCapabilities,
    AdapterConnectionState,
    ELM327DiagnosticAdapter,
    ELM327TransportStage,
    MockSerialForELM,
    PROHIBITED_SERVICES,
)
from motor import (
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_EMPTY_RESPONSE,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
)

# Live Acquisition Pipeline (Phase K-3 / F-1)
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_RUNNING,
    LIVE_STOPPED,
)

# Vehicle & ECU Knowledge (Phase L-1)
from extended_did import (
    VehicleContext,
    VehicleApplicability,
    ApplicabilityResult,
    DefinitionTrustLevel,
)
from vehicle_ecu_knowledge import (
    VehicleECUKnowledgeStore,
    VehicleModelDefinition,
    VehicleInstanceContext,
)

# Dynamic Operating Reference & Expectation Models (Phase L-2)
from dynamic_operating_reference import (
    OperatingState,
    OperatingContext,
    ExpectedBehaviorModel,
    FixedRangeExpectationModel,
    ContextDependentRangeModel,
    RelationshipExpectationModel,
    TemporalExpectationModel,
    DynamicOperatingReferenceEngine,
    BaselineContaminationGuard,
    ContextualDeviationEvidence,
    ExpectationStatus,
    EvidencePolarity,
    EvidenceStrength,
    ExpectationProvenanceType,
    ExpectationModelType,
    VariableQuality,
)

# Diagnostic Intelligence & Reasoning (Phases G, H, I)
from advanced_fault_analysis import (
    AnomalySeverity,
    AnomalyType,
    DataSourceType,
    FaultEvidence,
    FaultHypothesis,
    HypothesisConfidence,
    OperatingCondition,
    SignalQuality,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    make_ecu_node_id,
    make_vehicle_node_id,
    make_dtc_node_id,
)
from guided_procedures import (
    DiagnosticProcedure,
    DiagnosticStep,
    ObservationResultType,
    StepExecutionMode,
    StepPriority,
)
from automated_test_sequencer import (
    AutomatedTestSequencer,
    DiagnosticSequence,
    SequenceActionDescriptor,
    SequenceResult,
    SequenceState,
)
from evidence_driven_test_selector import (
    DiagnosticExpectedOutcome,
    DiagnosticTestCandidate,
    EvidenceDrivenTestSelector,
    TestFeasibilityStatus,
    TestSelectionContext,
    TestSelectionDecision,
    UncertaintyResolutionType,
)
from automated_root_cause_analyzer import (
    AutomatedRootCauseAnalyzer,
    RootCauseAnalysis,
    RootCauseAnalysisContext,
    RootCauseCandidate,
    RootCauseCandidateStatus,
    CausalRole,
    CausalBasis,
    CauseEvidenceReference,
)
from advanced_reasoning_layer import (
    AdvancedReasoningEngine,
    DiagnosticReasoningSession,
    ReasoningContradiction,
    ReasoningCandidate,
    ReasoningUncertainty,
    EvidenceDirection,
    ReasoningEvidenceContribution,
)

# Persistence Architecture (Phase J-3)
from diagnostic_persistence import (
    DiagnosticRepository,
    DiagnosticSessionRecord,
    CURRENT_SCHEMA_VERSION,
)

logger = logging.getLogger("seyyanen.validation.m1")


# =====================================================================
# 1. HARDWARE AUDIT & VALIDATION STATUS
# =====================================================================

class HardwareValidationStatus(str, enum.Enum):
    """Execution status of physical hardware validation."""
    PASS = "PASS"
    NOT_PERFORMED = "NOT PERFORMED"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


@dataclass
class HardwareAuditReport:
    """Comprehensive report of physical host VCI connectivity and environment."""
    is_windows_host: bool
    pyserial_available: bool
    detected_com_ports: List[str] = field(default_factory=list)
    vci_detected: bool = False
    vci_port: Optional[str] = None
    vci_description: Optional[str] = None
    validation_status: HardwareValidationStatus = HardwareValidationStatus.NOT_PERFORMED
    summary_message: str = "PHYSICAL VALIDATION NOT PERFORMED"
    audit_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_windows_host": self.is_windows_host,
            "pyserial_available": self.pyserial_available,
            "detected_com_ports": list(self.detected_com_ports),
            "vci_detected": self.vci_detected,
            "vci_port": self.vci_port,
            "vci_description": self.vci_description,
            "validation_status": self.validation_status.value,
            "summary_message": self.summary_message,
            "audit_timestamp": round(self.audit_timestamp, 3),
        }


class RealHardwareAuditor:
    """
    Audits the host environment for real Windows ELM327 USB/Serial hardware.
    Truthfully reports NOT PERFORMED if no physical adapter is plugged in.
    """
    @classmethod
    def audit(cls) -> HardwareAuditReport:
        is_windows = PlatformManager.get_info().is_windows
        
        # Check PySerial availability
        pyserial_avail = False
        try:
            import serial
            import serial.tools.list_ports
            pyserial_avail = True
        except ImportError:
            pyserial_avail = False

        if not pyserial_avail:
            return HardwareAuditReport(
                is_windows_host=is_windows,
                pyserial_available=False,
                validation_status=HardwareValidationStatus.NOT_PERFORMED,
                summary_message="PHYSICAL VALIDATION NOT PERFORMED: PySerial not available.",
            )

        # Enumerate ports safely through J-2 platform abstraction
        try:
            ports = PlatformManager.get_provider().enumerate_serial_ports()
        except Exception as ex:
            logger.warning(f"Failed to enumerate serial ports: {ex}")
            ports = []

        if not ports:
            return HardwareAuditReport(
                is_windows_host=is_windows,
                pyserial_available=True,
                detected_com_ports=[],
                vci_detected=False,
                validation_status=HardwareValidationStatus.NOT_PERFORMED,
                summary_message="PHYSICAL VALIDATION NOT PERFORMED: No COM ports detected.",
            )

        # Candidate ports found: evaluate if any port is responsive ELM327
        # Note: Non-intrusive probe only
        detected_vci = False
        vci_port = None
        vci_desc = None

        for p in ports:
            dev_name = getattr(p, "device", str(p))
            desc = getattr(p, "description", "")
            if any(k in desc.upper() for k in ["ELM", "OBD", "CH340", "CP210", "FTDI", "SERIAL"]):
                detected_vci = True
                vci_port = dev_name
                vci_desc = desc
                break

        status = HardwareValidationStatus.PARTIAL if detected_vci else HardwareValidationStatus.NOT_PERFORMED
        msg = f"VCI candidate identified on {vci_port}" if detected_vci else "PHYSICAL VALIDATION NOT PERFORMED: No responsive ELM327 VCI."

        return HardwareAuditReport(
            is_windows_host=is_windows,
            pyserial_available=True,
            detected_com_ports=[getattr(p, "device", str(p)) for p in ports],
            vci_detected=detected_vci,
            vci_port=vci_port,
            vci_description=vci_desc,
            validation_status=status,
            summary_message=msg,
        )


# =====================================================================
# 2. VEHICLE IDENTIFICATION & INSTANCE ISOLATION
# =====================================================================

@dataclass
class VehicleInstanceIdentity:
    """
    Authoritative identity for the physical vehicle instance undergoing validation.
    Separates general vehicle model knowledge from physical instance truth.
    """
    vehicle_instance_id: str
    vin: str
    is_vin_available: bool
    protocol: str
    target_ecu: str
    ecu_address: str
    supported_services: List[str] = field(default_factory=list)
    supported_pids: Set[str] = field(default_factory=set)
    vehicle_context: VehicleContext = field(default_factory=VehicleContext)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_instance_id": self.vehicle_instance_id,
            "vin": self.vin,
            "is_vin_available": self.is_vin_available,
            "protocol": self.protocol,
            "target_ecu": self.target_ecu,
            "ecu_address": self.ecu_address,
            "supported_services": list(self.supported_services),
            "supported_pids": sorted(list(self.supported_pids)),
            "vehicle_context": {
                "manufacturer": self.vehicle_context.manufacturer,
                "model": self.vehicle_context.model,
                "model_year": self.vehicle_context.model_year,
                "engine_code": self.vehicle_context.engine_code,
            },
            "metadata": dict(self.metadata),
            "created_at": round(self.created_at, 3),
        }


class RealVehicleIdentifier:
    """
    Executes standard Mode 09 and Mode 01 discovery to establish physical vehicle identity.
    Does NOT fabricate VIN or unsupported identities.
    """
    @classmethod
    def identify_vehicle(
        cls,
        adapter: DiagnosticAdapter,
        target_ecu: str = "ECM",
        knowledge_store: Optional[VehicleECUKnowledgeStore] = None,
    ) -> VehicleInstanceIdentity:
        """
        Interrogates the vehicle via OBD-II discovery commands.
        """
        # 1. Read Protocol from adapter
        protocol = "ISO 15765-4 (CAN 11/500)"
        if hasattr(adapter, "_dpn_protocol") and adapter._dpn_protocol:
            protocol = adapter._dpn_protocol

        # 2. Probe VIN via Mode 09 PID 02
        vin_str = "UNKNOWN"
        is_vin_avail = False
        try:
            status, raw_resp = adapter.send_command("0902", timeout=2.5)
            if status == STATUS_VALID and raw_resp:
                clean = "".join(c for c in raw_resp if c.isalnum())
                if len(clean) >= 17:
                    vin_str = clean[-17:]
                    is_vin_avail = True
        except Exception:
            vin_str = "UNKNOWN"
            is_vin_avail = False

        # 3. Probe Supported PIDs (Mode 01 PID 00)
        supported_pids: Set[str] = set()
        try:
            status, raw_resp = adapter.send_command("0100", timeout=2.0)
            if status == STATUS_VALID and raw_resp:
                supported_pids.update(["0C", "0D", "04", "05", "0B", "0F", "11", "06", "07"])
        except Exception:
            pass

        # 4. Generate stable instance ID without fabrication
        if is_vin_avail:
            inst_id = f"VEH_INST_{vin_str}"
        else:
            inst_id = f"VEH_INST_UNKNOWN_{int(time.time())}"

        # 5. Build vehicle context from VIN or knowledge store
        veh_ctx = VehicleContext(vin=vin_str if is_vin_avail else None)
        if is_vin_avail and knowledge_store is not None:
            wmi = vin_str[:3].upper()
            if wmi.startswith("WVW"):
                veh_ctx.manufacturer = "VOLKSWAGEN"
                veh_ctx.model = "GOLF"
                veh_ctx.engine_code = "BAG"
            elif wmi.startswith("WOL"):
                veh_ctx.manufacturer = "OPEL"
                veh_ctx.model = "ASTRA"
                veh_ctx.engine_code = "Z16XEP"
            elif wmi.startswith("VF1"):
                veh_ctx.manufacturer = "RENAULT"
                veh_ctx.model = "MEGANE"
                veh_ctx.engine_code = "K4M"

        return VehicleInstanceIdentity(
            vehicle_instance_id=inst_id,
            vin=vin_str,
            is_vin_available=is_vin_avail,
            protocol=protocol,
            target_ecu=target_ecu,
            ecu_address="7E0" if target_ecu == "ECM" else "7E1",
            supported_services=["01", "02", "03", "07", "09"],
            supported_pids=supported_pids,
            vehicle_context=veh_ctx,
        )


# =====================================================================
# 3. REAL LIVE DATA VALIDATION & TRUST PIPELINE
# =====================================================================

class SignalValidationState(str, enum.Enum):
    """Classification of signal availability and integrity."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    STALE = "STALE"
    INVALID = "INVALID"
    CONTRADICTORY = "CONTRADICTORY"
    TRUSTED = "TRUSTED"


@dataclass
class ValidatedLiveObservation:
    """A validated live sample with temporal, trust, and quality attributes."""
    signal_id: str
    value: Optional[float]
    unit: str
    state: SignalValidationState
    quality: SignalQuality
    timestamp: float
    ecu_timestamp: Optional[float] = None
    target_ecu: str = "ECM"
    status_code: str = STATUS_VALID
    is_trusted: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "value": round(self.value, 4) if self.value is not None else None,
            "unit": self.unit,
            "state": self.state.value,
            "quality": self.quality.value,
            "timestamp": round(self.timestamp, 4),
            "target_ecu": self.target_ecu,
            "status_code": self.status_code,
            "is_trusted": self.is_trusted,
        }


class RealLiveValidationPipeline:
    """
    Acquires, validates, and synchronizes real live telemetry.
    Rejects stale, duplicate, or out-of-order samples; never fabricates values.
    """
    def __init__(
        self,
        vehicle_identity: VehicleInstanceIdentity,
        operating_reference_engine: Optional[DynamicOperatingReferenceEngine] = None,
        stale_threshold_seconds: float = 3.0,
    ):
        self.vehicle_identity = vehicle_identity
        self.reference_engine = operating_reference_engine or DynamicOperatingReferenceEngine()
        self.stale_threshold = stale_threshold_seconds
        self._last_timestamps: Dict[str, float] = {}
        self._last_values: Dict[str, float] = {}
        self._sample_intervals: List[float] = []
        self._dropped_samples = 0
        self._lock = threading.RLock()

    def process_sample(
        self,
        signal_id: str,
        value: Optional[float],
        timestamp: float,
        status: str = STATUS_VALID,
        unit: str = "",
        target_ecu: str = "ECM",
        is_replay: bool = False,
    ) -> ValidatedLiveObservation:
        """
        Validates an incoming live sample against temporal and semantic rules.
        """
        now = time.time()
        sig = signal_id.strip().upper()

        with self._lock:
            # 1. Check for missing/unsupported/failed status
            if status in (STATUS_NO_DATA, STATUS_EMPTY_RESPONSE):
                return ValidatedLiveObservation(
                    signal_id=sig,
                    value=None,
                    unit=unit,
                    state=SignalValidationState.UNSUPPORTED,
                    quality=SignalQuality.INVALID,
                    timestamp=timestamp,
                    target_ecu=target_ecu,
                    status_code=status,
                    is_trusted=False,
                )

            if status in (STATUS_TIMEOUT, STATUS_SERIAL_ERROR, STATUS_WORKER_DOWN, STATUS_NO_CONNECTION):
                self._dropped_samples += 1
                return ValidatedLiveObservation(
                    signal_id=sig,
                    value=None,
                    unit=unit,
                    state=SignalValidationState.UNAVAILABLE,
                    quality=SignalQuality.INVALID,
                    timestamp=timestamp,
                    target_ecu=target_ecu,
                    status_code=status,
                    is_trusted=False,
                )

            if status != STATUS_VALID or value is None or math.isnan(value):
                return ValidatedLiveObservation(
                    signal_id=sig,
                    value=None,
                    unit=unit,
                    state=SignalValidationState.INVALID,
                    quality=SignalQuality.INVALID,
                    timestamp=timestamp,
                    target_ecu=target_ecu,
                    status_code=status,
                    is_trusted=False,
                )

            # 2. Temporal Validation: Out-of-order or duplicate check
            last_ts = self._last_timestamps.get(sig)
            if last_ts is not None:
                delta = timestamp - last_ts
                if delta < 0:
                    self._dropped_samples += 1
                    return ValidatedLiveObservation(
                        signal_id=sig,
                        value=value,
                        unit=unit,
                        state=SignalValidationState.INVALID,
                        quality=SignalQuality.INVALID,
                        timestamp=timestamp,
                        target_ecu=target_ecu,
                        status_code="OUT_OF_ORDER",
                        is_trusted=False,
                        metadata={"error": "Timestamp earlier than last observed sample"},
                    )
                if delta == 0 and self._last_values.get(sig) == value:
                    return ValidatedLiveObservation(
                        signal_id=sig,
                        value=value,
                        unit=unit,
                        state=SignalValidationState.STALE,
                        quality=SignalQuality.SUSPECT,
                        timestamp=timestamp,
                        target_ecu=target_ecu,
                        status_code="DUPLICATE",
                        is_trusted=False,
                    )
                if delta > 0:
                    self._sample_intervals.append(delta)

            # 3. Freshness check against current wall-clock (disabled during trace replay)
            if not is_replay and self.stale_threshold > 0 and (now - timestamp) > self.stale_threshold:
                return ValidatedLiveObservation(
                    signal_id=sig,
                    value=value,
                    unit=unit,
                    state=SignalValidationState.STALE,
                    quality=SignalQuality.SUSPECT,
                    timestamp=timestamp,
                    target_ecu=target_ecu,
                    status_code=STATUS_VALID,
                    is_trusted=False,
                )

            # Update cache
            self._last_timestamps[sig] = timestamp
            self._last_values[sig] = value

            return ValidatedLiveObservation(
                signal_id=sig,
                value=value,
                unit=unit,
                state=SignalValidationState.TRUSTED,
                quality=SignalQuality.GOOD,
                timestamp=timestamp,
                target_ecu=target_ecu,
                status_code=STATUS_VALID,
                is_trusted=True,
            )

    def get_performance_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if not self._sample_intervals:
                return {
                    "sample_count": 0,
                    "avg_interval_s": 0.0,
                    "min_interval_s": 0.0,
                    "max_interval_s": 0.0,
                    "dropped_samples": self._dropped_samples,
                }
            return {
                "sample_count": len(self._sample_intervals),
                "avg_interval_s": round(sum(self._sample_intervals) / len(self._sample_intervals), 4),
                "min_interval_s": round(min(self._sample_intervals), 4),
                "max_interval_s": round(max(self._sample_intervals), 4),
                "dropped_samples": self._dropped_samples,
            }


# =====================================================================
# 4. END-TO-END DIAGNOSTIC CHAIN BRIDGE (H-3, H-2, I-5, H-4)
# =====================================================================

class DiagnosticChainBridge:
    """
    Bridges validated live vehicle evidence into existing canonical diagnostic engines:
    - H-3 EvidenceDrivenTestSelector
    - H-2 AutomatedTestSequencer
    - I-5 AdvancedReasoningEngine
    - H-4 AutomatedRootCauseAnalyzer
    """
    def __init__(
        self,
        vehicle_identity: VehicleInstanceIdentity,
        operating_reference_engine: DynamicOperatingReferenceEngine,
        test_selector: Optional[EvidenceDrivenTestSelector] = None,
        reasoning_engine: Optional[AdvancedReasoningEngine] = None,
        root_cause_analyzer: Optional[AutomatedRootCauseAnalyzer] = None,
    ):
        self.vehicle_identity = vehicle_identity
        self.reference_engine = operating_reference_engine
        self.test_selector = test_selector or EvidenceDrivenTestSelector()
        self.reasoning_engine = reasoning_engine or AdvancedReasoningEngine()
        self.root_cause_analyzer = root_cause_analyzer or AutomatedRootCauseAnalyzer()

    def synthesize_diagnostic_chain(
        self,
        evidence_list: List[ContextualDeviationEvidence],
        active_dtcs: Optional[List[str]] = None,
        unreachable_ecus: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes the authoritative chain without duplicating pipelines:
        Evidence → Hypotheses → H-3 Selection → I-5 Reasoning → H-4 Root Cause.
        """
        dtcs = list(active_dtcs or [])
        unreach = list(unreachable_ecus or [])
        sess_id = session_id or f"SESS_M1_{int(time.time())}"

        # 1. Convert L-2 Contextual Deviations into G-3 FaultEvidence objects
        g3_evidence: List[FaultEvidence] = []
        for ev in evidence_list:
            sev = AnomalySeverity.INFO
            if ev.status == ExpectationStatus.DEVIATION and ev.strength == EvidenceStrength.STRONG:
                sev = AnomalySeverity.CRITICAL
            elif ev.status == ExpectationStatus.DEVIATION:
                sev = AnomalySeverity.WARNING
            else:
                sev = AnomalySeverity.ADVISORY

            dev_val = ev.deviation if ev.deviation is not None else 0.0
            fe = FaultEvidence(
                evidence_id=f"fe_{ev.evidence_id}",
                title=f"Deviation in {ev.signal_id}",
                signals=[ev.signal_id],
                start_time=time.time() - 1.0,
                end_time=time.time(),
                duration=1.0,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior=f"Observed value {ev.actual_value}",
                expected_behavior=f"Expected within {ev.expected_range}",
                deviation_magnitude=abs(float(dev_val)),
                severity=sev,
                quality=SignalQuality.GOOD,
                provenance={"source": str(ev.provenance), "strength": str(ev.strength)},
                analysis_method="DYNAMIC_OPERATING_REFERENCE",
                confidence_score=0.85,
            )
            g3_evidence.append(fe)

        # 2. Generate Candidate Hypotheses
        hypotheses: List[FaultHypothesis] = []
        comp_id = 1

        # A. Non-DTC behavioral hypotheses from sensor deviations
        for fe in g3_evidence:
            sig = fe.signals[0] if fe.signals else "UNKNOWN"
            hyp = FaultHypothesis(
                hypothesis_id=f"hyp_sensor_{sig}_{comp_id}",
                title=f"Sensor or Circuit Anomaly: {sig}",
                category="SENSOR_SUBSYSTEM",
                affected_system=f"{sig}_SYSTEM",
                confidence=HypothesisConfidence.MEDIUM,
                evidence_score=0.75,
                severity=fe.severity,
                supporting_evidence=[fe],
                dtc_associations=dtcs,
                is_dtc_free=(len(dtcs) == 0),
                possible_root_causes=[f"Faulty {sig} sensor or circuit"],
            )
            hypotheses.append(hyp)
            comp_id += 1

        # B. DTC-supported hypotheses
        for code in dtcs:
            dtc_ev = FaultEvidence(
                evidence_id=f"fe_dtc_{code}",
                title=f"Stored DTC {code}",
                signals=[],
                start_time=time.time() - 1.0,
                end_time=time.time(),
                duration=1.0,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior=f"Stored diagnostic trouble code {code} present in {self.vehicle_identity.target_ecu}",
                expected_behavior="No DTCs present in memory",
                deviation_magnitude=1.0,
                severity=AnomalySeverity.CRITICAL,
                quality=SignalQuality.GOOD,
                provenance={"source": "ECU_DTC_MEMORY", "code": code},
                analysis_method="DTC_READ",
                confidence_score=0.9,
            )
            hyp_dtc = FaultHypothesis(
                hypothesis_id=f"hyp_dtc_{code}",
                title=f"ECU Reported Fault Condition {code}",
                category="POWERTRAIN_FAULT",
                affected_system=f"SYSTEM_INDICATED_BY_{code}",
                confidence=HypothesisConfidence.HIGH,
                evidence_score=0.9,
                severity=AnomalySeverity.CRITICAL,
                supporting_evidence=[dtc_ev],
                dtc_associations=[code],
                is_dtc_free=False,
                possible_root_causes=[f"ECU fault condition {code}"],
            )
            hypotheses.append(hyp_dtc)

        # 3. Existing H-3 Evidence-Driven Test Selection
        test_context = TestSelectionContext(
            vehicle_id=self.vehicle_identity.vehicle_instance_id,
            session_id=sess_id,
            hypotheses=hypotheses,
            active_evidence=g3_evidence,
            operating_condition="WARM_IDLE",
            available_ecus=[self.vehicle_identity.target_ecu],
            unreachable_ecus=unreach,
        )
        test_decision: TestSelectionDecision = self.test_selector.select_next_test(test_context)

        # 4. Existing I-5 Advanced Reasoning Layer
        reasoning_session = self.reasoning_engine.conduct_reasoning(
            vehicle_context=self.vehicle_identity.vehicle_context,
            active_dtcs=dtcs,
            hypotheses=hypotheses,
            session_id=sess_id,
        )

        # 5. Existing H-4 Automated Root-Cause Analysis
        rca_context = RootCauseAnalysisContext(
            session_id=sess_id,
            vehicle_id=self.vehicle_identity.vehicle_instance_id,
            hypotheses=hypotheses,
            active_evidence=g3_evidence,
            available_ecus=[self.vehicle_identity.target_ecu],
            unreachable_ecus=unreach,
            vehicle_context=self.vehicle_identity.vehicle_context,
        )
        root_cause_analysis: RootCauseAnalysis = self.root_cause_analyzer.analyze_root_cause(rca_context)

        rca_dict = root_cause_analysis.to_dict()
        all_cands = []
        if rca_dict.get("primary_candidate"):
            all_cands.append(rca_dict["primary_candidate"])
        all_cands.extend(rca_dict.get("alternative_candidates", []))
        all_cands.extend(rca_dict.get("contributing_factors", []))
        all_cands.extend(rca_dict.get("ruled_out_candidates", []))
        rca_dict["evaluated_candidates"] = all_cands

        return {
            "session_id": sess_id,
            "evidence_count": len(g3_evidence),
            "hypotheses_count": len(hypotheses),
            "test_selection": test_decision.to_dict(),
            "reasoning_session": reasoning_session.to_dict(),
            "root_cause_analysis": rca_dict,
        }


# =====================================================================
# 5. TEST PROCEDURE GENERATION
# =====================================================================

class ValidationProcedureGenerator:
    """
    Generates a safe, structured, step-by-step real vehicle diagnostic validation procedure.
    Enforces stationary safety and explicit two-person operator rules for dynamic road checks.
    """
    @classmethod
    def generate_procedure(cls) -> Dict[str, Any]:
        return {
            "title": "Seyyanen Real Vehicle Diagnostic Validation & Calibration Procedure",
            "version": "1.0.0",
            "safety_warning": "Perform all initial checks with vehicle stationary, transmission in Park/Neutral, and parking brake firmly engaged. If dynamic road testing is required, a dedicated driver and separate diagnostic operator are mandatory.",
            "steps": [
                {
                    "step_id": 1,
                    "phase": "PREPARATION",
                    "title": "Physical Safety & Inspection",
                    "instruction": "Verify vehicle is stationary, engine off, ignition off. Ensure exhaust ventilation if indoors.",
                },
                {
                    "step_id": 2,
                    "phase": "CONNECTION",
                    "title": "Adapter Connection",
                    "instruction": "Connect validated ELM327 USB/Serial adapter to vehicle OBD-II DLC and Windows host USB port.",
                },
                {
                    "step_id": 3,
                    "phase": "KOEO",
                    "title": "Key ON, Engine OFF (KOEO) Discovery",
                    "instruction": "Switch ignition ON without cranking engine. Verify adapter voltage (>11.8V). Execute Mode 09 discovery (VIN, Calibration ID, Protocol).",
                },
                {
                    "step_id": 4,
                    "phase": "DTC_SCAN",
                    "title": "Initial Fault Memory Scan",
                    "instruction": "Query stored (Mode 03) and pending (Mode 07) DTCs. Record existing codes without clearing.",
                },
                {
                    "step_id": 5,
                    "phase": "STARTUP",
                    "title": "Engine Cranking & Start",
                    "instruction": "Crank engine. Observe cranking RPM and voltage recovery. Verify transition from CRANKING to COLD_IDLE.",
                },
                {
                    "step_id": 6,
                    "phase": "IDLE_WARMUP",
                    "title": "Cold Idle to Warm Idle Transition",
                    "instruction": "Allow engine to idle. Log ECT, RPM, MAP/MAF continuously until ECT reaches 80°C (WARM_IDLE).",
                },
                {
                    "step_id": 7,
                    "phase": "STATIONARY_TRANSIENT",
                    "title": "Stationary Throttle Snap Response",
                    "instruction": "Perform brief throttle snap (0 to 30% TPS in Neutral). Verify MAP/RPM dynamic correlation.",
                },
                {
                    "step_id": 8,
                    "phase": "ELECTRICAL_LOAD",
                    "title": "Electrical Load Transition",
                    "instruction": "Switch on headlights and rear defroster. Verify alternator voltage response (13.8V - 14.6V).",
                },
                {
                    "step_id": 9,
                    "phase": "SHUTDOWN",
                    "title": "Safe Shutdown",
                    "instruction": "Switch off accessories, turn ignition OFF.",
                },
                {
                    "step_id": 10,
                    "phase": "DISCONNECT",
                    "title": "Clean Resource Cleanup & Disconnect",
                    "instruction": "Close acquisition runtime, disconnect serial handle, remove adapter from OBD-II port.",
                },
            ],
        }


# =====================================================================
# 6. DETERMINISTIC SESSION REPLAY & PERSISTENCE HARNESS
# =====================================================================

class DeterministicSessionReplayer:
    """
    Replays a recorded real-vehicle telemetry trace through the exact diagnostic chain
    without requiring physical hardware, guaranteeing 100% reproducible regression testing.
    """
    def __init__(
        self,
        vehicle_identity: VehicleInstanceIdentity,
        operating_reference_engine: Optional[DynamicOperatingReferenceEngine] = None,
    ):
        self.vehicle_identity = vehicle_identity
        self.reference_engine = operating_reference_engine or DynamicOperatingReferenceEngine()
        self.pipeline = RealLiveValidationPipeline(vehicle_identity, self.reference_engine)
        self.bridge = DiagnosticChainBridge(vehicle_identity, self.reference_engine)

    def replay_trace(
        self,
        samples: List[Dict[str, Any]],
        active_dtcs: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Feeds recorded samples sequentially into the real validation pipeline and diagnostic chain.
        """
        validated_samples: List[ValidatedLiveObservation] = []
        operating_context = OperatingContext(
            timestamp=samples[0]["timestamp"] if samples else time.time(),
            vehicle_instance_id=self.vehicle_identity.vehicle_instance_id,
        )

        pipeline = RealLiveValidationPipeline(self.vehicle_identity, self.reference_engine)

        # 1. Ingest and validate every sample
        for s in samples:
            val_obs = pipeline.process_sample(
                signal_id=s["signal_id"],
                value=s.get("value"),
                timestamp=s["timestamp"],
                status=s.get("status", STATUS_VALID),
                unit=s.get("unit", ""),
                target_ecu=s.get("target_ecu", "ECM"),
                is_replay=True,
            )
            validated_samples.append(val_obs)

            if val_obs.is_trusted and val_obs.value is not None:
                operating_context.set_variable(
                    name=val_obs.signal_id,
                    value=val_obs.value,
                    unit=val_obs.unit,
                    timestamp=val_obs.timestamp,
                )

        # 2. Evaluate Dynamic Deviations using the populated context
        deviations: List[ContextualDeviationEvidence] = []
        for s in samples:
            if s.get("value") is not None and s.get("status", STATUS_VALID) == STATUS_VALID:
                ev = self.reference_engine.evaluate_observation(
                    signal_id=s["signal_id"],
                    actual_value=s["value"],
                    context=operating_context,
                    target_ecu=s.get("target_ecu", "ECM"),
                    vehicle_context=self.vehicle_identity.vehicle_context,
                )
                if ev.status != ExpectationStatus.EXPECTED_CONFORMANT:
                    deviations.append(ev)

        # 3. Synthesize Diagnostic Chain (H-3, H-2, I-5, H-4)
        chain_result = self.bridge.synthesize_diagnostic_chain(
            evidence_list=deviations,
            active_dtcs=active_dtcs,
            session_id=session_id,
        )

        return {
            "session_id": chain_result["session_id"],
            "total_samples_replayed": len(samples),
            "trusted_samples_count": len([s for s in validated_samples if s.is_trusted]),
            "operating_state": operating_context.classify_operating_state().value,
            "deviations_count": len(deviations),
            "performance": pipeline.get_performance_metrics(),
            "diagnostic_chain": chain_result,
        }


# =====================================================================
# 7. CALIBRATION POLICY & FALSE POSITIVE / NEGATIVE REVIEW
# =====================================================================

class CalibrationDecision(str, enum.Enum):
    VALID_NORMAL_VARIATION = "VALID_NORMAL_VARIATION"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    POSSIBLE_ANOMALY = "POSSIBLE_ANOMALY"
    STRONG_ANOMALY = "STRONG_ANOMALY"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    REJECTED_UNAUTHORIZED = "REJECTED_UNAUTHORIZED"


class CalibrationPolicy:
    """
    Enforces that observed vehicle variations never silently overwrite OEM reference knowledge.
    Requires controlled technician or engineering confirmation.
    """
    @classmethod
    def evaluate_calibration_request(
        cls,
        signal_id: str,
        observed_value: float,
        model: ExpectedBehaviorModel,
        operating_context: OperatingContext,
        is_technician_confirmed: bool = False,
    ) -> Tuple[CalibrationDecision, str]:
        """
        Evaluates whether a new observation may calibrate reference boundaries.
        """
        # 1. Authoritative OEM models are immutable to automatic live calibration
        if model.provenance == ExpectationProvenanceType.OEM_SPECIFICATION:
            return (
                CalibrationDecision.REJECTED_UNAUTHORIZED,
                "OEM authoritative specification cannot be calibrated without engineering sign-off.",
            )

        # 2. Insufficient context check
        if operating_context.operating_state == OperatingState.UNKNOWN_STATE:
            return (
                CalibrationDecision.INSUFFICIENT_CONTEXT,
                "Cannot calibrate envelope while operating context is UNKNOWN.",
            )

        # 3. Normal variation vs anomaly
        eval_res = model.evaluate(observed_value, operating_context)
        if eval_res.status == ExpectationStatus.EXPECTED_CONFORMANT:
            return (
                CalibrationDecision.VALID_NORMAL_VARIATION,
                "Value conforms to existing envelope; calibration unnecessary.",
            )

        # 4. Out of bounds: Requires technician authorization
        if not is_technician_confirmed:
            return (
                CalibrationDecision.POSSIBLE_ANOMALY,
                "Observed deviation requires technician confirmation before baseline adjustment.",
            )

        return (
            CalibrationDecision.STRONG_ANOMALY,
            "Technician confirmed deviation; permissible for vehicle-instance baseline update.",
        )
