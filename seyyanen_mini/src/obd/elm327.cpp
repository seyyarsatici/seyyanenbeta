#include "elm327.h"
#include <ctype.h>
#include <string.h>

Elm327Client::Elm327Client(VLinkerBluetoothTransport& transport)
    : _transport(transport),
      _state(ELM_STATE_UNINITIALIZED) {
    strncpy(_protocol, "AUTO (SEARCHING)", sizeof(_protocol) - 1);
}

Elm327Client::~Elm327Client() {}

void Elm327Client::reset() {
    _state = ELM_STATE_UNINITIALIZED;
    strncpy(_protocol, "UNKNOWN", sizeof(_protocol) - 1);
}

Elm327State Elm327Client::getState() const {
    return _state;
}

const char* Elm327Client::getStateString() const {
    return elm327StateToString(_state);
}

bool Elm327Client::isReady() const {
    return (_state == ELM_STATE_READY) && _transport.isConnected();
}

const char* Elm327Client::getProtocol() const {
    return _protocol;
}

const char* Elm327Client::getRawIdentity() const {
    return _transport.getAdapterIdentity().raw_identity;
}

AdapterBrand Elm327Client::getBrand() const {
    return _transport.getAdapterIdentity().brand;
}

const char* Elm327Client::getBrandName() const {
    return adapterBrandToString(getBrand());
}

bool Elm327Client::executeInitCommand(const char* cmd, const char* name, uint32_t timeoutMs) {
    char raw[64];
    memset(raw, 0, sizeof(raw));

    uint32_t latency;
    SampleStatus status = query(cmd, raw, sizeof(raw), latency, timeoutMs);

    if (status != SAMPLE_STATUS_VALID) {
        Serial.printf("[MINI-OBD] %s (%s) failed! Status: %s, Raw: '%s'\n",
                      cmd, name, sampleStatusToString(status), raw);
        return false;
    }

    char clean[64];
    cleanResponse(raw, clean, sizeof(clean));

    // Accept OK, adapter banners, protocol strings, or numbers
    if (strstr(clean, "OK") != NULL ||
        strstr(clean, "ELM") != NULL ||
        strstr(clean, "VLINKER") != NULL ||
        strstr(clean, "OBD") != NULL ||
        strstr(clean, "STN") != NULL ||
        strstr(clean, "AUTO") != NULL ||
        strstr(clean, "SEARCHING") != NULL ||
        strstr(clean, "ISO") != NULL ||
        strstr(clean, "CAN") != NULL ||
        strstr(clean, "J1850") != NULL ||
        strstr(clean, "41") != NULL ||
        strlen(clean) > 0) {
        
        Serial.printf("[MINI-OBD] %s -> OK (%s)\n", cmd, clean);
        return true;
    }

    Serial.printf("[MINI-OBD] %s -> UNEXPECTED RESPONSE: '%s'\n", cmd, clean);
    return false;
}

bool Elm327Client::initialize() {
    if (!_transport.isConnected()) {
        Serial.println("[MINI-OBD] Cannot initialize: VLinker transport is not CONNECTED!");
        _state = ELM_STATE_TRANSPORT_ERROR;
        return false;
    }

    _state = ELM_STATE_INITIALIZING;
    strncpy(_protocol, "AUTO (SEARCHING)", sizeof(_protocol) - 1);
    Serial.println("[MINI-OBD] ELM327 initialization started");

    // 1. ATZ (Reset adapter)
    delay(200);
    if (!executeInitCommand("ATZ", "Reset Adapter", 2000)) {
        _state = ELM_STATE_INVALID_RESPONSE;
        return false;
    }
    delay(600); // Allow adapter micro-controller to complete restart

    // 2. ATE0 (Echo off)
    if (!executeInitCommand("ATE0", "Echo Off", 600)) {
        _state = ELM_STATE_INVALID_RESPONSE;
        return false;
    }

    // 3. ATL0 (Linefeeds off)
    if (!executeInitCommand("ATL0", "Linefeeds Off", 600)) {
        _state = ELM_STATE_INVALID_RESPONSE;
        return false;
    }

    // 4. ATS0 (Spaces off)
    if (!executeInitCommand("ATS0", "Spaces Off", 600)) {
        _state = ELM_STATE_INVALID_RESPONSE;
        return false;
    }

    // 5. ATH0 (Headers off for standard Mode 01)
    if (!executeInitCommand("ATH0", "Headers Off", 600)) {
        _state = ELM_STATE_INVALID_RESPONSE;
        return false;
    }

    // 6. ATSP0 (Automatic protocol detection)
    if (!executeInitCommand("ATSP0", "Set Protocol Auto", 1000)) {
        _state = ELM_STATE_INVALID_RESPONSE;
        return false;
    }

    // 7. ATDP (Display Protocol description)
    char dpRaw[64];
    uint32_t dpLatency;
    if (query("ATDP", dpRaw, sizeof(dpRaw), dpLatency, 1000) == SAMPLE_STATUS_VALID) {
        char dpClean[32];
        cleanResponse(dpRaw, dpClean, sizeof(dpClean));
        if (strlen(dpClean) > 0 && strcmp(dpClean, "?") != 0) {
            strncpy(_protocol, dpClean, sizeof(_protocol) - 1);
        }
    }
    Serial.printf("[MINI-OBD] Active vehicle protocol: %s\n", _protocol);

    _state = ELM_STATE_READY;
    Serial.println("[MINI-OBD] OBD layer READY");
    return true;
}

SampleStatus Elm327Client::query(const char* cmd, char* rawOut, size_t maxLen, uint32_t& latencyMs, uint32_t timeoutMs) {
    if (!cmd || !rawOut || maxLen == 0) {
        return SAMPLE_STATUS_MALFORMED;
    }
    rawOut[0] = '\0';
    latencyMs = 0;

    if (!_transport.isConnected()) {
        return SAMPLE_STATUS_TRANSPORT_ERR;
    }

    if (!VLinkerBluetoothTransport::isCommandSafe(cmd)) {
        return SAMPLE_STATUS_SAFETY_BLOCKED;
    }

    uint32_t tStart = millis();
    bool ok = _transport.transact(cmd, rawOut, maxLen, timeoutMs);
    uint32_t tEnd = millis();
    latencyMs = (tEnd >= tStart) ? (tEnd - tStart) : 0;

    if (!ok) {
        if (_transport.getLastError() == TRANSPORT_ERR_TRANSACTION_TIMEOUT) {
            return SAMPLE_STATUS_TIMEOUT;
        }
        return SAMPLE_STATUS_TRANSPORT_ERR;
    }

    if (strlen(rawOut) == 0) {
        return SAMPLE_STATUS_NO_DATA;
    }

    char clean[64];
    cleanResponse(rawOut, clean, sizeof(clean));

    if (isErrorResponse(clean)) {
        if (strstr(clean, "NODATA") != NULL) {
            return SAMPLE_STATUS_NO_DATA;
        }
        if (strstr(clean, "UNABLETOCONNECT") != NULL || strstr(clean, "BUSINIT") != NULL) {
            return SAMPLE_STATUS_PROTOCOL_ERR;
        }
        return SAMPLE_STATUS_MALFORMED;
    }

    return SAMPLE_STATUS_VALID;
}

void Elm327Client::cleanResponse(const char* raw, char* cleaned, size_t maxLen) {
    if (!raw || !cleaned || maxLen == 0) return;

    size_t outIdx = 0;
    for (size_t i = 0; raw[i] != '\0' && outIdx < (maxLen - 1); ++i) {
        char c = raw[i];
        if (c != '\r' && c != '\n' && c != '>' && c != ' ') {
            cleaned[outIdx++] = (char)toupper((unsigned char)c);
        }
    }
    cleaned[outIdx] = '\0';
}

bool Elm327Client::isErrorResponse(const char* cleaned) {
    if (!cleaned || strlen(cleaned) == 0) return true;
    if (strstr(cleaned, "NODATA") != NULL ||
        strstr(cleaned, "STOPPED") != NULL ||
        strstr(cleaned, "UNABLETOCONNECT") != NULL ||
        strstr(cleaned, "BUSINIT") != NULL ||
        strstr(cleaned, "CANERROR") != NULL ||
        strstr(cleaned, "ERROR") != NULL ||
        strcmp(cleaned, "?") == 0) {
        return true;
    }
    return false;
}
