# SEYYANEN MINI — PHASE M-4 PHYSICAL HARDWARE TEST WALKTHROUGH

**Target Setup:**
- Device: ESP32-WROOM-32D
- OBD-II Adapter: vLinker MC+ Bluetooth Classic (SPP)
- Vehicle: OBD-II compliant passenger car (12V OBD-II port)
- Firmware Phase: Phase M-4 Live Acquisition Engine

---

## 1. PRE-TEST SAFETY GATES & PREREQUISITES

> [!IMPORTANT]
> - Phase M-4 is strictly **READ-ONLY** (Mode 01 only). All write commands (Mode 04 DTC clears, Mode 08 actuator tests, UDS services) are blocked at the firmware transport layer.
> - Ensure vehicle battery voltage is healthy (>12.2V before ignition ON).
> - Perform tests with the vehicle in **PARK / NEUTRAL** with the parking brake firmly set.
> - Do not perform high-speed driving or distracted testing. All observations must be conducted stationary at idle.

---

## 2. STEP-BY-STEP PHYSICAL VALIDATION PROCEDURE

### Step 1: Flash M-4 Firmware
Connect ESP32 to computer via USB and upload the compiled firmware:
```bash
pio run -e esp32dev -t upload
pio device monitor -b 115200
```
Verify banner in serial output:
```text
==================================================
   SEYYANEN MINI — PHASE M-4: LIVE ACQUISITION
   Target: ESP32-WROOM-32D / Bluetooth Classic
   Engine: Deterministic Sequential Polling
   Quality: Explicit Freshness & Zero-Resistance
   Storage: Bounded Ring Buffer (M-5 Handoff)
==================================================
```

### Step 2: Plug vLinker MC+ into Vehicle OBD-II Port
1. Locate the vehicle 16-pin DLC port (typically under the driver dashboard).
2. Firmly plug in the vLinker MC+ adapter.
3. Verify the adapter power LED illuminates.

### Step 3: Turn Vehicle Ignition to ON / RUN (KOEO)
1. Turn vehicle ignition key to **ON / RUN** (or press Start button without pressing brake pedal).
2. Engine remains stopped at this stage (Key-On Engine-Off).
3. ECUs wake up and begin responding on the CAN / K-Line bus.

### Step 4: Verify Transport Link (M-2 Verification)
1. In the ESP32 serial monitor, observe Bluetooth discovery and SPP connection to `vLinker MC-Android`.
2. Confirm the adapter identity is verified (`ATI` -> `VLINKER...`).
3. Verify state transition: `DISCONNECTED -> CONNECTING -> CONNECTED`.

### Step 5: Verify OBD-II Layer Initialization (M-3 Verification)
1. Verify the ELM327 initialization sequence succeeds:
   - `ATZ` (Reset)
   - `ATE0` (Echo Off)
   - `ATL0` (Linefeeds Off)
   - `ATS0` (Spaces Off)
   - `ATSP0` (Auto Protocol)
   - `0100` (Bus Search & Protocol Lock)
2. State transition: `OBD: READY`.

### Step 6: Verify Supported PID Scan (M-3 Verification)
1. Confirm automatic discovery of Mode 01 standard PIDs via bitmaps:
   - Bitmap `0100` returns supported PIDs `0101` through `0120`.
   - If bit 32 is set, `0120` is queried.
2. Confirm PID table is populated (e.g., `RPM (010C)`, `ECT (0105)`, `MAP (010B)`, `TPS (0111)` marked as `SUPPORTED`).

### Step 7: Connect to Seyyanen Mini Wi-Fi SoftAP
1. On phone, laptop, or tablet, connect to the Wi-Fi network:
   - **SSID:** `Seyyanen-Mini`
   - **Password:** `seyyanen2026`
2. Open web browser and navigate to:
   ```text
   http://192.168.4.1/
   ```
3. Verify the modern dashboard renders with badges:
   - `BT: CONNECTED`
   - `OBD: READY`
   - `ACQ: IDLE`

### Step 8: Start Live Acquisition
1. In the web dashboard, click `[ START ACQUISITION ]` (or send `POST /api/acquisition/start`).
2. Verify:
   - Badge changes to `ACQ: RUNNING` (emerald green).
   - Session ID appears: `MINI-SESSION-000001`.
   - Uptime timer increments smoothly.
   - Throughput counter displays active polling rate (e.g. 8–15 req/s).

### Step 9: Observe KOEO Telemetry
With the engine off:
- **RPM (010C):** 0 rpm (Quality: `GOOD`, Freshness: `FRESH`, Age: <150 ms)
- **ECT (0105):** Ambient/engine coolant temperature (e.g. 20–75 °C)
- **MAP (010B):** Atmospheric pressure (~98–102 kPa at sea level)
- **TPS (0111):** Throttle resting position (~10–18%)

### Step 10: Start Engine to Idle (KOER)
1. Turn ignition to START and crank the engine.
2. Allow engine to idle smoothly in PARK.
3. Observe live dashboard updates:
   - **RPM (010C):** Transitions immediately from 0 to idle speed (e.g., 700–900 rpm).
   - **ECT (0105):** Gradually increases as coolant warms.
   - **MAP (010B):** Drops from atmospheric (~100 kPa) to engine vacuum (~28–40 kPa).
   - **TPS (0111):** Stable resting idle throttle.

### Step 11: Slightly Vary Engine RPM
1. Lightly tap the accelerator pedal to raise engine speed to ~1500–2000 rpm.
2. Verify in the live UI:
   - RPM indicator immediately tracks the increase (e.g., 1850 rpm).
   - TPS indicator increases concurrently.
   - Quality tags remain `GOOD` with age consistently <150 ms.
   - Release pedal and confirm RPM returns to idle.

### Step 12: Validate Fairness & Starvation Prevention
1. Verify that while RPM and TPS are updated at fast intervals (120ms), slow signals like ECT (1200ms) and MAP (350ms) continue to update with freshness `FRESH` or `AGING` (never permanently `STALE`).

### Step 13: Test Pause and Resume
1. Click `[ PAUSE ]`:
   - State transitions to `ACQ: PAUSED`.
   - Throughput drops to 0 req/s.
   - Signal values retain last valid readings; ages increment; freshness tags decay from `FRESH -> AGING -> STALE`.
2. Click `[ RESUME ]`:
   - State returns to `ACQ: RUNNING`.
   - Signals refresh and return to `FRESH`.

### Step 14: Stop Acquisition and Verify Session Separation
1. Click `[ STOP ACQUISITION ]`:
   - State transitions to `ACQ: STOPPED`.
2. Click `[ START ACQUISITION ]` again:
   - New session ID is generated: `MINI-SESSION-000002`.
   - Sequence number resets to 1.
   - Previous session samples in history remain separated.

---

## 3. PHYSICAL TEST LOG CHECKLIST

| Test Step | Expected Result | Observed Result | Status |
|-----------|-----------------|-----------------|--------|
| Bluetooth Classic SPP Pairing | Connected to vLinker MC+ within 5s | | PENDING HW |
| ELM327 Initialization | Auto protocol locked to ISO 15765-4 CAN | | PENDING HW |
| Supported PID Scan | >10 Mode 01 PIDs discovered | | PENDING HW |
| KOEO Readings | RPM=0, MAP=~100kPa, ECT=ambient | | PENDING HW |
| KOER Idle Transition | RPM=700-900, MAP=28-40kPa | | PENDING HW |
| Throttle Blip | RPM & TPS track pedal instantaneously | | PENDING HW |
| Signal Freshness Decay | Decay to AGING/STALE when paused | | PENDING HW |
| Session Separation | MINI-SESSION-000001 -> MINI-SESSION-000002 | | PENDING HW |

**Current Status:** `SEYYANEN MINI M-4 — READY FOR PHYSICAL LIVE ACQUISITION TEST`
