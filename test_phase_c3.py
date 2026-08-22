#!/usr/bin/env python3
"""
Test Suite for Phase C-3: Single-Sensor Physical Plausibility Layer (Tests A through H)
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
    QUALITY_IMPLAUSIBLE,
    PHYSICS_PLAUSIBLE,
    PHYSICS_IMPLAUSIBLE_HIGH,
    PHYSICS_IMPLAUSIBLE_LOW,
    PHYSICS_UNKNOWN,
    PHYSICAL_LIMITS,
    derive_quality_from_status,
)

def run_tests():
    print("🚀 Running Phase C-3 Physical Plausibility Tests (Tests A through H)...")
    engine = AutoExpertEngine()

    # TEST A — Plausible ECT (90°C)
    print("\n--- TEST A: Plausible ECT (90°C) ---")
    entry_a = engine._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, source="MODE01")
    assert entry_a["status"] == STATUS_VALID
    assert entry_a["quality"] == QUALITY_GOOD
    assert entry_a["physics_status"] == PHYSICS_PLAUSIBLE
    hist_a = engine._get_sensor_history("ECT")
    assert len(hist_a) == 1
    assert hist_a[0]["val"] == 90.0
    print(f"Test A Result: status={entry_a['status']}, quality={entry_a['quality']}, physics={entry_a['physics_status']}, hist_len={len(hist_a)}")

    # TEST B — Implausibly High ECT (315°C)
    print("\n--- TEST B: Implausibly High ECT (315°C) ---")
    entry_b = engine._update_sensor_cache("ECT", 315.0, status=STATUS_VALID, source="MODE01")
    assert entry_b["status"] == STATUS_VALID
    assert entry_b["quality"] == QUALITY_IMPLAUSIBLE
    assert entry_b["physics_status"] == PHYSICS_IMPLAUSIBLE_HIGH
    assert engine.data_cache["ECT"]["val"] == 315.0
    hist_b = engine._get_sensor_history("ECT")
    # History must not contain 315.0 (still length 1 with 90.0)
    assert len(hist_b) == 1
    assert hist_b[0]["val"] == 90.0
    print(f"Test B Result: status={entry_b['status']}, quality={entry_b['quality']}, physics={entry_b['physics_status']}, cached_val={engine.data_cache['ECT']['val']}, hist_len={len(hist_b)}")

    # TEST C — Implausibly Low ECT (-100°C)
    print("\n--- TEST C: Implausibly Low ECT (-100°C) ---")
    entry_c = engine._update_sensor_cache("ECT", -100.0, status=STATUS_VALID, source="MODE01")
    assert entry_c["status"] == STATUS_VALID
    assert entry_c["quality"] == QUALITY_IMPLAUSIBLE
    assert entry_c["physics_status"] == PHYSICS_IMPLAUSIBLE_LOW
    assert engine.data_cache["ECT"]["val"] == -100.0
    hist_c = engine._get_sensor_history("ECT")
    assert len(hist_c) == 1
    assert hist_c[0]["val"] == 90.0
    print(f"Test C Result: status={entry_c['status']}, quality={entry_c['quality']}, physics={entry_c['physics_status']}, hist_len={len(hist_c)}")

    # TEST D — Unknown Sensor
    print("\n--- TEST D: Unknown Sensor ---")
    entry_d = engine._update_sensor_cache("CUSTOM_NEW_SENSOR", 42.0, status=STATUS_VALID, source="MODE01")
    assert entry_d["status"] == STATUS_VALID
    assert entry_d["quality"] == QUALITY_GOOD
    assert entry_d["physics_status"] == PHYSICS_UNKNOWN
    hist_d = engine._get_sensor_history("CUSTOM_NEW_SENSOR")
    assert len(hist_d) == 1
    assert hist_d[0]["val"] == 42.0
    print(f"Test D Result: status={entry_d['status']}, quality={entry_d['quality']}, physics={entry_d['physics_status']}")

    # TEST E — Boundary Values (-60°C and 180°C inclusive)
    print("\n--- TEST E: Boundary Values ---")
    entry_e_low = engine._update_sensor_cache("ECT", -60.0, status=STATUS_VALID, source="MODE01")
    assert entry_e_low["physics_status"] == PHYSICS_PLAUSIBLE
    assert entry_e_low["quality"] == QUALITY_GOOD

    entry_e_high = engine._update_sensor_cache("ECT", 180.0, status=STATUS_VALID, source="MODE01")
    assert entry_e_high["physics_status"] == PHYSICS_PLAUSIBLE
    assert entry_e_high["quality"] == QUALITY_GOOD
    print(f"Test E Result: -60.0 -> {entry_e_low['physics_status']}, 180.0 -> {entry_e_high['physics_status']}")

    # Connect mock simulator for integration tests
    engine.baglan()
    time.sleep(0.5)

    # TEST F — Mode22 Integration (Implausible value)
    print("\n--- TEST F: Mode22 Integration (Implausible Decoded Value) ---")
    # DID 1640 returns 6216400096 in mock (bytes 0x00, 0x96 -> 150).
    # Configure formula to produce MAP = 350 (exceeds max 300)
    engine.custom_pids = {
        "221640": {
            "isim": "MAP",
            "header": "7E0",
            "formul": "B + 200"  # 150 + 200 = 350
        }
    }
    engine.current_header = "7DF"
    engine.custom_pid_counter = 4
    hist_map_before = len(engine._get_sensor_history("MAP"))
    mock_data = {}
    engine.tek_veri_oku(mock_data)

    assert engine.data_cache["MAP"]["val"] == 350.0
    assert engine.data_cache["MAP"]["quality"] == QUALITY_IMPLAUSIBLE
    assert engine.data_cache["MAP"]["physics_status"] == PHYSICS_IMPLAUSIBLE_HIGH
    assert len(engine._get_sensor_history("MAP")) == hist_map_before
    print(f"Test F Result: Mode22 MAP={engine.data_cache['MAP']['val']}, quality={engine.data_cache['MAP']['quality']}, physics={engine.data_cache['MAP']['physics_status']}")

    # TEST G — Recovery
    print("\n--- TEST G: Recovery ---")
    # First: ECT = 315 (implausible)
    engine._update_sensor_cache("ECT", 315.0, status=STATUS_VALID, source="MODE01")
    assert engine.data_cache["ECT"]["quality"] == QUALITY_IMPLAUSIBLE
    assert engine.data_cache["ECT"]["physics_status"] == PHYSICS_IMPLAUSIBLE_HIGH
    hist_len_before_g = len(engine._get_sensor_history("ECT"))

    # Second: ECT = 91 (plausible recovery)
    engine._update_sensor_cache("ECT", 91.0, status=STATUS_VALID, source="MODE01")
    assert engine.data_cache["ECT"]["val"] == 91.0
    assert engine.data_cache["ECT"]["quality"] == QUALITY_GOOD
    assert engine.data_cache["ECT"]["physics_status"] == PHYSICS_PLAUSIBLE
    hist_g = engine._get_sensor_history("ECT")
    assert len(hist_g) == hist_len_before_g + 1
    assert hist_g[-1]["val"] == 91.0
    print(f"Test G Result: recovered ECT={engine.data_cache['ECT']['val']}, quality={engine.data_cache['ECT']['quality']}, physics={engine.data_cache['ECT']['physics_status']}")

    # TEST H — Regression Checks (Phase A, B, C-1, C-2)
    print("\n--- TEST H: Regression Checks ---")
    # 1. Phase A: derive_quality_from_status
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    assert derive_quality_from_status(STATUS_NRC) == QUALITY_INVALID
    assert derive_quality_from_status(STATUS_DID_MISMATCH) == QUALITY_INVALID
    
    # 2. Phase B: manual_did_probe
    probe_res = engine.manual_did_probe("1640", header="7E0")
    assert probe_res["ok"] is True
    assert probe_res["status"] == STATUS_VALID
    
    # 3. Phase C-2: Freshness / Age
    assert engine._is_sensor_fresh("ECT", max_age=2.0) is True
    assert engine._get_sensor_age("ECT") < 1.0

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE C-3 TESTS (Tests A through H) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
