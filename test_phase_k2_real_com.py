"""
test_phase_k2_real_com.py - Phase K-2: Real Windows COM Selection & Hardware Arbitration Test Suite
=====================================================================================================

Comprehensive test suite verifying that Seyyanen connects strictly to real physical/Bluetooth
COM ports and NEVER silently falls back to COM_MOCK / MockSerial in normal user mode.

Covered Scenarios:
  A. Real COM enumeration (prioritizes VCI / Bluetooth / USB serial)
  B. Explicit COM selection (user specified port bypasses discovery)
  C. Candidate probing (safe read-only ATZ/ATI handshake)
  D. Invalid/non-ELM327 COM rejection (incoming Bluetooth port or non-responsive port rejected)
  E. Successful ELM327 detection (dual Bluetooth arbitration: COM3 fails, COM4 succeeds)
  F. No-device truthful failure (raises AdapterUnavailableError; no silent simulation)
  G. Mock mode explicitly enabled (simulation=True allows MockSerial)
  H. Mock mode not silently activated (normal connection with no adapter FAILS truthfully)
  I. GUI/runtime connection state transitions (truthful presentation badges)
  J. Shutdown/close after failed probe (handles properly closed)
  K. No leaked serial handles across multi-candidate probe loops
  L. Existing K-1/K-3 invariants remain valid (read-only safety, non-blocking connect)
"""

import sys
import os
import time
import threading
import unittest
from typing import Optional, List, Dict, Any
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serial
from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterConnectionState,
    AdapterType,
    TransportMedium,
    ELM327DiagnosticAdapter,
    ELM327TransportStage,
    PortProbeResult,
    MockSerialForELM,
    AdapterConnectionError,
    AdapterUnavailableError,
    enumerate_candidate_ports,
    probe_elm327_port,
    discover_and_probe_elm327,
    list_available_com_ports,
    cli_probe_port,
    log_real_connect,
)
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_STARTING,
    LIVE_RUNNING,
    LIVE_ERROR,
    LIVE_STOPPED,
)
from live_ui import LivePresentationModel
from motor import AutoExpertEngine, port_secici, is_simulation_mode


class MockPortInfo:
    """Simulates serial.tools.list_ports.ListPortInfo object returned by pyserial."""
    def __init__(self, device: str, description: str = "", hwid: str = ""):
        self.device = device
        self.description = description
        self.hwid = hwid


class FakeCandidateSerial:
    """
    Simulated serial connection for probing specific COM candidates.
    Allows simulating:
      - Clean ELM327 response (e.g. COM4 outgoing)
      - vLinker response (e.g. vLinker MC+ v2.2)
      - Silent timeout / hang (e.g. COM3 incoming Bluetooth)
      - Access denied / permission error
      - Garbage / non-ELM327 data
    """
    def __init__(
        self,
        port: str,
        baudrate: int = 38400,
        timeout: float = 1.0,
        write_timeout: float = 1.0,
        behavior: str = "ok",  # "ok", "vlinker", "timeout", "garbage", "error"
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.behavior = behavior
        self.is_open = True
        self.closed = False
        self._tx_buf = bytearray()
        self._rx_buf = bytearray()

        if behavior == "error":
            self.is_open = False
            raise serial.SerialException(f"Access denied on {port}")

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise serial.SerialException("Port is closed")
        self._tx_buf.extend(data)
        if b"\r" in data or b"\n" in data:
            cmd = bytes(self._tx_buf).decode("ascii", errors="replace").strip().upper()
            cmd_clean = cmd.replace(" ", "")
            self._tx_buf.clear()
            if self.behavior == "ok":
                if "ATZ" in cmd_clean or "ATI" in cmd_clean:
                    self._rx_buf.extend(b"\r\rELM327 v1.5\r\r>")
                elif cmd.startswith("AT"):
                    self._rx_buf.extend(b"OK\r\r>")
                elif cmd == "0100":
                    self._rx_buf.extend(b"41 00 BE 1F B8 10\r\r>")
                else:
                    self._rx_buf.extend(b"NO DATA\r\r>")
            elif self.behavior == "vlinker":
                if "ATZ" in cmd_clean or "ATI" in cmd_clean or "ATWS" in cmd_clean:
                    self._rx_buf.extend(b"\r\rvLinker MC+ v2.2 MICROSYS\r\r>")
                elif cmd.startswith("AT"):
                    self._rx_buf.extend(b"OK\r\r>")
                elif cmd == "0100":
                    self._rx_buf.extend(b"41 00 BE 1F B8 10\r\r>")
                else:
                    self._rx_buf.extend(b"NO DATA\r\r>")
            elif self.behavior == "garbage":
                self._rx_buf.extend(b"\xaa\xbb\xcc\xff\x00\x01\x02")
            elif self.behavior == "timeout":
                # Do nothing, simulate complete silence
                pass
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise serial.SerialException("Port is closed")
        if not self._rx_buf:
            return b""
        chunk = self._rx_buf[:size]
        self._rx_buf = self._rx_buf[size:]
        return bytes(chunk)

    def reset_input_buffer(self) -> None:
        self._rx_buf.clear()

    def reset_output_buffer(self) -> None:
        self._tx_buf.clear()

    def close(self) -> None:
        self.is_open = False
        self.closed = True
        self._rx_buf.clear()
        self._tx_buf.clear()


class TestPhaseK2RealCOM(unittest.TestCase):
    """Rigorous certification suite for Real Windows COM Port Selection."""

    # -----------------------------------------------------------------
    # A. Real COM enumeration
    # -----------------------------------------------------------------
    def test_A_real_com_enumeration(self):
        """A: Candidate enumeration discovers Windows COM ports and prioritizes VCI/Bluetooth candidates."""
        mock_ports = [
            MockPortInfo("COM1", "Communications Port", "ACPI\\PNP0501"),
            MockPortInfo("COM3", "Standard Serial over Bluetooth link (COM3)", "BTHENUM\\{...}"),
            MockPortInfo("COM4", "Standard Serial over Bluetooth link (COM4)", "BTHENUM\\{...}"),
            MockPortInfo("COM7", "USB-SERIAL CH340 (COM7)", "USB\\VID_1A86&PID_7523"),
        ]
        with patch("serial.tools.list_ports.comports", return_value=mock_ports):
            candidates = enumerate_candidate_ports()
            devices = [c["device"] for c in candidates]
            # USB VCI (CH340) must be prioritized first
            self.assertEqual(devices[0], "COM7")
            # Bluetooth serial ports must follow
            self.assertIn("COM3", devices)
            self.assertIn("COM4", devices)
            # Generic COM1 must be at the end
            self.assertEqual(devices[-1], "COM1")

    # -----------------------------------------------------------------
    # B. Explicit COM selection
    # -----------------------------------------------------------------
    def test_B_explicit_com_selection(self):
        """B: When explicit COM port is specified, discovery is bypassed and port is targeted directly."""
        candidates = enumerate_candidate_ports("COM4")
        self.assertEqual([c["device"] for c in candidates], ["COM4"])

        candidates_lower = enumerate_candidate_ports("com3")
        self.assertEqual([c["device"] for c in candidates_lower], ["COM3"])

    # -----------------------------------------------------------------
    # C. Candidate probing (Valid ELM327)
    # -----------------------------------------------------------------
    def test_C_candidate_probing_valid_elm327(self):
        """C: Probing an ELM327 candidate returns structured PortProbeResult with adapter_detected=True."""
        opened_ports = []
        def factory(port="COM4", baudrate=38400, **kw):
            p = FakeCandidateSerial(port=port, baudrate=baudrate, behavior="ok", **kw)
            opened_ports.append(p)
            return p

        res = probe_elm327_port("COM4", baudrates=[38400], timeout=1.0, serial_factory=factory)
        self.assertIsNotNone(res)
        self.assertEqual(res.port, "COM4")
        self.assertEqual(res.transport, "serial")
        self.assertTrue(res.adapter_detected)
        self.assertEqual(res.connection_state, "CONNECTED")
        self.assertIn("ELM327", res.adapter_identity)
        self.assertIsNone(res.failure_reason)
        # Probe connection must be closed after probe
        self.assertTrue(opened_ports[0].closed)

    # -----------------------------------------------------------------
    # D. Invalid/non-ELM327 COM rejection
    # -----------------------------------------------------------------
    def test_D_invalid_non_elm327_com_rejection(self):
        """D: Non-responsive (incoming Bluetooth) or garbage-spewing ports are rejected truthfully."""
        # 1. Timeout candidate (e.g. incoming Bluetooth port)
        res_timeout = probe_elm327_port(
            "COM3",
            baudrates=[38400],
            timeout=0.3,
            serial_factory=lambda port=None, baudrate=38400, **kw: FakeCandidateSerial(port or "COM3", baudrate, behavior="timeout", **kw),
        )
        self.assertIn(res_timeout.failure_reason, ("TIMEOUT", "TIMEOUT_NO_RESPONSE", "NO_ELM327_RESPONSE"))

        # 2. Garbage candidate
        res_garbage = probe_elm327_port(
            "COM5",
            baudrates=[38400],
            timeout=0.3,
            serial_factory=lambda port=None, baudrate=38400, **kw: FakeCandidateSerial(port or "COM5", baudrate, behavior="garbage", **kw),
        )
        self.assertFalse(res_garbage.adapter_detected)
        self.assertEqual(res_garbage.connection_state, "FAILED")

        # 3. Access denied candidate
        res_err = probe_elm327_port(
            "COM6",
            baudrates=[38400],
            timeout=0.3,
            serial_factory=lambda port=None, baudrate=38400, **kw: FakeCandidateSerial(port or "COM6", baudrate, behavior="error", **kw),
        )
        self.assertFalse(res_err.adapter_detected)
        self.assertEqual(res_err.connection_state, "FAILED")

    # -----------------------------------------------------------------
    # E. Successful ELM327 detection (Dual Bluetooth arbitration)
    # -----------------------------------------------------------------
    def test_E_dual_bluetooth_arbitration(self):
        """E: When COM3 is incoming (times out) and COM4 is outgoing (responds), COM4 is chosen."""
        mock_ports = [
            MockPortInfo("COM3", "Standard Serial over Bluetooth link (COM3)"),
            MockPortInfo("COM4", "Standard Serial over Bluetooth link (COM4)"),
        ]

        def factory(port, baudrate, **kw):
            if port == "COM3":
                return FakeCandidateSerial(port, baudrate, behavior="timeout", **kw)
            elif port == "COM4":
                return FakeCandidateSerial(port, baudrate, behavior="ok", **kw)
            return FakeCandidateSerial(port, baudrate, behavior="error", **kw)

        with patch("serial.tools.list_ports.comports", return_value=mock_ports):
            winner, all_probes = discover_and_probe_elm327(
                serial_factory=factory,
                timeout_per_port=0.3,
            )
            self.assertIsNotNone(winner)
            self.assertEqual(winner.port, "COM4")
            self.assertTrue(winner.adapter_detected)
            self.assertEqual(len(all_probes), 2)
            # First candidate (COM3) failed
            self.assertFalse(all_probes[0].adapter_detected)
            # Second candidate (COM4) succeeded
            self.assertTrue(all_probes[1].adapter_detected)

    # -----------------------------------------------------------------
    # F. No-device truthful failure
    # -----------------------------------------------------------------
    def test_F_no_device_truthful_failure(self):
        """F: If no real COM ports exist or none respond, adapter raises AdapterUnavailableError."""
        # Case 1: No ports at all
        with patch("serial.tools.list_ports.comports", return_value=[]):
            adapter = ELM327DiagnosticAdapter(adapter_id="TEST_NO_DEVICE", simulation=False)
            with self.assertRaises(AdapterUnavailableError) as ctx:
                adapter.connect(timeout=1.0)
            self.assertIn("No compatible ELM327 adapter detected", str(ctx.exception))
            self.assertFalse(adapter.is_connected())
            self.assertEqual(adapter.connection_state, AdapterConnectionState.FAILED)
            # Verify MockSerial was NOT instantiated
            self.assertNotEqual(adapter.port, "COM_MOCK")

        # Case 2: Ports exist but none respond
        mock_ports = [MockPortInfo("COM3", "Bluetooth Serial Port")]
        with patch("serial.tools.list_ports.comports", return_value=mock_ports):
            adapter2 = ELM327DiagnosticAdapter(
                adapter_id="TEST_NO_RESPONSE",
                simulation=False,
                serial_factory=lambda p, b, **kw: FakeCandidateSerial(p, b, behavior="timeout", **kw),
            )
            with self.assertRaises(AdapterUnavailableError):
                adapter2.connect(timeout=0.5)
            self.assertFalse(adapter2.is_connected())
            self.assertNotEqual(adapter2.port, "COM_MOCK")

    # -----------------------------------------------------------------
    # G. Mock mode explicitly enabled
    # -----------------------------------------------------------------
    def test_G_mock_mode_explicitly_enabled(self):
        """G: Mock mode is strictly allowed ONLY when explicitly requested (simulation=True)."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="EXPLICIT_MOCK",
            simulation=True,
        )
        ok = adapter.connect(timeout=1.0)
        self.assertTrue(ok)
        self.assertTrue(adapter.is_connected())
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        self.assertEqual(adapter.port, "COM_MOCK")
        adapter.disconnect()

    # -----------------------------------------------------------------
    # H. Mock mode not silently activated
    # -----------------------------------------------------------------
    def test_H_mock_mode_not_silently_activated(self):
        """H: When simulation=False, connection attempt NEVER falls back to COM_MOCK or MockSerial."""
        with patch("serial.tools.list_ports.comports", return_value=[]):
            # 1. Test at motor.py level
            engine = AutoExpertEngine(simulation=False)
            ok = engine.baglan(simulation=False)
            self.assertFalse(ok)
            self.assertNotEqual(engine.bagli_port, "COM_MOCK")

            # 2. Test port_secici level
            chosen_port = port_secici(simulation=False)
            self.assertIsNone(chosen_port)
            self.assertNotEqual(chosen_port, "COM_MOCK")

            # 3. Test runtime level
            runtime = LiveAcquisitionRuntime(simulation=False)
            conn_ok = runtime.connect(timeout=0.5)
            self.assertFalse(conn_ok)
            self.assertEqual(runtime.connection_state, AdapterConnectionState.FAILED)
            self.assertNotEqual(getattr(runtime.adapter, "port", None), "COM_MOCK")

    # -----------------------------------------------------------------
    # I. GUI/runtime connection state
    # -----------------------------------------------------------------
    def test_I_gui_runtime_connection_state(self):
        """I: GUI presentation badges accurately reflect real COM status vs simulation."""
        # Real connection success badge
        badge_real = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_RUNNING,
            is_serial_open=True,
            connection_state="CONNECTED",
            is_simulation=False,
            port="COM4",
        )
        self.assertEqual(badge_real["status"], "BAĞLI: COM4")
        self.assertIn("COM4", badge_real["detail"])

        # Real connection failure badge
        badge_fail = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_ERROR,
            is_serial_open=False,
            connection_state="FAILED",
            is_simulation=False,
            port=None,
        )
        self.assertEqual(badge_fail["status"], "BAĞLANTI HATASI")

        # Explicit simulation badge
        badge_sim = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_RUNNING,
            is_serial_open=True,
            connection_state="CONNECTED",
            is_simulation=True,
            port="COM_MOCK",
        )
        self.assertEqual(badge_sim["status"], "SİMÜLASYON (COM_MOCK)")

    # -----------------------------------------------------------------
    # J & K. Shutdown / close after failed probe & no leaked handles
    # -----------------------------------------------------------------
    def test_J_and_K_probe_handles_cleaned_up_without_leak(self):
        """J & K: Serial instances opened during probing are closed immediately without handle leaks."""
        created_serials = []
        def tracking_factory(port, baudrate, **kw):
            s = FakeCandidateSerial(port, baudrate, behavior="timeout", **kw)
            created_serials.append(s)
            return s

        candidates = ["COM3", "COM4", "COM5"]
        with patch("serial.tools.list_ports.comports", return_value=[MockPortInfo(c) for c in candidates]):
            discover_and_probe_elm327(serial_factory=tracking_factory, timeout_per_port=0.1)

        # Ports are closed without leaks (early break skips alternate bauds on silent ports)
        self.assertGreaterEqual(len(created_serials), 3)
        for s in created_serials:
            self.assertTrue(s.closed, f"Serial port {s.port} was left unclosed after probing!")
            self.assertFalse(s.is_open)

    # -----------------------------------------------------------------
    # L. Existing K-1/K-3 invariants remain valid
    # -----------------------------------------------------------------
    def test_L_k1_k3_invariants_preserved(self):
        """L: Async non-blocking connection and trusted acquisition pipeline remain intact."""
        mock_ports = [MockPortInfo("COM4", "ELM327 Interface")]
        def factory(port="COM4", baudrate=38400, **kw):
            return FakeCandidateSerial(port=port, baudrate=baudrate, behavior="ok", **kw)

        with patch("serial.tools.list_ports.comports", return_value=mock_ports):
            adapter = ELM327DiagnosticAdapter(
                adapter_id="INVARIANTS_TEST",
                port="COM4",
                simulation=False,
                serial_factory=factory,
            )
            runtime = LiveAcquisitionRuntime(adapter=adapter, simulation=False)

            ev = threading.Event()
            res = []
            runtime.connect_async(timeout=2.0, on_finished=lambda ok, err: (res.append(ok), ev.set()))
            self.assertIn(runtime.connection_state, (AdapterConnectionState.CONNECTING, AdapterConnectionState.CONNECTED))

            ev.wait(timeout=2.0)
            self.assertTrue(res[0])
            self.assertEqual(runtime.connection_state, AdapterConnectionState.CONNECTED)
            self.assertEqual(runtime.adapter.port, "COM4")
            runtime.stop()

    # -----------------------------------------------------------------
    # REGRESSION TEST: Click "OBD Connect" in normal production mode
    # -----------------------------------------------------------------
    def test_11_regression_obd_connect_never_falls_back_to_mock(self):
        """
        REGRESSION PROOF (Section 11):
        Clicking 'OBD Connect' in normal production mode with no real hardware available:
          - MUST NOT connect to COM_MOCK.
          - MUST NOT start MockSerial.
          - MUST report truthful failure.
        """
        with patch("serial.tools.list_ports.comports", return_value=[]):
            engine = AutoExpertEngine(simulation=False)
            runtime = LiveAcquisitionRuntime(engine=engine, simulation=False)

            # Attempt connection as performed by LiveConnectWorker
            ok = runtime.connect(timeout=1.0)
            self.assertFalse(ok, "Connection must NOT succeed when no physical adapter is present")
            self.assertEqual(runtime.connection_state, AdapterConnectionState.FAILED)
            self.assertNotEqual(engine.bagli_port, "COM_MOCK")
            self.assertNotEqual(getattr(runtime.adapter, "port", None), "COM_MOCK")

    # -----------------------------------------------------------------
    # VLinker Hardware Banner & Identity Validation
    # -----------------------------------------------------------------
    def test_vlinker_hardware_response_accepted(self):
        """VLinker adapters reporting 'vLinker MC+ v2.2...' must be accepted and initialized."""
        mock_ports = [MockPortInfo("COM4", "vLinker MC+ Bluetooth")]
        def factory(port="COM4", baudrate=38400, **kw):
            return FakeCandidateSerial(port=port, baudrate=baudrate, behavior="vlinker", **kw)

        with patch("serial.tools.list_ports.comports", return_value=mock_ports):
            adapter = ELM327DiagnosticAdapter(
                adapter_id="VLINKER_TEST",
                port="COM4",
                simulation=False,
                serial_factory=factory,
            )
            ok = adapter.connect(timeout=2.0)
            self.assertTrue(ok)
            self.assertTrue(adapter.is_connected())
            self.assertIn("vLinker", adapter.elm_version)
            self.assertEqual(adapter.transport_stage, ELM327TransportStage.VEHICLE_PROTOCOL_READY)
            adapter.disconnect()

    # -----------------------------------------------------------------
    # CLI Explicit Probe Port Command
    # -----------------------------------------------------------------
    def test_cli_probe_port_outcomes(self):
        """Section 5: cli_probe_port returns correct outcomes for various adapter states."""
        # 1. ELM327 / VLinker success
        res_ok = cli_probe_port(
            "COM4",
            serial_factory=lambda port, baudrate, **kw: FakeCandidateSerial(port, baudrate, behavior="ok", **kw),
        )
        self.assertEqual(res_ok, "ELM327_DETECTED")

        res_vlinker = cli_probe_port(
            "COM4",
            serial_factory=lambda port, baudrate, **kw: FakeCandidateSerial(port, baudrate, behavior="vlinker", **kw),
        )
        self.assertEqual(res_vlinker, "ELM327_DETECTED")

        # 2. Timeout
        res_timeout = cli_probe_port(
            "COM3",
            serial_factory=lambda port, baudrate, **kw: FakeCandidateSerial(port, baudrate, behavior="timeout", **kw),
        )
        self.assertEqual(res_timeout, "TIMEOUT")

        # 3. Access Denied / Port Busy
        res_busy = cli_probe_port(
            "COM3",
            serial_factory=lambda port, baudrate, **kw: FakeCandidateSerial(port, baudrate, behavior="error", **kw),
        )
        self.assertEqual(res_busy, "PORT_BUSY")

        # 4. Garbage / Invalid Response
        res_garbage = cli_probe_port(
            "COM5",
            serial_factory=lambda port, baudrate, **kw: FakeCandidateSerial(port, baudrate, behavior="garbage", **kw),
        )
        self.assertEqual(res_garbage, "INVALID_RESPONSE")

    # -----------------------------------------------------------------
    # No Duplicate Serial Handle Ownership
    # -----------------------------------------------------------------
    def test_no_duplicate_serial_handles_during_connect(self):
        """Section 7: Probe handle is cleanly closed before persistent connection opens."""
        opened_handles: List[FakeCandidateSerial] = []
        def factory(port="COM4", baudrate=38400, **kw):
            s = FakeCandidateSerial(port=port, baudrate=baudrate, behavior="ok", **kw)
            opened_handles.append(s)
            return s

        mock_ports = [
            MockPortInfo("COM3", "Bluetooth Incoming"),
            MockPortInfo("COM4", "Bluetooth Outgoing"),
        ]
        with patch("serial.tools.list_ports.comports", return_value=mock_ports):
            adapter = ELM327DiagnosticAdapter(
                adapter_id="DUP_TEST",
                simulation=False,
                serial_factory=factory,
            )
            ok = adapter.connect(timeout=2.0)
            self.assertTrue(ok)

            # Check that only the active persistent handle is open; probe handle was closed
            open_count = sum(1 for h in opened_handles if h.is_open and not h.closed)
            self.assertEqual(open_count, 1, "Exactly one serial handle must be active at any time")
            adapter.disconnect()
            open_count_after = sum(1 for h in opened_handles if h.is_open and not h.closed)
            self.assertEqual(open_count_after, 0, "All handles must be closed after disconnect")

    # -----------------------------------------------------------------
    # Structured REAL-CONNECT Logging
    # -----------------------------------------------------------------
    def test_real_connect_structured_logging(self):
        """Section 2: [REAL-CONNECT] messages are emitted during candidate discovery and connection."""
        import io
        import contextlib

        mock_ports = [
            MockPortInfo("COM3", "Bluetooth Incoming"),
            MockPortInfo("COM4", "Bluetooth Outgoing"),
        ]
        def factory(port="COM4", baudrate=38400, **kw):
            behavior = "timeout" if port == "COM3" else "ok"
            return FakeCandidateSerial(port=port, baudrate=baudrate, behavior=behavior, **kw)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with patch("serial.tools.list_ports.comports", return_value=mock_ports):
                adapter = ELM327DiagnosticAdapter(
                    adapter_id="LOG_TEST",
                    simulation=False,
                    serial_factory=factory,
                )
                adapter.connect(timeout=2.0)
                adapter.disconnect()

        output = buf.getvalue()
        self.assertIn("[REAL-CONNECT] Starting physical adapter discovery", output)
        self.assertIn("[REAL-CONNECT] Enumerating Windows COM ports", output)
        self.assertIn("[REAL-CONNECT] Candidate: COM3", output)
        self.assertIn("[REAL-CONNECT] Candidate: COM4", output)
        self.assertIn("[REAL-CONNECT] Probing COM3", output)
        self.assertIn("[REAL-CONNECT] COM3 rejected: reason=TIMEOUT", output)
        self.assertIn("[REAL-CONNECT] Probing COM4", output)
        self.assertIn("[REAL-CONNECT] ELM327 detected on COM4", output)
        self.assertIn("[REAL-CONNECT] Establishing active connection on COM4", output)


if __name__ == "__main__":
    unittest.main()
