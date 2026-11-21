#include <Arduino.h>
#include "config.h"
#include "display_manager.h"
#include "vlinker_client.h"
#include "obd_manager.h"

DisplayManager display;
VlinkerClient vlinker;
ObdManager obd;

// Bluetooth connect/inquiry may block for up to ten seconds. Keep all transport
// activity on its own task; the UI loop only reads state and renders snapshots.
void bluetoothTask(void*) {
  if(!vlinker.begin()) {
    Serial.println("Bluetooth SPP init failed; verify original ESP32 target");
    vTaskDelete(nullptr);
    return;
  }
  for(;;) {
    vlinker.tick(); obd.tick(vlinker);
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
void setup() {
  Serial.begin(115200); delay(50);
  Serial.println("[FW] MINI-SEYYANEN-OBD-2026-11-21-R3");
  Serial.printf("[BOOT] Bluetooth Classic SPP=STARTING adapter=%s ECU protocol=AUTO then KWP fallback\n",
                Config::VlinkerDisplayName);
  display.begin();
  if(xTaskCreatePinnedToCore(bluetoothTask,"obd-spp",8192,nullptr,1,nullptr,0)!=pdPASS)
    Serial.println("Bluetooth worker task could not start; display remains available");
}
void loop() {
  display.pollSwipe();
  DisplayValue rows[5]; char values[5][24];
  ObdValue latest[5]; obd.snapshot(latest);
  for(size_t i=0;i<5;i++) {
    bool current=latest[i].valid && (uint32_t)(millis()-latest[i].updatedAt)<=Config::StaleTimeoutMs;
    if(!current) strlcpy(values[i],"NONE",sizeof(values[i]));
    else if(i==0 || i==2) snprintf(values[i],sizeof(values[i]),"%.0f",latest[i].value);
    else snprintf(values[i],sizeof(values[i]),"%.1f",latest[i].value);
    rows[i]={latest[i].name,values[i],latest[i].unit};
  }
  char btStatus[48];
  if(vlinker.state()==LinkState::Connected)
    snprintf(btStatus,sizeof(btStatus),"CONNECTED %s",Config::VlinkerDisplayName);
  else if(vlinker.state()==LinkState::Connecting) strlcpy(btStatus,"CONNECTING",sizeof(btStatus));
  else strlcpy(btStatus,"DISCONNECTED",sizeof(btStatus));

  const char* ecuStatus="ECU: DISCONNECTED";
  switch(obd.ecuState()) {
    case EcuState::AdapterInitializing: ecuStatus="ECU: ADAPTER"; break;
    case EcuState::Searching: ecuStatus="ECU: SEARCHING"; break;
    case EcuState::Connected: ecuStatus="ECU: CONNECTED"; break;
    case EcuState::ConnectedNoTargets: ecuStatus="ECU: NO TARGET PID"; break;
    case EcuState::ConnectedAmbiguous: ecuStatus="ECU: AMBIGUOUS"; break;
    case EcuState::Failed: ecuStatus="ECU: FAILED"; break;
    case EcuState::Disconnected: default: break;
  }
  display.render(rows,btStatus,ecuStatus);
  delay(8);
}
