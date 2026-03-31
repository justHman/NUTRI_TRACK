---
name: update-imports
description: Quickly update import statements across the workspace after a symbol or file rename. Accepts the old and new symbol/file name and updates all relevant imports.
argument-hint: "Specify the old and new symbol or file name (e.g., old: utils.cache_utils, new: utils.cache_manager)"
---

# Update Imports After Rename

When a symbol (function, class, variable) or file is renamed, update all import statements across the workspace to reflect the change.

**Workflow:**
1. **Input:** Receive the old and new symbol or file name.
2. **Analysis:**
   - Search the entire workspace for all import statements referencing the old name.
   - Use code-review-graph for semantic and transitive import discovery if available.
3. **Update:**
   - Replace all occurrences of the old import with the new one, ensuring correct syntax and style for each language (Python, JS, etc.).
   - If the symbol is re-exported or used in `__init__.py` or index files, update those as well.
4. **Validation:**
   - Suggest or run tests for affected files to ensure nothing is broken after the update.

*Reference: Use in conjunction with [cross-file-refactor.instructions.md](../instructions/cross-file-refactor.instructions.md) for full consistency.*
