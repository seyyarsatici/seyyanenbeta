#include "obd_response_parser.h"
#include "ecu_registry.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <string>

using namespace ObdResponseParser;

static Frame positive(const char* raw, uint8_t pid, uint8_t bytes = 1) {
  Result parsed;
  parse(raw, parsed);
  Frame frame{};
  assert(findPositive(parsed, pid, bytes, frame));
  return frame;
}

static void testBitmapForms() {
  const char* forms[] = {
    "4100BE3FA813",
    "0100\r\n4100BE3FA813",
    "41 00 BE 3F A8 13",
    "7E8 06 41 00 BE 3F A8 13",
    "SEARCHING...\r\n0100\r\n7E8 06 41 00 BE 3F A8 13"
  };
  for (const char* form : forms) {
    Frame frame = positive(form, 0x00, 4);
    const uint32_t bitmap = bitmapValue(frame);
    assert(bitmap == 0xBE3FA813UL);
    const uint8_t targets[] = {0x05, 0x11, 0x0B, 0x06, 0x07};
    for (uint8_t pid : targets) assert(bitmapSupports(bitmap, pid));
  }
  Result echoed;
  parse("0100\r\n4100BE3FA813", echoed);
  assert(echoed.error == ParseError::None && echoed.count == 1);
}

static void testPidFormsAndEcho() {
  Frame frame = positive("41055F", 0x05);
  assert(frame.payload[0] == 0x5F);
  assert(positive("0105\r\n41055F", 0x05).payload[0] == 0x5F);
  assert(positive("41 05 5F", 0x05).payload[0] == 0x5F);
  frame = positive("7E8 03 41 05 5F", 0x05);
  assert(frame.hasEcuHeader && strcmp(frame.ecuHeader, "7E8") == 0);
  assert(frame.payload[0] == 0x5F);
  frame = positive("18DAF110 03 41 05 5F", 0x05);
  assert(frame.hasEcuHeader && strcmp(frame.ecuHeader, "18DAF110") == 0);
  assert(frame.payload[0] == 0x5F);
  frame = positive("7EA0341055F", 0x05);
  assert(frame.hasEcuHeader && strcmp(frame.ecuHeader, "7EA") == 0);
  assert(frame.payload[0] == 0x5F);
  frame = positive("7EF0341055F", 0x05);
  assert(frame.hasEcuHeader && strcmp(frame.ecuHeader, "7EF") == 0);
  assert(frame.payload[0] == 0x5F);
  frame = positive("18DAF110064100BE3FA813", 0x00, 4);
  assert(frame.hasEcuHeader && strcmp(frame.ecuHeader, "18DAF110") == 0);
  assert(bitmapValue(frame) == 0xBE3FA813UL);
  frame = positive("SEARCHING...\r\n0105\r\n7E8 03 41 05 5F", 0x05);
  assert(frame.payload[0] == 0x5F);
  assert(strstr(frame.rawLine, "7E8") != 0);
}

static void testWrongShortAndTextResponses() {
  Result parsed;
  Frame frame{};
  parse("410B26", parsed);
  assert(!findPositive(parsed, 0x05, 1, frame));
  parse("4105", parsed);
  assert(!findPositive(parsed, 0x05, 1, frame));
  assert(frame.service == 0x41 && frame.pid == 0x05 && frame.payloadLength == 0);
  const char* text[] = {"NO DATA", "SEARCHING...", "UNABLE TO CONNECT", "?"};
  for (const char* raw : text) {
    parse(raw, parsed);
    assert(parsed.count == 0);
  }
  parse("7E8 02 41 05 5F", parsed); // Declared ISO-TP length is inconsistent.
  assert(parsed.count == 0);
}

static void testPositiveAndNegativeAndMultipleEcus() {
  Result parsed;
  parse("7E8 03 41 05 5F\r\n7E9 03 7F 01 12", parsed);
  assert(parsed.count == 2);
  Frame positiveFrame{}, negativeFrame{};
  assert(findPositive(parsed, 0x05, 1, positiveFrame));
  assert(positiveFrame.hasEcuHeader && strcmp(positiveFrame.ecuHeader, "7E8") == 0);
  assert(findNegative(parsed, 0x01, negativeFrame));
  assert(negativeFrame.hasEcuHeader && strcmp(negativeFrame.ecuHeader, "7E9") == 0);
  assert(negativeFrame.nrc == 0x12);

  parse("7E8 06 41 00 BE 3F A8 13\r\n7E9 06 41 00 00 00 00 00", parsed);
  assert(parsed.count == 2);
  assert(parsed.frames[0].hasEcuHeader && parsed.frames[1].hasEcuHeader);
  assert(bitmapValue(parsed.frames[0]) == 0xBE3FA813UL);
  assert(bitmapValue(parsed.frames[1]) == 0x00000000UL);

  parse("4100BE3FA813410000000000", parsed);
  assert(parsed.count == 2);
  assert(bitmapValue(parsed.frames[0]) == 0xBE3FA813UL);
  assert(bitmapValue(parsed.frames[1]) == 0x00000000UL);

  parse("7E8 03 41 05 5F\r\n7E9 03 41 05 59", parsed);
  assert(parsed.count == 2);
  assert(parsed.frames[0].payload[0] == 0x5F && parsed.frames[1].payload[0] == 0x59);
  uint8_t positiveCount = 0;
  assert(findPositive(parsed, 0x05, 1, positiveFrame, "7E9", &positiveCount));
  assert(positiveCount == 2 && strcmp(positiveFrame.ecuHeader, "7E9") == 0);
  assert(positiveFrame.payload[0] == 0x59);
  assert(!findPositive(parsed, 0x05, 1, positiveFrame, "7EA"));

  parse("7EA 06 41 00 BE 3F A8 13\r\n7EA 03 41 05 5F", parsed);
  assert(parsed.count == 2);
  assert(parsed.frames[0].hasEcuHeader && parsed.frames[1].hasEcuHeader);
  assert(strcmp(parsed.frames[0].ecuHeader, parsed.frames[1].ecuHeader) == 0);
  assert(parsed.frames[0].pid == 0x00 && parsed.frames[1].pid == 0x05);

  parse("7EA064100BE3FA813\r\n7EA0341055F", parsed);
  assert(parsed.count == 2);
  assert(strcmp(parsed.frames[0].ecuHeader, "7EA") == 0);
  assert(strcmp(parsed.frames[1].ecuHeader, "7EA") == 0);
  assert(bitmapValue(parsed.frames[0]) == 0xBE3FA813UL);
  assert(parsed.frames[1].service == 0x41 && parsed.frames[1].pid == 0x05);
}

static void testMalformedAndCapacityCases() {
  Result parsed;
  Frame frame{};
  parse("7E8 07 41 00 BE 3F A8 13", parsed); // Declared ISO-TP length too long.
  assert(parsed.count == 0);
  parse("4105", parsed);
  assert(!findPositive(parsed, 0x05, 1, frame));
  parse("410B26", parsed);
  assert(!findPositive(parsed, 0x05, 1, frame));

  std::string longLine(180, 'A');
  parse(longLine.c_str(), parsed);
  assert(parsed.count == 0);
  assert(parsed.ignoredTextLines > 0);

  std::string manyFrames;
  for (unsigned i = 0; i < MaxFrames + 3; ++i) {
    if (!manyFrames.empty()) manyFrames += "\r\n";
    manyFrames += "4105";
    manyFrames += (i & 1) ? "5F" : "59";
  }
  parse(manyFrames.c_str(), parsed);
  assert(parsed.count == MaxFrames);
  assert(parsed.overflow);
}

static void testConversions() {
  float value = 0;
  assert(decodeMode01Byte(0x05, 0x5F, value) && fabsf(value - 55.0f) < 0.001f);
  assert(decodeMode01Byte(0x06, 0x80, value) && fabsf(value) < 0.001f);
  assert(decodeMode01Byte(0x07, 0x79, value) && fabsf(value - (-5.46875f)) < 0.001f);
  assert(decodeMode01Byte(0x0B, 0x26, value) && fabsf(value - 38.0f) < 0.001f);
  assert(decodeMode01Byte(0x11, 0x2B, value) && fabsf(value - 16.862745f) < 0.001f);
  assert(!decodeMode01Byte(0x99, 0, value));
}

static void testKwpFramingAndChecksum() {
  Result parsed;
  parse("48 6B 10 41 00 BE 3F A8 13 BC", parsed, Protocol::KwP);
  assert(parsed.count == 1);
  const Frame& bitmap = parsed.frames[0];
  assert(bitmap.protocol == Protocol::KwP && bitmap.hasEcuHeader);
  assert(bitmap.hasTargetAddress && bitmap.targetAddress == 0x6B);
  assert(bitmap.hasSourceAddress && bitmap.sourceAddress == 0x10);
  assert(strcmp(bitmap.ecuHeader, "K10") == 0);
  assert(bitmap.checksum == ChecksumStatus::Valid);
  assert(bitmapValue(bitmap) == 0xBE3FA813UL);

  parse("486B104100BE3FA813BC", parsed, Protocol::KwP);
  assert(parsed.count == 1 && parsed.frames[0].sourceAddress == 0x10);
  parse("48 6B 10 41 00 BE 3F A8 13", parsed, Protocol::KwP);
  assert(parsed.count == 1 && parsed.frames[0].checksum == ChecksumStatus::Absent);
  parse("06 41 00 BE 3F A8 13 FF", parsed, Protocol::KwP);
  assert(parsed.count == 1 && !parsed.frames[0].hasEcuHeader && parsed.frames[0].protocol == Protocol::KwP);
  parse("C0 6B 10 06 41 00 BE 3F A8 13 3A", parsed, Protocol::KwP);
  assert(parsed.count == 1 && parsed.frames[0].targetAddress == 0x6B && parsed.frames[0].sourceAddress == 0x10);
  parse("86 6B 10 41 00 BE 3F A8 13 FA", parsed, Protocol::KwP);
  assert(parsed.count == 1 && parsed.frames[0].checksum == ChecksumStatus::Valid);

  parse("46 6B 10 41 0C 1A F8 20", parsed, Protocol::KwP);
  assert(parsed.count == 1 && parsed.frames[0].pid == 0x0C && parsed.frames[0].payloadLength == 2);
  assert(parsed.frames[0].payload[0] == 0x1A && parsed.frames[0].payload[1] == 0xF8);
  parse("45 6B 10 41 05 5F 65", parsed, Protocol::KwP);
  assert(parsed.count == 1 && parsed.frames[0].pid == 0x05 && parsed.frames[0].payload[0] == 0x5F);
  parse("45 6B 10 7F 01 12 52", parsed, Protocol::KwP);
  Frame kwpNegative{};
  assert(findNegative(parsed, 0x01, kwpNegative) && kwpNegative.nrc == 0x12);
  assert(kwpNegative.sourceAddress == 0x10 && kwpNegative.checksum == ChecksumStatus::Valid);
  parse("48 6B 10 41 00 BE 3F A8 13 BD", parsed, Protocol::KwP);
  assert(parsed.count == 0); // Invalid additive checksum is rejected.
  assert(parsed.error == ParseError::InvalidChecksum);
  parse("48 6B 10 41 00 BE 3F A8 13 BC 00", parsed, Protocol::KwP);
  assert(parsed.count == 0); // Trailing bytes beyond one frame are rejected.
  parse("48 6B 10 41 00 BE", parsed, Protocol::KwP);
  assert(parsed.count == 0); // Declared length exceeds available frame.
  assert(parsed.error == ParseError::InvalidLength);
  parse("48 6B 10 41 05 5F", parsed);
  assert(parsed.count == 0); // Malformed KWP must not fall through as headerless OBD data.
}

static void testKwpMultipleEcuFramesRemainDistinct() {
  Result parsed;
  parse("48 6B 10 41 00 BE 3F A8 13 BC\r\n48 6B 11 41 00 00 00 00 00 05", parsed, Protocol::KwP);
  assert(parsed.count == 2);
  assert(parsed.frames[0].sourceAddress == 0x10 && parsed.frames[1].sourceAddress == 0x11);
  assert(bitmapValue(parsed.frames[0]) == 0xBE3FA813UL);
  assert(bitmapValue(parsed.frames[1]) == 0);
}

static void testEcuRegistryIdentityAndVerification() {
  EcuRegistry::Registry registry;
  Result parsed;
  parse("7E8 06 41 00 BE 3F A8 13", parsed);
  assert(parsed.count == 1 && registry.addBitmap(parsed.frames[0], 100));
  assert(registry.count() == 1 && registry.uniqueCandidate() == 0);
  const EcuRegistry::Record& can = registry.at(0);
  assert(strcmp(can.responseIdentity, "7E8") == 0);
  assert(can.hasRequestIdentity && strcmp(can.requestIdentity, "7E0") == 0);
  assert(can.rpmSupported);

  parse("7E8 06 41 00 BE 3F A8 13", parsed);
  assert(registry.addBitmap(parsed.frames[0], 200) && registry.count() == 1);
  parse("7E9 06 41 00 08 00 00 00", parsed);
  assert(registry.addBitmap(parsed.frames[0], 300) && registry.count() == 2);
  assert(registry.at(0).bitmap == 0xBE3FA813UL && registry.at(1).bitmap == 0x08000000UL);
  assert(registry.ambiguous() && registry.uniqueCandidate() < 0);

  parse("7EA 03 41 05 5F", parsed);
  assert(!registry.addResponse(parsed.frames[0], 400)); // Unselected identity cannot verify 7E8.
  parse("7E8 04 41 0C 1A F8", parsed);
  assert(registry.addResponse(parsed.frames[0], 500));
  assert(registry.uniqueRpmResponder() == 0 && !registry.ambiguous());

  EcuRegistry::Registry extendedCan;
  parse("18DAF110 06 41 00 BE 3F A8 13", parsed);
  assert(extendedCan.addBitmap(parsed.frames[0], 1));
  assert(extendedCan.at(0).hasRequestIdentity && strcmp(extendedCan.at(0).requestIdentity, "18DA10F1") == 0);

  EcuRegistry::Registry conflict;
  parse("7E8 06 41 00 BE 3F A8 13", parsed); assert(conflict.addBitmap(parsed.frames[0], 1));
  parse("7E8 06 41 00 00 00 00 00", parsed); assert(conflict.addBitmap(parsed.frames[0], 2));
  assert(conflict.count() == 1 && conflict.at(0).bitmapConflict && conflict.uniqueCandidate() < 0);

  EcuRegistry::Registry kwp;
  parse("48 6B 10 41 00 BE 3F A8 13 BC", parsed, Protocol::KwP);
  assert(kwp.addBitmap(parsed.frames[0], 10));
  assert(kwp.at(0).hasIdentity && strcmp(kwp.at(0).responseIdentity, "K10") == 0);
  assert(kwp.at(0).hasTargetAddress && kwp.at(0).targetAddress == 0x6B);
  assert(!kwp.at(0).hasRequestIdentity); // No CAN-style KWP address arithmetic.
  parse("48 6A 10 41 00 BE 3F A8 13", parsed, Protocol::KwP);
  assert(kwp.addBitmap(parsed.frames[0], 11) && kwp.count() == 1); // Same ECU source, target is not ECU identity.
}

static void testDeterministicParserFuzzSmoke() {
  static const char alphabet[] = "0123456789ABCDEFabcdef :,\t-SEARCHINGNO DATA?";
  uint32_t state = 0xC0FFEEu;
  char input[192];
  for (unsigned sample = 0; sample < 20000; ++sample) {
    state = state * 1664525u + 1013904223u;
    const size_t length = state % (sizeof(input) - 1);
    for (size_t i = 0; i < length; ++i) {
      state = state * 1664525u + 1013904223u;
      input[i] = alphabet[state % (sizeof(alphabet) - 1)];
    }
    input[length] = '\0';
    Result parsed;
    parse(input, parsed);
    assert(parsed.count <= MaxFrames);
    for (uint8_t i = 0; i < parsed.count; ++i) {
      assert(parsed.frames[i].payloadLength <= MaxPayload);
      assert(memchr(parsed.frames[i].rawLine, '\0', MaxRawLine) != 0);
    }
  }
}

int main() {
  testBitmapForms();
  testPidFormsAndEcho();
  testWrongShortAndTextResponses();
  testPositiveAndNegativeAndMultipleEcus();
  testMalformedAndCapacityCases();
  testConversions();
  testKwpFramingAndChecksum();
  testKwpMultipleEcuFramesRemainDistinct();
  testEcuRegistryIdentityAndVerification();
  testDeterministicParserFuzzSmoke();
  puts("OBD response parser tests passed");
  return 0;
}
