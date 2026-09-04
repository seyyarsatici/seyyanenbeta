#!/usr/bin/env python3
"""
Test Suite for Phase C-6: Vehicle-Specific Operating Envelope Layer (Tests A through J)
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
    derive_quality_from_status,
)

# Mock VehicleProfile matching main.py structure
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
    print("🚀 Running Phase C-6 Vehicle-Specific Operating Envelope Tests (Tests A through J)...")
    engine = AutoExpertEngine()

    diesel_profile = MockVehicleProfile(
        motor_kodu="Z19DTH",
        marka="OPEL",
        aciklama="1.9 CDTI",
        yakit_tipi="DIESEL",
        max_rpm=4500,
        redline=4500,
        idle_rpm=820,
        hedef_ect=90,
    )

    # TEST A — RPM below redline
    print("\n--- TEST A: RPM Below Redline ---")
    engine.vehicle_profile = diesel_profile
    entry_a = engine._update_sensor_cache("RPM", 3000.0, status=STATUS_VALID, source="MODE01")
    assert entry_a["envelope_status"] == ENVELOPE_NORMAL
    assert entry_a["quality"] == QUALITY_GOOD
    print(f"Test A Result: RPM=3000, redline=4500 -> envelope={entry_a['envelope_status']}, quality={entry_a['quality']}")

    # TEST B — RPM above redline
    print("\n--- TEST B: RPM Above Redline ---")
    engine.sensor_history.clear()
    entry_b = engine._update_sensor_cache("RPM", 5000.0, status=STATUS_VALID, source="MODE01")
    assert entry_b["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH
    # Quality must NOT become ERROR/INVALID solely due to envelope
    assert entry_b["quality"] == QUALITY_GOOD
    print(f"Test B Result: RPM=5000, redline=4500 -> envelope={entry_b['envelope_status']}, quality={entry_b['quality']}")

    # TEST C — Generic physical limit vs vehicle envelope
    print("\n--- TEST C: Physical Plausibility vs Vehicle Envelope Separation ---")
    # RPM 5000 is physically plausible for combustion engines in general (< 15000), but exceeds 4500 diesel redline
    assert entry_b["physics_status"] == PHYSICS_PLAUSIBLE
    assert entry_b["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH
    print(f"Test C Result: physics={entry_b['physics_status']}, envelope={entry_b['envelope_status']}")

    # TEST D — No active profile
    print("\n--- TEST D: No Active Profile ---")
    engine.vehicle_profile = None
    entry_d = engine._update_sensor_cache("RPM", 5000.0, status=STATUS_VALID, source="MODE01")
    assert entry_d["envelope_status"] == ENVELOPE_UNKNOWN
    print(f"Test D Result: envelope={entry_d['envelope_status']}")

    # TEST E — Idle reference
    print("\n--- TEST E: Idle Reference ---")
    engine.vehicle_profile = diesel_profile
    engine.sensor_history.clear()
    entry_e = engine._update_sensor_cache("RPM", 820.0, status=STATUS_VALID, source="MODE01")
    assert entry_e["envelope_status"] == ENVELOPE_NORMAL
    print(f"Test E Result: RPM=820, idle=820 -> envelope={entry_e['envelope_status']}")

    # TEST F — Idle not incorrectly applied at running speed
    print("\n--- TEST F: Idle Not Incorrectly Applied ---")
    engine.sensor_history.clear()
    entry_f = engine._update_sensor_cache("RPM", 2500.0, status=STATUS_VALID, source="MODE01")
    assert entry_f["envelope_status"] == ENVELOPE_NORMAL
    print(f"Test F Result: RPM=2500, idle=820 -> envelope={entry_f['envelope_status']} (no idle failure)")

    # TEST G — ECT target is not a hard limit
    print("\n--- TEST G: ECT Target is Not a Hard Ceiling ---")
    entry_g = engine._update_sensor_cache("ECT", 98.0, status=STATUS_VALID, source="MODE01")
    # ECT does not have a hard vehicle-specific operating ceiling defined; returns UNKNOWN
    assert entry_g["envelope_status"] == ENVELOPE_UNKNOWN
    assert entry_g["quality"] == QUALITY_GOOD
    print(f"Test G Result: ECT=98, hedef=90 -> envelope={entry_g['envelope_status']}, quality={entry_g['quality']}")

    # TEST H — Unknown profile field
    print("\n--- TEST H: Unknown Profile Field / Malformed Profile ---")
    malformed_profile = MockVehicleProfile(
        motor_kodu="TEST",
        marka="TEST",
        aciklama="TEST",
        yakit_tipi="GASOLINE",
        max_rpm=0,
        redline=None,  # No redline
        idle_rpm=0,
        hedef_ect=0,
    )
    engine.vehicle_profile = malformed_profile
    engine.sensor_history.clear()
    entry_h = engine._update_sensor_cache("RPM", 4000.0, status=STATUS_VALID, source="MODE01")
    assert entry_h["envelope_status"] == ENVELOPE_UNKNOWN
    print(f"Test H Result: malformed redline -> envelope={entry_h['envelope_status']}")

    # TEST I — Quality preservation (Physical Implausibility Priority)
    print("\n--- TEST I: Quality Preservation & Priority ---")
    engine.vehicle_profile = diesel_profile
    engine.sensor_history.clear()
    # 1. Plausible RPM (5000) above redline -> quality remains GOOD
    entry_i1 = engine._update_sensor_cache("RPM", 5000.0, status=STATUS_VALID, source="MODE01")
    assert entry_i1["physics_status"] == PHYSICS_PLAUSIBLE
    assert entry_i1["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH
    assert entry_i1["quality"] == QUALITY_GOOD

    # 2. Implausible RPM (16000) above redline -> quality remains IMPLAUSIBLE (C-3 quality not downgraded)
    entry_i2 = engine._update_sensor_cache("RPM", 16000.0, status=STATUS_VALID, source="MODE01")
    assert entry_i2["physics_status"] == PHYSICS_IMPLAUSIBLE_HIGH
    assert entry_i2["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH
    assert entry_i2["quality"] == QUALITY_IMPLAUSIBLE
    print(f"Test I Result: RPM 5000 -> quality={entry_i1['quality']}; RPM 16000 -> quality={entry_i2['quality']}")

    # Connect mock simulator for regression
    engine.baglan()
    time.sleep(0.5)

    # TEST J — Phase A-C regression
    print("\n--- TEST J: Regression Checks ---")
    # Phase A
    assert derive_quality_from_status(STATUS_TIMEOUT) == QUALITY_ERROR
    
    # Phase B
    probe_res = engine.manual_did_probe("1640", header="7E0")
    assert probe_res["ok"] is True
    
    # Phase C-2
    assert engine._is_sensor_fresh("RPM", max_age=1000000.0) is True

    # Phase C-3
    assert engine._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE

    # Phase C-4
    assert engine._check_temporal_plausibility("RPM", 850.0, timestamp=time.time()) == TEMPORAL_PLAUSIBLE

    # Phase C-5
    correlations = engine._check_cross_sensor_correlations()
    assert len(correlations) == 3

    # Clean up
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    print("\n✅ ALL PHASE C-6 TESTS (Tests A through J) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
