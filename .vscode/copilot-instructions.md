# NutriTrack — GitHub Copilot Instructions

## Project Purpose
NutriTrack is a FastAPI service that uses **AWS Bedrock Qwen3-VL 235B** to analyze food photos and return structured nutritional data (calories, protein, carbs, fat) per dish and ingredient. It supplements vision model output with real USDA FoodData Central lookups.

## Key Architecture
- **Entry point**: `scripts/pipeline.py` → `analyze_nutrition(image_path, method="tools"|"manual")`
- **Vision model**: `models/QWEN3VL.py` — Bedrock `converse()` API, supports tool-calling loop
- **Nutrition data**: `third_apis/USDA.py` — 2-tier cache (RAM LRU + JSON file) → USDA API
- **API server**: `templates/api.py` — FastAPI with lifespan-managed clients (`POST /analyze`, `GET /health`)
- **UI**: `templates/ui.py` — Gradio interface

## Core Data Model (Pydantic v2, `models/QWEN3VL.py`)
```
FoodList → dishes: List[FoodItem] → ingredients: List[Ingredient] → estimated_nutritions: NutritionInfo
```
`FoodList` is returned by both pipeline methods.

## Two Analysis Methods
| Method | Description |
|--------|-------------|
| `tools` | Model calls `get_nutritions_and_ingredients_by_weight()` via Bedrock tool-calling loop |
| `manual` | 2-step: Qwen identifies dishes → code loops USDA per-ingredient |

## Non-Negotiable Rules
1. **Logging**: always `from config.logging_config import get_logger; logger = get_logger(__name__)` — never `logging.getLogger()`
2. **Pydantic v2**: use `model_validate()` / `model_dump()` — never `parse_obj()` / `.dict()`
3. **Image limit**: 3 MB for Bedrock — `utils/processor.py` handles compression
4. **Type hints**: required on all function signatures
5. **No new deps** without updating `requirements.txt`

## Skill Files
For deeper context on specific subsystems, reference these files in your Copilot Chat:
- `#nutritrack-architecture` — full pipeline data flow, caching, Pydantic schemas
- `#usda-client` — USDA client method signatures, cache layers, S3 sync

## Copilot Bridge To .claude
- Treat `.claude/` as the source of truth for project-specific rules, skills, and MCP context.
- Before proposing code changes, prioritize these files when relevant:
	- `.claude/CLAUDE.md`
	- `.claude/rules/python-conventions.instructions.md`
	- `.claude/rules/api-patterns.instructions.md`
	- `.claude/rules/bedrock-integration.instructions.md`
	- `.claude/rules/test-conventions.instructions.md`
	- `.claude/skills/nutritrack-architecture.md`
	- `.claude/skills/usda-client.md`
- If guidance conflicts, follow this precedence:
	1. `.github/copilot-instructions.md`
	2. Matching `.claude/rules/*.instructions.md`
	3. `.claude/skills/*.md`
	4. `.claude/CLAUDE.md`

## Prompt And Instruction Files
- Prompt file example: `.github/prompts/plan-claudeFolderSetup.prompt.md`.
- Use prompt files for planning/workflow generation.
- Use `.instructions.md` files for coding behavior and style constraints.

## MCP Tooling (Copilot In VS Code)
- Register MCP servers via VS Code MCP config (workspace-level), not only `.claude/.mcp.json`.
- Keep `.claude/.mcp.json` as Claude-oriented config and mirror active servers into `.vscode/mcp.json` for Copilot usage.
