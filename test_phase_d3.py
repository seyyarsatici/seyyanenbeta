#!/usr/bin/env python3
"""
Test Suite for Phase D-3: Diagnostic Test Recommendation Engine (Tests A through O)
"""
import sys
import os
import time
from dataclasses import dataclass

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
    derive_quality_from_status,
)

@dataclass
class MockVehicleProfile:
    motor_kodu: str
    marka: str
    aciklama: str
    yakit_tipi: str
    max_rpm: int
    redline: int
    idle_rpm: int
    hedef_ect: int

def run_tests():
    print("🚀 Running Phase D-3 Diagnostic Test Recommendation Engine Tests (Tests A through O)...")
    engine = AutoExpertEngine()

    def get_test_by_id(test_list, t_id):
        for t in test_list:
            if t["id"] == t_id:
                return t
        return None

    # Helper to populate standard trusted cache for tests
    def populate_trusted_cache():
        engine.data_cache.clear()
        engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("SPEED", 0.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("STFT", 2.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("LTFT", 1.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("MAF", 2.5, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("MAP", 35.0, status=STATUS_VALID, source="MODE01")
        engine._update_sensor_cache("TPS", 15.0, status=STATUS_VALID, source="MODE01")

    # TEST A — Supported lean hypothesis
    print("\n--- TEST A: Supported Lean Hypothesis ---")
    populate_trusted_cache()
    mock_hyp_a = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["FUEL_TRIM_POSITIVE"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_a = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    t_trim_a = get_test_by_id(res_a, "CHECK_FUEL_TRIM")
    assert t_trim_a is not None
    assert t_trim_a["status"] == TEST_RECOMMENDED
    assert t_trim_a["priority"] == TEST_PRIORITY_HIGH
    assert t_trim_a["safety"] == TEST_SAFE_READ
    print(f"Test A Result: id={t_trim_a['id']}, status={t_trim_a['status']}, priority={t_trim_a['priority']}, safety={t_trim_a['safety']}")

    # TEST B — Supported airflow hypothesis
    print("\n--- TEST B: Supported Airflow Hypothesis ---")
    populate_trusted_cache()
    mock_hyp_b = [
        {"id": "AIRFLOW_MEASUREMENT_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["AIRFLOW_LOW"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_b = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_b)
    t_maf_b = get_test_by_id(res_b, "CHECK_MAF_AIRFLOW_CORRELATION")
    assert t_maf_b is not None
    assert t_maf_b["status"] == TEST_RECOMMENDED
    assert t_maf_b["priority"] == TEST_PRIORITY_HIGH
    assert t_maf_b["safety"] == TEST_GUIDED_DRIVER
    print(f"Test B Result: id={t_maf_b['id']}, status={t_maf_b['status']}, priority={t_maf_b['priority']}")

    # TEST C — Supported cooling hypothesis
    print("\n--- TEST C: Supported Cooling Hypothesis ---")
    populate_trusted_cache()
    mock_hyp_c = [
        {"id": "COOLING_SYSTEM_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["ECT_TOO_COLD"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_c = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_c)
    t_cool_c = get_test_by_id(res_c, "CHECK_ECT_WARMUP")
    assert t_cool_c is not None
    assert t_cool_c["status"] == TEST_RECOMMENDED
    assert t_cool_c["priority"] == TEST_PRIORITY_HIGH
    print(f"Test C Result: id={t_cool_c['id']}, status={t_cool_c['status']}, priority={t_cool_c['priority']}")

    # TEST D — Supported correlation hypothesis
    print("\n--- TEST D: Supported Correlation Hypothesis ---")
    populate_trusted_cache()
    mock_hyp_d = [
        {"id": "SENSOR_CORRELATION_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": ["SENSOR_CORRELATION_INCONSISTENT"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_d = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_d)
    t_corr_d = get_test_by_id(res_d, "CHECK_SENSOR_REPEATABILITY")
    assert t_corr_d is not None
    assert t_corr_d["status"] == TEST_RECOMMENDED
    assert t_corr_d["priority"] == TEST_PRIORITY_HIGH
    print(f"Test D Result: id={t_corr_d['id']}, status={t_corr_d['status']}, priority={t_corr_d['priority']}")

    # TEST E — Possible hypothesis
    print("\n--- TEST E: Possible Hypothesis ---")
    populate_trusted_cache()
    mock_hyp_e = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_POSSIBLE, "severity": "WARNING", "title": "", "supporting_evidence": ["FUEL_TRIM_POSITIVE"], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_e = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_e)
    t_trim_e = get_test_by_id(res_e, "CHECK_FUEL_TRIM")
    assert t_trim_e is not None
    assert t_trim_e["status"] in (TEST_RECOMMENDED, TEST_OPTIONAL)
    assert t_trim_e["priority"] == TEST_PRIORITY_MEDIUM
    print(f"Test E Result: id={t_trim_e['id']}, status={t_trim_e['status']}, priority={t_trim_e['priority']}")

    # TEST F — Contradicted hypothesis (no confirmation test generated solely for it)
    print("\n--- TEST F: Contradicted Hypothesis ---")
    populate_trusted_cache()
    mock_hyp_f = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_CONTRADICTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": ["FUEL_TRIM_NEGATIVE"], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_f = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_f)
    assert get_test_by_id(res_f, "CHECK_FUEL_TRIM") is None
    print("Test F Result: No high-priority confirmation test generated for contradicted hypothesis")

    # TEST G — Missing evidence test generation
    print("\n--- TEST G: Missing Evidence Test Generation ---")
    populate_trusted_cache()
    mock_hyp_g = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_POSSIBLE, "severity": "WARNING", "title": "", "supporting_evidence": ["FUEL_TRIM_POSITIVE"], "contradicting_evidence": [], "missing_evidence": ["ENGINE_RUNNING"], "reason": "", "context": {}, "next_step": None}
    ]
    res_g = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_g)
    t_eng_g = get_test_by_id(res_g, "CHECK_ENGINE_STATE_AND_TEMPERATURE")
    assert t_eng_g is not None
    assert t_eng_g["status"] == TEST_RECOMMENDED
    print(f"Test G Result: id={t_eng_g['id']}, status={t_eng_g['status']}")

    # TEST H — Shared test deduplication
    print("\n--- TEST H: Shared Test Deduplication ---")
    populate_trusted_cache()
    mock_hyp_h = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None},
        {"id": "FUEL_SYSTEM_RICH", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_h = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_h)
    trim_tests = [t for t in res_h if t["id"] == "CHECK_FUEL_TRIM"]
    assert len(trim_tests) == 1
    assert "FUEL_SYSTEM_LEAN" in trim_tests[0]["hypotheses"]
    assert "FUEL_SYSTEM_RICH" in trim_tests[0]["hypotheses"]
    print(f"Test H Result: Unique CHECK_FUEL_TRIM with merged hypotheses: {trim_tests[0]['hypotheses']}")

    # TEST I — Safety & Priority ordering
    print("\n--- TEST I: Safety & Priority Ordering ---")
    populate_trusted_cache()
    mock_hyp_i = [
        {"id": "AIRFLOW_MEASUREMENT_ISSUE", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None},
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_i = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_i)
    # Check that SAFE_READ items come before GUIDED_DRIVER items
    safety_sequence = [t["safety"] for t in res_i]
    safe_idx = [i for i, s in enumerate(safety_sequence) if s == TEST_SAFE_READ]
    driver_idx = [i for i, s in enumerate(safety_sequence) if s == TEST_GUIDED_DRIVER]
    if safe_idx and driver_idx:
        assert max(safe_idx) < min(driver_idx)
    print(f"Test I Result: Ordered safety sequence: {safety_sequence}")

    # TEST J — Prerequisite blocking
    print("\n--- TEST J: Prerequisite Blocking ---")
    engine.data_cache.clear()
    # RPM is missing, ECT is present
    engine._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, source="MODE01")
    mock_hyp_j = [
        {"id": "FUEL_SYSTEM_LEAN", "status": HYPOTHESIS_SUPPORTED, "severity": "WARNING", "title": "", "supporting_evidence": [], "contradicting_evidence": [], "missing_evidence": [], "reason": "", "context": {}, "next_step": None}
    ]
    res_j = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_j)
    t_trim_j = get_test_by_id(res_j, "CHECK_FUEL_TRIM")
    assert t_trim_j is not None
    assert t_trim_j["status"] == TEST_BLOCKED
    assert t_trim_j["blocking_reason"] is not None
    print(f"Test J Result: id={t_trim_j['id']}, status={t_trim_j['status']}, blocking_reason='{t_trim_j['blocking_reason']}'")

    # TEST K — No executable commands
    print("\n--- TEST K: No Executable Commands Verification ---")
    for t in res_a:
        assert "command" not in t
        assert "raw_frame" not in t
        assert "payload" not in t
        assert "uds" not in t
        assert t.get("result") is None
    print("Test K Result: All recommendations verified strictly observational (no executable payloads)")

    # TEST L — No repair directives
    print("\n--- TEST L: No Repair Directives Verification ---")
    forbidden_terms = ["replace", "change part", "install new", "repair ", "parça değiştir"]
    for t in res_a + res_b + res_c:
        text_corpus = (t["title"] + " " + t["purpose"] + " " + t["interpretation"] + " " + " ".join(t["procedure"])).lower()
        for term in forbidden_terms:
            assert term not in text_corpus, f"Forbidden repair term '{term}' found in test {t['id']}"
    print("Test L Result: All test descriptions verified free from repair directives")

    # TEST M — No duplicate IDs in one result set
    print("\n--- TEST M: Deterministic Unique Test IDs ---")
    populate_trusted_cache()
    res_m1 = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    res_m2 = engine._recommend_diagnostic_tests(hypotheses=mock_hyp_a)
    assert len(res_m1) == len(res_m2)
    ids = [t["id"] for t in res_m1]
    assert len(ids) == len(set(ids))
    print(f"Test M Result: Deterministic unique IDs verified ({ids})")

    # TEST N — D-1 -> D-2 -> D-3 Full Chain
    print("\n--- TEST N: Full End-to-End Chain (D-1 -> D-2 -> D-3) ---")
    engine.data_cache.clear()
    engine.vehicle_profile = MockVehicleProfile(
        motor_kodu="Z19DTH", marka="OPEL", aciklama="1.9 CDTI", yakit_tipi="DIESEL",
        max_rpm=4500, redline=4500, idle_rpm=820, hedef_ect=90
    )
    # Set positive fuel trim and low MAF on running engine
    engine._update_sensor_cache("RPM", 1200.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("STFT", 18.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("LTFT", 16.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("MAF", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("MAP", 40.0, status=STATUS_VALID, source="MODE01")

    # Call D-3 with hypotheses=None -> internally executes D-1 -> D-2 -> D-3
    chain_tests = engine._recommend_diagnostic_tests()
    chain_test_ids = [t["id"] for t in chain_tests]
    assert "CHECK_FUEL_TRIM" in chain_test_ids
    assert "CHECK_MAF_AIRFLOW_CORRELATION" in chain_test_ids
    print(f"Test N Result: End-to-end chain generated test recommendations: {chain_test_ids}")

    # Connect mock simulator for regression
    engine.baglan()
    time.sleep(0.5)

    # TEST O — Full Phase A/B/C/D-1/D-2 Regression
    print("\n--- TEST O: Phase A/B/C/D-1/D-2 Regression ---")
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    probe_res = engine.manual_did_probe("1640", header="7E0")
    assert probe_res["ok"] is True
    assert engine._is_sensor_fresh("RPM", max_age=1000000.0) is True
    assert engine._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE
    assert engine._check_temporal_plausibility("RPM", 850.0, timestamp=time.time()) == TEMPORAL_PLAUSIBLE
    corr = engine._check_cross_sensor_correlations()
    assert len(corr) == 3
    ev = engine._collect_diagnostic_evidence()
    assert isinstance(ev, list)
    hyp = engine._infer_fault_hypotheses(ev)
    assert isinstance(hyp, list)

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE D-3 TESTS (Tests A through O) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
