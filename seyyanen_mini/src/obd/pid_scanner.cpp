#include "pid_scanner.h"

PidScanner::PidScanner(Obd2Client& obdClient)
    : _obdClient(obdClient),
      _state(SCANNER_STATE_IDLE),
      _regCount(0),
      _registryOverflowCount(0) {
    memset(_dynamicNames, 0, sizeof(_dynamicNames));
    memset(_dynamicCodes, 0, sizeof(_dynamicCodes));
    initPidRegistry();
}

PidScanner::~PidScanner() {}

void PidScanner::initPidRegistry() {
    _regCount = 0;
    _registryOverflowCount = 0;
    _state = SCANNER_STATE_IDLE;

    // Standard Mode 01 PIDs (0100..0111)
    registerPid(0x0100, "Supported PIDs [01-20]", "PID00", "bitmap",
                "Supported PIDs block 01-20 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);

    registerPid(0x0101, "Monitor Status Since DTCs Cleared", "STATUS", "status",
                "OBD-II monitor status bits", "Bitmask", "DECODER_RAW",
                5000, 2, NULL, 0.0f, 0.0f);

    registerPid(0x0102, "Freeze DTC", "FRZ_DTC", "code",
                "Diagnostic Trouble Code causing freeze frame", "DTC string", "DECODER_RAW",
                5000, 2, NULL, 0.0f, 0.0f);

    registerPid(0x0103, "Fuel System Status", "FUEL_SYS", "flags",
                "Fuel system open/closed loop status", "Bitmask", "DECODER_RAW",
                3000, 2, NULL, 0.0f, 0.0f);

    registerPid(0x0104, "Calculated Engine Load", "LOAD", "%",
                "Calculated percentage of engine peak torque", "A*100/255", "DECODER_LOAD",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeEngineLoad, 0.0f, 100.0f);

    registerPid(0x0105, "Engine Coolant Temperature", "ECT", "degC",
                "Coolant temp measured by cylinder head/radiator sensor", "A-40", "DECODER_ECT",
                SEYYANEN_INTERVAL_SLOW, 2, Obd2::decodeECT, -40.0f, 150.0f);

    registerPid(0x0106, "Short Term Fuel Trim Bank 1", "STFT1", "%",
                "Immediate closed-loop air/fuel ratio correction", "(A-128)*100/128", "DECODER_STFT",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeSTFT, -100.0f, 100.0f);

    registerPid(0x0107, "Long Term Fuel Trim Bank 1", "LTFT1", "%",
                "Persistent learned air/fuel ratio correction", "(A-128)*100/128", "DECODER_LTFT",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeLTFT, -100.0f, 100.0f);

    registerPid(0x010B, "Intake Manifold Absolute Pressure", "MAP", "kPa",
                "Absolute manifold pressure measured downstream of throttle", "A", "DECODER_MAP",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeMAP, 0.0f, 255.0f);

    registerPid(0x010C, "Engine Speed", "RPM", "rpm",
                "Rotational speed of crankshaft in revolutions per minute", "((A*256)+B)/4", "DECODER_RPM",
                SEYYANEN_INTERVAL_FAST, 0, Obd2::decodeRPM, 0.0f, 10000.0f);

    registerPid(0x010D, "Vehicle Speed", "SPEED", "km/h",
                "Current road speed calculated by transmission sensor", "A", "DECODER_SPEED",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeSpeed, 0.0f, 350.0f);

    registerPid(0x010E, "Ignition Timing Advance", "TIMING", "deg",
                "Ignition spark timing advance before top dead center", "(A/2)-64", "DECODER_TIMING",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeTimingAdvance, -64.0f, 63.5f);

    registerPid(0x010F, "Intake Air Temperature", "IAT", "degC",
                "Air temperature inside intake manifold/airbox", "A-40", "DECODER_IAT",
                SEYYANEN_INTERVAL_SLOW, 2, Obd2::decodeIAT, -40.0f, 150.0f);

    registerPid(0x0110, "MAF Air Flow Rate", "MAF", "g/s",
                "Mass of air entering cylinders per second", "((A*256)+B)/100", "DECODER_MAF",
                SEYYANEN_INTERVAL_MEDIUM, 1, Obd2::decodeMAF, 0.0f, 655.35f);

    registerPid(0x0111, "Throttle Position", "TPS", "%",
                "Absolute throttle blade opening percentage", "A*100/255", "DECODER_TPS",
                SEYYANEN_INTERVAL_FAST, 0, Obd2::decodeTPS, 0.0f, 100.0f);

    // Chained Range Marker PIDs up to 01E0
    registerPid(0x0120, "Supported PIDs [21-40]", "PID20", "bitmap",
                "Supported PIDs block 21-40 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
    registerPid(0x0140, "Supported PIDs [41-60]", "PID40", "bitmap",
                "Supported PIDs block 41-60 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
    registerPid(0x0160, "Supported PIDs [61-80]", "PID60", "bitmap",
                "Supported PIDs block 61-80 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
    registerPid(0x0180, "Supported PIDs [81-A0]", "PID80", "bitmap",
                "Supported PIDs block 81-A0 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
    registerPid(0x01A0, "Supported PIDs [A1-C0]", "PIDA0", "bitmap",
                "Supported PIDs block A1-C0 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
    registerPid(0x01C0, "Supported PIDs [C1-E0]", "PIDC0", "bitmap",
                "Supported PIDs block C1-E0 bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
    registerPid(0x01E0, "Supported PIDs [E1-FF]", "PIDE0", "bitmap",
                "Supported PIDs block E1-FF bitmap", "32-bit bitmap", "DECODER_BITMAP",
                0, 2, NULL, 0.0f, 0.0f);
}

void PidScanner::registerPid(uint16_t pid, const char* name, const char* shortCode, const char* unit,
                             const char* description, const char* rawFormula, const char* decoderId,
                             uint32_t intervalMs, uint8_t priority, PidDecodeFunc fn,
                             float minValid, float maxValid) {
    if (_regCount >= MAX_REGISTERED_PIDS) {
        _registryOverflowCount++;
        return;
    }

    PidMetadata& m = _registry[_regCount++];
    m.pid = pid;
    m.mode = (uint8_t)((pid >> 8) & 0xFF);
    m.name = name;
    m.short_code = shortCode;
    m.unit = unit;
    m.description = description;
    m.raw_formula = rawFormula;
    m.decoder_id = decoderId;
    m.supported = false;
    m.source_range = 0;
    m.bit_index = 0;
    m.priority = priority;
    m.poll_interval_ms = intervalMs;
    m.decode_fn = fn;
    m.min_valid = minValid;
    m.max_valid = maxValid;
    m.last_smoke_value = 0.0f;
    m.has_smoke_value = false;
}

bool PidScanner::scanBitmapRange(uint8_t basePid, uint32_t& bitmapOut) {
    Serial.printf("[MINI-PID] Request 01%02X\n", basePid);

    ObdResult res = _obdClient.request(0x01, basePid, 2000);

    if (res.status != SAMPLE_STATUS_VALID || res.normalized_len < 4) {
        Serial.printf("[MINI-PID] 01%02X failed or returned insufficient payload! Raw: '%s'\n",
                      basePid, res.raw_response);
        return false;
    }

    Serial.printf("[MINI-PID] RX: %s\n", res.raw_response);
    bitmapOut = Obd2::bytesToUint32(res.normalized_bytes);
    applyBitmapToRegistry(basePid, bitmapOut);

    return true;
}

void PidScanner::applyBitmapToRegistry(uint8_t basePid, uint32_t bitmap) {
    // 1. Check already registered PIDs
    for (size_t i = 0; i < _regCount; ++i) {
        uint8_t pidNumber = (uint8_t)(_registry[i].pid & 0xFF);
        if (_registry[i].mode != 0x01) continue;

        // Check if PID falls inside block [basePid + 1 ... basePid + 32]
        if (pidNumber > basePid && pidNumber <= (basePid + 32)) {
            uint8_t relativePid = pidNumber - basePid;
            bool supp = Obd2::isPidBitSet(bitmap, relativePid);
            _registry[i].supported = supp;
            _registry[i].source_range = basePid;
            _registry[i].bit_index = relativePid;

            if (supp) {
                Serial.printf("[MINI-PID] Supported: 01%02X (%s)\n", pidNumber, _registry[i].short_code);
            }
        }
    }

    // 2. Dynamically register any newly discovered supported PIDs not yet in registry
    for (uint8_t relativePid = 1; relativePid <= 32; ++relativePid) {
        if (Obd2::isPidBitSet(bitmap, relativePid)) {
            uint8_t pidNum = basePid + relativePid;
            uint16_t fullPid = 0x0100 | pidNum;

            if (!findPid(fullPid)) {
                if (_regCount < MAX_REGISTERED_PIDS) {
                    size_t idx = _regCount;
                    snprintf(_dynamicNames[idx], sizeof(_dynamicNames[idx]), "Mode 01 PID %02X", pidNum);
                    snprintf(_dynamicCodes[idx], sizeof(_dynamicCodes[idx]), "PID%02X", pidNum);

                    registerPid(fullPid, _dynamicNames[idx], _dynamicCodes[idx], "",
                                "Standard OBD-II Parameter", "Raw", "DECODER_RAW",
                                SEYYANEN_INTERVAL_SLOW_MS, 2, NULL, 0.0f, 0.0f);
                    // Mark as supported and record range/bit
                    _registry[idx].supported = true;
                    _registry[idx].source_range = basePid;
                    _registry[idx].bit_index = relativePid;
                    Serial.printf("[MINI-PID] Dynamically registered supported: 01%02X\n", pidNum);
                } else {
                    _registryOverflowCount++;
                    Serial.printf("[MINI-PID] WARNING: Registry capacity full! Cannot register 01%02X (Overflow count: %u)\n",
                                  pidNum, (unsigned int)_registryOverflowCount);
                }
            }
        }
    }
}

bool PidScanner::scanSupportedPids() {
    if (!_obdClient.isReady()) {
        Serial.println("[MINI-PID] Cannot scan: OBD client is not READY!");
        _state = SCANNER_STATE_ERROR;
        return false;
    }

    _state = SCANNER_STATE_SCANNING;
    Serial.println("[MINI-PID] Scanning supported PIDs (Standard Mode 01 Chained Discovery)");

    uint8_t currentBase = 0x00;
    while (true) {
        uint32_t bitmap = 0;
        if (!scanBitmapRange(currentBase, bitmap)) {
            Serial.printf("[MINI-PID] Bitmap query for 01%02X failed!\n", currentBase);
            _state = SCANNER_STATE_ERROR;
            return false;
        }

        // Bit 32 indicates presence of next range (currentBase + 0x20)
        bool hasNext = Obd2::isPidBitSet(bitmap, 32);
        if (!hasNext || currentBase >= 0xE0) {
            if (!hasNext) {
                Serial.printf("[MINI-PID] ECU does not advertise PIDs beyond 01%02X; stopping chained scan cleanly.\n", currentBase + 0x20);
            } else {
                Serial.println("[MINI-PID] Reached maximum standard Mode 01 range 01E0.");
            }
            break;
        }

        currentBase += 0x20;
        Serial.printf("[MINI-PID] Next range 01%02X advertised as supported by ECU.\n", currentBase);
    }

    _state = SCANNER_STATE_COMPLETE;
    Serial.println("[MINI-PID] Scan complete");
    Serial.printf("[MINI-PID] Supported PID count: %u\n", (unsigned int)getSupportedCount());

    char listStr[128];
    getSupportedPidListString(listStr, sizeof(listStr));
    Serial.printf("[MINI-PID] Discovered PIDs: %s\n", listStr);

    return true;
}

bool PidScanner::probeSmokePids() {
    if (_state != SCANNER_STATE_COMPLETE || !_obdClient.isReady()) {
        Serial.println("[MINI-OBD] Cannot probe smoke PIDs: scan not complete or OBD not ready.");
        return false;
    }

    Serial.println("[MINI-OBD] Executing harmless initial smoke probes (010C, 0105, 010D)...");

    // 1. Engine RPM (010C)
    PidMetadata* mRpm = findPid(0x010C);
    if (mRpm && mRpm->supported) {
        ObdResult r = queryPid(0x010C);
        if (r.status == SAMPLE_STATUS_VALID) {
            mRpm->last_smoke_value = r.decoded_value;
            mRpm->has_smoke_value = true;
            Serial.printf("[MINI-OBD] Smoke Probe 010C (RPM) -> %.2f %s (Latency: %u ms)\n",
                          r.decoded_value, r.unit, (unsigned int)r.latency_ms);
        }
    }

    // 2. Engine Coolant Temperature (0105)
    PidMetadata* mEct = findPid(0x0105);
    if (mEct && mEct->supported) {
        ObdResult r = queryPid(0x0105);
        if (r.status == SAMPLE_STATUS_VALID) {
            mEct->last_smoke_value = r.decoded_value;
            mEct->has_smoke_value = true;
            Serial.printf("[MINI-OBD] Smoke Probe 0105 (ECT) -> %.2f %s (Latency: %u ms)\n",
                          r.decoded_value, r.unit, (unsigned int)r.latency_ms);
        }
    }

    // 3. Vehicle Speed (010D)
    PidMetadata* mSpd = findPid(0x010D);
    if (mSpd && mSpd->supported) {
        ObdResult r = queryPid(0x010D);
        if (r.status == SAMPLE_STATUS_VALID) {
            mSpd->last_smoke_value = r.decoded_value;
            mSpd->has_smoke_value = true;
            Serial.printf("[MINI-OBD] Smoke Probe 010D (Speed) -> %.2f %s (Latency: %u ms)\n",
                          r.decoded_value, r.unit, (unsigned int)r.latency_ms);
        }
    }

    Serial.println("[MINI-OBD] Smoke probes completed successfully.");
    return true;
}

PidScannerState PidScanner::getState() const {
    return _state;
}

const char* PidScanner::getStateString() const {
    return scannerStateToString(_state);
}

bool PidScanner::isScanned() const {
    return (_state == SCANNER_STATE_COMPLETE);
}

size_t PidScanner::getRegisteredCount() const {
    return _regCount;
}

size_t PidScanner::getSupportedCount() const {
    size_t count = 0;
    for (size_t i = 0; i < _regCount; ++i) {
        if (_registry[i].supported) count++;
    }
    return count;
}

size_t PidScanner::getRegistryOverflowCount() const {
    return _registryOverflowCount;
}

PidMetadata* PidScanner::getPidMetadata(size_t index) {
    if (index >= _regCount) return NULL;
    return &_registry[index];
}

const PidMetadata* PidScanner::getPidMetadata(size_t index) const {
    if (index >= _regCount) return NULL;
    return &_registry[index];
}

PidMetadata* PidScanner::findPid(uint16_t pid) {
    for (size_t i = 0; i < _regCount; ++i) {
        if (_registry[i].pid == pid) {
            return &_registry[i];
        }
    }
    return NULL;
}

const PidMetadata* PidScanner::findPid(uint16_t pid) const {
    for (size_t i = 0; i < _regCount; ++i) {
        if (_registry[i].pid == pid) {
            return &_registry[i];
        }
    }
    return NULL;
}

ObdResult PidScanner::queryPid(uint16_t pid, uint32_t timeoutMs) {
    uint8_t mode = (uint8_t)((pid >> 8) & 0xFF);
    uint8_t pidNumber = (uint8_t)(pid & 0xFF);
    return _obdClient.request(mode, pidNumber, timeoutMs);
}

void PidScanner::getSupportedPidListString(char* buffer, size_t maxLen) const {
    if (!buffer || maxLen == 0) return;
    buffer[0] = '\0';

    bool first = true;
    for (size_t i = 0; i < _regCount; ++i) {
        if (_registry[i].supported) {
            char item[16];
            snprintf(item, sizeof(item), "%s01%02X", first ? "" : " ", (uint8_t)(_registry[i].pid & 0xFF));
            first = false;
            strncat(buffer, item, maxLen - strlen(buffer) - 1);
        }
    }
}
