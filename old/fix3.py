import sys
import re

main_path = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\main.py'
with open(main_path, 'r', encoding='utf-8') as f:
    main_code = f.read()

# 4. Try..Except loop in main.py
start_idx = main_code.find("while time.time() - baslangic < süre_sn:")
end_idx = main_code.find("except KeyboardInterrupt:", start_idx)

if start_idx != -1 and end_idx != -1:
    before = main_code[:start_idx]
    loop_body_unindented = main_code[start_idx:end_idx]
    after = main_code[end_idx:]
    
    lines = loop_body_unindented.splitlines()
    new_loop_lines = []
    # while line itself is original, no extra indent
    new_loop_lines.append(lines[0]) 
    new_loop_lines.append("            try:")
    
    for line in lines[1:]:
        if line.strip() == "":
            new_loop_lines.append(line)
        else:
            new_loop_lines.append("    " + line)
            
    # Add exception block
    new_loop_lines.append("            except serial.SerialException as e:")
    new_loop_lines.append("                print(f\"\\n{Dashboard.RED}⚠️  Bağlantı koptu, tekrar bağlanmaya çalışılıyor...{Dashboard.WHITE}\")")
    new_loop_lines.append("                time.sleep(3)")
    new_loop_lines.append("                engine.baglan()")
    new_loop_lines.append("    ")
    
    main_code = before + "\\n".join(new_loop_lines) + after

with open(main_path, 'w', encoding='utf-8') as f:
    f.write(main_code)

print("Phase 2 main.py done")

motor_path = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\motor.py'
with open(motor_path, 'r', encoding='utf-8') as f:
    motor_code = f.read()

old_eval = 'func = eval(f"lambda x: {f_str}", {"__builtins__": {}})'
new_eval = '''yasakli = ["__", "import", "exec", "eval", "os", "sys", "subprocess", "globals", "builtins", "class", "mro", "subclasses"]
                                            if any(kd in f_str for kd in yasakli):
                                                raise ValueError(f"Guvenlik Ihlali: {f_str}")
                                            func = eval(f"lambda x: {f_str}", {"__builtins__": {}})'''
motor_code = motor_code.replace(old_eval, new_eval)

with open(motor_path, 'w', encoding='utf-8') as f:
    f.write(motor_code)

print("Phase 2 motor.py done")
