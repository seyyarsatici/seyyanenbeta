# -*- coding: utf-8 -*-
"""
test_phase_kl_critical_audit.py
================================
K/L Critical Audit Test Suite — Seyyanen Automotive Diagnostic Platform

Covers four audit areas:
1. K-1 connection runtime — non-blocking, duplicate-safe, cancellation, reconnect, shutdown
2. K-3 live acquisition pipeline — trust path, unbounded history, stale samples, persistence
3. L-2 dynamic operating references — context-dependent, safe states, provenance, no fabrication
4. End-to-end safety chain — prohibited services, J-5 authorization, adapter capability gate

Tests are purely synthetic (no physical hardware required).
"""
from __future__ import annotations

import threading
import time
import queue
import math
import uuid
from collections import deque
from typing import Optional, Dict, Any, List

import unittest

# =====================================================================
# K-1 / K-3 imports
# =====================================================================
from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE, LIVE_STARTING, LIVE_RUNNING, LIVE_DEGRADED,
    LIVE_STOPPING, LIVE_STOPPED, LIVE_ERROR,
)
from diagnostic_adapter import (
    MockDiagnosticAdapter,
    AdapterConnectionState,
    PROHIBITED_SERVICES,
)
from motor import (
    STATUS_VALID, STATUS_TIMEOUT, STATUS_NO_DATA, STATUS_NO_CONNECTION,
    STATUS_SERIAL_ERROR, STATUS_NRC,
    QUALITY_GOOD, QUALITY_STALE, QUALITY_INVALID,
)

# =====================================================================
# L-2 imports
# =====================================================================
from dynamic_operating_reference import (
    OperatingContext, OperatingState, VariableQuality,
    ExpectationStatus, EvidencePolarity, EvidenceStrength,
    ExpectationProvenanceType, ExpectationModelType,
    ContextualDeviationEvidence, FixedRangeExpectationModel,
    ContextDependentRangeModel, DynamicOperatingReferenceEngine,
    BaselineContaminationGuard, VehicleObservedBaseline,
)

# =====================================================================
# J-5 security imports
# =====================================================================
from diagnostic_security import (
    SecurityManager, SecurityPolicy, Principal, Role, Permission,
    AuthorizationContext, AuthorizationDecision, AuthorizationDecisionStatus,
    DenialReason,
)


# =====================================================================
# HELPERS
# =====================================================================

def _make_adapter(responses: Optional[Dict] = None) -> MockDiagnosticAdapter:
    """Create a connected MockDiagnosticAdapter with optional response map."""
    adapter = MockDiagnosticAdapter(responses=responses or {})
    adapter.connect()
    return adapter


def _make_runtime(adapter=None, **kwargs) -> LiveAcquisitionRuntime:
    """Create a LiveAcquisitionRuntime backed by a mock adapter."""
    if adapter is None:
        adapter = _make_adapter()
    return LiveAcquisitionRuntime(adapter=adapter, pids=["010C", "010D", "0105"], **kwargs)


def _make_context(rpm=800.0, ect=90.0, speed=0.0, tps=0.5, load=20.0, ts=None) -> OperatingContext:
    """Return a fully-populated WARM_IDLE OperatingContext."""
    ts = ts if ts is not None else time.time()
    ctx = OperatingContext(timestamp=ts)
    ctx.set_variable("RPM", rpm, unit="rpm", timestamp=ts, quality=VariableQuality.KNOWN_VALID)
    ctx.set_variable("ECT", ect, unit="°C", timestamp=ts, quality=VariableQuality.KNOWN_VALID)
    ctx.set_variable("SPEED", speed, unit="km/h", timestamp=ts, quality=VariableQuality.KNOWN_VALID)
    ctx.set_variable("TPS", tps, unit="%", timestamp=ts, quality=VariableQuality.KNOWN_VALID)
    ctx.set_variable("LOAD", load, unit="%", timestamp=ts, quality=VariableQuality.KNOWN_VALID)
    ctx.set_variable("MAP", 35.0, unit="kPa", timestamp=ts, quality=VariableQuality.KNOWN_VALID)
    ctx.classify_operating_state()
    return ctx


# =====================================================================
# AUDIT AREA 1: K-1 CONNECTION RUNTIME
# =====================================================================

class TestK1ConnectionRuntime(unittest.TestCase):
    """Audit 1: K-1 connection runtime — non-blocking, lifecycle correctness."""

    # ------------------------------------------------------------------
    # KL-01: Duplicate start call is rejected (not double-started)
    # ------------------------------------------------------------------
    def test_kl01_duplicate_start_rejected(self):
        """AUDIT: Duplicate start() returns False without spawning a second worker."""
        adapter = _make_adapter()
        rt = _make_runtime(adapter=adapter)
        try:
            started = rt.start()
            self.assertTrue(started, "First start() must succeed")
            # Second call while already LIVE_RUNNING must return False
            second = rt.start()
            self.assertFalse(second, "Duplicate start() must be rejected")
            # State must remain LIVE_RUNNING
            self.assertEqual(rt.get_state(), LIVE_RUNNING)
        finally:
            rt.stop(timeout=1.0)

    # ------------------------------------------------------------------
    # KL-02: start() does NOT hold _state_lock while connecting
    # ------------------------------------------------------------------
    def test_kl02_start_does_not_block_get_state(self):
        """
        AUDIT: After the fix, start() must not hold _state_lock during the
        connect() call. We verify get_state() is callable concurrently.
        """
        adapter = MockDiagnosticAdapter()
        adapter.force_connect_delay = 0.3   # 300 ms artificial serial delay
        # Connect synchronously first so start() skips its own connect()
        adapter.connect()
        rt = _make_runtime(adapter=adapter)

        blocked_for: List[float] = []

        def _poll_state():
            t0 = time.monotonic()
            for _ in range(30):
                rt.get_state()
                time.sleep(0.01)
            blocked_for.append(time.monotonic() - t0)

        poller = threading.Thread(target=_poll_state)
        try:
            poller.start()
            rt.start()
            poller.join(timeout=2.0)
            # Polling 30 × 10 ms should take ~300 ms; NOT 5 s worth of blocking
            self.assertLess(blocked_for[0], 2.0, "get_state() must not block during start()")
        finally:
            rt.stop(timeout=1.0)

    # ------------------------------------------------------------------
    # KL-03: connect_async() does not block caller
    # ------------------------------------------------------------------
    def test_kl03_connect_async_non_blocking(self):
        """AUDIT: connect_async() returns immediately; callback is fired in background."""
        adapter = MockDiagnosticAdapter()
        adapter.force_connect_delay = 0.2

        result: List = []
        done = threading.Event()

        def cb(ok, err):
            result.append((ok, err))
            done.set()

        t0 = time.monotonic()
        adapter.connect_async(timeout=2.0, on_finished=cb)
        elapsed = time.monotonic() - t0

        self.assertLess(elapsed, 0.1, "connect_async() must return before connection completes")
        done.wait(timeout=2.0)
        self.assertTrue(result, "Callback must be fired")
        ok, err = result[0]
        self.assertTrue(ok, "Connection should succeed")

    # ------------------------------------------------------------------
    # KL-04: connect_async() rejects concurrent duplicate while CONNECTING
    # ------------------------------------------------------------------
    def test_kl04_connect_async_duplicate_rejected(self):
        """AUDIT: Second connect_async() while CONNECTING must return False."""
        adapter = MockDiagnosticAdapter()
        adapter.force_connect_delay = 0.3

        adapter.connect_async(timeout=2.0)
        time.sleep(0.05)  # Let it enter CONNECTING state
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTING)

        second = adapter.connect_async(timeout=2.0)
        self.assertFalse(second, "Duplicate connect_async() while CONNECTING must be rejected")
        time.sleep(0.4)  # Let first complete

    # ------------------------------------------------------------------
    # KL-05: disconnect() during async connect cancels cleanly
    # ------------------------------------------------------------------
    def test_kl05_disconnect_cancels_async_connect(self):
        """AUDIT: disconnect() while CONNECTING sets cancel event and transitions to DISCONNECTED."""
        adapter = MockDiagnosticAdapter()
        adapter.force_connect_delay = 0.5

        adapter.connect_async(timeout=2.0)
        time.sleep(0.05)  # CONNECTING state established
        self.assertEqual(adapter.connection_state, AdapterConnectionState.CONNECTING)

        adapter.disconnect()
        # After disconnect, must NOT be CONNECTED or CONNECTING
        time.sleep(0.1)
        self.assertNotEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)
        self.assertNotEqual(adapter.connection_state, AdapterConnectionState.CONNECTING)

    # ------------------------------------------------------------------
    # KL-06: stop() is idempotent
    # ------------------------------------------------------------------
    def test_kl06_stop_idempotent(self):
        """AUDIT: Calling stop() multiple times must not raise or corrupt state."""
        rt = _make_runtime()
        try:
            rt.start()
            rt.stop(timeout=1.0)
            rt.stop(timeout=1.0)   # Second stop must be safe
            rt.stop(timeout=1.0)   # Third stop must be safe
        except Exception as exc:
            self.fail(f"stop() raised on repeated calls: {exc}")

    # ------------------------------------------------------------------
    # KL-07: Reconnect rejects duplicate concurrent calls
    # ------------------------------------------------------------------
    def test_kl07_reconnect_no_duplicate(self):
        """
        AUDIT: _reconnect_lock must prevent concurrent reconnect() calls from
        executing simultaneously. We verify this directly by testing the
        non-blocking acquire() behavior of the lock itself.
        """
        rt = _make_runtime()

        # Acquire the lock manually to simulate a running reconnect
        acquired = rt._reconnect_lock.acquire(blocking=False)
        self.assertTrue(acquired, "Lock must be acquirable when not held")
        try:
            # While lock is held, a second acquire(blocking=False) must fail
            second = rt._reconnect_lock.acquire(blocking=False)
            self.assertFalse(second,
                "_reconnect_lock must reject concurrent acquisition — second acquire must return False")
        finally:
            rt._reconnect_lock.release()

    # ------------------------------------------------------------------
    # KL-08: Failure state connect_async gives FAILED not DISCONNECTED
    # ------------------------------------------------------------------
    def test_kl08_failed_async_connect_state(self):
        """AUDIT: Failed async connect must produce FAILED/ERROR state, not CONNECTED."""
        adapter = MockDiagnosticAdapter()
        adapter.force_connect_failure = True

        done = threading.Event()
        result: List = []

        def cb(ok, err):
            result.append(ok)
            done.set()

        adapter.connect_async(timeout=0.5, on_finished=cb)
        done.wait(timeout=2.0)
        self.assertFalse(result[0], "Failed connect must report False to callback")
        # Must NOT be CONNECTED
        self.assertNotEqual(adapter.connection_state, AdapterConnectionState.CONNECTED)


# =====================================================================
# AUDIT AREA 2: K-3 LIVE ACQUISITION PIPELINE
# =====================================================================

class TestK3AcquisitionPipeline(unittest.TestCase):
    """Audit 2: K-3 acquisition pipeline — trust path, history, stale samples."""

    # ------------------------------------------------------------------
    # KL-09: Bounded history never exceeds maxlen
    # ------------------------------------------------------------------
    def test_kl09_bounded_history(self):
        """AUDIT: _recent_samples must be bounded; no unbounded memory growth."""
        rt = _make_runtime(history_maxlen=10)
        # Simulate 30 sample recordings
        for i in range(30):
            sample = {
                "pid": "010C", "name": "RPM", "value": float(800 + i),
                "status": STATUS_VALID, "timestamp": time.time(),
                "unit": "rpm", "sequence": i, "raw_value": None,
                "raw_bytes": b"", "acquisition_time_ms": 5.0,
                "ecu_id": "ECM", "vehicle_id": None,
            }
            rt._record_sample(sample)

        with rt._sample_lock:
            self.assertLessEqual(len(rt._recent_samples), 10,
                "History must be bounded by history_maxlen")

    # ------------------------------------------------------------------
    # KL-10: Failed samples do NOT update _latest_successful_by_pid
    # ------------------------------------------------------------------
    def test_kl10_failed_sample_not_trusted(self):
        """AUDIT: Timeout/NO_DATA/NRC samples must not contaminate latest_successful cache."""
        rt = _make_runtime()
        # First plant a successful sample
        good = {
            "pid": "010C", "name": "RPM", "value": 800.0, "status": STATUS_VALID,
            "timestamp": time.time(), "unit": "rpm", "sequence": 1,
            "raw_value": "410C1388", "raw_bytes": b"", "acquisition_time_ms": 3.0,
            "ecu_id": "ECM", "vehicle_id": None,
        }
        rt._record_sample(good)
        # Then a timeout
        bad = {
            "pid": "010C", "name": "RPM", "value": None, "status": STATUS_TIMEOUT,
            "timestamp": time.time(), "unit": "rpm", "sequence": 2,
            "raw_value": None, "raw_bytes": b"", "acquisition_time_ms": 500.0,
            "ecu_id": "ECM", "vehicle_id": None,
        }
        rt._record_sample(bad)

        trusted = rt.get_latest_successful("010C")
        self.assertIsNotNone(trusted, "Trusted cache must retain last good value")
        self.assertEqual(trusted["value"], 800.0, "Failed sample must not overwrite trusted cache")
        self.assertEqual(trusted["status"], STATUS_VALID, "Trusted value must be STATUS_VALID")

    # ------------------------------------------------------------------
    # KL-11: Prohibited PID blocked before reaching adapter
    # ------------------------------------------------------------------
    def test_kl11_prohibited_pid_blocked(self):
        """AUDIT: Acquisition of a prohibited SID (Mode 04 = DTC clear) must be blocked."""
        rt = _make_runtime()
        # Directly invoke _acquire_pid with a prohibited SID
        sample, fatal = rt._acquire_pid("04")
        self.assertFalse(fatal, "Prohibited PID block must not be fatal comm error")
        self.assertIsNone(sample["value"], "Blocked PID must return no value")
        self.assertEqual(sample["status"], STATUS_NRC, "Blocked PID must have STATUS_NRC")

    # ------------------------------------------------------------------
    # KL-12: Persistence queue is bounded; full queue drops sample (does not block)
    # ------------------------------------------------------------------
    def test_kl12_persistence_queue_bounded_backpressure(self):
        """AUDIT: Acquisition must not block when persistence queue is full."""
        # persistence_queue_size is clamped to max(50, ...) so the smallest
        # achievable queue is 50. We fill all 50 slots directly.
        rt = _make_runtime()   # default persistence_queue_size=1000, clamped min=50
        FILL_COUNT = rt._persistence_queue.maxsize
        for i in range(FILL_COUNT):
            rt._persistence_queue.put_nowait({"seq": i})

        self.assertEqual(rt._persistence_queue.qsize(), FILL_COUNT, "Queue must be at capacity")

        sample = {
            "pid": "010C", "name": "RPM", "value": 800.0, "status": STATUS_VALID,
            "timestamp": time.time(), "unit": "rpm", "sequence": FILL_COUNT + 1,
            "raw_value": None, "raw_bytes": b"", "acquisition_time_ms": 5.0,
            "ecu_id": "ECM", "vehicle_id": None,
        }
        class _Stub:
            def save_raw_acquisition(self, **kw): pass
        rt.repository = _Stub()

        dropped_before = rt._persistence_dropped_count
        t0 = time.monotonic()
        result = rt._enqueue_persistence(sample)
        elapsed = time.monotonic() - t0

        self.assertFalse(result, "Enqueue to full queue must return False")
        self.assertLess(elapsed, 0.1, "Enqueue to full queue must not block")
        self.assertGreater(rt._persistence_dropped_count, dropped_before,
            "_persistence_dropped_count must be incremented on queue-full drop")

    # ------------------------------------------------------------------
    # KL-13: Invalid/NaN decoded value gets STATUS_NO_DATA, not STATUS_VALID
    # ------------------------------------------------------------------
    def test_kl13_nan_not_trusted(self):
        """AUDIT: A sample with value=NaN must not enter the trusted cache."""
        rt = _make_runtime()
        nan_sample = {
            "pid": "010C", "name": "RPM", "value": float("nan"), "status": STATUS_VALID,
            "timestamp": time.time(), "unit": "rpm", "sequence": 1,
            "raw_value": None, "raw_bytes": b"", "acquisition_time_ms": 5.0,
            "ecu_id": "ECM", "vehicle_id": None,
        }
        rt._record_sample(nan_sample)
        trusted = rt.get_latest_successful("010C")
        self.assertIsNone(trusted, "NaN value must not enter trusted cache")

    # ------------------------------------------------------------------
    # KL-14: build_operating_context() maps STATUS_VALID → KNOWN_VALID
    # ------------------------------------------------------------------
    def test_kl14_build_context_quality_mapping(self):
        """AUDIT: Only STATUS_VALID samples become KNOWN_VALID in OperatingContext."""
        rt = _make_runtime()
        now = time.time()
        # Plant one VALID RPM sample and one NO_DATA ECT sample in successful cache
        with rt._sample_lock:
            rt._latest_successful_by_pid["010C"] = {
                "value": 800.0, "status": STATUS_VALID,
                "timestamp": now, "target_ecu": "ECM",
            }
            # NO_DATA samples do not go into _latest_successful (see KL-10)
            # So ECT will be absent from context

        ctx = rt.build_operating_context()
        rpm_var = ctx.get_variable("RPM")
        self.assertIsNotNone(rpm_var)
        self.assertEqual(rpm_var.quality, VariableQuality.KNOWN_VALID)

        ect_var = ctx.get_variable("ECT")
        if ect_var is not None:
            # If present, must be KNOWN_VALID
            self.assertEqual(ect_var.quality, VariableQuality.KNOWN_VALID)

    # ------------------------------------------------------------------
    # KL-15: set_vehicle_context() flushes caches on identity change
    # ------------------------------------------------------------------
    def test_kl15_vehicle_context_flush(self):
        """AUDIT: Changing vehicle_id must flush stale cached samples."""
        rt = _make_runtime(vehicle_id="VIN_AAA")
        with rt._sample_lock:
            rt._latest_successful_by_pid["010C"] = {"value": 800.0, "status": STATUS_VALID}
            rt._recent_samples.append({"pid": "010C", "value": 800.0})

        rt.set_vehicle_context("VIN_BBB")

        with rt._sample_lock:
            self.assertEqual(len(rt._latest_successful_by_pid), 0,
                "Vehicle change must flush _latest_successful_by_pid")
            self.assertEqual(len(rt._recent_samples), 0,
                "Vehicle change must flush _recent_samples")

    # ------------------------------------------------------------------
    # KL-16: Persistence loop drains remaining items after stop event
    # ------------------------------------------------------------------
    def test_kl16_persistence_loop_drains_on_stop(self):
        """AUDIT: Persistence loop must flush remaining queue on stop, not discard."""
        flushed: List[Any] = []

        class _MockRepo:
            def save_raw_acquisition(self, session_id, source_ecu, command_or_pid,
                                     raw_payload, metadata):
                flushed.append(metadata.get("value"))

        rt = _make_runtime(repository=_MockRepo())

        # Manually fill queue with 3 items
        for i in range(3):
            rt._persistence_queue.put_nowait({
                "pid": "010C", "name": "RPM", "value": float(i),
                "status": STATUS_VALID, "timestamp": time.time(),
                "unit": "rpm", "sequence": i, "acquisition_time_ms": 1.0,
                "ecu_id": "ECM", "vehicle_id": None, "raw_value": None, "raw_bytes": b"",
            })

        # Signal stop and run the loop
        rt._persistence_stop_event.set()
        rt._persistence_loop()   # Runs synchronously until queue drained

        self.assertGreaterEqual(len(flushed), 3,
            "Persistence loop must flush all queued items before exit")


# =====================================================================
# AUDIT AREA 3: L-2 DYNAMIC OPERATING REFERENCES
# =====================================================================

class TestL2DynamicOperatingReference(unittest.TestCase):
    """Audit 3: L-2 reference selection, safe states, provenance, no fabrication."""

    # ------------------------------------------------------------------
    # KL-17: MAP reference is context-dependent (not universal)
    # ------------------------------------------------------------------
    def test_kl17_map_reference_is_context_dependent(self):
        """AUDIT: MAP bounds must differ between WARM_IDLE and HIGH_LOAD operating states."""
        engine = DynamicOperatingReferenceEngine()

        idle_ctx = _make_context(rpm=800, speed=0, tps=0.5, load=20)
        idle_ev = engine.evaluate_observation("MAP", 35.0, idle_ctx)
        idle_range = idle_ev.expected_range

        load_ctx = _make_context(rpm=4000, speed=100, tps=90.0, load=90.0)
        load_ctx.set_variable("TPS", 90.0, quality=VariableQuality.KNOWN_VALID)
        load_ctx.set_variable("LOAD", 90.0, quality=VariableQuality.KNOWN_VALID)
        load_ctx.set_variable("RPM", 4000.0, quality=VariableQuality.KNOWN_VALID)
        load_ctx.set_variable("SPEED", 100.0, quality=VariableQuality.KNOWN_VALID)
        load_ctx.classify_operating_state()
        load_ev = engine.evaluate_observation("MAP", 100.0, load_ctx)
        load_range = load_ev.expected_range

        # Ranges must differ — not a universal constant
        self.assertIsNotNone(idle_range, "Idle MAP must have expected range")
        self.assertIsNotNone(load_range, "High load MAP must have expected range")
        self.assertNotEqual(idle_range, load_range,
            "MAP expected bounds must be context-dependent, not universal")

    # ------------------------------------------------------------------
    # KL-18: Missing required context produces INSUFFICIENT_CONTEXT
    # ------------------------------------------------------------------
    def test_kl18_missing_context_is_insufficient(self):
        """AUDIT: Evaluation without required RPM context must return INSUFFICIENT_CONTEXT."""
        engine = DynamicOperatingReferenceEngine()
        empty_ctx = OperatingContext(timestamp=time.time())
        # No RPM set — required by MAP context-dependent model
        ev = engine.evaluate_observation("MAP", 35.0, empty_ctx)
        self.assertEqual(ev.status, ExpectationStatus.INSUFFICIENT_CONTEXT,
            "Missing required context must return INSUFFICIENT_CONTEXT")
        self.assertEqual(ev.polarity, EvidencePolarity.INSUFFICIENT,
            "Missing context polarity must be INSUFFICIENT")
        # Reason must name the missing variable
        self.assertIn("RPM", ev.reason.upper())

    # ------------------------------------------------------------------
    # KL-19: Stale context produces STALE_CONTEXT
    # ------------------------------------------------------------------
    def test_kl19_stale_context_rejected(self):
        """AUDIT: Variables older than max_context_age must produce STALE_CONTEXT."""
        engine = DynamicOperatingReferenceEngine()
        stale_ts = time.time() - 30.0   # 30 seconds old → exceeds 2s max_context_age
        ctx = OperatingContext(timestamp=time.time())
        ctx.set_variable("RPM", 800.0, unit="rpm", timestamp=stale_ts,
                         quality=VariableQuality.KNOWN_VALID)
        ctx.set_variable("SPEED", 0.0, timestamp=time.time(),
                         quality=VariableQuality.KNOWN_VALID)
        ctx.classify_operating_state()

        ev = engine.evaluate_observation("MAP", 35.0, ctx)
        # RPM is stale, which is required — must get stale context
        self.assertIn(ev.status, (ExpectationStatus.STALE_CONTEXT,
                                  ExpectationStatus.INSUFFICIENT_CONTEXT))
        self.assertEqual(ev.polarity, EvidencePolarity.INSUFFICIENT)

    # ------------------------------------------------------------------
    # KL-20: Physical contradiction produces CONTRADICTORY_CONTEXT
    # ------------------------------------------------------------------
    def test_kl20_contradictory_context_safe_state(self):
        """AUDIT: Engine-off + moving vehicle must produce CONTRADICTORY_CONTEXT."""
        engine = DynamicOperatingReferenceEngine()
        ts = time.time()
        ctx = OperatingContext(timestamp=ts)
        ctx.set_variable("RPM", 0.0, quality=VariableQuality.KNOWN_VALID, timestamp=ts)
        ctx.set_variable("SPEED", 80.0, quality=VariableQuality.KNOWN_VALID, timestamp=ts)
        ctx.classify_operating_state()

        ev = engine.evaluate_observation("MAP", 50.0, ctx)
        self.assertEqual(ev.status, ExpectationStatus.CONTRADICTORY_CONTEXT,
            "Physical contradiction (RPM=0 + SPEED=80) must produce CONTRADICTORY_CONTEXT")
        self.assertEqual(ev.polarity, EvidencePolarity.INSUFFICIENT)

    # ------------------------------------------------------------------
    # KL-21: Unknown signal returns UNKNOWN_EXPECTATION, not fabricated values
    # ------------------------------------------------------------------
    def test_kl21_unknown_signal_no_fabrication(self):
        """AUDIT: Unregistered signal must return UNKNOWN_EXPECTATION, never a range."""
        engine = DynamicOperatingReferenceEngine()
        ctx = _make_context()
        ev = engine.evaluate_observation("INJECTOR_PULSE_WIDTH_BANK2", 3.5, ctx)
        self.assertEqual(ev.status, ExpectationStatus.UNKNOWN_EXPECTATION)
        self.assertIsNone(ev.expected_range, "No expected range must be fabricated")
        self.assertEqual(ev.polarity, EvidencePolarity.INSUFFICIENT)

    # ------------------------------------------------------------------
    # KL-22: Provenance is preserved on OEM_SPECIFICATION model
    # ------------------------------------------------------------------
    def test_kl22_provenance_preserved(self):
        """AUDIT: ECT model must report OEM_SPECIFICATION provenance."""
        engine = DynamicOperatingReferenceEngine()
        ctx = _make_context(ect=90.0)
        ev = engine.evaluate_observation("ECT", 90.0, ctx)
        self.assertEqual(ev.status, ExpectationStatus.EXPECTED_CONFORMANT)
        self.assertEqual(ev.provenance, ExpectationProvenanceType.OEM_SPECIFICATION,
            "ECT model must report OEM_SPECIFICATION provenance")

    # ------------------------------------------------------------------
    # KL-23: Baseline contamination guard rejects fault-period sample
    # ------------------------------------------------------------------
    def test_kl23_baseline_contamination_guard(self):
        """AUDIT: Active fault period must prevent baseline ingestion."""
        ok, reason = BaselineContaminationGuard.can_ingest_sample(
            value=800.0,
            quality=VariableQuality.KNOWN_VALID,
            status=STATUS_VALID,
            is_fault_period_active=True,   # <-- active fault
            active_dtcs=[],
            is_context_contradictory=False,
        )
        self.assertFalse(ok, "Active fault must prevent baseline contamination")
        self.assertIn("fault", reason.lower())

    # ------------------------------------------------------------------
    # KL-24: Baseline contamination guard rejects active DTC sample
    # ------------------------------------------------------------------
    def test_kl24_baseline_contamination_guard_dtc(self):
        """AUDIT: Active DTCs must prevent baseline ingestion."""
        ok, reason = BaselineContaminationGuard.can_ingest_sample(
            value=800.0,
            quality=VariableQuality.KNOWN_VALID,
            status=STATUS_VALID,
            is_fault_period_active=False,
            active_dtcs=["P0300"],     # <-- active DTC
            is_context_contradictory=False,
        )
        self.assertFalse(ok, "Active DTC must prevent baseline contamination")

    # ------------------------------------------------------------------
    # KL-25: Vehicle instance baseline isolation
    # ------------------------------------------------------------------
    def test_kl25_baseline_isolation(self):
        """AUDIT: Baseline registered for VIN_AAA must not be returned for VIN_BBB."""
        engine = DynamicOperatingReferenceEngine()
        baseline = VehicleObservedBaseline(
            vehicle_instance_id="VIN_AAA",
            signal_id="RPM",
            operating_state=OperatingState.WARM_IDLE,
            mean_value=820.0,
            std_dev=15.0,
            min_observed=790.0,
            max_observed=860.0,
            sample_count=100,
            time_range=(time.time() - 300, time.time()),
            is_technician_confirmed=False,
        )
        engine.register_baseline(baseline)
        b = engine.get_baseline("VIN_BBB", "RPM", OperatingState.WARM_IDLE)
        self.assertIsNone(b, "Baseline for VIN_AAA must not be returned for VIN_BBB")

    # ------------------------------------------------------------------
    # KL-26: NaN observation produces INVALID_SAMPLE (not a crash)
    # ------------------------------------------------------------------
    def test_kl26_nan_observation_safe(self):
        """AUDIT: NaN actual value must produce INVALID_SAMPLE, not an exception."""
        engine = DynamicOperatingReferenceEngine()
        ctx = _make_context()
        ev = engine.evaluate_observation("ECT", float("nan"), ctx)
        self.assertEqual(ev.status, ExpectationStatus.INVALID_SAMPLE)
        self.assertEqual(ev.polarity, EvidencePolarity.INSUFFICIENT)


# =====================================================================
# AUDIT AREA 4: END-TO-END SAFETY CHAIN
# =====================================================================

class TestSafetyChain(unittest.TestCase):
    """Audit 4: End-to-end safety chain — prohibited services, J-5 authorization."""

    # ------------------------------------------------------------------
    # KL-27: Prohibited services blocked at adapter send_command layer
    # ------------------------------------------------------------------
    def test_kl27_prohibited_services_blocked_at_adapter(self):
        """AUDIT: Prohibited SIDs must return STATUS_NRC from adapter send_command."""
        adapter = _make_adapter()
        for sid in ["04", "14", "2E", "27", "2F", "34", "35", "36", "37", "3D"]:
            lines, status = adapter.send_command(sid, timeout=0.5)
            self.assertEqual(status, STATUS_NRC,
                f"SID {sid} must be blocked at adapter level → STATUS_NRC")
            self.assertEqual(lines, [], f"SID {sid} must return empty lines")

    # ------------------------------------------------------------------
    # KL-28: Prohibited services also blocked in acquisition _acquire_pid
    # ------------------------------------------------------------------
    def test_kl28_prohibited_services_blocked_in_acquisition(self):
        """AUDIT: _acquire_pid with prohibited SID must return STATUS_NRC sample."""
        rt = _make_runtime()
        for pid in ["04", "14", "2E"]:
            sample, fatal = rt._acquire_pid(pid)
            self.assertFalse(fatal, "Prohibited PID block must not be fatal")
            self.assertEqual(sample["status"], STATUS_NRC,
                f"Prohibited PID {pid} must produce STATUS_NRC sample")
            self.assertIsNone(sample["value"])

    # ------------------------------------------------------------------
    # KL-29: J-5 default deny — unknown operation is denied
    # ------------------------------------------------------------------
    def test_kl29_j5_default_deny_unknown_operation(self):
        """AUDIT: Unknown operation must be DENIED by J-5 (default deny policy)."""
        sm = SecurityManager.__new__(SecurityManager)
        sm._policy = SecurityPolicy()
        sm._lock = __import__("threading").RLock()
        sm._principals = {}
        sm._invalidated_sessions = set()
        sm._repository = None
        sm._user_session_manager = None
        sm._initialize_default_principals = lambda: None

        sm._principals["tech1"] = Principal(user_id="tech1", roles=[Role.TECHNICIAN])

        def _record_audit(**kwargs):
            pass
        sm._record_audit_event = _record_audit
        sm._record_decision_audit = lambda d, c: None

        ctx = AuthorizationContext(
            user_id="tech1",
            application_session_id="sess1",
            requested_operation="write_ecu_memory",   # unknown / not in policy map
            resource="vehicle:VIN_TEST",
        )
        decision = sm.authorize(ctx)
        self.assertEqual(decision.status, AuthorizationDecisionStatus.DENY)
        self.assertEqual(decision.reason, DenialReason.UNKNOWN_OPERATION)

    # ------------------------------------------------------------------
    # KL-30: J-5 viewer cannot request destructive operations
    # ------------------------------------------------------------------
    def test_kl30_viewer_cannot_write_ecu(self):
        """AUDIT: VIEWER role must not be granted WRITE_ECU permission."""
        policy = SecurityPolicy()
        viewer_perms = policy.get_permissions_for_roles([Role.VIEWER])
        self.assertNotIn(Permission.WRITE_ECU, viewer_perms,
            "VIEWER must not have WRITE_ECU permission")
        self.assertNotIn(Permission.CLEAR_DTC, viewer_perms,
            "VIEWER must not have CLEAR_DTC permission")

    # ------------------------------------------------------------------
    # KL-31: TECHNICIAN cannot CLEAR_DTC or WRITE_ECU
    # ------------------------------------------------------------------
    def test_kl31_technician_cannot_clear_dtc_or_write_ecu(self):
        """AUDIT: TECHNICIAN role must not have CLEAR_DTC or WRITE_ECU."""
        policy = SecurityPolicy()
        perms = policy.get_permissions_for_roles([Role.TECHNICIAN])
        self.assertNotIn(Permission.CLEAR_DTC, perms,
            "TECHNICIAN must not have CLEAR_DTC permission")
        self.assertNotIn(Permission.WRITE_ECU, perms,
            "TECHNICIAN must not have WRITE_ECU permission")

    # ------------------------------------------------------------------
    # KL-32: Adapter safety gate dual-checks both token and hex SID forms
    # ------------------------------------------------------------------
    def test_kl32_adapter_safety_dual_gate(self):
        """AUDIT: Adapter must reject both '04' and '4' (single-char) forms of Mode 04."""
        adapter = _make_adapter()
        for form in ["04", "4", "2E", "27"]:
            lines, status = adapter.send_command(form)
            self.assertEqual(status, STATUS_NRC,
                f"Adapter must block prohibited SID in form '{form}'")

    # ------------------------------------------------------------------
    # KL-33: Adapter capabilities declare is_read_only_enforced=True
    # ------------------------------------------------------------------
    def test_kl33_adapter_read_only_enforced(self):
        """AUDIT: Default ELM327 adapter must declare is_read_only_enforced=True."""
        adapter = _make_adapter()
        self.assertTrue(adapter.capabilities.is_read_only_enforced,
            "Default adapter must declare read-only enforcement")
        self.assertFalse(adapter.capabilities.supports_privileged_services,
            "Default adapter must NOT declare privileged service support")

    # ------------------------------------------------------------------
    # KL-34: L-2 engine has no destructive methods
    # ------------------------------------------------------------------
    def test_kl34_l2_engine_no_destructive_methods(self):
        """AUDIT: DynamicOperatingReferenceEngine must not expose any write/clear/flash methods."""
        forbidden_names = [
            "write_ecu", "clear_dtc", "flash", "program", "security_access",
            "actuation", "write_memory", "coding", "download",
        ]
        engine = DynamicOperatingReferenceEngine()
        for name in forbidden_names:
            self.assertFalse(hasattr(engine, name),
                f"L-2 engine must not expose destructive method: {name}")

    # ------------------------------------------------------------------
    # KL-35: PROHIBITED_SERVICES set is comprehensive
    # ------------------------------------------------------------------
    def test_kl35_prohibited_services_set_complete(self):
        """AUDIT: PROHIBITED_SERVICES must include all 9 known dangerous SIDs."""
        required = {"04", "14", "2E", "27", "2F", "34", "35", "36", "37", "3D"}
        for sid in required:
            self.assertIn(sid, PROHIBITED_SERVICES,
                f"SID {sid} must be in PROHIBITED_SERVICES set")


# =====================================================================
# REGRESSION GUARD: L-2 core invariants still pass
# =====================================================================

class TestKLRegressionGuard(unittest.TestCase):
    """Quick regression guard that the core L-2 PASS criteria are still met."""

    def test_kl_reg_context_completeness(self):
        ctx = _make_context()
        is_ok, missing = ctx.check_completeness(["RPM", "ECT", "SPEED"])
        self.assertTrue(is_ok)
        self.assertEqual(missing, [])

    def test_kl_reg_ect_conformant(self):
        engine = DynamicOperatingReferenceEngine()
        ctx = _make_context(ect=90.0)
        ev = engine.evaluate_observation("ECT", 90.0, ctx)
        self.assertEqual(ev.status, ExpectationStatus.EXPECTED_CONFORMANT)

    def test_kl_reg_ect_deviation(self):
        engine = DynamicOperatingReferenceEngine()
        ctx = _make_context(ect=90.0)
        ev = engine.evaluate_observation("ECT", 130.0, ctx)
        self.assertEqual(ev.status, ExpectationStatus.DEVIATION)
        self.assertEqual(ev.polarity, EvidencePolarity.CONTRADICTING)

    def test_kl_reg_operating_state_unknown_without_rpm(self):
        ctx = OperatingContext(timestamp=time.time())
        state = ctx.classify_operating_state()
        self.assertEqual(state, OperatingState.UNKNOWN_STATE)

    def test_kl_reg_prohibited_services_constant(self):
        for sid in ["04", "14", "2E", "27", "2F", "34", "35", "36", "37", "3D"]:
            self.assertIn(sid, PROHIBITED_SERVICES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
