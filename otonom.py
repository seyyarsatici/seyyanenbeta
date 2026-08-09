import google.generativeai as genai
import time
import re

# ==========================================
# 1. API VE AYARLAR
# ==========================================
API_KEY = "BURAYA_API_ANAHTARINI_YAZ"
genai.configure(api_key=API_KEY)
MODEL_NAME = "gemini-1.5-pro" # veya 2.5 pro

# Otonom döngünün kaç kere tekrar edeceğini (tartışacağını) belirliyoruz
MAX_DONGU = 3 

# ==========================================
# 2. DOSYA OKUMA VE KAYDETME
# ==========================================
def dosya_oku(dosya_yolu):
    try:
        with open(dosya_yolu, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""

def dosya_kaydet(dosya_yolu, icerik):
    with open(dosya_yolu, 'w', encoding='utf-8') as f:
        f.write(icerik)

def kodu_ayikla(metin):
    match = re.search(r'```python\n(.*?)\n```', metin, re.DOTALL)
    return match.group(1).strip() if match else metin.strip()

# Dosyaları alıyoruz
mevcut_ui = dosya_oku("main_ui.py")
mevcut_algoritma = dosya_oku("expert_system.py")

# ==========================================
# 3. YAPILACAK GÖREV (SENİN İSTEĞİN)
# ==========================================
GOREV_TANIMI = """
1. `main_ui.py` dosyasına gerçek zamanlı OBD verilerini asenkron (QThread) okuyacak bir 'Bağlantı' mekanizması ekle.
2. `expert_system.py` dosyasındaki analiz sonuçlarını UI üzerinde daha detaylı gösterecek bir panel (Matplotlib grafikleriyle) oluştur.
"""

print("🚀 SEYYANEN OTONOM AI HABERLEŞME AĞI BAŞLATILDI...\n")

# ==========================================
# 4. AJANLARIN TANIMLANMASI
# ==========================================
coder_ajan = genai.GenerativeModel(
    model_name=MODEL_NAME,
    system_instruction="Sen usta bir PyQt6 ve Veri Bilimi geliştiricisisin. Görevin, sana verilen kodu istenen hedeflere göre sıfırdan ve hatasız yazmaktır. Sadece Python kodu üretirsin."
)

reviewer_ajan = genai.GenerativeModel(
    model_name=MODEL_NAME,
    system_instruction="Sen çok katı bir Senior Yazılım Mimarı ve Kalite Kontrol (QA) uzmanısın. Yazılımcıdan (Coder) gelen kodu UI donması, PyQt6 hataları veya mantık hataları için denetlersin. Eğer kodda hata varsa hataları detaylıca raporla ve 'SONUÇ: RED' yaz. Eğer kod kusursuzsa ve görevi tam yapıyorsa 'SONUÇ: ONAY' yaz."
)

# ==========================================
# 5. OTONOM HABERLEŞME DÖNGÜSÜ (LOOP)
# ==========================================
dongu = 1
gecmis_elestiri = "" # Denetçinin bir önceki turdaki fırçaları

while dongu <= MAX_DONGU:
    print(f"🔄 --- DÖNGÜ {dongu}/{MAX_DONGU} BAŞLIYOR ---")
    
    # ----------------------------------------------------
    # ADIM A: CODER KODU YAZAR / DÜZELTİR
    # ----------------------------------------------------
    print("💻 [YAZILIMCI AI]: Görev üzerinde çalışıyor ve kodu yazıyor...")
    
    coder_prompt = f"""
    GÖREV: {GOREV_TANIMI}
    
    MEVCUT main_ui.py KODU:
    {mevcut_ui}
    
    MEVCUT expert_system.py KODU:
    {mevcut_algoritma}
    
    DENETÇİNİN (REVIEWER) BİR ÖNCEKİ ELEŞTİRİSİ (Varsa bunları kesinlikle düzelt!):
    {gecmis_elestiri}
    
    Bana `main_ui.py`'nin son ve mükemmel halini ver.
    """
    
    coder_cevap = coder_ajan.generate_content(coder_prompt)
    yeni_ui_kodu = kodu_ayikla(coder_cevap.text)
    
    time.sleep(2) # API limitine takılmamak için
    
    # ----------------------------------------------------
    # ADIM B: REVIEWER (DENETÇİ) KODU KONTROL EDER
    # ----------------------------------------------------
    print("🛡️ [DENETÇİ AI]: Yazılımcının kodunu test ediyor ve mantık hatalarını arıyor...")
    
    reviewer_prompt = f"""
    Yazılımcı aşağıdaki UI kodunu yazdı. GÖREV şuydu: {GOREV_TANIMI}
    
    YAZILAN KOD:
    {yeni_ui_kodu}
    
    Bu kodu incele. Threading doğru yapılmış mı? Hata var mı? 
    Raporunu yaz. En sona kesinlikle 'SONUÇ: ONAY' veya 'SONUÇ: RED' yaz.
    """
    
    reviewer_cevap = reviewer_ajan.generate_content(reviewer_prompt)
    inceleme_raporu = reviewer_cevap.text
    print(f"📋 DENETÇİ RAPORU:\n{inceleme_raporu}\n")
    
    # ----------------------------------------------------
    # ADIM C: KARAR MEKANİZMASI
    # ----------------------------------------------------
    if "SONUÇ: ONAY" in inceleme_raporu.upper():
        print("✅ [BAŞARILI]: Denetçi kodu onayladı! Otonom sistem döngüden çıkıyor.")
        dosya_kaydet("main_ui_GELISTIRILMIS.py", yeni_ui_kodu)
        print("📁 Yeni kod 'main_ui_GELISTIRILMIS.py' olarak kaydedildi.")
        break
    else:
        print("❌ [REDDEDİLDİ]: Denetçi hata buldu. Kod düzeltme için Yazılımcıya geri gönderiliyor...")
        gecmis_elestiri = inceleme_raporu # Eleştiriyi yazılımcıya besle
        dongu += 1
        time.sleep(2)

if dongu > MAX_DONGU:
    print("⚠️ Maksimum döngüye ulaşıldı ancak Denetçi kodu onaylamadı. Son hali yinede kaydediliyor.")
    dosya_kaydet("main_ui_DEBUG.py", yeni_ui_kodu)

print("🏁 Otonom Haberleşme Sistemi kapandı.")