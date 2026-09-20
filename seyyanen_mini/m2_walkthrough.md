# Phase M-2 Walkthrough: VLinker Bluetooth Classic Transport

Phase M-2 of **Seyyanen Mini** establishes the isolated, deterministic Bluetooth Classic SPP transport layer for the ESP32-WROOM-32D targeting the VLinker MC+ diagnostic adapter.

---

## 1. Phase Boundaries & Responsibilities

### What M-2 Owns:
- **Bluetooth Classic SPP Initialization**: Master/Client RFCOMM channel via Arduino-ESP32 `BluetoothSerial`.
- **Target Selection**: Flexible device name matching (`SEYYANEN_VLINKER_NAME`) or known MAC address resolution (`SEYYANEN_VLINKER_MAC`).
- **Single Session Ownership**: Exactly one instance owns the SPP connection; prevents duplicate or conflicting sessions.
- **Identity Gate**: Physical SPP link connected does **not** equal `CONNECTED`. The state transitions to `CONNECTED` strictly after the `ATI` transaction succeeds and returns a recognized adapter banner.
- **Adapter Recognition**: Normalizes identity for `VLINKER`, `OBDLINK`, `STN`, and `ELM327`. Rejects garbage/non-OBD devices with `INVALID_ADAPTER_RESPONSE`.
- **Exponential Backoff Reconnection**: 1000ms -> 2000ms -> 4000ms -> 8000ms -> 16000ms (max). Automatically resets to 1000ms upon successful connection.
- **Safe Command Interceptor**: Rejects destructive Mode 04 (Clear DTCs), Mode 08 (Actuator Control), and UDS write services (0x10, 0x11, 0x27, 0x2E, 0x31) before transmission.
- **Transport Health & Diagnostics**: Tracks RX/TX bytes, round-trip latency, retry counters, and granular error classifications (`TransportError`).
- **Local Web Status Interface**: Standalone Access Point (`192.168.4.1`) displaying live transport state, identity banner, health stats, and connection controls (`[CONNECT]`, `[DISCONNECT]`, `[RECONNECT]`).

### What M-2 Does NOT Include:
- No OBD-II PID decoding.
- No PID scheduling or background acquisition loops.
- No microSD logging.
- No vehicle diagnostics or fault analysis.
- The only diagnostic transaction executed in Phase M-2 is the harmless adapter identity handshake (`ATI`).

---

## 2. Key Files Modified & Created

```
seyyanen_mini/
├── include/
│   ├── mini_config.h              # Added target MAC, backoff timing (1s..16s), ATI timeouts
│   └── mini_types.h               # Added TransportError, AdapterIdentityInfo, TransportHealth
├── src/
│   ├── transport/
│   │   ├── vlinker_bt.h           # VLinkerBluetoothTransport class definition
│   │   └── vlinker_bt.cpp         # SPP client, backoff loop, ATI handshake, safety filter
│   ├── web/
│   │   ├── web_server.h           # M-2 HTTP WebServer header
│   │   └── web_server.cpp         # Embedded M-2 dashboard (PROGMEM) with live transport monitor
│   └── main.cpp                   # Application entry point focused strictly on M-2 transport loop
├── test/
│   ├── test_m2_transport.py       # Deterministic host unit tests for M-2
│   └── test_mini_core.py          # Baseline core tests from M-1
├── m2_hardware_walkthrough.md     # Step-by-step physical validation instructions
└── m2_walkthrough.md              # This document
```

---

## 3. Test Verification Results

All deterministic host-side tests passed with 0 failures:

```powershell
python seyyanen_mini/test/test_m2_transport.py -v
```

```text
test_command_safety_filter (__main__.TestM2Transport.test_command_safety_filter) ... ok
test_disconnect_lifecycle (__main__.TestM2Transport.test_disconnect_lifecycle) ... ok
test_duplicate_connection_prevention (__main__.TestM2Transport.test_duplicate_connection_prevention) ... ok
test_exponential_backoff_progression (__main__.TestM2Transport.test_exponential_backoff_progression) ... ok
test_identity_handshake_recognition (__main__.TestM2Transport.test_identity_handshake_recognition) ... ok
test_invalid_identity_rejection (__main__.TestM2Transport.test_invalid_identity_rejection) ... ok
test_no_false_connected_state (__main__.TestM2Transport.test_no_false_connected_state) ... ok
test_response_buffering_and_prompt (__main__.TestM2Transport.test_response_buffering_and_prompt) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.001s

OK
```

All 8 baseline tests from M-1 also continue to pass:
```powershell
python seyyanen_mini/test/test_mini_core.py -v
```
```text
Ran 8 tests in 0.001s
OK
```

---

## 4. Current Status

`SEYYANEN MINI M-2 — READY FOR PHYSICAL VLINKER TEST`
