# Project Setup Plan

## Context
- Need to initialize project configuration files for NutriTrack.
- Must set up CLAUDE.md, memory, settings, MCP servers.
- Align with project structure described in documentation.

## Goals
1. Ensure `.claude/CLAUDE.md` contains the provided project instructions.
2. Create necessary memory files for user, feedback, project, reference.
3. Configure `.claude/settings.json` and `settings.local.json` for API keys and logging.
4. Verify MCP servers are correctly defined in `.claude/.mcp.json`.
5. Set up initial memory entries for user role, feedback, and project context.

## Steps

1. **Read existing documentation** in `app/` to confirm project layout:
   - Read `app/README.md` (if exists) or use provided instructions.
   - Confirm directory structure matches `app/` layout.

2. **Create/Update CLAUDE.md**:
   - Overwrite `app/.claude/CLAUDE.md` with the content from `D:\Project\Code\nutritrack-documentation\app\.claude\CLAUDE.md` (already exists). Ensure it's up-to-date.

3. **Initialize Memory**:
   - Create `app/.claude/memory/` if not exists.
   - Save initial memories:
     - `user.md` describing user role/goals.
     - `feedback.md` capturing any known user preferences.
     - `project.md` outlining current project state and deadlines.
     - `reference.md` pointing to external resources (e.g., AWS Bedrock docs).

4. **Configure Settings**:
   - Edit `app/.claude/settings.json` to include:
     - Logging level config.
     - Any required environment variables (e.g., `DEMO_KEY` placeholder).
   - Optionally create `settings.local.json` for local overrides (ensure not committed).

5. **Verify MCP Servers**:
   - Confirm `app/.claude/.mcp.json` includes all required servers:
     - `fetch`, `aws-core`, `aws-documentation`, `aws-diagram`, `code-review-graph`.
   - Ensure command paths are correct for `npx` and `uvx`.

6. **Final Validation**:
   - Use `Read` tool to inspect each generated file.
   - Ensure no syntax errors in JSON files.
   - Confirm that all documented paths match actual file locations.

## Verification Method
- Use `Read` tool to inspect each generated file.
- Ensure no syntax errors in JSON files.
- Confirm that all documented paths match actual file locations.

## Dependencies
- None external; only file system operations.

## Risks
- Overwriting existing `.claude/CLAUDE.md` without backup (ensure version control).
- Incorrect JSON formatting causing CLI errors on next run.

## Next Actions
- Execute the plan steps sequentially.
- After completion, call `ExitPlanMode` to signal readiness for implementation.