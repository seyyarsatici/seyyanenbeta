"""
Seyyanen Mini PC Integration — Sample Parser
Streaming CSV row parser preserving raw evidence and parsed sample representations.
"""

import csv
from dataclasses import dataclass
from typing import Generator, Optional, Tuple, Dict, Any, List

EXPECTED_HEADER = [
    "timestamp_us", "sequence", "frame_id", "pid", "name",
    "request", "raw_response", "decoded_value", "unit",
    "status", "quality", "freshness", "latency_us"
]


@dataclass
class RawMiniSample:
    row_index: int
    timestamp_us: int
    sequence: int
    frame_id: int
    pid: str
    name: str
    request: str
    raw_response: str
    decoded_value: Optional[float]
    unit: str
    status: str
    quality: str
    freshness: str
    latency_us: int
    raw_decoded_str: str


class SampleParser:
    """Streams and parses rows from session.csv lines."""

    @staticmethod
    def parse_stream(line_generator: Generator[str, None, None]) -> Generator[Tuple[Optional[RawMiniSample], Optional[str]], None, None]:
        """
        Yields (sample, error_string) for each line in the stream.
        """
        reader = csv.reader(line_generator)
        row_idx = 0
        header_checked = False

        for row in reader:
            row_idx += 1
            if not row or (len(row) == 1 and not row[0].strip()):
                continue

            if not header_checked:
                # Validate header
                cleaned_header = [c.strip() for c in row]
                if cleaned_header != EXPECTED_HEADER:
                    yield None, f"SCHEMA_MISMATCH: Invalid header at row 1. Expected {EXPECTED_HEADER}, got {cleaned_header}"
                    return
                header_checked = True
                continue

            if len(row) != len(EXPECTED_HEADER):
                yield None, f"SCHEMA_MISMATCH: Row {row_idx} column count mismatch: expected {len(EXPECTED_HEADER)}, got {len(row)}"
                continue

            (raw_ts, raw_seq, raw_frame, raw_pid, raw_name,
             raw_req, raw_resp, raw_val, raw_unit,
             raw_status, raw_quality, raw_fresh, raw_lat) = [c.strip() for c in row]

            # Parse integers
            try:
                ts_us = int(raw_ts)
            except ValueError:
                yield None, f"INVALID_TIMESTAMP: Row {row_idx} has non-integer timestamp_us: '{raw_ts}'"
                continue

            try:
                seq = int(raw_seq)
            except ValueError:
                yield None, f"INVALID_NUMERIC_VALUE: Row {row_idx} has non-integer sequence: '{raw_seq}'"
                continue

            try:
                frame_id = int(raw_frame)
            except ValueError:
                yield None, f"INVALID_NUMERIC_VALUE: Row {row_idx} has non-integer frame_id: '{raw_frame}'"
                continue

            try:
                lat_us = int(raw_lat)
            except ValueError:
                yield None, f"INVALID_NUMERIC_VALUE: Row {row_idx} has non-integer latency_us: '{raw_lat}'"
                continue

            status_norm = raw_status.upper()
            quality_norm = raw_quality.upper()

            # Zero-Resistance Rule & Decoded Float Parsing
            decoded_float: Optional[float] = None
            if status_norm == "VALID":
                if not raw_val:
                    yield None, f"INVALID_NUMERIC_VALUE: Row {row_idx} has VALID status but empty decoded_value"
                    continue
                try:
                    decoded_float = float(raw_val)
                except ValueError:
                    yield None, f"INVALID_NUMERIC_VALUE: Row {row_idx} non-float decoded_value on VALID sample: '{raw_val}'"
                    continue
            else:
                # Failed sample (TIMEOUT, NO_DATA, etc.)
                if raw_val:
                    # Critical Zero-Resistance violation: fabricated 0.0 or number on failure
                    yield None, f"ZERO_RESISTANCE_VIOLATION: Row {row_idx} has status '{status_norm}' but non-empty decoded_value '{raw_val}'"
                    continue
                decoded_float = None

            sample = RawMiniSample(
                row_index=row_idx,
                timestamp_us=ts_us,
                sequence=seq,
                frame_id=frame_id,
                pid=raw_pid.upper(),
                name=raw_name,
                request=raw_req,
                raw_response=raw_resp,
                decoded_value=decoded_float,
                unit=raw_unit,
                status=status_norm,
                quality=quality_norm,
                freshness=raw_fresh.upper(),
                latency_us=lat_us,
                raw_decoded_str=raw_val,
            )

            yield sample, None
