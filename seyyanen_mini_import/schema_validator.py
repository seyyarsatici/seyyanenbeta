"""
Seyyanen Mini PC Integration — Schema Validator
Validates session files, metadata structure, and row integrity with classified error taxonomy.
"""

import re
from typing import List, Optional, Dict, Any, Tuple
from .metadata_parser import MiniSessionMetadata
from .sample_parser import RawMiniSample

VALID_STATUSES = {
    "VALID", "TIMEOUT", "NO_DATA", "TRANSPORT_ERR",
    "MALFORMED", "SAFETY_BLOCKED", "NOT_SUPPORTED"
}

VALID_QUALITIES = {
    "GOOD", "FRESH", "AGING", "STALE", "TIMEOUT",
    "NO_DATA", "TRANSPORT_ERROR", "MALFORMED",
    "SAFETY_BLOCKED", "NOT_SUPPORTED", "SUSPECT", "DEGRADED"
}


class SchemaValidationError(Exception):
    def __init__(self, code: str, message: str, row: Optional[int] = None):
        super().__init__(f"[{code}] {message}" + (f" (row {row})" if row else ""))
        self.code = code
        self.message = message
        self.row = row


class SchemaValidator:
    """Classified validation engine for Seyyanen Mini imports."""

    @staticmethod
    def validate_metadata(metadata: Optional[MiniSessionMetadata]) -> List[str]:
        errors: List[str] = []
        if metadata is None:
            return ["MISSING_METADATA: metadata.json missing or failed to parse"]

        if not metadata.session_id or metadata.session_id == "UNKNOWN":
            errors.append("INVALID_METADATA: session_id is missing or UNKNOWN")

        if not re.match(r'^[a-zA-Z0-9_-]+$', metadata.session_id):
            errors.append(f"INVALID_METADATA: session_id contains invalid characters: '{metadata.session_id}'")

        if metadata.session_state not in ("COMPLETED", "RECOVERABLE_INCOMPLETE", "ACTIVE"):
            errors.append(f"INVALID_METADATA: invalid session_state '{metadata.session_state}'")

        if not metadata.supported_pids:
            errors.append("INVALID_METADATA: supported_pids is empty")

        return errors

    @staticmethod
    def validate_pid(pid: str) -> bool:
        return bool(re.match(r'^[0-9A-Fa-f]{4}$', pid))

    @staticmethod
    def validate_sample(sample: RawMiniSample, prev_sample: Optional[RawMiniSample]) -> Tuple[List[str], List[str]]:
        """
        Validates an individual sample and checks sequence/timestamp against prev_sample.
        Returns: (errors, warnings)
        """
        errors: List[str] = []
        warnings: List[str] = []

        # 1. PID code format
        if not SchemaValidator.validate_pid(sample.pid):
            errors.append(f"INVALID_PID: Row {sample.row_index} has invalid PID format '{sample.pid}'")

        # 2. Status validation
        if sample.status not in VALID_STATUSES:
            errors.append(f"INVALID_STATUS: Row {sample.row_index} has unknown status '{sample.status}'")

        # 3. Quality validation
        if sample.quality not in VALID_QUALITIES:
            warnings.append(f"UNKNOWN_QUALITY: Row {sample.row_index} has non-standard quality '{sample.quality}'")

        # 4. Monotonic timestamp & sequence continuity
        if prev_sample is not None:
            if sample.timestamp_us < prev_sample.timestamp_us:
                errors.append(
                    f"NON_MONOTONIC_TIMESTAMP: Row {sample.row_index} timestamp ({sample.timestamp_us}) "
                    f"< previous ({prev_sample.timestamp_us})"
                )
            elif sample.timestamp_us == prev_sample.timestamp_us:
                warnings.append(
                    f"DUPLICATE_TIMESTAMP: Row {sample.row_index} has identical timestamp as previous ({sample.timestamp_us})"
                )

            if sample.sequence != prev_sample.sequence + 1:
                errors.append(
                    f"DISCONTINUOUS_SEQUENCE: Row {sample.row_index} sequence {sample.sequence} "
                    f"!= expected {prev_sample.sequence + 1}"
                )

        return errors, warnings
