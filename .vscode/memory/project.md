---
name: project
description: NutriTrack project: analyze food photos with Qwen3-VL and USDA API, FastAPI + Gradio, Docker/AppRunner deployment.
type: project
---

Current state:
- Tech stack: AWS Bedrock (Qwen3-VL), FastAPI, Gradio, USDA API, Pydantic v2.
- Key modules: models/QWEN3VL.py, scripts/pipeline.py, templates/api.py, third_apis/USDA.py.
- L1/L2 caching implemented; S3 optional.
- Docker and AppRunner configs exist.

Recent activity (git):
- Branch `tera` active.
- Modified: .claude/.mcp.json, config/prompt_config.py, data/usda_cache.json, templates/api.py, utils/transformer.py.

No hard deadlines defined yet.