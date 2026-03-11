# Plan: Setup `.claude` Folder for NutriTrack

**TL;DR**: Populate the empty `.claude` folder with GitHub Copilot custom instructions, coding rules, skill files, and MCP config — all tuned to NutriTrack's AWS Bedrock + FastAPI + USDA architecture.

---

## Phase 1 — Always-on Instructions

### 1. Fill `.claude/CLAUDE.md`
Full project overview: purpose, architecture map, analysis methods (`tools` vs `manual`), key commands (`uvicorn`, `pytest`, `docker`), env vars, deployment notes. Serves as reference doc for both Copilot and Claude Code.

### 2. Create `.github/copilot-instructions.md` *(new file)*
Compact "always on" system context for GitHub Copilot Chat (< 50 lines): project purpose, stack, key files, and how to reference skill files for deeper knowledge. *Parallel with step 1.*

---

## Phase 2 — Scoped Rules (`.instructions.md` with `applyTo` frontmatter)

### 3. Create `.claude/rules/python-conventions.instructions.md`
`applyTo: **/*.py`
Rules: Pydantic v2 models for all data structures, mandatory type hints, logging via `config/logging_config.py`, no bare `except`, prefer `Path` over `os.path`. *Parallel with steps 4–5.*

### 4. Create `.claude/rules/api-patterns.instructions.md`
`applyTo: templates/*.py`
FastAPI lifespan pattern (from `templates/api.py`), response schema via Pydantic, `HTTPException` for errors, `BackgroundTasks` for async side effects. *Parallel with steps 3, 5.*

### 5. Create `.claude/rules/bedrock-integration.instructions.md`
`applyTo: models/*.py`
Bedrock `converse()` API call pattern, tool-calling loop (stop reason `tool_use` → run tool → append result → continue), error handling for `ThrottlingException`. *Parallel with steps 3–4.*

---

## Phase 3 — Skills (`.claude/skills/`)

### 6. Create `.claude/skills/nutritrack-architecture.md`
Full architecture knowledge for large tasks: pipeline data flow, `FoodList`→`FoodItem`→`Ingredient`→`NutritionInfo` Pydantic schema, L1/L2 caching strategy, cooking-method nutrition adjustments.

### 7. Create `.claude/skills/usda-client.md`
USDA client patterns: method signatures (`get_nutritions_and_ingredients_by_weight`), 2-tier cache structure, S3 sync behavior, mock mode for `DEMO_KEY`. *Parallel with step 6.*

---

## Phase 4 — Tooling Config

### 8. Fill `.claude/.mcp.json`
Add `fetch` (`@modelcontextprotocol/server-fetch` — for testing USDA/API endpoints) and `brave-search` (`@modelcontextprotocol/server-brave-search` — with `BRAVE_API_KEY` placeholder for AWS/USDA docs lookup).

### 9. Fill `.claude/settings.json`
Allow list: `Bash(python:*)`, `Bash(pytest:*)`, `Bash(pip:*)`, `Bash(uvicorn:*)`, `Bash(docker:*)`.

### 10. Update `.vscode/settings.json` *(create if absent)*
Add `"github.copilot.chat.codeGeneration.useInstructionFiles": true` to enable auto-discovery of `.instructions.md` files.

---

## Relevant Files (reference only, do not modify)

- `.claude/CLAUDE.md` — fill (currently empty)
- `.claude/.mcp.json` — fill (currently empty)
- `.claude/settings.json` — fill (currently empty)
- `scripts/pipeline.py` — reference for architecture/flow docs
- `models/QWEN3VL.py` — reference for Bedrock rule patterns
- `templates/api.py` — reference for FastAPI rule patterns
- `third_apis/USDA.py` — reference for USDA skill content

## New Files to Create

- `.github/copilot-instructions.md`
- `.claude/rules/python-conventions.instructions.md`
- `.claude/rules/api-patterns.instructions.md`
- `.claude/rules/bedrock-integration.instructions.md`
- `.claude/skills/nutritrack-architecture.md`
- `.claude/skills/usda-client.md`

---

## Verification

1. Open GitHub Copilot Chat → ask "What is this project?" → should return NutriTrack-specific context without you describing it.
2. Open `models/QWEN3VL.py` and ask Copilot to add a method → it should follow Bedrock `converse()` patterns from the rule.
3. Check VS Code Settings → `github.copilot.chat.codeGeneration.useInstructionFiles` is `true`.
4. In Copilot Chat, start a message with `#usda-client` → the skill content should be injected.

---

## Decisions

- `agents/` folder skipped (not in priorities)
- `brave-search` requires a real `BRAVE_API_KEY` — plan includes a placeholder; fill it from https://api.search.brave.com/
- `.github/copilot-instructions.md` is a new file outside `.claude/` but is the standard GitHub Copilot path for always-applied instructions

---

## Open Questions

1. **`BRAVE_API_KEY`** — Do you already have a Brave Search API key, or use the placeholder?
2. **`.vscode/settings.json`** — If one already exists, the key will be merged into it; flag any conflicts before implementation.
