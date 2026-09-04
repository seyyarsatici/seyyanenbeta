"""
Phase E-5: Acquisition Result Validation & Snapshot Consistency Test Suite
Tests A through S:
- TEST A: All valid -> status=VALID, quality=GOOD, complete=True, errors=[], warnings=[]
- TEST B: Valid but stale -> accepted=True, fresh=False, no timestamp mutation
- TEST C: Implausible -> accepted=False, snapshot quality=IMPLAUSIBLE
- TEST D: NRC -> accepted=False, no spurious error
- TEST E: Timeout -> accepted=False, snapshot quality=ERROR
- TEST F: DID mismatch -> accepted=False
- TEST G: Contradictory status/value -> error detected, accepted=False
- TEST H: Contradictory quality/status -> error detected, accepted=False
- TEST I: Duplicate measurement -> warning reported, no silent deletion
- TEST J: Timestamp missing -> validation error, accepted=False
- TEST K: Future timestamp -> validation error, accepted=False
- TEST L: Backward timestamp ordering -> validation warning
- TEST M: Mode 22 response consistency -> anchored check enforced
- TEST N: Payload contains 7F -> valid payload not misclassified as NRC
- TEST O: Empty results -> clean structured snapshot, no exception
- TEST P: Zero I/O -> verify no serial/network calls during validation
- TEST Q: Original result immutability -> input dicts untouched
- TEST R: Snapshot replacement -> last_validated_snapshot updated cleanly
- TEST S: Regression integration -> DiagnosticSession proxy verified
"""

import time
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NRC,
    STATUS_DID_MISMATCH,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
)

def run_tests():
    print("🚀 Running Phase E-5 Acquisition Result Validation Tests (Tests A through S)...")

    engine = AutoExpertEngine()
    now = time.time()

    # TEST A — All valid
    print("\n--- TEST A: All Valid Acquisition Results ---")
    results_a = [
        {
            "type": "MODE22_DID",
            "id": "1640",
            "header": "7E0",
            "service": "22",
            "request": "221640",
            "status": STATUS_VALID,
            "quality": QUALITY_GOOD,
            "response": "6216400096",
            "payload_hex": "0096",
            "payload_bytes": [0, 150],
            "value": 150,
            "source": "MODE22_CSV",
            "timestamp": now - 0.1,
            "error": None,
        },
        {
            "type": "MODE01_PID",
            "id": "010C",
            "header": "7DF",
            "service": "01",
            "request": "010C",
            "status": STATUS_VALID,
            "quality": QUALITY_GOOD,
            "response": "410C1F40",
            "payload_hex": "1F40",
            "payload_bytes": [31, 64],
            "value": 2000.0,
            "source": "STANDARD_OBD",
            "timestamp": now - 0.05,
            "error": None,
        },
    ]
    snapshot_a = engine.validate_acquisition_results(results_a)
    assert snapshot_a["status"] == STATUS_VALID
    assert snapshot_a["quality"] == QUALITY_GOOD
    assert snapshot_a["complete"] is True
    assert snapshot_a["valid_count"] == 2
    assert snapshot_a["invalid_count"] == 0
    assert len(snapshot_a["errors"]) == 0
    assert len(snapshot_a["warnings"]) == 0
    assert snapshot_a["results"][0]["validation"]["accepted"] is True
    assert snapshot_a["results"][0]["validation"]["fresh"] is True
    print(f"Test A Result: status={snapshot_a['status']}, quality={snapshot_a['quality']}, complete={snapshot_a['complete']}, valid_count={snapshot_a['valid_count']}")

    # TEST B — Valid but stale
    print("\n--- TEST B: Valid But Stale Data ---")
    old_ts = now - 15.0  # 15 seconds old
    results_b = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "request": "221640",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "6216400096",
        "payload_hex": "0096",
        "payload_bytes": [0, 150],
        "value": 150,
        "source": "MODE22_CSV",
        "timestamp": old_ts,
        "error": None,
    }]
    snapshot_b = engine.validate_acquisition_results(results_b)
    assert snapshot_b["quality"] == QUALITY_STALE
    assert snapshot_b["results"][0]["validation"]["accepted"] is True
    assert snapshot_b["results"][0]["validation"]["fresh"] is False
    assert snapshot_b["results"][0]["timestamp"] == old_ts  # Timestamp unchanged
    assert any("stale" in w for w in snapshot_b["warnings"])
    print(f"Test B Result: quality={snapshot_b['quality']}, fresh={snapshot_b['results'][0]['validation']['fresh']}, timestamp preserved={snapshot_b['results'][0]['timestamp'] == old_ts}")

    # TEST C — Implausible
    print("\n--- TEST C: Implausible Measurement ---")
    results_c = [{
        "type": "MODE01_PID",
        "id": "0105",
        "header": "7DF",
        "service": "01",
        "request": "0105",
        "status": STATUS_VALID,
        "quality": QUALITY_IMPLAUSIBLE,
        "response": "4105FFFF",
        "payload_hex": "FFFF",
        "payload_bytes": [255, 255],
        "value": 300.0,
        "source": "STANDARD_OBD",
        "timestamp": now,
        "error": None,
    }]
    snapshot_c = engine.validate_acquisition_results(results_c)
    assert snapshot_c["results"][0]["validation"]["accepted"] is False
    assert snapshot_c["quality"] == QUALITY_IMPLAUSIBLE
    assert snapshot_c["complete"] is False
    print(f"Test C Result: accepted={snapshot_c['results'][0]['validation']['accepted']}, quality={snapshot_c['quality']}")

    # TEST D — NRC
    print("\n--- TEST D: Legitimate NRC Handling ---")
    results_d = [{
        "type": "MODE22_DID",
        "id": "336A",
        "header": "7E0",
        "service": "22",
        "request": "22336A",
        "status": STATUS_NRC,
        "quality": QUALITY_INVALID,
        "response": "7F2231",
        "payload_hex": None,
        "payload_bytes": [],
        "value": None,
        "source": "MODE22_CSV",
        "timestamp": now,
        "error": "NRC 0x31: Request Out of Range",
    }]
    snapshot_d = engine.validate_acquisition_results(results_d)
    assert snapshot_d["results"][0]["validation"]["accepted"] is False
    assert snapshot_d["quality"] == QUALITY_INVALID
    assert len(snapshot_d["errors"]) == 0  # Legitimate NRC is not a validator software error
    print("Test D Result: NRC classified as accepted=False without raising validator internal errors.")

    # TEST E — Timeout
    print("\n--- TEST E: Timeout Handling ---")
    results_e = [{
        "type": "MODE22_DID",
        "id": "DEAD",
        "header": "7E0",
        "service": "22",
        "request": "22DEAD",
        "status": STATUS_TIMEOUT,
        "quality": QUALITY_ERROR,
        "response": None,
        "payload_hex": None,
        "payload_bytes": [],
        "value": None,
        "source": "USER",
        "timestamp": now,
        "error": "Communication timed out",
    }]
    snapshot_e = engine.validate_acquisition_results(results_e)
    assert snapshot_e["results"][0]["validation"]["accepted"] is False
    assert snapshot_e["quality"] == QUALITY_ERROR
    print(f"Test E Result: status={snapshot_e['status']}, quality={snapshot_e['quality']}")

    # TEST F — DID Mismatch
    print("\n--- TEST F: DID Mismatch Handling ---")
    results_f = [{
        "type": "MODE22_DID",
        "id": "1940",
        "header": "7E0",
        "service": "22",
        "request": "221940",
        "status": STATUS_DID_MISMATCH,
        "quality": QUALITY_INVALID,
        "response": "AA6219400096",
        "payload_hex": None,
        "payload_bytes": [],
        "value": None,
        "source": "USER",
        "timestamp": now,
        "error": "DID response detected with offset / mismatch",
    }]
    snapshot_f = engine.validate_acquisition_results(results_f)
    assert snapshot_f["results"][0]["validation"]["accepted"] is False
    print("Test F Result: DID mismatch correctly rejected from accepted results.")

    # TEST G — Contradictory Status / Value
    print("\n--- TEST G: Contradictory Status / Value Contradiction ---")
    results_g = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "request": "221640",
        "status": STATUS_TIMEOUT,
        "quality": QUALITY_ERROR,
        "response": None,
        "payload_hex": None,
        "payload_bytes": [],
        "value": 150,  # Contradiction: timeout but has decoded value!
        "source": "MODE22_CSV",
        "timestamp": now,
        "error": "Communication timed out",
    }]
    snapshot_g = engine.validate_acquisition_results(results_g)
    assert snapshot_g["results"][0]["validation"]["accepted"] is False
    assert any("Contradictory" in e for e in snapshot_g["errors"])
    print(f"Test G Result: Detected contradiction: {snapshot_g['errors'][0]}")

    # TEST H — Contradictory Quality / Status
    print("\n--- TEST H: Contradictory Quality / Status ---")
    results_h = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "request": "221640",
        "status": STATUS_NRC,
        "quality": QUALITY_GOOD,  # Contradiction: NRC but reported GOOD!
        "response": "7F2231",
        "payload_hex": None,
        "payload_bytes": [],
        "value": None,
        "source": "MODE22_CSV",
        "timestamp": now,
        "error": None,
    }]
    snapshot_h = engine.validate_acquisition_results(results_h)
    assert snapshot_h["results"][0]["validation"]["accepted"] is False
    assert any("Contradictory" in e for e in snapshot_h["errors"])
    print(f"Test H Result: Detected contradiction: {snapshot_h['errors'][0]}")

    # TEST I — Duplicate Measurement
    print("\n--- TEST I: Duplicate Measurement Detection ---")
    results_i = [
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": STATUS_VALID, "quality": QUALITY_GOOD, "response": "6216400096", "value": 150, "timestamp": now - 0.1},
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": STATUS_VALID, "quality": QUALITY_GOOD, "response": "6216400096", "value": 150, "timestamp": now - 0.05},
    ]
    snapshot_i = engine.validate_acquisition_results(results_i)
    assert len(snapshot_i["results"]) == 2  # No silent deletion
    assert any("Duplicate" in w for w in snapshot_i["warnings"])
    print(f"Test I Result: Duplicate warning logged, both results preserved: {snapshot_i['warnings'][0]}")

    # TEST J — Timestamp Missing
    print("\n--- TEST J: Missing Timestamp ---")
    results_j = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "6216400096",
        "value": 150,
        "timestamp": None,
    }]
    snapshot_j = engine.validate_acquisition_results(results_j)
    assert snapshot_j["results"][0]["validation"]["accepted"] is False
    assert any("Invalid timestamp" in e for e in snapshot_j["errors"])
    print(f"Test J Result: Missing timestamp flagged: {snapshot_j['errors'][0]}")

    # TEST K — Future Timestamp
    print("\n--- TEST K: Future Timestamp ---")
    results_k = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "6216400096",
        "value": 150,
        "timestamp": now + 500.0,
    }]
    snapshot_k = engine.validate_acquisition_results(results_k)
    assert snapshot_k["results"][0]["validation"]["accepted"] is False
    assert any("Future timestamp" in e for e in snapshot_k["errors"])
    print(f"Test K Result: Future timestamp flagged: {snapshot_k['errors'][0]}")

    # TEST L — Backward Timestamp Ordering
    print("\n--- TEST L: Backward Timestamp Ordering ---")
    results_l = [
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": STATUS_VALID, "quality": QUALITY_GOOD, "response": "6216400096", "value": 150, "timestamp": now},
        {"type": "MODE22_DID", "id": "1641", "header": "7E0", "service": "22", "status": STATUS_VALID, "quality": QUALITY_GOOD, "response": "6216410096", "value": 150, "timestamp": now - 10.0},
    ]
    snapshot_l = engine.validate_acquisition_results(results_l)
    assert any("Backward timestamp" in w for w in snapshot_l["warnings"])
    print(f"Test L Result: Backward ordering logged in warnings: {snapshot_l['warnings'][0]}")

    # TEST M — Mode 22 Response Consistency Check
    print("\n--- TEST M: Mode 22 Response Consistency ---")
    results_m_valid = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "6216400096",
        "value": 150,
        "timestamp": now,
    }]
    snap_m_v = engine.validate_acquisition_results(results_m_valid)
    assert snap_m_v["results"][0]["validation"]["accepted"] is True

    results_m_invalid = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "AA6216400096",  # Unanchored prefix
        "value": 150,
        "timestamp": now,
    }]
    snap_m_inv = engine.validate_acquisition_results(results_m_invalid)
    assert snap_m_inv["results"][0]["validation"]["accepted"] is False
    assert any("mismatch" in e for e in snap_m_inv["errors"])
    print("Test M Result: Mode 22 anchored prefix strictly enforced.")

    # TEST N — Payload Contains 7F
    print("\n--- TEST N: Payload Byte 7F Is Not NRC ---")
    results_n = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "6216407F00",
        "payload_hex": "7F00",
        "payload_bytes": [127, 0],
        "value": 32512,
        "source": "MODE22_CSV",
        "timestamp": now,
        "error": None,
    }]
    snapshot_n = engine.validate_acquisition_results(results_n)
    assert snapshot_n["status"] == STATUS_VALID
    assert snapshot_n["results"][0]["validation"]["accepted"] is True
    print("Test N Result: Payload 7F00 validated correctly as accepted=True.")

    # TEST O — Empty Results
    print("\n--- TEST O: Empty Results Snapshot ---")
    snapshot_o = engine.validate_acquisition_results([])
    assert snapshot_o["status"] == STATUS_NO_DATA
    assert snapshot_o["quality"] == QUALITY_INVALID
    assert snapshot_o["complete"] is None
    assert snapshot_o["results"] == []
    print("Test O Result: Empty results cleanly returned valid structured empty snapshot.")

    # TEST P — Zero I/O Guarantee
    print("\n--- TEST P: Zero I/O Guarantee ---")
    def fail_on_io(*args, **kwargs):
        raise AssertionError("komut_gonder was called during validation! Validation MUST be zero-I/O.")
    old_kg = engine.komut_gonder
    engine.komut_gonder = fail_on_io
    try:
        snap_p = engine.validate_acquisition_results(results_a)
        assert snap_p["status"] == STATUS_VALID
        print("Test P Result: Verified validate_acquisition_results performs zero I/O.")
    finally:
        engine.komut_gonder = old_kg

    # TEST Q — Original Result Immutability
    print("\n--- TEST Q: Original Result Immutability ---")
    orig_item = {
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "response": "6216400096",
        "value": 150,
        "timestamp": now,
    }
    input_list = [orig_item]
    engine.validate_acquisition_results(input_list)
    assert "validation" not in orig_item
    print("Test Q Result: Original result dictionaries were not mutated.")

    # TEST R — Snapshot Replacement
    print("\n--- TEST R: Snapshot Replacement ---")
    engine.validate_acquisition_results(results_a)
    assert engine.last_validated_snapshot["valid_count"] == 2
    engine.validate_acquisition_results(results_c)
    assert engine.last_validated_snapshot["valid_count"] == 0
    assert engine.last_validated_snapshot["quality"] == QUALITY_IMPLAUSIBLE
    print("Test R Result: last_validated_snapshot correctly holds only latest snapshot.")

    # TEST S — DiagnosticSession Proxy Integration
    print("\n--- TEST S: DiagnosticSession Integration ---")
    session = DiagnosticSession(engine=engine)
    session_snap = session.validate_acquisition_results(results_a)
    assert session_snap["status"] == STATUS_VALID
    assert session.get_validated_snapshot()["status"] == STATUS_VALID
    print("Test S Result: DiagnosticSession seamlessly proxies validation.")

    print("\n✅ ALL PHASE E-5 TESTS (Tests A through S) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
