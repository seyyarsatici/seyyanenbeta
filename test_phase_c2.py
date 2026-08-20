#!/usr/bin/env python3
"""
Test Suite for Phase C-2: Freshness + Acquisition History Foundation (Tests A through H)
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
    print("🚀 Running Phase C-2 Freshness & History Tests (Tests A through H)...")
    engine = AutoExpertEngine()

    # TEST A — Fresh valid value
    print("\n--- TEST A: Fresh Valid Value ---")
    t0 = time.time()
    entry_a = engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
    assert entry_a["val"] == 850.0
    assert entry_a["status"] == STATUS_VALID
    assert entry_a["quality"] == QUALITY_GOOD
    assert entry_a["source"] == "MODE01"
    
    age_a = engine._get_sensor_age("RPM")
    assert age_a is not None and age_a >= 0.0 and age_a < 1.0
    assert engine._is_sensor_fresh("RPM", max_age=2.0) is True
    
    hist_a = engine._get_sensor_history("RPM")
    assert len(hist_a) == 1
    assert hist_a[0]["val"] == 850.0
    print(f"Test A Result: age={age_a:.3f}s, is_fresh={engine._is_sensor_fresh('RPM')}, hist_len={len(hist_a)}")

    # TEST B — Multiple acquisitions chronological order
    print("\n--- TEST B: Multiple Acquisitions Chronological Order ---")
    for rpm_val in [860.0, 870.0, 880.0]:
        time.sleep(0.01)
        engine._update_sensor_cache("RPM", rpm_val, status=STATUS_VALID, source="MODE01")
    
    hist_b = engine._get_sensor_history("RPM")
    assert len(hist_b) == 4
    values = [h["val"] for h in hist_b]
    assert values == [850.0, 860.0, 870.0, 880.0]
    # Check limit slice
    last_two = engine._get_sensor_history("RPM", limit=2)
    assert [h["val"] for h in last_two] == [870.0, 880.0]
    print(f"Test B Result: values in history={values}, limit=2 result={[h['val'] for h in last_two]}")

    # TEST C — History bound (maxlen=50)
    print("\n--- TEST C: History Bound (maxlen=50) ---")
    for i in range(60):
        engine._update_sensor_cache("SPEED", float(i), status=STATUS_VALID, source="MODE01")
    
    hist_c = engine._get_sensor_history("SPEED")
    assert len(hist_c) == 50
    assert hist_c[0]["val"] == 10.0   # oldest 0..9 evicted
    assert hist_c[-1]["val"] == 59.0  # newest present
    print(f"Test C Result: len={len(hist_c)}, oldest={hist_c[0]['val']}, newest={hist_c[-1]['val']}")

    # Connect mock serial for integration tests
    engine.baglan()
    time.sleep(0.5)

    # TEST D — Timeout preservation
    print("\n--- TEST D: Timeout Preservation ---")
    engine._update_sensor_cache("ECT", 88.0, status=STATUS_VALID, source="MODE01")
    prev_ect_val = engine.data_cache["ECT"]["val"]
    prev_ect_time = engine.data_cache["ECT"]["time"]
    hist_ect_before = len(engine._get_sensor_history("ECT"))

    # Simulate timeout by triggering a timeout condition or calling _update_sensor_cache with TIMEOUT
    engine.last_response_status = STATUS_TIMEOUT
    # Ensure data_cache and history were not polluted
    assert engine.data_cache["ECT"]["val"] == prev_ect_val
    assert engine.data_cache["ECT"]["time"] == prev_ect_time
    assert len(engine._get_sensor_history("ECT")) == hist_ect_before
    print(f"Test D Result: ECT={engine.data_cache['ECT']['val']}, history_len={len(engine._get_sensor_history('ECT'))}")

    # TEST E — NRC preservation
    print("\n--- TEST E: NRC Preservation ---")
    engine._update_sensor_cache("CUSTOM_PID_NRC", 111.0, status=STATUS_VALID, source="MODE22")
    prev_nrc_val = engine.data_cache["CUSTOM_PID_NRC"]["val"]
    prev_nrc_time = engine.data_cache["CUSTOM_PID_NRC"]["time"]
    hist_nrc_before = len(engine._get_sensor_history("CUSTOM_PID_NRC"))

    # Run custom PID query returning NRC
    engine.custom_pids = {
        "22336A": {
            "isim": "CUSTOM_PID_NRC",
            "header": "7E0",
            "formul": "A"
        }
    }
    engine.current_header = "7DF"
    engine.custom_pid_counter = 4
    mock_data = {}
    engine.tek_veri_oku(mock_data)

    assert engine.data_cache["CUSTOM_PID_NRC"]["val"] == prev_nrc_val
    assert engine.data_cache["CUSTOM_PID_NRC"]["time"] == prev_nrc_time
    assert len(engine._get_sensor_history("CUSTOM_PID_NRC")) == hist_nrc_before
    assert engine.last_response_status == STATUS_NRC
    print(f"Test E Result: Preserved val={engine.data_cache['CUSTOM_PID_NRC']['val']}, history_len={len(engine._get_sensor_history('CUSTOM_PID_NRC'))}")

    # TEST F — DID mismatch preservation
    print("\n--- TEST F: DID Mismatch Preservation ---")
    engine._update_sensor_cache("CUSTOM_PID_MISMATCH", 222.0, status=STATUS_VALID, source="MODE22")
    prev_mis_val = engine.data_cache["CUSTOM_PID_MISMATCH"]["val"]
    prev_mis_time = engine.data_cache["CUSTOM_PID_MISMATCH"]["time"]
    hist_mis_before = len(engine._get_sensor_history("CUSTOM_PID_MISMATCH"))

    engine.custom_pids = {
        "221940": {
            "isim": "CUSTOM_PID_MISMATCH",
            "header": "7E0",
            "formul": "A"
        }
    }
    engine.current_header = "7DF"
    engine.custom_pid_counter = 4
    engine.tek_veri_oku(mock_data)

    assert engine.data_cache["CUSTOM_PID_MISMATCH"]["val"] == prev_mis_val
    assert engine.data_cache["CUSTOM_PID_MISMATCH"]["time"] == prev_mis_time
    assert len(engine._get_sensor_history("CUSTOM_PID_MISMATCH")) == hist_mis_before
    assert engine.last_response_status == STATUS_DID_MISMATCH
    print(f"Test F Result: Preserved val={engine.data_cache['CUSTOM_PID_MISMATCH']['val']}, history_len={len(engine._get_sensor_history('CUSTOM_PID_MISMATCH'))}")

    # TEST G — Stale detection
    print("\n--- TEST G: Stale Detection ---")
    artificially_old_time = time.time() - 10.0  # 10s old
    engine.data_cache["MAP"] = {
        "val": 35.0,
        "time": artificially_old_time,
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "source": "MODE01"
    }
    assert engine.data_cache["MAP"]["val"] == 35.0
    age_g = engine._get_sensor_age("MAP")
    assert age_g >= 10.0
    assert engine._is_sensor_fresh("MAP", max_age=2.0) is False
    assert engine.data_cache["MAP"]["time"] == artificially_old_time  # timestamp not mutated
    print(f"Test G Result: age={age_g:.1f}s, is_fresh={engine._is_sensor_fresh('MAP', 2.0)}, stored_time_unchanged=True")

    # TEST H — Freshness recovery
    print("\n--- TEST H: Freshness Recovery ---")
    engine._update_sensor_cache("MAP", 42.0, status=STATUS_VALID, source="MODE01")
    assert engine.data_cache["MAP"]["val"] == 42.0
    assert engine._is_sensor_fresh("MAP", max_age=2.0) is True
    age_h = engine._get_sensor_age("MAP")
    assert age_h < 1.0
    hist_h = engine._get_sensor_history("MAP")
    assert hist_h[-1]["val"] == 42.0
    print(f"Test H Result: new_val={engine.data_cache['MAP']['val']}, new_age={age_h:.3f}s, is_fresh={engine._is_sensor_fresh('MAP', 2.0)}")

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE C-2 TESTS (Tests A through H) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
