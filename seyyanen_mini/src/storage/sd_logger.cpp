#include "sd_logger.h"
#include <esp_timer.h>
#include <string.h>

// ==============================================================================
// SEYYANEN MINI - PHASE M-5 MICROSD STORAGE ENGINE IMPLEMENTATION
// ==============================================================================

SdLogger::SdLogger()
    : _spi(VSPI),
      _sdAvailable(false),
      _status(STORAGE_STATUS_IDLE),
      _csPin(SEYYANEN_SD_CS_PIN),
      _writeBufferLen(0),
      _lastFlushMs(0) {
    memset(_lastError, 0, sizeof(_lastError));
    memset(&_currentSession, 0, sizeof(_currentSession));
    memset(_sessionDir, 0, sizeof(_sessionDir));
    memset(_csvPath, 0, sizeof(_csvPath));
    memset(_metaPath, 0, sizeof(_metaPath));
    memset(_eventsPath, 0, sizeof(_eventsPath));
    memset(_writeBuffer, 0, sizeof(_writeBuffer));
    memset(&_metrics, 0, sizeof(_metrics));
    memset(_storageQueue, 0, sizeof(_storageQueue));

    _queueHead = 0;
    _queueTail = 0;
    _queueCount = 0;
    _metrics.health_state = STORAGE_HEALTH_OK;

    _storageMutex = xSemaphoreCreateMutex();
    _currentSession.session_state = SESSION_STATE_NO_SESSION;
}

SdLogger::~SdLogger() {
    end();
    if (_storageMutex) {
        vSemaphoreDelete(_storageMutex);
    }
}

bool SdLogger::begin(uint8_t csPin, uint8_t mosiPin, uint8_t misoPin, uint8_t sckPin, uint32_t spiFreq) {
    _csPin = csPin;
    Serial.println("[MINI-SD] Initializing microSD...");
    Serial.printf("[MINI-SD] SPI Bus: SCK=%u, MISO=%u, MOSI=%u, CS=%u, Freq=%u Hz\n",
                  sckPin, misoPin, mosiPin, csPin, (unsigned int)spiFreq);

    _spi.begin(sckPin, misoPin, mosiPin, csPin);

    if (!SD.begin(csPin, _spi, spiFreq)) {
        Serial.println("[MINI-SD] ERROR: CARD_NOT_PRESENT or mount failed!");
        _status = STORAGE_STATUS_NO_CARD;
        strncpy(_lastError, "CARD_NOT_PRESENT", sizeof(_lastError) - 1);
        _sdAvailable = false;
        return false;
    }

    uint8_t cardType = SD.cardType();
    if (cardType == CARD_NONE) {
        Serial.println("[MINI-SD] ERROR: CARD_NOT_PRESENT (Type None)");
        _status = STORAGE_STATUS_NO_CARD;
        strncpy(_lastError, "CARD_NOT_PRESENT", sizeof(_lastError) - 1);
        _sdAvailable = false;
        return false;
    }

    const char* typeStr = "UNKNOWN";
    if (cardType == CARD_MMC) typeStr = "MMC";
    else if (cardType == CARD_SD) typeStr = "SDSC";
    else if (cardType == CARD_SDHC) typeStr = "SDHC";

    uint64_t totalBytes = SD.cardSize();
    uint64_t totalMB = totalBytes / (1024ULL * 1024ULL);
    uint64_t usedBytes = SD.usedBytes();
    uint64_t freeBytes = (totalBytes > usedBytes) ? (totalBytes - usedBytes) : 0;
    uint64_t freeMB = freeBytes / (1024ULL * 1024ULL);

    Serial.println("[MINI-SD] Card detected");
    Serial.printf("[MINI-SD] Type: %s\n", typeStr);
    Serial.printf("[MINI-SD] Capacity: %llu MB\n", totalMB);
    Serial.printf("[MINI-SD] Free space: %llu MB\n", freeMB);

    // Create Base Directories
    if (!SD.exists(SEYYANEN_SD_BASE_DIR)) {
        SD.mkdir(SEYYANEN_SD_BASE_DIR);
    }
    if (!SD.exists(SEYYANEN_SD_SESSIONS_DIR)) {
        SD.mkdir(SEYYANEN_SD_SESSIONS_DIR);
    }

    _sdAvailable = true;
    _status = STORAGE_STATUS_READY;
    strncpy(_lastError, "NONE", sizeof(_lastError) - 1);

    // Scan for incomplete sessions from past power cuts
    scanIncompleteSessions();

    return true;
}

void SdLogger::end() {
    stopSession();
    if (_sdAvailable) {
        SD.end();
        _sdAvailable = false;
        _status = STORAGE_STATUS_IDLE;
    }
}

bool SdLogger::isReady() const {
    return _sdAvailable && (_status == STORAGE_STATUS_READY);
}

StorageStatus SdLogger::getStorageStatus() const {
    return _status;
}

void SdLogger::getStorageInfo(StorageInfo& outInfo) {
    memset(&outInfo, 0, sizeof(outInfo));
    outInfo.status = _status;
    outInfo.card_present = _sdAvailable;
    outInfo.is_mounted = _sdAvailable;

    if (_sdAvailable) {
        uint8_t cardType = SD.cardType();
        if (cardType == CARD_MMC) strncpy(outInfo.card_type, "MMC", sizeof(outInfo.card_type) - 1);
        else if (cardType == CARD_SD) strncpy(outInfo.card_type, "SDSC", sizeof(outInfo.card_type) - 1);
        else if (cardType == CARD_SDHC) strncpy(outInfo.card_type, "SDHC", sizeof(outInfo.card_type) - 1);
        else strncpy(outInfo.card_type, "UNKNOWN", sizeof(outInfo.card_type) - 1);

        outInfo.total_bytes = SD.cardSize();
        uint64_t used = SD.usedBytes();
        outInfo.free_bytes = (outInfo.total_bytes > used) ? (outInfo.total_bytes - used) : 0;
    } else {
        strncpy(outInfo.card_type, "NONE", sizeof(outInfo.card_type) - 1);
    }
}

void SdLogger::getStorageMetrics(StorageMetrics& outMetrics) {
    if (_storageMutex && xSemaphoreTake(_storageMutex, pdMS_TO_TICKS(30)) == pdTRUE) {
        _metrics.samples_pending = _writeBufferLen > 0 ? 1 : 0;
        outMetrics = _metrics;
        xSemaphoreGive(_storageMutex);
    }
}

const char* SdLogger::getLastError() const {
    return _lastError;
}

bool SdLogger::isValidSessionId(const char* sessionId) {
    if (!sessionId) return false;
    size_t len = strlen(sessionId);
    if (len < 3 || len > 35) return false;

    // Security Gate: strictly alphanumeric and dashes/underscores (no '/', '\', '..')
    for (size_t i = 0; i < len; ++i) {
        char c = sessionId[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_')) {
            return false;
        }
    }
    return true;
}

bool SdLogger::startSession(const char* sessionId,
                            const AdapterIdentityInfo& adapterId,
                            const char* protocol,
                            const PidScanner& scanner) {
    if (!_sdAvailable) {
        Serial.println("[MINI-SD] Cannot start session: Storage not available.");
        _status = STORAGE_STATUS_NO_CARD;
        strncpy(_lastError, "CARD_NOT_PRESENT", sizeof(_lastError) - 1);
        return false;
    }

    if (!isValidSessionId(sessionId)) {
        Serial.printf("[MINI-SD] Rejected invalid or unsafe session ID: '%s'\n", sessionId ? sessionId : "NULL");
        strncpy(_lastError, "INVALID_SESSION_ID", sizeof(_lastError) - 1);
        return false;
    }

    if (_currentSession.session_state == SESSION_STATE_ACTIVE) {
        stopSession();
    }

    if (_storageMutex && xSemaphoreTake(_storageMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        // Prepare Directory Structure
        snprintf(_sessionDir, sizeof(_sessionDir), "%s/%s", SEYYANEN_SD_SESSIONS_DIR, sessionId);
        snprintf(_csvPath, sizeof(_csvPath), "%s/session.csv", _sessionDir);
        snprintf(_metaPath, sizeof(_metaPath), "%s/metadata.json", _sessionDir);
        snprintf(_eventsPath, sizeof(_eventsPath), "%s/events.log", _sessionDir);

        if (!SD.exists(_sessionDir)) {
            if (!SD.mkdir(_sessionDir)) {
                Serial.printf("[MINI-SD] Failed to create session directory '%s'\n", _sessionDir);
                _status = STORAGE_STATUS_FILESYSTEM_ERROR;
                strncpy(_lastError, "DIR_CREATE_FAILED", sizeof(_lastError) - 1);
                xSemaphoreGive(_storageMutex);
                return false;
            }
        }

        // Open Primary CSV File
        _sessionFile = SD.open(_csvPath, FILE_WRITE);
        if (!_sessionFile) {
            Serial.printf("[MINI-SD] Failed to open CSV file '%s' for writing\n", _csvPath);
            _status = STORAGE_STATUS_WRITE_ERROR;
            strncpy(_lastError, "FILE_OPEN_FAILED", sizeof(_lastError) - 1);
            xSemaphoreGive(_storageMutex);
            return false;
        }

        // Open Events Log File
        _eventsFile = SD.open(_eventsPath, FILE_WRITE);

        // Reset Buffer & Metrics
        _writeBufferLen = 0;
        _lastFlushMs = millis();

        // Initialize Session Metadata
        memset(&_currentSession, 0, sizeof(_currentSession));
        strncpy(_currentSession.session_id, sessionId, sizeof(_currentSession.session_id) - 1);
        _currentSession.start_timestamp_us = esp_timer_get_time();
        strncpy(_currentSession.firmware_version, "1.0.0", sizeof(_currentSession.firmware_version) - 1);
        strncpy(_currentSession.mini_version, "M-5", sizeof(_currentSession.mini_version) - 1);
        strncpy(_currentSession.adapter_name, adapterId.adapter_name, sizeof(_currentSession.adapter_name) - 1);
        strncpy(_currentSession.adapter_model, adapterId.model, sizeof(_currentSession.adapter_model) - 1);
        strncpy(_currentSession.adapter_firmware, adapterId.firmware, sizeof(_currentSession.adapter_firmware) - 1);
        strncpy(_currentSession.adapter_raw_identity, adapterId.raw_identity, sizeof(_currentSession.adapter_raw_identity) - 1);
        strncpy(_currentSession.transport_medium, "BLUETOOTH_SPP", sizeof(_currentSession.transport_medium) - 1);
        strncpy(_currentSession.protocol, protocol ? protocol : "UNKNOWN", sizeof(_currentSession.protocol) - 1);
        strncpy(_currentSession.vehicle_context_status, "UNKNOWN", sizeof(_currentSession.vehicle_context_status) - 1); // Strictly UNKNOWN if no VIN
        _currentSession.supported_pid_count = scanner.getSupportedCount();
        _currentSession.session_state = SESSION_STATE_ACTIVE;

        // Write CSV Header
        const char* header = "timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us\n";
        bufferAppend(header, strlen(header));
        flushBufferToFile();

        // Write initial metadata marking ACTIVE
        persistMetadataJson(false);

        // Log session start event
        writeEvent("SESSION_START", "Recording session active");

        Serial.printf("[MINI-SD] Session started: %s\n", sessionId);
        xSemaphoreGive(_storageMutex);
        return true;
    }

    return false;
}

bool SdLogger::stopSession() {
    if (_currentSession.session_state != SESSION_STATE_ACTIVE &&
        _currentSession.session_state != SESSION_STATE_STARTING) {
        return true;
    }

    if (_storageMutex && xSemaphoreTake(_storageMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        _currentSession.session_state = SESSION_STATE_STOPPING;
        writeEvent("SESSION_STOP", "Finalizing session");

        // Flush remaining buffer
        flushBufferToFile();

        if (_sessionFile) {
            _sessionFile.flush();
            _sessionFile.close();
        }

        if (_eventsFile) {
            _eventsFile.flush();
            _eventsFile.close();
        }

        _currentSession.end_timestamp_us = esp_timer_get_time();
        _currentSession.session_state = SESSION_STATE_COMPLETED;

        // Persist final metadata with state COMPLETED
        persistMetadataJson(true);

        Serial.printf("[MINI-SD] Session finalized: %s. Written samples: %u, Errors: %u\n",
                      _currentSession.session_id,
                      (unsigned int)_currentSession.sample_count,
                      (unsigned int)_currentSession.error_count);

        xSemaphoreGive(_storageMutex);
        return true;
    }

    return false;
}

bool SdLogger::isSessionActive() const {
    return (_currentSession.session_state == SESSION_STATE_ACTIVE);
}

void SdLogger::getCurrentSession(SessionMetadata& outMetadata) const {
    outMetadata = _currentSession;
}

const char* SdLogger::getCurrentSessionId() const {
    return _currentSession.session_id;
}

void SdLogger::escapeCsvField(const char* src, char* dst, size_t maxLen) {
    if (!src || !dst || maxLen < 3) {
        if (dst && maxLen > 0) dst[0] = '\0';
        return;
    }

    dst[0] = '\"';
    size_t di = 1;
    for (size_t si = 0; src[si] != '\0' && di < maxLen - 2; ++si) {
        if (src[si] == '\"') {
            if (di < maxLen - 3) {
                dst[di++] = '\"';
                dst[di++] = '\"';
            }
        } else if (src[si] == '\r' || src[si] == '\n') {
            dst[di++] = ' ';
        } else {
            dst[di++] = src[si];
        }
    }
    dst[di++] = '\"';
    dst[di] = '\0';
}

void SdLogger::formatSampleToCsvRow(const MeasurementSample& sample, const char* pidName, char* outRow, size_t maxLen) {
    char escapedRaw[72];
    escapeCsvField(sample.raw_response, escapedRaw, sizeof(escapedRaw));

    char valBuf[16];
    if (sample.status == SAMPLE_STATUS_VALID) {
        snprintf(valBuf, sizeof(valBuf), "%.2f", sample.decoded_value);
    } else {
        // Zero-resistance rule: Do NOT output fake 0.0 for failed measurements!
        valBuf[0] = '\0';
    }

    snprintf(outRow, maxLen,
        "%llu,%u,%u,01%02X,%s,01%02X,%s,%s,%s,%s,%s,%s,%u\n",
        (unsigned long long)sample.timestamp_us,
        (unsigned int)sample.sequence,
        (unsigned int)sample.sequence, // frame grouping
        (uint8_t)(sample.pid & 0xFF),
        (pidName && strlen(pidName) > 0) ? pidName : sample.name,
        (uint8_t)(sample.pid & 0xFF),
        escapedRaw,
        valBuf,
        sample.unit,
        sampleStatusToString(sample.status),
        qualityGradeToString(sample.quality),
        freshnessStateToString(sample.freshness),
        (unsigned int)sample.latency_us
    );
}

bool SdLogger::enqueueSample(const MeasurementSample& sample) {
    if (!_sdAvailable || _currentSession.session_state != SESSION_STATE_ACTIVE || !_sessionFile) {
        _metrics.samples_dropped++;
        _metrics.health_state = STORAGE_HEALTH_WRITE_ERROR;
        return false;
    }

    if (_storageMutex && xSemaphoreTake(_storageMutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        if (_queueCount >= SEYYANEN_STORAGE_QUEUE_CAPACITY) {
            // Queue full -> sample dropped, transition to OVERFLOW state
            _metrics.samples_dropped++;
            _metrics.health_state = STORAGE_HEALTH_OVERFLOW;
            xSemaphoreGive(_storageMutex);
            return false;
        }

        // Enqueue sample into bounded ring buffer
        _storageQueue[_queueHead] = sample;
        _queueHead = (_queueHead + 1) % SEYYANEN_STORAGE_QUEUE_CAPACITY;
        _queueCount++;

        _metrics.queue_depth = _queueCount;
        if (_queueCount > _metrics.queue_high_water_mark) {
            _metrics.queue_high_water_mark = _queueCount;
        }

        // Assess queue backpressure threshold
        if (_queueCount >= SEYYANEN_STORAGE_BACKPRESSURE_THRESHOLD) {
            _metrics.backpressure_events++;
            _metrics.health_state = STORAGE_HEALTH_BACKPRESSURE;
        } else if (_metrics.health_state != STORAGE_HEALTH_WRITE_ERROR) {
            _metrics.health_state = STORAGE_HEALTH_OK;
        }

        xSemaphoreGive(_storageMutex);
        return true;
    }

    _metrics.samples_dropped++;
    return false;
}

bool SdLogger::writeSample(const MeasurementSample& sample, const char* pidName) {
    (void)pidName;
    return enqueueSample(sample);
}

void SdLogger::processStorageQueue() {
    if (!_sdAvailable || !_sessionFile) return;

    if (_storageMutex && xSemaphoreTake(_storageMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
        while (_queueCount > 0) {
            MeasurementSample s = _storageQueue[_queueTail];
            _queueTail = (_queueTail + 1) % SEYYANEN_STORAGE_QUEUE_CAPACITY;
            _queueCount--;
            _metrics.queue_depth = _queueCount;

            char row[256];
            formatSampleToCsvRow(s, s.name, row, sizeof(row));
            size_t rowLen = strlen(row);
            if (rowLen > 0) {
                bufferAppend(row, rowLen);
                _currentSession.sample_count++;
                _metrics.samples_written++;
                if (s.status != SAMPLE_STATUS_VALID) {
                    _currentSession.error_count++;
                }
            }
        }

        if (_queueCount < SEYYANEN_STORAGE_BACKPRESSURE_THRESHOLD &&
            _metrics.health_state == STORAGE_HEALTH_BACKPRESSURE) {
            _metrics.health_state = STORAGE_HEALTH_OK;
        }

        xSemaphoreGive(_storageMutex);
    }
}

bool SdLogger::writeFrame(const AcquisitionFrame& frame) {
    if (_currentSession.session_state == SESSION_STATE_ACTIVE) {
        _currentSession.frame_count++;
        return true;
    }
    return false;
}

bool SdLogger::writeEvent(const char* eventType, const char* message) {
    if (!_sdAvailable || !_eventsFile) return false;

    uint64_t nowUs = esp_timer_get_time();
    char line[128];
    int len = snprintf(line, sizeof(line), "%llu [%s] %s\n",
                       (unsigned long long)nowUs,
                       eventType ? eventType : "EVENT",
                       message ? message : "");
    if (len > 0) {
        _eventsFile.write((const uint8_t*)line, (size_t)len);
        _eventsFile.flush();
        return true;
    }
    return false;
}

void SdLogger::bufferAppend(const char* str, size_t len) {
    if (!str || len == 0) return;

    // If buffer would overflow, flush existing contents first
    if (_writeBufferLen + len >= SEYYANEN_SD_WRITE_BUFFER_SIZE) {
        flushBufferToFile();
    }

    if (len >= SEYYANEN_SD_WRITE_BUFFER_SIZE) {
        // Direct write for giant block
        if (_sessionFile) {
            uint64_t tStart = esp_timer_get_time();
            size_t written = _sessionFile.write((const uint8_t*)str, len);
            _metrics.last_write_latency_us = (uint32_t)(esp_timer_get_time() - tStart);
            if (written != len) {
                _metrics.write_errors++;
                _status = STORAGE_STATUS_WRITE_ERROR;
                _metrics.health_state = STORAGE_HEALTH_WRITE_ERROR;
            }
        }
        return;
    }

    memcpy(_writeBuffer + _writeBufferLen, str, len);
    _writeBufferLen += len;
}

void SdLogger::flushBufferToFile() {
    if (_writeBufferLen > 0 && _sessionFile) {
        uint64_t tStart = esp_timer_get_time();
        size_t written = _sessionFile.write((const uint8_t*)_writeBuffer, _writeBufferLen);
        _metrics.last_write_latency_us = (uint32_t)(esp_timer_get_time() - tStart);

        if (written != _writeBufferLen) {
            _metrics.write_errors++;
            _status = STORAGE_STATUS_WRITE_ERROR;
            _metrics.health_state = STORAGE_HEALTH_WRITE_ERROR;
            strncpy(_lastError, "WRITE_FAILED", sizeof(_lastError) - 1);
        }
        _writeBufferLen = 0;
    }
}

void SdLogger::flush() {
    if (_storageMutex && xSemaphoreTake(_storageMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        flushBufferToFile();
        if (_sessionFile) {
            uint64_t tStart = esp_timer_get_time();
            _sessionFile.flush();
            _metrics.last_flush_latency_us = (uint32_t)(esp_timer_get_time() - tStart);
            _metrics.flush_count++;
            _lastFlushMs = millis();
        }
        xSemaphoreGive(_storageMutex);
    }
}

void SdLogger::update() {
    if (_currentSession.session_state != SESSION_STATE_ACTIVE) return;

    // First drain decoupled in-memory storage queue into buffer
    processStorageQueue();

    if (millis() - _lastFlushMs >= SEYYANEN_SD_FLUSH_INTERVAL_MS) {
        flush();
    }
}

void SdLogger::persistMetadataJson(bool finalCompleted) {
    File meta = SD.open(_metaPath, FILE_WRITE);
    if (!meta) return;

    String json = "{\n";
    json += "  \"session_id\": \"" + String(_currentSession.session_id) + "\",\n";
    json += "  \"start_timestamp_us\": " + String((unsigned long long)_currentSession.start_timestamp_us) + ",\n";
    json += "  \"end_timestamp_us\": " + String((unsigned long long)_currentSession.end_timestamp_us) + ",\n";
    json += "  \"start_wall_time\": \"" + String(_currentSession.start_wall_time) + "\",\n";
    json += "  \"end_wall_time\": \"" + String(_currentSession.end_wall_time) + "\",\n";
    json += "  \"session_start_monotonic_us\": " + String((unsigned long long)_currentSession.start_timestamp_us) + ",\n";
    json += "  \"session_start_wall_clock\": \"" + String(_currentSession.start_wall_time) + "\",\n";
    json += "  \"time_mapping_formula\": \"sample_wall_clock = session_start_wall_clock + (sample.timestamp_us - session_start_monotonic_us)\",\n";
    json += "  \"firmware_version\": \"" + String(_currentSession.firmware_version) + "\",\n";
    json += "  \"mini_version\": \"" + String(_currentSession.mini_version) + "\",\n";
    json += "  \"adapter_name\": \"" + String(_currentSession.adapter_name) + "\",\n";
    json += "  \"adapter_model\": \"" + String(_currentSession.adapter_model) + "\",\n";
    json += "  \"adapter_firmware\": \"" + String(_currentSession.adapter_firmware) + "\",\n";
    json += "  \"adapter_raw_identity\": \"" + String(_currentSession.adapter_raw_identity) + "\",\n";
    json += "  \"transport_medium\": \"" + String(_currentSession.transport_medium) + "\",\n";
    json += "  \"protocol\": \"" + String(_currentSession.protocol) + "\",\n";
    json += "  \"vehicle_context_status\": \"" + String(_currentSession.vehicle_context_status) + "\",\n";
    json += "  \"supported_pid_count\": " + String(_currentSession.supported_pid_count) + ",\n";
    json += "  \"sample_count\": " + String(_currentSession.sample_count) + ",\n";
    json += "  \"frame_count\": " + String(_currentSession.frame_count) + ",\n";
    json += "  \"error_count\": " + String(_currentSession.error_count) + ",\n";
    json += "  \"session_state\": \"" + String(sessionStateToString(finalCompleted ? SESSION_STATE_COMPLETED : SESSION_STATE_ACTIVE)) + "\"\n";
    json += "}\n";

    meta.print(json);
    meta.flush();
    meta.close();
}

void SdLogger::scanIncompleteSessions() {
    File sessionsDir = SD.open(SEYYANEN_SD_SESSIONS_DIR);
    if (!sessionsDir || !sessionsDir.isDirectory()) return;

    File entry = sessionsDir.openNextFile();
    while (entry) {
        if (entry.isDirectory()) {
            char metaFile[96];
            snprintf(metaFile, sizeof(metaFile), "%s/metadata.json", entry.path());
            if (SD.exists(metaFile)) {
                File f = SD.open(metaFile, FILE_READ);
                if (f) {
                    String content = f.readString();
                    f.close();
                    if (content.indexOf("\"session_state\": \"ACTIVE\"") >= 0) {
                        Serial.printf("[MINI-SD] Recovered incomplete session: %s\n", entry.name());
                        content.replace("\"session_state\": \"ACTIVE\"", "\"session_state\": \"RECOVERABLE_INCOMPLETE\"");
                        File fw = SD.open(metaFile, FILE_WRITE);
                        if (fw) {
                            fw.print(content);
                            fw.close();
                        }
                    }
                }
            }
        }
        entry = sessionsDir.openNextFile();
    }
}

size_t SdLogger::listSessions(SessionSummary* outSummaries, size_t maxCount) {
    if (!_sdAvailable || !outSummaries || maxCount == 0) return 0;

    size_t count = 0;
    File sessionsDir = SD.open(SEYYANEN_SD_SESSIONS_DIR);
    if (!sessionsDir || !sessionsDir.isDirectory()) return 0;

    File entry = sessionsDir.openNextFile();
    while (entry && count < maxCount) {
        if (entry.isDirectory()) {
            SessionSummary& s = outSummaries[count];
            memset(&s, 0, sizeof(s));
            strncpy(s.session_id, entry.name(), sizeof(s.session_id) - 1);
            strncpy(s.folder_path, entry.path(), sizeof(s.folder_path) - 1);

            char csvPath[96];
            snprintf(csvPath, sizeof(csvPath), "%s/session.csv", entry.path());
            if (SD.exists(csvPath)) {
                File cf = SD.open(csvPath, FILE_READ);
                if (cf) {
                    s.size_bytes = cf.size();
                    cf.close();
                }
            }

            char metaFile[96];
            snprintf(metaFile, sizeof(metaFile), "%s/metadata.json", entry.path());
            s.state = SESSION_STATE_COMPLETED;
            if (SD.exists(metaFile)) {
                File mf = SD.open(metaFile, FILE_READ);
                if (mf) {
                    String m = mf.readString();
                    mf.close();
                    if (m.indexOf("RECOVERABLE_INCOMPLETE") >= 0) {
                        s.state = SESSION_STATE_RECOVERABLE_INCOMPLETE;
                    } else if (m.indexOf("ACTIVE") >= 0) {
                        s.state = SESSION_STATE_ACTIVE;
                    }
                }
            }

            count++;
        }
        entry = sessionsDir.openNextFile();
    }

    return count;
}

bool SdLogger::readSessionMetadata(const char* sessionId, String& outJson) {
    if (!_sdAvailable || !isValidSessionId(sessionId)) return false;

    char metaPath[96];
    snprintf(metaPath, sizeof(metaPath), "%s/%s/metadata.json", SEYYANEN_SD_SESSIONS_DIR, sessionId);
    if (!SD.exists(metaPath)) return false;

    File f = SD.open(metaPath, FILE_READ);
    if (!f) return false;
    outJson = f.readString();
    f.close();
    return true;
}

File SdLogger::openSessionFileForRead(const char* sessionId, const char* filename) {
    if (!_sdAvailable || !isValidSessionId(sessionId)) {
        return File();
    }

    // Security Filter: Strictly allow only approved file names
    if (!filename || (strcmp(filename, "session.csv") != 0 &&
                      strcmp(filename, "metadata.json") != 0 &&
                      strcmp(filename, "events.log") != 0)) {
        return File();
    }

    char targetPath[96];
    snprintf(targetPath, sizeof(targetPath), "%s/%s/%s", SEYYANEN_SD_SESSIONS_DIR, sessionId, filename);
    if (!SD.exists(targetPath)) {
        return File();
    }

    return SD.open(targetPath, FILE_READ);
}
