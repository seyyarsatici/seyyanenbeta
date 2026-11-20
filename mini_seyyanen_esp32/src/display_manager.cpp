#include "display_manager.h"
#include "config.h"

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
  _touch.begin(_touchSpi); _touch.setRotation(1); setTheme(Theme::Day);
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
    if (horizontal) {
      toggleTheme(); changed=true;
    }
  }
  return changed;
}
void DisplayManager::render(const DisplayValue* values, const char* btStatus, const char* ecuStatus) {
  static char previous[5][24]{}; static char previousBtStatus[40]{}; static char previousEcuStatus[24]{};
  if (_dirty) {
    _tft.fillScreen(_bg); _tft.setTextColor(_fg,_bg);
    for(int i=0;i<4;i++) _tft.drawFastHLine(8,65+i*43,304,_line);
    _dirty=false; for(auto& row:previous) row[0]='\0';
    previousBtStatus[0]='\0'; previousEcuStatus[0]='\0';
  }
  if (strcmp(previousBtStatus,btStatus)!=0 || strcmp(previousEcuStatus,ecuStatus)!=0) {
    _tft.setFont(&fonts::Font2); _tft.setTextSize(1);
    _tft.fillRect(0,0,Config::ScreenWidth,21,_bg); _tft.setTextColor(_fg,_bg);
    _tft.setCursor(8,2); _tft.print(btStatus);
    int ecuWidth=_tft.textWidth(ecuStatus);
    _tft.setCursor(Config::ScreenWidth-8-ecuWidth,2); _tft.print(ecuStatus);
    strlcpy(previousBtStatus,btStatus,sizeof(previousBtStatus));
    strlcpy(previousEcuStatus,ecuStatus,sizeof(previousEcuStatus));
  }
  for(int i=0;i<5;i++) if(strcmp(previous[i],values[i].value)!=0) {
    int y=23+i*43;
    _tft.fillRect(6,y,308,42,_bg); _tft.setTextColor(_fg,_bg);
    _tft.setFont(&fonts::Font2); _tft.setTextSize(1);
    _tft.setCursor(8,y+13); _tft.print(values[i].name);

    // Right-align the value and unit as one group. Recompute the group's
    // origin from the live value so NONE and differently-sized values move together.
    _tft.setFont(&fonts::Font4);
    int valueWidth=_tft.textWidth(values[i].value);
    int unitWidth=(i==0)?14:_tft.textWidth(values[i].unit);
    int unitGap=7;
    int valueX=Config::ScreenWidth-8-valueWidth-unitGap-unitWidth;
    int unitX=valueX+valueWidth+unitGap;
    _tft.setCursor(valueX,y+7); _tft.print(values[i].value);
    _tft.setFont(&fonts::Font2);
    if(i==0) {
      _tft.drawCircle(unitX+2,y+22,2,_fg);
      _tft.setCursor(unitX+8,y+13); _tft.print('C');
    } else {
      _tft.setCursor(unitX,y+13); _tft.print(values[i].unit);
    }
    strlcpy(previous[i],values[i].value,sizeof(previous[i]));
  }
}
