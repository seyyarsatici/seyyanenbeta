#!/usr/bin/env python3
"""
Test Suite for Phase D-2: Fault Hypothesis Engine (Tests A through L)
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
    HYPOTHESIS_INFO,
    HYPOTHESIS_WARNING,
    HYPOTHESIS_CRITICAL,
    SOURCE_DIRECT,
    SOURCE_CROSS_SENSOR,
    SOURCE_VEHICLE_PROFILE,
    derive_quality_from_status,
)

def run_tests():
    print("🚀 Running Phase D-2 Fault Hypothesis Engine Tests (Tests A through L)...")
    engine = AutoExpertEngine()

    def get_hyp_by_id(hypotheses, hyp_id):
        for h in hypotheses:
            if h["id"] == hyp_id:
                return h
        return None

    # TEST A — Strong lean evidence
    print("\n--- TEST A: Strong Lean Evidence ---")
    mock_ev_a = [
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {"RPM": 850.0}, "reason": "", "source": "DIRECT"},
        {"id": "FUEL_TRIM_POSITIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["STFT", "LTFT"], "observations": {"STFT": 18.0, "LTFT": 16.0}, "reason": "", "source": "DIRECT"},
        {"id": "AIRFLOW_LOW", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["MAF", "RPM"], "observations": {"MAF": 0.0, "RPM": 850.0}, "reason": "", "source": "DIRECT"}
    ]
    res_a = engine._infer_fault_hypotheses(evidence=mock_ev_a)
    h_lean_a = get_hyp_by_id(res_a, "FUEL_SYSTEM_LEAN")
    assert h_lean_a is not None
    assert h_lean_a["status"] == HYPOTHESIS_SUPPORTED
    assert "FUEL_TRIM_POSITIVE" in h_lean_a["supporting_evidence"]
    assert h_lean_a["next_step"] is None
    print(f"Test A Result: id={h_lean_a['id']}, status={h_lean_a['status']}, supporting={h_lean_a['supporting_evidence']}")

    # TEST B — Weak lean evidence (single positive trim, no running context)
    print("\n--- TEST B: Weak Lean Evidence ---")
    mock_ev_b = [
        {"id": "FUEL_TRIM_POSITIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["STFT"], "observations": {"STFT": 16.0}, "reason": "", "source": "DIRECT"}
    ]
    res_b = engine._infer_fault_hypotheses(evidence=mock_ev_b)
    h_lean_b = get_hyp_by_id(res_b, "FUEL_SYSTEM_LEAN")
    assert h_lean_b is not None
    assert h_lean_b["status"] == HYPOTHESIS_POSSIBLE
    print(f"Test B Result: id={h_lean_b['id']}, status={h_lean_b['status']}, supporting={h_lean_b['supporting_evidence']}")

    # TEST C — Lean contradiction (negative fuel trim)
    print("\n--- TEST C: Lean Contradiction ---")
    mock_ev_c = [
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {"RPM": 850.0}, "reason": "", "source": "DIRECT"},
        {"id": "FUEL_TRIM_NEGATIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["STFT"], "observations": {"STFT": -18.0}, "reason": "", "source": "DIRECT"}
    ]
    res_c = engine._infer_fault_hypotheses(evidence=mock_ev_c)
    h_lean_c = get_hyp_by_id(res_c, "FUEL_SYSTEM_LEAN")
    assert h_lean_c is not None
    assert h_lean_c["status"] == HYPOTHESIS_CONTRADICTED
    assert "FUEL_TRIM_NEGATIVE" in h_lean_c["contradicting_evidence"]
    print(f"Test C Result: id={h_lean_c['id']}, status={h_lean_c['status']}, contradicting={h_lean_c['contradicting_evidence']}")

    # TEST D — Strong rich evidence
    print("\n--- TEST D: Strong Rich Evidence ---")
    mock_ev_d = [
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {"RPM": 850.0}, "reason": "", "source": "DIRECT"},
        {"id": "FUEL_TRIM_NEGATIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["STFT", "LTFT"], "observations": {"STFT": -18.0, "LTFT": -16.0}, "reason": "", "source": "DIRECT"}
    ]
    res_d = engine._infer_fault_hypotheses(evidence=mock_ev_d)
    h_rich_d = get_hyp_by_id(res_d, "FUEL_SYSTEM_RICH")
    assert h_rich_d is not None
    assert h_rich_d["status"] == HYPOTHESIS_SUPPORTED
    assert "FUEL_TRIM_NEGATIVE" in h_rich_d["supporting_evidence"]
    print(f"Test D Result: id={h_rich_d['id']}, status={h_rich_d['status']}, supporting={h_rich_d['supporting_evidence']}")

    # TEST E — Airflow issue
    print("\n--- TEST E: Airflow Measurement Issue ---")
    mock_ev_e = [
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {"RPM": 1500.0}, "reason": "", "source": "DIRECT"},
        {"id": "AIRFLOW_LOW", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["MAF", "RPM"], "observations": {"MAF": 0.0, "RPM": 1500.0}, "reason": "", "source": "DIRECT"}
    ]
    res_e = engine._infer_fault_hypotheses(evidence=mock_ev_e)
    h_air_e = get_hyp_by_id(res_e, "AIRFLOW_MEASUREMENT_ISSUE")
    assert h_air_e is not None
    assert h_air_e["status"] == HYPOTHESIS_SUPPORTED
    assert "AIRFLOW_LOW" in h_air_e["supporting_evidence"]
    print(f"Test E Result: id={h_air_e['id']}, status={h_air_e['status']}, title='{h_air_e['title']}'")

    # TEST F — Cooling issue
    print("\n--- TEST F: Cooling System Issue ---")
    mock_ev_f = [
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {"RPM": 800.0}, "reason": "", "source": "DIRECT"},
        {"id": "ECT_TOO_COLD", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["ECT"], "observations": {"ECT": 60.0}, "reason": "", "source": "VEHICLE_PROFILE"}
    ]
    res_f = engine._infer_fault_hypotheses(evidence=mock_ev_f)
    h_cool_f = get_hyp_by_id(res_f, "COOLING_SYSTEM_ISSUE")
    assert h_cool_f is not None
    assert h_cool_f["status"] == HYPOTHESIS_SUPPORTED
    assert "ECT_TOO_COLD" in h_cool_f["supporting_evidence"]
    print(f"Test F Result: id={h_cool_f['id']}, status={h_cool_f['status']}, title='{h_cool_f['title']}'")

    # TEST G — Correlation issue
    print("\n--- TEST G: Multi-Sensor Correlation Issue ---")
    mock_ev_g = [
        {"id": "SENSOR_CORRELATION_INCONSISTENT", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["RPM", "SPEED"], "observations": {"rule": "RPM_VSS"}, "reason": "", "source": "CROSS_SENSOR"}
    ]
    res_g = engine._infer_fault_hypotheses(evidence=mock_ev_g)
    h_corr_g = get_hyp_by_id(res_g, "SENSOR_CORRELATION_ISSUE")
    assert h_corr_g is not None
    assert h_corr_g["status"] == HYPOTHESIS_SUPPORTED
    assert "SENSOR_CORRELATION_INCONSISTENT" in h_corr_g["supporting_evidence"]
    print(f"Test G Result: id={h_corr_g['id']}, status={h_corr_g['status']}, supporting={h_corr_g['supporting_evidence']}")

    # TEST H — No useful evidence (empty evidence list)
    print("\n--- TEST H: No Useful Evidence (Empty List) ---")
    res_h = engine._infer_fault_hypotheses(evidence=[])
    for h in res_h:
        assert h["status"] == HYPOTHESIS_INSUFFICIENT
    print(f"Test H Result: All {len(res_h)} hypotheses INSUFFICIENT")

    # TEST I — Missing evidence
    print("\n--- TEST I: Missing Evidence Tracking ---")
    mock_ev_i = [
        {"id": "FUEL_TRIM_POSITIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["STFT"], "observations": {"STFT": 18.0}, "reason": "", "source": "DIRECT"},
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_UNKNOWN, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {}, "reason": "", "source": "DIRECT"}
    ]
    res_i = engine._infer_fault_hypotheses(evidence=mock_ev_i)
    h_lean_i = get_hyp_by_id(res_i, "FUEL_SYSTEM_LEAN")
    assert h_lean_i is not None
    assert h_lean_i["status"] == HYPOTHESIS_POSSIBLE
    assert "ENGINE_RUNNING" in h_lean_i["missing_evidence"]
    assert h_lean_i["status"] != HYPOTHESIS_CONTRADICTED
    print(f"Test I Result: id={h_lean_i['id']}, status={h_lean_i['status']}, missing={h_lean_i['missing_evidence']}")

    # TEST J — Evidence deduplication
    print("\n--- TEST J: Evidence Deduplication ---")
    mock_ev_j = [
        {"id": "ENGINE_RUNNING", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_INFO, "sensors": ["RPM"], "observations": {"RPM": 850.0}, "reason": "", "source": "DIRECT"},
        {"id": "FUEL_TRIM_POSITIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["STFT"], "observations": {"STFT": 18.0}, "reason": "", "source": "DIRECT"},
        {"id": "FUEL_TRIM_POSITIVE", "status": EVIDENCE_SUPPORTED, "severity": EVIDENCE_WARNING, "sensors": ["LTFT"], "observations": {"LTFT": 16.0}, "reason": "", "source": "DIRECT"}
    ]
    res_j = engine._infer_fault_hypotheses(evidence=mock_ev_j)
    h_lean_j = get_hyp_by_id(res_j, "FUEL_SYSTEM_LEAN")
    assert h_lean_j["supporting_evidence"].count("FUEL_TRIM_POSITIVE") == 1
    print(f"Test J Result: supporting_evidence count for FUEL_TRIM_POSITIVE = {h_lean_j['supporting_evidence'].count('FUEL_TRIM_POSITIVE')}")

    # TEST K — No raw-value re-diagnosis (derives purely from evidence semantics)
    print("\n--- TEST K: Pure Evidence Derivation ---")
    # Verify that passing evidence list alone (with empty data_cache) generates hypotheses purely from evidence
    engine.data_cache.clear()
    res_k = engine._infer_fault_hypotheses(evidence=mock_ev_a)
    h_lean_k = get_hyp_by_id(res_k, "FUEL_SYSTEM_LEAN")
    assert h_lean_k["status"] == HYPOTHESIS_SUPPORTED
    print(f"Test K Result: Hypothesis evaluated purely from evidence with empty data_cache: status={h_lean_k['status']}")

    # Connect mock simulator for regression
    engine.baglan()
    time.sleep(0.5)

    # TEST L — Phase A/B/C/D-1 regression
    print("\n--- TEST L: Full Regression Checks ---")
    # Phase A
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    # Phase B
    probe_res = engine.manual_did_probe("1640", header="7E0")
    print("PROBE_RES in test_phase_d2:", probe_res)
    assert probe_res["ok"] is True
    # Phase C-2
    engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
    assert engine._is_sensor_fresh("RPM", max_age=1000000.0) is True
    # Phase C-3
    assert engine._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE
    # Phase C-4
    assert engine._check_temporal_plausibility("RPM", 850.0, timestamp=time.time()) == TEMPORAL_PLAUSIBLE
    # Phase C-5
    corr = engine._check_cross_sensor_correlations()
    assert len(corr) == 3
    # Phase D-1
    ev = engine._collect_diagnostic_evidence()
    assert isinstance(ev, list)

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE D-2 TESTS (Tests A through L) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
