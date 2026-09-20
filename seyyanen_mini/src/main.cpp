#include <Arduino.h>
#include "mini_config.h"
#include "mini_types.h"
#include "transport/vlinker_bt.h"
#include "obd/elm327.h"
#include "obd/obd2_client.h"
#include "obd/pid_scanner.h"
#include "acquisition/sample.h"
#include "acquisition/quality.h"
#include "acquisition/scheduler.h"
#include "storage/sd_logger.h"
#include "web/web_server.h"

// ==============================================================================
// SEYYANEN MINI - PHASE M-5 APPLICATION ENTRY POINT
// ==============================================================================

// Core Subsystems Owned in Phase M-5
static VLinkerBluetoothTransport btTransport;
static Elm327Client              elmClient(btTransport);
static Obd2Client                obdClient(elmClient);
static PidScanner                pidScanner(obdClient);
static SampleRingBuffer          sampleRingBuffer;
static SdLogger                  sdLogger;
static AcquisitionScheduler      acqScheduler(btTransport, obdClient, pidScanner, sampleRingBuffer);
static MiniWebServer             webServer(btTransport, elmClient, pidScanner, acqScheduler, sdLogger);

// State Flags for Auto-Sequence
static bool g_autoSequenceStarted = false;

void printBanner() {
    Serial.println("\n==================================================");
    Serial.println("   SEYYANEN MINI — PHASE M-5: SD PERSISTENCE      ");
    Serial.println("   Target: ESP32-WROOM-32D / Bluetooth Classic    ");
    Serial.println("   Storage: SPI MicroSD / Bounded In-Memory Write ");
    Serial.println("   Data Model: Raw Evidence + Normalized + Decoded");
    Serial.println("   Integrity: Failure != Zero / Safe File Rotation");
    Serial.println("==================================================\n");
}

void setup() {
    // 1. Initialize Host Serial Diagnostics
    Serial.begin(SEYYANEN_SERIAL_BAUD);
    delay(400);
    printBanner();

    // 2. Initialize MicroSD Persistence Logger
    if (sdLogger.begin()) {
        Serial.println("[SYSTEM] MicroSD logging engine mounted and ready.");
        acqScheduler.setLogger(&sdLogger);
    } else {
        Serial.println("[SYSTEM] MicroSD card not present or failed mount. Continuing in live-only mode.");
    }

    // 3. Initialize Wi-Fi Access Point & Web Monitor
    Serial.println("[SYSTEM] Starting Web Server & Wi-Fi SoftAP...");
    if (webServer.begin()) {
        Serial.printf("[SYSTEM] Web Dashboard ready at http://%u.%u.%u.%u\n", 
                      SEYYANEN_AP_IP);
    }

    // 4. Initialize Bluetooth Classic SPP Transport
    Serial.println("[SYSTEM] Initializing VLinker Bluetooth Classic Transport...");
    if (btTransport.begin(SEYYANEN_BT_DEVICE_NAME)) {
        Serial.println("[SYSTEM] Bluetooth Classic SPP master initialized successfully.");
    } else {
        Serial.println("[SYSTEM] CRITICAL: Bluetooth Classic initialization failed!");
    }

    // 5. Initial Connection Attempt
    Serial.printf("[SYSTEM] Attempting connection to target: '%s'...\n", SEYYANEN_VLINKER_NAME);
    btTransport.connect(SEYYANEN_VLINKER_NAME, SEYYANEN_VLINKER_MAC);

    Serial.println("[SYSTEM] System initialization complete. Scheduler in IDLE state.");
    Serial.println("[SYSTEM] Awaiting BT Link & OBD Discovery before starting acquisition.\n");
}

void loop() {
    // 1. Handle Web Client HTTP Requests
    webServer.update();

    // 2. Transport Housekeeping & Reconnection Loop
    btTransport.update();

    // 3. MicroSD Logger Housekeeping & Periodic Flush
    sdLogger.update();

    // 4. Automated Setup Progression: BT CONNECTED -> ELM327 INIT -> PID SCAN -> READY
    // In accordance with Section 25: remain in IDLE until explicit command to start.
    if (btTransport.isConnected()) {
        if (!g_autoSequenceStarted) {
            g_autoSequenceStarted = true;
            Serial.println("[SYSTEM] Bluetooth link verified. Initializing ELM327 OBD layer...");

            if (elmClient.initialize()) {
                Serial.println("[SYSTEM] ELM327 initialized successfully! Running supported PID scan...");
                if (pidScanner.scanSupportedPids()) {
                    Serial.println("[SYSTEM] Supported PID discovery complete! Setting up active schedule...");
                    acqScheduler.setupActiveSchedule();
                    Serial.println("[SYSTEM] Acquisition Scheduler ready in IDLE state. Awaiting start command.");
                }
            } else {
                Serial.println("[SYSTEM] ELM327 initialization failed. Check vehicle ignition / ECU connection.");
            }
        }
    } else {
        // Reset sequence flag on disconnect so it runs again when reconnected
        if (g_autoSequenceStarted) {
            g_autoSequenceStarted = false;
        }
    }

    // 5. Cooperative Non-Blocking Acquisition Scheduler Step
    acqScheduler.update();

    yield();
}
