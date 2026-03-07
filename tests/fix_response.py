import re
import json

path = r'd:\Project\Code\nutritrack-documentation\app\data\output\response.json'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Try to find the inner JSON string
match = re.search(r"\{'text':\s*'(.*?)'\s*\}", content, re.DOTALL)
if match:
    json_str = match.group(1)
    
    # We should also replace any escaped characters that might have been lost or retain them
    try:
        # Since it's a literal JSON string spanning multiple lines, we can just load it
        parsed_json = json.loads(json_str)
        
        # Now create the proper wrapper
        final_obj = {
            "role": "assistant",
            "content": [
                {
                    "text": json.dumps(parsed_json, indent=2, ensure_ascii=False)
                }
            ]
        }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(final_obj, f, indent=2, ensure_ascii=False)
            
        print("Successfully formatted response.json (Method 1)")
    except json.JSONDecodeError as e:
        print(f"Failed to parse inner JSON: {e}")
else:
    print("Could not find inner JSON structure with regex.")
