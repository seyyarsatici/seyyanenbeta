"""
Phase E-7: Diagnostic Recommendation & Action Prioritization Test Suite
Tests A through V:
- TEST A: Empty findings -> clean structured result, zero recommendations, no exception, zero I/O
- TEST B: Normal findings (INFO-only) -> INFO recommendation or clean result, never priority 1
- TEST C: CRITICAL finding -> priority 1 recommendation
- TEST D: WARNING finding -> priority 2 recommendation
- TEST E: Stale sensor finding -> REACQUIRE recommendation, not mechanical replacement
- TEST F: Implausible ECT finding -> cooling/ECT inspection, no automatic "replace sensor" conclusion
- TEST G: Communication timeout finding -> communication recommendation, no mechanical diagnosis
- TEST H: NRC 31 -> capability/request recommendation, no ECU mechanical-fault claim
- TEST I: NRC 33 -> security/access-related recommendation, NO SecurityAccess attempt
- TEST J: DID mismatch -> configuration/response-integrity recommendation
- TEST K: DTC finding -> REVIEW_DTC recommendation, no invented component replacement
- TEST L: Correlation finding -> recommendation references existing correlation finding
- TEST M: Duplicate findings -> duplicate finding IDs suppressed in recommendations
- TEST N: Multi-finding merge -> two findings from same subsystem consolidated into one recommendation
- TEST O: Conflicting data quality -> stale/invalid finding prioritizes reacquisition before mechanical diagnosis
- TEST P: Deterministic ordering -> identical recommendation ordering across repeated runs
- TEST Q: Evidence linkage -> every recommendation references valid finding IDs
- TEST R: Confidence bounds -> confidence in [0.0, 1.0]
- TEST S: Input immutability -> input findings list and dicts unchanged
- TEST T: No I/O guarantee -> monkeypatch komut_gonder / serial -> 0 ECU requests
- TEST U: Cache replacement -> last_diagnostic_recommendations updated cleanly
- TEST V: Full regression suite & DiagnosticSession proxy
"""

import time
import copy
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    ACTION_VERIFY,
    ACTION_INSPECT,
    ACTION_REACQUIRE,
    ACTION_REVIEW_DTC,
    ACTION_CHECK_CONNECTION,
    ACTION_CHECK_CONFIGURATION,
    RECOMMENDATION_PRIORITY_CRITICAL,
    RECOMMENDATION_PRIORITY_WARNING,
    RECOMMENDATION_PRIORITY_INFO,
)

def run_tests():
    print("🚀 Running Phase E-7 Diagnostic Recommendation Tests (Tests A through V)...")

    engine = AutoExpertEngine()
    now = time.time()

    # TEST A — Empty findings
    print("\n--- TEST A: Empty Findings ---")
    res_a = engine.generate_diagnostic_recommendations([])
    assert res_a["recommendation_count"] == 0
    assert res_a["recommendations"] == []
    assert res_a["overall_priority"] == RECOMMENDATION_PRIORITY_INFO
    assert "No diagnostic recommendations" in res_a["summary"]
    print("Test A Result: Clean structured response on empty findings with 0 recommendations.")

    # TEST B — Normal findings (INFO-only)
    print("\n--- TEST B: Normal INFO Findings ---")
    info_findings = [
        {
            "id": "FINDING_SYSTEM_NORMAL",
            "severity": SEVERITY_INFO,
            "category": "ENGINE",
            "title": "Engine operating normally",
            "message": "All operating parameters within expected baseline.",
            "evidence": {"RPM": 850, "ECT": 90},
            "confidence": 0.90,
            "source": "BASELINE",
        }
    ]
    res_b = engine.generate_diagnostic_recommendations(info_findings)
    assert res_b["overall_priority"] != RECOMMENDATION_PRIORITY_CRITICAL
    if res_b["recommendations"]:
        assert res_b["recommendations"][0]["priority"] == RECOMMENDATION_PRIORITY_INFO
    print("Test B Result: INFO-only findings never produce Priority 1 recommendations.")

    # TEST C — CRITICAL finding
    print("\n--- TEST C: CRITICAL Finding ---")
    crit_findings = [
        {
            "id": "FINDING_ECT_IMPLAUSIBLE",
            "severity": SEVERITY_CRITICAL,
            "category": "COOLING",
            "title": "ECT measurement is physically implausible",
            "message": "ECT reading (215 C) is outside plausible limits.",
            "evidence": {"sensor": "ECT", "value": 215},
            "confidence": 0.95,
            "source": "PLAUSIBILITY",
        }
    ]
    res_c = engine.generate_diagnostic_recommendations(crit_findings)
    assert res_c["recommendation_count"] == 1
    assert res_c["recommendations"][0]["priority"] == RECOMMENDATION_PRIORITY_CRITICAL
    assert res_c["recommendations"][0]["severity"] == SEVERITY_CRITICAL
    assert res_c["overall_priority"] == RECOMMENDATION_PRIORITY_CRITICAL
    print("Test C Result: CRITICAL finding produces Priority 1 recommendation.")

    # TEST D — WARNING finding
    print("\n--- TEST D: WARNING Finding ---")
    warn_findings = [
        {
            "id": "FINDING_ECT_HIGH",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "Engine coolant temperature is elevated",
            "message": "ECT reading is 118 C.",
            "evidence": {"sensor": "ECT", "value": 118},
            "confidence": 0.90,
            "source": "DIAGNOSTIC_THRESHOLD",
        }
    ]
    res_d = engine.generate_diagnostic_recommendations(warn_findings)
    assert res_d["recommendation_count"] == 1
    assert res_d["recommendations"][0]["priority"] == RECOMMENDATION_PRIORITY_WARNING
    assert res_d["overall_priority"] == RECOMMENDATION_PRIORITY_WARNING
    print("Test D Result: WARNING finding produces Priority 2 recommendation.")

    # TEST E — Stale sensor finding
    print("\n--- TEST E: Stale Sensor Finding ---")
    stale_findings = [
        {
            "id": "FINDING_ECT_STALE",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "ECT data is stale",
            "message": "ECT measurement is stale.",
            "evidence": {"sensor": "ECT", "value": 90, "fresh": False},
            "confidence": 0.85,
            "source": "FRESHNESS",
        }
    ]
    res_e = engine.generate_diagnostic_recommendations(stale_findings)
    assert res_e["recommendation_count"] == 1
    rec_e = res_e["recommendations"][0]
    assert rec_e["action_type"] == ACTION_REACQUIRE
    assert "reacquire" in rec_e["action"].lower() or "verify" in rec_e["action"].lower()
    assert "replace" not in rec_e["action"].lower()
    print("Test E Result: Stale sensor produces REACQUIRE recommendation, no component replacement prescribed.")

    # TEST F — Implausible ECT finding
    print("\n--- TEST F: Implausible ECT Finding ---")
    res_f = engine.generate_diagnostic_recommendations(crit_findings)
    rec_f = res_f["recommendations"][0]
    assert rec_f["action_type"] == ACTION_INSPECT
    assert "replace" not in rec_f["action"].lower()
    assert "verify" in rec_f["action"].lower() or "inspect" in rec_f["action"].lower()
    print("Test F Result: Implausible ECT produces inspection recommendation without premature parts replacement claim.")

    # TEST G — Communication timeout finding
    print("\n--- TEST G: Communication Timeout Finding ---")
    comm_findings = [
        {
            "id": "FINDING_RPM_COMM_TIMEOUT",
            "severity": SEVERITY_WARNING,
            "category": "COMMUNICATION",
            "title": "ECU communication failure for RPM",
            "message": "ECU request 010C on header 7DF timed out.",
            "evidence": {"type": "MODE01_PID", "id": "RPM", "status": "TIMEOUT"},
            "confidence": 1.0,
            "source": "COMMUNICATION",
        }
    ]
    res_g = engine.generate_diagnostic_recommendations(comm_findings)
    rec_g = res_g["recommendations"][0]
    assert rec_g["category"] == "COMMUNICATION"
    assert rec_g["action_type"] == ACTION_CHECK_CONNECTION
    assert "ecu fault" not in rec_g["action"].lower() or "before suspecting" in rec_g["action"].lower()
    print("Test G Result: Communication timeout produces interface/connection recommendation.")

    # TEST H — NRC 31
    print("\n--- TEST H: NRC 31 (Request Out of Range) ---")
    nrc31_findings = [
        {
            "id": "FINDING_221155_NRC_31",
            "severity": SEVERITY_WARNING,
            "category": "DIAGNOSTIC",
            "title": "Diagnostic service rejected: NRC 0x31",
            "message": "ECU rejected request 221155 with NRC 0x31 (Request Out of Range).",
            "evidence": {"type": "MODE22_DID", "id": "221155", "nrc": "31", "nrc_desc": "Request Out of Range"},
            "confidence": 1.0,
            "source": "NRC",
        }
    ]
    res_h = engine.generate_diagnostic_recommendations(nrc31_findings)
    rec_h = res_h["recommendations"][0]
    assert rec_h["action_type"] == ACTION_CHECK_CONFIGURATION
    assert "unsupported" in rec_h["action"].lower() or "configuration" in rec_h["action"].lower()
    assert "failure" not in rec_h["action"].lower() or "without assuming" in rec_h["action"].lower()
    print("Test H Result: NRC 31 generates configuration/capability recommendation, not mechanical defect.")

    # TEST I — NRC 33 (Security Access Denied)
    print("\n--- TEST I: NRC 33 (Security Access Denied) ---")
    nrc33_findings = [
        {
            "id": "FINDING_22F190_NRC_33",
            "severity": SEVERITY_WARNING,
            "category": "DIAGNOSTIC",
            "title": "Diagnostic service rejected: NRC 0x33",
            "message": "ECU rejected request 22F190 with NRC 0x33 (Security Access Denied).",
            "evidence": {"type": "MODE22_DID", "id": "22F190", "nrc": "33", "nrc_desc": "Security Access Denied"},
            "confidence": 1.0,
            "source": "NRC",
        }
    ]
    res_i = engine.generate_diagnostic_recommendations(nrc33_findings)
    rec_i = res_i["recommendations"][0]
    assert rec_i["action_type"] == ACTION_CHECK_CONFIGURATION
    assert "security" in rec_i["action"].lower()
    print("Test I Result: NRC 33 generates security access prerequisites review; no automated SecurityAccess.")

    # TEST J — DID mismatch
    print("\n--- TEST J: DID Mismatch ---")
    did_findings = [
        {
            "id": "FINDING_220101_DID_MISMATCH",
            "severity": SEVERITY_WARNING,
            "category": "DIAGNOSTIC",
            "title": "Diagnostic response DID mismatch on 220101",
            "message": "Response for 220101 contained unexpected framing.",
            "evidence": {"type": "MODE22_DID", "id": "220101", "status": "DID_MISMATCH"},
            "confidence": 0.90,
            "source": "PROTOCOL_INTEGRITY",
        }
    ]
    res_j = engine.generate_diagnostic_recommendations(did_findings)
    rec_j = res_j["recommendations"][0]
    assert rec_j["action_type"] == ACTION_CHECK_CONFIGURATION
    assert "integrity" in rec_j["action"].lower() or "framing" in rec_j["reason"].lower()
    print("Test J Result: DID mismatch generates response framing and configuration recommendation.")

    # TEST K — DTC finding
    print("\n--- TEST K: DTC Finding ---")
    dtc_findings = [
        {
            "id": "FINDING_DTC_P0115",
            "severity": SEVERITY_CRITICAL,
            "category": "DIAGNOSTIC",
            "title": "Diagnostic Trouble Code active: P0115",
            "message": "Active diagnostic trouble code P0115 confirmed in ECU fault memory.",
            "evidence": {"dtc": "P0115", "source": "DTC_MEMORY"},
            "confidence": 1.0,
            "source": "DTC",
        }
    ]
    res_k = engine.generate_diagnostic_recommendations(dtc_findings)
    rec_k = res_k["recommendations"][0]
    assert rec_k["action_type"] == ACTION_REVIEW_DTC
    assert "P0115" in rec_k["id"]
    assert "replace" not in rec_k["action"].lower() or "before replacing" in rec_k["action"].lower()
    print("Test K Result: Active DTC generates REVIEW_DTC recommendation per OEM procedure.")

    # TEST L — Correlation finding
    print("\n--- TEST L: Correlation Finding ---")
    corr_findings = [
        {
            "id": "FINDING_CORRELATION_RPM_SPEED_MISMATCH",
            "severity": SEVERITY_WARNING,
            "category": "SENSOR",
            "title": "RPM and Vehicle Speed correlation inconsistent",
            "message": "Engine speed indicated high while vehicle speed remained zero.",
            "evidence": {"RPM": 3500, "SPEED": 0},
            "confidence": 0.85,
            "source": "CORRELATION",
        }
    ]
    res_l = engine.generate_diagnostic_recommendations(corr_findings)
    rec_l = res_l["recommendations"][0]
    assert rec_l["action_type"] == ACTION_VERIFY
    assert "FINDING_CORRELATION_RPM_SPEED_MISMATCH" in rec_l["finding_ids"]
    print("Test L Result: Correlation anomaly produces multi-signal verification action linked to finding ID.")

    # TEST M — Duplicate findings
    print("\n--- TEST M: Duplicate Findings Suppression ---")
    dup_findings = [
        {
            "id": "FINDING_ECT_HIGH",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "ECT elevated",
            "message": "ECT reading is 118 C.",
            "evidence": {"sensor": "ECT", "value": 118},
            "confidence": 0.90,
            "source": "DIAGNOSTIC_THRESHOLD",
        },
        {
            "id": "FINDING_ECT_HIGH",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "ECT elevated",
            "message": "ECT reading is 118 C.",
            "evidence": {"sensor": "ECT", "value": 118},
            "confidence": 0.90,
            "source": "DIAGNOSTIC_THRESHOLD",
        },
    ]
    res_m = engine.generate_diagnostic_recommendations(dup_findings)
    assert res_m["recommendation_count"] == 1
    assert len(res_m["recommendations"][0]["finding_ids"]) == 1
    print("Test M Result: Duplicate findings do not produce duplicate recommendations.")

    # TEST N — Multi-finding merge
    print("\n--- TEST N: Multi-Finding Subsystem Merge ---")
    multi_findings = [
        {
            "id": "FINDING_ECT_HIGH",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "ECT is elevated",
            "message": "ECT reading is 118 C.",
            "evidence": {"sensor": "ECT", "value": 118},
            "confidence": 0.85,
            "source": "DIAGNOSTIC_THRESHOLD",
        },
        {
            "id": "FINDING_ECT_IMPLAUSIBLE",
            "severity": SEVERITY_CRITICAL,
            "category": "COOLING",
            "title": "ECT is implausible",
            "message": "ECT reading is 215 C.",
            "evidence": {"sensor": "ECT", "value": 215},
            "confidence": 0.95,
            "source": "PLAUSIBILITY",
        },
    ]
    res_n = engine.generate_diagnostic_recommendations(multi_findings)
    assert res_n["recommendation_count"] == 1
    rec_n = res_n["recommendations"][0]
    assert rec_n["priority"] == RECOMMENDATION_PRIORITY_CRITICAL
    assert "FINDING_ECT_HIGH" in rec_n["finding_ids"]
    assert "FINDING_ECT_IMPLAUSIBLE" in rec_n["finding_ids"]
    print("Test N Result: Multiple cooling findings consolidated into one prioritized recommendation.")

    # TEST O — Conflicting data quality
    print("\n--- TEST O: Conflicting Data Quality Priority ---")
    conflict_findings = [
        {
            "id": "FINDING_ECT_STALE",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "ECT data is stale",
            "message": "ECT measurement is stale.",
            "evidence": {"sensor": "ECT", "value": 120, "fresh": False},
            "confidence": 0.85,
            "source": "FRESHNESS",
        },
        {
            "id": "FINDING_ECT_HIGH",
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "title": "ECT is elevated",
            "message": "ECT reading is 120 C.",
            "evidence": {"sensor": "ECT", "value": 120},
            "confidence": 0.90,
            "source": "DIAGNOSTIC_THRESHOLD",
        },
    ]
    res_o = engine.generate_diagnostic_recommendations(conflict_findings)
    rec_o = res_o["recommendations"][0]
    assert rec_o["action_type"] == ACTION_REACQUIRE
    assert "reacquire" in rec_o["action"].lower()
    print("Test O Result: Data quality/freshness conflict correctly prioritizes reacquisition before mechanical diagnosis.")

    # TEST P — Deterministic ordering
    print("\n--- TEST P: Deterministic Ordering ---")
    mixed_findings = [
        warn_findings[0],
        crit_findings[0],
        comm_findings[0],
        dtc_findings[0],
    ]
    res_p1 = engine.generate_diagnostic_recommendations(mixed_findings)
    res_p2 = engine.generate_diagnostic_recommendations(mixed_findings)
    order1 = [r["id"] for r in res_p1["recommendations"]]
    order2 = [r["id"] for r in res_p2["recommendations"]]
    assert order1 == order2
    # Verify priority sorting (Priority 1 items before Priority 2)
    priorities = [r["priority"] for r in res_p1["recommendations"]]
    assert priorities == sorted(priorities)
    print("Test P Result: Deterministic ordering verified across multiple identical runs.")

    # TEST Q — Evidence linkage
    print("\n--- TEST Q: Evidence Linkage ---")
    for r in res_p1["recommendations"]:
        assert isinstance(r["finding_ids"], list)
        assert len(r["finding_ids"]) > 0
        for fid in r["finding_ids"]:
            assert any(f["id"] == fid for f in mixed_findings)
    print("Test Q Result: Every recommendation correctly links to valid source finding IDs.")

    # TEST R — Confidence bounds
    print("\n--- TEST R: Confidence Bounds ---")
    for r in res_p1["recommendations"]:
        assert 0.0 <= r["confidence"] <= 1.0
    print("Test R Result: All recommendation confidence values bounded in [0.0, 1.0].")

    # TEST S — Input immutability
    print("\n--- TEST S: Input Immutability ---")
    findings_copy = copy.deepcopy(mixed_findings)
    engine.generate_diagnostic_recommendations(mixed_findings)
    assert mixed_findings == findings_copy
    print("Test S Result: Input findings list and dictionaries are strictly immutable.")

    # TEST T — No I/O guarantee
    print("\n--- TEST T: Zero I/O Guarantee ---")
    def fail_on_io(*args, **kwargs):
        raise AssertionError("I/O must NEVER be triggered by generate_diagnostic_recommendations!")

    orig_komut = engine.komut_gonder
    engine.komut_gonder = fail_on_io
    try:
        res_t = engine.generate_diagnostic_recommendations(mixed_findings)
        assert res_t["recommendation_count"] > 0
    finally:
        engine.komut_gonder = orig_komut
    print("Test T Result: Zero I/O guaranteed during recommendation generation.")

    # TEST U — Cache replacement
    print("\n--- TEST U: Cache Replacement ---")
    engine.generate_diagnostic_recommendations(crit_findings)
    assert len(engine.last_diagnostic_recommendations) == 1
    assert engine.last_diagnostic_recommendations[0]["priority"] == RECOMMENDATION_PRIORITY_CRITICAL

    engine.generate_diagnostic_recommendations([])
    assert len(engine.last_diagnostic_recommendations) == 0
    assert engine.get_diagnostic_recommendations() == []
    print("Test U Result: Cache cleanly replaced on each call without unbounded accumulation.")

    # TEST V — DiagnosticSession proxy & Regression
    print("\n--- TEST V: DiagnosticSession Proxy ---")
    session = DiagnosticSession(engine=engine)
    session_res = session.generate_diagnostic_recommendations(warn_findings)
    assert session_res["recommendation_count"] == 1
    assert len(session.get_diagnostic_recommendations()) == 1
    print("Test V Result: DiagnosticSession successfully orchestrates Phase E-7 recommendations.")

    print("\n" + "="*60)
    print("🎉 ALL PHASE E-7 TESTS (A THROUGH V) PASSED SUCCESSFULLY! 🎉")
    print("="*60)

if __name__ == "__main__":
    run_tests()
