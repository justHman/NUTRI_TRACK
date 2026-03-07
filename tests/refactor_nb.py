import json
import os

path = r'd:\Project\Code\nutritrack-documentation\app\tests\test_all.ipynb'
if not os.path.exists(path):
    print(f"Error: {path} not found")
    exit(1)

with open(path, 'r', encoding='utf-8') as f:
    nb = json.load(f)

for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        source_str = "".join(cell['source'])
        
        # 1. USDA
        if "test_normalize_query" in source_str and "usda_results = [" in source_str:
            cell['source'] = [
                "usda_results = usda_tests.run_all(usda_client)\n",
                "print(f\"\\nUSDA Client tests passed: {sum(1 for r in usda_results if r)}/{len(usda_results)}\")"
            ]
        
        # 2. Qwen Model Tests - Execution
        elif "qwen_tests.run_all(qwen)" in source_str or ("test_analyze_food(" in source_str and "q1 =" in source_str):
            cell['source'] = [
                "qwen_results = qwen_tests.run_all(qwen)\n",
                "for i, r in enumerate(qwen_results):\n",
                "    # Extract method slug like 'converse', 'tools', etc.\n",
                "    method_slug = r['method'].lower().replace(' ', '_')\n",
                "    save_raw_output(f\"q{i+1}_{method_slug}_{r['image']}.json\", r.get(\"raw_output\"))\n"
            ]
            
        # 3. Qwen Results Aggregation
        elif "qwen_results = [q1, q2, q3, q4, q5, q6]" in source_str:
            cell['source'] = [s.replace("qwen_results = [q1, q2, q3, q4, q5, q6]", "qwen_results = qwen_results # Already defined") for s in cell['source']]

        # 4. Pipeline Tests - Execution
        elif "pipeline_tests.run_all(qwen, usda_client)" in source_str or ("pipeline_tests.test_pipeline_tools" in source_str and "p1 =" in source_str):
            cell['source'] = [
                "import tests.test_pipeline as pipeline_tests\n",
                "\n",
                "pipe_results = pipeline_tests.run_all(qwen, usda_client)\n",
                "for i, r in enumerate(pipe_results):\n",
                "    method_slug = r['method'].lower().replace(' ', '_')\n",
                "    save_raw_output(f\"p{i+1}_pipeline_{method_slug}_{r['image']}.json\", r.get(\"raw_output\"))\n"
            ]

        # 5. Pipeline Results Aggregation
        elif "pipe_results = [p1, p2, p3, p4]" in source_str:
            cell['source'] = [s.replace("pipe_results = [p1, p2, p3, p4]", "pipe_results = pipe_results # Already defined") for s in cell['source']]

        # 6. API Tests
        elif "api_tests.test_health_check()" in source_str or "api_tests.run_all()" in source_str:
            # We want to keep the try/except/finally structure but replace the test calls
            lines = cell['source']
            new_lines = []
            skip = False
            for line in lines:
                if "api_tests.test_health_check()" in line or "api_results = api_tests.run_all()" in line:
                    if "api_results = api_tests.run_all()" not in "".join(new_lines):
                        new_lines.append("    api_results = api_tests.run_all()\n")
                    skip = True
                elif skip and ("api_tests.test_analyze" in line or "api_results = [" in line):
                    continue
                elif skip and "print(f\"\\nAPI tests passed:" in line:
                    new_lines.append("    print(f\"\\nAPI tests passed: {sum(1 for r in api_results if r.get('success'))}/{len(api_results)}\")\n")
                    skip = False
                elif not skip:
                    new_lines.append(line)
            cell['source'] = new_lines

with open(path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

print("✅ test_all.ipynb refactored successfully.")
