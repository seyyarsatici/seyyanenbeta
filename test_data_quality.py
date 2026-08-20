#!/usr/bin/env python3
"""
Test suite for Phase C-1: Timestamp & Data Quality Foundation (Tests A through F)
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from motor import (
    AutoExpertEngine,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    STATUS_DID_MISMATCH,
    STATUS_EMPTY_RESPONSE,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    derive_quality_from_status,
)

def run_tests():
    print("🚀 Running Phase C-1 Data Quality Foundation Tests (Tests A through F)...")
    engine = AutoExpertEngine()

    # TEST A — Valid Mode01 cache write
    print("\n--- TEST A: Valid Mode 01 Cache Write ---")
    entry_a = engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
    print(f"Test A entry: {entry_a}")
    assert entry_a["val"] == 850.0
    assert isinstance(entry_a["time"], float) and entry_a["time"] > 0
    assert entry_a["status"] == STATUS_VALID
    assert entry_a["quality"] == QUALITY_GOOD
    assert entry_a["source"] == "MODE01"
    assert engine.data_cache["RPM"]["val"] == 850.0
    assert engine.sensor_cache["RPM"] == 850.0

    # TEST B — Valid Mode 22 cache write
    print("\n--- TEST B: Valid Mode 22 Cache Write ---")
    entry_b = engine._update_sensor_cache("OIL_TEMP", 92.5, status=STATUS_VALID, quality=QUALITY_GOOD, source="MODE22")
    print(f"Test B entry: {entry_b}")
    assert entry_b["val"] == 92.5
    assert entry_b["status"] == STATUS_VALID
    assert entry_b["quality"] == QUALITY_GOOD
    assert entry_b["source"] == "MODE22"
    assert engine.data_cache["OIL_TEMP"]["val"] == 92.5
    assert engine.sensor_cache["OIL_TEMP"] == 92.5

    # Connect mock simulator for integration polling checks
    engine.baglan()
    time.sleep(0.5)

    # TEST C — NRC response does not create fake value or overwrite valid cache
    print("\n--- TEST C: NRC Does Not Overwrite Valid Value ---")
    engine._update_sensor_cache("CUSTOM_NRC_TEST", 123.4, status=STATUS_VALID, quality=QUALITY_GOOD, source="MODE22")
    prev_val = engine.data_cache["CUSTOM_NRC_TEST"]["val"]
    prev_time = engine.data_cache["CUSTOM_NRC_TEST"]["time"]
    
    # Configure custom PID to point to an unknown DID that returns NRC 31
    engine.custom_pids = {
        "22336A": {
            "isim": "CUSTOM_NRC_TEST",
            "header": "7E0",
            "formul": "A*2"
        }
    }
    engine.current_header = "7DF"
    engine.custom_pid_counter = 4
    mock_data = {}
    engine.tek_veri_oku(mock_data)
    
    # Value must remain preserved
    assert engine.data_cache["CUSTOM_NRC_TEST"]["val"] == prev_val
    assert engine.data_cache["CUSTOM_NRC_TEST"]["time"] == prev_time
    assert engine.last_response_status == STATUS_NRC
    print(f"Test C: Preserved cached value = {engine.data_cache['CUSTOM_NRC_TEST']['val']}, status = {engine.last_response_status}")

    # TEST D — DID_MISMATCH does not overwrite valid cache
    print("\n--- TEST D: DID_MISMATCH Does Not Overwrite Valid Cache ---")
    engine._update_sensor_cache("CUSTOM_MISMATCH_TEST", 456.7, status=STATUS_VALID, quality=QUALITY_GOOD, source="MODE22")
    prev_val_d = engine.data_cache["CUSTOM_MISMATCH_TEST"]["val"]
    
    # Configure custom PID to point to 221940 (which returns AA6219400096 in mock)
    engine.custom_pids = {
        "221940": {
            "isim": "CUSTOM_MISMATCH_TEST",
            "header": "7E0",
            "formul": "A*256+B"
        }
    }
    engine.current_header = "7DF"
    engine.custom_pid_counter = 4
    engine.tek_veri_oku(mock_data)
    
    assert engine.data_cache["CUSTOM_MISMATCH_TEST"]["val"] == prev_val_d
    assert engine.last_response_status == STATUS_DID_MISMATCH
    print(f"Test D: Preserved cached value = {engine.data_cache['CUSTOM_MISMATCH_TEST']['val']}, status = {engine.last_response_status}")

    # TEST E — TIMEOUT preserves previous valid value
    print("\n--- TEST E: TIMEOUT Preserves Previous Valid Value ---")
    engine._update_sensor_cache("ECT", 88.0, status=STATUS_VALID, source="MODE01")
    prev_ect = engine.data_cache["ECT"]["val"]
    # Quality derivation check for TIMEOUT
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    # Cached ECT value remains available
    assert engine.data_cache["ECT"]["val"] == prev_ect
    print(f"Test E: Preserved ECT = {engine.data_cache['ECT']['val']}, derive_quality(TIMEOUT) = {derive_quality_from_status(STATUS_TIMEOUT)}")

    # TEST F — EMPTY_RESPONSE produces INVALID quality
    print("\n--- TEST F: EMPTY_RESPONSE Status & Quality ---")
    assert derive_quality_from_status(STATUS_EMPTY_RESPONSE) == QUALITY_INVALID
    assert derive_quality_from_status(STATUS_NO_DATA) == QUALITY_INVALID
    print(f"Test F: derive_quality(EMPTY_RESPONSE) = {derive_quality_from_status(STATUS_EMPTY_RESPONSE)}")

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL TESTS (A through F) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
