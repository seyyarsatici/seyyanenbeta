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
// Simulated response times 100/500/700/1500/3000 ms plus five 500 ms request
// intervals make one five-PID sweep about 8.3 s. 20 s exceeds that cycle while
// still expiring data that stops updating; vehicle timing is not yet measured.
constexpr uint32_t StaleTimeoutMs = 20000;
// AUTO search/KWP initialization can exceed short ELM timeouts; allow 25 s for
// the initial bitmap response. Physical timing remains unverified.
constexpr uint32_t EcuResponseTimeoutMs = 25000;
constexpr uint32_t PidResponseTimeoutMs = 5000;
constexpr uint32_t EcuRetryIntervalMs = 8000;
// If a timed-out SPP command never yields its old prompt, disconnect/reconnect
// the adapter to establish a fresh response stream instead of guessing by silence.
constexpr uint32_t SppResyncTimeoutMs = 8000;
constexpr uint8_t PidFailureLimit = 3;
constexpr uint16_t SwipeThresholdPx = 65;
}
