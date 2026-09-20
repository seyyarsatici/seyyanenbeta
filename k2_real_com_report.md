# Phase K-2 Real COM Port Selection & Hardware Connection Audit Report

## 1. Executive Summary

- **Phase Objective:** Resolve real Windows COM-port selection and eliminate silent `COM_MOCK` / `MockSerial` fallback during real-vehicle validation when clicking "OBD Connect" in GUI or connecting via `LiveAcquisitionRuntime` / `ELM327DiagnosticAdapter`.
- **Target Hardware Architecture:** Real ELM327-compatible Bluetooth / USB Serial adapter connected to a Windows host exposing dual COM ports (e.g. COM3 incoming / COM4 outgoing).
- **Audit Outcome:** 100% automated regression and unit test pass across all 176 tests in the Seyyanen test suite. Real COM discovery and non-destructive handshake implemented without modifying safety gates, diagnostic intelligence, or dual authorization barriers.
- **Current Certification Status:**
  `K-2 REAL COM PASS — READY FOR PHYSICAL ELM327 TEST`

---

## 2. Exact Root Cause Analysis: Silent COM_MOCK Activation

Prior to this fix, clicking "OBD Connect" in the GUI immediately entered simulation mode with the following console trace:
```text
"🔌 Simülasyon Aktif: MockSerial Kullanılıyor"
"🚀 Bağlantı Başlatılıyor: COM_MOCK"
"🔌 MOCK SİMÜLATÖR V107 BAŞLATILDI"
```

The investigation identified the exact chain of triggers across three repository locations:

1. **`motor.py` line 40:**
   ```python
   try:
       from mock_serial import MockSerial
       MOCK_AVAILABLE = True
   except ImportError:
       MOCK_AVAILABLE = False
   ```
   Because `mock_serial.py` exists on disk in the project directory, `MOCK_AVAILABLE` was set to `True` unconditionally on every startup.

2. **`motor.py:port_secici()` (lines 444-448):**
   ```python
   if MOCK_AVAILABLE:
       print("🔌 Simülasyon Aktif: MockSerial Kullanılıyor")
       return "COM_MOCK"
   ```
   Whenever a COM port was not explicitly provided by the caller, `port_secici()` checked `if MOCK_AVAILABLE: return "COM_MOCK"`. This completely aborted any search for real Windows serial ports.

3. **`motor.py:AutoExpertEngine.baglan()` (lines 849-854):**
   ```python
   if MOCK_AVAILABLE:
       self.ser = MockSerial(port=selected_port, ...)
   ```
   Regardless of whether a user had a real adapter plugged in, `baglan()` instantiated `MockSerial` whenever `MOCK_AVAILABLE` was True.

4. **`diagnostic_adapter.py:_do_connect()`:**
   `ELM327DiagnosticAdapter` previously delegated directly to `self.engine.baglan()`, surrendering J-1 adapter authority to `motor.py`'s unconditional mock check.

---

## 3. Architecture & Code Changes

To preserve the J-1 adapter authority, K-1 non-blocking runtime, K-2 serial transport, and K-3 trusted acquisition pipeline without modifying any diagnostic intelligence layers (D, H, I, L), the following targeted modifications were made:

### 3.1 `motor.py`
- **Added `is_simulation_mode(explicit)` helper:** Inspects explicit parameters, CLI flags (`--simulation`, `--mock`), and environment variable `SIMULATION=true`.
- **Refactored `port_secici(simulation=None, interactive=False)`:**
  - Removed unconditional `if MOCK_AVAILABLE: return "COM_MOCK"`.
  - Only returns `"COM_MOCK"` if `is_simulation_mode(simulation)` is strictly `True`.
  - For normal production mode, discovers real candidate COM ports via `diagnostic_adapter.enumerate_candidate_ports()` and probes them. If none respond, returns `None` (preventing console `input()` prompts from hanging the Qt event loop).
- **Updated `AutoExpertEngine.__init__` & `baglan()`:**
  - Added `simulation: Optional[bool] = None`.
  - Initialized `self.bagli_port = None`.
  - In `baglan()`, only uses `MockSerial` if `selected_port == "COM_MOCK"` or simulation is explicitly active. Otherwise, establishes real physical serial communication via `serial.Serial(selected_port)`.

### 3.2 `diagnostic_adapter.py`
- **Added `PortProbeResult` Dataclass:**
  Exposes structured probe findings: `port`, `transport="serial"`, `connection_state`, `adapter_detected`, `adapter_identity`, `baudrate`, `failure_reason`, and `description`.
- **Implemented `enumerate_candidate_ports(explicit_port)`:**
  - Discovers all serial ports via `serial.tools.list_ports.comports()`.
  - Sorts candidates deterministically by priority:
    - Priority 0: Explicit user-specified port (e.g. `COM4`, normalized to uppercase).
    - Priority 1: Known VCI / OBD chipsets (CH340, FTDI, CP210, Prolific, vLinker, ELM327).
    - Priority 2: Bluetooth serial ports (`Standard Serial over Bluetooth link`).
    - Priority 3: Generic COM ports.
- **Implemented `probe_elm327_port(port, baudrates, timeout, serial_factory, on_status)`:**
  - Performs safe, strictly read-only handshake on candidate ports: sends `\r\rATZ\r` followed by `ATI\r`.
  - Validates plausible ELM327/OBD response markers (`ELM327`, `OBDLINK`, `VLINKER`, `STN`, `OK`, `>`).
  - Closes candidate handles immediately upon probe completion (zero handle leaks).
- **Implemented `discover_and_probe_elm327(...)`:**
  - Arbitrates dual Bluetooth COM ports (e.g. COM3 vs COM4): probes candidates in order, tolerates silent timeouts on incoming ports, and successfully connects to the responding outgoing port.
- **Implemented `list_available_com_ports(verbose)` & CLI Support:**
  - Added CLI troubleshooting tool callable via `python diagnostic_adapter.py --list-ports`.
- **Preserved `ELM327DiagnosticAdapter` Authority in `_do_connect()`:**
  - Added explicit `simulation: bool = False` flag.
  - In normal hardware mode (`simulation=False`), automatically discovers and probes real candidate ports, opens dedicated physical serial link at detected baudrate (38400 / 9600 / 115200), executes deterministic ELM initialization, and connects the engine.
  - If no compatible hardware responds, raises `AdapterUnavailableError` and transitions state to `FAILED`. Never silently enters simulation.

### 3.3 `live_runtime.py`
- Added `simulation: bool = False` to `LiveAcquisitionRuntime.__init__`.
- Transferred `simulation` flag directly to `ELM327DiagnosticAdapter(simulation=self.simulation)`.

### 3.4 `live_ui.py`
- Updated `LivePresentationModel.get_connection_info`:
  - When real hardware is connected, formats status badge as `BAĞLI: COM4` (or `BAĞLI VE AKTİF`).
  - When simulation is explicitly active, formats badge as `SİMÜLASYON (COM_MOCK)`.
  - When connection fails, formats badge truthfully as `BAĞLANTI HATASI`.
- Updated `LiveConnectWorker`:
  - Emits truthful, technician-oriented messages describing the probed and selected COM port.

### 3.5 `main_ui.py`
- In `MainUI.__init__`, detects simulation flags from CLI arguments (`--simulation`, `--mock`) or environment (`SIMULATION=true`). Defaults to `simulation_mode = False`.
- In `open_live_diagnostics()`, instantiates `AutoExpertEngine` and `LiveAcquisitionRuntime` with `simulation=self.simulation_mode`.

---

## 4. Test Verification & Results

### 4.1 New Certification Test Suite (`test_phase_k2_real_com.py`)
All 13 specific scenarios passed:
- `test_A_real_com_enumeration`: Discovers and prioritizes VCI/Bluetooth ports.
- `test_B_explicit_com_selection`: Honors explicit user port without rediscovery.
- `test_C_candidate_probing_valid_elm327`: Validates non-destructive read-only ATZ/ATI handshake.
- `test_D_invalid_non_elm327_com_rejection`: Rejects incoming Bluetooth timeouts and garbage data.
- `test_E_dual_bluetooth_arbitration`: COM3 incoming times out; COM4 outgoing connects successfully.
- `test_F_no_device_truthful_failure`: Raises `AdapterUnavailableError`; no silent mock activation.
- `test_G_mock_mode_explicitly_enabled`: `simulation=True` permits `MockSerial` when explicitly asked.
- `test_H_mock_mode_not_silently_activated`: Normal mode without adapter fails truthfully.
- `test_I_gui_runtime_connection_state`: Presentation badges accurately reflect real COM vs mock.
- `test_J_and_K_probe_handles_cleaned_up_without_leak`: 9 probed serial instances closed cleanly.
- `test_L_k1_k3_invariants_preserved`: Non-blocking async connect and trusted acquisition remain intact.
- `test_11_regression_obd_connect_never_falls_back_to_mock`: Production GUI connect with no hardware fails truthfully.
- `test_diagnostic_list_available_com_ports`: `--list-ports` utility accurately lists OS ports.

### 4.2 Full Regression Test Suite
Executed the entire suite across all K and L phases:
```powershell
python -m unittest test_phase_k1.py test_phase_k2.py test_phase_k2_real_com.py test_phase_k3.py test_phase_kl_critical_audit.py test_phase_l1.py test_phase_l2.py
```
**Result:**
```text
Ran 176 tests in 14.330s
OK
```

---

## 5. Physical Validation Status

| Layer / Criteria | Status | Evidence |
|---|---|---|
| Windows COM Enumeration | CERTIFIED (Automated) | Prioritizes VCI & Bluetooth; 13/13 tests pass |
| Dual Bluetooth COM Arbitration | CERTIFIED (Automated) | COM3 incoming timeout rejected; COM4 outgoing chosen |
| Silent Mock Suppression | CERTIFIED (Automated) | Regression test proves `COM_MOCK` is never selected silently |
| Physical Hardware Validation | **READY FOR FIELD TEST** | Awaiting live vehicle/adapter connection by technician |

Final Status:
**`K-2 REAL COM PASS — READY FOR PHYSICAL ELM327 TEST`**
