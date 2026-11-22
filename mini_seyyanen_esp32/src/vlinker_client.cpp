#include "vlinker_client.h"
#include "config.h"
#include <ctype.h>
#include <string.h>

namespace {
constexpr const char* InitCommands[] = {
  "ATZ", "ATE0", "ATL0", "ATS1", "ATH1", "ATI"
};
constexpr uint8_t InitCommandCount = sizeof(InitCommands) / sizeof(InitCommands[0]);

bool adapterAccepted(const char* command, const String& response) {
  String upper = response;
  upper.toUpperCase();
  upper.trim();
  if (!upper.length() || upper.indexOf('?') >= 0 || upper.indexOf("ERROR") >= 0 ||
      upper.indexOf("UNABLE TO CONNECT") >= 0 || upper.indexOf("NO DATA") >= 0 ||
      upper.indexOf("SEARCHING") >= 0 || upper.indexOf("BUS INIT") >= 0) return false;
  if (!strcmp(command, "ATZ")) {
    // Clone adapters vary: accept a reset banner or plain OK, but not an echo
    // alone or arbitrary nonempty text as evidence that the adapter reset.
    if (upper == "ATZ") return false;
    return upper.indexOf("OK") >= 0 || upper.indexOf("ELM") >= 0 ||
           upper.indexOf("STN") >= 0 || upper.indexOf("VLINKER") >= 0 ||
           upper.indexOf("VGATE") >= 0 || upper.indexOf("OBD") >= 0 ||
           upper.indexOf("VERSION") >= 0 || upper.indexOf("FW") >= 0;
  }
  if (!strcmp(command, "ATE0") || !strcmp(command, "ATL0") ||
      !strcmp(command, "ATS1") || !strcmp(command, "ATH1"))
    return upper.indexOf("OK") >= 0;
  if (!strcmp(command, "ATI"))
    return upper != "ATI";
  if (!strcmp(command, "ATDP") || !strcmp(command, "ATDPN"))
    return upper.indexOf("AUTO") >= 0 || upper.indexOf("ISO") >= 0 ||
           upper.indexOf("SAE") >= 0 || upper.indexOf("KWP") >= 0 ||
           upper.indexOf("CAN") >= 0 || upper.indexOf("J1850") >= 0 ||
           upper.indexOf("PROTOCOL") >= 0 ||
           upper.indexOf("USER") >= 0 || upper.indexOf("OK") >= 0 ||
           (upper.length() == 1 && isdigit(static_cast<unsigned char>(upper[0])));
  return false;
}
}

bool ArduinoBluetoothTransport::begin(const char* localName, bool master) {
  return _serial.begin(localName, master);
}
bool ArduinoBluetoothTransport::connected() { return _serial.connected(); }
bool ArduinoBluetoothTransport::connectByName(const String& remoteName) { return _serial.connect(remoteName); }
bool ArduinoBluetoothTransport::connectByMac(uint8_t remoteAddress[6]) { return _serial.connect(remoteAddress); }
int ArduinoBluetoothTransport::available() { return _serial.available(); }
int ArduinoBluetoothTransport::read() { return _serial.read(); }
size_t ArduinoBluetoothTransport::print(const char* text) { return _serial.print(text); }
size_t ArduinoBluetoothTransport::print(char character) { return _serial.print(character); }
bool ArduinoBluetoothTransport::disconnect() { return _serial.disconnect(); }

VlinkerClient::VlinkerClient() : _transport(&_defaultTransport) {}
VlinkerClient::VlinkerClient(BluetoothTransport& transport) : _transport(&transport) {}

bool VlinkerClient::begin() {
  // BluetoothClassic SPP is available on the original ESP32 used by this board.
  _ready=_transport->begin("Seyyanen-OBD", true);
  _lastConnectAttempt=millis()-5000;
  _resyncRecoveryPending=false;
  Serial.printf("[SPP] Classic SPP master initialization %s; target=%s\n",
                _ready ? "ready" : "failed", Config::VlinkerName);
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
      ok=_transport->connectByMac(mac);
    }
  } else {
    ok=_transport->connectByName(String(Config::VlinkerName));
  }
  _state=ok?LinkState::Connected:LinkState::Disconnected;
  _lastConnectAttempt=millis();
  _initStep=0; _initCommandInFlight=false; _initialized=false; _initRetryAt=0;
  _waiting=false; _rx=""; _response=""; _complete=false; _desynchronized=false;
  _desyncStarted=0; _responseTimedOut=false;
  if(ok) {
    Serial.printf("[SPP] Connected; adapter label='%s'; ECU is not yet connected\n",
                  Config::VlinkerDisplayName);
  } else {
    Serial.printf("[SPP] Connection failed for '%s'\n",Config::VlinkerName);
  }
  return ok;
}

void VlinkerClient::startCommand(const char* command,uint32_t timeoutMs) {
  _rx=""; _response=""; _complete=false; _responseTimedOut=false;
  _responseStarted=millis(); _responseTimeout=timeoutMs;
  _transport->print(command); _transport->print('\r'); _waiting=true;
  Serial.printf("[SPP TX] %s\n",command);
}

bool VlinkerClient::sendCommand(const char* command,uint32_t timeoutMs) {
  if (state()!=LinkState::Connected || !_initialized || _waiting || _complete || _desynchronized) return false;
  startCommand(command,timeoutMs);
  return true;
}

void VlinkerClient::tick() {
  if (!_ready) return;
  if (state()!=LinkState::Connected) {
    if ((uint32_t)(millis()-_lastConnectAttempt)>=5000) connectNow();
    return;
  }
  if (!_transport->connected()) {
    _state=LinkState::Disconnected;
    _waiting=false; _complete=false; _initialized=false; _responseTimedOut=false;
    _initStep=0; _initCommandInFlight=false; _desynchronized=false; _desyncStarted=0; _rx=""; _response="";
    Serial.println("[SPP] Disconnected");
    return;
  }

  while (_transport->available()) {
    char c=static_cast<char>(_transport->read());
    if (_desynchronized) {
      // After a timeout, discard the old command's tail through its ELM prompt.
      // It must never be delivered as the response to the next OBD request.
      if(c=='>') {
        _desynchronized=false;
        Serial.println("[SPP] Drained late response through its prompt; response not delivered to a later command");
      }
    } else if(c=='>' && _waiting) {
      _waiting=false; _response=_rx; _complete=true; _responseTimedOut=false;
      Serial.printf("[SPP RX] %s\n",_response.c_str());
    } else if(_waiting && _rx.length()<512) {
      _rx+=c;
    }
  }
  if (_waiting && (uint32_t)(millis()-_responseStarted)>=_responseTimeout) {
    _waiting=false; _response=_rx; _complete=true; _responseTimedOut=true;
    _desynchronized=true; _desyncStarted=millis();
    Serial.printf("[SPP TIMEOUT] %s before prompt after %lu ms; bytes=%u RAW=%s\n",
                  _response.length() ? "incomplete response" : "no response",
                  static_cast<unsigned long>(_responseTimeout), static_cast<unsigned>(_response.length()),
                  _response.length() ? _response.c_str() : "<empty>");
  }
  // Silence does not prove an ELM response boundary. Drain only through the
  // old prompt; if it never arrives, reset the SPP session to clear its stream.
  if(_desynchronized && (uint32_t)(millis()-_desyncStarted)>=Config::SppResyncTimeoutMs) {
    Serial.println("[SPP] Old ELM prompt not received; disconnecting to resynchronize safely");
    _resyncRecoveryPending = !_initCommandInFlight;
    _transport->disconnect();
    _state=LinkState::Disconnected;
    _lastConnectAttempt=millis();
    _waiting=false; _complete=false; _initialized=false; _initStep=0;
    _initCommandInFlight=false; _desynchronized=false; _responseTimedOut=false;
    _rx=""; _response="";
    return;
  }

  if (_initialized) return; // OBD manager owns responses after adapter setup.

  if (_initCommandInFlight && _complete) {
    const char* command=InitCommands[_initStep];
    bool accepted=!_responseTimedOut && adapterAccepted(command, _response);
    Serial.printf("[AT INIT %s] %s => RAW=%s\n",accepted?"OK":"FAILED",
                  command,_response.length()?_response.c_str():"<empty>");
    if (accepted && !strcmp(command, "ATI"))
      Serial.printf("[SPP ADAPTER] identity RAW=%s\n", _response.c_str());
    if (accepted && !strcmp(command, "ATDP"))
      Serial.printf("[OBD PROTOCOL] adapter reports %s; ECU connection still unverified\n", _response.c_str());
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

  if (!_desynchronized && !_initCommandInFlight && !_initialized &&
      (int32_t)(millis()-_initRetryAt)>=0) {
    startCommand(InitCommands[_initStep],_initStep==0?6000:3000);
    _initCommandInFlight=true;
  }
}

bool VlinkerClient::takeResponse(String& response, bool* timedOut) {
  if (!_complete || !_initialized) return false;
  response=_response;
  if(timedOut) *timedOut=_responseTimedOut;
  _complete=false;
  return true;
}
