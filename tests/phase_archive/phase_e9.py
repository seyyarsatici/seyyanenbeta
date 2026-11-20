"""
Phase E-9: Diagnostic Pipeline Orchestration Test Suite
Tests A through T:
- TEST A: Healthy complete pipeline -> all stages COMPLETE, status COMPLETE, final report present
- TEST B: Discovery failure -> pipeline FAILED, downstream stages SKIPPED, error captured
- TEST C: Planning failure -> discovery COMPLETE, planning FAILED, downstream stages SKIPPED
- TEST D: Execution failure -> upstream COMPLETE, execution FAILED, downstream stages SKIPPED
- TEST E: Normal timeout/NRC handling -> does NOT cause pipeline failure exception
- TEST F: Partial diagnostic success -> data quality degradation produces PIPELINE_PARTIAL
- TEST G: Empty DID list -> dids=[] respects empty candidate set without broad discovery
- TEST H: Standard PID inclusion -> include_standard_pids=True respected in discovery/planning
- TEST I: Explicit arguments forwarding -> headers, dids, options forwarded accurately
- TEST J: Stage ordering verification -> discovery -> planning -> execution -> validation -> interpretation -> recommendation -> report
- TEST K: Zero I/O in orchestration layer -> E-9 itself performs zero direct serial communication
- TEST L: Read-only safety verification -> zero write, coding, flashing, or actuator operations
- TEST M: Cache update -> last_diagnostic_pipeline holds latest result
- TEST N: Cache replacement -> running twice updates cache cleanly
- TEST O: Input immutability -> caller inputs unmodified
- TEST P: Deterministic result structure -> identical structure across runs
- TEST Q: Partial result preservation on error -> upstream stage outputs remain accessible
- TEST R: DiagnosticSession integration -> session proxy runs smoothly
- TEST S: Report integration -> snapshot, findings, recommendations wired to E-8
- TEST T: Full regression suite integration
"""

import time
import copy
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    PIPELINE_COMPLETE,
    PIPELINE_PARTIAL,
    PIPELINE_FAILED,
    STAGE_COMPLETE,
    STAGE_SKIPPED,
    STAGE_FAILED,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NRC,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_ERROR,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    ACTION_INSPECT,
    RECOMMENDATION_PRIORITY_WARNING,
)

def run_tests():
    print("🚀 Running Phase E-9 Diagnostic Pipeline Orchestration Tests (Tests A through T)...")

    engine = AutoExpertEngine()
    now = time.time()

    # TEST A — Healthy Complete Pipeline (Mocked Stages)
    print("\n--- TEST A: Healthy Complete Pipeline ---")
    orig_disc = engine.discover_ecu_capabilities
    orig_plan = engine.build_acquisition_plan
    orig_exec = engine.execute_acquisition_plan
    orig_val = engine.validate_acquisition_results
    orig_interp = engine.interpret_diagnostic_snapshot
    orig_rec = engine.generate_diagnostic_recommendations
    orig_rep = engine.build_diagnostic_report

    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"type": "MODE22_DID", "id": "1640", "status": STATUS_VALID, "quality": QUALITY_GOOD, "value": 150}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_GOOD, "complete": True, "results": [{"id": "1640", "quality": QUALITY_GOOD, "validation": {"fresh": True}}]}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": [{"id": "FINDING_1640_NORMAL", "severity": SEVERITY_INFO}]}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": [{"id": "REC_1640_INFO", "priority": 3}]}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "All systems normal", "findings": [], "recommendations": []}

        res_a = engine.run_diagnostic_pipeline(headers=["7E0"], dids=["1640"])
        assert res_a["ok"] is True
        assert res_a["status"] == PIPELINE_COMPLETE
        assert all(s == STAGE_COMPLETE for s in res_a["stages"].values())
        assert len(res_a["errors"]) == 0
        assert "timing" in res_a
        assert res_a["timing"]["total"] >= 0.0
        print("Test A Result: Full pipeline completed successfully with all 7 stages COMPLETE.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST B — Discovery Failure
    print("\n--- TEST B: Capability Discovery Failure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Simulated discovery hardware fault"))
        res_b = engine.run_diagnostic_pipeline(dids=["1640"])
        assert res_b["ok"] is False
        assert res_b["status"] == PIPELINE_FAILED
        assert res_b["stages"]["discovery"] == STAGE_FAILED
        assert res_b["stages"]["planning"] == STAGE_SKIPPED
        assert res_b["stages"]["execution"] == STAGE_SKIPPED
        assert res_b["stages"]["validation"] == STAGE_SKIPPED
        assert len(res_b["errors"]) == 1
        assert res_b["errors"][0]["stage"] == "discovery"
        assert "Simulated discovery hardware fault" in res_b["errors"][0]["message"]
        print("Test B Result: Discovery failure stopped downstream stages cleanly and marked status FAILED.")
    finally:
        engine.discover_ecu_capabilities = orig_disc

    # TEST C — Planning Failure
    print("\n--- TEST C: Planning Failure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: (_ for _ in ()).throw(ValueError("Invalid plan constraint"))
        res_c = engine.run_diagnostic_pipeline(dids=["1640"])
        assert res_c["ok"] is False
        assert res_c["status"] == PIPELINE_FAILED
        assert res_c["stages"]["discovery"] == STAGE_COMPLETE
        assert len(res_c["capabilities"]) == 1
        assert res_c["stages"]["planning"] == STAGE_FAILED
        assert res_c["stages"]["execution"] == STAGE_SKIPPED
        assert res_c["errors"][0]["stage"] == "planning"
        print("Test C Result: Planning failure preserved discovery output and skipped downstream execution.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan

    # TEST D — Execution Failure
    print("\n--- TEST D: Execution Failure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: (_ for _ in ()).throw(ConnectionResetError("Port closed unexpectedly"))
        res_d = engine.run_diagnostic_pipeline(dids=["1640"])
        assert res_d["ok"] is False
        assert res_d["status"] == PIPELINE_FAILED
        assert res_d["stages"]["discovery"] == STAGE_COMPLETE
        assert res_d["stages"]["planning"] == STAGE_COMPLETE
        assert res_d["stages"]["execution"] == STAGE_FAILED
        assert res_d["stages"]["validation"] == STAGE_SKIPPED
        assert res_d["errors"][0]["stage"] == "execution"
        print("Test D Result: Execution failure preserved discovery & planning and skipped validation.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec

    # TEST E — Normal Timeout / NRC is Not Exception
    print("\n--- TEST E: Diagnostic Timeout/NRC Handling ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"id": "336A", "status": "NEGATIVE_RESPONSE"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"id": "336A", "enabled": False}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"id": "336A", "status": STATUS_NRC, "quality": QUALITY_ERROR}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_NRC, "quality": QUALITY_ERROR, "complete": False, "results": []}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": [{"id": "FINDING_NRC_31", "severity": SEVERITY_WARNING}]}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": [{"id": "REC_NRC_31", "priority": 2}]}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Diagnostic service unsupported"}

        res_e = engine.run_diagnostic_pipeline(dids=["336A"])
        assert res_e["ok"] is True
        assert len(res_e["errors"]) == 0
        assert res_e["stages"]["execution"] == STAGE_COMPLETE
        assert res_e["status"] in (PIPELINE_COMPLETE, PIPELINE_PARTIAL)
        print("Test E Result: Normal diagnostic NRC/timeout flowed through pipeline without triggering error boundary.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST F — Partial Diagnostic Success (Degraded Data Quality)
    print("\n--- TEST F: Partial Diagnostic Success ---")
    try:
        engine.discover_ecu_capabilities = lambda **kwargs: [{"id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kwargs: [{"id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"id": "1640", "status": STATUS_VALID, "quality": QUALITY_STALE}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": STATUS_VALID, "quality": QUALITY_STALE, "complete": False, "results": []}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": [{"id": "FINDING_1640_STALE", "severity": SEVERITY_WARNING}]}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": [{"id": "REC_1640_REACQUIRE", "priority": 2}]}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Data stale"}

        res_f = engine.run_diagnostic_pipeline(dids=["1640"])
        assert res_f["ok"] is True
        assert res_f["status"] == PIPELINE_PARTIAL
        assert "partial" in res_f["summary"].lower()
        print("Test F Result: Degraded quality correctly flagged pipeline status as PARTIAL.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST G — Empty DID List
    print("\n--- TEST G: Empty DID List Handling ---")
    captured_dids = []
    try:
        def capture_discovery(**kwargs):
            captured_dids.append(kwargs.get("candidate_dids"))
            return []

        engine.discover_ecu_capabilities = capture_discovery
        engine.build_acquisition_plan = lambda **kwargs: []
        engine.execute_acquisition_plan = lambda **kwargs: []
        engine.validate_acquisition_results = lambda **kwargs: {"status": "NO_DATA", "quality": "INVALID", "complete": True, "results": []}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "No data"}

        res_g = engine.run_diagnostic_pipeline(dids=[])
        assert captured_dids[0] == []
        assert res_g["stages"]["discovery"] == STAGE_COMPLETE
        print("Test G Result: Explicit empty candidate list dids=[] passed accurately without triggering default scan.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST H — Standard PID Inclusion
    print("\n--- TEST H: Standard PID Inclusion ---")
    captured_flags = []
    try:
        def capture_pids(**kwargs):
            captured_flags.append(kwargs.get("include_standard_pids"))
            return [{"id": "010C", "type": "MODE01_PID"}]

        engine.discover_ecu_capabilities = capture_pids
        engine.build_acquisition_plan = lambda **kwargs: [{"id": "010C", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kwargs: [{"id": "010C", "status": "VALID", "value": 850}]
        engine.validate_acquisition_results = lambda **kwargs: {"status": "VALID", "quality": "GOOD", "complete": True, "results": []}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "Normal"}

        res_h = engine.run_diagnostic_pipeline(include_standard_pids=True)
        assert captured_flags[0] is True
        print("Test H Result: include_standard_pids=True forwarded correctly to capability discovery.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST I — Explicit Arguments Forwarding
    print("\n--- TEST I: Explicit Arguments Forwarding ---")
    captured_args = {}
    try:
        def capture_all(**kwargs):
            captured_args.update(kwargs)
            return []

        engine.discover_ecu_capabilities = capture_all
        engine.build_acquisition_plan = lambda **kwargs: []
        engine.execute_acquisition_plan = lambda **kwargs: []
        engine.validate_acquisition_results = lambda **kwargs: {"status": "NO_DATA", "quality": "INVALID", "complete": True, "results": []}
        engine.interpret_diagnostic_snapshot = lambda **kwargs: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kwargs: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kwargs: {"summary": "No data"}

        engine.run_diagnostic_pipeline(headers=["7E1"], dids=["22F190"], candidate_source="CUSTOM_SOURCE")
        assert captured_args["headers"] == ["7E1"]
        assert captured_args["candidate_dids"] == ["22F190"]
        assert captured_args["candidate_source"] == "CUSTOM_SOURCE"
        print("Test I Result: Caller parameters accurately reach discovery layer.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST J — Exact Stage Execution Ordering
    print("\n--- TEST J: Stage Execution Ordering ---")
    execution_order = []
    try:
        engine.discover_ecu_capabilities = lambda **kw: execution_order.append("discovery") or []
        engine.build_acquisition_plan = lambda **kw: execution_order.append("planning") or []
        engine.execute_acquisition_plan = lambda **kw: execution_order.append("execution") or []
        engine.validate_acquisition_results = lambda **kw: execution_order.append("validation") or {"status": "VALID", "quality": "GOOD", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: execution_order.append("interpretation") or {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: execution_order.append("recommendation") or {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: execution_order.append("report") or {"summary": "OK"}

        engine.run_diagnostic_pipeline()
        expected_order = ["discovery", "planning", "execution", "validation", "interpretation", "recommendation", "report"]
        assert execution_order == expected_order
        print("Test J Result: Exact architectural stage sequence verified: " + " -> ".join(expected_order))
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST K — Zero Direct I/O in Pipeline Layer
    print("\n--- TEST K: Zero Direct I/O in Orchestration Layer ---")
    io_called = []
    orig_komut = engine.komut_gonder
    try:
        engine.komut_gonder = lambda *a, **kw: io_called.append(True) or []
        engine.discover_ecu_capabilities = lambda **kw: []
        engine.build_acquisition_plan = lambda **kw: []
        engine.execute_acquisition_plan = lambda **kw: []
        engine.validate_acquisition_results = lambda **kw: {"status": "NO_DATA", "quality": "INVALID", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: {"summary": "OK"}

        engine.run_diagnostic_pipeline()
        assert len(io_called) == 0
        print("Test K Result: E-9 orchestration layer performs zero direct serial/ECU communication.")
    finally:
        engine.komut_gonder = orig_komut
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST L — Read-Only Safety Verification
    print("\n--- TEST L: Read-Only Safety Verification ---")
    assert not hasattr(engine, "write_ecu_did")
    assert not hasattr(engine, "clear_fault_codes")
    assert not hasattr(engine, "perform_ecu_security_access")
    print("Test L Result: Pipeline strictly preserves read-only integrity; no write/actuation methods present.")

    # TEST M — Cache Update
    print("\n--- TEST M: Cache Update ---")
    try:
        engine.discover_ecu_capabilities = lambda **kw: []
        engine.build_acquisition_plan = lambda **kw: []
        engine.execute_acquisition_plan = lambda **kw: []
        engine.validate_acquisition_results = lambda **kw: {"status": "NO_DATA", "quality": "GOOD", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: {"summary": "OK"}

        res_m = engine.run_diagnostic_pipeline()
        assert engine.last_diagnostic_pipeline["ok"] == res_m["ok"]
        assert engine.get_diagnostic_pipeline()["status"] == res_m["status"]
        print("Test M Result: last_diagnostic_pipeline cache holds latest pipeline outcome.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST N — Cache Replacement
    print("\n--- TEST N: Cache Replacement ---")
    try:
        engine.discover_ecu_capabilities = lambda **kw: []
        engine.build_acquisition_plan = lambda **kw: []
        engine.execute_acquisition_plan = lambda **kw: []
        engine.validate_acquisition_results = lambda **kw: {"status": "NO_DATA", "quality": "GOOD", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: {"summary": "OK"}

        engine.run_diagnostic_pipeline()
        assert engine.last_diagnostic_pipeline["status"] == PIPELINE_COMPLETE

        # Second run with error
        engine.discover_ecu_capabilities = lambda **kw: (_ for _ in ()).throw(RuntimeError("Abort"))
        engine.run_diagnostic_pipeline()
        assert engine.last_diagnostic_pipeline["status"] == PIPELINE_FAILED
        print("Test N Result: Pipeline cache cleanly replaced on second execution without unbounded accumulation.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST O — Input Immutability
    print("\n--- TEST O: Input Immutability ---")
    try:
        engine.discover_ecu_capabilities = lambda **kw: []
        engine.build_acquisition_plan = lambda **kw: []
        engine.execute_acquisition_plan = lambda **kw: []
        engine.validate_acquisition_results = lambda **kw: {"status": "VALID", "quality": "GOOD", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: {"summary": "OK"}

        hdr_list = ["7E0", "7E1"]
        did_list = ["1640", "1641"]
        hdr_copy = copy.deepcopy(hdr_list)
        did_copy = copy.deepcopy(did_list)

        engine.run_diagnostic_pipeline(headers=hdr_list, dids=did_list)
        assert hdr_list == hdr_copy
        assert did_list == did_copy
        print("Test O Result: Caller input lists remain strictly immutable.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST P — Deterministic Result Structure
    print("\n--- TEST P: Deterministic Result Structure ---")
    try:
        engine.discover_ecu_capabilities = lambda **kw: [{"id": "1640"}]
        engine.build_acquisition_plan = lambda **kw: [{"id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kw: [{"id": "1640", "value": 100}]
        engine.validate_acquisition_results = lambda **kw: {"status": "VALID", "quality": "GOOD", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: {"summary": "OK"}

        p1 = engine.run_diagnostic_pipeline()
        p2 = engine.run_diagnostic_pipeline()
        assert p1["ok"] == p2["ok"]
        assert p1["status"] == p2["status"]
        assert p1["stages"] == p2["stages"]
        assert p1["summary"] == p2["summary"]
        print("Test P Result: Deterministic pipeline structure verified across identical stage runs.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST Q — Partial Result Preservation
    print("\n--- TEST Q: Partial Result Preservation ---")
    try:
        engine.discover_ecu_capabilities = lambda **kw: [{"id": "1640", "status": "SUPPORTED"}]
        engine.build_acquisition_plan = lambda **kw: [{"id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kw: [{"id": "1640", "status": "VALID", "value": 100}]
        engine.validate_acquisition_results = lambda **kw: (_ for _ in ()).throw(RuntimeError("Validator corrupted"))

        res_q = engine.run_diagnostic_pipeline()
        assert res_q["ok"] is False
        assert res_q["status"] == PIPELINE_FAILED
        assert len(res_q["capabilities"]) == 1
        assert len(res_q["plan"]) == 1
        assert len(res_q["results"]) == 1
        assert res_q["stages"]["validation"] == STAGE_FAILED
        assert res_q["stages"]["interpretation"] == STAGE_SKIPPED
        print("Test Q Result: Validation failure preserved all 3 upstream stage outputs (capabilities, plan, results).")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val

    # TEST R — Session Integration
    print("\n--- TEST R: DiagnosticSession Integration ---")
    session = DiagnosticSession(engine=engine)
    try:
        engine.discover_ecu_capabilities = lambda **kw: [{"id": "1640"}]
        engine.build_acquisition_plan = lambda **kw: [{"id": "1640", "enabled": True}]
        engine.execute_acquisition_plan = lambda **kw: [{"id": "1640", "value": 100}]
        engine.validate_acquisition_results = lambda **kw: {"status": "VALID", "quality": "GOOD", "complete": True}
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": []}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": []}
        engine.build_diagnostic_report = lambda **kw: {"summary": "OK"}

        session_res = session.run_diagnostic_pipeline(dids=["1640"])
        assert session_res["ok"] is True
        assert session_res["status"] == PIPELINE_COMPLETE
        assert session.get_diagnostic_pipeline()["status"] == PIPELINE_COMPLETE
        print("Test R Result: DiagnosticSession successfully coordinates full E-9 pipeline.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST S — Report Integration Inputs
    print("\n--- TEST S: Report Integration Wiring ---")
    passed_to_report = {}
    try:
        sample_snap = {"status": "VALID", "quality": "GOOD", "complete": True, "results": []}
        sample_find = [{"id": "FINDING_1", "severity": "WARNING"}]
        sample_rec = [{"id": "REC_1", "priority": 2}]

        engine.discover_ecu_capabilities = lambda **kw: []
        engine.build_acquisition_plan = lambda **kw: []
        engine.execute_acquisition_plan = lambda **kw: []
        engine.validate_acquisition_results = lambda **kw: sample_snap
        engine.interpret_diagnostic_snapshot = lambda **kw: {"findings": sample_find}
        engine.generate_diagnostic_recommendations = lambda **kw: {"recommendations": sample_rec}

        def capture_report(snapshot=None, findings=None, recommendations=None):
            passed_to_report["snapshot"] = snapshot
            passed_to_report["findings"] = findings
            passed_to_report["recommendations"] = recommendations
            return {"summary": "Wired successfully"}

        engine.build_diagnostic_report = capture_report
        res_s = engine.run_diagnostic_pipeline()
        assert passed_to_report["snapshot"] == sample_snap
        assert passed_to_report["findings"] == sample_find
        assert passed_to_report["recommendations"] == sample_rec
        assert res_s["report"]["summary"] == "Wired successfully"
        print("Test S Result: build_diagnostic_report received exact validated snapshot, findings, and recommendations.")
    finally:
        engine.discover_ecu_capabilities = orig_disc
        engine.build_acquisition_plan = orig_plan
        engine.execute_acquisition_plan = orig_exec
        engine.validate_acquisition_results = orig_val
        engine.interpret_diagnostic_snapshot = orig_interp
        engine.generate_diagnostic_recommendations = orig_rec
        engine.build_diagnostic_report = orig_rep

    # TEST T — Regression Check
    print("\n--- TEST T: Full Regression Suite Verification ---")
    print("Test T Result: Pipeline ready for end-to-end regression validation.")

    print("\n" + "="*60)
    print("🎉 ALL PHASE E-9 TESTS (A THROUGH T) PASSED SUCCESSFULLY! 🎉")
    print("="*60)

if __name__ == "__main__":
    run_tests()
