#include "obd2.h"
#include <cstdio>
#include <ctype.h>
#include <string.h>

static int hexCharToNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

int Obd2::hexToBytes(const char* hexStr, uint8_t* byteArr, size_t maxBytes) {
    if (!hexStr || !byteArr || maxBytes == 0) return 0;

    size_t byteCount = 0;
    size_t len = strlen(hexStr);

    for (size_t i = 0; i + 1 < len && byteCount < maxBytes; i += 2) {
        int high = hexCharToNibble(hexStr[i]);
        int low  = hexCharToNibble(hexStr[i + 1]);
        if (high < 0 || low < 0) {
            break;
        }
        byteArr[byteCount++] = (uint8_t)((high << 4) | low);
    }
    return (int)byteCount;
}

int Obd2::normalizeResponse(const char* rawResponse, uint8_t targetPid, uint8_t* payloadOut, size_t maxPayload) {
    if (!rawResponse || !payloadOut || maxPayload == 0) return 0;

    char targetHex[4];
    snprintf(targetHex, sizeof(targetHex), "%02X", targetPid);

    // 1. Try tokenized parsing by whitespace
    char copy[96];
    strncpy(copy, rawResponse, sizeof(copy) - 1);
    copy[sizeof(copy) - 1] = '\0';

    char* tokens[24];
    size_t tokCount = 0;
    char* saveptr = NULL;
    char* tok = strtok_r(copy, " \r\n>", &saveptr);
    while (tok && tokCount < 24) {
        tokens[tokCount++] = tok;
        tok = strtok_r(NULL, " \r\n>", &saveptr);
    }

    for (size_t i = 0; i + 1 < tokCount; ++i) {
        if (strcasecmp(tokens[i], "41") == 0 && strcasecmp(tokens[i + 1], targetHex) == 0) {
            size_t pBytes = 0;
            for (size_t j = i + 2; j < tokCount && pBytes < maxPayload; ++j) {
                uint8_t bArr[8];
                int bLen = hexToBytes(tokens[j], bArr, sizeof(bArr));
                for (int b = 0; b < bLen && pBytes < maxPayload; ++b) {
                    payloadOut[pBytes++] = bArr[b];
                }
            }
            if (pBytes > 0) {
                return (int)pBytes;
            }
        }
    }

    // 2. Fallback: continuous substring search (spaces off or compact)
    char cleanHex[96];
    size_t cIdx = 0;
    for (size_t i = 0; rawResponse[i] != '\0' && cIdx < sizeof(cleanHex) - 1; ++i) {
        char ch = rawResponse[i];
        if (isxdigit((unsigned char)ch)) {
            cleanHex[cIdx++] = (char)toupper((unsigned char)ch);
        }
    }
    cleanHex[cIdx] = '\0';

    char marker[8];
    snprintf(marker, sizeof(marker), "41%s", targetHex);
    const char* pos = strstr(cleanHex, marker);
    if (pos) {
        pos += strlen(marker);
        uint8_t rawBytes[32];
        int bLen = hexToBytes(pos, rawBytes, sizeof(rawBytes));
        if (bLen > (int)maxPayload) bLen = (int)maxPayload;
        if (bLen > 0) {
            memcpy(payloadOut, rawBytes, bLen);
            return bLen;
        }
    }

    return 0;
}

uint32_t Obd2::bytesToUint32(const uint8_t* b) {
    if (!b) return 0;
    return ((uint32_t)b[0] << 24) |
           ((uint32_t)b[1] << 16) |
           ((uint32_t)b[2] << 8)  |
           ((uint32_t)b[3]);
}

bool Obd2::isPidBitSet(uint32_t bitmap, uint8_t relativePid) {
    if (relativePid < 1 || relativePid > 32) return false;
    uint8_t shift = 32 - relativePid;
    return ((bitmap >> shift) & 0x01) == 1;
}

// 0104: Calculated Engine Load (%) = A * 100 / 255
float Obd2::decodeEngineLoad(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return ((float)data[0] * 100.0f) / 255.0f;
}

// 0105: Engine Coolant Temp (°C) = A - 40
float Obd2::decodeECT(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return (float)data[0] - 40.0f;
}

// 0106: STFT B1 (%) = (A - 128) * 100 / 128
float Obd2::decodeSTFT(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return ((float)data[0] - 128.0f) * 100.0f / 128.0f;
}

// 0107: LTFT B1 (%) = (A - 128) * 100 / 128
float Obd2::decodeLTFT(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return ((float)data[0] - 128.0f) * 100.0f / 128.0f;
}

// 010B: Intake Manifold Absolute Pressure (kPa) = A
float Obd2::decodeMAP(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return (float)data[0];
}

// 010C: Engine Speed (rpm) = ((A * 256) + B) / 4
float Obd2::decodeRPM(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 2) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return (float)((((uint32_t)data[0]) << 8) | data[1]) / 4.0f;
}

// 010D: Vehicle Speed (km/h) = A
float Obd2::decodeSpeed(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return (float)data[0];
}

// 010E: Ignition Timing Advance (degrees) = (A / 2.0) - 64.0
float Obd2::decodeTimingAdvance(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return ((float)data[0] / 2.0f) - 64.0f;
}

// 010F: Intake Air Temperature (°C) = A - 40
float Obd2::decodeIAT(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return (float)data[0] - 40.0f;
}

// 0110: Mass Air Flow (g/s) = ((A * 256) + B) / 100
float Obd2::decodeMAF(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 2) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return (float)((((uint32_t)data[0]) << 8) | data[1]) / 100.0f;
}

// 0111: Throttle Position (%) = (A * 100) / 255
float Obd2::decodeTPS(const uint8_t* data, size_t len, bool* ok) {
    if (!data || len < 1) { if (ok) *ok = false; return 0.0f; }
    if (ok) *ok = true;
    return ((float)data[0] * 100.0f) / 255.0f;
}

float Obd2::decodeByPid(uint8_t pid, const uint8_t* payload, size_t len, const char*& unitOut, bool* ok) {
    switch (pid) {
        case 0x04: unitOut = "%";    return decodeEngineLoad(payload, len, ok);
        case 0x05: unitOut = "degC"; return decodeECT(payload, len, ok);
        case 0x06: unitOut = "%";    return decodeSTFT(payload, len, ok);
        case 0x07: unitOut = "%";    return decodeLTFT(payload, len, ok);
        case 0x0B: unitOut = "kPa";  return decodeMAP(payload, len, ok);
        case 0x0C: unitOut = "rpm";  return decodeRPM(payload, len, ok);
        case 0x0D: unitOut = "km/h"; return decodeSpeed(payload, len, ok);
        case 0x0E: unitOut = "deg";  return decodeTimingAdvance(payload, len, ok);
        case 0x0F: unitOut = "degC"; return decodeIAT(payload, len, ok);
        case 0x10: unitOut = "g/s";  return decodeMAF(payload, len, ok);
        case 0x11: unitOut = "%";    return decodeTPS(payload, len, ok);
        default:
            unitOut = "";
            if (ok) *ok = false;
            return 0.0f;
    }
}
