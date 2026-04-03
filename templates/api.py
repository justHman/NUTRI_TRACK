"""
NutriTrack FastAPI Server
=========================
API endpoint for food image analysis and nutrition label OCR.

Usage (from app/ directory):
    python templates/api.py

Endpoints:
    GET  /          - Root health check
    GET  /health    - Health check
    POST /analyze-food   - Upload food image → nutrition analysis JSON
    POST /analyze-label  - Upload label image → nutrition label OCR JSON
    POST /scan-barcode   - Upload barcode image → scan & lookup in L1/L2/L3
"""

import os
import socket
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import NutriLogger, get_logger
from models.ANALYSIST import ANALYSIST
from models.OCRER import OCRER
from scripts.food_analyzer import analyze_food_nutrition
from scripts.label_analyzer import analyze_label
from scripts.scan_barcode import barcode_pipeline
from third_apis.AvocavoNutrition import AvocavoNutritionClient
from third_apis.OpenFoodFacts import OpenFoodFactsClient
from third_apis.USDA import USDAClient
from utils.getter import get_ip

load_dotenv(os.path.join(project_root, "config", ".env"))
logger: NutriLogger = get_logger(__name__)

FAVICON_PATH: str = os.path.join(os.path.dirname(__file__), "favicon.ico")

# ─── App Lifespan ────────────────────────────────────────────────────────────

analysist_client: Optional[ANALYSIST] = None
ocrer_client: Optional[OCRER] = None
usda_client: Optional[USDAClient] = None
avocavo_client: Optional[AvocavoNutritionClient] = None
openfoodfacts_client: Optional[OpenFoodFactsClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize models on startup, cleanup on shutdown"""
    global \
        analysist_client, \
        ocrer_client, \
        usda_client, \
        avocavo_client, \
        openfoodfacts_client
    logger.title("Starting NutriTrack API Server")

    logger.info(
        f"Loading analysist {os.getenv('ANALYSIST_MODEL_ID', 'qwen.qwen3-vl-235b-a22b')} model..."
    )
    analysist_client = ANALYSIST(
        region=os.getenv("AWS_REGION", "ap-southeast-2"),
        model_id=os.getenv("ANALYSIST_MODEL_ID", "qwen.qwen3-vl-235b-a22b"),
    )

    logger.info(
        f"Loading ocrer {os.getenv('OCRER_MODEL_ID', 'qwen.qwen3-vl-235b-a22b')} model..."
    )
    ocrer_client = OCRER(
        region=os.getenv("AWS_REGION", "ap-southeast-2"),
        model_id=os.getenv("OCRER_MODEL_ID", "qwen.qwen3-vl-235b-a22b"),
    )

    logger.info("Initializing USDA client...")
    usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY", "DEMO_KEY"))

    logger.info("Initializing Avocavo Nutrition client...")
    avocavo_client = AvocavoNutritionClient(
        api_key=os.getenv("AVOCAVO_NUTRITION_API_KEY", "DEMO_KEY")
    )

    logger.info("Initializing OpenFoodFacts client...")
    openfoodfacts_client = OpenFoodFactsClient()

    logger.info("All models loaded. NutriTrack API is ready!")
    ip = get_ip()
    logger.info(f"API running on http://{ip}:8000")
    yield
    logger.info("Shutting down NutriTrack API server...")


# ─── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="NutriTrack API",
    description="Upload a food image → nutrition analysis (Qwen3 VL + USDA), or a label image → nutrition label OCR",
    version="2.0.0",
    lifespan=lifespan,
)


# ─── Swagger UI Security Scheme ───────────────────────────────────────────────
# Thêm nút "Authorize 🔒" vào Swagger UI để có thể test các endpoint từ /docs
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema: dict[str, any] = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Nhập JWT token (không cần prefix 'Bearer '). Token phải có claim: service=backend",
        }
    }
    # Áp dụng security cho tất cả endpoint (trừ các public path đã excluded trong middleware)
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

# Dùng để inject vào Swagger UI — không thực sự validate ở đây (middleware đảm nhiệm)
bear_scheme = HTTPBearer(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY: str = os.getenv("NUTRITRACK_API_KEY", "")
ALGORITHM = "HS256"


@app.middleware("http")
async def auth_middleware(request: Request, call_next) -> JSONResponse:
    excluded_paths: list[str] = [
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/favicon.ico",
        "/openapi.json",
        "/fly",
        "/docs/oauth2-redirect",
    ]
    if request.url.path in excluded_paths or request.url.path.startswith("/fly/logs/"):
        return await call_next(request)

    auth_header: str = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid Authorization header"},
        )

    token: str = auth_header.split(" ")[1]
    try:
        if not SECRET_KEY:
            return JSONResponse(
                status_code=500,
                content={"detail": "Server hasn't configured the API secret key yet!"},
            )

        payload: dict[str, any] = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload["service"].lower().strip() != "backend":
            return JSONResponse(
                status_code=403, content={"detail": "Forbidden: invalid service claim"}
            )
        request.state.user = payload
    except ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"detail": "Token has expired"})
    except JWTError:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})

    return await call_next(request)


# ─── Endpoints ───────────────────────────────────────────────────────────────


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    if os.path.isfile(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    from fastapi.responses import Response

    return Response(status_code=204)


@app.get("/")
async def root():
    logger.debug("Health check requested")
    hostname: str = socket.gethostname()
    ip_addr: str = get_ip()

    result = {
        "status": "ok",
        "server_info": {
            "hostname": hostname,
            "ip": ip_addr,
            "container": os.getenv("HOSTNAME", hostname),
        },
        "analysist_model": analysist_client.model_id if analysist_client else None,
        "ocrer_model": ocrer_client.model_id if ocrer_client else None,
        "usda_ready": usda_client is not None,
        "avocavo_ready": avocavo_client is not None,
        "openfoodfacts_ready": openfoodfacts_client is not None,
    }
    return result


@app.get("/health")
async def health_check():
    logger.debug("Health check requested")
    hostname: str = socket.gethostname()
    ip_addr: str = get_ip()

    result = {
        "status": "ok",
        "server_info": {
            "hostname": hostname,
            "ip": ip_addr,
            "container": os.getenv("HOSTNAME", hostname),
        },
        "analysist_model": analysist_client.model_id if analysist_client else None,
        "ocrer_model": ocrer_client.model_id if ocrer_client else None,
        "usda_ready": usda_client is not None,
        "avocavo_ready": avocavo_client is not None,
        "openfoodfacts_ready": openfoodfacts_client is not None,
    }
    return result


@app.get("/fly/logs/{app_name}")
def get_fly_logs(app_name: str):
    url: str = f"https://fly.io/apps/{app_name}/monitoring"
    if os.getenv("FLY_APP_NAME"):
        # Thay vì RedirectResponse, trả về JSON để Frontend tự window.open()
        return {
            "status": "success",
            "fly_monitoring_url": url,
            "message": "You are running on Fly.io.",
        }

    return {
        "status": "Local",
        "fly_monitoring_url": url,
        "message": f"You are running on Localhost. Please check your terminal/console for logs. Maybe it is running on Fly.io, check {url}",
    }


@app.post("/analyze-food")
async def analyze_food_image(
    file: UploadFile = File(...),
    method: str = Query(
        default="tools",
        description="Analysis method: 'tools' (model-driven) or 'manual' (2-step)",
    ),
):
    """Upload a food image → full nutrition analysis JSON.

    Query params:
        method: 'tools' (default) — model calls USDA tools directly
                'manual' — traditional Qwen → USDA per ingredient
    """
    logger.info(
        "Received /analyze-food request: filename=%s, content_type=%s, method=%s",
        file.filename,
        file.content_type,
        method,
    )

    if method not in ("tools", "manual"):
        raise HTTPException(
            status_code=400, detail="method must be 'tools' or 'manual'"
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        logger.warning("Rejected upload: invalid content type '%s'", file.content_type)
        raise HTTPException(status_code=400, detail="File must be an image")

    image_bytes = await file.read()
    filename = file.filename or "upload.jpg"
    logger.debug(
        "Read uploaded file into memory: %s (%.2f MB)",
        filename,
        len(image_bytes) / 1024 / 1024,
    )

    if analysist_client is None:
        raise HTTPException(status_code=503, detail="ANALYSIST model not initialized")

    try:
        start = time.time()
        logger.info("Starting analysis pipeline (method=%s)...", method)
        results = analyze_food_nutrition(
            analysist=analysist_client,
            client=usda_client,
            method=method,
            image_bytes=image_bytes,
            filename=filename,
        )
        elapsed = time.time() - start

        num_dishes = len(results.get("dishes", []))
        logger.info(
            "Analysis complete: %d dish(es) detected in %.1fs", num_dishes, elapsed
        )

        bedrock_usage: dict[str, int | float] = {
            "token_input": analysist_client.token_input,
            "price_input": round(analysist_client.price_input, 8),
            "token_output": analysist_client.token_output,
            "price_output": round(analysist_client.price_output, 8),
            "total_tokens": analysist_client.token_input
            + analysist_client.token_output,
            "total_price": round(
                analysist_client.price_input + analysist_client.price_output, 8
            ),
            "bedrock_calls": analysist_client.bedrock_calls,
        }

        result = {
            "success": True,
            "method": "POST",
            "endpoint": "/analyze-food",
            "feature": "food_analysis",
            "query_params": {"method": method},
            "image": filename,
            "data": results,
            "message": f"Detected {num_dishes} dish(es).",
            "bedrock_usage": bedrock_usage,
            "time_s": round(elapsed, 2),
        }
        return result

    except Exception as e:
        logger.error(
            "Analysis failed for file '%s': %s", file.filename, str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/analyze-label")
async def analyze_label_image(
    file: UploadFile = File(...),
):
    """Upload a product image → nutrition label OCR → structured JSON.

    If no nutrition label is detected in the image, returns success=True
    with label_detected=False and an empty dishes array.
    """
    logger.info(
        "Received /analyze-label request: filename=%s, content_type=%s",
        file.filename,
        file.content_type,
    )

    if not file.content_type or not file.content_type.startswith("image/"):
        logger.warning("Rejected upload: invalid content type '%s'", file.content_type)
        raise HTTPException(status_code=400, detail="File must be an image")

    image_bytes = await file.read()
    filename = file.filename or "upload.jpg"
    logger.debug(
        "Read uploaded file into memory: %s (%.2f MB)",
        filename,
        len(image_bytes) / 1024 / 1024,
    )

    if ocrer_client is None:
        raise HTTPException(status_code=503, detail="OCRER model not initialized")

    try:
        start = time.time()
        logger.info("Starting label analysis pipeline...")
        results = analyze_label(
            ocrer=ocrer_client, image_bytes=image_bytes, filename=filename
        )
        elapsed = time.time() - start

        dishes = results.get("labels", [])
        num_dishes = len(dishes)
        has_label = num_dishes > 0

        if has_label:
            message = f"Detected {num_dishes} product(s) with nutrition label."
            logger.info(
                "Label analysis complete: %d product(s) detected in %.1fs",
                num_dishes,
                elapsed,
            )
        else:
            message = "No nutrition label detected in the image."
            logger.info("Label analysis complete: no label detected in %.1fs", elapsed)

        bedrock_usage: dict[str, int | float] = {
            "token_input": ocrer_client.token_input,
            "price_input": round(ocrer_client.price_input, 8),
            "token_output": ocrer_client.token_output,
            "price_output": round(ocrer_client.price_output, 8),
            "total_tokens": ocrer_client.token_input + ocrer_client.token_output,
            "total_price": round(
                ocrer_client.price_input + ocrer_client.price_output, 8
            ),
            "bedrock_calls": ocrer_client.bedrock_calls,
        }

        result = {
            "success": True,
            "method": "POST",
            "endpoint": "/analyze-label",
            "feature": "label_analysis",
            "image": filename,
            "data": results,
            "message": message,
            "bedrock_usage": bedrock_usage,
            "time_s": round(elapsed, 2),
            "label_detected": has_label,
        }
        return result

    except Exception as e:
        logger.error(
            "Label analysis failed for file '%s': %s",
            file.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Label analysis failed: {str(e)}")


@app.post("/scan-barcode")
async def scan_barcode_image(
    file: UploadFile = File(...),
):
    """Upload a barcode image → scan barcode → lookup product in caches → API search fallback.

    The client reads the image file and sends the raw bytes.
    The pipeline decodes the barcode using pyrxing, then searches
    L1 (RAM) → L2 (disk JSON) caches across OpenFoodFacts, Avocavo, and USDA.
    On full cache miss, falls back to API calls in order:
    Avocavo → OpenFoodFacts → USDA.
    """
    logger.info(
        "Received /scan-barcode request: filename=%s, content_type=%s",
        file.filename,
        file.content_type,
    )

    if not file.content_type or not file.content_type.startswith("image/"):
        logger.warning("Rejected upload: invalid content type '%s'", file.content_type)
        raise HTTPException(status_code=400, detail="File must be an image")

    image_bytes = await file.read()
    filename = file.filename or "upload.png"
    logger.debug(
        "Read uploaded file into memory: %s (%.2f KB)",
        filename,
        len(image_bytes) / 1024,
    )

    try:
        start = time.time()
        logger.info("Starting barcode pipeline...")
        clients = {
            "avocavo": avocavo_client,
            "openfoodfacts": openfoodfacts_client,
            "usda": usda_client,
        }
        result = barcode_pipeline(image_bytes, clients=clients)
        elapsed = time.time() - start

        found = result.get("found", False)
        food = result.get("food", {})
        barcode = food.get("barcode", "") if food else ""

        if found:
            message = f"Barcode {barcode} found (source={result.get('source')})."
            logger.info(
                "Barcode scan complete: %s found in %s (%.2fs)",
                barcode,
                result.get("source"),
                elapsed,
            )
        elif barcode:
            message = f"Barcode {barcode} decoded but not found in any cache."
            logger.info(
                "Barcode scan complete: %s not in cache (%.2fs)", barcode, elapsed
            )
        else:
            message = "No barcode detected in image."
            logger.info("Barcode scan complete: no barcode detected (%.2fs)", elapsed)

        result = {
            "success": True,
            "method": "POST",
            "endpoint": "/scan-barcode",
            "feature": "barcode_scan",
            "image": filename,
            "data": result,
            "message": message,
            "time_s": round(elapsed, 2),
        }

        return result

    except Exception as e:
        logger.error(
            "Barcode scan failed for file '%s': %s",
            file.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Barcode scan failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting uvicorn server...")
    uvicorn.run("templates.api:app", host="0.0.0.0", port=8000, reload=True)
