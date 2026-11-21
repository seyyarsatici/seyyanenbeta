#include "obd_response_parser.h"
#include <ctype.h>
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
              const char* header, bool hasHeader, Result& result) {
  size_t cursor = 0;
  while (cursor < length && !result.overflow) {
    const uint8_t service = bytes[cursor];
    if (service == 0x41 && cursor + 1 < length) {
      const uint8_t pid = bytes[cursor + 1];
      const uint8_t expected = pid == 0x00 ? 4 : 1;
      const size_t available = length - (cursor + 2);
      const uint8_t payloadLength = static_cast<uint8_t>(available < expected ? available : expected);
      if (result.count >= MaxFrames) { result.overflow = true; return; }
      Frame& frame = result.frames[result.count++];
      const size_t copyLength = rawLength < sizeof(frame.rawLine) - 1 ? rawLength : sizeof(frame.rawLine) - 1;
      memcpy(frame.rawLine, rawLine, copyLength);
      frame.rawLine[copyLength] = '\0';
      frame.hasEcuHeader = hasHeader;
      if (hasHeader) strncpy(frame.ecuHeader, header, sizeof(frame.ecuHeader) - 1);
      frame.service = service; frame.pid = pid; frame.payloadLength = payloadLength;
      for (uint8_t i = 0; i < payloadLength; ++i) frame.payload[i] = bytes[cursor + 2 + i];
      cursor += 2 + payloadLength;
      if (payloadLength < expected) return;
    } else if (service == 0x7F && cursor + 1 < length) {
      const uint8_t responseService = bytes[cursor + 1];
      const bool hasNrc = cursor + 2 < length;
      if (result.count >= MaxFrames) { result.overflow = true; return; }
      Frame& frame = result.frames[result.count++];
      const size_t copyLength = rawLength < sizeof(frame.rawLine) - 1 ? rawLength : sizeof(frame.rawLine) - 1;
      memcpy(frame.rawLine, rawLine, copyLength);
      frame.rawLine[copyLength] = '\0';
      frame.hasEcuHeader = hasHeader;
      if (hasHeader) strncpy(frame.ecuHeader, header, sizeof(frame.ecuHeader) - 1);
      frame.service = service; frame.pid = responseService; frame.negative = true;
      if (hasNrc) { frame.nrc = bytes[cursor + 2]; frame.payload[0] = frame.nrc; frame.payloadLength = 1; }
      cursor += hasNrc ? 3 : 2;
      if (!hasNrc) return;
    } else {
      ++cursor;
    }
  }
}

void parseLine(const char* line, size_t length, Result& result) {
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
    // ATH1 + ATS0 compact 11-bit response, e.g. 7EA0341055F.
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
    return;
  }

  uint8_t bytes[MaxHex / 2]{};
  const size_t byteCount = compactLength / 2;
  for (size_t i = 0; i < byteCount; ++i) bytes[i] = hexByte(compact + i * 2);
  size_t pduOffset = 0;
  if (headerLength && bytes[0] <= 0x0F) {
    if (byteCount < 2 || bytes[0] != byteCount - 1) {
      ++result.ignoredTextLines;
      return;
    }
    pduOffset = 1;
  }
  if (pduOffset >= byteCount) return;

  const uint8_t before = result.count;
  storePdu(bytes + pduOffset, byteCount - pduOffset, line, length,
           header, headerLength != 0, result);
  if (before == result.count) ++result.ignoredTextLines;
}
}

void parse(const char* response, Result& result) {
  result = Result{};
  if (!response) return;
  char line[MaxLine]{};
  size_t length = 0;
  for (const char* p = response;; ++p) {
    const char c = *p;
    if (c == '\r' || c == '\n' || c == '\0') {
      parseLine(line, length, result);
      length = 0;
      if (c == '\0') break;
    } else if (length + 1 < sizeof(line)) {
      line[length++] = c;
    } else {
      ++result.ignoredTextLines;
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
