#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>
#include "vlinker_client.h"
#include "ecu_registry.h"
#include <atomic>

struct ObdValue { const char* name; const char* unit; float value; bool valid; uint32_t updatedAt; };
enum class EcuState : uint8_t { Disconnected, AdapterInitializing, Searching, Connected, ConnectedNoTargets, ConnectedAmbiguous, Failed };

class ObdManager {
 public:
  enum class PendingCommand : uint8_t {
    None,
    TryKwpFast, SetKwpFast, BitmapKwpFast,
    TryKwpSlow, SetKwpSlow, BitmapKwpSlow,
    TryIso9141, SetIso9141, BitmapIso9141,
    TryAuto, SetAuto, BitmapAuto,
    ReadProtocolDescription, ReadProtocolNumber, VerifyRpm, Pid
  };
  void tick(VlinkerClient& client);
  void snapshot(ObdValue* destination) const;
  EcuState ecuState() const { return _ecuState.load(); }
 private:
  static constexpr uint8_t Count=5;
  static constexpr uint8_t Pids[Count]={0x05,0x11,0x0B,0x06,0x07};
  struct QueuedCommand { PendingCommand owner{PendingCommand::None}; char text[8]{}; uint32_t timeout{0}; bool active{false}; };
  ObdValue _values[Count]={{"ECT","C",0,false,0},{"THROTTLE POSITION","%",0,false,0},{"MAP","kPa",0,false,0},{"STFT","%",0,false,0},{"LTFT","%",0,false,0}};
  bool _pending{false}, _wasConnected{false}, _supportKnown{false};
  bool _hasSelectedEcuHeader{false};
  char _selectedEcuHeader[9]{};
  char _protocolDescription[40]{}, _protocolNumber[8]{};
  uint8_t _candidateIndex{0}, _nextIndex{0};
  uint8_t _failures[Count]{}, _consecutiveTimeouts{0};
  bool _supported[Count]{};
  uint32_t _nextRequest{0};
  PendingCommand _pendingCommand{PendingCommand::None};
  QueuedCommand _queued{};
  EcuRegistry::Registry _registry{};
  std::atomic<EcuState> _ecuState{EcuState::Disconnected};
  mutable portMUX_TYPE _valueMux = portMUX_INITIALIZER_UNLOCKED;

  void invalidateValues();
  void resetDiscovery(bool clearRegistry);
  void scheduleDiscoveryRetry(const char* reason);
  void beginCandidate(VlinkerClient& client);
  void tryNextCandidate(VlinkerClient& client, const char* reason);
  void startSelectedProtocol(VlinkerClient& client);
  bool queueCommand(VlinkerClient& client, const char* text, PendingCommand owner, uint32_t timeout);
  void pumpQueued(VlinkerClient& client);
  void processBitmap(const String& response, VlinkerClient& client);
  void processRpm(const String& response, VlinkerClient& client, bool timedOut);
  void selectRecord(uint8_t index, VlinkerClient& client);
  void consumePid(const String& response, bool timedOut);
  void processResponse(const String& response, bool timedOut, VlinkerClient& client);
};
