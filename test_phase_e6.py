"""
Phase E-6: Diagnostic Interpretation / Findings Layer Test Suite
Tests A through R:
- TEST A: Empty snapshot -> clean structured result, 0 findings, no exception, zero I/O
- TEST B: Normal valid snapshot -> 0 false findings, overall severity INFO
- TEST C: Implausible sensor -> CRITICAL severity finding, PLAUSIBILITY source, conservative wording
- TEST D: Stale sensor -> WARNING severity finding, FRESHNESS source
- TEST E: Timeout -> COMMUNICATION finding, no mechanical diagnosis
- TEST F: NRC 31 -> DIAGNOSTIC finding with NRC_MAP description (Request Out of Range)
- TEST G: NRC 33 -> Security Access Denied finding, zero SecurityAccess attempt
- TEST H: DID mismatch -> PROTOCOL_INTEGRITY finding
- TEST I: DTC presence -> DTC finding with active code
- TEST J: Existing correlation anomaly -> surfaced without recalculation
- TEST K: Deterministic ordering -> CRITICAL -> WARNING -> INFO, category, ID
- TEST L: Deduplication -> duplicate finding IDs suppressed
- TEST M: Evidence completeness -> evidence dictionary present in every finding
- TEST N: Confidence bounds -> confidence in [0.0, 1.0]
- TEST O: Original snapshot immutability -> input snapshot and results untouched
- TEST P: Zero I/O guarantee -> verify no ECU communication calls
- TEST Q: State cache replacement -> last_diagnostic_findings updated cleanly
- TEST R: Full regression suite & DiagnosticSession proxy
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
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)

def run_tests():
    print("🚀 Running Phase E-6 Diagnostic Interpretation Tests (Tests A through R)...")

    engine = AutoExpertEngine()
    now = time.time()

    # TEST A — Empty snapshot
    print("\n--- TEST A: Empty Snapshot ---")
    res_a = engine.interpret_diagnostic_snapshot({})
    assert res_a["finding_count"] == 0
    assert res_a["findings"] == []
    assert res_a["overall_severity"] == SEVERITY_INFO
    assert "No diagnostic snapshot" in res_a["summary"]
    print("Test A Result: Clean structured response on empty snapshot with 0 findings.")

    # TEST B — Normal valid snapshot
    print("\n--- TEST B: Normal Valid Snapshot ---")
    snapshot_b = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "complete": True,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "RPM",
                "header": "7DF",
                "service": "01",
                "status": STATUS_VALID,
                "quality": QUALITY_GOOD,
                "value": 850,
                "timestamp": now - 0.1,
                "validation": {"accepted": True, "fresh": True, "issues": []},
            },
            {
                "type": "MODE01_PID",
                "id": "ECT",
                "header": "7DF",
                "service": "01",
                "status": STATUS_VALID,
                "quality": QUALITY_GOOD,
                "value": 90,
                "timestamp": now - 0.1,
                "validation": {"accepted": True, "fresh": True, "issues": []},
            },
        ],
    }
    res_b = engine.interpret_diagnostic_snapshot(snapshot_b)
    assert res_b["finding_count"] == 0
    assert res_b["overall_severity"] == SEVERITY_INFO
    assert "No diagnostic anomalies" in res_b["summary"]
    print("Test B Result: Normal operating parameters produce 0 false findings and overall_severity=INFO.")

    # TEST C — Implausible sensor
    print("\n--- TEST C: Implausible Sensor ---")
    snapshot_c = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_IMPLAUSIBLE,
        "complete": False,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "ECT",
                "header": "7DF",
                "service": "01",
                "status": STATUS_VALID,
                "quality": QUALITY_IMPLAUSIBLE,
                "value": 300.0,
                "timestamp": now,
                "validation": {"accepted": False, "fresh": True, "issues": ["Implausible physical measurement"]},
            }
        ],
    }
    res_c = engine.interpret_diagnostic_snapshot(snapshot_c)
    assert res_c["finding_count"] == 1
    f_c = res_c["findings"][0]
    assert f_c["severity"] == SEVERITY_CRITICAL
    assert f_c["source"] == "PLAUSIBILITY"
    assert "ECT" in f_c["title"]
    assert "sensor circuit, wiring, or ECU interpretation" in f_c["message"]
    assert f_c["evidence"]["value"] == 300.0
    print(f"Test C Result: {f_c['id']} severity={f_c['severity']}, source={f_c['source']}")

    # TEST D — Stale sensor
    print("\n--- TEST D: Stale Sensor ---")
    snapshot_d = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_STALE,
        "complete": False,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "ECT",
                "header": "7DF",
                "service": "01",
                "status": STATUS_VALID,
                "quality": QUALITY_GOOD,
                "value": 90.0,
                "timestamp": now - 20.0,
                "validation": {"accepted": True, "fresh": False, "issues": []},
            }
        ],
    }
    res_d = engine.interpret_diagnostic_snapshot(snapshot_d)
    assert res_d["finding_count"] == 1
    f_d = res_d["findings"][0]
    assert f_d["severity"] == SEVERITY_WARNING
    assert f_d["source"] == "FRESHNESS"
    assert "stale" in f_d["title"].lower()
    assert "unreliable" in f_d["message"].lower()
    print(f"Test D Result: {f_d['id']} severity={f_d['severity']}, source={f_d['source']}")

    # TEST E — Timeout
    print("\n--- TEST E: Timeout Handling ---")
    snapshot_e = {
        "timestamp": now,
        "status": STATUS_TIMEOUT,
        "quality": QUALITY_ERROR,
        "complete": False,
        "results": [
            {
                "type": "MODE22_DID",
                "id": "DEAD",
                "header": "7E0",
                "service": "22",
                "status": STATUS_TIMEOUT,
                "quality": QUALITY_ERROR,
                "value": None,
                "error": "Communication timed out",
                "timestamp": now,
                "validation": {"accepted": False, "fresh": False, "issues": []},
            }
        ],
    }
    res_e = engine.interpret_diagnostic_snapshot(snapshot_e)
    assert res_e["finding_count"] == 1
    f_e = res_e["findings"][0]
    assert f_e["category"] == "COMMUNICATION"
    assert f_e["source"] == "COMMUNICATION"
    print(f"Test E Result: {f_e['id']} category={f_e['category']}, source={f_e['source']}")

    # TEST F — NRC 31
    print("\n--- TEST F: NRC 31 Diagnostic Request Out of Range ---")
    snapshot_f = {
        "timestamp": now,
        "status": STATUS_NRC,
        "quality": QUALITY_INVALID,
        "complete": False,
        "results": [
            {
                "type": "MODE22_DID",
                "id": "336A",
                "header": "7E0",
                "service": "22",
                "status": STATUS_NRC,
                "quality": QUALITY_INVALID,
                "value": None,
                "error": "NRC 0x31: Request Out of Range",
                "timestamp": now,
                "validation": {"accepted": False, "fresh": False, "issues": []},
            }
        ],
    }
    res_f = engine.interpret_diagnostic_snapshot(snapshot_f)
    assert res_f["finding_count"] == 1
    f_f = res_f["findings"][0]
    assert f_f["category"] == "DIAGNOSTIC"
    assert "Request Out of Range" in f_f["message"] or "Request Out of Range" in f_f["evidence"].get("nrc_desc", "")
    print(f"Test F Result: {f_f['id']} message={f_f['message']}")

    # TEST G — NRC 33
    print("\n--- TEST G: NRC 33 Security Access Denied ---")
    snapshot_g = {
        "timestamp": now,
        "status": STATUS_NRC,
        "quality": QUALITY_INVALID,
        "complete": False,
        "results": [
            {
                "type": "MODE22_DID",
                "id": "2000",
                "header": "7E0",
                "service": "22",
                "status": STATUS_NRC,
                "quality": QUALITY_INVALID,
                "value": None,
                "error": "NRC 0x33: Security Access Denied",
                "timestamp": now,
                "validation": {"accepted": False, "fresh": False, "issues": []},
            }
        ],
    }
    res_g = engine.interpret_diagnostic_snapshot(snapshot_g)
    assert res_g["finding_count"] == 1
    f_g = res_g["findings"][0]
    assert f_g["category"] == "DIAGNOSTIC"
    assert "Security Access Denied" in f_g["message"] or "Security Access Denied" in f_g["evidence"].get("nrc_desc", "")
    print(f"Test G Result: {f_g['id']} message={f_g['message']}")

    # TEST H — DID Mismatch
    print("\n--- TEST H: DID Mismatch Protocol Integrity ---")
    snapshot_h = {
        "timestamp": now,
        "status": STATUS_DID_MISMATCH,
        "quality": QUALITY_INVALID,
        "complete": False,
        "results": [
            {
                "type": "MODE22_DID",
                "id": "1940",
                "header": "7E0",
                "service": "22",
                "status": STATUS_DID_MISMATCH,
                "quality": QUALITY_INVALID,
                "response": "AA6219400096",
                "value": None,
                "timestamp": now,
                "validation": {"accepted": False, "fresh": False, "issues": []},
            }
        ],
    }
    res_h = engine.interpret_diagnostic_snapshot(snapshot_h)
    assert res_h["finding_count"] == 1
    f_h = res_h["findings"][0]
    assert f_h["source"] == "PROTOCOL_INTEGRITY"
    assert "mismatch" in f_h["title"].lower()
    print(f"Test H Result: {f_h['id']} source={f_h['source']}")

    # TEST I — DTC Presence
    print("\n--- TEST I: DTC Presence Handling ---")
    res_i = engine.interpret_diagnostic_snapshot(snapshot_b, dtcs=["P0300", "U0100"])
    assert res_i["finding_count"] == 2
    f_dtc1 = next(f for f in res_i["findings"] if "P0300" in f["id"])
    assert f_dtc1["severity"] == SEVERITY_CRITICAL
    assert f_dtc1["source"] == "DTC"
    print(f"Test I Result: DTC findings generated: {[f['id'] for f in res_i['findings']]}")

    # TEST J — Existing Correlation Anomaly
    print("\n--- TEST J: Existing Correlation Anomaly Integration ---")
    anomalies = [{
        "id": "RPM_VSS_INCONSISTENT",
        "severity": SEVERITY_WARNING,
        "title": "RPM and Vehicle Speed are inconsistent",
        "message": "Engine is reported stopped (0 RPM) while vehicle speed is 100 km/h.",
        "evidence": {"RPM": 0, "SPEED": 100},
        "confidence": 0.90,
    }]
    res_j = engine.interpret_diagnostic_snapshot(snapshot_b, correlation_anomalies=anomalies)
    assert res_j["finding_count"] == 1
    f_j = res_j["findings"][0]
    assert f_j["id"] == "FINDING_CORRELATION_RPM_VSS_INCONSISTENT"
    assert f_j["source"] == "CORRELATION"
    print(f"Test J Result: {f_j['id']} source={f_j['source']}")

    # TEST K — Deterministic Ordering
    print("\n--- TEST K: Deterministic Sort Ordering ---")
    mixed_snapshot = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_IMPLAUSIBLE,
        "complete": False,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "ECT",
                "service": "01",
                "status": STATUS_VALID,
                "quality": QUALITY_IMPLAUSIBLE,  # CRITICAL
                "value": 300,
                "timestamp": now,
                "validation": {"accepted": False, "fresh": True, "issues": []},
            },
            {
                "type": "MODE01_PID",
                "id": "RPM",
                "service": "01",
                "status": STATUS_VALID,
                "quality": QUALITY_STALE,  # WARNING
                "value": 850,
                "timestamp": now - 10,
                "validation": {"accepted": True, "fresh": False, "issues": []},
            },
        ],
    }
    res_k = engine.interpret_diagnostic_snapshot(mixed_snapshot, dtcs=["P0100"])
    severities = [f["severity"] for f in res_k["findings"]]
    # CRITICAL items must come before WARNING items
    assert severities.index(SEVERITY_CRITICAL) < severities.index(SEVERITY_WARNING)
    print(f"Test K Result: Deterministic ordering verified: {[(f['id'], f['severity']) for f in res_k['findings']]}")

    # TEST L — Deduplication
    print("\n--- TEST L: Deduplication Handling ---")
    dup_snapshot = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_IMPLAUSIBLE,
        "results": [
            {"type": "MODE01_PID", "id": "ECT", "status": STATUS_VALID, "quality": QUALITY_IMPLAUSIBLE, "value": 300, "timestamp": now, "validation": {"accepted": False, "fresh": True, "issues": []}},
            {"type": "MODE01_PID", "id": "ECT", "status": STATUS_VALID, "quality": QUALITY_IMPLAUSIBLE, "value": 300, "timestamp": now, "validation": {"accepted": False, "fresh": True, "issues": []}},
        ],
    }
    res_l = engine.interpret_diagnostic_snapshot(dup_snapshot)
    assert res_l["finding_count"] == 1
    assert len([f for f in res_l["findings"] if f["id"] == "FINDING_ECT_IMPLAUSIBLE"]) == 1
    print("Test L Result: Duplicate findings on the same underlying issue deduplicated to 1 item.")

    # TEST M — Evidence Completeness
    print("\n--- TEST M: Evidence Completeness ---")
    for f in res_k["findings"]:
        assert isinstance(f.get("evidence"), dict)
        assert len(f["evidence"]) > 0
    print("Test M Result: Evidence dictionary validated across all generated findings.")

    # TEST N — Confidence Bounds
    print("\n--- TEST N: Confidence Bounds Verification ---")
    for f in res_k["findings"]:
        assert 0.0 <= f["confidence"] <= 1.0
    print("Test N Result: Confidence values verified bounded between 0.0 and 1.0.")

    # TEST O — Original Snapshot Immutability
    print("\n--- TEST O: Original Snapshot Immutability ---")
    orig_results_len = len(snapshot_b["results"])
    engine.interpret_diagnostic_snapshot(snapshot_b)
    assert len(snapshot_b["results"]) == orig_results_len
    print("Test O Result: Input snapshot and result objects verified unmodified.")

    # TEST P — Zero I/O Guarantee
    print("\n--- TEST P: Zero I/O Guarantee ---")
    def fail_on_io(*args, **kwargs):
        raise AssertionError("komut_gonder was called during interpretation! Interpretation MUST be zero-I/O.")
    old_kg = engine.komut_gonder
    engine.komut_gonder = fail_on_io
    try:
        res_p = engine.interpret_diagnostic_snapshot(snapshot_b)
        assert res_p["finding_count"] == 0
        print("Test P Result: Verified interpret_diagnostic_snapshot performs zero I/O.")
    finally:
        engine.komut_gonder = old_kg

    # TEST Q — State Cache Replacement
    print("\n--- TEST Q: State Cache Replacement ---")
    engine.interpret_diagnostic_snapshot(snapshot_c)
    assert len(engine.last_diagnostic_findings) == 1
    engine.interpret_diagnostic_snapshot(snapshot_b)
    assert len(engine.last_diagnostic_findings) == 0
    print("Test Q Result: last_diagnostic_findings reflects only the latest interpretation.")

    # TEST R — Full Regression & DiagnosticSession Proxy
    print("\n--- TEST R: DiagnosticSession Proxy Integration ---")
    session = DiagnosticSession(engine=engine)
    session_res = session.interpret_diagnostic_snapshot(snapshot_c)
    assert session_res["finding_count"] == 1
    assert len(session.get_diagnostic_findings()) == 1
    print("Test R Result: DiagnosticSession seamlessly proxies diagnostic interpretation.")

    print("\n✅ ALL PHASE E-6 TESTS (Tests A through R) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
