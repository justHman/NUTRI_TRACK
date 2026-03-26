---
applyTo: "templates/*.py"
---

# API Patterns — NutriTrack FastAPI

## App Initialization
- Use `@asynccontextmanager` lifespan (not deprecated `on_event`) for startup/shutdown:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # startup: init Qwen3VL and USDAClient
      qwen_client = Qwen3VL()
      usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
      yield
      # shutdown: cleanup if needed
  
  app = FastAPI(lifespan=lifespan)
  ```
- Heavy clients (`Qwen3VL`, `USDAClient`) are initialized **once** at startup as module-level globals, then injected into endpoint handlers.

## Endpoint Patterns
- Accept file uploads via `UploadFile = File(...)`.
- Accept config parameters via `Query(default=…, description="…")`.
- **Image input contract — bytes only at the pipeline boundary:**
  - API endpoints read the upload with `await file.read()` and pass `image_bytes: bytes` to the pipeline.
  - Pipelines and scripts **never** accept a file path from the outside — only `bytes` or `bytearray`.
  - Reading the image file from disk is the **UI's responsibility** (`open(path, "rb").read()` in `ui.py`).
  - If a pipeline internally needs a file path (e.g., for a library that doesn't support bytes), write a private temp file and delete it in a `finally` block:
    ```python
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name
    try:
        result = some_lib(tmp_path)
    finally:
        os.unlink(tmp_path)
    ```
- Always read upload bytes with `await file.read()` then pass as `image_bytes=` to the pipeline — never pass `UploadFile` objects deeper than the endpoint handler.

## Response and Error Handling
- Return plain `dict` from endpoints (FastAPI serializes automatically).
- Raise `HTTPException(status_code=…, detail="…")` for all error cases — never return error dicts.
- Use `status_code=400` for bad input, `500` for unexpected server errors.
- Log the exception before raising `HTTPException(500)`:
  ```python
  except Exception as e:
      logger.error("Analyze failed: %s", e, exc_info=True)
      raise HTTPException(status_code=500, detail=str(e))
  ```

## CORS
- The app uses `allow_origins=["*"]` for development. For production, restrict to known origins.

## Health Check
- `GET /health` must return `qwen_model` (model ID string) and `usda_ready` (bool) at minimum.
- Never block health check with expensive operations — read pre-initialized state only.
