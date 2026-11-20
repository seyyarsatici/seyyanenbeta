#pragma once
#include <Arduino.h>

// Original Sunton ESP32-2432S028R (classic ESP32-WROOM-32), V0.1 pin map.
// Confirm against your PCB/schematic before changing pins; revisions exist.
namespace Config {
// Manufacturer's ESP32-2432S028R specification says ILI9341. Some later
// dual-USB lookalikes/revisions have shipped with ST7789 instead; set to 1
// only after checking the board/packaging or running the display probe.
#define MINI_SEYYANEN_TFT_ST7789 0
constexpr int ScreenWidth = 320;
constexpr int ScreenHeight = 240;
constexpr int TftSclk = 14, TftMosi = 13, TftMiso = 12;
constexpr int TftCs = 15, TftDc = 2, TftRst = -1, Backlight = 21;
constexpr int TouchSclk = 25, TouchMosi = 32, TouchMiso = 39;
constexpr int TouchCs = 33, TouchIrq = 36;
// XPT2046 setRotation(1) is aligned with LovyanGFX rotation(1) on this panel.
constexpr bool TouchSwapXY = false;
constexpr bool TouchInvertX = false, TouchInvertY = false;
constexpr uint16_t TouchMinX = 200, TouchMaxX = 3900;
constexpr uint16_t TouchMinY = 200, TouchMaxY = 3900;

// Set one or both of these to configure the adapter. A MAC address takes
// precedence; otherwise a Bluetooth device-name inquiry is used.
constexpr char VlinkerName[] = "vLinker MC-Android";
constexpr char VlinkerMac[] = "";
// BluetoothSerial does not expose the remote friendly name after connecting.
// This label is shown in the dashboard when the adapter is connected.
constexpr char VlinkerDisplayName[] = "VLINKER MC+";
constexpr uint32_t PollIntervalMs = 500;
constexpr uint32_t StaleTimeoutMs = 5000;
// AUTO protocol search and KWP 5-baud initialization can exceed a short ELM timeout.
constexpr uint32_t EcuResponseTimeoutMs = 12000;
constexpr uint32_t PidResponseTimeoutMs = 5000;
constexpr uint16_t SwipeThresholdPx = 65;
}
