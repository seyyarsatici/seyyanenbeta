import re

main_path = r"c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\main.py"
motor_path = r"c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\motor.py"

with open(main_path, "r", encoding="utf-8") as f:
    main_code = f.read()

# 1. VERSION Fix
main_code = main_code.replace('VERSION = "V110 - Enterprise Release"', 'VERSION = "V111 - Master Release"')

# 2. Diesel MAP Fix
main_code = main_code.replace(
    "vakum_stab = fiziksel.get('VakumStabilitesi', 0)",
    "vakum_stab = fiziksel.get('VakumStabilitesi', 0)\n    vakum_str = f\"%{vakum_stab:.1f}\" if isinstance(vakum_stab, (int, float)) else str(vakum_stab)"
)
main_code = main_code.replace(
    "4. {SENSOR_UID['MAP']} Mekanik Saglik (Vakum): %{vakum_stab:.1f} Dalgalanma",
    "4. {SENSOR_UID['MAP']} Mekanik Saglik (Vakum): {vakum_str} Dalgalanma"
)

old_vakum_block = """    # 3. Vakum Stabilitesi (Rölanti MAP σ/Avg)
    hot_idle_map = [d.get("MAP") for d in kayitlar if d.get("Phase") == "HOT" and d.get("MAP") and d.get("RPM") < 1200]
    if len(hot_idle_map) > 10:"""
new_vakum_block = """    # 3. Vakum Stabilitesi (Rölanti MAP σ/Avg)
    hot_idle_map = [d.get("MAP") for d in kayitlar if d.get("Phase") == "HOT" and d.get("MAP") and d.get("RPM") < 1200]
    if profil.yakit_tipi.upper() == "DIESEL":
        vakum_stabilitesi = "N/A (Dizel araçlarda vakum aranmaz)"
    elif len(hot_idle_map) > 10:"""
main_code = main_code.replace(old_vakum_block, new_vakum_block)

# 3. "or 0" fixes in main.py
main_code = main_code.replace("voltaj = float(anlik_veri.get('Voltaj') or 0.0)", "_v = anlik_veri.get('Voltaj'); voltaj = float(_v) if _v is not None else 0.0")
main_code = main_code.replace("ect    = anlik_veri.get('ECT') or 0", "_e = anlik_veri.get('ECT'); ect = _e if _e is not None else 0")
main_code = main_code.replace("tps    = float(anlik_veri.get('TPS') or 0.0)", "_t = anlik_veri.get('TPS'); tps = float(_t) if _t is not None else 0.0")
main_code = main_code.replace("load   = float(anlik_veri.get('LOAD') or 0.0)", "_l = anlik_veri.get('LOAD'); load = float(_l) if _l is not None else 0.0")

# Later ones
main_code = main_code.replace("rpm = int(anlik_veri.get('RPM') or 0)", "_rpm=anlik_veri.get('RPM'); rpm = int(_rpm) if _rpm is not None else 0")
main_code = main_code.replace("stft = anlik_veri.get('STFT') or 0", "_stft=anlik_veri.get('STFT'); stft = _stft if _stft is not None else 0")
main_code = main_code.replace("ltft = anlik_veri.get('LTFT') or 0", "_ltft=anlik_veri.get('LTFT'); ltft = _ltft if _ltft is not None else 0")
main_code = main_code.replace("gosterilecek_deger = float(anlik_veri.get('LOAD') or 0)", "_gload=anlik_veri.get('LOAD'); gosterilecek_deger = float(_gload) if _gload is not None else 0")

# 4. Try..Except loop in main.py
# Find the while loop
start_idx = main_code.find("while time.time() - baslangic < süre_sn:")
end_idx = main_code.find("except KeyboardInterrupt:", start_idx)

if start_idx != -1 and end_idx != -1:
    before = main_code[:start_idx]
    loop_body_unindented = main_code[start_idx:end_idx]
    after = main_code[end_idx:]
    
    # We want to wrap the inside of the while loop in try except.
    # The while loop itself starts with `while ... :`
    lines = loop_body_unindented.splitlines()
    new_loop_lines = []
    new_loop_lines.append(lines[0]) # while ...:
    new_loop_lines.append("            try:")
    
    for line in lines[1:]:
        if line.strip() == "":
            new_loop_lines.append(line)
        else:
            new_loop_lines.append("    " + line)
            
    # Add exception block
    new_loop_lines.append("            except serial.SerialException as e:")
    new_loop_lines.append("                print(f\"\\n{Dashboard.RED}⚠️  Bağlantı koptu, tekrar bağlanmaya çalışılıyor... ({e}){Dashboard.WHITE}\")")
    new_loop_lines.append("                time.sleep(3)")
    new_loop_lines.append("                engine.baglan()")
    new_loop_lines.append("    ")
    
    main_code = before + "\n".join(new_loop_lines) + after

with open(main_path, "w", encoding="utf-8") as f:
    f.write(main_code)
    
print("main.py fixed")

# motor.py fix
with open(motor_path, "r", encoding="utf-8") as f:
    motor_code = f.read()

old_eval = 'func = eval(f"lambda x: {f_str}", {"__builtins__": {}})'
new_eval = '''yasakli = ["__", "import", "exec", "eval", "os", "sys", "subprocess", "globals", "builtins", "class", "mro", "subclasses"]
                                            if any(kd in f_str for kd in yasakli):
                                                raise ValueError(f"Guvenlik Ihlali: {f_str}")
                                            func = eval(f"lambda x: {f_str}", {"__builtins__": {}})'''
motor_code = motor_code.replace(old_eval, new_eval)

with open(motor_path, "w", encoding="utf-8") as f:
    f.write(motor_code)

print("motor.py fixed")
