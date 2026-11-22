#include "obd_manager.h"
#include "config.h"
#include "obd_response_parser.h"
#include <string.h>

constexpr uint8_t ObdManager::Pids[ObdManager::Count];

namespace {
using ObdResponseParser::Frame;
using ObdResponseParser::Result;
using ObdResponseParser::Protocol;

// Per the target-specific configurable preference: KWP fast, KWP slow,
// ISO9141, then adapter AUTO. These are candidate preferences, not claims
// about the protocol used by the target vehicle.
constexpr uint8_t CandidateCount = Config::ProtocolOrderCount;

Protocol protocolFor(uint8_t protocol) {
  if (protocol == 5 || protocol == 4) return Protocol::KwP;
  if (protocol == 3) return Protocol::Iso9141;
  return Protocol::Unknown;
}

const char* protocolName(uint8_t protocol) {
  switch (protocol) {
    case 5: return "ISO 14230-4 KWP FAST (ATTP5)";
    case 4: return "ISO 14230-4 KWP 5-BAUD (ATTP4)";
    case 3: return "ISO 9141-2 5-BAUD (ATTP3)";
    default: return "AUTO (ATTP0)";
  }
}

const char* bitmapFailureStatus(const String& response) {
  String upper = response; upper.toUpperCase();
  if (upper.indexOf("BUS INIT: OK") >= 0) return "adapter reports bus initialization; no positive ECU bitmap yet";
  if (upper.indexOf("BUS INIT: ERROR") >= 0) return "bus initialization failed";
  if (upper.indexOf("SEARCHING") >= 0) return "protocol search ended without positive bitmap";
  if (upper.indexOf("NO DATA") >= 0) return "adapter returned NO DATA";
  if (upper.indexOf("UNABLE TO CONNECT") >= 0) return "adapter could not connect to ECU";
  if (upper.indexOf('?') >= 0) return "adapter rejected command";
  return "no valid positive 4100 frame";
}

const char* parserErrorName(ObdResponseParser::ParseError error) {
  switch (error) {
    case ObdResponseParser::ParseError::InvalidLength: return "invalid frame length";
    case ObdResponseParser::ParseError::InvalidChecksum: return "invalid ISO 14230 checksum";
    case ObdResponseParser::ParseError::UnsupportedFrame: return "unsupported frame form";
    case ObdResponseParser::ParseError::FrameCapacity: return "frame capacity exceeded";
    case ObdResponseParser::ParseError::LineTooLong: return "response line exceeds parser limit";
    default: return "none";
  }
}

bool protocolDescriptionValid(const String& response) {
  String upper = response; upper.toUpperCase(); upper.trim();
  if (!upper.length() || upper.indexOf('?') >= 0 || upper.indexOf("ERROR") >= 0 ||
      upper.indexOf("NO DATA") >= 0 || upper.indexOf("SEARCHING") >= 0 ||
      upper.indexOf("BUS INIT") >= 0 || upper.indexOf("UNABLE TO CONNECT") >= 0) return false;
  return upper.indexOf("AUTO") >= 0 || upper.indexOf("ISO") >= 0 || upper.indexOf("KWP") >= 0 ||
         upper.indexOf("CAN") >= 0 || upper.indexOf("J1850") >= 0 || upper.indexOf("SAE") >= 0 ||
         upper.indexOf("PROTOCOL") >= 0 || upper.indexOf("USER") >= 0;
}

bool protocolNumberValid(const String& response) {
  String upper = response; upper.toUpperCase(); upper.trim();
  if (!upper.length() || upper.indexOf('?') >= 0 || upper.indexOf("ERROR") >= 0 ||
      upper.indexOf("NO DATA") >= 0 || upper.indexOf("SEARCHING") >= 0 || upper.indexOf("BUS INIT") >= 0) return false;
  const char* value = upper.c_str();
  if (*value == 'A') ++value; // ELM auto-selected protocol marker.
  return value[0] >= '0' && value[0] <= '9' && value[1] == '\0';
}

bool isBitmap(ObdManager::PendingCommand command) {
  return command == ObdManager::PendingCommand::BitmapKwpFast ||
         command == ObdManager::PendingCommand::BitmapKwpSlow ||
         command == ObdManager::PendingCommand::BitmapIso9141 ||
         command == ObdManager::PendingCommand::BitmapAuto;
}

uint8_t protocolForCommand(ObdManager::PendingCommand command) {
  switch (command) {
    case ObdManager::PendingCommand::TryKwpFast:
    case ObdManager::PendingCommand::SetKwpFast:
    case ObdManager::PendingCommand::BitmapKwpFast: return 5;
    case ObdManager::PendingCommand::TryKwpSlow:
    case ObdManager::PendingCommand::SetKwpSlow:
    case ObdManager::PendingCommand::BitmapKwpSlow: return 4;
    case ObdManager::PendingCommand::TryIso9141:
    case ObdManager::PendingCommand::SetIso9141:
    case ObdManager::PendingCommand::BitmapIso9141: return 3;
    default: return 0;
  }
}

ObdManager::PendingCommand tryCommand(uint8_t protocol) {
  switch (protocol) {
    case 5: return ObdManager::PendingCommand::TryKwpFast;
    case 4: return ObdManager::PendingCommand::TryKwpSlow;
    case 3: return ObdManager::PendingCommand::TryIso9141;
    default: return ObdManager::PendingCommand::TryAuto;
  }
}

ObdManager::PendingCommand setCommand(uint8_t protocol) {
  switch (protocol) {
    case 5: return ObdManager::PendingCommand::SetKwpFast;
    case 4: return ObdManager::PendingCommand::SetKwpSlow;
    case 3: return ObdManager::PendingCommand::SetIso9141;
    default: return ObdManager::PendingCommand::SetAuto;
  }
}

ObdManager::PendingCommand bitmapCommand(uint8_t protocol) {
  switch (protocol) {
    case 5: return ObdManager::PendingCommand::BitmapKwpFast;
    case 4: return ObdManager::PendingCommand::BitmapKwpSlow;
    case 3: return ObdManager::PendingCommand::BitmapIso9141;
    default: return ObdManager::PendingCommand::BitmapAuto;
  }
}
}

void ObdManager::invalidateValues() {
  portENTER_CRITICAL(&_valueMux);
  for (uint8_t i = 0; i < Count; ++i) _values[i].valid = false;
  portEXIT_CRITICAL(&_valueMux);
}

void ObdManager::resetDiscovery(bool clearRegistry) {
  _pending = false;
  _pendingCommand = PendingCommand::None;
  _queued = QueuedCommand{};
  _supportKnown = false;
  _hasSelectedEcuHeader = false;
  _selectedEcuHeader[0] = '\0';
  _protocolDescription[0] = _protocolNumber[0] = '\0';
  _candidateIndex = _nextIndex = _consecutiveTimeouts = 0;
  for (uint8_t i = 0; i < Count; ++i) { _supported[i] = false; _failures[i] = 0; }
  if (clearRegistry) _registry.clear();
  invalidateValues();
}

void ObdManager::scheduleDiscoveryRetry(const char* reason) {
  resetDiscovery(true);
  _ecuState = EcuState::Failed;
  _nextRequest = millis() + Config::EcuRetryIntervalMs;
  Serial.printf("[OBD DISCOVERY] All protocol work stopped; retry in %lu ms: %s\n",
                static_cast<unsigned long>(Config::EcuRetryIntervalMs), reason);
}

bool ObdManager::queueCommand(VlinkerClient& client, const char* text,
                              PendingCommand owner, uint32_t timeout) {
  if (_pending) return false;
  if (client.sendCommand(text, timeout)) {
    _pending = true;
    _pendingCommand = owner;
    _nextRequest = millis() + timeout;
    Serial.printf("[OBD TX] %s owner=%u timeout=%lu ms\n", text,
                  static_cast<unsigned>(owner), static_cast<unsigned long>(timeout));
    return true;
  }
  _queued.owner = owner;
  strlcpy(_queued.text, text, sizeof(_queued.text));
  _queued.timeout = timeout;
  _queued.active = true;
  _nextRequest = millis() + 250;
  Serial.printf("[OBD QUEUE] %s owner=%u deferred until SPP transaction is synchronized\n",
                text, static_cast<unsigned>(owner));
  return false;
}

void ObdManager::pumpQueued(VlinkerClient& client) {
  if (!_queued.active || _pending) return;
  if (client.sendCommand(_queued.text, _queued.timeout)) {
    _pending = true;
    _pendingCommand = _queued.owner;
    _nextRequest = millis() + _queued.timeout;
    Serial.printf("[OBD TX] %s owner=%u (deferred command sent)\n",
                  _queued.text, static_cast<unsigned>(_pendingCommand));
    _queued = QueuedCommand{};
  }
}

void ObdManager::beginCandidate(VlinkerClient& client) {
  if (_candidateIndex >= CandidateCount) {
    scheduleDiscoveryRetry("all configured protocol candidates failed");
    return;
  }
  const uint8_t protocol = Config::ProtocolOrder[_candidateIndex];
  _registry.clear();
  _ecuState = EcuState::Searching;
  char command[8]; snprintf(command, sizeof(command), "ATTP%u", protocol);
  const PendingCommand owner = tryCommand(protocol);
  Serial.printf("[OBD DISCOVERY] candidate=%u/%u protocol=%s\n",
                static_cast<unsigned>(_candidateIndex + 1), static_cast<unsigned>(CandidateCount),
                protocolName(protocol));
  queueCommand(client, command, owner, 4000);
}

void ObdManager::tryNextCandidate(VlinkerClient& client, const char* reason) {
  Serial.printf("[OBD DISCOVERY] candidate %u failed: %s\n",
                static_cast<unsigned>(_candidateIndex + 1), reason);
  ++_candidateIndex;
  if (_candidateIndex >= CandidateCount) {
    scheduleDiscoveryRetry("KWP fast, KWP 5-baud, ISO9141 and AUTO did not produce a valid 0100 response");
    return;
  }
  _supportKnown = false;
  beginCandidate(client);
}

void ObdManager::startSelectedProtocol(VlinkerClient& client) {
  queueCommand(client, "ATDP", PendingCommand::ReadProtocolDescription, 3000);
}

void ObdManager::processBitmap(const String& response, VlinkerClient& client) {
  Result parsed;
  const uint8_t protocolId = Config::ProtocolOrder[_candidateIndex];
  const Protocol hint = protocolFor(protocolId);
  ObdResponseParser::parse(response.c_str(), parsed, hint);
  if (parsed.overflow) {
    Serial.printf("[OBD PARSER] 0100 frame capacity exceeded; refusing partial selection RAW=%s\n", response.c_str());
    tryNextCandidate(client, "bitmap response exceeded parser capacity");
    return;
  }
  if (parsed.error != ObdResponseParser::ParseError::None) {
    Serial.printf("[OBD PARSER] 0100 response contained rejected frame (%s); refusing partial ECU selection RAW=%s\n",
                  parserErrorName(parsed.error), response.c_str());
    tryNextCandidate(client, parserErrorName(parsed.error));
    return;
  }
  uint8_t accepted = 0;
  for (uint8_t i = 0; i < parsed.count; ++i) {
    const Frame& frame = parsed.frames[i];
    if (frame.negative || frame.service != 0x41 || frame.pid != 0x00 || frame.payloadLength < 4) continue;
    if (!frame.hasEcuHeader) _registry.noteHeaderlessReply();
    if (_registry.addBitmap(frame, millis())) {
      ++accepted;
      Serial.printf("[OBD ECU] protocol=%s identity=%s bitmap=%08lX RPM=%s\n",
                    protocolName(protocolId), frame.hasEcuHeader ? frame.ecuHeader : "UNKNOWN",
                    static_cast<unsigned long>(ObdResponseParser::bitmapValue(frame)),
                    ObdResponseParser::bitmapSupports(ObdResponseParser::bitmapValue(frame), 0x0C) ? "SUPPORTED" : "NO");
    }
  }
  if (!accepted || !_registry.count()) {
    Frame negative{};
    if (ObdResponseParser::findNegative(parsed, 0x01, negative))
      Serial.printf("[OBD NRC] PID=0100 ECU=%s service=01 NRC=%02X RAW=%s\n",
                    negative.hasEcuHeader ? negative.ecuHeader : "UNKNOWN-SINGLE", negative.nrc, negative.rawLine);
    Serial.printf("[OBD BITMAP] REJECT reason=%s parser=%s RAW=%s\n",
                  bitmapFailureStatus(response), parserErrorName(parsed.error),
                  response.length() ? response.c_str() : "<empty>");
    tryNextCandidate(client, response.length() ? parserErrorName(parsed.error) : "0100 response timeout/empty");
    return;
  }
  _supportKnown = true;
  _consecutiveTimeouts = 0;
  Serial.printf("[OBD PROTOCOL] candidate=%s ATDP=%s ATDPN=%s; positive 0100 confirms ECU communication\n",
                protocolName(protocolId), _protocolDescription, _protocolNumber);

  if (_registry.ambiguous()) {
    bool rpmPossible = false, bitmapConflict = false;
    for (uint8_t i = 0; i < _registry.count(); ++i) {
      rpmPossible |= _registry.at(i).rpmSupported;
      bitmapConflict |= _registry.at(i).bitmapConflict;
    }
    if (rpmPossible && !bitmapConflict && _registry.anonymousReplies() <= 1) {
      Serial.println("[OBD ECU] Multiple identities remain separate; issuing one read-only 010C RPM verification probe");
      queueCommand(client, "010C", PendingCommand::VerifyRpm, Config::PidResponseTimeoutMs);
    } else {
      _ecuState = EcuState::ConnectedAmbiguous;
      Serial.println("[OBD ECU] Multiple ECU identities/replies cannot be tied to RPM evidence; refusing target PID polling");
    }
    _nextRequest = millis() + Config::EcuRetryIntervalMs;
    return;
  }
  const int8_t candidate = _registry.uniqueCandidate();
  if (candidate < 0) {
    _ecuState = EcuState::ConnectedAmbiguous;
    Serial.println("[OBD ECU] ECU identity/bitmap is conflicting or headerless-multiple; refusing target PID polling");
    _nextRequest = millis() + Config::EcuRetryIntervalMs;
    return;
  }
  const EcuRegistry::Record& record = _registry.at(static_cast<uint8_t>(candidate));
  if (record.rpmSupported) {
    Serial.printf("[OBD ECU] sole 0100 candidate supports 010C; verifying its response identity before target polling (%s)\n",
                  record.hasIdentity ? record.responseIdentity : "headerless single response");
    queueCommand(client, "010C", PendingCommand::VerifyRpm, Config::PidResponseTimeoutMs);
    _nextRequest = millis() + Config::PidResponseTimeoutMs;
    return;
  }
  Serial.println("[OBD ECU] Single 0100 identity; PID 010C unsupported, using sole candidate without fabricating RPM evidence");
  selectRecord(static_cast<uint8_t>(candidate), client);
}

void ObdManager::processRpm(const String& response, VlinkerClient& client, bool timedOut) {
  Result parsed;
  const uint8_t protocolId = Config::ProtocolOrder[_candidateIndex];
  ObdResponseParser::parse(response.c_str(), parsed, protocolFor(protocolId));
  uint8_t matched = 0;
  for (uint8_t i = 0; i < parsed.count; ++i) {
    Frame& frame = parsed.frames[i];
    if (!frame.negative && frame.service == 0x41 && frame.pid == 0x0C && frame.payloadLength >= 2) {
      if (_registry.addResponse(frame, millis())) {
        ++matched;
        const uint16_t rawRpm = static_cast<uint16_t>((frame.payload[0] << 8) | frame.payload[1]);
        Serial.printf("[OBD ECU VERIFY] PID=010C ECU=%s A=%u B=%u rpm=%.2f RAW=%s\n",
                      frame.hasEcuHeader ? frame.ecuHeader : "UNKNOWN", frame.payload[0], frame.payload[1],
                      rawRpm / 4.0f, frame.rawLine);
      }
    }
  }
  const int8_t selected = _registry.uniqueRpmResponder();
  if (!timedOut && parsed.error == ObdResponseParser::ParseError::None && matched && selected >= 0) {
    if (_registry.count() > 1)
      Serial.println("[OBD ECU] one distinct ECU answered 010C; this is engine-role evidence, not absolute proof");
    selectRecord(static_cast<uint8_t>(selected), client);
    return;
  }
  _ecuState = EcuState::ConnectedAmbiguous;
  Serial.printf("[OBD ECU VERIFY] 010C did not uniquely verify an ECU; matched=%u timeout=%s RAW=%s; target PID polling stopped\n",
                matched, timedOut ? "yes" : "no", response.c_str());
  _nextRequest = millis() + Config::EcuRetryIntervalMs;
}

void ObdManager::selectRecord(uint8_t index, VlinkerClient&) {
  if (index >= _registry.count()) { _ecuState = EcuState::ConnectedAmbiguous; return; }
  const EcuRegistry::Record& record = _registry.at(index);
  if (record.bitmapConflict || _registry.anonymousReplies() > 1) {
    _ecuState = EcuState::ConnectedAmbiguous;
    Serial.println("[OBD ECU] refusing selection because bitmap identity evidence conflicts");
    return;
  }
  _hasSelectedEcuHeader = record.hasIdentity;
  strlcpy(_selectedEcuHeader, record.responseIdentity, sizeof(_selectedEcuHeader));
  const uint32_t bitmap = record.bitmap;
  uint8_t supportedCount = 0;
  for (uint8_t i = 0; i < Count; ++i) {
    _supported[i] = ObdResponseParser::bitmapSupports(bitmap, Pids[i]);
    _failures[i] = 0;
    supportedCount += _supported[i] ? 1 : 0;
    Serial.printf("[OBD SUPPORT] ECU=%s PID=01%02X status=%s\n",
                  record.hasIdentity ? record.responseIdentity : "UNKNOWN-SINGLE",
                  Pids[i], _supported[i] ? "SUPPORTED" : "UNSUPPORTED");
    if (!_supported[i]) {
      portENTER_CRITICAL(&_valueMux); _values[i].valid = false; portEXIT_CRITICAL(&_valueMux);
    }
  }
  _supportKnown = true;
  _nextIndex = 0;
  _consecutiveTimeouts = 0;
  _ecuState = supportedCount ? EcuState::Connected : EcuState::ConnectedNoTargets;
  Serial.printf("[OBD ECU SELECT] identity=%s request-identity=%s protocol=%s targets=%u/5 verified010C=%s; bitmap is not merged across ECUs\n",
                record.hasIdentity ? record.responseIdentity : "UNKNOWN-SINGLE",
                record.hasRequestIdentity ? record.requestIdentity : "NOT DERIVED",
                protocolName(Config::ProtocolOrder[_candidateIndex]), supportedCount,
                record.verificationSignal ? "yes" : "no");
  _nextRequest = millis() + (supportedCount ? Config::PollIntervalMs : Config::EcuRetryIntervalMs);
}

void ObdManager::consumePid(const String& response, bool timedOut) {
  Result parsed;
  const Protocol protocol = protocolFor(Config::ProtocolOrder[_candidateIndex]);
  ObdResponseParser::parse(response.c_str(), parsed, protocol);
  if (_nextIndex >= Count) _nextIndex = 0;
  const uint8_t index = _nextIndex;
  const uint8_t pid = Pids[index];
  Frame positive{}, negative{};
  uint8_t positiveCount = 0;
  bool hasPositive = ObdResponseParser::findPositive(parsed, pid, 1, positive,
      _hasSelectedEcuHeader ? _selectedEcuHeader : nullptr, &positiveCount);
  bool unknownIdentity = false;
  if (!_hasSelectedEcuHeader && hasPositive && (positive.hasEcuHeader || positiveCount > 1)) {
    hasPositive = false;
    unknownIdentity = true;
  }
  const bool hasNegative = ObdResponseParser::findNegative(parsed, 0x01, negative);
  if (timedOut || !hasPositive) {
    const char* reason = timedOut ? "SPP prompt timeout" : unknownIdentity ? "PID response identity is not attributable to selected ECU" :
                         parsed.error != ObdResponseParser::ParseError::None ? parserErrorName(parsed.error) :
                         hasNegative ? "negative Mode 01 response" : "no matching positive 41/PID payload";
    Serial.printf("[OBD ERROR] PID=01%02X REASON=%s RAW=%s\n", pid, reason, response.c_str());
    if (_failures[index] < 255) ++_failures[index];
    if (_failures[index] >= Config::PidFailureLimit) {
      portENTER_CRITICAL(&_valueMux); _values[index].valid = false; portEXIT_CRITICAL(&_valueMux);
      Serial.printf("[OBD PID] PID=01%02X invalid after %u failures; remains scheduled\n", pid, _failures[index]);
    }
    if (timedOut) { if (_consecutiveTimeouts < 255) ++_consecutiveTimeouts; }
    else _consecutiveTimeouts = 0;
    if (hasNegative) Serial.printf("[OBD NRC] ECU=%s service=01 NRC=%02X\n", negative.hasEcuHeader ? negative.ecuHeader : "UNKNOWN", negative.nrc);
    _nextIndex = static_cast<uint8_t>((index + 1) % Count);
    if (_consecutiveTimeouts >= Config::PidFailureLimit || response.indexOf("UNABLE TO CONNECT") >= 0 || response.indexOf("BUS INIT: ERROR") >= 0) {
      Serial.println("[OBD ECU] transport/ECU loss confirmed; restarting full protocol discovery");
      scheduleDiscoveryRetry("ECU response link lost during PID polling");
    }
    return;
  }
  if (hasNegative)
    Serial.printf("[OBD INFO] PID=01%02X ignored negative frame because selected ECU returned a positive reply ECU=%s NRC=%02X\n",
                  pid, negative.hasEcuHeader ? negative.ecuHeader : "UNKNOWN", negative.nrc);
  const uint8_t raw = positive.payload[0];
  float value = 0;
  if (!ObdResponseParser::decodeMode01Byte(pid, raw, value)) {
    Serial.printf("[OBD ERROR] PID=01%02X no decoder RAW=%s\n", pid, response.c_str());
    _nextIndex = static_cast<uint8_t>((index + 1) % Count);
    return;
  }
  _failures[index] = 0;
  _consecutiveTimeouts = 0;
  const uint32_t updatedAt = millis();
  portENTER_CRITICAL(&_valueMux);
  _values[index].value = value; _values[index].valid = true; _values[index].updatedAt = updatedAt;
  portEXIT_CRITICAL(&_valueMux);
  Serial.printf("[OBD VALUE] ECU=%s PID=01%02X %s=%.2f %s A=%u updatedAtMs=%lu RAW=%s\n",
                positive.hasEcuHeader ? positive.ecuHeader : "UNKNOWN-SINGLE", pid,
                _values[index].name, value, _values[index].unit, raw,
                static_cast<unsigned long>(updatedAt), response.c_str());
  _nextIndex = static_cast<uint8_t>((index + 1) % Count);
}

void ObdManager::processResponse(const String& response, bool timedOut, VlinkerClient& client) {
  const PendingCommand completed = _pendingCommand;
  _pending = false;
  _pendingCommand = PendingCommand::None;
  if (completed == PendingCommand::TryKwpFast || completed == PendingCommand::TryKwpSlow ||
      completed == PendingCommand::TryIso9141 || completed == PendingCommand::TryAuto) {
    String upper = response; upper.toUpperCase(); upper.trim();
    const uint8_t protocol = protocolForCommand(completed);
    if (timedOut) { tryNextCandidate(client, "ATTP selection timeout"); return; }
    if (upper.indexOf('?') >= 0 || upper.indexOf("NOT SUPPORTED") >= 0 || upper.indexOf("ERROR") >= 0) {
      char command[8]; snprintf(command, sizeof(command), "ATSP%u", protocol);
      Serial.printf("[OBD PROTOCOL] ATTP%u unsupported/rejected; trying compatibility fallback %s RAW=%s\n",
                    protocol, command, response.c_str());
      queueCommand(client, command, setCommand(protocol), 4000);
    } else if (upper.indexOf("BUS INIT") < 0 && upper.indexOf("SEARCHING") < 0 &&
               (upper.indexOf("OK") >= 0 || upper.indexOf("PROTOCOL") >= 0 ||
                (upper.length() == 1 && upper[0] == static_cast<char>('0' + protocol)))) {
      Serial.printf("[OBD PROTOCOL] ATTP%u accepted RAW=%s\n", protocol, response.c_str());
      startSelectedProtocol(client);
    } else {
      tryNextCandidate(client, "ATTP response did not confirm protocol selection");
    }
    return;
  }
  if (completed == PendingCommand::SetKwpFast || completed == PendingCommand::SetKwpSlow ||
      completed == PendingCommand::SetIso9141 || completed == PendingCommand::SetAuto) {
    String upper = response; upper.toUpperCase(); upper.trim();
    if (!timedOut && upper.indexOf("OK") >= 0) {
      Serial.printf("[OBD PROTOCOL] ATSP%u compatibility fallback accepted; ECU remains unverified RAW=%s\n",
                    protocolForCommand(completed), response.c_str());
      startSelectedProtocol(client);
    } else tryNextCandidate(client, "ATSP compatibility fallback was rejected/timed out");
    return;
  }
  if (completed == PendingCommand::ReadProtocolDescription) {
    if (timedOut || !protocolDescriptionValid(response)) {
      tryNextCandidate(client, "ATDP protocol description unavailable"); return;
    }
    strlcpy(_protocolDescription, response.c_str(), sizeof(_protocolDescription));
    Serial.printf("[OBD PROTOCOL] ATDP RAW=%s\n", response.c_str());
    queueCommand(client, "ATDPN", PendingCommand::ReadProtocolNumber, 3000);
    return;
  }
  if (completed == PendingCommand::ReadProtocolNumber) {
    if (timedOut || !protocolNumberValid(response)) {
      tryNextCandidate(client, "ATDPN selected protocol number unavailable"); return;
    }
    strlcpy(_protocolNumber, response.c_str(), sizeof(_protocolNumber));
    Serial.printf("[OBD PROTOCOL] ATDPN RAW=%s; candidate=%s\n", response.c_str(),
                  protocolName(Config::ProtocolOrder[_candidateIndex]));
    char command[8]; snprintf(command, sizeof(command), "0100");
    queueCommand(client, command, bitmapCommand(Config::ProtocolOrder[_candidateIndex]), Config::EcuResponseTimeoutMs);
    return;
  }
  if (isBitmap(completed)) {
    if (timedOut) {
      Serial.printf("[OBD ERROR] PID=0100 REASON=timeout during %s RAW=%s\n",
                    protocolName(protocolForCommand(completed)), response.c_str());
      tryNextCandidate(client, "0100 probe timed out");
    } else processBitmap(response, client);
    return;
  }
  if (completed == PendingCommand::VerifyRpm) { processRpm(response, client, timedOut); return; }
  if (completed == PendingCommand::Pid) {
    consumePid(response, timedOut);
    if (_ecuState == EcuState::Connected) _nextRequest = millis() + Config::PollIntervalMs;
    return;
  }
}

void ObdManager::tick(VlinkerClient& client) {
  const bool connected = client.state() == LinkState::Connected;
  if (_wasConnected && !connected) {
    const bool resync = client.takeResyncRecovery();
    resetDiscovery(true);
    _ecuState = EcuState::Disconnected;
    _nextRequest = millis();
    Serial.printf("[OBD ECU] Bluetooth lost; registry/cache reset; discovery restarts at configured first candidate%s\n",
                  resync ? " after SPP resynchronization" : "");
  }
  if (!connected) _ecuState = EcuState::Disconnected;
  else if (!client.ready()) _ecuState = EcuState::AdapterInitializing;
  else if (_ecuState == EcuState::Disconnected || _ecuState == EcuState::AdapterInitializing)
    _ecuState = EcuState::Searching;
  _wasConnected = connected;

  const uint32_t now = millis();
  uint8_t staleIndices[Count]{}; uint32_t staleUpdatedAt[Count]{}; uint8_t staleCount = 0;
  portENTER_CRITICAL(&_valueMux);
  for (uint8_t i = 0; i < Count; ++i) if (_values[i].valid && static_cast<uint32_t>(now - _values[i].updatedAt) > Config::StaleTimeoutMs) {
    _values[i].valid = false; staleIndices[staleCount] = i; staleUpdatedAt[staleCount++] = _values[i].updatedAt;
  }
  portEXIT_CRITICAL(&_valueMux);
  for (uint8_t i = 0; i < staleCount; ++i)
    Serial.printf("[OBD STALE] PID=01%02X lastSuccessMs=%lu ageMs=%lu; display NONE\n", Pids[staleIndices[i]],
                  static_cast<unsigned long>(staleUpdatedAt[i]), static_cast<unsigned long>(now - staleUpdatedAt[i]));

  String response; bool timedOut = false;
  if (client.takeResponse(response, &timedOut) && _pending) processResponse(response, timedOut, client);
  if (!connected || !client.ready() || _pending) return;
  if (_queued.active) { pumpQueued(client); return; }
  if (static_cast<int32_t>(millis() - _nextRequest) < 0) return;

  if (_ecuState == EcuState::Failed || _ecuState == EcuState::Disconnected || _ecuState == EcuState::AdapterInitializing) {
    _candidateIndex = 0;
    beginCandidate(client);
    return;
  }
  if (_ecuState == EcuState::ConnectedAmbiguous || _ecuState == EcuState::ConnectedNoTargets) {
    _candidateIndex = 0;
    _supportKnown = false;
    beginCandidate(client);
    return;
  }
  if (!_supportKnown) { _candidateIndex = 0; beginCandidate(client); return; }

  for (uint8_t tries = 0; tries < Count; ++tries) {
    const uint8_t index = _nextIndex;
    if (!_supported[index]) { _nextIndex = static_cast<uint8_t>((index + 1) % Count); continue; }
    char command[8]; snprintf(command, sizeof(command), "01%02X", Pids[index]);
    queueCommand(client, command, PendingCommand::Pid, Config::PidResponseTimeoutMs);
    return;
  }
  _nextRequest = millis() + Config::EcuRetryIntervalMs;
}

void ObdManager::snapshot(ObdValue* destination) const {
  portENTER_CRITICAL(&_valueMux);
  memcpy(destination, _values, sizeof(_values));
  portEXIT_CRITICAL(&_valueMux);
}
