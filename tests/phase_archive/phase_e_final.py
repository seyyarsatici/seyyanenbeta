"""
test_phase_e_final.py
======================
Comprehensive Final Integration, Hardening & Quality-Gate Test Suite
Exercises complete C/D/E stack using real implementations and mock serial infrastructure.

Structure:
- PART 1: E-4 / E-5 Data Contract Hardening Tests (Tests 1.A - 1.G)
- PART 2: E-6 Response / NRC Hardening Tests (Tests 2.A - 2.C)
- PART 3: DTC Integration into E Pipeline Tests (Tests 3.A - 3.F)
- PART 4: True End-to-End Integration Tests (Tests 4.1 - 4.10)
"""

import time
import copy
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_EMPTY_RESPONSE,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    STATUS_DID_MISMATCH,
    QUALITY_GOOD,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    QUALITY_STALE,
    QUALITY_SUSPECT,
    CAPABILITY_SUPPORTED,
    CAPABILITY_UNSUPPORTED,
    CAPABILITY_NEGATIVE_RESPONSE,
    CAPABILITY_TIMEOUT,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    PIPELINE_COMPLETE,
    PIPELINE_PARTIAL,
    PIPELINE_FAILED,
)


def run_part1_tests(engine):
    print("\n=======================================================")
    print("PART 1: E-4 / E-5 DATA CONTRACT HARDENING TESTS")
    print("=======================================================")

    # 1.A: Fresh valid acquisition
    print("\n[PART 1 - TEST A] Fresh valid acquisition")
    now_ts = time.time()
    res_a = engine._update_sensor_cache("RPM", 850.0, status=STATUS_VALID, timestamp=now_ts, source="MODE01")
    assert res_a["quality"] == QUALITY_GOOD, f"Expected GOOD, got {res_a['quality']}"
    assert engine._is_sensor_fresh("RPM") is True, "Expected sensor to be fresh"
    
    val_res_a = engine.validate_acquisition_results([{
        "type": "MODE01_PID",
        "id": "RPM",
        "header": "7DF",
        "service": "01",
        "request": "010C",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "value": 850.0,
        "timestamp": now_ts,
    }])
    assert val_res_a["status"] == STATUS_VALID
    assert val_res_a["quality"] == QUALITY_GOOD
    assert val_res_a["results"][0]["validation"]["accepted"] is True
    assert val_res_a["results"][0]["validation"]["fresh"] is True
    print("  -> Passed: Fresh valid acquisition validated as accepted and fresh.")

    # 1.B: Stale acquisition
    print("\n[PART 1 - TEST B] Stale acquisition")
    stale_ts = time.time() - 5.0
    engine.data_cache["STALE_SENS"] = {
        "val": 42.0,
        "time": stale_ts,
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
    }
    assert engine._is_sensor_fresh("STALE_SENS") is False, "Expected sensor to be stale"
    val_res_b = engine.validate_acquisition_results([{
        "type": "MODE22_DID",
        "id": "STALE_SENS",
        "header": "7E0",
        "service": "22",
        "request": "229999",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "value": 42.0,
        "timestamp": stale_ts,
    }])
    assert val_res_b["quality"] == QUALITY_STALE
    assert val_res_b["results"][0]["validation"]["fresh"] is False
    print("  -> Passed: Stale acquisition detected via canonical freshness.")

    # 1.C: Valid response but implausible value
    print("\n[PART 1 - TEST C] Valid response but implausible value")
    engine._update_sensor_cache("ECT", 350.0, status=STATUS_VALID, source="MODE01")
    assert engine.data_cache["ECT"]["quality"] == QUALITY_IMPLAUSIBLE
    val_res_c = engine.validate_acquisition_results([{
        "type": "MODE01_PID",
        "id": "ECT",
        "name": "ECT",
        "header": "7DF",
        "service": "01",
        "request": "0105",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,  # E-4 might have initially tagged GOOD
        "value": 350.0,
        "timestamp": time.time(),
    }])
    assert val_res_c["results"][0]["quality"] == QUALITY_IMPLAUSIBLE
    assert val_res_c["results"][0]["validation"]["accepted"] is False
    assert val_res_c["quality"] == QUALITY_IMPLAUSIBLE
    print("  -> Passed: Implausible value correctly synchronizes cache quality and rejects acceptance.")

    # 1.D: Timeout preserving previous cache
    print("\n[PART 1 - TEST D] Timeout preserving previous cache")
    valid_ts = time.time()
    engine._update_sensor_cache("RPM", 900.0, status=STATUS_VALID, timestamp=valid_ts, source="MODE01")
    old_cache = dict(engine.data_cache["RPM"])
    old_hist_len = len(engine.sensor_history.get("RPM", []))
    
    # Execute plan that times out
    plan_timeout = [{
        "type": "MODE22_DID",
        "id": "DEAD",
        "header": "7E0",
        "service": "22",
        "request": "22DEAD",
        "enabled": True,
    }]
    exec_res_d = engine.execute_acquisition_plan(plan_timeout)
    assert len(exec_res_d) == 1
    assert exec_res_d[0]["status"] == STATUS_TIMEOUT
    # Verify previous RPM cache is untouched
    assert engine.data_cache["RPM"]["val"] == 900.0
    assert engine.data_cache["RPM"]["time"] == valid_ts
    assert len(engine.sensor_history.get("RPM", [])) == old_hist_len
    print("  -> Passed: Timeout preserved previous cache and history.")

    # 1.E: NRC preserving previous cache
    print("\n[PART 1 - TEST E] NRC preserving previous cache")
    plan_nrc = [{
        "type": "MODE22_DID",
        "id": "336A",
        "header": "7E0",
        "service": "22",
        "request": "22336A",
        "enabled": True,
    }]
    exec_res_e = engine.execute_acquisition_plan(plan_nrc)
    assert len(exec_res_e) == 1
    assert exec_res_e[0]["status"] == STATUS_NRC
    assert engine.data_cache["RPM"]["val"] == 900.0
    assert len(engine.sensor_history.get("RPM", [])) == old_hist_len
    print("  -> Passed: NRC preserved previous cache and history.")

    # 1.F: E-5 uses canonical freshness behavior
    print("\n[PART 1 - TEST F] E-5 uses canonical freshness behavior")
    assert hasattr(engine, "_is_sensor_fresh")
    assert hasattr(engine, "_get_sensor_age")
    engine._update_sensor_cache("TEST_SENS", 10.0, status=STATUS_VALID)
    assert engine._is_sensor_fresh("TEST_SENS") is True
    print("  -> Passed: Canonical freshness methods available and verified.")

    # 1.G: Cache quality and E-layer validation quality remain consistent
    print("\n[PART 1 - TEST G] Cache quality and E-layer validation quality remain consistent")
    engine._update_sensor_cache("MAP", 999.0, status=STATUS_VALID)
    assert engine.data_cache["MAP"]["quality"] == QUALITY_IMPLAUSIBLE
    snap_g = engine.validate_acquisition_results([{
        "type": "MODE01_PID",
        "id": "MAP",
        "name": "MAP",
        "header": "7DF",
        "service": "01",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "value": 999.0,
        "timestamp": time.time(),
    }])
    assert snap_g["results"][0]["quality"] == QUALITY_IMPLAUSIBLE
    print("  -> Passed: Cache quality overrides stale/divergent validation quality.")


def run_part2_tests(engine):
    print("\n=======================================================")
    print("PART 2: E-6 RESPONSE / NRC HARDENING TESTS")
    print("=======================================================")

    # 2.A: Genuine NRC 7F 22 31
    print("\n[PART 2 - TEST A] Genuine NRC 7F 22 31")
    snap_nrc = {
        "status": STATUS_NRC,
        "quality": QUALITY_INVALID,
        "results": [{
            "type": "MODE22_DID",
            "id": "336A",
            "header": "7E0",
            "service": "22",
            "request": "22336A",
            "status": STATUS_NRC,
            "quality": QUALITY_INVALID,
            "nrc": "31",
            "nrc_desc": "Request Out Of Range",
            "response": "7F 22 31",
            "validation": {"accepted": False, "fresh": True, "issues": []},
        }]
    }
    interp_a = engine.interpret_diagnostic_snapshot(snap_nrc)
    nrc_finding = next((f for f in interp_a["findings"] if f["source"] == "NRC"), None)
    assert nrc_finding is not None, "Expected NRC finding"
    assert nrc_finding["evidence"]["nrc"] == "31"
    print("  -> Passed: Genuine NRC classified as STATUS_NRC with NRC 31.")

    # 2.B: Positive response containing payload byte 7F (e.g. 62 16 40 7F 00)
    print("\n[PART 2 - TEST B] Positive response containing payload byte 7F")
    if hasattr(engine.ser, "mock_1640_payload"):
        engine.ser.mock_1640_payload = "7F00"
    
    plan_7f = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "request": "221640",
        "source": "MODE22_CSV",
        "enabled": True,
    }]
    exec_res_b = engine.execute_acquisition_plan(plan_7f)
    assert len(exec_res_b) == 1
    assert exec_res_b[0]["status"] == STATUS_VALID, f"Expected STATUS_VALID, got {exec_res_b[0]['status']}"
    assert exec_res_b[0]["payload_hex"] == "7F00"
    
    snap_7f = engine.validate_acquisition_results(exec_res_b)
    interp_b = engine.interpret_diagnostic_snapshot(snap_7f)
    # Must NOT contain an NRC finding!
    nrc_findings = [f for f in interp_b["findings"] if f["source"] == "NRC"]
    assert len(nrc_findings) == 0, f"False NRC finding generated on 7F payload: {nrc_findings}"
    print("  -> Passed: Positive payload containing 0x7F byte correctly recognized as VALID, NOT NRC.")

    # 2.C: Multi-frame payload containing 7F
    print("\n[PART 2 - TEST C] Multi-frame payload containing 7F")
    plan_mf = [{
        "type": "MODE22_DID",
        "id": "1641",
        "header": "7E0",
        "service": "22",
        "request": "221641",
        "source": "MODE22_CSV",
        "enabled": True,
    }]
    exec_res_c = engine.execute_acquisition_plan(plan_mf)
    assert len(exec_res_c) == 1
    assert exec_res_c[0]["status"] == STATUS_VALID
    assert len(exec_res_c[0]["payload_bytes"]) > 0
    print("  -> Passed: Multi-frame payload with 7F correctly reassembled and validated.")


def run_part3_tests(engine):
    print("\n=======================================================")
    print("PART 3: DTC INTEGRATION INTO E PIPELINE TESTS")
    print("=======================================================")

    # 3.A: Valid DTC response
    print("\n[PART 3 - TEST A] Valid DTC response")
    dtc_res_a = engine.read_diagnostic_trouble_codes()
    assert dtc_res_a["type"] == "DTC"
    assert dtc_res_a["status"] == STATUS_VALID
    assert "codes" in dtc_res_a
    assert isinstance(dtc_res_a["codes"], list)
    print(f"  -> Passed: Structured DTC result returned codes: {dtc_res_a['codes']}")

    # 3.B: Multiple DTCs
    print("\n[PART 3 - TEST B] Multiple DTCs structured parsing")
    structured_multi_dtc = {
        "type": "DTC",
        "status": STATUS_VALID,
        "codes": ["P0300", "P0171", "C0035"],
        "details": [
            {"kod": "P0300", "aciklama": "Random/Multiple Cylinder Misfire Detected"},
            {"kod": "P0171", "aciklama": "System Too Lean (Bank 1)"},
            {"kod": "C0035", "aciklama": "Left Front Wheel Speed Circuit"},
        ],
        "raw_response": ["43 03 03 00 01 71 40 35"],
        "timestamp": time.time(),
    }
    empty_snap = {
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "results": [],
    }
    interp_b = engine.interpret_diagnostic_snapshot(snapshot=empty_snap, dtcs=structured_multi_dtc)
    dtc_findings = [f for f in interp_b["findings"] if f["source"] == "DTC"]
    assert len(dtc_findings) == 3, f"Expected 3 DTC findings, got {len(dtc_findings)}"
    assert any(f["id"] == "FINDING_DTC_P0300" for f in dtc_findings)
    assert any(f["id"] == "FINDING_DTC_P0171" for f in dtc_findings)
    assert any(f["id"] == "FINDING_DTC_C0035" for f in dtc_findings)
    print("  -> Passed: Multiple DTCs produced exactly 3 structured findings.")

    # 3.C: No DTCs
    print("\n[PART 3 - TEST C] No DTCs")
    structured_no_dtc = {
        "type": "DTC",
        "status": STATUS_NO_DATA,
        "codes": [],
        "details": [],
        "raw_response": ["NO DATA"],
        "timestamp": time.time(),
    }
    interp_c = engine.interpret_diagnostic_snapshot(snapshot=empty_snap, dtcs=structured_no_dtc)
    dtc_findings_c = [f for f in interp_c["findings"] if f["source"] == "DTC"]
    assert len(dtc_findings_c) == 0, "No DTC findings should be generated when no DTCs are present"
    print("  -> Passed: No DTCs produce zero false DTC findings.")

    # 3.D: DTC communication timeout
    print("\n[PART 3 - TEST D] DTC communication timeout")
    structured_timeout = {
        "type": "DTC",
        "status": STATUS_TIMEOUT,
        "codes": [],
        "details": [],
        "raw_response": [],
        "timestamp": time.time(),
        "error": "Communication timed out",
    }
    interp_d = engine.interpret_diagnostic_snapshot(snapshot=empty_snap, dtcs=structured_timeout)
    dtc_findings_d = [f for f in interp_d["findings"] if f["source"] == "DTC"]
    assert len(dtc_findings_d) == 0, "Timeout must not fabricate fake DTC findings"
    print("  -> Passed: DTC communication timeout produces no fake DTC findings.")

    # 3.E: Malformed DTC response
    print("\n[PART 3 - TEST E] Malformed DTC response")
    structured_malformed = {
        "type": "DTC",
        "status": STATUS_VALID,
        "codes": ["", "   ", None],
        "details": [],
        "raw_response": ["43 GARBAGE"],
        "timestamp": time.time(),
    }
    interp_e = engine.interpret_diagnostic_snapshot(snapshot=empty_snap, dtcs=structured_malformed)
    dtc_findings_e = [f for f in interp_e["findings"] if f["source"] == "DTC"]
    assert len(dtc_findings_e) == 0, "Malformed DTC entries must be safely skipped"
    print("  -> Passed: Malformed DTC entries safely ignored.")

    # 3.F: DTC results survive through E interpretation/report pipeline
    print("\n[PART 3 - TEST F] DTC results survive through E interpretation/report pipeline")
    snap_f = engine.validate_acquisition_results([{
        "type": "MODE01_PID",
        "id": "RPM",
        "header": "7DF",
        "service": "01",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "value": 800.0,
        "timestamp": time.time(),
    }])
    interp_f = engine.interpret_diagnostic_snapshot(snapshot=snap_f, dtcs=structured_multi_dtc)
    recs_f = engine.generate_diagnostic_recommendations(interp_f["findings"])
    report_f = engine.build_diagnostic_report(snapshot=snap_f, findings=interp_f["findings"], recommendations=recs_f["recommendations"])
    assert report_f["finding_count"] >= 3
    assert any("P0300" in f["title"] for f in report_f["findings"])
    print("  -> Passed: DTC findings survived through recommendation and reporting layers.")


def run_part4_e2e_tests():
    print("\n=======================================================")
    print("PART 4: TRUE E2E INTEGRATION TESTS (REAL E1 -> E9)")
    print("=======================================================")

    # TEST 1 — CLEAN END-TO-END
    print("\n[TEST 1] Clean End-to-End Execution")
    session = DiagnosticSession()
    assert session.start() is True
    time.sleep(0.3)
    
    if hasattr(session.engine.ser, "mock_1640_payload"):
        session.engine.ser.mock_1640_payload = "0096"

    pipe_res1 = session.run_diagnostic_pipeline(
        headers=["7E0"],
        dids=["1640"],
        include_unsupported=False,
    )
    assert pipe_res1["ok"] is True
    assert pipe_res1["status"] in (PIPELINE_COMPLETE, PIPELINE_PARTIAL)
    assert pipe_res1["stages"]["discovery"] == "COMPLETE"
    assert pipe_res1["stages"]["planning"] == "COMPLETE"
    assert pipe_res1["stages"]["execution"] == "COMPLETE"
    assert pipe_res1["stages"]["validation"] == "COMPLETE"
    assert pipe_res1["stages"]["interpretation"] == "COMPLETE"
    assert pipe_res1["stages"]["recommendation"] == "COMPLETE"
    assert pipe_res1["stages"]["report"] == "COMPLETE"
    assert len(pipe_res1["results"]) == 1
    assert pipe_res1["results"][0]["status"] == STATUS_VALID
    assert pipe_res1["results"][0]["value"] == 150
    session.stop()
    print("  -> Passed: Clean end-to-end pipeline completed through all 7 stages.")

    # TEST 2 — UNSUPPORTED DID
    print("\n[TEST 2] Unsupported DID Execution")
    session2 = DiagnosticSession()
    session2.start()
    time.sleep(0.3)
    pipe_res2 = session2.run_diagnostic_pipeline(
        headers=["7E0"],
        dids=["336A"],  # Returns NRC 31 in mock serial -> UNSUPPORTED
        include_unsupported=False,
    )
    assert pipe_res2["ok"] is True
    assert len(pipe_res2["plan"]) == 0  # Not planned because unsupported
    session2.stop()
    print("  -> Passed: Unsupported DID preserved, zero fabricated measurements.")

    # TEST 3 — TIMEOUT
    print("\n[TEST 3] Timeout Representation")
    engine3 = AutoExpertEngine()
    engine3.baglan()
    time.sleep(0.3)
    engine3._update_sensor_cache("RPM", 800.0, status=STATUS_VALID)
    old_time = engine3.data_cache["RPM"]["time"]
    
    plan_to = [{
        "type": "MODE22_DID",
        "id": "DEAD",
        "header": "7E0",
        "service": "22",
        "request": "22DEAD",
        "enabled": True,
    }]
    res_to = engine3.execute_acquisition_plan(plan_to)
    assert len(res_to) == 1
    assert res_to[0]["status"] == STATUS_TIMEOUT
    snap_to = engine3.validate_acquisition_results(res_to)
    interp_to = engine3.interpret_diagnostic_snapshot(snap_to)
    comm_findings = [f for f in interp_to["findings"] if f["source"] == "COMMUNICATION"]
    assert len(comm_findings) == 1
    assert engine3.data_cache["RPM"]["val"] == 800.0
    assert engine3.data_cache["RPM"]["time"] == old_time
    print("  -> Passed: Timeout represented structurally, previous cache intact.")

    # TEST 4 — NRC
    print("\n[TEST 4] NRC Handling")
    plan_nrc4 = [{
        "type": "MODE22_DID",
        "id": "336A",
        "header": "7E0",
        "service": "22",
        "request": "22336A",
        "enabled": True,
    }]
    res_nrc4 = engine3.execute_acquisition_plan(plan_nrc4)
    assert len(res_nrc4) == 1
    assert res_nrc4[0]["status"] == STATUS_NRC
    snap_nrc4 = engine3.validate_acquisition_results(res_nrc4)
    interp_nrc4 = engine3.interpret_diagnostic_snapshot(snap_nrc4)
    nrc_findings4 = [f for f in interp_nrc4["findings"] if f["source"] == "NRC"]
    assert len(nrc_findings4) == 1
    assert nrc_findings4[0]["evidence"]["nrc"] == "31"
    print("  -> Passed: NRC preserved, no false sensor values fabricated.")

    # TEST 5 — IMPLAUSIBLE VALUE
    print("\n[TEST 5] Implausible Value Filtering")
    # Simulate an ECU response with impossible ECT
    engine3._update_sensor_cache("ECT", 320.0, status=STATUS_VALID)
    assert engine3.data_cache["ECT"]["quality"] == QUALITY_IMPLAUSIBLE
    snap5 = engine3.validate_acquisition_results([{
        "type": "MODE01_PID",
        "id": "ECT",
        "name": "ECT",
        "header": "7DF",
        "service": "01",
        "status": STATUS_VALID,
        "quality": QUALITY_GOOD,
        "value": 320.0,
        "timestamp": time.time(),
    }])
    assert snap5["results"][0]["validation"]["accepted"] is False
    interp5 = engine3.interpret_diagnostic_snapshot(snap5)
    plaus_findings = [f for f in interp5["findings"] if f["source"] == "PLAUSIBILITY"]
    assert len(plaus_findings) == 1
    print("  -> Passed: Implausible value flagged as suspicious and rejected from acceptance.")

    # TEST 6 — DTC END-TO-END
    print("\n[TEST 6] DTC End-to-End Pipeline Integration")
    session6 = DiagnosticSession()
    session6.start()
    time.sleep(0.3)
    structured_dtc = session6.read_dtcs()
    pipe_res6 = session6.run_diagnostic_pipeline(
        headers=["7E0"],
        dids=["1640"],
        dtcs=structured_dtc,
    )
    assert pipe_res6["ok"] is True
    # Verify DTC finding is included in final report
    assert any("DTC" in f.get("source", "") for f in pipe_res6["findings"])
    session6.stop()
    print("  -> Passed: Real Mode 03 DTC flowed through entire pipeline to report.")

    # TEST 7 — PARTIAL PIPELINE FAILURE
    print("\n[TEST 7] Partial Pipeline Failure Error Boundary")
    engine7 = AutoExpertEngine()
    engine7.baglan()
    time.sleep(0.3)
    # Inject failure into report stage
    orig_report = engine7.build_diagnostic_report
    try:
        engine7.build_diagnostic_report = lambda **kw: (_ for _ in ()).throw(RuntimeError("Report crash test"))
        pipe_res7 = engine7.run_diagnostic_pipeline(
            headers=["7E0"],
            dids=["1640"],
            dtcs={"type": "DTC", "status": STATUS_VALID, "codes": ["P0300"]},
        )
        assert pipe_res7["ok"] is False
        assert pipe_res7["status"] == PIPELINE_FAILED
        assert pipe_res7["stages"]["report"] == "FAILED"
        assert len(pipe_res7["capabilities"]) > 0
        assert len(pipe_res7["results"]) > 0
        assert len(pipe_res7["findings"]) > 0  # Upstream findings preserved
    finally:
        engine7.build_diagnostic_report = orig_report
    print("  -> Passed: Pipeline handles downstream stage failure without losing upstream results.")

    # TEST 8 — REPEATED RUNS & STATE ISOLATION
    print("\n[TEST 8] Repeated Runs & State Isolation")
    session8 = DiagnosticSession()
    session8.start()
    time.sleep(0.3)
    
    # Run 1: with DTCs (generates findings)
    pipe_1 = session8.run_diagnostic_pipeline(
        headers=["7E0"],
        dids=["1640"],
        dtcs={"type": "DTC", "status": STATUS_VALID, "codes": ["P0300"]},
    )
    assert len(pipe_1["findings"]) > 0

    # Run 2: Clean without DTCs
    pipe_2 = session8.run_diagnostic_pipeline(
        headers=["7E0"],
        dids=["1640"],
        dtcs={"type": "DTC", "status": STATUS_NO_DATA, "codes": []},
    )
    assert not any("P0300" in f["id"] for f in pipe_2["findings"]), "Run 1 findings leaked into Run 2!"
    session8.stop()
    print("  -> Passed: Independent runs maintain complete state isolation.")

    # TEST 9 — INPUT IMMUTABILITY
    print("\n[TEST 9] Input Immutability")
    headers_input = ["7E0", "7E1"]
    dids_input = ["1640", "1641"]
    orig_headers = list(headers_input)
    orig_dids = list(dids_input)
    
    session9 = DiagnosticSession()
    session9.start()
    time.sleep(0.3)
    session9.run_diagnostic_pipeline(
        headers=headers_input,
        dids=dids_input,
    )
    assert headers_input == orig_headers, "Headers list was modified by pipeline!"
    assert dids_input == orig_dids, "DIDs list was modified by pipeline!"
    session9.stop()
    print("  -> Passed: Caller inputs are strictly immutable.")

    # TEST 10 — HEADER SAFETY
    print("\n[TEST 10] CAN Header Restoration Safety")
    session10 = DiagnosticSession()
    session10.start()
    time.sleep(0.3)
    session10.engine.current_header = "7DF"
    session10.run_diagnostic_pipeline(
        headers=["7E0"],
        dids=["1640"],
    )
    assert session10.engine.current_header == "7DF", f"Header was not restored! (Current: {session10.engine.current_header})"
    session10.stop()
    print("  -> Passed: CAN Header was safely restored to original value.")


def main():
    print("===================================================================")
    print("STARTING COMPLETE PHASE E FINAL INTEGRATION & HARDENING TEST SUITE")
    print("===================================================================")

    engine = AutoExpertEngine()
    engine.baglan()
    time.sleep(0.5)

    try:
        run_part1_tests(engine)
        run_part2_tests(engine)
        run_part3_tests(engine)
        run_part4_e2e_tests()
        print("\n===================================================================")
        print("ALL FINAL INTEGRATION AND HARDENING TESTS PASSED SUCCESSFULLY!")
        print("===================================================================")
    finally:
        if hasattr(engine, "ser") and engine.ser:
            engine.ser.close()


if __name__ == "__main__":
    main()
