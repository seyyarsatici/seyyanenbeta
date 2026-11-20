# Virtual ELM327 Test Harness & Deterministic Lifecycle Walkthrough

## 1. Architecture Overview

The Virtual ELM327 test harness provides a deterministic, byte-level emulation of an ELM327 / VLinker diagnostic adapter. It enables rigorous lifecycle and connection validation without requiring physical vehicle hardware or the physical VLinker Bluetooth adapter.

```
+-----------------------------------------------------------------------------------+
|                            Seyyanen Application Flow                              |
|                                                                                   |
|   GUI (main_ui.py)                                                                |
|         |                                                                         |
|         v                                                                         |
|   LiveAcquisitionRuntime (live_runtime.py / live_acquisition.py)                 |
|         |                                                                         |
|         v                                                                         |
|   ELM327DiagnosticAdapter (diagnostic_adapter.py)                                 |
|         |                                                                         |
|         v                                                                         |
|   serial_factory Injection Point                                                  |
|         |                                                                         |
|         +----------------------------------+----------------------------------+   |
|         | [Default: Production / Vehicle]  | [Opt-In: Virtual Test Harness]   |   |
|         v                                  v                                  |   |
|   pyserial (serial.Serial)           VirtualSerialTransport (virtual_elm327) |   |
|         |                                  |                                  |   |
|         v                                  v                                  |   |
|   Windows COM Port (e.g. COM3 / COM4)VirtualELM327Responder                   |   |
|         |                                  |                                  |   |
|         v                                  v                                  |   |
|   Physical VLinker MC+ / ECU         Deterministic ASCII frames + '>' prompt  |   |
+-----------------------------------------------------------------------------------+
```

### Key Architectural Invariants:
1. **Production Path Untouched**: The real hardware path through `serial.Serial`, candidate COM port discovery, and Bluetooth SPP timing remains the 100% default.
2. **Opt-in Only**: The virtual harness is strictly opt-in via:
   - Explicit `serial_factory` parameter injection, OR
   - Explicit port target: `port="COM_VIRTUAL"`, OR
   - Environment variable: `SEYYANEN_VIRTUAL_ELM327=1`.
   When real COM devices exist, real devices always take precedence.
3. **No MockSerial Leakage**: `MockSerialForELM` (which generates synthetic vehicle telemetry for simulation mode) is completely absent from this harness. The adapter operates in strict `simulation=False` production mode.

---

## 2. Virtual Transport vs. Legacy MockSerial

| Feature | Legacy `MockSerial` | `VirtualSerialTransport` (This Harness) |
|---|---|---|
| **Operating Layer** | Engine level simulator (`AutoExpertEngine`) | PySerial `Serial` drop-in layer |
| **Adapter Mode** | `simulation=True` (`COM_MOCK`) | `simulation=False` (Strict real hardware mode) |
| **Protocol Logic** | Fakes sensor values directly into engine dict | Exercises real `_send_raw_command`, `_execute_initialization`, AT parser |
| **Byte-Level I/O** | High-level dictionary lookups | Real ASCII wire bytes, CR (`\r`), prompt (`>`), linefeeds |
| **Latency Modeling**| None / instant | Deterministic latency (instant, 50ms, 100ms, 500ms) |
| **Fault Injection** | Hardcoded exceptions | Drop, timeout, disconnect, malformed frames, NO DATA, ? |
| **Hardware Verification**| Fails to test adapter state machine | Tests 100% of adapter state transitions and timing |

---

## 3. How to Run Self-Test and Integration Tests

### A. CLI Responder Self-Test
Validates the complete command dictionary, newline formatting, and `>` prompt termination:
```powershell
python virtual_elm327.py --self-test
```
*Expected Output:*
```
============================================================
  SEYYANEN VIRTUAL ELM327 TEST HARNESS: SELF-TEST
============================================================
[PASS] CMD: ATZ          -> Resp: '\r\rELM327 v2.2\r\r>'              (Expected: 'ELM327 v2.2')
[PASS] CMD: ATI          -> Resp: 'ELM327 v2.2\r\r>'                  (Expected: 'ELM327 v2.2')
[PASS] CMD: ATE0         -> Resp: 'OK\r\r>'                           (Expected: 'OK')
[PASS] CMD: ATL0         -> Resp: 'OK\r\r>'                           (Expected: 'OK')
[PASS] CMD: ATS0         -> Resp: 'OK\r\r>'                           (Expected: 'OK')
[PASS] CMD: ATH1         -> Resp: 'OK\r\r>'                           (Expected: 'OK')
[PASS] CMD: AT SP 0      -> Resp: 'OK\r\r>'                           (Expected: 'OK')
[PASS] CMD: AT DPN       -> Resp: 'A6\r\r>'                           (Expected: 'A6')
[PASS] CMD: AT DP        -> Resp: 'ISO 15765-4 (CAN 11/500)\r\r>'     (Expected: 'ISO 15765-4 (CAN 11/500)')
[PASS] CMD: ATRV         -> Resp: '12.6V\r\r>'                        (Expected: '12.6V')
[PASS] CMD: 0100         -> Resp: '4100 BE 3E B8 13\r\r>'             (Expected: '4100 BE 3E B8 13')
[PASS] CMD: 010C         -> Resp: '410C 1A F8\r\r>'                   (Expected: '410C 1A F8')
...
>>> ALL VIRTUAL ELM327 COMMANDS PASSED DETERMINISTIC SELF-TEST.
```

### B. Fault & Scenario Demos
```powershell
python virtual_elm327.py --scenario normal
python virtual_elm327.py --scenario timeout
python virtual_elm327.py --scenario disconnect
python virtual_elm327.py --scenario malformed
```

### C. Direct Port Probe Verification
Test probing `COM_VIRTUAL` directly through the CLI diagnostic command in `diagnostic_adapter.py`:
```powershell
python diagnostic_adapter.py --probe-port COM_VIRTUAL
```
*Expected Output:*
```
==================================================
  SEYYANEN OBD ADAPTER DIAGNOSTIC PROBE: COM_VIRTUAL
==================================================
[PROBE-PORT] Target Port: COM_VIRTUAL
[PROBE-PORT] Opening COM_VIRTUAL @ 38400 baud (timeout=0.1s)...
[PROBE-PORT] Serial handle opened successfully.
[PROBE-PORT] Waiting 0.4s for Bluetooth/UART stabilization...
[PROBE-PORT] Sending harmless identification sequence: \r\rATI\r
[PROBE-PORT] Raw Response: 'ELM327 v2.2\r\r>'
[PROBE-PORT] Outcome: ELM327_DETECTED (Identity: ELM327 V2.2)
[PROBE-PORT] Serial handle cleanly closed.
==================================================
```

### D. Full Lifecycle Integration Test
Validates connection, probe, initialization, PID queries, disconnect, and reconnect:
```powershell
python test_virtual_elm327_integration.py
```
*Expected Output:*
```
============================================================
  SEYYANEN VIRTUAL ELM327 LIFECYCLE INTEGRATION TEST
============================================================
[VIRTUAL-ELM] PASS
[PROBE] PASS
[INIT] PASS
[0100] PASS
[010C] PASS
[DISCONNECT] PASS
[RECONNECT] PASS
============================================================
>>> ALL INTEGRATION LIFECYCLE CHECKS PASSED.
============================================================
```

### E. Unit & Invariant Test Suite
```powershell
python -m unittest test_virtual_elm327.py -v
```

---

## 4. Validating the Production Connection Path

To validate how `main_ui.py` behaves when no physical hardware is present, enable the test flag:

```powershell
# In PowerShell:
$env:SEYYANEN_VIRTUAL_ELM327="1"
python main_ui.py
```
When you click **"OBD Bağlan"**:
1. The runtime attempts Windows COM discovery.
2. If no physical COM devices are found, it detects `COM_VIRTUAL` (Virtual ELM327 Test Harness).
3. The CMD console logs:
   ```
   [REAL-CONNECT] Enumerating Windows COM ports
   [REAL-CONNECT] Candidate: COM_VIRTUAL | description=Virtual ELM327 Test Harness
   [REAL-CONNECT] Probing COM_VIRTUAL
   [REAL-CONNECT] ELM327 detected on COM_VIRTUAL
   [REAL-CONNECT] Establishing active connection on COM_VIRTUAL
   [REAL-CONNECT] Active connection open on COM_VIRTUAL @ 38400 baud
   [REAL-CONNECT] ELM327 adapter responsive: ELM327 v2.2
   [REAL-CONNECT] ELM327 initialization successful on COM_VIRTUAL
   ```
4. The GUI displays: **`BAĞLI: COM_VIRTUAL`** in green (NOT simulation mode!).

To return to standard physical hardware:
```powershell
Remove-Item Env:\SEYYANEN_VIRTUAL_ELM327
```

---

## 5. Limitations & Physical UART Distinction

> [!WARNING]
> The virtual ELM327 test harness emulates the protocol framing, ASCII responses, timeouts, and state transitions of the ELM327.
> It does **NOT** validate:
> - Physical FTDI / CH340 / CP210 USB UART driver handshakes.
> - Windows Bluetooth RFCOMM driver pairing, passkeys, and RF link drops.
> - Physical voltage levels on CAN High / CAN Low (pins 6 & 14) or K-Line (pin 7).
> - Vehicle electrical noise or actual 12V vehicle battery sag during cranking.
> 
> Physical hardware validation remains explicitly distinct and requires testing against the real physical VLinker MC+ or FT232 adapter.

---

## 6. Testing Against COM5 / FT232 or Virtual COM Pairs (com0com)

To bridge the software emulator to an actual physical Windows COM port without touching a vehicle:

1. **Using USB UART Loopback (FT232 / CH340 / CP210)**:
   - Connect an FTDI USB-to-Serial dongle to the PC (e.g. assigned as `COM5`).
   - Run a standalone bridge or connect the adapter to `COM5`:
     ```powershell
     python diagnostic_adapter.py --probe-port COM5
     ```
2. **Using Null-Modem Virtual COM Pair (e.g. com0com)**:
   - Install `com0com` to create linked virtual port pairs: `CNCA0 <-> CNCB0` (or `COM10 <-> COM11`).
   - Run a responder loop script on `COM11` feeding bytes to `VirtualELM327Responder`.
   - Point Seyyanen to `COM10`.
   - Seyyanen communicates with `COM10` through real Windows kernel serial drivers (`pyserial.Serial("COM10")`), validating the entire Windows OS serial I/O stack without vehicle hardware!
