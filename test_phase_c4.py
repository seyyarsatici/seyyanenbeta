#!/usr/bin/env python3
"""
Test Suite for Phase C-4: Temporal Plausibility Layer (Tests A through I)
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
    QUALITY_SUSPECT,
    PHYSICS_PLAUSIBLE,
    PHYSICS_IMPLAUSIBLE_HIGH,
    PHYSICS_IMPLAUSIBLE_LOW,
    PHYSICS_UNKNOWN,
    TEMPORAL_PLAUSIBLE,
    TEMPORAL_SUSPECT,
    TEMPORAL_UNKNOWN,
    TEMPORAL_LIMITS,
    derive_quality_from_status,
)

def run_tests():
    print("🚀 Running Phase C-4 Temporal Plausibility Tests (Tests A through I)...")
    engine = AutoExpertEngine()

    t0 = time.time()

    # TEST A — First sample
    print("\n--- TEST A: First Sample (No previous history) ---")
    entry_a = engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, timestamp=t0, source="MODE01")
    assert entry_a["status"] == STATUS_VALID
    assert entry_a["quality"] == QUALITY_GOOD
    assert entry_a["temporal_status"] == TEMPORAL_UNKNOWN
    hist_a = engine._get_sensor_history("RPM")
    assert len(hist_a) == 1
    assert hist_a[0]["val"] == 800.0
    print(f"Test A Result: quality={entry_a['quality']}, temporal={entry_a['temporal_status']}, hist_len={len(hist_a)}")

    # TEST B — Normal temporal change (Rate = 100 RPM/s <= 50000)
    print("\n--- TEST B: Normal Temporal Change ---")
    entry_b = engine._update_sensor_cache("RPM", 900.0, status=STATUS_VALID, timestamp=t0 + 1.0, source="MODE01")
    assert entry_b["status"] == STATUS_VALID
    assert entry_b["quality"] == QUALITY_GOOD
    assert entry_b["temporal_status"] == TEMPORAL_PLAUSIBLE
    hist_b = engine._get_sensor_history("RPM")
    assert len(hist_b) == 2
    assert hist_b[-1]["val"] == 900.0
    print(f"Test B Result: quality={entry_b['quality']}, temporal={entry_b['temporal_status']}, hist_len={len(hist_b)}")

    # TEST C — Excessive temporal jump (Rate = 420000 RPM/s > 50000)
    print("\n--- TEST C: Excessive Temporal Jump ---")
    entry_c = engine._update_sensor_cache("RPM", 5100.0, status=STATUS_VALID, timestamp=t0 + 1.01, source="MODE01")
    assert entry_c["status"] == STATUS_VALID
    assert entry_c["quality"] == QUALITY_SUSPECT
    assert entry_c["temporal_status"] == TEMPORAL_SUSPECT
    assert engine.data_cache["RPM"]["val"] == 5100.0
    hist_c = engine._get_sensor_history("RPM")
    # Must NOT enter trusted history (still length 2 with [800, 900])
    assert len(hist_c) == 2
    assert hist_c[-1]["val"] == 900.0
    print(f"Test C Result: quality={entry_c['quality']}, temporal={entry_c['temporal_status']}, cached_val={engine.data_cache['RPM']['val']}, hist_len={len(hist_c)}")

    # TEST D — Physical + Temporal Suspicion (ECT 90 -> 315 in 0.1s)
    print("\n--- TEST D: Physical + Temporal Suspicion ---")
    engine._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, timestamp=t0, source="MODE01")
    entry_d = engine._update_sensor_cache("ECT", 315.0, status=STATUS_VALID, timestamp=t0 + 0.1, source="MODE01")
    assert entry_d["physics_status"] == PHYSICS_IMPLAUSIBLE_HIGH
    assert entry_d["temporal_status"] == TEMPORAL_SUSPECT
    # Physical implausibility takes precedence over temporal suspect
    assert entry_d["quality"] == QUALITY_IMPLAUSIBLE
    hist_d = engine._get_sensor_history("ECT")
    assert len(hist_d) == 1
    assert hist_d[0]["val"] == 90.0
    print(f"Test D Result: quality={entry_d['quality']}, physics={entry_d['physics_status']}, temporal={entry_d['temporal_status']}")

    # TEST E — Invalid communication response
    print("\n--- TEST E: Invalid Communication Response ---")
    entry_e = engine._update_sensor_cache("ECT", None, status=STATUS_TIMEOUT, timestamp=t0 + 0.2)
    assert entry_e["status"] == STATUS_TIMEOUT
    assert entry_e["quality"] == QUALITY_ERROR
    assert "temporal_status" not in entry_e or entry_e.get("temporal_status") is None
    print(f"Test E Result: status={entry_e['status']}, quality={entry_e['quality']}")

    # TEST F — Unknown sensor
    print("\n--- TEST F: Unknown Sensor ---")
    engine._update_sensor_cache("UNREGISTERED_SENSOR", 10.0, status=STATUS_VALID, timestamp=t0, source="MODE01")
    entry_f = engine._update_sensor_cache("UNREGISTERED_SENSOR", 5000.0, status=STATUS_VALID, timestamp=t0 + 0.001, source="MODE01")
    assert entry_f["temporal_status"] == TEMPORAL_UNKNOWN
    assert entry_f["quality"] == QUALITY_GOOD
    print(f"Test F Result: quality={entry_f['quality']}, temporal={entry_f['temporal_status']}")

    # TEST G — Same timestamp (dt = 0)
    print("\n--- TEST G: Same Timestamp (dt = 0) ---")
    engine._update_sensor_cache("SPEED", 50.0, status=STATUS_VALID, timestamp=t0, source="MODE01")
    entry_g = engine._update_sensor_cache("SPEED", 60.0, status=STATUS_VALID, timestamp=t0, source="MODE01")
    assert entry_g["temporal_status"] == TEMPORAL_UNKNOWN
    assert entry_g["quality"] == QUALITY_GOOD
    print(f"Test G Result: temporal={entry_g['temporal_status']}, quality={entry_g['quality']}")

    # TEST H — Recovery from suspect spike
    print("\n--- TEST H: Recovery from Suspect Spike ---")
    # Baseline: RPM has [800, 900] in history. Last entry was suspect 5100.
    # New valid sample: RPM = 950 at t0 + 2.0. Compared against trusted 900 at t0 + 1.0 (Rate = 50 RPM/s <= 50000)
    entry_h = engine._update_sensor_cache("RPM", 950.0, status=STATUS_VALID, timestamp=t0 + 2.0, source="MODE01")
    assert entry_h["temporal_status"] == TEMPORAL_PLAUSIBLE
    assert entry_h["quality"] == QUALITY_GOOD
    hist_h = engine._get_sensor_history("RPM")
    assert len(hist_h) == 3
    assert [x["val"] for x in hist_h] == [800.0, 900.0, 950.0]
    print(f"Test H Result: recovered_val={entry_h['val']}, temporal={entry_h['temporal_status']}, history={[x['val'] for x in hist_h]}")

    # Connect mock simulator for regression checks
    engine.baglan()
    time.sleep(1.0)

    # TEST I — Regression checks (Phase A, B, C-1, C-2, C-3)
    print("\n--- TEST I: Regression Checks ---")
    # Phase A status derivation
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    assert derive_quality_from_status(STATUS_NRC) == QUALITY_INVALID
    
    # Phase B manual DID probe
    probe_res = engine.manual_did_probe("1640", header="7E0")
    print("PROBE_RES in C4:", probe_res)
    assert probe_res["ok"] is True
    assert probe_res["status"] == STATUS_VALID

    # Phase C-2 freshness / age
    assert engine._is_sensor_fresh("RPM", max_age=10000000.0) is True

    # Phase C-3 boundary plausibility
    assert engine._check_physical_plausibility("ECT", 180.0) == PHYSICS_PLAUSIBLE
    assert engine._check_physical_plausibility("ECT", 315.0) == PHYSICS_IMPLAUSIBLE_HIGH

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE C-4 TESTS (Tests A through I) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
