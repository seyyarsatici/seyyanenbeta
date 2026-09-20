#include "obd2_client.h"
#include <string.h>

Obd2Client::Obd2Client(Elm327Client& elm)
    : _elm(elm) {}

Obd2Client::~Obd2Client() {}

bool Obd2Client::isReady() const {
    return _elm.isReady();
}

bool Obd2Client::isModeAllowed(uint8_t mode) {
    // Phase M-3 is strictly read-only Mode 01
    return (mode == 0x01);
}

ObdResult Obd2Client::request(uint8_t mode, uint8_t pid, uint32_t timeoutMs) {
    ObdResult res;
    memset(&res, 0, sizeof(res));
    res.timestamp_us = esp_timer_get_time();
    res.mode = mode;
    res.pid = pid;
    snprintf(res.request, sizeof(res.request), "%02X%02X", mode, pid);

    // 1. Safety Check: Only Mode 01 permitted
    if (!isModeAllowed(mode)) {
        res.status = SAMPLE_STATUS_SAFETY_BLOCKED;
        strncpy(res.error_msg, "MODE_BLOCKED_SAFETY", sizeof(res.error_msg) - 1);
        return res;
    }

    // 2. Hardware / Protocol Readiness Check
    if (!_elm.isReady()) {
        res.status = SAMPLE_STATUS_TRANSPORT_ERR;
        strncpy(res.error_msg, "ELM_NOT_READY", sizeof(res.error_msg) - 1);
        return res;
    }

    // 3. Execute query via ELM327 Client
    uint32_t latency = 0;
    SampleStatus qStat = _elm.query(res.request, res.raw_response, sizeof(res.raw_response), latency, timeoutMs);
    res.latency_ms = latency;
    res.status = qStat;

    if (qStat != SAMPLE_STATUS_VALID) {
        if (qStat == SAMPLE_STATUS_NO_DATA) {
            strncpy(res.error_msg, "NO_DATA", sizeof(res.error_msg) - 1);
        } else if (qStat == SAMPLE_STATUS_TIMEOUT) {
            strncpy(res.error_msg, "TIMEOUT", sizeof(res.error_msg) - 1);
        } else {
            strncpy(res.error_msg, "TRANSPORT_OR_MALFORMED", sizeof(res.error_msg) - 1);
        }
        return res;
    }

    // 4. Normalize Response (Strips CAN headers like '7E8 04 41 0C ...' or parses '41 0C ...')
    int payloadLen = Obd2::normalizeResponse(res.raw_response, pid, res.normalized_bytes, sizeof(res.normalized_bytes));
    if (payloadLen <= 0) {
        res.status = SAMPLE_STATUS_MALFORMED;
        strncpy(res.error_msg, "MISSING_MODE01_PAYLOAD", sizeof(res.error_msg) - 1);
        return res;
    }
    res.normalized_len = (size_t)payloadLen;

    // 5. Decode Semantic Value (if standard decoder available)
    const char* unitStr = "";
    bool decodeOk = false;
    res.decoded_value = Obd2::decodeByPid(pid, res.normalized_bytes, res.normalized_len, unitStr, &decodeOk);
    strncpy(res.unit, unitStr, sizeof(res.unit) - 1);

    if (decodeOk) {
        res.status = SAMPLE_STATUS_VALID;
        strncpy(res.error_msg, "OK", sizeof(res.error_msg) - 1);
    } else {
        // Bitmap or raw bytes without numerical scalar decoder
        res.status = SAMPLE_STATUS_VALID;
        strncpy(res.error_msg, "RAW_PAYLOAD_ONLY", sizeof(res.error_msg) - 1);
    }

    return res;
}

ObdResult Obd2Client::rawRequest(const char* cmd, uint32_t timeoutMs) {
    ObdResult res;
    memset(&res, 0, sizeof(res));
    res.timestamp_us = esp_timer_get_time();

    if (!cmd || strlen(cmd) < 4) {
        res.status = SAMPLE_STATUS_MALFORMED;
        strncpy(res.error_msg, "INVALID_CMD", sizeof(res.error_msg) - 1);
        return res;
    }

    strncpy(res.request, cmd, sizeof(res.request) - 1);

    // Extract mode and PID from command string
    int modeVal = 0, pidVal = 0;
    if (sscanf(cmd, "%02x%02x", &modeVal, &pidVal) == 2 ||
        sscanf(cmd, "%02X%02X", &modeVal, &pidVal) == 2) {
        return request((uint8_t)modeVal, (uint8_t)pidVal, timeoutMs);
    }

    res.status = SAMPLE_STATUS_SAFETY_BLOCKED;
    strncpy(res.error_msg, "UNRECOGNIZED_MODE", sizeof(res.error_msg) - 1);
    return res;
}
