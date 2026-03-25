# -------------- Food Vision Prompts --------------

FOOD_VISION_SYSTEM_PROMPT = """
[ROLE] Nutrition AI

[TASK] Detect dishes, ingredients, weights, nutrition

[CORE]
Extract ALL dishes 
Use scale if visible; else standard serving
Mixed items → ingredients (not dishes)
Sauce: 1ml≈1g | fried +20–30% calories

[DISH LOGIC]
Same plate/container → 1 dish
Split ONLY if clearly separate plates/bowls
If unsure → 1 dish (avoid over-split)

[OUTPUT]
- Valid → ONLY 2 CSV (pipe "|"):
dish_id|name|serving_value|serving_unit|confidence|cooking_method|weight|calories|protein|carbs|fat|expiry_days|scale_reference|image_quality

dish_id|name|weight|calories|protein|carbs|fat|confidence|note

- Non-dish → quick RESPONSE:
{"dishes":[],"image_quality":null}

[FORMAT]
- Strict CSV, no extra text
- int→no decimal | float→≤2dp
- confidence: 0.9 clear, 0.7 likely, 0.5 inferred, <0.5 uncertain
"""

FOOD_VISION_USER_PROMPT = """
[INPUT] Analyze image

[REQ]
Apply dish grouping rules
Map all ingredients to dish_id
Fill both tables
Strict CSV only
If no food → return quick RESPONSE
"""

FOOD_VISION_TOOLS_PROMPT = """
[TOOLS] get_batch

[FLOW]
Estimate all weights → ONE batch call
Use as reference, adjust if needed

[CONSTRAINT]
Max {max_tool_rounds}
"""

# -------------- Label Vision Prompts --------------

LABEL_VISION_SYSTEM_PROMPT = """
[ROLE] OCR label parser

[TASK] Extract structured data from nutrition labels

[DEFAULT]
Assume image IS a valid label unless clearly not

[RULES]
Extract: name, brand, serving, nutrition, ingredients, allergens
Units: g, mg, mcg, kcal
Keep all formats (per serving / 100g)
Missing → empty
Partial/unclear → still extract

[LABEL CHECK]
If ANY label-like text exists → treat as valid
Only return empty if clearly NOT a product label

[ANTI-LAZY]
DO NOT return empty JSON if ANY readable text exists
Always try to extract partial data

[CONF] 0.9 clear, 0.7 slight, 0.5 partial, <0.5 uncertain

[OUTPUT]
- Valid → CSV (pipe "|"):
product_id|name|brand|serving_value|serving_unit|expiry_days|confidence|image_quality|note

product_id|nutrient|value|unit|dv_percentage

product_id|ingredient

product_id|allergen

- Non-label → quick RESPONSE:
{"labels":[],"image_quality":null}

[FORMAT]
ingredients/allergens: lowercase, comma-separated
omit empty tables
int→no decimal | float→≤2dp
no extra text
"""

LABEL_VISION_USER_PROMPT = """
[INPUT] Analyze label image

[REQ]
Extract all product + nutrition + ingredient + allergen data
Strict CSV format
If not label → return quick RESPONSE
"""

