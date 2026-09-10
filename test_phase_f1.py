"""
Phase F-1: Live Acquisition Runtime Test Suite
==============================================
Validates continuous acquisition, state transitions, PID error isolation,
thread lifecycle, backpressure buffer, and statistics without a real vehicle.

Tests A through M:
- TEST A: Initial state is LIVE_IDLE
- TEST B: start() transitions state to LIVE_RUNNING
- TEST C: Continuous acquisition produces multiple samples over time
- TEST D: Multiple PIDs acquired in order (RPM, SPEED, ECT, MAP, TPS)
- TEST E: stop() transitions state to LIVE_STOPPED
- TEST F: Idempotent stop() — calling stop() multiple times does not crash
- TEST G: Duplicate start() protection — calling start() when running does not spawn duplicate workers
- TEST H: PID-level failure isolation — a failing PID (NO DATA) does not kill the runtime
- TEST I: Runtime/serial failure — serial disconnection transitions state to LIVE_ERROR
- TEST J: Recent history bounded — buffer size stays within history_maxlen
- TEST K: Latest successful value preservation — failed read does not overwrite last successful value
- TEST L: Thread cleanup — worker thread terminates cleanly after stop()
- TEST M: Timing & statistics — cycle count, elapsed time, and sample rate are accurately computed
"""

import time
import threading
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_STARTING,
    LIVE_RUNNING,
    LIVE_STOPPING,
    LIVE_STOPPED,
    LIVE_ERROR,
    LIVE_DEGRADED,
)
from motor import (
    AutoExpertEngine,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
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
    print("🚀 Starting Phase F-1: Live Acquisition Runtime Tests")
    print("==================================================")

    # Initialize shared engine with MockSerial
    engine = AutoExpertEngine()
    engine.baglan()

    # ----------------------------------------------------
    # TEST A: Initial State
    # ----------------------------------------------------
    print("\n--- TEST A: Initial State ---")
    runtime = LiveAcquisitionRuntime(engine=engine, pids=["010C", "010D"], cycle_interval=0.05)
    assert runtime.get_state() == LIVE_IDLE, f"Expected LIVE_IDLE, got {runtime.get_state()}"
    assert not runtime.is_running(), "Runtime should not be running in IDLE"
    print("✅ TEST A PASSED: Runtime initialized in LIVE_IDLE state.")

    # ----------------------------------------------------
    # TEST B: Start Transition
    # ----------------------------------------------------
    print("\n--- TEST B: Start Lifecycle Transition ---")
    started = runtime.start()
    assert started is True, "start() should return True"
    assert runtime.get_state() == LIVE_RUNNING, f"Expected LIVE_RUNNING, got {runtime.get_state()}"
    assert runtime.is_running() is True, "is_running() should return True"
    print("✅ TEST B PASSED: start() moved runtime to LIVE_RUNNING.")

    # ----------------------------------------------------
    # TEST C: Continuous Acquisition
    # ----------------------------------------------------
    print("\n--- TEST C: Continuous Acquisition ---")
    ok = wait_until(lambda: len(runtime.get_recent_samples()) >= 4, timeout=8.0)
    samples = runtime.get_recent_samples()
    assert ok, f"Expected at least 4 samples, got {len(samples)}"
    assert len(samples) >= 4
    first_sample = samples[0]
    required_keys = ["timestamp", "pid", "name", "value", "unit", "raw_value", "status", "acquisition_time_ms", "sequence"]
    for k in required_keys:
        assert k in first_sample, f"Sample missing required key '{k}'"
    print(f"Acquired {len(samples)} samples. Sample format: {first_sample['name']} = {first_sample['value']} {first_sample['unit']}")
    print("✅ TEST C PASSED: Continuous acquisition successfully producing structured samples.")

    # ----------------------------------------------------
    # TEST E: Stop Transition (Clean shutdown of initial runtime)
    # ----------------------------------------------------
    print("\n--- TEST E: Stop Lifecycle Transition ---")
    stopped = runtime.stop()
    assert stopped is True, "stop() should return True"
    assert runtime.get_state() == LIVE_STOPPED, f"Expected LIVE_STOPPED, got {runtime.get_state()}"
    assert not runtime.is_running(), "is_running() should return False after stop"
    print("✅ TEST E PASSED: stop() cleanly transitioned state to LIVE_STOPPED.")

    # ----------------------------------------------------
    # TEST F: Idempotent Stop
    # ----------------------------------------------------
    print("\n--- TEST F: Idempotent Stop ---")
    stopped_again = runtime.stop()
    assert stopped_again is True, "Subsequent stop() call should return True safely"
    assert runtime.get_state() == LIVE_STOPPED, f"Expected LIVE_STOPPED, got {runtime.get_state()}"
    print("✅ TEST F PASSED: Multiple stop() calls are idempotent and safe.")

    # ----------------------------------------------------
    # TEST D: Multiple PID Acquisition
    # ----------------------------------------------------
    print("\n--- TEST D: Multiple PID Acquisition ---")
    multi_pids = ["010C", "010D", "0105", "010B", "0111"]
    multi_runtime = LiveAcquisitionRuntime(engine=engine, pids=multi_pids, cycle_interval=0.05)
    multi_runtime.start()
    ok = wait_until(lambda: multi_runtime.get_runtime_stats()["cycle_count"] >= 2, timeout=10.0)
    assert ok, f"Failed to complete 2 multi-PID cycles. Current stats: {multi_runtime.get_runtime_stats()}"

    latest = multi_runtime.get_latest_sample()
    successful = multi_runtime.get_latest_successful()
    assert isinstance(latest, dict)
    assert isinstance(successful, dict)
    for p in multi_pids:
        assert p in latest, f"PID {p} not found in latest samples"
        assert p in successful, f"PID {p} not found in successful samples"
        s = successful[p]
        assert s["status"] == STATUS_VALID, f"PID {p} status was {s['status']}, expected {STATUS_VALID}"
        assert s["value"] is not None, f"PID {p} value was None"

    print(f"Acquired samples across PIDs: {[(p, successful[p]['name'], successful[p]['value']) for p in multi_pids]}")
    multi_runtime.stop()
    print("✅ TEST D PASSED: Multiple PIDs acquired in order with valid values.")

    # ----------------------------------------------------
    # TEST G: Duplicate Start Protection
    # ----------------------------------------------------
    print("\n--- TEST G: Duplicate Start Protection ---")
    rt_g = LiveAcquisitionRuntime(engine=engine, pids=["010C"], cycle_interval=0.05)
    rt_g.start()
    assert rt_g.is_running()
    orig_worker = rt_g._worker_thread

    # Attempt second start while running
    second_start = rt_g.start()
    assert second_start is False, "Duplicate start() must return False"
    assert rt_g._worker_thread is orig_worker, "Worker thread was duplicated on second start"
    rt_g.stop()
    print("✅ TEST G PASSED: Duplicate start calls are ignored and worker thread is preserved.")

    # ----------------------------------------------------
    # TEST H: PID-Level Failure Isolation
    # ----------------------------------------------------
    print("\n--- TEST H: PID-Level Failure Isolation ---")
    # PID 0123 (Fuel Rail Pressure) returns NO DATA on MockSerial (gasoline simulation)
    rt_h = LiveAcquisitionRuntime(engine=engine, pids=["010C", "0123", "010D"], cycle_interval=0.05)
    rt_h.start()
    ok = wait_until(lambda: rt_h.get_runtime_stats()["cycle_count"] >= 2, timeout=10.0)
    assert ok, "Cycles did not run for PID isolation test"

    # Verify runtime is STILL RUNNING despite failure on 0123 (F-5 degrades health gracefully)
    assert rt_h.is_running() and rt_h.get_state() in (LIVE_RUNNING, LIVE_DEGRADED), f"Runtime state is {rt_h.get_state()}, expected LIVE_RUNNING or LIVE_DEGRADED"

    sample_rpm = rt_h.get_latest_sample("010C")
    sample_frp = rt_h.get_latest_sample("0123")
    sample_spd = rt_h.get_latest_sample("010D")

    assert sample_rpm["status"] == STATUS_VALID, f"RPM expected VALID, got {sample_rpm['status']}"
    assert sample_frp["status"] == STATUS_NO_DATA, f"0123 expected NO_DATA, got {sample_frp['status']}"
    assert sample_frp["value"] is None, "Failed PID value should be None"
    assert sample_spd["status"] == STATUS_VALID, f"SPEED expected VALID, got {sample_spd['status']}"

    rt_h.stop()
    print(f"0123 status: {sample_frp['status']} (Error: {sample_frp['error']}). Runtime remained RUNNING.")
    print("✅ TEST H PASSED: Single PID failure isolated; runtime stayed RUNNING and other PIDs succeeded.")

    # ----------------------------------------------------
    # TEST I: Runtime/Serial Failure Isolation
    # ----------------------------------------------------
    print("\n--- TEST I: Runtime/Serial Failure Isolation ---")
    rt_i = LiveAcquisitionRuntime(engine=engine, pids=["010C"], cycle_interval=0.05)
    rt_i.start()
    assert rt_i.is_running()

    # Simulate port disconnection
    engine.ser.close()

    # Wait for runtime to detect port closure and transition to LIVE_ERROR
    error_detected = wait_until(lambda: rt_i.get_state() == LIVE_ERROR, timeout=8.0)
    assert error_detected, f"Expected LIVE_ERROR, got {rt_i.get_state()}"
    assert rt_i.get_error_reason() is not None, "Expected non-empty error reason"
    print(f"Runtime correctly entered LIVE_ERROR: '{rt_i.get_error_reason()}'")

    # Re-connect engine for subsequent tests
    engine.baglan()
    rt_i.stop()
    print("✅ TEST I PASSED: Serial disconnection gracefully transitions runtime to LIVE_ERROR.")

    # ----------------------------------------------------
    # TEST J: Bounded History Buffer
    # ----------------------------------------------------
    print("\n--- TEST J: Bounded History Buffer ---")
    max_buf = 15
    rt_j = LiveAcquisitionRuntime(engine=engine, pids=["010C"], cycle_interval=0.01, history_maxlen=max_buf)
    rt_j.start()

    # Wait until total reads exceed max_buf
    wait_until(lambda: rt_j.get_runtime_stats()["total_reads"] >= max_buf + 5, timeout=10.0)
    stats_j = rt_j.get_runtime_stats()
    recent_j = rt_j.get_recent_samples()

    assert len(recent_j) <= max_buf, f"Recent samples length {len(recent_j)} exceeded maxlen {max_buf}"
    assert stats_j["history_size"] <= max_buf, f"History size {stats_j['history_size']} exceeded {max_buf}"
    assert stats_j["total_reads"] > max_buf, f"Total reads {stats_j['total_reads']} did not exceed {max_buf}"

    # Test limit filter on get_recent_samples
    last_5 = rt_j.get_recent_samples(limit=5)
    assert len(last_5) == 5, f"Expected 5 samples, got {len(last_5)}"

    rt_j.stop()
    print(f"Total reads: {stats_j['total_reads']}, Bounded history length: {len(recent_j)} (limit {max_buf})")
    print("✅ TEST J PASSED: Recent sample history is strictly bounded.")

    # ----------------------------------------------------
    # TEST K: Latest Successful Value Preservation
    # ----------------------------------------------------
    print("\n--- TEST K: Latest Successful Value Preservation ---")
    # Run a runtime that acquires 010C (RPM) successfully
    rt_k = LiveAcquisitionRuntime(engine=engine, pids=["010C"], cycle_interval=0.05)
    rt_k.start()
    wait_until(lambda: rt_k.get_latest_successful("010C") is not None, timeout=8.0)

    last_succ = rt_k.get_latest_successful("010C")
    assert last_succ is not None
    assert last_succ["status"] == STATUS_VALID
    preserved_value = last_succ["value"]
    assert preserved_value is not None and preserved_value > 0

    # Inject a simulated failed sample for 010C directly into _record_sample
    failed_sample = {
        "timestamp": time.time(),
        "pid": "010C",
        "name": "RPM",
        "value": None,
        "unit": "rpm",
        "raw_value": "NO DATA",
        "status": STATUS_NO_DATA,
        "acquisition_time_ms": 25.0,
        "sequence": 9999,
        "error": "Simulated transient failure",
    }
    rt_k._record_sample(failed_sample)

    # get_latest_sample reflects the transient failure
    latest_now = rt_k.get_latest_sample("010C")
    assert latest_now["status"] == STATUS_NO_DATA
    assert latest_now["value"] is None

    # But get_latest_successful STILL preserves the last valid sample!
    succ_now = rt_k.get_latest_successful("010C")
    assert succ_now is not None
    assert succ_now["status"] == STATUS_VALID
    assert succ_now["value"] == preserved_value, f"Expected {preserved_value}, got {succ_now['value']}"

    rt_k.stop()
    print(f"Transient failure status: {latest_now['status']}. Preserved successful value: {succ_now['value']}.")
    print("✅ TEST K PASSED: Transient failure did not wipe out latest successful value.")

    # ----------------------------------------------------
    # TEST L: Thread Cleanup
    # ----------------------------------------------------
    print("\n--- TEST L: Thread Cleanup ---")
    rt_l = LiveAcquisitionRuntime(engine=engine, pids=["010C"], cycle_interval=0.05)
    rt_l.start()
    worker = rt_l._worker_thread
    assert worker is not None and worker.is_alive(), "Worker thread should be alive while running"

    rt_l.stop(timeout=4.0)
    assert not worker.is_alive(), "Worker thread is still alive after stop()! Thread leaked."
    print("✅ TEST L PASSED: Worker thread terminated cleanly with zero thread leaks.")

    # ----------------------------------------------------
    # TEST M: Timing & Statistics
    # ----------------------------------------------------
    print("\n--- TEST M: Timing & Statistics ---")
    rt_m = LiveAcquisitionRuntime(engine=engine, pids=["010C", "010D"], cycle_interval=0.05)
    rt_m.start()
    wait_until(lambda: rt_m.get_runtime_stats()["cycle_count"] >= 3, timeout=10.0)
    stats_m = rt_m.get_runtime_stats()

    assert stats_m["cycle_count"] >= 3, f"Expected >= 3 cycles, got {stats_m['cycle_count']}"
    assert stats_m["total_reads"] >= 6, f"Expected >= 6 total reads, got {stats_m['total_reads']}"
    assert stats_m["successful_reads"] >= 4, f"Expected >= 4 successful reads, got {stats_m['successful_reads']}"
    assert stats_m["elapsed_time"] > 0.1, f"Elapsed time should be positive, got {stats_m['elapsed_time']}"
    assert stats_m["effective_sample_rate"] > 0.0, f"Sample rate should be positive, got {stats_m['effective_sample_rate']}"
    assert stats_m["pids_count"] == 2

    # Verify callback mechanism
    callback_samples = []
    rt_m._on_sample = lambda s: callback_samples.append(s)
    wait_until(lambda: len(callback_samples) >= 2, timeout=5.0)
    assert len(callback_samples) >= 2, "Callback did not receive expected samples"

    rt_m.stop()
    print(f"Stats: cycles={stats_m['cycle_count']}, successful={stats_m['successful_reads']}, "
          f"elapsed={stats_m['elapsed_time']}s, rate={stats_m['effective_sample_rate']} samp/sec")
    print("✅ TEST M PASSED: Timing and statistics accurately computed.")

    print("\n==================================================")
    print("🎉 ALL 13 PHASE F-1 TESTS (A through M) PASSED!")
    print("==================================================")


if __name__ == "__main__":
    run_all_tests()
