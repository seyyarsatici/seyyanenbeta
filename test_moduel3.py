#!/usr/bin/env python3
"""
Test senaryosu: Modül 3 (Expert System ve Raporlama) işlevlerini doğrula
"""

import os
import sys
import json
from pathlib import Path

# Test dizini
test_dir = Path(__file__).parent
print(f"[TEST] Test dizini: {test_dir}")

# test_telemetry.csv var mı?
test_csv = test_dir / "test_telemetry.csv"
if test_csv.exists():
    print(f"✅ Test dosyası mevcut: {test_csv}")
else:
    print(f"❌ Test dosyası bulunamadı: {test_csv}")
    sys.exit(1)

# history.json yoksa, ilk açılıştır
history_file = test_dir / "history.json"
if not history_file.exists():
    print(f"[TEST] history.json oluşturuluyor...")
    history_data = {"files": [str(test_csv)]}
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)
    print(f"✅ history.json oluşturuldu")

# PDF dosyası kontrolü
pdf_name = f"rapor_{test_csv.stem}.pdf"
pdf_path = test_dir / pdf_name
print(f"\n[TEST] PDF dosyası yolu: {pdf_path}")
print(f"[TEST] PDF mevcut mu? {pdf_path.exists()}")

# history.json içeriğini göster
with open(history_file, 'r', encoding='utf-8') as f:
    history = json.load(f)
print(f"\n[TEST] history.json içeriği:")
print(json.dumps(history, indent=2, ensure_ascii=False))

print(f"\n[TEST] Tüm hazırlıklar tamamlandı!")
print(f"[TEST] Uygulamayı çalıştırabilirsiniz: python main_ui.py")
