#include "scheduler.h"
#include "storage/sd_logger.h"
#include <string.h>

uint32_t AcquisitionScheduler::s_sessionCounter = 1;

AcquisitionScheduler::AcquisitionScheduler(VLinkerBluetoothTransport& bt,
                                           Obd2Client& obdClient,
                                           PidScanner& scanner,
                                           SampleRingBuffer& ringBuffer)
    : _bt(bt),
      _obdClient(obdClient),
      _scanner(scanner),
      _ringBuffer(ringBuffer),
      _logger(nullptr),
      _state(ACQ_STATE_IDLE),
      _sequence(0),
      _frameId(0),
      _sessionStartUs(0),
      _cycleStartUs(0),
      _activePidCount(0),
      _unscheduledCount(0) {
    memset(_sessionId, 0, sizeof(_sessionId));
    memset(_activePids, 0, sizeof(_activePids));
    memset(_unscheduledPids, 0, sizeof(_unscheduledPids));
    memset(&_snapshot, 0, sizeof(_snapshot));
    memset(&_metrics, 0, sizeof(_metrics));

    _snapshotMutex = xSemaphoreCreateMutex();
    _snapshot.state = ACQ_STATE_IDLE;
}

AcquisitionScheduler::~AcquisitionScheduler() {
    stop();
    if (_snapshotMutex) {
        vSemaphoreDelete(_snapshotMutex);
    }
}

void AcquisitionScheduler::generateNewSessionId() {
    snprintf(_sessionId, sizeof(_sessionId), "MINI-SESSION-%06u", (unsigned int)s_sessionCounter++);
}

void AcquisitionScheduler::setLogger(SdLogger* logger) {
    _logger = logger;
}

bool AcquisitionScheduler::start(const char* sessionId) {
    // 1. Safety Gate: Cannot start if transport or OBD are not verified & ready
    if (!_bt.isConnected()) {
        Serial.println("[SCHEDULER] Cannot start: Bluetooth transport is not CONNECTED!");
        _state = ACQ_STATE_ERROR;
        return false;
    }

    if (!_obdClient.isReady()) {
        Serial.println("[SCHEDULER] Cannot start: OBD layer is not READY!");
        _state = ACQ_STATE_ERROR;
        return false;
    }

    if (!_scanner.isScanned() || _scanner.getSupportedCount() == 0) {
        Serial.println("[SCHEDULER] Cannot start: No supported PIDs discovered yet!");
        _state = ACQ_STATE_ERROR;
        return false;
    }

    _state = ACQ_STATE_STARTING;

    // 2. Establish Session Identifier
    if (sessionId && strlen(sessionId) > 0) {
        strncpy(_sessionId, sessionId, sizeof(_sessionId) - 1);
    } else {
        generateNewSessionId();
    }

    // 3. Reset Sequence & Frame Counters
    _sequence = 0;
    _frameId = 1;
    _sessionStartUs = esp_timer_get_time();
    _cycleStartUs = _sessionStartUs;

    // 4. Setup Active Polling Schedule
    setupActiveSchedule();

    // 5. Reset Metrics
    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        memset(&_metrics, 0, sizeof(_metrics));
        _metrics.active_pid_count = _activePidCount;
        strncpy(_snapshot.session_id, _sessionId, sizeof(_snapshot.session_id) - 1);
        _snapshot.state = ACQ_STATE_RUNNING;
        xSemaphoreGive(_snapshotMutex);
    }

    _state = ACQ_STATE_RUNNING;
    Serial.printf("[SCHEDULER] Live acquisition RUNNING. Session: %s, Active PIDs: %u\n",
                  _sessionId, (unsigned int)_activePidCount);

    if (_logger && _logger->isReady()) {
        _logger->startSession(_sessionId, _bt.getAdapterIdentity(), _obdClient.getProtocol(), _scanner);
    }
    return true;
}

bool AcquisitionScheduler::stop() {
    if (_state == ACQ_STATE_IDLE || _state == ACQ_STATE_STOPPED) {
        return true;
    }

    _state = ACQ_STATE_STOPPING;

    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        _snapshot.state = ACQ_STATE_STOPPED;
        xSemaphoreGive(_snapshotMutex);
    }

    _state = ACQ_STATE_STOPPED;
    Serial.printf("[SCHEDULER] Live acquisition STOPPED. Session: %s, Total Requests: %u\n",
                  _sessionId, (unsigned int)_metrics.total_requests);

    if (_logger && _logger->isSessionActive()) {
        _logger->stopSession();
    }
    return true;
}

bool AcquisitionScheduler::pause() {
    if (_state != ACQ_STATE_RUNNING) {
        return false;
    }

    _state = ACQ_STATE_PAUSED;
    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        _snapshot.state = ACQ_STATE_PAUSED;
        xSemaphoreGive(_snapshotMutex);
    }

    if (_logger && _logger->isSessionActive()) {
        _logger->writeEvent("ACQUISITION_PAUSED", "Scheduler paused");
    }

    Serial.println("[SCHEDULER] Live acquisition PAUSED.");
    return true;
}

bool AcquisitionScheduler::resume() {
    if (_state != ACQ_STATE_PAUSED) {
        return false;
    }

    _state = ACQ_STATE_RUNNING;
    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        _snapshot.state = ACQ_STATE_RUNNING;
        xSemaphoreGive(_snapshotMutex);
    }

    if (_logger && _logger->isSessionActive()) {
        _logger->writeEvent("ACQUISITION_RESUMED", "Scheduler resumed");
    }

    Serial.println("[SCHEDULER] Live acquisition RESUMED.");
    return true;
}

bool AcquisitionScheduler::isRunning() const {
    return (_state == ACQ_STATE_RUNNING);
}

AcquisitionState AcquisitionScheduler::getState() const {
    return _state;
}

const char* AcquisitionScheduler::getStateString() const {
    return acquisitionStateToString(_state);
}

const char* AcquisitionScheduler::getSessionId() const {
    return _sessionId;
}

uint32_t AcquisitionScheduler::getSequence() const {
    return _sequence;
}

uint32_t AcquisitionScheduler::getFrameId() const {
    return _frameId;
}

void AcquisitionScheduler::setupActiveSchedule() {
    _activePidCount = 0;
    _unscheduledCount = 0;
    size_t regCount = _scanner.getRegisteredCount();

    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        _snapshot.signal_count = 0;

        for (size_t i = 0; i < regCount; ++i) {
            const PidMetadata* m = _scanner.getPidMetadata(i);
            if (!m) continue;

            // Skip block bitmap header PIDs from live continuous polling
            if ((m->pid & 0x001F) == 0x0000 && m->decode_fn == NULL) continue;

            if (!m->supported) {
                if (_unscheduledCount < SEYYANEN_MAX_UNSCHEDULED_PIDS) {
                    UnscheduledPidInfo& u = _unscheduledPids[_unscheduledCount++];
                    u.pid = m->pid;
                    strncpy(u.name, m->short_code, sizeof(u.name) - 1);
                    u.reason = UNSCHEDULED_REASON_UNSUPPORTED;
                }
                continue;
            }

            if (_activePidCount < SEYYANEN_MAX_SCHEDULED_PIDS) {
                ScheduledPid& sp = _activePids[_activePidCount];
                sp.pid = m->pid;
                strncpy(sp.name, m->short_code, sizeof(sp.name) - 1);
                strncpy(sp.unit, m->unit, sizeof(sp.unit) - 1);
                sp.enabled = true;
                sp.priority = m->priority;
                sp.request_count = 0;
                sp.error_count = 0;
                sp.last_requested_us = 0;
                sp.last_success_us = 0;
                sp.target_interval_us = 0;
                sp.observed_interval_us = 0;
                sp.scheduler_delay_us = 0;
                sp.deadline_miss_count = 0;
                sp.is_deadline_miss = false;

                // Profile intervals in microseconds
                if (sp.priority == 0) {
                    sp.interval_us = (uint64_t)SEYYANEN_INTERVAL_FAST_MS * 1000ULL;
                } else if (sp.priority == 1) {
                    sp.interval_us = (uint64_t)SEYYANEN_INTERVAL_MEDIUM_MS * 1000ULL;
                } else {
                    sp.interval_us = (uint64_t)SEYYANEN_INTERVAL_SLOW_MS * 1000ULL;
                }
                sp.target_interval_us = sp.interval_us;

                // Setup Snapshot Signal
                LiveSignal& ls = _snapshot.signals[_snapshot.signal_count++];
                ls.pid = m->pid;
                strncpy(ls.name, m->short_code, sizeof(ls.name) - 1);
                strncpy(ls.unit, m->unit, sizeof(ls.unit) - 1);
                ls.value = m->last_smoke_value;
                ls.last_valid_value = m->last_smoke_value;
                ls.quality = m->has_smoke_value ? QUALITY_GRADE_GOOD : QUALITY_GRADE_NO_DATA;
                ls.freshness = FRESHNESS_NEVER_VALID;
                ls.last_success_us = 0;
                ls.age_ms = 0;
                ls.latency_ms = 0;
                ls.target_interval_ms = (uint32_t)(sp.target_interval_us / 1000ULL);
                ls.observed_interval_ms = 0;
                ls.scheduler_delay_ms = 0;
                ls.deadline_misses = 0;

                _activePidCount++;
            } else {
                // Exceeded scheduler capacity! Track explicitly
                if (_unscheduledCount < SEYYANEN_MAX_UNSCHEDULED_PIDS) {
                    UnscheduledPidInfo& u = _unscheduledPids[_unscheduledCount++];
                    u.pid = m->pid;
                    strncpy(u.name, m->short_code, sizeof(u.name) - 1);
                    u.reason = UNSCHEDULED_REASON_EXCEEDED_CAPACITY;
                }
            }
        }
        xSemaphoreGive(_snapshotMutex);
    }
}

int AcquisitionScheduler::selectNextDuePid(uint64_t nowUs) {
    if (_activePidCount == 0) return -1;

    int bestIdx = -1;
    uint64_t maxUrgency = 0;

    for (size_t i = 0; i < _activePidCount; ++i) {
        if (!_activePids[i].enabled) continue;

        // If never requested yet, it is immediately maximally due
        if (_activePids[i].last_requested_us == 0) {
            return (int)i;
        }

        uint64_t elapsed = (nowUs >= _activePids[i].last_requested_us) 
                           ? (nowUs - _activePids[i].last_requested_us) 
                           : 0;

        // A PID is due when elapsed >= interval
        if (elapsed >= _activePids[i].interval_us) {
            // Fairness Urgency Metric: proportional overdue ratio
            uint64_t urgency = (elapsed * 1000ULL) / _activePids[i].interval_us;
            if (urgency > maxUrgency) {
                maxUrgency = urgency;
                bestIdx = (int)i;
            }
        }
    }

    return bestIdx;
}

void AcquisitionScheduler::update() {
    if (_state != ACQ_STATE_RUNNING) {
        return;
    }

    // Check transport health: if Bluetooth dropped, escalate
    if (!_bt.isConnected()) {
        Serial.println("[SCHEDULER] Bluetooth link dropped. Entering PAUSED state.");
        pause();
        return;
    }

    uint64_t nowUs = esp_timer_get_time();
    int dueIdx = selectNextDuePid(nowUs);

    if (dueIdx >= 0) {
        executeScheduledQuery(_activePids[dueIdx], nowUs);
    }
}

void AcquisitionScheduler::executeScheduledQuery(ScheduledPid& sp, uint64_t nowUs) {
    // Timing Observability: Calculate observed interval and scheduler delay
    sp.target_interval_us = sp.interval_us;
    if (sp.last_requested_us > 0) {
        sp.observed_interval_us = (nowUs >= sp.last_requested_us) ? (nowUs - sp.last_requested_us) : sp.interval_us;
        uint64_t expectedDueUs = sp.last_requested_us + sp.interval_us;
        sp.scheduler_delay_us = (nowUs > expectedDueUs) ? (nowUs - expectedDueUs) : 0;
    } else {
        sp.observed_interval_us = sp.interval_us;
        sp.scheduler_delay_us = 0;
    }
    sp.last_requested_us = nowUs;
    sp.request_count++;

    // Deadline miss threshold: delay > 10% of target or > 25ms
    uint64_t missThresholdUs = (sp.interval_us / 10ULL) > 25000ULL ? (sp.interval_us / 10ULL) : 25000ULL;
    sp.is_deadline_miss = (sp.scheduler_delay_us > missThresholdUs);
    if (sp.is_deadline_miss) {
        sp.deadline_miss_count++;
    }

    // Strict Rule: NEVER hold snapshot mutex across blocking OBD I/O!
    uint64_t reqStartUs = esp_timer_get_time();
    ObdResult res = _obdClient.request(0x01, (uint8_t)(sp.pid & 0xFF), SEYYANEN_COMMAND_TIMEOUT);
    uint64_t respEndUs = esp_timer_get_time();

    bool isSuccess = (res.status == SAMPLE_STATUS_VALID);
    uint32_t latencyUs = (uint32_t)(respEndUs - reqStartUs);

    if (isSuccess) {
        sp.last_success_us = respEndUs;
    } else {
        sp.error_count++;
    }

    // Build MeasurementSample preserving all timing metrics
    MeasurementSample sample;
    memset(&sample, 0, sizeof(sample));
    strncpy(sample.session_id, _sessionId, sizeof(sample.session_id) - 1);
    sample.sequence = ++_sequence;
    sample.timestamp_us = respEndUs;
    sample.pid = sp.pid;
    strncpy(sample.name, sp.name, sizeof(sample.name) - 1);
    strncpy(sample.raw_response, res.raw_response, sizeof(sample.raw_response) - 1);
    memcpy(sample.normalized_bytes, res.normalized_bytes, res.normalized_len);
    sample.normalized_len = res.normalized_len;
    sample.decoded_value = res.decoded_value;
    strncpy(sample.unit, res.unit, sizeof(sample.unit) - 1);
    sample.status = res.status;
    sample.request_start_us = reqStartUs;
    sample.response_timestamp_us = respEndUs;
    sample.latency_us = latencyUs;
    sample.target_interval_us = (uint32_t)sp.target_interval_us;
    sample.observed_interval_us = (uint32_t)sp.observed_interval_us;
    sample.scheduler_delay_us = (uint32_t)sp.scheduler_delay_us;
    sample.is_deadline_miss = sp.is_deadline_miss;

    // Quality & Freshness Assessment
    const PidMetadata* meta = _scanner.findPid(sp.pid);
    sample.quality = QualityEngine::evaluate(sample, meta, respEndUs);
    sample.freshness = QualityEngine::evaluateFreshness(sp.last_success_us, respEndUs);

    // Push into Bounded Ring Buffer
    _ringBuffer.push(sample);

    // Decoupled Storage Queue (Phase M-5 Hardened)
    if (_logger && _logger->isSessionActive()) {
        _logger->enqueueSample(sample);
    }

    // Update Live Snapshot and Metrics under fast mutex
    updateLiveSignal(sp.pid, res.decoded_value, isSuccess, sample.quality, sample.freshness, respEndUs, res.latency_ms, sp);
}

void AcquisitionScheduler::updateLiveSignal(uint16_t pid, float val, bool valid, QualityGrade q,
                                            FreshnessState f, uint64_t nowUs, uint32_t latencyMs,
                                            const ScheduledPid& sp) {
    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(30)) == pdTRUE) {
        // Update Signal
        for (size_t i = 0; i < _snapshot.signal_count; ++i) {
            if (_snapshot.signals[i].pid == pid) {
                if (valid) {
                    _snapshot.signals[i].value = val;
                    _snapshot.signals[i].last_valid_value = val; // Retained value
                    _snapshot.signals[i].last_success_us = nowUs;
                }
                _snapshot.signals[i].quality = q;
                _snapshot.signals[i].freshness = f;
                _snapshot.signals[i].latency_ms = latencyMs;
                _snapshot.signals[i].age_ms = (nowUs > _snapshot.signals[i].last_success_us) 
                                              ? (uint32_t)((nowUs - _snapshot.signals[i].last_success_us) / 1000ULL)
                                              : 0;
                _snapshot.signals[i].target_interval_ms = (uint32_t)(sp.target_interval_us / 1000ULL);
                _snapshot.signals[i].observed_interval_ms = (uint32_t)(sp.observed_interval_us / 1000ULL);
                _snapshot.signals[i].scheduler_delay_ms = (uint32_t)(sp.scheduler_delay_us / 1000ULL);
                _snapshot.signals[i].deadline_misses = sp.deadline_miss_count;
                break;
            }
        }

        // Update Performance Metrics
        _metrics.total_requests++;
        if (valid) {
            _metrics.successful_requests++;
        } else {
            if (q == QUALITY_GRADE_TIMEOUT) _metrics.timeouts++;
            else if (q == QUALITY_GRADE_NO_DATA) _metrics.no_data_count++;
            else if (q == QUALITY_GRADE_TRANSPORT_ERROR) _metrics.transport_errors++;
            else _metrics.malformed_count++;
        }

        _metrics.last_latency_ms = latencyMs;
        if (_metrics.total_requests > 0) {
            // Running average latency
            _metrics.average_latency_ms = (_metrics.average_latency_ms * 0.9f) + ((float)latencyMs * 0.1f);
            uint64_t elapsedSec = (nowUs > _sessionStartUs) ? ((nowUs - _sessionStartUs) / 1000000ULL) : 1;
            if (elapsedSec > 0) {
                _metrics.requests_per_sec = (float)_metrics.total_requests / (float)elapsedSec;
            }
        }

        _snapshot.metrics = _metrics;
        _snapshot.uptime_sec = (uint32_t)((nowUs - _sessionStartUs) / 1000000ULL);

        xSemaphoreGive(_snapshotMutex);
    }
}

void AcquisitionScheduler::getSnapshot(LiveSnapshot& outSnapshot) {
    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        uint64_t nowUs = esp_timer_get_time();
        // Update ages dynamically before giving snapshot
        for (size_t i = 0; i < _snapshot.signal_count; ++i) {
            if (_snapshot.signals[i].last_success_us > 0) {
                _snapshot.signals[i].age_ms = (nowUs > _snapshot.signals[i].last_success_us) 
                                              ? (uint32_t)((nowUs - _snapshot.signals[i].last_success_us) / 1000ULL)
                                              : 0;
                _snapshot.signals[i].freshness = QualityEngine::evaluateFreshness(_snapshot.signals[i].last_success_us, nowUs);
            }
        }
        outSnapshot = _snapshot;
        xSemaphoreGive(_snapshotMutex);
    }
}

void AcquisitionScheduler::getMetrics(AcquisitionMetrics& outMetrics) {
    if (_snapshotMutex && xSemaphoreTake(_snapshotMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        outMetrics = _metrics;
        xSemaphoreGive(_snapshotMutex);
    }
}
