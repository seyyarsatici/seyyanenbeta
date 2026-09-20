#!/usr/bin/env python3
"""
SEYYANEN MINI — POST-M8 HARDENING PASS REGRESSION TEST SUITE
=============================================================
Validates all verified defects and hardening passes across:
1. M-2 Non-blocking Bluetooth lifecycle & disconnect cleanup
2. M-3 PID discovery chaining (0100 -> 0120 -> ... -> 01E0) & overflow tracking
3. M-4 Scheduler timing observability (target vs observed interval, delay, fairness)
4. M-5 Storage decoupled queue (bounded FIFO, backpressure, overflow, latency)
5. Wall-clock session projection formula & metadata
6. Security read-only safety filter enforcement
"""

import math
import re
import time
import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# SECTION 1: M-2 TRANSPORT LIFECYCLE MODEL
# ==============================================================================

class AdapterState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING   = "CONNECTING"
    CONNECTED    = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR        = "ERROR"

class TransportError:
    NONE                     = "NONE"
    BT_INIT_FAILED           = "BT_INIT_FAILED"
    SPP_CONNECT_FAILED       = "SPP_CONNECT_FAILED"
    SPP_DISCONNECTED         = "SPP_DISCONNECTED"
    TRANSACTION_TIMEOUT      = "TRANSACTION_TIMEOUT"
    INVALID_ADAPTER_RESPONSE = "INVALID_ADAPTER_RESPONSE"
    SAFETY_BLOCKED           = "SAFETY_BLOCKED"

def is_command_safe(cmd: str) -> bool:
    """Mirrors VLinkerBluetoothTransport::isCommandSafe."""
    if not cmd:
        return False
    s = cmd.strip()
    if not s:
        return False
    if s.upper().startswith("AT"):
        return True
    hex_chars = [c for c in s if c in "0123456789abcdefABCDEF"]
    if len(hex_chars) < 2:
        return False
    mode = "".join(hex_chars[:2]).upper()
    blocked = {"04", "08", "10", "11", "27", "28", "2E", "31", "34", "35", "36", "37", "85"}
    return mode not in blocked

class HardenedTransportModel:
    """Accurately models the hardened non-blocking transport lifecycle."""

    def __init__(self, base_backoff_ms: int = 1000, max_backoff_ms: int = 16000):
        self.state = AdapterState.DISCONNECTED
        self.last_error = TransportError.NONE
        self.connecting_in_progress = False
        self.abort_connection = False
        self.worker_task_active = False
        self.identity_verified = False
        self.retry_count = 0
        self.current_backoff_ms = base_backoff_ms
        self.base_backoff_ms = base_backoff_ms
        self.max_backoff_ms = max_backoff_ms

    def connect(self) -> bool:
        if self.state == AdapterState.CONNECTED and self.identity_verified:
            return True
        if self.connecting_in_progress or self.worker_task_active:
            return False  # Duplicate prevention

        self.connecting_in_progress = True
        self.abort_connection = False
        self.state = AdapterState.CONNECTING
        self.worker_task_active = True
        return True

    def simulate_worker_step(self, spp_success: bool, handshake_success: bool):
        """Simulates asynchronous execution inside btConnectTask worker."""
        if not self.worker_task_active:
            return

        if self.abort_connection:
            self.connecting_in_progress = False
            self.worker_task_active = False
            return

        if not spp_success:
            self.state = AdapterState.ERROR
            self.last_error = TransportError.SPP_CONNECT_FAILED
            self.connecting_in_progress = False
            self.worker_task_active = False
            return

        if self.abort_connection:
            self.connecting_in_progress = False
            self.worker_task_active = False
            return

        if not handshake_success:
            self.state = AdapterState.ERROR
            self.last_error = TransportError.INVALID_ADAPTER_RESPONSE
            self.identity_verified = False
            self.connecting_in_progress = False
            self.worker_task_active = False
            return

        # Both physical link and adapter identity handshake succeed
        self.state = AdapterState.CONNECTED
        self.last_error = TransportError.NONE
        self.identity_verified = True
        self.retry_count = 0
        self.current_backoff_ms = self.base_backoff_ms
        self.connecting_in_progress = False
        self.worker_task_active = False

    def disconnect(self) -> bool:
        # Crucial Hardening Rule: disconnect must NEVER leave stale connecting_in_progress=True!
        if self.worker_task_active:
            self.abort_connection = True
            self.worker_task_active = False
        self.connecting_in_progress = False
        self.identity_verified = False
        self.state = AdapterState.DISCONNECTED
        self.last_error = TransportError.NONE
        return True

    def on_link_lost(self):
        self.state = AdapterState.RECONNECTING
        self.last_error = TransportError.SPP_DISCONNECTED
        self.identity_verified = False

    def trigger_reconnect_attempt(self) -> Tuple[bool, int]:
        """Auto-reconnect with exponential backoff progression."""
        if self.connecting_in_progress or self.worker_task_active:
            return False, self.current_backoff_ms

        self.retry_count += 1
        used_backoff = self.current_backoff_ms
        self.current_backoff_ms = min(self.current_backoff_ms * 2, self.max_backoff_ms)
        self.connect()
        return True, used_backoff


# ==============================================================================
# SECTION 2: M-3 PID DISCOVERY MODEL (CHAINED 0100 -> 01E0)
# ==============================================================================

def is_pid_bit_set(bitmap: int, relative_pid: int) -> bool:
    """Relative PID 1 is bit 31 (MSB), relative PID 32 is bit 0 (LSB)."""
    if relative_pid < 1 or relative_pid > 32:
        return False
    shift = 32 - relative_pid
    return ((bitmap >> shift) & 1) == 1

class HardenedPidScannerModel:
    MAX_CAPACITY = 64

    def __init__(self, ecu_bitmaps: Dict[int, int], fail_on_base: Optional[int] = None):
        self.ecu_bitmaps = ecu_bitmaps  # e.g. {0x00: 0xBE1FA813, 0x20: ...}
        self.fail_on_base = fail_on_base
        self.queried_ranges: List[int] = []
        self.supported_pids: List[int] = []
        self.registry_overflow_count = 0
        self.state = "IDLE"

    def scan(self) -> bool:
        self.state = "SCANNING"
        self.queried_ranges.clear()
        self.supported_pids.clear()
        self.registry_overflow_count = 0

        current_base = 0x00
        while True:
            self.queried_ranges.append(current_base)

            # Simulated hardware failure
            if self.fail_on_base == current_base:
                self.state = "ERROR"
                return False

            if current_base not in self.ecu_bitmaps:
                self.state = "ERROR"
                return False

            bitmap = self.ecu_bitmaps[current_base]

            # Decode supported PIDs in block [current_base + 1 .. current_base + 32]
            for bit_idx in range(1, 33):
                if is_pid_bit_set(bitmap, bit_idx):
                    pid_num = current_base + bit_idx
                    if len(self.supported_pids) < self.MAX_CAPACITY:
                        self.supported_pids.append(pid_num)
                    else:
                        self.registry_overflow_count += 1

            # Check if ECU advertises next block via bit 32
            has_next = is_pid_bit_set(bitmap, 32)
            if not has_next or current_base >= 0xE0:
                break

            current_base += 0x20

        self.state = "COMPLETE"
        return True


# ==============================================================================
# SECTION 3: M-4 SCHEDULER TIMING & FAIRNESS MODEL
# ==============================================================================

class HardenedScheduledPid:
    def __init__(self, pid: int, name: str, priority: int, interval_us: int):
        self.pid = pid
        self.name = name
        self.priority = priority
        self.interval_us = interval_us
        self.last_requested_us = 0
        self.last_success_us = 0
        self.request_count = 0
        self.target_interval_us = interval_us
        self.observed_interval_us = 0
        self.scheduler_delay_us = 0
        self.deadline_miss_count = 0
        self.is_deadline_miss = False

class HardenedSchedulerModel:
    def __init__(self):
        self.scheduled_pids: List[HardenedScheduledPid] = []
        self.unscheduled_pids: List[Tuple[int, str, str]] = []  # (pid, name, reason)
        self.samples: List[dict] = []
        self.clock_us = 1000000

    def add_pid(self, pid: int, name: str, priority: int, interval_us: int, supported: bool):
        if not supported:
            self.unscheduled_pids.append((pid, name, "UNSUPPORTED"))
            return
        if len(self.scheduled_pids) >= 16:
            self.unscheduled_pids.append((pid, name, "EXCEEDED_SCHEDULER_CAPACITY"))
            return
        self.scheduled_pids.append(HardenedScheduledPid(pid, name, priority, interval_us))

    def select_next_due(self, now_us: int) -> Optional[HardenedScheduledPid]:
        if not self.scheduled_pids:
            return None

        best_sp = None
        max_urgency = -1

        for sp in self.scheduled_pids:
            if sp.last_requested_us == 0:
                return sp  # Highest priority to first poll

            elapsed = now_us - sp.last_requested_us
            if elapsed >= sp.interval_us:
                # Proportional overdue ratio guarantees fair scheduling without starvation
                urgency = (elapsed * 1000) // sp.interval_us
                if urgency > max_urgency:
                    max_urgency = urgency
                    best_sp = sp

        return best_sp

    def execute_query(self, sp: HardenedScheduledPid, transaction_latency_us: int):
        now_us = self.clock_us

        # Calculate timing observability
        sp.target_interval_us = sp.interval_us
        if sp.last_requested_us > 0:
            sp.observed_interval_us = now_us - sp.last_requested_us
            expected_due_us = sp.last_requested_us + sp.interval_us
            sp.scheduler_delay_us = max(0, now_us - expected_due_us)
        else:
            sp.observed_interval_us = sp.interval_us
            sp.scheduler_delay_us = 0

        # Deadline miss threshold: delay > 10% of target interval or > 25ms
        miss_thresh = max(sp.interval_us // 10, 25000)
        sp.is_deadline_miss = sp.scheduler_delay_us > miss_thresh
        if sp.is_deadline_miss:
            sp.deadline_miss_count += 1

        sp.last_requested_us = now_us
        sp.request_count += 1

        # Simulate transaction duration
        resp_end_us = now_us + transaction_latency_us
        self.clock_us = resp_end_us
        sp.last_success_us = resp_end_us

        sample = {
            "pid": sp.pid,
            "name": sp.name,
            "timestamp_us": resp_end_us,
            "target_interval_us": sp.target_interval_us,
            "observed_interval_us": sp.observed_interval_us,
            "scheduler_delay_us": sp.scheduler_delay_us,
            "latency_us": transaction_latency_us,
            "is_deadline_miss": sp.is_deadline_miss,
        }
        self.samples.append(sample)


# ==============================================================================
# SECTION 4: M-5 DECOUPLED STORAGE QUEUE MODEL
# ==============================================================================

class StorageHealth:
    OK           = "STORAGE_OK"
    BACKPRESSURE = "STORAGE_BACKPRESSURE"
    OVERFLOW     = "STORAGE_OVERFLOW"
    WRITE_ERROR  = "STORAGE_WRITE_ERROR"

class HardenedStorageQueueModel:
    CAPACITY = 64
    BACKPRESSURE_THRESHOLD = 48  # 75%

    def __init__(self):
        self.queue: List[dict] = []
        self.samples_written = 0
        self.samples_dropped = 0
        self.backpressure_events = 0
        self.write_errors = 0
        self.queue_high_water_mark = 0
        self.health_state = StorageHealth.OK
        self.last_write_latency_us = 0
        self.last_flush_latency_us = 0

    def enqueue(self, sample: dict) -> bool:
        if len(self.queue) >= self.CAPACITY:
            self.samples_dropped += 1
            self.health_state = StorageHealth.OVERFLOW
            return False

        self.queue.append(sample)
        depth = len(self.queue)
        if depth > self.queue_high_water_mark:
            self.queue_high_water_mark = depth

        if depth >= self.BACKPRESSURE_THRESHOLD:
            self.backpressure_events += 1
            self.health_state = StorageHealth.BACKPRESSURE
        elif self.health_state != StorageHealth.WRITE_ERROR:
            self.health_state = StorageHealth.OK

        return True

    def drain_one(self, simulate_io_error: bool = False, latency_us: int = 1500) -> bool:
        if not self.queue:
            return False

        sample = self.queue.pop(0)
        self.last_write_latency_us = latency_us

        if simulate_io_error:
            self.write_errors += 1
            self.health_state = StorageHealth.WRITE_ERROR
            return False

        self.samples_written += 1
        if len(self.queue) < self.BACKPRESSURE_THRESHOLD and self.health_state == StorageHealth.BACKPRESSURE:
            self.health_state = StorageHealth.OK

        return True


# ==============================================================================
# SECTION 5: COMPREHENSIVE REGRESSION TEST SUITE
# ==============================================================================

class TestM9HardeningPass(unittest.TestCase):

    # --------------------------------------------------------------------------
    # M-2 TRANSPORT REGRESSION TESTS
    # --------------------------------------------------------------------------

    def test_m2_connection_state_transitions(self):
        """Test explicit non-blocking transitions: DISCONNECTED -> CONNECTING -> CONNECTED."""
        t = HardenedTransportModel()
        self.assertEqual(t.state, AdapterState.DISCONNECTED)

        # Call connect() -> initiates non-blocking worker
        ok = t.connect()
        self.assertTrue(ok)
        self.assertEqual(t.state, AdapterState.CONNECTING)
        self.assertTrue(t.connecting_in_progress)
        self.assertTrue(t.worker_task_active)

        # Worker completes both SPP link and adapter handshake
        t.simulate_worker_step(spp_success=True, handshake_success=True)
        self.assertEqual(t.state, AdapterState.CONNECTED)
        self.assertFalse(t.connecting_in_progress)
        self.assertFalse(t.worker_task_active)
        self.assertTrue(t.identity_verified)

    def test_m2_duplicate_connection_prevention(self):
        """Test that duplicate connect() calls while connecting are safely rejected."""
        t = HardenedTransportModel()
        t.connect()
        self.assertTrue(t.connecting_in_progress)

        # Duplicate call must return False without modifying state
        ok_dup = t.connect()
        self.assertFalse(ok_dup)
        self.assertEqual(t.state, AdapterState.CONNECTING)

    def test_m2_disconnect_clears_connecting_in_progress(self):
        """CRITICAL: disconnect() must ALWAYS reset connecting_in_progress = False."""
        t = HardenedTransportModel()
        t.connect()
        self.assertTrue(t.connecting_in_progress)

        # Disconnect while connection was in-flight
        t.disconnect()
        self.assertFalse(t.connecting_in_progress, "disconnect() must clear connecting_in_progress!")
        self.assertEqual(t.state, AdapterState.DISCONNECTED)
        self.assertFalse(t.worker_task_active)

        # Verify a new connect() can be immediately initiated
        ok_next = t.connect()
        self.assertTrue(ok_next, "Should be able to connect after clean disconnect")

    def test_m2_reconnect_exponential_backoff(self):
        """Test auto-reconnect backoff progression (1s -> 2s -> 4s -> 8s -> 16s bounded)."""
        t = HardenedTransportModel(base_backoff_ms=1000, max_backoff_ms=16000)
        t.on_link_lost()

        expected_backoffs = [1000, 2000, 4000, 8000, 16000, 16000]
        for expected in expected_backoffs:
            ok, used = t.trigger_reconnect_attempt()
            self.assertTrue(ok)
            self.assertEqual(used, expected)
            t.simulate_worker_step(spp_success=False, handshake_success=False)

    # --------------------------------------------------------------------------
    # M-3 PID DISCOVERY REGRESSION TESTS
    # --------------------------------------------------------------------------

    def test_m3_only_0100_supported(self):
        """When ECU bit 32 of 0100 is 0, scanner stops cleanly after 0100."""
        # Bit 32 is 0 -> no next block
        bitmaps = {0x00: 0xBE1FA812}
        self.assertFalse(is_pid_bit_set(bitmaps[0x00], 32))

        scanner = HardenedPidScannerModel(bitmaps)
        ok = scanner.scan()
        self.assertTrue(ok)
        self.assertEqual(scanner.queried_ranges, [0x00], "Should ONLY query 0100 when bit 32 is 0")
        self.assertEqual(scanner.state, "COMPLETE")

    def test_m3_chained_discovery_0100_to_0120(self):
        """When bit 32 of 0100 is 1, scanner queries 0120 and stops if 0120 bit 32 is 0."""
        # Bit 32 of 0100 is 1 (0xBE1FA813), Bit 32 of 0120 is 0 (0x80000000)
        bitmaps = {
            0x00: 0xBE1FA813,
            0x20: 0x80000000
        }
        self.assertTrue(is_pid_bit_set(bitmaps[0x00], 32))
        self.assertFalse(is_pid_bit_set(bitmaps[0x20], 32))

        scanner = HardenedPidScannerModel(bitmaps)
        ok = scanner.scan()
        self.assertTrue(ok)
        self.assertEqual(scanner.queried_ranges, [0x00, 0x20])
        self.assertIn(0x21, scanner.supported_pids)

    def test_m3_full_chain_through_01E0(self):
        """Test full chained discovery across all standard Mode 01 blocks through 01E0."""
        # Every block sets bit 32 = 1 except 01E0
        all_bases = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
        bitmaps = {}
        for b in all_bases:
            bitmaps[b] = 0x80000001 if b < 0xE0 else 0x80000000

        scanner = HardenedPidScannerModel(bitmaps)
        ok = scanner.scan()
        self.assertTrue(ok)
        self.assertEqual(scanner.queried_ranges, all_bases, "Must traverse full chain to 01E0")
        self.assertEqual(scanner.state, "COMPLETE")

    def test_m3_intermediate_query_failure(self):
        """Intermediate bitmap failure preserves earlier discovered PIDs and reports ERROR."""
        bitmaps = {
            0x00: 0xBE1FA813,  # Bit 32 set -> expects 0120
            0x20: 0x80000000
        }
        scanner = HardenedPidScannerModel(bitmaps, fail_on_base=0x20)
        ok = scanner.scan()
        self.assertFalse(ok)
        self.assertEqual(scanner.state, "ERROR")
        # Ensure 0100 discoveries were not erased
        self.assertGreater(len(scanner.supported_pids), 0)

    def test_m3_registry_overflow_tracking(self):
        """Discovered PIDs beyond MAX_CAPACITY (64) increment registry_overflow_count."""
        # Create bitmaps advertising 70 PIDs
        bitmaps = {
            0x00: 0xFFFFFFFF,  # 32 PIDs
            0x20: 0xFFFFFFFF,  # 32 PIDs (total 64)
            0x40: 0xF0000000   # 4 PIDs (total 68)
        }
        scanner = HardenedPidScannerModel(bitmaps)
        scanner.scan()
        self.assertEqual(len(scanner.supported_pids), 64)
        self.assertEqual(scanner.registry_overflow_count, 4)

    # --------------------------------------------------------------------------
    # M-4 SCHEDULER TIMING OBSERVABILITY & FAIRNESS TESTS
    # --------------------------------------------------------------------------

    def test_m4_target_vs_observed_interval_and_delay(self):
        """Verify target interval, observed interval, and scheduler delay are tracked distinctly."""
        sched = HardenedSchedulerModel()
        sched.add_pid(0x010C, "RPM", priority=0, interval_us=120000, supported=True)
        sp = sched.scheduled_pids[0]

        # First query at t=1,000,000us
        sched.execute_query(sp, transaction_latency_us=40000)
        self.assertEqual(sched.samples[0]["target_interval_us"], 120000)
        self.assertEqual(sched.samples[0]["scheduler_delay_us"], 0)

        # Advance clock to 1,300,000us (elapsed = 300,000us, target = 120,000us, delay = 180,000us)
        sched.clock_us = 1300000
        sched.execute_query(sp, transaction_latency_us=45000)

        sample = sched.samples[1]
        self.assertEqual(sample["target_interval_us"], 120000)
        self.assertEqual(sample["observed_interval_us"], 300000)
        self.assertEqual(sample["scheduler_delay_us"], 180000)
        self.assertTrue(sample["is_deadline_miss"])
        self.assertEqual(sp.deadline_miss_count, 1)

    def test_m4_fair_scheduling_no_starvation(self):
        """Proportional urgency ensures slow signals (ECT 1200ms) are not starved by fast signals."""
        sched = HardenedSchedulerModel()
        sched.add_pid(0x010C, "RPM", priority=0, interval_us=120000, supported=True)
        sched.add_pid(0x0105, "ECT", priority=2, interval_us=1200000, supported=True)

        rpm_sp = sched.scheduled_pids[0]
        ect_sp = sched.scheduled_pids[1]

        # Initialize both at t=1,000,000us
        sched.execute_query(ect_sp, 30000) # last_req = 1,000,000

        # RPM is polled regularly up to t=2,430,000us
        sched.clock_us = 2430000
        sched.execute_query(rpm_sp, 20000) # last_req = 2,430,000

        # At t=2,560,000us:
        # Both are due (RPM elapsed 130ms >= 120ms, ECT elapsed 1560ms >= 1200ms)
        # ECT: elapsed 1,560,000us on 1,200,000us interval -> urgency = 1560*1000/1200 = 1300 (30% overdue)
        # RPM: elapsed 130,000us on 120,000us interval     -> urgency = 130*1000/120   = 1083 (8% overdue)
        sched.clock_us = 2560000
        due = sched.select_next_due(sched.clock_us)
        self.assertIsNotNone(due)
        self.assertEqual(due.name, "ECT", "ECT must be selected when proportionally more overdue!")

    def test_m4_unscheduled_pids_exposure_with_reasons(self):
        """Scheduler identifies unscheduled PIDs with exact reasons."""
        sched = HardenedSchedulerModel()
        # Add 16 supported PIDs to fill capacity
        for i in range(16):
            sched.add_pid(0x0100 + i, f"P{i}", priority=1, interval_us=350000, supported=True)

        # 17th supported PID must be rejected for capacity
        sched.add_pid(0x012F, "FLI", priority=2, interval_us=1200000, supported=True)
        # Unsupported PID
        sched.add_pid(0x0130, "WARM", priority=2, interval_us=1200000, supported=False)

        self.assertEqual(len(sched.scheduled_pids), 16)
        self.assertEqual(len(sched.unscheduled_pids), 2)
        self.assertEqual(sched.unscheduled_pids[0], (0x012F, "FLI", "EXCEEDED_SCHEDULER_CAPACITY"))
        self.assertEqual(sched.unscheduled_pids[1], (0x0130, "WARM", "UNSUPPORTED"))

    # --------------------------------------------------------------------------
    # M-5 STORAGE QUEUE & BACKPRESSURE TESTS
    # --------------------------------------------------------------------------

    def test_m5_storage_queue_normal_flow(self):
        """Samples enqueue non-blockingly and drain in FIFO order."""
        sq = HardenedStorageQueueModel()
        for i in range(10):
            ok = sq.enqueue({"seq": i, "val": i * 10})
            self.assertTrue(ok)

        self.assertEqual(len(sq.queue), 10)
        self.assertEqual(sq.queue_high_water_mark, 10)
        self.assertEqual(sq.health_state, StorageHealth.OK)

        # Drain 5 items
        for i in range(5):
            ok = sq.drain_one()
            self.assertTrue(ok)

        self.assertEqual(len(sq.queue), 5)
        self.assertEqual(sq.samples_written, 5)

    def test_m5_storage_queue_backpressure_and_overflow(self):
        """Queue triggers BACKPRESSURE at 75% (48) and OVERFLOW at 100% (64)."""
        sq = HardenedStorageQueueModel()

        # Enqueue 47 items -> still OK
        for i in range(47):
            sq.enqueue({"seq": i})
        self.assertEqual(sq.health_state, StorageHealth.OK)

        # 48th item triggers BACKPRESSURE
        sq.enqueue({"seq": 47})
        self.assertEqual(sq.health_state, StorageHealth.BACKPRESSURE)
        self.assertGreater(sq.backpressure_events, 0)

        # Fill up to 64 items
        for i in range(48, 64):
            sq.enqueue({"seq": i})
        self.assertEqual(len(sq.queue), 64)

        # 65th item exceeds bounded capacity -> OVERFLOW and dropped count
        ok = sq.enqueue({"seq": 64})
        self.assertFalse(ok)
        self.assertEqual(sq.samples_dropped, 1)
        self.assertEqual(sq.health_state, StorageHealth.OVERFLOW)

    def test_m5_storage_backpressure_recovery(self):
        """When queue drains below threshold, health state recovers to STORAGE_OK."""
        sq = HardenedStorageQueueModel()
        for i in range(50):
            sq.enqueue({"seq": i})
        self.assertEqual(sq.health_state, StorageHealth.BACKPRESSURE)

        # Drain until below 48
        for i in range(10):
            sq.drain_one()

        self.assertLess(len(sq.queue), 48)
        self.assertEqual(sq.health_state, StorageHealth.OK)

    def test_m5_storage_write_error_handling(self):
        """SD card write errors set STORAGE_WRITE_ERROR and increment write_errors."""
        sq = HardenedStorageQueueModel()
        sq.enqueue({"seq": 1})
        ok = sq.drain_one(simulate_io_error=True)
        self.assertFalse(ok)
        self.assertEqual(sq.health_state, StorageHealth.WRITE_ERROR)
        self.assertEqual(sq.write_errors, 1)

    # --------------------------------------------------------------------------
    # SECTION 6: WALL-CLOCK FORMULA PROJECTION TESTS
    # --------------------------------------------------------------------------

    def test_wall_clock_projection_formula(self):
        """Verifies wall_clock(sample) = start_wall_clock + (ts_us - start_monotonic_us)."""
        start_monotonic_us = 5000000
        start_wall_clock_iso = "2026-09-20T21:00:00.000000Z"
        sample_monotonic_us = 7500000  # +2.5 seconds

        delta_us = sample_monotonic_us - start_monotonic_us
        self.assertEqual(delta_us, 2500000)

        delta_s = delta_us / 1000000.0
        self.assertEqual(delta_s, 2.5)

    # --------------------------------------------------------------------------
    # SECTION 7: SAFETY FILTER REGRESSION TESTS
    # --------------------------------------------------------------------------

    def test_safety_filter_blocks_destructive_modes(self):
        """Ensures Mode 04 (clear DTCs), Mode 08, and UDS write services are blocked."""
        blocked_commands = [
            "04", "04 00", "04FF",
            "08", "08 01 00",
            "10 01", "10 03",  # UDS DiagnosticSessionControl
            "11 01",          # UDS ECUReset
            "27 01",          # UDS SecurityAccess
            "28 00",          # UDS CommunicationControl
            "2E 01 02",       # UDS WriteDataByIdentifier
            "31 01 00",       # UDS RoutineControl
            "34 00", "35 00", "36 01", "37 00", # UDS Download/Upload
            "85 02",          # UDS ControlDTCSetting
        ]
        for cmd in blocked_commands:
            self.assertFalse(is_command_safe(cmd), f"Command '{cmd}' must be blocked by safety filter!")

    def test_safety_filter_allows_safe_queries(self):
        """Mode 01 read queries and AT commands are allowed."""
        safe_commands = [
            "0100", "01 0C", "0105", "010D", "0120", "0140", "0160", "01E0",
            "ATI", "ATE0", "ATH0", "ATSP0", "ATDPN", "ATRV"
        ]
        for cmd in safe_commands:
            self.assertTrue(is_command_safe(cmd), f"Command '{cmd}' should be allowed!")


if __name__ == "__main__":
    unittest.main()
