import time
import sys
from motor import AutoExpertEngine, MOCK_AVAILABLE
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_reset():
    print("🚀 TEST: Simulation Reset Mechanism", flush=True)
    print(f"Global MOCK_AVAILABLE: {MOCK_AVAILABLE}", flush=True)
    
    engine = AutoExpertEngine()
    
    # 1. Connect
    print("1. Connecting...", flush=True)
    if not engine.baglan():
        print("❌ Connection Failed", flush=True)
        return

    print(f"Engine Ser Type: {type(engine.ser)}", flush=True)

    # 2. Simulate User Delay
    delay = 5
    print(f"2. Simulating {delay}s menu delay...", flush=True)
    time.sleep(delay)
    
    # Check data BEFORE reset
    print("3. Reading data BEFORE reset...", flush=True)
    data_before = engine.tek_veri_oku("UNKNOWN")
    rpm_before = data_before.get("RPM", 0)
    print(f"   RPM Before: {rpm_before} (Expected > 0)", flush=True)
    
    # 3. RESET
    print("4. Resetting Simulation...", flush=True)
    engine.simulasyonu_sifirla()
    sys.stdout.flush()
    time.sleep(1) # Give it a moment to process
    
    # Check data AFTER reset
    print("5. Reading data AFTER reset...", flush=True)
    data_after = engine.tek_veri_oku("UNKNOWN")
    rpm_after = data_after.get("RPM", 0)
    print(f"   RPM After: {rpm_after} (Expected 0)", flush=True)
    
    if rpm_after == 0 and rpm_before > 0:
        print("\n✅ TEST PASSED", flush=True)
    else:
        print("\n❌ TEST FAILED", flush=True)
        print(f"   Before: {rpm_before}, After: {rpm_after}", flush=True)

if __name__ == "__main__":
    test_reset()
