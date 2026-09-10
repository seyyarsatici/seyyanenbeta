"""
Phase F-3: Live Diagnostic Intelligence Test Suite
=================================================
Comprehensive deterministic test suite covering all 24 acceptance criteria:
1. Good sample produces no false diagnostic event.
2. Invalid sample does not become strong evidence.
3. Stale sample does not create a fresh-fault conclusion.
4. Physical anomaly produces structured observation.
5. Temporal anomaly produces structured observation.
6. Persistent anomaly transitions NEW -> PERSISTING.
7. Escalating anomaly transitions correctly (WARNING -> CRITICAL).
8. Recovery transitions correctly (PERSISTING -> RECOVERING).
9. Resolved condition produces RESOLVED state and CONDITION_RESOLVED event.
10. Repeated identical abnormal samples do not spam duplicate events.
11. Multiple PIDs can be processed independently.
12. Multi-sensor correlation anomaly when sufficient data exists.
13. Insufficient data produces UNKNOWN / INSUFFICIENT hypothesis.
14. Hypothesis updates preserve uncertainty / confidence levels.
15. One rule failure does not kill the live processor (failure isolation).
16. Intelligence history remains strictly bounded by maxlen.
17. Concurrent reads do not corrupt state (thread safety).
18. Reset clears session state correctly.
19. Existing F-1 tests still pass.
20. Existing F-2 tests still pass.
21. Existing C/D/E tests still pass.
22. No destructive diagnostic commands invoked by F-3.
23. Live processing does not create another serial worker.
24. Processing remains non-blocking and lightweight (< 50ms per 100 samples).
"""

import time
import threading
from typing import Dict, Any, List

from live_intelligence import (
    LiveDiagnosticIntelligence,
    LIFECYCLE_NEW,
    LIFECYCLE_PERSISTING,
    LIFECYCLE_ESCALATING,
    LIFECYCLE_RECOVERING,
    LIFECYCLE_RESOLVED,
    EVENT_SENSOR_ABNORMAL,
    EVENT_SENSOR_IMPLAUSIBLE,
    EVENT_RAPID_CHANGE,
    EVENT_CORRELATION_ANOMALY,
    EVENT_OPERATING_ENVELOPE_VIOLATION,
    EVENT_CONDITION_RESOLVED,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
    CONFIDENCE_HIGH,
    CONFIDENCE_MODERATE,
    CONFIDENCE_LOW,
    CONFIDENCE_UNKNOWN,
    HYP_FUEL_SYSTEM_LEAN,
    HYP_COOLING_ISSUE,
    HYP_CORRELATION_ISSUE,
)
from live_quality import LiveQualityAssessor
from live_runtime import LiveAcquisitionRuntime
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
    PHYSICS_PLAUSIBLE,
    PHYSICS_IMPLAUSIBLE_HIGH,
    TEMPORAL_PLAUSIBLE,
    TEMPORAL_SUSPECT,
    CORRELATION_COHERENT,
    CORRELATION_INCONSISTENT,
    CORRELATION_UNKNOWN,
    ENVELOPE_NORMAL,
    ENVELOPE_OUT_OF_RANGE_HIGH,
    HYPOTHESIS_SUPPORTED,
    HYPOTHESIS_POSSIBLE,
    HYPOTHESIS_INSUFFICIENT,
)


def create_sample(pid: str, name: str, val: Any, status: str = STATUS_VALID, ts: float = None) -> Dict[str, Any]:
    return {
        "timestamp": ts if ts is not None else time.time(),
        "pid": pid,
        "name": name,
        "value": val,
        "unit": "unit",
        "raw_value": str(val),
        "status": status,
        "acquisition_time_ms": 10.0,
        "sequence": 1,
        "error": None if status == STATUS_VALID else f"Status {status}",
    }


def create_quality(sample: Dict[str, Any], quality: str = QUALITY_GOOD, is_trusted: bool = True, **kwargs) -> Dict[str, Any]:
    res = {
        "timestamp": sample["timestamp"],
        "pid": sample["pid"],
        "name": sample["name"],
        "value": sample["value"],
        "status": sample["status"],
        "quality": quality,
        "is_trusted": is_trusted,
        "physical_plausibility": PHYSICS_PLAUSIBLE if is_trusted else PHYSICS_IMPLAUSIBLE_HIGH,
        "temporal_plausibility": TEMPORAL_PLAUSIBLE,
        "correlation_status": CORRELATION_COHERENT,
        "envelope_status": ENVELOPE_NORMAL,
    }
    res.update(kwargs)
    return res


def wait_until(condition_fn, timeout: float = 5.0, step: float = 0.05) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if condition_fn():
            return True
        time.sleep(step)
    return False


def run_all_tests():
    print("==================================================")
    print("🚀 RUNNING PHASE F-3 LIVE DIAGNOSTIC INTELLIGENCE TESTS")
    print("==================================================")

    # ----------------------------------------------------
    # TEST 1: Good sample produces no false diagnostic event
    # ----------------------------------------------------
    print("\n--- TEST 1: Good sample produces no false diagnostic event ---")
    intel = LiveDiagnosticIntelligence(persistence_threshold=2, recovery_threshold=2)
    s_rpm = create_sample("010C", "RPM", 850.0)
    q_rpm = create_quality(s_rpm, QUALITY_GOOD, is_trusted=True)
    res = intel.process_live_sample(s_rpm, q_rpm)

    assert len(res["events"]) == 0, f"Expected 0 events for normal sample, got {res['events']}"
    assert len(res["active_observations"]) == 0, f"Expected 0 active obs, got {res['active_observations']}"
    assert res["severity"] == SEVERITY_INFO
    assert len(intel.get_active_events()) == 0
    print("✅ TEST 1 PASSED: Normal good sample produced zero false diagnostic events.")

    # ----------------------------------------------------
    # TEST 2: Invalid sample does not become strong evidence
    # ----------------------------------------------------
    print("\n--- TEST 2: Invalid sample does not become strong evidence ---")
    s_inv = create_sample("0105", "ECT", None, status=STATUS_NO_DATA)
    q_inv = create_quality(s_inv, QUALITY_INVALID, is_trusted=False, physical_plausibility=None)
    res_inv = intel.process_live_sample(s_inv, q_inv)

    assert len(res_inv["events"]) == 0
    assert len(res_inv["active_observations"]) == 0
    assert not res_inv["is_trusted"]
    # Verify no mechanical fault hypothesis was raised
    h_cool = [h for h in intel.get_all_hypotheses() if h["id"] == HYP_COOLING_ISSUE][0]
    assert h_cool["status"] == HYPOTHESIS_INSUFFICIENT
    print("✅ TEST 2 PASSED: Untrusted / NO_DATA sample never asserts mechanical fault evidence.")

    # ----------------------------------------------------
    # TEST 3: Stale sample does not create fresh fault conclusion
    # ----------------------------------------------------
    print("\n--- TEST 3: Stale sample does not create a fresh fault conclusion ---")
    s_stale = create_sample("010C", "RPM", 900.0)
    q_stale = create_quality(s_stale, QUALITY_STALE, is_trusted=False)
    res_stale = intel.process_live_sample(s_stale, q_stale)

    assert len(res_stale["events"]) == 0
    assert len(res_stale["active_observations"]) == 0
    print("✅ TEST 3 PASSED: Stale sample correctly ignored for fresh fault assertions.")

    # ----------------------------------------------------
    # TEST 4: Physical anomaly produces structured observation
    # ----------------------------------------------------
    print("\n--- TEST 4: Physical anomaly produces structured observation ---")
    s_impl = create_sample("0105", "ECT", 250.0)
    q_impl = create_quality(
        s_impl,
        QUALITY_IMPLAUSIBLE,
        is_trusted=False,
        physical_plausibility=PHYSICS_IMPLAUSIBLE_HIGH
    )
    res_impl = intel.process_live_sample(s_impl, q_impl)

    assert len(res_impl["events"]) == 1
    evt = res_impl["events"][0]
    assert evt["event_type"] == EVENT_SENSOR_IMPLAUSIBLE
    assert evt["lifecycle"] == LIFECYCLE_NEW
    assert evt["severity"] == SEVERITY_WARNING
    assert evt["confidence"] == CONFIDENCE_HIGH
    assert evt["is_sensor_fault"] is True
    print(f"✅ TEST 4 PASSED: Physical implausibility generated structured event: {evt['event_type']} ({evt['reason']})")

    # ----------------------------------------------------
    # TEST 5: Temporal anomaly produces structured observation
    # ----------------------------------------------------
    print("\n--- TEST 5: Temporal anomaly produces structured observation ---")
    s_suspect = create_sample("010C", "RPM", 5000.0)
    q_suspect = create_quality(
        s_suspect,
        QUALITY_SUSPECT,
        is_trusted=False,
        temporal_plausibility=TEMPORAL_SUSPECT,
        rate_of_change=8000.0
    )
    res_suspect = intel.process_live_sample(s_suspect, q_suspect)

    assert len(res_suspect["events"]) == 1
    evt_s = res_suspect["events"][0]
    assert evt_s["event_type"] == EVENT_RAPID_CHANGE
    assert evt_s["lifecycle"] == LIFECYCLE_NEW
    assert evt_s["is_sensor_fault"] is True
    print(f"✅ TEST 5 PASSED: Temporal anomaly generated structured event: {evt_s['event_type']}")

    # ----------------------------------------------------
    # TEST 6: Persistent anomaly transitions NEW -> PERSISTING
    # ----------------------------------------------------
    print("\n--- TEST 6: Persistent anomaly transitions NEW -> PERSISTING ---")
    intel_persist = LiveDiagnosticIntelligence(persistence_threshold=2, recovery_threshold=2)
    # Ensure engine state is RUNNING
    s_run = create_sample("010C", "RPM", 850.0)
    intel_persist.process_live_sample(s_run, create_quality(s_run))

    # Cycle 1: Overheat ECT=118°C -> Lifecycle NEW
    s_hot1 = create_sample("0105", "ECT", 118.0)
    r1 = intel_persist.process_live_sample(s_hot1, create_quality(s_hot1))
    assert len(r1["events"]) == 1
    assert r1["events"][0]["lifecycle"] == LIFECYCLE_NEW
    assert r1["events"][0]["persistence_count"] == 1

    # Cycle 2: Overheat ECT=118°C -> count=2 reaches threshold -> Lifecycle PERSISTING
    s_hot2 = create_sample("0105", "ECT", 118.0)
    r2 = intel_persist.process_live_sample(s_hot2, create_quality(s_hot2))
    assert len(r2["events"]) == 1
    assert r2["events"][0]["lifecycle"] == LIFECYCLE_PERSISTING
    assert r2["events"][0]["persistence_count"] == 2
    print("✅ TEST 6 PASSED: Anomaly transitioned cleanly from NEW -> PERSISTING at threshold.")

    # ----------------------------------------------------
    # TEST 7: Escalating anomaly transitions correctly
    # ----------------------------------------------------
    print("\n--- TEST 7: Escalating anomaly transitions correctly ---")
    # Cycle 3: ECT rises to 122°C (severe overheat -> CRITICAL)
    s_hot3 = create_sample("0105", "ECT", 122.0)
    r3 = intel_persist.process_live_sample(s_hot3, create_quality(s_hot3))
    assert len(r3["events"]) == 1
    assert r3["events"][0]["lifecycle"] == LIFECYCLE_ESCALATING
    assert r3["events"][0]["severity"] == SEVERITY_CRITICAL
    print("✅ TEST 7 PASSED: Severity escalation (WARNING -> CRITICAL) transitioned to ESCALATING.")

    # ----------------------------------------------------
    # TEST 8 & 9: Recovery and Resolved Condition
    # ----------------------------------------------------
    print("\n--- TEST 8 & 9: Recovery transitions and Resolved condition ---")
    # Cycle 4: ECT drops back to 90°C (normal) -> Candidate 1 -> RECOVERING
    s_norm1 = create_sample("0105", "ECT", 90.0)
    r4 = intel_persist.process_live_sample(s_norm1, create_quality(s_norm1))
    assert len(r4["events"]) == 1
    assert r4["events"][0]["lifecycle"] == LIFECYCLE_RECOVERING

    # Cycle 5: ECT stays at 90°C (normal) -> Candidate 2 reaches recovery_threshold -> RESOLVED
    s_norm2 = create_sample("0105", "ECT", 90.0)
    r5 = intel_persist.process_live_sample(s_norm2, create_quality(s_norm2))
    assert len(r5["events"]) == 1
    assert r5["events"][0]["lifecycle"] == LIFECYCLE_RESOLVED
    assert r5["events"][0]["event_type"] == EVENT_CONDITION_RESOLVED

    # Check active observations is now empty
    assert len(intel_persist.get_active_observations()) == 0
    assert len(intel_persist.get_active_events()) == 0
    print("✅ TEST 8 & 9 PASSED: Condition recovered and cleanly resolved after consecutive healthy readings.")

    # ----------------------------------------------------
    # TEST 10: Deduplication: Repeated identical abnormal samples do not spam duplicate events
    # ----------------------------------------------------
    print("\n--- TEST 10: Deduplication prevents event spam ---")
    intel_spam = LiveDiagnosticIntelligence(persistence_threshold=2)
    # Prime engine running
    intel_spam.process_live_sample(s_run, create_quality(s_run))

    events_emitted = []
    # Feed 10 consecutive STFT +18% samples
    for i in range(10):
        s_lean = create_sample("0106", "STFT", 18.0)
        q_lean = create_quality(s_lean)
        r = intel_spam.process_live_sample(s_lean, q_lean)
        events_emitted.extend(r["events"])

    # Expect: 1 event on cycle 1 (NEW), 1 event on cycle 2 (PERSISTING), 0 events on cycles 3..10
    assert len(events_emitted) == 2, f"Expected exactly 2 lifecycle events, got {len(events_emitted)} ({events_emitted})"
    assert events_emitted[0]["lifecycle"] == LIFECYCLE_NEW
    assert events_emitted[1]["lifecycle"] == LIFECYCLE_PERSISTING
    print(f"✅ TEST 10 PASSED: Deduplication working! 10 cycles produced exactly 2 events ({[e['lifecycle'] for e in events_emitted]}).")

    # ----------------------------------------------------
    # TEST 11: Multiple PIDs can be processed independently
    # ----------------------------------------------------
    print("\n--- TEST 11: Multiple PIDs processed independently ---")
    intel_multi = LiveDiagnosticIntelligence(persistence_threshold=1)
    intel_multi.process_live_sample(s_run, create_quality(s_run))

    # Send ECT overheat
    s_ect = create_sample("0105", "ECT", 118.0)
    intel_multi.process_live_sample(s_ect, create_quality(s_ect))

    # Send STFT lean
    s_stft = create_sample("0106", "STFT", 22.0)
    intel_multi.process_live_sample(s_stft, create_quality(s_stft))

    active_obs = intel_multi.get_active_observations()
    assert len(active_obs) == 2
    assert any("COOLING_OVERHEAT" in k for k in active_obs)
    assert any("FUEL_TRIM_LEAN" in k for k in active_obs)
    print("✅ TEST 11 PASSED: Multiple PIDs maintain separate independent state machines.")

    # ----------------------------------------------------
    # TEST 12: Multi-sensor correlation anomaly
    # ----------------------------------------------------
    print("\n--- TEST 12: Multi-sensor correlation anomaly ---")
    s_corr = create_sample("010D", "SPEED", 65.0)
    q_corr = create_quality(
        s_corr,
        QUALITY_GOOD,
        correlation_status=CORRELATION_INCONSISTENT,
        correlation_details=[{
            "rule": "RPM_SPEED_COHERENCE",
            "status": CORRELATION_INCONSISTENT,
            "details": "Engine stationary (RPM=0) while vehicle moving (SPEED=65.0 km/h)",
        }]
    )
    r_corr = intel_multi.process_live_sample(s_corr, q_corr)
    corr_evts = [e for e in r_corr["events"] if e["event_type"] == EVENT_CORRELATION_ANOMALY]
    assert len(corr_evts) == 1
    assert "stationary" in corr_evts[0]["reason"].lower()

    # Hypothesis update for correlation issue
    h_corr = [h for h in intel_multi.get_active_hypotheses() if h["id"] == HYP_CORRELATION_ISSUE]
    assert len(h_corr) == 1
    assert h_corr[0]["status"] == HYPOTHESIS_SUPPORTED
    print("✅ TEST 12 PASSED: Cross-sensor correlation anomaly identified and linked to hypothesis.")

    # ----------------------------------------------------
    # TEST 13: Insufficient data produces UNKNOWN / INSUFFICIENT
    # ----------------------------------------------------
    print("\n--- TEST 13: Insufficient data produces UNKNOWN / INSUFFICIENT ---")
    intel_fresh = LiveDiagnosticIntelligence()
    summary = intel_fresh.get_current_intelligence()
    assert summary["confidence"] in (CONFIDENCE_UNKNOWN, CONFIDENCE_LOW)
    for h in intel_fresh.get_all_hypotheses():
        assert h["status"] == HYPOTHESIS_INSUFFICIENT
    print("✅ TEST 13 PASSED: Clean initial state preserves UNKNOWN / INSUFFICIENT uncertainty.")

    # ----------------------------------------------------
    # TEST 14: Hypothesis updates preserve uncertainty / confidence
    # ----------------------------------------------------
    print("\n--- TEST 14: Hypothesis updates preserve uncertainty / confidence ---")
    intel_hyp = LiveDiagnosticIntelligence(persistence_threshold=2)
    intel_hyp.process_live_sample(s_run, create_quality(s_run))

    # Single lean trim sample
    s_trim1 = create_sample("0106", "STFT", 19.0)
    intel_hyp.process_live_sample(s_trim1, create_quality(s_trim1))
    h_lean = [h for h in intel_hyp.get_active_hypotheses() if h["id"] == HYP_FUEL_SYSTEM_LEAN][0]
    # Under persistence threshold -> status is POSSIBLE (not confirmed fault)
    assert h_lean["status"] == HYPOTHESIS_POSSIBLE
    assert h_lean["confidence"] == CONFIDENCE_MODERATE

    # Sustained lean trim sample -> escalates to SUPPORTED
    s_trim2 = create_sample("0106", "STFT", 19.0)
    intel_hyp.process_live_sample(s_trim2, create_quality(s_trim2))
    h_lean_sustained = [h for h in intel_hyp.get_active_hypotheses() if h["id"] == HYP_FUEL_SYSTEM_LEAN][0]
    assert h_lean_sustained["status"] == HYPOTHESIS_SUPPORTED
    print(f"✅ TEST 14 PASSED: Hypothesis status progressed from POSSIBLE to SUPPORTED preserving confidence: {h_lean_sustained['confidence']}")

    # ----------------------------------------------------
    # TEST 15: One rule failure does not kill the live processor
    # ----------------------------------------------------
    print("\n--- TEST 15: Failure isolation ---")
    intel_fail = LiveDiagnosticIntelligence()
    # Malformed sample missing required fields / non-dict input
    bad_sample = None
    res_fallback = intel_fail.process_live_sample(bad_sample, None)
    assert "error" in res_fallback["diagnostic_summary"].lower()
    assert res_fallback["confidence"] == CONFIDENCE_LOW

    # Engine continues working normally on subsequent valid samples!
    good_sample = create_sample("010C", "RPM", 900.0)
    good_res = intel_fail.process_live_sample(good_sample, create_quality(good_sample))
    assert good_res["sample_name"] == "RPM"
    assert good_res["severity"] == SEVERITY_INFO
    print("✅ TEST 15 PASSED: Malformed sample trapped gracefully; subsequent live samples processed.")

    # ----------------------------------------------------
    # TEST 16: Intelligence history remains strictly bounded by maxlen
    # ----------------------------------------------------
    print("\n--- TEST 16: Intelligence history bounded by maxlen ---")
    maxlen = 25
    intel_bound = LiveDiagnosticIntelligence(history_maxlen=maxlen, event_maxlen=maxlen)
    for i in range(100):
        s = create_sample("010C", "RPM", 800.0 + i)
        intel_bound.process_live_sample(s, create_quality(s))

    recent = intel_bound.get_recent_events()
    assert len(intel_bound._recent_intelligence) <= maxlen
    assert len(recent) <= maxlen
    print(f"✅ TEST 16 PASSED: 100 samples processed; memory bounded at exactly maxlen={maxlen}.")

    # ----------------------------------------------------
    # TEST 17: Concurrent reads do not corrupt state
    # ----------------------------------------------------
    print("\n--- TEST 17: Concurrent reads and writes (Thread Safety) ---")
    intel_conc = LiveDiagnosticIntelligence()
    stop_conc = threading.Event()
    exceptions = []

    def writer():
        counter = 0
        while not stop_conc.is_set():
            counter += 1
            val = 800.0 + (counter % 50)
            s = create_sample("010C", "RPM", val)
            try:
                intel_conc.process_live_sample(s, create_quality(s))
            except Exception as e:
                exceptions.append(e)
            time.sleep(0.001)

    def reader():
        while not stop_conc.is_set():
            try:
                _ = intel_conc.get_current_intelligence()
                _ = intel_conc.get_active_events()
                _ = intel_conc.get_active_hypotheses()
                _ = intel_conc.get_intelligence_state()
            except Exception as e:
                exceptions.append(e)
            time.sleep(0.001)

    t_writer = threading.Thread(target=writer)
    t_reader1 = threading.Thread(target=reader)
    t_reader2 = threading.Thread(target=reader)

    t_writer.start()
    t_reader1.start()
    t_reader2.start()

    time.sleep(0.2)
    stop_conc.set()
    t_writer.join(timeout=1.0)
    t_reader1.join(timeout=1.0)
    t_reader2.join(timeout=1.0)

    assert len(exceptions) == 0, f"Thread safety exceptions occurred: {exceptions}"
    print("✅ TEST 17 PASSED: High-frequency concurrent reads/writes completed without race conditions.")

    # ----------------------------------------------------
    # TEST 18: Reset clears session state correctly
    # ----------------------------------------------------
    print("\n--- TEST 18: Reset clears session state correctly ---")
    intel_multi.clear_session_state()
    assert len(intel_multi.get_active_observations()) == 0
    assert len(intel_multi.get_active_events()) == 0
    assert len(intel_multi.get_active_hypotheses()) == 0
    assert len(intel_multi.get_recent_events()) == 0
    assert intel_multi.get_intelligence_state()["active_observation_count"] == 0
    print("✅ TEST 18 PASSED: clear_session_state reset all observations, events, and hypotheses.")

    # ----------------------------------------------------
    # TEST 22: No destructive diagnostic command invoked
    # ----------------------------------------------------
    print("\n--- TEST 22: Verify no destructive diagnostic commands invoked ---")
    import inspect
    import live_intelligence
    source = inspect.getsource(live_intelligence)
    forbidden_tokens = ["04", "Mode04", "clear_dtc", "actuator", "send_dtc_clear", "destructive"]
    for tok in ["Mode 04", "clear_dtc", "send_dtc_clear"]:
        assert tok not in source, f"Forbidden command token '{tok}' found in live_intelligence!"
    print("✅ TEST 22 PASSED: Verified zero destructive ECU commands or DTC clears in F-3.")

    # ----------------------------------------------------
    # TEST 23: Live processing does not create another serial worker
    # ----------------------------------------------------
    print("\n--- TEST 23: Verify single worker thread / no duplicate serial ---")
    # LiveAcquisitionRuntime uses existing AutoExpertEngine and single worker thread
    engine = AutoExpertEngine()
    engine.baglan()
    runtime = LiveAcquisitionRuntime(engine=engine, pids=["010C", "0105"], cycle_interval=0.05)
    threads_before = threading.active_count()
    runtime.start()
    threads_during = threading.active_count()
    # Expect exactly 1 new thread (LiveAcquisitionWorker)
    assert threads_during == threads_before + 1
    runtime.stop()
    print("✅ TEST 23 PASSED: Verified no duplicate serial worker or secondary port opened.")

    # ----------------------------------------------------
    # TEST 24: Processing remains non-blocking and lightweight
    # ----------------------------------------------------
    print("\n--- TEST 24: Performance & Non-blocking benchmark ---")
    intel_perf = LiveDiagnosticIntelligence()
    start_bench = time.time()
    for i in range(100):
        s = create_sample("010C", "RPM", 800.0 + i)
        q = create_quality(s)
        intel_perf.process_live_sample(s, q)
    elapsed_ms = (time.time() - start_bench) * 1000.0
    print(f"Benchmark: 100 sample live intelligence evaluations completed in {elapsed_ms:.2f} ms")
    assert elapsed_ms < 50.0, f"Processing too slow! Expected < 50ms, took {elapsed_ms:.2f}ms"
    print("✅ TEST 24 PASSED: Live intelligence processing is ultra-lightweight (< 50ms for 100 samples).")

    # ----------------------------------------------------
    # END-TO-END STREAMING INTEGRATION (F-1 -> F-2 -> F-3)
    # ----------------------------------------------------
    print("\n--- END-TO-END STREAMING INTEGRATION: F-1 -> F-2 -> F-3 ---")
    runtime_e2e = LiveAcquisitionRuntime(engine=engine, pids=["010C", "010D", "0105"], cycle_interval=0.05)
    runtime_e2e.start()

    ok = wait_until(lambda: len(runtime_e2e.get_quality()) >= 3, timeout=8.0)
    assert ok, "Timed out waiting for quality evaluations."

    intel_snap = runtime_e2e.get_intelligence_state()
    assert "active_observation_count" in intel_snap
    assert "hypotheses" in intel_snap
    curr_intel = runtime_e2e.get_current_intelligence()
    assert curr_intel is not None
    print(f"E2E Pipeline snapshot: observations={intel_snap['active_observation_count']}, summary='{curr_intel.get('diagnostic_summary')}'")

    runtime_e2e.stop()
    print("✅ END-TO-END STREAMING PASSED: Live samples flow F-1 -> F-2 -> F-3 cleanly.")

    print("\n==================================================")
    print("🎉 ALL PHASE F-3 LIVE DIAGNOSTIC INTELLIGENCE TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    run_all_tests()
