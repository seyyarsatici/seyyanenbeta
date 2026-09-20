"""
Seyyanen Mini PC Integration — Importer Facade
Primary API for importing, previewing, and handing off Mini sessions to the desktop Seyyanen platform.
"""

import os
import hashlib
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Generator, Tuple

from .session_reader import SessionReader
from .metadata_parser import MetadataParser, MiniSessionMetadata
from .sample_parser import SampleParser, RawMiniSample
from .schema_validator import SchemaValidator
from .timestamp_normalizer import TimestampNormalizer
from .mini_normalizer import MiniNormalizer, MiniObservation
from .import_report import MiniImportReport

# In-memory registry for imported session hashes to ensure idempotency
_IMPORTED_SESSION_HASHES: Dict[str, str] = {}


@dataclass
class MiniSessionPreview:
    session_id: str
    source_path: str
    firmware_version: str
    protocol: str
    adapter_name: str
    duration_seconds: float
    sample_count: int
    supported_pid_count: int
    vehicle_identity_status: str
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    is_valid: bool = False


@dataclass
class MiniImportResult:
    success: bool
    session_metadata: Optional[MiniSessionMetadata]
    observations: List[MiniObservation]
    report: MiniImportReport
    source: str
    session_hash: str
    already_imported: bool = False
    vehicle_attached: Optional[str] = None


def compute_session_hash(session_id: str, sample_count: int, first_ts: int, last_ts: int) -> str:
    """Computes a deterministic hash for a session to prevent silent duplicate imports."""
    data = f"{session_id}:{sample_count}:{first_ts}:{last_ts}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def preview_mini_session(path: str) -> MiniSessionPreview:
    """
    Fast inspection of a Mini session without loading samples into memory.
    Reads metadata and first few CSV rows to provide a lightweight preview.
    """
    errors: List[str] = []
    warnings: List[str] = []

    try:
        with SessionReader(path) as reader:
            raw_meta = reader.read_metadata_content()
            meta, meta_errors = MetadataParser.parse(raw_meta)
            errors.extend(meta_errors)

            if meta is None:
                return MiniSessionPreview(
                    session_id="UNKNOWN",
                    source_path=path,
                    firmware_version="UNKNOWN",
                    protocol="UNKNOWN",
                    adapter_name="UNKNOWN",
                    duration_seconds=0.0,
                    sample_count=0,
                    supported_pid_count=0,
                    vehicle_identity_status="UNKNOWN",
                    warnings=warnings,
                    errors=errors,
                    is_valid=False,
                )

            csv_path = reader.get_csv_path()
            if not csv_path or not os.path.isfile(csv_path):
                errors.append("MISSING_SAMPLE_FILE: session.csv not found in session")

            # Check header
            try:
                line_gen = reader.stream_csv_lines()
                first_line = next(line_gen, None)
                if not first_line:
                    errors.append("EMPTY_SAMPLE_FILE: session.csv is empty")
            except Exception as e:
                errors.append(f"SAMPLE_FILE_ERROR: {str(e)}")

            is_valid = len(errors) == 0

            return MiniSessionPreview(
                session_id=meta.session_id,
                source_path=path,
                firmware_version=meta.firmware_version,
                protocol=meta.protocol,
                adapter_name=meta.adapter.adapter_name,
                duration_seconds=meta.duration_seconds,
                sample_count=meta.sample_count,
                supported_pid_count=len(meta.supported_pids),
                vehicle_identity_status=meta.vehicle.vehicle_identity_status,
                warnings=warnings,
                errors=errors,
                is_valid=is_valid,
            )
    except Exception as e:
        return MiniSessionPreview(
            session_id="UNKNOWN",
            source_path=path,
            firmware_version="UNKNOWN",
            protocol="UNKNOWN",
            adapter_name="UNKNOWN",
            duration_seconds=0.0,
            sample_count=0,
            supported_pid_count=0,
            vehicle_identity_status="UNKNOWN",
            warnings=warnings,
            errors=[f"READ_ERROR: {str(e)}"],
            is_valid=False,
        )


def import_mini_session(path: str, options: Optional[Dict[str, Any]] = None) -> MiniImportResult:
    """
    Primary entry point: Imports a Seyyanen Mini session.
    Parses, validates, normalizes, and packages data with full provenance.
    """
    options = options or {}
    force_reimport = bool(options.get("force_reimport", False))
    streaming_mode = bool(options.get("streaming_mode", False))

    report = MiniImportReport(source_path=os.path.abspath(path))
    observations: List[MiniObservation] = []

    try:
        with SessionReader(path) as reader:
            # 1. Parse Metadata
            raw_meta = reader.read_metadata_content()
            metadata, meta_errors = MetadataParser.parse(raw_meta)
            report.errors.extend(meta_errors)

            if metadata is None:
                report.session_id = "UNKNOWN"
                return MiniImportResult(
                    success=False,
                    session_metadata=None,
                    observations=[],
                    report=report,
                    source="SEYYANEN_MINI",
                    session_hash="",
                    already_imported=False,
                )

            report.session_id = metadata.session_id

            # 2. Validate Metadata Schema
            meta_val_errors = SchemaValidator.validate_metadata(metadata)
            report.errors.extend(meta_val_errors)

            # 3. Setup Normalizers
            ts_normalizer = TimestampNormalizer(base_iso_str=metadata.start_time_iso)
            mini_normalizer = MiniNormalizer(metadata)

            # 4. Stream & Parse CSV Rows
            prev_sample: Optional[RawMiniSample] = None
            first_ts: int = 0
            last_ts: int = 0
            seen_sequences = set()

            for sample, err in SampleParser.parse_stream(reader.stream_csv_lines()):
                report.rows_read += 1

                if err:
                    report.errors.append(err)
                    report.rows_invalid += 1
                    continue

                if sample is None:
                    continue

                # Check duplicate sequence
                if sample.sequence in seen_sequences:
                    report.duplicates += 1
                    report.warnings.append(f"DUPLICATE_SEQUENCE: Row {sample.row_index} sequence {sample.sequence} seen previously")
                seen_sequences.add(sample.sequence)

                # Validation
                s_errors, s_warnings = SchemaValidator.validate_sample(sample, prev_sample)
                if s_errors:
                    report.errors.extend(s_errors)
                    report.rows_invalid += 1
                    continue

                if s_warnings:
                    report.warnings.extend(s_warnings)

                if first_ts == 0:
                    first_ts = sample.timestamp_us
                    ts_normalizer.set_origin(first_ts)
                last_ts = sample.timestamp_us

                report.rows_valid += 1
                report.unique_pids.add(sample.pid)

                # Accounting
                if sample.status == "VALID":
                    report.valid_samples += 1
                else:
                    report.failed_samples += 1
                    if sample.status == "TIMEOUT":
                        report.timeouts += 1
                    elif sample.status == "NO_DATA":
                        report.no_data += 1
                    elif sample.status in ("TRANSPORT_ERR", "SAFETY_BLOCKED"):
                        report.transport_errors += 1

                # Normalize sample into observation
                rel_time_s, wall_clock_iso = ts_normalizer.normalize(sample.timestamp_us)
                obs = mini_normalizer.normalize_sample(sample, rel_time_s, wall_clock_iso)

                if not streaming_mode:
                    observations.append(obs)

                prev_sample = sample

            # Finalize report
            report.timestamp_start_us = first_ts
            report.timestamp_end_us = last_ts
            if first_ts > 0 and last_ts >= first_ts:
                report.duration_s = (last_ts - first_ts) / 1000000.0

            # Compute session hash for idempotency
            sess_hash = compute_session_hash(metadata.session_id, report.rows_valid, first_ts, last_ts)

            already_imported = False
            if sess_hash in _IMPORTED_SESSION_HASHES:
                if not force_reimport:
                    already_imported = True
                    report.warnings.append(f"ALREADY_IMPORTED: Session '{metadata.session_id}' (hash: {sess_hash}) was previously imported.")
            else:
                _IMPORTED_SESSION_HASHES[sess_hash] = metadata.session_id

            success = (len(report.errors) == 0) and not (already_imported and not force_reimport)

            return MiniImportResult(
                success=success,
                session_metadata=metadata,
                observations=observations,
                report=report,
                source="SEYYANEN_MINI",
                session_hash=sess_hash,
                already_imported=already_imported,
                vehicle_attached=None,
            )

    except Exception as e:
        report.errors.append(f"IMPORT_FATAL_ERROR: {str(e)}")
        return MiniImportResult(
            success=False,
            session_metadata=None,
            observations=[],
            report=report,
            source="SEYYANEN_MINI",
            session_hash="",
            already_imported=False,
        )


def attach_session_to_vehicle(result: MiniImportResult, vehicle_id_or_profile: Any) -> MiniImportResult:
    """
    Explicit user action to bind an imported session to a vehicle instance.
    Does not guess or fabricate identity.
    """
    if isinstance(vehicle_id_or_profile, str):
        result.vehicle_attached = vehicle_id_or_profile
        if result.session_metadata:
            result.session_metadata.vehicle.vehicle_identity_status = "ATTACHED"
            result.session_metadata.vehicle.vin = vehicle_id_or_profile
    else:
        # Profile object with VIN or motor_kodu
        v_id = getattr(vehicle_id_or_profile, "vin", None) or getattr(vehicle_id_or_profile, "motor_kodu", "CUSTOM")
        result.vehicle_attached = str(v_id)
        if result.session_metadata:
            result.session_metadata.vehicle.vehicle_identity_status = "ATTACHED"
    return result


def handoff_to_c_layer(observations: List[MiniObservation], engine: Any = None) -> Dict[str, Any]:
    """
    Feeds normalized Mini observations into the existing C-layer (AutoExpertEngine).
    Existing C-layer quality, physics, and temporal validation determine trust.
    Mini-originated data is treated as evidence, never pre-trusted.
    """
    if engine is None:
        try:
            from motor import AutoExpertEngine
            engine = AutoExpertEngine()
        except ImportError:
            return {"error": "AutoExpertEngine not available", "processed": 0}

    trusted_count = 0
    suspect_count = 0
    error_count = 0

    for obs in observations:
        sensor_name = obs.canonical_name
        val = obs.value
        status = obs.status
        ts = obs.normalized_time_s

        # Feed into engine's native sensor cache update
        entry = engine._update_sensor_cache(
            sensor_name,
            val,
            status=status,
            timestamp=ts,
            source=obs.provenance.source
        )

        q = entry.get("quality")
        if q == "GOOD":
            trusted_count += 1
        elif q in ("SUSPECT", "IMPLAUSIBLE"):
            suspect_count += 1
        else:
            error_count += 1

    return {
        "processed": len(observations),
        "trusted": trusted_count,
        "suspect_or_implausible": suspect_count,
        "errors": error_count,
        "engine_history_lengths": {k: len(v) for k, v in getattr(engine, "sensor_history", {}).items()}
    }
