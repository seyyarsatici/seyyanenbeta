#!/usr/bin/env python3
"""
Test Suite for D-Layer Hardening (Tests A through H)
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
    ENVELOPE_NORMAL,
    ENVELOPE_OUT_OF_RANGE_HIGH,
    ENVELOPE_OUT_OF_RANGE_LOW,
    ENVELOPE_UNKNOWN,
    EVIDENCE_SUPPORTED,
    EVIDENCE_CONTRADICTED,
    EVIDENCE_UNKNOWN,
    EVIDENCE_INFO,
    EVIDENCE_WARNING,
    EVIDENCE_CRITICAL,
    HYPOTHESIS_SUPPORTED,
    HYPOTHESIS_POSSIBLE,
    HYPOTHESIS_CONTRADICTED,
    HYPOTHESIS_INSUFFICIENT,
    TEST_RECOMMENDED,
    TEST_OPTIONAL,
    TEST_BLOCKED,
    TEST_NOT_APPLICABLE,
    TEST_PRIORITY_LOW,
    TEST_PRIORITY_MEDIUM,
    TEST_PRIORITY_HIGH,
    TEST_SAFE_READ,
    TEST_GUIDED_DRIVER,
    TEST_WORKSHOP,
    TEST_ACTUATION,
)

def run_hardening_tests():
    print("🚀 Running D-Layer Hardening Tests (Tests A through H)...")
    engine = AutoExpertEngine()

    def get_test_by_id(test_list, t_id):
        for t in test_list:
            if t["id"] == t_id:
                return t
        return None

    def populate_trusted_cache():
        engine.data_cache.clear()
        engine.sensor_history.clear()
        engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("SPEED", 0.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("STFT", 2.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("LTFT", 1.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("MAF", 2.5, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("MAP", 35.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("TPS", 15.0, status=STATUS_VALID, source="MODE01")

    # TEST A: trusted fresh GOOD prerequisite passes
    print("\n--- TEST A: Trusted Fresh GOOD Prerequisite Passes ---")
    populate_trusted_cache()
    mock_hyp_a = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["FUEL_TRIM_POSITIVE"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_a = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    t_trim_a = get_test_by_id(res_a, "CHECK_FUEL_TRIM")
    assert t_trim_a is not None
    assert t_trim_a["status"] == TEST_RECOMMENDED
    assert t_trim_a["blocking_reason"] is None
    print(f"Test A Result: status={t_trim_a['status']}, blocking_reason={t_trim_a['blocking_reason']}")

    # TEST B: QUALITY_SUSPECT prerequisite blocks
    print("\n--- TEST B: QUALITY_SUSPECT Prerequisite Blocks ---")
    populate_trusted_cache()
    # Modify RPM to SUSPECT
    engine.data_cache["RPM"]["quality"] = QUALITY_SUSPECT
    res_b = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    t_trim_b = get_test_by_id(res_b, "CHECK_FUEL_TRIM")
    assert t_trim_b is not None
    assert t_trim_b["status"] == TEST_BLOCKED
    assert "RPM" in t_trim_b["blocking_reason"]
    print(f"Test B Result: status={t_trim_b['status']}, blocking_reason='{t_trim_b['blocking_reason']}'")

    # TEST C: stale GOOD prerequisite blocks
    print("\n--- TEST C: Stale GOOD Prerequisite Blocks ---")
    populate_trusted_cache()
    # Age the RPM entry by modifying timestamp in cache & history
    old_time = time.time() - 20.0
    engine.data_cache["RPM"]["time"] = old_time
    if "RPM" in engine.sensor_history and engine.sensor_history["RPM"]:
        engine.sensor_history["RPM"][-1]["time"] = old_time
    res_c = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    t_trim_c = get_test_by_id(res_c, "CHECK_FUEL_TRIM")
    assert t_trim_c is not None
    assert t_trim_c["status"] == TEST_BLOCKED
    assert "stale" in t_trim_c["blocking_reason"]
    print(f"Test C Result: status={t_trim_c['status']}, blocking_reason='{t_trim_c['blocking_reason']}'")

    # TEST D: QUALITY_IMPLAUSIBLE prerequisite blocks
    print("\n--- TEST D: QUALITY_IMPLAUSIBLE Prerequisite Blocks ---")
    populate_trusted_cache()
    engine.data_cache["RPM"]["quality"] = QUALITY_IMPLAUSIBLE
    res_d = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    t_trim_d = get_test_by_id(res_d, "CHECK_FUEL_TRIM")
    assert t_trim_d is not None
    assert t_trim_d["status"] == TEST_BLOCKED
    assert "IMPLAUSIBLE" in t_trim_d["blocking_reason"]
    print(f"Test D Result: status={t_trim_d['status']}, blocking_reason='{t_trim_d['blocking_reason']}'")

    # TEST E: missing RPM/ECT can still produce CHECK_ENGINE_STATE_AND_TEMPERATURE recommendation (not BLOCKED)
    print("\n--- TEST E: Missing Evidence Test Does Not Block Itself ---")
    engine.data_cache.clear() # Completely empty data cache (no RPM, no ECT)
    mock_hyp_e = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_POSSIBLE, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": ["ENGINE_RUNNING"], "reason": "", "context": {}, "next_step": None}
    ]
    res_e = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_e)
    t_eng_e = get_test_by_id(res_e, "CHECK_ENGINE_STATE_AND_TEMPERATURE")
    assert t_eng_e is not None
    assert t_eng_e["status"] == TEST_RECOMMENDED
    assert t_eng_e["blocking_reason"] is None
    print(f"Test E Result: id={t_eng_e['id']}, status={t_eng_e['status']}, provides_inputs={t_eng_e['provides_inputs']}, blocking_reason={t_eng_e['blocking_reason']}")

    # TEST F: cooling hypothesis does not affect CHECK_SENSOR_REPEATABILITY optional/recommended state
    print("\n--- TEST F: CHECK_SENSOR_REPEATABILITY State Isolation ---")
    populate_trusted_cache()
    # Scenario 1: SENSOR_CORRELATION_ISSUE is SUPPORTED, COOLING_SYSTEM_ISSUE is POSSIBLE (is_cool_supp would be False)
    mock_hyp_f1 = [
        {"id": "SENSOR_CORRELATION_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["SENSOR_CORRELATION_INCONSISTENT"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None},
        {"id": "COOLING_SYSTEM_ISSUE", "status": HYPOTHESIS_POSSIBLE, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_f1 = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_f1)
    t_corr_f1 = get_test_by_id(res_f1, "CHECK_SENSOR_REPEATABILITY")
    assert t_corr_f1["status"] == TEST_RECOMMENDED
    assert t_corr_f1["priority"] == TEST_PRIORITY_HIGH

    # Scenario 2: SENSOR_CORRELATION_ISSUE is SUPPORTED, COOLING_SYSTEM_ISSUE is SUPPORTED
    mock_hyp_f2 = [
        {"id": "SENSOR_CORRELATION_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["SENSOR_CORRELATION_INCONSISTENT"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None},
        {"id": "COOLING_SYSTEM_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_f2 = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_f2)
    t_corr_f2 = get_test_by_id(res_f2, "CHECK_SENSOR_REPEATABILITY")
    assert t_corr_f2["status"] == TEST_RECOMMENDED
    assert t_corr_f2["priority"] == TEST_PRIORITY_HIGH
    print(f"Test F Result: CHECK_SENSOR_REPEATABILITY status is isolated and remains {t_corr_f1['status']} across different cooling hypothesis states")

    # TEST G: D-1 does not reuse stale C-5 result after current cache changes
    print("\n--- TEST G: D-1 Does Not Reuse Stale C-5 Inconsistency ---")
    engine.data_cache.clear()
    engine.sensor_history.clear()
    # Step 1: Set RPM=0, SPEED=120
    engine._update_sensor_cache("RPM", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    c5_res1 = engine._check_cross_sensor_correlations()
    assert any(r["status"] == CORRELATION_INCONSISTENT for r in c5_res1)
    assert any(r["status"] == CORRELATION_INCONSISTENT for r in engine.last_correlation_results)

    # Step 2: Change cache to RPM=800, SPEED=0 (coherent)
    engine.sensor_history.clear()
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 0.0, status=STATUS_VALID, source="MODE01")
    # Step 3: Call D-1 _collect_diagnostic_evidence()
    ev_g = engine._collect_diagnostic_evidence()
    ev_ids_g = [e["id"] for e in ev_g]
    assert "SENSOR_CORRELATION_INCONSISTENT" not in ev_ids_g
    print("Test G Result: Stale C-5 inconsistency was NOT reused by D-1 after cache changed to coherent state")

    # TEST H: D-1 picks up a newly created current C-5 inconsistency
    print("\n--- TEST H: D-1 Picks Up Fresh C-5 Inconsistency ---")
    # Reverse: cache is coherent RPM=800, SPEED=0
    ev_h1 = engine._collect_diagnostic_evidence()
    assert "SENSOR_CORRELATION_INCONSISTENT" not in [e["id"] for e in ev_h1]

    # Change to RPM=0, SPEED=120 without running _check_cross_sensor_correlations manually
    engine.sensor_history.clear()
    engine._update_sensor_cache("RPM", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    ev_h2 = engine._collect_diagnostic_evidence()
    assert "SENSOR_CORRELATION_INCONSISTENT" in [e["id"] for e in ev_h2]
    print("Test H Result: D-1 automatically detected and picked up fresh C-5 inconsistency on current cache snapshot")

    print("\n✅ ALL D-LAYER HARDENING TESTS (Tests A through H) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_hardening_tests()
