#include "vlinker_bt.h"
#include <ctype.h>
#include <string.h>

VLinkerBluetoothTransport::VLinkerBluetoothTransport()
    : _state(ADAPTER_STATE_DISCONNECTED),
      _lastError(TRANSPORT_ERR_NONE),
      _hasMacTarget(false),
      _btStarted(false),
      _connectingInProgress(false),
      _abortConnection(false),
      _connectTaskHandle(NULL),
      _lastAttemptMs(0),
      _currentBackoffMs(SEYYANEN_BT_BACKOFF_BASE_MS) {
    memset(&_identity, 0, sizeof(_identity));
    memset(&_health, 0, sizeof(_health));
    memset(_targetName, 0, sizeof(_targetName));
    memset(_targetMac, 0, sizeof(_targetMac));
    memset(_macBytes, 0, sizeof(_macBytes));

    strncpy(_identity.transport, "BLUETOOTH_SPP", sizeof(_identity.transport) - 1);
    strncpy(_identity.adapter_name, "UNKNOWN", sizeof(_identity.adapter_name) - 1);
    strncpy(_identity.manufacturer, "UNKNOWN", sizeof(_identity.manufacturer) - 1);
    strncpy(_identity.model, "UNKNOWN", sizeof(_identity.model) - 1);
    strncpy(_identity.firmware, "UNKNOWN", sizeof(_identity.firmware) - 1);
    strncpy(_identity.raw_identity, "UNKNOWN", sizeof(_identity.raw_identity) - 1);
    strncpy(_identity.remote_mac, "N/A", sizeof(_identity.remote_mac) - 1);
    _identity.brand = ADAPTER_BRAND_UNKNOWN;
    _identity.verified = false;

    _health.state = ADAPTER_STATE_DISCONNECTED;
    _health.last_error = TRANSPORT_ERR_NONE;
    _health.current_backoff_ms = SEYYANEN_BT_BACKOFF_BASE_MS;
}

VLinkerBluetoothTransport::~VLinkerBluetoothTransport() {
    cancelConnectTask();
    end();
}

void VLinkerBluetoothTransport::cancelConnectTask() {
    _abortConnection = true;
    if (_connectTaskHandle != NULL) {
        vTaskDelete(_connectTaskHandle);
        _connectTaskHandle = NULL;
    }
    _connectingInProgress = false;
}

bool VLinkerBluetoothTransport::begin(const char* localName) {
    if (_btStarted) {
        return true;
    }
    // Initialize BluetoothSerial in Master/Client mode
    if (!_btSerial.begin(localName, true)) {
        Serial.println("[MINI-BT] Bluetooth initialization failed!");
        setState(ADAPTER_STATE_ERROR, TRANSPORT_ERR_BT_INIT_FAILED);
        return false;
    }
    _btStarted = true;
    setState(ADAPTER_STATE_DISCONNECTED, TRANSPORT_ERR_NONE);
    Serial.printf("[MINI-BT] Bluetooth initialized. Device Name: '%s'\n", localName);
    return true;
}

void VLinkerBluetoothTransport::end() {
    disconnect();
    if (_btStarted) {
        _btSerial.end();
        _btStarted = false;
    }
    setState(ADAPTER_STATE_DISCONNECTED, TRANSPORT_ERR_NONE);
}

bool VLinkerBluetoothTransport::parseMacAddress(const char* macStr, uint8_t* outBytes) {
    if (!macStr || strlen(macStr) < 17 || !outBytes) return false;

    int values[6];
    int count = sscanf(macStr, "%x:%x:%x:%x:%x:%x", 
                       &values[0], &values[1], &values[2], 
                       &values[3], &values[4], &values[5]);
    if (count != 6) {
        count = sscanf(macStr, "%x-%x-%x-%x-%x-%x", 
                       &values[0], &values[1], &values[2], 
                       &values[3], &values[4], &values[5]);
    }
    if (count == 6) {
        for (int i = 0; i < 6; ++i) {
            outBytes[i] = (uint8_t)values[i];
        }
        return true;
    }
    return false;
}

void VLinkerBluetoothTransport::connectTaskWorker(void* param) {
    VLinkerBluetoothTransport* self = static_cast<VLinkerBluetoothTransport*>(param);
    if (!self) {
        vTaskDelete(NULL);
        return;
    }

    bool rawConnected = false;
    if (self->_hasMacTarget) {
        Serial.printf("[MINI-BT] Connecting SPP to target MAC: %s...\n", self->_targetMac);
        rawConnected = self->_btSerial.connect(self->_macBytes);
    } else {
        Serial.printf("[MINI-BT] Searching for target: %s...\n", self->_targetName);
        Serial.printf("[MINI-BT] Connecting SPP to target Name: '%s'...\n", self->_targetName);
        rawConnected = self->_btSerial.connect(self->_targetName);
    }

    if (self->_abortConnection) {
        self->_connectingInProgress = false;
        self->_connectTaskHandle = NULL;
        vTaskDelete(NULL);
        return;
    }

    if (!rawConnected) {
        Serial.println("[MINI-BT] State: ERROR");
        Serial.println("[MINI-BT] Reason: SPP_CONNECT_FAILED");
        self->setState(ADAPTER_STATE_ERROR, TRANSPORT_ERR_SPP_CONNECT_FAILED);
        self->_connectingInProgress = false;
        self->_connectTaskHandle = NULL;
        vTaskDelete(NULL);
        return;
    }

    Serial.println("[MINI-BT] SPP connected");

    // Physical link stabilization delay with abort check
    for (int i = 0; i < (SEYYANEN_BT_STABILIZE_DELAY_MS / 50); ++i) {
        if (self->_abortConnection) {
            self->disconnect();
            self->_connectingInProgress = false;
            self->_connectTaskHandle = NULL;
            vTaskDelete(NULL);
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    self->flushRx();

    // Mandatory Step: Adapter Identity Handshake (ATI)
    // Rule: Bluetooth link connected != diagnostic adapter verified!
    // The state transitions to CONNECTED only after ATI handshake succeeds.
    if (self->_abortConnection || !self->performIdentityHandshake()) {
        Serial.println("[MINI-BT] State: ERROR");
        Serial.println("[MINI-BT] Reason: INVALID_ADAPTER_RESPONSE");
        if (self->_btSerial.connected()) {
            self->_btSerial.disconnect();
        }
        self->_identity.verified = false;
        self->setState(ADAPTER_STATE_ERROR, TRANSPORT_ERR_INVALID_ADAPTER_RESPONSE);
        self->_connectingInProgress = false;
        self->_connectTaskHandle = NULL;
        vTaskDelete(NULL);
        return;
    }

    // Success: State transitions to CONNECTED only now!
    self->setState(ADAPTER_STATE_CONNECTED, TRANSPORT_ERR_NONE);
    self->_health.connected_since_ms = millis();
    self->_health.retry_count = 0;
    self->_currentBackoffMs = SEYYANEN_BT_BACKOFF_BASE_MS;
    self->_health.current_backoff_ms = self->_currentBackoffMs;

    Serial.println("[MINI-BT] State: CONNECTED");
    self->_connectingInProgress = false;
    self->_connectTaskHandle = NULL;
    vTaskDelete(NULL);
}

bool VLinkerBluetoothTransport::connect(const char* targetName, const char* targetMac) {
    // Prevent duplicate or concurrent connection attempts
    if (_state == ADAPTER_STATE_CONNECTED && _btSerial.connected() && _identity.verified) {
        Serial.println("[MINI-BT] Connect requested but transport is already CONNECTED and verified.");
        return true;
    }

    if (_connectingInProgress || _connectTaskHandle != NULL) {
        Serial.println("[MINI-BT] Connect attempt already in progress, ignoring duplicate call.");
        return false;
    }

    _connectingInProgress = true;
    _abortConnection = false;

    // Configure Target
    if (targetMac && strlen(targetMac) >= 17 && parseMacAddress(targetMac, _macBytes)) {
        strncpy(_targetMac, targetMac, sizeof(_targetMac) - 1);
        strncpy(_identity.remote_mac, targetMac, sizeof(_identity.remote_mac) - 1);
        _hasMacTarget = true;
    } else {
        _hasMacTarget = false;
        _targetMac[0] = '\0';
    }

    if (targetName && strlen(targetName) > 0) {
        strncpy(_targetName, targetName, sizeof(_targetName) - 1);
    } else {
        strncpy(_targetName, SEYYANEN_VLINKER_NAME, sizeof(_targetName) - 1);
    }

    if (!_btStarted) {
        if (!begin()) {
            _connectingInProgress = false;
            return false;
        }
    }

    setState(ADAPTER_STATE_CONNECTING, TRANSPORT_ERR_NONE);
    _lastAttemptMs = millis();

    // Dispatch non-blocking FreeRTOS connection worker
    BaseType_t res = xTaskCreate(
        connectTaskWorker,
        "btConnectTask",
        4096,
        this,
        1,
        &_connectTaskHandle
    );

    if (res != pdPASS) {
        Serial.println("[MINI-BT] Failed to spawn connection worker task!");
        setState(ADAPTER_STATE_ERROR, TRANSPORT_ERR_BT_INIT_FAILED);
        _connectingInProgress = false;
        _connectTaskHandle = NULL;
        return false;
    }

    return true;
}

bool VLinkerBluetoothTransport::disconnect() {
    cancelConnectTask(); // Always terminates worker and resets _connectingInProgress = false
    if (_btSerial.connected()) {
        _btSerial.disconnect();
    }
    _identity.verified = false;
    setState(ADAPTER_STATE_DISCONNECTED, TRANSPORT_ERR_NONE);
    Serial.println("[MINI-BT] SPP link disconnected.");
    return true;
}

bool VLinkerBluetoothTransport::reconnect() {
    Serial.println("[MINI-BT] Explicit reconnect requested.");
    disconnect();
    return connect(_targetName, _hasMacTarget ? _targetMac : NULL);
}

void VLinkerBluetoothTransport::update() {
    // 1. If CONNECTED, continuously verify hardware link health
    if (_state == ADAPTER_STATE_CONNECTED) {
        if (!_btSerial.connected()) {
            Serial.println("[MINI-BT] Link dropped unexpectedly. Transitioning to RECONNECTING.");
            _identity.verified = false;
            setState(ADAPTER_STATE_RECONNECTING, TRANSPORT_ERR_SPP_DISCONNECTED);
            _lastAttemptMs = millis();
        }
        return;
    }

    // 2. Auto-reconnect with exponential backoff if enabled
    if (SEYYANEN_BT_AUTO_RECONNECT && 
        (_state == ADAPTER_STATE_RECONNECTING || _state == ADAPTER_STATE_ERROR)) {
        
        if (!_connectingInProgress && _connectTaskHandle == NULL && (millis() - _lastAttemptMs >= _currentBackoffMs)) {
            _lastAttemptMs = millis();
            _health.retry_count++;

            Serial.printf("[MINI-BT] Reconnect attempt #%u after %u ms backoff...\n",
                          (unsigned int)_health.retry_count, (unsigned int)_currentBackoffMs);

            // Calculate next exponential backoff: 1s -> 2s -> 4s -> 8s -> 16s (bounded)
            _currentBackoffMs = _currentBackoffMs * 2;
            if (_currentBackoffMs > SEYYANEN_BT_BACKOFF_MAX_MS) {
                _currentBackoffMs = SEYYANEN_BT_BACKOFF_MAX_MS;
            }
            _health.current_backoff_ms = _currentBackoffMs;

            connect(_targetName, _hasMacTarget ? _targetMac : NULL);
        }
    }
}

bool VLinkerBluetoothTransport::performIdentityHandshake() {
    Serial.println("[MINI-BT] Sending ATI");

    char response[96];
    memset(response, 0, sizeof(response));

    flushRx();

    uint32_t tStart = millis();
    if (!send("ATI")) {
        _lastError = TRANSPORT_ERR_REMOTE_REJECTED;
        return false;
    }

    // Read until ELM327 / VLinker prompt '>'
    int bytes = receiveUntil(response, sizeof(response), '>', SEYYANEN_BT_ATI_TIMEOUT_MS);
    uint32_t tLatency = millis() - tStart;
    _health.last_latency_ms = tLatency;

    if (bytes <= 0) {
        Serial.printf("[MINI-BT] ATI failed to receive response within %u ms!\n", SEYYANEN_BT_ATI_TIMEOUT_MS);
        _lastError = TRANSPORT_ERR_TRANSACTION_TIMEOUT;
        return false;
    }

    Serial.printf("[MINI-BT] RX: %s\n", response);
    parseIdentityResponse(response);

    if (_identity.verified) {
        Serial.printf("[MINI-BT] Adapter verified: %s (Brand: %s, Model: %s, FW: %s)\n", 
                      _identity.adapter_name, adapterBrandToString(_identity.brand),
                      _identity.model, _identity.firmware);
        _health.last_successful_comm_ms = millis();
        _health.last_response_timestamp_ms = millis();
        return true;
    } else {
        Serial.printf("[MINI-BT] Unrecognized adapter response: '%s'\n", response);
        _lastError = TRANSPORT_ERR_INVALID_ADAPTER_RESPONSE;
        return false;
    }
}

void VLinkerBluetoothTransport::parseIdentityResponse(const char* rawResponse) {
    if (!rawResponse || strlen(rawResponse) == 0) {
        _identity.verified = false;
        return;
    }

    // Store cleaned raw identity
    char clean[64];
    size_t cIdx = 0;
    for (size_t i = 0; rawResponse[i] != '\0' && cIdx < sizeof(clean) - 1; ++i) {
        char ch = rawResponse[i];
        if (ch != '\r' && ch != '\n' && ch != '>') {
            clean[cIdx++] = ch;
        }
    }
    clean[cIdx] = '\0';
    strncpy(_identity.raw_identity, clean, sizeof(_identity.raw_identity) - 1);

    // Uppercase copy for substring detection
    char upper[64];
    for (size_t i = 0; clean[i] != '\0' && i < sizeof(upper) - 1; ++i) {
        upper[i] = (char)toupper((unsigned char)clean[i]);
    }
    upper[cIdx] = '\0';

    // Check identity markers
    if (strstr(upper, "VLINKER") != NULL) {
        _identity.brand = ADAPTER_BRAND_VLINKER;
        strncpy(_identity.adapter_name, "vLinker MC+", sizeof(_identity.adapter_name) - 1);
        strncpy(_identity.manufacturer, "MICROSYS", sizeof(_identity.manufacturer) - 1);
        strncpy(_identity.model, "MC+", sizeof(_identity.model) - 1);
        _identity.verified = true;
    } else if (strstr(upper, "OBDLINK") != NULL) {
        _identity.brand = ADAPTER_BRAND_OBDLINK;
        strncpy(_identity.adapter_name, "OBDLink", sizeof(_identity.adapter_name) - 1);
        strncpy(_identity.manufacturer, "OBDLink", sizeof(_identity.manufacturer) - 1);
        strncpy(_identity.model, "MX+", sizeof(_identity.model) - 1);
        _identity.verified = true;
    } else if (strstr(upper, "STN") != NULL) {
        _identity.brand = ADAPTER_BRAND_STN;
        strncpy(_identity.adapter_name, "STN Adapter", sizeof(_identity.adapter_name) - 1);
        strncpy(_identity.manufacturer, "OBD Solutions", sizeof(_identity.manufacturer) - 1);
        strncpy(_identity.model, "STN11xx/21xx", sizeof(_identity.model) - 1);
        _identity.verified = true;
    } else if (strstr(upper, "ELM327") != NULL) {
        _identity.brand = ADAPTER_BRAND_ELM327;
        strncpy(_identity.adapter_name, "ELM327 Compatible", sizeof(_identity.adapter_name) - 1);
        strncpy(_identity.manufacturer, "ELM Electronics", sizeof(_identity.manufacturer) - 1);
        strncpy(_identity.model, "ELM327", sizeof(_identity.model) - 1);
        _identity.verified = true;
    } else {
        _identity.brand = ADAPTER_BRAND_UNKNOWN;
        _identity.verified = false;
        return;
    }

    // Extract firmware version if present (e.g. "v2.2" or "v1.5")
    const char* vPos = clean;
    bool foundFw = false;
    while (*vPos != '\0') {
        if ((*vPos == 'v' || *vPos == 'V') && isdigit((unsigned char)*(vPos + 1))) {
            char fw[16] = {0};
            size_t f = 0;
            while (*vPos != '\0' && *vPos != ' ' && f < sizeof(fw) - 1) {
                fw[f++] = *vPos++;
            }
            fw[f] = '\0';
            strncpy(_identity.firmware, fw, sizeof(_identity.firmware) - 1);
            foundFw = true;
            break;
        }
        vPos++;
    }
    if (!foundFw) {
        strncpy(_identity.firmware, "UNKNOWN", sizeof(_identity.firmware) - 1);
    }
}

bool VLinkerBluetoothTransport::isConnected() const {
    return (_state == ADAPTER_STATE_CONNECTED) && _btSerial.connected() && _identity.verified;
}

AdapterState VLinkerBluetoothTransport::getState() const {
    return _state;
}

const char* VLinkerBluetoothTransport::getStateString() const {
    return adapterStateToString(_state);
}

TransportError VLinkerBluetoothTransport::getLastError() const {
    return _lastError;
}

const char* VLinkerBluetoothTransport::getLastErrorString() const {
    return transportErrorToString(_lastError);
}

const AdapterIdentityInfo& VLinkerBluetoothTransport::getAdapterIdentity() const {
    return _identity;
}

const TransportHealth& VLinkerBluetoothTransport::getHealth() const {
    return _health;
}

const char* VLinkerBluetoothTransport::getRemoteAddress() const {
    return _hasMacTarget ? _targetMac : _targetName;
}

const char* VLinkerBluetoothTransport::getTargetName() const {
    return _targetName;
}

void VLinkerBluetoothTransport::setState(AdapterState newState, TransportError err) {
    _state = newState;
    _health.state = newState;
    if (err != TRANSPORT_ERR_NONE || newState == ADAPTER_STATE_CONNECTED) {
        _lastError = err;
        _health.last_error = err;
    }
}

bool VLinkerBluetoothTransport::isCommandSafe(const char* cmd) {
    if (!cmd) return false;

    while (*cmd == ' ' || *cmd == '\t') cmd++;
    if (*cmd == '\0') return false;

    // AT commands are harmless configuration/inspection
    if ((cmd[0] == 'A' || cmd[0] == 'a') && (cmd[1] == 'T' || cmd[1] == 't')) {
        return true;
    }

    // Extract first 2 hex digits
    char hexMode[3] = {0};
    int i = 0;
    for (int k = 0; cmd[k] != '\0' && i < 2; ++k) {
        if (isxdigit((unsigned char)cmd[k])) {
            hexMode[i++] = (char)toupper((unsigned char)cmd[k]);
        }
    }
    if (i < 2) return false;

    // Block destructive OBD modes & UDS write services
    if (strcmp(hexMode, "04") == 0 || strcmp(hexMode, "08") == 0) {
        return false;
    }

    const char* blocked[] = {
        "10", "11", "27", "28", "2E", "31", "34", "35", "36", "37", "85", NULL
    };
    for (int b = 0; blocked[b] != NULL; ++b) {
        if (strcmp(hexMode, blocked[b]) == 0) {
            return false;
        }
    }

    return true;
}

bool VLinkerBluetoothTransport::sendRaw(const uint8_t* data, size_t len) {
    if (!_btSerial.connected() || !data || len == 0) {
        return false;
    }
    size_t written = _btSerial.write(data, len);
    _health.tx_byte_count += written;
    return (written == len);
}

bool VLinkerBluetoothTransport::send(const char* cmd) {
    if (!_btSerial.connected() || !cmd) {
        return false;
    }

    if (!isCommandSafe(cmd)) {
        Serial.printf("[MINI-BT] Command rejected by safety filter: %s\n", cmd);
        _lastError = TRANSPORT_ERR_SAFETY_BLOCKED;
        return false;
    }

    size_t len = strlen(cmd);
    size_t written = _btSerial.print(cmd);
    written += _btSerial.print("\r");
    _health.tx_byte_count += written;
    return (written >= len);
}

int VLinkerBluetoothTransport::receive(char* buffer, size_t maxLen, uint32_t timeoutMs) {
    if (!buffer || maxLen == 0) return 0;
    buffer[0] = '\0';

    if (!_btSerial.connected()) {
        _lastError = TRANSPORT_ERR_SPP_DISCONNECTED;
        return -1;
    }

    size_t idx = 0;
    uint32_t startMs = millis();

    while ((millis() - startMs) < timeoutMs) {
        while (_btSerial.available() > 0) {
            char c = (char)_btSerial.read();
            _health.rx_byte_count++;
            if (idx < maxLen - 1) {
                buffer[idx++] = c;
            }
        }
        if (idx > 0) {
            buffer[idx] = '\0';
            return (int)idx;
        }
        yield();
    }

    buffer[idx] = '\0';
    return (idx > 0) ? (int)idx : -2; // -2 = timeout
}

int VLinkerBluetoothTransport::receiveUntil(char* buffer, size_t maxLen, char terminator, uint32_t timeoutMs) {
    if (!buffer || maxLen == 0) return 0;
    buffer[0] = '\0';

    if (!_btSerial.connected()) {
        _lastError = TRANSPORT_ERR_SPP_DISCONNECTED;
        return -1;
    }

    size_t idx = 0;
    uint32_t startMs = millis();

    while ((millis() - startMs) < timeoutMs) {
        while (_btSerial.available() > 0) {
            char c = (char)_btSerial.read();
            _health.rx_byte_count++;

            if (c == terminator) {
                buffer[idx] = '\0';
                return (int)idx;
            }

            if (idx < maxLen - 1) {
                buffer[idx++] = c;
            }
        }
        yield();
    }

    buffer[idx] = '\0';
    return (idx > 0) ? (int)idx : -2;
}

bool VLinkerBluetoothTransport::transact(const char* request, char* response, size_t maxLen, uint32_t timeoutMs) {
    if (!request || !response || maxLen == 0) return false;
    response[0] = '\0';

    if (!isConnected()) {
        _lastError = TRANSPORT_ERR_SPP_DISCONNECTED;
        return false;
    }

    flushRx();

    uint32_t tStart = millis();
    if (!send(request)) {
        return false;
    }

    int bytes = receiveUntil(response, maxLen, '>', timeoutMs);
    uint32_t tLatency = millis() - tStart;
    _health.last_latency_ms = tLatency;

    if (bytes >= 0) {
        _health.last_successful_comm_ms = millis();
        _health.last_response_timestamp_ms = millis();
        return true;
    }

    _lastError = (bytes == -2) ? TRANSPORT_ERR_TRANSACTION_TIMEOUT : TRANSPORT_ERR_SPP_DISCONNECTED;
    return false;
}

void VLinkerBluetoothTransport::flushRx() {
    while (_btSerial.available() > 0) {
        _btSerial.read();
    }
}
