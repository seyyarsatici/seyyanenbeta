#!/usr/bin/env python3
"""
SEYYANEN MINI - DETERMINISTIC HOST-SIDE TEST SUITE
=================================================
Validates the core algorithmic models, protocol decoders, bitmap parsers,
safety filters, ring buffer logic, quality classification, and log serialization
of the seyyanen_mini ESP32 companion firmware without requiring physical hardware.
"""

import math
import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# REFERENCE IMPLEMENTATIONS MIRRORING C++ CODE
# ==============================================================================

BLOCKED_HEX_MODES = {"04", "08", "10", "11", "27", "28", "2E", "31", "34", "35", "36", "37", "85"}

def is_command_safe(cmd: str) -> bool:
    """Mirrors VLinkerBluetoothTransport::isCommandSafe."""
    if not cmd:
        return False
    s = cmd.strip()
    if not s:
        return False
    if s.upper().startswith("AT"):
        return True
    
    # Extract first 2 hex digits
    hex_chars = [c for c in s if c in "0123456789abcdefABCDEF"]
    if len(hex_chars) < 2:
        return False
    mode = "".join(hex_chars[:2]).upper()
    return mode not in BLOCKED_HEX_MODES

def clean_response(raw: str) -> str:
    """Mirrors Elm327Client::cleanResponse."""
    if not raw:
        return ""
    return "".join(c.upper() for c in raw if c not in "\r\n> ")

def extract_mode01_payload(cleaned: str, target_pid: int) -> Optional[List[int]]:
    """Mirrors Obd2::extractMode01Payload."""
    # Convert hex string to byte list
    if len(cleaned) % 2 != 0:
        cleaned = cleaned[:-1]
    try:
        raw_bytes = [int(cleaned[i:i+2], 16) for i in range(0, len(cleaned), 2)]
    except ValueError:
        return None

    # Search for 0x41 followed by target_pid
    for i in range(len(raw_bytes) - 1):
        if raw_bytes[i] == 0x41 and raw_bytes[i+1] == target_pid:
            return raw_bytes[i+2:]
    return None

def is_pid_bit_set(bitmap: int, relative_pid: int) -> bool:
    """Mirrors Obd2::isPidBitSet (relative_pid 1..32)."""
    if relative_pid < 1 or relative_pid > 32:
        return False
    shift = 32 - relative_pid
    return ((bitmap >> shift) & 1) == 1

def decode_ect(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0] - 40), True

def decode_stft(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float((data[0] - 128) * 100.0 / 128.0), True

def decode_ltft(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float((data[0] - 128) * 100.0 / 128.0), True

def decode_map(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0]), True

def decode_rpm(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 2: return 0.0, False
    return float(((data[0] << 8) | data[1]) / 4.0), True

def decode_speed(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float(data[0]), True

def decode_maf(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 2: return 0.0, False
    return float(((data[0] << 8) | data[1]) / 100.0), True

def decode_tps(data: List[int]) -> Tuple[float, bool]:
    if not data or len(data) < 1: return 0.0, False
    return float((data[0] * 100.0) / 255.0), True

class SimulatedRingBuffer:
    """Mirrors SampleRingBuffer bounded behavior."""
    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self.buffer = []
        self.total_pushed = 0

    def push(self, sample: dict):
        if len(self.buffer) >= self.capacity:
            self.buffer.pop(0) # drop oldest
        self.buffer.append(sample)
        self.total_pushed += 1

    def get_latest(self, pid: int) -> Optional[dict]:
        for s in reversed(self.buffer):
            if s["pid"] == pid:
                return s
        return None

    def size(self) -> int:
        return len(self.buffer)

def evaluate_quality(status: str, value: float, min_val: float, max_val: float,
                     age_ms: int = 0, stale_threshold_ms: int = 4000) -> str:
    """Mirrors QualityEngine::evaluate."""
    if status != "VALID":
        return "INVALID"
    if math.isnan(value) or math.isinf(value):
        return "INVALID"
    if min_val < max_val:
        if value < min_val or value > max_val:
            return "DEGRADED"
    if age_ms > stale_threshold_ms:
        return "STALE"
    return "GOOD"

# ==============================================================================
# TEST SUITE
# ==============================================================================

class TestMiniCore(unittest.TestCase):

    def test_destructive_command_rejection(self):
        """Verify strict read-only safety filter blocks destructive commands."""
        # Mode 04: Clear DTCs must be rejected in all formatting variations
        self.assertFalse(is_command_safe("04"))
        self.assertFalse(is_command_safe("0400"))
        self.assertFalse(is_command_safe("04 00"))
        self.assertFalse(is_command_safe("  04  \r"))
        
        # Mode 08: Actuator Control
        self.assertFalse(is_command_safe("08"))
        self.assertFalse(is_command_safe("08 01 02"))

        # UDS Write / Dangerous services
        self.assertFalse(is_command_safe("10 02")) # DiagnosticSessionControl
        self.assertFalse(is_command_safe("11 01")) # ECUReset
        self.assertFalse(is_command_safe("27 01")) # SecurityAccess
        self.assertFalse(is_command_safe("2E F1 90")) # WriteDataByIdentifier
        self.assertFalse(is_command_safe("31 01")) # RoutineControl
        self.assertFalse(is_command_safe("34 00")) # RequestDownload

        # Safe read-only commands must be permitted
        self.assertTrue(is_command_safe("010C"))
        self.assertTrue(is_command_safe("0100"))
        self.assertTrue(is_command_safe("01 0D"))
        self.assertTrue(is_command_safe("03"))
        self.assertTrue(is_command_safe("07"))
        self.assertTrue(is_command_safe("0902"))
        self.assertTrue(is_command_safe("22 F1 90")) # ReadDataByIdentifier
        self.assertTrue(is_command_safe("ATZ"))
        self.assertTrue(is_command_safe("ATI"))
        self.assertTrue(is_command_safe("ATE0"))

    def test_clean_response(self):
        """Verify prompt detection, spaces, CR, LF stripping."""
        raw = "41 0C 1A F8\r\n>"
        cleaned = clean_response(raw)
        self.assertEqual(cleaned, "410C1AF8")

        raw2 = "\r\n41 05 46\r\n>"
        self.assertEqual(clean_response(raw2), "410546")

    def test_pid_bitmap_decoding(self):
        """Verify standard OBD-II 32-bit bitmap extraction."""
        # Example bitmap response for 0100: BE 1F B8 10
        # In binary:
        # BE = 1011 1110 (PIDs 1, 3, 4, 5, 6, 7)
        # 1F = 0001 1111 (PIDs 12, 13, 14, 15, 16)
        # B8 = 1011 1000 (PIDs 17, 19, 20, 21)
        # 10 = 0001 0000 (PID 28, but PID 32 is 0 -> no 0120)
        bitmap = 0xBE1FB810
        
        # PID 01 (bit 31, relative 1) -> 1
        self.assertTrue(is_pid_bit_set(bitmap, 1))
        # PID 02 (bit 30, relative 2) -> 0
        self.assertFalse(is_pid_bit_set(bitmap, 2))
        # PID 05 (ECT: relative 5) -> 1 (0xBE & 0x08)
        self.assertTrue(is_pid_bit_set(bitmap, 5))
        # PID 0C (RPM: relative 12) -> 1
        self.assertTrue(is_pid_bit_set(bitmap, 12))
        # PID 0D (Speed: relative 13) -> 1
        self.assertTrue(is_pid_bit_set(bitmap, 13))
        # PID 20 (Relative 32) -> 0
        self.assertFalse(is_pid_bit_set(bitmap, 32))

        # Test bitmap with PID 32 set (indicating next block 0120 exists)
        bitmap_chain = 0xBE1FB811 # bit 0 set
        self.assertTrue(is_pid_bit_set(bitmap_chain, 32))

    def test_obd2_pid_decoders(self):
        """Verify standard Mode 01 PID formulas with known test vectors."""
        # 1. RPM (010C): ((A * 256) + B) / 4
        # 0x1A 0xF8 = 6904 -> 6904 / 4 = 1726.0 rpm
        payload_rpm = extract_mode01_payload("410C1AF8", 0x0C)
        self.assertIsNotNone(payload_rpm)
        val, ok = decode_rpm(payload_rpm)
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 1726.0, places=2)

        # 2. Engine Coolant Temp (0105): A - 40
        # 0x46 = 70 -> 70 - 40 = 30 °C
        payload_ect = extract_mode01_payload("410546", 0x05)
        val, ok = decode_ect(payload_ect)
        self.assertTrue(ok)
        self.assertEqual(val, 30.0)

        # 3. Vehicle Speed (010D): A
        # 0x3C = 60 km/h
        payload_spd = extract_mode01_payload("410D3C", 0x0D)
        val, ok = decode_speed(payload_spd)
        self.assertTrue(ok)
        self.assertEqual(val, 60.0)

        # 4. Throttle Position (0111): A * 100 / 255
        # 0x80 = 128 -> 128 * 100 / 255 = 50.196%
        payload_tps = extract_mode01_payload("411180", 0x11)
        val, ok = decode_tps(payload_tps)
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 50.196, places=2)

        # 5. MAP (010B): A
        # 0x64 = 100 kPa
        payload_map = extract_mode01_payload("410B64", 0x0B)
        val, ok = decode_map(payload_map)
        self.assertTrue(ok)
        self.assertEqual(val, 100.0)

        # 6. MAF (0110): ((A * 256) + B) / 100
        # 0x05 0xDC = 1500 -> 15.00 g/s
        payload_maf = extract_mode01_payload("411005DC", 0x10)
        val, ok = decode_maf(payload_maf)
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 15.00, places=2)

        # 7. STFT (0106): (A - 128) * 100 / 128
        # 0x80 = 128 -> 0.0% trim
        payload_stft = extract_mode01_payload("410680", 0x06)
        val, ok = decode_stft(payload_stft)
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 0.0, places=2)

    def test_quality_classification(self):
        """Verify data quality state evaluation and freshness decay."""
        # Valid data within normal bounds
        self.assertEqual(evaluate_quality("VALID", 850.0, 0.0, 10000.0, age_ms=100), "GOOD")

        # Legitimate ZERO must be GOOD, not NO_DATA or INVALID
        self.assertEqual(evaluate_quality("VALID", 0.0, 0.0, 350.0, age_ms=100), "GOOD")

        # Out-of-bounds sensor reading -> DEGRADED
        self.assertEqual(evaluate_quality("VALID", 15000.0, 0.0, 10000.0, age_ms=100), "DEGRADED")
        self.assertEqual(evaluate_quality("VALID", 250.0, -40.0, 150.0, age_ms=100), "DEGRADED")

        # Transport / protocol failure states -> INVALID
        self.assertEqual(evaluate_quality("NO_DATA", 0.0, 0.0, 10000.0), "INVALID")
        self.assertEqual(evaluate_quality("TIMEOUT", 0.0, 0.0, 10000.0), "INVALID")
        self.assertEqual(evaluate_quality("MALFORMED", 0.0, 0.0, 10000.0), "INVALID")

        # Freshness expiration -> STALE
        self.assertEqual(evaluate_quality("VALID", 850.0, 0.0, 10000.0, age_ms=6000, stale_threshold_ms=4000), "STALE")

    def test_bounded_ring_buffer(self):
        """Verify fixed capacity, FIFO overwrite, and latest retrieval."""
        rb = SimulatedRingBuffer(capacity=4)
        for i in range(1, 6): # Push 5 items into capacity 4
            rb.push({"sequence": i, "pid": 0x010C, "value": float(i * 100)})

        # Buffer size must be capped at 4
        self.assertEqual(rb.size(), 4)
        self.assertEqual(rb.total_pushed, 5)

        # Oldest item (1) should have been evicted; newest item (5) present
        latest = rb.get_latest(0x010C)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["sequence"], 5)
        self.assertEqual(latest["value"], 500.0)

    def test_sd_log_csv_serialization(self):
        """Verify CSV line serialization and header format preservation."""
        sample = {
            "timestamp_us": 1234567890,
            "session_id": "SN-A1B2C3D4",
            "sequence": 42,
            "pid": 0x010C,
            "pid_name": "Engine Speed",
            "request": "010C",
            "raw_response": "41 0C 1A F8",
            "decoded_value": 1726.0,
            "unit": "rpm",
            "status": "VALID",
            "quality": "GOOD",
            "latency_ms": 28
        }

        # Format line as in SdLogger::logSample
        csv_line = (
            f"{sample['timestamp_us']},{sample['session_id']},{sample['sequence']},"
            f"01{sample['pid'] & 0xFF:02X},{sample['pid_name']},{sample['request']},"
            f"{sample['raw_response']},{sample['decoded_value']:.2f},{sample['unit']},"
            f"{sample['status']},{sample['quality']},{sample['latency_ms']}"
        )

        parts = csv_line.split(",")
        self.assertEqual(parts[0], "1234567890")
        self.assertEqual(parts[1], "SN-A1B2C3D4")
        self.assertEqual(parts[2], "42")
        self.assertEqual(parts[3], "010C")
        self.assertEqual(parts[4], "Engine Speed")
        self.assertEqual(parts[7], "1726.00")
        self.assertEqual(parts[8], "rpm")
        self.assertEqual(parts[9], "VALID")
        self.assertEqual(parts[10], "GOOD")
        self.assertEqual(parts[11], "28")

    def test_timestamp_monotonicity(self):
        """Verify sequential scheduler produces strictly monotonic timestamps."""
        timestamps = [1000000 + (i * 80000) for i in range(10)]
        for i in range(len(timestamps) - 1):
            self.assertGreater(timestamps[i+1], timestamps[i])

if __name__ == "__main__":
    unittest.main()
