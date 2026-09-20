# SEYYANEN MINI — PHASE M-4 WALKTHROUGH & ARCHITECTURE SUMMARY

## 1. ARCHITECTURAL ROLE & FLOW

Phase M-4 turns the verified OBD/PID layer from Phase M-3 into a deterministic live acquisition engine.

```
+-------------------------------------------------------------+
|                VLinkerBluetoothTransport (M-2)              |
|        [Strict Transport Authority, SPP Client, Keepalive]  |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                     Elm327Client (M-3)                      |
|          [AT Command Protocol, Reset, Prompt Handling]      |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                      Obd2Client (M-3)                       |
|           [Mode 01 Dispatch, Normalized Response]           |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|             Supported PID Metadata Table (M-3)              |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                Acquisition Scheduler (M-4)                  |
|  - Lifecycle State Machine (IDLE -> RUNNING -> PAUSED...)   |
|  - Deterministic Due-Time Polling & Fairness Metric        |
|  - Strictly Serialized Wire I/O (One Transaction at a Time)|
|  - Lock-Free OBD I/O (FreeRTOS Mutex never held across wire)|
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                  MeasurementSample (M-4)                    |
|  - Monotonic timestamp (us), Raw response, Decoded value    |
|  - Latency tracking (us), Quality grade, Freshness decay    |
+-------------------------------------------------------------+
             /                                 \
            v                                   v
+------------------------+          +-------------------------+
|  Bounded Ring Buffer   |          |  Live Snapshot Engine   |
|  (256 Samples, FIFO)   |          |  (Lightweight Web State)|
+------------------------+          +-------------------------+
            |                                   |
            v                                   v
+------------------------+          +-------------------------+
| Phase M-5 SD Logging   |          |  Web REST API & UI      |
| (Handoff Ready)        |          |  /api/live, /api/status |
+------------------------+          +-------------------------+
```

---

## 2. KEY ARCHITECTURAL PRINCIPLES IMPLEMENTED

### A. Strict Serialization & Lock-Free Wire I/O
- Exactly **ONE** active OBD request is on the wire at any time. No overlapping requests (`010C` and `010D` are never concurrent).
- **Concurrency Rule:** FreeRTOS mutexes are **NEVER** held across blocking OBD requests (`_obdClient.request(...)`). The web server can query `/api/live` at 10 Hz without blocking or experiencing HTTP timeouts. Mutex acquisition is restricted to sub-millisecond memory updates.

### B. Starvation Prevention (Fairness Metric)
- With polling profiles ranging from 120ms (FAST: RPM, TPS) to 350ms (MEDIUM: MAP, Speed) and 1200ms (SLOW: ECT, IAT), a naive priority loop would starve slow PIDs.
- Implemented an **urgency metric**:
  $$\text{urgency} = \frac{\text{elapsed\_us} \times 1000}{\text{interval\_us}}$$
  The due PID with the largest urgency ratio is scheduled next, mathematically preventing starvation.

### C. Zero-Resistance Quality Model (Failure $\ne$ 0.0)
- Failures (e.g. `TIMEOUT`, `NO_DATA`, `MALFORMED`) do **NOT** overwrite the signal value with zero.
- `last_valid_value` is preserved. If RPM was 1800 rpm and the next frame times out, the system reports `last_valid_value = 1800`, `quality = TIMEOUT`, `freshness = AGING/STALE`. It does not report RPM = 0 as if the engine stalled.

### D. Explicit Freshness Decay
Every signal tracks elapsed time since the last successful OBD response:
- `FRESH`: $\le 600\text{ ms}$
- `AGING`: $600\text{ ms} < \text{age} \le 2500\text{ ms}$
- `STALE`: $> 2500\text{ ms}$
- `NEVER_VALID`: No successful response recorded yet.

### E. Bounded Ring Buffer & Session Identity
- Fixed capacity of 256 `MeasurementSample` records. Oldest samples are evicted deterministically upon overflow with zero heap churn.
- Every acquisition run is tagged with a unique monotonic session ID: `MINI-SESSION-000001`, `MINI-SESSION-000002`, etc. Sequence numbers reset with each session.

---

## 3. FILES CREATED & MODIFIED

| File | Status | Description |
|------|--------|-------------|
| [mini_config.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/include/mini_config.h) | Modified | Added fast/medium/slow intervals, freshness thresholds, ring buffer capacity |
| [mini_types.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/include/mini_types.h) | Modified | Defined `AcquisitionState`, `QualityGrade`, `FreshnessState`, `MeasurementSample`, `AcquisitionFrame`, `LiveSignal`, `LiveSnapshot`, `AcquisitionMetrics` |
| [quality.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/quality.h) | Created | Quality & Freshness evaluation engine header |
| [quality.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/quality.cpp) | Created | Implemented non-zero fallback quality grading & freshness state transitions |
| [sample.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/sample.h) | Created | Thread-safe bounded ring buffer (256 samples) header |
| [sample.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/sample.cpp) | Created | Implemented bounded ring buffer with `push`, `getRecent`, `getSince` |
| [scheduler.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/scheduler.h) | Created | Acquisition Scheduler class header with FreeRTOS mutexes |
| [scheduler.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/scheduler.cpp) | Created | Implemented deterministic polling, urgency fairness, lock-free I/O, lifecycle state machine |
| [web_server.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/web/web_server.h) | Modified | Declared Phase M-4 REST endpoints (`/api/live`, `/api/metrics`, `/api/acquisition/*`) |
| [web_server.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/web/web_server.cpp) | Modified | Inlined modern live acquisition dashboard in PROGMEM, implemented REST handlers |
| [main.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/main.cpp) | Modified | Connected `AcquisitionScheduler` and `SampleRingBuffer` into system boot & non-blocking `loop()` |
| [test_m4_acquisition.py](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/test/test_m4_acquisition.py) | Created | Deterministic test suite covering tests A through V |
| [m4_hardware_walkthrough.md](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m4_hardware_walkthrough.md) | Created | Vehicle validation procedure for KOEO & KOER idle telemetry |
| [m4_walkthrough.md](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m4_walkthrough.md) | Created | Architecture walkthrough, testing results, and M-5 handoff contract |

---

## 4. VERIFICATION & TEST RESULTS

All 22 specification tests (A through V) plus existing tests for M-1, M-2, and M-3 were executed deterministically:
```bash
python -m unittest discover -s seyyanen_mini/test -p "test_*.py" -v
```

**Results:**
- `test_mini_core.py`: 8/8 PASSED
- `test_m2_transport.py`: 8/8 PASSED
- `test_m3_obd.py`: 20/20 PASSED
- `test_m4_acquisition.py`: 22/22 PASSED
- **Total Test Suite:** **58/58 PASSED (100%)**

### Detailed Breakdown of Phase M-4 Tests:
- **Test A:** Scheduler due-time calculation from microsecond timestamps.
- **Test B:** Priority-based intervals (Fast 120ms, Medium 350ms, Slow 1200ms).
- **Test C:** Starvation prevention via proportional urgency ratio.
- **Test D & E:** Strictly serialized OBD requests; max concurrent requests $\equiv 1$.
- **Test F:** Monotonically increasing microsecond timestamps.
- **Test G:** `AcquisitionFrame` grouping sequential samples with distinct individual timestamps.
- **Test H & I:** Freshness evaluation (`FRESH` $\to$ `AGING` $\to$ `STALE` $\to$ `NEVER_VALID`).
- **Test J:** `TIMEOUT` handling retains last valid value (zero-resistance verification).
- **Test K:** `NO_DATA` handled with explicit quality grade.
- **Test L:** Transport disconnection escalates scheduler from `RUNNING` to `PAUSED`.
- **Test M:** Single PID error does not kill the acquisition session.
- **Test N & O:** Ring buffer capacity bounded at 256; oldest samples evicted deterministically.
- **Test P:** Monotonic session separation (`MINI-SESSION-000001`, `000002`).
- **Test Q:** Metrics tally totals, successes, errors, and running latency.
- **Test R:** Backpressure bounds execution to 1 request per scheduler step; no unbounded backlog.
- **Test S:** Complete state machine (`IDLE` $\to$ `RUNNING` $\to$ `PAUSED` $\to$ `RUNNING` $\to$ `STOPPED`).
- **Test T & U:** Live snapshot and Web REST API return consistent state without direct Bluetooth access.
- **Test V:** FreeRTOS shared-state mutex is **never** held during blocking OBD wire transactions.

---

## 5. MEMORY & EMBEDDED FOOTPRINT CONSIDERATIONS

1. **Zero Dynamic Allocation in Steady State:**
   - Ring buffer is statically allocated (`256 * sizeof(MeasurementSample)` $\approx 78\text{ KB}$).
   - Live snapshot is a single flat struct (`sizeof(LiveSnapshot)` $\approx 2.5\text{ KB}$).
   - Web server sends small, structured JSON payloads ($< 1\text{ KB}$ per `/api/live` call).
2. **ESP32 Free SRAM Margin:**
   - ESP32 has ~320 KB internal SRAM available for heap.
   - Total static allocation for M-4 subsystems is under 85 KB, leaving $> 200\text{ KB}$ of continuous headroom for Wi-Fi and Bluetooth stacks.
3. **No History Duplication:**
   - Web endpoint `/api/live` only returns the current `LiveSnapshot`, avoiding full ring buffer serialization over HTTP.

---

## 6. CLEAN CONTRACT FOR PHASE M-5 (MICROSD PERSISTENCE)

Phase M-5 owns high-speed microSD persistence. The M-4 architecture cleanly decouples acquisition from storage:

1. **Data Structures Consumed by M-5:**
   - `MeasurementSample`: Contains complete schema (`session_id`, `sequence`, `timestamp_us`, `pid`, `raw_response`, `normalized_bytes`, `decoded_value`, `unit`, `quality`, `latency_us`).
   - `AcquisitionFrame`: Contains temporal cycle bounds (`cycle_start_us`, `cycle_end_us`, `samples[]`).
2. **Access Interfaces for M-5:**
   - `SampleRingBuffer::getSince(last_written_us)`: Allows the SD writer task to pull batches of pending samples.
   - `SampleRingBuffer::getRecent(n)`: Retrieves newest samples for cache flush.
   - `AcquisitionScheduler::getSessionId()`: Provides session filename prefix (e.g. `/sdcard/sessions/SESSION_000001.csv`).
3. **Zero Transport Knowledge:**
   - M-5 will have **no direct dependency** on `BluetoothClassic`, `Elm327Client`, or `Obd2Client`.
   - M-5 will simply observe the ring buffer and session lifecycle events.

---

## 7. PHYSICAL VALIDATION STATUS

- Software Implementation: **COMPLETE**
- Deterministic Host Tests: **58/58 PASSING**
- Hardware Walkthrough Guide: **PUBLISHED** (`m4_hardware_walkthrough.md`)

```
SEYYANEN MINI M-4 — READY FOR PHYSICAL LIVE ACQUISITION TEST
```
*(Status will advance to `SEYYANEN MINI M-4 — PHYSICALLY VALIDATED` upon live in-vehicle telemetry observation).*
