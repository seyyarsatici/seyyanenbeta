# -*- coding: utf-8 -*-
"""
SEYYANEN AUTOMOTIVE DIAGNOSTIC PLATFORM
Phase G-3: Advanced Fault Analysis Engine
=============================================================================
This module implements Phase G-3 of the Seyyanen diagnostic architecture.
It consumes validated time-series vehicle data, G-2 structured evidence, and
operating conditions to produce explainable, evidence-backed fault hypotheses.

Strict architectural invariants:
  - READ-ONLY: Never sends serial commands, clears DTCs, or actuates components.
  - LARGE-SCALE: Vectorized time-series analysis handling 100,000+ samples.
  - DETERMINISTIC: Zero LLM dependency in core truth, evidence, or ranking.
  - QUALITY GATE: Distinguishes physical vehicle faults from acquisition failures.
  - DTC-FREE CAPABILITY: Generates verified hypotheses even with 0 DTCs.
  - SCOPE BOUNDARY: Strictly analytical. Excludes G-4, G-5, H, and I.
=============================================================================
"""

from __future__ import annotations

import collections
import enum
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np

# Reusable quality and status constants from Phase C / G-1 / G-2
from motor import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
)
from advanced_ecu_services import (
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NRC,
    STATUS_SERIAL_ERROR,
    STATUS_TRANSACTION_CANCELLED as STATUS_CANCELLED,
    STATUS_RESPONSE_MISMATCH,
    STATUS_PARSE_ERROR,
)
from extended_did import (
    VehicleContext,
    StructuredDiagnosticEvidence,
    AcquisitionBatch,
)


# =====================================================================
# 1. ENUMERATIONS & TAXONOMY
# =====================================================================

class DataSourceType(str, enum.Enum):
    """Provenance type of an individual time-series sample or signal."""
    MEASURED = "MEASURED"
    ALIGNED = "ALIGNED"
    INTERPOLATED = "INTERPOLATED"
    AGGREGATED = "AGGREGATED"
    DERIVED = "DERIVED"


class SignalQuality(str, enum.Enum):
    """Standardized quality classification for diagnostic signals."""
    GOOD = "GOOD"
    SUSPECT = "SUSPECT"
    STALE = "STALE"
    INVALID = "INVALID"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_legacy(cls, quality_str: Optional[str]) -> "SignalQuality":
        if not quality_str:
            return cls.UNKNOWN
        q_up = quality_str.strip().upper()
        if q_up in ("GOOD", QUALITY_GOOD):
            return cls.GOOD
        if q_up in ("SUSPECT", QUALITY_SUSPECT):
            return cls.SUSPECT
        if q_up in ("STALE", QUALITY_STALE):
            return cls.STALE
        if q_up in ("INVALID", QUALITY_INVALID, QUALITY_IMPLAUSIBLE):
            return cls.INVALID
        if q_up in ("ERROR", QUALITY_ERROR):
            return cls.ERROR
        return cls.UNKNOWN


class OperatingCondition(str, enum.Enum):
    """Segmented engine/vehicle operational state."""
    STARTUP = "STARTUP"
    COLD_START = "COLD_START"
    WARM_UP = "WARM_UP"
    IDLE = "IDLE"
    LOW_RPM = "LOW_RPM"
    MEDIUM_RPM = "MEDIUM_RPM"
    HIGH_RPM = "HIGH_RPM"
    STEADY_CRUISE = "STEADY_CRUISE"
    ACCELERATION = "ACCELERATION"
    DECELERATION = "DECELERATION"
    HIGH_LOAD = "HIGH_LOAD"
    LOW_LOAD = "LOW_LOAD"
    THROTTLE_TRANSITION = "THROTTLE_TRANSITION"
    ENGINE_BRAKING = "ENGINE_BRAKING"
    SHUTDOWN = "SHUTDOWN"
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AnomalySeverity(str, enum.Enum):
    """Severity classification of an anomaly or finding."""
    INFO = "INFO"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AnomalyType(str, enum.Enum):
    """Taxonomy of detected diagnostic anomalies."""
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
    SUDDEN_SPIKE = "SUDDEN_SPIKE"
    SUDDEN_DROP = "SUDDEN_DROP"
    SENSOR_FLATLINE = "SENSOR_FLATLINE"
    SENSOR_DROPOUT = "SENSOR_DROPOUT"
    ABNORMAL_RATE_OF_CHANGE = "ABNORMAL_RATE_OF_CHANGE"
    PERSISTENT_DRIFT = "PERSISTENT_DRIFT"
    CONTROL_OSCILLATION = "CONTROL_OSCILLATION"
    WARMUP_DEFICIENCY = "WARMUP_DEFICIENCY"
    RESPONSE_DELAY = "RESPONSE_DELAY"
    RESPONSE_MISSING = "RESPONSE_MISSING"
    RESPONSE_INVERTED = "RESPONSE_INVERTED"
    CROSS_SENSOR_INCONSISTENCY = "CROSS_SENSOR_INCONSISTENCY"
    MULTIVARIATE_INCONSISTENCY = "MULTIVARIATE_INCONSISTENCY"
    MODEL_RESIDUAL_HIGH = "MODEL_RESIDUAL_HIGH"
    ACQUISITION_ANOMALY = "ACQUISITION_ANOMALY"


class HypothesisConfidence(str, enum.Enum):
    """Calibrated confidence of a fault hypothesis."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class DTCImpact(str, enum.Enum):
    """Relationship between a DTC and observed time-series evidence."""
    PRIMARY_CANDIDATE = "PRIMARY_CANDIDATE"
    SECONDARY_EFFECT = "SECONDARY_EFFECT"
    CORROBORATING_EVIDENCE = "CORROBORATING_EVIDENCE"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    HISTORICAL_UNVERIFIED = "HISTORICAL_UNVERIFIED"
    NEUTRAL = "NEUTRAL"


# =====================================================================
# 2. DATA MODELS & TIME SERIES CONTAINERS
# =====================================================================

@dataclass
class TimeSeriesSignal:
    """
    Vectorized representation of a single diagnostic signal across time.
    Uses contiguous numpy arrays for fast vectorized numerical operations.
    """
    signal_name: str
    unit: str
    timestamps: np.ndarray             # float64 timestamps (seconds)
    values: np.ndarray                 # float64 decoded values (np.nan for missing)
    raw_values: Optional[np.ndarray] = None   # Optional raw values/bytes
    qualities: Optional[np.ndarray] = None    # SignalQuality strings
    source_types: Optional[np.ndarray] = None # DataSourceType strings
    ecu_source: str = "7E0"
    definition_id: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.timestamps, np.ndarray):
            self.timestamps = np.asarray(self.timestamps, dtype=np.float64)
        if not isinstance(self.values, np.ndarray):
            self.values = np.asarray(self.values, dtype=np.float64)
        n = len(self.timestamps)
        if self.qualities is None:
            self.qualities = np.full(n, SignalQuality.GOOD.value, dtype=object)
        if self.source_types is None:
            self.source_types = np.full(n, DataSourceType.MEASURED.value, dtype=object)

    def __len__(self) -> int:
        return len(self.timestamps)

    @property
    def valid_mask(self) -> np.ndarray:
        """Returns boolean mask where values are not NaN and quality is GOOD or SUSPECT."""
        return ~np.isnan(self.values) & (self.qualities != SignalQuality.INVALID.value) & (self.qualities != SignalQuality.ERROR.value)

    @property
    def valid_values(self) -> np.ndarray:
        return self.values[self.valid_mask]

    @property
    def valid_timestamps(self) -> np.ndarray:
        return self.timestamps[self.valid_mask]

    def slice_window(self, start_time: float, end_time: float) -> "TimeSeriesSignal":
        """Returns a view/copy of this signal within [start_time, end_time]."""
        mask = (self.timestamps >= start_time) & (self.timestamps <= end_time)
        return TimeSeriesSignal(
            signal_name=self.signal_name,
            unit=self.unit,
            timestamps=self.timestamps[mask],
            values=self.values[mask],
            raw_values=self.raw_values[mask] if self.raw_values is not None else None,
            qualities=self.qualities[mask] if self.qualities is not None else None,
            source_types=self.source_types[mask] if self.source_types is not None else None,
            ecu_source=self.ecu_source,
            definition_id=self.definition_id,
        )

    def mean(self) -> float:
        v = self.valid_values
        return float(np.mean(v)) if len(v) > 0 else float("nan")

    def std(self) -> float:
        v = self.valid_values
        return float(np.std(v)) if len(v) > 1 else 0.0

    def min(self) -> float:
        v = self.valid_values
        return float(np.min(v)) if len(v) > 0 else float("nan")

    def max(self) -> float:
        v = self.valid_values
        return float(np.max(v)) if len(v) > 0 else float("nan")


@dataclass
class DTCRecord:
    """Representation of an active, pending, or historical Diagnostic Trouble Code."""
    code: str
    status: str = "CONFIRMED"
    first_timestamp: Optional[float] = None
    last_timestamp: Optional[float] = None
    ecu_source: str = "7E0"
    occurrence_count: int = 1
    freeze_frame: Dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None


@dataclass
class OperatingConditionSegment:
    """Contiguous time interval of a specific vehicle operating condition."""
    condition: OperatingCondition
    start_time: float
    end_time: float
    duration: float
    confidence: float = 1.0
    signals_used: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticDataSet:
    """
    Top-level diagnostic container containing synchronized time-series signals,
    DTC history, session provenance, and vehicle configuration context.
    """
    dataset_id: str
    vehicle_context: Optional[VehicleContext] = None
    signals: Dict[str, TimeSeriesSignal] = field(default_factory=dict)
    dtc_records: List[DTCRecord] = field(default_factory=list)
    session_start_time: float = 0.0
    session_end_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_signal(self, signal: TimeSeriesSignal) -> None:
        self.signals[signal.signal_name.strip().upper()] = signal
        if len(signal.timestamps) > 0:
            t_min = float(signal.timestamps[0])
            t_max = float(signal.timestamps[-1])
            self.session_start_time = min(self.session_start_time or t_min, t_min)
            self.session_end_time = max(self.session_end_time or t_max, t_max)

    def get_signal(self, signal_name: str) -> Optional[TimeSeriesSignal]:
        return self.signals.get(signal_name.strip().upper())

    def get_coverage_report(self) -> Dict[str, Any]:
        """Calculates data coverage, missing signal analysis, and duration."""
        duration = max(0.0, self.session_end_time - self.session_start_time)
        signal_reports = {}
        for name, sig in self.signals.items():
            n_total = len(sig)
            n_valid = int(np.sum(sig.valid_mask))
            coverage_pct = (n_valid / n_total * 100.0) if n_total > 0 else 0.0
            signal_reports[name] = {
                "total_samples": n_total,
                "valid_samples": n_valid,
                "coverage_pct": round(coverage_pct, 2),
                "unit": sig.unit,
                "mean": round(sig.mean(), 2) if not math.isnan(sig.mean()) else None,
                "min": round(sig.min(), 2) if not math.isnan(sig.min()) else None,
                "max": round(sig.max(), 2) if not math.isnan(sig.max()) else None,
            }

        return {
            "dataset_id": self.dataset_id,
            "session_start_time": self.session_start_time,
            "session_end_time": self.session_end_time,
            "duration_seconds": round(duration, 3),
            "signal_count": len(self.signals),
            "signals": signal_reports,
            "dtc_count": len(self.dtc_records),
            "vehicle_context": {
                "manufacturer": self.vehicle_context.manufacturer if self.vehicle_context else None,
                "model": self.vehicle_context.model if self.vehicle_context else None,
                "engine_code": self.vehicle_context.engine_code if self.vehicle_context else None,
            } if self.vehicle_context else None,
        }

    @classmethod
    def from_dataframe(
        cls,
        df: Any,
        time_column: str = "timestamp",
        vehicle_context: Optional[VehicleContext] = None,
        dtcs: Optional[List[DTCRecord]] = None,
        dataset_id: Optional[str] = None,
    ) -> "DiagnosticDataSet":
        """Builds a DiagnosticDataSet from a pandas DataFrame."""
        ds_id = dataset_id or f"DS-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        dataset = cls(dataset_id=ds_id, vehicle_context=vehicle_context, dtc_records=dtcs or [])
        if time_column not in df.columns:
            raise ValueError(f"Time column '{time_column}' not found in DataFrame columns")

        ts_array = df[time_column].to_numpy(dtype=np.float64)
        for col in df.columns:
            if col == time_column:
                continue
            vals = df[col].to_numpy(dtype=np.float64)
            sig = TimeSeriesSignal(
                signal_name=col,
                unit="",
                timestamps=ts_array,
                values=vals,
            )
            dataset.add_signal(sig)
        return dataset

    @classmethod
    def from_records(
        cls,
        records: Sequence[Dict[str, Any]],
        time_key: str = "timestamp",
        vehicle_context: Optional[VehicleContext] = None,
        dataset_id: Optional[str] = None,
    ) -> "DiagnosticDataSet":
        """Builds a DiagnosticDataSet from a sequence of flat dictionary records."""
        ds_id = dataset_id or f"DS-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        dataset = cls(dataset_id=ds_id, vehicle_context=vehicle_context)
        if not records:
            return dataset

        timestamps = [r.get(time_key, 0.0) for r in records]
        keys = set()
        for r in records:
            keys.update(r.keys())
        keys.discard(time_key)

        ts_array = np.asarray(timestamps, dtype=np.float64)
        for k in keys:
            vals = [float(r[k]) if r.get(k) is not None and not math.isnan(float(r[k])) else np.nan for r in records]
            dataset.add_signal(TimeSeriesSignal(
                signal_name=k,
                unit="",
                timestamps=ts_array,
                values=np.asarray(vals, dtype=np.float64),
            ))
        return dataset

    @classmethod
    def from_acquisition_batches(
        cls,
        batches: Sequence[AcquisitionBatch],
        vehicle_context: Optional[VehicleContext] = None,
        dataset_id: Optional[str] = None,
    ) -> "DiagnosticDataSet":
        """Converts a sequence of Phase G-2 AcquisitionBatch snapshots into a time-series dataset."""
        ds_id = dataset_id or f"DS-BATCHES-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        dataset = cls(dataset_id=ds_id, vehicle_context=vehicle_context)
        if not batches:
            return dataset

        # Group evidence by signal identifier
        signal_data: Dict[str, Dict[str, list]] = collections.defaultdict(
            lambda: {"timestamps": [], "values": [], "qualities": [], "units": [], "sources": []}
        )

        for b in batches:
            t = (b.start_time + b.end_time) / 2.0
            for ident, ev in b.evidence.items():
                val = ev.decoded_value
                unit = ev.unit or ""
                q = SignalQuality.from_legacy(ev.quality).value
                # If composite multi-field, also unpack individual fields
                if ev.fields:
                    for f_name, f_obj in ev.fields.items():
                        full_name = f"{ident}_{f_name}".upper()
                        f_val = f_obj.decoded_value if f_obj.is_valid else np.nan
                        signal_data[full_name]["timestamps"].append(t)
                        signal_data[full_name]["values"].append(float(f_val) if isinstance(f_val, (int, float)) else np.nan)
                        signal_data[full_name]["qualities"].append(q if f_obj.is_valid else SignalQuality.INVALID.value)
                        signal_data[full_name]["units"].append(f_obj.unit or "")
                        signal_data[full_name]["sources"].append(DataSourceType.MEASURED.value)

                # Primary identifier signal
                num_val = float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else np.nan
                signal_data[ident.upper()]["timestamps"].append(t)
                signal_data[ident.upper()]["values"].append(num_val)
                signal_data[ident.upper()]["qualities"].append(q)
                signal_data[ident.upper()]["units"].append(unit)
                signal_data[ident.upper()]["sources"].append(DataSourceType.MEASURED.value)

        for s_name, data in signal_data.items():
            primary_unit = data["units"][0] if data["units"] else ""
            dataset.add_signal(TimeSeriesSignal(
                signal_name=s_name,
                unit=primary_unit,
                timestamps=np.asarray(data["timestamps"], dtype=np.float64),
                values=np.asarray(data["values"], dtype=np.float64),
                qualities=np.asarray(data["qualities"], dtype=object),
                source_types=np.asarray(data["sources"], dtype=object),
            ))
        return dataset


# =====================================================================
# 3. ANOMALY & EVIDENCE DATA MODELS
# =====================================================================

@dataclass
class PointAnomaly:
    """Individual or localized point anomaly."""
    anomaly_id: str
    anomaly_type: AnomalyType
    signal_name: str
    timestamp: float
    observed_value: float
    expected_range: Tuple[Optional[float], Optional[float]]
    severity: AnomalySeverity
    details: str
    is_acquisition_fault: bool = False
    operating_condition: OperatingCondition = OperatingCondition.UNKNOWN


@dataclass
class TemporalAnomaly:
    """Temporal or patterned anomaly spanning a time window."""
    anomaly_id: str
    anomaly_type: AnomalyType
    signal_name: str
    start_time: float
    end_time: float
    duration: float
    magnitude: float
    baseline_value: float
    peak_value: float
    recovery_time: Optional[float] = None
    occurrence_count: int = 1
    operating_condition: OperatingCondition = OperatingCondition.UNKNOWN
    severity: AnomalySeverity = AnomalySeverity.WARNING
    confidence: float = 0.8
    details: str = ""
    is_acquisition_fault: bool = False


@dataclass
class LagMeasurement:
    """Temporal lag evaluation between a driver event and follower sensor response."""
    driver_signal: str
    response_signal: str
    event_time: float
    driver_transition_magnitude: float
    observed_lag_s: float
    expected_lag_s: float
    delay_error_s: float
    status: str  # NORMAL, DELAYED, MISSING, INSUFFICIENT, INVERTED
    confidence: float = 0.85
    details: str = ""


@dataclass
class EvidenceSnippet:
    """Compact time window slice pinpointing exact diagnostic evidence for technicians."""
    start_timestamp: float
    end_timestamp: float
    duration_s: float
    primary_signals: List[str]
    observed_summary: Dict[str, Any]
    operating_condition: OperatingCondition


@dataclass
class FaultEvidence:
    """Structured diagnostic evidence unit supporting or contradicting a hypothesis."""
    evidence_id: str
    title: str
    signals: List[str]
    start_time: float
    end_time: float
    duration: float
    operating_condition: OperatingCondition
    observed_behavior: str
    expected_behavior: str
    deviation_magnitude: float
    severity: AnomalySeverity
    quality: SignalQuality
    provenance: Dict[str, Any]
    analysis_method: str
    confidence_score: float
    supporting_observations: List[str] = field(default_factory=list)
    contradicting_observations: List[str] = field(default_factory=list)
    snippet: Optional[EvidenceSnippet] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "signals": self.signals,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "operating_condition": self.operating_condition.value,
            "observed_behavior": self.observed_behavior,
            "expected_behavior": self.expected_behavior,
            "deviation_magnitude": round(self.deviation_magnitude, 3),
            "severity": self.severity.value,
            "quality": self.quality.value,
            "analysis_method": self.analysis_method,
            "confidence_score": round(self.confidence_score, 2),
            "supporting_observations": self.supporting_observations,
            "contradicting_observations": self.contradicting_observations,
        }


@dataclass
class DTCCorrelation:
    """Structured correlation between a DTC and observed time-series behavior."""
    dtc_code: str
    status: str
    impact: DTCImpact
    supporting_signals: List[str]
    contradicting_signals: List[str]
    supporting_anomalies: List[str]
    temporal_proximity_s: Optional[float]
    operating_condition: OperatingCondition
    notes: str


@dataclass
class FaultHypothesis:
    """
    Structured fault hypothesis produced by Phase G-3.
    Explicitly tracks supporting evidence, contradicting evidence,
    DTC associations, and calibrated confidence.
    """
    hypothesis_id: str
    title: str
    category: str
    affected_system: str
    supporting_evidence: List[FaultEvidence] = field(default_factory=list)
    contradicting_evidence: List[FaultEvidence] = field(default_factory=list)
    evidence_score: float = 0.0
    confidence: HypothesisConfidence = HypothesisConfidence.INSUFFICIENT
    severity: AnomalySeverity = AnomalySeverity.WARNING
    occurrence_count: int = 1
    operating_conditions: List[OperatingCondition] = field(default_factory=list)
    first_occurrence: float = 0.0
    last_occurrence: float = 0.0
    dtc_associations: List[str] = field(default_factory=list)
    is_dtc_free: bool = False
    possible_root_causes: List[str] = field(default_factory=list)
    alternative_explanations: List[str] = field(default_factory=list)
    required_additional_evidence: List[str] = field(default_factory=list)
    recommended_test_reference: Optional[str] = None
    is_inconclusive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "title": self.title,
            "category": self.category,
            "affected_system": self.affected_system,
            "confidence": self.confidence.value,
            "severity": self.severity.value,
            "evidence_score": round(self.evidence_score, 2),
            "occurrence_count": self.occurrence_count,
            "operating_conditions": [c.value for c in self.operating_conditions],
            "dtc_associations": self.dtc_associations,
            "is_dtc_free": self.is_dtc_free,
            "is_inconclusive": self.is_inconclusive,
            "supporting_evidence_ids": [e.evidence_id for e in self.supporting_evidence],
            "contradicting_evidence_ids": [e.evidence_id for e in self.contradicting_evidence],
            "possible_root_causes": self.possible_root_causes,
            "alternative_explanations": self.alternative_explanations,
            "required_additional_evidence": self.required_additional_evidence,
            "recommended_test_reference": self.recommended_test_reference,
        }


@dataclass
class AnalysisResult:
    """Comprehensive, serializable result container of the G-3 diagnostic pipeline."""
    analysis_id: str
    dataset_id: str
    vehicle_context: Optional[Dict[str, Any]] = None
    session_start_time: float = 0.0
    session_end_time: float = 0.0
    duration_seconds: float = 0.0
    coverage_report: Dict[str, Any] = field(default_factory=dict)
    quality_summary: Dict[str, int] = field(default_factory=dict)
    operating_condition_summary: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Union[PointAnomaly, TemporalAnomaly]] = field(default_factory=list)
    evidence: List[FaultEvidence] = field(default_factory=list)
    dtc_correlations: List[DTCCorrelation] = field(default_factory=list)
    hypotheses: List[FaultHypothesis] = field(default_factory=list)
    explanations: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "dataset_id": self.dataset_id,
            "vehicle_context": self.vehicle_context,
            "duration_seconds": round(self.duration_seconds, 3),
            "coverage_report": self.coverage_report,
            "quality_summary": self.quality_summary,
            "operating_condition_summary": self.operating_condition_summary,
            "anomalies_count": len(self.anomalies),
            "evidence_count": len(self.evidence),
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "dtc_correlations": [
                {
                    "dtc": c.dtc_code,
                    "impact": c.impact.value,
                    "condition": c.operating_condition.value,
                    "notes": c.notes,
                }
                for c in self.dtc_correlations
            ],
            "explanations": self.explanations,
            "warnings": self.warnings,
            "provenance": self.provenance,
        }


# =====================================================================
# 4. TIME ALIGNMENT & DATA QUALITY GATE
# =====================================================================

class DataQualityGate:
    """
    Ensures that low-quality, stale, or communication-error samples do not
    poison high-confidence vehicle diagnostic hypotheses.
    """
    @classmethod
    def filter_and_classify(cls, dataset: DiagnosticDataSet) -> Dict[str, int]:
        """
        Classifies quality across all signals and counts distribution.
        Missing data is preserved as NaN, never silently converted to zero.
        """
        quality_counts = {
            SignalQuality.GOOD.value: 0,
            SignalQuality.SUSPECT.value: 0,
            SignalQuality.STALE.value: 0,
            SignalQuality.INVALID.value: 0,
            SignalQuality.ERROR.value: 0,
            SignalQuality.UNKNOWN.value: 0,
        }

        for sig in dataset.signals.values():
            if sig.qualities is None:
                continue
            for q in sig.qualities:
                if q in quality_counts:
                    quality_counts[q] += 1
                else:
                    quality_counts[SignalQuality.UNKNOWN.value] += 1
        return quality_counts


class TimeSeriesAligner:
    """
    Aligns asynchronous diagnostic signals onto a common uniform timestamp grid
    using nearest-neighbor matching within a strict tolerance window.
    Strictly tags aligned/interpolated values so synthetic precision is never fabricated.
    """
    @classmethod
    def align_signals(
        cls,
        signals: Dict[str, TimeSeriesSignal],
        target_frequency_hz: float = 10.0,
        max_tolerance_s: float = 0.25,
    ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Returns:
          - common_timestamps: 1D array of uniform timestamps.
          - aligned_values: Dict of signal_name -> 1D array of values.
          - source_types: Dict of signal_name -> 1D array of DataSourceType strings.
        """
        if not signals:
            return np.array([]), {}, {}

        # Determine global overlapping time window
        starts = [s.timestamps[0] for s in signals.values() if len(s.timestamps) > 0]
        ends = [s.timestamps[-1] for s in signals.values() if len(s.timestamps) > 0]
        if not starts or not ends:
            return np.array([]), {}, {}

        t_min = max(starts)
        t_max = min(ends)
        if t_max <= t_min:
            # Fallback to total span if asynchronous intervals do not overlap strictly
            t_min = min(starts)
            t_max = max(ends)

        dt = 1.0 / target_frequency_hz
        common_ts = np.arange(t_min, t_max + dt / 2.0, dt, dtype=np.float64)
        n_points = len(common_ts)

        aligned_values: Dict[str, np.ndarray] = {}
        source_types: Dict[str, np.ndarray] = {}

        for name, sig in signals.items():
            out_vals = np.full(n_points, np.nan, dtype=np.float64)
            out_types = np.full(n_points, DataSourceType.DERIVED.value, dtype=object)

            if len(sig.timestamps) == 0:
                aligned_values[name] = out_vals
                source_types[name] = out_types
                continue

            # Vectorized nearest-neighbor search using searchsorted
            idx = np.searchsorted(sig.timestamps, common_ts)
            idx = np.clip(idx, 0, len(sig.timestamps) - 1)
            left_idx = np.maximum(0, idx - 1)

            dist_right = np.abs(sig.timestamps[idx] - common_ts)
            dist_left = np.abs(sig.timestamps[left_idx] - common_ts)

            best_idx = np.where(dist_left < dist_right, left_idx, idx)
            best_dist = np.minimum(dist_left, dist_right)

            within_tol = best_dist <= max_tolerance_s
            out_vals[within_tol] = sig.values[best_idx[within_tol]]
            out_types[within_tol] = np.where(
                best_dist[within_tol] < 1e-4,
                DataSourceType.MEASURED.value,
                DataSourceType.ALIGNED.value,
            )

            aligned_values[name] = out_vals
            source_types[name] = out_types

        return common_ts, aligned_values, source_types


# =====================================================================
# 5. OPERATING CONDITION SEGMENTER
# =====================================================================

class OperatingConditionSegmenter:
    """
    Partitions vehicle time-series logs into distinct operating condition intervals
    (Cold Start, Warm-Up, Idle, Cruise, Acceleration, High Load, etc.).
    """
    @classmethod
    def segment(
        cls,
        dataset: DiagnosticDataSet,
        window_size_s: float = 1.0,
    ) -> List[OperatingConditionSegment]:
        rpm_sig = dataset.get_signal("RPM")
        speed_sig = dataset.get_signal("SPEED")
        tps_sig = dataset.get_signal("TPS") or dataset.get_signal("THROTTLE")
        ect_sig = dataset.get_signal("ECT")
        load_sig = dataset.get_signal("LOAD") or dataset.get_signal("ENGINE_LOAD")
        map_sig = dataset.get_signal("MAP")

        if not rpm_sig or len(rpm_sig) == 0:
            # Cannot segment operating conditions without engine speed
            dur = max(0.0, dataset.session_end_time - dataset.session_start_time)
            return [OperatingConditionSegment(
                condition=OperatingCondition.UNKNOWN,
                start_time=dataset.session_start_time,
                end_time=dataset.session_end_time,
                duration=dur,
                confidence=0.0,
                signals_used=[],
                details={"reason": "Missing RPM signal"},
            )]

        # Time grid alignment for segmentation signals
        seg_signals = {}
        for s in [rpm_sig, speed_sig, tps_sig, ect_sig, load_sig, map_sig]:
            if s is not None and len(s) > 0:
                seg_signals[s.signal_name] = s

        grid_ts, aligned_vals, _ = TimeSeriesAligner.align_signals(
            seg_signals, target_frequency_hz=5.0, max_tolerance_s=1.0
        )

        n = len(grid_ts)
        if n == 0:
            return []

        rpms = aligned_vals.get(rpm_sig.signal_name, np.zeros(n))
        speeds = aligned_vals.get(speed_sig.signal_name, np.zeros(n)) if speed_sig else np.zeros(n)
        tps = aligned_vals.get(tps_sig.signal_name, np.zeros(n)) if tps_sig else np.zeros(n)
        ects = aligned_vals.get(ect_sig.signal_name, np.full(n, 85.0)) if ect_sig else np.full(n, 85.0)
        loads = aligned_vals.get(load_sig.signal_name, np.zeros(n)) if load_sig else np.zeros(n)
        maps = aligned_vals.get(map_sig.signal_name, np.zeros(n)) if map_sig else np.zeros(n)

        # Derivatives
        dt = np.gradient(grid_ts)
        dt = np.where(dt <= 0, 0.2, dt)
        d_speed = np.gradient(speeds) / dt
        d_tps = np.gradient(tps) / dt

        # Point-wise classification
        point_conditions = []
        for i in range(n):
            r = rpms[i]
            s = speeds[i]
            th = tps[i]
            e = ects[i]
            ld = loads[i]
            mp = maps[i]
            dsp = d_speed[i]
            dth = d_tps[i]

            if math.isnan(r) or r < 50:
                c = OperatingCondition.SHUTDOWN if i > 0 and rpms[i-1] >= 400 else OperatingCondition.UNKNOWN
            elif e < 45.0 and (grid_ts[i] - grid_ts[0]) < 120.0:
                c = OperatingCondition.COLD_START
            elif e < 75.0:
                c = OperatingCondition.WARM_UP
            elif r < 1100 and s < 3.0 and th < 6.0:
                c = OperatingCondition.IDLE
            elif dth > 15.0 or (dsp > 3.0 and th > 15.0):
                c = OperatingCondition.ACCELERATION
            elif dsp < -3.0 and th < 4.0:
                c = OperatingCondition.DECELERATION
            elif th < 2.0 and s > 25.0 and r > 1500:
                c = OperatingCondition.ENGINE_BRAKING
            elif ld > 75.0 or mp > 80.0:
                c = OperatingCondition.HIGH_LOAD
            elif s > 35.0 and abs(dsp) < 1.5 and abs(dth) < 5.0:
                c = OperatingCondition.STEADY_CRUISE
            elif r >= 3800:
                c = OperatingCondition.HIGH_RPM
            elif r >= 2000:
                c = OperatingCondition.MEDIUM_RPM
            elif r >= 1000:
                c = OperatingCondition.LOW_RPM
            else:
                c = OperatingCondition.UNKNOWN
            point_conditions.append(c)

        # Group contiguous segments
        segments: List[OperatingConditionSegment] = []
        cur_cond = point_conditions[0]
        cur_start = grid_ts[0]

        for i in range(1, n):
            if point_conditions[i] != cur_cond:
                t_end = grid_ts[i-1]
                segments.append(OperatingConditionSegment(
                    condition=cur_cond,
                    start_time=cur_start,
                    end_time=t_end,
                    duration=max(0.0, t_end - cur_start),
                    signals_used=list(seg_signals.keys()),
                ))
                cur_cond = point_conditions[i]
                cur_start = grid_ts[i]

        # Final segment
        t_final = grid_ts[-1]
        segments.append(OperatingConditionSegment(
            condition=cur_cond,
            start_time=cur_start,
            end_time=t_final,
            duration=max(0.0, t_final - cur_start),
            signals_used=list(seg_signals.keys()),
        ))
        return segments


# =====================================================================
# 6. POINT & TEMPORAL ANOMALY DETECTORS
# =====================================================================

class PointAnomalyDetector:
    """
    Detects instant or local anomalies: impossible physical values,
    sudden spikes/drops, flatlines (freeze), and serial dropouts.
    """
    PHYSICAL_LIMITS = {
        "RPM": (0.0, 9000.0),
        "SPEED": (0.0, 320.0),
        "ECT": (-40.0, 135.0),
        "IAT": (-40.0, 85.0),
        "MAP": (10.0, 260.0),
        "MAF": (0.0, 450.0),
        "TPS": (0.0, 100.0),
        "THROTTLE": (0.0, 100.0),
        "STFT": (-50.0, 50.0),
        "LTFT": (-50.0, 50.0),
        "O2": (0.0, 1.3),
        "O2_B1S1": (0.0, 1.3),
        "O2_B1S2": (0.0, 1.3),
        "VOLTAGE": (6.0, 18.0),
    }

    @classmethod
    def detect(cls, dataset: DiagnosticDataSet) -> List[PointAnomaly]:
        anomalies: List[PointAnomaly] = []

        for name, sig in dataset.signals.items():
            if len(sig) == 0:
                continue

            # 1. Physical limits check
            limits = cls.PHYSICAL_LIMITS.get(name)
            if limits:
                min_lim, max_lim = limits
                val_mask = sig.valid_mask
                v = sig.values[val_mask]
                ts = sig.timestamps[val_mask]

                bad_low = v < min_lim
                bad_high = v > max_lim

                for t_val, bad_val in zip(ts[bad_low], v[bad_low]):
                    anomalies.append(PointAnomaly(
                        anomaly_id=f"PANOM-{name}-LOW-{int(t_val*100)}",
                        anomaly_type=AnomalyType.VALUE_OUT_OF_RANGE,
                        signal_name=name,
                        timestamp=float(t_val),
                        observed_value=float(bad_val),
                        expected_range=limits,
                        severity=AnomalySeverity.CRITICAL if name in ("ECT", "RPM") else AnomalySeverity.WARNING,
                        details=f"{name} measurement ({bad_val:.1f} {sig.unit}) strictly below physical floor ({min_lim:.1f})",
                    ))

                for t_val, bad_val in zip(ts[bad_high], v[bad_high]):
                    anomalies.append(PointAnomaly(
                        anomaly_id=f"PANOM-{name}-HIGH-{int(t_val*100)}",
                        anomaly_type=AnomalyType.VALUE_OUT_OF_RANGE,
                        signal_name=name,
                        timestamp=float(t_val),
                        observed_value=float(bad_val),
                        expected_range=limits,
                        severity=AnomalySeverity.CRITICAL if name in ("ECT", "RPM") else AnomalySeverity.WARNING,
                        details=f"{name} measurement ({bad_val:.1f} {sig.unit}) strictly above physical ceiling ({max_lim:.1f})",
                    ))

            # 2. Sudden spikes/drops (isolated 1-2 sample transient impulses)
            if len(sig.valid_values) >= 5:
                vals = sig.valid_values
                ts = sig.valid_timestamps
                diffs = np.diff(vals)
                std_diff = np.std(diffs)
                mean_diff = np.mean(diffs)

                if std_diff > 1e-4:
                    spike_thresh = max(std_diff * 4.5, 20.0 if name == "RPM" else 15.0)
                    for i in range(len(diffs) - 1):
                        d1 = diffs[i]
                        d2 = diffs[i+1]
                        # Sharp impulse: jump up then immediate return down (or vice versa)
                        if abs(d1) > spike_thresh and (d1 * d2 < 0) and abs(d2) > spike_thresh * 0.7:
                            anom_type = AnomalyType.SUDDEN_SPIKE if d1 > 0 else AnomalyType.SUDDEN_DROP
                            anomalies.append(PointAnomaly(
                                anomaly_id=f"PANOM-{name}-SPIKE-{int(ts[i+1]*100)}",
                                anomaly_type=anom_type,
                                signal_name=name,
                                timestamp=float(ts[i+1]),
                                observed_value=float(vals[i+1]),
                                expected_range=(float(vals[i] - std_diff*2), float(vals[i] + std_diff*2)),
                                severity=AnomalySeverity.WARNING,
                                details=f"Isolated impulse {anom_type.value} of {d1:+.1f} {sig.unit} detected at t={ts[i+1]:.2f}s",
                            ))

            # 3. Communication / Acquisition dropouts
            if sig.qualities is not None:
                err_mask = (sig.qualities == SignalQuality.ERROR.value) | (sig.qualities == SignalQuality.INVALID.value)
                if np.any(err_mask):
                    for err_t in sig.timestamps[err_mask]:
                        anomalies.append(PointAnomaly(
                            anomaly_id=f"ACQ-ANOM-{name}-{int(err_t*100)}",
                            anomaly_type=AnomalyType.ACQUISITION_ANOMALY,
                            signal_name=name,
                            timestamp=float(err_t),
                            observed_value=0.0,
                            expected_range=(None, None),
                            severity=AnomalySeverity.INFO,
                            details=f"Transport acquisition failure / timeout logged for {name}",
                            is_acquisition_fault=True,
                        ))

        return anomalies


class TemporalAnomalyDetector:
    """
    Detects temporal patterns across time:
      - Sensor Flatline / Freeze during dynamic operation
      - Closed-Loop Oscillations / Hunting
      - Persistent Drift during steady cruise
      - Warm-Up Deficiencies
      - Intermittent Excursions
    """
    @classmethod
    def detect(
        cls,
        dataset: DiagnosticDataSet,
        segments: List[OperatingConditionSegment],
    ) -> List[TemporalAnomaly]:
        anomalies: List[TemporalAnomaly] = []

        rpm_sig = dataset.get_signal("RPM")
        dynamic_engine = (rpm_sig.std() > 150.0) if (rpm_sig and len(rpm_sig) > 10) else False

        for name, sig in dataset.signals.items():
            if len(sig) < 15:
                continue

            # 1. Sensor Flatline / Freeze Check
            # Signal has zero variance while the engine is dynamically operating
            if dynamic_engine and name in ("ECT", "MAP", "TPS", "MAF", "O2", "O2_B1S1", "SPEED"):
                vals = sig.valid_values
                ts = sig.valid_timestamps
                if len(vals) >= 20:
                    val_std = np.std(vals)
                    if val_std < 1e-5:
                        dur = float(ts[-1] - ts[0])
                        if dur >= 5.0:
                            anomalies.append(TemporalAnomaly(
                                anomaly_id=f"TANOM-{name}-FLATLINE",
                                anomaly_type=AnomalyType.SENSOR_FLATLINE,
                                signal_name=name,
                                start_time=float(ts[0]),
                                end_time=float(ts[-1]),
                                duration=dur,
                                magnitude=0.0,
                                baseline_value=float(vals[0]),
                                peak_value=float(vals[0]),
                                severity=AnomalySeverity.CRITICAL if name in ("ECT", "MAP") else AnomalySeverity.WARNING,
                                confidence=0.92,
                                details=f"{name} sensor flatlined at {vals[0]:.2f} {sig.unit} across {dur:.1f}s while engine operating state was dynamic",
                            ))

            # 2. Control Oscillation / Hunting Check (e.g. STFT hunting, Idle RPM hunting)
            if name in ("STFT", "RPM", "LTFT"):
                vals = sig.valid_values
                ts = sig.valid_timestamps
                if len(vals) >= 30:
                    dt = np.mean(np.diff(ts))
                    if dt > 0:
                        # Zero-crossing of mean-centered signal
                        v_zero = vals - np.mean(vals)
                        signs = np.sign(v_zero)
                        zero_crossings = np.sum(np.diff(signs) != 0)
                        dur = float(ts[-1] - ts[0])
                        freq = (zero_crossings / 2.0) / max(1.0, dur)
                        amp = np.std(vals) * 2.0

                        # Criteria for abnormal hunting: frequency between 0.2 Hz and 2.5 Hz with notable amplitude
                        is_hunting = False
                        if name == "STFT" and freq >= 0.2 and amp >= 12.0:
                            is_hunting = True
                        elif name == "RPM" and freq >= 0.3 and amp >= 180.0:
                            is_hunting = True

                        if is_hunting:
                            anomalies.append(TemporalAnomaly(
                                anomaly_id=f"TANOM-{name}-OSC",
                                anomaly_type=AnomalyType.CONTROL_OSCILLATION,
                                signal_name=name,
                                start_time=float(ts[0]),
                                end_time=float(ts[-1]),
                                duration=dur,
                                magnitude=float(amp),
                                baseline_value=float(np.mean(vals)),
                                peak_value=float(np.max(vals)),
                                severity=AnomalySeverity.WARNING,
                                confidence=0.88,
                                details=f"Unstable control oscillation in {name}: frequency ~{freq:.2f} Hz, amplitude ~{amp:.1f} {sig.unit}",
                            ))

            # 3. Persistent Drift during Steady Cruise / Idle
            for seg in segments:
                if seg.condition in (OperatingCondition.STEADY_CRUISE, OperatingCondition.IDLE) and seg.duration >= 10.0:
                    sub_sig = sig.slice_window(seg.start_time, seg.end_time)
                    if len(sub_sig.valid_values) >= 10:
                        v = sub_sig.valid_values
                        t = sub_sig.valid_timestamps
                        slope, _ = np.polyfit(t - t[0], v, 1)
                        total_drift = slope * (t[-1] - t[0])
                        # If drift is large for a sensor expected to be stationary
                        if name in ("STFT", "LTFT", "MAP") and abs(total_drift) >= 12.0:
                            anomalies.append(TemporalAnomaly(
                                anomaly_id=f"TANOM-{name}-DRIFT-{int(seg.start_time)}",
                                anomaly_type=AnomalyType.PERSISTENT_DRIFT,
                                signal_name=name,
                                start_time=float(seg.start_time),
                                end_time=float(seg.end_time),
                                duration=seg.duration,
                                magnitude=float(total_drift),
                                baseline_value=float(v[0]),
                                peak_value=float(v[-1]),
                                operating_condition=seg.condition,
                                severity=AnomalySeverity.WARNING,
                                confidence=0.82,
                                details=f"{name} exhibited persistent drift of {total_drift:+.1f} {sig.unit} across steady {seg.condition.value}",
                            ))

        # 4. Warm-Up Deficiency Check
        ect_sig = dataset.get_signal("ECT")
        if ect_sig and len(ect_sig.valid_values) >= 15:
            e_vals = ect_sig.valid_values
            e_ts = ect_sig.valid_timestamps
            total_dur = float(e_ts[-1] - e_ts[0])
            start_temp = float(e_vals[0])
            final_temp = float(e_vals[-1])
            # If engine operated > 240 seconds and started cold (<50C) but failed to reach 72C
            if start_temp < 50.0 and total_dur >= 240.0 and final_temp < 72.0:
                anomalies.append(TemporalAnomaly(
                    anomaly_id="TANOM-ECT-WARMUP-DEFICIENT",
                    anomaly_type=AnomalyType.WARMUP_DEFICIENCY,
                    signal_name="ECT",
                    start_time=float(e_ts[0]),
                    end_time=float(e_ts[-1]),
                    duration=total_dur,
                    magnitude=final_temp - start_temp,
                    baseline_value=start_temp,
                    peak_value=final_temp,
                    operating_condition=OperatingCondition.WARM_UP,
                    severity=AnomalySeverity.WARNING,
                    confidence=0.90,
                    details=f"Coolant temperature rose only {final_temp - start_temp:.1f}°C in {total_dur:.0f}s (reached {final_temp:.1f}°C, target >=80°C)",
                ))

        return anomalies


# =====================================================================
# 7. CROSS-SENSOR LAG & RESIDUAL ANALYZER
# =====================================================================

class CrossSensorAnalyzer:
    """
    Analyzes physical relationships and temporal delays between signals:
      - Throttle -> MAP / MAF response lag
      - Fuel Trim -> O2 sensor switching response lag
      - Speed-Density air mass model residuals
      - Idle vs Cruise fuel trim divergence (Vacuum Leak signature)
    """
    @classmethod
    def analyze_throttle_lag(
        cls,
        dataset: DiagnosticDataSet,
        expected_lag_s: float = 0.150,
        max_acceptable_lag_s: float = 0.350,
    ) -> List[LagMeasurement]:
        """Detects lag between a sharp throttle tip-in and the corresponding MAP response."""
        tps_sig = dataset.get_signal("TPS") or dataset.get_signal("THROTTLE")
        map_sig = dataset.get_signal("MAP")
        if not tps_sig or not map_sig or len(tps_sig) < 10 or len(map_sig) < 10:
            return []

        # Common 20Hz alignment for transient detection
        common_ts, aligned, _ = TimeSeriesAligner.align_signals(
            {tps_sig.signal_name: tps_sig, map_sig.signal_name: map_sig},
            target_frequency_hz=20.0,
            max_tolerance_s=0.25,
        )
        if len(common_ts) < 10:
            return []

        tps_vals = aligned[tps_sig.signal_name]
        map_vals = aligned[map_sig.signal_name]

        dt = np.gradient(common_ts)
        dt = np.where(dt <= 0, 0.05, dt)
        d_tps = np.gradient(tps_vals) / dt

        # Find sharp positive throttle transitions: d_tps > 40%/s
        tip_in_indices = np.where(d_tps > 40.0)[0]
        measurements: List[LagMeasurement] = []
        last_event_t = -10.0

        for idx in tip_in_indices:
            t0 = common_ts[idx]
            if t0 - last_event_t < 2.0:
                continue  # Debounce events within 2 seconds
            last_event_t = t0

            # Inspect follower window up to 1.5s after t0
            win_mask = (common_ts >= t0) & (common_ts <= t0 + 1.5)
            win_map = map_vals[win_mask]
            win_t = common_ts[win_mask]
            if len(win_map) < 3:
                continue

            base_map = map_vals[idx]
            peak_map = np.max(win_map)
            map_rise = peak_map - base_map

            if map_rise < 8.0:  # Minimum significant MAP response (kPa)
                measurements.append(LagMeasurement(
                    driver_signal=tps_sig.signal_name,
                    response_signal=map_sig.signal_name,
                    event_time=float(t0),
                    driver_transition_magnitude=float(d_tps[idx]),
                    observed_lag_s=1.5,
                    expected_lag_s=expected_lag_s,
                    delay_error_s=1.5 - expected_lag_s,
                    status="MISSING",
                    confidence=0.85,
                    details=f"MAP rose only {map_rise:.1f} kPa following throttle tip-in of {d_tps[idx]:.1f} %/s",
                ))
                continue

            # 63% rise time
            target_map = base_map + 0.63 * map_rise
            rise_indices = np.where(win_map >= target_map)[0]
            if len(rise_indices) > 0:
                t_resp = win_t[rise_indices[0]]
                obs_lag = max(0.0, float(t_resp - t0))
                stat = "DELAYED" if obs_lag > max_acceptable_lag_s else "NORMAL"
                measurements.append(LagMeasurement(
                    driver_signal=tps_sig.signal_name,
                    response_signal=map_sig.signal_name,
                    event_time=float(t0),
                    driver_transition_magnitude=float(d_tps[idx]),
                    observed_lag_s=obs_lag,
                    expected_lag_s=expected_lag_s,
                    delay_error_s=obs_lag - expected_lag_s,
                    status=stat,
                    confidence=0.90,
                    details=f"Throttle tip-in at t={t0:.2f}s: MAP reached 63% rise in {obs_lag*1000:.0f}ms (expected <= {expected_lag_s*1000:.0f}ms)",
                ))
        return measurements

    @classmethod
    def evaluate_fuel_trim_divergence(
        cls,
        dataset: DiagnosticDataSet,
        segments: List[OperatingConditionSegment],
    ) -> Dict[str, Any]:
        """
        Calculates fuel trim behavior across operating states:
        Vacuum leak signature: high positive trims at idle that normalize under cruise/load.
        Fuel delivery restriction signature: high positive trims at high load/cruise.
        """
        stft_sig = dataset.get_signal("STFT")
        ltft_sig = dataset.get_signal("LTFT")
        if not stft_sig and not ltft_sig:
            return {"status": "NO_DATA"}

        idle_trims = []
        cruise_trims = []
        high_load_trims = []

        for seg in segments:
            dur = seg.duration
            if dur < 2.0:
                continue

            # Collect available trims
            for sig in [stft_sig, ltft_sig]:
                if sig:
                    sub = sig.slice_window(seg.start_time, seg.end_time)
                    if len(sub.valid_values) > 0:
                        m = sub.mean()
                        if seg.condition == OperatingCondition.IDLE:
                            idle_trims.append(m)
                        elif seg.condition == OperatingCondition.STEADY_CRUISE:
                            cruise_trims.append(m)
                        elif seg.condition == OperatingCondition.HIGH_LOAD:
                            high_load_trims.append(m)

        mean_idle = float(np.mean(idle_trims)) if idle_trims else 0.0
        mean_cruise = float(np.mean(cruise_trims)) if cruise_trims else 0.0
        mean_load = float(np.mean(high_load_trims)) if high_load_trims else 0.0

        is_vacuum_leak = (mean_idle >= 14.0) and (mean_cruise <= 8.0) and (idle_trims is not None and len(idle_trims) > 0)
        is_fuel_delivery = (mean_load >= 15.0 or mean_cruise >= 15.0) and (mean_idle < 10.0)

        return {
            "status": "EVALUATED",
            "mean_idle_trim": round(mean_idle, 2),
            "mean_cruise_trim": round(mean_cruise, 2),
            "mean_high_load_trim": round(mean_load, 2),
            "is_vacuum_leak_pattern": is_vacuum_leak,
            "is_fuel_delivery_pattern": is_fuel_delivery,
            "idle_sample_count": len(idle_trims),
            "cruise_sample_count": len(cruise_trims),
        }

    @classmethod
    def evaluate_airflow_residual(
        cls,
        dataset: DiagnosticDataSet,
    ) -> Dict[str, Any]:
        """
        Speed-Density theoretical airflow estimation vs measured MAF:
        Theoretical MAF (g/s) ~ (RPM * Disp_L * VE * MAP_kPa) / (2 * 60 * 287 * (IAT_C + 273.15)) * 1000
        """
        maf_sig = dataset.get_signal("MAF")
        rpm_sig = dataset.get_signal("RPM")
        map_sig = dataset.get_signal("MAP")
        iat_sig = dataset.get_signal("IAT")

        if not maf_sig or not rpm_sig or not map_sig:
            return {"status": "INSUFFICIENT_SIGNALS"}

        # Use vehicle displacement if available, else standard 1.6L baseline
        disp_l = 1.6
        if dataset.vehicle_context:
            if getattr(dataset.vehicle_context, "displacement_liters", None) is not None:
                disp_l = dataset.vehicle_context.displacement_liters
            elif dataset.vehicle_context.metadata and "displacement_liters" in dataset.vehicle_context.metadata:
                disp_l = float(dataset.vehicle_context.metadata["displacement_liters"])

        common_ts, aligned, _ = TimeSeriesAligner.align_signals(
            {"MAF": maf_sig, "RPM": rpm_sig, "MAP": map_sig, "IAT": iat_sig} if iat_sig else {"MAF": maf_sig, "RPM": rpm_sig, "MAP": map_sig},
            target_frequency_hz=5.0,
            max_tolerance_s=0.5,
        )
        if len(common_ts) < 10:
            return {"status": "INSUFFICIENT_SAMPLES"}

        mafs = aligned["MAF"]
        rpms = aligned["RPM"]
        maps = aligned["MAP"]
        iats = aligned.get("IAT", np.full(len(common_ts), 25.0))

        # Filter valid running engine points
        valid_mask = ~np.isnan(mafs) & ~np.isnan(rpms) & ~np.isnan(maps) & (rpms >= 800) & (maps >= 25)
        if np.sum(valid_mask) < 5:
            return {"status": "INSUFFICIENT_VALID_POINTS"}

        v_maf = mafs[valid_mask]
        v_rpm = rpms[valid_mask]
        v_map = maps[valid_mask]
        v_iat_k = iats[valid_mask] + 273.15

        # Volumetric efficiency approximation (typically 0.75 - 0.85 for naturally aspirated)
        ve = 0.80
        # Theoretical mass airflow in g/s:
        # Air mass flow = (RPM / 120) * (Disp / 1000) * (MAP * 1000 / (287.058 * IAT_K)) * VE * 1000
        theoretical_maf = (v_rpm / 120.0) * (disp_l / 1000.0) * (v_map * 1000.0 / (287.058 * v_iat_k)) * ve * 1000.0

        residual = v_maf - theoretical_maf
        pct_error = (residual / theoretical_maf) * 100.0
        mean_pct_error = float(np.mean(pct_error))

        is_biased = abs(mean_pct_error) >= 25.0
        return {
            "status": "EVALUATED",
            "mean_measured_maf": round(float(np.mean(v_maf)), 2),
            "mean_theoretical_maf": round(float(np.mean(theoretical_maf)), 2),
            "mean_residual_pct": round(mean_pct_error, 1),
            "is_maf_biased": is_biased,
            "sample_count": int(np.sum(valid_mask)),
        }


# =====================================================================
# 8. DTC CORRELATION & DTC-FREE FAULT DETECTION
# =====================================================================

class DTCCorrelator:
    """
    Correlates Diagnostic Trouble Codes with time-series evidence.
    DTCs are treated as corroborating or secondary evidence, NEVER sole proof.
    Supports DTC-free fault detection when DTC count is zero.
    """
    DTC_SIGNAL_MAP = {
        "P0171": {"signals": ["STFT", "LTFT", "O2", "MAP", "MAF"], "expected_state": "LEAN"},
        "P0172": {"signals": ["STFT", "LTFT", "O2", "MAP", "MAF"], "expected_state": "RICH"},
        "P0101": {"signals": ["MAF", "MAP", "TPS", "RPM"], "expected_state": "AIRFLOW_ERROR"},
        "P0106": {"signals": ["MAP", "TPS", "RPM"], "expected_state": "MAP_ERROR"},
        "P0115": {"signals": ["ECT"], "expected_state": "COOLANT_SENSOR_ERROR"},
        "P0128": {"signals": ["ECT", "IAT", "SPEED"], "expected_state": "THERMOSTAT_ERROR"},
        "P0130": {"signals": ["O2", "O2_B1S1", "STFT"], "expected_state": "O2_CIRCUIT_ERROR"},
        "P0133": {"signals": ["O2", "O2_B1S1", "STFT"], "expected_state": "SLOW_O2_RESPONSE"},
        "P0300": {"signals": ["RPM", "STFT", "LTFT"], "expected_state": "RANDOM_MISFIRE"},
    }

    @classmethod
    def correlate(
        cls,
        dtc_records: List[DTCRecord],
        anomalies: List[Union[PointAnomaly, TemporalAnomaly]],
        fuel_trim_result: Dict[str, Any],
        lag_measurements: Optional[List[LagMeasurement]] = None,
    ) -> List[DTCCorrelation]:
        correlations: List[DTCCorrelation] = []
        lags = lag_measurements or []

        for record in dtc_records:
            code = record.code.strip().upper()
            rule = cls.DTC_SIGNAL_MAP.get(code)
            supporting_sigs = []
            contradicting_sigs = []
            supp_anoms = []
            impact = DTCImpact.NEUTRAL
            notes = ""

            # Check fuel trim DTCs (P0171 / P0172)
            if code == "P0171":
                mean_idle = fuel_trim_result.get("mean_idle_trim", 0.0)
                mean_cruise = fuel_trim_result.get("mean_cruise_trim", 0.0)
                if mean_idle >= 12.0 or mean_cruise >= 12.0:
                    impact = DTCImpact.PRIMARY_CANDIDATE
                    supporting_sigs = ["STFT", "LTFT"]
                    notes = f"P0171 (System Lean) strongly corroborated by elevated fuel trims (Idle: +{mean_idle:.1f}%, Cruise: +{mean_cruise:.1f}%)"
                elif mean_idle <= -10.0 or mean_cruise <= -10.0:
                    impact = DTCImpact.CONTRADICTORY_EVIDENCE
                    contradicting_sigs = ["STFT", "LTFT"]
                    notes = f"P0171 (System Lean) contradicted by current negative fuel trims ({mean_idle:.1f}%)"
                else:
                    impact = DTCImpact.CORROBORATING_EVIDENCE
                    notes = "P0171 present, trims mildly elevated or unconfirmed"

            elif code == "P0300":
                # If severe lean condition is present, misfire is likely secondary downstream effect
                mean_idle = fuel_trim_result.get("mean_idle_trim", 0.0)
                mean_cruise = fuel_trim_result.get("mean_cruise_trim", 0.0)
                if fuel_trim_result.get("is_vacuum_leak_pattern") or mean_idle >= 10.0 or mean_cruise >= 10.0:
                    impact = DTCImpact.SECONDARY_EFFECT
                    supporting_sigs = ["STFT", "LTFT", "RPM"]
                    notes = "P0300 random misfire is likely a secondary consequence of severe air/fuel lean imbalance"
                else:
                    impact = DTCImpact.PRIMARY_CANDIDATE
                    notes = "P0300 primary ignition/cylinder anomaly"

            elif code == "P0133":
                # Check for O2 lag anomalies
                o2_lags = [m for m in lags if "O2" in m.response_signal and m.status == "DELAYED"]
                if o2_lags:
                    impact = DTCImpact.PRIMARY_CANDIDATE
                    supporting_sigs = ["O2"]
                    supp_anoms.append("DELAYED_O2_RESPONSE")
                    notes = f"P0133 slow O2 response confirmed by measured lag of {o2_lags[0].observed_lag_s*1000:.0f}ms"
                else:
                    impact = DTCImpact.CORROBORATING_EVIDENCE
                    notes = "P0133 stored without distinct transient lag captured"

            else:
                # Generic anomaly check for matching signal
                matched = [a for a in anomalies if rule and a.signal_name in rule.get("signals", [])]
                if matched:
                    impact = DTCImpact.CORROBORATING_EVIDENCE
                    supporting_sigs = list({a.signal_name for a in matched})
                    supp_anoms = [a.anomaly_id for a in matched[:3]]
                    notes = f"DTC {code} corroborated by {len(matched)} active signal anomalies"
                else:
                    impact = DTCImpact.HISTORICAL_UNVERIFIED
                    notes = f"DTC {code} present but no direct real-time signal violation observed in this session"

            correlations.append(DTCCorrelation(
                dtc_code=code,
                status=record.status,
                impact=impact,
                supporting_signals=supporting_sigs,
                contradicting_signals=contradicting_sigs,
                supporting_anomalies=supp_anoms,
                temporal_proximity_s=0.0,
                operating_condition=OperatingCondition.UNKNOWN,
                notes=notes,
            ))
        return correlations


# =====================================================================
# 9. EVIDENCE BUILDER, HYPOTHESIS GENERATOR & RANKING
# =====================================================================

class EvidenceBuilder:
    """
    Transforms detected anomalies, cross-sensor lag measurements, and
    segmented conditions into structured, inspectable FaultEvidence units.
    """
    @classmethod
    def build_evidence(
        cls,
        anomalies: List[Union[PointAnomaly, TemporalAnomaly]],
        lag_measurements: List[LagMeasurement],
        fuel_trim_analysis: Dict[str, Any],
        airflow_analysis: Dict[str, Any],
    ) -> List[FaultEvidence]:
        evidence_list: List[FaultEvidence] = []
        ev_counter = 0

        # 1. Vacuum Leak / Fuel Trim Divergence Evidence
        if fuel_trim_analysis.get("is_vacuum_leak_pattern"):
            ev_counter += 1
            idle_val = fuel_trim_analysis.get("mean_idle_trim", 0.0)
            cruise_val = fuel_trim_analysis.get("mean_cruise_trim", 0.0)
            evidence_list.append(FaultEvidence(
                evidence_id=f"EV-VACUUM-LEAK-{ev_counter:03d}",
                title="Fuel trim divergence between idle and cruise",
                signals=["STFT", "LTFT", "RPM", "MAP"],
                start_time=0.0,
                end_time=0.0,
                duration=0.0,
                operating_condition=OperatingCondition.IDLE,
                observed_behavior=f"Elevated positive trim at warm idle (+{idle_val:.1f}%) normalizing during cruise (+{cruise_val:.1f}%)",
                expected_behavior="Fuel trim corrections remain balanced across all loads (within +/- 8%)",
                deviation_magnitude=abs(idle_val - cruise_val),
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={"source": "CrossSensorAnalyzer.evaluate_fuel_trim_divergence"},
                analysis_method="OPERATING_CONDITION_FUEL_TRIM_COMPARISON",
                confidence_score=0.92,
                supporting_observations=[
                    f"Idle fuel correction elevated: +{idle_val:.1f}%",
                    f"Correction attenuates under load: +{cruise_val:.1f}%",
                    "Behavior matches unmetered air entering post-throttle",
                ],
                contradicting_observations=[],
            ))

        # 2. Fuel Delivery Restriction Evidence
        if fuel_trim_analysis.get("is_fuel_delivery_pattern"):
            ev_counter += 1
            load_val = fuel_trim_analysis.get("mean_high_load_trim", 0.0)
            evidence_list.append(FaultEvidence(
                evidence_id=f"EV-FUEL-RESTRICTION-{ev_counter:03d}",
                title="Fuel trim escalation under high engine load",
                signals=["STFT", "LTFT", "LOAD", "RPM"],
                start_time=0.0,
                end_time=0.0,
                duration=0.0,
                operating_condition=OperatingCondition.HIGH_LOAD,
                observed_behavior=f"Fuel trims climb sharply (+{load_val:.1f}%) under high load/RPM demand",
                expected_behavior="Fuel trims remain stable without starving at wide open throttle",
                deviation_magnitude=load_val,
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={"source": "CrossSensorAnalyzer.evaluate_fuel_trim_divergence"},
                analysis_method="LOAD_FUELING_SATURATION_CHECK",
                confidence_score=0.88,
                supporting_observations=[f"Fuel demand unfulfilled under load (+{load_val:.1f}%)"],
                contradicting_observations=[],
            ))

        # 3. MAF Scaling / Calibration Bias Evidence
        if airflow_analysis.get("is_maf_biased"):
            ev_counter += 1
            res_pct = airflow_analysis.get("mean_residual_pct", 0.0)
            meas_maf = airflow_analysis.get("mean_measured_maf", 0.0)
            theo_maf = airflow_analysis.get("mean_theoretical_maf", 0.0)
            evidence_list.append(FaultEvidence(
                evidence_id=f"EV-MAF-BIAS-{ev_counter:03d}",
                title="Mass Air Flow measurement deviates from Speed-Density model",
                signals=["MAF", "MAP", "RPM", "IAT"],
                start_time=0.0,
                end_time=0.0,
                duration=0.0,
                operating_condition=OperatingCondition.STEADY_CRUISE,
                observed_behavior=f"Measured MAF ({meas_maf:.1f} g/s) differs from theoretical model ({theo_maf:.1f} g/s) by {res_pct:+.1f}%",
                expected_behavior="Measured MAF aligns within +/- 15% of physical volumetric model",
                deviation_magnitude=abs(res_pct),
                severity=AnomalySeverity.WARNING,
                quality=SignalQuality.GOOD,
                provenance={"source": "CrossSensorAnalyzer.evaluate_airflow_residual"},
                analysis_method="SPEED_DENSITY_RESIDUAL_MODEL",
                confidence_score=0.85,
                supporting_observations=[f"Systematic MAF residual of {res_pct:+.1f}% across multiple operating points"],
                contradicting_observations=[],
            ))

        # 4. Sensor Lag / Delay Evidence
        for lag in lag_measurements:
            if lag.status in ("DELAYED", "MISSING"):
                ev_counter += 1
                evidence_list.append(FaultEvidence(
                    evidence_id=f"EV-LAG-{lag.driver_signal}-{lag.response_signal}-{ev_counter:03d}",
                    title=f"Dynamic response delay: {lag.driver_signal} -> {lag.response_signal}",
                    signals=[lag.driver_signal, lag.response_signal],
                    start_time=lag.event_time,
                    end_time=lag.event_time + lag.observed_lag_s,
                    duration=lag.observed_lag_s,
                    operating_condition=OperatingCondition.ACCELERATION,
                    observed_behavior=f"{lag.response_signal} response delayed by {lag.observed_lag_s*1000:.0f}ms (error: {lag.delay_error_s*1000:+.0f}ms)",
                    expected_behavior=f"Response within {lag.expected_lag_s*1000:.0f}ms of driver transition",
                    deviation_magnitude=lag.delay_error_s,
                    severity=AnomalySeverity.WARNING,
                    quality=SignalQuality.GOOD,
                    provenance={"source": "CrossSensorAnalyzer.analyze_throttle_lag"},
                    analysis_method="STEP_RESPONSE_LAG_ANALYSIS",
                    confidence_score=lag.confidence,
                    supporting_observations=[lag.details],
                    contradicting_observations=[],
                ))

        # 5. Temporal / Point Anomalies as Evidence
        for anom in anomalies:
            if anom.is_acquisition_fault:
                continue  # Acquisition dropouts do NOT become vehicle fault evidence!

            ev_counter += 1
            if isinstance(anom, TemporalAnomaly):
                evidence_list.append(FaultEvidence(
                    evidence_id=f"EV-TANOM-{anom.signal_name}-{anom.anomaly_type.value}-{ev_counter:03d}",
                    title=f"Temporal anomaly in {anom.signal_name}: {anom.anomaly_type.value}",
                    signals=[anom.signal_name],
                    start_time=anom.start_time,
                    end_time=anom.end_time,
                    duration=anom.duration,
                    operating_condition=anom.operating_condition,
                    observed_behavior=anom.details,
                    expected_behavior=f"Stable expected signal behavior without {anom.anomaly_type.value}",
                    deviation_magnitude=anom.magnitude,
                    severity=anom.severity,
                    quality=SignalQuality.GOOD,
                    provenance={"anomaly_id": anom.anomaly_id},
                    analysis_method="TEMPORAL_PATTERN_DETECTION",
                    confidence_score=anom.confidence,
                    supporting_observations=[anom.details],
                    contradicting_observations=[],
                ))
            elif isinstance(anom, PointAnomaly):
                evidence_list.append(FaultEvidence(
                    evidence_id=f"EV-PANOM-{anom.signal_name}-{anom.anomaly_type.value}-{ev_counter:03d}",
                    title=f"Point anomaly in {anom.signal_name}: {anom.anomaly_type.value}",
                    signals=[anom.signal_name],
                    start_time=anom.timestamp,
                    end_time=anom.timestamp,
                    duration=0.0,
                    operating_condition=anom.operating_condition,
                    observed_behavior=anom.details,
                    expected_behavior=f"Value within limits {anom.expected_range}",
                    deviation_magnitude=abs(anom.observed_value),
                    severity=anom.severity,
                    quality=SignalQuality.SUSPECT,
                    provenance={"anomaly_id": anom.anomaly_id},
                    analysis_method="PHYSICAL_LIMIT_VERIFICATION",
                    confidence_score=0.75,
                    supporting_observations=[anom.details],
                    contradicting_observations=[],
                ))

        return evidence_list


class HypothesisRankingEngine:
    """
    Evaluates, scores, and ranks diagnostic fault hypotheses.
    Enforces supporting evidence minus contradicting evidence.
    Calibrates confidence (HIGH / MEDIUM / LOW / INSUFFICIENT) and handles competing hypotheses.
    """
    @classmethod
    def generate_and_rank_hypotheses(
        cls,
        evidence: List[FaultEvidence],
        dtc_correlations: List[DTCCorrelation],
        vehicle_context: Optional[VehicleContext] = None,
    ) -> List[FaultHypothesis]:
        hypotheses: List[FaultHypothesis] = []
        ev_by_id = {e.evidence_id: e for e in evidence}
        all_signals = {s for e in evidence for s in e.signals}
        dtc_codes = {c.dtc_code for c in dtc_correlations}

        # -----------------------------------------------------------------
        # 1. HYPOTHESIS: UNMETERED INTAKE AIR / VACUUM LEAK
        # -----------------------------------------------------------------
        vac_supp: List[FaultEvidence] = []
        vac_contra: List[FaultEvidence] = []

        for e in evidence:
            if "EV-VACUUM-LEAK" in e.evidence_id:
                vac_supp.append(e)
            elif "EV-MAF-BIAS" in e.evidence_id and e.deviation_magnitude > 35.0:
                # Severe MAF bias can be an alternative explanation
                vac_contra.append(e)
            elif "EV-TANOM-MAP-DRIFT" in e.evidence_id:
                vac_supp.append(e)

        score_vac = sum(e.confidence_score * (1.5 if e.quality == SignalQuality.GOOD else 0.8) for e in vac_supp)
        score_vac -= sum(e.confidence_score * 0.8 for e in vac_contra)

        if vac_supp:
            dtc_assoc = [c for c in dtc_codes if c in ("P0171", "P0106", "P0300")]
            conf = HypothesisConfidence.HIGH if (score_vac >= 1.2 and not vac_contra) else (HypothesisConfidence.MEDIUM if score_vac >= 0.7 else HypothesisConfidence.LOW)
            hypotheses.append(FaultHypothesis(
                hypothesis_id="HYP-INTAKE-VACUUM-LEAK",
                title="Unmetered Intake Air / Vacuum Leak",
                category="AIR_INDUCTION",
                affected_system="INTAKE_MANIFOLD",
                supporting_evidence=vac_supp,
                contradicting_evidence=vac_contra,
                evidence_score=max(0.0, score_vac),
                confidence=conf,
                severity=AnomalySeverity.WARNING,
                occurrence_count=len(vac_supp),
                operating_conditions=[e.operating_condition for e in vac_supp],
                dtc_associations=dtc_assoc,
                is_dtc_free=(len(dtc_assoc) == 0),
                possible_root_causes=[
                    "Intake manifold gasket leak",
                    "Disconnected or deteriorated vacuum hose",
                    "PCV valve stuck open or leaking",
                    "Brake booster vacuum diaphragm leak",
                ],
                alternative_explanations=["MAF calibration underreporting bias", "Fuel injector minor restriction"],
                required_additional_evidence=["Perform intake smoke test", "Verify fuel trims when clamping PCV line"],
                recommended_test_reference="TEST_VACUUM_INTEGRITY_CHECK",
            ))

        # -----------------------------------------------------------------
        # 2. HYPOTHESIS: MAF SENSOR CALIBRATION / AIRFLOW BIAS
        # -----------------------------------------------------------------
        maf_supp: List[FaultEvidence] = []
        maf_contra: List[FaultEvidence] = []

        for e in evidence:
            if "EV-MAF-BIAS" in e.evidence_id:
                maf_supp.append(e)
            elif "EV-VACUUM-LEAK" in e.evidence_id:
                # If trims normalize at cruise, it contradicts simple MAF scaling bias
                maf_contra.append(e)

        score_maf = sum(e.confidence_score * (1.5 if e.quality == SignalQuality.GOOD else 0.8) for e in maf_supp)
        score_maf -= sum(e.confidence_score * 0.7 for e in maf_contra)

        if maf_supp:
            dtc_assoc = [c for c in dtc_codes if c in ("P0101", "P0171", "P0172")]
            conf = HypothesisConfidence.HIGH if (score_maf >= 1.2 and not maf_contra) else (HypothesisConfidence.MEDIUM if score_maf >= 0.7 else HypothesisConfidence.LOW)
            hypotheses.append(FaultHypothesis(
                hypothesis_id="HYP-MAF-CALIBRATION-BIAS",
                title="Mass Air Flow Sensor Measurement Bias",
                category="AIR_MEASUREMENT",
                affected_system="MAF_SENSOR",
                supporting_evidence=maf_supp,
                contradicting_evidence=maf_contra,
                evidence_score=max(0.0, score_maf),
                confidence=conf,
                severity=AnomalySeverity.WARNING,
                occurrence_count=len(maf_supp),
                operating_conditions=[e.operating_condition for e in maf_supp],
                dtc_associations=dtc_assoc,
                is_dtc_free=(len(dtc_assoc) == 0),
                possible_root_causes=[
                    "Contaminated hot-wire / sensing element",
                    "Airflow disturbance upstream of MAF",
                    "Sensor electrical aging or reference drift",
                ],
                alternative_explanations=["Unmetered air entering post-sensor", "Incorrect volumetric efficiency estimation"],
                required_additional_evidence=["Inspect MAF element for contamination", "Measure MAF g/s at stationary 2500 RPM"],
                recommended_test_reference="TEST_MAF_AIRFLOW_CORRELATION",
            ))

        # -----------------------------------------------------------------
        # 3. HYPOTHESIS: SLOW O2 SENSOR RESPONSE / DEGRADATION
        # -----------------------------------------------------------------
        o2_supp: List[FaultEvidence] = []
        for e in evidence:
            if ("O2" in e.signals and "EV-LAG" in e.evidence_id) or "TANOM-O2-FLATLINE" in e.evidence_id:
                o2_supp.append(e)

        if o2_supp:
            dtc_assoc = [c for c in dtc_codes if c in ("P0130", "P0133")]
            hypotheses.append(FaultHypothesis(
                hypothesis_id="HYP-O2-SENSOR-DEGRADATION",
                title="Upstream Oxygen Sensor Aging / Sluggish Response",
                category="EXHAUST_EMISSIONS",
                affected_system="O2_SENSOR_BANK1",
                supporting_evidence=o2_supp,
                contradicting_evidence=[],
                evidence_score=len(o2_supp) * 1.2,
                confidence=HypothesisConfidence.HIGH if len(o2_supp) >= 2 else HypothesisConfidence.MEDIUM,
                severity=AnomalySeverity.WARNING,
                occurrence_count=len(o2_supp),
                operating_conditions=[e.operating_condition for e in o2_supp],
                dtc_associations=dtc_assoc,
                is_dtc_free=(len(dtc_assoc) == 0),
                possible_root_causes=["Silicone or carbon poisoning of zirconia element", "Heater degradation"],
                alternative_explanations=["Exhaust manifold pinhole leak before sensor"],
                required_additional_evidence=["Check O2 sensor response during snap throttle"],
                recommended_test_reference="TEST_O2_DYNAMIC_RESPONSE",
            ))

        # -----------------------------------------------------------------
        # 4. HYPOTHESIS: COOLING THERMOSTAT STUCK OPEN
        # -----------------------------------------------------------------
        therm_supp = [e for e in evidence if "ECT" in e.signals and ("WARMUP" in e.evidence_id or "WARMUP" in e.title)]
        if therm_supp:
            dtc_assoc = [c for c in dtc_codes if c == "P0128"]
            hypotheses.append(FaultHypothesis(
                hypothesis_id="HYP-THERMOSTAT-STUCK-OPEN",
                title="Engine Thermostat Failure / Stuck Partially Open",
                category="COOLING_SYSTEM",
                affected_system="THERMOSTAT",
                supporting_evidence=therm_supp,
                contradicting_evidence=[],
                evidence_score=2.0,
                confidence=HypothesisConfidence.HIGH,
                severity=AnomalySeverity.WARNING,
                occurrence_count=len(therm_supp),
                operating_conditions=[OperatingCondition.WARM_UP],
                dtc_associations=dtc_assoc,
                is_dtc_free=(len(dtc_assoc) == 0),
                possible_root_causes=["Thermostat valve mechanically jammed open", "Deteriorated rubber seal ring"],
                alternative_explanations=["ECT sensor calibration low bias", "Electric cooling fan running continuously"],
                required_additional_evidence=["Measure radiator inlet hose temperature during cold warm-up"],
                recommended_test_reference="TEST_THERMOSTAT_WARMUP_CURVE",
            ))

        # -----------------------------------------------------------------
        # 5. HYPOTHESIS: SENSOR FLATLINE / HARDWARE FREEZE
        # -----------------------------------------------------------------
        flatlines = [e for e in evidence if "FLATLINE" in e.evidence_id or "FLATLINE" in e.title]
        for fl in flatlines:
            sig = fl.signals[0] if fl.signals else "SENSOR"
            hypotheses.append(FaultHypothesis(
                hypothesis_id=f"HYP-SENSOR-FREEZE-{sig}",
                title=f"{sig} Sensor Hardware Flatline / Signal Lock",
                category="SENSOR_HARDWARE",
                affected_system=f"{sig}_CIRCUIT",
                supporting_evidence=[fl],
                contradicting_evidence=[],
                evidence_score=2.2,
                confidence=HypothesisConfidence.HIGH,
                severity=AnomalySeverity.CRITICAL if sig in ("ECT", "MAP") else AnomalySeverity.WARNING,
                occurrence_count=1,
                operating_conditions=[fl.operating_condition],
                dtc_associations=[],
                is_dtc_free=True,
                possible_root_causes=[f"{sig} internal sensing element seized/shorted", "Harness open-circuit or bridge"],
                alternative_explanations=["Vehicle operating in absolute steady state without variation"],
                required_additional_evidence=[f"Unplug {sig} and check if ECU registers open-circuit fallback"],
                recommended_test_reference=f"TEST_{sig}_CIRCUIT_INTEGRITY",
            ))

        # -----------------------------------------------------------------
        # 6. HYPOTHESIS: THROTTLE RESTRICTION / DELAYED RESPONSE
        # -----------------------------------------------------------------
        throt_delays = [e for e in evidence if "EV-LAG-TPS-MAP" in e.evidence_id or "EV-LAG-THROTTLE-MAP" in e.evidence_id]
        if throt_delays:
            hypotheses.append(FaultHypothesis(
                hypothesis_id="HYP-THROTTLE-RESTRICTION",
                title="Throttle Body Coking or Manifold Response Restriction",
                category="AIR_INDUCTION",
                affected_system="THROTTLE_BODY",
                supporting_evidence=throt_delays,
                contradicting_evidence=[],
                evidence_score=1.5,
                confidence=HypothesisConfidence.MEDIUM,
                severity=AnomalySeverity.WARNING,
                occurrence_count=len(throt_delays),
                operating_conditions=[OperatingCondition.ACCELERATION],
                dtc_associations=[],
                is_dtc_free=True,
                possible_root_causes=["Heavy carbon sludge around throttle bore/plate", "Electronic throttle actuator lag"],
                alternative_explanations=["MAP sensor port partially clogged"],
                required_additional_evidence=["Visual inspection of throttle plate and bore for carbon deposits"],
                recommended_test_reference="TEST_THROTTLE_BORE_INSPECTION",
            ))

        # Check for Competing Hypotheses / Inconclusive Distinction
        # (e.g. Vacuum leak vs MAF bias with close scores)
        h_vac = next((h for h in hypotheses if h.hypothesis_id == "HYP-INTAKE-VACUUM-LEAK"), None)
        h_maf = next((h for h in hypotheses if h.hypothesis_id == "HYP-MAF-CALIBRATION-BIAS"), None)
        if h_vac and h_maf:
            diff = abs(h_vac.evidence_score - h_maf.evidence_score)
            if diff <= 0.65 and h_vac.confidence != HypothesisConfidence.INSUFFICIENT and h_maf.confidence != HypothesisConfidence.INSUFFICIENT:
                h_vac.is_inconclusive = True
                h_maf.is_inconclusive = True
                h_vac.title += " (INCONCLUSIVE — ADDITIONAL EVIDENCE REQUIRED)"
                h_maf.title += " (INCONCLUSIVE — ADDITIONAL EVIDENCE REQUIRED)"

        # Sort hypotheses by evidence_score descending
        hypotheses.sort(key=lambda h: h.evidence_score, reverse=True)
        return hypotheses


# =====================================================================
# 10. DIAGNOSTIC EXPLANATION GENERATOR
# =====================================================================

class DiagnosticExplanationGenerator:
    """
    Generates explainable, technician-readable narratives strictly derived
    from structured evidence. ZERO LLM dependency; zero hallucination.
    """
    @classmethod
    def generate_explanations(
        cls,
        hypotheses: List[FaultHypothesis],
        dtc_correlations: List[DTCCorrelation],
    ) -> List[Dict[str, Any]]:
        explanations = []

        for hyp in hypotheses:
            supp_texts = [e.observed_behavior for e in hyp.supporting_evidence]
            contra_texts = [e.observed_behavior for e in hyp.contradicting_evidence]
            dtc_text = ", ".join(hyp.dtc_associations) if hyp.dtc_associations else "NO DTC SUPPORTING THIS FINDING"

            window_text = "N/A"
            if hyp.supporting_evidence:
                first_t = min(e.start_time for e in hyp.supporting_evidence)
                last_t = max(e.end_time for e in hyp.supporting_evidence)
                conds = ", ".join({e.operating_condition.value for e in hyp.supporting_evidence})
                window_text = f"t={first_t:.1f}s to t={last_t:.1f}s under [{conds}]"

            interp = (
                f"The observed evidence strongly matches {hyp.title}. "
                f"Supporting evidence outweighing contradicting indicators with a calibrated score of {hyp.evidence_score:.2f}."
            )
            if hyp.is_inconclusive:
                interp = (
                    f"Evidence equally supports multiple competing root causes. "
                    f"Both {hyp.title} and alternative mechanisms remain plausible without further physical testing."
                )

            exp = {
                "hypothesis_id": hyp.hypothesis_id,
                "finding": hyp.title,
                "why": " | ".join(supp_texts[:2]) if supp_texts else "Identified via multi-sensor relationship modeling",
                "evidence_window": window_text,
                "associated_dtcs": dtc_text,
                "interpretation": interp,
                "confidence": hyp.confidence.value,
                "severity": hyp.severity.value,
                "alternatives": hyp.alternative_explanations,
                "recommended_verification": hyp.required_additional_evidence,
            }
            explanations.append(exp)

        return explanations


# =====================================================================
# 11. TOP-LEVEL ADVANCED FAULT ANALYZER (PIPELINE ORCHESTRATOR)
# =====================================================================

class AdvancedFaultAnalyzer:
    """
    Top-level analytical engine implementing the complete Phase G-3 diagnostic pipeline:
      Vehicle Context
        ↓
      Data Quality Filtering
        ↓
      Operating Condition Segmentation
        ↓
      Point & Temporal Anomaly Detection
        ↓
      Cross-Sensor & Dynamic Lag Analysis
        ↓
      DTC Correlation (with DTC-Free capability)
        ↓
      Evidence Generation & Weighting
        ↓
      Hypothesis Ranking & Inconclusive Differentiation
        ↓
      Technician Diagnostic Explanations
    """
    def __init__(self):
        self._analysis_counter = 0

    @staticmethod
    def _vehicle_context_to_dict(ctx: Optional[VehicleContext]) -> Optional[Dict[str, Any]]:
        if ctx is None:
            return None
        if hasattr(ctx, "to_dict") and callable(ctx.to_dict):
            return ctx.to_dict()
        return {
            "manufacturer": getattr(ctx, "manufacturer", None),
            "model": getattr(ctx, "model", None),
            "model_year": getattr(ctx, "model_year", None),
            "engine_code": getattr(ctx, "engine_code", None),
            "transmission": getattr(ctx, "transmission", None),
            "ecu_family": getattr(ctx, "ecu_family", None),
            "software_id": getattr(ctx, "software_id", None),
            "metadata": getattr(ctx, "metadata", {}),
        }

    def analyze_dataset(
        self,
        dataset: DiagnosticDataSet,
        vehicle_context: Optional[VehicleContext] = None,
    ) -> AnalysisResult:
        """
        Executes the complete G-3 fault analysis on a DiagnosticDataSet.
        Guaranteed read-only and deterministic.
        """
        self._analysis_counter += 1
        analysis_id = f"AFA-{int(time.time())}-{self._analysis_counter:04d}"
        ctx = vehicle_context or dataset.vehicle_context

        # 1. Coverage Report & Quality Gate
        coverage = dataset.get_coverage_report()
        quality_counts = DataQualityGate.filter_and_classify(dataset)

        warnings: List[str] = []
        if len(dataset.signals) == 0:
            warnings.append("Dataset contains 0 signals. Analysis cannot proceed.")
            return AnalysisResult(
                analysis_id=analysis_id,
                dataset_id=dataset.dataset_id,
                vehicle_context=self._vehicle_context_to_dict(ctx),
                session_start_time=dataset.session_start_time,
                session_end_time=dataset.session_end_time,
                duration_seconds=0.0,
                coverage_report=coverage,
                quality_summary=quality_counts,
                operating_condition_summary={},
                warnings=warnings,
                provenance={"engine": "AdvancedFaultAnalyzer", "version": "Phase-G3-1.0"},
            )

        # 2. Operating Condition Segmentation
        segments = OperatingConditionSegmenter.segment(dataset)
        cond_durations: Dict[str, float] = collections.defaultdict(float)
        for s in segments:
            cond_durations[s.condition.value] += s.duration
        cond_summary = {k: round(v, 2) for k, v in cond_durations.items()}

        # 3. Point & Temporal Anomaly Detection
        point_anomalies = PointAnomalyDetector.detect(dataset)
        temporal_anomalies = TemporalAnomalyDetector.detect(dataset, segments)
        all_anomalies: List[Union[PointAnomaly, TemporalAnomaly]] = []
        all_anomalies.extend(point_anomalies)
        all_anomalies.extend(temporal_anomalies)

        # 4. Cross-Sensor & Lag Analysis
        lag_measurements = CrossSensorAnalyzer.analyze_throttle_lag(dataset)
        fuel_trim_result = CrossSensorAnalyzer.evaluate_fuel_trim_divergence(dataset, segments)
        airflow_result = CrossSensorAnalyzer.evaluate_airflow_residual(dataset)

        # 5. DTC Correlation
        dtc_correlations = DTCCorrelator.correlate(
            dtc_records=dataset.dtc_records,
            anomalies=all_anomalies,
            fuel_trim_result=fuel_trim_result,
            lag_measurements=lag_measurements,
        )

        # 6. Structured Evidence Generation
        evidence = EvidenceBuilder.build_evidence(
            anomalies=all_anomalies,
            lag_measurements=lag_measurements,
            fuel_trim_analysis=fuel_trim_result,
            airflow_analysis=airflow_result,
        )

        # 7. Hypothesis Ranking & Competition
        hypotheses = HypothesisRankingEngine.generate_and_rank_hypotheses(
            evidence=evidence,
            dtc_correlations=dtc_correlations,
            vehicle_context=ctx,
        )

        # 8. Technician Diagnostic Explanations
        explanations = DiagnosticExplanationGenerator.generate_explanations(
            hypotheses=hypotheses,
            dtc_correlations=dtc_correlations,
        )

        dur_s = max(0.0, dataset.session_end_time - dataset.session_start_time)
        return AnalysisResult(
            analysis_id=analysis_id,
            dataset_id=dataset.dataset_id,
            vehicle_context=self._vehicle_context_to_dict(ctx),
            session_start_time=dataset.session_start_time,
            session_end_time=dataset.session_end_time,
            duration_seconds=dur_s,
            coverage_report=coverage,
            quality_summary=quality_counts,
            operating_condition_summary=cond_summary,
            anomalies=all_anomalies,
            evidence=evidence,
            dtc_correlations=dtc_correlations,
            hypotheses=hypotheses,
            explanations=explanations,
            warnings=warnings,
            provenance={
                "engine": "AdvancedFaultAnalyzer",
                "version": "Phase-G3-1.0",
                "signals_analyzed": list(dataset.signals.keys()),
                "total_samples": sum(len(s) for s in dataset.signals.values()),
            },
        )
