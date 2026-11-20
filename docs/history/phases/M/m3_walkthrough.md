# Phase M-3 Walkthrough: OBD-II Protocol + PID Discovery Engine

Phase M-3 builds directly on the Phase M-2 Bluetooth Classic SPP transport. It establishes the protocol communication client (`Elm327Client`), generic read-oriented transaction engine (`Obd2Client`), response normalizer, 32-bit supported PID discovery engine (`PidScanner`), standard Mode 01 decoders, and a decoupled API contract for the future Phase M-4 scheduler.

---

## 1. Architecture & Pipeline

```
+-------------------------------------------------------------------------+
|                  VLinkerBluetoothTransport (M-2 LAYER)                  |
|  - Authoritative SPP connection with vLinker MC+                        |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ transact(cmd, rawOut, maxLen, timeoutMs)
                                    ▼
+-------------------------------------------------------------------------+
|                        Elm327Client (M-3 CORE)                          |
|  - Initialization Sequence: ATZ -> ATE0 -> ATL0 -> ATS0 -> ATH0         |
|                             -> ATSP0 -> ATDP                            |
|  - States: UNINITIALIZED, INITIALIZING, READY, TIMEOUT, ERROR           |
|  - Preserves exact raw ASCII responses up to prompt '>'                 |
|  - Strict single-transaction serialization                              |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ query(cmd, rawOut, latencyMs)
                                    ▼
+-------------------------------------------------------------------------+
|                        Obd2Client (M-3 CORE)                            |
|  - Generic Mode 01 Dispatcher: request(mode, pid, timeoutMs)            |
|  - 3-Layer Response Model:                                              |
|      1. RAW: Exact adapter string (e.g. '7E8 04 41 0C 1A F8\r\n>')      |
|      2. NORMALIZED: Canonical payload bytes (e.g. [0x1A, 0xF8])         |
|      3. DECODED: Interpreted physical value (e.g. 1726.0 rpm)           |
|  - Safety Interceptor: Blocks Mode 04, UDS 0x14, 0x27, 0x2E, 0x2F...    |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ request(0x01, basePid)
                                    ▼
+-------------------------------------------------------------------------+
|                        PidScanner (M-3 DISCOVERY)                       |
|  - Chained 32-bit Bitmaps: 0100 -> 0120 (conditional if bit 32 set)     |
|  - Dynamic Support Resolution (no blind queries to unadvertised ranges) |
|  - Standard Mode 01 Metadata Registry (PIDs 0100..0111)                 |
|  - Harmless initial smoke probe reads (010C, 0105, 010D)                |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
+-------------------------------------------------------------------------+
|                     M-3 WEB PRESENTATION & M-4 HANDOFF                  |
|  - Web UI: OBD State (READY), Protocol, Supported PID Matrix Table      |
|  - Clean M-4 Handoff API for future AcquisitionScheduler                |
+-------------------------------------------------------------------------+
```

---

## 2. Standard Mode 01 PID Formulas Implemented

| PID | Parameter Name | Unit | Formula | Physical Sanity Bounds |
| :--- | :--- | :--- | :--- | :--- |
| **0104** | Calculated Engine Load | `%` | `A * 100 / 255` | 0.0 to 100.0% |
| **0105** | Engine Coolant Temp (ECT) | `°C` | `A - 40` | -40.0 to 150.0 °C |
| **0106** | Short Term Fuel Trim Bank 1 | `%` | `(A - 128) * 100 / 128` | -100.0 to 100.0% |
| **0107** | Long Term Fuel Trim Bank 1 | `%` | `(A - 128) * 100 / 128` | -100.0 to 100.0% |
| **010B** | Intake Manifold Pressure (MAP) | `kPa` | `A` | 0.0 to 255.0 kPa |
| **010C** | Engine RPM | `rpm` | `((A * 256) + B) / 4` | 0.0 to 10000.0 rpm |
| **010D** | Vehicle Speed | `km/h` | `A` | 0.0 to 350.0 km/h |
| **010E** | Ignition Timing Advance | `deg` | `(A / 2) - 64` | -64.0 to 63.5 deg |
| **010F** | Intake Air Temp (IAT) | `°C` | `A - 40` | -40.0 to 150.0 °C |
| **0110** | MAF Air Flow Rate | `g/s` | `((A * 256) + B) / 100` | 0.0 to 655.35 g/s |
| **0111** | Throttle Position (TPS) | `%` | `A * 100 / 255` | 0.0 to 100.0% |

---

## 3. Response Normalization Engine

Adapters and vehicle ECUs return responses in varying formats depending on ECU type and ELM327 settings:
- **Direct Form**: `41 0C 1A F8`
- **Framed 11-bit CAN**: `7E8 04 41 0C 1A F8`
- **Framed 29-bit CAN**: `18DAF110 04 41 0C 1A F8`
- **Compact Form (Spaces Off)**: `410C1AF8` or `7E804410C1AF8`

`Obd2::normalizeResponse` handles both tokenized (space-delimited) and continuous forms:
1. Locates the Mode 01 positive response marker (`0x41`) followed by the target PID.
2. Extracts subsequent payload bytes into canonical byte arrays.
3. Preserves the unmodified raw ASCII response for evidence verification.

---

## 4. Chained 32-bit Bitmap Discovery

In standard OBD-II, PIDs `0100`, `0120`, `0140`, etc. return 32-bit bitmaps indicating support for the next 32 PIDs:
- **Relative PID 1**: Bit 31 (MSB)
- **Relative PID 32**: Bit 0 (LSB) — specifically indicates whether the **next 32-PID range exists**!

`PidScanner::scanSupportedPids` implements conditional chaining:
1. Queries `0100` and extracts bitmap for PIDs `01`..`20`.
2. Inspects bit 32 of `0100`. Only if asserted, it queries `0120`.
3. If bit 32 is not asserted, it halts the chained scan immediately, avoiding blind, unnecessary queries to the vehicle ECU.

---

## 5. M-4 Handoff Contract API

The future Phase M-4 `AcquisitionScheduler` interacts exclusively with the high-level decoupled API exposed by `PidScanner` and `Obd2Client`:

```cpp
// 1. Check if ELM327 and OBD layers are ready for polling
bool isReady = obdClient.isReady();

// 2. Query count and metadata of discovered supported PIDs
size_t count = pidScanner.getSupportedCount();
const PidMetadata* meta = pidScanner.getPidMetadata(index);

// 3. Request a single PID measurement (returns RAW, NORMALIZED, and DECODED layers)
ObdResult result = pidScanner.queryPid(0x010C); // e.g. Engine RPM
if (result.status == SAMPLE_STATUS_VALID) {
    float rpm = result.decoded_value;
    uint32_t latency = result.latency_ms;
    uint64_t timestamp = result.timestamp_us;
}
```

The future scheduler does **not** need to manage Bluetooth connection handles, AT commands, prompt detection, or hex decoding.

---

## 6. Deterministic Host Test Results

All 20 tests (A through T) passed with 100% success:

```powershell
python seyyanen_mini/test/test_m3_obd.py -v
```

```text
test_A_elm327_initialization_sequence (__main__.TestM3Obd.test_A_elm327_initialization_sequence) ... ok
test_B_adapter_identity_acceptance (__main__.TestM3Obd.test_B_adapter_identity_acceptance) ... ok
test_C_invalid_initialization_response (__main__.TestM3Obd.test_C_invalid_initialization_response) ... ok
test_D_generic_mode01_request_validation (__main__.TestM3Obd.test_D_generic_mode01_request_validation) ... ok
test_E_valid_010C_response_rpm (__main__.TestM3Obd.test_E_valid_010C_response_rpm) ... ok
test_F_valid_0105_response_ect (__main__.TestM3Obd.test_F_valid_0105_response_ect) ... ok
test_G_valid_010B_response_map (__main__.TestM3Obd.test_G_valid_010B_response_map) ... ok
test_H_valid_010D_response_speed (__main__.TestM3Obd.test_H_valid_010D_response_speed) ... ok
test_I_valid_0110_response_maf (__main__.TestM3Obd.test_I_valid_0110_response_maf) ... ok
test_J_no_data_response_handling (__main__.TestM3Obd.test_J_no_data_response_handling) ... ok
test_K_timeout_handling (__main__.TestM3Obd.test_K_timeout_handling) ... ok
test_L_malformed_response_handling (__main__.TestM3Obd.test_L_malformed_response_handling) ... ok
test_M_response_normalization (__main__.TestM3Obd.test_M_response_normalization) ... ok
test_N_supported_pid_bitmap_decoding (__main__.TestM3Obd.test_N_supported_pid_bitmap_decoding) ... ok
test_O_multiple_supported_pid_ranges_chaining (__main__.TestM3Obd.test_O_multiple_supported_pid_ranges_chaining) ... ok
test_P_unsupported_pid_detection (__main__.TestM3Obd.test_P_unsupported_pid_detection) ... ok
test_Q_transaction_serialization (__main__.TestM3Obd.test_Q_transaction_serialization) ... ok
test_R_raw_response_preservation (__main__.TestM3Obd.test_R_raw_response_preservation) ... ok
test_S_standard_decoder_formulas (__main__.TestM3Obd.test_S_standard_decoder_formulas) ... ok
test_T_destructive_command_rejection (__main__.TestM3Obd.test_T_destructive_command_rejection) ... ok

----------------------------------------------------------------------
Ran 20 tests in 0.001s

OK
```

Total regression test suite (M-1, M-2, M-3): **36 tests passing, 0 failures**.

---

## 7. Current Milestone Status

**`SEYYANEN MINI M-3 — READY FOR PHYSICAL OBD/PID TEST`**
