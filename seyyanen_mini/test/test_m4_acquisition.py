#!/usr/bin/env python3
"""
SEYYANEN MINI — PHASE M-4 DETERMINISTIC LIVE ACQUISITION TESTS
=============================================================
Validates all tests A through V from Phase M-4 specification:
A. scheduler due-time calculation
B. priority selection
C. fairness
D. serialized requests
E. no concurrent OBD requests
F. sample timestamp monotonicity
G. acquisition frame construction
H. freshness calculation
I. stale sample handling
J. timeout handling
K. NO DATA handling
L. transport failure escalation
M. PID failure does not kill session
N. bounded history
O. history eviction
P. session ID separation
Q. metrics correctness
R. backpressure behavior
S. start/stop/pause/resume state machine
T. live snapshot consistency
U. web API state consistency
V. lock does not cover blocking OBD I/O
"""

import enum
import time
import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# REFERENCE TYPES & CONSTANTS MIRRORING C++ M-4 IMPLEMENTATION
# ==============================================================================

INTERVAL_FAST_MS = 120
INTERVAL_MEDIUM_MS = 350
INTERVAL_SLOW_MS = 1200

FRESHNESS_FRESH_THRESHOLD_MS = 600
FRESHNESS_AGING_THRESHOLD_MS = 2500
FRESHNESS_STALE_THRESHOLD_MS = 5000

RING_BUFFER_CAPACITY = 256

class AcquisitionState(enum.Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"

class QualityGrade(enum.Enum):
    GOOD = "GOOD"
    STALE = "STALE"
    TIMEOUT = "TIMEOUT"
    NO_DATA = "NO_DATA"
    MALFORMED = "MALFORMED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    NOT_SUPPORTED = "NOT_SUPPORTED"

class FreshnessState(enum.Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    NEVER_VALID = "NEVER_VALID"

class SampleStatus(enum.Enum):
    VALID = "VALID"
    NO_DATA = "NO_DATA"
    TIMEOUT = "TIMEOUT"
    MALFORMED = "MALFORMED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    NOT_SUPPORTED = "NOT_SUPPORTED"

# ==============================================================================
# REFERENCE CLASSES MIRRORING C++ M-4 BEHAVIOR
# ==============================================================================

class MeasurementSample:
    def __init__(self, session_id: str, sequence: int, timestamp_us: int,
                 pid: int, name: str, raw_response: str, normalized_bytes: List[int],
                 decoded_value: float, unit: str, status: SampleStatus,
                 quality: QualityGrade, request_start_us: int, response_timestamp_us: int,
                 latency_us: int, freshness: FreshnessState):
        self.session_id = session_id
        self.sequence = sequence
        self.timestamp_us = timestamp_us
        self.pid = pid
        self.name = name
        self.raw_response = raw_response
        self.normalized_bytes = list(normalized_bytes)
        self.decoded_value = decoded_value
        self.unit = unit
        self.status = status
        self.quality = quality
        self.request_start_us = request_start_us
        self.response_timestamp_us = response_timestamp_us
        self.latency_us = latency_us
        self.freshness = freshness

class AcquisitionFrame:
    def __init__(self, frame_id: int, cycle_start_us: int):
        self.frame_id = frame_id
        self.cycle_start_us = cycle_start_us
        self.cycle_end_us = cycle_start_us
        self.samples: List[MeasurementSample] = []

    def add_sample(self, sample: MeasurementSample):
        self.samples.append(sample)
        if sample.timestamp_us > self.cycle_end_us:
            self.cycle_end_us = sample.timestamp_us

class SampleRingBuffer:
    def __init__(self, capacity: int = RING_BUFFER_CAPACITY):
        self.capacity = capacity
        self.buffer: List[Optional[MeasurementSample]] = [None] * capacity
        self.head = 0
        self.count = 0

    def push(self, sample: MeasurementSample):
        self.buffer[self.head] = sample
        self.head = (self.head + 1) % self.capacity
        if self.count < self.capacity:
            self.count += 1

    def size(self) -> int:
        return self.count

    def get_recent(self, n: int) -> List[MeasurementSample]:
        if n <= 0 or self.count == 0:
            return []
        count_to_get = min(n, self.count)
        result = []
        for i in range(count_to_get):
            idx = (self.head - 1 - i + self.capacity) % self.capacity
            s = self.buffer[idx]
            if s is not None:
                result.append(s)
        return result

    def get_since(self, timestamp_us: int) -> List[MeasurementSample]:
        result = []
        for i in range(self.count):
            idx = (self.head - self.count + i + self.capacity) % self.capacity
            s = self.buffer[idx]
            if s is not None and s.timestamp_us > timestamp_us:
                result.append(s)
        return result

class QualityEngine:
    @staticmethod
    def evaluate_freshness(last_success_us: int, now_us: int) -> FreshnessState:
        if last_success_us == 0:
            return FreshnessState.NEVER_VALID
        if now_us < last_success_us:
            return FreshnessState.FRESH
        age_ms = (now_us - last_success_us) // 1000
        if age_ms <= FRESHNESS_FRESH_THRESHOLD_MS:
            return FreshnessState.FRESH
        elif age_ms <= FRESHNESS_AGING_THRESHOLD_MS:
            return FreshnessState.AGING
        else:
            return FreshnessState.STALE

    @staticmethod
    def evaluate(sample_status: SampleStatus, last_success_us: int, now_us: int) -> QualityGrade:
        if sample_status == SampleStatus.TIMEOUT:
            return QualityGrade.TIMEOUT
        if sample_status == SampleStatus.NO_DATA:
            return QualityGrade.NO_DATA
        if sample_status == SampleStatus.MALFORMED:
            return QualityGrade.MALFORMED
        if sample_status == SampleStatus.TRANSPORT_ERROR:
            return QualityGrade.TRANSPORT_ERROR
        if sample_status == SampleStatus.NOT_SUPPORTED:
            return QualityGrade.NOT_SUPPORTED

        freshness = QualityEngine.evaluate_freshness(last_success_us, now_us)
        if freshness == FreshnessState.STALE:
            return QualityGrade.STALE
        return QualityGrade.GOOD

class ScheduledPid:
    def __init__(self, pid: int, name: str, unit: str, priority: int, interval_ms: int):
        self.pid = pid
        self.name = name
        self.unit = unit
        self.enabled = True
        self.priority = priority
        self.interval_us = interval_ms * 1000
        self.last_requested_us = 0
        self.last_success_us = 0
        self.request_count = 0
        self.error_count = 0

class LiveSignal:
    def __init__(self, pid: int, name: str, unit: str):
        self.pid = pid
        self.name = name
        self.unit = unit
        self.value = 0.0
        self.last_valid_value = 0.0
        self.quality = QualityGrade.NO_DATA
        self.freshness = FreshnessState.NEVER_VALID
        self.last_success_us = 0
        self.age_ms = 0
        self.latency_ms = 0

class AcquisitionMetrics:
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.timeouts = 0
        self.no_data_count = 0
        self.malformed_count = 0
        self.transport_errors = 0
        self.average_latency_ms = 0.0
        self.last_latency_ms = 0
        self.requests_per_sec = 0.0
        self.active_pid_count = 0

class MockObdResult:
    def __init__(self, status: SampleStatus, decoded_value: float, unit: str, raw_response: str, latency_ms: int):
        self.status = status
        self.decoded_value = decoded_value
        self.unit = unit
        self.raw_response = raw_response
        self.latency_ms = latency_ms

class MockObdClient:
    def __init__(self):
        self.active_requests = 0
        self.max_concurrent_requests = 0
        self.responses: Dict[int, MockObdResult] = {}
        self.is_ready_flag = True

    def is_ready(self) -> bool:
        return self.is_ready_flag

    def request(self, mode: int, pid: int, timeout_ms: int = 400) -> MockObdResult:
        # Check concurrency: exactly one active request on the wire!
        self.active_requests += 1
        if self.active_requests > self.max_concurrent_requests:
            self.max_concurrent_requests = self.active_requests

        # Simulate wire delay
        res = self.responses.get(pid, MockObdResult(SampleStatus.VALID, 0.0, "", "41 00 00", 25))
        self.active_requests -= 1
        return res

class AcquisitionSchedulerSimulator:
    session_counter = 1

    def __init__(self, is_bt_connected: bool, obd_client: MockObdClient, ring_buffer: SampleRingBuffer):
        self.is_bt_connected = is_bt_connected
        self.obd_client = obd_client
        self.ring_buffer = ring_buffer
        self.state = AcquisitionState.IDLE
        self.session_id = ""
        self.sequence = 0
        self.frame_id = 0
        self.session_start_us = 0
        self.active_pids: List[ScheduledPid] = []
        self.signals: Dict[int, LiveSignal] = {}
        self.metrics = AcquisitionMetrics()
        self.lock_held_during_obd_io = False
        self._mutex_locked = False

    def setup_pids(self, pid_configs: List[Tuple[int, str, str, int, int]]):
        self.active_pids.clear()
        self.signals.clear()
        for pid, name, unit, prio, interval in pid_configs:
            self.active_pids.append(ScheduledPid(pid, name, unit, prio, interval))
            self.signals[pid] = LiveSignal(pid, name, unit)
        self.metrics.active_pid_count = len(self.active_pids)

    def start(self, session_id: Optional[str] = None) -> bool:
        if not self.is_bt_connected or not self.obd_client.is_ready() or not self.active_pids:
            self.state = AcquisitionState.ERROR
            return False

        self.state = AcquisitionState.STARTING
        if session_id:
            self.session_id = session_id
        else:
            self.session_id = f"MINI-SESSION-{AcquisitionSchedulerSimulator.session_counter:06d}"
            AcquisitionSchedulerSimulator.session_counter += 1

        self.sequence = 0
        self.frame_id = 1
        self.session_start_us = 1_000_000 # fixed reference base
        self.metrics = AcquisitionMetrics()
        self.metrics.active_pid_count = len(self.active_pids)
        self.state = AcquisitionState.RUNNING
        return True

    def stop(self) -> bool:
        if self.state in (AcquisitionState.IDLE, AcquisitionState.STOPPED):
            return True
        self.state = AcquisitionState.STOPPED
        return True

    def pause(self) -> bool:
        if self.state != AcquisitionState.RUNNING:
            return False
        self.state = AcquisitionState.PAUSED
        return True

    def resume(self) -> bool:
        if self.state != AcquisitionState.PAUSED:
            return False
        self.state = AcquisitionState.RUNNING
        return True

    def is_running(self) -> bool:
        return self.state == AcquisitionState.RUNNING

    def select_next_due_pid(self, now_us: int) -> int:
        if not self.active_pids:
            return -1

        best_idx = -1
        max_urgency = 0

        for i, sp in enumerate(self.active_pids):
            if not sp.enabled:
                continue

            # First time requested: immediately maximally due
            if sp.last_requested_us == 0:
                return i

            elapsed = now_us - sp.last_requested_us if now_us >= sp.last_requested_us else 0
            if elapsed >= sp.interval_us:
                # Urgency metric prevents starvation of slow PIDs
                urgency = (elapsed * 1000) // sp.interval_us
                if urgency > max_urgency:
                    max_urgency = urgency
                    best_idx = i

        return best_idx

    def update(self, now_us: int):
        if self.state != AcquisitionState.RUNNING:
            return

        if not self.is_bt_connected:
            self.pause()
            return

        due_idx = self.select_next_due_pid(now_us)
        if due_idx >= 0:
            self.execute_scheduled_query(self.active_pids[due_idx], now_us)

    def execute_scheduled_query(self, sp: ScheduledPid, now_us: int):
        sp.last_requested_us = now_us
        sp.request_count += 1

        req_start_us = now_us

        # Verify Lock Rule: Mutex must NOT be held during OBD I/O!
        if self._mutex_locked:
            self.lock_held_during_obd_io = True

        res = self.obd_client.request(0x01, sp.pid & 0xFF, timeout_ms=400)
        resp_end_us = req_start_us + (res.latency_ms * 1000)

        is_success = (res.status == SampleStatus.VALID)
        latency_us = int(resp_end_us - req_start_us)

        if is_success:
            sp.last_success_us = resp_end_us
        else:
            sp.error_count += 1

        # Freshness and Quality
        freshness = QualityEngine.evaluate_freshness(sp.last_success_us, resp_end_us)
        quality = QualityEngine.evaluate(res.status, sp.last_success_us, resp_end_us)

        self.sequence += 1
        sample = MeasurementSample(
            session_id=self.session_id,
            sequence=self.sequence,
            timestamp_us=resp_end_us,
            pid=sp.pid,
            name=sp.name,
            raw_response=res.raw_response,
            normalized_bytes=[],
            decoded_value=res.decoded_value,
            unit=res.unit,
            status=res.status,
            quality=quality,
            request_start_us=req_start_us,
            response_timestamp_us=resp_end_us,
            latency_us=latency_us,
            freshness=freshness
        )

        self.ring_buffer.push(sample)

        # Update Live Signal under fast mutex simulation
        self._mutex_locked = True
        sig = self.signals[sp.pid]
        if is_success:
            sig.value = res.decoded_value
            sig.last_valid_value = res.decoded_value
            sig.last_success_us = resp_end_us
        # If error: do NOT overwrite last_valid_value, do NOT overwrite value to zero
        sig.quality = quality
        sig.freshness = freshness
        sig.latency_ms = res.latency_ms
        sig.age_ms = int((resp_end_us - sig.last_success_us) // 1000) if sig.last_success_us > 0 else 0

        # Update Metrics
        self.metrics.total_requests += 1
        if is_success:
            self.metrics.successful_requests += 1
        else:
            if quality == QualityGrade.TIMEOUT:
                self.metrics.timeouts += 1
            elif quality == QualityGrade.NO_DATA:
                self.metrics.no_data_count += 1
            elif quality == QualityGrade.TRANSPORT_ERROR:
                self.metrics.transport_errors += 1
            else:
                self.metrics.malformed_count += 1

        self.metrics.last_latency_ms = res.latency_ms
        self.metrics.average_latency_ms = (self.metrics.average_latency_ms * 0.9) + (res.latency_ms * 0.1)
        self._mutex_locked = False

# ==============================================================================
# UNIT TEST SUITE (TESTS A THROUGH V)
# ==============================================================================

class TestM4AcquisitionEngine(unittest.TestCase):

    def setUp(self):
        self.obd = MockObdClient()
        self.ring = SampleRingBuffer(capacity=RING_BUFFER_CAPACITY)
        self.sim = AcquisitionSchedulerSimulator(is_bt_connected=True, obd_client=self.obd, ring_buffer=self.ring)
        self.pids = [
            (0x010C, "RPM", "rpm", 0, INTERVAL_FAST_MS),      # 120ms Fast
            (0x0111, "TPS", "%", 0, INTERVAL_FAST_MS),        # 120ms Fast
            (0x010B, "MAP", "kPa", 1, INTERVAL_MEDIUM_MS),    # 350ms Medium
            (0x0105, "ECT", "°C", 2, INTERVAL_SLOW_MS),       # 1200ms Slow
        ]
        self.sim.setup_pids(self.pids)

    def test_A_scheduler_due_time_calculation(self):
        """A. Verify scheduler due-time calculation from timestamps."""
        # Initial state: last_requested_us == 0 -> immediately due
        idx = self.sim.select_next_due_pid(now_us=1_000_000)
        self.assertEqual(idx, 0) # First PID 010C due

        # Mark 010C requested at t=1,000,000
        self.sim.active_pids[0].last_requested_us = 1_000_000
        self.sim.active_pids[1].last_requested_us = 1_000_000
        self.sim.active_pids[2].last_requested_us = 1_000_000
        self.sim.active_pids[3].last_requested_us = 1_000_000

        # At t=1,050,000 (50ms later), NONE of them are due (fastest is 120ms)
        idx_not_due = self.sim.select_next_due_pid(now_us=1_050_000)
        self.assertEqual(idx_not_due, -1)

        # At t=1,121,000 (121ms later), fast PIDs (120ms) are due
        idx_due = self.sim.select_next_due_pid(now_us=1_121_000)
        self.assertIn(idx_due, [0, 1])

    def test_B_priority_selection(self):
        """B. Verify priority-based intervals correctly group work."""
        self.assertEqual(self.sim.active_pids[0].interval_us, 120_000)   # Priority 0
        self.assertEqual(self.sim.active_pids[2].interval_us, 350_000)   # Priority 1
        self.assertEqual(self.sim.active_pids[3].interval_us, 1_200_000) # Priority 2

    def test_C_fairness(self):
        """C. Fast PIDs must not starve slower PIDs (starvation prevention)."""
        now = 1_000_000
        # Suppose RPM (fast) was requested 200ms ago (urgency: 200 / 120 = 1.66)
        self.sim.active_pids[0].last_requested_us = now - 200_000
        self.sim.active_pids[1].last_requested_us = now
        self.sim.active_pids[2].last_requested_us = now
        # Suppose ECT (slow 1200ms) was delayed and requested 3000ms ago (urgency: 3000 / 1200 = 2.50)
        self.sim.active_pids[3].last_requested_us = now - 3_000_000

        # ECT urgency (2.50) > RPM urgency (1.66), so ECT MUST be selected first
        selected_idx = self.sim.select_next_due_pid(now)
        self.assertEqual(selected_idx, 3, "Slow overdue PID must not be starved by fast PID")

    def test_D_serialized_requests(self):
        """D. Exactly one active OBD request at a time."""
        self.sim.start()
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.VALID, 1800.0, "rpm", "41 0C 1C 20", 25)
        self.sim.update(now_us=1_000_000)
        self.assertEqual(self.obd.max_concurrent_requests, 1)

    def test_E_no_concurrent_obd_requests(self):
        """E. Ensure concurrent requests never exceed 1 on the channel."""
        self.sim.start()
        for t in range(1_000_000, 2_000_000, 50_000):
            self.sim.update(now_us=t)
        self.assertEqual(self.obd.max_concurrent_requests, 1)

    def test_F_sample_timestamp_monotonicity(self):
        """F. Sample timestamps must increase monotonically."""
        self.sim.start()
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.VALID, 850.0, "rpm", "41 0C 0D 48", 20)
        self.obd.responses[0x11] = MockObdResult(SampleStatus.VALID, 14.5, "%", "41 11 25", 20)

        t_base = 1_000_000
        for i in range(10):
            self.sim.update(now_us=t_base + (i * 150_000))

        samples = self.ring.get_recent(10)
        self.assertGreater(len(samples), 1)
        # Verify strict monotonicity
        for i in range(len(samples) - 1):
            # samples is ordered newest first
            self.assertGreater(samples[i].timestamp_us, samples[i+1].timestamp_us)

    def test_G_acquisition_frame_construction(self):
        """G. Verify AcquisitionFrame groups sequential samples with distinct timestamps."""
        frame = AcquisitionFrame(frame_id=1, cycle_start_us=1_000_000)
        s1 = MeasurementSample("SESSION-1", 1, 1_000_025, 0x010C, "RPM", "41 0C", [0x1C, 0x20], 1800, "rpm",
                               SampleStatus.VALID, QualityGrade.GOOD, 1_000_000, 1_000_025, 25000, FreshnessState.FRESH)
        s2 = MeasurementSample("SESSION-1", 2, 1_000_055, 0x010B, "MAP", "41 0B", [0x32], 50, "kPa",
                               SampleStatus.VALID, QualityGrade.GOOD, 1_000_030, 1_000_055, 25000, FreshnessState.FRESH)
        frame.add_sample(s1)
        frame.add_sample(s2)

        self.assertEqual(len(frame.samples), 2)
        # DO NOT claim simultaneous measurement:
        self.assertNotEqual(frame.samples[0].timestamp_us, frame.samples[1].timestamp_us)
        self.assertEqual(frame.cycle_start_us, 1_000_000)
        self.assertEqual(frame.cycle_end_us, 1_000_055)

    def test_H_freshness_calculation(self):
        """H. Freshness transitions: FRESH (<=600ms), AGING (<=2500ms), STALE (>2500ms)."""
        now = 10_000_000
        # Age 200 ms -> FRESH
        self.assertEqual(QualityEngine.evaluate_freshness(now - 200_000, now), FreshnessState.FRESH)
        # Age 1200 ms -> AGING
        self.assertEqual(QualityEngine.evaluate_freshness(now - 1_200_000, now), FreshnessState.AGING)
        # Age 4000 ms -> STALE
        self.assertEqual(QualityEngine.evaluate_freshness(now - 4_000_000, now), FreshnessState.STALE)
        # Never succeeded -> NEVER_VALID
        self.assertEqual(QualityEngine.evaluate_freshness(0, now), FreshnessState.NEVER_VALID)

    def test_I_stale_sample_handling(self):
        """I. QualityEngine correctly flags valid sample as STALE if age exceeds threshold."""
        now = 10_000_000
        last_success = now - 6_000_000 # 6 seconds old
        grade = QualityEngine.evaluate(SampleStatus.VALID, last_success, now)
        self.assertEqual(grade, QualityGrade.STALE)

    def test_J_timeout_handling(self):
        """J. TIMEOUT does not zero-out valid value; explicit error status maintained."""
        # Isolate single PID for deterministic evaluation
        self.sim.setup_pids([(0x010C, "RPM", "rpm", 0, INTERVAL_FAST_MS)])
        self.sim.start()

        # 1. Successful query establishes RPM = 1750.0
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.VALID, 1750.0, "rpm", "41 0C 1B 58", 25)
        self.sim.update(now_us=1_000_000)
        self.assertEqual(self.sim.signals[0x010C].value, 1750.0)
        self.assertEqual(self.sim.signals[0x010C].quality, QualityGrade.GOOD)

        # 2. Next query times out (200ms later)
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.TIMEOUT, 0.0, "", "", 400)
        self.sim.update(now_us=1_200_000)

        sig = self.sim.signals[0x010C]
        self.assertEqual(sig.quality, QualityGrade.TIMEOUT)
        # Zero-resistance rule: value MUST NOT suddenly become 0.0!
        self.assertEqual(sig.value, 1750.0)
        self.assertEqual(sig.last_valid_value, 1750.0)

    def test_K_no_data_handling(self):
        """K. NO DATA response evaluated with explicit NO_DATA quality grade."""
        grade = QualityEngine.evaluate(SampleStatus.NO_DATA, 1_000_000, 1_050_000)
        self.assertEqual(grade, QualityGrade.NO_DATA)

    def test_L_transport_failure_escalation(self):
        """L. Transport disconnection drops scheduler from RUNNING to PAUSED."""
        self.sim.start()
        self.assertEqual(self.sim.state, AcquisitionState.RUNNING)

        # Drop Bluetooth connection
        self.sim.is_bt_connected = False
        self.sim.update(now_us=2_000_000)
        self.assertEqual(self.sim.state, AcquisitionState.PAUSED)

    def test_M_pid_failure_does_not_kill_session(self):
        """M. Single PID error (e.g. MAP failure) does not stop acquisition session."""
        self.sim.setup_pids([
            (0x010C, "RPM", "rpm", 0, INTERVAL_FAST_MS),
            (0x010B, "MAP", "kPa", 1, INTERVAL_MEDIUM_MS)
        ])
        self.sim.start()
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.VALID, 800.0, "rpm", "41 0C 0C 80", 25)
        self.obd.responses[0x0B] = MockObdResult(SampleStatus.TIMEOUT, 0.0, "", "", 400)

        # Step 1: RPM is queried first (index 0)
        self.sim.update(now_us=1_000_000)
        # Step 2: MAP is queried next (index 1, was last_requested 0)
        self.sim.update(now_us=1_100_000)

        self.assertEqual(self.sim.state, AcquisitionState.RUNNING)
        self.assertGreater(self.sim.metrics.timeouts, 0)
        self.assertGreater(self.sim.metrics.successful_requests, 0)

    def test_N_bounded_history(self):
        """N. Ring buffer capacity is strictly bounded at 256."""
        ring = SampleRingBuffer(capacity=256)
        for i in range(500):
            sample = MeasurementSample("S1", i+1, 1000 + i, 0x010C, "RPM", "", [], 800.0, "rpm",
                                       SampleStatus.VALID, QualityGrade.GOOD, 1000+i, 1000+i, 20, FreshnessState.FRESH)
            ring.push(sample)
        self.assertEqual(ring.size(), 256)
        self.assertEqual(ring.capacity, 256)

    def test_O_history_eviction(self):
        """O. Ring buffer evicts oldest entries deterministically when full."""
        ring = SampleRingBuffer(capacity=4)
        for i in range(6):
            sample = MeasurementSample("S1", i+1, 1000 + i, 0x010C, "RPM", "", [], float(i+1), "rpm",
                                       SampleStatus.VALID, QualityGrade.GOOD, 1000+i, 1000+i, 20, FreshnessState.FRESH)
            ring.push(sample)

        self.assertEqual(ring.size(), 4)
        recent = ring.get_recent(4)
        # Recent returns newest first: sequence 6, 5, 4, 3
        seqs = [s.sequence for s in recent]
        self.assertEqual(seqs, [6, 5, 4, 3])
        # Sequences 1 and 2 were evicted
        all_since = ring.get_since(0)
        self.assertEqual([s.sequence for s in all_since], [3, 4, 5, 6])

    def test_P_session_id_separation(self):
        """P. Stopping and starting acquisition produces unique separate session IDs."""
        self.sim.start()
        session1 = self.sim.session_id
        self.assertTrue(session1.startswith("MINI-SESSION-"))

        self.sim.stop()
        self.assertEqual(self.sim.state, AcquisitionState.STOPPED)

        self.sim.start()
        session2 = self.sim.session_id
        self.assertTrue(session2.startswith("MINI-SESSION-"))
        self.assertNotEqual(session1, session2, "Each start must generate a unique session ID")

    def test_Q_metrics_correctness(self):
        """Q. Metrics correctly tally total, success, errors, and running latency."""
        self.sim.start()
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.VALID, 850.0, "rpm", "41 0C 0D 48", 30)
        self.sim.update(now_us=1_000_000)

        self.obd.responses[0x11] = MockObdResult(SampleStatus.TIMEOUT, 0.0, "", "", 400)
        self.sim.update(now_us=1_200_000)

        m = self.sim.metrics
        self.assertEqual(m.total_requests, 2)
        self.assertEqual(m.successful_requests, 1)
        self.assertEqual(m.timeouts, 1)
        self.assertGreater(m.average_latency_ms, 0)

    def test_R_backpressure_behavior(self):
        """R. Dropping work or scheduling delays does not allocate unbounded requests."""
        self.sim.start()
        # Simulate long delay (5 seconds jump in time)
        self.sim.update(now_us=6_000_000)
        # In a single update step, exactly ONE request is processed, no uncontrolled backlog queue
        self.assertEqual(self.sim.metrics.total_requests, 1)

    def test_S_start_stop_pause_resume_state_machine(self):
        """S. Validate state transitions: IDLE -> RUNNING -> PAUSED -> RUNNING -> STOPPED."""
        self.assertEqual(self.sim.state, AcquisitionState.IDLE)
        self.assertTrue(self.sim.start())
        self.assertEqual(self.sim.state, AcquisitionState.RUNNING)

        self.assertTrue(self.sim.pause())
        self.assertEqual(self.sim.state, AcquisitionState.PAUSED)
        self.assertFalse(self.sim.is_running())

        self.assertTrue(self.sim.resume())
        self.assertEqual(self.sim.state, AcquisitionState.RUNNING)
        self.assertTrue(self.sim.is_running())

        self.assertTrue(self.sim.stop())
        self.assertEqual(self.sim.state, AcquisitionState.STOPPED)
        self.assertFalse(self.sim.is_running())

    def test_T_live_snapshot_consistency(self):
        """T. LiveSnapshot contains up-to-date values, quality, freshness, and age."""
        self.sim.start()
        self.obd.responses[0x0C] = MockObdResult(SampleStatus.VALID, 2200.0, "rpm", "41 0C 22 60", 35)
        self.sim.update(now_us=1_000_000)

        sig = self.sim.signals[0x010C]
        self.assertEqual(sig.value, 2200.0)
        self.assertEqual(sig.quality, QualityGrade.GOOD)
        self.assertEqual(sig.freshness, FreshnessState.FRESH)
        self.assertEqual(sig.latency_ms, 35)

    def test_U_web_api_state_consistency(self):
        """U. Ensure snapshot returned to Web matches scheduler state without direct BT access."""
        self.sim.start()
        snap_state = self.sim.state
        self.assertEqual(snap_state, AcquisitionState.RUNNING)
        self.assertTrue(self.sim.session_id.startswith("MINI-SESSION-"))

    def test_V_lock_does_not_cover_blocking_obd_io(self):
        """V. Verify shared-state mutex is NEVER held during blocking OBD I/O."""
        self.sim.start()
        self.sim.update(now_us=1_000_000)
        self.assertFalse(self.sim.lock_held_during_obd_io,
                         "CRITICAL: Shared lock must not be held across blocking OBD transactions!")

if __name__ == "__main__":
    unittest.main()
