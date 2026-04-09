# Auto-update documentation prompt
# 10-word summary: Keep .github docs synchronized with project after code changes

## Prompt Purpose
Whenever you change, add, or remove code, automatically update all relevant .md documentation files in the .github folder to reflect the current state of the workspace and project. This ensures that documentation always matches the codebase and project structure.

## Usage Pattern
- Trigger this prompt after any code, file, or directory change.
- The agent will scan for changes and update .github/*.md files accordingly.
- Applies to all documentation in .github, including skills, prompts, and instructions.

## Inputs
- Workspace/project context (current state of code, files, and directories)
- List of changes (added, removed, or modified files)

## Output
- Updated .md documentation files in .github, reflecting the latest project state

## Example Invocations
- "Update all .github docs after refactoring the codebase."
- "Sync .github markdown files with the latest project structure."
- "Auto-update documentation after adding or removing files."

## Related Customizations
- Prompt for generating new documentation from code
- Prompt for validating documentation accuracy
- Prompt for summarizing project changes in changelogs
