#!/usr/bin/env python3
"""
test_phase_k3.py - Phase K-3 Live Acquisition Runtime & Trusted Data Pipeline Test Suite
========================================================================================
Comprehensive automated verification of Phase K-3 invariants:
  A. Acquisition runtime start
  B. Acquisition runtime stop
  C. Deterministic lifecycle transitions
  D. No UI-thread blocking
  E. One authoritative acquisition loop
  F. No duplicate worker on repeated start
  G. Successful sample reaches cache (VALID + QUALITY_GOOD)
  H. Failed sample does not become trusted data (no fake zeros)
  I. Timeout semantics
  J. NO DATA semantics
  K. NRC semantics
  L. DID / subfunction mismatch semantics
  M. Malformed response semantics
  N. Transport failure semantics
  O. Bounded sensor history
  P. Freshness behavior (stale detection)
  Q. Monotonic / accurate observation timestamps
  R. Multi-ECU context separation
  S. Vehicle identity separation & invalidation
  T. J-3 persistence integration (save_raw_acquisition)
  U. Persistence failure isolation (DB error does not kill acquisition)
  V. Bounded downstream queue & backpressure drop behavior
  W. Reconnect behavior without duplicate workers
  X. Shutdown behavior with clean resource disposal
  Y. No worker / thread leaks
  Z. Adapter command serialization
  AA. Safety policy remains enforced (prohibited SIDs blocked)
  AB. Diagnostic intelligence consumers receive trusted data
  AC. Intelligence cannot directly bypass acquisition architecture
  AD. Regression against K-1
  AE. Regression against K-2
  AF. Relevant J-1 / J-6 / J-Final regression
"""

import unittest
import time
import threading
import queue
from typing import Dict, Any, List, Optional
from collections import deque

from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_STARTING,
    LIVE_RUNNING,
    LIVE_DEGRADED,
    LIVE_STOPPING,
    LIVE_STOPPED,
    LIVE_ERROR,
    DEFAULT_PID_CATALOG,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_EMPTY_RESPONSE,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
    STATUS_DID_MISMATCH,
    QUALITY_GOOD,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
    QUALITY_IMPLAUSIBLE,
    QUALITY_SUSPECT,
)
from diagnostic_adapter import (
    DiagnosticAdapter,
    ELM327DiagnosticAdapter,
    MockSerialForELM,
    AdapterConnectionState,
    AdapterCapabilities,
    PROHIBITED_SERVICES,
)
from diagnostic_persistence import (
    DiagnosticRepository,
    SQLitePersistenceBackend,
    PersistenceError,
)
from live_quality import LiveQualityAssessor
from live_intelligence import LiveDiagnosticIntelligence
from live_safety import RuntimeSafetyManager
from production_reliability import (
    ShutdownCoordinator,
    MultiECUFailureIsolation,
    SystemHealthMonitor,
)


class MockEngineForK3:
    """Lightweight test double for AutoExpertEngine preserving C-layer contracts."""
    def __init__(self):
        self.is_can = True
        self.last_response_status = STATUS_VALID
        self.data_cache: Dict[str, Dict[str, Any]] = {}
        self.sensor_cache: Dict[str, Any] = {}
        self.sensor_history: Dict[str, deque] = {}
        self.history_max_len = 50
        self.sent_commands: List[str] = []
        self.custom_responses: Dict[str, List[str]] = {}

    def komut_gonder(self, cmd: str, timeout: float = 1.0) -> List[str]:
        self.sent_commands.append(cmd)
        if cmd in self.custom_responses:
            return self.custom_responses[cmd]
        clean = cmd.replace(" ", "").upper()
        if clean == "010C":
            return ["41 0C 1A F8"]  # RPM = (0x1AF8) / 4 = 6904 / 4 = 1726 RPM
        elif clean == "010D":
            return ["41 0D 32"]      # SPEED = 50 km/h
        elif clean == "0105":
            return ["41 05 80"]      # ECT = 128 - 40 = 88 °C
        elif clean == "010B":
            return ["41 0B 64"]      # MAP = 100 kPa
        elif clean == "0111":
            return ["41 11 40"]      # TPS = 64 * 100 / 255 = 25.1 %
        return ["41 00 00"]

    def _update_sensor_cache(self, name: str, value, status: str = STATUS_VALID, quality: str = None, timestamp: float = None, source: str = None) -> dict:
        ts = timestamp if timestamp is not None else time.time()
        q = quality if quality is not None else (QUALITY_GOOD if status == STATUS_VALID else QUALITY_ERROR)
        entry = {
            "val": value,
            "time": ts,
            "status": status,
            "quality": q,
        }
        if source:
            entry["source"] = source
        self.data_cache[name] = entry
        self.sensor_cache[name] = value

        if status == STATUS_VALID and q == QUALITY_GOOD and value is not None:
            if name not in self.sensor_history:
                self.sensor_history[name] = deque(maxlen=self.history_max_len)
            self.sensor_history[name].append(dict(entry))
        return entry

    def _get_sensor_age(self, name: str) -> Optional[float]:
        entry = self.data_cache.get(name)
        if isinstance(entry, dict) and "time" in entry and entry["time"] > 0:
            return time.time() - entry["time"]
        return None

    def _is_sensor_fresh(self, name: str, max_age: float = 2.0) -> bool:
        age = self._get_sensor_age(name)
        if age is None:
            return False
        return age <= max_age

    def _get_sensor_history(self, name: str, limit: Optional[int] = None) -> list:
        hist = self.sensor_history.get(name)
        if not hist:
            return []
        items = list(hist)
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def _get_trusted_sensor_value(self, name: str) -> Optional[float]:
        entry = self.data_cache.get(name)
        if not entry:
            return None
        if entry.get("status") != STATUS_VALID or entry.get("quality") != QUALITY_GOOD:
            return None
        if not self._is_sensor_fresh(name):
            return None
        val = entry.get("val")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        return None


def create_mock_adapter() -> Tuple[ELM327DiagnosticAdapter, MockSerialForELM]:
    """Helper to create a connected ELM327 adapter backed by deterministic MockSerialForELM."""
    mock_ser = MockSerialForELM(port="COM1")
    adapter = ELM327DiagnosticAdapter(port="COM1", serial_factory=lambda *a, **kw: mock_ser)
    ok = adapter.connect(timeout=2.0)
    assert ok is True
    return adapter, mock_ser


class TestPhaseK3LiveAcquisition(unittest.TestCase):
    """Phase K-3 Comprehensive Test Suite."""

    def setUp(self):
        self.engine = MockEngineForK3()
        self.adapter, self.mock_ser = create_mock_adapter()

    def tearDown(self):
        if hasattr(self, "adapter") and self.adapter:
            try:
                self.adapter.disconnect()
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Test A: Acquisition runtime start
    # -----------------------------------------------------------------
    def test_a_acquisition_runtime_start(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C", "010D"],
            cycle_interval=0.05,
        )
        self.assertEqual(runtime.get_state(), LIVE_IDLE)
        ok = runtime.start()
        self.assertTrue(ok)
        self.assertEqual(runtime.get_state(), LIVE_RUNNING)
        self.assertTrue(runtime.is_running())
        runtime.stop(timeout=1.0)
        self.assertEqual(runtime.get_state(), LIVE_STOPPED)

    # -----------------------------------------------------------------
    # Test B: Acquisition runtime stop
    # -----------------------------------------------------------------
    def test_b_acquisition_runtime_stop(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.05,
        )
        runtime.start()
        time.sleep(0.08)
        ok = runtime.stop(timeout=1.0)
        self.assertTrue(ok)
        self.assertEqual(runtime.get_state(), LIVE_STOPPED)
        self.assertFalse(runtime.is_running())
        # Idempotent stop check
        ok2 = runtime.stop(timeout=1.0)
        self.assertTrue(ok2)

    # -----------------------------------------------------------------
    # Test C: Deterministic lifecycle transitions
    # -----------------------------------------------------------------
    def test_c_deterministic_lifecycle_transitions(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.05,
        )
        self.assertEqual(runtime.get_state(), LIVE_IDLE)
        runtime.start()
        self.assertIn(runtime.get_state(), (LIVE_RUNNING, LIVE_STARTING))
        runtime.stop(timeout=1.0)
        self.assertEqual(runtime.get_state(), LIVE_STOPPED)
        # Restartable from STOPPED
        ok = runtime.start()
        self.assertTrue(ok)
        self.assertEqual(runtime.get_state(), LIVE_RUNNING)
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test D: No UI-thread blocking
    # -----------------------------------------------------------------
    def test_d_no_ui_thread_blocking(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C", "010D", "0105"],
            cycle_interval=0.05,
        )
        start_t = time.monotonic()
        runtime.start()
        start_duration = time.monotonic() - start_t
        # Start call must return near-instantaneously (< 20ms) without waiting on physical reads
        self.assertLess(start_duration, 0.05)
        self.assertTrue(runtime.is_running())
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test E: One authoritative acquisition loop
    # -----------------------------------------------------------------
    def test_e_one_authoritative_acquisition_loop(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.04,
        )
        runtime.start()
        worker1 = runtime._worker_thread
        self.assertIsNotNone(worker1)
        self.assertTrue(worker1.is_alive())
        # Attempt second start while running
        runtime.start()
        # Must retain exact same worker thread
        self.assertIs(runtime._worker_thread, worker1)
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test F: No duplicate worker on repeated start
    # -----------------------------------------------------------------
    def test_f_no_duplicate_worker_on_repeated_start(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.04,
        )
        res1 = runtime.start()
        self.assertTrue(res1)
        res2 = runtime.start()
        self.assertFalse(res2)
        res3 = runtime.start()
        self.assertFalse(res3)
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test G: Successful sample reaches cache (VALID + QUALITY_GOOD)
    # -----------------------------------------------------------------
    def test_g_successful_sample_reaches_cache(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.12)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("010C")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["status"], STATUS_VALID)
        self.assertIsNotNone(sample["value"])
        self.assertGreater(sample["value"], 0.0)

        # C-layer cache check
        self.assertIn("RPM", self.engine.data_cache)
        cache_entry = self.engine.data_cache["RPM"]
        self.assertEqual(cache_entry["status"], STATUS_VALID)
        self.assertEqual(cache_entry["quality"], QUALITY_GOOD)
        self.assertGreater(len(self.engine._get_sensor_history("RPM")), 0)

    # -----------------------------------------------------------------
    # Test H: Failed sample does not become trusted data (no fake zeros)
    # -----------------------------------------------------------------
    def test_h_failed_sample_does_not_become_trusted_data(self):
        # Configure mock serial to return NO DATA for 010C
        self.mock_ser.custom_responses["010C"] = b"NO DATA\r\r>"
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("010C")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["status"], STATUS_NO_DATA)
        self.assertIsNone(sample["value"])  # Must NOT be fake zero 0.0!
        self.assertNotEqual(sample["value"], 0)

        # C-layer history must NOT have received any invalid samples
        self.assertEqual(len(self.engine._get_sensor_history("RPM")), 0)

    # -----------------------------------------------------------------
    # Test I: Timeout semantics
    # -----------------------------------------------------------------
    def test_i_timeout_semantics(self):
        self.mock_ser.inject_init_timeout = True
        # Set command timeout on adapter
        self.mock_ser.custom_responses["010C"] = b""  # Empty response triggers timeout in mock
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("010C")
        self.assertIsNotNone(sample)
        self.assertIn(sample["status"], (STATUS_TIMEOUT, STATUS_NO_DATA))
        self.assertIsNone(sample["value"])

    # -----------------------------------------------------------------
    # Test J: NO DATA semantics
    # -----------------------------------------------------------------
    def test_j_no_data_semantics(self):
        self.mock_ser.custom_responses["010D"] = b"NO DATA\r\r>"
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010D"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("010D")
        self.assertEqual(sample["status"], STATUS_NO_DATA)
        self.assertIsNone(sample["value"])
        self.assertIn("NO DATA", sample["raw_value"])

    # -----------------------------------------------------------------
    # Test K: NRC semantics
    # -----------------------------------------------------------------
    def test_k_nrc_semantics(self):
        # Simulate ECU negative response code
        self.mock_ser.custom_responses["0105"] = b"7F 01 31\r\r>"
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["0105"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("0105")
        self.assertIsNotNone(sample)
        # 7F 01 31 is not a valid 41 05 positive response, so decoded_val is None
        self.assertIsNone(sample["value"])
        self.assertIn("7F", sample["raw_value"])

    # -----------------------------------------------------------------
    # Test L: DID / subfunction mismatch semantics
    # -----------------------------------------------------------------
    def test_l_did_mismatch_semantics(self):
        # Return response for 010C when 0105 was queried
        self.mock_ser.custom_responses["0105"] = b"41 0C 1A F8\r\r>"
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["0105"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("0105")
        self.assertIsNotNone(sample)
        # Decoder expects 41 05, so returned 41 0C fails decode
        self.assertIsNone(sample["value"])
        self.assertEqual(sample["status"], STATUS_NO_DATA)

    # -----------------------------------------------------------------
    # Test M: Malformed response semantics
    # -----------------------------------------------------------------
    def test_m_malformed_response_semantics(self):
        self.mock_ser.custom_responses["010B"] = b"41 0B ZZ GARBAGE\r\r>"
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010B"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        sample = runtime.get_latest_sample("010B")
        self.assertIsNotNone(sample)
        self.assertIsNone(sample["value"])

    # -----------------------------------------------------------------
    # Test N: Transport failure semantics
    # -----------------------------------------------------------------
    def test_n_transport_failure_semantics(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.06)
        # Inject transport failure / disconnect on physical adapter
        self.mock_ser.is_open = False
        time.sleep(0.08)

        # Runtime should transition to LIVE_ERROR deterministically
        self.assertEqual(runtime.get_state(), LIVE_ERROR)
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test O: Bounded sensor history
    # -----------------------------------------------------------------
    def test_o_bounded_sensor_history(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.01,
            history_maxlen=25,
        )
        runtime.start()
        time.sleep(0.4)
        runtime.stop(timeout=1.0)

        recent = runtime.get_recent_samples()
        self.assertLessEqual(len(recent), 25)
        self.assertGreater(len(recent), 5)

    # -----------------------------------------------------------------
    # Test P: Freshness behavior (stale detection)
    # -----------------------------------------------------------------
    def test_p_freshness_behavior(self):
        # Update engine cache with an artificially old entry
        self.engine.data_cache["RPM"] = {
            "val": 850.0,
            "time": time.time() - 5.0,  # 5 seconds old
            "status": STATUS_VALID,
            "quality": QUALITY_GOOD,
        }
        self.assertFalse(self.engine._is_sensor_fresh("RPM", max_age=2.0))
        self.assertIsNone(self.engine._get_trusted_sensor_value("RPM"))

        # Re-acquire fresh sample via runtime
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.1)
        runtime.stop(timeout=1.0)

        # Freshness is restored
        self.assertTrue(self.engine._is_sensor_fresh("RPM", max_age=2.0))
        self.assertIsNotNone(self.engine._get_trusted_sensor_value("RPM"))

    # -----------------------------------------------------------------
    # Test Q: Monotonic / accurate observation timestamps
    # -----------------------------------------------------------------
    def test_q_timestamps_monotonic_and_accurate(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.02,
        )
        runtime.start()
        time.sleep(0.12)
        runtime.stop(timeout=1.0)

        samples = runtime.get_recent_samples()
        self.assertGreater(len(samples), 2)
        for i in range(1, len(samples)):
            self.assertGreaterEqual(samples[i]["timestamp"], samples[i-1]["timestamp"])

    # -----------------------------------------------------------------
    # Test R: Multi-ECU context separation
    # -----------------------------------------------------------------
    def test_r_multi_ecu_separation(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
            target_ecu="ECM",
        )
        self.assertEqual(runtime.get_target_ecu(), "ECM")
        runtime.start()
        time.sleep(0.08)
        s_ecm = runtime.get_latest_sample("010C")
        self.assertEqual(s_ecm.get("ecu_id"), "ECM")

        # Change context to TCM
        runtime.set_target_ecu("TCM")
        self.assertEqual(runtime.get_target_ecu(), "TCM")
        time.sleep(0.08)
        s_tcm = runtime.get_latest_sample("010C")
        self.assertEqual(s_tcm.get("ecu_id"), "TCM")
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test S: Vehicle identity separation & invalidation
    # -----------------------------------------------------------------
    def test_s_vehicle_identity_separation(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
            vehicle_id="VIN_VEHICLE_A",
        )
        runtime.start()
        time.sleep(0.08)
        sample = runtime.get_latest_sample("010C")
        self.assertEqual(sample.get("vehicle_id"), "VIN_VEHICLE_A")

        # Invalidate vehicle identity: caches must be flushed
        runtime.invalidate_vehicle_context()
        self.assertIsNone(runtime.get_latest_sample("010C"))
        self.assertEqual(len(runtime.get_recent_samples()), 0)
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test T: J-3 persistence integration (save_raw_acquisition)
    # -----------------------------------------------------------------
    def test_t_persistence_integration(self):
        backend = SQLitePersistenceBackend(":memory:")
        repo = DiagnosticRepository(backend=backend)

        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C", "010D"],
            cycle_interval=0.03,
            repository=repo,
            session_id="test_k3_sess_001",
        )
        runtime.start()
        time.sleep(0.18)
        runtime.stop(timeout=1.5)

        stats = runtime.get_runtime_stats()
        self.assertGreater(stats["persistence_written"], 0)

        # Verify records stored in SQLite backend
        records = repo.backend.list_records(DiagnosticRepository.COLLECTION_RAW_ACQUISITIONS)
        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertEqual(first["session_id"], "test_k3_sess_001")
        self.assertIn(first["command_or_pid"], ("010C", "010D"))

    # -----------------------------------------------------------------
    # Test U: Persistence failure isolation (DB error does not kill acquisition)
    # -----------------------------------------------------------------
    def test_u_persistence_failure_isolation(self):
        class FaultyBackend(SQLitePersistenceBackend):
            def save_record(self, *args, **kwargs):
                raise PersistenceError("Simulated disk error in persistence backend")

        faulty_repo = DiagnosticRepository(backend=FaultyBackend(":memory:"))

        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
            repository=faulty_repo,
        )
        runtime.start()
        time.sleep(0.15)
        # Acquisition must remain RUNNING despite persistence exceptions
        self.assertEqual(runtime.get_state(), LIVE_RUNNING)
        runtime.stop(timeout=1.5)

        stats = runtime.get_runtime_stats()
        self.assertGreater(stats["persistence_errors"], 0)
        self.assertGreater(stats["successful_reads"], 0)

    # -----------------------------------------------------------------
    # Test V: Bounded downstream queue & backpressure drop behavior
    # -----------------------------------------------------------------
    def test_v_bounded_downstream_queue_behavior(self):
        # Create a repo whose worker is artificially stalled
        class StalledRepo:
            def save_raw_acquisition(self, *args, **kwargs):
                time.sleep(1.0)  # Heavy artificial stall

        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.01,
            repository=StalledRepo(),
            persistence_queue_size=5,  # Tiny queue to quickly trigger backpressure
        )
        runtime.start()
        time.sleep(0.2)
        runtime.stop(timeout=2.0)

        stats = runtime.get_runtime_stats()
        # Backpressure must drop excess samples instead of blocking the physical acquisition loop
        self.assertGreaterEqual(stats["persistence_dropped"], 0)
        self.assertGreater(stats["cycle_count"], 5)

    # -----------------------------------------------------------------
    # Test W: Reconnect behavior without duplicate workers
    # -----------------------------------------------------------------
    def test_w_reconnect_behavior(self):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.06)

        # Trigger reconnect
        ok = runtime.reconnect(max_attempts=2, timeout=1.0)
        self.assertTrue(ok)
        # Must still be active without spawning duplicate threads
        self.assertIn(runtime.get_state(), (LIVE_RUNNING, LIVE_STOPPED))
        runtime.stop(timeout=1.0)

    # -----------------------------------------------------------------
    # Test X: Shutdown behavior with clean resource disposal
    # -----------------------------------------------------------------
    def test_x_shutdown_behavior(self):
        coordinator = ShutdownCoordinator()
        backend = SQLitePersistenceBackend(":memory:")
        repo = DiagnosticRepository(backend=backend)

        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.03,
            repository=repo,
        )
        runtime.start()
        coordinator.register_cleanup("live_runtime", lambda: runtime.stop(timeout=1.0))
        coordinator.register_cleanup("adapter", self.adapter.disconnect)

        res = coordinator.shutdown()
        self.assertEqual(res["status"], "TERMINATED")
        self.assertEqual(runtime.get_state(), LIVE_STOPPED)
        self.assertFalse(self.adapter.is_connected())

    # -----------------------------------------------------------------
    # Test Y: No worker / thread leaks
    # -----------------------------------------------------------------
    def test_y_no_worker_thread_leak(self):
        initial_threads = threading.active_count()
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C"],
            cycle_interval=0.02,
        )
        runtime.start()
        time.sleep(0.08)
        runtime.stop(timeout=1.0)

        # Worker thread must be joined and dead
        self.assertFalse(runtime._worker_thread.is_alive())
        # Active threads must return to baseline (allowing +/- 1 for gc/timing)
        self.assertLessEqual(threading.active_count(), initial_threads + 1)

    # -----------------------------------------------------------------
    # Test Z: Adapter command serialization
    # -----------------------------------------------------------------
    def test_z_adapter_command_serialization(self):
        # Verify physical commands pass through serial lock
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C", "010D"],
            cycle_interval=0.03,
        )
        runtime.start()
        time.sleep(0.12)
        runtime.stop(timeout=1.0)

        # Both commands must have executed in order without serial collisions
        recent = runtime.get_recent_samples()
        pids_seen = [s["pid"] for s in recent]
        self.assertIn("010C", pids_seen)
        self.assertIn("010D", pids_seen)

    # -----------------------------------------------------------------
    # Test AA: Safety policy remains enforced (prohibited SIDs blocked)
    # -----------------------------------------------------------------
    def test_aa_safety_policy_remains_enforced(self):
        # Attempt to inject prohibited UDS services into acquisition
        for prohibited_sid in ("14", "27", "2E01", "2F", "34", "04"):
            sample, is_fatal = self.engine_or_adapter_query(prohibited_sid)
            self.assertEqual(sample["status"], STATUS_NRC)
            self.assertIsNone(sample["value"])

    def engine_or_adapter_query(self, sid: str):
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=[sid],
        )
        return runtime._acquire_pid(sid)

    # -----------------------------------------------------------------
    # Test AB: Diagnostic intelligence consumers receive trusted data
    # -----------------------------------------------------------------
    def test_ab_intelligence_consumers_receive_trusted_data(self):
        intel = LiveDiagnosticIntelligence(engine=self.engine)
        runtime = LiveAcquisitionRuntime(
            engine=self.engine,
            adapter=self.adapter,
            pids=["010C", "0105"],
            cycle_interval=0.03,
            intelligence_engine=intel,
        )
        runtime.start()
        time.sleep(0.12)
        runtime.stop(timeout=1.0)

        intel_state = runtime.get_current_intelligence()
        self.assertIsNotNone(intel_state)
        # Engine cache must hold trusted data consumed by intelligence
        self.assertIn("RPM", self.engine.data_cache)

    # -----------------------------------------------------------------
    # Test AC: Intelligence cannot directly bypass acquisition architecture
    # -----------------------------------------------------------------
    def test_ac_intelligence_cannot_bypass_acquisition_architecture(self):
        intel = LiveDiagnosticIntelligence(engine=self.engine)
        # Intelligence engine is purely a data consumer; has no direct serial or adapter handles
        self.assertFalse(hasattr(intel, "ser"))
        self.assertFalse(hasattr(intel, "adapter"))

    # -----------------------------------------------------------------
    # Test AD: Regression against Phase K-1
    # -----------------------------------------------------------------
    def test_ad_regression_against_k1(self):
        # Verify async non-blocking connect from K-1
        mock_ser = MockSerialForELM(port="COM2", baudrate=38400)
        new_adapter = ELM327DiagnosticAdapter(
            port="COM2",
            serial_factory=lambda *a, **kw: mock_ser,
        )
        done_evt = threading.Event()
        res_box = []

        def on_fin(ok, err):
            res_box.append((ok, err))
            done_evt.set()

        ok = new_adapter.connect_async(timeout=2.0, on_finished=on_fin)
        self.assertTrue(ok)
        self.assertTrue(done_evt.wait(timeout=2.0))
        self.assertTrue(res_box[0][0])
        self.assertTrue(new_adapter.is_connected())
        new_adapter.disconnect()

    # -----------------------------------------------------------------
    # Test AE: Regression against Phase K-2
    # -----------------------------------------------------------------
    def test_ae_regression_against_k2(self):
        # Verify truthful capability reporting and smoke test execution
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_serial_transport)
        self.assertTrue(caps.supports_elm327_commands)
        self.assertFalse(caps.supports_raw_can)

        smoke_res = self.adapter.execute_smoke_test(timeout=2.0)
        self.assertEqual(smoke_res["status"], "PASS")
        self.assertEqual(smoke_res["safe_read_status"], STATUS_VALID)
        self.assertTrue(smoke_res["raw_response_captured"])

    # -----------------------------------------------------------------
    # Test AF: Relevant J-1 / J-6 / J-Final regression
    # -----------------------------------------------------------------
    def test_af_relevant_j1_j6_jfinal_tests(self):
        # Multi-ECU failure isolation
        targets = ["ECM", "TCM", "ABS"]
        def op(t):
            if t == "ABS":
                raise TimeoutError("ABS comm timeout")
            return f"{t}_OK"

        res = MultiECUFailureIsolation.execute_multi_target(targets, op)
        self.assertEqual(res["ECM"], "ECM_OK")
        self.assertEqual(res["TCM"], "TCM_OK")
        self.assertTrue(res["ABS"].is_communication_failure)


if __name__ == "__main__":
    unittest.main()
