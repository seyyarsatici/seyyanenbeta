#ifndef MINI_CONFIG_H
#define MINI_CONFIG_H

#include <stdint.h>

// ==============================================================================
// SEYYANEN MINI - EMBEDDED CONFIGURATION CONSTANTS (PHASE M-5)
// ==============================================================================

// 1. Wi-Fi Access Point (Local Web Interface)
#define SEYYANEN_AP_SSID                "SEYYANEN-MINI"
#define SEYYANEN_AP_PASS                "seyyanen123"
#define SEYYANEN_AP_CHANNEL             1
#define SEYYANEN_AP_MAX_CONN            4
#define SEYYANEN_AP_IP                  192, 168, 4, 1
#define SEYYANEN_AP_GATEWAY             192, 168, 4, 1
#define SEYYANEN_AP_SUBNET              255, 255, 255, 0
#define SEYYANEN_HTTP_PORT              80

// 2. Bluetooth Classic SPP (VLinker MC+ / ELM327 / STN)
#define SEYYANEN_BT_DEVICE_NAME         "SeyyanenMini"
#define SEYYANEN_VLINKER_NAME           "vLinker MC"          // Target name substring
#define SEYYANEN_VLINKER_MAC            ""                    // Optional known MAC
#define SEYYANEN_BT_CONNECT_TIMEOUT_MS  12000                 // Timeout per SPP connect attempt
#define SEYYANEN_BT_STABILIZE_DELAY_MS  350                   // Pause after SPP link up before first TX
#define SEYYANEN_BT_TRANSACTION_TIMEOUT 2500                  // ms per command/response transaction
#define SEYYANEN_BT_ATI_TIMEOUT_MS      2000                  // Timeout specifically for ATI handshake
#define SEYYANEN_COMMAND_TIMEOUT        1200                  // ms per OBD query

// 3. Exponential Backoff Reconnect Parameters
#define SEYYANEN_BT_BACKOFF_BASE_MS     1000                  // Initial retry delay (1s)
#define SEYYANEN_BT_BACKOFF_MAX_MS      16000                 // Maximum bounded backoff (16s)
#define SEYYANEN_BT_AUTO_RECONNECT      true                  // Automatic reconnection

// 4. Acquisition Scheduler Polling Profiles (Phase M-4)
#define SEYYANEN_INTERVAL_FAST_MS       120                   // Fast: RPM, Throttle (120ms)
#define SEYYANEN_INTERVAL_MEDIUM_MS     350                   // Medium: MAP, MAF, Trims, Speed (350ms)
#define SEYYANEN_INTERVAL_SLOW_MS       1200                  // Slow: ECT, IAT, Load, Timing (1200ms)

// 5. Freshness Thresholds (Microseconds)
#define SEYYANEN_FRESH_THRESHOLD_US     600000ULL             // Fresh: < 0.6s
#define SEYYANEN_AGING_THRESHOLD_US     2500000ULL            // Aging: 0.6s .. 2.5s
#define SEYYANEN_STALE_THRESHOLD_US     5000000ULL            // Stale: >= 2.5s

// 6. Bounded In-Memory History
#define SEYYANEN_RING_BUFFER_SIZE       256                   // Maximum samples in RAM
#define SEYYANEN_MAX_SCHEDULED_PIDS     16                    // Maximum active PIDs in scheduler

// 7. MicroSD SPI Persistence (Phase M-5)
#define SEYYANEN_SD_CS_PIN              5                     // VSPI Chip Select (GPIO 5)
#define SEYYANEN_SD_MOSI_PIN            23                    // VSPI Master Out Slave In (GPIO 23)
#define SEYYANEN_SD_MISO_PIN            19                    // VSPI Master In Slave Out (GPIO 19)
#define SEYYANEN_SD_SCK_PIN             18                    // VSPI Clock (GPIO 18)
#define SEYYANEN_SD_SPI_FREQ            20000000              // 20 MHz SPI Clock
#define SEYYANEN_SD_WRITE_BUFFER_SIZE   1024                  // 1 KB bounded write buffer
#define SEYYANEN_SD_FLUSH_INTERVAL_MS   2000                  // Flush to card every 2 seconds
#define SEYYANEN_SD_BASE_DIR            "/SEYYANEN"
#define SEYYANEN_SD_SESSIONS_DIR        "/SEYYANEN/SESSIONS"
#define SEYYANEN_MAX_SESSIONS_LIST      32                    // Max sessions in directory listing

// 8. System Serial Debug
#define SEYYANEN_SERIAL_BAUD            115200

#endif // MINI_CONFIG_H
