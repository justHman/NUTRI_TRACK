# Refactoring skill for codebases
# 10-word summary: Token-efficient, readable, minimal, non-redundant, well-structured code refactoring

## Purpose
This skill guides professional refactoring engineers and developers to:
- Aggressively reduce codebase token count and context window usage
- Eliminate redundant variables, files, and code
- Enforce meaningful, concise naming for files, variables, and functions
- Inline single-use, short functions (<20 lines)
- Extract short, multi-use logic into functions
- Remove all comments except for a 2-line file header (10 words each)
- Organize code: imports, enums, structs/classes, logic (in that order)
- Avoid file bloat: prefer directory trees, keep files <1000 lines
- Delete unused variables, functions, and files
- Never create excessive files in a single directory

## Workflow
1. Review the codebase for redundant code, variables, and files.
2. Refactor logic to inline or extract functions as per usage count and length.
3. Rename files, variables, and functions for clarity and brevity.
4. Remove all comments except the required 2-line file header.
5. Reorganize code sections: imports, enums, structs/classes, logic.
6. Delete unused code and files.
7. Restructure directories to avoid clutter and improve glanceability.
8. Validate that code remains readable and functional.

## Decision Points
- Inline or extract functions based on length and usage count.
- Delete or merge files based on usage and size.
- Restructure directories if file count grows too large.

## Completion Criteria
- No redundant code, variables, or files remain.
- All files have only a 2-line header comment.
- Code is concise, readable, and well-structured.
- Directory and file structure is clean and logical.

## Example Prompts
- "Refactor this module to minimize token count and redundancy."
- "Remove all unused variables and files in the project."
- "Restructure directories for better organization and glanceability."

## Related Customizations
- Skill for enforcing naming conventions
- Skill for automated unused code detection
- Skill for directory structure optimization
