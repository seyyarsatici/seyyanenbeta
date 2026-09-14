# Phase K-3 Walkthrough: Live Acquisition Runtime and Trusted Data Pipeline

This document details the architectural implementation, integration boundaries, data contracts, validation results, performance benchmarks, and physical hardware status for **Phase K-3: Live Acquisition Runtime and Trusted Data Pipeline** in Seyyanen (`seyyarsatici/seyyanenbeta`).

---

## 1. Actual Acquisition Call Graph

```
[LiveAcquisitionRuntime._acquisition_loop] (Daemon Worker Thread)
       │
       ▼ (Monotonic Timing & Drift Compensation)
[_execute_cycle]
       │
       ▼ (Per-PID Circuit-Breaker Check: should_poll_pid)
[_acquire_pid(pid)]
       │
       ├─► [LiveSafety Dual-Gate Check] (Blocks prohibited services 04, 14, 2E, 27, 2F, 34-37, 3D)
       │
       ├─► [DiagnosticAdapter.send_command(clean_pid)] (Authoritative J-1 Hardware Boundary)
       │         │
       │         ▼ (Adapter Thread-Safe Command Serialization: self._serial_lock)
       │   [ELM327DiagnosticAdapter._send_raw_command]
       │         │
       │         ▼ (UART Serial I/O: pyserial)
       │   [Physical / Virtual Vehicle ECU]
       │
       ▼ (Raw String & Byte Preservation: raw_str, raw_bytes)
[_decode_pid_response] (Safe hex payload decoding without fake zeros)
       │
       ▼ (Construct Standard Observation Sample: value, status, timestamps, ECU/Vehicle context)
[_record_sample]
       │
       ├─► [LiveQualityAssessor.evaluate_sample] (Phase F-2 & C-layer Quality Assessment)
       │
       ├─► [AutoExpertEngine._update_sensor_cache] (C-layer cache & history synchronizer)
       │         │
       │         ▼
       │   [sensor_history append ONLY if status == VALID and quality == GOOD]
       │
       ├─► [LiveDiagnosticIntelligence.process_live_sample] (Phase F-3 Consumer)
       │
       ├─► [RuntimeSafetyManager.record_pid_result] (Phase F-5 Circuit Breaker)
       │
       ├─► [_enqueue_persistence] (Phase J-3 Bounded Persistence Queue)
       │         │
       │         ▼ (Non-blocking queue.put_nowait)
       │   [queue.Queue(maxsize=1000)]
       │         │
       │         ▼ (Dedicated Persistence Worker Thread)
       │   [DiagnosticRepository.save_raw_acquisition] (Decoupled SQLite Database)
       │
       └─► [_fire_callback] (Thread-Safe Presentation / Observer Dispatch)
```

---

## 2. Authoritative Scheduler

`LiveAcquisitionRuntime` is the single authoritative scheduler for live diagnostic telemetry:
- **Single Threaded Master**: Only one background worker thread (`LiveAcquisitionWorker`) is spawned per active diagnostic session.
- **Race Condition Prevention**: `start()` is protected by `self._state_lock`. Duplicate calls to `start()` immediately return `False` without spawning secondary threads or resetting active timing schedules.
- **Monotonic Scheduling**: Target cycles are scheduled using `time.monotonic()`, calculating time remaining until the next scheduled cycle and waiting via `self._stop_event.wait(timeout=wait_duration)`. This eliminates cumulative drift caused by physical UART transmission latency.

---

## 3. Adapter Interaction

The live acquisition runtime never writes directly to physical serial ports:
- **Hardware Routing**: All diagnostic command dispatches in `_acquire_pid` route through `self.adapter.send_command(clean_pid, timeout=timeout_val)` when connected.
- **J-1 Authority**: All capability checks (`capabilities.supports_serial_transport`), connection checks (`is_connected()`), and response status classifications (`STATUS_VALID`, `STATUS_TIMEOUT`, `STATUS_NO_DATA`, `STATUS_SERIAL_ERROR`, `STATUS_NRC`) are authoritative from J-1.
- **Legacy Fallback**: If initialized without an adapter or in virtual testing mode, fallback to `self.engine.komut_gonder` is retained for 100% backward compatibility.

---

## 4. Scheduling Policy

- **Configurable Cadence**: `cycle_interval` (default 0.1s, configurable from 0.01s upwards).
- **Sequential PID Polling**: Within each cycle, PIDs are polled sequentially over the shared physical serial transport to eliminate command interleaving.
- **Circuit-Breaker Throttling**: Before dispatching a PID, `self.safety_manager.should_poll_pid(pid)` is evaluated. If a PID has suffered repeated timeouts (circuit `OPEN`), rapid polling is suppressed to protect the adapter from queue starvation.

---

## 5. Raw -> Normalized -> Decoded -> Trusted Pipeline

Every observation flows through an explicit, 5-stage transformation pipeline:
1. **Raw Serial Payload**: Preserved bit-for-bit in `sample["raw_bytes"]` and `sample["raw_value"]`.
2. **Normalized Response**: Echoes, carriage returns, line feeds, and prompt characters (`>`) are stripped.
3. **Protocol Decoding**: Decoded into standard physical units (`sample["value"]`). If the response fails parsing, has a DID mismatch, or contains malformed non-hex bytes, `sample["value"] = None`. **Fake zeros (0.0) are strictly forbidden.**
4. **C-Layer Quality Evaluation**: `LiveQualityAssessor` evaluates physical limits (`PHYSICAL_LIMITS`), temporal plausibility (`TEMPORAL_LIMITS`), vehicle operating envelope (`ENVELOPE_NORMAL`), cross-sensor correlation, and freshness.
5. **Trusted Observation**: Only samples with `status == STATUS_VALID` and `quality == QUALITY_GOOD` are promoted to trusted observations and recorded in `latest_successful_by_pid` and `self.sensor_history`.

---

## 6. Cache & History Behavior

- **`data_cache[sensor_name]`**:
  - Valid samples update `val`, `time`, `status`, and `quality`.
  - Failed samples (timeout, NO DATA, NRC) do NOT overwrite the prior valid value in `data_cache`. The cached value retains its previous reading and ages naturally until `_is_sensor_fresh(name, max_age=2.0)` evaluates to `False` (stale value semantics).
- **`sensor_history[sensor_name]`**:
  - Enforces strict bounded capacity (`maxlen=50`).
  - Only appends records when `status == STATUS_VALID` and `quality == QUALITY_GOOD`.
  - Stale, invalid, suspect, or implausible values are permanently excluded from trusted history.
- **`latest_by_pid` vs `latest_successful_by_pid`**:
  - `get_latest_sample(pid)` reflects the exact result of the most recent query (including errors).
  - `get_latest_successful_sample(pid)` preserves the last known valid reading across transient query failures.

---

## 7. Persistence Architecture

- **J-3 DiagnosticRepository Integration**: Pluggable `repository: Optional[DiagnosticRepository] = None` and `session_id: str`.
- **Decoupled Asynchronous Worker**: Acquisition does not write synchronously to disk or SQLite. Samples are enqueued into `_persistence_queue` (`queue.Queue(maxsize=1000)`).
- **Dedicated Persistence Thread**: `LivePersistenceWorker` drains the queue and writes records in batches via `repository.save_raw_acquisition(...)`.
- **Failure Isolation**: If the storage backend encounters errors (disk full, lock contention), the exception is caught, `persistence_errors` is incremented, and physical acquisition continues without interruption.

---

## 8. Backpressure Behavior

- **Bounded Queue**: Default capacity is 1,000 items.
- **Saturation Drop Policy**: When the persistence queue fills up (e.g., due to slow disk I/O), `_enqueue_persistence` performs non-blocking `put_nowait`. If full, it drops the sample, increments `_persistence_dropped_count`, and logs a warning.
- **Invariant Preserved**: Physical vehicle communication cadence is NEVER throttled or stalled by slow persistent storage.

---

## 9. UI Boundary

- **Asynchronous Presenter**: LiveDiagnosticWidget consumes data via a thread-safe `QTimer` polling loop (~11 FPS).
- **Zero I/O on GUI Thread**: UI buttons delegate to asynchronous workers (`LiveConnectWorker`, `LiveReconnectWorker`) and runtime controls (`runtime.start()`, `runtime.stop()`).
- **No Direct Serial Access**: The UI never accesses serial handles or dispatches AT/OBD commands directly.

---

## 10. Intelligence Boundary

- **Pure Data Consumers**: `LiveDiagnosticIntelligence` (Phase F-3), `DiagnosticWorkflow` (Phase H), and `DiagnosticReasoningSession` (Phase I) consume structured samples and quality results.
- **No Reverse Channel**: Diagnostic intelligence cannot bypass the acquisition scheduler to perform direct serial I/O or dispatch commands to the adapter.

---

## 11. Multi-ECU Handling

- **ECU Identity Preservation**: Every sample includes `"ecu_id"` (default `"ECM"` or explicitly configured target).
- **Context Routing**: `set_target_ecu(ecu_id)` updates the active target ECU context.
- **Isolation**: In accordance with `MultiECUFailureIsolation`, a failure or timeout on ECU A never corrupts or invalidates observations acquired from ECU B.

---

## 12. Vehicle Identity Handling

- **Vehicle Context Binding**: Every sample records `"vehicle_id"`.
- **Cache Invalidation on Vehicle Switch**: When `set_vehicle_context(vehicle_id)` detects a new vehicle identity, or `invalidate_vehicle_context()` is invoked, internal sample history, `latest_by_pid`, and `latest_successful_by_pid` are immediately cleared to prevent cross-vehicle telemetry contamination.

---

## 13. Reconnect Behavior

- **Controlled Bounded Reconnection**: `reconnect(max_attempts=3, timeout=2.0)` uses exponential backoff (0.2s, 0.4s, 0.8s) with non-blocking stop event cancellation.
- **Adapter Verification Probe**: Successfully reconnecting re-verifies communication with an initial probe query (`010C`) over `self.adapter.send_command`.
- **Single Authority Preserved**: Reconnection transitions the existing worker thread back to `LIVE_RUNNING` without spawning duplicate workers.

---

## 14. Shutdown Behavior

- **Graceful Resource Disposal**: Integrated with `ShutdownCoordinator`.
- **Cooperative Join**: Worker threads and persistence threads are stopped via threading events and joined within bounded timeouts (`timeout=2.0s`).
- **Zero Dangling Handles**: All serial handles and database locks are cleanly released.

---

## 15. Tests & Validation Results

Automated test suite `test_phase_k3.py` was executed on the Windows host with Python 3.14:

| Test Identifier | Category | Invariant Verified | Result |
|---|---|---|---|
| `test_a` | Runtime Start | Clean initialization and transition to `LIVE_RUNNING` | **PASSED** |
| `test_b` | Runtime Stop | Clean termination, thread join, and transition to `LIVE_STOPPED` | **PASSED** |
| `test_c` | Lifecycle Transitions | Valid transition matrix and safe restartability | **PASSED** |
| `test_d` | UI Thread Blocking | `start()` returns in < 20ms without blocking caller | **PASSED** |
| `test_e` | Single Authority | Exactly one worker thread per acquisition session | **PASSED** |
| `test_f` | Duplicate Start | Repeated `start()` calls rejected safely | **PASSED** |
| `test_g` | Cache Ingestion | Valid observations enter `data_cache` and `sensor_history` | **PASSED** |
| `test_h` | Failed Sample Semantics | `NO DATA` produces `value=None` (strictly zero fake zeros) | **PASSED** |
| `test_i` | Timeout Semantics | Timeouts classified as `STATUS_TIMEOUT` without history pollution | **PASSED** |
| `test_j` | NO DATA Semantics | `STATUS_NO_DATA` preserved with raw error payload | **PASSED** |
| `test_k` | NRC Semantics | ECU negative responses preserve `STATUS_NRC` | **PASSED** |
| `test_l` | DID Mismatch | Mismatched echo payload rejected safely | **PASSED** |
| `test_m` | Malformed Responses | Non-hex corrupted frames handled without worker exceptions | **PASSED** |
| `test_n` | Transport Failure | Physical adapter disconnect transitions to `LIVE_ERROR` | **PASSED** |
| `test_o` | Bounded History | History buffer strictly capped at `history_maxlen` | **PASSED** |
| `test_p` | Freshness Behavior | Aging values detected as stale; freshness restored on valid read | **PASSED** |
| `test_q` | Monotonic Timestamps | Observation timestamps monotonically advance | **PASSED** |
| `test_r` | Multi-ECU Separation | Observations retain distinct ECU contexts (`ECM`, `TCM`) | **PASSED** |
| `test_s` | Vehicle Identity | Vehicle context switch flushes stale telemetry caches | **PASSED** |
| `test_t` | J-3 Persistence | Raw acquisitions written asynchronously to SQLite backend | **PASSED** |
| `test_u` | Failure Isolation | Storage backend exceptions do not kill physical acquisition | **PASSED** |
| `test_v` | Bounded Backpressure | Saturated persistence buffer drops excess samples without stall | **PASSED** |
| `test_w` | Controlled Reconnect | Bounded reconnect re-establishes connection and probes adapter | **PASSED** |
| `test_x` | Graceful Shutdown | `ShutdownCoordinator` cleanly stops runtime and releases adapter | **PASSED** |
| `test_y` | Resource Safety | Zero worker thread leaks or unjoined thread handles | **PASSED** |
| `test_z` | Command Serialization | Concurrent commands serialized over adapter `_serial_lock` | **PASSED** |
| `test_aa` | Safety Gate Policy | Prohibited services (04, 14, 2E, 27, 2F, 34-37) blocked with `STATUS_NRC` | **PASSED** |
| `test_ab` | Intelligence Consumers | F-3 / H / I engines receive trusted validated observations | **PASSED** |
| `test_ac` | Direct Bypass Rejection | Intelligence consumers have no raw physical I/O handles | **PASSED** |
| `test_ad` | K-1 Regression | Non-blocking `connect_async` verified | **PASSED** |
| `test_ae` | K-2 Regression | Truthful capability reporting and smoke test verified | **PASSED** |
| `test_af` | J-1/J-6 Regression | Multi-ECU failure isolation verified | **PASSED** |

**Summary: 32 / 32 PASSED in 5.700s (0 failures, 0 errors).**

---

## 16. Performance Measurements

Synthetic benchmarks executed on the Windows host (Python 3.14 on Windows 11):

| Benchmark Measurement | Measured Value | Unit |
|---|---|---|
| Acquisition Loop Dispatch Overhead (Mock UART) | **0.0451** | ms / sample (45.1 µs) |
| C-Layer Sensor Cache Update Cost | **0.0006** | ms / update (0.6 µs) |
| Bounded Sensor History Append Cost | **0.0002** | ms / append (0.2 µs) |
| Persistence Queue Enqueue Cost (`queue.put_nowait`) | **0.0018** | ms / op (1.8 µs) |
| SQLite Raw Acquisition Persist Write Cost | **0.0313** | ms / write (31.3 µs) |
| Bounded Queue Saturation Drop (100 inserts @ 10 cap) | **0.1089** | ms total (90 dropped, O(1) non-blocking) |

---

## 17. Physical Hardware Validation Status

> **Physical Windows + ELM327 USB Hardware Validation: NOT PERFORMED**
> 
> Although PySerial is verified installed on the host and the serial integration architecture was validated against deterministic UART test doubles, **no physical ELM327 USB dongle or live vehicle OBD-II port is currently connected** to the test system.
> In strict accordance with architectural safety rules, physical hardware testing is explicitly recorded as **NOT PERFORMED**. No mock execution has been fabricated as real physical validation.

---

## 18. Known Limitations

1. **Physical Baud Rate**: Real ELM327 hardware is constrained by the physical baud rate (standard 38400 baud, ~15-30 PID queries per second depending on vehicle CAN bus latency). The runtime scheduler drift compensation accommodates this, but physical polling rates cannot exceed physical UART limits.
2. **Standard OBD Mode 01 vs Manufacturer Extended DIDs**: Mode 01 queries are standard 2-byte responses; manufacturer-specific Mode 22 multi-byte frames require ISO-TP reassembly provided by `extended_did.py`.
3. **Database Write Cadence on Heavy Multi-PID Streams**: Very high sample rates with thousands of continuous observations may generate storage load; the bounded queue backpressure protects physical acquisition by dropping unpersisted samples when storage capacity is constrained.
