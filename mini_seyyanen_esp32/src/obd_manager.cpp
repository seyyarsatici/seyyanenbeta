#include "obd_manager.h"
#include "config.h"
#include <ctype.h>

constexpr uint8_t ObdManager::Pids[ObdManager::Count];

namespace {
String hexResponseLines(const String& response) {
  String result;
  result.reserve(response.length());
  String line;
  line.reserve(40);
  auto appendLine = [&]() {
    String candidate;
    candidate.reserve(line.length());
    bool clean=true;
    for(size_t i=0;i<line.length();++i) {
      char c=line[i];
      if(isxdigit(static_cast<unsigned char>(c))) candidate+=static_cast<char>(toupper(static_cast<unsigned char>(c)));
      else if(!isspace(static_cast<unsigned char>(c))) { clean=false; break; }
    }
    // Discard text such as SEARCHING, BUS INIT and NO DATA instead of
    // accidentally treating their A-F letters as ECU payload bytes.
    if(clean && candidate.length()>=4 && (candidate.indexOf("41")>=0 || candidate.indexOf("7F")>=0))
      result+=candidate;
    line="";
  };
  for(size_t i=0;i<response.length();++i) {
    char c=response[i];
    if(c=='\r' || c=='\n') appendLine();
    else if(line.length()<80) line+=c;
  }
  appendLine();
  return result;
}

bool hasNegativeResponse(const String& hex) {
  return hex.indexOf("7F01")>=0;
}

const char* responseFailure(const String& response) {
  String upper=response; upper.toUpperCase();
  if(upper.indexOf("SEARCHING")>=0) return "SEARCHING without a completed ECU reply";
  if(upper.indexOf("BUS INIT")>=0) return "BUS INIT failed before a completed ECU reply";
  if(upper.indexOf("UNABLE TO CONNECT")>=0) return "UNABLE TO CONNECT";
  if(upper.indexOf("NO DATA")>=0) return "NO DATA";
  if(upper.indexOf('?')>=0) return "adapter returned '?'";
  if(!response.length()) return "empty response / timeout";
  return "no valid 41xx ECU response";
}
}

bool ObdManager::hasPid(const String& response,uint8_t base,uint8_t pid) {
  String hex=hexResponseLines(response);
  int pos=hex.indexOf("4100");
  if(pos<0 || pos+12>static_cast<int>(hex.length())) return false;
  uint32_t bitmap=strtoul(hex.substring(pos+4,pos+12).c_str(),nullptr,16);
  if(pid<=base || (uint16_t)(pid-base)>32) return false;
  uint8_t offset=static_cast<uint8_t>(pid-base-1);
  return (bitmap & (1UL<<(31-offset)))!=0;
}

void ObdManager::failAutoAndSelectKwp(VlinkerClient& client,const String& response) {
  Serial.printf("[OBD ECU] AUTO protocol bitmap failed: %s; raw='%s'\n",
                responseFailure(response),response.c_str());
  if(_fallbackTried) {
    _ecuState=EcuState::Failed;
    Serial.println("[OBD ECU] ECU connection failed after AUTO and KWP 5-baud attempts");
    _nextRequest=millis()+10000;
    return;
  }
  _fallbackTried=true;
  Serial.println("[OBD PROTOCOL] AUTO failed; trying ATSP4 (ISO 14230-4 KWP, 5-baud init, 10.4 kbaud)");
  if(client.sendCommand("ATSP4",3000)) {
    _pending=true; _pendingCommand=PendingCommand::SelectKwp;
    _nextRequest=millis()+3000;
  } else {
    _ecuState=EcuState::Failed;
    Serial.println("[OBD PROTOCOL] Could not queue ATSP4; adapter busy or not ready");
  }
}

void ObdManager::consume(const String& response) {
  String hex=hexResponseLines(response);
  if(!_supportKnown) {
    int pos=hex.indexOf("4100");
    if(pos<0 || pos+12>static_cast<int>(hex.length())) return;
    uint32_t bitmap=strtoul(hex.substring(pos+4,pos+12).c_str(),nullptr,16);
    _supportKnown=true;
    _ecuState=EcuState::Connected;
    Serial.printf("[OBD ECU] Positive 0100 response; support bitmap=%08lX; ECU communication confirmed\n",
                  static_cast<unsigned long>(bitmap));
    for(uint8_t i=0;i<Count;i++) {
      _supported[i]=hasPid(response,0x00,Pids[i]);
      Serial.printf("[OBD SUPPORT] 01%02X %s\n",Pids[i],_supported[i]?"supported":"unsupported");
      if(!_supported[i]) {
        portENTER_CRITICAL(&_valueMux); _values[i].valid=false; portEXIT_CRITICAL(&_valueMux);
      }
    }
    _nextIndex=0;
    return;
  }

  if(_nextIndex>=Count) _nextIndex=0;
  uint8_t pid=Pids[_nextIndex];
  char expected[5]; snprintf(expected,sizeof(expected),"41%02X",pid);
  int pos=hex.indexOf(expected);
  if(hasNegativeResponse(hex) || response.indexOf("NO DATA")>=0 || response.indexOf('?')>=0 || pos<0 ||
     pos+6>static_cast<int>(hex.length())) {
    const char* cause=hasNegativeResponse(hex)?"ECU negative response":responseFailure(response);
    String upper=response; upper.toUpperCase();
    bool ecuLost=!response.length() || upper.indexOf("UNABLE TO CONNECT")>=0 ||
                 upper.indexOf("SEARCHING")>=0 || upper.indexOf("BUS INIT")>=0;
    _supported[_nextIndex]=false;
    portENTER_CRITICAL(&_valueMux); _values[_nextIndex].valid=false; portEXIT_CRITICAL(&_valueMux);
    Serial.printf("[OBD PID] 01%02X unsupported/invalid (%s); raw='%s'; extracted='%s'\n",
                  pid,cause,response.c_str(),hex.c_str());
    if(ecuLost) {
      _ecuState=EcuState::Failed;
      Serial.println("[OBD ECU] ECU stopped responding after a previously confirmed bitmap");
    }
    _nextIndex=static_cast<uint8_t>((_nextIndex+1)%Count);
    return;
  }

  uint8_t a=static_cast<uint8_t>(strtoul(hex.substring(pos+4,pos+6).c_str(),nullptr,16));
  float value=a;
  if(pid==0x05) value=static_cast<float>(a)-40.0f;
  else if(pid==0x11) value=static_cast<float>(a)*100.0f/255.0f;
  else if(pid==0x06 || pid==0x07) value=(static_cast<float>(a)-128.0f)*100.0f/128.0f;
  portENTER_CRITICAL(&_valueMux);
  _values[_nextIndex].value=value; _values[_nextIndex].valid=true; _values[_nextIndex].updatedAt=millis();
  portEXIT_CRITICAL(&_valueMux);
  Serial.printf("[OBD PID] 01%02X raw='%s' payload=%s A=%u value=%.2f %s\n",
                pid,response.c_str(),hex.c_str(),a,value,_values[_nextIndex].unit);
  _nextIndex=static_cast<uint8_t>((_nextIndex+1)%Count);
}

void ObdManager::tick(VlinkerClient& client) {
  bool connected=client.state()==LinkState::Connected;
  if(_wasConnected && !connected) {
    _supportKnown=false; _pending=false; _pendingCommand=PendingCommand::None;
    _fallbackTried=false; _nextIndex=0; _ecuState=EcuState::Disconnected;
    portENTER_CRITICAL(&_valueMux);
    for(uint8_t i=0;i<Count;i++) _values[i].valid=false;
    portEXIT_CRITICAL(&_valueMux);
    Serial.println("[OBD ECU] Bluetooth lost; ECU state reset");
  }
  if(connected && !client.ready()) _ecuState=EcuState::AdapterInitializing;
  else if(!connected) _ecuState=EcuState::Disconnected;
  else if(!_supportKnown && _ecuState!=EcuState::Failed) _ecuState=EcuState::Searching;
  _wasConnected=connected;

  String response;
  if(client.takeResponse(response) && _pending) {
    PendingCommand completed=_pendingCommand;
    _pending=false; _pendingCommand=PendingCommand::None;
    if(completed==PendingCommand::Bitmap) {
      String bitmapHex=hexResponseLines(response);
      int bitmapPos=bitmapHex.indexOf("4100");
      if(bitmapPos>=0 && bitmapPos+12<=static_cast<int>(bitmapHex.length())) consume(response);
      else failAutoAndSelectKwp(client,response);
    } else if(completed==PendingCommand::Pid) {
      consume(response);
    } else if(completed==PendingCommand::SelectKwp) {
      String upper=response; upper.toUpperCase();
      if(upper.indexOf("OK")<0 || upper.indexOf('?')>=0) {
        Serial.printf("[OBD PROTOCOL] ATSP4 rejected; raw='%s'\n",response.c_str());
        _ecuState=EcuState::Failed; _nextRequest=millis()+10000;
      } else {
        Serial.printf("[OBD PROTOCOL] ATSP4 accepted; response='%s'\n",response.c_str());
        if(client.sendCommand("ATDP",3000)) {
          _pending=true; _pendingCommand=PendingCommand::ReadProtocol;
        } else {
          _ecuState=EcuState::Failed;
          Serial.println("[OBD PROTOCOL] Could not queue ATDP after ATSP4");
        }
      }
    } else if(completed==PendingCommand::ReadProtocol) {
      Serial.printf("[OBD PROTOCOL] Selected protocol after KWP fallback: %s\n",response.c_str());
      _nextRequest=millis();
    }
    if(_supportKnown) _nextRequest=millis()+Config::PollIntervalMs;
  }

  if(!connected || !client.ready() || _pending || (int32_t)(millis()-_nextRequest)<0) return;
  if(_ecuState==EcuState::Failed) return;
  if(!_supportKnown) {
    _ecuState=EcuState::Searching;
    if(client.sendCommand("0100",Config::EcuResponseTimeoutMs)) {
      _pending=true; _pendingCommand=PendingCommand::Bitmap;
      _nextRequest=millis()+Config::EcuResponseTimeoutMs;
      Serial.println("[OBD TX] 0100 supported PID bitmap (AUTO/KWP ECU probe)");
    }
    return;
  }

  for(uint8_t tries=0;tries<Count;tries++) {
    uint8_t i=_nextIndex;
    if(!_supported[i]) { _nextIndex=static_cast<uint8_t>((_nextIndex+1)%Count); continue; }
    char cmd[5]; snprintf(cmd,sizeof(cmd),"01%02X",Pids[i]);
    if(client.sendCommand(cmd,Config::PidResponseTimeoutMs)) {
      _pending=true; _pendingCommand=PendingCommand::Pid;
      _nextRequest=millis()+Config::PidResponseTimeoutMs;
      Serial.printf("[OBD TX] PID %s\n",cmd);
    }
    return;
  }
  _nextRequest=millis()+2000;
}

void ObdManager::snapshot(ObdValue* destination) const {
  portENTER_CRITICAL(&_valueMux);
  memcpy(destination,_values,sizeof(_values));
  portEXIT_CRITICAL(&_valueMux);
}
