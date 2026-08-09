import sys

main_path = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\main.py'
with open(main_path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. VERSION
text = text.replace('VERSION = "V110 - Enterprise Release"', 'VERSION = "V111 - Master Release"')

# 2. Vakum Str Fix
old1 = """    vakum_stab = fiziksel.get('VakumStabilitesi', 0)
    ve_pct = fiziksel.get('VolHacimselVerimlilik', None)"""

new1 = """    vakum_stab = fiziksel.get('VakumStabilitesi', 0)
    if isinstance(vakum_stab, (int, float)):
        vakum_str = f\"%{vakum_stab:.1f}\"
    else:
        vakum_str = str(vakum_stab)
    ve_pct = fiziksel.get('VolHacimselVerimlilik', None)"""

text = text.replace(old1, new1)

old2 = """4. {SENSOR_UID['MAP']} Mekanik Saglik (Vakum): %{vakum_stab:.1f} Dalgalanma"""
new2 = """4. {SENSOR_UID['MAP']} Mekanik Saglik (Vakum): {vakum_str} Dalgalanma"""
text = text.replace(old2, new2)

old3 = """    # 3. Vakum Stabilitesi (Rölanti MAP σ/Avg)
    hot_idle_map = [d.get("MAP") for d in kayitlar if d.get("Phase") == "HOT" and d.get("MAP") and d.get("RPM") < 1200]
    if len(hot_idle_map) > 10:"""
new3 = """    # 3. Vakum Stabilitesi (Rölanti MAP σ/Avg)
    hot_idle_map = [d.get("MAP") for d in kayitlar if d.get("Phase") == "HOT" and d.get("MAP") and d.get("RPM") < 1200]
    if profil.yakit_tipi.upper() == "DIESEL":
        vakum_stabilitesi = "N/A (Dizel araçlarda vakum aranmaz)"
    elif len(hot_idle_map) > 10:"""
text = text.replace(old3, new3)

# 3. or 0 Fixes (Specific instances)
text = text.replace("voltaj = float(anlik_veri.get('Voltaj') or 0.0)", "_v = anlik_veri.get('Voltaj'); voltaj = float(_v) if _v is not None else 0.0")
text = text.replace("ect    = anlik_veri.get('ECT') or 0", "_e = anlik_veri.get('ECT'); ect = _e if _e is not None else 0")
text = text.replace("tps    = float(anlik_veri.get('TPS') or 0.0)", "_t = anlik_veri.get('TPS'); tps = float(_t) if _t is not None else 0.0")
text = text.replace("load   = float(anlik_veri.get('LOAD') or 0.0)", "_l = anlik_veri.get('LOAD'); load = float(_l) if _l is not None else 0.0")

text = text.replace("rpm = int(anlik_veri.get('RPM') or 0)", "_r = anlik_veri.get('RPM'); rpm = int(_r) if _r is not None else 0")
text = text.replace("stft = anlik_veri.get('STFT') or 0", "_s = anlik_veri.get('STFT'); stft = _s if _s is not None else 0")
text = text.replace("ltft = anlik_veri.get('LTFT') or 0", "_lt = anlik_veri.get('LTFT'); ltft = _lt if _lt is not None else 0")
text = text.replace("gosterilecek_deger = float(anlik_veri.get('LOAD') or 0)", "_gl = anlik_veri.get('LOAD'); gosterilecek_deger = float(_gl) if _gl is not None else 0.0")

with open(main_path, 'w', encoding='utf-8') as f:
    f.write(text)

print('Phase 1 done')
