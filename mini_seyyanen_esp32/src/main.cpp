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
  Serial.println("[FW] MINI-SEYYANEN-OBD-2026-11-22-R5");
  Serial.printf("[BOOT] Bluetooth Classic SPP=STARTING adapter=%s ECU discovery=KWP-fast,KWP-5baud,ISO9141,AUTO\n",
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
  display.render(rows,vlinker.state(),obd.ecuState());
  delay(8);
}
