# USDA Client — Reference

Use this skill when implementing USDA lookup features, modifying caching behavior, or writing new tool dispatchers in the Bedrock integration.

---

## Client Initialization

```python
from third_apis.USDA import USDAClient

usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
```

- Pass `api_key="DEMO_KEY"` for offline/mock mode — all lookups return synthetic nutrition data, no HTTP calls made.
- `USDAClient` is a singleton-style heavy object. Initialize once at app startup and reuse.

---

## Public Method Signatures

### `get_nutritions(query, pageSize=5) → Dict[str, float]`
Returns per-100g nutrition dict. Falls back to mock data on USDA miss.
```python
{
    "calories": 130.0,   # kcal per 100g
    "protein":  2.7,     # g per 100g
    "carbs":    28.2,    # g per 100g
    "fat":      0.1      # g per 100g
}
```

### `get_ingredients(query, pageSize=5) → Optional[List[str]]`
Returns ingredient list string parsed from USDA food entry. Returns `None` on miss.

### `get_nutritions_and_ingredients(query, pageSize=5) → Optional[Dict]`
Combined lookup — single cache hit. Returns:
```python
{
    "description": "white rice, cooked",
    "nutritions":  {"calories": ..., "protein": ..., "carbs": ..., "fat": ...},  # per 100g
    "ingredients": ["water", "rice"]
}
```

### `get_nutritions_and_ingredients_by_weight(query, weight_g, pageSize=5) → Optional[Dict]`
**Primary method used by the Bedrock tool dispatcher.** Calls `get_nutritions_and_ingredients()` then scales by `weight_g`.
```python
{
    "description": "white rice, cooked",
    "nutritions":  {"calories": 234.0, "protein": 4.9, "carbs": 50.8, "fat": 0.4},  # actual for weight_g
    "weight_g":    180.0,
    "ingredients": ["water", "rice"]
}
```

### `search_best(normalized_query, pageSize=5) → Optional[dict]`
Internal cache-aware search. Returns raw USDA food entry dict. Use public methods instead.

---

## Cache Behavior

### L1 — RAM LRU
- Module-level singleton `_l1: _LRUCache` with `maxsize=256`.
- Survives for the lifetime of the process.
- Key: `normalized_query` string (lowercased, Unicode-normalized).
- On hit: promotes entry to MRU position.

### L2 — Disk JSON
- File: `data/usda_cache.json`
- Key: normalized query string.
- Entry structure: `{_ts: unix_timestamp, …USDA food fields}`.
- TTL: 30 days (`_CACHE_TTL_DAYS`). Expired entries trigger a fresh L3 call.
- Loaded once at module import; saved after every L3 miss + fetch.

### L3 — USDA FoodData Central API
- Endpoint: `GET https://api.nal.usda.gov/fdc/v1/foods/search`
- Parameters: `query`, `pageSize`, `api_key`
- On success: result saved to L1 and L2 (and optionally S3).

### S3 Sync (optional)
- Triggered by env var `AWS_S3_CACHE_BUCKET`.
- On startup: downloads `usda_cache.json` from S3 → local disk (cold-start warm-up).
- On every L2 write: uploads updated cache to S3 (background, fire-and-forget style).
- Errors during S3 sync are logged as warnings — they never block the main flow.

---

## Query Normalization

All queries go through `_normalize_query(query)` before cache lookup:
- Unicode NFC normalization
- Lowercased, stripped
- Basic diacritic removal for Vietnamese food names

This ensures `"Cơm Tấm"` and `"com tam"` map to the same cache key.

---

## Mock Data (DEMO_KEY)

When `api_key == "DEMO_KEY"`, `get_nutritions()` returns a fixed mock dict and `search_best()` returns `None`. No network calls are made. Use for:
- Local development without a real USDA key
- Unit tests that shouldn't depend on external APIs

---

## Nutrient ID Mapping

The client parses these USDA nutrient IDs from the API response:

| USDA nutrient ID | Field |
|---|---|
| `203` | `protein` |
| `204` | `fat` |
| `205` | `carbs` |
| `208`, `2047`, `2048` | `calories` (kcal only) |

---

## Integration with Bedrock Tool Calling

In the tools pipeline, `USDAClient.get_nutritions_and_ingredients_by_weight()` is the Python function that backs the Bedrock tool `get_nutritions_and_ingredients_by_weight`. The dispatcher in `QWEN3VL.analyze_with_tool_calling()` extracts `food_name` and `weight_g` from `toolUse.input` and calls this method directly:

```python
result = usda_client.get_nutritions_and_ingredients_by_weight(
    query=tool_input["food_name"],
    weight_g=float(tool_input["weight_g"])
)
tool_result_content = json.dumps(result or {}, ensure_ascii=False)
```

The result is returned to the model as a `toolResult` block and the loop continues until `stopReason != "tool_use"`.

---

## Error and Fallback Behavior

| Situation | Behavior |
|---|---|
| L1 miss + L2 hit (not expired) | Return L2 entry, promote to L1 |
| L2 miss or expired | Call L3 (USDA API), save to L1 + L2 |
| USDA API returns 0 results | `search_best()` returns `None`; `get_nutritions()` falls back to mock |
| USDA API error / network failure | Exception caught, logged as warning, falls back to mock |
| `weight_g == 0` | `calculate_ingredient_nutrition()` returns all zeros |
