#pragma once
#include "config.h"
#include <Arduino.h>
#include <LovyanGFX.hpp>
#include <XPT2046_Touchscreen.h>

enum class Theme : uint8_t { Day, Night };
enum class LinkState : uint8_t;
enum class EcuState : uint8_t;
struct DisplayValue { const char* name; const char* value; const char* unit; };
class DisplayManager {
 public:
  DisplayManager();
  bool begin();
  void setTheme(Theme theme);
  bool pollSwipe();
  void render(const DisplayValue* values, LinkState linkState, EcuState ecuState);
 private:
  enum class Screen : uint8_t { Splash, ConnectionStatus, Dashboard };
  void toggleTheme();
  void renderConnectionStatus(LinkState linkState, EcuState ecuState);
  void renderDashboard(const DisplayValue* values);
  class Display : public lgfx::LGFX_Device {
   public: Display();
   private:
#if MINI_SEYYANEN_TFT_ST7789
    lgfx::Panel_ST7789 _panel;
#else
    lgfx::Panel_ILI9341 _panel;
#endif
    lgfx::Bus_SPI _bus;
  };
  Display _tft;
  SPIClass _touchSpi{VSPI};
  XPT2046_Touchscreen _touch;
  Theme _theme{Theme::Day};
  Screen _screen{Screen::Splash};
  uint32_t _screenStartedAt{0};
  bool _touching{false};
  int16_t _startX{0}, _startY{0};
  int16_t _lastX{0}, _lastY{0};
  uint16_t _bg{0xFFFF}, _fg{0x0000}, _line{0xC618};
  bool _dirty{true};
  char _previousValues[5][24]{};
  char _previousBtStatus[24]{};
  char _previousEcuStatus[24]{};
};
