#pragma once
#include "obd_response_parser.h"
#include <stdint.h>

namespace EcuRegistry {
constexpr uint8_t Capacity = 8;
enum class Role : uint8_t { Unknown, ProbableEngine };
struct Record {
  ObdResponseParser::Protocol protocol{ObdResponseParser::Protocol::Unknown};
  char responseIdentity[9]{};
  char requestIdentity[9]{};
  bool hasIdentity{false};
  bool hasRequestIdentity{false};
  uint8_t targetAddress{0};
  bool hasTargetAddress{false};
  uint32_t bitmap{0};
  bool bitmapKnown{false};
  bool bitmapConflict{false};
  uint32_t lastSuccess{0};
  bool rpmSupported{false};
  bool rpmResponded{false};
  bool verificationSignal{false};
  Role role{Role::Unknown};
};

class Registry {
 public:
  void clear();
  bool addBitmap(const ObdResponseParser::Frame& frame, uint32_t now);
  bool addResponse(const ObdResponseParser::Frame& frame, uint32_t now);
  void noteHeaderlessReply() { if (_anonymousReplies < 255) ++_anonymousReplies; }
  uint8_t count() const { return _count; }
  uint8_t anonymousReplies() const { return _anonymousReplies; }
  const Record& at(uint8_t index) const { return _records[index]; }
  Record& at(uint8_t index) { return _records[index]; }
  int8_t uniqueCandidate() const;
  int8_t uniqueRpmResponder() const;
  bool ambiguous() const;
 private:
  Record _records[Capacity]{};
  uint8_t _count{0};
  uint8_t _anonymousReplies{0};
  int8_t find(const ObdResponseParser::Frame& frame) const;
  int8_t ensure(const ObdResponseParser::Frame& frame);
  static void deriveCanRequest(Record& record);
};
}
