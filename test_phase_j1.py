#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-1
===================================================
Hardware & Adapter Abstraction Test Suite
`test_phase_j1.py`

Certifies:
  A. Adapter interface compliance
  B. Mock adapter lifecycle
  C. Connect / disconnect
  D. Deterministic request / response
  E. Timeout handling
  F. Communication failure
  G. Malformed response
  H. Unsupported capability fails closed
  I. Capability discovery
  J. Adapter metadata serialization
  K. Adapter registry / factory
  L. Multiple adapter implementations behind one interface
  M. ELM327 boundary integration
  N. Future rich adapter (J2534) capability representation
  O. Safety policy enforcement & prohibited services fail-closed
  P. Communication failure != component failure
  Q. Invalid lifecycle transitions
  R. Repeated connect / disconnect determinism
  S. Cancellation and timeout boundedness
  T. Backward compatibility with existing diagnostic pipeline
  + Adversarial safety bypass prevention
"""

import sys
import os
import time
import unittest
from typing import List, Dict, Any, Tuple

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diagnostic_adapter import (
    AdapterConnectionState,
    AdapterType,
    TransportMedium,
    DiagnosticProtocol,
    AdapterCapabilities,
    AdapterMetadata,
    AdapterError,
    AdapterUnavailableError,
    AdapterConnectionError,
    AdapterTimeoutError,
    UnsupportedCapabilityError,
    ProtocolConfigurationError,
    MalformedResponseError,
    TransportFailureError,
    AdapterResetError,
    AdapterStateError,
    DiagnosticAdapter,
    MockDiagnosticAdapter,
    ELM327DiagnosticAdapter,
    J2534DiagnosticAdapter,
    AdapterRegistry,
    PROHIBITED_SERVICES,
)

from advanced_ecu_services import (
    ITransportAdapter,
    ServiceSafetyPolicy,
    ServiceSafetyClassification,
    DiagnosticTransactionManager,
    AdvancedServiceRequest,
    STATUS_VALID,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
)


class MockEngineForELM:
    """Mock engine simulating AutoExpertEngine komut_gonder interface."""
    def __init__(self):
        self.last_response_status = STATUS_VALID
        self.command_log: List[str] = []
        self.responses: Dict[str, List[str]] = {
            "AT Z": ["ELM327 v1.5"],
            "AT WS": ["ELM327 v1.5"],
            "AT SH 7E0": ["OK"],
            "AT SP 6": ["OK"],
            "AT RV": ["12.5V"],
            "0100": ["41 00 BE 3E B8 11"],
            "010C": ["41 0C 0F A0"],  # 1000 RPM
            "220100": ["62 01 00 12 34"],
        }
        self.ser = type("MockSer", (), {"is_open": True, "close": lambda self: None})()

    def komut_gonder(self, komut: str, timeout: float = 1.0) -> List[str]:
        self.command_log.append(komut)
        clean = komut.strip().upper()
        if clean in self.responses:
            self.last_response_status = STATUS_VALID
            return self.responses[clean]
        for k, v in self.responses.items():
            if clean.startswith(k):
                self.last_response_status = STATUS_VALID
                return v
        self.last_response_status = STATUS_NO_DATA
        return []


class TestPhaseJ1AdapterAbstraction(unittest.TestCase):
    """Exhaustive test suite certifying Phase J-1 Hardware & Adapter Abstraction."""

    def setUp(self):
        self.mock_adapter = MockDiagnosticAdapter(adapter_id="TEST_MOCK_01")

    def tearDown(self):
        if self.mock_adapter.is_connected():
            self.mock_adapter.disconnect()

    # =====================================================================
    # A: ADAPTER INTERFACE COMPLIANCE
    # =====================================================================
    def test_A_adapter_interface_compliance(self):
        """DiagnosticAdapter satisfies ITransportAdapter contract and canonical API."""
        self.assertTrue(issubclass(DiagnosticAdapter, ITransportAdapter))
        self.assertIsInstance(self.mock_adapter, ITransportAdapter)
        self.assertIsInstance(self.mock_adapter, DiagnosticAdapter)

        # Verify presence of all canonical methods
        expected_methods = [
            "connect", "disconnect", "is_connected", "reset",
            "set_protocol", "get_current_header", "set_header",
            "read_battery_voltage", "send_command", "require_capability"
        ]
        for m in expected_methods:
            self.assertTrue(hasattr(self.mock_adapter, m), f"Missing method: {m}")

    # =====================================================================
    # B: MOCK ADAPTER LIFECYCLE
    # =====================================================================
    def test_B_mock_adapter_lifecycle(self):
        """Adapter transitions through DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTED."""
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.DISCONNECTED)
        self.assertFalse(self.mock_adapter.is_connected())

        connected = self.mock_adapter.connect()
        self.assertTrue(connected)
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.CONNECTED)
        self.assertTrue(self.mock_adapter.is_connected())

        disconnected = self.mock_adapter.disconnect()
        self.assertTrue(disconnected)
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.DISCONNECTED)
        self.assertFalse(self.mock_adapter.is_connected())

    # =====================================================================
    # C: CONNECT / DISCONNECT STATE CONTROL
    # =====================================================================
    def test_C_connect_disconnect_states(self):
        """Idempotent connect and disconnect operations do not corrupt state."""
        self.mock_adapter.connect()
        # Second connect while already connected returns True cleanly
        self.assertTrue(self.mock_adapter.connect())
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.CONNECTED)

        self.mock_adapter.disconnect()
        # Second disconnect while disconnected returns True cleanly
        self.assertTrue(self.mock_adapter.disconnect())
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.DISCONNECTED)

    # =====================================================================
    # D: DETERMINISTIC REQUEST / RESPONSE
    # =====================================================================
    def test_D_deterministic_request_response(self):
        """Adapter returns deterministic responses for registered commands."""
        self.mock_adapter.connect()
        self.mock_adapter.register_response("010C", ["41 0C 0F A0"])
        self.mock_adapter.register_response("221122", ["62 11 22 AA BB CC"])

        lines1, status1 = self.mock_adapter.send_command("010C")
        self.assertEqual(status1, STATUS_VALID)
        self.assertEqual(lines1, ["41 0C 0F A0"])

        lines2, status2 = self.mock_adapter.send_command("22 11 22")
        self.assertEqual(status2, STATUS_VALID)
        self.assertEqual(lines2, ["62 11 22 AA BB CC"])

        # Unregistered command returns STATUS_NO_DATA
        lines3, status3 = self.mock_adapter.send_command("0199")
        self.assertEqual(status3, STATUS_NO_DATA)
        self.assertEqual(lines3, [])

    # =====================================================================
    # E: TIMEOUT HANDLING
    # =====================================================================
    def test_E_timeout_handling(self):
        """Simulated timeout produces STATUS_TIMEOUT without raising unhandled exception."""
        self.mock_adapter.connect()
        self.mock_adapter.force_timeout = True

        lines, status = self.mock_adapter.send_command("0100", timeout=0.1)
        self.assertEqual(status, STATUS_TIMEOUT)
        self.assertEqual(lines, [])

    # =====================================================================
    # F: COMMUNICATION FAILURE
    # =====================================================================
    def test_F_communication_failure(self):
        """Simulated transport failure transitions adapter to ERROR state and returns SERIAL_ERROR."""
        self.mock_adapter.connect()
        self.mock_adapter.force_transport_error = True

        lines, status = self.mock_adapter.send_command("010C")
        self.assertEqual(status, STATUS_SERIAL_ERROR)
        self.assertEqual(lines, [])
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.ERROR)

    # =====================================================================
    # G: MALFORMED RESPONSE
    # =====================================================================
    def test_G_malformed_response(self):
        """Corrupted framing returns STATUS_SERIAL_ERROR and preserves stability."""
        self.mock_adapter.connect()
        self.mock_adapter.force_malformed = True

        lines, status = self.mock_adapter.send_command("0105")
        self.assertEqual(status, STATUS_SERIAL_ERROR)
        self.assertEqual(lines, [])

    # =====================================================================
    # H: UNSUPPORTED CAPABILITY FAILS CLOSED
    # =====================================================================
    def test_H_unsupported_capability_fails_closed(self):
        """Requesting unsupported capability raises UnsupportedCapabilityError deterministically."""
        elm = ELM327DiagnosticAdapter()
        # ELM327 does not support raw CAN streaming
        self.assertFalse(elm.capabilities.supports_raw_can)
        with self.assertRaises(UnsupportedCapabilityError) as cm:
            elm.require_capability("supports_raw_can")
        self.assertIn("supports_raw_can", str(cm.exception))

    # =====================================================================
    # I: CAPABILITY DISCOVERY
    # =====================================================================
    def test_I_capability_discovery(self):
        """AdapterRegistry queries find matching adapters without hard-coded conditionals."""
        raw_can_adapters = AdapterRegistry.find_adapters_with_capabilities(supports_raw_can=True)
        self.assertIn(AdapterType.J2534_PASS_THRU, raw_can_adapters)
        self.assertNotIn(AdapterType.ELM327, raw_can_adapters)

        obd_adapters = AdapterRegistry.find_adapters_with_capabilities(supports_obd2_standard=True)
        self.assertIn(AdapterType.ELM327, obd_adapters)
        self.assertIn(AdapterType.MOCK_REFERENCE, obd_adapters)

    # =====================================================================
    # J: ADAPTER METADATA SERIALIZATION
    # =====================================================================
    def test_J_adapter_metadata_serialization(self):
        """AdapterMetadata round-trips cleanly via to_dict and from_dict."""
        meta = self.mock_adapter.metadata
        d = meta.to_dict()
        reconstructed = AdapterMetadata.from_dict(d)

        self.assertEqual(reconstructed.adapter_id, meta.adapter_id)
        self.assertEqual(reconstructed.adapter_type, meta.adapter_type)
        self.assertEqual(reconstructed.transport_medium, meta.transport_medium)
        self.assertEqual(reconstructed.firmware_version, meta.firmware_version)
        self.assertEqual(reconstructed.capabilities.supports_iso15765_can, meta.capabilities.supports_iso15765_can)

    # =====================================================================
    # K: ADAPTER REGISTRY / FACTORY
    # =====================================================================
    def test_K_adapter_registry_factory(self):
        """Registry registers and instantiates adapters dynamically."""
        supported = AdapterRegistry.list_supported_types()
        self.assertIn(AdapterType.MOCK_REFERENCE, supported)
        self.assertIn(AdapterType.ELM327, supported)
        self.assertIn(AdapterType.J2534_PASS_THRU, supported)

        inst = AdapterRegistry.create_adapter(AdapterType.MOCK_REFERENCE, adapter_id="FACTORY_MOCK_01")
        self.assertEqual(inst.adapter_id, "FACTORY_MOCK_01")
        self.assertIsInstance(inst, MockDiagnosticAdapter)

        # Duplicate registration without override fails
        with self.assertRaises(ValueError):
            AdapterRegistry.register_factory(AdapterType.MOCK_REFERENCE, lambda **kw: inst, override=False)

    # =====================================================================
    # L: MULTIPLE ADAPTER IMPLEMENTATIONS BEHIND ONE INTERFACE
    # =====================================================================
    def test_L_multiple_adapter_implementations_behind_one_interface(self):
        """Diverse adapters operate polymorphically behind the canonical DiagnosticAdapter contract."""
        adapters: List[DiagnosticAdapter] = [
            MockDiagnosticAdapter(adapter_id="ADAPTER_MOCK"),
            ELM327DiagnosticAdapter(engine=MockEngineForELM(), adapter_id="ADAPTER_ELM"),
            J2534DiagnosticAdapter(adapter_id="ADAPTER_J2534"),
        ]

        for a in adapters:
            self.assertTrue(isinstance(a, DiagnosticAdapter))
            a.connect()
            self.assertTrue(a.is_connected())
            # Polymorphic header setting
            self.assertTrue(a.set_header("7E0"))
            self.assertEqual(a.get_current_header(), "7E0")
            # Polymorphic command dispatch
            lines, status = a.send_command("0100")
            self.assertIn(status, (STATUS_VALID, STATUS_NO_DATA))
            a.disconnect()
            self.assertFalse(a.is_connected())

    # =====================================================================
    # M: ELM327 BOUNDARY INTEGRATION
    # =====================================================================
    def test_M_elm327_boundary_integration(self):
        """ELM327 adapter manages AT commands and reads battery voltage."""
        mock_eng = MockEngineForELM()
        elm = ELM327DiagnosticAdapter(engine=mock_eng, adapter_id="ELM_TEST")
        elm.connect()

        # Voltage reading
        volts = elm.read_battery_voltage()
        self.assertEqual(volts, 12.5)

        # Protocol selection
        self.assertTrue(elm.set_protocol(DiagnosticProtocol.ISO_15765_4_CAN_11_500))
        self.assertIn("AT SP 6", mock_eng.command_log)

        # Hardware reset
        self.assertTrue(elm.reset(hard=True))
        self.assertIn("AT Z", mock_eng.command_log)

        # Normal command
        lines, status = elm.send_command("010C")
        self.assertEqual(status, STATUS_VALID)
        self.assertEqual(lines, ["41 0C 0F A0"])
        elm.disconnect()

    # =====================================================================
    # N: FUTURE RICH ADAPTER (J2534) CAPABILITY REPRESENTATION
    # =====================================================================
    def test_N_future_rich_adapter_capability_representation(self):
        """J2534 adapter explicitly models multi-channel and raw CAN capabilities."""
        j2534 = J2534DiagnosticAdapter(adapter_id="J2534_PROBE", device_name="DrewTech CarDAQ-Plus")
        self.assertEqual(j2534.adapter_type, AdapterType.J2534_PASS_THRU)
        self.assertTrue(j2534.capabilities.supports_raw_can)
        self.assertTrue(j2534.capabilities.supports_multi_channel)
        self.assertEqual(j2534.capabilities.channel_count, 2)
        self.assertTrue(j2534.capabilities.supports_extended_addressing)
        self.assertTrue(j2534.capabilities.supports_variable_baudrate)

    # =====================================================================
    # O: SAFETY POLICY ENFORCEMENT & PROHIBITED SERVICES FAIL-CLOSED
    # =====================================================================
    def test_O_safety_policy_enforcement(self):
        """Prohibited services (04, 14, 2E, 27, 2F, 34-37) are blocked at the adapter boundary."""
        self.mock_adapter.connect()
        prohibited = ["04", "14", "2E 0100 00", "27 01", "2F 1234 03", "34 00", "36 01", "37"]

        for bad_cmd in prohibited:
            lines, status = self.mock_adapter.send_command(bad_cmd)
            self.assertEqual(status, STATUS_NRC, f"Service '{bad_cmd}' must be blocked with STATUS_NRC!")
            self.assertEqual(lines, [])

    # =====================================================================
    # P: COMMUNICATION FAILURE != COMPONENT FAILURE
    # =====================================================================
    def test_P_communication_failure_is_not_component_failure(self):
        """Adapter communication failure is strictly marked as a communication failure."""
        err = AdapterTimeoutError("CAN bus timeout on ECU 0x7E0", adapter_id="ADAPTER_01")
        self.assertTrue(hasattr(err, "is_communication_failure"))
        self.assertTrue(err.is_communication_failure)
        self.assertEqual(err.adapter_id, "ADAPTER_01")

        # Invariant check: Exception representation identifies transport level
        self.assertIn("AdapterTimeoutError", str(err))

    # =====================================================================
    # Q: INVALID LIFECYCLE TRANSITIONS
    # =====================================================================
    def test_Q_invalid_lifecycle_transitions(self):
        """Operations executed in invalid lifecycle states fail closed with appropriate errors."""
        # Disconnected: send_command returns STATUS_NO_CONNECTION
        lines, status = self.mock_adapter.send_command("0100")
        self.assertEqual(status, STATUS_NO_CONNECTION)

        # Disconnected: set_header raises AdapterStateError
        with self.assertRaises(AdapterStateError):
            self.mock_adapter.set_header("7E0")

        # Disconnected: reset raises AdapterStateError
        with self.assertRaises(AdapterStateError):
            self.mock_adapter.reset()

        # Connect failure simulation
        self.mock_adapter.force_connect_failure = True
        with self.assertRaises(AdapterConnectionError):
            self.mock_adapter.connect()
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.ERROR)

    # =====================================================================
    # R: REPEATED CONNECT / DISCONNECT DETERMINISM
    # =====================================================================
    def test_R_repeated_connect_disconnect_determinism(self):
        """Repeated 50 connect/disconnect cycles execute cleanly without leaking state."""
        for i in range(50):
            self.mock_adapter.connect()
            self.assertTrue(self.mock_adapter.is_connected())
            self.mock_adapter.disconnect()
            self.assertFalse(self.mock_adapter.is_connected())
        self.assertEqual(self.mock_adapter.connection_state, AdapterConnectionState.DISCONNECTED)

    # =====================================================================
    # S: CANCELLATION AND TIMEOUT BOUNDEDNESS
    # =====================================================================
    def test_S_cancellation_and_timeout_boundedness(self):
        """Adapter calls complete within bounded execution time without hanging."""
        self.mock_adapter.connect()
        start = time.perf_counter()
        # Execute command with 0.1s timeout
        self.mock_adapter.send_command("0100", timeout=0.1)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.5)

    # =====================================================================
    # T: BACKWARD COMPATIBILITY WITH EXISTING DIAGNOSTIC PIPELINE
    # =====================================================================
    def test_T_backward_compatibility_with_existing_diagnostic_pipeline(self):
        """DiagnosticTransactionManager directly operates with DiagnosticAdapter."""
        self.mock_adapter.connect()
        self.mock_adapter.register_response("220100", ["62 01 00 12 34"])

        # Inject DiagnosticAdapter as ITransportAdapter into DiagnosticTransactionManager
        tx_mgr = DiagnosticTransactionManager(
            transport=self.mock_adapter,
            safety_policy=ServiceSafetyPolicy(allow_non_readonly=False),
        )

        req = AdvancedServiceRequest(
            service_id="22",
            payload="0100",
            target_ecu="ECM",
            safety_classification=ServiceSafetyClassification.READ_ONLY,
            timeout=1.0,
        )
        resp = tx_mgr.execute_request(req)
        self.assertTrue(resp.is_positive)
        self.assertEqual(resp.raw_lines, ["62 01 00 12 34"])

    # =====================================================================
    # ADVERSARIAL: SAFETY BYPASS PREVENTION
    # =====================================================================
    def test_adversarial_safety_bypass_attempts(self):
        """Malicious attempts to send destructive commands through adapter are blocked."""
        self.mock_adapter.connect()
        evasive_cmds = [
            " 04 ",           # Spaced Mode 04 Clear DTCs
            "14FFFFFF",       # UDS 0x14 Clear all groups
            "2eF1901234",     # UDS 0x2E Write VIN
            "2701",           # UDS 0x27 Security Seed Request
            "2F010203",       # UDS 0x2F Actuator Drive
            "340001",         # UDS 0x34 Flash Download Request
            "3601AABB",       # UDS 0x36 Flash Block Transfer
            "37",             # UDS 0x37 Flash Transfer Exit
        ]
        for cmd in evasive_cmds:
            lines, status = self.mock_adapter.send_command(cmd)
            self.assertEqual(status, STATUS_NRC)
            self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
