#ifndef PID_SCANNER_H
#define PID_SCANNER_H

#include <Arduino.h>
#include "obd2_client.h"
#include "obd2.h"
#include "mini_types.h"
#include "mini_config.h"

#define MAX_REGISTERED_PIDS 24

class PidScanner {
public:
    explicit PidScanner(Obd2Client& obdClient);
    ~PidScanner();

    // Registry & Initialization
    void initPidRegistry();

    // Discovery Sequence (Chained 0100 -> 0120 -> 0140...)
    bool scanSupportedPids();

    // Harmless Single Smoke Probes (010C, 0105, 010D)
    bool probeSmokePids();

    // State & Status
    PidScannerState getState() const;
    const char* getStateString() const;
    bool isScanned() const;
    size_t getRegisteredCount() const;
    size_t getSupportedCount() const;

    // M-4 Handoff Contract API
    PidMetadata* getPidMetadata(size_t index);
    const PidMetadata* getPidMetadata(size_t index) const;
    PidMetadata* findPid(uint16_t pid);
    const PidMetadata* findPid(uint16_t pid) const;
    ObdResult queryPid(uint16_t pid, uint32_t timeoutMs = SEYYANEN_COMMAND_TIMEOUT);

    void getSupportedPidListString(char* buffer, size_t maxLen) const;

private:
    Obd2Client&     _obdClient;
    PidScannerState _state;
    PidMetadata     _registry[MAX_REGISTERED_PIDS];
    size_t          _regCount;

    void registerPid(uint16_t pid, const char* name, const char* shortCode, const char* unit,
                     const char* description, const char* rawFormula, const char* decoderId,
                     uint32_t intervalMs, uint8_t priority, PidDecodeFunc fn,
                     float minValid, float maxValid);

    bool scanBitmapRange(uint8_t basePid, uint32_t& bitmapOut);
    void applyBitmapToRegistry(uint8_t basePid, uint32_t bitmap);
};

#endif // PID_SCANNER_H
