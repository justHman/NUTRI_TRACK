import ast
import json
import os
import re

files = [
    r'd:\Project\Code\nutritrack-documentation\app\data\output\response.json',
    r'd:\Project\Code\nutritrack-documentation\app\data\output\toolUse_response.json'
]

def attempt_fix_truncated(content):
    """Very basic attempt to fix truncated Python/JSON structure for visualization."""
    # If it ends with a comma or partial key, try to strip it back to a valid object
    # This is complex, but let's try a simple approach: 
    # Try to find the last complete dictionary or list item.
    
    # Balance braces/brackets/quotes
    open_curly = content.count('{')
    close_curly = content.count('}')
    open_square = content.count('[')
    close_square = content.count(']')
    
    # If it fails ast.literal_eval, we might have an open string
    # Let's try adding closing markers until it parses or we hit a limit
    for closing in ["'", '"}', '}', ']}', ']}', ']}', ']}']:
        try:
            temp = content + closing
            return ast.literal_eval(temp)
        except:
            continue
    
    # If still fails, try to find the last '}' and cut there
    last_brace = content.rfind('}')
    if last_brace != -1:
        truncated = content[:last_brace+1]
        # Check if we need more closing
        for suffix in ["", "]", "}"]:
            try:
                return ast.literal_eval(truncated + suffix)
            except:
                continue
    return None

for file_path in files:
    if not os.path.exists(file_path):
        continue
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        data = None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(content)
            except (SyntaxError, ValueError):
                print(f"File {file_path} is truncated, attempting fix...")
                data = attempt_fix_truncated(content)
        
        if data:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Formatted {file_path}")
        else:
            print(f"Could not fix {file_path}")
            
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
