---
name: fix-bug
description: Diagnose and fix a runtime bug or failing test. Analyzes session logs, defines the root cause, and applies a robust fix.
argument-hint: "Paste the error stack trace, test failure, or describe the incorrect behavior..."
---

# Bug Fix Procedure

Please analyze the reported bug and provide a systematic fix following these steps:

1. **Information Gathering**:
   - Consult `logs/session.log` if this is a runtime or server error to gain full context.
   - Identify the specific files, classes, and methods implicated in the failure.

2. **Root Cause Analysis**:
   - Briefly explain *why* the bug is occurring before generating code. 
   - Check if this relates to known project issues (e.g., regex additive code corruption, AWS Bedrock 2MB image constraints, or LRUCache TTL edge cases).

3. **Proposed Fix**:
   - Outline the necessary changes.
   - For ingredient string manipulation, ensure standard regex bounds like `(?<![A-Za-z0-9])...(?![A-Za-z0-9])` are used.
   - Ensure the fix preserves clean architecture, Python type hints, and avoids tight coupling as per our `[Coding Standards](../instructions/coding-standards.instructions.md)`.

4. **Implementation & Testing**:
   - Provide the corrected code.
   - Suggest a quick strategy or generate a `pytest` snippet to prevent this specific bug from regressing in the future.

> **Note:** `logs/session.log` only persists for the current running session. If you restart or run a new session, it will be overwritten. To debug past sessions, check the other `.log` files in the `logs/` folder (e.g., `logs/nutritrack.log.4`). The higher the number in the filename (e.g., `.log.4`), the more recent the log file.
