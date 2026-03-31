---
description: "Use when refactoring, editing, or modifying any code file. Ensures all related files (including those importing from the target file) are discovered and updated for consistency. Leverage MCP code-review-graph for impact analysis."
applyTo: "**/*.py"
---
# Cross-File Refactor Consistency

Whenever you refactor, edit, or modify any code file:

1. **Impact Analysis**:
   - Use tools like MCP code-review-graph to discover all related files.
   - Identify files that import any symbol from the file being changed, as well as files that are transitively affected (e.g., re-exports, subclassing, or usage).

2. **Synchronized Refactoring**:
   - For every related file, update imports, function calls, class usage, and documentation to match the changes in the original file.
   - Ensure that all code remains consistent, type-safe, and functional after the change.

3. **Testing**:
   - Suggest or run tests for all affected files to verify correctness after the refactor.

*Reference: This instruction enforces workspace-wide consistency and prevents broken imports or mismatched interfaces after code changes. Always use automated graph/code analysis tools to avoid missing dependencies.*
