#!/usr/bin/env python3
"""
Test Suite for Phase C-5: Cross-Sensor Correlation Layer (Tests A through L)
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
    CORRELATION_COHERENT,
    CORRELATION_INCONSISTENT,
    CORRELATION_UNKNOWN,
    CORRELATION_THRESHOLDS,
    derive_quality_from_status,
)

def run_tests():
    print("🚀 Running Phase C-5 Cross-Sensor Correlation Tests (Tests A through L)...")
    engine = AutoExpertEngine()

    def get_result_by_rule(results, rule_name):
        for r in results:
            if r["rule"] == rule_name:
                return r
        return None

    # TEST A — RPM/SPEED contradiction (RPM=0, SPEED=120)
    print("\n--- TEST A: RPM/SPEED Contradiction (RPM=0, SPEED=120) ---")
    engine._update_sensor_cache("RPM", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    res_a = engine._check_cross_sensor_correlations()
    r_vss_a = get_result_by_rule(res_a, "RPM_VSS")
    assert r_vss_a is not None
    assert r_vss_a["status"] == CORRELATION_INCONSISTENT
    print(f"Test A Result: rule={r_vss_a['rule']}, status={r_vss_a['status']}, details={r_vss_a['details']}")

    # TEST B — RPM/SPEED coherent (RPM=800, SPEED=0)
    print("\n--- TEST B: RPM/SPEED Coherent (RPM=800, SPEED=0) ---")
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 0.0, status=STATUS_VALID, source="MODE01")
    res_b = engine._check_cross_sensor_correlations()
    r_vss_b = get_result_by_rule(res_b, "RPM_VSS")
    assert r_vss_b is not None
    assert r_vss_b["status"] == CORRELATION_COHERENT
    print(f"Test B Result: rule={r_vss_b['rule']}, status={r_vss_b['status']}")

    # TEST C — High TPS / Low RPM contradiction (TPS=90, RPM=800)
    print("\n--- TEST C: High TPS / Low RPM Contradiction (TPS=90, RPM=800) ---")
    engine._update_sensor_cache("TPS", 90.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    res_c = engine._check_cross_sensor_correlations()
    r_tps_c = get_result_by_rule(res_c, "TPS_RPM")
    assert r_tps_c is not None
    assert r_tps_c["status"] == CORRELATION_INCONSISTENT
    print(f"Test C Result: rule={r_tps_c['rule']}, status={r_tps_c['status']}, details={r_tps_c['details']}")

    # TEST D — High TPS / normal RPM (TPS=90, RPM=2500)
    print("\n--- TEST D: High TPS / Normal RPM (TPS=90, RPM=2500) ---")
    engine._update_sensor_cache("TPS", 90.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("RPM", 2500.0, status=STATUS_VALID, source="MODE01")
    res_d = engine._check_cross_sensor_correlations()
    r_tps_d = get_result_by_rule(res_d, "TPS_RPM")
    assert r_tps_d is not None
    assert r_tps_d["status"] == CORRELATION_COHERENT
    print(f"Test D Result: rule={r_tps_d['rule']}, status={r_tps_d['status']}")

    # TEST E — High TPS / extremely low MAP (TPS=90, RPM=2000, MAP=15)
    print("\n--- TEST E: High TPS / Extremely Low MAP (TPS=90, RPM=2000, MAP=15) ---")
    engine._update_sensor_cache("TPS", 90.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("RPM", 2000.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("MAP", 15.0, status=STATUS_VALID, source="MODE01")
    res_e = engine._check_cross_sensor_correlations()
    r_map_e = get_result_by_rule(res_e, "TPS_MAP")
    assert r_map_e is not None
    assert r_map_e["status"] == CORRELATION_INCONSISTENT
    print(f"Test E Result: rule={r_map_e['rule']}, status={r_map_e['status']}, details={r_map_e['details']}")

    # TEST F — Coherent TPS/MAP (TPS=90, RPM=2500, MAP=90)
    print("\n--- TEST F: Coherent TPS/MAP (TPS=90, RPM=2500, MAP=90) ---")
    engine._update_sensor_cache("TPS", 90.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("RPM", 2500.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("MAP", 90.0, status=STATUS_VALID, source="MODE01")
    res_f = engine._check_cross_sensor_correlations()
    r_map_f = get_result_by_rule(res_f, "TPS_MAP")
    assert r_map_f is not None
    assert r_map_f["status"] == CORRELATION_COHERENT
    print(f"Test F Result: rule={r_map_f['rule']}, status={r_map_f['status']}")

    # TEST G — Missing data
    print("\n--- TEST G: Missing Data ---")
    engine.data_cache.pop("SPEED", None)
    res_g = engine._check_cross_sensor_correlations()
    r_vss_g = get_result_by_rule(res_g, "RPM_VSS")
    assert r_vss_g is not None
    assert r_vss_g["status"] == CORRELATION_UNKNOWN
    print(f"Test G Result: rule={r_vss_g['rule']}, status={r_vss_g['status']}")

    # TEST H — Implausible input excluded (RPM=31500 implausible, SPEED=120)
    print("\n--- TEST H: Implausible Input Excluded ---")
    engine._update_sensor_cache("RPM", 31500.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    assert engine.data_cache["RPM"]["quality"] == QUALITY_IMPLAUSIBLE
    res_h = engine._check_cross_sensor_correlations()
    r_vss_h = get_result_by_rule(res_h, "RPM_VSS")
    assert r_vss_h["status"] == CORRELATION_UNKNOWN
    print(f"Test H Result: RPM quality={engine.data_cache['RPM']['quality']}, correlation_status={r_vss_h['status']}")

    # TEST I — Temporally suspect input excluded
    print("\n--- TEST I: Temporally Suspect Input Excluded ---")
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, timestamp=1000.0, source="MODE01")
    # Spike TPS by 90% in 0.001s (rate = 90000 %/s > 500)
    engine._update_sensor_cache("TPS", 10.0, status=STATUS_VALID, timestamp=1000.0, source="MODE01")
    engine._update_sensor_cache("TPS", 90.0, status=STATUS_VALID, timestamp=1000.001, source="MODE01")
    assert engine.data_cache["TPS"]["quality"] == QUALITY_SUSPECT
    res_i = engine._check_cross_sensor_correlations()
    r_tps_i = get_result_by_rule(res_i, "TPS_RPM")
    assert r_tps_i["status"] == CORRELATION_UNKNOWN
    print(f"Test I Result: TPS quality={engine.data_cache['TPS']['quality']}, correlation_status={r_tps_i['status']}")

    # TEST J — Freshness requirement
    print("\n--- TEST J: Freshness Requirement ---")
    stale_time = time.time() - 10.0
    engine.data_cache["RPM"] = {
        "val": 0.0,
        "time": stale_time,
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "source": "MODE01"
    }
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    assert engine._is_sensor_fresh("RPM", max_age=2.0) is False
    res_j = engine._check_cross_sensor_correlations()
    r_vss_j = get_result_by_rule(res_j, "RPM_VSS")
    assert r_vss_j["status"] == CORRELATION_UNKNOWN
    print(f"Test J Result: is_fresh={engine._is_sensor_fresh('RPM')}, correlation_status={r_vss_j['status']}")

    # TEST K — No false quality mutation
    print("\n--- TEST K: No False Quality Mutation ---")
    engine._update_sensor_cache("RPM", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    prev_rpm_q = engine.data_cache["RPM"]["quality"]
    prev_speed_q = engine.data_cache["SPEED"]["quality"]
    res_k = engine._check_cross_sensor_correlations()
    r_vss_k = get_result_by_rule(res_k, "RPM_VSS")
    assert r_vss_k["status"] == CORRELATION_INCONSISTENT
    assert engine.data_cache["RPM"]["quality"] == prev_rpm_q == QUALITY_GOOD
    assert engine.data_cache["SPEED"]["quality"] == prev_speed_q == QUALITY_GOOD
    print(f"Test K Result: correlation={r_vss_k['status']}, RPM quality remained={engine.data_cache['RPM']['quality']}, SPEED quality remained={engine.data_cache['SPEED']['quality']}")

    # Connect mock simulator for regression
    engine.baglan()
    time.sleep(0.5)

    # TEST L — Phase A/B/C regression
    print("\n--- TEST L: Regression Checks ---")
    # Phase A status derivation
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    assert derive_quality_from_status(STATUS_NRC) == QUALITY_INVALID
    
    # Phase B manual DID probe
    probe_res = engine.manual_did_probe("1640", header="7E0")
    assert probe_res["ok"] is True
    assert probe_res["status"] == STATUS_VALID

    # Phase C-2 history
    hist = engine._get_sensor_history("SPEED")
    assert len(hist) > 0

    # Phase C-3 physical check
    assert engine._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE

    # Phase C-4 temporal check
    assert engine._check_temporal_plausibility("RPM", 850.0, timestamp=time.time()) == TEMPORAL_PLAUSIBLE

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE C-5 TESTS (Tests A through L) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
