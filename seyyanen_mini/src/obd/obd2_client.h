#ifndef OBD2_CLIENT_H
#define OBD2_CLIENT_H

#include <Arduino.h>
#include <esp_timer.h>
#include "elm327.h"
#include "obd2.h"
#include "mini_types.h"
#include "mini_config.h"

// ==============================================================================
// OBD-II TRANSACTION CLIENT (PHASE M-3)
// ==============================================================================

class Obd2Client {
public:
    explicit Obd2Client(Elm327Client& elm);
    ~Obd2Client();

    // Standard OBD Mode 01 Request Dispatcher
    // Retains RAW -> NORMALIZED -> DECODED
    ObdResult request(uint8_t mode, uint8_t pid, uint32_t timeoutMs = SEYYANEN_COMMAND_TIMEOUT);

    // Raw String Query (Mode 01 only)
    ObdResult rawRequest(const char* cmd, uint32_t timeoutMs = SEYYANEN_COMMAND_TIMEOUT);

    // Readiness
    bool isReady() const;

    // Strict Safety Check
    static bool isModeAllowed(uint8_t mode);

private:
    Elm327Client& _elm;
};

#endif // OBD2_CLIENT_H
