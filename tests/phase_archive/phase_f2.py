"""
Phase F-2: Real-Time Data Quality Test Suite
============================================
Comprehensive test suite covering all 25 acceptance criteria:
1. VALID sample -> QUALITY_GOOD
2. NO_DATA -> QUALITY_INVALID
3. NRC -> QUALITY_INVALID
4. TIMEOUT -> QUALITY_ERROR
5. Physical high limit violation (ECT=250) -> QUALITY_IMPLAUSIBLE
6. Physical low limit violation (ECT=-70) -> QUALITY_IMPLAUSIBLE
7. First sample -> TEMPORAL_UNKNOWN (not suspect)
8. Temporal plausibility with normal dt -> TEMPORAL_PLAUSIBLE, QUALITY_GOOD
9. Excessive rate-of-change -> TEMPORAL_SUSPECT, QUALITY_SUSPECT
10. Different dt values produce logically different temporal evaluations
11. Missing cross-sensor data -> CORRELATION_UNKNOWN (not contradictory)
12. Genuine cross-sensor contradiction -> CORRELATION_INCONSISTENT
13. Vehicle operating envelope normal case -> ENVELOPE_NORMAL
14. Operating envelope violation -> ENVELOPE_OUT_OF_RANGE_HIGH
15. Latest successful value preserved across transient failures
16. Failed query is not reported as fresh
17. Quality transition GOOD -> SUSPECT
18. Quality transition SUSPECT -> GOOD
19. Quality transition GOOD -> ERROR
20. Quality history buffer strictly bounded by maxlen
21. Independent quality tracking across multiple PIDs
22. Evaluation failure isolation (malformed sample doesn't crash runtime)
23. Thread-safe snapshot access during live acquisition
24. Existing F-1 live streaming integration
25. Multiple live PID quality tracking on real mock stream
"""

import time
import threading
from live_quality import (
    LiveQualityAssessor,
    DEFAULT_NAME_MAP,
)
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_RUNNING,
    LIVE_STOPPED,
)
from motor import (
    AutoExpertEngine,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    QUALITY_SUSPECT,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NRC,
    STATUS_SERIAL_ERROR,
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
    ENVELOPE_UNKNOWN,
)


def wait_until(predicate, timeout=8.0, interval=0.05):
    """Deterministic polling helper to avoid flaky sleep."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def run_all_tests():
    print("==================================================")
    print("🚀 Starting Phase F-2: Real-Time Data Quality Tests")
    print("==================================================")

    assessor = LiveQualityAssessor(max_age=2.0, history_maxlen=50, transition_maxlen=50)

    # ----------------------------------------------------
    # TEST 1: VALID sample -> QUALITY_GOOD
    # ----------------------------------------------------
    print("\n--- TEST 1: VALID Sample -> QUALITY_GOOD ---")
    s1 = {
        "timestamp": time.time(),
        "pid": "010C",
        "name": "RPM",
        "value": 850.0,
        "unit": "rpm",
        "status": STATUS_VALID,
        "sequence": 1,
    }
    r1 = assessor.evaluate_sample(s1)
    assert r1["quality"] == QUALITY_GOOD, f"Expected GOOD, got {r1['quality']}"
    assert r1["is_trusted"] is True
    assert r1["physical_plausibility"] == PHYSICS_PLAUSIBLE
    print(f"Test 1 Result: quality={r1['quality']}, is_trusted={r1['is_trusted']}")
    print("✅ TEST 1 PASSED: VALID sample classified as QUALITY_GOOD.")

    # ----------------------------------------------------
    # TEST 2: NO_DATA -> QUALITY_INVALID
    # ----------------------------------------------------
    print("\n--- TEST 2: NO_DATA -> QUALITY_INVALID ---")
    s2 = {
        "timestamp": time.time(),
        "pid": "0123",
        "name": "FUEL_RAIL_PRESS",
        "value": None,
        "unit": "kPa",
        "status": STATUS_NO_DATA,
        "sequence": 2,
    }
    r2 = assessor.evaluate_sample(s2)
    assert r2["quality"] == QUALITY_INVALID, f"Expected INVALID, got {r2['quality']}"
    assert r2["is_trusted"] is False
    assert any("NO_DATA" in reason for reason in r2["quality_reasons"])
    print(f"Test 2 Result: quality={r2['quality']}, reasons={r2['quality_reasons']}")
    print("✅ TEST 2 PASSED: NO_DATA classified as QUALITY_INVALID.")

    # ----------------------------------------------------
    # TEST 3: NRC -> QUALITY_INVALID
    # ----------------------------------------------------
    print("\n--- TEST 3: NRC -> QUALITY_INVALID ---")
    s3 = {
        "timestamp": time.time(),
        "pid": "0105",
        "name": "ECT",
        "value": None,
        "unit": "°C",
        "status": STATUS_NRC,
        "sequence": 3,
    }
    r3 = assessor.evaluate_sample(s3)
    assert r3["quality"] == QUALITY_INVALID, f"Expected INVALID, got {r3['quality']}"
    assert r3["is_trusted"] is False
    print(f"Test 3 Result: quality={r3['quality']}")
    print("✅ TEST 3 PASSED: NRC classified as QUALITY_INVALID.")

    # ----------------------------------------------------
    # TEST 4: TIMEOUT -> QUALITY_ERROR
    # ----------------------------------------------------
    print("\n--- TEST 4: TIMEOUT -> QUALITY_ERROR ---")
    s4 = {
        "timestamp": time.time(),
        "pid": "010B",
        "name": "MAP",
        "value": None,
        "unit": "kPa",
        "status": STATUS_TIMEOUT,
        "sequence": 4,
    }
    r4 = assessor.evaluate_sample(s4)
    assert r4["quality"] == QUALITY_ERROR, f"Expected ERROR, got {r4['quality']}"
    assert r4["is_trusted"] is False
    assert any("TIMEOUT" in reason for reason in r4["quality_reasons"])
    print(f"Test 4 Result: quality={r4['quality']}, reasons={r4['quality_reasons']}")
    print("✅ TEST 4 PASSED: TIMEOUT classified as QUALITY_ERROR.")

    # ----------------------------------------------------
    # TEST 5: Physical High Limit Violation
    # ----------------------------------------------------
    print("\n--- TEST 5: Physical High Limit Violation ---")
    # ECT limit is (-60, 180). Send 250 °C
    s5 = {
        "timestamp": time.time(),
        "pid": "0105",
        "name": "ECT",
        "value": 250.0,
        "unit": "°C",
        "status": STATUS_VALID,
        "sequence": 5,
    }
    r5 = assessor.evaluate_sample(s5)
    assert r5["quality"] == QUALITY_IMPLAUSIBLE, f"Expected IMPLAUSIBLE, got {r5['quality']}"
    assert r5["physical_plausibility"] == PHYSICS_IMPLAUSIBLE_HIGH
    assert r5["is_trusted"] is False
    assert any("Physical limit violation" in reason for reason in r5["quality_reasons"])
    print(f"Test 5 Result: quality={r5['quality']}, physics={r5['physical_plausibility']}")
    print("✅ TEST 5 PASSED: Out-of-range high sample classified as QUALITY_IMPLAUSIBLE.")

    # ----------------------------------------------------
    # TEST 6: Physical Low Limit Violation
    # ----------------------------------------------------
    print("\n--- TEST 6: Physical Low Limit Violation ---")
    # ECT limit is (-60, 180). Send -70 °C
    s6 = {
        "timestamp": time.time(),
        "pid": "0105",
        "name": "ECT",
        "value": -70.0,
        "unit": "°C",
        "status": STATUS_VALID,
        "sequence": 6,
    }
    r6 = assessor.evaluate_sample(s6)
    assert r6["quality"] == QUALITY_IMPLAUSIBLE, f"Expected IMPLAUSIBLE, got {r6['quality']}"
    assert r6["physical_plausibility"] == PHYSICS_IMPLAUSIBLE_LOW
    assert r6["is_trusted"] is False
    print(f"Test 6 Result: quality={r6['quality']}, physics={r6['physical_plausibility']}")
    print("✅ TEST 6 PASSED: Out-of-range low sample classified as QUALITY_IMPLAUSIBLE.")

    # ----------------------------------------------------
    # TEST 7: First Sample -> TEMPORAL_UNKNOWN
    # ----------------------------------------------------
    print("\n--- TEST 7: First Sample -> TEMPORAL_UNKNOWN ---")
    # SPEED has no previous history in this assessor
    s7 = {
        "timestamp": time.time(),
        "pid": "010D",
        "name": "SPEED",
        "value": 60.0,
        "unit": "km/h",
        "status": STATUS_VALID,
        "sequence": 7,
    }
    r7 = assessor.evaluate_sample(s7)
    assert r7["quality"] == QUALITY_GOOD
    assert r7["temporal_plausibility"] == TEMPORAL_UNKNOWN, f"Expected TEMPORAL_UNKNOWN, got {r7['temporal_plausibility']}"
    assert r7["is_trusted"] is True
    print(f"Test 7 Result: temporal={r7['temporal_plausibility']}, quality={r7['quality']}")
    print("✅ TEST 7 PASSED: First sample correctly marked TEMPORAL_UNKNOWN without false failure.")

    # ----------------------------------------------------
    # TEST 8: Temporal Plausibility with Normal dt
    # ----------------------------------------------------
    print("\n--- TEST 8: Temporal Plausibility Normal dt ---")
    t0 = time.time()
    s8_1 = {
        "timestamp": t0,
        "pid": "010D",
        "name": "SPEED",
        "value": 60.0,
        "unit": "km/h",
        "status": STATUS_VALID,
        "sequence": 81,
    }
    assessor.evaluate_sample(s8_1)

    # 1.0 second later, speed goes to 65 km/h (rate = 5 km/h/s, max is 100)
    s8_2 = {
        "timestamp": t0 + 1.0,
        "pid": "010D",
        "name": "SPEED",
        "value": 65.0,
        "unit": "km/h",
        "status": STATUS_VALID,
        "sequence": 82,
    }
    r8 = assessor.evaluate_sample(s8_2)
    assert r8["temporal_plausibility"] == TEMPORAL_PLAUSIBLE, f"Expected PLAUSIBLE, got {r8['temporal_plausibility']}"
    assert r8["quality"] == QUALITY_GOOD
    assert r8["rate_of_change"] == 5.0
    print(f"Test 8 Result: rate={r8['rate_of_change']} km/h/s, temporal={r8['temporal_plausibility']}")
    print("✅ TEST 8 PASSED: Normal rate of change evaluates as TEMPORAL_PLAUSIBLE.")

    # ----------------------------------------------------
    # TEST 9: Excessive Rate of Change -> QUALITY_SUSPECT
    # ----------------------------------------------------
    print("\n--- TEST 9: Excessive Rate of Change -> QUALITY_SUSPECT ---")
    # ECT max rate is 20 °C/s. Let's send a 90 °C jump in 0.5s (rate = 180 °C/s)
    t_ect = time.time()
    s9_1 = {
        "timestamp": t_ect,
        "pid": "0105",
        "name": "ECT",
        "value": 85.0,
        "unit": "°C",
        "status": STATUS_VALID,
        "sequence": 91,
    }
    assessor.evaluate_sample(s9_1)

    s9_2 = {
        "timestamp": t_ect + 0.5,
        "pid": "0105",
        "name": "ECT",
        "value": 175.0,  # +90 in 0.5s -> 180 °C/s
        "unit": "°C",
        "status": STATUS_VALID,
        "sequence": 92,
    }
    r9 = assessor.evaluate_sample(s9_2)
    assert r9["temporal_plausibility"] == TEMPORAL_SUSPECT, f"Expected SUSPECT, got {r9['temporal_plausibility']}"
    assert r9["quality"] == QUALITY_SUSPECT, f"Expected QUALITY_SUSPECT, got {r9['quality']}"
    assert r9["is_trusted"] is False
    assert any("Temporal rate-of-change suspect" in reason for reason in r9["quality_reasons"])
    print(f"Test 9 Result: quality={r9['quality']}, rate={r9['rate_of_change']} °C/s")
    print("✅ TEST 9 PASSED: Excessive rate of change marked as QUALITY_SUSPECT.")

    # ----------------------------------------------------
    # TEST 10: Logical Difference with Different dt Values
    # ----------------------------------------------------
    print("\n--- TEST 10: Different dt Values Logic ---")
    # 2000 RPM delta in 0.01s (rate = 200,000 > 50,000 limit -> SUSPECT)
    # vs same 2000 RPM delta in 0.5s (rate = 4,000 < 50,000 limit -> PLAUSIBLE)
    t_rpm = time.time()
    assessor.evaluate_sample({
        "timestamp": t_rpm,
        "pid": "010C",
        "name": "RPM",
        "value": 1000.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })

    # Small dt -> suspect
    r10_small = assessor.evaluate_sample({
        "timestamp": t_rpm + 0.01,
        "pid": "010C",
        "name": "RPM",
        "value": 3000.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    assert r10_small["temporal_plausibility"] == TEMPORAL_SUSPECT

    # Reset base and try large dt -> plausible
    assessor.evaluate_sample({
        "timestamp": t_rpm + 1.0,
        "pid": "010C",
        "name": "RPM",
        "value": 1000.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    r10_large = assessor.evaluate_sample({
        "timestamp": t_rpm + 1.5,
        "pid": "010C",
        "name": "RPM",
        "value": 3000.0,  # 2000 RPM in 0.5s -> 4000/s (well below 50,000)
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    assert r10_large["temporal_plausibility"] == TEMPORAL_PLAUSIBLE
    print("✅ TEST 10 PASSED: Different dt values evaluated logically.")

    # ----------------------------------------------------
    # TEST 11: Missing Companion Sensor -> CORRELATION_UNKNOWN
    # ----------------------------------------------------
    print("\n--- TEST 11: Missing Companion Sensor -> CORRELATION_UNKNOWN ---")
    fresh_assessor = LiveQualityAssessor()
    # Only send TPS (no RPM or MAP yet)
    r11 = fresh_assessor.evaluate_sample({
        "timestamp": time.time(),
        "pid": "0111",
        "name": "TPS",
        "value": 90.0,
        "unit": "%",
        "status": STATUS_VALID,
    })
    assert r11["correlation_status"] == CORRELATION_UNKNOWN
    print(f"Test 11 Result: correlation={r11['correlation_status']}")
    print("✅ TEST 11 PASSED: Missing dependent sensor evaluates to CORRELATION_UNKNOWN.")

    # ----------------------------------------------------
    # TEST 12: Cross-Sensor Inconsistency -> CORRELATION_INCONSISTENT
    # ----------------------------------------------------
    print("\n--- TEST 12: Cross-Sensor Inconsistency ---")
    # RULE 1: Standstill RPM (<= 50) but moving SPEED (>= 10)
    t_corr = time.time()
    fresh_assessor.evaluate_sample({
        "timestamp": t_corr,
        "pid": "010C",
        "name": "RPM",
        "value": 0.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    r12 = fresh_assessor.evaluate_sample({
        "timestamp": t_corr + 0.05,
        "pid": "010D",
        "name": "SPEED",
        "value": 80.0,  # 80 km/h while RPM=0!
        "unit": "km/h",
        "status": STATUS_VALID,
    })
    assert r12["correlation_status"] == CORRELATION_INCONSISTENT
    assert any("RPM_VSS" in cd.get("rule", "") for cd in r12["correlation_details"])
    print(f"Test 12 Result: correlation={r12['correlation_status']}")
    print("✅ TEST 12 PASSED: Real cross-sensor contradiction flagged as CORRELATION_INCONSISTENT.")

    # ----------------------------------------------------
    # TEST 13 & 14: Vehicle Operating Envelope
    # ----------------------------------------------------
    print("\n--- TEST 13 & 14: Vehicle Operating Envelope ---")
    class DummyProfile:
        redline = 6500

    env_engine = AutoExpertEngine()
    env_engine.vehicle_profile = DummyProfile()
    env_assessor = LiveQualityAssessor(engine=env_engine)

    # Below redline -> NORMAL
    r13 = env_assessor.evaluate_sample({
        "timestamp": time.time(),
        "pid": "010C",
        "name": "RPM",
        "value": 3500.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    assert r13["envelope_status"] == ENVELOPE_NORMAL

    # Above redline -> OUT_OF_RANGE_HIGH
    r14 = env_assessor.evaluate_sample({
        "timestamp": time.time() + 0.1,
        "pid": "010C",
        "name": "RPM",
        "value": 7200.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    assert r14["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH
    print(f"Test 13/14 Result: Normal={r13['envelope_status']}, Redline Violation={r14['envelope_status']}")
    print("✅ TEST 13 & 14 PASSED: Operating envelope normal and violation cases verified.")

    # ----------------------------------------------------
    # TEST 15 & 16: Preservation of Last Successful Value & Freshness
    # ----------------------------------------------------
    print("\n--- TEST 15 & 16: Last Successful Value Preservation ---")
    t_succ = time.time()
    assessor.evaluate_sample({
        "timestamp": t_succ,
        "pid": "010C",
        "name": "RPM",
        "value": 850.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    last_succ_before = assessor.get_last_successful("010C")
    assert last_succ_before is not None
    assert last_succ_before["value"] == 850.0

    # Next query is TIMEOUT
    assessor.evaluate_sample({
        "timestamp": t_succ + 0.2,
        "pid": "010C",
        "name": "RPM",
        "value": None,
        "unit": "rpm",
        "status": STATUS_TIMEOUT,
    })

    # Current sample is ERROR and not trusted
    current_q = assessor.get_quality("010C")
    assert current_q["quality"] == QUALITY_ERROR
    assert current_q["is_trusted"] is False
    assert current_q["value"] is None

    # Preserved last successful is STILL 850.0 with original timestamp!
    last_succ_after = assessor.get_last_successful("010C")
    assert last_succ_after["value"] == 850.0
    assert last_succ_after["timestamp"] == t_succ
    print(f"Current quality: {current_q['quality']}, Preserved value: {last_succ_after['value']}")
    print("✅ TEST 15 & 16 PASSED: Last successful value preserved and transient failure not marked fresh.")

    # ----------------------------------------------------
    # TEST 17, 18, 19: Quality Transitions
    # ----------------------------------------------------
    print("\n--- TEST 17, 18, 19: Quality Transitions ---")
    trans_assessor = LiveQualityAssessor(max_age=2.0)
    transitions_captured = []
    trans_assessor._on_quality_change = lambda t: transitions_captured.append(t)

    t_tr = time.time()
    # 1. Base GOOD sample
    trans_assessor.evaluate_sample({
        "timestamp": t_tr,
        "pid": "0105",
        "name": "ECT",
        "value": 80.0,
        "unit": "°C",
        "status": STATUS_VALID,
    })
    assert len(transitions_captured) == 0  # First sample is initial state, not transition

    # 2. Transition GOOD -> SUSPECT (excessive jump)
    trans_assessor.evaluate_sample({
        "timestamp": t_tr + 0.1,
        "pid": "0105",
        "name": "ECT",
        "value": 150.0,  # 70 °C jump in 0.1s -> 700 °C/s
        "unit": "°C",
        "status": STATUS_VALID,
    })
    assert len(transitions_captured) == 1
    t1 = transitions_captured[-1]
    assert t1["old_quality"] == QUALITY_GOOD
    assert t1["new_quality"] == QUALITY_SUSPECT
    print(f"Captured transition 1: {t1['old_quality']} -> {t1['new_quality']}")

    # 3. Transition SUSPECT -> GOOD (plausible continuation)
    trans_assessor.evaluate_sample({
        "timestamp": t_tr + 5.0,
        "pid": "0105",
        "name": "ECT",
        "value": 85.0,  # Jump over 5 seconds is plausible
        "unit": "°C",
        "status": STATUS_VALID,
    })
    assert len(transitions_captured) == 2
    t2 = transitions_captured[-1]
    assert t2["old_quality"] == QUALITY_SUSPECT
    assert t2["new_quality"] == QUALITY_GOOD
    print(f"Captured transition 2: {t2['old_quality']} -> {t2['new_quality']}")

    # 4. Transition GOOD -> ERROR (communication timeout)
    trans_assessor.evaluate_sample({
        "timestamp": t_tr + 5.5,
        "pid": "0105",
        "name": "ECT",
        "value": None,
        "unit": "°C",
        "status": STATUS_TIMEOUT,
    })
    assert len(transitions_captured) == 3
    t3 = transitions_captured[-1]
    assert t3["old_quality"] == QUALITY_GOOD
    assert t3["new_quality"] == QUALITY_ERROR
    print(f"Captured transition 3: {t3['old_quality']} -> {t3['new_quality']}")
    print("✅ TEST 17, 18, 19 PASSED: Quality transitions reliably detected and structured.")

    # ----------------------------------------------------
    # TEST 20: Bounded History
    # ----------------------------------------------------
    print("\n--- TEST 20: Bounded Quality History ---")
    bound_assessor = LiveQualityAssessor(history_maxlen=10)
    for i in range(25):
        bound_assessor.evaluate_sample({
            "timestamp": time.time(),
            "pid": "010C",
            "name": "RPM",
            "value": 800.0 + i,
            "unit": "rpm",
            "status": STATUS_VALID,
        })
    history = bound_assessor.get_quality_history()
    assert len(history) == 10, f"Expected 10, got {len(history)}"
    print(f"History length: {len(history)} (limit: 10)")
    print("✅ TEST 20 PASSED: Quality evaluation history is strictly bounded.")

    # ----------------------------------------------------
    # TEST 21: Independent Multiple PID Tracking
    # ----------------------------------------------------
    print("\n--- TEST 21: Independent Multiple PID Tracking ---")
    pids_assessor = LiveQualityAssessor()
    pids_assessor.evaluate_sample({
        "timestamp": time.time(),
        "pid": "010C",
        "name": "RPM",
        "value": 850.0,
        "unit": "rpm",
        "status": STATUS_VALID,
    })
    pids_assessor.evaluate_sample({
        "timestamp": time.time(),
        "pid": "0105",
        "name": "ECT",
        "value": 300.0,  # Implausible
        "unit": "°C",
        "status": STATUS_VALID,
    })
    pids_assessor.evaluate_sample({
        "timestamp": time.time(),
        "pid": "010D",
        "name": "SPEED",
        "value": None,
        "unit": "km/h",
        "status": STATUS_TIMEOUT,
    })

    q_rpm = pids_assessor.get_quality("010C")
    q_ect = pids_assessor.get_quality("0105")
    q_spd = pids_assessor.get_quality("010D")

    assert q_rpm["quality"] == QUALITY_GOOD
    assert q_ect["quality"] == QUALITY_IMPLAUSIBLE
    assert q_spd["quality"] == QUALITY_ERROR
    snapshot = pids_assessor.get_quality_snapshot()
    assert snapshot["good_count"] == 1
    assert snapshot["implausible_count"] == 1
    assert snapshot["error_count"] == 1
    print(f"Snapshot summary: {snapshot}")
    print("✅ TEST 21 PASSED: Multiple PIDs maintain independent quality states.")

    # ----------------------------------------------------
    # TEST 22: Failure Isolation (Malformed Sample)
    # ----------------------------------------------------
    print("\n--- TEST 22: Failure Isolation ---")
    fail_assessor = LiveQualityAssessor()
    # Deliberately malformed sample with invalid types
    malformed_sample = {
        "timestamp": "invalid_timestamp",
        "pid": "010C",
        "name": "RPM",
        "value": {"bad": "data"},
        "status": STATUS_VALID,
    }
    err_res = fail_assessor.evaluate_sample(malformed_sample)
    assert err_res["quality"] in (QUALITY_ERROR, QUALITY_INVALID)
    # Subsequent normal sample still evaluates cleanly!
    clean_res = fail_assessor.evaluate_sample({
        "timestamp": time.time(),
        "pid": "010D",
        "name": "SPEED",
        "value": 50.0,
        "unit": "km/h",
        "status": STATUS_VALID,
    })
    assert clean_res["quality"] == QUALITY_GOOD
    print("✅ TEST 22 PASSED: Malformed sample trapped gracefully; subsequent evaluation intact.")

    # ----------------------------------------------------
    # TEST 23, 24, 25: LiveAcquisitionRuntime Integration & MockSerial
    # ----------------------------------------------------
    print("\n--- TEST 23, 24, 25: LiveAcquisitionRuntime Integration ---")
    engine = AutoExpertEngine()
    engine.baglan()

    live_pids = ["010C", "010D", "0105"]
    runtime = LiveAcquisitionRuntime(engine=engine, pids=live_pids, cycle_interval=0.05)
    runtime.start()

    # Wait until quality evaluations are present for all live PIDs
    ok = wait_until(lambda: len(runtime.get_quality()) >= 3, timeout=10.0)
    assert ok, f"Expected quality for all live PIDs, got {runtime.get_quality()}"

    # Verify thread-safe snapshot access during live acquisition
    all_q = runtime.get_quality()
    snap = runtime.get_quality_snapshot()
    assert isinstance(all_q, dict)
    for p in live_pids:
        assert p in all_q
        q_item = all_q[p]
        assert "quality" in q_item
        assert "is_trusted" in q_item
        print(f"Live Quality PID {p} ({q_item['name']}): quality={q_item['quality']}, val={q_item['value']}")

    assert snap["total_tracked_pids"] >= 3
    trusted_val = runtime.get_trusted_value("010C")
    assert trusted_val is not None and trusted_val > 0, f"Expected trusted RPM, got {trusted_val}"

    runtime.stop()
    print("✅ TEST 23, 24, 25 PASSED: LiveAcquisitionRuntime seamlessly evaluates and exposes real-time quality.")

    print("\n==================================================")
    print("🎉 ALL 25 PHASE F-2 QUALITY TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    run_all_tests()
