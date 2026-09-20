"""
Seyyanen Mini PC Integration — Normalizer & Provenance Layer
Transforms raw Mini samples into canonical Seyyanen observations with rich provenance.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple
from .metadata_parser import MiniSessionMetadata
from .sample_parser import RawMiniSample

# Known standard Mode 01 canonical names
PID_MAP = {
    "0104": ("LOAD", "%"),
    "0105": ("ECT", "degC"),
    "0106": ("STFT1", "%"),
    "0107": ("LTFT1", "%"),
    "010B": ("MAP", "kPa"),
    "010C": ("RPM", "rpm"),
    "010D": ("SPEED", "km/h"),
    "010E": ("TIMING", "deg"),
    "010F": ("IAT", "degC"),
    "0110": ("MAF", "g/s"),
    "0111": ("TPS", "%"),
}


@dataclass
class ObservationProvenance:
    source: str = "SEYYANEN_MINI"
    source_session_id: str = "UNKNOWN"
    source_file: str = "session.csv"
    source_row: int = 0
    mini_firmware_version: str = "UNKNOWN"
    mini_version: str = "1.0"
    adapter_identity: str = "UNKNOWN"
    transport_medium: str = "BLUETOOTH_SPP"
    protocol: str = "UNKNOWN"


@dataclass
class MiniObservation:
    timestamp_us: int
    normalized_time_s: float
    wall_clock_iso: Optional[str]
    pid: str
    canonical_name: str
    value: Optional[float]
    unit: str
    status: str
    quality: str
    freshness: str
    latency_us: int
    raw_response: str
    mini_decoded_value: Optional[float]
    provenance: ObservationProvenance = field(default_factory=ObservationProvenance)
    reconciliation: str = "UNKNOWN_PID"

    def to_c_layer_dict(self) -> Dict[str, Any]:
        """Produces a dictionary directly compatible with C-layer sensor caches."""
        return {
            "name": self.canonical_name,
            "val": self.value,
            "status": self.status,
            "quality": self.quality,
            "timestamp": self.normalized_time_s,
            "timestamp_us": self.timestamp_us,
            "raw_response": self.raw_response,
            "latency_ms": self.latency_us / 1000.0,
            "source": self.provenance.source,
            "provenance": {
                "source_session_id": self.provenance.source_session_id,
                "source_row": self.provenance.source_row,
                "adapter": self.provenance.adapter_identity,
                "protocol": self.provenance.protocol
            }
        }


class MiniNormalizer:
    """Normalizes raw Mini samples into structured MiniObservation instances."""

    def __init__(self, metadata: MiniSessionMetadata):
        self.metadata = metadata
        self.known_mini_pids = {p.pid: p for p in metadata.supported_pids}

    def reconcile_pid(self, pid: str, unit: str) -> Tuple[str, str, str]:
        """
        Reconciles PID against desktop taxonomy.
        Returns: (canonical_name, canonical_unit, reconciliation_status)
        """
        pid_upper = pid.upper()
        if pid_upper in PID_MAP:
            desktop_name, desktop_unit = PID_MAP[pid_upper]
            if pid_upper in self.known_mini_pids:
                mini_unit = self.known_mini_pids[pid_upper].unit
                if mini_unit.lower() == desktop_unit.lower():
                    return desktop_name, desktop_unit, "MINI_METADATA_MATCH"
                else:
                    return desktop_name, desktop_unit, "MINI_METADATA_DIFFERS"
            return desktop_name, desktop_unit, "DESKTOP_METADATA_MATCH"

        # Not in standard desktop map
        name = pid_upper
        if pid_upper in self.known_mini_pids:
            name = self.known_mini_pids[pid_upper].name or pid_upper
        return name, unit, "UNKNOWN_PID"

    def normalize_sample(self, sample: RawMiniSample, rel_time_s: float, wall_clock_iso: Optional[str]) -> MiniObservation:
        canonical_name, canonical_unit, reconciliation = self.reconcile_pid(sample.pid, sample.unit)

        # Mapping status to desktop concepts
        # VALID, TIMEOUT, NO_DATA, TRANSPORT_ERR, etc.
        status = sample.status
        quality = sample.quality

        provenance = ObservationProvenance(
            source="SEYYANEN_MINI",
            source_session_id=self.metadata.session_id,
            source_file="session.csv",
            source_row=sample.row_index,
            mini_firmware_version=self.metadata.firmware_version,
            mini_version=self.metadata.mini_protocol_version,
            adapter_identity=f"{self.metadata.adapter.adapter_name} ({self.metadata.adapter.firmware})",
            transport_medium=self.metadata.adapter.transport,
            protocol=self.metadata.protocol,
        )

        return MiniObservation(
            timestamp_us=sample.timestamp_us,
            normalized_time_s=rel_time_s,
            wall_clock_iso=wall_clock_iso,
            pid=sample.pid,
            canonical_name=canonical_name,
            value=sample.decoded_value,
            unit=canonical_unit,
            status=status,
            quality=quality,
            freshness=sample.freshness,
            latency_us=sample.latency_us,
            raw_response=sample.raw_response,
            mini_decoded_value=sample.decoded_value,
            provenance=provenance,
            reconciliation=reconciliation,
        )
