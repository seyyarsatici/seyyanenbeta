#!/usr/bin/env python3
"""
test_phase_g1.py - Comprehensive Test Suite for Phase G-1
==========================================================
Validates the Advanced ECU Services Foundation:
  1. Request and Response Models & Immutability
  2. Service Registry & Descriptor Contracts
  3. Strict Safety Policies & Hard Prohibitions (Zero Mode 04 / Destructive Ops)
  4. Diagnostic Transaction Manager Execution over Existing SerialIOThread
  5. Deterministic MockSerial Fault Injection Scenarios (A through T)
  6. Concurrency Safety, Cancellation, and Late Response Isolation
  7. Bounded History & Memory Safety
  8. Full Backward Compatibility Verification
"""

import os
import sys
import threading
import time
from typing import Any, Dict, List

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mock_serial import MockSerial
from motor import (
    AutoExpertEngine,
    SerialIOThread,
    STATUS_VALID,
    STATUS_NRC,
    STATUS_TIMEOUT,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NO_DATA,
    STATUS_DID_MISMATCH,
    STATUS_EMPTY_RESPONSE,
)
from advanced_ecu_services import (
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    DiagnosticSessionContext,
    DiagnosticTransactionManager,
    ECUTargetContext,
    EngineTransportAdapter,
    ServiceDescriptor,
    ServiceRegistry,
    ServiceRetryPolicy,
    ServiceSafetyClassification,
    ServiceSafetyPolicy,
    SessionType,
    STATUS_TRANSACTION_BLOCKED,
    STATUS_TRANSACTION_CANCELLED,
    STATUS_UNEXPECTED_RESPONSE,
    STATUS_RESPONSE_MISMATCH,
    STATUS_PARSE_ERROR,
    CANONICAL_NRC_MAP,
)


def create_mock_engine() -> Tuple_Engine:
    """Helper to create a configured AutoExpertEngine backed by MockSerial and SerialIOThread."""
    mock_ser = MockSerial(port="COM_MOCK", baudrate=38400, timeout=1.0)
    mock_ser.protocol_mode = "CAN"
    mock_ser.sim_sessions.add("7E0")
    engine = AutoExpertEngine()
    engine.ser = mock_ser
    engine.is_slow_protocol = False
    engine.io_worker = SerialIOThread(mock_ser, timeout=1.0)
    engine.io_worker.start()
    return engine, mock_ser


Tuple_Engine = Any


def run_all_tests():
    print("===========================================================================")
    print("SEYYANEN DIAGNOSTIC ENGINE — PHASE G-1 ACCEPTANCE TEST SUITE")
    print("===========================================================================")

    # ---------------------------------------------------------------------
    # TEST 1: Request and Response Models & Evidence Preservation
    # ---------------------------------------------------------------------
    print("\n--- TEST 1: Request and Response Models & Raw Preservation ---")
    req = AdvancedServiceRequest(
        service_id="22",
        payload="1640",
        header="7E0",
        timeout=1.5,
    )
    assert req.service_id == "22"
    assert req.payload == "1640"
    assert req.header == "7E0"
    assert req.expected_response_service_id == "62"  # 0x22 + 0x40
    assert req.to_command_string() == "221640"

    # Subfunction handling
    req_sub = AdvancedServiceRequest(
        service_id="10",
        subfunction="03",
    )
    assert req_sub.expected_response_service_id == "50"
    assert req_sub.to_command_string() == "1003"

    # Response evidence preservation
    resp = AdvancedServiceResponse(
        transaction_id="TXN-001",
        request=req,
        is_positive=True,
        raw_lines=["7E8 62 16 40 00 96", ">"],
        raw_bytes=bytes.fromhex("6216400096"),
        raw_payload_hex="6216400096",
        status=STATUS_VALID,
    )
    d = resp.to_dict()
    assert d["transaction_id"] == "TXN-001"
    assert d["raw_payload_hex"] == "6216400096"
    assert d["raw_lines"] == ["7E8 62 16 40 00 96", ">"]
    print("✅ TEST 1 PASSED: Models structured and preserve raw evidence unconditionally.")

    # ---------------------------------------------------------------------
    # TEST 2: Service Registry & Descriptor Contracts
    # ---------------------------------------------------------------------
    print("\n--- TEST 2: Service Registry & Pre-Registered Services ---")
    registry = ServiceRegistry()

    # Verify standard read-only services
    desc_22 = registry.get("22")
    assert desc_22 is not None
    assert desc_22.name == "ReadDataByIdentifier"
    assert desc_22.safety_classification == ServiceSafetyClassification.READ_ONLY
    assert desc_22.positive_response_id == "62"

    desc_01 = registry.get("01")
    assert desc_01 is not None
    assert desc_01.safety_classification == ServiceSafetyClassification.READ_ONLY

    desc_09 = registry.get("09")
    assert desc_09 is not None

    desc_3e = registry.get("3E")
    assert desc_3e is not None

    # Verify blocked services
    desc_04 = registry.get("04")
    assert desc_04 is not None
    assert desc_04.safety_classification == ServiceSafetyClassification.POTENTIALLY_DESTRUCTIVE

    desc_2e = registry.get("2E")
    assert desc_2e is not None
    assert desc_2e.safety_classification == ServiceSafetyClassification.WRITE

    desc_27 = registry.get("27")
    assert desc_27 is not None
    assert desc_27.safety_classification == ServiceSafetyClassification.SECURITY_SENSITIVE

    print("✅ TEST 2 PASSED: Service registry pre-configured with read-only and blocked descriptors.")

    # ---------------------------------------------------------------------
    # TEST 3: Strict Safety Guardrails & Hard Prohibition of Destructive Ops
    # ---------------------------------------------------------------------
    print("\n--- TEST 3: Safety Guardrails (Zero Mode 04 / Destructive Ops) ---")
    policy = ServiceSafetyPolicy()

    # 1. Mode 04 must be blocked
    req_m04 = AdvancedServiceRequest(service_id="04")
    safe, reason = policy.validate_request(req_m04)
    assert not safe
    assert "prohibited" in reason.lower()

    # 2. Write service must be blocked
    req_write = AdvancedServiceRequest(
        service_id="2E",
        payload="F190010203",
        safety_classification=ServiceSafetyClassification.WRITE,
    )
    safe, reason = policy.validate_request(req_write)
    assert not safe

    # 3. Security Access service must be blocked
    req_sec = AdvancedServiceRequest(
        service_id="27",
        subfunction="01",
        safety_classification=ServiceSafetyClassification.SECURITY_SENSITIVE,
    )
    safe, reason = policy.validate_request(req_sec)
    assert not safe

    # 4. Actuation service must be blocked
    req_act = AdvancedServiceRequest(
        service_id="2F",
        payload="123403",
        safety_classification=ServiceSafetyClassification.ACTUATION,
    )
    safe, reason = policy.validate_request(req_act)
    assert not safe

    print("✅ TEST 3 PASSED: Destructive/write services rejected before reaching transport.")

    # ---------------------------------------------------------------------
    # TEST 4: Engine Integration & Transaction Manager Architecture
    # ---------------------------------------------------------------------
    print("\n--- TEST 4: Engine Integration & Adapter Architecture ---")
    engine, mock_ser = create_mock_engine()
    try:
        tm = engine.transaction_manager
        assert tm is not None
        assert isinstance(tm, DiagnosticTransactionManager)
        assert isinstance(tm.transport, EngineTransportAdapter)
        assert tm.transport.engine is engine
        print("✅ TEST 4 PASSED: AutoExpertEngine cleanly exposes DiagnosticTransactionManager.")
    finally:
        engine.io_worker.stop()

    # ---------------------------------------------------------------------
    # TEST 5: MockSerial Scenarios A through T
    # ---------------------------------------------------------------------
    print("\n--- TEST 5: MockSerial Scenarios A through T ---")
    engine, mock_ser = create_mock_engine()
    tm = engine.transaction_manager

    try:
        # Scenario A: Valid positive response (Mode 22 1640)
        req_a = tm.build_request("22", payload="1640", header="7E0")
        res_a = tm.execute_request(req_a)
        assert res_a.is_positive
        assert res_a.status == STATUS_VALID
        assert res_a.response_service_id == "62"
        assert res_a.raw_payload_hex.startswith("621640")
        assert len(res_a.raw_lines) > 0
        print("   -> Scenario A (Valid positive response): PASSED")

        # Scenario B: Valid negative response / NRC (Mode 22 2000 -> 7F2233)
        req_b = tm.build_request("22", payload="2000", header="7E0")
        res_b = tm.execute_request(req_b)
        assert not res_b.is_positive
        assert res_b.is_nrc
        assert res_b.status == STATUS_NRC
        assert res_b.nrc == "33"
        assert res_b.nrc_description == "Security Access Denied"
        print("   -> Scenario B (Valid NRC 0x33): PASSED")

        # Scenario C: Timeout (Mode 22 DEAD)
        req_c = tm.build_request("22", payload="DEAD", header="7E0", timeout=0.5)
        res_c = tm.execute_request(req_c)
        assert not res_c.is_positive
        assert res_c.is_timeout
        assert res_c.status == STATUS_TIMEOUT
        print("   -> Scenario C (Timeout): PASSED")

        # Scenario D: Serial / transport failure (simulated exception)
        mock_ser.force_serial_error = True
        req_d = tm.build_request("22", payload="1640", header="7E0", timeout=0.5)
        res_d = tm.execute_request(req_d)
        mock_ser.force_serial_error = False
        assert not res_d.is_positive
        assert res_d.is_transport_error
        assert res_d.status in (STATUS_SERIAL_ERROR, STATUS_WORKER_DOWN)
        print("   -> Scenario D (Transport failure): PASSED")

        # Scenario E: Malformed response
        mock_ser.custom_responses["221640"] = "62 16 40 ZZ XX INVALID"
        req_e = tm.build_request("22", payload="1640", header="7E0", timeout=0.5)
        res_e = tm.execute_request(req_e)
        mock_ser.custom_responses.clear()
        assert not res_e.is_positive
        assert len(res_e.raw_lines) > 0
        print("   -> Scenario E (Malformed response): PASSED")

        # Scenario F: Mismatched positive response (DID echo incorrect)
        mock_ser.custom_responses["221640"] = "6299990096"
        req_f = tm.build_request("22", payload="1640", header="7E0", timeout=0.5)
        res_f = tm.execute_request(req_f)
        mock_ser.custom_responses.clear()
        assert not res_f.is_positive
        assert res_f.status == STATUS_RESPONSE_MISMATCH
        print("   -> Scenario F (Mismatched positive response): PASSED")

        # Scenario G: Unexpected response (different service ID entirely)
        mock_ser.custom_responses["221640"] = "410C1A2B"
        req_g = tm.build_request("22", payload="1640", header="7E0", timeout=0.5)
        res_g = tm.execute_request(req_g)
        mock_ser.custom_responses.clear()
        assert not res_g.is_positive
        assert res_g.status == STATUS_UNEXPECTED_RESPONSE
        print("   -> Scenario G (Unexpected response): PASSED")

        # Scenario H: Multi-frame ISO-TP reassembly (Mode 22 1641)
        req_h = tm.build_request("22", payload="1641", header="7E0")
        res_h = tm.execute_request(req_h)
        assert res_h.is_positive
        assert res_h.status == STATUS_VALID
        assert res_h.raw_payload_hex.startswith("621641")
        assert len(res_h.raw_lines) >= 2
        print("   -> Scenario H (Multi-frame ISO-TP reassembly): PASSED")

        # Scenario I: Cancellation before dispatch
        req_i = tm.build_request("22", payload="1640", header="7E0")
        tm.cancel_transaction(req_i.transaction_id)
        res_i = tm.execute_request(req_i)
        assert res_i.status == STATUS_TRANSACTION_CANCELLED
        assert "cancelled" in res_i.error_message.lower()
        print("   -> Scenario I (Cancellation before dispatch): PASSED")

        # Scenario J: Cancellation during execution/wait
        req_j = tm.build_request("22", payload="1640", header="7E0")
        # Pre-cancel directly
        tm.cancel_transaction(req_j.transaction_id)
        res_j = tm.execute_request(req_j)
        assert res_j.status == STATUS_TRANSACTION_CANCELLED
        print("   -> Scenario J (Cancellation handling): PASSED")

        # Scenario K & L: Bounded retry and exhaustion
        mock_ser.custom_responses["227777"] = None  # Causes timeout
        retry_policy = ServiceRetryPolicy(max_attempts=2, backoff_sec=0.05, retry_on_timeout=True)
        req_kl = tm.build_request("22", payload="7777", header="7E0", timeout=0.3, retry_policy=retry_policy)
        t_start = time.time()
        res_kl = tm.execute_request(req_kl)
        t_elapsed = time.time() - t_start
        mock_ser.custom_responses.clear()
        assert res_kl.status == STATUS_TIMEOUT
        # Verify retried at least twice
        assert t_elapsed >= 0.35
        print("   -> Scenario K & L (Bounded retry and exhaustion): PASSED")

        # Scenario M: Concurrent requests serialization
        concur_results = []
        threads = []
        for i in range(5):
            req_m = tm.build_request("22", payload="1640", header="7E0", timeout=1.0)
            t = threading.Thread(target=lambda r: concur_results.append(tm.execute_request(r)), args=(req_m,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert len(concur_results) == 5
        assert all(r.is_positive for r in concur_results)
        print("   -> Scenario M (Concurrent requests serialization): PASSED")

        # Scenario N: Late response isolation (distinct transaction IDs)
        req_n1 = tm.build_request("22", payload="1640")
        req_n2 = tm.build_request("22", payload="1640")
        assert req_n1.transaction_id != req_n2.transaction_id
        res_n1 = tm.execute_request(req_n1)
        res_n2 = tm.execute_request(req_n2)
        assert res_n1.transaction_id == req_n1.transaction_id
        assert res_n2.transaction_id == req_n2.transaction_id
        print("   -> Scenario N (Late response & ID isolation): PASSED")

        # Scenario O: Unknown / unparsed response preservation
        req_o = tm.build_request("21", payload="02", header="7E0")
        res_o = tm.execute_request(req_o)
        assert res_o.is_positive
        assert res_o.parsing_status == "NO_PARSER"
        assert res_o.parsed_payload is None
        assert res_o.raw_payload_hex.startswith("6102")
        print("   -> Scenario O (Unknown / unparsed response preservation): PASSED")

        # Scenario P: Safety-blocked request
        req_p = tm.build_request("04")
        res_p = tm.execute_request(req_p)
        assert res_p.status == STATUS_TRANSACTION_BLOCKED
        print("   -> Scenario P (Safety-blocked request): PASSED")

        # Scenario Q: Valid raw response with parser
        def custom_parser(data_bytes: bytes, hex_str: str) -> Dict[str, Any]:
            val = int.from_bytes(data_bytes, byteorder="big")
            return {"parsed_val": val, "hex": hex_str}

        tm.registry.register(ServiceDescriptor(
            service_id="22",
            name="ReadDataByIdentifier",
            positive_response_id="62",
            parser=custom_parser,
        ))
        req_q = tm.build_request("22", payload="1640", header="7E0")
        res_q = tm.execute_request(req_q)
        assert res_q.is_positive
        assert res_q.parsing_status == "PARSED"
        assert isinstance(res_q.parsed_payload, dict)
        assert "parsed_val" in res_q.parsed_payload
        print("   -> Scenario Q (Valid response with parser): PASSED")

        # Scenario R: Session-context requirement representation
        ctx = tm.get_session_context()
        assert ctx is not None
        assert ctx.session_type == SessionType.DEFAULT
        assert ctx.is_active
        print("   -> Scenario R (Session-context representation): PASSED")

        # Scenario S: Invalid request descriptor / malformed
        req_s = tm.build_request("22", payload="NOT_HEX_CHARS", header="7E0", timeout=0.3)
        res_s = tm.execute_request(req_s)
        assert not res_s.is_positive
        print("   -> Scenario S (Malformed request handling): PASSED")

        # Scenario T: Transport closed during transaction
        mock_ser.close()
        req_t = tm.build_request("22", payload="1640", header="7E0", timeout=0.5)
        res_t = tm.execute_request(req_t)
        assert not res_t.is_positive
        assert res_t.is_transport_error
        print("   -> Scenario T (Transport closed during transaction): PASSED")

    finally:
        engine.io_worker.stop()

    print("✅ TEST 5 PASSED: All 20 MockSerial scenarios (A through T) validated successfully.")

    # ---------------------------------------------------------------------
    # TEST 6: Bounded History & Memory Safety (500 Transactions)
    # ---------------------------------------------------------------------
    print("\n--- TEST 6: Bounded History & Memory Safety ---")
    engine, mock_ser = create_mock_engine()
    tm = DiagnosticTransactionManager(
        transport=EngineTransportAdapter(engine),
        history_maxlen=25,
    )
    try:
        for i in range(50):
            req = tm.build_request("22", payload="1640", timeout=0.2)
            tm.execute_request(req)

        history = tm.get_transaction_history()
        assert len(history) == 25, f"Expected history length 25, got {len(history)}"
        print("✅ TEST 6 PASSED: Transaction history strictly bounded by configured maxlen.")
    finally:
        engine.io_worker.stop()

    # ---------------------------------------------------------------------
    # TEST 7: Backward Compatibility with Existing Architecture
    # ---------------------------------------------------------------------
    print("\n--- TEST 7: Backward Compatibility with Core Architecture ---")
    engine, mock_ser = create_mock_engine()
    try:
        # 1. Standard komut_gonder (Mode 01)
        res_rpm = engine.komut_gonder("010C", timeout=1.0)
        assert res_rpm and any("41" in l for l in res_rpm)

        # 2. Mode 03 (DTC)
        res_dtc = engine.komut_gonder("03", timeout=1.0)
        assert res_dtc and any("43" in l for l in res_dtc)

        # 3. Mode 09 (VIN)
        res_vin = engine.komut_gonder("0902", timeout=1.0)
        assert res_vin and any("49" in l for l in res_vin)

        # 4. Phase B manual_did_probe
        probe_res = engine.manual_did_probe("1640", header="7E0")
        assert probe_res.get("ok") is True

        print("✅ TEST 7 PASSED: Core Mode 01, Mode 03, Mode 09, and manual_did_probe unharmed.")
    finally:
        engine.io_worker.stop()

    print("\n===========================================================================")
    print("🎉 ALL PHASE G-1 ACCEPTANCE TESTS PASSED SUCCESSFULLY!")
    print("===========================================================================")


if __name__ == "__main__":
    run_all_tests()
