# NutriTrack Architecture — Full Reference

Use this skill when working on cross-cutting features, large refactors, or anything that touches multiple layers of the pipeline.

---

## End-to-End Data Flow

```
User uploads image
       │
       ▼
templates/api.py  POST /analyze?method=tools|manual
       │  reads bytes, calls analyze_nutrition()
       ▼
scripts/pipeline.py  analyze_nutrition(image_path, …, method)
       │
       ├─ method="tools" ──► _analyze_with_tools()
       │       │
       │       ▼
       │  models/QWEN3VL.py  analyze_food_with_tools()
       │       │  Bedrock converse() + toolConfig
       │       │
       │       ▼ (stopReason == "tool_use")
       │  Tool dispatcher calls:
       │  third_apis/USDA.py  get_nutritions_and_ingredients_by_weight(name, weight_g)
       │       │  L1 → L2 → USDA API
       │       │
       │       ▼ (stopReason == "end_turn")
       │  Parse final assistant text → FoodList.model_validate_json()
       │
       └─ method="manual" ──► _analyze_manual()
               │
               ▼
          models/QWEN3VL.py  analyze_food()
               │  Identifies dishes + estimates ingredients (no USDA)
               ▼
          For each ingredient:
          third_apis/USDA.py  get_nutritions(name)  → per-100g dict
          utils/caculator.py  calculate_ingredient_nutrition(usda_100g, weight_g)
               ▼
          Aggregate nutrition, apply cooking-method adjustments
               ▼
          Return FoodList.model_dump()
```

---

## Pydantic Schema Hierarchy

```python
class NutritionInfo(BaseModel):
    calories: float   # kcal
    protein:  float   # g
    carbs:    float   # g
    fat:      float   # g

class Ingredient(BaseModel):
    name:                 str
    vi_name:              Optional[str]
    estimated_weight_g:   Optional[float]
    estimated_nutritions: Optional[NutritionInfo]
    confidence:           Optional[float]   # 0.0 – 1.0
    note:                 Optional[str]     # e.g. "inferred – typical pho garnish"

class FoodItem(BaseModel):
    name:                        str
    vi_name:                     Optional[str]
    confidence:                  Optional[float]
    cooking_method:              Optional[str]  # grilled | fried | steamed | boiled | raw | mixed
    ingredients:                 List[Ingredient]
    total_estimated_weight_g:    Optional[float]
    total_estimated_nutritions:  Optional[NutritionInfo]
    scale_reference_used:        Optional[str]

class FoodList(BaseModel):
    dishes:        List[FoodItem]
    image_quality: Optional[str]  # good | poor_lighting | blurry | partial_view
```

`FoodList` is the **only** return type from both pipeline paths. Always use `model_dump()` when serializing.

---

## USDA Cache Hierarchy

```
L1: RAM LRU (_LRUCache, maxsize=256, module-level singleton)
    key: normalized_query string
    value: best USDA food dict

L2: data/usda_cache.json (30-day TTL)
    key: normalized_query string
    value: {_ts: float, ...USDA food dict fields}

L3: USDA FoodData Central API
    endpoint: GET /fdc/v1/foods/search?query=…&api_key=…
    → on miss: result saved to L1 + L2 + optional S3 upload

Optional S3 sync:
    env: AWS_S3_CACHE_BUCKET
    key: usda_cache.json
    on startup: download from S3 to local L2
    on write: upload updated L2 to S3
```

`DEMO_KEY` short-circuits all network calls and returns mock data — useful for tests without real API keys.

---

## Cooking Method Adjustments (utils/caculator.py)

Applied to `total_estimated_nutritions` after summing ingredients:

| `cooking_method` value | Calories multiplier | Fat multiplier |
|---|---|---|
| `"fried"` | ×1.30 | ×1.30 |
| `"grilled"` | ×1.15 | ×1.15 |
| `"steamed"`, `"boiled"`, `"raw"`, `"mixed"` | ×1.00 | ×1.00 |
| (anything else) | ×1.00 | ×1.00 |

---

## Bedrock Tool Config (config/nutrition_tool_config.json)

The JSON file is loaded at module import in `QWEN3VL.py` and passed as `toolConfig` to every `converse()` call in the tools method. The single registered tool is:

```json
{
  "name": "get_nutritions_and_ingredients_by_weight",
  "description": "Look up USDA nutrition data for a food item by name and weight",
  "inputSchema": {
    "json": {
      "type": "object",
      "properties": {
        "food_name": { "type": "string" },
        "weight_g":  { "type": "number" }
      },
      "required": ["food_name", "weight_g"]
    }
  }
}
```

---

## Prompt Architecture (config/prompt_config.py)

| Constant | Used by | Purpose |
|---|---|---|
| `FOOD_VISION_SYSTEM_PROMPT` | `analyze_food()` (manual method) | Role, rules, edge cases |
| `FOOD_VISION_USER_PROMPT` | `analyze_food()` (manual method) | JSON schema template in prompt |
| `FOOD_VISION_TOOLS_PROMPT` | `analyze_food_with_tools()` | Tool-use instructions (appended to system prompt) |

---

## Image Preprocessing (utils/processor.py)

`prepare_image_for_bedrock(image_path, image_bytes, filename) → (bytes, format_str)`

- Accepts path **or** raw bytes (for API upload path).
- Converts RGBA → RGB before JPEG compression.
- Resizes to max 1024px longest edge if over limit.
- Enforces 3 MB cap via iterative JPEG quality reduction.
- Returns `(compressed_bytes, "jpeg"|"png")`.

---

## FastAPI Lifespan Pattern

`Qwen3VL` and `USDAClient` are initialized **once at startup** as module-level globals:
```python
qwen_client: Qwen3VL = None
usda_client: USDAClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global qwen_client, usda_client
    qwen_client = Qwen3VL()
    usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
    yield
    # shutdown cleanup here if needed
```
Endpoint handlers reference these globals directly — never re-initialize per request.

---

## Deployment Targets

| Target | Config file | Start command |
|---|---|---|
| Local dev | `config/.env` | `uvicorn templates.api:app --reload` |
| Docker | `Dockerfile` (python:3.10-slim) | `uvicorn templates.api:app --host 0.0.0.0 --port 8000` |
| AWS AppRunner | `apprunner.yaml` | same as Docker, runtime Python 3.11 |
| ECS/Fargate | `docs/ecs_deployment_guide.md` | Task definition with env from Secrets Manager |
