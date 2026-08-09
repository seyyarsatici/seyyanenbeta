import re

filepath = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\raporlayici.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: ileri_doldur
content = content.replace(
    "if v is not None:\n                s = v",
    "if isinstance(v, (int, float)):\n                s = v"
)

# Fix 2: ltft_clean
content = content.replace(
    "ltft_clean = [v for v in ltft if v is not None]",
    "ltft_clean = [v for v in ltft if isinstance(v, (int, float))]"
)


# Fix 3: sanal_saglik_analizi parts
# 1. VIBRASYON
pat1 = r"(    vib_idx = fiziksel\.get\('VibrasyonIndeksi', 0\)\n)(    score = 100 if vib_idx < 20 else \(20 if vib_idx > 100 else 60\)\n    status = \"MUKEMMEL\" if score==100 else \(\"KOTU\" if score==20 else \"ORTA\"\)\n    health_scores\[\"VIBRATION\"\] = \{\n        \"Parca\": \"Atesleme & Denge\",\n        \"Metrik\": f\"Vib\. Indeksi: \{vib_idx:\.1f\}\",\n        \"Skor\": score, \"Durum\": status,\n        \"Renk\": puan_renk\(score\)\n    \})"
rep1 = r"""\1    if isinstance(vib_idx, (int, float)):
\2
    else:
        health_scores["VIBRATION"] = {
            "Parca": "Atesleme & Denge",
            "Metrik": str(vib_idx),
            "Skor": "-", "Durum": "N/A",
            "Renk": puan_renk(None, True)
        }"""
# Need to shift indentation inside group 2. To keep it simple, I'll just fully replace the blocks.

content = content.replace("""    # 1. ATESLE ME & VIBRASYON
    vib_idx = fiziksel.get('VibrasyonIndeksi', 0)
    score = 100 if vib_idx < 20 else (20 if vib_idx > 100 else 60)
    status = "MUKEMMEL" if score==100 else ("KOTU" if score==20 else "ORTA")
    health_scores["VIBRATION"] = {
        "Parca": "Atesleme & Denge",
        "Metrik": f"Vib. Indeksi: {vib_idx:.1f}",
        "Skor": score, "Durum": status,
        "Renk": puan_renk(score)
    }""", """    # 1. ATESLE ME & VIBRASYON
    vib_idx = fiziksel.get('VibrasyonIndeksi', 0)
    if isinstance(vib_idx, (int, float)):
        score = 100 if vib_idx < 20 else (20 if vib_idx > 100 else 60)
        status = "MUKEMMEL" if score==100 else ("KOTU" if score==20 else "ORTA")
        health_scores["VIBRATION"] = {
            "Parca": "Atesleme & Denge",
            "Metrik": f"Vib. Indeksi: {vib_idx:.1f}",
            "Skor": score, "Durum": status,
            "Renk": puan_renk(score)
        }
    else:
        health_scores["VIBRATION"] = {
            "Parca": "Atesleme & Denge",
            "Metrik": str(vib_idx),
            "Skor": "-", "Durum": "N/A",
            "Renk": puan_renk(None, True)
        }""")

content = content.replace("""    # 2. YAKIT SISTEMI
    fuel_dev = fiziksel.get('ToplamYakitSapmasi', 0)
    score = 100 if fuel_dev < 5 else (40 if fuel_dev > 15 else 70)
    status = "MUKEMMEL" if score==100 else ("KIRLI/ARIZALI" if score==40 else "MAKUL")
    health_scores["FUEL"] = {
        "Parca": "Yakit Sistemi",
        "Metrik": f"Sapma: %{fuel_dev:.1f}",
        "Skor": score, "Durum": status,
        "Renk": puan_renk(score)
    }""", """    # 2. YAKIT SISTEMI
    fuel_dev = fiziksel.get('ToplamYakitSapmasi', 0)
    if isinstance(fuel_dev, (int, float)):
        score = 100 if fuel_dev < 5 else (40 if fuel_dev > 15 else 70)
        status = "MUKEMMEL" if score==100 else ("KIRLI/ARIZALI" if score==40 else "MAKUL")
        health_scores["FUEL"] = {
            "Parca": "Yakit Sistemi",
            "Metrik": f"Sapma: %{fuel_dev:.1f}",
            "Skor": score, "Durum": status,
            "Renk": puan_renk(score)
        }
    else:
        health_scores["FUEL"] = {
            "Parca": "Yakit Sistemi",
            "Metrik": str(fuel_dev),
            "Skor": "-", "Durum": "N/A",
            "Renk": puan_renk(None, True)
        }""")

content = content.replace("""    # 3. TERMOSTAT & ISINMA
    warm_eff = fiziksel.get('IsinmaVerimi', 0)
    score = 95 if warm_eff > 5 else (30 if warm_eff < 2 else 70)
    status = "VERIMLI" if score==95 else ("ACIK KALMIS" if score==30 else "NORMAL")
    health_scores["THERM"] = {
        "Parca": "Termostat",
        "Metrik": f"Verim: {warm_eff:.1f} C/dk",
        "Skor": score, "Durum": status,
        "Renk": puan_renk(score)
    }""", """    # 3. TERMOSTAT & ISINMA
    warm_eff = fiziksel.get('IsinmaVerimi', 0)
    if isinstance(warm_eff, (int, float)):
        score = 95 if warm_eff > 5 else (30 if warm_eff < 2 else 70)
        status = "VERIMLI" if score==95 else ("ACIK KALMIS" if score==30 else "NORMAL")
        health_scores["THERM"] = {
            "Parca": "Termostat",
            "Metrik": f"Verim: {warm_eff:.1f} C/dk",
            "Skor": score, "Durum": status,
            "Renk": puan_renk(score)
        }
    else:
        health_scores["THERM"] = {
            "Parca": "Termostat",
            "Metrik": str(warm_eff),
            "Skor": "-", "Durum": "N/A",
            "Renk": puan_renk(None, True)
        }""")

content = content.replace("""    # 4. VAKUM KACAGI
    vac_stab = fiziksel.get('VakumStabilitesi', 0)
    score = 100 if vac_stab < 1 else (50 if vac_stab > 5 else 80)
    status = "SIZDIRMAZ" if score==100 else ("KACAK VAR" if score==50 else "YIPRANMIS")
    health_scores["VACUUM"] = {
        "Parca": "Emme Manifoldu",
        "Metrik": f"Dalgalanma: %{vac_stab:.1f}",
        "Skor": score, "Durum": status,
        "Renk": puan_renk(score)
    }""", """    # 4. VAKUM KACAGI
    vac_stab = fiziksel.get('VakumStabilitesi', 0)
    if isinstance(vac_stab, (int, float)):
        score = 100 if vac_stab < 1 else (50 if vac_stab > 5 else 80)
        status = "SIZDIRMAZ" if score==100 else ("KACAK VAR" if score==50 else "YIPRANMIS")
        health_scores["VACUUM"] = {
            "Parca": "Emme Manifoldu",
            "Metrik": f"Dalgalanma: %{vac_stab:.1f}",
            "Skor": score, "Durum": status,
            "Renk": puan_renk(score)
        }
    else:
        health_scores["VACUUM"] = {
            "Parca": "Emme Manifoldu",
            "Metrik": str(vac_stab),
            "Skor": "-", "Durum": "N/A",
            "Renk": puan_renk(None, True)
        }""")

content = content.replace("""    # 5. Direktif 2: Volumetrik Verimlilik
    ve_pct = fiziksel.get('VolHacimselVerimlilik')
    if ve_pct is not None:
        score = 100 if 75 <= ve_pct <= 100 else (60 if 55 <= ve_pct < 75 else 35)
        status = "IDEAL" if score==100 else ("DUSUK" if score==60 else "KRITIK")
        health_scores["VE"] = {
            "Parca": "Hacimsel Verimlilik",
            "Metrik": f"%{ve_pct}",
            "Skor": score, "Durum": status,
            "Renk": puan_renk(score)
        }""", """    # 5. Direktif 2: Volumetrik Verimlilik
    ve_pct = fiziksel.get('VolHacimselVerimlilik')
    if isinstance(ve_pct, (int, float)):
        score = 100 if 75 <= ve_pct <= 100 else (60 if 55 <= ve_pct < 75 else 35)
        status = "IDEAL" if score==100 else ("DUSUK" if score==60 else "KRITIK")
        health_scores["VE"] = {
            "Parca": "Hacimsel Verimlilik",
            "Metrik": f"%{ve_pct}",
            "Skor": score, "Durum": status,
            "Renk": puan_renk(score)
        }
    elif ve_pct is not None:
        health_scores["VE"] = {
            "Parca": "Hacimsel Verimlilik",
            "Metrik": str(ve_pct),
            "Skor": "-", "Durum": "N/A",
            "Renk": puan_renk(None, True)
        }""")


with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done wrapping type checks in raporlayici.py")
