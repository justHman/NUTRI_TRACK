# Project Guidelines

## Code Style
- **Python Frameworks**: Built using standard Python standards (3.10+). Use type hints. 
- **FastAPI Backend**: `templates/api.py` acts as the FastAPI REST server. Uses JWT auth, lifespan context managers, and CORS middleware.
- **Gradio Frontend**: `templates/ui.py` acts as the frontend visualization application connecting to the FastAPI backend.

## Architecture
This project processes food images/barcodes to retrieve and aggregate nutrition data automatically using Vision Language Models (VLMs) and external APIs.
- **`templates/`**: Core API and UI entry points.
- **`third_apis/`**: External data adapters (`USDAClient`, `AvocavoNutritionClient`, `OpenFoodFactsClient`) that enforce heavy caching to reduce repeated external lookups.
- **`models/`**: Central abstractions (e.g. `Qwen3VL` for vision-language analysis, `LRUCache`).
- **`scripts/`**: High-level execution pipelines mapping Image/Barcode → AI Evaluation/OCR → 3rd-party mapping API calls → Result extraction.
- **`utils/`**: Global reusable functionality like cache persistence (`cache_utils.py`), math `caculator.py`, and Bedrock image resizing/normalization (`processor.py`).
- **`infra/`**: Contains Terraform code used to rapidly deploy AWS services; highly modular and reusable for deploying elsewhere.

For deployments (AWS, ECS/Fargate + Spot (optional), CI/CD, and Fly.io), **do not invent architectures**—always link and refer to the specific guides inside the `docs/` folder (e.g., `docs/aws_secure_architecture_guide.md`, `docs/complete_deployment_guide.md`, etc.).

## Build and Test
- **Dependencies (`requirements.txt` & `requirements-dev.txt`)**: ALWAYS update `requirements-dev.txt` when installing new test/dev libraries. Keep `requirements.txt` strictly to production-necessary libraries out of the deployment image to minimize build times and save cloud resources.
- **Docker Building (`.dockerignore`)**: Always update when creating non-essential local files. Keeping ignored files up to date ensures the final image stays as light as possible.
- **Running Locally**: The backend server is triggered via `uvicorn templates.api:app --host 0.0.0.0 --port 8000`.
- **Debugging Session (`session.log`)**: ALWAYS read `logs/session.log` when encountering errors. This file captures the full session scope, sized perfectly to give context without over-wasting LLM tokens. Fix the error block continuously and test until resolving it.
- **Testing**: Run `pytest`. Unit and pipeline tests are located in `tests/`. Those calling live external APIs should use `@pytest.mark.integration`.

## Conventions
- **Regex Logic**: When doing ingredient cleanup via Regex, ALWAYS use negative lookbehinds/lookaheads like `(?<![A-Za-z0-9])...(?![A-Za-z0-9])` to avoid corrupting additive/European "E" numbers (like E500, e621).
- **Custom Logging**: Rely on the configured `config/logging_config.py`. It includes standard logger methods alongside a custom `logger.title(msg)` method that prints framed section headers for clearer pipeline visibility.
- **Image Processing**: Bedrock enforces a 2MB raw bytes limit per image (Base64 encoding increases size by ~33%). Images must be preprocessed/compressed via `processor.py` before inference.
- **Cache Rules**: Handled locally via config. Negative responses (404, 204) are explicitly cacheable.
- **Tools Menu (`nutrition_tool_config.json`)**: Update this JSON schema whenever modifying or adding tool calling menus provided to Qwen3VL via AWS Bedrock.
- **Prompt Engineering (`prompt_config.py`)**: Extremely important file configurations. Modifying prompts has immense impact on pipeline accuracy, structured output generation, speed and overall VLM token optimization.
