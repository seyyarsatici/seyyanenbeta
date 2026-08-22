#!/usr/bin/env python3
"""
Comprehensive C-Layer Integration Matrix Test
Validates all C-1 through C-6 layers operating together in sequence.
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

def run_integration_matrix():
    print("🚀 Running C-Layer Comprehensive Integration Matrix...")
    engine = AutoExpertEngine()

    diesel_profile = MockVehicleProfile(
        motor_kodu="Z19DTH",
        marka="OPEL",
        aciklama="1.9 CDTI 150hp",
        yakit_tipi="DIESEL",
        max_rpm=4500,
        redline=4500,
        idle_rpm=820,
        hedef_ect=90,
    )
    engine.vehicle_profile = diesel_profile
    t0 = 2000000.0

    # 1. LAYERED SEQUENCE AUDIT
    print("\n--- 1. Layered Sequence Audit ---")

    # Sample 1: RPM = 800 at T0
    s1 = engine._update_sensor_cache("RPM", 800.0, status=STATUS_VALID, timestamp=t0, source="MODE01")
    assert s1["status"] == STATUS_VALID
    assert s1["quality"] == QUALITY_GOOD
    assert s1["physics_status"] == PHYSICS_PLAUSIBLE
    assert s1["temporal_status"] == TEMPORAL_UNKNOWN
    assert s1["envelope_status"] == ENVELOPE_NORMAL
    assert len(engine._get_sensor_history("RPM")) == 1
    assert engine._get_sensor_history("RPM")[-1]["val"] == 800.0
    print(f"Sample 1 (800 RPM @ T0): quality={s1['quality']}, physics={s1['physics_status']}, temporal={s1['temporal_status']}, envelope={s1['envelope_status']}, hist_len=1 ✅")

    # Sample 2: RPM = 900 at T0 + 1.0 (Rate = 100 RPM/s <= 50000)
    s2 = engine._update_sensor_cache("RPM", 900.0, status=STATUS_VALID, timestamp=t0 + 1.0, source="MODE01")
    assert s2["status"] == STATUS_VALID
    assert s2["quality"] == QUALITY_GOOD
    assert s2["physics_status"] == PHYSICS_PLAUSIBLE
    assert s2["temporal_status"] == TEMPORAL_PLAUSIBLE
    assert s2["envelope_status"] == ENVELOPE_NORMAL
    assert len(engine._get_sensor_history("RPM")) == 2
    assert engine._get_sensor_history("RPM")[-1]["val"] == 900.0
    print(f"Sample 2 (900 RPM @ T0+1.0): quality={s2['quality']}, physics={s2['physics_status']}, temporal={s2['temporal_status']}, envelope={s2['envelope_status']}, hist_len=2 ✅")

    # Sample 3: RPM = 5000 at T0 + 1.01 (Rate = 410000 RPM/s > 50000)
    s3 = engine._update_sensor_cache("RPM", 5000.0, status=STATUS_VALID, timestamp=t0 + 1.01, source="MODE01")
    assert s3["status"] == STATUS_VALID
    assert s3["quality"] == QUALITY_SUSPECT
    assert s3["physics_status"] == PHYSICS_PLAUSIBLE  # 5000 is physically plausible (< 15000)
    assert s3["temporal_status"] == TEMPORAL_SUSPECT  # 410000 RPM/s exceeds temporal rate limit
    assert s3["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH  # 5000 exceeds 4500 redline
    # Crucial: Must NOT enter trusted history (still length 2 with [800, 900])
    assert len(engine._get_sensor_history("RPM")) == 2
    assert engine._get_sensor_history("RPM")[-1]["val"] == 900.0
    print(f"Sample 3 (5000 RPM @ T0+1.01): quality={s3['quality']}, physics={s3['physics_status']}, temporal={s3['temporal_status']}, envelope={s3['envelope_status']}, hist_len=2 (excluded) ✅")

    # Sample 4: RPM = 16000 at T0 + 2.0 (Physical Implausibility overrides everything)
    s4 = engine._update_sensor_cache("RPM", 16000.0, status=STATUS_VALID, timestamp=t0 + 2.0, source="MODE01")
    assert s4["status"] == STATUS_VALID
    assert s4["quality"] == QUALITY_IMPLAUSIBLE  # C-3 precedence
    assert s4["physics_status"] == PHYSICS_IMPLAUSIBLE_HIGH
    assert s4["envelope_status"] == ENVELOPE_OUT_OF_RANGE_HIGH
    assert len(engine._get_sensor_history("RPM")) == 2
    print(f"Sample 4 (16000 RPM @ T0+2.0): quality={s4['quality']}, physics={s4['physics_status']}, envelope={s4['envelope_status']}, hist_len=2 (excluded) ✅")

    # Sample 5: RPM = 950 at T0 + 3.0 (Recovery: compares against trusted Sample 2 [900 at T0+1.0], dt=2.0s, rate=25 RPM/s)
    s5 = engine._update_sensor_cache("RPM", 950.0, status=STATUS_VALID, timestamp=t0 + 3.0, source="MODE01")
    assert s5["status"] == STATUS_VALID
    assert s5["quality"] == QUALITY_GOOD
    assert s5["physics_status"] == PHYSICS_PLAUSIBLE
    assert s5["temporal_status"] == TEMPORAL_PLAUSIBLE
    assert s5["envelope_status"] == ENVELOPE_NORMAL
    assert len(engine._get_sensor_history("RPM")) == 3
    assert engine._get_sensor_history("RPM")[-1]["val"] == 950.0
    assert [x["val"] for x in engine._get_sensor_history("RPM")] == [800.0, 900.0, 950.0]
    print(f"Sample 5 (950 RPM @ T0+3.0 - Recovery): quality={s5['quality']}, temporal={s5['temporal_status']}, hist={[x['val'] for x in engine._get_sensor_history('RPM')]} ✅")

    # 2. CROSS-SENSOR CORRELATION WITH MULTI-LAYER INPUTS
    print("\n--- 2. Cross-Sensor Correlation with Layered Inputs ---")
    # Set SPEED = 0 at t0+3.0 (valid, plausible, fresh)
    engine._update_sensor_cache("SPEED", 0.0, status=STATUS_VALID, timestamp=t0 + 3.0, source="MODE01")
    # Set TPS = 15.0 at t0+3.0 (valid, plausible, fresh)
    engine._update_sensor_cache("TPS", 15.0, status=STATUS_VALID, timestamp=t0 + 3.0, source="MODE01")
    # Set MAP = 35.0 at t0+3.0 (valid, plausible, fresh)
    engine._update_sensor_cache("MAP", 35.0, status=STATUS_VALID, timestamp=t0 + 3.0, source="MODE01")

    corr = engine._check_cross_sensor_correlations()
    for r in corr:
        assert r["status"] == CORRELATION_COHERENT
        print(f"Rule {r['rule']}: status={r['status']} ✅")

    # Verify that correlation evaluation did NOT mutate sensor quality or data_cache
    assert engine.data_cache["RPM"]["quality"] == QUALITY_GOOD
    assert engine.data_cache["SPEED"]["quality"] == QUALITY_GOOD
    assert engine.data_cache["TPS"]["quality"] == QUALITY_GOOD
    assert engine.data_cache["MAP"]["quality"] == QUALITY_GOOD

    # 3. COMMUNICATION FAILURE PRECEDENCE
    print("\n--- 3. Communication Failure Precedence ---")
    err_entry = engine._update_sensor_cache("ECT", None, status=STATUS_TIMEOUT, timestamp=t0 + 4.0)
    assert err_entry["status"] == STATUS_TIMEOUT
    assert err_entry["quality"] == QUALITY_ERROR
    assert "physics_status" not in err_entry or err_entry["physics_status"] is None
    assert "temporal_status" not in err_entry or err_entry["temporal_status"] is None
    print(f"TIMEOUT: status={err_entry['status']}, quality={err_entry['quality']} ✅")

    print("\n🎉 ALL C-LAYER INTEGRATION MATRIX CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    run_integration_matrix()
