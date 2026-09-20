# Seyyanen Mini — ESP32 Hardware Acquisition Companion

`seyyanen_mini` is an isolated embedded data-acquisition companion designed for the ESP32-WROOM-32D microcontroller. It serves as the physical collection and telemetry persistence edge node for the **Seyyanen Diagnostic Ecosystem**, interfacing directly with vehicles via a **VLinker MC+** (or compatible STN/OBDLink/ELM327 adapter) over Bluetooth Classic SPP.

```
+-------------------------------------------------------------------------+
|                              VEHICLE ECU                                |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ OBD-II (ISO 15765-4 / CAN)
                                    ▼
+-------------------------------------------------------------------------+
|                         VLinker MC+ Adapter                             |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ Bluetooth Classic (SPP)
                                    ▼
+-------------------------------------------------------------------------+
|                     SEYYANEN MINI (ESP32-WROOM-32D)                     |
|                                                                         |
|  [VLinker BT Transport] -> [ELM327 Client] -> [PID Scanner (0100..)]    |
|                                                     │                   |
|                                                     ▼                   |
|  [Web AP: 192.168.4.1]  <-  [Ring Buffer]  <- [Acquisition Scheduler]   |
|         │                        │                                      |
|         ▼                        ▼                                      |
|   (Local Web UI)          [microSD SPI]                                 |
|                         (CSV Session Stream)                            |
+-------------------------------------------------------------------------+
                                    │
                                    ▼ (Download / SD Import)
+-------------------------------------------------------------------------+
|                  SEYYANEN DESKTOP REASONING ENGINE                      |
|      (Temporal Analysis, Cross-Sensor RCA, Fault Intelligence)          |
+-------------------------------------------------------------------------+
```

---

## 1. Architectural Principles

- **Separation of Concerns**: The ESP32 is strictly an acquisition edge node. It is responsible for transport, protocol handshakes, supported PID discovery, deterministic acquisition scheduling, raw response preservation, unit decoding, high-resolution microsecond timestamps, quality classification, bounded in-memory buffering, SPI microSD persistence, and a local Web AP presentation layer.
- **Strict Read-Only Safety**: The firmware operates in read-only mode. All Mode 04 (Clear DTCs), Mode 08 (Actuator Control), and UDS write/security services (0x10, 0x11, 0x27, 0x2E, 0x31, 0x34..0x37) are intercepted and rejected prior to transmission.
- **No Fabricated Timing**: Sequential OBD queries are preserved with individual timestamps and round-trip latency measurements. The scheduler groups readings into logical cycles without claiming simultaneous acquisition.
- **Desktop Authority**: Advanced temporal analysis, dynamic operating references, cross-sensor fault correlation, and root-cause analysis remain exclusively in the desktop Seyyanen software.

---

## 2. Hardware Requirements & Wiring

### Hardware Checklist
1. **ESP32 Development Board**: ESP32-WROOM-32D or original ESP32 with Bluetooth Classic support (ESP32-S2/S3/C3 do NOT support Bluetooth Classic).
2. **OBD Adapter**: VLinker MC+ Bluetooth, OBDLink MX/LX, or STN-compatible Bluetooth Classic adapter.
3. **microSD Card Module**: SPI-compatible 3.3V/5V microSD breakout card reader formatted as FAT32.
4. **Wiring / Jumper Wires**: Direct connections between ESP32 and microSD reader.

### MicroSD SPI Wiring Table

| microSD Pin | ESP32 GPIO (VSPI) | Description |
| :--- | :--- | :--- |
| **CS** | **GPIO 5** | Chip Select |
| **MOSI** | **GPIO 23** | SPI Master Out Slave In |
| **MISO** | **GPIO 19** | SPI Master In Slave Out |
| **SCK** | **GPIO 18** | SPI Clock |
| **VCC** | **3.3V / 5V** | Power supply (matches module spec) |
| **GND** | **GND** | Ground |

---

## 3. Project Structure

```
seyyanen_mini/
├── platformio.ini              # PlatformIO configuration (esp32dev, Arduino, BT Classic)
├── include/
│   ├── mini_config.h           # System constants, pinouts, timing, AP settings
│   └── mini_types.h            # Lifecycle states, sample structs, PID metadata
├── src/
│   ├── main.cpp                # Application entry and cooperative loop orchestrator
│   ├── transport/
│   │   ├── vlinker_bt.h        # Bluetooth Classic SPP transport header
│   │   └── vlinker_bt.cpp      # BluetoothSerial master client & safety filter
│   ├── obd/
│   │   ├── elm327.h            # ELM327 / VLinker protocol client header
│   │   └── elm327.cpp          # Protocol handshake, identity parsing, prompt detection
│   │   ├── obd2.h              # OBD-II Mode 01 PID formulas & hex parser header
│   │   └── obd2.cpp            # Decoders for RPM, Speed, ECT, MAP, MAF, TPS, trims
│   │   ├── pid_scanner.h       # Supported PID discovery scanner header
│   │   └── pid_scanner.cpp     # 32-bit bitmap extraction (0100..0120)
│   ├── acquisition/
│   │   ├── sample.h            # Bounded runtime ring buffer header
│   │   └── sample.cpp          # Overwrite-safe circular sample buffer (256 entries)
│   │   ├── quality.h           # Data quality evaluation engine header
│   │   └── quality.cpp         # Physical range and freshness validation
│   │   ├── scheduler.h         # Acquisition scheduler header
│   │   └── scheduler.cpp       # Deterministic, non-blocking sequential querying
│   ├── storage/
│   │   ├── sd_logger.h         # MicroSD SPI persistence logger header
│   │   └── sd_logger.cpp       # CSV stream logging with metadata headers & periodic flush
│   └── web/
│       ├── web_server.h        # Embedded HTTP WebServer & REST API header
│       └── web_server.cpp      # Standalone SoftAP server with embedded UI assets
├── data/
│   └── web/
│       ├── index.html          # Responsive telemetry dashboard markup
│       ├── style.css           # Modern Seyyanen dark theme stylesheet
│       └── app.js              # Real-time polling and recording controller
├── test/
│   └── test_mini_core.py       # Deterministic host-side unit test suite
└── README.md                   # This specification document
```

---

## 4. Flashing & Configuration

### Using PlatformIO
1. Open the project root or navigate to `seyyanen_mini/`:
   ```bash
   cd seyyanen_mini
   ```
2. Build firmware:
   ```bash
   pio run
   ```
3. Flash to ESP32:
   ```bash
   pio run -t upload
   ```
4. Open serial monitor (115200 baud):
   ```bash
   pio run -t monitor
   ```

### Using Arduino IDE
1. Open `src/main.cpp` or create a sketch pointing to the source directory.
2. Select Board: **ESP32 Dev Module**.
3. Partition Scheme: **Default 4MB with spiffs (1.2MB APP / 1.5MB SPIFFS)**.
4. Upload to ESP32.

---

## 5. VLinker Pairing & Connection Process

1. Plug the **VLinker MC+** into the vehicle's OBD-II port. Verify the adapter power LED is illuminated.
2. Power on the ESP32.
3. Upon booting, the ESP32 activates Bluetooth Classic in master mode and scans for devices matching `vLinker MC` (configured in `include/mini_config.h`).
4. Once paired and connected, the ESP32 initiates the protocol handshake:
   - `ATZ` (Reset)
   - `ATE0` (Echo off)
   - `ATL0` (Linefeeds off)
   - `ATH0` (Headers off)
   - `ATS0` (Spaces off)
   - `ATSP0` (Auto protocol search)
   - `ATI` (Identity query)
5. The ESP32 queries `0100` (and `0120` if chained) to discover supported PIDs and registers only those supported by the vehicle ECU.

---

## 6. Local Web Interface (SoftAP)

When the ESP32 boots, it broadcasts an isolated Wi-Fi Access Point:

- **SSID**: `SEYYANEN-MINI`
- **Password**: `seyyanen123`
- **Dashboard URL**: `http://192.168.4.1`

### Dashboard Capabilities:
1. **Adapter State & Identity**: Live display of Bluetooth connection state (`CONNECTED`, `CONNECTING`, `DISCONNECTED`), hardware family (`VLINKER`, `OBDLINK`, `STN`, `ELM327`), and vehicle protocol.
2. **Live Telemetry Gauges**: Real-time gauge updates for RPM, Throttle, Vehicle Speed, Coolant Temp, MAP, MAF, and Fuel Trims with quality badges (`GOOD`, `DEGRADED`, `STALE`, `INVALID`).
3. **Telemetry Recording Control**:
   - **Start Recording**: Initiates a new persistent session on the microSD card.
   - **Stop Recording**: Closes and flushes the session file.
   - **Download CSV Log**: Streams the active/latest session log directly to the browser for offline import into Seyyanen Desktop.
4. **Supported PIDs Matrix**: Full table of registered PIDs, intervals, support status, and live values.

---

## 7. Log File Format Specification

Session files are stored on the microSD card with names following the pattern:
`/SESSION_0001.csv`, `/SESSION_0002.csv`, etc.

### File Schema:
```csv
# SEYYANEN_MINI_ACQUISITION_LOG_V1
# session_id: SN-8A3B4C12-D5E6F7A8
# adapter_brand: VLINKER
# adapter_identity: vLinker MC+ v2.2
# protocol: ISO 15765-4 (CAN 11/500)
# supported_pids: 0105,010B,010C,010D,0110,0111
# start_timestamp_us: 1726859345123456
timestamp_us,session_id,sequence,pid,pid_name,request,raw_response,decoded_value,unit,status,quality,latency_ms
1726859345203456,SN-8A3B4C12-D5E6F7A8,1,010C,Engine Speed,010C,410C1AF8,1726.00,rpm,VALID,GOOD,24
1726859345283456,SN-8A3B4C12-D5E6F7A8,2,0111,Throttle Position,0111,411135,20.78,%,VALID,GOOD,22
1726859345583456,SN-8A3B4C12-D5E6F7A8,3,010D,Vehicle Speed,010D,410D32,50.00,km/h,VALID,GOOD,26
```

---

## 8. Current Scope & Intentional Limitations

- **Mode 01 Standard PIDs**: Focuses on core powertrain metrics (`0105`, `0106`, `0107`, `010B`, `010C`, `010D`, `0110`, `0111`).
- **Read-Only**: No active actuator testing, adaptation resets, or DTC clearing.
- **Single Master**: Designed for a single VLinker connection per session.
- **MicroSD Dependency**: Recording requires a functional FAT32 SPI microSD module; web dashboard live streaming works even if SD is detached.

---

## 9. Verification & Acceptance Milestone

### Automated Host Verification
All core algorithms, transport state machines, OBD-II protocol engines, live acquisition schedulers, microSD storage engines, web APIs, and vehicle session validators are validated using deterministic Python test suites:
```powershell
# Phase M-7 Real Vehicle Validation & Hardening Suite (Tests A through N)
python seyyanen_mini/test/test_m7_validation.py -v

# Run Standalone Session Validator against Canonical Dataset
python seyyanen_mini/validate_mini_session.py seyyanen_mini/MINI_REAL_VEHICLE_VALIDATION_SESSION

# Phase M-6 Web UI & Session Management Suite (Tests A through T)
python seyyanen_mini/test/test_m6_web.py -v

# Phase M-5 MicroSD Storage & Session Persistence Suite (Tests A through X)
python seyyanen_mini/test/test_m5_storage.py -v

# Phase M-4 Live Acquisition Engine Suite (Tests A through V)
python seyyanen_mini/test/test_m4_acquisition.py -v

# Phase M-3 OBD-II Protocol & PID Discovery Suite
python seyyanen_mini/test/test_m3_obd.py -v

# Phase M-2 Transport Suite
python seyyanen_mini/test/test_m2_transport.py -v

# Core Protocol & Algorithm Suite
python seyyanen_mini/test/test_mini_core.py -v

# Run entire test suite
python -m unittest discover -s seyyanen_mini/test -p "test_*.py" -v
```
**Test Results**: 116/116 tests passing (100% success).

### Physical Hardware Acceptance Walkthrough
Follow the comprehensive step-by-step physical test procedures in:
- Phase M-2: [`m2_hardware_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m2_hardware_walkthrough.md)
- Phase M-3: [`m3_hardware_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m3_hardware_walkthrough.md)
- Phase M-4: [`m4_hardware_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m4_hardware_walkthrough.md)
- Phase M-5: [`m5_hardware_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m5_hardware_walkthrough.md)
- Phase M-6: [`m6_hardware_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m6_hardware_walkthrough.md)
- Phase M-7: [`m7_physical_validation_report.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m7_physical_validation_report.md) & [`m7_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/seyyanen_mini/m7_walkthrough.md)

---

## Project Status

**`SEYYANEN MINI M-7 — READY FOR END-TO-END PHYSICAL IN-VEHICLE RUN`**


