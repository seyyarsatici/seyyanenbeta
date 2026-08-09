import re

filepath = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Part 1: Insert uzman_sistem_analizi before detayli_parca_analizi
expert_system_code = """def uzman_sistem_analizi(kayitlar, profil):
    teshis_sonuclari = set()
    if not kayitlar:
        return ["Yetersiz veri (Kayıt yok)"]
        
    for data in kayitlar:
        rpm = data.get("RPM")
        map_kpa = data.get("MAP")
        ltft = data.get("LTFT")
        stft = data.get("STFT")
        o2 = data.get("O2_B1S1")
        tps = data.get("TPS")
        speed = data.get("SPEED")
        ect = data.get("ECT")
        time_elapsed = data.get("Time", 0)
        
        # Sadece motor çalışıyorsa değerlendir
        if rpm is None or rpm < 400:
            continue
            
        # 1. Vakum Kaçağı veya Emme Sızıntısı
        if rpm < 1000 and map_kpa is not None and map_kpa > 45:
            if ltft is not None and ltft > 12:
                teshis_sonuclari.add("Olası Vakum Kaçağı: Rölantide aşırı vakum kaybı (MAP yüksek) ve ECU sürekli yakıt ekliyor (LTFT > %12).")
        
        # 2. Zayıf Yakıt Pompası / Basıncı
        if rpm > 2000 and tps is not None and tps > 20:
            toplam_trim = (ltft if ltft is not None else 0) + (stft if stft is not None else 0)
            if toplam_trim > 20 and o2 is not None and o2 < 0.2:
                teshis_sonuclari.add("Zayıf Yakıt Pompası / Filtresi: Yük altında ECU aşırı yakıt istiyor ancak oksijen sensörü (O2) fakir karışım gösteriyor.")
                
        # 3. Kirli / Hatalı MAF
        if rpm < 2000 and map_kpa is not None and map_kpa < 35:
            if ltft is not None and 8 < ltft < 18:
                teshis_sonuclari.add("Kirli MAF Sensörü: Manifold basıncı (MAP) normal olmasına rağmen uzun vadeli yakıt trimi (LTFT) yüksek.")
                
        # 4. EGR Açık Kalması (Kaçak)
        if rpm < 1000 and map_kpa is not None and map_kpa > 50:
            if stft is not None and ltft is not None and abs(stft + ltft) < 8:
                teshis_sonuclari.add("EGR Valfi Açık Kalmış (Sızıntı): Rölantide manifolta egzoz gazı giriyor (MAP çok yüksek) ancak yakıt trimi dengeli.")
                
        # 5. Katalitik Konvertör Tıkanıklığı
        if rpm > 2500 and tps is not None and tps > 30 and map_kpa is not None and map_kpa > 80:
            if ltft is not None and abs(ltft) < 10:
                teshis_sonuclari.add("Olası Tıkalı Katalitik Konvertör: Yüksek devir ve yükte manifolt basıncı düşemiyor (Egzoz çıkamadığı için basınç yığılıyor).")
                
        # 6. Ateşleme Sorunu / Misfire
        if stft is not None and stft > 20 and o2 is not None and o2 < 0.2:
            if rpm < 2000:
                teshis_sonuclari.add("Olası Ateşleme Sorunu (Bobin/Buji): Yanmamış oksijen egzoza atıldığı için sensör fakir algılıyor, ECU anlık yakıt (STFT) pompalıyor.")
                
        # 7. İşeyen / Sızdıran Enjektör
        if ltft is not None and ltft < -15:
            teshis_sonuclari.add("Enjektör Sızdırması / Zengin Karışım: Motor beyni sürekli yakıt kısmaya çalışıyor (LTFT < -%15).")
            
        # 8. Açık Kalan Termostat
        if time_elapsed > 600 and ect is not None and ect < 75:
            teshis_sonuclari.add("Termostat Açık Kalmış: Motor 10 dakikadan uzun süredir çalışmasına rağmen ideal sıcaklığa (75+ °C) ulaşamadı.")

    # Dizel filtreleme (Dizelde MAP/Trim ilişkisi farklı çalışır)
    if profil and profil.yakit_tipi.upper() == "DIESEL":
        teshis_sonuclari = {t for t in teshis_sonuclari if not any(x in t for x in ["Vakum Kaçağı", "Kirli MAF", "Enjektör Sızdırması", "Ateşleme Sorunu"])}
        if not teshis_sonuclari:
            teshis_sonuclari.add("Dizel motor mekaniği mevcut Mode01 parametreleriyle olağan görünüyor.")
            
    if not teshis_sonuclari:
        teshis_sonuclari.add("Motorun temel sensör ilişkilerinde belirgin bir mekanik / elektronik anormallik tespit edilmedi (Mükemmel Uyum).")
        
    return list(teshis_sonuclari)

def detayli_parca_analizi"""

content = content.replace("def detayli_parca_analizi", expert_system_code)

# Part 2: Update JSON payload compilation
old_payload = 'rapor_tam = {**meta, "Analiz": detayli_karne, "Asamalar": asamali_rapor, "Log": kayitlar}'
new_payload = '''        uzman_sonuclari = uzman_sistem_analizi(kayitlar, profil)
        rapor_tam = {**meta, "Analiz": detayli_karne, "Uzman_Sistem_Teshisi": uzman_sonuclari, "Asamalar": asamali_rapor, "Log": kayitlar}'''

content = content.replace(old_payload, new_payload)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Implementation complete.")
