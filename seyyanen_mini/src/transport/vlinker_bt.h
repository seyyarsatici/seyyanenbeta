#ifndef VLINKER_BT_H
#define VLINKER_BT_H

#include <Arduino.h>
#include <BluetoothSerial.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include "mini_config.h"
#include "mini_types.h"

// ==============================================================================
// VLINKER BLUETOOTH CLASSIC SPP TRANSPORT (PHASE M-2 HARDENED)
// ==============================================================================

class VLinkerBluetoothTransport {
public:
    VLinkerBluetoothTransport();
    ~VLinkerBluetoothTransport();

    // Lifecycle
    bool begin(const char* localName = SEYYANEN_BT_DEVICE_NAME);
    void end();
    bool connect(const char* targetName = SEYYANEN_VLINKER_NAME, const char* targetMac = SEYYANEN_VLINKER_MAC);
    bool disconnect();
    bool reconnect();
    void update(); // Non-blocking periodic housekeeping & backoff retry

    // State & Identity Inspection
    bool isConnected() const;
    AdapterState getState() const;
    const char* getStateString() const;
    TransportError getLastError() const;
    const char* getLastErrorString() const;
    const AdapterIdentityInfo& getAdapterIdentity() const;
    const TransportHealth& getHealth() const;
    const char* getRemoteAddress() const;
    const char* getTargetName() const;
    bool isConnectingInProgress() const { return _connectingInProgress; }

    // MAC Caching Inspection & Control
    bool hasCachedMac() const { return _hasCachedMac; }
    const char* getCachedMac() const { return _cachedMac; }
    bool loadCachedMac();
    void saveCachedMac(const char* macStr);
    void clearCachedMac();

    // Target Filtering
    static bool isTargetDevice(const char* name);

    // Transport I/O Operations
    bool sendRaw(const uint8_t* data, size_t len);
    bool send(const char* cmd);
    int  receive(char* buffer, size_t maxLen, uint32_t timeoutMs);
    int  receiveUntil(char* buffer, size_t maxLen, char terminator, uint32_t timeoutMs);
    bool transact(const char* request, char* response, size_t maxLen, uint32_t timeoutMs = SEYYANEN_BT_TRANSACTION_TIMEOUT);
    void flushRx();

    // Safety Filter & Helpers
    static bool isCommandSafe(const char* cmd);
    static bool parseMacAddress(const char* macStr, uint8_t* outBytes);

private:
    mutable BluetoothSerial _btSerial;
    SemaphoreHandle_t   _busMutex;
    AdapterState        _state;
    TransportError      _lastError;
    AdapterIdentityInfo _identity;
    TransportHealth     _health;

    char                _targetName[32];
    char                _targetMac[24];
    uint8_t             _macBytes[6];
    bool                _hasMacTarget;

    char                _cachedMac[24];
    uint8_t             _cachedMacBytes[6];
    bool                _hasCachedMac;
    uint32_t            _macConnectFailures;

    bool                _btStarted;
    volatile bool       _workerRunning;
    volatile bool       _connectingInProgress;
    volatile bool       _abortConnection;
    volatile bool       _discoveredTarget;
    TaskHandle_t        _connectTaskHandle;
    uint32_t            _lastAttemptMs;
    uint32_t            _currentBackoffMs;

    static void onDeviceDiscovered(BTAdvertisedDevice* dev);
    static VLinkerBluetoothTransport* s_discoveryInstance;

    void setState(AdapterState newState, TransportError err = TRANSPORT_ERR_NONE);
    bool performIdentityHandshake();
    void parseIdentityResponse(const char* rawResponse);
    void cancelConnectTask();
    static void connectTaskWorker(void* param);
};

#endif // VLINKER_BT_H
