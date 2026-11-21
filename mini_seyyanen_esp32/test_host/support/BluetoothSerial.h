#pragma once
#include "Arduino.h"

class BluetoothSerial {
 public:
  bool begin(const char*, bool = false) { return false; }
  bool connected() const { return false; }
  bool connect(const String&) { return false; }
  bool connect(uint8_t*, int = 0, int = 0, int = 0) { return false; }
  int available() { return 0; }
  int read() { return -1; }
  size_t print(const char*) { return 0; }
  size_t print(char) { return 0; }
  bool disconnect() { return true; }
};
