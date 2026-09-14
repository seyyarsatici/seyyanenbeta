"""
test_phase_k2.py - Phase K-2: Real Windows ELM327 USB/Serial Diagnostic Adapter Integration
=============================================================================================

Comprehensive test suite verifying:
  A. Adapter factory creates the ELM327 serial adapter
  B. Capability reporting is truthful (serial, ELM327, read-only; no J2534/SocketCAN)
  C. Serial open success
  D. Serial open failure (port missing or denied fails closed)
  E. Initialization success (ATZ, ATE0, ATL0, ATS0, ATH1, ATSP0, ATDPN)
  F. Initialization timeout (bounded timeout, state transitions to FAILED/ERROR)
  G. Malformed initialization response
  H. ELM327 ERROR handling (CAN ERROR, BUS ERROR mapped to STATUS_SERIAL_ERROR)
  I. NO DATA handling (mapped to STATUS_NO_DATA)
  J. Command serialization (one physical path)
  K. Concurrent request protection (lock guards physical serial link)
  L. Disconnect behavior (cleans up port and resources)
  M. Reconnect behavior (clean reconnect without stale state)
  N. Adapter disappearance during operation (USB disconnect / SerialException)
  O. Shutdown during connection
  P. Raw response preservation (last_raw_response captured)
  Q. Vehicle response distinguishable from ELM327 transport errors (NRC vs CAN ERROR)
  R. Destructive-service protection remains intact (0x14, 0x27, 0x2E, 0x2F, 0x34-0x37, 0x3D)
  S. J-6 production reliability integration
  T. K-1 non-blocking integration
  U. Existing mock/UDS/Mode22 regressions & Smoke test verification
"""

import sys
import os
import time
import threading
import unittest
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diagnostic_adapter import (
    DiagnosticAdapter,
    AdapterConnectionState,
    AdapterType,
    TransportMedium,
    DiagnosticProtocol,
    AdapterCapabilities,
    AdapterMetadata,
    AdapterRegistry,
    ELM327DiagnosticAdapter,
    ELM327TransportStage,
    MockSerialForELM,
    AdapterConnectionError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    TransportFailureError,
    AdapterResetError,
)
from advanced_ecu_services import (
    DiagnosticTransactionManager,
    AdvancedServiceRequest,
    ServiceSafetyClassification,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
)


class TestPhaseK2RealELM327Integration(unittest.TestCase):
    """Exhaustive test suite certifying Phase K-2 Real ELM327 USB/Serial Adapter Integration."""

    def test_A_adapter_factory_creates_elm327_serial_adapter(self):
        """A: AdapterRegistry dynamically instantiates ELM327DiagnosticAdapter with SERIAL_USB medium."""
        adapter = AdapterRegistry.create_adapter(
            AdapterType.ELM327,
            adapter_id="FACTORY_ELM327",
            port="COM3",
            baudrate=38400,
        )
        self.assertIsInstance(adapter, ELM327DiagnosticAdapter)
        self.assertEqual(adapter.metadata.adapter_type, AdapterType.ELM327)
        self.assertEqual(adapter.metadata.transport_medium, TransportMedium.SERIAL_USB)
        self.assertEqual(adapter.port, "COM3")
        self.assertEqual(adapter.baudrate, 38400)
        self.assertFalse(adapter.is_connected())
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.DISCONNECTED)

    def test_B_capability_reporting_is_truthful(self):
        """B: ELM327 capabilities truthfully advertise serial/OBD support and deny J2534/SocketCAN/Raw-CAN."""
        adapter = ELM327DiagnosticAdapter(adapter_id="CAP_TEST", port="COM1")
        caps = adapter.capabilities

        # Supported features
        self.assertTrue(caps.supports_serial_transport)
        self.assertTrue(caps.supports_elm327_commands)
        self.assertTrue(caps.supports_obd2_standard)
        self.assertTrue(caps.supports_iso15765_can)
        self.assertTrue(caps.supports_voltage_reading)
        self.assertTrue(caps.supports_hardware_reset)
        self.assertTrue(caps.is_read_only_enforced)

        # Unsupported features truthfully rejected
        self.assertFalse(caps.supports_raw_can, "ELM327 must not advertise raw CAN streaming")
        self.assertFalse(caps.supports_multi_channel, "ELM327 must not advertise multi-channel")
        self.assertFalse(caps.supports_privileged_services, "ELM327 must not advertise privileged services")
        self.assertEqual(caps.channel_count, 1)

    def test_C_serial_open_success(self):
        """C: Serial port opens successfully and reaches PORT_OPENED and ELM327_RESPONSIVE."""
        mock_ser = MockSerialForELM(port="COM4", baudrate=38400)
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_OPEN_OK",
            port="COM4",
            baudrate=38400,
            serial_factory=lambda port, baudrate, **kw: mock_ser,
        )

        ok = adapter.connect(timeout=2.0)
        self.assertTrue(ok)
        self.assertTrue(adapter.is_connected())
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        self.assertIn(
            adapter.transport_stage,
            (ELM327TransportStage.ELM327_RESPONSIVE, ELM327TransportStage.VEHICLE_PROTOCOL_READY),
        )
        self.assertTrue(adapter.is_adapter_responsive)
        self.assertTrue(mock_ser.is_open)
        adapter.disconnect()
        self.assertFalse(adapter.is_connected())
        self.assertFalse(mock_ser.is_open)

    def test_D_serial_open_failure(self):
        """D: Serial port opening failure fails closed without leaking state."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_OPEN_FAIL",
            port="COM99",
            baudrate=38400,
            serial_factory=lambda port, baudrate, **kw: MockSerialForELM(port=port, fail_open=True),
        )

        with self.assertRaises(AdapterConnectionError):
            adapter.connect(timeout=1.0)

        self.assertFalse(adapter.is_connected())
        self.assertIn(adapter.connection_state, (AdapterConnectionState.FAILED, AdapterConnectionState.ERROR))
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.DISCONNECTED)

    def test_E_initialization_success_sequence(self):
        """E: Full initialization sequence (ATZ, ATE0, ATL0, ATS0, ATH1, ATSP0, ATDPN) executes correctly."""
        mock_ser = MockSerialForELM(port="COM5", baudrate=38400)
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_INIT_OK",
            port="COM5",
            baudrate=38400,
            serial_factory=lambda *a, **kw: mock_ser,
        )

        ok = adapter.connect(timeout=3.0)
        self.assertTrue(ok)
        self.assertEqual(adapter.elm_version, "ELM327 v1.5")
        self.assertIsNotNone(adapter.detected_protocol)
        self.assertTrue(adapter.is_vehicle_ready)
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.VEHICLE_PROTOCOL_READY)

        # Verify command transmission history in mock serial
        tx_str = "".join(mock_ser._tx_history).replace(" ", "")
        self.assertIn("ATZ", tx_str)
        self.assertIn("ATE0", tx_str)
        self.assertIn("ATH1", tx_str)
        self.assertIn("ATSP0", tx_str)
        self.assertIn("0100", tx_str)
        adapter.disconnect()

    def test_F_initialization_timeout(self):
        """F: Adapter unresponsiveness during initialization triggers timeout and transitions to FAILED."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_INIT_TIMEOUT",
            port="COM6",
            baudrate=38400,
            read_timeout=0.1,
            serial_factory=lambda *a, **kw: MockSerialForELM(port="COM6", fail_init_timeout=True),
        )

        with self.assertRaises(AdapterConnectionError):
            adapter.connect(timeout=0.5)

        self.assertFalse(adapter.is_connected())
        self.assertIn(adapter.connection_state, (AdapterConnectionState.FAILED, AdapterConnectionState.ERROR))
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.DISCONNECTED)

    def test_G_malformed_initialization_response(self):
        """G: Corrupted / garbage response during initialization fails closed."""
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_INIT_GARBAGE",
            port="COM7",
            read_timeout=0.2,
            serial_factory=lambda *a, **kw: MockSerialForELM(
                port="COM7",
                fail_init_error=True,
            ),
        )

        with self.assertRaises(AdapterConnectionError):
            adapter.connect(timeout=0.5)

        self.assertFalse(adapter.is_connected())
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.DISCONNECTED)

    def test_H_elm327_error_handling(self):
        """H: CAN ERROR and BUS ERROR are correctly mapped to STATUS_SERIAL_ERROR."""
        mock_ser = MockSerialForELM(port="COM8")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_BUS_ERR",
            port="COM8",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        # Inject bus error on next command
        mock_ser.inject_bus_error = True
        lines, status = adapter.send_command("010C")
        self.assertEqual(status, STATUS_SERIAL_ERROR)
        self.assertIn("CAN ERROR", " ".join(lines).upper())
        adapter.disconnect()

    def test_I_no_data_handling(self):
        """I: NO DATA from ELM327 is mapped to STATUS_NO_DATA without generating serial errors."""
        mock_ser = MockSerialForELM(port="COM9")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_NO_DATA",
            port="COM9",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        # Inject NO DATA
        mock_ser.inject_no_data = True
        lines, status = adapter.send_command("0123")
        self.assertEqual(status, STATUS_NO_DATA)
        self.assertIn("NO DATA", " ".join(lines).upper())
        adapter.disconnect()

    def test_J_command_serialization(self):
        """J: Multiple commands dispatched in sequence are strictly serialized through one path."""
        mock_ser = MockSerialForELM(port="COM10")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_SERIAL_PATH",
            port="COM10",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        # Send three consecutive commands
        adapter.send_command("010C")
        adapter.send_command("010D")
        adapter.send_command("AT RV")

        tx = mock_ser._tx_history
        self.assertIn("010C", tx)
        self.assertIn("010D", tx)
        self.assertIn("ATRV", [t.replace(" ", "") for t in tx])
        adapter.disconnect()

    def test_K_concurrent_request_protection(self):
        """K: Concurrent caller threads cannot interleave or corrupt serial transactions."""
        mock_ser = MockSerialForELM(port="COM11")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_CONCURRENT",
            port="COM11",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        results = []
        errors = []

        def worker(cmd):
            try:
                for _ in range(5):
                    lines, status = adapter.send_command(cmd, timeout=1.0)
                    results.append((cmd, status))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=("010C",))
        t2 = threading.Thread(target=worker, args=("010D",))
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        self.assertEqual(len(errors), 0, f"Concurrent workers raised unexpected errors: {errors}")
        self.assertEqual(len(results), 10, "All 10 serialized transactions must complete")
        for cmd, status in results:
            self.assertEqual(status, STATUS_VALID)
        adapter.disconnect()

    def test_L_disconnect_behavior(self):
        """L: Disconnect cleanly closes serial link, clears buffers, and resets stage to DISCONNECTED."""
        mock_ser = MockSerialForELM(port="COM12")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_DISCONNECT",
            port="COM12",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()
        self.assertTrue(adapter.is_connected())

        adapter.disconnect()
        self.assertFalse(adapter.is_connected())
        self.assertFalse(mock_ser.is_open)
        self.assertEqual(adapter.transport_stage, ELM327TransportStage.DISCONNECTED)
        self.assertIsNone(adapter.last_raw_response)
        self.assertEqual(adapter.last_normalized_response, [])

    def test_M_reconnect_behavior(self):
        """M: Clean reconnection after disconnect succeeds without stale buffers or deadlocks."""
        mock_ser = MockSerialForELM(port="COM13")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_RECONNECT",
            port="COM13",
            serial_factory=lambda *a, **kw: mock_ser,
        )

        for cycle in range(3):
            ok = adapter.connect(timeout=2.0)
            self.assertTrue(ok, f"Connection cycle {cycle} failed")
            self.assertTrue(adapter.is_connected())
            lines, status = adapter.send_command("010C")
            self.assertEqual(status, STATUS_VALID)
            adapter.disconnect()
            self.assertFalse(adapter.is_connected())
            mock_ser.open()  # Reopen mock for next cycle

    def test_N_adapter_disappearance_during_operation(self):
        """N: Physical adapter unplug / SerialException is caught as TransportFailureError."""
        mock_ser = MockSerialForELM(port="COM14")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_UNPLUG",
            port="COM14",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        # Simulate device disappearance
        mock_ser.simulate_disconnect = True

        # send_command should catch TransportFailureError and return STATUS_SERIAL_ERROR
        lines, status = adapter.send_command("010C")
        self.assertEqual(status, STATUS_SERIAL_ERROR)
        self.assertFalse(mock_ser.is_open)

    def test_O_shutdown_during_connection(self):
        """O: Disconnect during in-progress async connection cleanly aborts without hanging."""
        mock_ser = MockSerialForELM(port="COM15")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_SHUTDOWN",
            port="COM15",
            serial_factory=lambda *a, **kw: mock_ser,
        )

        adapter.connect_async(timeout=3.0)
        time.sleep(0.01)
        adapter.disconnect()

        self.assertFalse(adapter.is_connected())
        self.assertEqual(adapter.connection_state, AdapterConnectionState.DISCONNECTED)

    def test_P_raw_response_preservation(self):
        """P: Adapter captures and preserves raw byte stream in last_raw_response."""
        mock_ser = MockSerialForELM(port="COM16")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_RAW_CAPTURE",
            port="COM16",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        lines, status = adapter.send_command("010C")
        self.assertEqual(status, STATUS_VALID)
        self.assertIsNotNone(adapter.last_raw_response)
        self.assertIsInstance(adapter.last_raw_response, bytes)
        self.assertIn(b">", adapter.last_raw_response)
        adapter.disconnect()

    def test_Q_vehicle_response_distinguishable_from_transport_errors(self):
        """Q: ECU Negative Response (7F 22 31) maps to STATUS_NRC, distinct from STATUS_SERIAL_ERROR."""
        mock_ser = MockSerialForELM(port="COM17")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_DISTINGUISH",
            port="COM17",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        # 1. ECU NRC
        mock_ser.inject_nrc = True
        lines, status_nrc = adapter.send_command("220100")
        self.assertEqual(status_nrc, STATUS_NRC, "ECU 7F NRC must map to STATUS_NRC")
        mock_ser.inject_nrc = False

        # 2. Transport error
        mock_ser.inject_bus_error = True
        lines, status_err = adapter.send_command("220100")
        self.assertEqual(status_err, STATUS_SERIAL_ERROR, "Bus failure must map to STATUS_SERIAL_ERROR")

        self.assertNotEqual(status_nrc, status_err)
        adapter.disconnect()

    def test_R_destructive_service_protection_intact(self):
        """R: Prohibited services (0x14, 0x27, 0x2E, 0x2F, 0x34-0x37, 0x3D) are blocked at adapter boundary."""
        mock_ser = MockSerialForELM(port="COM18")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_SAFETY",
            port="COM18",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        prohibited = ["04", "14", "27 01", "2E 01 02", "2F 01 03", "34", "35", "36", "37", "3D"]
        for bad_cmd in prohibited:
            lines, status = adapter.send_command(bad_cmd)
            self.assertEqual(status, STATUS_NRC, f"Prohibited service '{bad_cmd}' must be rejected with STATUS_NRC")
            self.assertNotIn(bad_cmd.split()[0], "".join(mock_ser._tx_history))

        adapter.disconnect()

    def test_S_production_reliability_integration(self):
        """S: Production reliability / DiagnosticTransactionManager operates cleanly with real ELM327 adapter."""
        mock_ser = MockSerialForELM(port="COM19")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_RELIABILITY",
            port="COM19",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        mgr = DiagnosticTransactionManager(transport=adapter)
        req = AdvancedServiceRequest(
            service_id="01",
            payload="0C",
            target_ecu="ECM",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            timeout=1.5,
        )
        resp = mgr.execute_request(req)
        self.assertTrue(resp.is_positive)
        self.assertIn("7E8 04 41 0C 0F A0", "".join(resp.raw_lines))
        adapter.disconnect()

    def test_T_k1_nonblocking_integration(self):
        """T: K-1 connect_async with real ELM327 transport returns immediately and fires callback."""
        mock_ser = MockSerialForELM(port="COM20")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_ASYNC_K1",
            port="COM20",
            serial_factory=lambda *a, **kw: mock_ser,
        )

        callback_event = threading.Event()
        callback_res = {}

        def on_finished(ok, err):
            callback_res["ok"] = ok
            callback_res["err"] = err
            callback_event.set()

        t_start = time.perf_counter()
        initiated = adapter.connect_async(timeout=2.0, on_finished=on_finished)
        t_elapsed = time.perf_counter() - t_start

        self.assertTrue(initiated)
        self.assertLess(t_elapsed, 0.08, "connect_async must return immediately (<80ms)")
        self.assertTrue(callback_event.wait(timeout=2.0))
        self.assertTrue(callback_res["ok"])
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        adapter.disconnect()

    def test_U_diagnostic_smoke_test_path(self):
        """U: execute_smoke_test runs safe read-only sequence (AT RV + 0100) and returns structured report."""
        mock_ser = MockSerialForELM(port="COM21")
        adapter = ELM327DiagnosticAdapter(
            adapter_id="ELM_SMOKE",
            port="COM21",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        adapter.connect()

        report = adapter.execute_smoke_test(timeout=2.0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["port"], "COM21")
        self.assertEqual(report["battery_voltage"], 12.6)
        self.assertEqual(report["safe_read_command"], "0100")
        self.assertEqual(report["safe_read_status"], STATUS_VALID)
        self.assertTrue(report["raw_response_captured"])
        adapter.disconnect()


if __name__ == "__main__":
    unittest.main()
