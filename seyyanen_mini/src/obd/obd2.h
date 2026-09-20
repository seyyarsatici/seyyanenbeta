#ifndef OBD2_H
#define OBD2_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "mini_types.h"

// ==============================================================================
// OBD-II PROTOCOL DECODERS & NORMALIZATION ENGINE (PHASE M-3)
// ==============================================================================

class Obd2 {
public:
    // Convert hex string to byte array
    static int hexToBytes(const char* hexStr, uint8_t* byteArr, size_t maxBytes);

    // Normalize raw response (direct '41 0C 1A F8' or framed '7E8 04 41 0C 1A F8')
    // Extracts canonical payload bytes following '41 <targetPid>'
    static int normalizeResponse(const char* rawResponse, uint8_t targetPid, uint8_t* payloadOut, size_t maxPayload);

    // 32-bit Bitmap Inspection
    static bool isPidBitSet(uint32_t bitmap, uint8_t relativePid);
    static uint32_t bytesToUint32(const uint8_t* bytes);

    // Standard Mode 01 PID Decoders
    static float decodeEngineLoad(const uint8_t* data, size_t len, bool* ok); // 0104 (%)
    static float decodeECT(const uint8_t* data, size_t len, bool* ok);        // 0105 (°C)
    static float decodeSTFT(const uint8_t* data, size_t len, bool* ok);       // 0106 (%)
    static float decodeLTFT(const uint8_t* data, size_t len, bool* ok);       // 0107 (%)
    static float decodeMAP(const uint8_t* data, size_t len, bool* ok);        // 010B (kPa)
    static float decodeRPM(const uint8_t* data, size_t len, bool* ok);        // 010C (rpm)
    static float decodeSpeed(const uint8_t* data, size_t len, bool* ok);      // 010D (km/h)
    static float decodeTimingAdvance(const uint8_t* data, size_t len, bool* ok);// 010E (deg)
    static float decodeIAT(const uint8_t* data, size_t len, bool* ok);        // 010F (°C)
    static float decodeMAF(const uint8_t* data, size_t len, bool* ok);        // 0110 (g/s)
    static float decodeTPS(const uint8_t* data, size_t len, bool* ok);        // 0111 (%)

    // Universal Decoder Lookup
    static float decodeByPid(uint8_t pid, const uint8_t* payload, size_t len, const char*& unitOut, bool* ok);
};

#endif // OBD2_H
