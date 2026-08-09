import sys

filepath = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\main.py'
try:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # The line is literally: `while time.time() - baslangic < süre_sn:\n            try:\n`
    # We want to replace all occurrences of `\n` in that huge line with actual real newlines.
    
    # Alternatively, let's just do line by line:
    lines = content.splitlines(keepends=True)
    new_lines = []
    found = False
    for i, line in enumerate(lines):
        if r'\n' in line and 'while time.time()' in line:
            print(f"Found at line {i+1}")
            line = line.replace(r'\n', '\n')
            found = True
        new_lines.append(line)
        
    if found:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("Fixed successfully.")
    else:
        print("Could not find the problematic line.")

except Exception as e:
    print(f"Error: {e}")
