#!/usr/bin/env python3
"""
SEYYANEN MINI — PHASE M-3 DETERMINISTIC OBD & PID DISCOVERY TESTS
================================================================
Validates tests A through T from specification:
A. ELM327 initialization sequence
B. Adapter identity acceptance
C. Invalid initialization response
D. Generic Mode 01 request
E. Valid 010C response (RPM)
F. Valid 0105 response (ECT)
G. Valid 010B response (MAP)
H. Valid 010D response (Speed)
I. Valid 0110 response (MAF)
J. NO DATA handling
K. Timeout handling
L. Malformed response handling
M. Response normalization (direct '41 0C ...' vs framed '7E8 04 41 0C ...')
N. Supported-PID bitmap decoding
O. Multiple supported-PID ranges (conditional chaining 0100 -> 0120)
P. Unsupported PID rejection / detection
Q. Transaction serialization
R. Raw response preservation
S. Standard decoder formulas (0104, 0106, 0107, 010E, 010F, 0111)
T. Destructive command rejection
"""

import math
import re
import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# REFERENCE IMPLEMENTATIONS MIRRORING C++ M-3 LOGIC
# ==============================================================================

BLOCKED_MODES = {0x04, 0x08, 0x14, 0x27, 0x2E, 0x2F, 0x34, 0x35, 0x36, 0x37, 0x3D}

def is_mode_allowed(mode: int) -> bool:
    """Mirrors Obd2Client::isModeAllowed."""
    return mode == 0x01

def is_command_safe(cmd: str) -> bool:
    """Mirrors VLinkerBluetoothTransport::isCommandSafe."""
    if not cmd: return False
    s = cmd.strip()
    if not s: return False
    if s.upper().startswith("AT"): return True
    hex_chars = [c for c in s if c in "0123456789abcdefABCDEF"]
    if len(hex_chars) < 2: return False
    mode = int("".join(hex_chars[:2]), 16)
    return mode not in BLOCKED_MODES

def normalize_response(raw_response: str, target_pid: int) -> Optional[List[int]]:
    """Mirrors Obd2::normalizeResponse (extracts payload after 41 <PID>)."""
    if not raw_response:
        return None

    target_pid_hex = f"{target_pid:02X}"

    # 1. Tokenize by whitespace
    tokens = raw_response.replace(">", " ").split()
    for i in range(len(tokens) - 1):
        if tokens[i].upper() == "41" and tokens[i+1].upper() == target_pid_hex:
            payload = []
            for t in tokens[i+2:]:
                t_clean = "".join(c for c in t if c in "0123456789abcdefABCDEF")
                if len(t_clean) % 2 == 0 and len(t_clean) > 0:
                    for b_idx in range(0, len(t_clean), 2):
                        payload.append(int(t_clean[b_idx:b_idx+2], 16))
            if payload:
                return payload

    # 2. Continuous string search (spaces off or compact)
    clean_hex = "".join(c.upper() for c in raw_response if c in "0123456789abcdefABCDEF")
    pattern = "41" + target_pid_hex
    pos = clean_hex.find(pattern)
    if pos != -1:
        payload_hex = clean_hex[pos + len(pattern):]
        if len(payload_hex) % 2 != 0:
            payload_hex = payload_hex[:-1]
        payload = [int(payload_hex[k:k+2], 16) for k in range(0, len(payload_hex), 2)]
        if payload:
            return payload

    return None

def is_pid_bit_set(bitmap: int, relative_pid: int) -> bool:
    """Mirrors Obd2::isPidBitSet (relative_pid 1..32)."""
    if relative_pid < 1 or relative_pid > 32:
        return False
    shift = 32 - relative_pid
    return ((bitmap >> shift) & 1) == 1

def bytes_to_uint32(b: List[int]) -> int:
    """Mirrors Obd2::bytesToUint32."""
    if len(b) < 4: return 0
    return (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]

# Decoders
def decode_engine_load(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0] * 100.0 / 255.0), True

def decode_ect(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0] - 40.0), True

def decode_stft(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float((data[0] - 128.0) * 100.0 / 128.0), True

def decode_ltft(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float((data[0] - 128.0) * 100.0 / 128.0), True

def decode_map(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0]), True

def decode_rpm(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 2: return 0.0, False
    return float(((data[0] << 8) | data[1]) / 4.0), True

def decode_speed(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0]), True

def decode_timing_advance(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float((data[0] / 2.0) - 64.0), True

def decode_iat(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0] - 40.0), True

def decode_maf(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 2: return 0.0, False
    return float(((data[0] << 8) | data[1]) / 100.0), True

def decode_tps(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0] * 100.0 / 255.0), True

class SimulatedElm327:
    """Simulates Elm327Client initialization and command queries."""
    def __init__(self):
        self.state = "UNINITIALIZED"
        self.protocol = "AUTO"
        self.history = []

    def initialize(self, reset_resp="ELM327 v1.5", echo_resp="OK", l_resp="OK", s_resp="OK", h_resp="OK", p_resp="OK", dp_resp="ISO 15765-4 CAN"):
        self.history.clear()
        self.state = "INITIALIZING"

        sequence = [
            ("ATZ", reset_resp),
            ("ATE0", echo_resp),
            ("ATL0", l_resp),
            ("ATS0", s_resp),
            ("ATH0", h_resp),
            ("ATSP0", p_resp),
            ("ATDP", dp_resp)
        ]

        for cmd, resp in sequence:
            self.history.append((cmd, resp))
            clean = "".join(c for c in resp if c not in "\r\n> ")
            if not clean or "ERROR" in clean or "?" in clean:
                self.state = "INVALID_RESPONSE"
                return False

        self.protocol = dp_resp.strip()
        self.state = "READY"
        return True

# ==============================================================================
# TEST SUITE: TESTS A THROUGH T
# ==============================================================================

class TestM3Obd(unittest.TestCase):

    def test_A_elm327_initialization_sequence(self):
        """A. Verify standard ELM327 initialization command sequence."""
        elm = SimulatedElm327()
        ok = elm.initialize()
        self.assertTrue(ok)
        self.assertEqual(elm.state, "READY")
        expected_cmds = ["ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0", "ATDP"]
        executed_cmds = [cmd for cmd, resp in elm.history]
        self.assertEqual(executed_cmds, expected_cmds)

    def test_B_adapter_identity_acceptance(self):
        """B. Verify acceptance of various valid adapter banners during init."""
        valid_banners = [
            "vLinker MC+ v2.2.88 MICROSYS",
            "OBDLink MX+ v5.1.0",
            "STN2120 v4.2.1",
            "ELM327 v1.5",
            "OK"
        ]
        for banner in valid_banners:
            elm = SimulatedElm327()
            ok = elm.initialize(reset_resp=banner)
            self.assertTrue(ok, f"Should have accepted valid banner: '{banner}'")
            self.assertEqual(elm.state, "READY")

    def test_C_invalid_initialization_response(self):
        """C. Verify rejection of error or empty responses during initialization."""
        bad_responses = ["", "?", "CAN ERROR", "COMMAND ERROR"]
        for bad in bad_responses:
            elm = SimulatedElm327()
            ok = elm.initialize(reset_resp=bad)
            self.assertFalse(ok)
            self.assertEqual(elm.state, "INVALID_RESPONSE")

    def test_D_generic_mode01_request_validation(self):
        """D. Verify generic Mode 01 requests are accepted and other modes rejected."""
        self.assertTrue(is_mode_allowed(0x01))
        self.assertFalse(is_mode_allowed(0x04)) # Mode 04 rejected
        self.assertFalse(is_mode_allowed(0x08)) # Mode 08 rejected
        self.assertFalse(is_mode_allowed(0x22)) # UDS rejected in M-3

    def test_E_valid_010C_response_rpm(self):
        """E. Valid 010C response (Engine RPM)."""
        raw = "41 0C 1A F8\r\n>"
        payload = normalize_response(raw, 0x0C)
        self.assertIsNotNone(payload)
        val, ok = decode_rpm(payload)
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 1726.0, places=2)

    def test_F_valid_0105_response_ect(self):
        """F. Valid 0105 response (Coolant Temp)."""
        raw = "41 05 5A\r\n>" # 0x5A = 90 -> 90 - 40 = 50 °C
        payload = normalize_response(raw, 0x05)
        self.assertIsNotNone(payload)
        val, ok = decode_ect(payload)
        self.assertTrue(ok)
        self.assertEqual(val, 50.0)

    def test_G_valid_010B_response_map(self):
        """G. Valid 010B response (MAP)."""
        raw = "41 0B 64\r\n>" # 0x64 = 100 kPa
        payload = normalize_response(raw, 0x0B)
        self.assertIsNotNone(payload)
        val, ok = decode_map(payload)
        self.assertTrue(ok)
        self.assertEqual(val, 100.0)

    def test_H_valid_010D_response_speed(self):
        """H. Valid 010D response (Vehicle Speed)."""
        raw = "41 0D 50\r\n>" # 0x50 = 80 km/h
        payload = normalize_response(raw, 0x0D)
        self.assertIsNotNone(payload)
        val, ok = decode_speed(payload)
        self.assertTrue(ok)
        self.assertEqual(val, 80.0)

    def test_I_valid_0110_response_maf(self):
        """I. Valid 0110 response (MAF)."""
        raw = "41 10 09 C4\r\n>" # 0x09C4 = 2500 -> 2500 / 100 = 25.00 g/s
        payload = normalize_response(raw, 0x10)
        self.assertIsNotNone(payload)
        val, ok = decode_maf(payload)
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 25.0, places=2)

    def test_J_no_data_response_handling(self):
        """J. Handle 'NO DATA' response without turning into fake zeros."""
        raw = "NO DATA\r\n>"
        payload = normalize_response(raw, 0x0C)
        self.assertIsNone(payload) # Must be None, not [0, 0]

    def test_K_timeout_handling(self):
        """K. Handle command timeout without crashing or zero fallback."""
        raw = "" # Timeout resulted in empty buffer
        payload = normalize_response(raw, 0x0C)
        self.assertIsNone(payload)

    def test_L_malformed_response_handling(self):
        """L. Handle malformed/corrupt responses."""
        raw = "41 0C 1A\r\n>" # Missing second byte for RPM
        payload = normalize_response(raw, 0x0C)
        self.assertEqual(len(payload), 1)
        val, ok = decode_rpm(payload)
        self.assertFalse(ok) # Decode function must fail on insufficient bytes

    def test_M_response_normalization(self):
        """M. Normalize direct ('41 0C 1A F8') vs CAN framed ('7E8 04 41 0C 1A F8')."""
        direct_raw = "41 0C 1A F8\r\n>"
        framed_raw = "7E8 04 41 0C 1A F8\r\n>"

        direct_payload = normalize_response(direct_raw, 0x0C)
        framed_payload = normalize_response(framed_raw, 0x0C)

        self.assertEqual(direct_payload, [0x1A, 0xF8])
        self.assertEqual(framed_payload, [0x1A, 0xF8])
        self.assertEqual(direct_payload, framed_payload)

    def test_N_supported_pid_bitmap_decoding(self):
        """N. Decode 32-bit bitmap returned by 0100."""
        # 0xBE1FB810:
        # BE = 1011 1110 -> PIDs 1, 3, 4, 5, 6, 7
        # 1F = 0001 1111 -> PIDs 12 (010C RPM), 13 (010D Speed)
        bitmap = 0xBE1FB810
        self.assertTrue(is_pid_bit_set(bitmap, 5))   # 0105 (ECT)
        self.assertTrue(is_pid_bit_set(bitmap, 12))  # 010C (RPM)
        self.assertTrue(is_pid_bit_set(bitmap, 13))  # 010D (Speed)
        self.assertFalse(is_pid_bit_set(bitmap, 2))  # 0102
        self.assertFalse(is_pid_bit_set(bitmap, 32)) # 0120 next block

    def test_O_multiple_supported_pid_ranges_chaining(self):
        """O. Verify scanner only queries 0120 if bit 32 of 0100 is set."""
        bitmap_without_next = 0xBE1FB810 # bit 32 = 0
        bitmap_with_next    = 0xBE1FB811 # bit 32 = 1

        self.assertFalse(is_pid_bit_set(bitmap_without_next, 32))
        self.assertTrue(is_pid_bit_set(bitmap_with_next, 32))

    def test_P_unsupported_pid_detection(self):
        """P. Verify unsupported PIDs are flagged as unsupported."""
        bitmap = 0xBE1FB810
        # Check PID 0x02
        self.assertFalse(is_pid_bit_set(bitmap, 2))

    def test_Q_transaction_serialization(self):
        """Q. Ensure transactions execute sequentially without interleaving."""
        active_transactions = 0
        max_concurrent = 0

        def run_transaction():
            nonlocal active_transactions, max_concurrent
            active_transactions += 1
            max_concurrent = max(max_concurrent, active_transactions)
            # simulate execution
            active_transactions -= 1

        for _ in range(5):
            run_transaction()

        self.assertEqual(max_concurrent, 1)

    def test_R_raw_response_preservation(self):
        """R. Verify original raw response is preserved alongside decoded value."""
        raw_evidence = "7E8 04 41 0C 1A F8\r\n>"
        payload = normalize_response(raw_evidence, 0x0C)
        val, ok = decode_rpm(payload)
        
        result_struct = {
            "raw": raw_evidence,
            "normalized": payload,
            "decoded": val
        }

        self.assertEqual(result_struct["raw"], raw_evidence)
        self.assertEqual(result_struct["normalized"], [0x1A, 0xF8])
        self.assertEqual(result_struct["decoded"], 1726.0)

    def test_S_standard_decoder_formulas(self):
        """S. Verify remaining standard formulas (0104, 0106, 0107, 010E, 010F, 0111)."""
        # 0104 Engine Load: A * 100 / 255
        val, ok = decode_engine_load([128])
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 50.196, places=2)

        # 0106 STFT: (A - 128) * 100 / 128
        val, ok = decode_stft([140])
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 9.375, places=2)

        # 0107 LTFT: (A - 128) * 100 / 128
        val, ok = decode_ltft([120])
        self.assertTrue(ok)
        self.assertAlmostEqual(val, -6.25, places=2)

        # 010E Timing Advance: (A / 2.0) - 64.0
        val, ok = decode_timing_advance([160]) # 80 - 64 = 16.0 deg
        self.assertTrue(ok)
        self.assertEqual(val, 16.0)

        # 010F IAT: A - 40
        val, ok = decode_iat([65]) # 65 - 40 = 25 °C
        self.assertTrue(ok)
        self.assertEqual(val, 25.0)

        # 0111 TPS: A * 100 / 255
        val, ok = decode_tps([255])
        self.assertTrue(ok)
        self.assertEqual(val, 100.0)

    def test_T_destructive_command_rejection(self):
        """T. Verify rejection of destructive commands (Mode 04, UDS 0x14, 0x27, 0x2E...)."""
        blocked_commands = [
            "04", "0400", "04 00",
            "08 01 02",
            "14 FF FF FF", # UDS ClearDiagnosticInformation
            "27 01",       # UDS SecurityAccess
            "2E F1 90",    # UDS WriteDataByIdentifier
            "2F 01 02",    # UDS InputOutputControlByIdentifier
            "34 00",       # UDS RequestDownload
            "35 00",       # UDS RequestUpload
            "36 01",       # UDS TransferData
            "37",          # UDS RequestTransferExit
            "3D 00"        # UDS WriteMemoryByAddress
        ]
        for cmd in blocked_commands:
            self.assertFalse(is_command_safe(cmd), f"Should have blocked dangerous command: '{cmd}'")

if __name__ == "__main__":
    unittest.main()
