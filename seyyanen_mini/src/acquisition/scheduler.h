#ifndef SCHEDULER_H
#define SCHEDULER_H

#include <Arduino.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "transport/vlinker_bt.h"
#include "obd/obd2_client.h"
#include "obd/pid_scanner.h"
#include "sample.h"
#include "quality.h"
#include "mini_types.h"
#include "mini_config.h"

// ==============================================================================
// LIVE ACQUISITION SCHEDULER (PHASE M-4)
// ==============================================================================

struct ScheduledPid {
    uint16_t pid;
    char     name[24];
    char     unit[12];
    bool     enabled;
    uint8_t  priority;         // 0: Fast, 1: Medium, 2: Slow
    uint64_t interval_us;      // Microsecond interval
    uint64_t last_requested_us;
    uint64_t last_success_us;
    uint32_t request_count;
    uint32_t error_count;
};

class SdLogger;

class AcquisitionScheduler {
public:
    AcquisitionScheduler(VLinkerBluetoothTransport& bt,
                         Obd2Client& obdClient,
                         PidScanner& scanner,
                         SampleRingBuffer& ringBuffer);
    ~AcquisitionScheduler();

    // Logger Binding (Phase M-5)
    void setLogger(SdLogger* logger);

    // Lifecycle Controls
    bool start(const char* sessionId = NULL);
    bool stop();
    bool pause();
    bool resume();

    // State Inspection
    bool isRunning() const;
    AcquisitionState getState() const;
    const char* getStateString() const;
    const char* getSessionId() const;
    uint32_t getSequence() const;
    uint32_t getFrameId() const;

    // Snapshot & Metrics (Thread-safe copy for Web presentation)
    void getSnapshot(LiveSnapshot& outSnapshot);
    void getMetrics(AcquisitionMetrics& outMetrics);

    // Non-blocking cooperative step called in loop()
    void update();

    // Rebuild active schedule from supported PID list
    void setupActiveSchedule();

private:
    VLinkerBluetoothTransport& _bt;
    Obd2Client&                _obdClient;
    PidScanner&                _scanner;
    SampleRingBuffer&          _ringBuffer;
    SdLogger*                  _logger;

    AcquisitionState           _state;
    char                       _sessionId[36];
    uint32_t                   _sequence;
    uint32_t                   _frameId;
    uint64_t                   _sessionStartUs;
    uint64_t                   _cycleStartUs;

    ScheduledPid               _activePids[SEYYANEN_MAX_SCHEDULED_PIDS];
    size_t                     _activePidCount;

    LiveSnapshot               _snapshot;
    AcquisitionMetrics         _metrics;
    SemaphoreHandle_t          _snapshotMutex;

    static uint32_t            s_sessionCounter;

    void generateNewSessionId();
    int  selectNextDuePid(uint64_t nowUs);
    void executeScheduledQuery(ScheduledPid& sp, uint64_t nowUs);
    void updateLiveSignal(uint16_t pid, float val, bool valid, QualityGrade q,
                          FreshnessState f, uint64_t nowUs, uint32_t latencyMs);
};

#endif // SCHEDULER_H
