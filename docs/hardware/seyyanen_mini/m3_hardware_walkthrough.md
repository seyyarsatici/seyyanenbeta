# Phase M-3 Hardware Acceptance Walkthrough

This document defines the physical hardware test procedure for **Phase M-3: OBD-II Protocol + PID Discovery Engine** using the **ESP32-WROOM-32D**, **vLinker MC+**, and a **real OBD-II vehicle** (or compliant ECU bench simulator).

> [!IMPORTANT]
> **Phase M-3 Scope Limitation**:
> - M-3 executes ELM327 initialization, 32-bit supported PID discovery, and harmless single smoke reads (`010C`, `0105`, `010D`).
> - Do NOT enable continuous high-frequency telemetry streaming (belongs to Phase M-4).
> - Do NOT enable microSD persistence logging (belongs to Phase M-5).

---

## 1. Test Setup & Wiring
1. **ESP32**: Powered via USB from laptop or independent 5V power bank.
2. **vLinker MC+**: Firmly seated into vehicle OBD-II diagnostic DLC port.
3. **Vehicle**: Vehicle parked safely, transmission in Park/Neutral, handbrake engaged.
4. **Ignition State**: **Ignition ON / Engine OFF (Key-On Engine-Off, KOEO)** or **Engine Idling (Key-On Engine-Running, KOER)**.
5. **Client Device**: Laptop or phone connected to Wi-Fi AP **`SEYYANEN-MINI`** (Password: `seyyanen123`).
6. **Serial Monitor**: 115200 baud monitoring USB serial output from ESP32.

---

## 2. Flash Firmware

```bash
cd seyyanen_mini

# Compile M-3 firmware
pio run

# Flash to ESP32
pio run -t upload

# Open Serial Monitor
pio run -t monitor
```

---

## 3. Physical Test Execution Steps

### Step 1: Bluetooth Link Establishment
1. Power ESP32. Observe serial monitor:
   ```text
   ==================================================
      SEYYANEN MINI — PHASE M-3: OBD-II DISCOVERY    
      Target: ESP32-WROOM-32D / Bluetooth Classic    
      Scope: ELM327 Init, Mode 01 Bitmaps, Decoders  
      Status: Read-Only (No SD / No High-Freq Sched) 
   ==================================================
   [SYSTEM] Starting Web Server & Wi-Fi SoftAP...
   [WEB] Access Point active. Open: http://192.168.4.1
   [SYSTEM] Initializing VLinker Bluetooth Classic Transport...
   [MINI-BT] Bluetooth initialized. Device Name: 'SeyyanenMini'
   [SYSTEM] Attempting connection to target: 'vLinker MC'...
   [MINI-BT] Connecting SPP to target Name: 'vLinker MC'...
   [MINI-BT] SPP connected
   [MINI-BT] Sending ATI
   [MINI-BT] RX: vLinker MC+ v2.2.88 MICROSYS
   [MINI-BT] Adapter verified: vLinker MC+ (Brand: VLINKER, Model: MC+, FW: v2.2.88)
   [MINI-BT] State: CONNECTED
   ```

### Step 2: Automated ELM327 Protocol Initialization
1. Turn vehicle ignition to **ON/RUN**.
2. Observe automated initialization sequence on serial monitor:
   ```text
   [SYSTEM] Bluetooth link verified. Initializing ELM327 OBD layer...
   [MINI-OBD] ELM327 initialization started
   [MINI-OBD] ATZ -> OK (ELM327 v1.5 / vLinker MC+)
   [MINI-OBD] ATE0 -> OK (OK)
   [MINI-OBD] ATL0 -> OK (OK)
   [MINI-OBD] ATS0 -> OK (OK)
   [MINI-OBD] ATH0 -> OK (OK)
   [MINI-OBD] ATSP0 -> OK (OK)
   [MINI-OBD] Active vehicle protocol: ISO 15765-4 (CAN 11/500)
   [MINI-OBD] OBD layer READY
   ```

### Step 3: Supported PID Discovery (32-bit Bitmaps)
1. The scanner automatically queries `0100` and conditional ranges:
   ```text
   [SYSTEM] ELM327 initialized successfully! Running supported PID scan...
   [MINI-PID] Scanning supported PIDs
   [MINI-PID] Request 0100
   [MINI-PID] RX: 41 00 BE 3E B8 11
   [MINI-PID] Supported: 0104 (LOAD)
   [MINI-PID] Supported: 0105 (ECT)
   [MINI-PID] Supported: 0106 (STFT1)
   [MINI-PID] Supported: 0107 (LTFT1)
   [MINI-PID] Supported: 010B (MAP)
   [MINI-PID] Supported: 010C (RPM)
   [MINI-PID] Supported: 010D (SPEED)
   [MINI-PID] Supported: 010E (TIMING)
   [MINI-PID] Supported: 010F (IAT)
   [MINI-PID] Supported: 0110 (MAF)
   [MINI-PID] Supported: 0111 (TPS)
   [MINI-PID] Next range 0120 advertised as supported by ECU.
   [MINI-PID] Request 0120
   [MINI-PID] RX: 41 20 80 00 00 00
   [MINI-PID] Scan complete
   [MINI-PID] Supported PID count: 11
   [MINI-PID] Discovered PIDs: 0104 0105 0106 0107 010B 010C 010D 010E 010F 0110 0111
   ```

### Step 4: Harmless Initial Smoke Reads
1. The scanner executes single reads of core powertrain parameters:
   ```text
   [SYSTEM] Supported PID discovery complete! Executing initial smoke probe...
   [MINI-OBD] Executing harmless initial smoke probes (010C, 0105, 010D)...
   [MINI-OBD] Smoke Probe 010C (RPM) -> 820.00 rpm (Latency: 28 ms)
   [MINI-OBD] Smoke Probe 0105 (ECT) -> 86.00 degC (Latency: 24 ms)
   [MINI-OBD] Smoke Probe 010D (Speed) -> 0.00 km/h (Latency: 22 ms)
   [MINI-OBD] Smoke probes completed successfully.
   ```

### Step 5: Web UI Verification
1. Open browser at `http://192.168.4.1`.
2. Verify:
   - Header Badges: `BT: CONNECTED`, `OBD: READY`, `SCAN: COMPLETE`.
   - Protocol Card: displays detected protocol (e.g. `ISO 15765-4 (CAN 11/500)`).
   - Discovered PIDs Table:
     - Supported PIDs marked with green `YES` badges.
     - Unadvertised PIDs marked with muted `NO` badges.
     - Plausible smoke values displayed for RPM, ECT, and Speed.
3. Test Interactive Action Buttons:
   - Click **`[ SMOKE PROBE ]`**: verify table values refresh with new single reads.
   - Click **`[ SCAN PIDS ]`**: verify scanner re-runs bitmap discovery cleanly.

---

## 4. Hardware Acceptance Criteria

| Validation Check | Acceptance Standard | Status |
| :--- | :--- | :--- |
| **M-2 Transport Handshake** | `ATI` verified as `VLINKER` | [ ] |
| **ELM327 Reset & Config** | `ATZ`..`ATSP0` sequence completes with `OBD layer READY` | [ ] |
| **Vehicle Protocol Identification** | `ATDP` reports real vehicle protocol without errors | [ ] |
| **Mode 01 Bitmap Decoding** | `0100` returns 4-byte payload correctly parsed into bit indices | [ ] |
| **Conditional Chaining** | `0120` queried only if bit 32 of `0100` is asserted | [ ] |
| **3-Layer Result Preservation** | RAW response, NORMALIZED payload, and DECODED float preserved | [ ] |
| **Plausible Smoke Readings** | RPM (KOER ~600-1200 or KOEO 0), ECT (~15-95°C), Speed (0 km/h) | [ ] |
| **Web Presentation** | Web UI reflects real discovered PID list and smoke values | [ ] |
| **Safety Interceptor** | Mode 04 and UDS write commands strictly blocked | [ ] |

---

## Milestone Status

When verified against real vehicle ECU:
`SEYYANEN MINI M-3 — PHYSICALLY VALIDATED`
