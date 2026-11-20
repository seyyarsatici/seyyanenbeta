# Phase M-2 Hardware Acceptance Walkthrough

This document defines the physical hardware test procedure for **Phase M-2: VLinker Bluetooth Classic Transport** on the **ESP32-WROOM-32D** communicating with a real **vLinker MC+** (or compatible STN/OBDLink adapter).

> [!IMPORTANT]
> **Scope Limitation for M-2**:
> Do NOT query vehicle PIDs (no 0100, 010C, etc.).
> Do NOT test SD logging.
> The only diagnostic transaction executed in Phase M-2 is the harmless adapter identity handshake (`ATI`).

---

## 1. Prerequisites & Equipment
- **ESP32 Development Board**: ESP32-WROOM-32D (or original ESP32 dual-core with Bluetooth Classic support).
- **Diagnostic Adapter**: vLinker MC+ Bluetooth Classic (or OBDLink MX+/LX or STN adapter).
- **Power Source**: USB cable for ESP32; 12V OBD-II power source (vehicle port or 12V bench OBD breakout power supply).
- **Client Device**: Phone or laptop with Wi-Fi and a modern web browser.
- **Terminal Monitor**: Serial terminal at `115200` baud (e.g. PlatformIO Monitor, Arduino Serial Monitor, or PuTTY).

---

## 2. Flash & Build Instructions

### Option A: Using PlatformIO
```bash
# Navigate to the embedded project directory
cd seyyanen_mini

# Build the firmware
pio run

# Flash to the ESP32 via USB
pio run -t upload

# Launch the Serial Monitor
pio run -t monitor
```

### Option B: Using Arduino IDE
1. Open `seyyanen_mini/src/main.cpp`.
2. Select Board: **ESP32 Dev Module**.
3. Baud Rate: `115200`.
4. Upload sketch.

---

## 3. Step-by-Step Physical Test Procedure

### Step 1: Boot ESP32 & Verify Initialization
1. Power the ESP32 via USB (do **not** connect the vLinker yet).
2. Observe the serial monitor:
   ```text
   ==================================================
      SEYYANEN MINI — PHASE M-2: VLINKER TRANSPORT   
      Target: ESP32-WROOM-32D / Bluetooth Classic    
      Scope: Transport, SPP Link, ATI Identity, Web  
      Status: Read-Only (No PIDs / No SD Active)     
   ==================================================

   [SYSTEM] Starting Web Server & Wi-Fi SoftAP...
   [WEB] Access Point active. Open: http://192.168.4.1
   [SYSTEM] Initializing VLinker Bluetooth Classic Transport...
   [MINI-BT] Bluetooth initialized. Device Name: 'SeyyanenMini'
   [SYSTEM] Attempting initial connection to VLinker target: 'vLinker MC'...
   [MINI-BT] Searching for target: vLinker MC...
   [MINI-BT] Connecting SPP to target Name: 'vLinker MC'...
   [MINI-BT] State: ERROR
   [MINI-BT] Reason: SPP_CONNECT_FAILED
   ```
3. Verify that the ESP32 transitions to `ERROR` / `RECONNECTING` because the vLinker is powered off.
4. Verify the exponential backoff progression in serial logs:
   `Reconnect attempt #1 after 1000 ms backoff...`
   `Reconnect attempt #2 after 2000 ms backoff...`
   `Reconnect attempt #3 after 4000 ms backoff...`

### Step 2: Connect to Local Web Dashboard
1. On your phone or laptop, open Wi-Fi settings.
2. Connect to SSID: **`SEYYANEN-MINI`** (Password: `seyyanen123`).
3. Open a browser and navigate to: `http://192.168.4.1`.
4. Verify the web UI displays:
   - **Bluetooth State**: `RECONNECTING` or `ERROR`
   - **Adapter Identity**: `UNKNOWN`
   - **Identity Handshake**: `NOT VERIFIED`
   - **Raw ATI Response**: `No response received yet.`

### Step 3: Power On the Real vLinker MC+
1. Plug the vLinker MC+ into the vehicle OBD port or 12V bench power supply.
2. Verify the red power LED on the vLinker illuminates.
3. Wait for the ESP32's next backoff retry or click **`[ CONNECT ]`** on the Web UI.

### Step 4: Verify SPP Connection & Identity Verification
1. Watch the serial monitor. You should observe:
   ```text
   [MINI-BT] Connecting SPP to target Name: 'vLinker MC'...
   [MINI-BT] SPP connected
   [MINI-BT] Sending ATI
   [MINI-BT] RX: vLinker MC+ v2.2.88 MICROSYS
   [MINI-BT] Adapter verified: vLinker MC+ (Brand: VLINKER, Model: MC+, FW: v2.2.88)
   [MINI-BT] State: CONNECTED
   ```
2. Verify that `State: CONNECTED` is printed **only after** the `RX: vLinker MC+ ...` line!
3. Check the web dashboard at `http://192.168.4.1`:
   - Top Status Badge: **`CONNECTED`** (green)
   - Recognized Adapter: **`vLinker MC+`**
   - Manufacturer: **`MICROSYS`**
   - Firmware: **`v2.2.88`**
   - Identity Handshake: **`VERIFIED (ATI)`**
   - Raw Banner: displays exact observed string: `vLinker MC+ v2.2.88 MICROSYS`
   - Latency: displays real round-trip time (e.g. ~15–35 ms).
   - Retry counter reset to `0`.

### Step 5: Test Disconnect & Web Controls
1. On the web dashboard, click **`[ DISCONNECT ]`**.
2. Verify serial output: `[MINI-BT] SPP link disconnected.`
3. Verify web UI status changes immediately to **`DISCONNECTED`**.
4. Click **`[ CONNECT ]`** or **`[ RECONNECT ]`**.
5. Verify the link re-establishes, repeats `ATI`, and returns to **`CONNECTED`**.

### Step 6: Test Fault Tolerance (Out-of-Range / Power Cut)
1. Unplug the vLinker MC+ from the power source while connected.
2. Observe serial monitor:
   ```text
   [MINI-BT] Link dropped unexpectedly. Transitioning to RECONNECTING.
   [MINI-BT] Reconnect attempt #1 after 1000 ms backoff...
   [MINI-BT] State: ERROR
   [MINI-BT] Reason: SPP_CONNECT_FAILED
   [MINI-BT] Reconnect attempt #2 after 2000 ms backoff...
   ```
3. Re-plug the vLinker MC+ into the power source.
4. Verify that within one retry interval, the ESP32 automatically discovers the vLinker, performs `ATI`, and recovers to **`CONNECTED`** without requiring an ESP32 reboot.

---

## 4. Hardware Acceptance Criteria

| Criteria | Expected Result | Pass/Fail |
| :--- | :--- | :--- |
| **BT Master Init** | `[MINI-BT] Bluetooth initialized` with no Bluedroid errors | [ ] |
| **SPP Link Establishment** | Successful RFCOMM SPP connection to vLinker | [ ] |
| **Identity Verification** | `ATI` sent, raw string preserved, parsed as `VLINKER` | [ ] |
| **Connection Gate** | State stays in `CONNECTING` until `ATI` completes successfully | [ ] |
| **Web Dashboard** | Real-time updates showing `CONNECTED`, MAC, latency, and banner | [ ] |
| **Backoff Reconnect** | Progression 1s -> 2s -> 4s -> 8s -> 16s upon link loss | [ ] |
| **Auto-Recovery** | Automatic re-connection when vLinker returns to range | [ ] |
| **Safety Block** | Strictly no Mode 04 or UDS write commands sent | [ ] |

---

## Final Milestone Status

Once all check items above have responded on physical hardware:
`SEYYANEN MINI M-2 — PHYSICALLY VALIDATED`
