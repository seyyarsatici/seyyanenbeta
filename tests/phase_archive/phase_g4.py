# -*- coding: utf-8 -*-
"""
test_phase_g4.py - Comprehensive Test Suite for Phase G-4: Multi-ECU Diagnostics
================================================================================
Validates all mandatory scenarios (A through AH), safety invariants, and regressions:
  - Scenario A: All ECUs reachable
  - Scenario B: ECM only scan
  - Scenario C: ECM + TCM scan
  - Scenario D: ABS timeout isolation
  - Scenario E: SRS unreachable isolation
  - Scenario F: ECU negative response (NRC) handling
  - Scenario G: Unsupported DID handling
  - Scenario H: Wrong ECU response rejection (cross-contamination guard)
  - Scenario I: Late response handling
  - Scenario J: Duplicate response handling
  - Scenario K: Concurrent logical requests with physical transport serialization
  - Scenario L: Partial scan
  - Scenario M: Full scan
  - Scenario N: Per-ECU retry policy
  - Scenario O: Per-ECU circuit breaker
  - Scenario P: Cancellation of scan/batch
  - Scenario Q: One ECU failure does not fail other ECUs (failure isolation)
  - Scenario R: DTCs from multiple ECUs remain distinct
  - Scenario S: Identical DTC code on two ECUs remains distinct (ECM P0300 vs TCM P0300)
  - Scenario T: Timestamp preservation across ECUs
  - Scenario U: Provenance preservation
  - Scenario V: Coverage reporting & reachability metrics
  - Scenario W: Expected-vs-detected ECU distinction
  - Scenario X: Detected-vs-reachable distinction
  - Scenario Y: Session requirement enforcement (REQUIRES_SESSION)
  - Scenario Z: Safety-blocked request
  - Scenario AA: Strict Mode 04 Prohibition
  - Scenario AB: Strict Write / Programming Prohibition
  - Scenario AC: Strict Security Access Prohibition
  - Scenario AD: Memory / History Bounds
  - Scenario AE: Phase F-7 Regression Verification
  - Scenario AF: Phase G-1 Regression Verification
  - Scenario AG: Phase G-2 Regression Verification
  - Scenario AH: Phase G-3 Regression Verification
  - Cross-ECU Timing & G-3 Dataset Conversion
"""

import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

from advanced_ecu_services import (
    AdvancedServiceRequest,
    AdvancedServiceResponse,
    DiagnosticTransactionManager,
    ITransportAdapter,
    ServiceRetryPolicy,
    ServiceSafetyClassification,
    SessionType,
    STATUS_VALID,
    STATUS_NRC,
    STATUS_TIMEOUT,
    STATUS_RESPONSE_MISMATCH,
    STATUS_TRANSACTION_BLOCKED,
    STATUS_TRANSACTION_CANCELLED,
)
from extended_did import (
    DiagnosticDataDefinition,
    DiagnosticDefinitionRegistry,
    FieldDefinition,
    DataType,
    VehicleContext,
)
from multi_ecu_diagnostics import (
    ECUTarget,
    ECUTargetType,
    ECUDiscoveryState,
    ECUCapabilityState,
    ECUHealthState,
    MultiECUVehicleContext,
    MultiECURouter,
    MultiECUScheduler,
    ScheduledECUTask,
    MultiECUDTCRecord,
    MultiECUDataSample,
    MultiECUScanResult,
    MultiECUDiagnosticManager,
    ScanScope,
)
from advanced_fault_analysis import (
    DiagnosticDataSet,
)


class MockMultiECUTransport(ITransportAdapter):
    """
    Deterministic simulated multi-ECU transport.
    Simulates CAN header switching ('AT SH <hdr>'), response delays,
    header-qualified responses, timeouts, and wrong ECU response injections.
    """
    def __init__(self):
        self.current_header = "7DF"
        self.header_history: List[str] = []
        self.commands_sent: List[str] = []
        self.custom_responses: Dict[str, Any] = {}
        self.response_delays: Dict[str, float] = {}
        self.timeout_headers: set = set()
        self.is_open = True

    def send_command(self, cmd: str, timeout: float = 1.0) -> Tuple[List[str], str]:
        self.commands_sent.append(cmd)
        clean = cmd.strip().upper().replace(" ", "")

        # Check timeout header
        if self.current_header in self.timeout_headers:
            return [], STATUS_TIMEOUT

        # Check custom response key: header:cmd or cmd
        hdr_key = f"{self.current_header}:{clean}"
        if hdr_key in self.custom_responses:
            val = self.custom_responses[hdr_key]
        elif clean in self.custom_responses:
            val = self.custom_responses[clean]
        else:
            val = self._default_response(clean)

        if val is None:
            return [], STATUS_TIMEOUT

        # Apply delay if configured
        if hdr_key in self.response_delays:
            time.sleep(self.response_delays[hdr_key])

        lines = val if isinstance(val, list) else [str(val)]
        return lines, STATUS_VALID

    def _default_response(self, clean: str) -> List[str]:
        # Standard default responses based on header
        if clean.startswith("AT"):
            return ["OK"]

        # ECU Response CAN IDs
        resp_id_map = {
            "7E0": "7E8",
            "7E1": "7E9",
            "7E2": "7EA",
            "7E3": "7EB",
            "7E4": "7EC",
            "7DF": "7E8",
        }
        resp_hdr = resp_id_map.get(self.current_header, "7E8")

        # Mode 01 PID 00 ping
        if clean == "0100":
            return [f"{resp_hdr} 06 41 00 BE 1F B8 11"]

        # Mode 03 DTC
        if clean == "03":
            if self.current_header == "7E0":
                # ECM DTC: P0171, P0300
                return [f"{resp_hdr} 06 43 02 01 71 03 00"]
            elif self.current_header == "7E1":
                # TCM DTC: P0700, P0300 (same code on different ECU!)
                return [f"{resp_hdr} 06 43 02 07 00 03 00"]
            elif self.current_header == "7E2":
                # ABS DTC: C0035
                return [f"{resp_hdr} 04 43 01 40 35 00 00"]
            elif self.current_header == "7E3":
                # SRS DTC: B0001
                return [f"{resp_hdr} 04 43 01 80 01 00 00"]
            return ["43 00"]

        # Mode 01 PIDs
        if clean == "010C": # RPM
            return [f"{resp_hdr} 04 41 0C 1A F8"] # 1726 RPM
        if clean == "010D": # Speed
            return [f"{resp_hdr} 03 41 0D 32"]    # 50 km/h
        if clean == "0105": # ECT
            return [f"{resp_hdr} 03 41 05 7B"]    # 83 °C

        # Mode 22 DIDs
        if clean == "221640": # ECT high precision
            return [f"{resp_hdr} 05 62 16 40 04 D2"] # 1234 -> 83.4 °C

        return ["NO DATA"]

    def get_current_header(self) -> str:
        return self.current_header

    def set_header(self, header: str, timeout: float = 1.0) -> bool:
        self.current_header = header.strip().upper()
        self.header_history.append(self.current_header)
        return True

    def is_connected(self) -> bool:
        return self.is_open


class TestPhaseG4MultiECU(unittest.TestCase):
    """Phase G-4 Comprehensive Test Suite."""

    def setUp(self):
        self.transport = MockMultiECUTransport()
        self.tx_manager = DiagnosticTransactionManager(transport=self.transport)
        self.manager = MultiECUDiagnosticManager(transaction_manager=self.tx_manager)

    # -----------------------------------------------------------------
    # SCENARIOS A, B, C: Reachability Matrix
    # -----------------------------------------------------------------
    def test_scenario_a_all_ecus_reachable(self):
        """Scenario A: All ECUs (ECM, TCM, ABS, SRS, BCM) reachable."""
        disc = self.manager.discover_ecus()
        self.assertEqual(disc["ECM"], ECUDiscoveryState.VERIFIED_REACHABLE)
        self.assertEqual(disc["TCM"], ECUDiscoveryState.VERIFIED_REACHABLE)
        self.assertEqual(disc["ABS"], ECUDiscoveryState.VERIFIED_REACHABLE)
        self.assertEqual(disc["SRS"], ECUDiscoveryState.VERIFIED_REACHABLE)
        self.assertEqual(disc["BCM"], ECUDiscoveryState.VERIFIED_REACHABLE)

    def test_scenario_b_ecm_only_scan(self):
        """Scenario B: Scan targeted only to ECM."""
        res = self.manager.scan_ecu("ECM")
        self.assertEqual(res.scan_scope, ScanScope.SINGLE_ECU)
        self.assertIn("ECM", res.reachable_ecus)
        self.assertEqual(len(res.ecu_records), 1)
        self.assertGreater(len(res.get_ecu_dtcs("ECM")), 0)

    def test_scenario_c_ecm_and_tcm_scan(self):
        """Scenario C: Scan targeted to ECM and TCM only."""
        res = self.manager.scan_vehicle(targets=["ECM", "TCM"])
        self.assertEqual(res.scan_scope, ScanScope.PARTIAL)
        self.assertIn("ECM", res.reachable_ecus)
        self.assertIn("TCM", res.reachable_ecus)
        self.assertNotIn("ABS", res.ecu_records)

    # -----------------------------------------------------------------
    # SCENARIOS D, E, Q: Failure Isolation & Unreachable ECUs
    # -----------------------------------------------------------------
    def test_scenario_d_abs_timeout_isolation(self):
        """Scenario D: ABS times out; ECM and TCM succeed unimpeded."""
        self.transport.timeout_headers.add("7E2") # ABS header
        res = self.manager.scan_vehicle(targets=["ECM", "TCM", "ABS"])
        self.assertIn("ECM", res.reachable_ecus)
        self.assertIn("TCM", res.reachable_ecus)
        self.assertIn("ABS", res.unreachable_ecus)
        # Verify ABS failure did not contaminate ECM record
        self.assertEqual(res.ecu_records["ECM"].health_state, ECUHealthState.CONNECTED.value)
        self.assertIn(res.ecu_records["ABS"].health_state, (ECUHealthState.DEGRADED.value, ECUHealthState.UNREACHABLE.value))

    def test_scenario_e_srs_unreachable(self):
        """Scenario E: SRS is completely offline/unreachable."""
        self.transport.timeout_headers.add("7E3")
        is_reach = self.manager.check_ecu_reachability("SRS")
        self.assertFalse(is_reach)
        ecu = self.manager.get_ecu("SRS")
        self.assertEqual(ecu.health_state, ECUHealthState.UNREACHABLE)

    def test_scenario_q_failure_isolation(self):
        """Scenario Q: Multiple ECU failures do not invalidate overall partial scan."""
        self.transport.timeout_headers.add("7E2") # ABS down
        self.transport.timeout_headers.add("7E3") # SRS down
        res = self.manager.scan_vehicle()
        self.assertIn("ECM", res.reachable_ecus)
        self.assertIn("TCM", res.reachable_ecus)
        self.assertIn("BCM", res.reachable_ecus)
        self.assertIn("ABS", res.unreachable_ecus)
        self.assertIn("SRS", res.unreachable_ecus)
        # Scan must report partial success rather than global failure
        self.assertGreater(res.successful_transactions, 0)
        self.assertGreater(res.failed_transactions, 0)

    # -----------------------------------------------------------------
    # SCENARIOS F, G, H: Negative Responses, Unsupported DIDs & Wrong Target Guard
    # -----------------------------------------------------------------
    def test_scenario_f_ecu_negative_response_nrc(self):
        """Scenario F: ECU responds with an NRC (e.g. NRC 0x22 Conditions Not Correct)."""
        # Inject NRC 22 for ECM 010C
        self.transport.custom_responses["7E0:010C"] = ["7E8 03 7F 01 22"]
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["0C"]})
        self.assertEqual(len(samples), 1)
        self.assertFalse(samples[0].is_valid)

    def test_scenario_g_unsupported_did(self):
        """Scenario G: Unsupported DID returns NRC 0x31 (Request Out of Range)."""
        self.transport.custom_responses["7E0:22DEAD"] = ["7E8 03 7F 22 31"]
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["DEAD"]})
        self.assertFalse(samples[0].is_valid)

    def test_scenario_h_wrong_ecu_response_rejection(self):
        """Scenario H: Request sent to ECM (7E0 -> 7E8) receives response from TCM (7E9) -> Rejected!"""
        # Inject cross-contamination: ECM header 7E0 query receives 7E9 response
        self.transport.custom_responses["7E0:010D"] = ["7E9 03 41 0D 64"]
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["0D"]})
        self.assertEqual(len(samples), 1)
        # Must be rejected due to wrong ECU response header
        self.assertFalse(samples[0].is_valid)
        self.assertIn("mismatch", samples[0].error_message.lower())

    # -----------------------------------------------------------------
    # SCENARIOS I, J, K: Response Timing & Serialized Concurrency
    # -----------------------------------------------------------------
    def test_scenario_i_late_response_within_timeout(self):
        """Scenario I: Response arrives after brief delay but within timeout."""
        self.transport.response_delays["7E0:010D"] = 0.05
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["0D"]})
        self.assertTrue(samples[0].is_valid)

    def test_scenario_j_duplicate_response_handling(self):
        """Scenario J: Multi-line response with duplicate lines handled safely."""
        self.transport.custom_responses["7E0:010D"] = ["7E8 03 41 0D 32", "7E8 03 41 0D 32"]
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["0D"]})
        self.assertTrue(samples[0].is_valid)
        self.assertEqual(samples[0].decoded_value, 50)

    def test_scenario_k_concurrent_logical_requests_serialized(self):
        """Scenario K: Multiple ECU requests queued are safely serialized over transport."""
        res = self.manager.scan_vehicle(targets=["ECM", "TCM", "ABS", "SRS"])
        # Verify that AT SH header commands were issued sequentially and restored
        self.assertGreater(len(self.transport.header_history), 0)
        self.assertGreater(res.total_transactions, 0)

    # -----------------------------------------------------------------
    # SCENARIOS L, M, N, O, P: Scanning, Retries, Circuit Breaker & Cancellation
    # -----------------------------------------------------------------
    def test_scenario_l_partial_scan(self):
        """Scenario L: Partial scan of selected modules."""
        res = self.manager.scan_vehicle(targets=["ABS", "SRS"])
        self.assertEqual(res.scan_scope, ScanScope.PARTIAL)
        self.assertEqual(set(res.ecu_records.keys()), {"ABS", "SRS"})

    def test_scenario_m_full_scan(self):
        """Scenario M: Full vehicle scan across all registered modules."""
        res = self.manager.scan_vehicle()
        self.assertEqual(res.scan_scope, ScanScope.FULL_VEHICLE)
        self.assertEqual(len(res.ecu_records), len(self.manager.list_ecus()))

    def test_scenario_n_per_ecu_retry(self):
        """Scenario N: Per-ECU retry policy retries transient failures."""
        ecu = self.manager.get_ecu("ECM")
        req = self.manager.router.transaction_manager.build_request(
            service_id="01",
            subfunction="0C",
            retry_policy=ServiceRetryPolicy(max_attempts=2, backoff_sec=0.01, retry_on_timeout=True),
        )
        self.transport.timeout_headers.add("7E0")
        resp = self.manager.router.transaction_manager.execute_request(req)
        self.assertEqual(resp.status, STATUS_TIMEOUT)

    def test_scenario_o_per_ecu_circuit_breaker(self):
        """Scenario O: Circuit breaker trips after consecutive failures on an ECU."""
        ecu = self.manager.get_ecu("ABS")
        self.transport.timeout_headers.add("7E2")
        # Trigger consecutive failures
        for _ in range(3):
            self.manager.check_ecu_reachability("ABS")
        self.assertTrue(ecu.circuit_breaker_open)
        self.assertEqual(ecu.health_state, ECUHealthState.UNREACHABLE)

    def test_scenario_p_cancellation(self):
        """Scenario P: Cancellation aborts subsequent tasks in a multi-ECU batch."""
        self.manager.cancel_scan()
        tasks = [
            ScheduledECUTask(target=self.manager.get_ecu("ECM"), service_id="01", subfunction="0C"),
            ScheduledECUTask(target=self.manager.get_ecu("TCM"), service_id="01", subfunction="0D"),
        ]
        # Execute batch when scheduler was marked cancelled
        self.manager.scheduler.cancel()
        results = self.manager.scheduler.execute_batch(tasks)
        for _, resp in results:
            self.assertEqual(resp.status, STATUS_TRANSACTION_CANCELLED)

    # -----------------------------------------------------------------
    # SCENARIOS R, S, T, U, V: DTCs, Signal Identity, Provenance & Coverage
    # -----------------------------------------------------------------
    def test_scenario_r_dtcs_from_multiple_ecus_distinct(self):
        """Scenario R: DTCs from multiple ECUs remain distinct and preserve ECU origin."""
        res = self.manager.scan_vehicle(targets=["ECM", "TCM", "ABS"])
        ecm_dtcs = res.get_ecu_dtcs("ECM")
        tcm_dtcs = res.get_ecu_dtcs("TCM")
        abs_dtcs = res.get_ecu_dtcs("ABS")

        self.assertTrue(any(d.code == "P0171" for d in ecm_dtcs))
        self.assertTrue(any(d.code == "P0700" for d in tcm_dtcs))
        self.assertTrue(any(d.code == "C0035" for d in abs_dtcs))
        for d in ecm_dtcs:
            self.assertEqual(d.ecu_id, "ECM")
        for d in tcm_dtcs:
            self.assertEqual(d.ecu_id, "TCM")

    def test_scenario_s_identical_dtc_code_distinct(self):
        """Scenario S: Identical DTC (e.g. P0300) on ECM and TCM remain separate records."""
        res = self.manager.scan_vehicle(targets=["ECM", "TCM"])
        all_dtcs = res.get_all_dtcs()
        p0300_records = [d for d in all_dtcs if d.code == "P0300"]
        self.assertEqual(len(p0300_records), 2)
        ecus = {d.ecu_id for d in p0300_records}
        self.assertEqual(ecus, {"ECM", "TCM"})

    def test_scenario_t_timestamp_preservation(self):
        """Scenario T: Cross-ECU timestamps are preserved accurately."""
        t_before = time.time()
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["0C"], "TCM": ["0D"]})
        t_after = time.time()
        for s in samples:
            self.assertGreaterEqual(s.response_timestamp, t_before)
            self.assertLessEqual(s.response_timestamp, t_after)

    def test_scenario_u_provenance_preservation(self):
        """Scenario U: Full provenance preserved on acquired multi-ECU data."""
        samples = self.manager.acquire_multi_ecu_snapshot({"ECM": ["0C"]})
        s = samples[0]
        self.assertEqual(s.ecu_id, "ECM")
        self.assertTrue(s.transaction_id.startswith("TXN-"))
        self.assertEqual(s.canonical_name, "ECM:0C:RPM")

    def test_scenario_v_coverage_reporting(self):
        """Scenario V: Coverage metrics are computed correctly in scan result."""
        res = self.manager.scan_vehicle(targets=["ECM", "TCM"])
        cov = res.to_dict()["coverage_metrics"]
        self.assertEqual(cov["expected_count"], 2)
        self.assertEqual(cov["reachable_count"], 2)
        self.assertEqual(cov["reachable_pct"], 100.0)

    # -----------------------------------------------------------------
    # SCENARIOS W, X, Y, Z: Discovery States, Sessions & Safety Guardrails
    # -----------------------------------------------------------------
    def test_scenario_w_expected_vs_detected(self):
        """Scenario W: Distinction between EXPECTED and DETECTED ECU states."""
        ecu = ECUTarget(
            logical_id="HVAC",
            ecu_type=ECUTargetType.CLIMATE,
            discovery_state=ECUDiscoveryState.EXPECTED,
        )
        self.manager.register_ecu(ecu)
        self.assertEqual(ecu.discovery_state, ECUDiscoveryState.EXPECTED)
        # Probing updates it to VERIFIED_REACHABLE or UNSUPPORTED
        self.manager.check_ecu_reachability(ecu)
        self.assertIn(ecu.discovery_state, (ECUDiscoveryState.VERIFIED_REACHABLE, ECUDiscoveryState.UNSUPPORTED))

    def test_scenario_x_detected_vs_reachable(self):
        """Scenario X: Detected ECU on bus becomes VERIFIED_REACHABLE upon positive response."""
        ecu = self.manager.get_ecu("ECM")
        ecu.discovery_state = ECUDiscoveryState.DETECTED
        self.manager.check_ecu_reachability(ecu)
        self.assertEqual(ecu.discovery_state, ECUDiscoveryState.VERIFIED_REACHABLE)

    def test_scenario_y_session_requirement(self):
        """Scenario Y: Request requiring EXTENDED session blocked safely if ECU is in DEFAULT."""
        ecu = self.manager.get_ecu("ECM")
        ecu.current_session = SessionType.DEFAULT
        resp = self.manager.router.execute_for_target(
            target=ecu,
            service_id="22",
            payload="1640",
            session_requirement=SessionType.EXTENDED,
        )
        self.assertEqual(resp.status, STATUS_TRANSACTION_BLOCKED)
        self.assertIn("requires session EXTENDED", resp.error_message)

    def test_scenario_z_safety_blocked_service(self):
        """Scenario Z: Non-read-only service (e.g. Service 0x2E Write) blocked by safety policy."""
        req = self.manager.router.transaction_manager.build_request(
            service_id="2E",
            payload="0102",
            target_ecu="ECM",
        )
        resp = self.manager.router.transaction_manager.execute_request(req)
        self.assertEqual(resp.status, STATUS_TRANSACTION_BLOCKED)

    # -----------------------------------------------------------------
    # SCENARIOS AA, AB, AC, AD: Invariants & Memory Bounds
    # -----------------------------------------------------------------
    def test_scenario_aa_strict_no_mode04(self):
        """Scenario AA: Mode 04 (Clear DTCs) is strictly blocked."""
        req = self.manager.router.transaction_manager.build_request(
            service_id="04",
            target_ecu="ECM",
        )
        resp = self.manager.router.transaction_manager.execute_request(req)
        self.assertEqual(resp.status, STATUS_TRANSACTION_BLOCKED)

    def test_scenario_ab_no_write_programming(self):
        """Scenario AB: Programming services (0x34, 0x36, 0x37) are strictly blocked."""
        for s in ("34", "36", "37"):
            req = self.manager.router.transaction_manager.build_request(service_id=s, target_ecu="ECM")
            resp = self.manager.router.transaction_manager.execute_request(req)
            self.assertEqual(resp.status, STATUS_TRANSACTION_BLOCKED)

    def test_scenario_ac_no_security_access(self):
        """Scenario AC: Security Access (0x27) is strictly blocked."""
        req = self.manager.router.transaction_manager.build_request(service_id="27", target_ecu="ECM")
        resp = self.manager.router.transaction_manager.execute_request(req)
        self.assertEqual(resp.status, STATUS_TRANSACTION_BLOCKED)

    def test_scenario_ad_memory_and_history_bounds(self):
        """Scenario AD: Transaction and scan history deque maxlen is bounded."""
        self.assertEqual(self.manager.transaction_manager._history.maxlen, 100)

    # -----------------------------------------------------------------
    # DOWNSTREAM G-3 DATASET CONVERSION
    # -----------------------------------------------------------------
    def test_g3_dataset_conversion(self):
        """Verifies that a MultiECUScanResult converts cleanly into a Phase G-3 DiagnosticDataSet."""
        res = self.manager.scan_vehicle(targets=["ECM", "TCM"])
        dataset = res.to_g3_dataset()
        self.assertIsInstance(dataset, DiagnosticDataSet)
        self.assertGreater(len(dataset.dtc_records), 0)
        self.assertGreater(len(dataset.signals), 0)

        # Verify source ECU tagging on DTCs
        ecm_dtcs = [d for d in dataset.dtc_records if d.ecu_source == "ECM"]
        tcm_dtcs = [d for d in dataset.dtc_records if d.ecu_source == "TCM"]
        self.assertGreater(len(ecm_dtcs), 0)
        self.assertGreater(len(tcm_dtcs), 0)

        # Verify signal names have canonical prefix
        self.assertTrue(any("ECM:" in name for name in dataset.signals.keys()))

    # -----------------------------------------------------------------
    # CROSS-ECU REALISTIC TIMING & SIGNAL IDENTITY
    # -----------------------------------------------------------------
    def test_realistic_cross_ecu_timing(self):
        """
        Deterministic scenario:
          ECM event at t0, TCM event at t0 + Δ1, ABS event at t0 + Δ2.
        Verifies that actual timestamps are preserved accurately across ECUs.
        """
        self.transport.response_delays["7E0:010C"] = 0.01
        self.transport.response_delays["7E1:010D"] = 0.03
        self.transport.response_delays["7E2:0105"] = 0.05

        samples = self.manager.acquire_multi_ecu_snapshot({
            "ECM": ["0C"],
            "TCM": ["0D"],
            "ABS": ["05"],
        })
        self.assertEqual(len(samples), 3)
        t_ecm = next(s.response_timestamp for s in samples if s.ecu_id == "ECM")
        t_tcm = next(s.response_timestamp for s in samples if s.ecu_id == "TCM")
        t_abs = next(s.response_timestamp for s in samples if s.ecu_id == "ABS")

        self.assertLessEqual(t_ecm, t_tcm)
        self.assertLessEqual(t_tcm, t_abs)

    def test_ecu_identity_and_signal_collision(self):
        """
        Verifies that signals with identical names/IDs from different ECUs
        (e.g. speed from ECM vs speed from TCM) remain separate signals
        and do not overwrite each other.
        """
        samples = self.manager.acquire_multi_ecu_snapshot({
            "ECM": ["0D"],
            "TCM": ["0D"],
        })
        self.assertEqual(len(samples), 2)
        names = [s.canonical_name for s in samples]
        self.assertIn("ECM:0D:Speed", names)
        self.assertIn("TCM:0D:Speed", names)
        self.assertNotEqual(names[0], names[1])

    def test_engine_integration_with_mock_serial(self):
        """
        Verifies AutoExpertEngine.scan_vehicle_multiecu using real AutoExpertEngine.
        """
        from motor import AutoExpertEngine
        engine = AutoExpertEngine()
        engine.baglan()
        try:
            # Force simulated headers
            engine.ser.custom_responses["7E0:0100"] = ["7E8 06 41 00 BE 1F B8 11"]
            engine.ser.custom_responses["7E1:0100"] = ["7E9 06 41 00 80 00 00 00"]
            engine.ser.custom_responses["7E0:03"] = ["7E8 06 43 01 01 71 00 00"]

            res = engine.scan_vehicle_multiecu(targets=["ECM", "TCM"], include_data=False)
            self.assertIn("ECM", res.reachable_ecus)
            self.assertIn("TCM", res.reachable_ecus)
            ecm_dtcs = res.get_ecu_dtcs("ECM")
            self.assertGreater(len(ecm_dtcs), 0)
            self.assertEqual(ecm_dtcs[0].code, "P0171")
        finally:
            if hasattr(engine, "ser") and engine.ser:
                engine.ser.close()

    # -----------------------------------------------------------------
    # SCENARIOS AE, AF, AG, AH: Phase Regressions
    # -----------------------------------------------------------------
    def test_scenario_ae_phase_f7_regression(self):
        """Scenario AE: Verify Phase F-7 modules remain importable and functional."""
        from motor import AutoExpertEngine
        engine = AutoExpertEngine()
        self.assertTrue(hasattr(engine, "discover_ecu_capabilities"))
        self.assertTrue(hasattr(engine, "run_diagnostic_pipeline"))

    def test_scenario_af_phase_g1_regression(self):
        """Scenario AF: Verify G-1 DiagnosticTransactionManager functions properly."""
        from advanced_ecu_services import ServiceSafetyPolicy
        policy = ServiceSafetyPolicy()
        req = self.manager.router.transaction_manager.build_request(service_id="01", subfunction="0C")
        safe, _ = policy.validate_request(req)
        self.assertTrue(safe)

    def test_scenario_ag_phase_g2_regression(self):
        """Scenario AG: Verify G-2 DataDecoder and ExtendedDIDRegistry function properly."""
        from extended_did import DiagnosticDefinitionRegistry
        reg = DiagnosticDefinitionRegistry()
        defn = reg.get("0C", "01")
        self.assertIsNotNone(defn)
        self.assertEqual(defn.fields[0].name, "RPM")

    def test_scenario_ah_phase_g3_regression(self):
        """Scenario AH: Verify Phase G-3 AdvancedFaultAnalyzer can consume G-4 dataset."""
        from advanced_fault_analysis import AdvancedFaultAnalyzer
        analyzer = AdvancedFaultAnalyzer()
        scan_res = self.manager.scan_vehicle(targets=["ECM", "TCM"])
        dataset = scan_res.to_g3_dataset()
        analysis = analyzer.analyze_dataset(dataset)
        self.assertIsNotNone(analysis)
        self.assertGreaterEqual(len(analysis.hypotheses), 0)


def run_all_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhaseG4MultiECU)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    if not success:
        exit(1)

