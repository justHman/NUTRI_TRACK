import json
path = r'd:\Project\Code\nutritrack-documentation\app\tests\test_all.ipynb'
with open(path, 'r', encoding='utf-8') as f:
    nb = json.load(f)

for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        source = "".join(cell.get('source', []))
        if "pipeline_tests.run_all(qwen, usda_client)" in source and "for i, r in enumerate(" in source:
            cell['source'] = [
                "import importlib\n",
                "import tests.test_pipeline as pipeline_tests\n",
                "importlib.reload(pipeline_tests)\n",
                "\n",
                "pipe_results = pipeline_tests.run_all(qwen, usda_client)\n",
                "for i, r in enumerate(pipe_results):\n",
                "    method_slug = r.get('method', 'unknown').lower().replace(' ', '_')\n",
                "    save_raw_output(f\"p{i+1}_pipeline_{method_slug}_{r.get('image', 'img')}.json\", r.get(\"raw_output\"))\n"
            ]
            break

with open(path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
    
print("Fixed notebook.")
