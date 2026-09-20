#ifndef VLINKER_BT_H
#define VLINKER_BT_H

#include <Arduino.h>
#include <BluetoothSerial.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
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

    // Transport I/O Operations
    bool sendRaw(const uint8_t* data, size_t len);
    bool send(const char* cmd);
    int  receive(char* buffer, size_t maxLen, uint32_t timeoutMs);
    int  receiveUntil(char* buffer, size_t maxLen, char terminator, uint32_t timeoutMs);
    bool transact(const char* request, char* response, size_t maxLen, uint32_t timeoutMs = SEYYANEN_BT_TRANSACTION_TIMEOUT);
    void flushRx();

    // Safety Filter
    static bool isCommandSafe(const char* cmd);

private:
    BluetoothSerial     _btSerial;
    AdapterState        _state;
    TransportError      _lastError;
    AdapterIdentityInfo _identity;
    TransportHealth     _health;

    char                _targetName[32];
    char                _targetMac[24];
    uint8_t             _macBytes[6];
    bool                _hasMacTarget;

    bool                _btStarted;
    volatile bool       _connectingInProgress;
    volatile bool       _abortConnection;
    TaskHandle_t        _connectTaskHandle;
    uint32_t            _lastAttemptMs;
    uint32_t            _currentBackoffMs;

    void setState(AdapterState newState, TransportError err = TRANSPORT_ERR_NONE);
    bool parseMacAddress(const char* macStr, uint8_t* outBytes);
    bool performIdentityHandshake();
    void parseIdentityResponse(const char* rawResponse);
    void cancelConnectTask();
    static void connectTaskWorker(void* param);
};

#endif // VLINKER_BT_H
