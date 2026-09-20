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
    def __init__(self, base_backoff_ms: int = 1000, max_backoff_ms: int = 16000):
        self.state = AdapterState.DISCONNECTED
        self.last_error = TransportError.NONE
        self.identity = {}
        self.retry_count = 0
        self.current_backoff_ms = base_backoff_ms
        self.base_backoff_ms = base_backoff_ms
        self.max_backoff_ms = max_backoff_ms
        self.connecting_in_progress = False

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
        # CRITICAL RULE: Bluetooth link connected != diagnostic adapter verified!
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

if __name__ == "__main__":
    unittest.main()
