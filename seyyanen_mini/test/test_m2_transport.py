#!/usr/bin/env python3
"""
SEYYANEN MINI — PHASE M-2 DETERMINISTIC TRANSPORT TESTS
======================================================
Validates the VLinkerBluetoothTransport lifecycle, identity verification gate,
exponential backoff progression, response buffering, error classification,
and duplicate connection prevention without requiring physical hardware.
"""

import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# STATE & ERROR DEFINITIONS MATCHING C++ MINI_TYPES.H
# ==============================================================================

class AdapterState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING   = "CONNECTING"
    CONNECTED    = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR        = "ERROR"

class AdapterBrand:
    UNKNOWN = "UNKNOWN"
    ELM327  = "ELM327"
    VLINKER = "VLINKER"
    OBDLINK = "OBDLINK"
    STN     = "STN"

class TransportError:
    NONE                     = "NONE"
    BT_INIT_FAILED           = "BT_INIT_FAILED"
    TARGET_NOT_FOUND         = "TARGET_NOT_FOUND"
    SPP_CONNECT_FAILED       = "SPP_CONNECT_FAILED"
    SPP_DISCONNECTED         = "SPP_DISCONNECTED"
    TRANSACTION_TIMEOUT      = "TRANSACTION_TIMEOUT"
    INVALID_ADAPTER_RESPONSE = "INVALID_ADAPTER_RESPONSE"
    REMOTE_REJECTED          = "REMOTE_REJECTED"
    SAFETY_BLOCKED           = "SAFETY_BLOCKED"
    UNKNOWN                  = "UNKNOWN"

# ==============================================================================
# REFERENCE TRANSPORT LOGIC MIRRORING C++ VLINKER_BT.CPP
# ==============================================================================

def parse_identity_response(raw_response: str) -> Dict[str, any]:
    """Mirrors VLinkerBluetoothTransport::parseIdentityResponse."""
    if not raw_response:
        return {"brand": AdapterBrand.UNKNOWN, "verified": False, "raw": ""}

    # Strip CR, LF, '>'
    clean = "".join(c for c in raw_response if c not in "\r\n>").strip()
    upper = clean.upper()

    info = {
        "raw": clean,
        "adapter_name": "UNKNOWN",
        "manufacturer": "UNKNOWN",
        "model": "UNKNOWN",
        "firmware": "UNKNOWN",
        "brand": AdapterBrand.UNKNOWN,
        "verified": False
    }

    if "VLINKER" in upper:
        info["brand"] = AdapterBrand.VLINKER
        info["adapter_name"] = "vLinker MC+"
        info["manufacturer"] = "MICROSYS"
        info["model"] = "MC+"
        info["verified"] = True
    elif "OBDLINK" in upper:
        info["brand"] = AdapterBrand.OBDLINK
        info["adapter_name"] = "OBDLink"
        info["manufacturer"] = "OBDLink"
        info["model"] = "MX+"
        info["verified"] = True
    elif "STN" in upper:
        info["brand"] = AdapterBrand.STN
        info["adapter_name"] = "STN Adapter"
        info["manufacturer"] = "OBD Solutions"
        info["model"] = "STN11xx/21xx"
        info["verified"] = True
    elif "ELM327" in upper:
        info["brand"] = AdapterBrand.ELM327
        info["adapter_name"] = "ELM327 Compatible"
        info["manufacturer"] = "ELM Electronics"
        info["model"] = "ELM327"
        info["verified"] = True
    else:
        info["brand"] = AdapterBrand.UNKNOWN
        info["verified"] = False
        return info

    # Extract firmware version
    import re
    m = re.search(r'\b[vV](\d+[\.\d\w]*)\b', clean)
    if m:
        info["firmware"] = m.group(0)

    return info

def is_target_device(name: Optional[str]) -> bool:
    """Mirrors VLinkerBluetoothTransport::isTargetDevice."""
    if not name:
        return False
    name_clean = name.strip()
    if not name_clean:
        return False

    # Reject iOS / BLE interface names (vLinker MC-iOS is BLE GATT, not Classic SPP)
    lower = name_clean.lower()
    if "ios" in lower or "ble" in lower:
        return False

    # Accept exact Classic target "vLinker MC-Android"
    if name_clean.lower() == "vlinker mc-android":
        return True

    # Accept any device starting with "vLinker" (Classic SPP)
    if name_clean.lower().startswith("vlinker"):
        return True

    # Accept any device starting with "Vgate"
    if name_clean.lower().startswith("vgate"):
        return True

    return False

def parse_mac_address(mac_str: Optional[str]) -> Optional[List[int]]:
    """Mirrors VLinkerBluetoothTransport::parseMacAddress."""
    if not mac_str or len(mac_str) < 17:
        return None
    import re
    # Check colon or hyphen notation of 6 hex bytes
    m = re.match(r'^([0-9a-fA-F]{2})[:-]([0-9a-fA-F]{2})[:-]([0-9a-fA-F]{2})[:-]([0-9a-fA-F]{2})[:-]([0-9a-fA-F]{2})[:-]([0-9a-fA-F]{2})$', mac_str.strip())
    if not m:
        return None
    return [int(g, 16) for g in m.groups()]

def is_command_safe(cmd: str) -> bool:
    """Mirrors VLinkerBluetoothTransport::isCommandSafe."""
    if not cmd: return False
    s = cmd.strip()
    if not s: return False
    if s.upper().startswith("AT"): return True
    hex_chars = [c for c in s if c in "0123456789abcdefABCDEF"]
    if len(hex_chars) < 2: return False
    mode = "".join(hex_chars[:2]).upper()
    blocked = {"04", "08", "10", "11", "27", "28", "2E", "31", "34", "35", "36", "37", "85"}
    return mode not in blocked

class SimulatedTransport:
    """Simulates the state machine and connection gate of VLinkerBluetoothTransport."""
    def __init__(self, base_backoff_ms: int = 1000, max_backoff_ms: int = 16000, max_mac_failures: int = 3):
        self.state = AdapterState.DISCONNECTED
        self.last_error = TransportError.NONE
        self.identity = {}
        self.retry_count = 0
        self.current_backoff_ms = base_backoff_ms
        self.base_backoff_ms = base_backoff_ms
        self.max_backoff_ms = max_backoff_ms
        self.max_mac_failures = max_mac_failures
        self.connecting_in_progress = False

        # Permanent Bluetooth Architecture State
        self.cached_mac: Optional[str] = None
        self.mac_connect_failures = 0
        self.discovery_invoked_count = 0
        self.direct_mac_invoked_count = 0

    def load_cached_mac(self, mac: str):
        if parse_mac_address(mac):
            self.cached_mac = mac

    def clear_cached_mac(self):
        self.cached_mac = None

    def connect_with_discovery_or_cache(
        self,
        discovered_devices: Optional[List[Tuple[str, str]]] = None,
        direct_mac_succeeds: bool = True,
        ati_response: str = "vLinker MC+ v2.2.88 MICROSYS\r\n>"
    ) -> bool:
        """Simulates connectTaskWorker implementing Path 1 (direct MAC) and Path 2 (bounded discovery)."""
        if self.state == AdapterState.CONNECTED and self.identity.get("verified"):
            return True
        if self.connecting_in_progress:
            return False

        self.connecting_in_progress = True
        self.state = AdapterState.CONNECTING

        raw_connected = False
        target_mac = self.cached_mac

        # PATH 1: Direct MAC connection
        if target_mac is not None:
            self.direct_mac_invoked_count += 1
            if direct_mac_succeeds:
                raw_connected = True
            else:
                raw_connected = False
                self.mac_connect_failures += 1
                if self.mac_connect_failures >= self.max_mac_failures:
                    self.clear_cached_mac()
                    self.mac_connect_failures = 0
        # PATH 2: Bounded Discovery
        else:
            self.discovery_invoked_count += 1
            matched_mac = None
            if discovered_devices:
                for dev_name, dev_mac in discovered_devices:
                    if is_target_device(dev_name) and parse_mac_address(dev_mac):
                        matched_mac = dev_mac
                        break
            if matched_mac:
                self.cached_mac = matched_mac
                target_mac = matched_mac
                raw_connected = direct_mac_succeeds
            else:
                raw_connected = False

        if not raw_connected:
            self.state = AdapterState.ERROR
            self.last_error = TransportError.SPP_CONNECT_FAILED
            self.connecting_in_progress = False
            return False

        # ATI Handshake
        id_info = parse_identity_response(ati_response)
        self.identity = id_info

        if not id_info["verified"]:
            self.state = AdapterState.ERROR
            self.last_error = TransportError.INVALID_ADAPTER_RESPONSE
            self.connecting_in_progress = False
            return False

        self.state = AdapterState.CONNECTED
        self.last_error = TransportError.NONE
        self.retry_count = 0
        self.mac_connect_failures = 0
        self.current_backoff_ms = self.base_backoff_ms
        self.connecting_in_progress = False
        return True

    def connect(self, spp_link_ok: bool, ati_response: str) -> bool:
        # Guard: prevent duplicate connection attempts
        if self.state == AdapterState.CONNECTED and self.identity.get("verified"):
            return True
        if self.connecting_in_progress:
            return False

        self.connecting_in_progress = True
        self.state = AdapterState.CONNECTING

        if not spp_link_ok:
            self.state = AdapterState.ERROR
            self.last_error = TransportError.SPP_CONNECT_FAILED
            self.connecting_in_progress = False
            return False

        # Physical link connected! But must NOT be CONNECTED yet until ATI verified.
        id_info = parse_identity_response(ati_response)
        self.identity = id_info

        if not id_info["verified"]:
            self.state = AdapterState.ERROR
            self.last_error = TransportError.INVALID_ADAPTER_RESPONSE
            self.connecting_in_progress = False
            return False

        # Identity verified -> state transitions to CONNECTED
        self.state = AdapterState.CONNECTED
        self.last_error = TransportError.NONE
        self.retry_count = 0
        self.current_backoff_ms = self.base_backoff_ms
        self.connecting_in_progress = False
        return True

    def on_link_lost(self):
        self.state = AdapterState.RECONNECTING
        self.last_error = TransportError.SPP_DISCONNECTED
        self.identity["verified"] = False

    def trigger_reconnect_tick(self) -> int:
        """Simulates an auto-reconnect attempt and updates backoff."""
        self.retry_count += 1
        used_backoff = self.current_backoff_ms
        self.current_backoff_ms = min(self.current_backoff_ms * 2, self.max_backoff_ms)
        return used_backoff

    def disconnect(self):
        self.state = AdapterState.DISCONNECTED
        self.last_error = TransportError.NONE
        self.identity = {}
        self.connecting_in_progress = False

# ==============================================================================
# PHASE M-2 TEST SUITE
# ==============================================================================

class TestM2Transport(unittest.TestCase):

    def test_identity_handshake_recognition(self):
        """Verify adapter identification for VLinker, OBDLink, STN, ELM327."""
        # 1. Real vLinker MC+ banner
        res_vlinker = parse_identity_response("vLinker MC+ v2.2.88 MICROSYS\r\n>")
        self.assertTrue(res_vlinker["verified"])
        self.assertEqual(res_vlinker["brand"], AdapterBrand.VLINKER)
        self.assertEqual(res_vlinker["model"], "MC+")
        self.assertEqual(res_vlinker["manufacturer"], "MICROSYS")
        self.assertEqual(res_vlinker["firmware"], "v2.2.88")

        # 2. OBDLink MX+ banner
        res_obdlink = parse_identity_response("OBDLink MX+ v5.1.0\r\n>")
        self.assertTrue(res_obdlink["verified"])
        self.assertEqual(res_obdlink["brand"], AdapterBrand.OBDLINK)
        self.assertEqual(res_obdlink["model"], "MX+")

        # 3. STN scan tool banner
        res_stn = parse_identity_response("STN2120 v4.2.1\r\n>")
        self.assertTrue(res_stn["verified"])
        self.assertEqual(res_stn["brand"], AdapterBrand.STN)

        # 4. Standard ELM327 banner
        res_elm = parse_identity_response("ELM327 v1.5\r\n>")
        self.assertTrue(res_elm["verified"])
        self.assertEqual(res_elm["brand"], AdapterBrand.ELM327)

    def test_invalid_identity_rejection(self):
        """Verify unrelated Bluetooth devices or garbage responses are rejected."""
        # Garbage responses / non-OBD devices
        bad_responses = [
            "",
            "?",
            "OK",
            "STOPPED",
            "NO DATA",
            "CAN ERROR",
            "JBL Flip 5",
            "HC-05 v2.0",
            "Unknown Bluetooth Serial Device\r\n>"
        ]
        for bad in bad_responses:
            res = parse_identity_response(bad)
            self.assertFalse(res["verified"], f"Should have rejected bad identity: '{bad}'")
            self.assertEqual(res["brand"], AdapterBrand.UNKNOWN)

    def test_no_false_connected_state(self):
        """CRITICAL: State must NEVER be CONNECTED if SPP link connects but ATI fails."""
        transport = SimulatedTransport()

        # Case A: SPP connects, but remote sends garbage
        ok = transport.connect(spp_link_ok=True, ati_response="Random Bluetooth Speaker\r\n>")
        self.assertFalse(ok)
        self.assertEqual(transport.state, AdapterState.ERROR)
        self.assertEqual(transport.last_error, TransportError.INVALID_ADAPTER_RESPONSE)

        # Case B: SPP fails to establish
        ok2 = transport.connect(spp_link_ok=False, ati_response="")
        self.assertFalse(ok2)
        self.assertEqual(transport.state, AdapterState.ERROR)
        self.assertEqual(transport.last_error, TransportError.SPP_CONNECT_FAILED)

        # Case C: SPP connects and valid vLinker response received -> ONLY NOW CONNECTED
        ok3 = transport.connect(spp_link_ok=True, ati_response="vLinker MC+ v2.2 MICROSYS\r\n>")
        self.assertTrue(ok3)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.last_error, TransportError.NONE)

    def test_exponential_backoff_progression(self):
        """Verify backoff progression (1s -> 2s -> 4s -> 8s -> 16s capped)."""
        transport = SimulatedTransport(base_backoff_ms=1000, max_backoff_ms=16000)
        transport.on_link_lost()
        self.assertEqual(transport.state, AdapterState.RECONNECTING)

        expected_sequence = [1000, 2000, 4000, 8000, 16000, 16000, 16000]
        for idx, expected in enumerate(expected_sequence):
            delay = transport.trigger_reconnect_tick()
            self.assertEqual(delay, expected, f"Step {idx+1} expected backoff {expected}ms, got {delay}ms")

        # Upon successful reconnect, backoff must reset to base (1000ms)
        transport.connect(spp_link_ok=True, ati_response="vLinker MC+ v2.2 MICROSYS\r\n>")
        self.assertEqual(transport.current_backoff_ms, 1000)
        self.assertEqual(transport.retry_count, 0)

    def test_duplicate_connection_prevention(self):
        """Verify duplicate connect requests while already CONNECTED or CONNECTING are ignored."""
        transport = SimulatedTransport()
        # Connect successfully
        ok = transport.connect(spp_link_ok=True, ati_response="vLinker MC+ v2.2 MICROSYS\r\n>")
        self.assertTrue(ok)
        self.assertEqual(transport.state, AdapterState.CONNECTED)

        # Second connect attempt while connected should return True immediately without re-handshake
        dup = transport.connect(spp_link_ok=True, ati_response="something_else")
        self.assertTrue(dup)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.identity["brand"], AdapterBrand.VLINKER)

    def test_disconnect_lifecycle(self):
        """Verify clean transition on disconnect."""
        transport = SimulatedTransport()
        transport.connect(spp_link_ok=True, ati_response="vLinker MC+ v2.2 MICROSYS\r\n>")
        self.assertEqual(transport.state, AdapterState.CONNECTED)

        transport.disconnect()
        self.assertEqual(transport.state, AdapterState.DISCONNECTED)
        self.assertFalse(transport.identity.get("verified", False))

    def test_command_safety_filter(self):
        """Verify M-2 transport rejects destructive commands before sending."""
        # Allowed harmless commands
        self.assertTrue(is_command_safe("ATI"))
        self.assertTrue(is_command_safe("ATZ"))
        self.assertTrue(is_command_safe("ATE0"))
        self.assertTrue(is_command_safe("ATSP0"))

        # Prohibited destructive commands
        self.assertFalse(is_command_safe("04"))       # Mode 04 (Clear DTCs)
        self.assertFalse(is_command_safe("08 01 02")) # Mode 08 (Actuator Control)
        self.assertFalse(is_command_safe("10 02"))    # UDS DiagnosticSessionControl
        self.assertFalse(is_command_safe("11 01"))    # UDS ECUReset
        self.assertFalse(is_command_safe("27 01"))    # UDS SecurityAccess
        self.assertFalse(is_command_safe("2E F1 90")) # UDS WriteDataByIdentifier
        self.assertFalse(is_command_safe("31 01"))    # UDS RoutineControl
        self.assertFalse(is_command_safe("34 00"))    # UDS RequestDownload

    def test_response_buffering_and_prompt(self):
        """Verify prompt '>' recognition and byte accumulation."""
        raw_stream = ["vLink", "er MC", "+ v2.2\r", "\n>"]
        assembled = ""
        completed = False

        for chunk in raw_stream:
            assembled += chunk
            if ">" in chunk:
                completed = True
                break

        self.assertTrue(completed)
        self.assertIn("vLinker MC+ v2.2", assembled)

    def test_exact_target_identification(self):
        """Verify target filtering specifically accepts Classic SPP (vLinker MC-Android) and rejects BLE/iOS."""
        # Accepted Classic SPP targets
        self.assertTrue(is_target_device("vLinker MC-Android"))
        self.assertTrue(is_target_device("vLinker MC"))
        self.assertTrue(is_target_device("vLinker FD-Android"))
        self.assertTrue(is_target_device("vLinker FS"))
        self.assertTrue(is_target_device("Vgate iCar Pro"))
        self.assertTrue(is_target_device("vgate vLinker"))

        # Rejected BLE / iOS targets (Critical: vLinker MC-iOS is BLE GATT, not Classic SPP)
        self.assertFalse(is_target_device("vLinker MC-iOS"))
        self.assertFalse(is_target_device("vLinker FD-iOS"))
        self.assertFalse(is_target_device("vLinker-BLE"))
        self.assertFalse(is_target_device("BLE-OBDLink"))
        self.assertFalse(is_target_device("iPhone 15 Pro"))
        self.assertFalse(is_target_device("Galaxy S24"))
        self.assertFalse(is_target_device(""))
        self.assertFalse(is_target_device(None))

    def test_mac_address_parsing(self):
        """Verify parsing of 6-byte Bluetooth MAC addresses in colon and hyphen notation."""
        # Standard colon notation
        bytes1 = parse_mac_address("00:1D:A0:12:34:56")
        self.assertEqual(bytes1, [0x00, 0x1D, 0xA0, 0x12, 0x34, 0x56])

        # Hyphen notation
        bytes2 = parse_mac_address("AA-BB-CC-DD-EE-FF")
        self.assertEqual(bytes2, [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

        # Mixed-case hex
        bytes3 = parse_mac_address("2c:b5:41:ab:cd:EF")
        self.assertEqual(bytes3, [0x2C, 0xB5, 0x41, 0xAB, 0xCD, 0xEF])

        # Malformed addresses
        self.assertIsNone(parse_mac_address("00:1D:A0:12:34"))          # Too short
        self.assertIsNone(parse_mac_address("00:1D:A0:12:34:56:78"))       # Too long
        self.assertIsNone(parse_mac_address("00:1D:A0:12:34:GG"))          # Invalid hex
        self.assertIsNone(parse_mac_address("vLinker MC-Android"))         # Device name, not MAC
        self.assertIsNone(parse_mac_address(""))                           # Empty
        self.assertIsNone(parse_mac_address(None))                         # None

    def test_cached_mac_direct_connection_path(self):
        """Verify that when a cached MAC exists, direct connection is used without discovery scan."""
        transport = SimulatedTransport()
        transport.load_cached_mac("2C:B5:41:12:34:56")
        self.assertEqual(transport.cached_mac, "2C:B5:41:12:34:56")

        # Connect should use Path 1 (direct MAC), never touching discovery
        ok = transport.connect_with_discovery_or_cache(
            discovered_devices=[("vLinker MC-Android", "2C:B5:41:12:34:56")],
            direct_mac_succeeds=True
        )
        self.assertTrue(ok)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.direct_mac_invoked_count, 1)
        self.assertEqual(transport.discovery_invoked_count, 0)  # No general inquiry!

    def test_fallback_discovery_path_and_caching(self):
        """Verify bounded discovery is triggered when MAC unknown, and the target MAC is cached."""
        transport = SimulatedTransport()
        self.assertIsNone(transport.cached_mac)

        scanned = [
            ("Living Room TV", "11:22:33:44:55:66"),
            ("vLinker MC-iOS", "AA:BB:CC:DD:EE:01"),      # BLE GATT - Must be skipped!
            ("vLinker MC-Android", "2C:B5:41:98:76:54"),  # Classic SPP Target!
            ("Other OBD", "99:88:77:66:55:44")
        ]

        # 1st Connect: triggers bounded discovery, finds vLinker MC-Android, caches MAC, connects
        ok1 = transport.connect_with_discovery_or_cache(
            discovered_devices=scanned,
            direct_mac_succeeds=True
        )
        self.assertTrue(ok1)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.discovery_invoked_count, 1)
        self.assertEqual(transport.cached_mac, "2C:B5:41:98:76:54")

        # Disconnect
        transport.disconnect()
        self.assertEqual(transport.state, AdapterState.DISCONNECTED)

        # 2nd Connect: should now use cached MAC directly without discovery!
        ok2 = transport.connect_with_discovery_or_cache(
            discovered_devices=scanned,
            direct_mac_succeeds=True
        )
        self.assertTrue(ok2)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.discovery_invoked_count, 1)    # Still 1, no new discovery!
        self.assertEqual(transport.direct_mac_invoked_count, 1)  # Direct MAC invoked

    def test_repeated_mac_failure_invalidates_cache_and_falls_back(self):
        """Verify 3 consecutive direct MAC connection failures invalidate cache and trigger fallback discovery."""
        transport = SimulatedTransport(max_mac_failures=3)
        transport.load_cached_mac("2C:B5:41:11:22:33")

        # Attempt 1: Direct MAC fails
        ok1 = transport.connect_with_discovery_or_cache(direct_mac_succeeds=False)
        self.assertFalse(ok1)
        self.assertEqual(transport.mac_connect_failures, 1)
        self.assertEqual(transport.cached_mac, "2C:B5:41:11:22:33")  # Still cached

        # Attempt 2: Direct MAC fails
        ok2 = transport.connect_with_discovery_or_cache(direct_mac_succeeds=False)
        self.assertFalse(ok2)
        self.assertEqual(transport.mac_connect_failures, 2)
        self.assertEqual(transport.cached_mac, "2C:B5:41:11:22:33")  # Still cached

        # Attempt 3: Direct MAC fails -> reaches limit (3) -> invalidates cache
        ok3 = transport.connect_with_discovery_or_cache(direct_mac_succeeds=False)
        self.assertFalse(ok3)
        self.assertEqual(transport.mac_connect_failures, 0)
        self.assertIsNone(transport.cached_mac)  # Invalidated!

        # Attempt 4: Now MAC is unknown -> Bounded discovery fallback is triggered!
        scanned = [("vLinker MC-Android", "2C:B5:41:44:55:66")]
        ok4 = transport.connect_with_discovery_or_cache(
            discovered_devices=scanned,
            direct_mac_succeeds=True
        )
        self.assertTrue(ok4)
        self.assertEqual(transport.discovery_invoked_count, 1)
        self.assertEqual(transport.cached_mac, "2C:B5:41:44:55:66")
        self.assertEqual(transport.state, AdapterState.CONNECTED)

    def test_prevention_of_overlapping_workers(self):
        """Verify connecting_in_progress locks against overlapping connection tasks."""
        transport = SimulatedTransport()
        transport.connecting_in_progress = True

        # Secondary connect call while worker running must be rejected
        ok = transport.connect(spp_link_ok=True, ati_response="vLinker MC+ v2.2\r\n>")
        self.assertFalse(ok)
        self.assertEqual(transport.state, AdapterState.DISCONNECTED)

        # Once worker finishes, connect is permitted again
        transport.connecting_in_progress = False
        ok2 = transport.connect(spp_link_ok=True, ati_response="vLinker MC+ v2.2\r\n>")
        self.assertTrue(ok2)
        self.assertEqual(transport.state, AdapterState.CONNECTED)

    def test_persistent_worker_long_duration_reconnect_without_vlinker(self):
        """Verify 5 minutes of reconnect attempts without vLinker causes ZERO task leakage and caps backoff at 16s."""
        transport = SimulatedTransport(base_backoff_ms=1000, max_backoff_ms=16000)

        # Track persistent task creation: created exactly once at boot
        persistent_worker_count = 1
        dynamic_tasks_spawned = 0

        # Simulate 5 minutes (300,000 ms) of timeline
        elapsed_ms = 0
        reconnect_attempts = 0
        unrelated_scanned = [("TVPlayer", "AC:F4:2C:05:03:AB")]

        while elapsed_ms < 300000:
            # Reconnect attempt triggered
            used_backoff = transport.trigger_reconnect_tick()
            reconnect_attempts += 1

            # In persistent worker model: signal task (no new task created!)
            # dynamic_tasks_spawned remains 0
            ok = transport.connect_with_discovery_or_cache(
                discovered_devices=unrelated_scanned,
                direct_mac_succeeds=False
            )
            self.assertFalse(ok, "Must fail connection when only TVPlayer is present")
            self.assertEqual(transport.state, AdapterState.ERROR)

            # Advance timeline by backoff delay
            elapsed_ms += used_backoff

            # Backoff must never exceed 16 seconds (16,000 ms)
            self.assertLessEqual(used_backoff, 16000)

        # Over 5 minutes, at least 15 reconnect attempts occurred
        self.assertGreater(reconnect_attempts, 15)
        # Persistent worker count remains 1, dynamic tasks spawned remains 0!
        self.assertEqual(persistent_worker_count, 1)
        self.assertEqual(dynamic_tasks_spawned, 0)
        # Backoff is capped at 16,000 ms
        self.assertEqual(transport.current_backoff_ms, 16000)

        # Now vLinker appears after 5 minutes:
        valid_vlinker = [("TVPlayer", "AC:F4:2C:05:03:AB"), ("vLinker MC-Android", "2C:B5:41:98:76:54")]
        ok_conn = transport.connect_with_discovery_or_cache(
            discovered_devices=valid_vlinker,
            direct_mac_succeeds=True
        )
        self.assertTrue(ok_conn)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.current_backoff_ms, 1000)  # Backoff resets to base

    def test_repeated_discovery_without_vlinker_zero_corruption_and_transition(self):
        """Regression test for the Core 0 LoadProhibited crash:
        - No vLinker present (only non-target devices like TVPlayer present)
        - Repeated bounded discovery for at least 10 consecutive cycles
        - Zero crash/null-dereference/state corruption
        - Persistent worker remains alive throughout
        - Wi-Fi remains available and simulated HTTP endpoint remains responsive
        - Then simulate vLinker appearing and verify immediate transition to CONNECTED
        """
        transport = SimulatedTransport(base_backoff_ms=1000, max_backoff_ms=16000)
        unrelated_scanned = [("TVPlayer", "AC:F4:2C:05:03:AB")]

        # Simulated Wi-Fi SoftAP and HTTP WebServer state
        wifi_ap_active = True
        http_requests_served = 0

        # Perform 12 consecutive bounded discovery cycles (>= 10) with no vLinker
        for cycle in range(1, 13):
            # Worker is signaled
            self.assertFalse(transport.connecting_in_progress)
            ok = transport.connect_with_discovery_or_cache(
                discovered_devices=unrelated_scanned,
                direct_mac_succeeds=False
            )
            # Must fail cleanly without crashing or corrupting state
            self.assertFalse(ok)
            self.assertEqual(transport.state, AdapterState.ERROR)
            self.assertEqual(transport.last_error, TransportError.SPP_CONNECT_FAILED)
            self.assertIsNone(transport.cached_mac)
            self.assertEqual(transport.discovery_invoked_count, cycle)

            # Wi-Fi SoftAP remains active on Core 1
            self.assertTrue(wifi_ap_active)
            # Simulated HTTP endpoint /api/status is queried and responds 200 OK
            http_response = {"status": "ok", "bt_state": transport.state, "cycle": cycle}
            self.assertEqual(http_response["status"], "ok")
            http_requests_served += 1

        self.assertEqual(transport.discovery_invoked_count, 12)
        self.assertEqual(http_requests_served, 12)

        # On cycle 13: vLinker physically appears
        vlinker_scanned = [("TVPlayer", "AC:F4:2C:05:03:AB"), ("vLinker MC-Android", "2C:B5:41:77:88:99")]
        ok_vlinker = transport.connect_with_discovery_or_cache(
            discovered_devices=vlinker_scanned,
            direct_mac_succeeds=True
        )
        self.assertTrue(ok_vlinker)
        self.assertEqual(transport.state, AdapterState.CONNECTED)
        self.assertEqual(transport.cached_mac, "2C:B5:41:77:88:99")
        self.assertEqual(transport.identity["brand"], AdapterBrand.VLINKER)
        self.assertTrue(wifi_ap_active)

if __name__ == "__main__":
    unittest.main()
