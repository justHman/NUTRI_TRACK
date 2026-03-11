---
applyTo: "models/*.py"
---

# Bedrock Integration Patterns — NutriTrack

## Client Initialization
- Always use `boto3.client("bedrock-runtime", region_name=self.region, config=Config(read_timeout=300))`.
- `read_timeout=300` is mandatory — vision model inference on large images can take 60–120 s.
- Region resolution order: constructor arg → `AWS_REGION` → `AWS_DEFAULT_REGION` → `"us-east-1"`.

## Converse API Call Structure
All Bedrock calls go through `self.client.converse(…)`:
```python
response = self.client.converse(
    modelId=self.model_id,
    messages=[{
        "role": "user",
        "content": [
            {"image": {"format": img_format, "source": {"bytes": image_bytes}}},
            {"text": prompt}
        ]
    }],
    system=[{"text": system_prompt}],   # optional
    inferenceConfig={"maxTokens": 8192, "temperature": 0.2, "topP": 0.9},
    toolConfig=NUTRITION_TOOL_CONFIG,   # only for tool-calling method
)
```
- Track token usage after every call: `self.input_tokens += response["usage"]["inputTokens"]`.

## Tool-Calling Loop Pattern
```
while stopReason == "tool_use":
    1. Append assistant message (with toolUse blocks) to messages list
    2. For each toolUse block → dispatch to corresponding Python function
    3. Append tool results as role="user" with toolResult blocks
    4. Call converse() again with updated messages
Stop when stopReason != "tool_use" → extract text from final message
```
- Validate tool inputs before dispatch: check `food_name` and `weight_g` are present and non-empty.
- Normalize tool names defensively: `get_nutritions_and*` → `get_nutritions_and_ingredients_by_weight`.
- Strip invalid `toolUse` blocks (missing name or inputs) before appending to messages to avoid `ParamValidationError`.

## Structured Output Parsing
- Parse the final assistant text response with `FoodList.model_validate_json(clean_json)`.
- Extract JSON from the response robustly:
  1. Try `re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)` first.
  2. Fall back to `text[text.find('{'):text.rfind('}')+1]`.
- Never trust raw response text as valid JSON without extraction.

## Disabled Features
- `analyze_with_instructor()` is intentionally commented out — Qwen3VL does not support `BEDROCK_TOOLS` mode in instructor. Do not uncomment without confirming model support.

## Image Preprocessing
- Always use `utils/processor.py::prepare_image_for_bedrock(image_path, image_bytes, filename)` before sending to Bedrock.
- This enforces the 3 MB raw limit and JPEG/PNG format requirement automatically.
