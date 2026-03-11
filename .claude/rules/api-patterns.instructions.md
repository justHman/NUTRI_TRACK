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
- Always read upload bytes with `await file.read()` then pass as `image_bytes=` to the pipeline — never write to disk unless a temp file is strictly needed.
- Wrap upload handling in try/finally to clean up temp files:
  ```python
  tmp = tempfile.NamedTemporaryFile(delete=False, suffix="…")
  try:
      …
  finally:
      os.unlink(tmp.name)
  ```

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
