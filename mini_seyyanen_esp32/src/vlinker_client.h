#pragma once
#include <Arduino.h>
#include <BluetoothSerial.h>
#include <atomic>

enum class LinkState : uint8_t { Disconnected, Connecting, Connected };
class VlinkerClient {
 public:
  bool begin();
  void tick();
  LinkState state() const { return _state.load(); }
  bool ready() const { return _initialized; }
  bool takeResponse(String& response);
  bool sendCommand(const char* command, uint32_t timeoutMs=2500);
 private:
  BluetoothSerial _bt;
  std::atomic<LinkState> _state{LinkState::Disconnected};
  uint32_t _lastConnectAttempt{0}, _responseStarted{0}, _responseTimeout{2500};
  String _rx, _response;
  bool _waiting{false}, _complete{false}, _ready{false};
  uint8_t _initStep{0};
  bool _initCommandInFlight{false}, _initialized{false};
  uint32_t _initRetryAt{0};
  bool connectNow();
  void startCommand(const char* command, uint32_t timeoutMs);
};
