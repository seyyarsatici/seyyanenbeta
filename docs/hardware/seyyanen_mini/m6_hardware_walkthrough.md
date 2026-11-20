# SEYYANEN MINI — PHASE M-6 PHYSICAL HARDWARE TEST WALKTHROUGH

**Target Setup:**
- Device: ESP32-WROOM-32D (Dual-Core 240 MHz, 520 KB SRAM)
- Storage: SPI MicroSD Card Module (FAT32 formatted card, e.g. 16GB / 32GB)
- OBD-II Adapter: vLinker MC+ Bluetooth Classic (SPP)
- Vehicle: OBD-II compliant passenger car (12V OBD-II DLC port)
- Client Devices: iPhone (Safari / Chrome), Android Phone (Chrome), Tablet, or Desktop Browser
- Firmware Phase: Phase M-6 Web UI & Session Management

---

## 1. HARDWARE & NETWORK TOPOLOGY

```
+------------------+         Bluetooth SPP        +--------------------+
|  vLinker MC+     | <=========================> |  ESP32-WROOM-32D   |
|  (OBD-II Port)   |                             |  - SoftAP: 192.168.4.1
+------------------+                             |  - SPI MicroSD Card
                                                 +--------------------+
                                                           ^
                                             Wi-Fi AP      |
                                        "SEYYANEN-MINI"    | (HTTP 80)
                                                           v
                                                 +--------------------+
                                                 | Mobile / PC Browser|
                                                 |  - Safari / Chrome |
                                                 |  - Responsive SPA  |
                                                 +--------------------+
```

| MicroSD Pin | ESP32 GPIO | Description |
| :--- | :--- | :--- |
| **CS** | **GPIO 5** | SPI Chip Select |
| **MOSI** | **GPIO 23** | SPI Master Out Slave In |
| **MISO** | **GPIO 19** | SPI Master In Slave Out |
| **SCK** | **GPIO 18** | SPI Clock |
| **VCC** | **3.3V / 5V** | Power (matches module rating) |
| **GND** | **GND** | Common Ground |

---

## 2. PRE-TEST SAFETY GATES & PREREQUISITES

> [!IMPORTANT]
> - Vehicle must be stationary in **PARK / NEUTRAL** with handbrake firmly engaged.
> - Testing is conducted in stationary Key-On Engine-Off (KOEO) and Key-On Engine-Running (KOER) idle states.
> - The web application communicates strictly through safe, read-only public subsystem APIs. No destructive diagnostic operations (DTC clearing, coding, actuator tests) exist in Seyyanen Mini M-6.
> - The Wi-Fi SoftAP operates in offline mode without requiring internet access.

---

## 3. STEP-BY-STEP PHYSICAL VALIDATION PROCEDURE

### Step 1: Flash Firmware & Connect to Wi-Fi AP
1. Build and upload firmware to the ESP32:
   ```bash
   pio run -e esp32dev -t upload
   pio device monitor -b 115200
   ```
2. Verify boot output:
   ```text
   [MINI-WIFI] Starting AP: SEYYANEN-MINI (Channel 1)
   [MINI-WIFI] AP started, IP: 192.168.4.1
   [MINI-WEB] Starting HTTP server on port 80...
   [MINI-WEB] HTTP server started successfully
   ```
3. On your smartphone (iPhone or Android) or laptop:
   - Open Wi-Fi settings.
   - Connect to SSID: `SEYYANEN-MINI` (Password: `seyyanen123`).
   - Confirm connection to IP `192.168.4.X`.

### Step 2: Open Responsive Web Dashboard
1. Open mobile browser (Safari, Chrome, Firefox) and navigate to:
   ```text
   http://192.168.4.1/
   ```
2. Verify the responsive layout:
   - Header title: **SEYYANEN MINI** with subtitle *Local Telemetry & Acquisition Console*.
   - System Health Pills: `TRANSPORT`, `OBD`, `ACQUISITION`, `STORAGE`.
   - Bottom / top navigation tabs: `Dashboard`, `Live Telemetry`, `Sessions`, `PIDs`, `System`.

### Step 3: Verify Initial Disconnected / Standby State
1. Without the vLinker MC+ powered, verify:
   - Transport Card: `DISCONNECTED`, Target MAC displayed.
   - OBD Card: `NOT READY`.
   - Acquisition Card: `STOPPED`.
   - Recording Card: `STOPPED`, Free Space displayed.
   - Actionable Banner: `"vLinker adapter disconnected. Ensure adapter is powered and tap Reconnect."`

### Step 4: Power vLinker MC+ & Connect Transport
1. Plug vLinker MC+ into the vehicle OBD-II DLC port.
2. Turn vehicle key to **ON (KOEO)**.
3. On the Dashboard or System tab, tap `[ RECONNECT ]`.
4. Within 3–8 seconds, verify:
   - Health pill `TRANSPORT` turns green `CONNECTED`.
   - Adapter identity displays: `vLinker MC+ v2.2` (or detected banner).
   - Error banner automatically clears.

### Step 5: Scan Vehicle PIDs
1. Navigate to the **PIDs** tab or tap `[ SCAN PIDS ]` on the Dashboard.
2. Observe PID scan status: `SCANNING` $\rightarrow$ `COMPLETE`.
3. Verify supported Mode 01 PID count increments (e.g. 24–36 PIDs discovered).
4. Browse the PID table:
   - Supported PIDs show green `YES` badge with Name, Unit, and Priority.
   - Unsupported PIDs show gray `NO` badge.
   - Verify there is **NO** raw command text box (safe diagnostic boundary).

### Step 6: Start Live Telemetry Acquisition
1. Switch to the **Live Telemetry** tab.
2. Tap `[ START ACQUISITION ]`.
3. Confirm Acquisition card updates to `RUNNING`.
4. Observe live signal cards streaming data at 500 ms refresh intervals:
   - **Engine RPM:** (e.g. `0 rpm` in KOEO, or idle `750 rpm` in KOER)
   - **Coolant Temp (ECT):** (e.g. `88 °C`)
   - **Manifold Absolute Pressure (MAP):** (e.g. `101 kPa` KOEO or `34 kPa` idle)
   - **Throttle Position (TPS):** (e.g. `14.1 %`)
   - **Vehicle Speed:** `0 km/h`
5. Verify signal quality badges:
   - Fresh readings show green `GOOD` / `FRESH` badge with millisecond age (e.g. `GOOD · 45ms`).
   - Disconnected/unsupported sensors show appropriate semantic badges (`STALE`, `NO DATA`), never fabricated zeros.

### Step 7: Start MicroSD Session Recording
1. Tap `[ START RECORDING ]`.
2. Observe toast notification: `"Recording started: MINI-SESSION-XXXXXX"`.
3. Verify Recording state changes to `ACTIVE`.
4. Watch `Written Samples` counter continuously increment (e.g., 10 to 30 samples/second).
5. Confirm `Dropped Samples` remains `0`.
6. Start the engine to idle (KOER) and observe live RPM updating smoothly without freezing or slowing down the HTTP dashboard.

### Step 8: Safe Active Download Rejection Gate
1. Navigate to the **Sessions** tab while recording is `ACTIVE`.
2. Tap `[ REFRESH ]`. The current active session is displayed with status `ACTIVE`.
3. Attempt to download the active session (or request `/api/sessions/download?id=...`).
4. Verify rejection feedback:
   - Web UI / API responds: `"Active recording session cannot be downloaded while writing. Stop recording first."`
   - Data corruption is prevented.

### Step 9: Stop Recording & Finalize Session
1. Tap `[ STOP RECORDING ]`.
2. Observe toast notification: `"Finalizing session..."` followed by `"Recording stopped and finalized."`
3. Verify Recording state transitions to `STOPPED`.
4. Samples written counter freezes at final count (e.g. 1,845 samples).

### Step 10: Inspect Session Metadata & Safely Download CSV
1. On the **Sessions** tab, tap `[ REFRESH ]`.
2. The finalized session is listed:
   - Status: `COMPLETED`
   - Samples: `~1,845 samples`
   - Size: `~140 KB`
3. Tap `[ VIEW METADATA ]` (or `[ VIEW ]`).
   - Modal popup opens displaying `metadata.json`:
     - Session ID
     - Start / End ISO timestamps & Duration
     - Sample Count, Frame Count, Error Count
     - Adapter & Protocol information
     - Supported PID table with poll rates and priorities
4. Close modal and tap `[ DOWNLOAD CSV ]`.
5. Verify browser receives file `MINI-SESSION-XXXXXX_session.csv`:
   - Inspect downloaded file in text viewer / spreadsheet.
   - Confirm CSV header matches M-5 schema.
   - Confirm monotonic microsecond timestamps and quoted raw responses.

### Step 11: Transport Disconnection & UI Recovery Validation
1. While acquisition is running, pull the vLinker MC+ from the vehicle DLC port.
2. Within 2 polling cycles (1–2 seconds):
   - Health pill `TRANSPORT` turns red `DISCONNECTED`.
   - Error banner appears: `"vLinker connection lost. Acquisition paused. Reconnect the adapter."`
   - Live telemetry signal badges transition from `GOOD` $\rightarrow$ `STALE` with elapsed age (e.g. `STALE · 3.2s`).
   - Web UI does NOT crash or freeze.
3. Plug the vLinker MC+ back into the DLC port.
4. Tap `[ RECONNECT ]`.
5. Verify transport reconnects, health pills return to green, and live telemetry resumes updating.

---

## 4. PHYSICAL TEST MATRIX & CHECKLIST

| Step | Validation Target | Pass Criteria | Status |
| :--- | :--- | :--- | :--- |
| **1** | Wi-Fi SoftAP | Connects on iPhone/Android to `SEYYANEN-MINI` | PENDING HW |
| **2** | Responsive Web UI | Dashboard renders cleanly on mobile screen | PENDING HW |
| **3** | Health Summary Pills | Pills reflect accurate Transport/OBD/Acq/Storage states | PENDING HW |
| **4** | Transport Controls | `[ CONNECT ]` / `[ RECONNECT ]` dispatch via M-2 API | PENDING HW |
| **5** | PID Discovery Table | Lists supported PIDs without raw command inputs | PENDING HW |
| **6** | Live Telemetry Cards | Shows RPM, ECT, MAP, TPS with quality & millisecond freshness | PENDING HW |
| **7** | Quality Visualization | Distinct styling for GOOD, FRESH, STALE, NO DATA | PENDING HW |
| **8** | Start/Stop Recording | Generates valid session ID, writes buffered samples | PENDING HW |
| **9** | Active Download Gate | Rejects downloading mutable session with HTTP 400 | PENDING HW |
| **10**| Session Detail Modal | Loads `metadata.json` without buffering full CSV in RAM | PENDING HW |
| **11**| Completed Download | Streams intact `session.csv` safely to mobile device | PENDING HW |
| **12**| Transport Fault Recovery| UI shows actionable banner, recovers cleanly on reconnect | PENDING HW |

---

**Current Status:** `SEYYANEN MINI M-6 — READY FOR END-TO-END PHYSICAL VALIDATION`
