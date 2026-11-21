#pragma once
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

extern uint32_t hostMillis;
extern bool hostLogsEnabled;
inline uint32_t millis() { return hostMillis; }

class String {
 public:
  String() = default;
  String(const char* value) : _value(value ? value : "") {}
  String(const std::string& value) : _value(value) {}
  String& operator=(const char* value) { _value = value ? value : ""; return *this; }
  String& operator=(const String&) = default;
  String& operator+=(char value) { _value += value; return *this; }
  size_t length() const { return _value.length(); }
  const char* c_str() const { return _value.c_str(); }
  char operator[](size_t index) const { return _value[index]; }
  int indexOf(const char* text, int start = 0) const {
    if (start < 0 || static_cast<size_t>(start) > _value.size()) return -1;
    const size_t found = _value.find(text ? text : "", static_cast<size_t>(start));
    return found == std::string::npos ? -1 : static_cast<int>(found);
  }
  int indexOf(char value) const {
    const size_t found = _value.find(value);
    return found == std::string::npos ? -1 : static_cast<int>(found);
  }
  void toUpperCase() {
    for (char& value : _value) value = static_cast<char>(std::toupper(static_cast<unsigned char>(value)));
  }
  void trim() {
    const size_t first = _value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) { _value.clear(); return; }
    const size_t last = _value.find_last_not_of(" \t\r\n");
    _value = _value.substr(first, last - first + 1);
  }
  bool operator==(const char* other) const { return _value == (other ? other : ""); }
  bool operator!=(const char* other) const { return !(*this == other); }
 private:
  std::string _value;
};

class HostSerial {
 public:
  template <typename... Args> void printf(const char* format, Args... args) const {
    if (hostLogsEnabled) std::printf(format, args...);
  }
  void println(const char* text = "") const { if (hostLogsEnabled) std::puts(text); }
};
extern HostSerial Serial;

inline size_t strlcpy(char* destination, const char* source, size_t size) {
  const size_t length = std::strlen(source);
  if (size) {
    const size_t copied = length < size - 1 ? length : size - 1;
    std::memcpy(destination, source, copied);
    destination[copied] = '\0';
  }
  return length;
}
