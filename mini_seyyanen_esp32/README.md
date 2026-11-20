# Mini Seyyanen ESP32

Standalone read-only OBD-II dashboard for an original ESP32-based 2.8-inch CYD board and a VLinker MC+ adapter. It displays ECT, throttle, MAP, STFT Bank 1 and LTFT Bank 1. It does not send ECU write, reset, actuator, or unrestricted scan requests.

## Hardware assumptions

The board is in the Sunton/Jingcai ESP32-2432S028R family and uses an original ESP32-WROOM module. The manufacturer's product specification for the `ESP32-2432S028R` SKU lists an ILI9341 TFT; the V0.1 schematic documents the XPT2046 touch controller and signal pins, but does not name the TFT driver IC. The two-USB (micro-USB + USB-C) physical revision described here creates uncertainty: some later CYD2USB boards/lookalikes use ST7789 even when vendor listings reuse the family name. ILI9341 is the firmware default from the manufacturer's SKU specification, not a confirmed measurement of this particular unit. The classic ESP32 supports Bluetooth BR/EDR and SPP; the USB CH340 is only for upload and serial logging.

This is a likely match, not an identification of the individual board. Product revisions and lookalike CYD boards change GPIO assignments and sometimes parts. In particular, two USB connectors and the module marking alone do not prove the exact PCB revision or TFT controller. Before wiring or uploading, compare the board silkscreen/revision and component layout with the [manufacturer board specification](https://make.net.za/wp-content/datasheets/Shenzhen%20Jingcai%20Intelligent%20ESP32-2432S028R%20Product%20Spec.pdf) and [V0.1 schematic](https://www.ardboard.com/downloads/ESP32_2432S028R_Schematics.pdf).

| Function | Likely controller / GPIO |
| --- | --- |
| TFT | ILI9341, 240x320 panel rotated to 320x240; SPI SCLK 14, MOSI 13, MISO 12, CS 15, DC 2, reset tied to board reset |
| TFT backlight | GPIO 21, active high via board transistor |
| Resistive touch | XPT2046; separate SPI SCLK 25, MOSI 32, MISO 39, CS 33, IRQ 36 |
| MCU Bluetooth | Original ESP32 BR/EDR + SPP; `BluetoothSerial` initiator/client |
| USB | CH340 serial for flashing and diagnostics only |

Pins, panel setup, touch calibration and rotation are isolated in `include/config.h` and the panel constructor in `src/display_manager.cpp`. To switch the TFT driver, set `MINI_SEYYANEN_TFT_ST7789` to `1` or `0` in `include/config.h`; ST7789 also uses a different inversion setting. There is no automatic fallback: verify the TFT controller and PCB revision before manually changing the driver. The physical touch controller and pin map should also be checked against the PCB revision.

### Touch calibration

The default raw coordinate range (200–3900) is a starting point. Open the serial monitor and temporarily use a touch calibration sketch or inspect `TS_Point` raw values; set min/max and swap/invert options in `config.h` for all four screen corners. Confirm a short tap does not change the theme and a deliberate left or right horizontal stroke does.

## VLinker MC+ Bluetooth

The ESP32 uses the Bluetooth radio directly; Windows COM port numbers do not apply. Arduino-ESP32 `BluetoothSerial` implements Classic Bluetooth SPP and initiator mode. Vgate documentation distinguishes the MC+ Android/Windows Bluetooth connection (`vLinker MC-Android`) from BLE app connections, and the owner's Windows COM-port usage is consistent with SPP. Therefore this firmware targets Classic SPP and deliberately does not implement BLE. If your device is a BLE-only variant, or an application-specific firmware/profile, this transport will not connect. Verify the exact adapter label/name/profile with the adapter paired to the PC before commissioning; actual ESP32-to-adapter connection is not claimed as tested.

Set `VlinkerName` or `VlinkerMac` in `include/config.h`. A non-empty MAC takes precedence; otherwise the firmware searches by name. The installed Arduino `BluetoothSerial` API does not expose the connected remote friendly name, so `VlinkerDisplayName` is the configurable label shown beside Bluetooth status. Pairing requirements depend on the adapter and its existing bond state; the firmware does not force a PIN. If initial pairing is required, follow the exact adapter instructions and verify the supported pairing flow. Remove the PC's active connection before connecting from the ESP32: the adapter may allow only one client at a time.

After SPP connects, the task sends `ATZ`, `ATE0`, `ATL0`, `ATS0`, `ATH0`, `ATSP0`, then `ATI` and `ATDP`, waiting for each `>` prompt and validating its response before proceeding. A failed/empty response is logged and the setup sequence retries from `ATZ`; OBD requests are held until setup completes. Adapter link and ECU state are independent. The initial `0100` automatic-protocol probe has a 12-second timeout. If AUTO does not produce a valid bitmap, firmware tries `ATSP4` (ISO 14230-4 KWP, 5-baud init, 10.4 kbaud), reads `ATDP`, and repeats `0100`. This selection is based on the vehicle protocol specified for the target vehicle; actual ECU communication still requires physical verification. Only bitmap-supported required PIDs are polled, each with a 5-second timeout. Serial logs include each command, raw response, bitmap, and parsed PID value. `SEARCHING`, `BUS INIT`, `NO DATA`, `?`, `UNABLE TO CONNECT`, partial prompts and timeouts are distinguished; unavailable/invalid data is not converted to zero.

## Build and upload

1. Install Visual Studio Code with PlatformIO IDE, or install PlatformIO Core, plus Git for Windows (the XPT2046 dependency is pinned to its upstream Git tag).
2. Open `mini_seyyanen_esp32/` as the PlatformIO project. The first build downloads the declared Espressif platform, LovyanGFX and XPT2046 v1.4. The XPT2046 library is fetched from its upstream Git tag because PlatformIO's registry entry exposes only an alpha package.
3. Connect the board by USB and identify its CH340 COM port in Device Manager. Close any serial monitor using that port.
4. The default environment is the sole environment, `[env:esp32-2432s028r]`, in `platformio.ini`. `MINI_SEYYANEN_TFT_ST7789` is `0` in `include/config.h`, so the default build selects ILI9341. Build with **PlatformIO: Build** or `pio run`. Upload from PowerShell in the project directory with `pio run -t upload --upload-port COM7`, replacing `COM7` with the CH340 port from Device Manager. Close any program holding that COM port first.
5. Open **PlatformIO: Serial Monitor** at 115200 baud or run `pio device monitor --port COM7 --baud 115200`. Confirm boot logs, adapter discovery/connection, ATI/ATDP replies, and ECU response messages.

The project uses the generic `esp32dev` PlatformIO board target because the display board is a carrier around the classic ESP32 module. Do not use a C3/S2/S3 target: those chips do not provide the same built-in Classic SPP support. A CH340 serial port is required only for upload and logs; it is unrelated to the OBD Bluetooth link.

## Operation and data behavior

The screen has a compact top connection status and five evenly spaced rows, with no dashboard title or bottom footer. Bluetooth status and the configured VLinker label appear on the left; ECU status appears separately on the right. Each row keeps its label on the left and right-aligns the live value with its unit as a single group. DAY uses a light background, dark text, and neutral separators; NIGHT uses black with lime text and separators. Swipe left or right at least 65 mapped screen pixels to toggle themes; short taps and mostly vertical drags do not toggle. No button is shown. Touch down/up and swipe classification are logged over USB serial. Values refresh sequentially; `EcuResponseTimeoutMs` controls initial bitmap/AUTO/KWP probing and `PidResponseTimeoutMs` controls PID requests. The last successful value is shown for up to 5 seconds, then becomes `NONE`. Unsupported PIDs are skipped after the `0100` bitmap. These settings are in `config.h`.

The conversions match the existing Seyyanen `motor.py` definitions:

| Row | PID | Conversion | Unit |
| --- | --- | --- | --- |
| ECT | 05 | A − 40 | °C |
| THROTTLE POSITION | 11 | A × 100 / 255 | % |
| MAP | 0B | A | kPa |
| STFT | 06 | (A − 128) × 100 / 128 | % |
| LTFT | 07 | (A − 128) × 100 / 128 | % |

## Verification status

The firmware build has been verified, but this diagnostic revision has not been uploaded or tested against the physical VLinker/vehicle. The user's previous Bluetooth pairing report applies to the prior firmware revision; no successful ECU response is claimed. Hardware verification remains:

### First hardware smoke test

- **Display initialization:** power the board and confirm the panel lights, has landscape orientation, and shows a connection status (`CONNECTING`, `CONNECTED`, or `DISCONNECTED`) at the top.
- **Five-row layout:** confirm ECT, THROTTLE POSITION, MAP, STFT, and LTFT all fit within 320x240 without clipped labels, values, or units. Initial values may read `NONE`.
- **Themes:** confirm DAY is light with dark text and NIGHT is black with lime text; verify the same five rows remain visible in both.
- **Resistive touch:** swipe horizontally at least 65 mapped pixels in either direction to toggle themes. Confirm one theme change per swipe; a short tap or vertical drag should not toggle. Serial shows `[TOUCH] down`, `[TOUCH] up`, and the horizontal classification. Record whether raw-range or axis calibration is needed.
- **Serial debug:** open the CH340 port at 115200 baud. Confirm the startup message and connection-state / SPP logs. Leave the VLinker disconnected for part of this check and verify the display and touch still respond while Bluetooth reports disconnected or connecting.

- Confirm PCB revision, TFT controller, touch controller, and pinout against the actual board.
- Build/upload through the CH340; verify rotation, colors, five-row fit, touch calibration, and swipe threshold.
- Discover/connect to the exact MC+ over SPP, confirm full prompt-terminated `ATI` and `ATDP` responses, then disconnect it from the PC first.
- With ignition in the required state, verify `0100` support bitmap and all five positive responses/formulas on the target ECU.
- Remove adapter power or Bluetooth range and confirm UI remains responsive, stale data becomes `NONE`, and reconnect succeeds.

## Source reuse

The Python application is not run on the ESP32. The C++ port follows the standard PID conversion entries in `motor.py`, and keeps the minimal AT initialization/prompt handling in line with the existing adapter conventions in `diagnostic_adapter.py`. Only standard Mode 01 read requests are sent.
