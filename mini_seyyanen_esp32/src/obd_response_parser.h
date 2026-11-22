#pragma once

#include <stddef.h>
#include <stdint.h>

namespace ObdResponseParser {
enum class Protocol : uint8_t { Unknown, Can, KwP, Iso9141 };
enum class ChecksumStatus : uint8_t { NotApplicable, Absent, Valid, Invalid };
enum class ParseError : uint8_t { None, InvalidLength, InvalidChecksum, UnsupportedFrame, FrameCapacity, LineTooLong };
constexpr uint8_t MaxFrames = 12;
constexpr uint8_t MaxPayload = 8;
constexpr size_t MaxRawLine = 96;

struct Frame {
  char rawLine[MaxRawLine]{};
  char ecuHeader[9]{};
  bool hasEcuHeader{false};
  Protocol protocol{Protocol::Unknown};
  uint8_t targetAddress{0};
  uint8_t sourceAddress{0};
  bool hasTargetAddress{false};
  bool hasSourceAddress{false};
  ChecksumStatus checksum{ChecksumStatus::NotApplicable};
  uint8_t service{0};       // Positive Mode 01 is 0x41, negative is 0x7F.
  uint8_t pid{0};           // For negative responses this is the requested service.
  uint8_t payload[MaxPayload]{};
  uint8_t payloadLength{0};
  uint8_t nrc{0};
  bool negative{false};
};

struct Result {
  Frame frames[MaxFrames]{};
  uint8_t count{0};
  uint16_t ignoredTextLines{0};
  bool overflow{false};
  ParseError error{ParseError::None};
};

// Parses each CR/LF-delimited ELM response line independently. Echoes and
// adapter status text are ignored; CAN headers and ISO-TP length bytes are
// retained/removed as appropriate before extracting OBD PDUs.
void parse(const char* response, Result& result, Protocol hint = Protocol::Unknown);

// Searches all parsed frames. On false, output receives the first matching
// service/PID frame if present (useful for reporting an incomplete payload).
bool findPositive(const Result& result, uint8_t pid, uint8_t requiredBytes, Frame& output,
                  const char* preferredEcuHeader = nullptr, uint8_t* matchingCount = nullptr);
bool findNegative(const Result& result, uint8_t requestedService, Frame& output);

bool decodeMode01Byte(uint8_t pid, uint8_t a, float& value);
uint32_t bitmapValue(const Frame& frame);
bool bitmapSupports(uint32_t bitmap, uint8_t pid);
}
