---
name: refactor-clean
description: Refactor code for modularity, readability, and SOLID/clean architecture. Accepts a file, function, or class and returns a cleaner, more maintainable version.
argument-hint: "Paste code or specify file/function/class to refactor..."
---

# Refactor for Clean Architecture

Refactor the provided code to maximize modularity, readability, and maintainability. Follow these steps:

1. **Analysis**:
   - Briefly explain the current structure and any design/code smells (e.g., tight coupling, lack of type hints, missing docstrings, large functions, or unclear responsibilities).

2. **Refactoring Plan**:
   - Outline the main changes you will make (e.g., extract functions, introduce interfaces, split classes, add type hints, improve docstrings, decouple logic, etc.).

3. **Implementation**:
   - Provide the refactored code, ensuring:
     - SOLID principles are followed (Single Responsibility, Open-Closed, etc.)
     - Clean separation of concerns
     - Comprehensive type hints and docstrings
     - Readability and maintainability are prioritized over cleverness

4. **Testing**:
   - Suggest a quick test or validation strategy to ensure the refactor did not break functionality.

*Reference: Adhere to [coding-standards.instructions.md](../instructions/coding-standards.instructions.md) for all code style and architecture rules.*
