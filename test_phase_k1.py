"""
test_phase_k1.py - Phase K-1 Non-Blocking Diagnostic Connection Runtime Hardening
==================================================================================

Comprehensive test suite verifying that diagnostic connection operations are
strictly non-blocking for callers, preserve J-1 hardware authority and J-6
production reliability, and eliminate UI freezes without architecture divergence.

Sections Covered:
  - Section A: Connection request returns immediately (non-blocking) under latency
  - Section B: CONNECTING state observable while connection attempt is active
  - Section C: Successful background connection reaches CONNECTED
  - Section D: Failed connection attempt reaches FAILED/ERROR with diagnostic reason
  - Section E: Repeated connection requests do not duplicate workers or corrupt state
  - Section F: Timeout enforcement transitions state out of CONNECTING
  - Section G: Worker exceptions are safely caught and surfaced without crash
  - Section H: Disconnect/shutdown during connection cancels without orphan threads
  - Section I: Adapter/serial resources not leaked on failure or cancellation (20 cycles)
  - Section J: Existing synchronous connection entry points remain valid for non-UI
  - Section K: Live runtime non-blocking delegation
  - Section L: Live presentation model connection badges (CONNECTING, FAILED, CONNECTED)
  - Section M: Connection failure does not diagnose vehicle fault (zero DTCs)
"""

import sys
import os
import time
import threading
import unittest
from typing import Optional, List, Dict

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterConnectionState,
    MockDiagnosticAdapter,
    ELM327DiagnosticAdapter,
    AdapterCapabilities,
    AdapterMetadata,
)
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_STARTING,
    LIVE_RUNNING,
    LIVE_ERROR,
    LIVE_STOPPED,
)


class FakeSerialMock:
    """Simulates PySerial serial.Serial object for non-hardware unit testing."""
    def __init__(self, port="COM3", baudrate=38400, is_open=True):
        self.port = port
        self.baudrate = baudrate
        self.is_open = is_open
        self.timeout = 1.0
        self._write_buffer = []

    def close(self):
        self.is_open = False

    def open(self):
        self.is_open = True

    def write(self, b):
        self._write_buffer.append(b)
        return len(b)

    def read(self, size=1):
        return b""

    def readline(self):
        return b"OK\r\n"

    def in_waiting(self):
        return 0


class FakeEngineMock:
    """Minimal engine mock for ELM327 adapter integration."""
    def __init__(self, should_succeed=True, connect_delay=0.0):
        self.ser = FakeSerialMock(is_open=False)
        self.should_succeed = should_succeed
        self.connect_delay = connect_delay
        self._connect_calls = 0
        self.vehicle_profile = None

    def baglan(self, profil=None):
        self._connect_calls += 1
        if self.connect_delay > 0:
            time.sleep(self.connect_delay)
        if self.should_succeed:
            self.ser.is_open = True
            return True
        else:
            self.ser.is_open = False
            return False

    def komut_gonder(self, komut: str, timeout: float = 1.0) -> List[str]:
        return ["OK"]


class TestPhaseK1NonBlockingConnection(unittest.TestCase):
    """Rigorous validation of Phase K-1 implementation criteria."""

    def test_section_a_connection_request_returns_immediately(self):
        """A: Connection request returns immediately (<80ms) while worker runs for 200ms."""
        adapter = MockDiagnosticAdapter(adapter_id="MOCK_ASYNC_A")
        adapter.force_connect_delay = 0.20  # 200ms simulated delay

        t_start = time.perf_counter()
        initiated = adapter.connect_async(timeout=2.0)
        t_elapsed = time.perf_counter() - t_start

        self.assertTrue(initiated, "Async connect initiation should return True")
        self.assertLess(t_elapsed, 0.08, f"connect_async must return immediately (took {t_elapsed:.4f}s)")
        
        # Cleanup
        adapter.disconnect()

    def test_section_b_connecting_state_observable(self):
        """B: CONNECTING state is observable by subscribers while connection attempt is active."""
        adapter = MockDiagnosticAdapter(adapter_id="MOCK_ASYNC_B")
        adapter.force_connect_delay = 0.15

        adapter.connect_async(timeout=2.0)
        # Immediately check observable state
        state_during = adapter.connection_state
        self.assertEqual(state_during, AdapterConnectionState.CONNECTING)

        # Wait for completion
        time.sleep(0.25)
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        adapter.disconnect()

    def test_section_c_successful_background_connection_reaches_connected(self):
        """C: Successful background connection transitions to CONNECTED and adapter becomes ready."""
        finished_event = threading.Event()
        callback_result = {}

        def on_finished(ok, err):
            callback_result["ok"] = ok
            callback_result["err"] = err
            finished_event.set()

        adapter = MockDiagnosticAdapter(adapter_id="MOCK_ASYNC_C")
        adapter.force_connect_delay = 0.05
        adapter.connect_async(timeout=2.0, on_finished=on_finished)

        self.assertTrue(finished_event.wait(timeout=1.0), "Callback must be invoked upon completion")
        self.assertTrue(callback_result["ok"])
        self.assertIsNone(callback_result["err"])
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        self.assertTrue(adapter.is_connected())
        adapter.disconnect()

    def test_section_d_failed_connection_reaches_failed_with_reason(self):
        """D: Failed connection attempt reaches FAILED/ERROR and records clear diagnostic reason."""
        finished_event = threading.Event()
        callback_result = {}

        def on_finished(ok, err):
            callback_result["ok"] = ok
            callback_result["err"] = err
            finished_event.set()

        adapter = MockDiagnosticAdapter(adapter_id="MOCK_ASYNC_D")
        adapter.force_connect_delay = 0.05
        adapter.force_connect_failure = True
        adapter.connect_async(timeout=2.0, on_finished=on_finished)

        self.assertTrue(finished_event.wait(timeout=1.0), "Callback must be invoked on failure")
        self.assertFalse(callback_result["ok"])
        self.assertIsNotNone(callback_result["err"])
        
        # State must be FAILED (which is equivalent to ERROR in contract)
        self.assertIn(adapter.connection_state, (AdapterConnectionState.FAILED, AdapterConnectionState.ERROR))
        self.assertFalse(adapter.is_connected())
        adapter.disconnect()

    def test_section_e_repeated_requests_do_not_duplicate_workers(self):
        """E: Repeated connection requests while CONNECTING do not duplicate workers."""
        adapter = MockDiagnosticAdapter(adapter_id="MOCK_ASYNC_E")
        adapter.force_connect_delay = 0.20

        first_call = adapter.connect_async(timeout=2.0)
        self.assertTrue(first_call)
        
        # Second call while in progress
        second_call = adapter.connect_async(timeout=2.0)
        self.assertFalse(second_call, "Duplicate connect_async call while CONNECTING must return False")

        # Wait to complete
        time.sleep(0.30)
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        adapter.disconnect()

    def test_section_f_timeout_enforcement_surfaces_properly(self):
        """F: Timeout enforcement transitions state out of CONNECTING."""
        finished_event = threading.Event()
        callback_result = {}

        def on_finished(ok, err):
            callback_result["ok"] = ok
            callback_result["err"] = err
            finished_event.set()

        adapter = MockDiagnosticAdapter(adapter_id="MOCK_ASYNC_F")
        adapter.force_connect_delay = 0.50  # Work takes 500ms
        adapter.connect_async(timeout=0.08, on_finished=on_finished)  # Timeout at 80ms

        self.assertTrue(finished_event.wait(timeout=1.5), "Timeout must fire callback")
        self.assertFalse(callback_result["ok"])
        self.assertIsNotNone(callback_result["err"])
        self.assertIn("timed out", str(callback_result["err"]).lower())
        self.assertIn(adapter.connection_state, (AdapterConnectionState.FAILED, AdapterConnectionState.ERROR))
        adapter.disconnect()

    def test_section_g_worker_exceptions_surfaced_without_unhandled_crash(self):
        """G: Worker exceptions in _do_connect are safely captured and callback receives exception."""
        class CrashingAdapter(MockDiagnosticAdapter):
            def _do_connect(self, timeout: float = 5.0) -> bool:
                raise RuntimeError("Simulated serial port hardware I/O fault")

        finished_event = threading.Event()
        callback_result = {}

        def on_finished(ok, err):
            callback_result["ok"] = ok
            callback_result["err"] = err
            finished_event.set()

        adapter = CrashingAdapter(adapter_id="MOCK_CRASH_G")
        adapter.connect_async(timeout=2.0, on_finished=on_finished)

        self.assertTrue(finished_event.wait(timeout=1.0))
        self.assertFalse(callback_result["ok"])
        self.assertIsNotNone(callback_result["err"])
        self.assertTrue(
            isinstance(callback_result["err"], RuntimeError) or "hardware I/O fault" in str(callback_result["err"]),
            f"Expected RuntimeError or message containing fault, got: {callback_result['err']}"
        )
        self.assertEqual(adapter.connection_state, AdapterConnectionState.FAILED)
        adapter.disconnect()

    def test_section_h_disconnect_shutdown_during_connection_no_leak(self):
        """H: Disconnect/shutdown while connecting cancels and cleans up without orphan threads."""
        adapter = MockDiagnosticAdapter(adapter_id="MOCK_CANCEL_H")
        adapter.force_connect_delay = 0.50  # Slow connection

        threads_before = threading.active_count()
        adapter.connect_async(timeout=2.0)
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTING)

        # Immediate disconnect during connection
        time.sleep(0.02)
        adapter.disconnect()

        self.assertEqual(adapter.connection_state, AdapterConnectionState.DISCONNECTED)
        time.sleep(0.10)
        threads_after = threading.active_count()
        self.assertLessEqual(threads_after, threads_before + 1, "No runaway background threads left")

    def test_section_i_adapter_serial_resources_not_leaked(self):
        """I: Adapter resources are not leaked after 20 repeated async connect/disconnect cycles."""
        engine_mock = FakeEngineMock(should_succeed=True, connect_delay=0.01)
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_RESOURCES_I",
            engine=engine_mock,
        )

        threads_baseline = threading.active_count()

        for _ in range(20):
            ev = threading.Event()
            adapter.connect_async(timeout=1.0, on_finished=lambda ok, err: ev.set())
            ev.wait(timeout=0.5)
            self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
            adapter.disconnect()
            self.assertEqual(adapter.connection_state, AdapterConnectionState.DISCONNECTED)

        # Allow any OS thread cleanup to settle
        time.sleep(0.05)
        threads_current = threading.active_count()
        self.assertLessEqual(threads_current, threads_baseline + 1, "Thread count should return to baseline")

    def test_section_j_existing_synchronous_connection_remains_valid(self):
        """J: Existing synchronous adapter.connect() and runtime.connect() remain valid for non-UI."""
        engine_mock = FakeEngineMock(should_succeed=True, connect_delay=0.0)
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_SYNC_J",
            engine=engine_mock,
        )
        ok = adapter.connect(timeout=2.0)
        self.assertTrue(ok)
        self.assertTrue(adapter.is_connected())
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        adapter.disconnect()
        self.assertEqual(adapter.connection_state, AdapterConnectionState.DISCONNECTED)

    def test_section_k_live_runtime_nonblocking_delegation(self):
        """K: LiveAcquisitionRuntime exposes connection_state, is_connected, and connect_async."""
        engine_mock = FakeEngineMock(should_succeed=True, connect_delay=0.02)
        adapter = MockDiagnosticAdapter(adapter_id="MOCK_RUNTIME_K")
        adapter.force_connect_delay = 0.05

        runtime = LiveAcquisitionRuntime(engine=engine_mock, adapter=adapter)
        self.assertEqual(runtime.connection_state, AdapterConnectionState.DISCONNECTED)
        self.assertFalse(runtime.is_connected())

        ev = threading.Event()
        res = []
        runtime.connect_async(timeout=1.0, on_finished=lambda ok, err: (res.append(ok), ev.set()))
        self.assertEqual(runtime.connection_state, AdapterConnectionState.CONNECTING)

        ev.wait(timeout=1.0)
        self.assertTrue(res[0])
        self.assertTrue(runtime.is_connected())
        self.assertEqual(runtime.connection_state, AdapterConnectionState.CONNECTED)

        # Now start runtime
        start_ok = runtime.start()
        self.assertTrue(start_ok)
        self.assertEqual(runtime.get_state(), LIVE_RUNNING)

        runtime.stop()
        self.assertIn(runtime.get_state(), (LIVE_STOPPED, LIVE_IDLE))

    def test_section_l_live_presentation_model_connection_badges(self):
        """L: LivePresentationModel formats CONNECTING, FAILED, and connected states properly."""
        from live_ui import LivePresentationModel

        # CONNECTING state
        badge_c = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_IDLE,
            is_serial_open=False,
            connection_state="CONNECTING"
        )
        self.assertEqual(badge_c["status"], "BAĞLANIYOR...")
        self.assertEqual(badge_c["bg"], "#F1C40F")

        # FAILED state
        badge_f = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_IDLE,
            is_serial_open=False,
            connection_state="FAILED"
        )
        self.assertEqual(badge_f["status"], "BAĞLANTI HATASI")
        self.assertEqual(badge_f["bg"], "#E74C3C")

        # CONNECTED state
        badge_ok = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_RUNNING,
            is_serial_open=True,
            connection_state="CONNECTED"
        )
        self.assertEqual(badge_ok["status"], "BAĞLI VE AKTİF")
        self.assertEqual(badge_ok["bg"], "#2ECC71")

    def test_section_m_connection_failure_not_vehicle_fault(self):
        """M: Verify connection failure does not trigger DTC reasoning or diagnose vehicle fault."""
        engine_mock = FakeEngineMock(should_succeed=False, connect_delay=0.0)
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_FAIL_M",
            engine=engine_mock,
        )
        runtime = LiveAcquisitionRuntime(engine=engine_mock, adapter=adapter)
        
        ok = runtime.connect(timeout=1.0)
        self.assertFalse(ok)
        self.assertEqual(runtime.connection_state, AdapterConnectionState.FAILED)
        
        # Verify DTC lifecycle engine has zero DTCs created or resolved from this failure
        if runtime.dtc_lifecycle_engine:
            active_dtcs = runtime.dtc_lifecycle_engine.get_active_dtcs()
            self.assertEqual(len(active_dtcs), 0, "Connection failure must never generate vehicle DTCs")


if __name__ == "__main__":
    unittest.main()
