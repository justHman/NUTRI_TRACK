---
applyTo: "**/*.py"
---

# Python Conventions — NutriTrack

## Logging
- **Every `.py` file must declare a module-level logger** — no exceptions:
  ```python
  from config.logging_config import get_logger
  logger = get_logger(__name__)
  ```
  This includes scripts, pipelines, utility modules, clients, and test helpers.
  Never use `logging.getLogger()` directly.
- Use `logger.title("…")` for major section headers (pipeline stages, initialization).
- Use `logger.info()` for key milestones and happy-path results.
- Use `logger.debug()` for detailed internals (cache hits, intermediate values).
- Use `logger.warning()` for handled edge cases (empty input, fallback used, cache miss).
- Use `logger.error("…", exc_info=True)` before re-raising or returning an error dict.

## Type Hints
- All function signatures **must** have type hints on parameters and return values.
- Use `Optional[T]` from `typing` for nullable fields, not `T | None` (Python 3.9 compat).
- Prefer `Dict`, `List`, `Tuple` from `typing` for Python 3.9 compatibility.

## Pydantic v2
- Use Pydantic v2 API exclusively:
  - `MyModel.model_validate(data)` — not `MyModel.parse_obj(data)`
  - `instance.model_dump()` — not `instance.dict()`
  - `MyModel.model_validate_json(raw_str)` — not `MyModel.parse_raw(raw_str)`
- All data transfer objects (DTOs) and structured outputs must be Pydantic `BaseModel` subclasses.
- Use `Field(description="…")` on every field — the description is used in Bedrock toolConfig.

## Error Handling
- Never use bare `except:` — always catch a specific exception or `Exception` with a log:
  ```python
  except Exception as e:
      logger.warning("Descriptive message: %s", e)
  ```
- Raise `FileNotFoundError` for missing files, `ValueError` for bad input, `HTTPException` in API layer.

## File Paths
- Prefer `pathlib.Path` over `os.path` for new path operations.
- Use `os.path` only when extending existing patterns in the same file for consistency.

## Imports
- Project root is `app/`. All internal imports are relative to that root (e.g., `from config.logging_config import get_logger`).
- `load_dotenv(os.path.join(project_root, "config", ".env"))` at module level for any file that reads env vars.

## Dependencies
- Do not add new packages without updating `requirements.txt`.
- Check `requirements.txt` before adding an import to confirm the package is listed.
