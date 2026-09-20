#ifndef WEB_SERVER_H
#define WEB_SERVER_H

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "transport/vlinker_bt.h"
#include "obd/elm327.h"
#include "obd/pid_scanner.h"
#include "acquisition/scheduler.h"
#include "storage/sd_logger.h"
#include "mini_config.h"

// ==============================================================================
// SEYYANEN MINI - PHASE M-5 WEB SERVER & STORAGE REST API
// ==============================================================================

class MiniWebServer {
public:
    MiniWebServer(VLinkerBluetoothTransport& bt,
                  Elm327Client& elm,
                  PidScanner& scanner,
                  AcquisitionScheduler& scheduler,
                  SdLogger& logger);
    ~MiniWebServer();

    bool begin();
    void update();

private:
    WebServer                  _server;
    VLinkerBluetoothTransport& _bt;
    Elm327Client&             _elm;
    PidScanner&               _scanner;
    AcquisitionScheduler&     _scheduler;
    SdLogger&                 _logger;

    void setupRoutes();

    // Handlers
    void handleRoot();
    void handleApiStatus();
    void handleApiLive();
    void handleApiMetrics();
    void handleApiPids();
    void handleApiConnect();
    void handleApiDisconnect();
    void handleApiReconnect();
    void handleApiObdInit();
    void handleApiObdScan();
    void handleApiAcqStart();
    void handleApiAcqStop();
    void handleApiAcqPause();
    void handleApiAcqResume();

    // Phase M-5 Storage & Session Endpoints
    void handleApiStorageStatus();
    void handleApiSessions();
    void handleApiSessionMetadata();
    void handleApiSessionDownload();
    void handleApiRecordingStart();
    void handleApiRecordingStop();

    void handleNotFound();
};

#endif // WEB_SERVER_H
