#ifndef ELM327_H
#define ELM327_H

#include <Arduino.h>
#include "transport/vlinker_bt.h"
#include "mini_types.h"
#include "mini_config.h"

// ==============================================================================
// ELM327 PROTOCOL CLIENT (PHASE M-3)
// ==============================================================================

class Elm327Client {
public:
    explicit Elm327Client(VLinkerBluetoothTransport& transport);
    ~Elm327Client();

    // Initialization Sequence
    // Executes: ATZ -> ATE0 -> ATL0 -> ATS0 -> ATH0 -> ATSP0 -> ATDP
    bool initialize();
    void reset();

    // State Inspection
    Elm327State getState() const;
    const char* getStateString() const;
    bool isReady() const;
    const char* getProtocol() const;
    const char* getRawIdentity() const;
    AdapterBrand getBrand() const;
    const char* getBrandName() const;

    // Command Query
    // Sends command, awaits prompt '>', computes latency, preserves raw response
    SampleStatus query(const char* cmd, char* rawOut, size_t maxLen, uint32_t& latencyMs, uint32_t timeoutMs = SEYYANEN_COMMAND_TIMEOUT);

    // Helpers
    static void cleanResponse(const char* raw, char* cleaned, size_t maxLen);
    static bool isPositiveResponse(const char* cleaned);
    static bool isErrorResponse(const char* cleaned);

private:
    VLinkerBluetoothTransport& _transport;
    Elm327State                _state;
    char                       _protocol[32];

    bool executeInitCommand(const char* cmd, const char* name, uint32_t timeoutMs = 1200);
};

#endif // ELM327_H
