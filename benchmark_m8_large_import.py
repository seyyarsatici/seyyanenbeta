#!/usr/bin/env python3
"""
Seyyanen Mini PC Integration — Large Data Streaming Benchmark
Tests streaming import of 100,000+ samples, measuring throughput (rows/sec) and peak memory.
"""

import os
import sys
import time
import csv
import json
import tempfile
import shutil
import tracemalloc

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seyyanen_mini_import import import_mini_session, preview_mini_session


def generate_benchmark_session(target_dir: str, sample_count: int = 100000):
    os.makedirs(target_dir, exist_ok=True)

    metadata = {
        "session_id": f"BENCH-SESSION-{sample_count}",
        "firmware_version": "1.0.0-m6",
        "mini_protocol_version": "1.0",
        "session_state": "COMPLETED",
        "start_time_iso": "2026-09-20T10:00:00.000Z",
        "duration_seconds": round(sample_count * 0.05, 2),
        "sample_count": sample_count,
        "frame_count": sample_count // 6,
        "error_count": sample_count // 100,
        "protocol": "ISO 15765-4 (CAN 11/500)",
        "adapter_identity": {
            "brand": "VLINKER",
            "adapter_name": "vLinker MC+",
            "firmware": "v2.2",
            "transport": "BLUETOOTH_SPP"
        },
        "vehicle_info": {
            "make": "Chevrolet",
            "model": "Aveo",
            "engine": "1.4L 16V DOHC (F14D3)",
            "vehicle_identity_status": "UNKNOWN"
        },
        "supported_pids": [
            {"pid": "010C", "name": "Engine Speed", "unit": "rpm", "supported": True},
            {"pid": "010B", "name": "Intake Manifold Pressure", "unit": "kPa", "supported": True},
            {"pid": "0111", "name": "Throttle Position", "unit": "%", "supported": True},
            {"pid": "0105", "name": "Engine Coolant Temp", "unit": "degC", "supported": True},
            {"pid": "010D", "name": "Vehicle Speed", "unit": "km/h", "supported": True},
            {"pid": "0104", "name": "Engine Load", "unit": "%", "supported": True},
        ]
    }

    with open(os.path.join(target_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    header = [
        "timestamp_us", "sequence", "frame_id", "pid", "name",
        "request", "raw_response", "decoded_value", "unit",
        "status", "quality", "freshness", "latency_us"
    ]

    csv_path = os.path.join(target_dir, "session.csv")
    cur_ts = 1726840000000000

    pids = [
        ("010C", "RPM", "41 0C 0C 30", "780.00", "rpm"),
        ("010B", "MAP", "41 0B 22", "34.00", "kPa"),
        ("0111", "TPS", "41 11 20", "12.55", "%"),
        ("0104", "LOAD", "41 04 37", "21.57", "%"),
        ("010D", "SPEED", "41 0D 00", "0.00", "km/h"),
        ("0105", "ECT", "41 05 7F", "87.00", "degC"),
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        # Batch writes for fast generator creation
        batch = []
        for i in range(sample_count):
            seq = i + 1
            frame_id = (i // 6) + 1
            pid_item = pids[i % 6]

            # 1% simulated intermittent NO DATA
            if i % 100 == 45:
                row = [
                    str(cur_ts), str(seq), str(frame_id), pid_item[0], pid_item[1],
                    pid_item[0], "NO DATA", "", pid_item[4],
                    "NO_DATA", "NO_DATA", "STALE", "24000"
                ]
            else:
                row = [
                    str(cur_ts), str(seq), str(frame_id), pid_item[0], pid_item[1],
                    pid_item[0], pid_item[2], pid_item[3], pid_item[4],
                    "VALID", "GOOD", "FRESH", "23000"
                ]

            batch.append(row)
            if len(batch) >= 10000:
                writer.writerows(batch)
                batch = []

            cur_ts += 50000  # 50ms step

        if batch:
            writer.writerows(batch)


def run_benchmark(sample_count: int = 100000):
    print("==================================================")
    print(f"  SEYYANEN MINI — M-8 LARGE DATA BENCHMARK")
    print(f"  Target: {sample_count:,} Samples Streaming Import")
    print("==================================================")

    temp_dir = tempfile.mkdtemp(prefix="m8_bench_")
    try:
        t_gen_start = time.perf_counter()
        print("1. Generating synthetic benchmark dataset...")
        generate_benchmark_session(temp_dir, sample_count=sample_count)
        t_gen_end = time.perf_counter()
        csv_size_mb = os.path.getsize(os.path.join(temp_dir, "session.csv")) / (1024 * 1024)
        print(f"   Generated {sample_count:,} samples in {t_gen_end - t_gen_start:.2f}s (CSV Size: {csv_size_mb:.2f} MB)")

        # 2. Preview benchmark
        t_prev_start = time.perf_counter()
        preview = preview_mini_session(temp_dir)
        t_prev_end = time.perf_counter()
        print(f"2. Fast Preview Time: {(t_prev_end - t_prev_start)*1000:.2f} ms (Valid: {preview.is_valid})")

        # 3. Streaming Import benchmark with memory profiling
        tracemalloc.start()
        t_import_start = time.perf_counter()

        # Run with streaming_mode=True to verify non-buffering throughput
        result = import_mini_session(temp_dir, options={"streaming_mode": True})

        t_import_end = time.perf_counter()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        duration = t_import_end - t_import_start
        rows_per_sec = sample_count / duration if duration > 0 else 0

        print("\n3. STREAMING IMPORT PERFORMANCE RESULTS:")
        print(f"   Import Duration:     {duration:.3f} seconds")
        print(f"   Throughput:          {rows_per_sec:,.0f} rows / second")
        print(f"   Peak RAM Usage:      {peak_mem / (1024 * 1024):.2f} MB")
        print(f"   Total Rows Read:     {result.report.rows_read:,}")
        print(f"   Valid Measurements:  {result.report.valid_samples:,}")
        print(f"   Failed Samples:      {result.report.failed_samples:,}")
        print(f"   Errors Detected:     {len(result.report.errors)}")
        print(f"   Success Status:      {result.success}")
        print("==================================================")

        assert result.success, f"Benchmark import failed with errors: {result.report.errors}"
        assert rows_per_sec > 10000, f"Throughput too low: {rows_per_sec} rows/sec"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    count = 100000
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    run_benchmark(count)
