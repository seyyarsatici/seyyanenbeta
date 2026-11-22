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
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }

class FakeBluetooth final : public BluetoothTransport {
 public:
  bool begin(const char*, bool master) override { sawMaster = master; return true; }
  bool connected() override { return link; }
  bool connectByName(const String& name) override { remoteName = name.c_str(); link = true; ++connects; return true; }
  bool connectByMac(uint8_t[6]) override { link = true; ++connects; return true; }
  int available() override { return static_cast<int>(incoming.size()); }
  int read() override { if (incoming.empty()) return -1; char c = incoming.front(); incoming.pop_front(); return static_cast<unsigned char>(c); }
  size_t print(const char* s) override { const size_t n = std::strlen(s); for (size_t i=0;i<n;++i) out(s[i]); return n; }
  size_t print(char c) override { out(c); return 1; }
  bool disconnect() override { link=false; ++disconnects; return true; }
  void inject(const std::string& s) { for(char c:s) incoming.push_back(c); }
  bool link{false}, sawMaster{false}; unsigned connects{0}, disconnects{0};
  std::string remoteName,lastCommand; std::deque<char> incoming; std::vector<std::string> commands;
 private:
  std::string pending;
  void out(char c) { if(c=='\r') { lastCommand=pending; commands.push_back(pending); pending.clear(); } else pending+=c; }
};

struct Harness {
  Harness() : client(bt) {
    hostMillis=0; require(client.begin(), "SPP begin failed"); client.tick(); client.tick();
    const char* commands[] = {"ATZ","ATE0","ATL0","ATS1","ATH1","ATI"};
    const char* replies[] = {"ELM327 v2.2","OK","OK","OK","OK","vLinker MC+"};
    for(size_t i=0;i<6;++i) { require(bt.lastCommand==commands[i], "adapter initialization order mismatch"); answer(replies[i]); }
    require(client.ready(), "adapter initialization did not complete");
    obd.tick(client); require(bt.lastCommand=="ATTP5", "discovery did not begin with KWP fast candidate");
  }
  void answer(const std::string& response) { bt.inject(response+"\r>"); client.tick(); obd.tick(client); }
  void selectCandidate(const std::string& description="ISO 14230-4 KWP FAST", const std::string& number="5") {
    answer("OK"); require(bt.lastCommand=="ATDP", "ATDP missing after protocol selection");
    answer(description); require(bt.lastCommand=="ATDPN", "ATDPN missing after ATDP");
    answer(number); require(bt.lastCommand=="0100", "0100 missing after protocol metadata");
  }
  void bitmap(const std::string& raw="4100BE3FA813") { answer(raw); }
  void verifyRpm(const std::string& raw="410C1AF8") { require(bt.lastCommand=="010C", "RPM verification probe missing"); answer(raw); }
  void discover(const std::string& raw="4100BE3FA813") { selectCandidate(); bitmap(raw); if (raw.find("BE3FA813")!=std::string::npos) verifyRpm(); }
  void send(const char* expected) { hostMillis += Config::PollIntervalMs; client.tick(); obd.tick(client); if(bt.lastCommand!=expected) std::fprintf(stderr,"Expected %s got %s at t=%lu\n",expected,bt.lastCommand.c_str(),static_cast<unsigned long>(hostMillis)); require(bt.lastCommand==expected, "unexpected command in state-machine sequence"); }
  void advance(uint32_t ms) { hostMillis += ms; }
  FakeBluetooth bt; VlinkerClient client; ObdManager obd; ObdValue values[5]{};
};

void testFastDiscoveryAndFivePidSweep() {
  Harness h; require(h.bt.sawMaster, "Classic SPP master mode missing"); h.discover();
  require(h.obd.ecuState()==EcuState::Connected, "0100+RPM did not confirm one ECU candidate");
  const char* commands[]={"0105","0111","010B","0106","0107"};
  const char* replies[]={"41055F","41112B","410B26","410680","410779"};
  for(size_t i=0;i<5;++i){h.send(commands[i]); h.answer(replies[i]);}
  h.obd.snapshot(h.values);
  require(h.values[0].valid && fabsf(h.values[0].value-55.0f)<.001f,"ECT formula mismatch");
  require(h.values[1].valid && fabsf(h.values[1].value-16.862745f)<.001f,"TPS formula mismatch");
  require(h.values[2].valid && h.values[2].value==38.0f,"MAP formula mismatch");
  require(h.values[3].valid && fabsf(h.values[3].value)<.001f,"STFT formula mismatch");
  require(h.values[4].valid && fabsf(h.values[4].value+5.46875f)<.001f,"LTFT formula mismatch");
}

void testUnsupportedAtTpFallsBackToAtSp() {
  Harness h; h.answer("?"); require(h.bt.lastCommand=="ATSP5","unsupported ATTP5 did not use ATSP5 fallback");
  h.answer("OK"); require(h.bt.lastCommand=="ATDP","fallback omitted ATDP");
  h.answer("ISO 14230-4 KWP FAST"); h.answer("5"); require(h.bt.lastCommand=="0100","fallback did not reach bitmap probe");
  h.bitmap("410000000000"); require(h.obd.ecuState()==EcuState::ConnectedNoTargets,"zero bitmap not reported as no targets");
}

void testProtocolCandidateOrderAndRetryBackoff() {
  Harness h;
  h.answer("?"); h.answer("?"); // ATSP5 rejected, advance.
  require(h.bt.lastCommand=="ATTP4","KWP slow candidate missing after protocol 5 rejection");
  h.answer("OK"); h.answer("ISO 14230-4 KWP 5 baud"); h.answer("4");
  h.bitmap("NO DATA"); require(h.bt.lastCommand=="ATTP3","ISO9141 candidate missing after KWP slow failure");
  h.answer("OK"); h.answer("ISO 9141-2"); h.answer("3"); h.bitmap("UNABLE TO CONNECT");
  require(h.bt.lastCommand=="ATTP0","AUTO candidate missing after explicit candidates fail");
  h.answer("OK"); h.answer("AUTO"); h.answer("A0"); h.bitmap("NO DATA");
  require(h.obd.ecuState()==EcuState::Failed,"all-candidate failure not recorded");
  const std::string last=h.bt.lastCommand; h.advance(Config::EcuRetryIntervalMs-1); h.client.tick(); h.obd.tick(h.client);
  require(h.bt.lastCommand==last,"unbounded/early retry happened before backoff");
  h.advance(1); h.client.tick(); h.obd.tick(h.client); require(h.bt.lastCommand=="ATTP5","retry did not restart configured order");
}

void testAutoCandidateCanSucceedAfterThreeExplicitProtocolsFail() {
  Harness h;
  h.answer("?"); h.answer("?");
  h.answer("?"); h.answer("?");
  h.answer("?"); h.answer("?");
  require(h.bt.lastCommand=="ATTP0","AUTO was not the final configured candidate");
  h.answer("OK"); h.answer("AUTO"); h.answer("A0");
  require(h.bt.lastCommand=="0100","AUTO did not issue bitmap probe");
  h.bitmap(); h.verifyRpm();
  require(h.obd.ecuState()==EcuState::Connected,"AUTO candidate did not succeed after explicit failures");
}

void testHeaderedMultipleEcusUseRpmEvidenceAndNeverMergeBitmaps() {
  Harness h; h.selectCandidate();
  h.bitmap("7E8 06 41 00 BE 3F A8 13\r\n7E9 06 41 00 BE 3F A8 13");
  require(h.bt.lastCommand=="010C","multiple ECU bitmap did not trigger RPM probe");
  h.answer("7E8 04 41 0C 1A F8");
  require(h.obd.ecuState()==EcuState::Connected,"unique RPM responder did not identify a pollable ECU");
  h.send("0105"); h.answer("7E8 03 41 05 5F\r\n7E9 03 41 05 20\r\n7EA 03 7F 01 12");
  h.obd.snapshot(h.values); require(h.values[0].valid && h.values[0].value==55.0f,"PID value came from a non-selected ECU");
}

void testHeaderlessMultiEcuRemainsAmbiguous() {
  Harness h; h.selectCandidate(); h.bitmap("4100BE3FA813\r\n410000000000");
  require(h.obd.ecuState()==EcuState::ConnectedAmbiguous,"headerless multi-ECU bitmap was not ambiguous");
  require(h.bt.lastCommand!="0105","ambiguous headerless ECU started target polling");
  h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
  require(h.bt.lastCommand=="ATTP5","ambiguous discovery did not restart from first candidate");
}

void testConflictingBitmapFromSameEcuIsNotMerged() {
  Harness h; h.selectCandidate(); h.bitmap("7E8 06 41 00 BE 3F A8 13\r\n7E8 06 41 00 00 00 00 00");
  require(h.obd.ecuState()==EcuState::ConnectedAmbiguous,"conflicting same-ECU bitmap was silently selected");
  require(h.bt.lastCommand!="0105","conflicting bitmap started target polling");
}

void testKwpFrameIdentityAndChecksummedResponse() {
  Harness h;
  h.selectCandidate("ISO 14230-4 KWP FAST","5");
  h.bitmap("48 6B 10 41 00 BE 3F A8 13 BC");
  require(h.bt.lastCommand=="010C", "KWP bitmap parser did not initiate RPM probe");
  h.verifyRpm("46 6B 10 41 0C 1A F8 20");
  require(h.obd.ecuState()==EcuState::Connected,"valid checksummed KWP exchange was not accepted");
  h.send("0105"); h.answer("45 6B 10 41 05 5F 65");
  h.obd.snapshot(h.values); require(h.values[0].valid && h.values[0].value==55.0f,"KWP PID response failed");
}

void testInvalidKwpChecksumRejected() {
  ObdResponseParser::Result result;
  ObdResponseParser::parse("48 6B 10 41 00 BE 3E B8 11 FA", result, ObdResponseParser::Protocol::KwP);
  require(result.count==0,"illustrative unverified/invalid checksum vector was accepted");
}

void testPidNoDataIsLocalAndRetries() {
  Harness h; h.discover(); h.send("0105"); h.answer("NO DATA");
  require(h.obd.ecuState()==EcuState::Connected,"single NO DATA caused ECU disconnect");
  h.send("0111"); h.answer("41112B"); h.obd.snapshot(h.values);
  require(h.values[1].valid,"other PID stopped after ECT NO DATA");
}

void testRpmVerificationFailureStopsPollingAndStaleValueExpires() {
  {
    Harness h; h.selectCandidate(); h.bitmap(); require(h.bt.lastCommand=="010C","RPM verification missing");
    h.answer("NO DATA"); require(h.obd.ecuState()==EcuState::ConnectedAmbiguous,"failed RPM verification was not surfaced");
    h.advance(Config::EcuRetryIntervalMs); h.client.tick(); h.obd.tick(h.client);
    require(h.bt.lastCommand=="ATTP5","failed RPM verification did not restart bounded discovery");
  }
  {
    Harness h; h.discover(); h.send("0105"); h.answer("41055F");
    h.obd.snapshot(h.values); require(h.values[0].valid,"pre-stale ECT was not stored");
    h.advance(Config::StaleTimeoutMs+1); h.client.tick(); h.obd.tick(h.client);
    h.obd.snapshot(h.values); require(!h.values[0].valid,"stale ECT survived beyond configured timeout");
  }
}

void testTimeoutOldPromptAndReconnectSafety() {
  Harness h; h.selectCandidate();
  h.advance(Config::EcuResponseTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  require(h.bt.lastCommand=="0100","bitmap timeout lost current in-flight command");
  h.bt.inject("\r>"); h.client.tick(); h.obd.tick(h.client);
  h.advance(250); h.client.tick(); h.obd.tick(h.client);
  require(h.bt.lastCommand=="ATTP4","next protocol was not deferred until stale prompt drain");
  require(h.bt.lastCommand!="0105","PID poll was sent after bitmap timeout");
}

void testMissingPromptReconnectRestartsInitializationAndDiscovery() {
  Harness h; h.selectCandidate(); h.advance(Config::EcuResponseTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  h.advance(Config::SppResyncTimeoutMs); h.client.tick(); h.obd.tick(h.client);
  require(h.bt.disconnects==1,"missing prompt did not reset SPP stream once");
  h.advance(5000); h.client.tick(); h.client.tick();
  const char* commands[]={"ATZ","ATE0","ATL0","ATS1","ATH1","ATI"};
  const char* replies[]={"ELM327 v2.2","OK","OK","OK","OK","vLinker MC+"};
  for(size_t i=0;i<6;++i){require(h.bt.lastCommand==commands[i],"reconnect skipped adapter initialization");h.answer(replies[i]);}
  h.obd.tick(h.client); require(h.bt.lastCommand=="ATTP5","reconnect did not restart configured discovery sequence");
  require(h.bt.disconnects==1,"reconnect caused a disconnect loop");
}

void testDelayedPositiveWithinCandidateTimeout() {
  Harness h; h.selectCandidate(); h.advance(Config::EcuResponseTimeoutMs-1000); h.client.tick(); h.obd.tick(h.client);
  h.bitmap("4100BE3FA813"); require(h.bt.lastCommand=="010C","late but in-window positive bitmap was discarded");
}

void testAtzRejectsTextAndEchoOnly() {
  FakeBluetooth bt; VlinkerClient client(bt); hostMillis=0; require(client.begin(),"SPP begin failed");
  client.tick(); client.tick(); require(bt.lastCommand=="ATZ","ATZ not first");
  bt.inject("SEARCHING...\r>"); client.tick(); require(!client.ready(),"SEARCHING accepted as ATZ");
}
}

int main() {
  try {
    testFastDiscoveryAndFivePidSweep();
    testUnsupportedAtTpFallsBackToAtSp();
    testProtocolCandidateOrderAndRetryBackoff();
    testAutoCandidateCanSucceedAfterThreeExplicitProtocolsFail();
    testHeaderedMultipleEcusUseRpmEvidenceAndNeverMergeBitmaps();
    testHeaderlessMultiEcuRemainsAmbiguous();
    testConflictingBitmapFromSameEcuIsNotMerged();
    testKwpFrameIdentityAndChecksummedResponse();
    testInvalidKwpChecksumRejected();
    testPidNoDataIsLocalAndRetries();
    testRpmVerificationFailureStopsPollingAndStaleValueExpires();
    testTimeoutOldPromptAndReconnectSafety();
    testMissingPromptReconnectRestartsInitializationAndDiscovery();
    testDelayedPositiveWithinCandidateTimeout();
    testAtzRejectsTextAndEchoOnly();
  } catch (const std::exception& error) { std::fprintf(stderr,"FAIL: %s\n",error.what()); return 1; }
  puts("OBD state-machine tests passed (15 scenario groups)");
  return 0;
}
