import time
import json
import statistics
import os
import logging
from dataclasses import dataclass, field

# --- V70: GERÇEK vLinker MC+ DONANIMI ---
from motor import AutoExpertEngine 
from dashboard import Dashboard
from expert_system import DiagnosticExpert

try:
    from raporlayici import rapor_olustur_pdf
    PDF_VAR = True
except ImportError:
    PDF_VAR = False
    print("📄 PDF modülü (raporlayici.py) bulunamadı, rapor sadece JSON olarak kaydedilecek.")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "V92 - Production Ready"

# ============================================================
# DIREKTIF 1+2: VehicleProfile Dataclass & MOTOR_KODU_DB
# Statik veritabanı YOK. Her araç motor koduna özel fabrika verisi.
# ============================================================
@dataclass
class VehicleProfile:
    motor_kodu: str
    marka: str
    aciklama: str
    yakit_tipi: str          # "DIESEL" | "GASOLINE" | "TURBO"
    max_rpm: int
    redline: int
    idle_rpm: int
    hedef_ect: int
    bore_mm: float = 0.0
    stroke_mm: float = 0.0
    silindir_adedi: int = 4
    displacement_cc: float = 0.0
    kompresyon_orani: float = 0.0
    lastik_eni: int = 0
    lastik_profil: int = 0
    lastik_jant: int = 0
    kaynak: str = "Bilinmiyor"

    @property
    def fuel_type_display(self):
        return {"DIESEL": "Dizel", "GASOLINE": "Benzin (Atm)", "TURBO": "Benzin (Turbo)"}.get(self.yakit_tipi, self.yakit_tipi)

    def to_dict(self):
        return {
            "Tip": self.yakit_tipi, "MaxRPM": self.max_rpm,
            "Redline": self.redline, "HedefECT": self.hedef_ect,
            "Bore": self.bore_mm, "Stroke": self.stroke_mm,
            "Displacement": self.displacement_cc, "Kompresyon": self.kompresyon_orani
        }


# Fabrika verileri — çapraz kaynak: auto-data.net, ultimatespecs.com
MOTOR_KODU_DB = {
    # --- GM / Opel / Chevrolet ---
    "Z18XER":  VehicleProfile("Z18XER","OPEL","1.8 16V","GASOLINE",6800,6500,750,90,80.5,88.2,4,1796,10.5,kaynak="auto-data.net"),
    "Z16XER":  VehicleProfile("Z16XER","OPEL","1.6 16V","GASOLINE",6500,6200,800,90,79.0,81.5,4,1598,10.5,kaynak="auto-data.net"),
    "Z16XEP":  VehicleProfile("Z16XEP","OPEL","1.6 16V Twinport","GASOLINE",6500,6200,780,90,79.0,81.5,4,1598,10.5,kaynak="auto-data.net"),
    "Z14XEP":  VehicleProfile("Z14XEP","OPEL","1.4 16V Twinport","GASOLINE",6500,6200,820,90,73.4,83.0,4,1364,10.5,kaynak="auto-data.net"),
    "Z20NET":  VehicleProfile("Z20NET","OPEL","2.0 Turbo","TURBO",6400,6000,750,100,86.0,86.0,4,1998,8.8,kaynak="auto-data.net"),
    "Z19DTH":  VehicleProfile("Z19DTH","OPEL","1.9 CDTI 150hp","DIESEL",4500,4300,820,90,82.0,90.4,4,1910,17.5,kaynak="auto-data.net"),
    "Z17DTH":  VehicleProfile("Z17DTH","OPEL","1.7 CDTI","DIESEL",4200,4000,850,85,79.0,86.0,4,1686,18.0,kaynak="auto-data.net"),
    "LDE":     VehicleProfile("LDE","CHEVROLET","1.4 ECOTEC","GASOLINE",6500,6200,750,90,73.4,83.5,4,1364,10.5,kaynak="auto-data.net"),
    "LXT":     VehicleProfile("LXT","CHEVROLET","1.2 ECOTEC","GASOLINE",6000,5800,800,90,73.4,73.0,4,1242,10.5,kaynak="auto-data.net"),
    # --- VW / AUDI / SKODA / SEAT ---
    "BXE":     VehicleProfile("BXE","VW","1.9 TDI 105hp","DIESEL",4600,4400,820,85,79.5,95.5,4,1896,19.5,kaynak="ultimatespecs.com"),
    "BMN":     VehicleProfile("BMN","VW","2.0 TDI 170hp","DIESEL",4400,4200,800,90,81.0,95.5,4,1968,18.5,kaynak="ultimatespecs.com"),
    "BKD":     VehicleProfile("BKD","VW","2.0 TDI 140hp","DIESEL",4400,4200,800,88,81.0,95.5,4,1968,18.5,kaynak="ultimatespecs.com"),
    "CAXA":    VehicleProfile("CAXA","VW","1.4 TSI 122hp","TURBO",6500,6200,720,95,76.5,75.6,4,1390,10.5,kaynak="auto-data.net"),
    "CBZA":    VehicleProfile("CBZA","VW","1.2 TSI 105hp","TURBO",5500,5200,750,95,71.0,76.0,4,1197,10.5,kaynak="auto-data.net"),
    "BZB":     VehicleProfile("BZB","VW","1.8 TSI 160hp","TURBO",6200,5900,720,98,82.5,84.1,4,1798,9.6,kaynak="auto-data.net"),
    "BVY":     VehicleProfile("BVY","VW","2.0 FSI 150hp","GASOLINE",6500,6200,720,92,82.5,92.8,4,1984,12.0,kaynak="auto-data.net"),
    # --- TOYOTA ---
    "1NZFE":   VehicleProfile("1NZFE","TOYOTA","1.5 VVT-i","GASOLINE",6200,5900,700,90,75.0,84.7,4,1497,10.5,kaynak="auto-data.net"),
    "2NZFE":   VehicleProfile("2NZFE","TOYOTA","1.3 VVT-i","GASOLINE",6000,5700,700,90,72.0,84.7,4,1298,10.5,kaynak="auto-data.net"),
    "1ZZFE":   VehicleProfile("1ZZFE","TOYOTA","1.8 VVT-i","GASOLINE",6400,6200,700,90,79.0,91.5,4,1794,10.0,kaynak="auto-data.net"),
    "2ZRFXE":  VehicleProfile("2ZRFXE","TOYOTA","1.8 Hybrid","GASOLINE",5200,5000,0,60,80.5,88.3,4,1798,13.0,kaynak="auto-data.net"),
    "1KD":     VehicleProfile("1KD","TOYOTA","3.0 D-4D","DIESEL",3800,3600,700,88,96.0,103.0,4,2982,17.9,kaynak="auto-data.net"),
    "2KD":     VehicleProfile("2KD","TOYOTA","2.5 D-4D","DIESEL",3800,3600,750,88,92.0,93.8,4,2494,18.5,kaynak="auto-data.net"),
    # --- FIAT / ALFA ---
    "199A2000":VehicleProfile("199A2000","FIAT","1.3 MultiJet","DIESEL",4000,3800,950,80,69.6,82.0,4,1248,17.6,kaynak="auto-data.net"),
    "955A3000":VehicleProfile("955A3000","FIAT","1.6 MultiJet","DIESEL",4200,4000,880,82,79.0,80.5,4,1598,16.8,kaynak="auto-data.net"),
    "199A6000":VehicleProfile("199A6000","FIAT","1.4 Fire","GASOLINE",6000,5700,850,90,72.0,84.0,4,1368,9.8,kaynak="auto-data.net"),
    # --- RENAULT ---
    "K9K":     VehicleProfile("K9K","RENAULT","1.5 dCi","DIESEL",4500,4200,780,85,76.0,80.5,4,1461,18.0,kaynak="auto-data.net"),
    "F4R":     VehicleProfile("F4R","RENAULT","2.0 16V","GASOLINE",6700,6500,750,90,82.7,93.0,4,1998,9.8,kaynak="auto-data.net"),
    "K4M":     VehicleProfile("K4M","RENAULT","1.6 16V","GASOLINE",6500,6200,750,90,79.5,80.5,4,1598,9.5,kaynak="auto-data.net"),
    "M9R":     VehicleProfile("M9R","RENAULT","2.0 dCi","DIESEL",4000,3800,750,85,84.0,90.0,4,1995,16.5,kaynak="auto-data.net"),
    # --- FORD ---
    "HHDA":    VehicleProfile("HHDA","FORD","1.6 TDCi","DIESEL",4500,4200,800,85,73.7,88.0,4,1499,18.0,kaynak="auto-data.net"),
    "AODA":    VehicleProfile("AODA","FORD","2.0 TDCi","DIESEL",4000,3800,750,88,85.0,88.0,4,1998,17.0,kaynak="auto-data.net"),
    "PNDA":    VehicleProfile("PNDA","FORD","1.0 EcoBoost","TURBO",6000,5700,720,95,74.0,61.5,3,998,10.0,kaynak="auto-data.net"),
    # --- BMW ---
    "N47D20":  VehicleProfile("N47D20","BMW","2.0d","DIESEL",4500,4300,700,90,84.0,90.0,4,1995,16.5,kaynak="ultimatespecs.com"),
    "N52B25":  VehicleProfile("N52B25","BMW","2.5i","GASOLINE",7000,6700,700,95,85.0,88.0,6,2497,10.7,kaynak="ultimatespecs.com"),
    # --- HYUNDAI / KIA ---
    "G4FC":    VehicleProfile("G4FC","HYUNDAI","1.6 CVVT","GASOLINE",6500,6300,700,90,77.0,85.4,4,1591,10.5,kaynak="auto-data.net"),
    "D4FB":    VehicleProfile("D4FB","HYUNDAI","1.6 CRDi","DIESEL",4000,3800,800,85,77.2,85.4,4,1582,17.3,kaynak="auto-data.net"),
    "G4NA":    VehicleProfile("G4NA","HYUNDAI","2.0 MPI","GASOLINE",6500,6300,700,90,86.0,86.0,4,1999,10.5,kaynak="auto-data.net"),
}

# BILINMEYEN ARAÇ İÇİN VARSAYILAN PROFIL — kullanıcı onayı zorunlu
def varsayilan_profil(yakit_tipi="GASOLINE") -> VehicleProfile:
    if yakit_tipi == "DIESEL":
        return VehicleProfile("BILINMIYOR","BILINMIYOR","(Varsayılan Dizel)","DIESEL",4800,4500,800,88,kaynak="Varsayılan — Onay Gerekli")
    elif yakit_tipi == "TURBO":
        return VehicleProfile("BILINMIYOR","BILINMIYOR","(Varsayılan Turbo)","TURBO",6500,6000,750,98,kaynak="Varsayılan — Onay Gerekli")
    else:
        return VehicleProfile("BILINMIYOR","BILINMIYOR","(Varsayılan Benzin)","GASOLINE",6800,6500,750,92,kaynak="Varsayılan — Onay Gerekli")


class VINDecoder:
    """
    Direktif 1: VIN çözümleyici — Motor kodunu VIN'den çıkarır, MOTOR_KODU_DB ile çapraz doğrular.
    """
    # WMI → Marka eşleşmesi
    WMI_DB = {
        "1G1": "GM", "1G8": "GM", "KL1": "GM", "W0L": "OPEL", "W0V": "OPEL",
        "JT": "TOYOTA", "NMT": "TOYOTA", "SB1": "TOYOTA",
        "WF0": "FORD", "NM0": "FORD", "1FA": "FORD", "1FT": "FORD",
        "WVW": "VW", "WV1": "VW", "WV2": "VW", "WVG": "VW",
        "JHM": "HONDA", "NLA": "HONDA", "SHH": "HONDA",
        "ZFA": "FIAT", "NM4": "FIAT", "ZAR": "ALFA",
        "VF1": "RENAULT", "VF3": "PEUGEOT", "VF7": "CITROEN",
        "WBA": "BMW", "WBS": "BMW", "WBY": "BMW",
        "KMH": "HYUNDAI", "KNA": "KIA", "U5Y": "KIA",
        "TRU": "AUDI", "WAU": "AUDI", "WAP": "PORSCHE",
        "BF9": "FORD_TR", "NMTB": "TOYOTA_TR",
    }

    # (WMI, VIN[4:8] pattern) → motor kodu tahminleri
    ENGINE_HINT_MAP = {
        ("W0L", "Z18"): "Z18XER",
        ("W0L", "Z16"): "Z16XER",
        ("W0L", "Z14"): "Z14XEP",
        ("W0L", "Z20"): "Z20NET",
        ("W0L", "Z19"): "Z19DTH",
        ("W0L", "Z17"): "Z17DTH",
        ("W0V", "Z18"): "Z18XER",
        ("WVW", "BXE"): "BXE",
        ("WVW", "BMN"): "BMN",
        ("WVW", "BKD"): "BKD",
        ("WVW", "CAX"): "CAXA",
        ("WVW", "BZB"): "BZB",
        ("WVW", "BVY"): "BVY",
        ("JT", "1NZ"): "1NZFE",
        ("JT", "1ZZ"): "1ZZFE",
        ("JT", "2ZR"): "2ZRFXE",
        ("JT", "1KD"): "1KD",
        ("ZFA", "199"): "199A2000",
        ("VF1", "K9K"): "K9K",
        ("VF1", "F4R"): "F4R",
        ("VF1", "K4M"): "K4M",
    }

    YILLAR = {
        'A':2010,'B':2011,'C':2012,'D':2013,'E':2014,'F':2015,'G':2016,
        'H':2017,'J':2018,'K':2019,'L':2020,'M':2021,'N':2022,'P':2023,
        'R':2024,'S':2025,'1':2001,'2':2002,'3':2003,'4':2004,'5':2005,
        '6':2006,'7':2007,'8':2008,'9':2009,'0':2000
    }

    def coz(self, vin):
        bilgi = {
            "VIN": vin, "Marka": "BILINMIYOR", "Yil": "---",
            "MotorKodu": None, "Motor": "---",
            "ProfilBulundu": False
        }
        if len(vin) != 17:
            return bilgi

        # WMI (3 karakter, önce 4 sonra 3 sonra 2 başlık bak)
        wmi = vin[:3].upper()
        for length in [3, 2]:
            prefix = vin[:length].upper()
            for key, marka in self.WMI_DB.items():
                if prefix.startswith(key[:length]):
                    bilgi["Marka"] = marka
                    break
            if bilgi["Marka"] != "BILINMIYOR":
                break

        # Model Yılı (10. karakter, index 9)
        yil_char = vin[9].upper()
        bilgi["Yil"] = str(self.YILLAR.get(yil_char, "---"))

        # Motor Kodu tahmin: VIN[4:7] üzerinden ENGINE_HINT_MAP
        vin_engine_hint = vin[4:7].upper()
        motor_kodu = None

        # 1. Tam eşleşme: MOTOR_KODU_DB'de doğrudan ara
        if vin[4:12].upper() in MOTOR_KODU_DB:
            motor_kodu = vin[4:12].upper()
        elif vin[4:8].upper() in MOTOR_KODU_DB:
            motor_kodu = vin[4:8].upper()

        # 2. Hint map üzerinden ara
        if not motor_kodu:
            for (wmi_prefix, hint), kod in self.ENGINE_HINT_MAP.items():
                if vin.upper().startswith(wmi_prefix) and vin_engine_hint.startswith(hint[:3]):
                    motor_kodu = kod
                    break

        if motor_kodu and motor_kodu in MOTOR_KODU_DB:
            profil = MOTOR_KODU_DB[motor_kodu]
            bilgi["MotorKodu"] = motor_kodu
            bilgi["Motor"] = profil.aciklama
            bilgi["ProfilBulundu"] = True
        else:
            bilgi["MotorKodu"] = None
            bilgi["Motor"] = f"({vin_engine_hint}...) — Tanımsız"

        return bilgi


def manuel_profil_gir() -> VehicleProfile:
    """
    Direktif 4: Kullanıcı sadece yakıt tipi, max RPM ve rölanti RPM'i girer.
    Bore/stroke/kompresyon/displacement kullanıcıya sorulmaz; arka planda
    güvenli varsayılanlar atanır (ZeroDivision koruması).
    """
    from dashboard import Dashboard
    print(f"\n{Dashboard.CYAN}=== MANUEL MOTOR PROFİLİ GİRİŞİ ==={Dashboard.WHITE}")
    print(f"{Dashboard.YELLOW}Sadece temel bilgiler sorulacak, diğerleri otomatik atanır.{Dashboard.WHITE}\n")

    def ask(prompt, default, cast=str):
        try:
            v = input(f"  {prompt} [{default}]: ").strip()
            return cast(v) if v else cast(default)
        except:
            return cast(default)

    motor_kodu  = ask("Motor Kodu (orn: Z18XER)", "BILINMIYOR").upper()
    # Veritabanında var mı kontrol et
    if motor_kodu in MOTOR_KODU_DB:
        print(f"  {Dashboard.GREEN}✓ Veritabaninda bulundu: {MOTOR_KODU_DB[motor_kodu].aciklama}{Dashboard.WHITE}")
        return MOTOR_KODU_DB[motor_kodu]

    yakit_secim = ask("Yakit Tipi (1=Benzin 2=Dizel 3=Turbo)", "1")
    yakit_tipi  = {"2": "DIESEL", "3": "TURBO"}.get(yakit_secim, "GASOLINE")
    max_rpm     = ask("Max RPM", "6500" if yakit_tipi != "DIESEL" else "4500", int)
    idle_rpm    = ask("Rolanti RPM", "750" if yakit_tipi != "DIESEL" else "820", int)

    # Arka planda varsayılanlar — kullanıcıya sorulmaz
    # 0.0 atanır: bilinmeyen hacimle sahte VE hesabı yapılmasın
    bore_mm      = 0.0
    stroke_mm    = 0.0
    kompresyon   = 0.0
    displacement = 0.0
    redline      = int(max_rpm * 0.95)
    hedef_ect    = 88 if yakit_tipi == "DIESEL" else 90

    return VehicleProfile(
        motor_kodu=motor_kodu, marka="BILINMIYOR", aciklama="Manuel Giris",
        yakit_tipi=yakit_tipi, max_rpm=max_rpm, redline=redline,
        idle_rpm=idle_rpm, hedef_ect=hedef_ect,
        bore_mm=bore_mm, stroke_mm=stroke_mm, silindir_adedi=4,
        displacement_cc=displacement, kompresyon_orani=kompresyon,
        kaynak="Kullanici Girisi"
    )


def volumetrik_verimlilik_hesapla(maf_gs, rpm, displacement_cc, baro_kpa=101.3):
    """
    Direktif 2: Volumetrik Verimlilik = Gercek Hava / Teorik Hava
    maf_gs   : MAF sensoru (g/s)
    rpm      : Anlık devir
    displacement_cc: Motor hacmi (cc)
    Doner: VE % (0-120), None hata/veri yok
    """
    if not maf_gs or not rpm or not displacement_cc or displacement_cc == 0 or rpm < 200:
        return None
    rho_air = 1.2929 * (baro_kpa / 101.325)  # kg/m3
    # 4-zamanli: her devir basina 1/2 emme stroku; silindir sayisi hacim icinde
    maf_theory_gs = (rpm / 2 / 60) * (displacement_cc / 1e6) * rho_air * 1000
    if maf_theory_gs <= 0:
        return None
    return round((maf_gs / maf_theory_gs) * 100, 1)

# Madde 5: Sensör UID Etiket Tablosu
SENSOR_UID = {
    "RPM":           "[S101]",
    "SPEED":         "[S102]",
    "Voltaj":        "[S103]",
    "ECT":           "[S104]",
    "MAP":           "[S105]",
    "STFT":          "[S106]",
    "LTFT":          "[S107]",
    "TPS":           "[S108]",
    "LOAD":          "[S109]",
    "MAF":           "[S110]",
    "IAT":           "[S111]",
    "O2_B1S1":       "[S112]",
    "O2_B1S2":       "[S113]",
    "TIMING_ADV":    "[S114]",
    "FUEL_RAIL_PRESS": "[S115]",
    "EGR_CMD":       "[S116]",
    "EGR_ERROR":     "[S117]",
    "BARO":          "[S118]",
    "CAT_TEMP_B1S1": "[S119]",
    "OIL_TEMP":      "[S120]",
    "TORQUE":        "[S121]",
    "BOOST_PRESS":   "[S122]",
    "MIL":           "[S123]",
}

def dtc_uid(dtc_code):
    """Madde 5: DTC koduna [E2xx] formatında UID üret"""
    try:
        num = int(dtc_code[1:]) % 1000
        return f"[E{200 + num % 100:03d}]"
    except:
        return "[E???]"


def ai_prompt_hazirla(veriler, dtc_list, arac_bilgisi, detayli_karne={}, is_lpg=False):
    ect_vals = [d.get('ECT', 0) for d in veriler if d.get('ECT') is not None]
    ect_max = max(ect_vals) if ect_vals else "Veri Yok"
    # Madde 1: None korumalı LTFT ortalaması
    ltft_vals = [d.get('LTFT') for d in veriler if d.get('LTFT') is not None]
    ltft_avg = statistics.mean(ltft_vals) if ltft_vals else None
    # Madde 2: Dizel araçlarda LTFT/STFT desteklenmiyorsa N/A göster
    arac_tipi_hint = arac_bilgisi.get('YakitSistemi', '')
    is_diesel = 'DIZEL' in str(arac_tipi_hint).upper() or 'DIESEL' in str(arac_tipi_hint).upper()
    if is_diesel and ltft_avg is None:
        ltft_str = "DIZEL - TRIM DESTEKLENMIYOR (N/A)"
    else:
        ltft_str = f"%{ltft_avg:.1f}" if ltft_avg is not None else "Veri Yok"

    # Madde 5: DTC listesine UID ekle
    if dtc_list:
        ariza_txt = ', '.join(f"{dtc_uid(c)} {c}" for c in dtc_list)
    else:
        ariza_txt = "YOK"

    fiziksel = detayli_karne.get('FIZIKSEL', {})
    vib_idx = fiziksel.get('VibrasyonIndeksi', 0)
    isinma_verimi = fiziksel.get('IsinmaVerimi', 0)
    yakit_sapmasi = fiziksel.get('ToplamYakitSapmasi', 0)
    vakum_stab = fiziksel.get('VakumStabilitesi', 0)
    ve_pct = fiziksel.get('VolHacimselVerimlilik', None)

    # Direktif 3: LPG notu
    yakit_notu = (
        "YAKIT: LPG - Trim sapmalarini LPG kalibrasyon toleransi olarak degerlendirin. "
        "LPG'de %+/-20 trim dogal kabul edilir, ancak DTC varsa ve vibrasyon yuksekse sorun mekaniktir."
    ) if is_lpg else "YAKIT: Benzin/Dizel (Standart trim toleransi: +/- %10)"

    ve_str = f"{SENSOR_UID.get('MAF','[S110]')} VolumetrikVerimlilik: %{ve_pct}" if ve_pct else "VolumetrikVerimlilik: Veri yok (MAF/displacement eksik)"

    prompt = f"""
SEN UZMAN BIR OTOMOTIV BASMUHENDISIN.
Asagidaki analiz verilerini yorumlayarak musteri icin net, guven verici, teknik derinligi olan bir ozet yaz.

ARAC: {arac_bilgisi.get('Marka')} - {arac_bilgisi.get('Motor')} ({arac_bilgisi.get('Yil')})
{yakit_notu}

MUHENDISLIK BULGULARI:
1. {SENSOR_UID['RPM']} Motor Dengesizligi (Vibrasyon): {vib_idx:.2f} (Ref: <20 Mukemmel, >40 Kotu)
   Yorum: {'Purussuz Calisiyor' if vib_idx < 20 else 'Hafif Titresimli' if vib_idx < 40 else 'Sarsintili/Tekleme Var'}

2. {SENSOR_UID['STFT']}+{SENSOR_UID['LTFT']} Yakit Sistemi Sagligi: %{yakit_sapmasi:.1f} Sapma
   Durum: {'Mukemmel' if yakit_sapmasi < 5 else 'Kirli Enjekter/Sensor' if yakit_sapmasi < 15 else 'Arizali Yakit Sistemi'}

3. {SENSOR_UID['ECT']} Sogutma Performansi: {isinma_verimi:.1f} C/dk Isinma Hizi, Motor Suyu Max: {ect_max} C
4. {SENSOR_UID['MAP']} Mekanik Saglik (Vakum): %{vakum_stab:.1f} Dalgalanma
5. {ve_str}

KRITIK VERILER:
- {SENSOR_UID['LTFT']} Toplam Yakit Trim (LTFT+STFT): {ltft_str}
- Ariza Kodlari: {ariza_txt}

GOREVIN:
Verileri harmanlayarak aracin genel saglik durumunu 'Usta Agziyla' ama kurumsal bir dille anlat. Eger vibrasyon yuksekse atesleme/kulaklara dikkat cek. Yakit sapmasi varsa sensor temizligi veya kacak ihtimalini belirt. LPG araciysa trim sapmasini buna gore yorumla. Ariza kodu yoksa ve degerler iyiyse 'Kefil olunabilecek arac' vurgusu yap.
"""
    return prompt

def surus_asamasi_tespit(veri, profil, onceki_asama="UNKNOWN"):
    """
    Direktif 1: VehicleProfile ile çalışan 5-aşamalı state machine.
    profil: VehicleProfile dataclass (hedef_ect attribute kullanılır)
    """
    rpm = int(veri.get("RPM") or 0)
    ect = veri.get("ECT")
    tps = float(veri.get("TPS") or 0.0)
    load = float(veri.get("LOAD") or 0.0)

    # hedef_ect: VehicleProfile veya dict destegi
    if hasattr(profil, 'hedef_ect'):
        hedef_ect = profil.hedef_ect
    else:
        hedef_ect = profil.get('hedef_ect', 90)

    # LOAD / DYNO: Sadece motor VE ECT yeterince sıcaksa
    # Direktif 5: ECT < 75 ise motoru LOAD fazına sokma
    if (tps > 70 or load > 80) and rpm > 500:
        if ect is not None and ect < 75:
            # Soğuk motor uyarısı — LOAD'a geçiş engellendi
            pass  # WARMUP/HOT mantığına düş
        else:
            return "LOAD"

    # KOEO: Motor dönmüyor
    if rpm < 50:
        return "KOEO"

    # CRANKING
    if 50 <= rpm < 500:
        return "CRANKING"

    # RPM >= 500: HOT mu WARMUP mu?
    if rpm >= 500:
        if onceki_asama == "HOT":
            if ect is not None and ect >= 70:
                return "HOT"
        if ect is not None and ect >= hedef_ect - 5:
            return "HOT"
        return "WARMUP"

    return onceki_asama if onceki_asama != "UNKNOWN" else "KOEO"


def filtrele_outlier(veri, onceki_veri=None):
    """
    V72: Fiziksel Veri Filtreleme
    Fiziksel olarak imkansız veya hatalı "outlier" değerleri temizle
    Sınırların dışındaki değerler için önceki değeri kullan veya None ata
    """
    SINIRLAR = {
        'RPM': (0, 8000),           # Max 8000 RPM (redline üstü imkansız)
        'ECT': (-40, 130),          # Motor sıcaklığı -40°C ila 130°C
        'Voltaj': (8.0, 18.0),      # Akü voltajı makul aralık
        'TPS': (0, 100),            # Gaz kelebeği % değeri
        'LOAD': (0, 100),           # Motor yükü % değeri
        'MAP': (10, 120),           # Hava basıncı kPa
        'SPEED': (0, 300),          # Hız km/h (max 300 km/h)
        'IAT': (-40, 120),          # V97: Emme havası sıcaklığı (-40 to 120)
        'TFT': (-40, 150),          # Şanzıman yağı sıcaklığı
        'O2_B1S1': (0.0, 1.5),      # O2 Voltajı (0-1.5V)
    }
    
    temiz_veri = veri.copy()
    for key, (min_val, max_val) in SINIRLAR.items():
        if key in temiz_veri and temiz_veri[key] is not None:
            val = temiz_veri[key]
            if not (min_val <= val <= max_val):
                # Outlier tespit edildi
                if onceki_veri and key in onceki_veri and onceki_veri[key] is not None:
                    temiz_veri[key] = onceki_veri[key]  # Önceki geçerli değeri kullan
                else:
                    temiz_veri[key] = None  # Geçersiz kıl
    
    return temiz_veri


def detayli_parca_analizi(kayitlar, ariza_kodlari, arac_bilgisi, profil=None, is_lpg=False):
    """
    Direktif 1+2+3: VehicleProfile tabanli, LPG toleransli, VE hesapli analiz.
    profil: VehicleProfile dataclass (None ise eski arac_tipi string mantigi fallback)
    """
    if not kayitlar: return {}

    # Geri uyumluluk: eski string profil algı
    if profil is None:
        arac_tipi = "DIESEL" if arac_bilgisi.get('Yakit') == 'DIESEL' else "GASOLINE"
    elif isinstance(profil, str):
        arac_tipi = profil
        profil = None
    else:
        arac_tipi = profil.yakit_tipi  # VehicleProfile

    def get_stat(key, func=statistics.mean):
        # V96: Sıfır Toleransı - Sadece None filtrele (0 geçerli bir değerdir)
        vals = [d.get(key) for d in kayitlar if d.get(key) is not None]
        
        # V97.4: BARO Düzeltmesi (0'ları filtrele)
        if key == "BARO":
            vals = [v for v in vals if v > 0]
            
        if not vals: return None
        if func == max: return max(vals)
        if func == min: return min(vals)
        return statistics.mean(vals)
    
    def not_ver(parca, olculen, ref, puan, durum):
        return {"Parca": parca, "Olculen": str(olculen), "Referans": ref, "Puan": puan, "Durum": durum}

    karne = {}

    # --- 1. ELEKTRİK & ATEŞLEME ---
    v_min = get_stat("Voltaj", min)
    v_avg = get_stat("Voltaj")
    
    if v_min:
        status = "IYI" if v_min > 9.6 else "ZAYIF/BITIK"
        karne["AKU"] = not_ver("Akü (Marş)", f"{v_min:.2f} V", "> 9.6 V", 100 if v_min>9.6 else 40, status)
    
    if v_avg:
        status = "NORMAL" if 13.2 <= v_avg <= 14.8 else ("YUKSEK" if v_avg > 14.8 else "SARJ ETMIYOR")
        karne["ALT"] = not_ver("Alternatör", f"{v_avg:.2f} V", "13.2-14.8V", 100 if status=="NORMAL" else 40, status)

    # V94: Fiziksel Özellik Çıkarımı (Feature Engineering)
    # 0 ve None değerleri filtrele
    
    # 1. Vibrasyon İndeksi (Rölanti RPM σ)
    hot_idle_rpm = [d.get("RPM") for d in kayitlar if d.get("Phase") == "HOT" and d.get("RPM") and 600 < d.get("RPM") < 1200]
    vibrasyon_indeksi = statistics.stdev(hot_idle_rpm) if len(hot_idle_rpm) > 10 else 0
    
    # 2. Isınma Verimi (Warmup ΔECT/Δt)
    warmup_data = [d for d in kayitlar if d.get("Phase") == "WARMUP" and d.get("ECT") is not None]
    if len(warmup_data) > 10:
        delta_ect = warmup_data[-1]["ECT"] - warmup_data[0]["ECT"]
        delta_time = (warmup_data[-1]["Time"] - warmup_data[0]["Time"]) / 60 # Dakika
        isinma_verimi = delta_ect / delta_time if delta_time > 0 else 0
    else:
        isinma_verimi = 0
        
    # 3. Vakum Stabilitesi (Rölanti MAP σ/Avg)
    hot_idle_map = [d.get("MAP") for d in kayitlar if d.get("Phase") == "HOT" and d.get("MAP") and d.get("RPM") < 1200]
    if len(hot_idle_map) > 10:
        map_std = statistics.stdev(hot_idle_map)
        map_avg_val = statistics.mean(hot_idle_map)
        vakum_stabilitesi = (map_std / map_avg_val) * 100 if map_avg_val > 0 else 0
    else:
        vakum_stabilitesi = 0

    # 4. Toplam Yakıt Sapması (|STFT| + |LTFT|)
    # Madde 1+2: None korumalı hesap, dizel araçlarda None geliyor
    all_trims = [
        abs(d.get("STFT") or 0) + abs(d.get("LTFT") or 0)
        for d in kayitlar
        if d.get("STFT") is not None and d.get("LTFT") is not None
    ]
    toplam_yakit_sapmasi = statistics.mean(all_trims) if all_trims else 0

    # 5. Direktif 2: Volumetrik Verimlilik (MAF + RPM + displacement)
    displacement_cc = getattr(profil, 'displacement_cc', 0) if profil and not isinstance(profil, str) else 0
    baro_avg = statistics.mean([d.get('BARO') for d in kayitlar if d.get('BARO') and d.get('BARO') > 0] or [101.3])
    hot_load_recs = [d for d in kayitlar if d.get('Phase') in ('HOT', 'WARMUP', 'LOAD') and d.get('MAF') and d.get('RPM', 0) > 300]
    if hot_load_recs and displacement_cc > 0:
        ve_list = [
            volumetrik_verimlilik_hesapla(d['MAF'], d['RPM'], displacement_cc, baro_avg)
            for d in hot_load_recs
        ]
        ve_list = [v for v in ve_list if v is not None and 20 <= v <= 120]
        vol_verimlilik = round(statistics.mean(ve_list), 1) if ve_list else None
    else:
        vol_verimlilik = None

    # Karneye Ekle (Raporlayıcı kullanacak)
    karne["FIZIKSEL"] = {
        "VibrasyonIndeksi": vibrasyon_indeksi,
        "IsinmaVerimi": isinma_verimi,
        "VakumStabilitesi": vakum_stabilitesi,
        "ToplamYakitSapmasi": toplam_yakit_sapmasi,
        "VolHacimselVerimlilik": vol_verimlilik,  # Direktif 2
    }

    ign_status = "SAGLAM"
    ign_point = 100
    
    if vibrasyon_indeksi > 40:
        ign_status = "SERT TEKLEME"
        ign_point = 30
    elif vibrasyon_indeksi > 20:
        ign_status = "HAFİF TİTREŞİM"
        ign_point = 70
            
    karne["IGN"] = not_ver("Ateşleme/Stabilite", f"Vibrasyon {vibrasyon_indeksi:.1f}", "<20", ign_point, ign_status)

    # --- 2. SOĞUTMA & YAĞLAMA ---
    ect_max = get_stat("ECT", max)
    if ect_max:
        status = "NORMAL" if 75 <= ect_max <= 108 else ("HARARET" if ect_max > 108 else "SOĞUK")
        karne["THERM"] = not_ver("Termostat/ECT", f"{ect_max:.0f} C", "80-105 C", 100 if status=="NORMAL" else 50, status)

    oil_temp = get_stat("OIL_TEMP", max)
    if oil_temp:
        status = "NORMAL" if oil_temp < 115 else "YÜKSEK"
        karne["OIL"] = not_ver("Yağ Sıcaklığı", f"{oil_temp:.0f} C", "<115 C", 100 if status=="NORMAL" else 60, status)

    # --- 3. HAVA GİRİŞ SİSTEMİ ---
    map_avg = get_stat("MAP")
    if map_avg:
        # V90: Barometrik Düzeltme Varsa Kullan
        baro = get_stat("BARO") or 101.3
        corrected_map = map_avg - (101.3 - baro)
        karne["MAP"] = not_ver("MAP Sensörü", f"{int(corrected_map)} kPa", "20-100 kPa", 100, "NORMAL")

    maf_avg = get_stat("MAF")
    if maf_avg:
        # V98: Dizel vs Benzin MAF Referansları
        if arac_tipi == "DIZEL":
            ref_maf = "Rölanti: 6-18 g/s"
            status = "NORMAL" if 5 <= maf_avg <= 20 else "N/A"
        else:
            ref_maf = "Rölanti: 2-6 g/s"
            status = "NORMAL"
            
        karne["MAF"] = not_ver("MAF Sensörü", f"{maf_avg:.1f} g/s", ref_maf, 100, "OKUNDU")

    iat_val = get_stat("IAT")
    if iat_val:
        karne["IAT"] = not_ver("Emme Havası (IAT)", f"{iat_val:.0f} C", "Ortam + 10-30", 100, "NORMAL")

    tps_val = get_stat("TPS")
    if tps_val is not None:
        karne["TPS"] = not_ver("Gaz Kelebeği", f"%{int(tps_val)}", "0-100", 100, "TEPKİ VAR")

    # --- 4. YAKIT SİSTEMİ ---
    # Madde 1+2: None korumalı trim hesabı — Dizel araçlarda STFT/LTFT None döner
    ltft_raw = get_stat("LTFT")
    stft_raw = get_stat("STFT")

    # Direktif 4: Anlık sapma kontrolü (sadece ortalamaya bakma)
    stft_vals_all = [d.get("STFT") for d in kayitlar if d.get("STFT") is not None]
    ltft_vals_all = [d.get("LTFT") for d in kayitlar if d.get("LTFT") is not None]

    # Madde 2: Dizel araçlarda Trim desteklenmiyorsa N/A etiketi, puanlamamaya dahil etme
    if arac_tipi == "DIESEL" and ltft_raw is None and stft_raw is None:
        karne["FUEL_TRIM"] = not_ver(
            "[S106] Yakit Ayari (Trim)",
            "DIZEL - N/A",
            "Desteklenmiyor",
            100,  # Puanı kırma
            "DIESEL - TRIM DESTEKLENMIYOR"
        )
        # Puanlama ve sapma hesabına dahil etme
        total_trim = 0
    else:
        ltft = ltft_raw or 0
        stft = stft_raw or 0
        total_trim = ltft + stft  # Madde 1: None korumalı (or 0)

        # Direktif 4: Anlık sapma analizi — STFT veya LTFT anlık eşiği aşıyorsa öncelikli yorumla
        lpg_tol = 20 if is_lpg else 10   # LPG'de +-20 normal, benzinde +-10
        anlık_zengin = any(v < -lpg_tol for v in stft_vals_all) or any(v < -lpg_tol for v in ltft_vals_all)
        anlık_fakir  = any(v >  lpg_tol for v in stft_vals_all) or any(v >  lpg_tol for v in ltft_vals_all)

        if is_lpg and abs(total_trim) < lpg_tol and not anlık_zengin and not anlık_fakir:
            fuel_status = "LPG TOLERANSI"
            fuel_point = 75
        elif anlık_zengin or total_trim < -(lpg_tol):
            fuel_status = "ZENGIN KARISIM (Yakit Kisiliyor)"
            fuel_point = 40
        elif anlık_fakir or total_trim > lpg_tol:
            fuel_status = "FAKIR KARISIM (Yakit Ekleniyor)"
            fuel_point = 40
        elif abs(total_trim) > lpg_tol - 5:
            fuel_status = "SINIRDA"
            fuel_point = 65
        else:
            fuel_status = "NORMAL"
            fuel_point = 100

        karne["FUEL_TRIM"] = not_ver("[S106] Yakit Ayari (Trim)", f"%{total_trim:.1f}", f"+/- %{lpg_tol}", fuel_point, fuel_status)

    frp = get_stat("FUEL_RAIL_PRESS")
    if frp:
        karne["FRP"] = not_ver("Enjektör Basıncı", f"{frp:.1f} kPa", "Yüksek Basınç", 100, "NORMAL")
    
    # --- 5. EGZOZ VE EMİSYON ---
    # Oksijen Sensörleri
    # V92: Gelişmiş O2 Raporlama
    o2_b1s1 = get_stat("O2_B1S1")
    if o2_b1s1 is not None:
         # V98: Dizel O2 Toleransı
         if arac_tipi == "DIZEL":
              karne["O2_S1"] = not_ver("Lambda (O2)", f"{o2_b1s1:.2f} V", "Geniş Bant", 100, "OKUNDU")
         else:
             if o2_b1s1 == 0.0:
                 karne["O2_S1"] = not_ver("O2 Sensörü (Ön)", "0.00 V", "-", 100, "ISINIYOR / HAZIR DEĞİL")
             else:
                 karne["O2_S1"] = not_ver("O2 Sensörü (Ön)", f"{o2_b1s1:.2f} V", "0.1-0.9V", 100, "ÇALIŞIYOR")
         
    cat_temp = get_stat("CAT_TEMP_B1S1", max) or get_stat("CAT_TEMP", max)
    if cat_temp:
        status = "NORMAL" if 400 < cat_temp < 900 else "SOĞUK/AŞIRI"
        karne["CAT"] = not_ver("Katalizör Sıcaklığı", f"{cat_temp:.0f} C", "400-900 C", 100 if status=="NORMAL" else 60, status)

    egr_err = get_stat("EGR_ERROR")
    if egr_err is not None:
        karne["EGR"] = not_ver("EGR Valfi", f"Hata %{egr_err:.1f}", "< %10", 100 if abs(egr_err)<10 else 50, "NORMAL" if abs(egr_err)<10 else "HATALI")

    # --- 6. PERFORMANS VE YÜK ---
    load_max = get_stat("LOAD", max)
    if load_max:
         karne["ENG_LOAD"] = not_ver("Motor Yükü", f"%{int(load_max)}", "Max > %80", 100 if load_max > 70 else 60, "YÜK ALTINDA" if load_max > 70 else "DÜŞÜK")

    # --- 10. TURBO (VAR İSE) ---
    # V100: Crash-Proof Boost Hesabı (None Kontrolü)
    boost_press_val = get_stat("BOOST_PRESS", max)
    map_val = get_stat("MAP", max)
    
    if boost_press_val is not None:
        turbo_boost = boost_press_val
    elif map_val is not None and map_val > 100:
        turbo_boost = map_val - 100
    else:
        turbo_boost = 0
    
    if turbo_boost > 5: # Atmosferiklerde negatif çıkabilir
         karne["TURBO"] = not_ver("Turbo Basıncı", f"{turbo_boost:.0f} kPa", "Pozitif", 100, "BASIYOR")

    # Genel ECU Bilgisi
    dtc_count = len(ariza_kodlari)
    karne["DTC"] = not_ver("Arıza Kaydı (DTC)", f"{dtc_count} Adet", "0", 100 if dtc_count==0 else 40, "TEMİZ" if dtc_count==0 else "ARIZALI")

    return karne

def asamali_analiz_yap(kayitlar, phase_timestamps=None):
    """
    V70: MULTI-PHASE DRIVE ANALYSIS
    Analyzes recorded data by drive phase and returns phase-specific metrics.
    """
    if not kayitlar:
        return {}
    
    # Group records by phase
    phase_data = {}
    for record in kayitlar:
        phase = record.get("Phase", "UNKNOWN")
        if phase not in phase_data:
            phase_data[phase] = []
        phase_data[phase].append(record)
    
    # Analysis results
    analiz = {}
    
    # KOEO Analysis
    if "KOEO" in phase_data:
        koeo = phase_data["KOEO"]
        voltaj_vals = [r.get("Voltaj", 0) for r in koeo if r.get("Voltaj")]
        result = {
            "Sure": len(koeo) * 0.1,  # Approximate duration (0.1s per record)
            "BaslangicVoltaj": max(voltaj_vals) if voltaj_vals else 0,
            "Durum": "İyi" if (voltaj_vals and max(voltaj_vals) > 12.2) else "Düşük Voltaj"
        }
        # V70: Add timestamps if available
        if phase_timestamps and "KOEO" in phase_timestamps:
            result["BaslangicZaman"] = phase_timestamps["KOEO"]["start"]
            result["BitisZaman"] = phase_timestamps["KOEO"]["end"]
        analiz["KOEO"] = result
    
    # CRANKING Analysis
    if "CRANKING" in phase_data:
        cranking = phase_data["CRANKING"]
        voltaj_vals = [r.get("Voltaj", 0) for r in cranking if r.get("Voltaj")]
        result = {
            "Sure": len(cranking) * 0.1,
            "MinVoltaj": min(voltaj_vals) if voltaj_vals else 0,
            "Durum": "Sağlam" if (voltaj_vals and min(voltaj_vals) > 9.0) else "Zayıf Akü"
        }
        if phase_timestamps and "CRANKING" in phase_timestamps:
            result["BaslangicZaman"] = phase_timestamps["CRANKING"]["start"]
            result["BitisZaman"] = phase_timestamps["CRANKING"]["end"]
        analiz["CRANKING"] = result
    
    # WARMUP Analysis
    if "WARMUP" in phase_data:
        warmup = phase_data["WARMUP"]
        ect_vals = [r.get("ECT") for r in warmup if r.get("ECT") is not None]
        
        # Calculate warm-up rate (V70: Safe calculation)
        try:
            if len(ect_vals) >= 2:
                ect_start = ect_vals[0]
                ect_end = ect_vals[-1]
                duration_min = (len(warmup) * 0.1) / 60  # minutes
                warmup_rate = (ect_end - ect_start) / duration_min if duration_min > 0 else 0
            else:
                warmup_rate = 0
        except (ValueError, ZeroDivisionError):
            warmup_rate = 0
        
        result = {
            "Sure": len(warmup) * 0.1,
            "IsinmaHizi": f"{warmup_rate:.1f} °C/dk",
            "Durum": "Normal" if 10 <= warmup_rate <= 25 else ("Yavaş" if warmup_rate < 10 else "Hızlı")
        }
        if phase_timestamps and "WARMUP" in phase_timestamps:
            result["BaslangicZaman"] = phase_timestamps["WARMUP"]["start"]
            result["BitisZaman"] = phase_timestamps["WARMUP"]["end"]
        analiz["WARMUP"] = result
    
    # HOT Analysis (Idle Stability)
    if "HOT" in phase_data:
        hot = phase_data["HOT"]
        # Filter idle RPM (< 1200)
        rpm_idle = [r.get("RPM", 0) for r in hot if r.get("RPM", 0) > 0 and r.get("RPM", 0) < 1200]
        
        try:
            if len(rpm_idle) >= 3:
                rpm_std = statistics.stdev(rpm_idle)
            else:
                rpm_std = 0
        except (ValueError, statistics.StatisticsError):
            rpm_std = 0
        
        result = {
            "Sure": len(hot) * 0.1,
            "RolantiStd": int(rpm_std),
            "Durum": "Stabil" if rpm_std < 25 else ("Hafif Dalgalı" if rpm_std < 40 else "Tekleme")
        }
        if phase_timestamps and "HOT" in phase_timestamps:
            result["BaslangicZaman"] = phase_timestamps["HOT"]["start"]
            result["BitisZaman"] = phase_timestamps["HOT"]["end"]
        analiz["HOT"] = result
    
    # LOAD/DYNO Analysis (Power Loss Estimation)
    if "LOAD" in phase_data:
        load_data = phase_data["LOAD"]
        max_rpm = max([r.get("RPM", 0) for r in load_data]) if load_data else 0
        
        ltft_vals = [r.get("LTFT", 0) for r in load_data if r.get("LTFT") is not None]
        stft_vals = [r.get("STFT", 0) for r in load_data if r.get("STFT") is not None]
        
        try:
            avg_ltft = statistics.mean(ltft_vals) if ltft_vals else 0
            avg_stft = statistics.mean(stft_vals) if stft_vals else 0
        except (ValueError, statistics.StatisticsError):
            avg_ltft = 0
            avg_stft = 0
            
        total_trim = avg_ltft + avg_stft
        
        rpm_vals = [r.get("RPM", 0) for r in load_data if r.get("RPM", 0) > 1500]
        try:
            rpm_std = statistics.stdev(rpm_vals) if len(rpm_vals) > 2 else 0
        except (ValueError, statistics.StatisticsError):
            rpm_std = 0
        
        fuel_penalty = (abs(total_trim) / 5) * 2.5 if abs(total_trim) > 15 else 0
        ign_penalty = 5 if rpm_std > 40 else (2 if rpm_std > 25 else 0)
        
        total_power_loss = min(fuel_penalty + ign_penalty, 30)  # Cap at 30%
        
        result = {
            "Sure": len(load_data) * 0.1,
            "MaxRPM": max_rpm,
            "GucKaybi": f"%{total_power_loss:.0f}",
            "Durum": "İyi" if total_power_loss < 5 else ("Kabul Edilebilir" if total_power_loss < 10 else "Düşük Performans")
        }
        if phase_timestamps and "LOAD" in phase_timestamps:
            result["BaslangicZaman"] = phase_timestamps["LOAD"]["start"]
            result["BitisZaman"] = phase_timestamps["LOAD"]["end"]
        analiz["LOAD"] = result
    
    return analiz


def rapor_olustur():
    Dashboard.print_header(f"AUTO-EXPERT: {VERSION}", Dashboard.CYAN)

    engine = AutoExpertEngine()
    if not engine.baglan(): return
    engine.kurulum_yap()

    # =========================================================
    # DIREKTIF 1 + 4: VIN Çözümleme & Human-in-the-Loop Onay
    # =========================================================
    decoder = VINDecoder()
    gelen_vin = getattr(engine, 'gercek_vin', getattr(engine, 'vin', 'BILINMIYOR'))
    arac_bilgisi = decoder.coz(gelen_vin)

    # Motor koduna göre profil bul
    motor_kodu = arac_bilgisi.get('MotorKodu')
    if motor_kodu and motor_kodu in MOTOR_KODU_DB:
        profil = MOTOR_KODU_DB[motor_kodu]
        kaynak_notu = profil.kaynak
    else:
        # Fuel hint'ten varsayılan
        hint = getattr(engine, 'fuel_hint', 'GASOLINE')
        yt = 'DIESEL' if hint in ('DIZEL', 'DIESEL') else 'GASOLINE'
        profil = varsayilan_profil(yt)
        kaynak_notu = "Veritabaninda bulunamadi"

    Dashboard.preflight_check(engine.desteklenen_pidler, engine.ariza_kodlari)

    # ---- DIREKTIF 4: ONAY EKRANI ----
    while True:
        print(f"\n{Dashboard.CYAN}{'='*54}")
        print(f"  ARAC KIMLIGI — ONAY BEKLENIYOR")
        print(f"{'='*54}{Dashboard.WHITE}")
        print(f"  VIN          : {gelen_vin}")
        print(f"  Motor Kodu   : {profil.motor_kodu}  ({kaynak_notu})")
        print(f"  Marka/Motor  : {profil.marka} {profil.aciklama}")
        print(f"  Yakit Tipi   : {profil.fuel_type_display}")
        print(f"  Max RPM      : {profil.max_rpm}")
        print(f"  Redline      : {profil.redline} RPM")
        print(f"  Rolanti      : {profil.idle_rpm} RPM")
        print(f"  Hedef ECT    : {profil.hedef_ect} °C")
        if profil.bore_mm > 0:
            print(f"  Bore/Stroke  : {profil.bore_mm}mm / {profil.stroke_mm}mm")
        if profil.displacement_cc > 0:
            print(f"  Hacim        : {profil.displacement_cc:.0f} cc")
        if profil.kompresyon_orani > 0:
            print(f"  Kompresyon   : {profil.kompresyon_orani}:1")
        print(f"{Dashboard.CYAN}{'='*54}{Dashboard.WHITE}")
        onay = input(f"{Dashboard.YELLOW}[Enter] Onayla  [D] Duzelt  [M] Manuel gir : {Dashboard.WHITE}").strip().upper()

        if onay == '':
            print(f"{Dashboard.GREEN}Profil onaylandi.{Dashboard.WHITE}")
            break
        elif onay == 'D':
            # Sadece mevcut profili referans göstererek düzeltilebilir alan gir
            print(f"{Dashboard.YELLOW}Girmek istemediginiz alanlari bos birakin (Enter = mevcut deger).{Dashboard.WHITE}")
            def _ask_override(label, current, cast=str):
                try:
                    v = input(f"  {label} [{current}]: ").strip()
                    return cast(v) if v else current
                except:
                    return current
            from dataclasses import replace as dc_replace
            profil = dc_replace(
                profil,
                marka       = _ask_override("Marka", profil.marka).upper(),
                aciklama    = _ask_override("Motor Aciklamasi", profil.aciklama),
                max_rpm     = _ask_override("Max RPM", profil.max_rpm, int),
                redline     = _ask_override("Redline RPM",  profil.redline, int),
                idle_rpm    = _ask_override("Rolanti RPM",  profil.idle_rpm, int),
                hedef_ect   = _ask_override("Hedef ECT (C)",profil.hedef_ect, int),
                bore_mm     = _ask_override("Bore (mm)",    profil.bore_mm, float),
                stroke_mm   = _ask_override("Stroke (mm)",  profil.stroke_mm, float),
                displacement_cc = _ask_override("Hacim (cc)", profil.displacement_cc, float),
                kompresyon_orani = _ask_override("Kompresyon", profil.kompresyon_orani, float),
                kaynak      = "Kullanici Duzeltmesi",
            )
            arac_bilgisi['Motor'] = profil.aciklama
            arac_bilgisi['Marka'] = profil.marka
            # Tekrar göster
        elif onay == 'M':
            profil = manuel_profil_gir()
            arac_bilgisi['Motor'] = profil.aciklama
            arac_bilgisi['Marka'] = profil.marka
            arac_bilgisi['MotorKodu'] = profil.motor_kodu
        else:
            print(f"{Dashboard.YELLOW}Gecersiz giris. Enter / D / M secin.{Dashboard.WHITE}")

    # ---- DIREKTIF 3: LPG sorusu ----
    lpg_cevap = input(f"\n{Dashboard.YELLOW}Test LPG'de mi YAPILIYOR? (e/h, Enter=Hayir): {Dashboard.WHITE}").strip().lower()
    is_lpg = lpg_cevap == 'e'
    if is_lpg:
        print(f"{Dashboard.YELLOW}(LPG MODU) Yakit trim sapmasi LPG toleransi (+/-20%) ile yorumlanacak.{Dashboard.WHITE}")
        arac_bilgisi['YakitSistemi'] = 'LPG'
    else:
        arac_bilgisi['YakitSistemi'] = profil.fuel_type_display

    # --- EXPERTSystem başlatma (zaman damgasıyla veri analizi için) ---
    uzman_sistem = DiagnosticExpert(vehicle_profile={
        "yakit_tipi": profil.yakit_tipi,
        "max_rpm": profil.max_rpm,
        "idle_rpm": profil.idle_rpm
    })

    try:
        girdi_kg = input(f"\n{Dashboard.YELLOW}Arac Agirligi (kg, Varsayilan 1350): {Dashboard.WHITE}")
        arac_agirligi = int(girdi_kg) if girdi_kg.strip() else 1350
    except:
        arac_agirligi = 1350
    print(f"{Dashboard.GREEN}Arac agirlik: {arac_agirligi} kg{Dashboard.WHITE}")

    AERO_PROFILES = {
        1: {"name": "Sedan", "Cd": 0.28, "Area": 2.2},
        2: {"name": "Hatchback", "Cd": 0.32, "Area": 2.1},
        3: {"name": "SUV / Pickup", "Cd": 0.38, "Area": 2.6},
        4: {"name": "Spor", "Cd": 0.25, "Area": 1.9},
        5: {"name": "Ticari / Van", "Cd": 0.42, "Area": 2.8}
    }
    print(f"\n{Dashboard.CYAN}Kasa Tipi Secimi:{Dashboard.WHITE}")
    for key, value in AERO_PROFILES.items():
        print(f"   {key}. {value['name']} (Cd: {value['Cd']}, Alan: {value['Area']} m2)")
    try:
        kasa_secim = int(input(f"{Dashboard.YELLOW}Secim (1-5, Varsayilan 1=Sedan): {Dashboard.WHITE}") or "1")
        if kasa_secim not in AERO_PROFILES: kasa_secim = 1
    except:
        kasa_secim = 1
    aero_data = AERO_PROFILES[kasa_secim]
    print(f"{Dashboard.GREEN}{aero_data['name']} secildi (Cd: {aero_data['Cd']}){Dashboard.WHITE}")

    zaman_damgasi = time.strftime('%Y%m%d_%H%M%S')
    klasor_adi = f"Ekspertiz_{arac_bilgisi['Marka']}_{zaman_damgasi}"
    PROJE_KLASORU = os.path.join(SCRIPT_DIR, 'rapor', klasor_adi)
    if not os.path.exists(PROJE_KLASORU): os.makedirs(PROJE_KLASORU)

    temp_path = os.path.join(PROJE_KLASORU, "temp_raw_data.json")
    kayitlar = []
    start_offset = 0
    resume_mode = False

    if os.path.exists(temp_path):
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                resume_data = json.load(f)
            
            print(f"\n{Dashboard.YELLOW}⚠️  Önceki test yarım kalmış ({len(resume_data)} kayıt).{Dashboard.WHITE}")
            devam = input("Devam etmek ister misiniz? (e/h, Enter=Hayır): ")
            
            if devam.lower() == 'e':
                kayitlar = resume_data
                start_offset = kayitlar[-1].get('Time', 0) if kayitlar else 0
                resume_mode = True
                print(f"{Dashboard.GREEN}✓ Test {int(start_offset)} saniyeden devam edecek{Dashboard.WHITE}")
            else:
                os.remove(temp_path)
                print(f"{Dashboard.CYAN}✓ Yeni test başlatılıyor{Dashboard.WHITE}")
        except Exception as e:
            print(f"{Dashboard.YELLOW}Uyarı: Önceki veri okunamadı ({e}), yeni test başlatılıyor{Dashboard.WHITE}")

    try:
        girdi = input(f"\n{Dashboard.YELLOW}⏱️ Test Süresi (Varsayılan 1200sn = 20dk, Enter bas geç): {Dashboard.WHITE}")
        süre_sn = int(girdi) if girdi.strip() else 1200
    except: süre_sn = 1200

    # V140: Bağlantı Stabilitesi (Buffer Temizliği ve Gecikme)
    if hasattr(engine, 'ser') and engine.ser and engine.ser.is_open:
        engine.ser.reset_input_buffer()
        engine.ser.reset_output_buffer()
        logging.info("Serial buffers cleared before test start.")
    time.sleep(0.5)

    print(f"\n{Dashboard.GREEN}🛑 TEST BASLIYOR ({süre_sn} Saniye = {süre_sn//60} dakika)...{Dashboard.WHITE}")
    time.sleep(2)
    
    
    # V94: Simülasyon Sıfırlama (Güvenli Kontrol)
    if hasattr(engine, 'simulasyonu_sifirla'):
        engine.simulasyonu_sifirla()
    
    # V106: Variable Initialization (CRASH FIX - Scope Safety)
    # Bu değişkenler try bloğundan önce tanımlanmalı ki except bloğu erişebilsin
    current_phase = "KOEO"
    previous_phase = "UNKNOWN"
    hata_sayaci = 0
    test_durdu = False
    phase_timestamps = {
        "KOEO": {"start": 0, "end": 0},
        "CRANKING": {"start": 0, "end": 0},
        "WARMUP": {"start": 0, "end": 0},
        "HOT": {"start": 0, "end": 0},
        "LOAD": {"start": 0, "end": 0}
    }
    baslangic = time.time() - start_offset
    
    # Kayıtlar listesi resume durumunda dolu olabilir, değilse boş başlat
    if 'kayitlar' not in locals(): kayitlar = []
    
    try:
        while time.time() - baslangic < süre_sn:
            # V106: Heartbeat Dönüşü (fresh_count)
            anlik_veri, fresh_count = engine.tek_veri_oku(engine.FAST, current_phase)
            
            # --- V140: UNIFIED DATA EXTRACTION & SYNC ---
            ect = anlik_veri.get('ECT')
            rpm = int(anlik_veri.get('RPM') or 0)
            tps = float(anlik_veri.get('TPS') or 0.0)
            load = float(anlik_veri.get('LOAD') or 0.0)
            voltaj = anlik_veri.get('Voltaj', 0.0)
            stft = anlik_veri.get('STFT') or 0
            ltft = anlik_veri.get('LTFT') or 0
            total_trim = stft + ltft
            frp = anlik_veri.get('FUEL_RAIL_PRESS')
            frp = anlik_veri.get('FUEL_RAIL_PRESS')
            
            # --- Expert System & Defibrillator ---
            if fresh_count > 0:
                hata_sayaci = 0
                if engine.data_cache:
                    teşhis_sonuçları = uzman_sistem.evaluate(engine.data_cache, engine.ariza_kodlari)
            else:
                hata_sayaci += 1
                if hata_sayaci > 5:
                    print(f"\n{Dashboard.RED}⚠️ BAĞLANTI RESETLENDİ (Veri Akışı Yok) - Lütfen Bekleyin...{Dashboard.WHITE}")
                    engine.baglanti_kontrol()
                    hata_sayaci = 0  # Reset after attempting fix
                else:
                    time.sleep(0.5) # Short pause on transient error

            # --- PHASE DETECTION & LOGGING ---
            previous_phase = current_phase
            current_phase = surus_asamasi_tespit(anlik_veri, profil, previous_phase)
            
            if current_phase != "KOEO" or fresh_count > 0:
                log_data = anlik_veri.copy() # Use a copy for logging
                if kayitlar:
                    log_data = filtrele_outlier(log_data, kayitlar[-1])
                else:
                    log_data = filtrele_outlier(log_data)

                log_data['Phase'] = current_phase
                log_data['Time'] = time.time() - baslangic + start_offset
                kayitlar.append(log_data)
            
            # --- PHASE CHANGE BANNERS ---
            if current_phase != previous_phase:
                if previous_phase in phase_timestamps and phase_timestamps[previous_phase]["end"] == 0:
                    phase_timestamps[previous_phase]["end"] = anlik_veri.get('Time', time.time() - baslangic + start_offset)
                if current_phase in phase_timestamps and phase_timestamps[current_phase]["start"] == 0:
                    phase_timestamps[current_phase]["start"] = anlik_veri.get('Time', time.time() - baslangic + start_offset)
                
                if current_phase == "KOEO":
                    Dashboard.show_koeo_banner(voltaj, "Sistem başlatıldı, kontak açık")
                elif current_phase == "CRANKING":
                    Dashboard.show_cranking_banner(voltaj, f"Voltaj düştü ({voltaj:.1f}V), marş başladı")
                elif current_phase == "WARMUP":
                    display_ect = ect if ect is not None else 20
                    Dashboard.show_warmup_banner(display_ect, profil.hedef_ect, "Motor calisti (RPM > 700), isinma basladi")
                elif current_phase == "HOT":
                    Dashboard.show_hot_banner(f"ECT hedef sıcaklığa ulaştı ({ect}°C)")
                elif current_phase == "LOAD":
                    neden = f"Yüksek TPS (%{tps:.0f})" if tps > 70 else f"Yüksek LOAD (%{load:.0f})"
                    Dashboard.show_load_banner(95, neden)
                time.sleep(1)
            
            # --- REAL-TIME WARNINGS & UI UPDATE ---
            if rpm > profil.max_rpm * 1.05:
                print(f"\n{Dashboard.RED}KRITIK: DEVIR SINIRI ASILDI! (RPM: {rpm}, Max: {profil.max_rpm}){Dashboard.WHITE}")
                time.sleep(0.5)

            power_str = ""
            if current_phase == "LOAD":
                if ect is not None and ect < 75:
                    print(f"\n{Dashboard.YELLOW}⚠️ UYARI: Motor Soğuk, Performans Ölçülemez (ECT: {ect}°C < 75°C).{Dashboard.WHITE}")
                    time.sleep(0.5)
                elif ect is None:
                     print(f"\n{Dashboard.YELLOW}⚠️ UYARI: ECT verisi yok, soğuk motor koruması devrede.{Dashboard.WHITE}")
                     time.sleep(0.5)
                
                instant_power_loss = (abs(total_trim) / 5) * 2.5 if abs(total_trim) > 15 else 0
                power_pct = 100 - instant_power_loss
                power_str = f"⚡ %{power_pct:.0f}"

            kalan_sure = int(süre_sn - (time.time() - baslangic))
            if kalan_sure < 0: kalan_sure = 0
            
            safe_max_rpm = int(profil.max_rpm * 0.7) if (ect is not None and ect < 70) else profil.max_rpm
            
            Dashboard.show_progress_bar(kalan_sure, current_phase, rpm, ect, total_trim, power_str, safe_max_rpm, tps, yakit_tipi=profil.yakit_tipi, frp=frp)
            
            time.sleep(0.1)

    except KeyboardInterrupt:
        test_durdu = True
        print(f"\n{Dashboard.YELLOW}⚠️  Test kullanıcı tarafından durduruldu.{Dashboard.WHITE}")

    # V100: Minimum Veri Kontrolü (Crash Prevention)
    süre_sn = int(time.time() - baslangic)
    if len(kayitlar) < 10 or süre_sn < 5:
        print(f"\n{Dashboard.RED}❌ Yetersiz Veri: Rapor oluşturulmadı.{Dashboard.WHITE}")
        print(f"📄 Alınan Veri: {len(kayitlar)} kayıt, {süre_sn} saniye")
        if test_durdu:
            print(f"{Dashboard.YELLOW}⚠️  Test erken durduruldu - en az 10 kayıt ve 5 saniye gerekli.{Dashboard.WHITE}")
        return
    
    for phase in phase_timestamps:
        if phase_timestamps[phase]["end"] is None:
            phase_timestamps[phase]["end"] = time.time() - baslangic

    dtc_data = getattr(engine, 'ariza_kodlari', [])
    
    # V100: KOEO Filtresi - Sadece motor çalışırken alınan veriyi analiz et
    analiz_verisi = [d for d in kayitlar if d.get('RPM', 0) > 0]
    if len(analiz_verisi) < 5:
        print(f"\n{Dashboard.RED}❌ Motor Çalışma Verisi Yetersiz!{Dashboard.WHITE}")
        return
    
    # Direktif 1+3: Profil ve LPG parametreli analiz
    detayli_karne = detayli_parca_analizi(analiz_verisi, dtc_data, arac_bilgisi, profil=profil, is_lpg=is_lpg)
    
    asamali_rapor = asamali_analiz_yap(kayitlar, phase_timestamps)
    
    gecerli_puanlar = [v['Puan'] for v in detayli_karne.values() if isinstance(v, dict) and 'Durum' in v and v['Durum'] not in ["DESTEKLENMIYOR", "BILGI"]]
    if gecerli_puanlar:
        ham_skor = int(sum(gecerli_puanlar)/len(gecerli_puanlar))
        if detayli_karne.get("ECU", {}).get("Puan", 100) < 100: ham_skor = min(ham_skor, 85)
        if detayli_karne.get("IGN", {}).get("Puan", 100) < 50: ham_skor = min(ham_skor, 75)
        skor = ham_skor
    else:
        skor = 0
    
    # V97.2: Dashboard Table Hotfix (FIZIKSEL verisi 'Durum' içermediği için filtrelendi)
    tablo_verisi = {k: v for k, v in detayli_karne.items() if isinstance(v, dict) and 'Durum' in v}
    Dashboard.show_results_table(tablo_verisi)
    
    Dashboard.show_score_summary(skor)
    
    if asamali_rapor:
        Dashboard.show_phase_analysis(asamali_rapor)

    ai_metni = ai_prompt_hazirla(kayitlar, dtc_data, arac_bilgisi, detayli_karne, is_lpg=is_lpg)
    txt_yolu = os.path.join(PROJE_KLASORU, "AI_ICIN_PROMPT.txt")
    with open(txt_yolu, "w", encoding="utf-8") as f: f.write(ai_metni)

    meta = {
        "Kimlik": arac_bilgisi,
        "Skor": skor,
        "Tarih": time.ctime(),
        "Versiyon": VERSION,
        "TestSuresi": süre_sn,
        "AracAgirligi": arac_agirligi,
        "Aero": aero_data,
        "GercekSensorSayisi": len(engine.desteklenen_pidler),
        "IsLPG": is_lpg,  # Direktif 3
        "AracProfili": {
            "Tip": profil.yakit_tipi,
            "MaxRPM": profil.max_rpm,
            "Redline": profil.redline,
            "IdleRPM": profil.idle_rpm,
            "HedefECT": profil.hedef_ect,
            "MotorKodu": profil.motor_kodu,
            "Bore": profil.bore_mm,
            "Stroke": profil.stroke_mm,
            "Displacement": profil.displacement_cc,
            "Kompresyon": profil.kompresyon_orani,
            "Kaynak": profil.kaynak,
        }
    }

    try:
        # V-Production GÖREV 3: Eksik Kritik Sensör Tespiti ve Uyarı Flag'i
        sensor_uyarisi = None
        eksik_sensorler = []
        log_verisi = kayitlar  # alias

        map_var = any((d.get('MAP') or 0) > 0 for d in log_verisi)
        maf_var = any((d.get('MAF') or 0) > 0 for d in log_verisi)
        frp_var = any((d.get('FUEL_RAIL_PRESS') or 0) > 0 for d in log_verisi)

        if not map_var: eksik_sensorler.append("MAP (Emme Manifoldu Basinci)")
        if not maf_var: eksik_sensorler.append("MAF (Hava Akis Olceri)")

        if eksik_sensorler:
            sensor_uyarisi = (
                "Dikkat: Bazi emisyon sensorleri bu arac profilinde kilitli olabilir, "
                "tehis temel verilerle yapilmistir. "
                f"Okunamayan sensorler: {', '.join(eksik_sensorler)}."
            )
            print(f"\n{Dashboard.YELLOW}⚠️  Sensor Uyarisi: {sensor_uyarisi}{Dashboard.WHITE}")

        rapor_tam = {**meta, "Analiz": detayli_karne, "Asamalar": asamali_rapor, "Log": kayitlar}
        if sensor_uyarisi:
            rapor_tam["SensorUyarisi"] = sensor_uyarisi

        json_path = os.path.join(PROJE_KLASORU, "Detayli_Rapor.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rapor_tam, f, indent=4, ensure_ascii=False)
        print(f"\n{Dashboard.GREEN}✅ JSON Rapor Kaydedildi: {json_path}{Dashboard.WHITE}")
        
        if PDF_VAR:
            pdf_path = os.path.join(PROJE_KLASORU, f"Rapor_{arac_bilgisi.get('Marka','Arac')}_{arac_bilgisi.get('Motor','Motor')}_{zaman_damgasi}.pdf")
            # V97.4: Keyword Arguments
            rapor_olustur_pdf(data=rapor_tam, pdf_path=pdf_path)
    except Exception as e:
        print(f"❌ Rapor Hatası: {e}")

if __name__ == "__main__":
    rapor_olustur()