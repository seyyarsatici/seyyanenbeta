#include "display_manager.h"
#include "config.h"
#include "obd_manager.h"
#include "vlinker_client.h"
#include "chevrolet_logo_rgb565.h"

DisplayManager::Display::Display() {
  auto b = _bus.config();
  b.spi_host = SPI2_HOST; b.spi_mode = 0; b.freq_write = 40000000;
  b.freq_read = 16000000; b.spi_3wire = false; b.use_lock = true;
  b.dma_channel = SPI_DMA_CH_AUTO; b.pin_sclk = Config::TftSclk;
  b.pin_mosi = Config::TftMosi; b.pin_miso = Config::TftMiso;
  b.pin_dc = Config::TftDc; _bus.config(b); _panel.setBus(&_bus);
  auto p = _panel.config(); p.pin_cs = Config::TftCs; p.pin_rst = Config::TftRst;
  p.pin_busy = -1; p.memory_width = 240; p.memory_height = 320;
  p.panel_width = 240; p.panel_height = 320; p.offset_x = 0; p.offset_y = 0;
  p.offset_rotation = 0;
  // Keep controller inversion off so rendered RGB565 pixels retain their
  // requested light/dark values. Select RGB channel order for RGB565 colors.
  p.invert = false;
  p.rgb_order = true;
  _panel.config(p); setPanel(&_panel);
}

DisplayManager::DisplayManager() : _touch(Config::TouchCs, Config::TouchIrq) {}
bool DisplayManager::begin() {
  pinMode(Config::Backlight, OUTPUT); digitalWrite(Config::Backlight, HIGH);
  _tft.init(); _tft.setRotation(1); _tft.setTextWrap(false);
  _touchSpi.begin(Config::TouchSclk, Config::TouchMiso, Config::TouchMosi, Config::TouchCs);
  _touch.begin(_touchSpi); _touch.setRotation(1);
  setTheme(Theme::Day);
  _screen = Screen::Splash;
  _screenStartedAt = millis();
  _tft.fillScreen(0xFFFF);
  _tft.pushImage((Config::ScreenWidth-ChevroletLogoWidth)/2,
                 (Config::ScreenHeight-ChevroletLogoHeight)/2,
                 ChevroletLogoWidth, ChevroletLogoHeight, ChevroletLogoRgb565);
  return true;
}
void DisplayManager::setTheme(Theme theme) {
  _theme = theme;
  if (theme == Theme::Day) { _bg=0xFFFF; _fg=0x0000; _line=0xC618; }
  else {
    _bg=0x0000;
    // Exact LimeGreen RGB888 source #32CD32, converted by LovyanGFX to RGB565.
    _fg=_tft.color565(0x32, 0xCD, 0x32);
    _line=_fg;
  }
  _dirty = true;
}
void DisplayManager::toggleTheme() {
  setTheme(_theme == Theme::Day ? Theme::Night : Theme::Day);
  Serial.printf("[DISPLAY] theme=%s\n", _theme == Theme::Day ? "DAY" : "NIGHT");
}
bool DisplayManager::pollSwipe() {
  bool changed=false;
  if (_touch.touched()) {
    TS_Point p=_touch.getPoint();
    // The XPT2046 library returns portrait panel axes in this rotation; map its
    // 320-long and 240-short axes to the landscape screen without swapping.
    int16_t x=map(p.x, Config::TouchMinX, Config::TouchMaxX, 0, Config::ScreenWidth-1);
    int16_t y=map(p.y, Config::TouchMinY, Config::TouchMaxY, 0, Config::ScreenHeight-1);
    if (Config::TouchSwapXY) { int16_t t=x; x=y; y=t; }
    if (Config::TouchInvertX) x=Config::ScreenWidth-1-x;
    if (Config::TouchInvertY) y=Config::ScreenHeight-1-y;
    x=constrain(x,0,Config::ScreenWidth-1);
    y=constrain(y,0,Config::ScreenHeight-1);
    if (!_touching) {
      _touching=true; _startX=x; _startY=y;
      Serial.printf("[TOUCH] down x=%d y=%d\n",x,y);
    }
    _lastX=x; _lastY=y;
  } else if (_touching) {
    _touching=false;
    // Ignore taps and vertical drags; require a deliberate horizontal stroke.
    int dx=_lastX-_startX, dy=_lastY-_startY;
    bool horizontal=abs(dx)>=Config::SwipeThresholdPx && abs(dx)>abs(dy)*1.3;
    Serial.printf("[TOUCH] up dx=%d dy=%d horizontal=%s\n",dx,dy,horizontal?"yes":"no");
    if (horizontal && _screen == Screen::Dashboard) {
      toggleTheme(); changed=true;
    }
  }
  return changed;
}
void DisplayManager::render(const DisplayValue* values, LinkState linkState, EcuState ecuState) {
  if (_screen == Screen::Splash) {
    if ((uint32_t)(millis()-_screenStartedAt) < 3000) return;
    _screen = Screen::ConnectionStatus;
    _previousBtStatus[0] = '\0';
    _previousEcuStatus[0] = '\0';
    _tft.fillScreen(0xFFFF);
    renderConnectionStatus(linkState, ecuState);
    return;
  }

  if (_screen == Screen::ConnectionStatus) {
    if (ecuState == EcuState::Connected) {
      _screen = Screen::Dashboard;
      setTheme(Theme::Day);
      _dirty = true;
      renderDashboard(values);
      return;
    }
    renderConnectionStatus(linkState, ecuState);
    return;
  }

  renderDashboard(values);
}

void DisplayManager::renderConnectionStatus(LinkState linkState, EcuState ecuState) {
  const char* btText = "BT: DISCONNECTED";
  if (linkState == LinkState::Connecting) btText = "BT: CONNECTING";
  else if (linkState == LinkState::Connected) btText = "BT: CONNECTED";

  const char* ecuText = "ECU: DISCONNECTED";
  switch (ecuState) {
    case EcuState::AdapterInitializing:
    case EcuState::Searching: ecuText = "ECU: CONNECTING"; break;
    case EcuState::Connected:
    case EcuState::ConnectedNoTargets:
    case EcuState::ConnectedAmbiguous: ecuText = "ECU: CONNECTED"; break;
    case EcuState::Disconnected:
    case EcuState::Failed: default: break;
  }

  _tft.setFont(&fonts::Font4); _tft.setTextSize(1); _tft.setTextColor(0x0000,0xFFFF);
  if (strcmp(_previousBtStatus,btText)!=0) {
    _tft.fillRect(0,72,Config::ScreenWidth,40,0xFFFF);
    int width=_tft.textWidth(btText);
    _tft.setCursor((Config::ScreenWidth-width)/2,78); _tft.print(btText);
    strlcpy(_previousBtStatus,btText,sizeof(_previousBtStatus));
  }
  if (strcmp(_previousEcuStatus,ecuText)!=0) {
    _tft.fillRect(0,126,Config::ScreenWidth,40,0xFFFF);
    int width=_tft.textWidth(ecuText);
    _tft.setCursor((Config::ScreenWidth-width)/2,132); _tft.print(ecuText);
    strlcpy(_previousEcuStatus,ecuText,sizeof(_previousEcuStatus));
  }
}

void DisplayManager::renderDashboard(const DisplayValue* values) {
  if (_dirty) {
    _tft.fillScreen(_bg); _tft.setTextColor(_fg,_bg);
    for(int i=0;i<4;i++) _tft.drawFastHLine(8,47+i*48,304,_line);
    _dirty=false; for(auto& row:_previousValues) row[0]='\0';
  }
  for(int i=0;i<5;i++) if(strcmp(_previousValues[i],values[i].value)!=0) {
    int y=i*48;
    _tft.fillRect(6,y,308,i==4?48:47,_bg); _tft.setTextColor(_fg,_bg);
    _tft.setFont(&fonts::Font2); _tft.setTextSize(1);
    _tft.setCursor(8,y+15); _tft.print(values[i].name);

    // Keep the unit adjacent to the live value, including when NONE is shown.
    _tft.setFont(&fonts::Font4);
    int valueWidth=_tft.textWidth(values[i].value);
    int unitGap=7;
    // Keep numeric right edges aligned independently of unit width.
    int valueRight=Config::ScreenWidth-50;
    int valueX=valueRight-valueWidth;
    int unitX=valueRight+unitGap;
    _tft.setCursor(valueX,y+9); _tft.print(values[i].value);
    _tft.setFont(&fonts::Font2);
    if(i==0) {
      _tft.drawCircle(unitX+2,y+22,2,_fg);
      _tft.setCursor(unitX+8,y+13); _tft.print('C');
    } else {
      _tft.setCursor(unitX,y+13); _tft.print(values[i].unit);
    }
    strlcpy(_previousValues[i],values[i].value,sizeof(_previousValues[i]));
  }
}
