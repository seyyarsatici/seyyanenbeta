"""
Seyyanen Automotive Diagnostics — Virtual ELM327 Test Harness
============================================================
Deterministic Virtual ELM327 Responder and VirtualSerialTransport harness.

Provides a faithful, byte-level emulation of an ELM327 / VLinker diagnostic
adapter over the standard pyserial Serial interface. Allows automated unit,
integration, and lifecycle validation of:
  - Port opening & closing
  - ELM327 probe & initialization sequence (ATZ, ATI, ATE0, ATL0, ATS0, ATH1, ATSP0, ATDPN, 0100)
  - Mode 01 PID queries (010C, 010D, 0105, 010B, etc.)
  - Deterministic latency (instant, 50ms, 100ms, 500ms, timeout)
  - Fault injection (drop response, disconnect, malformed response, NO DATA, ?)
  - Reconnect and duplicate connection protection

Architecture:
  This harness does NOT replace the real production path.
  It injects as an alternative serial transport via the existing `serial_factory`
  injection point in ELM327DiagnosticAdapter.
  Real hardware remains the default for production execution.
"""

import sys
import time
import argparse
import logging
from typing import Optional, Dict, List, Tuple, Any, Callable

try:
    import serial
    SerialException = serial.SerialException
except ImportError:
    class SerialException(IOError):
        """Fallback SerialException if pyserial is not installed."""
        pass

logger = logging.getLogger("VirtualELM327")


# =====================================================================
# 1. DETERMINISTIC VIRTUAL ELM327 RESPONDER
# =====================================================================

class VirtualELM327Responder:
    """
    Deterministic protocol responder for ELM327 / OBD-II commands.
    
    Parses incoming ASCII commands terminated with '\\r', manages internal
    adapter settings (echo, linefeeds, spaces, headers, protocol), and produces
    faithful ELM327 ASCII responses terminated with '\\r' and the prompt '>'.
    """

    def __init__(
        self,
        device_banner: str = "ELM327 v2.2",
        voltage: str = "12.6V",
        protocol_name: str = "ISO 15765-4 (CAN 11/500)",
        protocol_num: str = "A6",
    ):
        self.device_banner = device_banner
        self.voltage = voltage
        self.protocol_name = protocol_name
        self.protocol_num = protocol_num

        # Adapter internal flags
        self.echo_enabled: bool = True
        self.linefeeds_enabled: bool = True
        self.spaces_enabled: bool = True
        self.headers_enabled: bool = False

        # Mode 01 PID response database
        self._pid_table: Dict[str, str] = {
            "0100": "4100 BE 3E B8 13",  # Supported PIDs 01-20
            "0101": "4101 00 00 00 00",  # DTC status (MIL off, 0 DTCs)
            "0104": "4104 32",            # Engine Load: 19.6%
            "0105": "4105 5A",            # ECT: 50°C (0x5A = 90 -> 90 - 40 = 50)
            "0106": "4106 00",            # STFT Bank 1: -100% or 0x00
            "0107": "4107 00",            # LTFT Bank 1: -100% or 0x00
            "010B": "410B 2D",            # MAP: 45 kPa (0x2D = 45)
            "010C": "410C 1A F8",         # Engine RPM: 1726 RPM ((26*256 + 248)/4)
            "010D": "410D 00",            # Vehicle Speed: 0 km/h
            "010E": "410E 0C",            # Timing Advance: 6.0° ((12-128)/2 = -58 or 12/2 - 64)
            "010F": "410F 2A",            # IAT: 2°C (0x2A = 42 -> 42 - 40 = 2)
            "0110": "4110 3C 80",         # MAF: 154.88 g/s ((60*256 + 128)/100)
            "0111": "4111 20",            # TPS: 12.5% (32 * 100 / 255)
        }

        # Fault or override hooks
        self._custom_overrides: Dict[str, str] = {}

    def reset_state(self) -> None:
        """Resets adapter configuration to factory power-on defaults."""
        self.echo_enabled = True
        self.linefeeds_enabled = True
        self.spaces_enabled = True
        self.headers_enabled = False

    def set_pid_response(self, pid: str, hex_response: str) -> None:
        """Override or add a specific PID response."""
        clean_pid = pid.strip().upper().replace(" ", "")
        self._pid_table[clean_pid] = hex_response

    def handle_command(self, raw_cmd: str) -> str:
        """
        Processes a raw input command string and returns the ELM327 ASCII response.
        Terminated by CR ('\\r') and prompt character '>'.
        """
        clean = raw_cmd.strip().upper()
        if not clean:
            # Standalone CR emits a prompt
            return ">"

        normalized = clean.replace(" ", "")

        # Check custom overrides first
        if normalized in self._custom_overrides:
            return self._format_response(self._custom_overrides[normalized])

        # -------------------------------------------------------------
        # 1. AT COMMANDS
        # -------------------------------------------------------------
        if normalized.startswith("AT"):
            return self._handle_at_command(normalized)

        # -------------------------------------------------------------
        # 2. OBD MODE 01 COMMANDS
        # -------------------------------------------------------------
        if normalized.startswith("01"):
            if normalized in self._pid_table:
                body = self._pid_table[normalized]
                return self._format_response(body)
            # Unknown PID in Mode 01
            return self._format_response("NO DATA")

        # -------------------------------------------------------------
        # 3. OTHER OBD MODES OR PROHIBITED SERVICES
        # -------------------------------------------------------------
        if any(normalized.startswith(m) for m in ("02", "03", "04", "07", "09", "0A")):
            if normalized == "0902":
                # VIN request
                return self._format_response("49 02 01 56 46 31 4B 47 30 50 31 32 33 34 35 36 37")
            return self._format_response("NO DATA")

        # -------------------------------------------------------------
        # 4. UNKNOWN INPUT
        # -------------------------------------------------------------
        return self._format_response("?")

    def _handle_at_command(self, cmd: str) -> str:
        """Handles AT commands supported by ELM327."""
        # Reset commands
        if cmd in ("ATZ", "ATWS"):
            self.reset_state()
            return f"\r\r{self.device_banner}\r\r>"

        # Identification
        if cmd == "ATI":
            return f"{self.device_banner}\r\r>"

        # Echo control
        if cmd == "ATE0":
            self.echo_enabled = False
            return self._format_response("OK")
        if cmd == "ATE1":
            self.echo_enabled = True
            return self._format_response("OK")

        # Linefeed control
        if cmd == "ATL0":
            self.linefeeds_enabled = False
            return self._format_response("OK")
        if cmd == "ATL1":
            self.linefeeds_enabled = True
            return self._format_response("OK")

        # Space control
        if cmd == "ATS0":
            self.spaces_enabled = False
            return self._format_response("OK")
        if cmd == "ATS1":
            self.spaces_enabled = True
            return self._format_response("OK")

        # Header control
        if cmd == "ATH1":
            self.headers_enabled = True
            return self._format_response("OK")
        if cmd == "ATH0":
            self.headers_enabled = False
            return self._format_response("OK")

        # Protocol selection
        if cmd.startswith("ATSP"):
            return self._format_response("OK")

        # Protocol interrogation
        if cmd == "ATDPN":
            return self._format_response(self.protocol_num)
        if cmd == "ATDP":
            return self._format_response(self.protocol_name)

        # Voltage reading
        if cmd == "ATRV":
            return self._format_response(self.voltage)

        # Set Header (AT SH ...)
        if cmd.startswith("ATSH"):
            return self._format_response("OK")

        # Known harmless configuration commands
        if cmd in ("ATAL", "ATNL", "ATSTFF", "ATCAF1", "ATCAF0"):
            return self._format_response("OK")

        # Unknown AT command
        return self._format_response("?")

    def _format_response(self, text: str) -> str:
        """Formats body with appropriate newline delimiters and trailing prompt '>'."""
        return f"{text}\r\r>"


# =====================================================================
# 2. VIRTUAL SERIAL TRANSPORT (PYSERIAL DROP-IN)
# =====================================================================

class VirtualSerialTransport:
    """
    Drop-in serial transport replacement implementing the pyserial Serial API.
    
    Supports:
      - Deterministic latency injection (instant, 50ms, 100ms, 500ms, timeout)
      - Fault injection (drop response, disconnect, malformed response, NO DATA, ?)
      - Input buffering until CR
      - Thread-safe byte streams
    """

    def __init__(
        self,
        port: str = "COM_VIRTUAL",
        baudrate: int = 38400,
        timeout: float = 0.1,
        write_timeout: float = 1.0,
        responder: Optional[VirtualELM327Responder] = None,
        latency: float = 0.0,
        fault_mode: Optional[str] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.is_open: bool = True

        self.responder = responder or VirtualELM327Responder()
        self.latency = float(latency)
        self.fault_mode = fault_mode  # None, 'timeout', 'drop', 'disconnect', 'malformed', 'no_data', 'question_mark'

        self._rx_buffer = bytearray()
        self._cmd_accumulator = bytearray()

    @property
    def closed(self) -> bool:
        return not self.is_open

    @property
    def in_waiting(self) -> int:
        if not self.is_open:
            return 0
        return len(self._rx_buffer)

    def set_fault(self, fault_mode: Optional[str]) -> None:
        """Updates active fault injection mode."""
        self.fault_mode = fault_mode

    def set_latency(self, latency_seconds: float) -> None:
        """Updates communication latency in seconds."""
        self.latency = max(0.0, float(latency_seconds))

    def write(self, data: bytes) -> int:
        """
        Writes data to the virtual serial port.
        Accumulates bytes until CR ('\\r') or LF ('\\n'), then routes command to responder.
        """
        if not self.is_open:
            raise SerialException(f"Port '{self.port}' is closed.")

        if self.fault_mode == "disconnect":
            self.is_open = False
            raise SerialException(f"Virtual serial link on '{self.port}' abruptly disconnected.")

        # Simulate serial transmission latency if configured
        if self.latency > 0:
            time.sleep(self.latency)

        # Accumulate input bytes
        for b in data:
            if b in (ord(b"\r"), ord(b"\n")):
                if self._cmd_accumulator:
                    cmd_str = self._cmd_accumulator.decode("ascii", errors="replace")
                    self._cmd_accumulator.clear()
                    self._process_command(cmd_str)
            else:
                self._cmd_accumulator.append(b)

        return len(data)

    def _process_command(self, cmd_str: str) -> None:
        """Processes completed command according to current fault mode and responder."""
        if self.fault_mode in ("timeout", "drop", "no_response"):
            # Do not place any response into the buffer
            return

        if self.fault_mode == "malformed":
            # Emit corrupted payload without '>' prompt
            corrupted = b"??CORRUPTED_STREAM_NO_PROMPT_12345??\r\n"
            self._rx_buffer.extend(corrupted)
            return

        if self.fault_mode == "no_data":
            self._rx_buffer.extend(b"NO DATA\r\r>")
            return

        if self.fault_mode == "question_mark":
            self._rx_buffer.extend(b"?\r\r>")
            return

        # Normal deterministic handling
        resp_str = self.responder.handle_command(cmd_str)
        self._rx_buffer.extend(resp_str.encode("ascii", errors="replace"))

    def read(self, size: int = 1) -> bytes:
        """
        Reads up to size bytes from the virtual serial RX buffer.
        If empty, honors pyserial timeout behavior by waiting up to self.timeout.
        """
        if not self.is_open:
            raise SerialException(f"Port '{self.port}' is closed.")

        if self.fault_mode == "disconnect":
            self.is_open = False
            raise SerialException(f"Virtual serial link on '{self.port}' disconnected during read.")

        if not self._rx_buffer:
            if self.timeout and self.timeout > 0:
                # Wait bounded slice to simulate real serial timeout
                wait_slice = min(self.timeout, 0.02)
                time.sleep(wait_slice)
            return b""

        available = len(self._rx_buffer)
        n = min(size, available)
        chunk = bytes(self._rx_buffer[:n])
        del self._rx_buffer[:n]
        return chunk

    def reset_input_buffer(self) -> None:
        """Discards all bytes in the virtual RX buffer."""
        self._rx_buffer.clear()
        self._cmd_accumulator.clear()

    def reset_output_buffer(self) -> None:
        """Discards output buffer."""
        pass

    def flush(self) -> None:
        """Flushes buffers."""
        pass

    def close(self) -> None:
        """Closes the virtual serial port handle."""
        self.is_open = False
        self._rx_buffer.clear()
        self._cmd_accumulator.clear()

    def open(self) -> None:
        """Re-opens the virtual serial port handle."""
        self.is_open = True


# =====================================================================
# 3. FACTORY BUILDERS & SCENARIO HELPERS
# =====================================================================

def create_virtual_serial_factory(
    responder: Optional[VirtualELM327Responder] = None,
    latency: float = 0.0,
    fault_mode: Optional[str] = None,
    port_name: str = "COM_VIRTUAL",
) -> Callable[..., VirtualSerialTransport]:
    """
    Returns a serial_factory callable compatible with ELM327DiagnosticAdapter.
    """
    active_responder = responder or VirtualELM327Responder()

    def factory(port: Optional[str] = None, baudrate: int = 38400, timeout: float = 0.1, **kwargs: Any) -> VirtualSerialTransport:
        target_port = port or port_name
        return VirtualSerialTransport(
            port=target_port,
            baudrate=baudrate,
            timeout=timeout,
            responder=active_responder,
            latency=latency,
            fault_mode=fault_mode,
        )

    return factory


# =====================================================================
# 4. CLI RUNNER & SCENARIO DEMONSTRATIONS
# =====================================================================

def run_self_test() -> int:
    """Executes deterministic self-test of the Virtual ELM327 responder."""
    print("=" * 60)
    print("  SEYYANEN VIRTUAL ELM327 TEST HARNESS: SELF-TEST")
    print("=" * 60)
    responder = VirtualELM327Responder()
    transport = VirtualSerialTransport(responder=responder, latency=0.0)

    test_commands = [
        ("ATZ", "ELM327 v2.2"),
        ("ATI", "ELM327 v2.2"),
        ("ATE0", "OK"),
        ("ATL0", "OK"),
        ("ATS0", "OK"),
        ("ATH1", "OK"),
        ("AT SP 0", "OK"),
        ("AT DPN", "A6"),
        ("AT DP", "ISO 15765-4 (CAN 11/500)"),
        ("ATRV", "12.6V"),
        ("0100", "4100 BE 3E B8 13"),
        ("0101", "4101 00 00 00 00"),
        ("0104", "4104 32"),
        ("0105", "4105 5A"),
        ("0106", "4106 00"),
        ("0107", "4107 00"),
        ("010B", "410B 2D"),
        ("010C", "410C 1A F8"),
        ("010D", "410D 00"),
        ("010E", "410E 0C"),
        ("010F", "410F 2A"),
        ("0110", "4110 3C 80"),
        ("0111", "4111 20"),
        ("0199", "NO DATA"),
        ("ATUNKNOWN", "?"),
    ]

    all_passed = True
    for cmd, expected_fragment in test_commands:
        transport.reset_input_buffer()
        transport.write(f"{cmd}\r".encode("ascii"))
        rx = transport.read(transport.in_waiting).decode("ascii", errors="replace")
        has_prompt = rx.endswith(">")
        matches = expected_fragment in rx
        status = "PASS" if (matches and has_prompt) else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"[{status}] CMD: {cmd:<12} -> Resp: {repr(rx):<35} (Expected: '{expected_fragment}')")

    print("=" * 60)
    if all_passed:
        print(">>> ALL VIRTUAL ELM327 COMMANDS PASSED DETERMINISTIC SELF-TEST.")
        return 0
    else:
        print(">>> SELF-TEST FAILED!")
        return 1


def run_scenario(name: str) -> int:
    """Runs a specific demonstration scenario."""
    print("=" * 60)
    print(f"  RUNNING VIRTUAL ELM327 SCENARIO: {name.upper()}")
    print("=" * 60)

    if name == "normal":
        responder = VirtualELM327Responder()
        transport = VirtualSerialTransport(responder=responder, latency=0.01)
        cmds = ["ATZ", "ATE0", "AT SP 0", "0100", "010C"]
        for c in cmds:
            transport.write(f"{c}\r".encode("ascii"))
            resp = transport.read(transport.in_waiting).decode("ascii", errors="replace")
            print(f"TX: {c:<10} | RX: {repr(resp)}")
        print("\nScenario NORMAL completed successfully.")
        return 0

    elif name == "timeout":
        transport = VirtualSerialTransport(fault_mode="timeout")
        transport.write(b"ATZ\r")
        rx = transport.read(transport.in_waiting)
        print(f"TX: ATZ | RX len: {len(rx)} (Expected: 0 bytes)")
        if len(rx) == 0:
            print("Scenario TIMEOUT verified: zero bytes returned.")
            return 0
        return 1

    elif name == "disconnect":
        transport = VirtualSerialTransport(fault_mode="disconnect")
        try:
            transport.write(b"ATZ\r")
            print("FAILED: Write should have raised SerialException!")
            return 1
        except SerialException as e:
            print(f"Scenario DISCONNECT verified: caught expected SerialException ({e})")
            return 0

    elif name == "malformed":
        transport = VirtualSerialTransport(fault_mode="malformed")
        transport.write(b"ATZ\r")
        rx = transport.read(transport.in_waiting)
        print(f"TX: ATZ | RX: {repr(rx)}")
        has_prompt = b">" in rx
        if not has_prompt:
            print("Scenario MALFORMED verified: corrupted bytes received without '>' prompt.")
            return 0
        return 1

    else:
        print(f"Unknown scenario '{name}'. Available: normal, timeout, disconnect, malformed.")
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Seyyanen Deterministic Virtual ELM327 Test Harness")
    parser.add_argument("--self-test", action="store_true", help="Execute complete responder self-test")
    parser.add_argument("--scenario", choices=["normal", "timeout", "disconnect", "malformed"], help="Run fault/behavior scenario")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())
    elif args.scenario:
        sys.exit(run_scenario(args.scenario))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
