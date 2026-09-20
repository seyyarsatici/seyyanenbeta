# SEYYANEN MINI — PHASE M-5 WALKTHROUGH & ARCHITECTURE SUMMARY

## 1. ARCHITECTURAL ROLE & FLOW

Phase M-5 turns the live acquisition data from Phase M-4 into persistent, corruption-resilient session logs on MicroSD storage.

```
+-------------------------------------------------------------+
|                VLinkerBluetoothTransport (M-2)              |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                     Elm327Client (M-3)                      |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                      Obd2Client (M-3)                       |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                Acquisition Scheduler (M-4)                  |
|  - Strictly serialized wire I/O (One transaction at a time) |
|  - Monotonic microsecond timestamps                         |
|  - Quality evaluation & zero-resistance                     |
+-------------------------------------------------------------+
                              |
                     MeasurementSample
                              |
                              v
+-------------------------------------------------------------+
|                      SdLogger (M-5)                         |
|  - MicroSD Hardware Lifecycle & Card Health Monitoring      |
|  - Session Directory & File Management                      |
|  - Bounded 1 KB In-Memory Write Buffer                      |
|  - Periodic (2000 ms) & Threshold Flush Policy              |
|  - Power-Loss Awareness (ACTIVE -> COMPLETED marker)        |
|  - Failure Sample Preservation (Failure != 0.0)             |
|  - Raw Response Escaping & Evidence Preservation            |
|  - Sanitized Session Listing & Download Sandboxing          |
+-------------------------------------------------------------+
             /                                 \
            v                                   v
+------------------------+          +-------------------------+
|   microSD Filesystem   |          |      Web Server         |
|   /SEYYANEN/SESSIONS/  |          |  /api/storage/status    |
|   ├── session.csv      |          |  /api/sessions          |
|   ├── metadata.json    |          |  /api/sessions/download |
|   └── events.log       |          |  [START/STOP RECORDING] |
+------------------------+          +-------------------------+
```

---

## 2. KEY ARCHITECTURAL PRINCIPLES IMPLEMENTED

### A. Separation of Authority
- M-4 remains the **sole acquisition authority**.
- MicroSD access is strictly isolated behind `SdLogger`. The web server and acquisition scheduler never open log files directly.
- If storage is unmounted or fails during driving, **live acquisition continues uninterrupted** in memory. A storage fault does not freeze or crash the vehicle acquisition engine.

### B. Full Forensic Fidelity & Zero-Resistance
- Every sample preserves:
  1. `raw_response`: exact adapter response string, safely escaped and double-quoted.
  2. `decoded_value`: floating-point value in standard units.
  3. `status` & `quality`: technical status (`VALID`, `TIMEOUT`, `NO_DATA`, etc.).
  4. `latency_us`: round-trip time in microseconds.
- **Zero-Resistance Rule**: Failed requests leave `decoded_value` empty (consecutive commas `,,`). Zero is **never** fabricated.

### C. Bounded Write Buffering & Deterministic Flush
- Writes accumulate in a fixed 1024-byte in-memory buffer (`_writeBuffer`) to eliminate micro-writes over SPI.
- Flushes occur deterministically:
  1. When buffer capacity is reached ($\ge 1024$ bytes).
  2. Periodically every 2000 ms (`SEYYANEN_SD_FLUSH_INTERVAL_MS`).
  3. Explicitly upon `stopSession()` or when downloading an active session.

### D. Power-Loss Recovery & Session Lifecycle
- Upon session creation, `metadata.json` is written with `session_state: "ACTIVE"`.
- Upon clean stop, `metadata.json` is updated to `session_state: "COMPLETED"`.
- On boot, `scanIncompleteSessions()` discovers any session directories remaining in `ACTIVE` state (caused by sudden automotive power cut) and marks them `session_state: "RECOVERABLE_INCOMPLETE"`. The CSV data up to the last flush is preserved.

### E. Download Security & Active Session Protection
- Session IDs are strictly validated (`[a-zA-Z0-9_-]`). Any attempt to pass directory traversal (`../`, `..\`, `/`) is blocked immediately.
- Only three approved filenames (`session.csv`, `metadata.json`, `events.log`) can be opened for download.
- Active sessions are protected: if a user downloads an active session, the current buffer is flushed before streaming so no records are lost.

---

## 3. FILES CREATED & MODIFIED

| File | Status | Description |
| :--- | :--- | :--- |
| [include/mini_config.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/include/mini_config.h) | Modified | Added MicroSD VSPI pinouts, 20MHz SPI frequency, 1KB write buffer, flush intervals, and directory paths. |
| [include/mini_types.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/include/mini_types.h) | Modified | Defined `StorageStatus`, `SessionState`, `StorageInfo`, `SessionMetadata`, `SessionSummary`, `StorageMetrics`, and string conversion helpers. |
| [src/storage/sd_logger.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/storage/sd_logger.h) | Modified | Declared Phase M-5 `SdLogger` class with complete lifecycle, buffered writes, and safe download streaming. |
| [src/storage/sd_logger.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/storage/sd_logger.cpp) | Modified | Implemented SPI card initialization, CSV row serialization with zero-resistance, metadata persistence, incomplete session recovery, and session listing. |
| [src/acquisition/scheduler.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/scheduler.h) | Modified | Added forward declaration and logger hook (`setLogger`). |
| [src/acquisition/scheduler.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/acquisition/scheduler.cpp) | Modified | Forwarded sample capture, pause/resume events, and lifecycle changes to `SdLogger`. |
| [src/web/web_server.h](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/web/web_server.h) | Modified | Declared Phase M-5 storage, session listing, metadata, and download REST endpoints. |
| [src/web/web_server.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/web/web_server.cpp) | Modified | Updated HTML/CSS/JS dashboard with storage metrics, recording controls, session download table, and download streaming. |
| [src/main.cpp](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/src/main.cpp) | Modified | Initialized `SdLogger`, bound logger to `acqScheduler` and `webServer`, and added `sdLogger.update()` in `loop()`. |
| [log_format.md](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/log_format.md) | Created | Complete PC Seyyanen import specification (directory layout, CSV schema, JSON metadata, failure handling). |
| [test/test_m5_storage.py](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/test/test_m5_storage.py) | Created | Deterministic host unit test suite covering tests A through X (24 tests). |
| [m5_hardware_walkthrough.md](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m5_hardware_walkthrough.md) | Created | Physical test guide for real ESP32 + SPI MicroSD card + vehicle. |
| [m5_walkthrough.md](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m5_walkthrough.md) | Created | Architecture walkthrough, test results, and M-6 handoff contract. |
| [README.md](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/README.md) | Modified | Updated test commands, test counts (82/82), and status badge. |

---

## 4. VERIFICATION & TEST RESULTS

All 24 specification tests (A through X) and regression test suites for all phases were executed deterministically:
```powershell
python -m unittest discover -s seyyanen_mini/test -p "test_*.py" -v
```

```text
test_mini_core.py:       8/8   PASSED
test_m2_transport.py:    8/8   PASSED
test_m3_obd.py:          20/20 PASSED
test_m4_acquisition.py:  22/22 PASSED
test_m5_storage.py:      24/24 PASSED
----------------------------------------------------------------------
Total Test Suite:        82/82 PASSED (100%)
```

### Breakdown of Phase M-5 Tests:
- **Test A:** SD mount success, base directory creation.
- **Test B:** Card missing handled gracefully without crashing.
- **Test C:** Session folder, CSV, metadata, and event log creation.
- **Test D:** Distinct session ID uniqueness without directory collision.
- **Test E:** CSV header format conforms precisely to specification.
- **Test F:** Measurement sample serialization into CSV row.
- **Test G:** Raw response quoting and escaping.
- **Test H:** Failed samples leave `decoded_value` empty (no fake zero 0.0).
- **Test I:** Metadata JSON creation with active state and UNKNOWN vehicle status.
- **Test J:** Supported PID metadata persistence.
- **Test K & L:** In-memory buffered writes and explicit flush policy.
- **Test M:** Session finalization updates metadata to `COMPLETED`.
- **Test N:** Unfinalized sessions on boot marked `RECOVERABLE_INCOMPLETE`.
- **Test O & P:** SD write failure and disk full conditions handled with explicit error states.
- **Test Q:** In-memory write buffer strictly bounded to 1024 bytes.
- **Test R:** Dropped samples tracked in `samples_dropped` metric.
- **Test S:** Session listing without reading entire files into RAM.
- **Test T:** Active session protection flushes buffer prior to file read.
- **Test U:** Security Gate rejects path traversal attempts (`../`, `..\`, `/etc/passwd`).
- **Test V:** 64-bit timestamps and long-session sample counts supported.
- **Test W:** Microsecond timestamps preserved with full resolution.
- **Test X:** Download path validation permits only approved filenames.

---

## 5. MEMORY & EMBEDDED FOOTPRINT CONSIDERATIONS

1. **Static Memory Footprint:**
   - Write buffer: 1024 bytes.
   - Session metadata struct: ~380 bytes.
   - Listing summary buffer: ~32 entries $\times$ 128 bytes $\approx 4\text{ KB}$.
   - Total RAM consumed by M-5: $< 8\text{ KB}$, leaving $> 190\text{ KB}$ free heap on ESP32.
2. **Deterministic SPI Writes:**
   - Writes occur in chunks of up to 1024 bytes, reducing SPI bus contention and eliminating blocking on individual rows.
3. **Session Listing Scalability:**
   - Listing iterates directories and reads only `metadata.json` (or stat file size), never buffering multi-megabyte `session.csv` files into RAM.

---

## 6. CLEAN CONTRACT FOR PHASE M-6 (WEB & SESSION MANAGEMENT)

Phase M-6 owns enhanced web dashboard session management, offline analysis, and wireless session export.

Phase M-6 consumes:
- `SdLogger::listSessions(outSummaries, maxCount)`
- `SdLogger::readSessionMetadata(sessionId, outJson)`
- `SdLogger::openSessionFileForRead(sessionId, filename)`
- `SdLogger::getStorageInfo(outInfo)`
- `SdLogger::getStorageMetrics(outMetrics)`
- Phase M-6 has **no direct coupling** to low-level SPI or FAT filesystem operations.

---

## 7. PHYSICAL VALIDATION STATUS

- Software Implementation: **COMPLETE**
- Deterministic Host Tests: **82/82 PASSING**
- Hardware Walkthrough Guide: **PUBLISHED** (`m5_hardware_walkthrough.md`)
- PC Import Specification: **PUBLISHED** (`log_format.md`)

```text
SEYYANEN MINI M-5 — READY FOR PHYSICAL SD LOGGING TEST
```
*(Status will advance to `SEYYANEN MINI M-5 — PHYSICALLY VALIDATED` upon vehicle driving session recording and PC CSV import verification).*
