#include "obd_manager.h"
#include "obd_response_parser.h"
#include "config.h"
#include <cmath>
#include <cstdio>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

uint32_t hostMillis = 0;
bool hostLogsEnabled = false;
HostSerial Serial;

namespace {
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

class FakeBluetooth final : public BluetoothTransport {
 public:
  bool begin(const char*, bool master) override { sawMasterBegin = master; return true; }
  bool connected() override { return link; }
  bool connectByName(const String& name) override { remoteName = name.c_str(); link = true; ++connectCount; return true; }
  bool connectByMac(uint8_t[6]) override { link = true; ++connectCount; return true; }
  int available() override { return static_cast<int>(incoming.size()); }
  int read() override {
    if (incoming.empty()) return -1;
    const char value = incoming.front(); incoming.pop_front(); return static_cast<unsigned char>(value);
  }
  size_t print(const char* text) override {
    const size_t size = std::strlen(text);
    for (size_t i = 0; i < size; ++i) outgoing(text[i]);
    return size;
  }
  size_t print(char value) override { outgoing(value); return 1; }
  bool disconnect() override { link = false; ++disconnectCount; return true; }
  void inject(const std::string& text) { for (char value : text) incoming.push_back(value); }

  bool link{false}, sawMasterBegin{false};
  unsigned connectCount{0}, disconnectCount{0};
  std::string remoteName, lastCommand;
  std::deque<char> incoming;
  std::vector<std::string> commands;
 private:
  std::string pending;
  void outgoing(char value) {
    if (value == '\r') { lastCommand = pending; commands.push_back(pending); pending.clear(); }
    else pending += value;
  }
};

struct Harness {
  Harness() : client(transport) {
    hostMillis = 0;
    require(client.begin(), "SPP begin failed");
    client.tick(); // Starts the master connection.
    client.tick(); // Starts ATZ.
    initializeAdapter();
    obd.tick(client);
    require(transport.lastCommand == "0100", "initial AUTO bitmap command missing");
  }

  void initializeAdapter() {
    const char* commands[] = {"ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0", "ATI", "ATDP"};
    const char* replies[] = {"ELM327 v2.2", "OK", "OK", "OK", "OK", "OK", "vLinker MC+", "AUTO"};
    for (size_t i = 0; i < 8; ++i) {
      require(transport.lastCommand == commands[i], "AT initialization command order changed");
      answer(replies[i]);
    }
    require(client.ready(), "adapter initialization did not finish");
  }

  void answer(const std::string& response) {
    transport.inject(response + "\r>");
    client.tick();
    obd.tick(client);
  }

  void respondBitmap(const std::string& response = "4100BE3FA813") { answer(response); }

  void sendNextPid(const char* expected) {
    hostMillis += Config::PollIntervalMs;
    client.tick();
    obd.tick(client);
    if (transport.lastCommand != expected) {
      std::fprintf(stderr, "Expected PID %s, got %s at t=%lu\n", expected,
                   transport.lastCommand.c_str(), static_cast<unsigned long>(hostMillis));
      require(false, "unexpected sequential PID command");
    }
  }

  void advance(uint32_t ms) { hostMillis += ms; }
  ObdValue values[5]{};
  FakeBluetooth transport;
  VlinkerClient client;
  ObdManager obd;
};

void testSppAutoBitmapAndFivePidSweep() {
  Harness h;
  require(h.transport.sawMasterBegin, "BluetoothClassic master mode was not requested");
  h.respondBitmap();
  require(h.obd.ecuState() == EcuState::Connected, "positive AUTO bitmap did not confirm ECU");
  const char* commands[] = {"0105", "0111", "010B", "0106", "0107"};
  const char* responses[] = {"41055F", "41112B", "410B26", "410680", "410779"};
  for (size_t i = 0; i < 5; ++i) {
    h.sendNextPid(commands[i]);
    h.answer(responses[i]);
  }
  h.obd.snapshot(h.values);
  require(h.values[0].valid && std::fabs(h.values[0].value - 55.0f) < 0.001f, "ECT conversion failed");
  require(h.values[1].valid && std::fabs(h.values[1].value - 16.862745f) < 0.001f, "TPS conversion failed");
  require(h.values[2].valid && h.values[2].value == 38.0f, "MAP conversion failed");
  require(h.values[3].valid && std::fabs(h.values[3].value) < 0.001f, "STFT conversion failed");
  require(h.values[4].valid && std::fabs(h.values[4].value - (-5.46875f)) < 0.001f, "LTFT conversion failed");
}

void testAtzRejectsStatusTextAndEchoOnly() {
  FakeBluetooth transport;
  VlinkerClient client(transport);
  hostMillis = 0;
  require(client.begin(), "SPP begin failed for ATZ validation test");
  client.tick(); client.tick();
  require(transport.lastCommand == "ATZ", "ATZ was not first adapter command");
  transport.inject("SEARCHING...\r>");
  client.tick();
  require(!client.ready(), "SEARCHING text was accepted as ATZ success");
  hostMillis += 5000; client.tick(); client.tick();
  require(transport.lastCommand == "ATZ", "failed ATZ did not restart setup from ATZ");
  transport.inject("ATZ\r>"); client.tick();
  require(!client.ready(), "ATZ echo alone was accepted as reset response");
  hostMillis += 5000; client.tick(); client.tick();
  transport.inject("ELM327 v2.2\r>"); client.tick();
  require(transport.lastCommand == "ATE0", "valid clone reset banner was rejected");
}

void testNoDataIsPidLocal() {
  Harness h;
  h.respondBitmap();
  h.sendNextPid("0105"); h.answer("NO DATA");
  require(h.obd.ecuState() == EcuState::Connected, "single NO DATA incorrectly disconnected ECU");
  h.sendNextPid("0111"); h.answer("41112B");
  h.obd.snapshot(h.values);
  require(h.values[1].valid, "other supported PID stopped after NO DATA");
  for (unsigned cycle = 0; cycle < 2; ++cycle) {
    const char* commands[] = {"010B", "0106", "0107", "0105", "0111"};
    const char* responses[] = {"410B26", "410680", "410779", "NO DATA", "41112B"};
    for (size_t i = 0; i < 5; ++i) { h.sendNextPid(commands[i]); h.answer(responses[i]); }
  }
  h.obd.snapshot(h.values);
  require(!h.values[0].valid, "three PID-local failures did not invalidate ECT");
  require(h.obd.ecuState() == EcuState::Connected, "one PID failure streak became ECU loss");
  const char* retryCommands[] = {"010B", "0106", "0107", "0105"};
  const char* retryResponses[] = {"410B26", "410680", "410779", "41055F"};
  for (size_t i = 0; i < 4; ++i) {
    h.sendNextPid(retryCommands[i]);
    h.answer(retryResponses[i]);
  }
  h.obd.snapshot(h.values);
  require(h.values[0].valid, "PID was not retried after third failure");
}

void testLateAutoResponseFallsBackToKwp() {
  Harness h;
  h.advance(Config::EcuResponseTimeoutMs);
  h.client.tick(); h.obd.tick(h.client);
  require(h.transport.lastCommand == "0100", "AUTO probe command changed");
  h.transport.inject("\r>"); h.client.tick(); h.obd.tick(h.client); // Old AUTO prompt drains.
  h.advance(250); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.lastCommand == "ATSP4", "KWP fallback was not queued after AUTO timeout");
  h.answer("OK");
  require(h.transport.lastCommand == "ATDP", "ATDP was not read after ATSP4");
  h.answer("ISO 14230-4 KWP FAST");
  require(h.transport.lastCommand == "0100", "KWP bitmap was not requested after ATDP");
  h.respondBitmap();
  require(h.obd.ecuState() == EcuState::Connected, "positive KWP bitmap did not confirm ECU");
}

void testDelayedAutoResponseWithinWindow() {
  Harness h;
  h.advance(20000); h.client.tick(); h.obd.tick(h.client);
  require(h.obd.ecuState() == EcuState::Searching, "ECU not left in searching state during long AUTO");
  h.respondBitmap();
  require(h.obd.ecuState() == EcuState::Connected, "delayed AUTO bitmap was not accepted");
  require(h.transport.commands.back() != "ATSP4", "KWP fallback happened before AUTO timeout");
}

void testLatePidPromptCannotPoisonNextCommand() {
  Harness h;
  h.respondBitmap();
  h.sendNextPid("0105");
  h.advance(Config::PidResponseTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  h.transport.inject("41055F\r>"); // Stale payload + its delayed prompt.
  h.client.tick(); h.obd.tick(h.client);
  h.obd.snapshot(h.values);
  require(!h.values[0].valid, "late response was incorrectly committed as ECT");
  h.sendNextPid("0111");
}

void testNoPromptResyncReconnectsAndPreservesKwpFallback() {
  Harness h;
  h.advance(Config::EcuResponseTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.disconnectCount == 0, "SPP disconnected before resync deadline");
  h.advance(Config::SppResyncTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.disconnectCount == 1, "missing prompt did not reset SPP exactly once");
  require(h.obd.ecuState() == EcuState::Disconnected, "OBD state not reset on SPP resync");
  h.advance(5000); h.client.tick(); // Connect again.
  h.client.tick(); // Start ATZ.
  h.initializeAdapter();
  h.obd.tick(h.client);
  require(h.transport.lastCommand == "ATSP4", "pending KWP fallback was lost after resync");
  h.answer("OK"); h.answer("ISO 14230-4 KWP FAST");
  require(h.transport.lastCommand == "0100", "KWP bitmap missing after reinitialization");
  h.respondBitmap();
  require(h.obd.ecuState() == EcuState::Connected, "ECU not rediscovered after resync");
  require(h.transport.disconnectCount == 1, "unexpected repeated SPP reconnect loop");
}

void testEcuLossTriggersAutoRediscovery() {
  Harness h;
  h.respondBitmap();
  h.sendNextPid("0105"); h.answer("UNABLE TO CONNECT");
  require(h.obd.ecuState() == EcuState::Failed, "explicit ECU loss not reflected");
  h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.lastCommand == "ATSP0", "AUTO rediscovery did not start after ECU loss");
  h.answer("OK");
  require(h.transport.lastCommand == "0100", "bitmap not retried after ATSP0");
  h.respondBitmap();
  require(h.obd.ecuState() == EcuState::Connected, "ECU did not recover after rediscovery");
}

void testUnexpectedSppDropResetsAndReconnects() {
  Harness h;
  h.respondBitmap();
  h.sendNextPid("0105"); h.answer("41055F");
  h.obd.snapshot(h.values);
  require(h.values[0].valid, "pre-disconnect ECT value missing");

  h.transport.link = false;
  h.client.tick(); h.obd.tick(h.client);
  h.obd.snapshot(h.values);
  require(h.client.state() == LinkState::Disconnected, "SPP loss not reflected in link state");
  require(h.obd.ecuState() == EcuState::Disconnected, "SPP loss not reflected in ECU state");
  require(!h.values[0].valid, "SPP loss did not invalidate cached values");

  h.advance(5000); h.client.tick();
  require(h.client.state() == LinkState::Connected, "SPP reconnect attempt did not restore link");
  h.client.tick(); h.initializeAdapter(); h.obd.tick(h.client);
  require(h.transport.lastCommand == "0100", "fresh AUTO discovery did not follow SPP initialization");
  h.respondBitmap();
  require(h.obd.ecuState() == EcuState::Connected, "ECU was not rediscovered after SPP reconnect");
  require(h.transport.disconnectCount == 0, "ordinary SPP reconnect caused extra disconnects");
}

void testSelectedHeaderAndHeaderlessAmbiguity() {
  {
    Harness h;
    h.respondBitmap("7E8 06 41 00 08 00 00 00\r\n7E9 06 41 00 BE 3F A8 13");
    require(h.obd.ecuState() == EcuState::Connected, "header-aware bitmap selection failed");
    h.sendNextPid("0105");
    h.answer("7E8 03 41 05 20\r\n7E9 03 41 05 5F\r\n7EA 03 7F 01 12");
    h.obd.snapshot(h.values);
    require(h.values[0].valid && h.values[0].value == 55.0f, "PID did not follow selected ECU header / positive priority");
  }
  {
    Harness h;
    h.respondBitmap("4100BE3FA813\r\n410000000000");
    require(h.obd.ecuState() == EcuState::ConnectedAmbiguous, "headerless multi-ECU bitmap ambiguity not surfaced");
    const std::string last = h.transport.lastCommand;
    h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
    require(h.transport.lastCommand == "0100" && h.transport.lastCommand == last,
            "ambiguous headerless ECU result incorrectly started PID polling");
  }
  {
    Harness h;
    h.respondBitmap("7E8 06 41 00 BE 3F A8 13\r\n7E8 06 41 00 00 00 00 00");
    require(h.obd.ecuState() == EcuState::Connected, "same-header conflict should deterministically retain first bitmap");
    h.sendNextPid("0105"); h.answer("7E8 03 41 05 5F");
    h.obd.snapshot(h.values);
    require(h.values[0].valid && h.values[0].value == 55.0f, "first same-header bitmap was not used consistently");
  }
  {
    Harness h;
    h.respondBitmap("4100BE3FA813");
    h.sendNextPid("0105"); h.answer("7E8 03 41 05 5F");
    h.obd.snapshot(h.values);
    require(!h.values[0].valid, "headered PID response was accepted without a matching bitmap ECU identity");
  }
}

void testBitmapRediscoveryScenarios() {
  {
    Harness h;
    h.respondBitmap("410000000000");
    require(h.obd.ecuState() == EcuState::ConnectedNoTargets, "empty first bitmap did not enter no-target state");
    h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
    require(h.transport.lastCommand == "0100", "no-target state did not re-query bitmap");
    h.respondBitmap("410008208000"); // Supports 0105, 0111 and 010B.
    require(h.obd.ecuState() == EcuState::Connected, "rediscovery bitmap was not processed from no-target state");
    h.sendNextPid("0105"); h.answer("41055F");
    h.sendNextPid("0111"); h.answer("41112B");
    h.sendNextPid("010B"); h.answer("410B26");
    h.obd.snapshot(h.values);
    require(h.values[0].valid && h.values[1].valid && h.values[2].valid,
            "rediscovered supported PID set was not polled");
    require(!h.values[3].valid && !h.values[4].valid,
            "unsupported PIDs were polled or fabricated after rediscovery");
  }
  {
    Harness h;
    h.respondBitmap("4100BE3FA813\r\n410000000000");
    require(h.obd.ecuState() == EcuState::ConnectedAmbiguous, "initial headerless responses not marked ambiguous");
    h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
    require(h.transport.lastCommand == "0100", "ambiguous state did not re-query bitmap");
    h.respondBitmap("7EA064100BE3FA813");
    require(h.obd.ecuState() == EcuState::Connected, "single compact-header bitmap did not clear ambiguity");
    h.sendNextPid("0105"); h.answer("7EA0341055F");
    h.sendNextPid("0111"); h.answer("7EA0341112B");
    h.sendNextPid("010B"); h.answer("7EA03410B26");
    h.obd.snapshot(h.values);
    require(h.values[0].valid && h.values[1].valid && h.values[2].valid,
            "compact same-header PID responses were not associated with bitmap ECU");
  }
  {
    Harness h;
    h.respondBitmap("4100BE3FA813\r\n410000000000");
    require(h.obd.ecuState() == EcuState::ConnectedAmbiguous, "initial ambiguity setup failed");
    h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
    h.respondBitmap("4100BE3FA813\r\n410000000000");
    require(h.obd.ecuState() == EcuState::ConnectedAmbiguous, "repeated headerless ambiguity was cleared incorrectly");
    h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
    require(h.transport.lastCommand == "0100", "ambiguous rediscovery started a PID request");
  }
}

void testBitmapTimeoutKeepsKwpFallbackQueued(EcuState startingState) {
  Harness h;
  if (startingState == EcuState::ConnectedNoTargets) {
    h.respondBitmap("410000000000");
  } else {
    h.respondBitmap("4100BE3FA813\r\n410000000000");
  }
  require(h.obd.ecuState() == startingState, "fallback test did not enter requested ECU state");
  h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.lastCommand == "0100", "state did not issue its bitmap rediscovery query");
  const size_t beforeTimeout = h.transport.commands.size();
  h.advance(Config::EcuResponseTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.commands.size() == beforeTimeout,
          "ATSP4 was sent before the old AUTO response prompt was drained");
  require(h.obd.ecuState() == EcuState::Searching, "timed-out bitmap did not retain discovery state");

  h.transport.inject("\r>"); // Old AUTO prompt, before the 8-second hard reset.
  h.client.tick(); h.obd.tick(h.client);
  h.advance(250); h.client.tick(); h.obd.tick(h.client);
  require(h.transport.lastCommand == "ATSP4", "queued KWP fallback was not sent after old prompt");
  require(h.transport.commands.back() == "ATSP4", "normal PID request ran instead of KWP fallback");

  h.answer("OK");
  require(h.transport.lastCommand == "ATDP", "ATDP did not follow queued ATSP4");
  h.answer("ISO 14230-4 KWP FAST");
  require(h.transport.lastCommand == "0100", "KWP bitmap request did not follow ATDP");
  h.answer("7EA064100BE3FA813");
  require(h.obd.ecuState() == EcuState::Connected,
          "KWP bitmap did not complete after queued fallback");
}

void testBitmapTimeoutFallbackAfterNoTargetsAndAmbiguity() {
  testBitmapTimeoutKeepsKwpFallbackQueued(EcuState::ConnectedNoTargets);
  testBitmapTimeoutKeepsKwpFallbackQueued(EcuState::ConnectedAmbiguous);
}

void testOverflowingPidResponseIsRejectedLocally() {
  Harness h;
  h.respondBitmap();
  h.sendNextPid("0105");
  std::string response;
  for (unsigned i = 0; i < ObdResponseParser::MaxFrames + 1; ++i) {
    if (!response.empty()) response += "\r\n";
    response += "41055F";
  }
  h.answer(response);
  h.obd.snapshot(h.values);
  require(!h.values[0].valid, "partial overflowed PID response was committed");
  require(h.obd.ecuState() == EcuState::Connected, "PID frame overflow incorrectly lost ECU state");
  h.sendNextPid("0111");
  h.answer("41112B");
  h.obd.snapshot(h.values);
  require(h.values[1].valid, "overflow failure stopped other PID polling");
}

void testPollingTourAndStaleWindow() {
  Harness h;
  const uint32_t start = hostMillis;
  h.respondBitmap();
  const uint16_t delays[] = {100, 500, 700, 1500, 3000};
  const char* commands[] = {"0105", "0111", "010B", "0106", "0107"};
  const char* responses[] = {"41055F", "41112B", "410B26", "410680", "410779"};
  for (size_t i = 0; i < 5; ++i) {
    h.sendNextPid(commands[i]);
    h.advance(delays[i]);
    h.answer(responses[i]);
  }
  const uint32_t tourMs = hostMillis - start;
  require(tourMs == 8300, "heterogeneous-latency polling tour duration differs from configured schedule");
  require(tourMs < Config::StaleTimeoutMs, "one normal PID tour exceeded stale timeout");
  h.obd.snapshot(h.values);
  require(h.values[0].valid, "fresh ECT invalid before stale boundary");
  const uint32_t lastUpdate = h.values[4].updatedAt;
  h.advance(Config::StaleTimeoutMs - static_cast<uint32_t>(hostMillis - lastUpdate) - 1);
  h.obd.tick(h.client); h.obd.snapshot(h.values);
  require(h.values[4].valid, "value became stale before configured boundary");
  h.advance(2); h.obd.tick(h.client); h.obd.snapshot(h.values);
  require(!h.values[4].valid, "stale value remained valid beyond configured boundary");
}
}

int main() {
  try {
    testSppAutoBitmapAndFivePidSweep();
    testAtzRejectsStatusTextAndEchoOnly();
    testNoDataIsPidLocal();
    testLateAutoResponseFallsBackToKwp();
    testDelayedAutoResponseWithinWindow();
    testLatePidPromptCannotPoisonNextCommand();
    testNoPromptResyncReconnectsAndPreservesKwpFallback();
    testEcuLossTriggersAutoRediscovery();
    testUnexpectedSppDropResetsAndReconnects();
    testSelectedHeaderAndHeaderlessAmbiguity();
    testBitmapRediscoveryScenarios();
    testBitmapTimeoutFallbackAfterNoTargetsAndAmbiguity();
    testOverflowingPidResponseIsRejectedLocally();
    testPollingTourAndStaleWindow();
    std::puts("State-machine integration scenarios: 14 groups passed");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "State-machine integration test failed: %s\n", error.what());
    return 1;
  }
}
