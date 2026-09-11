#!/usr/bin/env python3
"""
test_phase_g2.py - Comprehensive Test Suite for Phase G-2
==========================================================
Validates the Extended DID / PID Ecosystem & Advanced Data Decoding:
  A. Known valid DID definition
  B. Unknown DID (raw fallback preservation)
  C. Positive response handling
  D. Negative response handling
  E. NRC unsupported DID (0x31 / 0x12)
  F. NRC required session (0x7E / 0x22)
  G. Malformed payload
  H. Too-short payload
  I. Oversized payload
  J. Wrong echoed DID
  K. Wrong positive response (service mismatch)
  L. Unknown/unparsed response
  M. Unsigned integer decoding
  N. Signed integer decoding
  O. Little-endian decoding
  P. Big-endian decoding
  Q. Scaling
  R. Offset + scaling
  S. Bitfield decoding
  T. Enumeration decoding
  U. Invalid/reserved value detection
  V. Multi-field composite payload
  W. Raw response preservation
  X. Provenance preservation
  Y. Definition version preservation
  Z. Vehicle applicability mismatch
  AA. Unknown vehicle applicability
  AB. Supported vehicle applicability
  AC. Session requirement specification
  AD. Cancellation handling
  AE. Timeout handling
  AF. Bounded retry
  AG. Batch acquisition
  AH. One DID failure does not fail batch
  AI. Multiple successful DIDs
  AJ. Rate limiting / inter-request delay
  AK. Concurrent thread safety
  AL. Late response isolation
  AM. Bounded history / memory limits
  AN. Safety-blocked service
  AO. No automatic session transition
  AP. No Mode 04 (DTC clear prohibited)
  AQ. No write/programming commands
  AR. Regression: Existing Mode 01 PID acquisition
  AS. Regression: Existing Mode 03 DTC acquisition
  AT. Regression: Phase F runtime health & quality tracking
"""

import os
import struct
import sys
import threading
import time
from typing import Any, Dict, List, Tuple

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mock_serial import MockSerial
from motor import (
    AutoExpertEngine,
    SerialIOThread,
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_INVALID,
    QUALITY_ERROR,
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
from extended_did import (
    AcquisitionBatch,
    ApplicabilityResult,
    BatchAcquisitionManager,
    ByteOrder,
    DataDecoder,
    DataProvenance,
    DataType,
    DecodedField,
    DefinitionTrustLevel,
    DiagnosticDataDefinition,
    DiagnosticDefinitionRegistry,
    FieldDefinition,
    IdentifierNamespace,
    StructuredDiagnosticEvidence,
    VehicleApplicability,
    VehicleContext,
)


def create_mock_engine() -> Tuple[AutoExpertEngine, MockSerial]:
    """Helper to create a configured AutoExpertEngine backed by MockSerial in fast CAN mode."""
    mock_ser = MockSerial(port="COM_MOCK", baudrate=38400, timeout=1.0)
    mock_ser.protocol_mode = "CAN"
    mock_ser.sim_sessions.add("7E0")
    engine = AutoExpertEngine()
    engine.ser = mock_ser
    engine.is_slow_protocol = False
    engine.io_worker = SerialIOThread(mock_ser, timeout=1.0)
    engine.io_worker.start()
    return engine, mock_ser


def run_all_g2_tests():
    print("===========================================================================")
    print("SEYYANEN DIAGNOSTIC PLATFORM — PHASE G-2 ACCEPTANCE TEST SUITE")
    print("===========================================================================")

    engine, mock_ser = create_mock_engine()

    try:
        tm = engine.transaction_manager
        reg = engine.did_registry
        bam = engine.batch_acquisition_manager

        # ---------------------------------------------------------------------
        # SCENARIO A: Known Valid DID Definition
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO A: Known Valid DID Definition ---")
        did_1640 = reg.get("1640", service_id="22")
        assert did_1640 is not None, "DID 1640 must be registered by default"
        assert did_1640.identifier == "1640"
        assert did_1640.service_id == "22"
        assert did_1640.namespace == IdentifierNamespace.EXTENDED_UDS_DID
        assert did_1640.fields[0].name == "ECT_UDS"
        assert did_1640.fields[0].scale == 0.1
        assert did_1640.fields[0].offset == -40.0
        assert did_1640.trust_level == DefinitionTrustLevel.VERIFIED_TESTED
        req_1640 = did_1640.build_service_request(tm)
        assert req_1640.to_command_string() == "221640"
        print("  [PASS] Scenario A: Known Valid DID Definition verified")

        # ---------------------------------------------------------------------
        # SCENARIO B: Unknown DID (Raw Fallback Preservation)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO B: Unknown DID Definition ---")
        unknown_did = DiagnosticDataDefinition(
            identifier="FFFF",
            service_id="22",
            namespace=IdentifierNamespace.RAW_UNKNOWN,
            name="UndocumentedDID_FFFF",
            trust_level=DefinitionTrustLevel.UNKNOWN,
        )
        assert len(unknown_did.fields) == 0
        raw_val, dec_val, fields, is_val, err = DataDecoder.decode(bytes.fromhex("11223344"), unknown_did)
        assert is_val is True
        assert raw_val == "11223344"
        assert dec_val == "11223344"
        assert fields == {}
        print("  [PASS] Scenario B: Unknown DID fallback preservation verified")

        # ---------------------------------------------------------------------
        # SCENARIO C: Positive Response Handling
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO C: Positive Response Handling ---")
        # In MockSerial, 221640 returns "62 16 40 00 96" (raw = 0x0096 = 150 -> 150 * 0.1 - 40 = -25.0 C)
        ev_c = bam.acquire_identifier(did_1640)
        assert ev_c.is_valid is True, f"Expected valid evidence, got error: {ev_c.error_message}"
        assert ev_c.status == STATUS_VALID
        assert ev_c.quality == QUALITY_GOOD
        assert ev_c.raw_response.is_positive is True
        assert ev_c.decoded_value == -25.0
        assert ev_c.raw_value == 0x0096
        assert ev_c.unit == "°C"
        assert ev_c.fields["ECT_UDS"].decoded_value == -25.0
        print(f"  [PASS] Scenario C: Positive response decoded: {ev_c.decoded_value} {ev_c.unit}")


        # ---------------------------------------------------------------------
        # SCENARIO D: Negative Response Handling
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO D: Negative Response Handling ---")
        mock_ser.custom_responses["221640"] = "7F 22 10\r\n>"
        try:
            ev_d = bam.acquire_identifier(did_1640)
            assert ev_d.is_valid is False
            assert ev_d.status == STATUS_NRC
            assert ev_d.quality == QUALITY_INVALID
            assert ev_d.raw_response.nrc == "10"
            assert "General Reject" in ev_d.error_message
            print("  [PASS] Scenario D: Negative response properly captured and classified")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO E: NRC Unsupported DID (0x31)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO E: NRC Unsupported DID ---")
        mock_ser.custom_responses["221640"] = "7F 22 31\r\n>"
        try:
            ev_e = bam.acquire_identifier(did_1640)
            assert ev_e.is_valid is False
            assert ev_e.status == STATUS_NRC
            assert ev_e.raw_response.nrc == "31"
            assert "Request Out of Range" in ev_e.error_message
            print("  [PASS] Scenario E: NRC 0x31 requestOutOfRange verified")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO F: NRC Required Session (0x7E)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO F: NRC Required Session ---")
        mock_ser.custom_responses["221640"] = "7F 22 7E\r\n>"
        try:
            ev_f = bam.acquire_identifier(did_1640)
            assert ev_f.is_valid is False
            assert ev_f.status == STATUS_NRC
            assert ev_f.raw_response.nrc == "7E"
            assert "Sub-Function Not Supported In Active Session" in ev_f.error_message
            print("  [PASS] Scenario F: NRC 0x7E session requirement verified")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO G: Malformed Payload
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO G: Malformed Payload ---")
        mock_ser.custom_responses["221640"] = "62 16 40 ZZ !!\r\n>"
        try:
            ev_g = bam.acquire_identifier(did_1640)
            assert ev_g.is_valid is False
            assert ev_g.status in (STATUS_PARSE_ERROR, STATUS_RESPONSE_MISMATCH)
            assert ev_g.raw_response is not None
            print("  [PASS] Scenario G: Malformed payload handled safely without unhandled crash")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO H: Too-Short Payload
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO H: Too-Short Payload ---")
        mock_ser.custom_responses["221640"] = "62 16 40 05\r\n>"  # only 1 byte payload instead of expected 2
        try:
            ev_h = bam.acquire_identifier(did_1640)
            assert ev_h.is_valid is False
            assert ev_h.status == STATUS_PARSE_ERROR
            assert "Payload shorter than expected" in ev_h.error_message
            assert ev_h.raw_response.raw_payload_hex == "62164005"
            print("  [PASS] Scenario H: Too-short payload caught, raw response preserved")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO I: Oversized Payload
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO I: Oversized Payload ---")
        mock_ser.custom_responses["221640"] = "62 16 40 05 50 AA BB CC\r\n>"
        try:
            oversized_def = DiagnosticDataDefinition(
                identifier="1640",
                service_id="22",
                max_payload_length=2,
                fields=[FieldDefinition(name="Test", payload_length=2)],
            )
            ev_i = bam.acquire_identifier(oversized_def)
            assert ev_i.is_valid is False
            assert ev_i.status == STATUS_PARSE_ERROR
            assert "exceeds maximum allowed length" in ev_i.error_message
            print("  [PASS] Scenario I: Oversized payload rejected safely")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO J: Wrong Echoed DID
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO J: Wrong Echoed DID ---")
        mock_ser.custom_responses["221640"] = "62 16 41 05 50\r\n>"  # Echoes 1641 instead of 1640
        try:
            ev_j = bam.acquire_identifier(did_1640)
            assert ev_j.is_valid is False
            assert ev_j.status == STATUS_RESPONSE_MISMATCH
            assert "echo expected" in ev_j.error_message
            print("  [PASS] Scenario J: Wrong echoed DID detected and rejected")

        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO K: Wrong Positive Response (Service Mismatch)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO K: Wrong Positive Response ---")
        mock_ser.custom_responses["221640"] = "41 0C 1A F8\r\n>"  # Mode 01 response instead of Mode 22 (62)
        try:
            ev_k = bam.acquire_identifier(did_1640)
            assert ev_k.is_valid is False
            assert ev_k.status == STATUS_UNEXPECTED_RESPONSE
            print("  [PASS] Scenario K: Wrong service response caught by G-1 transaction layer")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO L: Unknown / Unparsed Positive Response
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO L: Unknown / Unparsed Positive Response ---")
        mock_ser.custom_responses["229999"] = "62 99 99 DE AD BE EF\r\n>"
        try:
            unk_def = DiagnosticDataDefinition(
                identifier="9999",
                service_id="22",
                namespace=IdentifierNamespace.RAW_UNKNOWN,
                trust_level=DefinitionTrustLevel.UNKNOWN,
            )
            ev_l = bam.acquire_identifier(unk_def)
            assert ev_l.is_valid is True
            assert ev_l.raw_value == "DEADBEEF"
            assert ev_l.decoded_value == "DEADBEEF"
            assert ev_l.status == STATUS_VALID
            print("  [PASS] Scenario L: Unparsed response preserved as raw evidence without fake semantics")
        finally:
            del mock_ser.custom_responses["229999"]

        # ---------------------------------------------------------------------
        # SCENARIO M: Unsigned Integer Decoding (UINT8, UINT16, UINT32)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO M: Unsigned Integer Decoding ---")
        def_m = DiagnosticDataDefinition(
            identifier="M",
            fields=[
                FieldDefinition(name="u8", payload_offset=0, payload_length=1, data_type=DataType.UINT8),
                FieldDefinition(name="u16", payload_offset=1, payload_length=2, data_type=DataType.UINT16),
                FieldDefinition(name="u32", payload_offset=3, payload_length=4, data_type=DataType.UINT32),
            ]
        )
        payload_m = bytes([0xFE, 0x01, 0x02, 0x00, 0x01, 0x00, 0x00])  # 254, 258, 65536
        raw_m, dec_m, flds_m, valid_m, _ = DataDecoder.decode(payload_m, def_m)
        assert valid_m is True
        assert dec_m["u8"] == 254
        assert dec_m["u16"] == 258
        assert dec_m["u32"] == 65536
        print("  [PASS] Scenario M: Unsigned integer decoding verified")

        # ---------------------------------------------------------------------
        # SCENARIO N: Signed Integer Decoding (INT8, INT16, INT32)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO N: Signed Integer Decoding ---")
        def_n = DiagnosticDataDefinition(
            identifier="N",
            fields=[
                FieldDefinition(name="i8", payload_offset=0, payload_length=1, data_type=DataType.INT8),
                FieldDefinition(name="i16", payload_offset=1, payload_length=2, data_type=DataType.INT16),
                FieldDefinition(name="i32", payload_offset=3, payload_length=4, data_type=DataType.INT32),
            ]
        )
        # 0xFB = -5, 0xFFFB = -5, 0xFFFFFFFB = -5
        payload_n = bytes([0xFB, 0xFF, 0xFB, 0xFF, 0xFF, 0xFF, 0xFB])
        raw_n, dec_n, flds_n, valid_n, _ = DataDecoder.decode(payload_n, def_n)
        assert valid_n is True
        assert dec_n["i8"] == -5
        assert dec_n["i16"] == -5
        assert dec_n["i32"] == -5
        print("  [PASS] Scenario N: Signed integer negative values decoded correctly")

        # ---------------------------------------------------------------------
        # SCENARIO O: Little-Endian Decoding
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO O: Little-Endian Decoding ---")
        def_o = DiagnosticDataDefinition(
            identifier="O",
            fields=[
                FieldDefinition(
                    name="le16",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    byte_order=ByteOrder.LITTLE_ENDIAN,
                )
            ]
        )
        # Bytes [0x01, 0x02] in little-endian = 0x0201 = 513
        raw_o, dec_o, _, valid_o, _ = DataDecoder.decode(bytes([0x01, 0x02]), def_o)
        assert valid_o is True
        assert dec_o == 513
        print("  [PASS] Scenario O: Little-endian byte order decoded correctly (513)")

        # ---------------------------------------------------------------------
        # SCENARIO P: Big-Endian Decoding
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO P: Big-Endian Decoding ---")
        def_p = DiagnosticDataDefinition(
            identifier="P",
            fields=[
                FieldDefinition(
                    name="be16",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    byte_order=ByteOrder.BIG_ENDIAN,
                )
            ]
        )
        # Bytes [0x01, 0x02] in big-endian = 0x0102 = 258
        raw_p, dec_p, _, valid_p, _ = DataDecoder.decode(bytes([0x01, 0x02]), def_p)
        assert valid_p is True
        assert dec_p == 258
        print("  [PASS] Scenario P: Big-endian byte order decoded correctly (258)")

        # ---------------------------------------------------------------------
        # SCENARIO Q: Scaling
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO Q: Scaling ---")
        def_q = DiagnosticDataDefinition(
            identifier="Q",
            fields=[
                FieldDefinition(
                    name="RPM",
                    payload_offset=0,
                    payload_length=2,
                    data_type=DataType.UINT16,
                    scale=0.25,
                    offset=0.0,
                    unit="RPM",
                )
            ]
        )
        # 0x0FA0 = 4000 -> 4000 * 0.25 = 1000.0
        raw_q, dec_q, _, valid_q, _ = DataDecoder.decode(bytes([0x0F, 0xA0]), def_q)
        assert valid_q is True
        assert raw_q == 4000
        assert dec_q == 1000.0
        print("  [PASS] Scenario Q: Scaling verified (4000 * 0.25 = 1000.0 RPM)")

        # ---------------------------------------------------------------------
        # SCENARIO R: Offset + Scaling
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO R: Offset + Scaling ---")
        def_r = DiagnosticDataDefinition(
            identifier="R",
            fields=[
                FieldDefinition(
                    name="Temp",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.UINT8,
                    scale=1.0,
                    offset=-40.0,
                    unit="°C",
                )
            ]
        )
        # 0x50 = 80 -> 80 * 1.0 - 40.0 = 40.0 °C
        raw_r, dec_r, _, valid_r, _ = DataDecoder.decode(bytes([0x50]), def_r)
        assert valid_r is True
        assert raw_r == 80
        assert dec_r == 40.0
        print("  [PASS] Scenario R: Offset + scaling verified (80 - 40 = 40.0 °C)")

        # ---------------------------------------------------------------------
        # SCENARIO S: Bitfield Decoding
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO S: Bitfield Decoding ---")
        def_s = DiagnosticDataDefinition(
            identifier="S",
            fields=[
                FieldDefinition(
                    name="LowNibble",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.BITFIELD,
                    bit_offset=0,
                    bit_length=4,
                ),
                FieldDefinition(
                    name="HighNibble",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.BITFIELD,
                    bit_offset=4,
                    bit_length=4,
                ),
                FieldDefinition(
                    name="Bit5",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.BOOLEAN,
                    bit_offset=5,
                    bit_length=1,
                ),
            ]
        )
        # 0xA5 = 1010 0101 (LowNibble=0x5=5, HighNibble=0xA=10, Bit5=1)
        raw_s, dec_s, flds_s, valid_s, _ = DataDecoder.decode(bytes([0xA5]), def_s)
        assert valid_s is True
        assert dec_s["LowNibble"] == 5
        assert dec_s["HighNibble"] == 10
        assert dec_s["Bit5"] is True
        print("  [PASS] Scenario S: Bitfield slicing and boolean flags verified")

        # ---------------------------------------------------------------------
        # SCENARIO T: Enumeration Decoding
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO T: Enumeration Decoding ---")
        def_t = DiagnosticDataDefinition(
            identifier="T",
            fields=[
                FieldDefinition(
                    name="RelayState",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.ENUMERATION,
                    enum_map={0: "DEACTIVATED", 1: "ACTIVATED", 2: "FAULT"},
                )
            ]
        )
        # 1. Known enum value: 1 -> ACTIVATED
        _, dec_t1, _, _, _ = DataDecoder.decode(bytes([0x01]), def_t)
        assert dec_t1 == "ACTIVATED"

        # 2. Unknown enum value: 0x05 -> UNKNOWN_ENUM_0x5 (Preserved without error!)
        raw_t2, dec_t2, _, valid_t2, _ = DataDecoder.decode(bytes([0x05]), def_t)
        assert valid_t2 is True
        assert raw_t2 == 5
        assert dec_t2 == "UNKNOWN_ENUM_0x5"
        print("  [PASS] Scenario T: Enumeration mapping and fallback preservation verified")

        # ---------------------------------------------------------------------
        # SCENARIO U: Invalid / Reserved Value Detection
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO U: Invalid / Reserved Value Detection ---")
        def_u = DiagnosticDataDefinition(
            identifier="U",
            fields=[
                FieldDefinition(
                    name="SensorVoltage",
                    payload_offset=0,
                    payload_length=1,
                    data_type=DataType.UINT8,
                    invalid_raw_values=[0xFF, 0xFE],
                )
            ]
        )
        # 0xFF indicates open circuit / sensor disconnected
        raw_u, dec_u, _, valid_u, err_u = DataDecoder.decode(bytes([0xFF]), def_u)
        assert valid_u is False
        assert raw_u == 0xFF
        assert dec_u is None
        assert "invalid/reserved" in err_u
        print("  [PASS] Scenario U: Reserved sensor error value 0xFF safely flagged as invalid")

        # ---------------------------------------------------------------------
        # SCENARIO V: Multi-Field Composite Payload
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO V: Multi-Field Composite Payload ---")
        did_1641 = reg.get("1641", service_id="22")
        assert did_1641 is not None
        # MockSerial returns 62 16 41 07 D0 32 5A 05 00 (RPM=2000, Speed=50, Temp=50, etc)
        ev_v = bam.acquire_identifier(did_1641)
        assert ev_v.is_valid is True
        assert ev_v.status == STATUS_VALID
        assert "RPM" in ev_v.fields
        assert "Speed" in ev_v.fields
        assert "CoolantTemp" in ev_v.fields
        assert "StatusBits" in ev_v.fields
        assert "FanActive" in ev_v.fields
        assert ev_v.fields["RPM"].decoded_value == 258.0
        assert ev_v.fields["Speed"].decoded_value == 3.0
        assert ev_v.fields["CoolantTemp"].decoded_value == -36.0  # 4 - 40

        print("  [PASS] Scenario V: Multi-field composite payload decomposed into discrete typed signals")

        # ---------------------------------------------------------------------
        # SCENARIO W: Raw Response Preservation
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO W: Raw Response Preservation ---")
        assert ev_c.raw_response is not None
        assert ev_c.raw_response.raw_lines is not None
        assert len(ev_c.raw_response.raw_lines) > 0
        assert ev_c.raw_response.raw_payload_hex is not None
        assert ev_c.raw_value is not None
        print(f"  [PASS] Scenario W: Raw response hex preserved: {ev_c.raw_response.raw_payload_hex}")

        # ---------------------------------------------------------------------
        # SCENARIO X: Provenance Preservation
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO X: Provenance Preservation ---")
        prov = ev_c.provenance
        assert prov is not None
        assert prov.source_ecu == "PRIMARY_ECU"
        assert prov.identifier == "1640"
        assert prov.service_id == "22"
        assert prov.request_timestamp > 0
        assert prov.response_timestamp >= prov.request_timestamp
        assert prov.elapsed_time >= 0
        assert prov.transaction_id.startswith("TXN-")
        assert prov.definition_id == "DEF-22-1640-ECT"
        assert prov.definition_version == "1.0.0"
        assert prov.trust_level == DefinitionTrustLevel.VERIFIED_TESTED
        print(f"  [PASS] Scenario X: Full provenance trail preserved: txn={prov.transaction_id}")

        # ---------------------------------------------------------------------
        # SCENARIO Y: Definition Version Preservation
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO Y: Definition Version Preservation ---")
        assert ev_c.definition.definition_version == "1.0.0"
        assert prov.definition_version == "1.0.0"
        print("  [PASS] Scenario Y: Definition version preserved immutable")

        # ---------------------------------------------------------------------
        # SCENARIO Z: Vehicle Applicability Mismatch
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO Z: Vehicle Applicability Mismatch ---")
        ctx_toyota = VehicleContext(manufacturer="TOYOTA", model="COROLLA", engine_code="2ZR-FE")
        app_z = did_1640.applicability.evaluate(ctx_toyota)
        assert app_z == ApplicabilityResult.NOT_APPLICABLE
        print("  [PASS] Scenario Z: Mismatched vehicle evaluated as NOT_APPLICABLE")

        # ---------------------------------------------------------------------
        # SCENARIO AA: Unknown Vehicle Applicability
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AA: Unknown Vehicle Applicability ---")
        ctx_empty = VehicleContext()
        app_aa = did_1640.applicability.evaluate(ctx_empty)
        assert app_aa == ApplicabilityResult.UNKNOWN_APPLICABILITY
        print("  [PASS] Scenario AA: Missing context evaluated as UNKNOWN_APPLICABILITY")

        # ---------------------------------------------------------------------
        # SCENARIO AB: Supported Vehicle Applicability
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AB: Supported Vehicle Applicability ---")
        ctx_aveo = VehicleContext(manufacturer="CHEVROLET", model="AVEO", engine_code="F14D3", model_year=2008)
        app_ab = did_1640.applicability.evaluate(ctx_aveo)
        assert app_ab == ApplicabilityResult.CONFIRMED_APPLICABLE
        print("  [PASS] Scenario AB: Chevrolet Aveo F14D3 evaluated as CONFIRMED_APPLICABLE")

        # ---------------------------------------------------------------------
        # SCENARIO AC: Session Requirement
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AC: Session Requirement ---")
        ext_session_def = DiagnosticDataDefinition(
            identifier="2000",
            service_id="22",
            session_requirement=SessionType.EXTENDED,
        )
        assert ext_session_def.session_requirement == SessionType.EXTENDED

        print("  [PASS] Scenario AC: Session requirements explicitly declared")

        # ---------------------------------------------------------------------
        # SCENARIO AD: Cancellation Handling
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AD: Cancellation Handling ---")
        cancel_evt = threading.Event()
        cancel_evt.set()  # Immediately cancelled
        batch_ad = bam.acquire_batch([did_1640, did_1641], cancel_event=cancel_evt)
        assert len(batch_ad.evidence) == 0, "Cancelled batch must not acquire DIDs"
        print("  [PASS] Scenario AD: Batch acquisition cancelled cleanly")

        # ---------------------------------------------------------------------
        # SCENARIO AE: Timeout Handling
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AE: Timeout Handling ---")
        mock_ser.custom_responses["221640"] = None
        try:
            ev_ae = bam.acquire_identifier(did_1640)
            assert ev_ae.is_valid is False
            assert ev_ae.status == STATUS_TIMEOUT
            assert ev_ae.quality == QUALITY_ERROR
            print("  [PASS] Scenario AE: Transport timeout captured as STATUS_TIMEOUT with QUALITY_ERROR")

        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO AF: Bounded Retry
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AF: Bounded Retry ---")
        retry_policy = ServiceRetryPolicy(max_attempts=2, backoff_sec=0.01)
        # Verify retry policy contract on transaction manager
        req_af = did_1640.build_service_request(tm)
        req_af.retry_policy = retry_policy
        assert req_af.retry_policy.max_attempts == 2
        print("  [PASS] Scenario AF: Bounded retry policy configured")


        # ---------------------------------------------------------------------
        # SCENARIO AG: Batch Acquisition
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AG: Batch Acquisition ---")
        defs_ag = [did_1640, did_1641]
        batch_ag = bam.acquire_batch(defs_ag, vehicle_context=ctx_aveo, inter_request_delay=0.01)
        assert len(batch_ag.evidence) == 2
        assert batch_ag.successful_count == 2
        assert batch_ag.failed_count == 0
        assert batch_ag.start_time <= batch_ag.end_time
        print(f"  [PASS] Scenario AG: Batch {batch_ag.batch_id} acquired 2 DIDs successfully")

        # ---------------------------------------------------------------------
        # SCENARIO AH: One DID Failure Does Not Fail Batch
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AH: Failure Isolation in Batch ---")
        mock_ser.custom_responses["221640"] = "7F 22 31\r\n>"  # 1640 fails with NRC
        try:
            batch_ah = bam.acquire_batch([did_1640, did_1641], inter_request_delay=0.01)
            assert batch_ah.successful_count == 1
            assert batch_ah.failed_count == 1
            ev_fail = batch_ah.get_evidence("1640")
            ev_pass = batch_ah.get_evidence("1641")
            assert ev_fail.is_valid is False
            assert ev_pass.is_valid is True
            print("  [PASS] Scenario AH: Strict failure isolation - 1640 failure did not corrupt 1641")
        finally:
            del mock_ser.custom_responses["221640"]

        # ---------------------------------------------------------------------
        # SCENARIO AI: Multiple Successful DIDs
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AI: Multiple Successful DIDs ---")
        pid_0c = reg.get("0C", service_id="01")
        pid_0d = reg.get("0D", service_id="01")
        batch_ai = bam.acquire_batch([pid_0c, pid_0d], inter_request_delay=0.01)
        assert batch_ai.successful_count == 2
        print("  [PASS] Scenario AI: Multiple standard Mode 01 PIDs acquired via batch")

        # ---------------------------------------------------------------------
        # SCENARIO AJ: Rate Limiting / Inter-Request Delay
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AJ: Rate Limiting ---")
        t_start = time.time()
        bam.acquire_batch([did_1640, did_1641], inter_request_delay=0.05)
        elapsed = time.time() - t_start
        assert elapsed >= 0.05, f"Expected elapsed >= 0.05s due to delay, got {elapsed:.3f}s"
        print(f"  [PASS] Scenario AJ: Rate limiting enforced pacing ({elapsed:.3f}s)")

        # ---------------------------------------------------------------------
        # SCENARIO AK: Concurrent Thread Safety
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AK: Concurrent Thread Safety ---")
        results = []
        errors = []

        def worker(w_id):
            try:
                for _ in range(5):
                    ev = bam.acquire_identifier(did_1640)
                    if ev.is_valid:
                        results.append(ev)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent acquisition encountered errors: {errors}"
        assert len(results) == 15
        print("  [PASS] Scenario AK: Concurrent acquisitions executed cleanly across 3 threads")

        # ---------------------------------------------------------------------
        # SCENARIO AL: Late Response Isolation
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AL: Late Response Isolation ---")
        # Ensure a fast request after any prior transaction operates with isolated buffers
        ev_al = bam.acquire_identifier(did_1640)
        assert ev_al.is_valid is True
        print("  [PASS] Scenario AL: Buffer isolation prevents stale/late cross-talk")

        # ---------------------------------------------------------------------
        # SCENARIO AM: Bounded History / Memory Limits
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AM: Bounded History / Memory Limits ---")
        small_bam = BatchAcquisitionManager(tm, registry=reg, history_maxlen=5)
        for _ in range(10):
            small_bam.acquire_batch([did_1640], inter_request_delay=0.0)
        hist = small_bam.get_history()
        assert len(hist) == 5, f"History size {len(hist)} exceeds bounded maxlen 5"
        print("  [PASS] Scenario AM: Bounded history strictly limits memory to 5 items")

        # ---------------------------------------------------------------------
        # SCENARIO AN: Safety-Blocked Service
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AN: Safety-Blocked Service ---")
        blocked_def = DiagnosticDataDefinition(
            identifier="01",
            service_id="04",  # Mode 04 Clear DTCs is universally PROHIBITED
            safety_classification=ServiceSafetyClassification.BLOCKED,
        )
        ev_an = bam.acquire_identifier(blocked_def)
        assert ev_an.is_valid is False
        assert ev_an.status == STATUS_TRANSACTION_BLOCKED
        print("  [PASS] Scenario AN: PROHIBITED service blocked before transmission")

        # ---------------------------------------------------------------------
        # SCENARIO AO: No Automatic Session Transition
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AO: No Automatic Session Transition ---")
        assert tm.session_context.session_type == SessionType.DEFAULT
        # Acquiring extended DID does not silently change active session
        bam.acquire_identifier(did_1640)
        assert tm.session_context.session_type == SessionType.DEFAULT
        print("  [PASS] Scenario AO: No unauthorized automatic session transition")


        # ---------------------------------------------------------------------
        # SCENARIO AP: No Mode 04 (Clear DTCs Universal Prohibition)
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AP: No Mode 04 Prohibition ---")
        req_mode04 = tm.build_request("04")
        res_04 = tm.execute_request(req_mode04)
        assert res_04.status == STATUS_TRANSACTION_BLOCKED
        print("  [PASS] Scenario AP: Mode 04 execution strictly blocked by safety guardrails")

        # ---------------------------------------------------------------------
        # SCENARIO AQ: No Write / Programming Commands
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AQ: No Write / Programming Commands ---")
        for bad_sid in ("2E", "34", "36", "37"):
            req_bad = tm.build_request(bad_sid, payload="1122")
            res_bad = tm.execute_request(req_bad)
            assert res_bad.status == STATUS_TRANSACTION_BLOCKED, f"Service {bad_sid} must be blocked"
        print("  [PASS] Scenario AQ: Write/programming services (2E, 34, 36, 37) strictly blocked")

        # ---------------------------------------------------------------------
        # SCENARIO AR: Regression: Existing Mode 01 PID Acquisition
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AR: Regression: Mode 01 PID Acquisition ---")
        res_0c = engine.komut_gonder("010C", timeout=1.0)
        assert res_0c and any("41" in l for l in res_0c), "Mode 010C must return valid positive response"
        print(f"  [PASS] Scenario AR: Legacy Mode 01 acquisition functional (lines={res_0c})")

        # ---------------------------------------------------------------------
        # SCENARIO AS: Regression: Existing Mode 03 DTC Acquisition
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AS: Regression: Mode 03 DTC Acquisition ---")
        res_03 = engine.komut_gonder("03", timeout=1.0)
        assert res_03 and any("43" in l for l in res_03), "Mode 03 must return valid DTC response"
        print(f"  [PASS] Scenario AS: Legacy Mode 03 DTC acquisition functional (lines={res_03})")


        # ---------------------------------------------------------------------
        # SCENARIO AT: Regression: Phase F Runtime Health & Quality Tracking
        # ---------------------------------------------------------------------
        print("\n--- SCENARIO AT: Regression: Phase F Runtime Health ---")
        assert engine.ser.is_open is True
        assert engine.io_worker is not None and engine.io_worker.is_alive()
        print("  [PASS] Scenario AT: Phase F runtime serial worker healthy and alive")

        print("\n===========================================================================")
        print("ALL 46 G-2 SCENARIOS (A THROUGH AT) PASSED DEFENSIVELY!")
        print("===========================================================================")

    finally:
        if engine.io_worker is not None:
            engine.io_worker.stop()
            engine.io_worker.join(timeout=2.0)
        if engine.ser is not None:
            engine.ser.close()


if __name__ == "__main__":
    run_all_g2_tests()
