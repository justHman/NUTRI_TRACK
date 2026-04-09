---
name: generate-api
description: Include context to generate a new FastAPI endpoint following clean architecture, Pydantic validation, and project standards.
argument-hint: "What should this endpoint do? (e.g., path, method, payload, expected behavior)"
---

# FastAPI Endpoint Generation

Generate a new FastAPI endpoint for the NutriTrack backend based on my request. 

Please follow these strict steps and guidelines:

1. **Plan Before Coding**: Briefly summarize the path, HTTP method, required inputs, output models, and what underlying business logic/services will be involved.
2. **Schema Definition**: If new request/response models are needed, define them using Pydantic (e.g., in `utils/schemas.py`). Use appropriate field constraints and descriptions.
3. **Endpoint Implementation**: Write the router endpoint (typically in `templates/api.py`). Ensure it uses `async/await` appropriately.
4. **Clean Architecture**: Do not put complex business logic directly in the router! Delegate complex workflows to functions/classes in `scripts/` or `utils/`.
5. **Standards**: 
   - Apply robust exception handling (`HTTPException`).
   - Use strict Python type hints for all parameters and return types.
   - Include comprehensive docstrings.
   - For any external calls, use proper asynchronous behavior or integration limits.
   
*Reference: Always adhere to the general engineering rules defined in [coding-standards.instructions.md](../instructions/coding-standards.instructions.md).*
