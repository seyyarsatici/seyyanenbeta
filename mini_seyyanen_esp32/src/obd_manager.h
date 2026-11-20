#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>
#include "vlinker_client.h"
#include <atomic>

struct ObdValue { const char* name; const char* unit; float value; bool valid; uint32_t updatedAt; };
enum class EcuState : uint8_t { Disconnected, AdapterInitializing, Searching, Connected, Failed };
class ObdManager {
 public:
  void tick(VlinkerClient& client);
  void snapshot(ObdValue* destination) const;
  EcuState ecuState() const { return _ecuState.load(); }
 private:
  static constexpr uint8_t Count=5;
  static constexpr uint8_t Pids[Count]={0x05,0x11,0x0B,0x06,0x07};
  ObdValue _values[Count]={{"ECT","C",0,false,0},{"THROTTLE POSITION","%",0,false,0},{"MAP","kPa",0,false,0},{"STFT","%",0,false,0},{"LTFT","%",0,false,0}};
  bool _supportKnown{false}, _pending{false};
  bool _wasConnected{false};
  bool _fallbackTried{false};
  uint32_t _nextRequest{0};
  uint8_t _nextIndex{0};
  bool _supported[Count]{};
  enum class PendingCommand : uint8_t { None, Bitmap, Pid, SelectKwp, ReadProtocol };
  PendingCommand _pendingCommand{PendingCommand::None};
  std::atomic<EcuState> _ecuState{EcuState::Disconnected};
  mutable portMUX_TYPE _valueMux = portMUX_INITIALIZER_UNLOCKED;
  void consume(const String& response);
  void failAutoAndSelectKwp(VlinkerClient& client, const String& response);
  static bool hasPid(const String& response,uint8_t base,uint8_t pid);
};
