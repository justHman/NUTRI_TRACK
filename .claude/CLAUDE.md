# NutriTrack — Project Reference

## What This Project Does
NutriTrack analyzes food photos and returns detailed nutritional breakdowns (calories, protein, carbs, fat per dish and per ingredient). A user uploads an image → the system identifies dishes, lists ingredients, estimates portion weights, and returns structured JSON nutrition data.

---

## Tech Stack
| Layer | Technology |
|---|---|
| Vision model | AWS Bedrock — Qwen3-VL 235B (`qwen.qwen3-vl-235b-a22b`) |
| Framework | FastAPI + Uvicorn |
| UI | Gradio |
| Nutrition data | USDA FoodData Central API |
| Structured output | Pydantic v2 |
| Deployment | Docker, AWS AppRunner |
| Cache backend | In-process LRU (L1) + JSON file (L2) + optional S3 sync |

---

## Project Layout
```
app/
├── scripts/pipeline.py         # Main orchestrator — call analyze_nutrition()
├── models/QWEN3VL.py           # Qwen3VL client + Pydantic schemas (FoodList, FoodItem, …)
├── templates/api.py            # FastAPI app (lifespan, /analyze, /health)
├── templates/ui.py             # Gradio frontend
├── third_apis/USDA.py          # USDAClient — 2-tier cache + FoodData Central calls
├── utils/processor.py          # Image preprocessing for Bedrock (JPEG/PNG, 3 MB cap)
├── utils/caculator.py          # Nutrition math + cooking-method adjustments
├── config/
│   ├── logging_config.py       # get_logger() — always use this, never logging.getLogger directly
│   ├── prompt_config.py        # System & user prompts for Qwen
│   └── nutrition_tool_config.json  # Bedrock toolConfig for get_nutritions_and_ingredients_by_weight
├── data/
│   ├── usda_cache.json         # L2 persistent cache (auto-managed, commit to repo)
│   └── results/                # Analysis output JSON files (timestamped)
└── config/.env                 # AWS credentials + USDA key (not committed)
```

---

## Key Pydantic Schemas (models/QWEN3VL.py)
```python
NutritionInfo       # calories, protein, carbs, fat (all float, kcal/g)
Ingredient          # name, vi_name, estimated_weight_g, estimated_nutritions, confidence, note
FoodItem            # name, vi_name, confidence, cooking_method, ingredients[], totals, scale_reference_used
FoodList            # dishes: List[FoodItem], image_quality
```
`FoodList` is the single return type of both analysis methods.

---

## Two Analysis Methods

### `method="tools"` (recommended)
`analyze_food_with_tools()` — Qwen calls `get_nutritions_and_ingredients_by_weight(food_name, weight_g)` via Bedrock tool-calling. The model drives all USDA lookups. Returns a `FoodList` parsed from the final assistant message.

### `method="manual"` (2-step)
1. `qwen.analyze_food()` — Qwen identifies dishes/ingredients from the image
2. For each ingredient: `usda_client.get_nutritions(name)` → `calculate_ingredient_nutrition(usda_100g, weight_g)`
Returns a `FoodList` with USDA-overridden nutrition where available.

Entry point for both: `scripts/pipeline.py::analyze_nutrition(image_path, method=…)`

---

## USDAClient — Cache Hierarchy
```
L1: RAM LRU (256 entries, per-process)
L2: data/usda_cache.json (30-day TTL, persists across restarts)
L3: USDA FoodData Central API (only on L1+L2 miss)
    → result written back to L1 + L2 (and S3 if AWS_S3_CACHE_BUCKET is set)
```
Use `DEMO_KEY` = mock data returned, no real API calls.

---

## Environment Variables (config/.env)
```
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
USDA_API_KEY=...           # get from https://fdc.nal.usda.gov/api-guide.html
AWS_S3_CACHE_BUCKET=...    # optional; enables S3 USDA cache sync
```

---

## Common Commands
```bash
# Run API server (from app/ directory)
uvicorn templates.api:app --host 0.0.0.0 --port 8000 --reload

# Run pipeline directly
python -m scripts.pipeline <image_path> --method tools

# Run tests
pytest tests/ -v

# Docker
docker build -t nutritrack .
docker run -p 8000:8000 --env-file config/.env nutritrack

# Install dependencies
pip install -r requirements.txt
```

---

## Logging
Always use `get_logger` from `config/logging_config.py`:
```python
from config.logging_config import get_logger
logger = get_logger(__name__)
```
The logger supports `logger.title("…")` for section headers. Never use `logging.getLogger()` directly.

---

## Cooking Method Nutrition Adjustments (utils/caculator.py)
| Method | Adjustment |
|---|---|
| `fried` | +30% calories & fat |
| `grilled` | +15% calories & fat |
| `steamed`, `boiled`, `raw`, `mixed` | no change |

---

## Deployment
- **AppRunner**: `apprunner.yaml` — runtime Python 3.11, port 8000, build `pip install -r requirements.txt`, start `uvicorn templates.api:app --host 0.0.0.0 --port 8000`
- **ECS/Fargate**: see `docs/ecs_deployment_guide.md`
- **Docker**: `Dockerfile` — base `python:3.10-slim`, internal port 8000

---

## Notes for AI Assistants
- The project root assumed inside Docker is `app/`. All imports are relative to `app/`.
- Do not add new dependencies without updating `requirements.txt`.
- All new data models must use Pydantic v2 (`model_validate`, `model_dump`, not `parse_obj`/`dict()`).
- Image size limit for Bedrock: 3 MB raw — `utils/processor.py` handles compression automatically.
- `analyze_with_instructor()` in QWEN3VL.py is intentionally disabled (commented out) — do not uncomment without first confirming Qwen3VL supports BEDROCK_TOOLS mode.
