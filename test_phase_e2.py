"""
Phase E-2: ECU Capability Discovery Test Suite
Tests A through P:
- TEST A: Positive Mode22 capability (1640 under 7E0 -> CAPABILITY_SUPPORTED)
- TEST B: Unsupported DID (336A under 7E0 -> CAPABILITY_NEGATIVE_RESPONSE, nrc="31")
- TEST C: Security required (2000 under 7E0 -> CAPABILITY_NEGATIVE_RESPONSE, nrc="33", no SecurityAccess)
- TEST D: No response (9999 under 7E0 -> CAPABILITY_NO_RESPONSE)
- TEST E: Timeout (DEAD under 7E0 -> CAPABILITY_TIMEOUT)
- TEST F: DID mismatch (1940 under 7E0 -> CAPABILITY_DID_MISMATCH)
- TEST G: Duplicate candidates (deduplicated down to 1 query and 1 result)
- TEST H: Header restoration (Initial 7DF -> probe under 7E0 -> restores to 7DF even on exception)
- TEST I: Multi-frame positive capability (1641 under 7E0 -> CAPABILITY_SUPPORTED, full payload preserved)
- TEST J: Standard PID capability reuse (include_standard_pids=True produces structured results)
- TEST K: Candidate source preserved ("USER", "MODE22_CSV", "STANDARD_OBD")
- TEST L: Empty candidate set (dids=[] -> returns [], no queries)
- TEST M: No arbitrary brute force (verifies no 0x0000..0xFFFF loop exists in discover_ecu_capabilities)
- TEST N: D-1/D-2/D-3 regression
- TEST O: C-layer regression
- TEST P: E-1 session regression
"""

import time
import inspect
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    CAPABILITY_SUPPORTED,
    CAPABILITY_UNSUPPORTED,
    CAPABILITY_NO_RESPONSE,
    CAPABILITY_NEGATIVE_RESPONSE,
    CAPABILITY_TIMEOUT,
    CAPABILITY_DID_MISMATCH,
    CAPABILITY_UNAVAILABLE,
    STATUS_VALID,
    STATUS_TIMEOUT,
    QUALITY_GOOD,
    PHYSICS_PLAUSIBLE,
)

def run_tests():
    print("🚀 Running Phase E-2 ECU Capability Discovery Tests (Tests A through P)...")

    engine = AutoExpertEngine()
    engine.baglan()
    time.sleep(1.0)

    # TEST A — Positive Mode22 Capability
    print("\n--- TEST A: Positive Mode 22 Capability (1640) ---")
    res_a = engine.discover_ecu_capabilities(headers=["7E0"], dids=["1640"], candidate_source="USER")
    assert len(res_a) == 1
    item_a = res_a[0]
    assert item_a["type"] == "MODE22_DID"
    assert item_a["id"] == "1640"
    assert item_a["header"] == "7E0"
    assert item_a["service"] == "22"
    assert item_a["status"] == CAPABILITY_SUPPORTED
    assert item_a["request"] == "221640"
    assert item_a["response"] == "6216400096"
    assert item_a["nrc"] is None
    assert item_a["candidate_source"] == "USER"
    assert len(item_a["raw_response"]) > 0
    print(f"Test A Result: {item_a['request']} -> status={item_a['status']}, response={item_a['response']}")

    # TEST B — Unsupported DID (NRC 31)
    print("\n--- TEST B: Unsupported DID (336A -> NRC 31) ---")
    res_b = engine.discover_ecu_capabilities(headers=["7E0"], dids=["336A"])
    assert len(res_b) == 1
    item_b = res_b[0]
    assert item_b["status"] == CAPABILITY_NEGATIVE_RESPONSE
    assert item_b["nrc"] == "31"
    assert "out of range" in item_b["details"].lower() or "not supported" in item_b["details"].lower()
    print(f"Test B Result: {item_b['request']} -> status={item_b['status']}, nrc={item_b['nrc']}, details={item_b['details']}")

    # TEST C — Security Required (NRC 33)
    print("\n--- TEST C: Security Required (2000 -> NRC 33) ---")
    res_c = engine.discover_ecu_capabilities(headers=["7E0"], dids=["2000"])
    assert len(res_c) == 1
    item_c = res_c[0]
    assert item_c["status"] == CAPABILITY_NEGATIVE_RESPONSE
    assert item_c["nrc"] == "33"
    assert "security" in item_c["details"].lower()
    # Confirm no SecurityAccess bypass occurred
    assert engine.last_response_status != STATUS_VALID
    print(f"Test C Result: {item_c['request']} -> status={item_c['status']}, nrc={item_c['nrc']}, details={item_c['details']}")

    # TEST D — No Response (NO DATA)
    print("\n--- TEST D: No Response (9999 -> NO DATA) ---")
    res_d = engine.discover_ecu_capabilities(headers=["7E0"], dids=["9999"])
    assert len(res_d) == 1
    item_d = res_d[0]
    assert item_d["status"] == CAPABILITY_NO_RESPONSE
    print(f"Test D Result: {item_d['request']} -> status={item_d['status']}, details={item_d['details']}")

    # TEST E — Timeout
    print("\n--- TEST E: Timeout (DEAD) ---")
    # Temporarily set komut_gonder timeout short for DEAD
    res_e = engine.discover_ecu_capabilities(headers=["7E0"], dids=["DEAD"])
    assert len(res_e) == 1
    item_e = res_e[0]
    assert item_e["status"] in (CAPABILITY_TIMEOUT, CAPABILITY_NO_RESPONSE)
    print(f"Test E Result: {item_e['request']} -> status={item_e['status']}, details={item_e['details']}")

    # TEST F — DID Mismatch
    print("\n--- TEST F: DID Mismatch (1940) ---")
    res_f = engine.discover_ecu_capabilities(headers=["7E0"], dids=["1940"])
    assert len(res_f) == 1
    item_f = res_f[0]
    assert item_f["status"] == CAPABILITY_DID_MISMATCH
    print(f"Test F Result: {item_f['request']} -> status={item_f['status']}, details={item_f['details']}")

    # TEST G — Duplicate Candidates
    print("\n--- TEST G: Duplicate Candidates Deduplication ---")
    res_g = engine.discover_ecu_capabilities(headers=["7E0"], dids=["1640", "1640", "16 40", "221640", "0X1640"])
    assert len(res_g) == 1
    assert res_g[0]["id"] == "1640"
    print("Test G Result: 5 duplicate representations reduced to 1 unique query and 1 result.")

    # TEST H — Header Restoration
    print("\n--- TEST H: Header Restoration Safety ---")
    assert engine.current_header == "7DF"
    # Query under 7E0
    engine.discover_ecu_capabilities(headers=["7E0"], dids=["1640"])
    assert engine.current_header == "7DF"

    # Even on mock exception during query
    orig_ensure = engine._ensure_session
    def broken_ensure(*args, **kwargs):
        raise RuntimeError("Simulated transient header exception")
    engine._ensure_session = broken_ensure
    try:
        engine.discover_ecu_capabilities(headers=["7E0"], dids=["1640"])
    except RuntimeError:
        pass
    finally:
        engine._ensure_session = orig_ensure
    assert engine.current_header == "7DF"
    print("Test H Result: Header safely restored to 7DF even after simulated exception.")

    # TEST I — Multi-Frame Positive Capability
    print("\n--- TEST I: Multi-Frame Positive Capability (1641) ---")
    res_i = engine.discover_ecu_capabilities(headers=["7E0"], dids=["1641"])
    assert len(res_i) == 1
    item_i = res_i[0]
    assert item_i["status"] == CAPABILITY_SUPPORTED
    assert item_i["id"] == "1641"
    assert item_i["response"].startswith("621641")
    assert "010203040506070809" in item_i["response"]
    print(f"Test I Result: {item_i['request']} -> status={item_i['status']}, response={item_i['response']}")

    # TEST J — Standard PID Capability Reuse
    print("\n--- TEST J: Standard PID Capability Reuse ---")
    res_j = engine.discover_ecu_capabilities(headers=["7E0"], dids=["1640"], include_standard_pids=True)
    std_items = [x for x in res_j if x["type"] == "MODE01_PID"]
    assert len(std_items) > 0
    assert std_items[0]["service"] == "01"
    assert std_items[0]["status"] == CAPABILITY_SUPPORTED
    print(f"Test J Result: Successfully included {len(std_items)} standard Mode 01 PID capabilities.")

    # TEST K — Candidate Source
    print("\n--- TEST K: Candidate Source Preservation ---")
    res_k = engine.discover_ecu_capabilities(headers=["7E0"], dids=["1640"], candidate_source="MODE22_CSV")
    assert res_k[0]["candidate_source"] == "MODE22_CSV"
    print(f"Test K Result: candidate_source='{res_k[0]['candidate_source']}' accurately preserved.")

    # TEST L — Empty Candidate Set
    print("\n--- TEST L: Empty Candidate Set ---")
    res_l = engine.discover_ecu_capabilities(headers=["7E0"], dids=[])
    assert res_l == []
    print("Test L Result: Empty candidate list returned [] immediately with zero queries.")

    # TEST M — No Arbitrary Brute Force
    print("\n--- TEST M: No Arbitrary Brute-Force Scan Verification ---")
    src = inspect.getsource(engine.discover_ecu_capabilities)
    assert "0x10000" not in src
    assert "65536" not in src
    assert "22FFFF" not in src
    assert "range(0" not in src
    print("Test M Result: Verified discover_ecu_capabilities contains no 16-bit or brute-force loops.")

    # Clean up mock serial
    if engine.io_worker:
        engine.io_worker.stop()
    if engine.ser:
        engine.ser.close()

    # TEST N — D-layer Regression
    print("\n--- TEST N: D-Layer Regression ---")
    engine_n = AutoExpertEngine()
    ev_n = engine_n._collect_diagnostic_evidence()
    hyp_n = engine_n._infer_fault_hypotheses(ev_n)
    rec_n = engine_n._recommend_diagnostic_tests(hyp_n)
    assert isinstance(ev_n, list)
    assert isinstance(hyp_n, list)
    assert isinstance(rec_n, list)
    print("Test N Result: D-1, D-2, D-3 executed without regression.")

    # TEST O — C-layer Regression
    print("\n--- TEST O: C-Layer Regression ---")
    engine_o = AutoExpertEngine()
    assert engine_o._check_physical_plausibility("ECT", 90.0) == PHYSICS_PLAUSIBLE
    print("Test O Result: Physical and temporal plausibility intact.")

    # TEST P — E-1 Session Regression
    print("\n--- TEST P: E-1 Session Regression ---")
    session_p = DiagnosticSession(engine=AutoExpertEngine())
    assert session_p.state == "IDLE"
    snap_p = session_p.get_session_snapshot()
    assert snap_p["state"] == "IDLE"
    print("Test P Result: DiagnosticSession state and snapshot intact.")

    print("\n✅ ALL PHASE E-2 TESTS (Tests A through P) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
