#!/usr/bin/env python3
"""
Test Suite for Phase D-1: Diagnostic Evidence Engine (Tests A through O)
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
    SOURCE_DIRECT,
    SOURCE_CROSS_SENSOR,
    SOURCE_VEHICLE_PROFILE,
    SOURCE_TEMPORAL,
    SOURCE_PHYSICAL,
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
    print("🚀 Running Phase D-1 Diagnostic Evidence Engine Tests (Tests A through O)...")
    engine = AutoExpertEngine()

    def get_ev_by_id(evidence_list, ev_id):
        for ev in evidence_list:
            if ev["id"] == ev_id:
                return ev
        return None

    def reset_cache():
        engine.data_cache.clear()
        engine.sensor_history.clear()

    # TEST A — Engine running (RPM = 800)
    print("\n--- TEST A: Engine Running (RPM = 800) ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    ev_a = engine._collect_diagnostic_evidence()
    item_a = get_ev_by_id(ev_a, "ENGINE_RUNNING")
    assert item_a is not None
    assert item_a["status"] == EVIDENCE_SUPPORTED
    assert item_a["severity"] == EVIDENCE_INFO
    assert item_a["source"] == SOURCE_DIRECT
    print(f"Test A Result: id={item_a['id']}, status={item_a['status']}, severity={item_a['severity']}")

    # TEST B — Engine not running (RPM = 0)
    print("\n--- TEST B: Engine Not Running (RPM = 0) ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 0.0, status=STATUS_VALID, source="MODE01")
    ev_b = engine._collect_diagnostic_evidence()
    item_b = get_ev_by_id(ev_b, "ENGINE_NOT_RUNNING")
    assert item_b is not None
    assert item_b["status"] == EVIDENCE_SUPPORTED
    assert item_b["severity"] == EVIDENCE_INFO
    print(f"Test B Result: id={item_b['id']}, status={item_b['status']}, severity={item_b['severity']}")

    # TEST C — RPM missing/untrusted
    print("\n--- TEST C: RPM Missing / Untrusted ---")
    reset_cache()
    ev_c = engine._collect_diagnostic_evidence()
    item_c = get_ev_by_id(ev_c, "ENGINE_RUNNING")
    assert item_c is not None
    assert item_c["status"] == EVIDENCE_UNKNOWN
    print(f"Test C Result: id={item_c['id']}, status={item_c['status']}")

    # TEST D — Positive fuel trim (STFT=+18, LTFT=+16)
    print("\n--- TEST D: Positive Fuel Trim (STFT=+18, LTFT=+16) ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("STFT", 18.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("LTFT", 16.0, status=STATUS_VALID, source="MODE01")
    ev_d = engine._collect_diagnostic_evidence()
    item_d = get_ev_by_id(ev_d, "FUEL_TRIM_POSITIVE")
    assert item_d is not None
    assert item_d["status"] == EVIDENCE_SUPPORTED
    assert item_d["severity"] == EVIDENCE_WARNING
    print(f"Test D Result: id={item_d['id']}, status={item_d['status']}, severity={item_d['severity']}")

    # TEST E — Negative fuel trim (STFT=-18, LTFT=-16)
    print("\n--- TEST E: Negative Fuel Trim (STFT=-18, LTFT=-16) ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("STFT", -18.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("LTFT", -16.0, status=STATUS_VALID, source="MODE01")
    ev_e = engine._collect_diagnostic_evidence()
    item_e = get_ev_by_id(ev_e, "FUEL_TRIM_NEGATIVE")
    assert item_e is not None
    assert item_e["status"] == EVIDENCE_SUPPORTED
    assert item_e["severity"] == EVIDENCE_WARNING
    print(f"Test E Result: id={item_e['id']}, status={item_e['status']}, severity={item_e['severity']}")

    # TEST F — Fuel trim below threshold (STFT=+5, LTFT=+3)
    print("\n--- TEST F: Fuel Trim Below Threshold (STFT=+5, LTFT=+3) ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("STFT", 5.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("LTFT", 3.0, status=STATUS_VALID, source="MODE01")
    ev_f = engine._collect_diagnostic_evidence()
    assert get_ev_by_id(ev_f, "FUEL_TRIM_POSITIVE") is None
    assert get_ev_by_id(ev_f, "FUEL_TRIM_NEGATIVE") is None
    print(f"Test F Result: No false positive/negative fuel trim evidence")

    # TEST G — ECT too cold (Target=90, ECT=60, RPM=800)
    print("\n--- TEST G: ECT Too Cold (Target=90, ECT=60, RPM=800) ---")
    reset_cache()
    engine.vehicle_profile = MockVehicleProfile(
        motor_kodu="Z19DTH", marka="OPEL", aciklama="1.9 CDTI", yakit_tipi="DIESEL",
        max_rpm=4500, redline=4500, idle_rpm=820, hedef_ect=90
    )
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("ECT", 60.0, status=STATUS_VALID, source="MODE01")
    ev_g = engine._collect_diagnostic_evidence()
    item_g = get_ev_by_id(ev_g, "ECT_TOO_COLD")
    assert item_g is not None
    assert item_g["status"] == EVIDENCE_SUPPORTED
    assert item_g["severity"] == EVIDENCE_WARNING
    assert item_g["source"] == SOURCE_VEHICLE_PROFILE
    print(f"Test G Result: id={item_g['id']}, status={item_g['status']}, severity={item_g['severity']}")

    # TEST H — ECT target unavailable
    print("\n--- TEST H: ECT Target Unavailable ---")
    engine.vehicle_profile = None
    reset_cache()
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("ECT", 60.0, status=STATUS_VALID, source="MODE01")
    ev_h = engine._collect_diagnostic_evidence()
    assert get_ev_by_id(ev_h, "ECT_TOO_COLD") is None
    print(f"Test H Result: No invented threshold without vehicle profile")

    # TEST I — MAF zero while running (RPM=1500, MAF=0)
    print("\n--- TEST I: MAF Zero While Running (RPM=1500, MAF=0) ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 1500.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("MAF", 0.0, status=STATUS_VALID, source="MODE01")
    ev_i = engine._collect_diagnostic_evidence()
    item_i = get_ev_by_id(ev_i, "AIRFLOW_LOW")
    assert item_i is not None
    assert item_i["status"] == EVIDENCE_SUPPORTED
    assert item_i["severity"] == EVIDENCE_WARNING
    print(f"Test I Result: id={item_i['id']}, status={item_i['status']}, severity={item_i['severity']}")

    # TEST J — C-5 correlation evidence (RPM=0, SPEED=120)
    print("\n--- TEST J: C-5 Correlation Evidence Reuse ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 0.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("SPEED", 120.0, status=STATUS_VALID, source="MODE01")
    engine._check_cross_sensor_correlations()
    ev_j = engine._collect_diagnostic_evidence()
    item_j = get_ev_by_id(ev_j, "SENSOR_CORRELATION_INCONSISTENT")
    assert item_j is not None
    assert item_j["status"] == EVIDENCE_SUPPORTED
    assert item_j["severity"] == EVIDENCE_WARNING
    assert item_j["source"] == SOURCE_CROSS_SENSOR
    print(f"Test J Result: id={item_j['id']}, status={item_j['status']}, source={item_j['source']}")

    # TEST K — C-6 envelope evidence (Redline=4500, RPM=5000)
    print("\n--- TEST K: C-6 Envelope Evidence Reuse ---")
    reset_cache()
    engine.vehicle_profile = MockVehicleProfile(
        motor_kodu="Z19DTH", marka="OPEL", aciklama="1.9 CDTI", yakit_tipi="DIESEL",
        max_rpm=4500, redline=4500, idle_rpm=820, hedef_ect=90
    )
    engine._update_sensor_cache("RPM", 5000.0, status=STATUS_VALID, source="MODE01")
    ev_k = engine._collect_diagnostic_evidence()
    item_k = get_ev_by_id(ev_k, "VEHICLE_ENVELOPE_EXCEEDED")
    assert item_k is not None
    assert item_k["status"] == EVIDENCE_SUPPORTED
    assert item_k["severity"] == EVIDENCE_WARNING
    print(f"Test K Result: id={item_k['id']}, status={item_k['status']}")

    # TEST L — Untrusted sensor excluded from positive evidence (ECT=315 implausible)
    print("\n--- TEST L: Untrusted Sensor Excluded from Positive Evidence ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    engine._update_sensor_cache("ECT", 315.0, status=STATUS_VALID, source="MODE01")
    ev_l = engine._collect_diagnostic_evidence()
    assert get_ev_by_id(ev_l, "ECT_TOO_COLD") is None
    assert get_ev_by_id(ev_l, "ECT_TOO_HOT") is None
    # Meta-evidence is recorded
    item_l_meta = get_ev_by_id(ev_l, "SENSOR_PHYSICAL_IMPLAUSIBLE")
    assert item_l_meta is not None
    assert item_l_meta["status"] == EVIDENCE_SUPPORTED
    print(f"Test L Result: positive ECT evidence omitted; meta-evidence={item_l_meta['id']}")

    # TEST M — Evidence deduplication
    print("\n--- TEST M: Evidence Deduplication ---")
    ev_m1 = engine._collect_diagnostic_evidence()
    ev_m2 = engine._collect_diagnostic_evidence()
    assert len(ev_m1) == len(ev_m2)
    ids_1 = [x["id"] for x in ev_m1]
    assert len(ids_1) == len(set(ids_1))  # No duplicates
    print(f"Test M Result: Deterministic evidence count = {len(ev_m1)}, unique IDs = {len(set(ids_1))}")

    # TEST N — Missing data safe degradation
    print("\n--- TEST N: Missing Data Safe Degradation ---")
    reset_cache()
    engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, source="MODE01")
    ev_n = engine._collect_diagnostic_evidence()
    assert len(ev_n) == 1
    assert ev_n[0]["id"] == "ENGINE_RUNNING"
    print(f"Test N Result: Only engine-state evidence generated without exceptions")

    # Connect mock simulator for regression
    engine.baglan()
    time.sleep(0.5)

    # TEST O — Phase A/B/C regression
    print("\n--- TEST O: Phase A/B/C Regression Checks ---")
    # Phase A status derivation
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    # Phase B manual DID probe
    probe_res = engine.manual_did_probe("1640", header="7E0")
    assert probe_res["ok"] is True
    # Phase C-2 history
    assert engine._is_sensor_fresh("RPM", max_age=1000000.0) is True
    # Phase C-3 physical check
    assert engine._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE
    # Phase C-4 temporal check
    assert engine._check_temporal_plausibility("RPM", 850.0, timestamp=time.time()) == TEMPORAL_PLAUSIBLE
    # Phase C-5 cross-sensor check
    corr = engine._check_cross_sensor_correlations()
    assert len(corr) == 3

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE D-1 TESTS (Tests A through O) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
