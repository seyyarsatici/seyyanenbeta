import re

filepath = r'c:\Users\chnyg\OneDrive\Belgeler\py\seyyanen\main.py'
try:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # The issue: `print(f"\n{Dashboard.RED}` was split into:
    # print(f"
    # {Dashboard.RED}
    # which breaks the syntax in Python. Same for other Dashboard colors.
    
    # We can fix this by replacing the newline that is immediately followed by {Dashboard. with \n{Dashboard.
    
    fixed_content = re.sub(r'print\(f"\n({Dashboard\.[A-Z]+})', r'print(f"\\n\1', content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(fixed_content)

    print("Strings fixed.")

except Exception as e:
    print(f"Error: {e}")
