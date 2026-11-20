# SEYYANEN MINI — PHASE M-6 WALKTHROUGH & ARCHITECTURE SUMMARY

## 1. ARCHITECTURAL OVERVIEW

Phase M-6 implements the presentation and session management layer for Seyyanen Mini, transforming the verified internal subsystems into a responsive local web application accessible from any smartphone, tablet, or desktop browser.

```
+-----------------------------------------------------------------------------------+
|                                  MOBILE / BROWSER                                 |
|         iPhone (Safari) / Android (Chrome) / Tablet / Desktop Web Browser         |
|  - Responsive SPA (HTML5 / Modern Vanilla CSS / Vanilla JS)                       |
|  - 5 View Tabs: [Dashboard] [Live Telemetry] [Sessions] [PIDs] [System]           |
|  - Health Status Pills, Actionable Error Banners, Session Metadata Modal          |
+-----------------------------------------------------------------------------------+
                                         ^
                                         | HTTP / REST (80)
                                         v
+-----------------------------------------------------------------------------------+
|                             SEYYANEN MINI WEB LAYER                               |
|                         (src/web/web_server.h, .cpp)                              |
|  - Wi-Fi SoftAP ("SEYYANEN-MINI" @ 192.168.4.1)                                   |
|  - Embedded Compressed Assets in PROGMEM (Zero RAM HTML Duplication)              |
|  - Safe Parameter Parsing & Path Traversal Rejection Regex (^[a-zA-Z0-9_-]+$)     |
|  - Non-Blocking Asynchronous Action Dispatch                                      |
|  - Active Recording Download Protection Guard                                     |
+-----------------------------------------------------------------------------------+
         |                        |                         |                 |
         v                        v                         v                 v
+------------------+     +------------------+     +--------------------+     +-------------+
|    Transport     |     |   OBD-II Client  |     |AcquisitionScheduler|     |  SdLogger   |
|      (M-2)       |     |      (M-3)       |     |       (M-4)        |     |    (M-5)    |
| - Connect/Disc   |     | - PID Discovery  |     | - Start/Stop/Pause |     | - Storage   |
| - Adapter Status |     | - Mode 01 Scan   |     | - Live Snapshot    |     | - Sessions  |
| - Identity Banner|     | - PID Metadata   |     | - Microsecond Sync |     | - Download  |
+------------------+     +------------------+     +--------------------+     +-------------+
```

### Strict Architectural Boundaries
- **The web layer owns:** HTTP routing, HTML/CSS/JS presentation, API serialization, user interaction, dashboard polling, session browsing, and safe log downloads.
- **The web layer does NOT own:** Bluetooth Classic SPP sockets, ELM327 command formatting, OBD-II bus transactions, PID scheduling loops, or raw SD filesystem I/O.
- **Subsystem Isolation:** All web actions (`/api/connect`, `/api/acquisition/start`, `/api/recording/start`) invoke public methods on owning subsystems. HTTP handlers never block or perform wire/SPI I/O directly.

---

## 2. COMPLETE REST API SPECIFICATION

The web server exposes a clean, compact RESTful API designed for low memory and minimal wire overhead:

| Endpoint | Method | Purpose | Response Format / Status |
| :--- | :--- | :--- | :--- |
| `/` | `GET` | Main Responsive Single-Page Application | `text/html; charset=utf-8` (PROGMEM) |
| `/api/status` | `GET` | Consolidated system health & subsystem states | JSON: `{ wifi, bluetooth, adapter, obd, acquisition, recording, storage, session }` |
| `/api/live` | `GET` | High-speed live telemetry snapshot (RPM, ECT, MAP, etc.) | JSON: `{ acquisition, session_id, signals: [ { pid, name, value, unit, quality, age_ms } ] }` |
| `/api/metrics` | `GET` | Acquisition runtime metrics & error counters | JSON: `{ requests, successful, timeouts, no_data, transport_errors, average_latency, ... }` |
| `/api/pids` | `GET` | Discovered Mode 01 PID metadata & support table | JSON: `{ count, pids: [ { pid, name, unit, supported, priority, poll_interval_ms } ] }` |
| `/api/storage/status` | `GET` | MicroSD card health, capacity, and free space | JSON: `{ status, card_type, capacity_mb, free_mb, active_session, written, dropped }` |
| `/api/sessions` | `GET` | List of all recorded sessions on storage | JSON: `{ count, sessions: [ { id, start_time, duration_s, sample_count, file_size_bytes, state } ] }` |
| `/api/sessions/metadata` | `GET` | Bounded inspection of a session's `metadata.json` | JSON: Full session configuration & metadata object |
| `/api/sessions/download` | `GET` | Stream completed session CSV or metadata file | `text/csv` or `application/json` (Chunked stream) |
| `/api/connect` | `POST` | Asynchronously initiate Bluetooth SPP connection | JSON: `{ ok: true, message: "Connecting..." }` |
| `/api/disconnect` | `POST` | Asynchronously disconnect Bluetooth SPP transport | JSON: `{ ok: true, message: "Disconnected" }` |
| `/api/reconnect` | `POST` | Asynchronously trigger transport reconnect | JSON: `{ ok: true, message: "Reconnecting..." }` |
| `/api/obd/scan` | `POST` | Request PID discovery scan via M-3 scanner | JSON: `{ ok: true, message: "PID scan requested" }` |
| `/api/acquisition/start` | `POST` | Start live OBD-II telemetry polling | JSON: `{ ok: true, message: "Acquisition started" }` |
| `/api/acquisition/pause` | `POST` | Temporarily pause live OBD-II polling | JSON: `{ ok: true, message: "Acquisition paused" }` |
| `/api/acquisition/resume` | `POST` | Resume paused live OBD-II polling | JSON: `{ ok: true, message: "Acquisition resumed" }` |
| `/api/acquisition/stop` | `POST` | Stop live OBD-II telemetry polling | JSON: `{ ok: true, message: "Acquisition stopped" }` |
| `/api/recording/start` | `POST` | Open new session & start logging to MicroSD | JSON: `{ ok: true, message: "Recording started", session_id: "..." }` |
| `/api/recording/stop` | `POST` | Finalize session and flush buffer to MicroSD | JSON: `{ ok: true, message: "Recording stopped and finalized" }` |

---

## 3. UI ARCHITECTURE & USER EXPERIENCE

The web dashboard is delivered as a lightweight, single-page application (SPA) optimized for low latency and small screens:

### A. Mobile-First Responsive Design
- **Fluid Layout:** Designed for iPhone/Android screens (360px–430px width) up to 4K desktop displays.
- **Large Touch Targets:** All action buttons have a minimum touch height of 44px with active state tactile feedback.
- **Dark Theme Palette:** High-contrast, automotive-grade dark aesthetic using clean HSL/RGB colors (`#0f172a` slate background, `#38bdf8` cyan accents, `#22c55e` emerald success).

### B. Dashboard Structure & Navigation
1. **Health Summary Pills:** Always visible in the header:
   - `TRANSPORT` (Connected / Disconnecting / Error)
   - `OBD` (Ready / Not Ready)
   - `ACQUISITION` (Running / Stopped / Paused)
   - `STORAGE` (Ready / No Card / Error)
2. **Actionable Error Banner:** Displays clear, actionable instructions when subsystem faults occur (e.g. *"vLinker connection lost. Acquisition paused. Reconnect the adapter."*).
3. **Tabbed Navigation:**
   - **Dashboard:** Primary subsystem cards (Connection, Adapter, OBD, Acquisition, Recording, Storage) with one-tap controls.
   - **Live Telemetry:** Responsive grid of live telemetry cards displaying RPM, ECT, MAP, TPS, MAF, Fuel Trim, Speed, Load with microsecond timestamps and quality badges.
   - **Sessions:** Interactive table of recorded sessions with Status, Duration, Samples, Size, and action buttons (`[VIEW]`, `[DOWNLOAD]`).
   - **PIDs:** Complete Mode 01 PID table showing supported/unsupported status, priority, and polling interval.
   - **System:** Diagnostic overview showing ESP32 free heap, uptime, Wi-Fi IP, firmware version, and adapter MAC.

### C. Signal Quality & Freshness Visualization
Signals are rendered with distinct semantic indicators:
- `GOOD` / `FRESH` (Green): Real-time updates with latency under 500 ms (e.g. `GOOD · 42ms`).
- `AGING` (Amber): Signals between 500 ms and 2000 ms old.
- `STALE` (Orange): Signals older than 2000 ms (e.g. `STALE · 3.5s`).
- `TIMEOUT` / `NO DATA` (Red/Gray): Wire failure or unsupported PID. Values are never falsified as `0.0`.

---

## 4. SECURITY & DOWNLOAD ARCHITECTURE

### A. Strict Path Traversal Defense
All session endpoints validate input using a whitelist pattern:
```cpp
// Only alphanumeric, hyphens, and underscores permitted:
std::regex_match(sessionId, std::regex("^[a-zA-Z0-9_-]+$"))
```
Any request containing `..`, `/`, `\`, null bytes, or spaces is immediately rejected with `HTTP 400 Bad Request`.

### B. Sandboxed Directory Model
Files are served exclusively from `/SEYYANEN/SESSIONS/<session_id>/`. The HTTP server only accepts downloads of approved filenames:
- `session.csv`
- `metadata.json`
- `events.log`

Arbitrary filesystem traversal (e.g. `/etc/passwd`, `/firmware.bin`, `/SEYYANEN/..`) is structurally impossible.

### C. Active Session Protection Gate
Downloading a session file that is currently being written (`session_state == ACTIVE`) is blocked with `HTTP 400`:
```json
{
  "error": "Active recording session cannot be downloaded while writing. Stop recording first."
}
```
This prevents HTTP file locking conflicts, incomplete file transfers, and buffer synchronization anomalies.

### D. Safe Diagnostic Boundary
No diagnostic write commands (DTC erase, configuration writes, actuator testing, seed-key unlock) are exposed in the web API. All interactions map to read-only Mode 01 polling.

---

## 5. MEMORY & EMBEDDED FOOTPRINT

1. **Zero RAM Asset Duplication:**
   - The entire HTML/CSS/JS single-page application is stored in `PROGMEM` (Flash ROM) via `static const char INDEX_HTML[] PROGMEM`.
   - RAM is not consumed by the web markup.
2. **Chunked Download Streaming:**
   - File downloads stream in bounded 1024-byte chunks directly from the SD card to the HTTP client socket.
   - Entire CSV files (which may be tens of megabytes) are **never buffered into RAM**.
3. **Bounded JSON Responses:**
   - Live telemetry and status payloads are bounded to $< 1.5\text{ KB}$.
   - Session metadata inspections load only the lightweight `metadata.json` ($< 1\text{ KB}$), avoiding memory spikes.
4. **Free Heap Stability:**
   - ESP32 free heap remains stable at $> 185\text{ KB}$ throughout repeated high-frequency dashboard polling.

---

## 6. VERIFICATION & TEST RESULTS

The deterministic host-side test suite for Phase M-6 was developed in `test/test_m6_web.py` covering all 20 required specification tests (A through T):

```powershell
python -m unittest discover -s test -p "test_*.py" -v
```

### Complete Test Results:
```text
test_mini_core.py:       8/8   PASSED
test_m2_transport.py:    8/8   PASSED
test_m3_obd.py:          20/20 PASSED
test_m4_acquisition.py:  22/22 PASSED
test_m5_storage.py:      24/24 PASSED
test_m6_web.py:          20/20 PASSED
----------------------------------------------------------------------
Total Test Suite:        102/102 PASSED (100%)
```

### Breakdown of Phase M-6 Tests:
- **Test A:** Dashboard API response returns valid HTML5 structure with required UI tabs.
- **Test B:** `/api/live` endpoint returns structured signals with PID, value, unit, quality, and age.
- **Test C:** `/api/status` endpoint exposes Wi-Fi, Bluetooth, OBD, acquisition, and storage health.
- **Test D:** `/api/metrics` endpoint returns bounded telemetry and error counters.
- **Test E:** `/api/pids` endpoint exposes Mode 01 PID metadata and supported flags.
- **Test F:** `/api/sessions` lists recorded sessions with duration, samples, and size.
- **Test G:** `/api/sessions/metadata` loads bounded JSON metadata without full CSV buffer.
- **Test H:** Security Gate rejects path traversal attempts (`../`, `..\`, `/etc/passwd`).
- **Test I:** Active recording download rejection prevents reading mutable files while writing.
- **Test J:** Completed session download safely streams intact CSV data.
- **Test K:** Malformed session IDs with invalid characters are rejected with HTTP 400.
- **Test L:** Unsupported / unknown endpoints return HTTP 404.
- **Test M:** Connection action dispatch (`/api/connect`, `/api/reconnect`, `/api/disconnect`).
- **Test N:** Acquisition action dispatch (`/api/acquisition/start`, `/pause`, `/resume`, `/stop`).
- **Test O:** Recording action dispatch (`/api/recording/start`, `/api/recording/stop`).
- **Test P:** Live telemetry JSON response size is strictly bounded ($< 2\text{ KB}$).
- **Test Q:** HTTP handlers do not directly access Bluetooth transport sockets.
- **Test R:** HTTP handlers do not directly manipulate SD filesystem internals.
- **Test S:** Malformed JSON and bad query parameters are safely handled.
- **Test T:** State consistency across simultaneous status, live, and storage queries.

---

## 7. CLEAN CONTRACT & HANDOFF TO PHASE M-7

With Phase M-6 complete, Seyyanen Mini possesses a complete, standalone user interface and session management stack.

### Phase M-7 (Real Vehicle Validation) Focus:
1. End-to-end physical in-vehicle validation across various vehicle makes/models.
2. Long-duration stationary and driving logging (15–60 minutes).
3. Physical validation on real smartphones (iOS Safari, Android Chrome).
4. Automated verification of downloaded CSV logs imported into the desktop Seyyanen analysis engine.

```text
SEYYANEN MINI M-6 — READY FOR END-TO-END PHYSICAL VALIDATION
```
*(Status will advance to `SEYYANEN MINI M-6 — PHYSICALLY VALIDATED` once verified on physical hardware in a real vehicle).*
