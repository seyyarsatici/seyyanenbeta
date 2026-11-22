#include "ecu_registry.h"
#include <stdio.h>
#include <string.h>

namespace EcuRegistry {
void Registry::clear() { *this = Registry{}; }

int8_t Registry::find(const ObdResponseParser::Frame& frame) const {
  if (!frame.hasEcuHeader) {
    for (uint8_t i = 0; i < _count; ++i)
      if (!_records[i].hasIdentity && _records[i].protocol == frame.protocol) return static_cast<int8_t>(i);
    return -1;
  }
  for (uint8_t i = 0; i < _count; ++i) {
    const Record& record = _records[i];
    if (record.protocol == frame.protocol && record.hasIdentity &&
        strcmp(record.responseIdentity, frame.ecuHeader) == 0) return static_cast<int8_t>(i);
  }
  return -1;
}

int8_t Registry::ensure(const ObdResponseParser::Frame& frame) {
  const int8_t existing = find(frame);
  if (existing >= 0) return existing;
  if (_count >= Capacity) return -1;
  Record& record = _records[_count];
  record.protocol = frame.protocol;
  record.hasIdentity = frame.hasEcuHeader;
  record.targetAddress = frame.targetAddress;
  record.hasTargetAddress = frame.hasTargetAddress;
  if (frame.hasEcuHeader) {
    strncpy(record.responseIdentity, frame.ecuHeader, sizeof(record.responseIdentity) - 1);
    deriveCanRequest(record);
  }
  return static_cast<int8_t>(_count++);
}

void Registry::deriveCanRequest(Record& record) {
  // Only standardized ISO 15765-4 OBD response forms are mapped. KWP
  // response addresses are never converted into a request address here.
  if (record.protocol != ObdResponseParser::Protocol::Can) return;
  unsigned long id = 0;
  if (strlen(record.responseIdentity) == 3 && sscanf(record.responseIdentity, "%lx", &id) == 1 &&
      id >= 0x7E8 && id <= 0x7EF) {
    snprintf(record.requestIdentity, sizeof(record.requestIdentity), "%03lX", id - 8);
    record.hasRequestIdentity = true;
  } else if (strlen(record.responseIdentity) == 8 &&
             (strncmp(record.responseIdentity, "18DA", 4) == 0 ||
              strncmp(record.responseIdentity, "18DB", 4) == 0) && sscanf(record.responseIdentity, "%lx", &id) == 1) {
    snprintf(record.requestIdentity, sizeof(record.requestIdentity), "18DA%02lXF1", id & 0xFFUL);
    record.hasRequestIdentity = true;
  }
}

bool Registry::addBitmap(const ObdResponseParser::Frame& frame, uint32_t now) {
  const int8_t index = ensure(frame);
  if (index < 0) return false;
  Record& record = _records[index];
  const uint32_t bitmap = ObdResponseParser::bitmapValue(frame);
  if (!record.bitmapKnown) { record.bitmap = bitmap; record.bitmapKnown = true; }
  else if (record.bitmap != bitmap) record.bitmapConflict = true;
  record.rpmSupported = ObdResponseParser::bitmapSupports(record.bitmap, 0x0C);
  record.lastSuccess = now;
  return true;
}

bool Registry::addResponse(const ObdResponseParser::Frame& frame, uint32_t now) {
  const int8_t index = find(frame);
  if (index < 0) return false;
  Record& record = _records[index];
  record.lastSuccess = now;
  if (frame.service == 0x41 && frame.pid == 0x0C && frame.payloadLength >= 2) {
    record.rpmResponded = true;
    record.verificationSignal = true;
    record.role = Role::ProbableEngine;
  }
  return true;
}

int8_t Registry::uniqueCandidate() const {
  if (_count != 1 || _anonymousReplies > 1 || _records[0].bitmapConflict) return -1;
  return 0;
}

int8_t Registry::uniqueRpmResponder() const {
  int8_t selected = -1;
  for (uint8_t i = 0; i < _count; ++i) {
    if (!_records[i].rpmResponded || !_records[i].rpmSupported || _records[i].bitmapConflict) continue;
    if (selected >= 0) return -1;
    selected = static_cast<int8_t>(i);
  }
  if (_anonymousReplies > 1) return -1;
  return selected;
}

bool Registry::ambiguous() const {
  if (_anonymousReplies > 1) return true;
  for (uint8_t i = 0; i < _count; ++i) if (_records[i].bitmapConflict) return true;
  return _count > 1 && uniqueRpmResponder() < 0;
}
}
