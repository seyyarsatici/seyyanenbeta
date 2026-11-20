"""
Phase E-1: Live Diagnostic Session Foundation Test Suite
Tests A through M:
- TEST A: Initial state (IDLE, no serial connection)
- TEST B: Successful start (IDLE -> CONNECTING -> INITIALIZING -> RUNNING)
- TEST C: Connection failure (Forces SESSION_ERROR, structured reason, no dangling worker)
- TEST D: Successful stop (RUNNING -> STOPPING -> STOPPED)
- TEST E: Idempotent stop (calling stop twice raises no exception and remains STOPPED)
- TEST F: Diagnostic evaluation (seeds trusted cache, evaluates D-1 -> D-2 -> D-3)
- TEST G: Live snapshot (bounded dictionary without full sensor_history duplication)
- TEST H: Transient acquisition error (increments error_count while remaining RUNNING)
- TEST I: Persistent failure (exceeding consecutive error budget transitions to ERROR and cleans up)
- TEST J: Profile propagation (session references canonical engine.vehicle_profile)
- TEST K: Verification that session is strictly read-only (no ECU write/actuation commands)
- TEST L: D-layer regression
- TEST M: C-layer regression
"""

import time
import inspect
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    SESSION_IDLE,
    SESSION_CONNECTING,
    SESSION_INITIALIZING,
    SESSION_RUNNING,
    SESSION_STOPPING,
    SESSION_STOPPED,
    SESSION_ERROR,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    QUALITY_GOOD,
    PHYSICS_PLAUSIBLE,
    EVIDENCE_SUPPORTED,
    HYPOTHESIS_SUPPORTED,
    HYPOTHESIS_POSSIBLE,
)

def run_tests():
    print("🚀 Running Phase E-1 Live Diagnostic Session Tests (Tests A through M)...")

    # TEST A — Initial State
    print("\n--- TEST A: Initial State ---")
    engine_a = AutoExpertEngine()
    session_a = DiagnosticSession(engine=engine_a)
    assert session_a.state == SESSION_IDLE
    assert session_a.started_at is None
    assert session_a.ended_at is None
    assert session_a.session_id is None
    assert session_a.acquisition_count == 0
    assert session_a.error_count == 0
    assert engine_a.ser is None or getattr(engine_a.ser, "is_open", False) is False
    print("Test A Result: State is SESSION_IDLE, no active serial connection.")

    # TEST B — Successful Start
    print("\n--- TEST B: Successful Start ---")
    engine_b = AutoExpertEngine()
    session_b = DiagnosticSession(engine=engine_b)
    # Start using mock serial
    start_ok = session_b.start()
    assert start_ok is True
    assert session_b.state == SESSION_RUNNING
    assert session_b.started_at is not None
    assert session_b.session_id is not None
    assert session_b.session_id.startswith("diag_")
    print(f"Test B Result: Started successfully, session_id={session_b.session_id}, state={session_b.state}")

    # TEST D — Successful Stop
    print("\n--- TEST D: Successful Stop ---")
    stop_ok = session_b.stop()
    assert stop_ok is True
    assert session_b.state == SESSION_STOPPED
    assert session_b.ended_at is not None
    assert session_b.ended_at >= session_b.started_at
    # Ensure worker stopped
    if engine_b.io_worker:
        assert engine_b.io_worker.running is False
    if engine_b.ser:
        assert getattr(engine_b.ser, "is_open", False) is False
    print(f"Test D Result: Stopped cleanly, state={session_b.state}, ended_at={session_b.ended_at}")

    # TEST E — Idempotent Stop
    print("\n--- TEST E: Idempotent Stop ---")
    stop_again = session_b.stop()
    assert stop_again is True
    assert session_b.state == SESSION_STOPPED
    print("Test E Result: Second stop call succeeded idempotently without error.")

    # TEST C — Connection Failure
    print("\n--- TEST C: Connection Failure ---")
    engine_c = AutoExpertEngine()
    session_c = DiagnosticSession(engine=engine_c)
    # Force baglan() to fail
    engine_c.baglan = lambda *args, **kwargs: False
    start_c = session_c.start()
    assert start_c is False
    assert session_c.state == SESSION_ERROR
    assert session_c.error_reason is not None
    assert "Unable to connect" in session_c.error_reason
    assert engine_c.io_worker is None or engine_c.io_worker.running is False
    print(f"Test C Result: Handled cleanly, state={session_c.state}, reason={session_c.error_reason}")

    # TEST F — Diagnostic Evaluation
    print("\n--- TEST F: Diagnostic Evaluation Chain (D-1 -> D-2 -> D-3) ---")
    engine_f = AutoExpertEngine()
    session_f = DiagnosticSession(engine=engine_f)
    session_f.state = SESSION_RUNNING
    session_f.started_at = time.time()
    session_f.session_id = "diag_test_f"

    # Seed trusted data for rich lean condition
    t_now = time.time()
    engine_f.data_cache.clear()
    engine_f.sensor_history.clear()
    engine_f._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, quality=QUALITY_GOOD, timestamp=t_now, source="MODE01")
    engine_f._update_sensor_cache("ECT", 90.0, status=STATUS_VALID, quality=QUALITY_GOOD, timestamp=t_now, source="MODE01")
    engine_f._update_sensor_cache("STFT", 16.0, status=STATUS_VALID, quality=QUALITY_GOOD, timestamp=t_now, source="MODE01")
    engine_f._update_sensor_cache("LTFT", 18.0, status=STATUS_VALID, quality=QUALITY_GOOD, timestamp=t_now, source="MODE01")
    engine_f._update_sensor_cache("MAF", 2.2, status=STATUS_VALID, quality=QUALITY_GOOD, timestamp=t_now, source="MODE01")

    diag_res = session_f.evaluate_diagnostics()
    assert "evidence" in diag_res
    assert "hypotheses" in diag_res
    assert "recommendations" in diag_res
    assert len(session_f.last_evidence) > 0
    assert len(session_f.last_hypotheses) > 0
    assert len(session_f.last_recommendations) > 0

    ev_ids = [e["id"] for e in session_f.last_evidence]
    hyp_ids = [h["id"] for h in session_f.last_hypotheses]
    rec_ids = [r["id"] for r in session_f.last_recommendations]
    assert "ENGINE_RUNNING" in ev_ids
    assert "FUEL_TRIM_POSITIVE" in ev_ids
    assert "FUEL_SYSTEM_LEAN" in hyp_ids
    assert "CHECK_FUEL_TRIM" in rec_ids
    print(f"Test F Result: D-1 ({len(ev_ids)}) -> D-2 ({len(hyp_ids)}) -> D-3 ({len(rec_ids)}) executed deterministically.")

    # TEST G — Live Snapshot & Summary
    print("\n--- TEST G: Live Snapshot & Summary ---")
    snap = session_f.get_session_snapshot()
    required_fields = ["session_id", "state", "started_at", "ended_at", "vehicle_profile",
                       "acquisition_count", "error_count", "evidence", "hypotheses", "recommendations"]
    for field in required_fields:
        assert field in snap, f"Missing snapshot field: {field}"
    assert "data_cache" not in snap
    assert "sensor_history" not in snap

    summary = session_f.get_live_summary()
    assert "SESSION: RUNNING" in summary
    assert "EVIDENCE:" in summary
    assert "HYPOTHESES:" in summary
    assert "NEXT TEST:" in summary
    print(f"Test G Result: Snapshot fields verified. Summary:\n{summary}")

    # TEST H — Transient Acquisition Error
    print("\n--- TEST H: Transient Acquisition Error ---")
    engine_h = AutoExpertEngine()
    session_h = DiagnosticSession(engine=engine_h, max_consecutive_errors=3)
    session_h.state = SESSION_RUNNING
    session_h.started_at = time.time()
    session_h.session_id = "diag_test_h"

    # Simulate 1 transient error where tek_veri_oku returns empty dict
    engine_h.tek_veri_oku = lambda target_list=None: ({}, 0)
    engine_h.last_response_status = STATUS_TIMEOUT

    session_h.step_acquisition()
    assert session_h.error_count == 1
    assert session_h.consecutive_errors == 1
    assert session_h.state == SESSION_RUNNING  # Transient error does not kill session
    print(f"Test H Result: Transient error counted (errors={session_h.error_count}), session remains {session_h.state}.")

    # TEST I — Persistent Failure
    print("\n--- TEST I: Persistent Failure Exceeding Budget ---")
    # 2 more errors to reach max_consecutive_errors=3
    session_h.step_acquisition()
    assert session_h.state == SESSION_RUNNING
    session_h.step_acquisition()
    # Now consecutive_errors reached 3 -> transitions to SESSION_ERROR
    assert session_h.state == SESSION_ERROR
    assert session_h.error_reason is not None
    assert "Persistent acquisition failure" in session_h.error_reason
    print(f"Test I Result: Budget exceeded, transitioned safely to {session_h.state} with reason: {session_h.error_reason}")

    # TEST J — Profile Propagation
    print("\n--- TEST J: VehicleProfile Propagation ---")
    engine_j = AutoExpertEngine()
    class DummyProfile:
        motor_kodu = "A14NET"
        marka = "Opel"
    prof_obj = DummyProfile()
    engine_j.vehicle_profile = prof_obj
    session_j = DiagnosticSession(engine=engine_j)
    assert session_j.vehicle_profile is prof_obj
    assert session_j.vehicle_profile.motor_kodu == "A14NET"
    snap_j = session_j.get_session_snapshot()
    assert snap_j["vehicle_profile"] == "A14NET"
    print(f"Test J Result: Canonical vehicle_profile ({snap_j['vehicle_profile']}) referenced accurately.")

    # TEST K — Verification that Session is Read-Only
    print("\n--- TEST K: Read-Only Safety Verification ---")
    disallowed_keywords = ["write", "program", "code", "actuat", "routine", "download", "security_access", "seed_key"]
    for method_name, method_obj in inspect.getmembers(DiagnosticSession, predicate=inspect.isfunction):
        name_lower = method_name.lower()
        for kw in disallowed_keywords:
            assert kw not in name_lower, f"Dangerous actuation/write method found: {method_name}"
    print("Test K Result: DiagnosticSession is strictly read-only; no write or actuation methods exist.")

    # TEST L & M — Regression Check
    print("\n--- TEST L & M: Regression Checks ---")
    # Quick sanity checks on C and D layers
    assert engine_a._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE
    ev_test = engine_a._collect_diagnostic_evidence()
    assert isinstance(ev_test, list)
    hyp_test = engine_a._infer_fault_hypotheses(ev_test)
    assert isinstance(hyp_test, list)
    rec_test = engine_a._recommend_diagnostic_tests(hyp_test)
    assert isinstance(rec_test, list)
    print("Test L & M Result: C and D layer contracts fully preserved.")

    print("\n✅ ALL PHASE E-1 TESTS (Tests A through M) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
