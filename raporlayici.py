# -*- coding: utf-8 -*-
import os
import json
import uuid
import statistics
import re
import webbrowser
import base64
from io import BytesIO
from datetime import datetime
from pathlib import Path
import pandas as pd

# GÖREV 3: Arayüz donmasını engellemek için backend'i ayarla
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt

from fpdf import FPDF

# --- KURULUM BLOĞU ---

# GÖREV 1: Font ve Veritabanı Kurulumu
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(SCRIPT_DIR, 'fonts')
HTML_TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "seyyanen_template.html")

DEFAULT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Seyyanen Diagnostik Raporu</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }
    h1 { color: #111827; }
    .card { border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
    .title { font-weight: bold; margin-bottom: 6px; }
  </style>
</head>
<body>
  <h1>Seyyanen Diagnostik Raporu</h1>
  <div class="card"><div class="title">Ateşleme</div><div>{{atesleme_yorum}}</div></div>
  <div class="card"><div class="title">Yakıt</div><div>{{yakit_yorum}}</div></div>
  <div class="card"><div class="title">Hava</div><div>{{hava_yorum}}</div></div>
  <div class="card"><div class="title">Soğutma</div><div>{{sogutma_yorum}}</div></div>
</body>
</html>
"""

# V201: Lokal Font Çözümleme Fonksiyonu (Offline-First)
def _resolve_font():
    """
    V201: Font çözümleme fonksiyonu. Sırasıyla denenen yollar:
    1. Proje içindeki fonts/DejaVuSans.ttf
    2. İşletim sistemi font klasörleri
    3. None (FPDF standart Helvetica fontuna fallback yapar)
    
    Returns:
        str: Bulunmuş font dosyasının tam yolu, veya None
    """
    # Dene 1: Proje içindeki font
    project_font = Path(SCRIPT_DIR) / 'fonts' / 'DejaVuSans.ttf'
    if project_font.exists():
        return str(project_font)
    
    # Dene 2: Windows sistem fontları
    if os.name == 'nt':  # Windows
        windows_fonts = [
            Path('C:/Windows/Fonts/arial.ttf'),
            Path('C:/Windows/Fonts/Arial.ttf'),
            Path('C:/Windows/Fonts/arialbd.ttf'),
        ]
        for font_path in windows_fonts:
            if font_path.exists():
                return str(font_path)
    
    # Dene 3: Linux/macOS sistem fontları
    else:
        unix_fonts = [
            Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
            Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'),
            Path('/System/Library/Fonts/Arial.ttf'),  # macOS
        ]
        for font_path in unix_fonts:
            if font_path.exists():
                return str(font_path)
    
    # Fallback: None (FPDF will use Helvetica)
    return None

# FONT_PATH dinamik olarak belirlenir
FONT_PATH = _resolve_font()

# Arıza Kodu Veritabanı (Örnek Kodlar)
DTC_DB = {
    "P0100": "MAF Sensörü Devre Arızası", "P0101": "MAF Sensörü Aralık/Performans Hatası",
    "P0102": "MAF Sensörü Düşük Giriş", "P0103": "MAF Sensörü Yüksek Giriş",
    "P0106": "MAP Sensörü Aralık/Performans Hatası", "P0107": "MAP Sensörü Düşük Giriş",
    "P0117": "ECT Düşük Giriş", "P0118": "ECT Yüksek Giriş",
    "P0131": "O2 Sensörü B1S1 Düşük Voltaj", "P0132": "O2 Sensörü B1S1 Yüksek Voltaj",
    "P0171": "Sistem Çok Fakir - B1", "P0172": "Sistem Çok Zengin - B1",
    "P0300": "Rastgele/Çoklu Silindir Ateşleme Hatası", "P0301": "1. Silindir Ateşleme Hatası",
    "P0302": "2. Silindir Ateşleme Hatası", "P0303": "3. Silindir Ateşleme Hatası",
    "P0304": "4. Silindir Ateşleme Hatası", "P0087": "Düşük Yakıt Ray Basıncı",
    "P0299": "Turbo Basıncı Düşük", "P0546": "EGT Sensör Devresi Yüksek"
}

# --- YARDIMCI FONKSİYONLAR ---

def safe_str(text):
    """
    FPDF'in 'latin-1' codeciyle uyumlu hale getirmek icin string'i temizler.
    """
    text = str(text)
    replacements = {'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g', 'Ü': 'U', 'ü': 'u',
                    'Ş': 'S', 'ş': 's', 'Ö': 'O', 'ö': 'o', 'Ç': 'C', 'ç': 'c',
                    '’': "'", '“': '"', '”': '"', '…': '...'}
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.encode('latin-1', 'ignore').decode('latin-1')

class PDF(FPDF):
    """FPDF için Header ve Footer tanımlamalarını içeren alt sınıf."""
    def header(self):
        try:
            self.add_font('DejaVu', '', FONT_PATH, uni=True)
            self.set_font('DejaVu', 'B', 18)
        except RuntimeError:
            # Font zaten eklenmişse tekrar ekleme
            self.set_font('DejaVu', 'B', 18)
        except Exception:
            self.set_font('Helvetica', 'B', 18)
        
        self.set_fill_color(44, 62, 80) # Antrasit Arka Plan
        self.set_text_color(255, 255, 255)
        self.cell(0, 15, safe_str('SEYYANEN - OTOMOTIV TESHIS RAPORU'), border=1, ln=1, align='C', fill=True)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        try:
            self.set_font('DejaVu', '', 8)
        except:
            self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, safe_str(f'Sayfa {self.page_no()}'), 0, 0, 'C')

def grafik_ciz(df: pd.DataFrame):
    """Grafikleri base64 olarak üretir (self-contained HTML)."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    images = {}
    
    # Grafik 1: Motor Devri ve Hız
    if 'RPM' in df.columns and 'SPEED' in df.columns:
        fig, ax1 = plt.subplots(figsize=(10, 4))
        ax1.set_xlabel('Zaman (index)')
        ax1.set_ylabel('RPM', color='red')
        ax1.plot(df.index, df['RPM'], color='red', label='Motor Devri')
        ax1.tick_params(axis='y', labelcolor='red')
        ax2 = ax1.twinx()
        ax2.set_ylabel('Hız (km/h)', color='blue')
        ax2.plot(df.index, df['SPEED'], color='blue', label='Araç Hızı')
        ax2.tick_params(axis='y', labelcolor='blue')
        plt.title("Motor Devri ve Araç Hızı")
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        images["rpm_speed"] = base64.b64encode(buf.read()).decode("ascii")
        buf.close()
        plt.close()

    # Grafik 2: Manifold Basıncı (Turbo)
    if 'MAP' in df.columns:
        fig = plt.figure(figsize=(10, 3))
        plt.plot(df.index, df['MAP'], label='Manifold Basıncı (kPa)', color='purple')
        plt.title("Turbo Basıncı (MAP)")
        plt.ylabel("Basınç (kPa)")
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.legend()
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        images["map"] = base64.b64encode(buf.read()).decode("ascii")
        buf.close()
        plt.close(fig)

    return images


def _extract_json_block(text: str) -> str:
    """Markdown kod bloğu içinden JSON çıkarır."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1)
    return text


def _repair_json_text(text: str) -> str:
    """Sık AI JSON format bozulmalarını onarır."""
    fixed = text.strip()
    fixed = _extract_json_block(fixed)
    fixed = fixed.replace("“", '"').replace("”", '"').replace("’", "'")
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    return fixed


def _parse_ai_json(ai_payload) -> dict:
    """AI çıktısını güvenli şekilde dict'e çevirir."""
    if isinstance(ai_payload, dict):
        return ai_payload
    if not ai_payload:
        return {}
    try:
        return json.loads(ai_payload)
    except Exception:
        repaired = _repair_json_text(str(ai_payload))
        try:
            return json.loads(repaired)
        except Exception:
            return {}


def _validate_ai_response(ai_json: dict) -> dict:
    """
    V201: AI Yanıt Doğrulama ve Çevrimdışı Fallback
    
    Gemini API'den boş yanıt, JSON parse hatası veya network hatası durumlarında
    uygulamanın çökmesini engeller. Eksik anahtarlar için standart fallback sağlar.
    
    Args:
        ai_json (dict): AI'dan gelen JSON yanıtı
    
    Returns:
        dict: Doğrulanmış ve tam anahtarlarla dolu AI JSON
    """
    # Standart fallback sözlüğü
    fallback_template = {
        "model": "Fallback Model",
        "dil": "tr",
        "sablon": "Sorun/Olası Sebep/Çözüm Önerisi",
        "atesleme_yorum": "Ateşleme verisi analiz edilemedi (Çevrimdışı Mod).",
        "yakit_yorum": "Yakıt verisi analiz edilemedi (Çevrimdışı Mod).",
        "hava_yorum": "Hava verisi analiz edilemedi (Çevrimdışı Mod).",
        "sogutma_yorum": "Soğutma verisi analiz edilemedi (Çevrimdışı Mod).",
        "sorun": [],
        "olasi_sebep": [],
        "cozum_onerisi": []
    }
    
    # Eğer ai_json boş veya None ise fallback dön
    if not ai_json or not isinstance(ai_json, dict):
        return fallback_template
    
    # Gerekli anahtarları kontrol et ve eksik olanları fallback'ten doldur
    validated = dict(fallback_template)  # Fallback ile başla
    
    for key, value in ai_json.items():
        if key in validated:
            # Sadece aynı tipteyse değiştir
            if isinstance(value, type(validated[key])) or (isinstance(value, (list, tuple)) and isinstance(validated[key], list)):
                validated[key] = value
        else:
            # Bilinmeyen anahtarlar için ek olarak ekle (hata vermez, sadece uyarır)
            validated[key] = value
    
    return validated


def _pick_section(ai_json: dict, section_name: str, fallback: str) -> str:
    raw = ai_json.get(section_name)
    if isinstance(raw, list):
        return " | ".join(str(x) for x in raw if x)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return fallback


def _render_html_report(teshis_sonuclari: dict, output_html_path: str) -> bool:
    ai_json = _parse_ai_json(teshis_sonuclari.get("ai_yanit_json"))
    # V201: AI yanıtını doğrula ve eksik anahtarları doldur
    ai_json = _validate_ai_response(ai_json)
    
    sistem = teshis_sonuclari.get("sistem_gruplari", {})

    atesleme_fallback = f"Ateşleme verileri: {json.dumps(sistem.get('atesleme', {}), ensure_ascii=False)}"
    yakit_fallback = f"Yakıt verileri: {json.dumps(sistem.get('yakit', {}), ensure_ascii=False)}"
    hava_fallback = f"Hava verileri: {json.dumps(sistem.get('hava', {}), ensure_ascii=False)}"
    sogutma_fallback = f"Soğutma verileri: {json.dumps(sistem.get('sogutma', {}), ensure_ascii=False)}"

    images = teshis_sonuclari.get("grafikler_base64", {}) or {}
    grafikler_html = ""
    for title, b64_data in images.items():
        grafikler_html += (
            f"<div class='card'><div class='title'>Grafik: {title}</div>"
            f"<img style='max-width:100%;height:auto;' src='data:image/png;base64,{b64_data}' /></div>"
        )

    mapping = {
        "{{atesleme_yorum}}": _pick_section(ai_json, "atesleme_yorum", atesleme_fallback),
        "{{yakit_yorum}}": _pick_section(ai_json, "yakit_yorum", yakit_fallback),
        "{{hava_yorum}}": _pick_section(ai_json, "hava_yorum", hava_fallback),
        "{{sogutma_yorum}}": _pick_section(ai_json, "sogutma_yorum", sogutma_fallback),
        "{{base64_grafikler}}": grafikler_html,
    }

    if os.path.exists(HTML_TEMPLATE_PATH):
        with open(HTML_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = DEFAULT_HTML_TEMPLATE

    rendered = template
    for placeholder, value in mapping.items():
        rendered = rendered.replace(placeholder, str(value))

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    return True

def rapor_olustur_pdf_eski(data: dict, pdf_path: str):
    """
    Eski sistemden gelen, FPDF ve Matplotlib kullanan detaylı rapor oluşturucu.
    """
    pdf = PDF()
    pdf.add_page()

    # GÖREV 7: Rapor Puanı (safe_str ile sarmala)
    pdf.set_font_size(24)
    puan_str = data.get("arac_sagligi", "%?")
    try:
        puan = int(puan_str.strip('%'))
        if puan >= 80: renk = (0, 128, 0) # Yeşil
        elif puan >= 50: renk = (255, 165, 0) # Turuncu
        else: renk = (255, 0, 0) # Kırmızı
    except ValueError:
        renk = (0,0,0)
    pdf.set_text_color(*renk)
    pdf.cell(0, 10, safe_str(f"Genel Arac Sagligi: {safe_str(puan_str)}"), ln=1, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)

    # GÖREV 7: Bulgular ve Tavsiyeler (safe_str ile sarmala)
    pdf.set_font_size(14)
    pdf.cell(0, 10, safe_str("TESHIS BULGULARI"), ln=1, border='B')
    pdf.set_font_size(10)
    for bulgu in data.get("bulgular", []):
        # Hata kodunu ve açıklamayı ayır
        bulgu_parcalari = safe_str(bulgu).split(' - ', 1)
        kod = bulgu_parcalari[0]
        aciklama = bulgu_parcalari[1] if len(bulgu_parcalari) > 1 else ""
        
        # Bilinen bir kod ise, veritabanından açıklamasını al
        db_aciklama = DTC_DB.get(kod.split('(')[-1].strip(')'))
        if db_aciklama:
             aciklama = f"{safe_str(db_aciklama)} ({aciklama})"

        pdf.multi_cell(0, 7, f"- {safe_str(kod)}: {safe_str(aciklama)}", ln=1)
    pdf.ln(5)

    pdf.set_font_size(14)
    pdf.cell(0, 10, safe_str("ONERILEN EYLEMLER"), ln=1, border='B')
    pdf.set_font_size(10)
    for tavsiye in data.get("tavsiyeler", []):
        pdf.multi_cell(0, 7, f"- {safe_str(tavsiye)}", ln=1)
    pdf.ln(10)

    # Grafikler
    if "grafikler" in data and data["grafikler"]:
        if pdf.get_y() > 150: # Sayfada yeterli yer yoksa yeni sayfa aç
             pdf.add_page()
        pdf.set_font_size(14)
        pdf.cell(0, 10, safe_str("TELEMETRI GRAFIKLERI"), ln=1, align='C', border='B')
        pdf.ln(5)
        for grafik_path in data["grafikler"]:
            if os.path.exists(grafik_path):
                if pdf.get_y() > 200:
                     pdf.add_page()
                pdf.image(grafik_path, x=None, y=None, w=190)
                pdf.ln(5)

    pdf.output(pdf_path)

# --- GÖREV 2: Arayüze Uyumlu Köprü Fonksiyonu ---

def pdf_olustur(teshis_sonuclari: dict, df: pd.DataFrame, pdf_path: str) -> bool:
    """
    main_ui.py tarafından çağrılan, modern arayüze uyumlu köprü fonksiyonu.
    Bu fonksiyon, gelen veriyi eski raporlama sisteminin anladığı formata çevirir.
    """
    print("Bilgi: Gelişmiş FPDF raporlayıcı (köprü fonksiyonu) çalıştırıldı.")
    try:
        html_path = str(Path(pdf_path).with_suffix(".html"))

        # Adım 1: Grafik Çizimi (base64)
        grafikler_base64 = grafik_ciz(df)

        # Adım 2: Eski `rapor_olustur_pdf_eski` fonksiyonunun beklediği `data` sözlüğünü hazırla
        data_for_legacy_reporter = {
            "arac_sagligi": teshis_sonuclari.get("arac_sagligi", "%0"),
            "bulgular": teshis_sonuclari.get("bulgular", []),
            "tavsiyeler": teshis_sonuclari.get("tavsiyeler", []),
            "grafikler": []  # PDF akışını koru ama disk PNG üretme
        }

        # Adım 3: Eski rapor oluşturucuyu çağır
        rapor_olustur_pdf_eski(data=data_for_legacy_reporter, pdf_path=pdf_path)

        # Adım 4: HTML şablon raporunu üret (UTF-8)
        html_payload = dict(teshis_sonuclari)
        html_payload["grafikler_base64"] = grafikler_base64
        _render_html_report(teshis_sonuclari=html_payload, output_html_path=html_path)

        webbrowser.open(Path(html_path).as_uri())
        print(f"Başarılı: PDF Raporu '{pdf_path}' adresine kaydedildi.")
        print(f"Başarılı: HTML Raporu '{html_path}' adresine kaydedildi ve açıldı.")
        return True

    except Exception as e:
        print(f"Kritik PDF oluşturma hatası (köprü fonksiyonunda): {e}")
        import traceback
        traceback.print_exc()
        # Hata durumunda, içeriği bozuk olabilecek bir PDF bırakmamak için dosyayı sil
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)
        return False

# V201: Offline AI Fallback ve Lokal Font adaptasyonu tamamlandı
