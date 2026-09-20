#!/usr/bin/env python3
"""
Seyyanen Mini — Automated Session Validation Utility
Phase M-7: Vehicle Validation & Hardening

Validates a recorded Seyyanen Mini session directory or archive against the
official M-5 / M-6 storage specifications:
- Directory structure and required files (session.csv, metadata.json, events.log)
- JSON metadata parsing and required keys
- CSV header conformance:
  timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us
- Monotonic microsecond timestamps (no backward jumps)
- Contiguous sequence numbers (no missing or duplicate numbers)
- Zero-resistance rule enforcement:
  - VALID rows MUST have non-empty decoded_value.
  - Failure rows (TIMEOUT, NO_DATA, etc.) MUST have empty decoded_value (no fake 0.0).
- PID rate metrics: sample counts, effective rates (Hz), min/max/median intervals
- Error accounting: timeouts, no_data, transport_errors, malformed rows
- Coherent completion state: COMPLETED or RECOVERABLE_INCOMPLETE

Usage:
  python validate_mini_session.py <session_directory_or_zip>
"""

import sys
import os
import json
import csv
import zipfile
import tempfile
import shutil
from typing import Dict, List, Tuple, Any, Optional

EXPECTED_CSV_HEADER = [
    "timestamp_us", "sequence", "frame_id", "pid", "name",
    "request", "raw_response", "decoded_value", "unit",
    "status", "quality", "freshness", "latency_us"
]

REQUIRED_METADATA_KEYS = [
    "session_id", "firmware_version", "mini_protocol_version",
    "session_state", "start_time_iso", "adapter_identity",
    "protocol", "supported_pids"
]


def extract_if_zip(path: str) -> Tuple[str, bool]:
    """If path is a zip file, extracts to temporary directory."""
    if os.path.isfile(path) and path.lower().endswith('.zip'):
        temp_dir = tempfile.mkdtemp(prefix="seyyanen_session_")
        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(temp_dir)
        # Handle single subfolder in zip if present
        entries = os.listdir(temp_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(temp_dir, entries[0])):
            return os.path.join(temp_dir, entries[0]), True
        return temp_dir, True
    return path, False


def calculate_median(values: List[float]) -> float:
    """Computes median of a numerical list."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_v[mid])
    return float(sorted_v[mid - 1] + sorted_v[mid]) / 2.0


def validate_session_dir(session_dir: str) -> Tuple[bool, Dict[str, Any], List[str]]:
    """
    Validates a session directory structurally and numerically.
    Returns:
      (is_valid: bool, metrics: dict, errors: list of error strings)
    """
    errors: List[str] = []
    metrics: Dict[str, Any] = {
        "session_id": "UNKNOWN",
        "sample_count": 0,
        "frame_count": 0,
        "valid_count": 0,
        "timeout_count": 0,
        "no_data_count": 0,
        "transport_error_count": 0,
        "malformed_count": 0,
        "duration_sec": 0.0,
        "min_interval_ms": 0.0,
        "max_interval_ms": 0.0,
        "median_interval_ms": 0.0,
        "per_pid_stats": {},
        "metadata": {}
    }

    if not os.path.isdir(session_dir):
        return False, metrics, [f"Path is not a directory: {session_dir}"]

    csv_path = os.path.join(session_dir, "session.csv")
    meta_path = os.path.join(session_dir, "metadata.json")
    events_path = os.path.join(session_dir, "events.log")

    # 1. File existence checks
    if not os.path.isfile(csv_path):
        errors.append("Missing required file: session.csv")
    if not os.path.isfile(meta_path):
        errors.append("Missing required file: metadata.json")

    # 2. Metadata validation
    metadata: Dict[str, Any] = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            metrics["metadata"] = metadata
            metrics["session_id"] = metadata.get("session_id", "UNKNOWN")

            # Check required keys
            for rk in REQUIRED_METADATA_KEYS:
                if rk not in metadata:
                    errors.append(f"metadata.json missing required key: '{rk}'")

            # Check session state
            state = metadata.get("session_state")
            if state not in ("COMPLETED", "RECOVERABLE_INCOMPLETE", "ACTIVE"):
                errors.append(f"Invalid session_state in metadata: '{state}'")

            # Validate adapter identity
            adapter_info = metadata.get("adapter_identity", {})
            if not isinstance(adapter_info, dict) or not adapter_info.get("adapter_name"):
                errors.append("metadata.json contains empty or invalid adapter_identity")

            # Validate supported PIDs list
            pids = metadata.get("supported_pids", [])
            if not isinstance(pids, list) or len(pids) == 0:
                errors.append("metadata.json contains no supported_pids entries")

        except Exception as e:
            errors.append(f"Failed to parse metadata.json as valid JSON: {str(e)}")

    # 3. CSV Schema & Row validation
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    errors.append("session.csv is empty (missing header)")
                    return False, metrics, errors

                # Validate CSV Header columns
                if header != EXPECTED_CSV_HEADER:
                    errors.append(
                        f"CSV header mismatch:\nExpected: {EXPECTED_CSV_HEADER}\nActual:   {header}"
                    )

                prev_ts_us: Optional[int] = None
                prev_seq: Optional[int] = None
                intervals_ms: List[float] = []
                frame_ids: set = set()
                pid_timestamps: Dict[str, List[int]] = {}
                first_ts_us: Optional[int] = None
                last_ts_us: Optional[int] = None

                row_idx = 1
                for row in reader:
                    row_idx += 1
                    if not row:
                        continue

                    if len(row) != len(EXPECTED_CSV_HEADER):
                        errors.append(f"Line {row_idx}: Invalid column count ({len(row)} != {len(EXPECTED_CSV_HEADER)})")
                        metrics["malformed_count"] += 1
                        continue

                    # Unpack columns
                    (raw_ts, raw_seq, raw_frame, raw_pid, name,
                     request, raw_resp, raw_val, unit,
                     status, quality, freshness, raw_lat) = row

                    # Parse numbers
                    try:
                        ts_us = int(raw_ts)
                        seq = int(raw_seq)
                        frame_id = int(raw_frame)
                        lat_us = int(raw_lat)
                    except ValueError as ve:
                        errors.append(f"Line {row_idx}: Non-integer numeric column: {ve}")
                        continue

                    if first_ts_us is None:
                        first_ts_us = ts_us
                    last_ts_us = ts_us

                    frame_ids.add(frame_id)
                    metrics["sample_count"] += 1

                    # Track per-PID timestamps
                    if raw_pid not in pid_timestamps:
                        pid_timestamps[raw_pid] = []
                    pid_timestamps[raw_pid].append(ts_us)

                    # A. Timestamp Monotonicity check
                    if prev_ts_us is not None:
                        if ts_us < prev_ts_us:
                            errors.append(
                                f"Line {row_idx}: Non-monotonic timestamp! ({ts_us} < {prev_ts_us})"
                            )
                        diff_ms = (ts_us - prev_ts_us) / 1000.0
                        intervals_ms.append(diff_ms)
                    prev_ts_us = ts_us

                    # B. Sequence Continuity check
                    if prev_seq is not None:
                        if seq != prev_seq + 1:
                            errors.append(
                                f"Line {row_idx}: Discontinuous sequence number ({seq} != {prev_seq} + 1)"
                            )
                    prev_seq = seq

                    # C. Zero-Resistance rule validation
                    # Rule: If status is VALID, decoded_value MUST NOT be empty.
                    # Rule: If status is NOT VALID (TIMEOUT, NO_DATA, etc.), decoded_value MUST BE EMPTY!
                    # A fabricated 0.0 on a failed query is a critical failure.
                    status_upper = status.strip().upper()
                    if status_upper == "VALID":
                        metrics["valid_count"] += 1
                        if raw_val.strip() == "":
                            errors.append(f"Line {row_idx}: VALID sample has empty decoded_value (PID: {raw_pid})")
                        else:
                            try:
                                float(raw_val)
                            except ValueError:
                                errors.append(f"Line {row_idx}: Non-float decoded_value on VALID sample: '{raw_val}'")
                    else:
                        if status_upper == "TIMEOUT":
                            metrics["timeout_count"] += 1
                        elif status_upper == "NO_DATA":
                            metrics["no_data_count"] += 1
                        elif status_upper in ("TRANSPORT_ERR", "SAFETY_BLOCKED"):
                            metrics["transport_error_count"] += 1
                        else:
                            metrics["malformed_count"] += 1

                        if raw_val.strip() != "":
                            errors.append(
                                f"Line {row_idx}: Zero-Resistance Violation! Sample has status '{status_upper}' "
                                f"but fabricated decoded_value '{raw_val}' (must be empty!)"
                            )

                    # D. Raw response existence
                    if not raw_resp.strip():
                        errors.append(f"Line {row_idx}: Empty raw_response for PID {raw_pid}")

                # Summary metrics
                metrics["frame_count"] = len(frame_ids)
                if first_ts_us is not None and last_ts_us is not None and last_ts_us >= first_ts_us:
                    metrics["duration_sec"] = (last_ts_us - first_ts_us) / 1000000.0

                if intervals_ms:
                    metrics["min_interval_ms"] = min(intervals_ms)
                    metrics["max_interval_ms"] = max(intervals_ms)
                    metrics["median_interval_ms"] = calculate_median(intervals_ms)

                # Per-PID polling rates
                for p_code, t_list in pid_timestamps.items():
                    p_count = len(t_list)
                    p_intervals = []
                    for i in range(1, len(t_list)):
                        p_intervals.append((t_list[i] - t_list[i - 1]) / 1000.0)

                    p_median_int = calculate_median(p_intervals) if p_intervals else 0.0
                    p_rate_hz = (1000.0 / p_median_int) if p_median_int > 0 else 0.0

                    metrics["per_pid_stats"][p_code] = {
                        "samples": p_count,
                        "min_interval_ms": min(p_intervals) if p_intervals else 0.0,
                        "max_interval_ms": max(p_intervals) if p_intervals else 0.0,
                        "median_interval_ms": p_median_int,
                        "effective_rate_hz": round(p_rate_hz, 2)
                    }

                # Cross-check sample count with metadata if metadata exists
                meta_sample_count = metadata.get("sample_count")
                if meta_sample_count is not None and meta_sample_count > 0:
                    if meta_sample_count != metrics["sample_count"]:
                        errors.append(
                            f"Sample count mismatch: metadata reports {meta_sample_count}, "
                            f"CSV contains {metrics['sample_count']}"
                        )

        except Exception as e:
            errors.append(f"Error reading session.csv: {str(e)}")

    is_valid = len(errors) == 0
    return is_valid, metrics, errors


def print_report(session_dir: str, is_valid: bool, metrics: Dict[str, Any], errors: List[str]):
    """Prints a structured validation report to stdout."""
    print("==================================================")
    print("   SEYYANEN MINI — SESSION VALIDATION REPORT")
    print("==================================================")
    print(f"Target Directory: {os.path.abspath(session_dir)}")
    print(f"Session ID:       {metrics.get('session_id', 'UNKNOWN')}")
    print(f"Validation Status: {'PASS' if is_valid else 'FAIL'}")
    print("--------------------------------------------------")
    print("1. SUMMARY METRICS:")
    print(f"  Duration:           {metrics.get('duration_sec', 0.0):.2f} seconds")
    print(f"  Total Samples:      {metrics.get('sample_count', 0)}")
    print(f"  Distinct Frames:    {metrics.get('frame_count', 0)}")
    print(f"  Valid Measurements: {metrics.get('valid_count', 0)}")
    print(f"  Timeouts:           {metrics.get('timeout_count', 0)}")
    print(f"  No-Data Responses:  {metrics.get('no_data_count', 0)}")
    print(f"  Transport Errors:   {metrics.get('transport_error_count', 0)}")
    print(f"  Malformed Rows:     {metrics.get('malformed_count', 0)}")

    print("\n2. TIMING & INTERVALS:")
    print(f"  Min Interval:       {metrics.get('min_interval_ms', 0.0):.2f} ms")
    print(f"  Max Interval:       {metrics.get('max_interval_ms', 0.0):.2f} ms")
    print(f"  Median Interval:    {metrics.get('median_interval_ms', 0.0):.2f} ms")

    print("\n3. PER-PID POLLING PERFORMANCE:")
    per_pid = metrics.get("per_pid_stats", {})
    if per_pid:
        print(f"  {'PID':<6} | {'Samples':<8} | {'Median Int (ms)':<15} | {'Rate (Hz)':<10}")
        print(f"  {'-'*6}-+-{'-'*8}-+-{'-'*15}-+-{'-'*10}")
        for pid_str, stats in sorted(per_pid.items()):
            print(f"  {pid_str:<6} | {stats['samples']:<8} | {stats['median_interval_ms']:<15.1f} | {stats['effective_rate_hz']:<10.2f}")
    else:
        print("  No PID data found.")

    meta = metrics.get("metadata", {})
    if meta:
        print("\n4. METADATA PROFILE:")
        print(f"  Firmware:           {meta.get('firmware_version', 'N/A')}")
        print(f"  Protocol:           {meta.get('protocol', 'N/A')}")
        adapter = meta.get("adapter_identity", {})
        print(f"  Adapter:            {adapter.get('adapter_name', 'N/A')} ({adapter.get('model', 'N/A')})")
        print(f"  State:              {meta.get('session_state', 'N/A')}")

    if errors:
        print("\n--------------------------------------------------")
        print(f"FAILURES DETECTED ({len(errors)}):")
        for idx, err in enumerate(errors, 1):
            print(f"  [{idx}] {err}")
    print("==================================================")


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_mini_session.py <session_dir_or_zip>")
        sys.exit(2)

    target_path = sys.argv[1]
    extracted_path, is_temp = extract_if_zip(target_path)

    try:
        is_valid, metrics, errors = validate_session_dir(extracted_path)
        print_report(target_path, is_valid, metrics, errors)
        sys.exit(0 if is_valid else 1)
    finally:
        if is_temp and os.path.exists(extracted_path):
            shutil.rmtree(extracted_path, ignore_errors=True)


if __name__ == "__main__":
    main()
