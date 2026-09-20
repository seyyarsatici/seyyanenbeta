#ifndef SD_LOGGER_H
#define SD_LOGGER_H

#include <Arduino.h>
#include <FS.h>
#include <SD.h>
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "mini_types.h"
#include "mini_config.h"
#include "obd/pid_scanner.h"

// ==============================================================================
// SEYYANEN MINI - PHASE M-5 MICROSD STORAGE ENGINE
// ==============================================================================

class SdLogger {
public:
    SdLogger();
    ~SdLogger();

    // 1. Hardware Lifecycle & Initialization
    bool begin(uint8_t csPin = SEYYANEN_SD_CS_PIN,
               uint8_t mosiPin = SEYYANEN_SD_MOSI_PIN,
               uint8_t misoPin = SEYYANEN_SD_MISO_PIN,
               uint8_t sckPin = SEYYANEN_SD_SCK_PIN,
               uint32_t spiFreq = SEYYANEN_SD_SPI_FREQ);
    void end();

    // 2. Health & Status
    bool isReady() const;
    StorageStatus getStorageStatus() const;
    void getStorageInfo(StorageInfo& outInfo);
    void getStorageMetrics(StorageMetrics& outMetrics);
    const char* getLastError() const;

    // 3. Session Lifecycle Management
    bool startSession(const char* sessionId,
                      const AdapterIdentityInfo& adapterId,
                      const char* protocol,
                      const PidScanner& scanner);
    bool stopSession();
    bool isSessionActive() const;
    void getCurrentSession(SessionMetadata& outMetadata) const;
    const char* getCurrentSessionId() const;

    // 4. Sample & Event Serialization (Hardened Decoupled Storage Queue)
    bool enqueueSample(const MeasurementSample& sample);
    bool writeSample(const MeasurementSample& sample, const char* pidName = NULL);
    bool writeFrame(const AcquisitionFrame& frame);
    bool writeEvent(const char* eventType, const char* message);
    void flush();
    void update(); // Periodic housekeeping, queue draining & flush in loop()

    // 5. Directory Inspection & Web Download Sandboxing
    size_t listSessions(SessionSummary* outSummaries, size_t maxCount);
    bool readSessionMetadata(const char* sessionId, String& outJson);
    File openSessionFileForRead(const char* sessionId, const char* filename);

    // 6. Security Helper
    static bool isValidSessionId(const char* sessionId);

private:
    SPIClass          _spi;
    File              _sessionFile;
    File              _eventsFile;
    bool              _sdAvailable;
    StorageStatus     _status;
    char              _lastError[64];
    uint8_t           _csPin;

    SessionMetadata   _currentSession;
    char              _sessionDir[64];
    char              _csvPath[80];
    char              _metaPath[80];
    char              _eventsPath[80];

    // Bounded decoupled producer/consumer storage queue
    MeasurementSample _storageQueue[SEYYANEN_STORAGE_QUEUE_CAPACITY];
    size_t            _queueHead;
    size_t            _queueTail;
    size_t            _queueCount;

    // Bounded in-memory write buffer
    char              _writeBuffer[SEYYANEN_SD_WRITE_BUFFER_SIZE];
    size_t            _writeBufferLen;
    uint32_t          _lastFlushMs;

    StorageMetrics    _metrics;
    SemaphoreHandle_t _storageMutex;

    void bufferAppend(const char* str, size_t len);
    void flushBufferToFile();
    void processStorageQueue();
    void formatSampleToCsvRow(const MeasurementSample& sample, const char* pidName, char* outRow, size_t maxLen);
    void persistMetadataJson(bool finalCompleted);
    void scanIncompleteSessions();
    static void escapeCsvField(const char* src, char* dst, size_t maxLen);
};

#endif // SD_LOGGER_H
