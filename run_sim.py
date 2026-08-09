import sys
import builtins
import time
import threading

# Mock input to avoid blocking
input_responses = [
    "",    # Pre-flight onay (Enter)
    "",    # Araç tipi onay (Enter = Evet)
    "",    # Ağırlık onay (Enter = 1350kg)
    "1",   # Kasa tipi (1=Sedan)
]

def mock_input(prompt=None):
    if input_responses:
        return input_responses.pop(0)
    return ""

builtins.input = mock_input

print("🚀 SİMÜLASYON BAŞLATILIYOR (V90)...")
start_time = time.time()

# Run main
try:
    import main
    
    # Run in a thread to allow timeout kill if needed
    t = threading.Thread(target=main.rapor_olustur)
    t.start()
    
    # 25 saniye çalışsın (KOEO 5s + CRANK 3s + WARMUP 7s + LOAD 10s)
    t.join(timeout=25)
    
    print("\n✅ Simülasyon Süresi Doldu.")
    
except Exception as e:
    print(f"\n❌ SİMÜLASYON HATASI: {e}")
    sys.exit(1)
