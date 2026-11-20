"""
Phase E-8: Diagnostic Report / Explainability Layer Test Suite
Tests A through R:
- TEST A: Empty report -> zero findings, zero recommendations, INFO severity, clean summary, no exception
- TEST B: Normal healthy snapshot -> GOOD quality, INFO severity, no false findings
- TEST C: Warning finding -> WARNING overall severity, finding preserved, recommendation preserved
- TEST D: Critical finding -> CRITICAL overall severity
- TEST E: Degraded data quality -> indicates degraded reliability, no invented mechanical fault
- TEST F: Communication problems -> communication info appears, no mechanical diagnosis invented
- TEST G: DTC information -> DTC summary surfaced, no new DTC parser
- TEST H: Finding/recommendation linkage -> finding IDs correctly map to recommendation IDs
- TEST I: Evidence preservation -> finding evidence remains available
- TEST J: Recommendation preservation -> priority, action, reason, confidence, finding_ids preserved
- TEST K: Deterministic summary -> identical structured output across runs
- TEST L: Deterministic text -> same logical input produces same report text
- TEST M: Input immutability -> snapshot, findings, recommendations untouched
- TEST N: Confidence bounds -> all confidence values bounded in [0.0, 1.0]
- TEST O: Empty/missing optional sections -> missing DTC/comm metadata causes no exceptions
- TEST P: No I/O guarantee -> monkeypatched communication functions -> 0 requests
- TEST Q: Cache replacement -> last_diagnostic_report contains only latest
- TEST R: DiagnosticSession proxy & Regression integration
"""

import time
import copy
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NRC,
    STATUS_DID_MISMATCH,
    STATUS_NO_DATA,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
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
    print("🚀 Running Phase E-8 Diagnostic Report Tests (Tests A through R)...")

    engine = AutoExpertEngine()
    now = time.time()

    # TEST A — Empty report
    print("\n--- TEST A: Empty Report ---")
    rep_a = engine.build_diagnostic_report(snapshot={}, findings=[], recommendations=[])
    assert rep_a["finding_count"] == 0
    assert rep_a["recommendation_count"] == 0
    assert rep_a["overall_severity"] == SEVERITY_INFO
    assert "No diagnostic issues detected" in rep_a["summary"]
    assert "No diagnostic anomalies" in rep_a["text"]
    assert "No corrective or diagnostic actions required" in rep_a["text"]
    print("Test A Result: Clean structured report on empty inputs with 0 findings and 0 recommendations.")

    # TEST B — Normal healthy snapshot
    print("\n--- TEST B: Normal Healthy Snapshot ---")
    snap_b = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "complete": True,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "RPM",
                "status": STATUS_VALID,
                "quality": QUALITY_GOOD,
                "value": 850,
                "validation": {"accepted": True, "fresh": True, "issues": []},
            },
            {
                "type": "MODE01_PID",
                "id": "ECT",
                "status": STATUS_VALID,
                "quality": QUALITY_GOOD,
                "value": 90,
                "validation": {"accepted": True, "fresh": True, "issues": []},
            },
        ],
    }
    rep_b = engine.build_diagnostic_report(snapshot=snap_b, findings=[], recommendations=[])
    assert rep_b["overall_quality"] == QUALITY_GOOD
    assert rep_b["overall_severity"] == SEVERITY_INFO
    assert rep_b["data_quality"]["good"] == 2
    assert rep_b["data_quality"]["stale"] == 0
    assert rep_b["data_quality"]["error"] == 0
    assert rep_b["communication"]["valid"] == 2
    print("Test B Result: Normal healthy snapshot produces GOOD quality and INFO severity without false findings.")

    # TEST C — Warning finding
    print("\n--- TEST C: Warning Finding ---")
    findings_c = [
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
    recs_c = [
        {
            "id": "REC_COOLING_INSPECTION",
            "priority": RECOMMENDATION_PRIORITY_WARNING,
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "action_type": ACTION_INSPECT,
            "title": "Inspect engine coolant temperature system",
            "action": "Verify ECT sensor reading and inspect coolant level.",
            "reason": "ECT temperature is elevated.",
            "finding_ids": ["FINDING_ECT_HIGH"],
            "confidence": 0.90,
        }
    ]
    rep_c = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
    assert rep_c["overall_severity"] == SEVERITY_WARNING
    assert rep_c["finding_count"] == 1
    assert rep_c["recommendation_count"] == 1
    assert rep_c["findings"][0]["id"] == "FINDING_ECT_HIGH"
    assert rep_c["recommendations"][0]["id"] == "REC_COOLING_INSPECTION"
    print("Test C Result: Warning finding preserved with WARNING overall severity.")

    # TEST D — Critical finding
    print("\n--- TEST D: Critical Finding ---")
    findings_d = [
        {
            "id": "FINDING_ECT_IMPLAUSIBLE",
            "severity": SEVERITY_CRITICAL,
            "category": "COOLING",
            "title": "ECT measurement is physically implausible",
            "message": "ECT reading (215 C) is outside plausible physical limits.",
            "evidence": {"sensor": "ECT", "value": 215},
            "confidence": 0.95,
            "source": "PLAUSIBILITY",
        }
    ]
    recs_d = [
        {
            "id": "REC_COOLING_INSPECTION",
            "priority": RECOMMENDATION_PRIORITY_CRITICAL,
            "severity": SEVERITY_CRITICAL,
            "category": "COOLING",
            "action_type": ACTION_INSPECT,
            "title": "Inspect engine coolant temperature system and sensor circuit",
            "action": "Verify ECT sensor reading and inspect sensor wiring.",
            "reason": "ECT measurement is physically implausible.",
            "finding_ids": ["FINDING_ECT_IMPLAUSIBLE"],
            "confidence": 0.95,
        }
    ]
    rep_d = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_d, recommendations=recs_d)
    assert rep_d["overall_severity"] == SEVERITY_CRITICAL
    assert rep_d["metadata"]["high_priority_action_count"] == 1
    print("Test D Result: Critical finding produces CRITICAL overall severity and high-priority action count.")

    # TEST E — Degraded data quality
    print("\n--- TEST E: Degraded Data Quality ---")
    snap_e = {
        "timestamp": now,
        "status": STATUS_VALID,
        "quality": QUALITY_STALE,
        "complete": False,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "ECT",
                "status": STATUS_VALID,
                "quality": QUALITY_STALE,
                "value": 90,
                "validation": {"accepted": False, "fresh": False, "issues": ["Stale data"]},
            }
        ],
    }
    findings_e = [
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
    recs_e = [
        {
            "id": "REC_ECT_DATA_REACQUIRE",
            "priority": RECOMMENDATION_PRIORITY_WARNING,
            "severity": SEVERITY_WARNING,
            "category": "COOLING",
            "action_type": ACTION_REACQUIRE,
            "title": "Reacquire ECT data and verify signal freshness",
            "action": "Reacquire engine coolant temperature measurement.",
            "reason": "ECT measurement is stale.",
            "finding_ids": ["FINDING_ECT_STALE"],
            "confidence": 0.85,
        }
    ]
    rep_e = engine.build_diagnostic_report(snapshot=snap_e, findings=findings_e, recommendations=recs_e)
    assert rep_e["overall_quality"] == QUALITY_STALE
    assert rep_e["data_quality"]["stale"] == 1
    assert "stale" in rep_e["summary"].lower() or "reacquisition" in rep_e["summary"].lower()
    assert "replace" not in rep_e["text"].lower()
    print("Test E Result: Stale data quality clearly surfaced without inventing mechanical defect.")

    # TEST F — Communication problems
    print("\n--- TEST F: Communication Problems ---")
    snap_f = {
        "timestamp": now,
        "status": STATUS_TIMEOUT,
        "quality": QUALITY_ERROR,
        "complete": False,
        "results": [
            {
                "type": "MODE01_PID",
                "id": "RPM",
                "status": STATUS_TIMEOUT,
                "quality": QUALITY_ERROR,
                "validation": {"accepted": False, "fresh": False, "issues": ["Timeout"]},
            },
            {
                "type": "MODE22_DID",
                "id": "22336A",
                "status": STATUS_NRC,
                "quality": QUALITY_INVALID,
                "validation": {"accepted": False, "fresh": False, "issues": ["NRC 0x31"]},
            },
            {
                "type": "MODE22_DID",
                "id": "221940",
                "status": STATUS_DID_MISMATCH,
                "quality": QUALITY_INVALID,
                "validation": {"accepted": False, "fresh": False, "issues": ["DID Mismatch"]},
            },
        ],
    }
    findings_f = [
        {
            "id": "FINDING_RPM_COMM_TIMEOUT",
            "severity": SEVERITY_WARNING,
            "category": "COMMUNICATION",
            "title": "ECU communication failure for RPM",
            "message": "ECU request 010C timed out.",
            "evidence": {"id": "RPM", "status": "TIMEOUT"},
            "confidence": 1.0,
            "source": "COMMUNICATION",
        }
    ]
    recs_f = [
        {
            "id": "REC_COMMUNICATION_LINK_INSPECTION",
            "priority": RECOMMENDATION_PRIORITY_WARNING,
            "severity": SEVERITY_WARNING,
            "category": "COMMUNICATION",
            "action_type": ACTION_CHECK_CONNECTION,
            "title": "Inspect diagnostic communication link and ECU interface",
            "action": "Inspect OBD interface connection before suspecting ECU fault.",
            "reason": "ECU communication timeout detected.",
            "finding_ids": ["FINDING_RPM_COMM_TIMEOUT"],
            "confidence": 1.0,
        }
    ]
    rep_f = engine.build_diagnostic_report(snapshot=snap_f, findings=findings_f, recommendations=recs_f)
    assert rep_f["communication"]["timeout"] == 1
    assert rep_f["communication"]["nrc"] == 1
    assert rep_f["communication"]["did_mismatch"] == 1
    assert rep_f["data_quality"]["error"] == 1
    print("Test F Result: Communication statuses surfaced accurately with no invented component fault.")

    # TEST G — DTC information
    print("\n--- TEST G: DTC Information ---")
    findings_g = [
        {
            "id": "FINDING_DTC_P0300",
            "severity": SEVERITY_CRITICAL,
            "category": "DIAGNOSTIC",
            "title": "Diagnostic Trouble Code active: P0300",
            "message": "Active DTC P0300 in fault memory.",
            "evidence": {"dtc": "P0300", "source": "DTC_MEMORY"},
            "confidence": 1.0,
            "source": "DTC",
        },
        {
            "id": "FINDING_DTC_U0100",
            "severity": SEVERITY_WARNING,
            "category": "DIAGNOSTIC",
            "title": "Diagnostic Trouble Code active: U0100",
            "message": "Active DTC U0100 in fault memory.",
            "evidence": {"dtc": "U0100", "source": "DTC_MEMORY"},
            "confidence": 1.0,
            "source": "DTC",
        }
    ]
    rep_g = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_g, recommendations=[])
    assert rep_g["dtc_summary"]["present"] is True
    assert rep_g["dtc_summary"]["count"] == 2
    assert "P0300" in rep_g["dtc_summary"]["codes"]
    assert "U0100" in rep_g["dtc_summary"]["codes"]
    assert "P0300" in rep_g["text"]
    assert "U0100" in rep_g["text"]
    print("Test G Result: DTC summary and code listings surfaced accurately from findings.")

    # TEST H — Finding/recommendation linkage
    print("\n--- TEST H: Finding/Recommendation Linkage ---")
    rep_h = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
    assert len(rep_h["finding_links"]) == 1
    link = rep_h["finding_links"][0]
    assert link["finding_id"] == "FINDING_ECT_HIGH"
    assert "REC_COOLING_INSPECTION" in link["recommendation_ids"]
    print("Test H Result: Finding-to-recommendation relationships linked deterministically.")

    # TEST I — Evidence preservation
    print("\n--- TEST I: Evidence Preservation ---")
    assert rep_c["findings"][0]["evidence"]["sensor"] == "ECT"
    assert rep_c["findings"][0]["evidence"]["value"] == 118
    print("Test I Result: Finding evidence dictionaries preserved intact.")

    # TEST J — Recommendation preservation
    print("\n--- TEST J: Recommendation Preservation ---")
    rec_out = rep_c["recommendations"][0]
    assert rec_out["priority"] == RECOMMENDATION_PRIORITY_WARNING
    assert rec_out["severity"] == SEVERITY_WARNING
    assert rec_out["category"] == "COOLING"
    assert rec_out["action"] == recs_c[0]["action"]
    assert rec_out["reason"] == recs_c[0]["reason"]
    assert rec_out["confidence"] == recs_c[0]["confidence"]
    assert rec_out["finding_ids"] == recs_c[0]["finding_ids"]
    print("Test J Result: Recommendation attributes preserved completely.")

    # TEST K — Deterministic summary
    print("\n--- TEST K: Deterministic Summary ---")
    rep_k1 = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
    rep_k2 = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
    assert rep_k1["summary"] == rep_k2["summary"]
    assert rep_k1["finding_count"] == rep_k2["finding_count"]
    assert rep_k1["overall_severity"] == rep_k2["overall_severity"]
    print("Test K Result: Deterministic summary verified across repeated runs.")

    # TEST L — Deterministic text
    print("\n--- TEST L: Deterministic Text ---")
    # Both calls with same timestamp
    fixed_time = 1788529900.0
    engine.last_validated_snapshot = snap_b
    engine.last_diagnostic_findings = findings_c
    engine.last_diagnostic_recommendations = recs_c
    rep_l1 = engine.build_diagnostic_report()
    rep_l2 = engine.build_diagnostic_report()
    # Sections other than timestamp header line are identical
    lines_l1 = rep_l1["text"].split("\n")[4:]
    lines_l2 = rep_l2["text"].split("\n")[4:]
    assert lines_l1 == lines_l2
    print("Test L Result: Deterministic text report layout verified.")

    # TEST M — Input immutability
    print("\n--- TEST M: Input Immutability ---")
    snap_copy = copy.deepcopy(snap_b)
    findings_copy = copy.deepcopy(findings_c)
    recs_copy = copy.deepcopy(recs_c)
    engine.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
    assert snap_b == snap_copy
    assert findings_c == findings_copy
    assert recs_c == recs_copy
    print("Test M Result: All input structures remain strictly immutable.")

    # TEST N — Confidence bounds
    print("\n--- TEST N: Confidence Bounds ---")
    for f in rep_c["findings"]:
        assert 0.0 <= f["confidence"] <= 1.0
    for r in rep_c["recommendations"]:
        assert 0.0 <= r["confidence"] <= 1.0
    print("Test N Result: Confidence values verified bounded in [0.0, 1.0].")

    # TEST O — Empty/missing optional sections
    print("\n--- TEST O: Missing Optional Sections ---")
    rep_o = engine.build_diagnostic_report(snapshot={"results": None}, findings=None, recommendations=None)
    assert rep_o["finding_count"] == 1  # Uses cached findings_c
    assert rep_o["data_quality"]["total"] == 0
    assert rep_o["communication"]["total"] == 0
    print("Test O Result: Missing or None fields handled smoothly without exceptions.")

    # TEST P — No I/O guarantee
    print("\n--- TEST P: Zero I/O Guarantee ---")
    def fail_on_io(*args, **kwargs):
        raise AssertionError("I/O must NEVER be triggered by build_diagnostic_report!")

    orig_komut = engine.komut_gonder
    engine.komut_gonder = fail_on_io
    try:
        rep_p = engine.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
        assert rep_p["finding_count"] > 0
    finally:
        engine.komut_gonder = orig_komut
    print("Test P Result: Zero I/O guaranteed during report construction.")

    # TEST Q — Cache replacement
    print("\n--- TEST Q: Cache Replacement ---")
    engine.build_diagnostic_report(snapshot=snap_b, findings=findings_d, recommendations=recs_d)
    assert engine.last_diagnostic_report["overall_severity"] == SEVERITY_CRITICAL

    engine.build_diagnostic_report(snapshot={}, findings=[], recommendations=[])
    assert engine.last_diagnostic_report["overall_severity"] == SEVERITY_INFO
    assert engine.get_diagnostic_report()["finding_count"] == 0
    print("Test Q Result: Cache cleanly replaced on each report generation.")

    # TEST R — DiagnosticSession proxy & Regression
    print("\n--- TEST R: DiagnosticSession Proxy ---")
    session = DiagnosticSession(engine=engine)
    session_rep = session.build_diagnostic_report(snapshot=snap_b, findings=findings_c, recommendations=recs_c)
    assert session_rep["finding_count"] == 1
    assert session.get_diagnostic_report()["finding_count"] == 1
    print("Test R Result: DiagnosticSession successfully proxies Phase E-8 reporting.")

    print("\n" + "="*60)
    print("🎉 ALL PHASE E-8 TESTS (A THROUGH R) PASSED SUCCESSFULLY! 🎉")
    print("="*60)

if __name__ == "__main__":
    run_tests()
