"""
Seyyanen Diagnostic Architecture — Phase K-2 Virtual ELM327 Test Suite
======================================================================
Comprehensive test suite validating the Virtual ELM327 test harness,
VirtualSerialTransport abstraction, fault injection, latency configuration,
adapter lifecycle, and non-MockSerial production safety invariants.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from virtual_elm327 import (
    VirtualELM327Responder,
    VirtualSerialTransport,
    create_virtual_serial_factory,
    SerialException,
)
from diagnostic_adapter import (
    ELM327DiagnosticAdapter,
    probe_elm327_port,
    discover_and_probe_elm327,
    enumerate_candidate_ports,
    AdapterConnectionState,
    ELM327TransportStage,
    STATUS_SERIAL_ERROR,
)
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_RUNNING,
    LIVE_IDLE,
)
from live_ui import LivePresentationModel
from motor import (
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_NO_CONNECTION,
)


class TestVirtualELM327Harness(unittest.TestCase):
    """Deterministic validation of the Virtual ELM327 responder and transport."""

    def setUp(self):
        self.responder = VirtualELM327Responder()
        self.v_factory = create_virtual_serial_factory(responder=self.responder, latency=0.0)

    # -----------------------------------------------------------------
    # 1. Virtual ATI & ATZ
    # -----------------------------------------------------------------
    def test_01_virtual_ati_and_atz(self):
        """ATI and ATZ commands return faithful firmware banners ending with prompt '>'."""
        # Test ATZ
        resp_atz = self.responder.handle_command("ATZ")
        self.assertIn("ELM327 v2.2", resp_atz)
        self.assertTrue(resp_atz.endswith(">"), "Response must terminate with '>' prompt")

        # Test AT Z (with space)
        resp_atz_sp = self.responder.handle_command("AT Z")
        self.assertIn("ELM327 v2.2", resp_atz_sp)
        self.assertTrue(resp_atz_sp.endswith(">"))

        # Test ATI
        resp_ati = self.responder.handle_command("ATI")
        self.assertIn("ELM327 v2.2", resp_ati)
        self.assertTrue(resp_ati.endswith(">"))

        # Test ATWS (Warm Start)
        resp_ws = self.responder.handle_command("AT WS")
        self.assertIn("ELM327 v2.2", resp_ws)
        self.assertTrue(resp_ws.endswith(">"))

    # -----------------------------------------------------------------
    # 2. Virtual 0100 & 010C (OBD Mode 01 PIDs)
    # -----------------------------------------------------------------
    def test_02_virtual_0100_and_010c(self):
        """Mode 01 PID queries return valid hexadecimal representations and decodable values."""
        # PID 0100 (Supported PIDs)
        resp_0100 = self.responder.handle_command("0100")
        self.assertIn("4100 BE 3E B8 13", resp_0100)
        self.assertTrue(resp_0100.endswith(">"))

        # PID 010C (Engine RPM: 1726 RPM)
        resp_010c = self.responder.handle_command("010C")
        self.assertIn("410C 1A F8", resp_010c)
        self.assertTrue(resp_010c.endswith(">"))

        # PID 0105 (ECT: 50°C)
        resp_0105 = self.responder.handle_command("0105")
        self.assertIn("4105 5A", resp_0105)

        # PID 010B (MAP: 45 kPa)
        resp_010b = self.responder.handle_command("010B")
        self.assertIn("410B 2D", resp_010b)

        # PID 0111 (TPS: 12.5%)
        resp_0111 = self.responder.handle_command("0111")
        self.assertIn("4111 20", resp_0111)

    # -----------------------------------------------------------------
    # 3. Unknown Command Handling
    # -----------------------------------------------------------------
    def test_03_unknown_commands(self):
        """Unknown OBD PIDs return 'NO DATA' and unknown AT commands return '?'."""
        # Unknown OBD Mode 01 PID
        resp_obd = self.responder.handle_command("01FF")
        self.assertEqual(resp_obd, "NO DATA\r\r>")

        # Unknown AT command
        resp_at = self.responder.handle_command("AT FOOBAR")
        self.assertEqual(resp_at, "?\r\r>")

        # Unknown raw command
        resp_unk = self.responder.handle_command("INVALID_CMD_XYZ")
        self.assertEqual(resp_unk, "?\r\r>")

    # -----------------------------------------------------------------
    # 4. Prompt Character ('>') Parsing
    # -----------------------------------------------------------------
    def test_04_prompt_parsing(self):
        """All valid responder outputs must be safely delimited and terminate with '>'."""
        commands = ["ATZ", "ATI", "ATE0", "ATL0", "ATS0", "ATH1", "AT SP 0", "AT DPN", "AT DP", "ATRV", "0100", "010C", "0199", "AT_UNKNOWN"]
        for cmd in commands:
            resp = self.responder.handle_command(cmd)
            self.assertTrue(resp.endswith(">"), f"Command '{cmd}' response did not end with '>': {repr(resp)}")
            self.assertTrue(resp.endswith("\r\r>"), f"Command '{cmd}' response did not end with '\\r\\r>': {repr(resp)}")

    # -----------------------------------------------------------------
    # 5. Latency Configuration
    # -----------------------------------------------------------------
    def test_05_latency_configuration(self):
        """VirtualSerialTransport accurately honors deterministic latency configuration."""
        transport_instant = VirtualSerialTransport(responder=self.responder, latency=0.0)
        t0 = time.monotonic()
        transport_instant.write(b"0100\r")
        _ = transport_instant.read(transport_instant.in_waiting)
        dur_instant = time.monotonic() - t0
        self.assertLess(dur_instant, 0.04, "Instant latency should be near-zero")

        # 50ms latency
        transport_50ms = VirtualSerialTransport(responder=self.responder, latency=0.05)
        t0 = time.monotonic()
        transport_50ms.write(b"0100\r")
        _ = transport_50ms.read(transport_50ms.in_waiting)
        dur_50ms = time.monotonic() - t0
        self.assertGreaterEqual(dur_50ms, 0.045, "50ms latency was not honored")

        # 100ms latency
        transport_100ms = VirtualSerialTransport(responder=self.responder, latency=0.10)
        t0 = time.monotonic()
        transport_100ms.write(b"0100\r")
        _ = transport_100ms.read(transport_100ms.in_waiting)
        dur_100ms = time.monotonic() - t0
        self.assertGreaterEqual(dur_100ms, 0.09, "100ms latency was not honored")

    # -----------------------------------------------------------------
    # 6. Timeout / Drop Handling
    # -----------------------------------------------------------------
    def test_06_timeout_handling(self):
        """Fault mode 'timeout' yields no response bytes, properly triggering timeout status."""
        transport = VirtualSerialTransport(fault_mode="timeout")
        transport.write(b"ATZ\r")
        self.assertEqual(transport.in_waiting, 0)
        rx = transport.read(10)
        self.assertEqual(rx, b"")

        # In adapter
        adapter = ELM327DiagnosticAdapter(
            adapter_id="TIMEOUT_TEST",
            port="COM_VIRTUAL",
            serial_factory=lambda *a, **kw: VirtualSerialTransport(fault_mode="timeout"),
            simulation=False,
        )
        adapter.ser = adapter.serial_factory("COM_VIRTUAL")
        adapter._state = AdapterConnectionState.CONNECTED
        lines, status = adapter._send_raw_command("ATZ", timeout=0.15)
        self.assertEqual(status, STATUS_TIMEOUT)
        self.assertEqual(lines, [])

    # -----------------------------------------------------------------
    # 7. Disconnect Fault Injection
    # -----------------------------------------------------------------
    def test_07_disconnect_fault_injection(self):
        """Fault mode 'disconnect' abruptly closes handle and raises SerialException."""
        transport = VirtualSerialTransport(fault_mode="disconnect")
        with self.assertRaises(SerialException):
            transport.write(b"ATZ\r")
        self.assertFalse(transport.is_open)

        # In adapter
        adapter = ELM327DiagnosticAdapter(
            adapter_id="DISCONNECT_FAULT_TEST",
            port="COM_VIRTUAL",
            serial_factory=lambda *a, **kw: VirtualSerialTransport(fault_mode="disconnect"),
            simulation=False,
        )
        adapter.ser = adapter.serial_factory("COM_VIRTUAL")
        adapter._state = AdapterConnectionState.CONNECTED
        lines, status = adapter.send_command("010C")
        self.assertEqual(status, STATUS_SERIAL_ERROR)
        self.assertEqual(adapter.connection_state, AdapterConnectionState.ERROR)
        self.assertFalse(adapter.is_connected())

    # -----------------------------------------------------------------
    # 8. Malformed Response Fault Injection
    # -----------------------------------------------------------------
    def test_08_malformed_response_fault_injection(self):
        """Fault mode 'malformed' emits corrupted bytes without '>', causing probe rejection."""
        transport = VirtualSerialTransport(fault_mode="malformed")
        transport.write(b"ATZ\r")
        rx = transport.read(transport.in_waiting)
        self.assertNotIn(b">", rx)

        # Probe rejection
        probe_res = probe_elm327_port(
            port="COM_VIRTUAL",
            baudrates=[38400],
            timeout=0.3,
            serial_factory=lambda *a, **kw: VirtualSerialTransport(fault_mode="malformed"),
        )
        self.assertFalse(probe_res.adapter_detected)
        self.assertIn(probe_res.failure_reason, ("INVALID_RESPONSE", "INVALID_ELM327_RESPONSE", "NO_ELM327_RESPONSE"))

    # -----------------------------------------------------------------
    # 9. ELM327 Probe Succeeds
    # -----------------------------------------------------------------
    def test_09_elm327_probe_succeeds(self):
        """Standard virtual transport is correctly identified during candidate port probing."""
        probe_res = probe_elm327_port(
            port="COM_VIRTUAL",
            baudrates=[38400],
            timeout=1.0,
            serial_factory=self.v_factory,
        )
        self.assertTrue(probe_res.adapter_detected)
        self.assertEqual(probe_res.connection_state, "CONNECTED")
        self.assertIn("ELM327", (probe_res.adapter_identity or "").upper())

    # -----------------------------------------------------------------
    # 10. Adapter Initialization Succeeds
    # -----------------------------------------------------------------
    def test_10_adapter_initialization_succeeds(self):
        """Full initialization executes successfully, transitioning to VEHICLE_PROTOCOL_READY."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="INIT_SUCCESS_TEST",
            port="COM_VIRTUAL",
            serial_factory=self.v_factory,
            simulation=False,
        )
        self.assertTrue(adapter.connect(timeout=4.0))
        self.assertTrue(adapter.is_connected())
        self.assertTrue(adapter.is_adapter_responsive)
        self.assertTrue(adapter.is_vehicle_ready)
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.VEHICLE_PROTOCOL_READY)
        self.assertEqual(adapter.detected_protocol, "A6")
        adapter.disconnect()

    # -----------------------------------------------------------------
    # 11. Duplicate Connect Attempt Protection
    # -----------------------------------------------------------------
    def test_11_duplicate_connect_attempt_rejected(self):
        """Duplicate connection attempts on an already connected adapter are safely ignored."""
        created_transports = []

        def tracking_factory(*args, **kwargs):
            t = self.v_factory(*args, **kwargs)
            created_transports.append(t)
            return t

        adapter = ELM327DiagnosticAdapter(
            adapter_id="DUP_TEST",
            port="COM_VIRTUAL",
            serial_factory=tracking_factory,
            simulation=False,
        )
        self.assertTrue(adapter.connect(timeout=4.0))
        self.assertEqual(len(created_transports), 1)

        # Second connect call while already connected
        res2 = adapter.connect(timeout=4.0)
        self.assertTrue(res2)
        # Handle must NOT have been re-created or leaked
        self.assertEqual(len(created_transports), 1, "Duplicate connect must not allocate a second serial transport")
        adapter.disconnect()

    # -----------------------------------------------------------------
    # 12. Disconnect Then Reconnect Lifecycle
    # -----------------------------------------------------------------
    def test_12_disconnect_then_reconnect_works(self):
        """Adapter cleanly releases transport on disconnect and connects again without error."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="RECONNECT_TEST",
            port="COM_VIRTUAL",
            serial_factory=self.v_factory,
            simulation=False,
        )
        # Phase 1: Connect
        self.assertTrue(adapter.connect(timeout=4.0))
        self.assertTrue(adapter.is_connected())

        # Phase 2: Disconnect
        adapter.disconnect()
        self.assertFalse(adapter.is_connected())
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.DISCONNECTED)

        # Phase 3: Reconnect
        self.assertTrue(adapter.connect(timeout=4.0))
        self.assertTrue(adapter.is_connected())
        self.assertTrue(adapter.is_vehicle_ready)

        adapter.disconnect()

    # -----------------------------------------------------------------
    # 13. GUI / Runtime State Truthfulness
    # -----------------------------------------------------------------
    def test_13_gui_runtime_state_truthful(self):
        """Presentation badges report truthful connected port and never pretend to be COM_MOCK."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="UI_BADGE_TEST",
            port="COM_VIRTUAL",
            serial_factory=self.v_factory,
            simulation=False,
        )
        adapter.connect(timeout=4.0)

        runtime = LiveAcquisitionRuntime(
            adapter=adapter,
            simulation=False,
        )
        # Force connected state for badge verification
        badge = LivePresentationModel.get_connection_info(
            runtime_state=LIVE_RUNNING,
            is_serial_open=True,
            connection_state="CONNECTED",
            is_simulation=False,
            port="COM_VIRTUAL",
        )
        self.assertEqual(badge["status"], "BAĞLI: COM_VIRTUAL")
        self.assertIn("COM_VIRTUAL", badge["detail"])
        self.assertNotIn("SİMÜLASYON", badge["status"])
        adapter.disconnect()

    # -----------------------------------------------------------------
    # 14. Strict Absence of MockSerial
    # -----------------------------------------------------------------
    def test_14_no_mockserial_involved(self):
        """Validates that VirtualSerialTransport is used and MockSerial is strictly absent."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="NO_MOCKSERIAL_TEST",
            port="COM_VIRTUAL",
            serial_factory=self.v_factory,
            simulation=False,
        )
        adapter.connect(timeout=4.0)

        # Verify serial instance is VirtualSerialTransport and not MockSerialForELM
        from diagnostic_adapter import MockSerialForELM
        self.assertFalse(isinstance(adapter.ser, MockSerialForELM))
        self.assertIsInstance(adapter.ser, VirtualSerialTransport)
        self.assertFalse(adapter.simulation)
        adapter.disconnect()

    # -----------------------------------------------------------------
    # 15. Opt-in Environment Variable SEYYANEN_VIRTUAL_ELM327
    # -----------------------------------------------------------------
    def test_15_opt_in_environment_variable(self):
        """SEYYANEN_VIRTUAL_ELM327=1 enables automatic virtual factory injection when no factory passed."""
        # Case A: Variable is NOT set
        with patch.dict(os.environ, {}, clear=True):
            if "SEYYANEN_VIRTUAL_ELM327" in os.environ:
                del os.environ["SEYYANEN_VIRTUAL_ELM327"]
            adapter_prod = ELM327DiagnosticAdapter(adapter_id="PROD_NO_VIRTUAL", simulation=False)
            self.assertIsNone(adapter_prod.serial_factory, "Factory must remain None in production by default")

        # Case B: Variable IS set
        with patch.dict(os.environ, {"SEYYANEN_VIRTUAL_ELM327": "1"}):
            adapter_opt_in = ELM327DiagnosticAdapter(adapter_id="OPT_IN_VIRTUAL", simulation=False)
            self.assertIsNotNone(adapter_opt_in.serial_factory, "Factory should be injected when SEYYANEN_VIRTUAL_ELM327=1")
            # Verify factory produces a VirtualSerialTransport
            test_s = adapter_opt_in.serial_factory("COM_VIRTUAL")
            self.assertIsInstance(test_s, VirtualSerialTransport)
            test_s.close()


if __name__ == "__main__":
    unittest.main()
