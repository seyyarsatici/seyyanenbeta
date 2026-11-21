#include "obd_response_parser.h"
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

int main() {
  testBitmapForms();
  testPidFormsAndEcho();
  testWrongShortAndTextResponses();
  testPositiveAndNegativeAndMultipleEcus();
  testMalformedAndCapacityCases();
  testConversions();
  puts("OBD response parser tests passed");
  return 0;
}
