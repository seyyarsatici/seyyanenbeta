# Phase K-2 Real Hardware Walkthrough: ELM327 Windows Bluetooth / Serial Validation

> **STATUS:** `AUTOMATED TEST PASS — READY FOR PHYSICAL ELM327 TEST`  
> **VALIDATION TARGET:** Real Windows Bluetooth / USB Serial ELM327-compatible OBD adapter.  
> **DISTINCTION:** Automated regression tests have fully passed in software with mock hardware doubles. This walkthrough is the physical hardware validation procedure to be performed by the technician/engineer on the target Windows host with physical vehicle/OBD hardware.

---

## 1. Prerequisites & Adapter Pairing (Windows 10/11)

1. **Plug Adapter into Vehicle OBD-II Port:**
   - Connect your ELM327 adapter (e.g. vLinker FD+, OBDLink, or standard ELM327 Bluetooth) to the vehicle's 16-pin OBD-II port.
   - Switch vehicle ignition to **ON / RUN** (engine can be running or ignition-on; 12V OBD power LED on adapter must illuminate).

2. **Pair Bluetooth on Windows:**
   - Open **Windows Settings > Bluetooth & Devices**.
   - Ensure Bluetooth is turned **On**.
   - Click **Add device > Bluetooth**.
   - Select your OBD adapter (typically named `OBDII`, `vLinker`, `OBDLink`, or similar).
   - Enter PIN code if prompted (usually `1234` or `0000`).

---

## 2. Identify Windows COM Ports in Device Manager

Windows creates two virtual serial COM ports for standard Bluetooth SPP profiles: one **Incoming** (server) and one **Outgoing** (client). Only the **Outgoing** port can connect to the ELM327 adapter.

1. Press `Win + X` and select **Device Manager** (`devmgmt.msc`).
2. Expand the **Ports (COM & LPT)** section.
3. Note the COM port numbers assigned to Bluetooth:
   - For example:
     - `Standard Serial over Bluetooth link (COM3)`
     - `Standard Serial over Bluetooth link (COM4)`
4. *Optional Troubleshooting CLI:*
   Run the Seyyanen port inspection tool in PowerShell or Command Prompt:
   ```powershell
   python diagnostic_adapter.py --list-ports
   ```
   **Expected Output:**
   ```text
   Detected serial ports:
     - COM3 — Standard Serial over Bluetooth link (COM3) [Priority: Bluetooth]
     - COM4 — Standard Serial over Bluetooth link (COM4) [Priority: Bluetooth]
   ```

---

## 3. Launching Seyyanen in Real Hardware Mode

Run Seyyanen in normal production mode (**do NOT** provide `--simulation` or `--mock` flags):

```powershell
python main_ui.py
```

Verify that the console/startup logs **do not** announce:
```text
🔌 Simülasyon Aktif: MockSerial Kullanılıyor   <-- MUST NOT APPEAR
🚀 Bağlantı Başlatılıyor: COM_MOCK              <-- MUST NOT APPEAR
🔌 MOCK SİMÜLATÖR V107 BAŞLATILDI               <-- MUST NOT APPEAR
```

Instead, you should see normal initialization indicating real hardware mode.

---

## 4. Initiating OBD Connection

1. On the main window, click **🔗 OBD Bağlan** (or **🔎 OBD Sorgu**).
2. The **Canlı Teşhis (Live Diagnostics)** panel will appear.
3. Click **▶ Canlı Başlat**.
4. Observe the connection sequence in the UI badge and terminal log:
   - Badge changes to: `BAĞLANIYOR...` (Yellow)
   - Background worker probes candidate ports without freezing the GUI:
     ```text
     [INFO] Searching for OBD adapters across: COM3, COM4...
     [INFO] Testing COM3...
     [INFO] Testing COM3 at 38400 baud... (Times out safely on incoming port)
     [INFO] Testing COM4...
     [INFO] Testing COM4 at 38400 baud...
     [INFO] ELM327 detected on COM4 (ELM327 v1.5, 38400 baud)
     [INFO] Physical serial port 'COM4' opened at 38400 baud.
     ```
   - Top connection badge turns green:
     `BAĞLI: COM4` (Green)
   - Status detail confirms: `ECU canlı veri akışı aktif (COM4)`.

---

## 5. Verifying ELM327 Identity and Vehicle Live Data

1. **Observe Live Telemetry:**
   - PID table will populate with live sensor readings:
     - `010C` (Motor Devri / RPM)
     - `010D` (Araç Hızı / Speed)
     - `0105` (Motor Sıcaklığı / ECT)
   - Verify data quality badge shows `GÜVENİLİR (GOOD)`.
2. **Select Trend Curve:**
   - Click on row `010C` (RPM) to view the live graph.
   - Gently press accelerator pedal; verify waveform follows engine RPM dynamically.

---

## 6. What If No Adapter Is Connected? (Truthful Failure Verification)

If you attempt connection with the adapter unplugged or Bluetooth disconnected:
1. Click **▶ Canlı Başlat**.
2. Seyyanen probes all available COM ports.
3. It truthfully rejects unresponsive ports and presents an error dialog:
   ```text
   Kullanılabilir COM portlarında uyumlu ELM327 adaptörü bulunamadı.
   Port ve Bluetooth bağlantılarını kontrol edin.
   ```
4. Connection badge turns red: `BAĞLANTI HATASI`.
5. **CRITICAL VERIFICATION:** Under NO circumstances does Seyyanen enter `COM_MOCK` or fabricate vehicle data.

---

## 7. Explicit Simulation Mode (Development / CI Only)

If you need to run in mock simulation mode without vehicle hardware for test purposes:

```powershell
python main_ui.py --simulation
```
or
```powershell
$env:SIMULATION="true"; python main_ui.py
```

In this explicit mode, the GUI badge displays:
`SİMÜLASYON (COM_MOCK)` (Purple).
