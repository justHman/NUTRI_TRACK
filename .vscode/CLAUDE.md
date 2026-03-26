# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands
- **Run the API server**: `uvicorn templates.api:app --host 0.0.0.0 --port 8000 --reload`
- **Run the pipeline directly**: `python -m scripts.pipeline <image_path> --method tools`
- **Run tests**: `pytest tests/ -v`
- **Build the project**: `pip install -r requirements.txt`
- **Docker build**: `docker build -t nutritrack .`
- **Docker run**: `docker run -p 8000:8000 --env-file config/.env nutritrack`

## Project Architecture
NutriTrack is organized as follows:
- **Vision model**: AWS Bedrock — Qwen3-VL 235B (`qwen.qwen3-vl-235b-a22b`)
- **Backend**: FastAPI + Uvicorn (lifespan management with `@asynccontextmanager`)
- **UI**: Gradio frontend (`templates/ui.py`)
- **Nutrition data**: USDA FoodData Central API via `third_apis/USDA.py`
- **Structured output**: Pydantic v2 models (`models/QWEN3VL.py`)
- **Caching**: L1 RAM LRU, L2 JSON file (`data/usda_cache.json`), optional S3 sync
- **Configuration**: `config/` contains prompt configs, logging config, and Bedrock tool config
- **Utilities**:
  - `utils/processor.py` for image preprocessing
  - `utils/caculator.py` for nutrition math and cooking adjustments

## Key Entry Points
- **Pipeline**: `scripts/pipeline.py::analyze_nutrition()`
- **FastAPI endpoints**: `templates/api.py` (`/analyze`, `/health`)
- **Gradio UI**: `templates/ui.py`

## Logging Standard
- All modules import and use `get_logger(__name__)` from `config.logging_config`.
- Use `logger.info()` for milestones, `logger.debug()` for internals, `logger.warning()` for handled edge cases, and `logger.error(..., exc_info=True)` before raising exceptions.
- Use `logger.title("…")` for section headers.

## Important Notes
- Image size limit for Bedrock is 3 MB raw; preprocessing enforces this.
- Do not add dependencies without updating `requirements.txt`.
- All new data models must use Pydantic v2 (`model_validate`, `model_dump`).
- Use `allow_origins=["*"]` only for development; restrict in production.
- Health check (`/health`) must return `qwen_model` and `usda_ready` without delay.
