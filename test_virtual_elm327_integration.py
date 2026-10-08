"""
Seyyanen Automotive Diagnostics — Virtual ELM327 Integration Test
=================================================================
Validates the complete diagnostic adapter lifecycle using the real
ELM327DiagnosticAdapter connected to the VirtualSerialTransport.

Runs:
  1. Instantiation & Factory Injection
  2. Candidate Port Probing (probe_elm327_port)
  3. Initialization sequence (ATZ, ATE0, ATL0, ATS0, ATH1, ATSP0, ATDPN, 0100)
  4. Protocol interrogation (AT DPN)
  5. OBD-II Mode 01 PID queries (0100, 010C)
  6. Disconnect lifecycle
  7. Reconnect lifecycle
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from virtual_elm327 import (
    VirtualELM327Responder,
    VirtualSerialTransport,
    create_virtual_serial_factory,
)
from diagnostic_adapter import (
    ELM327DiagnosticAdapter,
    probe_elm327_port,
    AdapterConnectionState,
    ELM327TransportStage,
)
from motor import STATUS_VALID


def main() -> int:
    print("=" * 60)
    print("  SEYYANEN VIRTUAL ELM327 LIFECYCLE INTEGRATION TEST")
    print("=" * 60)

    try:
        # 1. Virtual ELM327 Component Validation
        responder = VirtualELM327Responder()
        v_fact = create_virtual_serial_factory(responder=responder, latency=0.0)
        test_ser = v_fact("COM_VIRTUAL")
        assert getattr(test_ser, "is_open", False) is True
        test_ser.close()
        print("[VIRTUAL-ELM] PASS")

        # 2. Port Probe Validation
        probe_res = probe_elm327_port(
            port="COM_VIRTUAL",
            baudrates=[38400],
            timeout=1.0,
            serial_factory=v_fact,
        )
        assert probe_res is not None, "Probe result must not be None"
        assert probe_res.adapter_detected is True, f"Probe failed: {probe_res.failure_reason}"
        assert "ELM327" in (probe_res.adapter_identity or "").upper(), f"Identity mismatch: {probe_res.adapter_identity}"
        print("[PROBE] PASS")

        # 3. Adapter Initialization
        adapter = ELM327DiagnosticAdapter(
            adapter_id="VIRTUAL_TEST_ADAPTER",
            port="COM_VIRTUAL",
            serial_factory=v_fact,
            simulation=False,  # Strict production path, NO MockSerial
        )
        connected = adapter.connect(timeout=4.0)
        assert connected is True, "Adapter connect() returned False"
        assert adapter.is_connected() is True, "Adapter state is not CONNECTED"
        assert adapter.is_adapter_responsive is True, "ELM327 not responsive"
        assert adapter.is_vehicle_ready is True, f"Vehicle protocol not ready, stage: {adapter.transport_stage}"
        assert adapter.elm_version is not None and "ELM327" in adapter.elm_version
        print("[INIT] PASS")

        # 4. Mode 01 PID 0100 Query
        lines_0100, status_0100 = adapter.send_command("0100", timeout=1.0)
        assert status_0100 == STATUS_VALID, f"0100 query failed with status: {status_0100}"
        assert any("4100" in l.replace(" ", "") for l in lines_0100), f"Unexpected 0100 response: {lines_0100}"
        print("[0100] PASS")

        # 5. Mode 01 PID 010C Query (Engine RPM)
        lines_010c, status_010c = adapter.send_command("010C", timeout=1.0)
        assert status_010c == STATUS_VALID, f"010C query failed with status: {status_010c}"
        assert any("410C" in l.replace(" ", "") for l in lines_010c), f"Unexpected 010C response: {lines_010c}"
        print("[010C] PASS")

        # 6. Disconnect
        adapter.disconnect()
        assert adapter.is_connected() is False, "Adapter still connected after disconnect()"
        assert adapter.transport_stage == ELM327TransportStage.DISCONNECTED
        assert adapter.ser is None or getattr(adapter.ser, "is_open", False) is False
        print("[DISCONNECT] PASS")

        # 7. Reconnect
        reconnected = adapter.connect(timeout=4.0)
        assert reconnected is True, "Adapter reconnect() returned False"
        assert adapter.is_connected() is True, "Adapter not connected after reconnect()"
        assert adapter.is_adapter_responsive is True
        print("[RECONNECT] PASS")

        adapter.disconnect()

        print("=" * 60)
        print(">>> ALL INTEGRATION LIFECYCLE CHECKS PASSED.")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n[FAIL] Integration test exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
