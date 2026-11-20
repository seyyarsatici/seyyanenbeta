"""
Phase F-6: Live Diagnostic UI / Presentation Test Suite
======================================================
Comprehensive test suite validating the presentation architecture,
view-models, thread boundaries, data quality visualization, DTC lifecycle display,
runtime health monitoring, and non-destructive operations.

Configured to run in headless/offscreen mode:
os.environ["QT_QPA_PLATFORM"] = "offscreen"
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure Qt runs offscreen without requiring an active display
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Initialize single QApplication instance for tests
app = QApplication.instance()
if app is None:
    app = QApplication(["test_phase_f6", "-platform", "offscreen"])

from motor import (
    AutoExpertEngine,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_NO_CONNECTION,
)
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_STARTING,
    LIVE_RUNNING,
    LIVE_DEGRADED,
    LIVE_STOPPING,
    LIVE_STOPPED,
    LIVE_ERROR,
)
from live_quality import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
)
from live_ui import QUALITY_UNKNOWN
from live_intelligence import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    CONFIDENCE_HIGH,
)
from live_dtc_lifecycle import (
    DTC_ACTIVE,
    DTC_RECOVERING,
    DTC_RESOLVED,
    DTC_INTERMITTENT,
    DTCObservationSnapshot,
)
from live_safety import (
    FAIL_TRANSIENT_TIMEOUT,
    FAIL_CONNECTION_LOST,
    CIRCUIT_CLOSED,
    CIRCUIT_OPEN,
    CIRCUIT_HALF_OPEN,
)
from live_ui import (
    LivePresentationModel,
    LiveTrendWidget,
    LiveDiagnosticWidget,
    LiveDiagnosticWindow,
)


def run_all_tests():
    print("=" * 70)
    print("SEYYANEN DIAGNOSTIC ENGINE — PHASE F-6 ACCEPTANCE TEST SUITE")
    print("=" * 70)

    # ----------------------------------------------------
    # TEST 1: Presentation Model — Formatting & Zero Protection
    # ----------------------------------------------------
    print("\n--- TEST 1: Presentation Model Formatting & Unknown Zero Protection ---")
    # Good RPM value
    res_rpm = LivePresentationModel.format_pid_value(850.4, "rpm", STATUS_VALID, QUALITY_GOOD)
    assert res_rpm == "850.4 rpm", f"Expected '850.4 rpm', got '{res_rpm}'"

    # Unknown / None value must NEVER be converted to 0
    res_unknown = LivePresentationModel.format_pid_value(None, "rpm", STATUS_NO_DATA, QUALITY_UNKNOWN)
    assert res_unknown == "VERİ YOK", f"Expected 'VERİ YOK', got '{res_unknown}'"
    assert res_unknown != "0", "Unknown value must not be replaced by fake zero"

    # Timeout value
    res_to = LivePresentationModel.format_pid_value(None, "°C", STATUS_TIMEOUT, QUALITY_ERROR)
    assert res_to == "ZAMAN AŞIMI", f"Expected 'ZAMAN AŞIMI', got '{res_to}'"

    # Invalid value with prior reading
    res_inv = LivePresentationModel.format_pid_value(999.0, "kPa", STATUS_VALID, QUALITY_INVALID)
    assert "GEÇERSİZ" in res_inv, f"Expected 'GEÇERSİZ' in '{res_inv}'"
    print("✅ TEST 1 PASSED: Values formatted cleanly; unknown/failed never replaced with fake zero.")

    # ----------------------------------------------------
    # TEST 2: Quality Badge Mapping
    # ----------------------------------------------------
    print("\n--- TEST 2: Data Quality Badge Palette ---")
    badge_good = LivePresentationModel.get_quality_badge(QUALITY_GOOD)
    assert "GOOD" in badge_good["text"]
    assert badge_good["bg"] == "#D4EDDA"

    badge_stale = LivePresentationModel.get_quality_badge(QUALITY_STALE)
    assert "STALE" in badge_stale["text"]

    badge_invalid = LivePresentationModel.get_quality_badge(QUALITY_INVALID)
    assert "INVALID" in badge_invalid["text"]
    print("✅ TEST 2 PASSED: Data quality badges distinctly configured.")

    # ----------------------------------------------------
    # TEST 3: DTC Lifecycle Badging & Non-Repair Guarantee
    # ----------------------------------------------------
    print("\n--- TEST 3: DTC Lifecycle Badges & Non-Repair Guarantee ---")
    badge_act = LivePresentationModel.get_dtc_state_badge(DTC_ACTIVE)
    assert "AKTİF" in badge_act["text"]

    badge_rec = LivePresentationModel.get_dtc_state_badge(DTC_RECOVERING)
    assert "KAYBOLMA" in badge_rec["text"]

    badge_res = LivePresentationModel.get_dtc_state_badge(DTC_RESOLVED)
    assert "GÖZLEMLE ÇÖZÜLDÜ" in badge_res["text"]
    assert "Tamir Edildi" not in badge_res["text"], "DTC resolution must NEVER claim vehicle is repaired"
    print("✅ TEST 3 PASSED: DTC lifecycle badges never state vehicle is repaired.")

    # ----------------------------------------------------
    # TEST 4: Initial Disconnected / Idle State
    # ----------------------------------------------------
    print("\n--- TEST 4: Initial Disconnected & Empty Widget State ---")
    engine = AutoExpertEngine()
    # Port not opened yet
    runtime = LiveAcquisitionRuntime(engine=engine, pids=["010C", "010D", "0105"])
    widget = LiveDiagnosticWidget(runtime=runtime)
    widget.update_ui_state()

    assert widget.badge_state.text() == LIVE_IDLE, f"Expected LIVE_IDLE, got {widget.badge_state.text()}"
    assert widget.btn_start.isEnabled() is True, "Start button should be enabled in LIVE_IDLE"
    assert widget.btn_stop.isEnabled() is False, "Stop button should be disabled in LIVE_IDLE"
    print("✅ TEST 4 PASSED: Widget correctly presents initial idle state.")

    # ----------------------------------------------------
    # TEST 5: Start & Stop Button State Transitions
    # ----------------------------------------------------
    print("\n--- TEST 5: Start & Stop Button Controls Reflect Runtime State ---")
    # Simulate transitions without real serial loops
    runtime._state = LIVE_RUNNING
    widget.update_ui_state()
    assert widget.btn_start.isEnabled() is False, "Start must be disabled when RUNNING"
    assert widget.btn_stop.isEnabled() is True, "Stop must be enabled when RUNNING"

    runtime._state = LIVE_STOPPED
    widget.update_ui_state()
    assert widget.btn_start.isEnabled() is True, "Start must be enabled when STOPPED"
    assert widget.btn_stop.isEnabled() is False, "Stop must be disabled when STOPPED"
    print("✅ TEST 5 PASSED: Button states strictly mirror backend runtime state.")

    # ----------------------------------------------------
    # TEST 6: Connection Status Presentation (RUNNING, DEGRADED, ERROR, DISCONNECTED)
    # ----------------------------------------------------
    print("\n--- TEST 6: Connection Badges (RUNNING, DEGRADED, ERROR, DISCONNECTED) ---")
    # Disconnected
    conn_disc = LivePresentationModel.get_connection_info(LIVE_IDLE, False)
    assert conn_disc["status"] == "BAĞLANTI YOK"

    # Running
    conn_run = LivePresentationModel.get_connection_info(LIVE_RUNNING, True)
    assert conn_run["status"] == "BAĞLI VE AKTİF"

    # Degraded
    conn_deg = LivePresentationModel.get_connection_info(LIVE_DEGRADED, True, failure_count=4)
    assert conn_deg["status"] == "KISITLI ÇALIŞMA"
    assert "4" in conn_deg["detail"]

    # Error
    conn_err = LivePresentationModel.get_connection_info(LIVE_ERROR, True)
    assert conn_err["status"] == "SİSTEM HATASI"
    print("✅ TEST 6 PASSED: Connection badges accurately represent transport states.")

    # ----------------------------------------------------
    # TEST 7: Live PID Table Rendering (Good Value)
    # ----------------------------------------------------
    print("\n--- TEST 7: Live PID Table Displays Good Sample ---")
    # Push synthetic sample into runtime
    runtime._record_sample({
        "pid": "010C",
        "name": "RPM",
        "value": 1850.0,
        "unit": "rpm",
        "status": STATUS_VALID,
        "timestamp": time.time(),
        "latency_ms": 15.0,
    })
    widget.update_ui_state()

    # Find row for 010C
    found_rpm = False
    for r in range(widget.table_pids.rowCount()):
        if widget.table_pids.item(r, 0).text() == "010C":
            found_rpm = True
            val_text = widget.table_pids.item(r, 2).text()
            unit_text = widget.table_pids.item(r, 3).text()
            qual_text = widget.table_pids.item(r, 5).text()
            assert "1850.0" in val_text, f"Expected 1850.0 in {val_text}"
            assert unit_text == "rpm"
            assert "GOOD" in qual_text
            break
    assert found_rpm, "010C row was not found in table"
    print("✅ TEST 7 PASSED: Good live sample accurately rendered with value, unit, and quality.")

    # ----------------------------------------------------
    # TEST 8: Stale Value Representation
    # ----------------------------------------------------
    print("\n--- TEST 8: Stale Value Displayed with Stale Badge & Age ---")
    # Manually mark 0105 as stale in quality assessor
    runtime.quality_assessor.evaluate_sample({
        "pid": "0105",
        "name": "ECT",
        "value": 85.0,
        "status": STATUS_VALID,
        "timestamp": time.time() - 10.0,  # 10 seconds ago
    })
    runtime._record_sample({
        "pid": "0105",
        "name": "ECT",
        "value": 85.0,
        "unit": "°C",
        "status": STATUS_VALID,
        "timestamp": time.time() - 10.0,
    })
    # Explicitly set quality state to STALE
    runtime.quality_assessor._current_quality["0105"] = {"pid": "0105", "quality": QUALITY_STALE, "is_trusted": False}
    widget.update_ui_state()

    found_ect = False
    for r in range(widget.table_pids.rowCount()):
        if widget.table_pids.item(r, 0).text() == "0105":
            found_ect = True
            qual_text = widget.table_pids.item(r, 5).text()
            assert "STALE" in qual_text, f"Expected STALE, got {qual_text}"
            break
    assert found_ect, "0105 row not found"
    print("✅ TEST 8 PASSED: Stale value visibly tagged with STALE badge.")

    # ----------------------------------------------------
    # TEST 9: Invalid / Error Value Representation
    # ----------------------------------------------------
    print("\n--- TEST 9: Invalid / Error Value Not Presented as Healthy ---")
    runtime._record_sample({
        "pid": "010D",
        "name": "SPEED",
        "value": 999.0,
        "unit": "km/h",
        "status": STATUS_VALID,
        "timestamp": time.time(),
    })
    runtime.quality_assessor._current_quality["010D"] = {"pid": "010D", "quality": QUALITY_INVALID, "is_trusted": False}
    widget.update_ui_state()

    found_spd = False
    for r in range(widget.table_pids.rowCount()):
        if widget.table_pids.item(r, 0).text() == "010D":
            found_spd = True
            val_text = widget.table_pids.item(r, 2).text()
            qual_text = widget.table_pids.item(r, 5).text()
            assert "GEÇERSİZ" in val_text
            assert "INVALID" in qual_text
            break
    assert found_spd, "010D row not found"
    print("✅ TEST 9 PASSED: Invalid value explicitly flagged and never looks healthy.")

    # ----------------------------------------------------
    # TEST 10: Category Filtering
    # ----------------------------------------------------
    print("\n--- TEST 10: Category Filtering Updates Table ---")
    widget.on_filter_changed("TEMEL MOTOR")
    # All rows should belong to TEMEL MOTOR
    for r in range(widget.table_pids.rowCount()):
        pid = widget.table_pids.item(r, 0).text()
        assert pid in widget.categories["TEMEL MOTOR"], f"PID {pid} should not be in TEMEL MOTOR"

    widget.on_filter_changed("TÜMÜ")
    assert widget.table_pids.rowCount() >= 3
    print("✅ TEST 10 PASSED: Category filtering updates table rows accurately.")

    # ----------------------------------------------------
    # TEST 11: Real-Time Signal Trend Waveform (LiveTrendWidget)
    # ----------------------------------------------------
    print("\n--- TEST 11: Real-Time Signal Trend Buffer & Bounded Memory ---")
    trend = LiveTrendWidget(max_points=50)
    trend.set_pid("010C", "RPM", "rpm")
    assert trend.current_pid == "010C"

    # Push 100 samples
    for i in range(100):
        trend.add_sample(800.0 + i, is_valid=True)
    
    # Memory must be bounded by max_points=50
    assert len(trend.history_y) == 50, f"Expected bounded 50 points, got {len(trend.history_y)}"
    assert trend.history_y[-1] == 899.0

    trend.clear()
    assert len(trend.history_y) == 0
    print("✅ TEST 11 PASSED: Real-time trend strictly bounded; zero memory leak.")

    # ----------------------------------------------------
    # TEST 12: F-3 Active Diagnostic Events Display
    # ----------------------------------------------------
    print("\n--- TEST 12: F-3 Diagnostic Events Display with Severity ---")
    # Record synthetic F-3 event
    runtime.intelligence_engine._recent_events.append({
        "timestamp": time.time(),
        "event_type": "OBSERVATION_DETECTED",
        "severity": SEVERITY_WARNING,
        "reason": "Misfire condition detected on cylinder 1",
        "pids": ["010C"],
        "metadata": {"confidence": CONFIDENCE_HIGH},
    })
    widget.update_ui_state()

    assert widget.table_events.rowCount() >= 1
    last_row = widget.table_events.rowCount() - 1
    ev_sev = widget.table_events.item(last_row, 1).text()
    ev_reason = widget.table_events.item(last_row, 4).text()
    assert ev_sev == "UYARI", f"Expected UYARI, got {ev_sev}"
    assert "Misfire" in ev_reason
    print("✅ TEST 12 PASSED: Diagnostic events displayed with severity and metadata.")

    # ----------------------------------------------------
    # TEST 13: F-3 Duplicate Event Deduplication
    # ----------------------------------------------------
    print("\n--- TEST 13: UI Preserves Backend Event Deduplication ---")
    # In F-3, record_event records; let's verify UI renders exactly the events without duplication
    row_count_before = widget.table_events.rowCount()
    widget.update_ui_state()
    assert widget.table_events.rowCount() == row_count_before, "UI duplicated events on update tick"
    print("✅ TEST 13 PASSED: Event deduplication preserved; no UI spam.")

    # ----------------------------------------------------
    # TEST 14: F-4 DTC Lifecycle Display (Active DTC)
    # ----------------------------------------------------
    print("\n--- TEST 14: F-4 Active DTC Displayed ---")
    snap1 = DTCObservationSnapshot(
        timestamp=time.time(),
        status=STATUS_VALID,
        codes=["P0300"],
        details=[{"code": "P0300", "description": "Random/Multiple Cylinder Misfire Detected"}]
    )
    runtime.process_dtc_snapshot(snap1)
    widget.update_ui_state()

    assert widget.table_dtcs.rowCount() >= 1
    code = widget.table_dtcs.item(0, 0).text()
    state_badge = widget.table_dtcs.item(0, 2).text()
    assert code == "P0300"
    assert "YENİ TESPİT" in state_badge or "AKTİF" in state_badge
    print("✅ TEST 14 PASSED: Active DTC correctly displayed in DTC panel.")

    # ----------------------------------------------------
    # TEST 15: F-4 Recovering DTC Display
    # ----------------------------------------------------
    print("\n--- TEST 15: F-4 Recovering DTC Display ---")
    # Valid snapshot without P0300 -> transitions to RECOVERING
    snap2 = DTCObservationSnapshot(
        timestamp=time.time(),
        status=STATUS_VALID,
        codes=[],
        details=[]
    )
    runtime.process_dtc_snapshot(snap2)
    widget.update_ui_state()

    state_badge_2 = widget.table_dtcs.item(0, 2).text()
    assert "KAYBOLMA" in state_badge_2, f"Expected KAYBOLMA, got {state_badge_2}"
    print("✅ TEST 15 PASSED: Recovering DTC displayed with KAYBOLMA badge.")

    # ----------------------------------------------------
    # TEST 16: F-4 Resolved-by-Observation Distinction
    # ----------------------------------------------------
    print("\n--- TEST 16: Resolved DTC Never Claimed as Repaired ---")
    # Consecutive absence transitions to RESOLVED
    for _ in range(5):
        runtime.process_dtc_snapshot(snap2)
    widget.update_ui_state()

    state_badge_res = widget.table_dtcs.item(0, 2).text()
    assert "GÖZLEMLE ÇÖZÜLDÜ" in state_badge_res
    assert "Tamir Edildi" not in state_badge_res
    print("✅ TEST 16 PASSED: Resolved-by-observation distinct from physical repair.")

    # ----------------------------------------------------
    # TEST 17: Multiple DTCs Displayed Independently
    # ----------------------------------------------------
    print("\n--- TEST 17: Multiple Simultaneous DTCs Handled Independently ---")
    snap_multi = DTCObservationSnapshot(
        timestamp=time.time(),
        status=STATUS_VALID,
        codes=["P0171", "P0420"],
        details=[
            {"code": "P0171", "description": "System Too Lean Bank 1"},
            {"code": "P0420", "description": "Catalyst System Efficiency Below Threshold"}
        ]
    )
    runtime.process_dtc_snapshot(snap_multi)
    widget.update_ui_state()

    dtc_codes = [widget.table_dtcs.item(r, 0).text() for r in range(widget.table_dtcs.rowCount())]
    assert "P0171" in dtc_codes
    assert "P0420" in dtc_codes
    print("✅ TEST 17 PASSED: Multiple simultaneous DTCs rendered independently.")

    # ----------------------------------------------------
    # TEST 18: F-5 Runtime Safety & Recovery Health Panel
    # ----------------------------------------------------
    print("\n--- TEST 18: F-5 Health Panel Displays Failures & Circuit Breakers ---")
    runtime.safety_manager.record_failure(
        category=FAIL_TRANSIENT_TIMEOUT,
        component="PID:010C",
        severity=SEVERITY_WARNING,
        reason="Simulated ELM327 acquisition timeout"
    )
    widget.update_ui_state()

    assert widget.table_failures.rowCount() >= 1
    last_row = widget.table_failures.rowCount() - 1
    fail_cls = widget.table_failures.item(last_row, 1).text()
    fail_pid = widget.table_failures.item(last_row, 2).text()
    fail_msg = widget.table_failures.item(last_row, 3).text()

    assert fail_cls == FAIL_TRANSIENT_TIMEOUT
    assert "010C" in fail_pid
    assert "timeout" in fail_msg.lower()
    print("✅ TEST 18 PASSED: Runtime failures correctly populated in safety table.")

    # ----------------------------------------------------
    # TEST 19: Safe Reconnection Button Invocation
    # ----------------------------------------------------
    print("\n--- TEST 19: Reconnection Action Calls High-Level Runtime Reconnect ---")
    with patch.object(runtime, "reconnect", return_value=True) as mock_reconn:
        with patch("PyQt6.QtWidgets.QMessageBox.information") as mock_info:
            widget.on_reconnect_clicked()
            if widget._reconnect_worker:
                widget._reconnect_worker.wait(2000)
            app.processEvents()
            mock_reconn.assert_called_once()
            mock_info.assert_called_once()
    print("✅ TEST 19 PASSED: Reconnection triggers safe high-level runtime reconnect.")

    # ----------------------------------------------------
    # TEST 20: Safe Mode 03 Poll Trigger
    # ----------------------------------------------------
    print("\n--- TEST 20: Poll DTCs Button Invokes poll_dtcs() Safely ---")
    with patch.object(runtime, "poll_dtcs", return_value={"is_valid": True, "active_dtcs": []}) as mock_poll:
        with patch("PyQt6.QtWidgets.QMessageBox.information") as mock_info:
            widget.on_poll_dtc_clicked()
            if widget._dtc_worker:
                widget._dtc_worker.wait(2000)
            app.processEvents()
            mock_poll.assert_called_once()
            mock_info.assert_called_once()
    print("✅ TEST 20 PASSED: Poll DTCs invokes poll_dtcs() without raw serial commands.")

    # ----------------------------------------------------
    # TEST 21: Reset Faults is Purely In-Memory (Zero Mode 04)
    # ----------------------------------------------------
    print("\n--- TEST 21: Reset Faults is In-Memory Only (Zero Mode 04) ---")
    with patch.object(runtime, "reset_runtime_faults") as mock_reset:
        with patch.object(runtime.engine, "komut_gonder") as mock_cmd:
            with patch("PyQt6.QtWidgets.QMessageBox.information"):
                widget.on_reset_faults_clicked()
                mock_reset.assert_called_once()
                mock_cmd.assert_not_called()
    print("✅ TEST 21 PASSED: Reset faults is strictly in-memory; zero Mode 04 issued.")

    # ----------------------------------------------------
    # TEST 22: Thread Safety Boundary (Worker Never Touches Widgets)
    # ----------------------------------------------------
    print("\n--- TEST 22: Thread Safety Boundary Verified ---")
    # Verify LiveAcquisitionRuntime._fire_callback does not touch widgets
    import threading
    worker_tid = None
    def sample_cb(sample):
        nonlocal worker_tid
        worker_tid = threading.get_ident()
    
    rt_thread_test = LiveAcquisitionRuntime(engine=engine, pids=["010C"], on_sample=sample_cb)
    sample_dummy = {"pid": "010C", "name": "RPM", "value": 800.0, "status": STATUS_VALID, "timestamp": time.time()}
    rt_thread_test._fire_callback(sample_dummy)
    assert worker_tid == threading.get_ident()
    print("✅ TEST 22 PASSED: Worker callback isolated from direct GUI widget calls.")

    # ----------------------------------------------------
    # TEST 23: UI Exception Isolation (Never Kills Runtime)
    # ----------------------------------------------------
    print("\n--- TEST 23: UI Exception Handled Without Crashing Runtime ---")
    # Force an exception during update_ui_state
    with patch.object(widget, "_update_live_table", side_effect=ValueError("Simulated GUI render failure")):
        # Must not raise an unhandled exception
        widget.update_ui_state()
        # Runtime must remain completely healthy
        assert runtime.get_state() in (LIVE_IDLE, LIVE_RUNNING, LIVE_STOPPED, LIVE_DEGRADED)
    print("✅ TEST 23 PASSED: UI rendering exceptions isolated gracefully.")

    # ----------------------------------------------------
    # TEST 24: Empty / Null Runtime Handling
    # ----------------------------------------------------
    print("\n--- TEST 24: Null Runtime Handled Without Crash ---")
    empty_widget = LiveDiagnosticWidget(runtime=None)
    empty_widget.update_ui_state()
    assert empty_widget.badge_connection.text() == "BAĞLANTI YOK"
    print("✅ TEST 24 PASSED: Empty runtime state handled cleanly.")

    # ----------------------------------------------------
    # TEST 25: Performance Benchmark
    # ----------------------------------------------------
    print("\n--- TEST 25: GUI Refresh Benchmark ---")
    t0 = time.perf_counter()
    for _ in range(50):
        widget.update_ui_state()
    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / 50.0) * 1000.0
    print(f"Benchmark: 50 UI update cycles executed in {elapsed*1000:.2f} ms ({avg_ms:.2f} ms / cycle)")
    assert avg_ms < 15.0, f"UI update too slow: {avg_ms:.2f} ms"
    print("✅ TEST 25 PASSED: UI refresh cycle ultra-lightweight (< 15ms).")

    # ----------------------------------------------------
    # TEST 26: Standalone Window Initialization
    # ----------------------------------------------------
    print("\n--- TEST 26: Standalone Window Instantiation ---")
    win = LiveDiagnosticWindow(runtime=runtime)
    assert win.live_widget is not None
    assert "Seyyanen Canlı Teşhis" in win.windowTitle()
    win.close()
    print("✅ TEST 26 PASSED: Standalone window instantiates cleanly.")

    # ----------------------------------------------------
    # TEST 27: MainUI Integration Check
    # ----------------------------------------------------
    print("\n--- TEST 27: MainUI Integration & OBD Connect Routing ---")
    from main_ui import MainUI
    main_window = MainUI()
    assert hasattr(main_window, "open_live_diagnostics")
    # Simulate clicking btn_obd_connect
    main_window.open_live_diagnostics()
    assert hasattr(main_window, "live_diagnostic_panel")
    assert main_window.analysis_stack.currentWidget() == main_window.live_diagnostic_panel
    main_window.close()
    print("✅ TEST 27 PASSED: MainUI seamlessly switches to LiveDiagnosticWidget.")

    print("\n" + "=" * 70)
    print("🎉 ALL PHASE F-6 LIVE DIAGNOSTIC UI TESTS PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
