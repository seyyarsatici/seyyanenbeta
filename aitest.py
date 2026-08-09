import genai
import os

# Anahtarı çevre değişkeninden veya doğrudan ayarla
# Prodüksiyonda: os.getenv("GEMINI_API_KEY") kullanılmalı
api_key = os.getenv("GEMINI_API_KEY", "AIzaSyB3dVevhZ6HLiF0KH4DmpaukuWzxVNJWOI")

try:
    genai.configure(api_key=api_key)
    
    print("🔍 Senin hesabına tanımlı modeller listeleniyor...\n")
    # list_models() kütüphane güncellendiği için artık çalışacaktır
    available_models = genai.list_models()
    
    found = False
    for m in available_models:
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ Kullanılabilir Model: {m.name}")
            found = True
            
    if not found:
        print("❌ Hesabına tanımlı hiçbir model bulunamadı!")
        
except Exception as e:
    # 400 hatası gelirse anahtarı kontrol et
    print(f"🔥 HATA: {e}")