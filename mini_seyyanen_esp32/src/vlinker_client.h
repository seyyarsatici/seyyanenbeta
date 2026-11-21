#pragma once
#include <Arduino.h>
#include <BluetoothSerial.h>
#include <atomic>

enum class LinkState : uint8_t { Disconnected, Connecting, Connected };

class BluetoothTransport {
 public:
  virtual ~BluetoothTransport() = default;
  virtual bool begin(const char* localName, bool master) = 0;
  virtual bool connected() = 0;
  virtual bool connectByName(const String& remoteName) = 0;
  virtual bool connectByMac(uint8_t remoteAddress[6]) = 0;
  virtual int available() = 0;
  virtual int read() = 0;
  virtual size_t print(const char* text) = 0;
  virtual size_t print(char character) = 0;
  virtual bool disconnect() = 0;
};

class ArduinoBluetoothTransport final : public BluetoothTransport {
 public:
  bool begin(const char* localName, bool master) override;
  bool connected() override;
  bool connectByName(const String& remoteName) override;
  bool connectByMac(uint8_t remoteAddress[6]) override;
  int available() override;
  int read() override;
  size_t print(const char* text) override;
  size_t print(char character) override;
  bool disconnect() override;
 private:
  BluetoothSerial _serial;
};

class VlinkerClient {
 public:
  VlinkerClient();
  explicit VlinkerClient(BluetoothTransport& transport);
  bool begin();
  void tick();
  LinkState state() const { return _state.load(); }
  bool ready() const { return _initialized; }
  bool takeResyncRecovery() {
    const bool pending = _resyncRecoveryPending;
    _resyncRecoveryPending = false;
    return pending;
  }
  bool takeResponse(String& response, bool* timedOut = nullptr);
  bool sendCommand(const char* command, uint32_t timeoutMs=2500);
 private:
  ArduinoBluetoothTransport _defaultTransport;
  BluetoothTransport* _transport;
  std::atomic<LinkState> _state{LinkState::Disconnected};
  uint32_t _lastConnectAttempt{0}, _responseStarted{0}, _responseTimeout{2500};
  uint32_t _desyncStarted{0};
  String _rx, _response;
  bool _waiting{false}, _complete{false}, _ready{false}, _desynchronized{false};
  bool _responseTimedOut{false};
  bool _resyncRecoveryPending{false};
  uint8_t _initStep{0};
  bool _initCommandInFlight{false}, _initialized{false};
  uint32_t _initRetryAt{0};
  bool connectNow();
  void startCommand(const char* command, uint32_t timeoutMs);
};
