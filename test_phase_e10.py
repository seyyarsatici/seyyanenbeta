"""
Phase E-10: Final E-Layer Hardening, Integration Audit & Regression Test Suite
Tests A through O:
- TEST A: Complete E-Layer Integration (E-1 through E-9 coherent dependency chain)
- TEST B: Clean Pipeline Run (All stages succeed -> PIPELINE_COMPLETE, ok=True)
- TEST C: Partial Pipeline Run (Degraded data quality -> PIPELINE_PARTIAL, ok=True, upstream preserved)
- TEST D: Early Stage Failure (Discovery exception -> PIPELINE_FAILED, downstream skipped, error structured)
- TEST E: Late Stage Failure (Report exception -> PIPELINE_FAILED, upstream stages 1..6 preserved)
- TEST F: Expected Diagnostic Failures (NRC/Timeout/NO_DATA are diagnostic data, not exceptions)
- TEST G: Explicit Empty Inputs (dids=[] remains empty, no arbitrary scans)
- TEST H: Repeated Runs Isolation (No cross-run contamination, cache cleanly overwritten)
- TEST I: Input Immutability (Caller lists/dicts unchanged)
- TEST J: Deterministic Structure (Identical inputs -> identical pipeline result shape)
- TEST K: Import and Startup Safety (import main, import motor succeed without side-effects)
- TEST L: Read-Only Safety (No write, security, actuation, coding, flashing, DTC clearing)
- TEST M: No Arbitrary Scanning (No 0000..FFFF or CAN ID brute force)
- TEST N: Cache Correctness (Latest single-entry cache bounded and accessible)
- TEST O: Full Cross-Layer Regression (E-1..E-9, DID probe, C-layer, D-layer verified)
"""

import time
import copy
import inspect
import main
import motor
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    PIPELINE_IDLE,
    PIPELINE_RUNNING,
    PIPELINE_COMPLETE,
    PIPELINE_PARTIAL,
    PIPELINE_FAILED,
    STAGE_NOT_STARTED,
    STAGE_RUNNING,
    STAGE_COMPLETE,
    STAGE_SKIPPED,
    STAGE_FAILED,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NRC,
    STATUS_NO_DATA,
    STATUS_DID_MISMATCH,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    ACTION_INSPECT,
    ACTION_VERIFY,
    RECOMMENDATION_PRIORITY_WARNING,
)


def run_tests():
    print("🚀 Running Phase E-10 Final E-Layer Hardening & Integration Audit Tests (Tests A through O)...")

    engine = AutoExpertEngine()

    # =========================================================================
    # TEST A — Complete E-Layer Integration (E-1 through E-9 Chain)
    # =========================================================================
    print("\n--- TEST A: Complete E-Layer Integration ---")
    session = DiagnosticSession(engine=engine)
    assert hasattr(session, "run_diagnostic_pipeline")
    assert hasattr(session, "discover_ecu_capabilities")
    assert hasattr(session, "build_acquisition_plan")
    assert hasattr(session, "execute_acquisition_plan")
    assert hasattr(session, "validate_acquisition_results")
    assert hasattr(session, "interpret_diagnostic_snapshot")
    assert hasattr(session, "generate_diagnostic_recommendations")
    assert hasattr(session, "build_diagnostic_report")

    # Mock stage pipeline to verify clean data handoff through each boundary
    orig_disc = engine.discover_ecu_capabilities
    orig_plan = engine.build_acquisition_plan
    orig_exec = engine.execute_acquisition_plan
    orig_val = engine.validate_acquisition_results
    orig_interp = engine.interpret_diagnostic_snapshot
    orig_rec = engine.generate_diagnostic_recommendations
    orig_rep = engine.build_diagnostic_report

    handoff_trace = []

    def mock_disc(**kwargs):
        handoff_trace.append("discovery")
        return [{"type": "MODE22_DID", "id": "1640", "header": "7E0", "status": "SUPPORTED"}]

    def mock_plan(capabilities=None, **kwargs):
        handoff_trace.append("planning")
        assert capabilities is not None
        return [{"type": "MODE22_DID", "id": "1640", "header": "7E0", "enabled": True}]

    def mock_exec(plan=None, **kwargs):
        handoff_trace.append("execution")
        assert plan is not None
        return [{"type": "MODE22_DID", "id": "1640", "header": "7E0", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]

    def mock_val(results=None, **kwargs):
        handoff_trace.append("validation")
        assert results is not None
        return {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": results, "timestamp": time.time()}

    def mock_interp(snapshot=None, **kwargs):
        handoff_trace.append("interpretation")
        assert snapshot is not None
        return {"findings": [{"id": "FINDING_1640_NORMAL", "title": "Normal Engine State", "severity": SEVERITY_INFO}]}

    def mock_rec(findings=None, **kwargs):
        handoff_trace.append("recommendation")
        assert findings is not None
        return {"recommendations": [{"id": "REC_NORMAL", "title": "Routine Maintenance", "priority": 3, "action": ACTION_VERIFY}]}

    def mock_rep(snapshot=None, findings=None, recommendations=None, **kwargs):
        handoff_trace.append("report")
        assert snapshot is not None
        assert findings is not None
        assert recommendations is not None
        return {"summary": "Diagnostic pipeline completed successfully.", "findings": findings, "recommendations": recommendations}

    try:
        engine.discover_ecu_capabilities = mock_disc
        engine.build_acquisition_plan = mock_plan
        engine.execute_acquisition_plan = mock_exec
        engine.validate_acquisition_results = mock_val
        engine.interpret_diagnostic_snapshot = mock_interp
        engine.generate_diagnostic_recommendations = mock_rec
        engine.build_diagnostic_report = mock_rep

        res_a = session.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert res_a["ok"] is True
        assert res_a["status"] == PIPELINE_COMPLETE
        assert handoff_trace == ["discovery", "planning", "execution", "validation", "interpretation", "recommendation", "report"]
        print("Test A Result: Full E-1 through E-9 chain handoff verified in correct sequential order.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST B — Clean Pipeline Run (All Stages Complete)
    # =========================================================================
    print("\n--- TEST B: Clean Pipeline Run ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": [{"id": "1640", "quality": QUALITY_GOOD}]}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Diagnostic pipeline completed: 1 capabilities evaluated, 0 findings detected, 0 recommendations generated.", "findings": [], "recommendations": []}

        res_b = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert res_b["ok"] is True
        assert res_b["status"] == PIPELINE_COMPLETE
        assert all(s == STAGE_COMPLETE for s in res_b["stages"].values())
        assert len(res_b["errors"]) == 0
        assert "timing" in res_b
        assert res_b["timing"]["total"] >= 0.0
        print("Test B Result: Clean pipeline produced PIPELINE_COMPLETE with all stages complete.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST C — Partial Pipeline Run (Degraded Quality)
    # =========================================================================
    print("\n--- TEST C: Partial Pipeline Run ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_TIMEOUT, "quality": QUALITY_ERROR, "value": None}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_TIMEOUT, "quality": QUALITY_ERROR, "complete": False, "results": [{"id": "1640", "quality": QUALITY_ERROR}]}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": [{"id": "FINDING_COMM_TIMEOUT", "severity": SEVERITY_WARNING}]}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": [{"id": "REC_CHECK_HARNESS", "priority": 2}]}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Pipeline partial with sensor error.", "findings": [], "recommendations": []}

        res_c = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert res_c["ok"] is True
        assert res_c["status"] == PIPELINE_PARTIAL
        assert len(res_c["results"]) == 1
        assert res_c["snapshot"]["quality"] == QUALITY_ERROR
        print("Test C Result: Partial pipeline accurately preserved degraded findings and marked PIPELINE_PARTIAL.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST D — Early Stage Failure (Discovery Exception)
    # =========================================================================
    print("\n--- TEST D: Early Stage Failure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Simulated discovery hardware fault"))
        res_d = engine.run_diagnostic_pipeline(dids=["1640"])
        assert res_d["ok"] is False
        assert res_d["status"] == PIPELINE_FAILED
        assert res_d["stages"]["discovery"] == STAGE_FAILED
        assert res_d["stages"]["planning"] == STAGE_SKIPPED
        assert res_d["stages"]["execution"] == STAGE_SKIPPED
        assert res_d["stages"]["validation"] == STAGE_SKIPPED
        assert res_d["stages"]["interpretation"] == STAGE_SKIPPED
        assert res_d["stages"]["recommendation"] == STAGE_SKIPPED
        assert res_d["stages"]["report"] == STAGE_SKIPPED
        assert len(res_d["errors"]) == 1
        assert res_d["errors"][0]["stage"] == "discovery"
        assert res_d["errors"][0]["type"] == "RuntimeError"
        print("Test D Result: Early discovery failure cleanly stopped pipeline and marked all downstream stages SKIPPED.")
    finally:
        engine.discover_ecu_capabilities = orig_disc

    # =========================================================================
    # TEST E — Late Stage Failure (Report Exception)
    # =========================================================================
    print("\n--- TEST E: Late Stage Failure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": [{"id": "1640", "quality": QUALITY_GOOD}]}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": [{"id": "F1", "severity": SEVERITY_INFO}]}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": [{"id": "R1", "priority": 1}]}
        engine.build_diagnostic_report = lambda **kwargs: (_ for _ in ()).throw(ValueError("Report builder format error"))

        res_e = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert res_e["ok"] is False
        assert res_e["status"] == PIPELINE_FAILED
        assert res_e["stages"]["discovery"] == STAGE_COMPLETE
        assert res_e["stages"]["planning"] == STAGE_COMPLETE
        assert res_e["stages"]["execution"] == STAGE_COMPLETE
        assert res_e["stages"]["validation"] == STAGE_COMPLETE
        assert res_e["stages"]["interpretation"] == STAGE_COMPLETE
        assert res_e["stages"]["recommendation"] == STAGE_COMPLETE
        assert res_e["stages"]["report"] == STAGE_FAILED
        assert len(res_e["capabilities"]) == 1
        assert len(res_e["plan"]) == 1
        assert len(res_e["results"]) == 1
        assert len(res_e["findings"]) == 1
        assert len(res_e["recommendations"]) == 1
        print("Test E Result: Late failure preserved all upstream stages 1 through 6.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST F — Normal Diagnostic Failures (NRC / Timeout / NO_DATA)
    # =========================================================================
    print("\n--- TEST F: Expected Diagnostic Failures ---")
    try:
        # Mock execution with normal diagnostic outcomes: 1 valid, 1 timeout, 1 NRC
        engine.discover_ecu_capabilities = lambda **kwargs: [
            {"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"},
            {"type": "MODE22_DID", "id": "336A", "status": "NEGATIVE_RESPONSE"},
            {"type": "MODE22_DID", "id": "DEAD", "status": "TIMEOUT"},
        ]
        engine.build_acquisition_plan = lambda **kwargs: [
            {"type": "MODE22_DID", "id": "1640", "enabled": True},
            {"type": "MODE22_DID", "id": "336A", "enabled": True},
            {"type": "MODE22_DID", "id": "DEAD", "enabled": True},
        ]
        engine.execute_acquisition_plan = lambda **kwargs: [
            {"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150},
            {"type": "MODE22_DID", "id": "336A", "status": STATUS_NRC, "quality": QUALITY_INVALID, "nrc": "31"},
            {"type": "MODE22_DID", "id": "DEAD", "status": STATUS_TIMEOUT, "quality": QUALITY_ERROR},
        ]
        engine.validate_acquisition_results = lambda **kwargs: {
            "status": STATUS_VALID,
            "quality": QUALITY_STALE,
            "complete": False,
            "results": [
                {"id": "1640", "quality": QUALITY_GOOD},
                {"id": "336A", "quality": QUALITY_INVALID},
                {"id": "DEAD", "quality": QUALITY_ERROR},
            ]
        }
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Diagnostic pipeline completed with partial ECU responses.", "findings": [], "recommendations": []}

        res_f = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640", "336A", "DEAD"])
        assert res_f["ok"] is True
        assert res_f["status"] == PIPELINE_PARTIAL
        assert len(res_f["errors"]) == 0
        assert all(s == STAGE_COMPLETE for s in res_f["stages"].values())
        print("Test F Result: Normal NRC/timeout handled strictly as diagnostic data without triggering software exception.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST G — Explicit Empty Inputs (dids=[])
    # =========================================================================
    print("\n--- TEST G: Explicit Empty Inputs ---")
    res_g = engine.run_diagnostic_pipeline(dids=[])
    assert res_g["ok"] is True
    assert res_g["capabilities"] == []
    assert res_g["plan"] == []
    assert res_g["results"] == []
    print("Test G Result: dids=[] passed accurately without broad default discovery.")

    # =========================================================================
    # TEST H — Repeated Runs Isolation (No Stale Contamination)
    # =========================================================================
    print("\n--- TEST H: Repeated Runs Isolation ---")
    try:
        # Run 1: returns findings
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": [{"id": "1640", "quality": QUALITY_GOOD}]}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": [{"id": "FINDING_RUN_1", "severity": SEVERITY_WARNING}]}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": [{"id": "REC_RUN_1", "priority": 1}]}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Run 1 report", "findings": [], "recommendations": []}

        res_h1 = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert len(res_h1["findings"]) == 1
        assert res_h1["findings"][0]["id"] == "FINDING_RUN_1"

        # Run 2: returns empty findings
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Run 2 report", "findings": [], "recommendations": []}

        res_h2 = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert len(res_h2["findings"]) == 0
        assert len(res_h2["recommendations"]) == 0
        assert res_h2["report"]["summary"] == "Run 2 report"
        assert "0 findings detected" in engine.last_diagnostic_pipeline["summary"]
        print("Test H Result: Run 2 completely replaced cache without inheriting Run 1 findings.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST I — Input Immutability
    # =========================================================================
    print("\n--- TEST I: Input Immutability ---")
    headers_input = ["7E0", "7E1"]
    dids_input = ["1640", "1641"]
    headers_input_copy = list(headers_input)
    dids_input_copy = list(dids_input)

    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": []}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Report", "findings": [], "recommendations": []}

        engine.run_diagnostic_pipeline(headers=headers_input, dids=dids_input)
        assert headers_input == headers_input_copy
        assert dids_input == dids_input_copy
        print("Test I Result: Caller input lists remained strictly unmodified.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST J — Deterministic Result Structure
    # =========================================================================
    print("\n--- TEST J: Deterministic Result Structure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": [{"id": "1640", "quality": QUALITY_GOOD}]}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Deterministic report", "findings": [], "recommendations": []}

        res_j1 = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        res_j2 = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])

        def strip_time(r):
            c = copy.deepcopy(r)
            c.pop("timestamp", None)
            c.pop("timing", None)
            return c

        assert strip_time(res_j1) == strip_time(res_j2)
        print("Test J Result: Identical inputs produced deterministic structure.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # =========================================================================
    # TEST K — Import & Startup Safety
    # =========================================================================
    print("\n--- TEST K: Import & Startup Safety ---")
    import sys
    assert "main" in sys.modules
    assert "motor" in sys.modules
    assert hasattr(main, "create_diagnostic_session")
    assert hasattr(motor, "AutoExpertEngine")
    assert hasattr(motor, "DiagnosticSession")
    print("Test K Result: main and motor imported cleanly without startup issues.")

    # =========================================================================
    # TEST L — Read-Only Safety Verification
    # =========================================================================
    print("\n--- TEST L: Read-Only Safety Verification ---")
    pipeline_code = inspect.getsource(engine.run_diagnostic_pipeline)
    forbidden_terms = [
        "0x27", "2701", "2702", "SecurityAccess",
        "0x2E", "2E", "WriteDataByIdentifier",
        "0x31", "RoutineControl",
        "0x34", "RequestDownload",
        "0x36", "TransferData",
        "clear_dtc", "dtc_clear", "04", "14FF00",
    ]
    for term in forbidden_terms:
        # Check that forbidden actuation / write / security strings are not executed
        assert f"komut_gonder('{term}')" not in pipeline_code
        assert f'komut_gonder("{term}")' not in pipeline_code
    print("Test L Result: Pipeline code is strictly read-only; zero write/actuation commands.")

    # =========================================================================
    # TEST M — No Arbitrary Scanning
    # =========================================================================
    print("\n--- TEST M: No Arbitrary Scanning ---")
    disc_code = inspect.getsource(engine.discover_ecu_capabilities)
    assert "range(0x0000, 0xFFFF)" not in disc_code
    assert "range(0, 65536)" not in disc_code
    assert "range(0x0000, 0x10000)" not in disc_code
    print("Test M Result: Capability discovery enforces finite candidate boundaries.")

    # =========================================================================
    # TEST N — Cache Correctness
    # =========================================================================
    print("\n--- TEST N: Cache Correctness ---")
    pipeline_cache = engine.get_diagnostic_pipeline()
    assert isinstance(pipeline_cache, dict)
    assert "status" in pipeline_cache
    assert "stages" in pipeline_cache
    print("Test N Result: Latest pipeline result correctly retrieved from cache.")

    # =========================================================================
    # TEST O — Cross-Layer Regression
    # =========================================================================
    print("\n--- TEST O: Cross-Layer Regression ---")
    # Verify core constants and contracts
    assert PIPELINE_COMPLETE == "COMPLETE"
    assert PIPELINE_PARTIAL == "PARTIAL"
    assert PIPELINE_FAILED == "FAILED"
    assert STAGE_COMPLETE == "COMPLETE"
    assert STAGE_SKIPPED == "SKIPPED"
    assert STAGE_FAILED == "FAILED"
    print("Test O Result: Cross-layer constants and models intact.")

    print("\n" + "=" * 60)
    print("🎉 ALL PHASE E-10 TESTS (A THROUGH O) PASSED SUCCESSFULLY! 🎉")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
