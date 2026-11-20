#include "vlinker_client.h"
#include "config.h"
#include <ctype.h>

namespace {
constexpr const char* InitCommands[] = {
  "ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0", "ATI", "ATDP"
};
constexpr uint8_t InitCommandCount = sizeof(InitCommands) / sizeof(InitCommands[0]);

bool adapterAccepted(const String& response) {
  String upper=response;
  upper.toUpperCase();
  upper.trim();
  return upper.length() && upper.indexOf('?')<0 &&
         upper.indexOf("ERROR")<0 && upper.indexOf("UNABLE TO CONNECT")<0;
}
}

bool VlinkerClient::begin() {
  // BluetoothClassic SPP is available on the original ESP32 used by this board.
  _ready=_bt.begin("Seyyanen-OBD", true);
  _lastConnectAttempt=millis()-5000;
  return _ready;
}

bool VlinkerClient::connectNow() {
  _state=LinkState::Connecting;
  bool ok=false;
  if (strlen(Config::VlinkerMac)) {
    uint8_t mac[6]; unsigned int b[6];
    if (sscanf(Config::VlinkerMac,"%x:%x:%x:%x:%x:%x",
               &b[0],&b[1],&b[2],&b[3],&b[4],&b[5])!=6) {
      Serial.println("[SPP] Invalid MAC in config.h");
    } else {
      for(int i=0;i<6;i++) mac[i]=static_cast<uint8_t>(b[i]);
      ok=_bt.connect(mac);
    }
  } else {
    ok=_bt.connect(String(Config::VlinkerName));
  }
  _state=ok?LinkState::Connected:LinkState::Disconnected;
  _lastConnectAttempt=millis();
  _initStep=0; _initCommandInFlight=false; _initialized=false; _initRetryAt=0;
  _waiting=false; _rx=""; _response=""; _complete=false;
  if(ok) {
    Serial.printf("[SPP] Connected; adapter label='%s'; ECU is not yet connected\n",
                  Config::VlinkerDisplayName);
  } else {
    Serial.printf("[SPP] Connection failed for '%s'\n",Config::VlinkerName);
  }
  return ok;
}

void VlinkerClient::startCommand(const char* command,uint32_t timeoutMs) {
  _rx=""; _response=""; _complete=false;
  _responseStarted=millis(); _responseTimeout=timeoutMs;
  _bt.print(command); _bt.print('\r'); _waiting=true;
  Serial.printf("[SPP TX] %s\n",command);
}

bool VlinkerClient::sendCommand(const char* command,uint32_t timeoutMs) {
  if (state()!=LinkState::Connected || !_initialized || _waiting || _complete) return false;
  startCommand(command,timeoutMs);
  return true;
}

void VlinkerClient::tick() {
  if (!_ready) return;
  if (state()!=LinkState::Connected) {
    if ((uint32_t)(millis()-_lastConnectAttempt)>=5000) connectNow();
    return;
  }
  if (!_bt.connected()) {
    _state=LinkState::Disconnected;
    _waiting=false; _complete=false; _initialized=false;
    _initStep=0; _initCommandInFlight=false;
    Serial.println("[SPP] Disconnected");
    return;
  }

  while (_bt.available()) {
    char c=static_cast<char>(_bt.read());
    if (c=='>' && _waiting) {
      _waiting=false; _response=_rx; _complete=true;
      Serial.printf("[SPP RX] %s\n",_response.c_str());
    } else if (_rx.length()<512) {
      _rx+=c;
    }
  }
  if (_waiting && (uint32_t)(millis()-_responseStarted)>=_responseTimeout) {
    _waiting=false; _response=_rx; _complete=true;
    Serial.printf("[SPP TIMEOUT] command response after %lu ms: %s\n",
                  static_cast<unsigned long>(_responseTimeout),_response.c_str());
  }

  if (_initialized) return; // OBD manager owns responses after adapter setup.

  if (_initCommandInFlight && _complete) {
    const char* command=InitCommands[_initStep];
    bool accepted=adapterAccepted(_response);
    Serial.printf("[AT INIT %s] %s => %s\n",accepted?"OK":"FAILED",
                  command,_response.length()?_response.c_str():"<empty>");
    _complete=false; _initCommandInFlight=false;
    if (!accepted) {
      Serial.printf("[AT INIT] Stopping sequence at %s; retrying from ATZ in 5 s\n",command);
      _initStep=0; _initRetryAt=millis()+5000;
      return;
    }
    ++_initStep;
    if (_initStep==InitCommandCount) {
      _initialized=true;
      Serial.println("[AT INIT] Adapter responded to all setup, identity and protocol commands; ECU still unverified");
      return;
    }
  }

  if (!_initCommandInFlight && !_initialized &&
      (int32_t)(millis()-_initRetryAt)>=0) {
    startCommand(InitCommands[_initStep],_initStep==0?6000:3000);
    _initCommandInFlight=true;
  }
}

bool VlinkerClient::takeResponse(String& response) {
  if (!_complete || !_initialized) return false;
  response=_response; _complete=false;
  return true;
}
