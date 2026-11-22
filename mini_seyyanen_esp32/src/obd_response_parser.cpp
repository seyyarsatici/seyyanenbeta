#include "obd_response_parser.h"
#include <ctype.h>
#include <stdio.h>
#include <string.h>

namespace ObdResponseParser {
namespace {
constexpr size_t MaxLine = 128;
constexpr size_t MaxHex = 112;

bool delimiter(char c) {
  return c == ' ' || c == '\t' || c == ':' || c == ',' || c == '-';
}

bool allHex(const char* text, size_t length) {
  if (!length) return false;
  for (size_t i = 0; i < length; ++i)
    if (!isxdigit(static_cast<unsigned char>(text[i]))) return false;
  return true;
}

uint8_t hexByte(const char* twoChars) {
  auto nibble = [](char c) -> uint8_t {
    c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
    return static_cast<uint8_t>(c <= '9' ? c - '0' : c - 'A' + 10);
  };
  return static_cast<uint8_t>((nibble(twoChars[0]) << 4) | nibble(twoChars[1]));
}

void storePdu(const uint8_t* bytes, size_t length, const char* rawLine, size_t rawLength,
              const char* header, bool hasHeader, Protocol protocol,
              uint8_t target, uint8_t source, ChecksumStatus checksum, Result& result) {
  size_t cursor = 0;
  while (cursor < length && !result.overflow) {
    const uint8_t service = bytes[cursor];
    if (service == 0x41 && cursor + 1 < length) {
      const uint8_t pid = bytes[cursor + 1];
      const uint8_t expected = pid == 0x00 ? 4 : (pid == 0x0C ? 2 : 1);
      const size_t available = length - (cursor + 2);
      const uint8_t payloadLength = static_cast<uint8_t>(available < expected ? available : expected);
      if (result.count >= MaxFrames) { result.overflow = true; result.error = ParseError::FrameCapacity; return; }
      Frame& frame = result.frames[result.count++];
      const size_t copyLength = rawLength < sizeof(frame.rawLine) - 1 ? rawLength : sizeof(frame.rawLine) - 1;
      memcpy(frame.rawLine, rawLine, copyLength);
      frame.rawLine[copyLength] = '\0';
      frame.hasEcuHeader = hasHeader;
      if (hasHeader) strncpy(frame.ecuHeader, header, sizeof(frame.ecuHeader) - 1);
      frame.protocol = protocol;
      frame.targetAddress = target; frame.sourceAddress = source;
      frame.hasTargetAddress = hasHeader && (protocol == Protocol::KwP || protocol == Protocol::Iso9141);
      frame.hasSourceAddress = frame.hasTargetAddress;
      frame.checksum = checksum;
      frame.service = service; frame.pid = pid; frame.payloadLength = payloadLength;
      for (uint8_t i = 0; i < payloadLength; ++i) frame.payload[i] = bytes[cursor + 2 + i];
      cursor += 2 + payloadLength;
      if (payloadLength < expected) return;
    } else if (service == 0x7F && cursor + 1 < length) {
      const uint8_t responseService = bytes[cursor + 1];
      const bool hasNrc = cursor + 2 < length;
      if (result.count >= MaxFrames) { result.overflow = true; result.error = ParseError::FrameCapacity; return; }
      Frame& frame = result.frames[result.count++];
      const size_t copyLength = rawLength < sizeof(frame.rawLine) - 1 ? rawLength : sizeof(frame.rawLine) - 1;
      memcpy(frame.rawLine, rawLine, copyLength);
      frame.rawLine[copyLength] = '\0';
      frame.hasEcuHeader = hasHeader;
      if (hasHeader) strncpy(frame.ecuHeader, header, sizeof(frame.ecuHeader) - 1);
      frame.protocol = protocol;
      frame.targetAddress = target; frame.sourceAddress = source;
      frame.hasTargetAddress = hasHeader && (protocol == Protocol::KwP || protocol == Protocol::Iso9141);
      frame.hasSourceAddress = frame.hasTargetAddress;
      frame.checksum = checksum;
      frame.service = service; frame.pid = responseService; frame.negative = true;
      if (hasNrc) { frame.nrc = bytes[cursor + 2]; frame.payload[0] = frame.nrc; frame.payloadLength = 1; }
      cursor += hasNrc ? 3 : 2;
      if (!hasNrc) return;
    } else {
      ++cursor;
    }
  }
}

uint8_t additiveChecksum(const uint8_t* bytes, size_t length) {
  uint16_t sum = 0;
  for (size_t i = 0; i < length; ++i) sum = static_cast<uint16_t>(sum + bytes[i]);
  return static_cast<uint8_t>(sum);
}

bool parseKwpLine(const char* line, size_t length, const char* compact, size_t compactLength,
                  Protocol hint, Result& result) {
  if (compactLength < 8 || (compactLength & 1U)) return false;
  uint8_t bytes[MaxHex / 2]{};
  const size_t count = compactLength / 2;
  for (size_t i = 0; i < count; ++i) bytes[i] = hexByte(compact + i * 2);
  const uint8_t format = bytes[0];
  const uint8_t addressMode = static_cast<uint8_t>(format & 0xC0);
  size_t cursor = 1;
  uint8_t declared = static_cast<uint8_t>(format & 0x3F);
  // ISO 14230 length counts the data field from the Service ID, excluding
  // addresses and checksum. CARB exception framing (0x48/0x68) is distinct:
  // the OBD-style format includes target/source bytes in its length.
  const bool carbException = addressMode == 0x40;
  const bool hasAddresses = addressMode == 0x40 || addressMode == 0x80 || addressMode == 0xC0;
  uint8_t target = 0, source = 0;
  if (hasAddresses) {
    if (cursor + 2 > count) { ++result.ignoredTextLines; result.error = ParseError::InvalidLength; return true; }
    target = bytes[cursor++]; source = bytes[cursor++];
  }
  if (carbException) {
    if (!declared) {
      if (cursor >= count) { ++result.ignoredTextLines; result.error = ParseError::InvalidLength; return true; }
      declared = bytes[cursor++];
    }
    if (declared < 4) { ++result.ignoredTextLines; result.error = ParseError::InvalidLength; return true; }
  } else if (!declared) {
    if (cursor >= count) { ++result.ignoredTextLines; result.error = ParseError::InvalidLength; return true; }
    declared = bytes[cursor++];
  }
  const size_t pduOffset = cursor;
  const size_t pduLength = carbException ? static_cast<size_t>(declared - 2U) : declared;
  const size_t declaredEnd = pduOffset + pduLength;
  if (declared < 2 || declaredEnd > count ||
      (count != declaredEnd && count != declaredEnd + 1)) {
    ++result.ignoredTextLines;
    result.error = ParseError::InvalidLength;
    return true;
  }
  ChecksumStatus checksum = ChecksumStatus::Absent;
  if (count == declaredEnd + 1) {
    checksum = additiveChecksum(bytes, declaredEnd) == bytes[declaredEnd]
                   ? ChecksumStatus::Valid : ChecksumStatus::Invalid;
    if (checksum == ChecksumStatus::Invalid) {
      ++result.ignoredTextLines;
      result.error = ParseError::InvalidChecksum;
      return true;
    }
  }
  char header[9]{};
  if (hasAddresses) {
    // Source address identifies the ECU in a response. Keep the target byte
    // separately; it identifies the receiver/tester, not a second ECU.
    snprintf(header, sizeof(header), "K%02X", source);
  }
  if (!pduLength) { ++result.ignoredTextLines; result.error = ParseError::UnsupportedFrame; return true; }
  const uint8_t before = result.count;
  storePdu(bytes + pduOffset, pduLength, line, length, header, hasAddresses,
           hint == Protocol::Iso9141 ? Protocol::Iso9141 : Protocol::KwP,
           target, source, checksum, result);
  if (before == result.count) ++result.ignoredTextLines;
  return true;
}

void parseLine(const char* line, size_t length, Result& result, Protocol hint) {
  if (!length) return;
  char compact[MaxHex + 1]{};
  size_t compactLength = 0;
  bool separated = false;
  for (size_t i = 0; i < length; ++i) {
    const char c = line[i];
    if (delimiter(c)) { separated = true; continue; }
    if (!isxdigit(static_cast<unsigned char>(c)) || compactLength >= MaxHex) {
      ++result.ignoredTextLines;
      return;
    }
    compact[compactLength++] = static_cast<char>(toupper(static_cast<unsigned char>(c)));
  }
  if (!compactLength) return;

  // KWP/ISO9141 link-layer frames are recognized before CAN. The address-mode
  // bits and inline/additional length must agree exactly; checksum-bearing
  // frames are accepted only after the ISO additive checksum validates.
  const uint8_t first = hexByte(compact);
  const bool canResponsePrefix = (compactLength >= 3 && compact[0] == '7' && compact[1] == 'E' &&
                                  compact[2] >= '8' && compact[2] <= 'F') ||
                                 (compactLength >= 8 &&
                                  (strncmp(compact, "18DA", 4) == 0 || strncmp(compact, "18DB", 4) == 0));
  const bool servicePduPrefix = first == 0x41 || first == 0x7F;
  const bool mode01CommandEcho = compactLength == 4 && compact[0] == '0' && compact[1] == '1';
  if (!canResponsePrefix && !servicePduPrefix && !mode01CommandEcho &&
      (hint == Protocol::KwP || hint == Protocol::Iso9141 || hint == Protocol::Unknown) &&
      parseKwpLine(line, length, compact, compactLength, hint, result)) return;

  char header[9]{};
  size_t headerLength = 0;
  size_t firstTokenStart = 0;
  while (firstTokenStart < length && delimiter(line[firstTokenStart])) ++firstTokenStart;
  size_t firstTokenEnd = firstTokenStart;
  while (firstTokenEnd < length && !delimiter(line[firstTokenEnd])) ++firstTokenEnd;
  const size_t firstTokenLength = firstTokenEnd - firstTokenStart;
  if ((separated && firstTokenLength == 3 && allHex(line + firstTokenStart, firstTokenLength)) ||
      (separated && firstTokenLength == 8 && allHex(line + firstTokenStart, firstTokenLength) &&
       (strncmp(line + firstTokenStart, "18DA", 4) == 0 || strncmp(line + firstTokenStart, "18DB", 4) == 0))) {
    headerLength = firstTokenLength;
  } else if (!separated && (compactLength & 1U) && compactLength >= 9 &&
             compact[0] == '7' && compact[1] == 'E' &&
             compact[2] >= '8' && compact[2] <= 'F') {
    // ATH1 + ATS1 compact 11-bit response, e.g. 7EA 03 41 05 5F.
    headerLength = 3;
  } else if (!separated && compactLength >= 14 &&
             ((compactLength - 8) & 1U) == 0 &&
             ((strncmp(compact, "18DA", 4) == 0) || (strncmp(compact, "18DB", 4) == 0))) {
    // Compact 29-bit ISO 15765 address. ELM ATH1 output includes the ISO-TP
    // length byte after the 8-hex-digit address; validate it before use.
    const size_t payloadBytes = (compactLength - 8) / 2;
    const uint8_t firstByte = hexByte(compact + 8);
    if (firstByte > 0x0F || firstByte == payloadBytes - 1)
      headerLength = 8;
  }
  if (headerLength) {
    memcpy(header, compact, headerLength);
    memmove(compact, compact + headerLength, compactLength - headerLength);
    compactLength -= headerLength;
  }
  if (!compactLength || (compactLength & 1U)) {
    ++result.ignoredTextLines;
    result.error = ParseError::InvalidLength;
    return;
  }

  uint8_t bytes[MaxHex / 2]{};
  const size_t byteCount = compactLength / 2;
  for (size_t i = 0; i < byteCount; ++i) bytes[i] = hexByte(compact + i * 2);
  size_t pduOffset = 0;
  if (headerLength && bytes[0] <= 0x0F) {
    if (byteCount < 2 || bytes[0] != byteCount - 1) {
      ++result.ignoredTextLines;
      result.error = ParseError::InvalidLength;
      return;
    }
    pduOffset = 1;
  }
  if (pduOffset >= byteCount) return;

  const uint8_t before = result.count;
  storePdu(bytes + pduOffset, byteCount - pduOffset, line, length,
           header, headerLength != 0, Protocol::Can, 0, 0,
           ChecksumStatus::NotApplicable, result);
  if (before == result.count) ++result.ignoredTextLines;
}
}

void parse(const char* response, Result& result, Protocol hint) {
  result = Result{};
  if (!response) return;
  char line[MaxLine]{};
  size_t length = 0;
  for (const char* p = response;; ++p) {
    const char c = *p;
    if (c == '\r' || c == '\n' || c == '\0') {
      parseLine(line, length, result, hint);
      length = 0;
      if (c == '\0') break;
    } else if (length + 1 < sizeof(line)) {
      line[length++] = c;
    } else {
      ++result.ignoredTextLines;
      result.error = ParseError::LineTooLong;
      while (*p && *p != '\r' && *p != '\n') ++p;
      length = 0;
      if (!*p) break;
    }
  }
}

bool findPositive(const Result& result, uint8_t pid, uint8_t requiredBytes, Frame& output,
                  const char* preferredEcuHeader, uint8_t* matchingCount) {
  bool foundShort = false;
  bool foundValid = false;
  bool foundPreferred = false;
  uint8_t matches = 0;
  Frame firstValid{};
  Frame preferred{};
  for (uint8_t i = 0; i < result.count; ++i) {
    const Frame& frame = result.frames[i];
    if (frame.negative || frame.service != 0x41 || frame.pid != pid) continue;
    if (frame.payloadLength >= requiredBytes) {
      ++matches;
      if (!foundValid) { firstValid = frame; foundValid = true; }
      if (preferredEcuHeader && frame.hasEcuHeader &&
          strcmp(frame.ecuHeader, preferredEcuHeader) == 0) {
        preferred = frame;
        foundPreferred = true;
      }
      continue;
    }
    if (!foundShort) { output = frame; foundShort = true; }
  }
  if (matchingCount) *matchingCount = matches;
  if (preferredEcuHeader) {
    if (foundPreferred) { output = preferred; return true; }
    if (foundValid) output = firstValid; // Retain for diagnostics, never accept another ECU's value.
    return false;
  }
  if (foundValid) output = firstValid;
  return foundValid;
}

bool findNegative(const Result& result, uint8_t requestedService, Frame& output) {
  for (uint8_t i = 0; i < result.count; ++i) {
    const Frame& frame = result.frames[i];
    if (frame.negative && frame.pid == requestedService && frame.payloadLength >= 1) {
      output = frame;
      return true;
    }
  }
  return false;
}

bool decodeMode01Byte(uint8_t pid, uint8_t a, float& value) {
  switch (pid) {
    case 0x05: value = static_cast<float>(a) - 40.0f; return true;
    case 0x11: value = static_cast<float>(a) * 100.0f / 255.0f; return true;
    case 0x0B: value = static_cast<float>(a); return true;
    case 0x06:
    case 0x07: value = (static_cast<float>(a) - 128.0f) * 100.0f / 128.0f; return true;
    default: return false;
  }
}

uint32_t bitmapValue(const Frame& frame) {
  if (frame.service != 0x41 || frame.pid != 0x00 || frame.payloadLength < 4) return 0;
  return (static_cast<uint32_t>(frame.payload[0]) << 24) |
         (static_cast<uint32_t>(frame.payload[1]) << 16) |
         (static_cast<uint32_t>(frame.payload[2]) << 8) |
          static_cast<uint32_t>(frame.payload[3]);
}

bool bitmapSupports(uint32_t bitmap, uint8_t pid) {
  if (pid == 0 || pid > 32) return false;
  const uint8_t offset = static_cast<uint8_t>(pid - 1);
  return (bitmap & (1UL << (31 - offset))) != 0;
}
}
