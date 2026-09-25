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

// State Flags & Concurrency Controls for Diagnostic Operations
static bool                             g_autoSequenceStarted = false;
static volatile DiagnosticOpState       g_diagOpState = DIAG_OP_IDLE;
static volatile DiagnosticOpState       g_requestedOp = DIAG_OP_IDLE;
static TaskHandle_t                     g_diagTaskHandle = NULL;
static SemaphoreHandle_t                g_diagMutex = NULL;

static DiagnosticOpState getDiagOpState() {
    return g_diagOpState;
}

static bool requestDiagOp(DiagnosticOpState op) {
    if (g_diagMutex && xSemaphoreTake(g_diagMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        if (g_diagOpState != DIAG_OP_IDLE) {
            xSemaphoreGive(g_diagMutex);
            return false;
        }
        g_requestedOp = op;
        g_diagOpState = op;
        if (g_diagTaskHandle) {
            xTaskNotifyGive(g_diagTaskHandle);
        }
        xSemaphoreGive(g_diagMutex);
        return true;
    }
    return false;
}

static void diagTaskWorker(void* param) {
    (void)param;
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        DiagnosticOpState currentOp = g_requestedOp;
        if (currentOp == DIAG_OP_AUTO_SEQUENCE) {
            Serial.println("[SYSTEM] Starting background auto-sequence...");
            if (btTransport.isConnected()) {
                if (elmClient.initialize()) {
                    Serial.println("[SYSTEM] Auto-sequence: ELM327 initialized! Running PID scan...");
                    if (btTransport.isConnected() && pidScanner.scanSupportedPids()) {
                        Serial.println("[SYSTEM] Auto-sequence: PID scan complete! Setting up active schedule...");
                        acqScheduler.setupActiveSchedule();
                        Serial.println("[SYSTEM] Auto-sequence complete. Scheduler ready in IDLE state.");
                    } else {
                        Serial.println("[SYSTEM] Auto-sequence: PID scan aborted or failed.");
                    }
                } else {
                    Serial.println("[SYSTEM] Auto-sequence: ELM327 initialization failed.");
                }
            }
        } else if (currentOp == DIAG_OP_MANUAL_INIT) {
            Serial.println("[SYSTEM] Running manual ELM327 initialization in background...");
            elmClient.initialize();
        } else if (currentOp == DIAG_OP_MANUAL_SCAN) {
            Serial.println("[SYSTEM] Running manual PID scan in background...");
            if (pidScanner.scanSupportedPids()) {
                acqScheduler.setupActiveSchedule();
            }
        }

        if (g_diagMutex && xSemaphoreTake(g_diagMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
            g_diagOpState = DIAG_OP_IDLE;
            g_requestedOp = DIAG_OP_IDLE;
            xSemaphoreGive(g_diagMutex);
        } else {
            g_diagOpState = DIAG_OP_IDLE;
            g_requestedOp = DIAG_OP_IDLE;
        }
    }
}

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

    // 2. Initialize Diagnostic Concurrency Manager & Worker
    g_diagMutex = xSemaphoreCreateMutex();
    xTaskCreatePinnedToCore(
        diagTaskWorker,
        "diagTask",
        4096,
        NULL,
        1,
        &g_diagTaskHandle,
        0 // Core 0 (protocol core)
    );

    // 3. Initialize MicroSD Persistence Logger
    if (sdLogger.begin()) {
        Serial.println("[SYSTEM] MicroSD logging engine mounted and ready.");
        acqScheduler.setLogger(&sdLogger);
    } else {
        Serial.println("[SYSTEM] MicroSD card not present or failed mount. Continuing in live-only mode.");
    }

    // 4. Initialize Wi-Fi Access Point & Web Monitor
    Serial.println("[SYSTEM] Starting Web Server & Wi-Fi SoftAP...");
    webServer.setDiagOpCallbacks(requestDiagOp, getDiagOpState);
    if (webServer.begin()) {
        Serial.printf("[SYSTEM] Web Dashboard ready at http://%u.%u.%u.%u\n", 
                      SEYYANEN_AP_IP);
    }

    // 5. Initialize Bluetooth Classic SPP Transport
    Serial.println("[SYSTEM] Initializing VLinker Bluetooth Classic Transport...");
    if (btTransport.begin(SEYYANEN_BT_DEVICE_NAME)) {
        Serial.println("[SYSTEM] Bluetooth Classic SPP master initialized successfully.");
    } else {
        Serial.println("[SYSTEM] CRITICAL: Bluetooth Classic initialization failed!");
    }

    // 6. Initial Connection Attempt
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
    // Non-blocking background dispatching ensures loop() responsiveness
    if (btTransport.isConnected()) {
        if (!g_autoSequenceStarted && g_diagOpState == DIAG_OP_IDLE) {
            g_autoSequenceStarted = true;
            Serial.println("[SYSTEM] Bluetooth link verified. Triggering background auto-sequence...");
            requestDiagOp(DIAG_OP_AUTO_SEQUENCE);
        }
    } else {
        // Reset sequence flag and invalidate ELM state on disconnect
        if (g_autoSequenceStarted) {
            g_autoSequenceStarted = false;
            elmClient.reset();
        }
    }

    // 5. Cooperative Non-Blocking Acquisition Scheduler Step
    acqScheduler.update();

    // Cooperative yield allowing FreeRTOS Idle task and lwIP background tasks to execute
    delay(2);
}
