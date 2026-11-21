#include "obd_manager.h"
#include "config.h"
#include "obd_response_parser.h"

constexpr uint8_t ObdManager::Pids[ObdManager::Count];

namespace {
using ObdResponseParser::Frame;
using ObdResponseParser::Result;

const char* responseFailure(const String& response) {
  String upper = response;
  upper.toUpperCase();
  if (upper.indexOf("SEARCHING") >= 0) return "SEARCHING without a completed ECU reply";
  if (upper.indexOf("BUS INIT") >= 0) return "BUS INIT failed before a completed ECU reply";
  if (upper.indexOf("UNABLE TO CONNECT") >= 0) return "UNABLE TO CONNECT";
  if (upper.indexOf("NO DATA") >= 0) return "NO DATA";
  if (upper.indexOf('?') >= 0) return "adapter returned '?'";
  if (!response.length()) return "empty response / timeout";
  return "no valid positive response for requested service/PID";
}

bool isTransportLoss(const String& response) {
  String upper = response;
  upper.toUpperCase();
  return upper.indexOf("UNABLE TO CONNECT") >= 0 || upper.indexOf("BUS INIT") >= 0;
}

bool protocolSelectionAccepted(const String& response, bool kwp, bool timedOut) {
  if (timedOut) return false;
  String upper = response;
  upper.toUpperCase(); upper.trim();
  if (!upper.length() || upper.indexOf('?') >= 0 || upper.indexOf("ERROR") >= 0 ||
      upper.indexOf("UNABLE TO CONNECT") >= 0) return false;
  if (upper.indexOf("OK") >= 0) return true;
  return kwp ? (upper.indexOf("KWP") >= 0 || upper.indexOf("ISO 14230") >= 0 ||
                upper.indexOf("PROTOCOL 4") >= 0 || upper == "4")
             : (upper.indexOf("AUTO") >= 0 || upper.indexOf("ISO") >= 0 ||
                upper.indexOf("SAE") >= 0 || upper.indexOf("CAN") >= 0 ||
                upper.indexOf("J1850") >= 0 || upper.indexOf("PROTOCOL 0") >= 0 || upper == "0");
}

uint8_t supportScore(uint32_t bitmap) {
  static constexpr uint8_t targetPids[] = {0x05, 0x11, 0x0B, 0x06, 0x07};
  uint8_t score = 0;
  for (uint8_t pid : targetPids)
    if (ObdResponseParser::bitmapSupports(bitmap, pid)) ++score;
  return score;
}

bool sameHeader(const Frame& left, const Frame& right) {
  return left.hasEcuHeader && right.hasEcuHeader &&
         strcmp(left.ecuHeader, right.ecuHeader) == 0;
}

bool hasBitmapResponse(const String& response) {
  Result parsed;
  ObdResponseParser::parse(response.c_str(), parsed);
  for (uint8_t i = 0; i < parsed.count; ++i) {
    const Frame& frame = parsed.frames[i];
    if (!frame.negative && frame.service == 0x41 && frame.pid == 0x00 && frame.payloadLength >= 4)
      return true;
  }
  return false;
}
}

void ObdManager::invalidateValues() {
  portENTER_CRITICAL(&_valueMux);
  for (uint8_t i = 0; i < Count; ++i) _values[i].valid = false;
  portEXIT_CRITICAL(&_valueMux);
}

void ObdManager::scheduleDiscoveryRetry(const char* reason) {
  _supportKnown = false;
  _pending = false;
  _pendingCommand = PendingCommand::None;
  _fallbackTried = false;
  _usingKwp = false;
  _hasSelectedEcuHeader = false;
  _ambiguousEcuSelection = false;
  _selectedEcuHeader[0] = '\0';
  _nextIndex = 0;
  _consecutiveTimeouts = 0;
  for (uint8_t i = 0; i < Count; ++i) {
    _supported[i] = false;
    _failures[i] = 0;
  }
  invalidateValues();
  _ecuState = EcuState::Failed;
  _nextRequest = millis() + Config::EcuRetryIntervalMs;
  Serial.printf("[OBD ECU] Discovery scheduled again in %lu ms: %s\n",
                static_cast<unsigned long>(Config::EcuRetryIntervalMs), reason);
}

bool ObdManager::requestBitmap(VlinkerClient& client, bool autoProtocol) {
  if (!client.sendCommand("0100", Config::EcuResponseTimeoutMs)) {
    _nextRequest = millis() + 250;
    return false;
  }
  _pending = true;
  _pendingCommand = autoProtocol ? PendingCommand::BitmapAuto : PendingCommand::BitmapKwp;
  _ecuState = EcuState::Searching;
  _nextRequest = millis() + Config::EcuResponseTimeoutMs;
  Serial.printf("[OBD TX] PID=0100 protocol=%s supported-PID bitmap\n",
                autoProtocol ? "AUTO" : "KWP-5BAUD");
  return true;
}

void ObdManager::failAutoAndSelectKwp(VlinkerClient& client, const String& response) {
  Serial.printf("[OBD ERROR] PID=0100 AUTO discovery failed reason=%s RAW=%s\n",
                responseFailure(response), response.c_str());
  _fallbackTried = true;
  Serial.println("[OBD PROTOCOL] Trying ATSP4 (ISO 14230-4 KWP, 5-baud initialization)");
  if (client.sendCommand("ATSP4", 3000)) {
    _pending = true;
    _pendingCommand = PendingCommand::SelectKwp;
    _nextRequest = millis() + 3000;
  } else {
    // A timed-out AUTO command may still own the SPP stream until its prompt
    // arrives. Preserve the fallback decision and queue ATSP4 after resync.
    _pendingCommand = PendingCommand::SelectKwp;
    _nextRequest = millis() + 250;
  }
}

void ObdManager::consume(const String& response, bool timedOut) {
  Result parsed;
  ObdResponseParser::parse(response.c_str(), parsed);
  if (parsed.overflow)
    Serial.printf("[OBD PARSER] frame capacity exceeded; raw response may contain additional ECU frames: %s\n",
                  response.c_str());

  if (parsed.overflow) {
    if (!_supportKnown) {
      scheduleDiscoveryRetry("0100 response exceeded parser frame capacity; ECU selection is incomplete");
      return;
    }
    const uint8_t index = _nextIndex < Count ? _nextIndex : 0;
    if (_failures[index] < 255) ++_failures[index];
    if (_failures[index] >= Config::PidFailureLimit) {
      portENTER_CRITICAL(&_valueMux); _values[index].valid = false; portEXIT_CRITICAL(&_valueMux);
    }
    Serial.printf("[OBD ERROR] PID=01%02X REASON=frame capacity exceeded; refusing partial ECU response RAW=%s\n",
                  Pids[index], response.c_str());
    _nextIndex = static_cast<uint8_t>((index + 1) % Count);
    return;
  }

  if (!_supportKnown) {
    uint8_t candidates[ObdResponseParser::MaxFrames]{};
    uint8_t candidateCount = 0;
    for (uint8_t i = 0; i < parsed.count; ++i) {
      const Frame& frame = parsed.frames[i];
      if (!frame.negative && frame.service == 0x41 && frame.pid == 0x00 && frame.payloadLength >= 4)
        candidates[candidateCount++] = i;
    }
    if (!candidateCount) return;

    // Repeated frames from the same visible ECU are kept distinct by the
    // parser but only its first 0100 bitmap is considered. Never OR bitmaps.
    uint8_t unique[ObdResponseParser::MaxFrames]{};
    uint8_t uniqueCount = 0;
    for (uint8_t c = 0; c < candidateCount; ++c) {
      const Frame& candidate = parsed.frames[candidates[c]];
      bool duplicateEcu = false;
      for (uint8_t u = 0; u < uniqueCount; ++u) {
        const Frame& prior = parsed.frames[unique[u]];
        if (sameHeader(candidate, prior)) {
          duplicateEcu = true;
          if (ObdResponseParser::bitmapValue(candidate) != ObdResponseParser::bitmapValue(prior))
            Serial.printf("[OBD BITMAP] Conflicting 0100 replies from ECU %s; retaining its first frame\n", candidate.ecuHeader);
          break;
        }
      }
      if (!duplicateEcu) unique[uniqueCount++] = candidates[c];
    }

    uint8_t selectedIndex = unique[0];
    uint8_t selectedScore = supportScore(ObdResponseParser::bitmapValue(parsed.frames[selectedIndex]));
    for (uint8_t i = 1; i < uniqueCount; ++i) {
      const uint8_t index = unique[i];
      const uint8_t score = supportScore(ObdResponseParser::bitmapValue(parsed.frames[index]));
      if (score > selectedScore) { selectedIndex = index; selectedScore = score; }
    }
    const Frame& selected = parsed.frames[selectedIndex];
    const uint32_t bitmap = ObdResponseParser::bitmapValue(selected);
    _hasSelectedEcuHeader = selected.hasEcuHeader;
    if (_hasSelectedEcuHeader) strlcpy(_selectedEcuHeader, selected.ecuHeader, sizeof(_selectedEcuHeader));
    else _selectedEcuHeader[0] = '\0';
    if (uniqueCount > 1) {
      bool allHeadered = true;
      for (uint8_t i = 0; i < uniqueCount; ++i)
        allHeadered = allHeadered && parsed.frames[unique[i]].hasEcuHeader;
      _ambiguousEcuSelection = !allHeadered;
      Serial.printf("[OBD BITMAP] %u distinct ECU bitmap(s); selecting by target-PID count (%s heuristic, ties keep first response; not proof of engine ECU)\n",
                    uniqueCount, allHeadered ? "header-aware" : "headerless/ambiguous");
      if (!allHeadered)
        Serial.println("[OBD ECU] Multiple bitmap replies lack ECU headers; refusing PID polling because bitmap-to-ECU identity cannot be verified");
    } else {
      _ambiguousEcuSelection = false;
    }
    Serial.printf("[OBD RX] PID=0100 ECU=%s RAW=%s\n",
                  selected.hasEcuHeader ? selected.ecuHeader : "UNKNOWN",
                  response.c_str());
    Serial.printf("[OBD BITMAP] selected=%08lX target-support=%u/5 ECU communication confirmed\n",
                  static_cast<unsigned long>(bitmap), selectedScore);

    _supportKnown = true;
    _fallbackTried = false;
    _consecutiveTimeouts = 0;
    _nextIndex = 0;
    uint8_t supportedCount = 0;
    for (uint8_t i = 0; i < Count; ++i) {
      _supported[i] = ObdResponseParser::bitmapSupports(bitmap, Pids[i]);
      _failures[i] = 0;
      supportedCount += _supported[i] ? 1 : 0;
      Serial.printf("[OBD SUPPORT] PID=01%02X status=%s\n",
                    Pids[i], _supported[i] ? "SUPPORTED" : "UNSUPPORTED");
      if (!_supported[i]) {
        portENTER_CRITICAL(&_valueMux); _values[i].valid = false; portEXIT_CRITICAL(&_valueMux);
      }
    }
    _ecuState = !supportedCount ? EcuState::ConnectedNoTargets :
                (_ambiguousEcuSelection ? EcuState::ConnectedAmbiguous : EcuState::Connected);
    if (!supportedCount)
      Serial.println("[OBD ECU] ECU answered, but none of the five requested PIDs are supported; PID polling is stopped");
    else
      Serial.printf("[OBD ECU] ECU answered; %u of five requested PIDs supported\n", supportedCount);
    return;
  }

  if (_nextIndex >= Count) _nextIndex = 0;
  const uint8_t index = _nextIndex;
  const uint8_t pid = Pids[index];
  Frame positive{};
  Frame negative{};
  uint8_t positiveCount = 0;
  bool hasPositive = ObdResponseParser::findPositive(
      parsed, pid, 1, positive, _hasSelectedEcuHeader ? _selectedEcuHeader : nullptr, &positiveCount);
  bool unidentifiedEcuResponse = false;
  if (!_hasSelectedEcuHeader && hasPositive &&
      (positiveCount > 1 || positive.hasEcuHeader)) {
    Serial.printf("[OBD ECU] PID=01%02X has no verifiable bitmap-to-response ECU identity; positive frames=%u; refusing value\n",
                  pid, positiveCount);
    hasPositive = false;
    unidentifiedEcuResponse = true;
  }
  const bool hasNegative = ObdResponseParser::findNegative(parsed, 0x01, negative);

  // A matching positive reply wins, even if a different ECU supplied a
  // negative response in the same adapter response.
  if (timedOut || !hasPositive) {
    const bool expectedButShort = positive.service == 0x41 && positive.pid == pid;
    const bool wrongEcu = expectedButShort && _hasSelectedEcuHeader &&
                          (!positive.hasEcuHeader || strcmp(positive.ecuHeader, _selectedEcuHeader) != 0);
    const char* reason = timedOut ? "response timeout before ELM prompt" :
                         (unidentifiedEcuResponse ? "PID reply ECU identity is ambiguous" :
                          (wrongEcu ? "positive PID response did not match selected bitmap ECU" :
                          (hasNegative ? "ECU negative response" :
                           (expectedButShort ? "matching PID response has incomplete payload" : responseFailure(response)))));
    Serial.printf("[OBD RX] PID=01%02X RAW=%s\n", pid, response.c_str());
    if (hasNegative && !timedOut)
      Serial.printf("[OBD ERROR] PID=01%02X REASON=%s ECU=%s NRC=%02X RAW=%s\n",
                    pid, reason, negative.hasEcuHeader ? negative.ecuHeader : "UNKNOWN",
                    negative.nrc, negative.rawLine);
    else
      Serial.printf("[OBD ERROR] PID=01%02X REASON=%s RAW=%s\n", pid, reason, response.c_str());

    if (_failures[index] < 255) ++_failures[index];
    if (_failures[index] >= Config::PidFailureLimit) {
      portENTER_CRITICAL(&_valueMux); _values[index].valid = false; portEXIT_CRITICAL(&_valueMux);
      Serial.printf("[OBD PID] PID=01%02X value invalid after %u consecutive failures; still supported and will be retried\n",
                    pid, _failures[index]);
    }
    if (timedOut) {
      if (_consecutiveTimeouts < 255) ++_consecutiveTimeouts;
    } else {
      // NO DATA and a negative PID response are not proof that the ECU link is lost.
      _consecutiveTimeouts = 0;
    }
    const bool explicitLoss = isTransportLoss(response);
    const bool repeatedTimeout = _consecutiveTimeouts >= Config::PidFailureLimit;
    _nextIndex = static_cast<uint8_t>((index + 1) % Count);
    if (explicitLoss || repeatedTimeout) {
      Serial.printf("[OBD ECU] Communication loss detected (%s); invalidating cache and restarting discovery\n",
                    explicitLoss ? reason : "three consecutive SPP command timeouts");
      scheduleDiscoveryRetry("ECU communication loss during PID polling");
    }
    return;
  }

  if (hasNegative)
    Serial.printf("[OBD INFO] Ignoring unrelated ECU negative PID reply ECU=%s NRC=%02X; matching positive reply found\n",
                  negative.hasEcuHeader ? negative.ecuHeader : "UNKNOWN", negative.nrc);
  if (positiveCount > 1)
    Serial.printf("[OBD INFO] PID=01%02X has %u positive ECU replies; selected ECU=%s, using one byte from that ECU/first response\n",
                  pid, positiveCount, positive.hasEcuHeader ? positive.ecuHeader : "UNKNOWN");
  const uint8_t a = positive.payload[0];
  float value = 0.0f;
  if (!ObdResponseParser::decodeMode01Byte(pid, a, value)) {
    Serial.printf("[OBD ERROR] PID=01%02X unsupported decoder RAW=%s\n", pid, response.c_str());
    _nextIndex = static_cast<uint8_t>((index + 1) % Count);
    return;
  }
  _failures[index] = 0; // A success clears only this PID's streak.
  _consecutiveTimeouts = 0;
  const uint32_t updatedAt = millis();
  portENTER_CRITICAL(&_valueMux);
  _values[index].value = value; _values[index].valid = true; _values[index].updatedAt = updatedAt;
  portEXIT_CRITICAL(&_valueMux);
  Serial.printf("[OBD RX] PID=01%02X ECU=%s RAW=%s\n", pid,
                positive.hasEcuHeader ? positive.ecuHeader : "UNKNOWN", response.c_str());
  Serial.printf("[OBD VALUE] %s=%.2f %s PID=01%02X A=%u updatedAtMs=%lu\n",
                _values[index].name, value, _values[index].unit, pid, a,
                static_cast<unsigned long>(updatedAt));
  _nextIndex = static_cast<uint8_t>((index + 1) % Count);
}

void ObdManager::tick(VlinkerClient& client) {
  const bool connected = client.state() == LinkState::Connected;
  if (_wasConnected && !connected) {
    const bool continueKwpAfterResync = client.takeResyncRecovery();
    const bool preserveKwpFallback = continueKwpAfterResync && _fallbackTried;
    _supportKnown = false; _pending = false; _pendingCommand = PendingCommand::None;
    _fallbackTried = preserveKwpFallback; _usingKwp = false; _hasSelectedEcuHeader = false;
    _ambiguousEcuSelection = false;
    _selectedEcuHeader[0] = '\0'; _nextIndex = 0; _consecutiveTimeouts = 0;
    for (uint8_t i = 0; i < Count; ++i) { _supported[i] = false; _failures[i] = 0; }
    invalidateValues();
    _ecuState = EcuState::Disconnected;
    Serial.printf("[OBD ECU] Bluetooth disconnected; ECU state/cache reset%s\n",
                  preserveKwpFallback ? "; pending KWP fallback will follow SPP resynchronization" : "");
  }
  if (connected && !client.ready()) _ecuState = EcuState::AdapterInitializing;
  else if (!connected) _ecuState = EcuState::Disconnected;
  else if (!_supportKnown && _ecuState != EcuState::Failed) _ecuState = EcuState::Searching;
  _wasConnected = connected;

  const uint32_t now = millis();
  uint8_t staleIndices[Count]{};
  uint32_t staleUpdatedAt[Count]{};
  uint8_t staleCount = 0;
  portENTER_CRITICAL(&_valueMux);
  for (uint8_t i = 0; i < Count; ++i) {
    if (_values[i].valid && static_cast<uint32_t>(now - _values[i].updatedAt) > Config::StaleTimeoutMs) {
      _values[i].valid = false;
      staleIndices[staleCount] = i;
      staleUpdatedAt[staleCount++] = _values[i].updatedAt;
    }
  }
  portEXIT_CRITICAL(&_valueMux);
  for (uint8_t i = 0; i < staleCount; ++i)
    Serial.printf("[OBD STALE] PID=01%02X lastSuccessMs=%lu ageMs=%lu; display NONE\n",
                  Pids[staleIndices[i]], static_cast<unsigned long>(staleUpdatedAt[i]),
                  static_cast<unsigned long>(now - staleUpdatedAt[i]));

  String response;
  bool responseTimedOut = false;
  if (client.takeResponse(response, &responseTimedOut) && _pending) {
    const PendingCommand completed = _pendingCommand;
    _pending = false; _pendingCommand = PendingCommand::None;
    if (completed == PendingCommand::BitmapAuto) {
      if (!responseTimedOut && hasBitmapResponse(response)) consume(response);
      else failAutoAndSelectKwp(client, response);
    } else if (completed == PendingCommand::BitmapKwp) {
      if (!responseTimedOut && hasBitmapResponse(response)) consume(response);
      else {
        Serial.printf("[OBD ERROR] PID=0100 KWP discovery failed reason=%s RAW=%s\n",
                      responseTimedOut ? "timeout before ELM prompt" : responseFailure(response), response.c_str());
        scheduleDiscoveryRetry("AUTO and KWP 0100 both failed");
      }
    } else if (completed == PendingCommand::Pid) {
      consume(response, responseTimedOut);
    } else if (completed == PendingCommand::SelectKwp || completed == PendingCommand::SelectAuto) {
      const bool selectingKwp = completed == PendingCommand::SelectKwp;
      const bool accepted = protocolSelectionAccepted(response, selectingKwp, responseTimedOut);
      if (!accepted) {
        Serial.printf("[OBD PROTOCOL] %s rejected/timeout RAW=%s\n",
                      selectingKwp ? "ATSP4" : "ATSP0", response.c_str());
        scheduleDiscoveryRetry(selectingKwp ? "adapter rejected ATSP4" : "adapter rejected ATSP0");
      } else if (selectingKwp) {
        _usingKwp = true;
        Serial.printf("[OBD PROTOCOL] ATSP4 accepted RAW=%s; ECU is not yet confirmed\n", response.c_str());
        if (client.sendCommand("ATDP", 3000)) {
          _pending = true; _pendingCommand = PendingCommand::ReadProtocolKwp;
        } else scheduleDiscoveryRetry("ATDP could not be queued after ATSP4");
      } else {
        _usingKwp = false;
        Serial.printf("[OBD PROTOCOL] ATSP0 accepted RAW=%s\n", response.c_str());
        if (!requestBitmap(client, true)) {
          _nextRequest = millis() + 250;
          Serial.println("[OBD PROTOCOL] 0100 could not be queued after ATSP0; will retry");
        }
      }
    } else if (completed == PendingCommand::ReadProtocolKwp) {
      if (responseTimedOut) {
        Serial.printf("[OBD ERROR] ATDP timed out after ATSP4 RAW=%s\n", response.c_str());
        scheduleDiscoveryRetry("ATDP timed out after ATSP4");
      } else {
        const bool protocolReported = protocolSelectionAccepted(response, true, false);
        Serial.printf("[OBD PROTOCOL] ATDP after KWP fallback%s RAW=%s\n",
                      protocolReported ? " confirmed KWP" : " did not identify KWP; probing selected ATSP4 anyway",
                      response.c_str());
        if (!requestBitmap(client, false)) scheduleDiscoveryRetry("KWP 0100 could not be queued");
      }
    }
    if (_supportKnown) {
      _nextRequest = millis() + (_ecuState == EcuState::Connected ? Config::PollIntervalMs : Config::EcuRetryIntervalMs);
    }
  }

  if (!connected || !client.ready() || _pending || static_cast<int32_t>(millis() - _nextRequest) < 0) return;
  if (_ecuState == EcuState::Failed) {
    Serial.println("[OBD PROTOCOL] Retrying discovery with ATSP0 / AUTO");
    if (client.sendCommand("ATSP0", 3000)) {
      _pending = true; _pendingCommand = PendingCommand::SelectAuto;
      _nextRequest = millis() + 3000;
    } else _nextRequest = millis() + 250;
    return;
  }
  if (!_supportKnown && _fallbackTried) {
    if (client.sendCommand("ATSP4", 3000)) {
      _pending = true; _pendingCommand = PendingCommand::SelectKwp;
      _nextRequest = millis() + 3000;
      Serial.println("[OBD PROTOCOL] Retrying ATSP4 after AUTO failure");
    } else _nextRequest = millis() + 250;
    return;
  }
  if (!_supportKnown) {
    requestBitmap(client, true); // Initial adapter initialization selected ATSP0.
    return;
  }
  if (_ecuState == EcuState::ConnectedNoTargets || _ecuState == EcuState::ConnectedAmbiguous) {
    if (!requestBitmap(client, !_usingKwp)) _nextRequest = millis() + 250;
    return;
  }

  for (uint8_t tries = 0; tries < Count; ++tries) {
    const uint8_t i = _nextIndex;
    if (!_supported[i]) { _nextIndex = static_cast<uint8_t>((_nextIndex + 1) % Count); continue; }
    char command[5]; snprintf(command, sizeof(command), "01%02X", Pids[i]);
    if (client.sendCommand(command, Config::PidResponseTimeoutMs)) {
      _pending = true; _pendingCommand = PendingCommand::Pid;
      _nextRequest = millis() + Config::PidResponseTimeoutMs;
      Serial.printf("[OBD TX] PID=01%02X\n", Pids[i]);
    } else _nextRequest = millis() + 250;
    return;
  }
  _nextRequest = millis() + Config::EcuRetryIntervalMs;
}

void ObdManager::snapshot(ObdValue* destination) const {
  portENTER_CRITICAL(&_valueMux);
  memcpy(destination, _values, sizeof(_values));
  portEXIT_CRITICAL(&_valueMux);
}
