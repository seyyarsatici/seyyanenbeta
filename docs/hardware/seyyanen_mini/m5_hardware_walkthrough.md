# SEYYANEN MINI — PHASE M-5 PHYSICAL HARDWARE TEST WALKTHROUGH

**Target Setup:**
- Device: ESP32-WROOM-32D
- Storage: SPI MicroSD Card Module (FAT32 formatted card, e.g. 16GB / 32GB)
- OBD-II Adapter: vLinker MC+ Bluetooth Classic (SPP)
- Vehicle: OBD-II compliant passenger car (12V OBD-II port)
- Firmware Phase: Phase M-5 MicroSD Logging & Session Persistence

---

## 1. HARDWARE WIRING & PIN CONFIGURATION

Ensure the MicroSD module is wired to the ESP32 VSPI bus pins:

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
> - Use a FAT32-formatted high-endurance microSD card (Class 10 or UHS-1).
> - Vehicle must be in **PARK / NEUTRAL** with parking brake firmly set.
> - All tests are stationary at idle (KOEO and idle KOER).
> - Strict **READ-ONLY OBD-II** (Mode 01 only). Destructive commands are blocked at the firmware transport layer.

---

## 3. STEP-BY-STEP PHYSICAL VALIDATION PROCEDURE

### Step 1: Insert MicroSD Card & Flash M-5 Firmware
1. Insert FAT32 formatted card into the ESP32 card slot.
2. Connect ESP32 to PC via USB.
3. Build and upload:
   ```bash
   pio run -e esp32dev -t upload
   pio device monitor -b 115200
   ```
4. Verify boot banner:
   ```text
   ==================================================
      SEYYANEN MINI — PHASE M-5: SD PERSISTENCE
      Target: ESP32-WROOM-32D / Bluetooth Classic
      Storage: SPI MicroSD / Bounded In-Memory Write
      Data Model: Raw Evidence + Normalized + Decoded
      Integrity: Failure != Zero / Safe File Rotation
   ==================================================
   ```

### Step 2: Confirm Card Detection & Capacity
In the serial terminal, verify card initialization:
```text
[MINI-SD] Initializing microSD...
[MINI-SD] Card detected
[MINI-SD] Type: SDHC
[MINI-SD] Capacity: 15193 MB
[MINI-SD] Free space: 15190 MB
```

### Step 3: Connect vLinker MC+ & Vehicle Ignition
1. Plug vLinker MC+ into the vehicle 16-pin OBD-II DLC port.
2. Turn ignition key to **ON / RUN (KOEO)**.
3. Observe Bluetooth connection: `BT: CONNECTED`.
4. Observe ELM327 protocol lock: `OBD: READY`.
5. Observe PID scan: Discovered Mode 01 PIDs.

### Step 4: Open Web Dashboard
1. Connect laptop or phone to Wi-Fi SoftAP: `SEYYANEN-MINI` (Password: `seyyanen123`).
2. Open browser at `http://192.168.4.1/`.
3. Check header badges:
   - `BT: CONNECTED`
   - `OBD: READY`
   - `ACQ: IDLE`
   - `SD: READY`
4. Confirm Storage box displays card free space and `STORAGE: READY`.

### Step 5: Start Live Acquisition & Recording
1. Click `[ START ACQUISITION ]`.
   - Scheduler enters `ACQ: RUNNING`.
   - Live telemetry cards begin displaying RPM, ECT, MAP, TPS, Speed with microsecond timestamps.
2. Click `[ START RECORDING ]`.
   - Storage card updates: `Active Session: MINI-SESSION-000001`.
   - `Written Samples` begins incrementing continuously (e.g. 10..25 samples/sec).
   - `Dropped Samples` remains `0`.

### Step 6: Stationary Engine Idle Observation
1. Start the vehicle engine to idle.
2. Let vehicle idle for 3–5 minutes.
3. Verify live RPM indicates 700–900 rpm.
4. Slightly press the accelerator pedal to raise RPM to ~1500 rpm for 10 seconds.
5. Release pedal back to idle.
6. Verify sample count steadily increases (e.g. >2,000 samples).

### Step 7: Stop Recording & Finalize Session
1. Click `[ STOP RECORDING ]`.
   - Card displays: `Recording finalized`.
   - Written count halts.
2. Click `[ REFRESH SESSIONS ]`.
   - The Recorded Sessions table updates to display:
     - **Session ID:** `MINI-SESSION-000001`
     - **Status:** `COMPLETED`
     - **Samples:** ~2,500
     - **Size:** ~180 KB
     - **Actions:** `[ DOWNLOAD CSV ]`

### Step 8: Download & Inspect Session Data
1. In the Sessions table, click `[ DOWNLOAD CSV ]`.
2. Browser downloads `MINI-SESSION-000001_session.csv`.
3. Open in Excel, VS Code, or text editor and inspect:
   - **Header row:**
     `timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us`
   - **Timestamps:** strictly monotonic microsecond increments.
   - **Raw response:** `"41 0C 1A F8"`, `"41 05 5A"`, etc. preserved and quoted.
   - **Values:** credible RPM, ECT, MAP readings.
   - **No fake zeros:** any failed query has empty `decoded_value` with explicit status `TIMEOUT` or `NO_DATA`.

### Step 9: Validate Second Session Separation
1. Click `[ START RECORDING ]` again.
2. Verify new session ID is generated: `MINI-SESSION-000002`.
3. Allow recording for 30 seconds, then click `[ STOP RECORDING ]`.
4. Refresh sessions table and confirm both `MINI-SESSION-000001` and `MINI-SESSION-000002` are listed separately.

### Step 10: Card Removal Error Handling
1. With recording stopped, eject the microSD card.
2. Click `[ REFRESH SESSIONS ]` or wait 2 seconds.
3. Observe header badge: `SD: NO_CARD`.
4. Verify live telemetry continues updating without freezing or crashing ESP32!
5. Reinsert microSD card and confirm status returns to `SD: READY`.

---

## 4. PHYSICAL TEST LOG CHECKLIST

| Step | Test Description | Expected Result | Status |
| :--- | :--- | :--- | :--- |
| 1 | MicroSD SPI Mount | Capacity & free space detected | PENDING HW |
| 2 | Base Directories | `/SEYYANEN/SESSIONS` created | PENDING HW |
| 3 | Start Recording | `session.csv` & `metadata.json` created | PENDING HW |
| 4 | KOER Idle Telemetry | Continuous buffered writes (>1000 rows) | PENDING HW |
| 5 | Dropped Sample Count | Remains 0 during continuous recording | PENDING HW |
| 6 | Throttle Variation | RPM variation recorded in CSV rows | PENDING HW |
| 7 | Session Finalization | `session_state: COMPLETED` in metadata | PENDING HW |
| 8 | Web Download | HTTP streaming downloads intact CSV | PENDING HW |
| 9 | Session Separation | Multiple sessions recorded in isolation | PENDING HW |
| 10| Card Eject Resilience | Live engine runs; SD error handled safely | PENDING HW |

**Current Status:** `SEYYANEN MINI M-5 — READY FOR PHYSICAL SD LOGGING TEST`
