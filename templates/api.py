"""
NutriTrack FastAPI Server
=========================
API endpoint for food image analysis and nutrition label OCR.

Usage (from app/ directory):
    python templates/api.py

Endpoints:
    GET  /          - Root health check
    GET  /health    - Health check
    GET  /jobs/{id} - Get background job status
    POST /analyze-food   - Upload food image → background analysis
    POST /analyze-label  - Upload label image → background OCR
    POST /scan-barcode   - Upload barcode image → background scan
"""

import os
import sys
import time
import socket
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
import anyio

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from jose import ExpiredSignatureError, JWTError, jwt
from fastapi.responses import FileResponse, JSONResponse

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

# In-memory dictionary to store async job status
job_store: dict[str, dict] = {}

def cleanup_old_jobs():
    """Keep memory footprint small by removing old jobs"""
    if len(job_store) > 1000:
        keys_to_delete = list(job_store.keys())[:200]
        for k in keys_to_delete:
            del job_store[k]

@asynccontextmanager
async def lifespan(app: FastAPI):
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = 100  # Nâng số lượng luồng chạy nền lên 100
    logger.info(f"Đã nâng giới hạn AnyIO Threadpool lên {limiter.total_tokens} luồng.")

    global analysist_client, ocrer_client, usda_client, avocavo_client, openfoodfacts_client
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
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi

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
    # Adding /jobs to exclusion or requiring auth. Here we assume /jobs requires auth unless we exclude it.
    # Exclude typical public endpoints, we will NOT exclude /jobs to protect data
    # Check if path starts with any of the protected prefixes
    protected_prefixes = ("/analyze-food", "/analyze-label", "/scan-barcode", "/jobs/", "/fly/logs/")
    is_protected = any(request.url.path.startswith(p) for p in protected_prefixes)
    
    if not is_protected:
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
                status_code=500, content={"detail": "Server hasn't configured the API secret key yet!"}
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

# ─── Async Workers ───────────────────────────────────────────────────────────

async def background_analyze_food_nutrition(job_id: str, method: str, image_bytes: bytes, filename: str):
    try:
        start = time.time()
        logger.info("Background Job %s (analyze-food) started for %s", job_id, filename)
        
        # Heavy sync function in threadpool
        results = await run_in_threadpool(
            analyze_food_nutrition, 
            analysist=analysist_client, 
            client=usda_client, 
            method=method, 
            image_bytes=image_bytes, 
            filename=filename
        )
        elapsed = time.time() - start
        
        num_dishes = len(results.get("dishes", []))
        
        bedrock_usage = {
            "token_input": analysist_client.token_input,
            "price_input": round(analysist_client.price_input, 8),
            "token_output": analysist_client.token_output,
            "price_output": round(analysist_client.price_output, 8),
            "total_tokens": analysist_client.token_input + analysist_client.token_output,
            "total_price": round(analysist_client.price_input + analysist_client.price_output, 8),
            "bedrock_calls": analysist_client.bedrock_calls,
        }
        
        payload = {
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
        
        job_store[job_id]["status"] = "completed"
        job_store[job_id]["result"] = payload
        logger.info("Background Job %s completed in %.1fs", job_id, elapsed)
    except Exception as e:
        logger.error("Background Job %s failed: %s", job_id, str(e), exc_info=True)
        job_store[job_id]["status"] = "failed"
        job_store[job_id]["error"] = f"Analysis failed: {str(e)}"

async def background_analyze_label(job_id: str, image_bytes: bytes, filename: str):
    try:
        start = time.time()
        logger.info("Background Job %s (analyze-label) started", job_id)
        results = await run_in_threadpool(
            analyze_label,
            ocrer=ocrer_client, image_bytes=image_bytes, filename=filename
        )
        elapsed = time.time() - start

        dishes = results.get("labels", [])
        num_dishes = len(dishes)
        has_label = num_dishes > 0

        if has_label:
            message = f"Detected {num_dishes} product(s) with nutrition label."
        else:
            message = "No nutrition label detected in the image."

        bedrock_usage = {
            "token_input": ocrer_client.token_input,
            "price_input": round(ocrer_client.price_input, 8),
            "token_output": ocrer_client.token_output,
            "price_output": round(ocrer_client.price_output, 8),
            "total_tokens": ocrer_client.token_input + ocrer_client.token_output,
            "total_price": round(ocrer_client.price_input + ocrer_client.price_output, 8),
            "bedrock_calls": ocrer_client.bedrock_calls,
        }

        payload = {
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
        job_store[job_id]["status"] = "completed"
        job_store[job_id]["result"] = payload
    except Exception as e:
        logger.error("Background Job %s failed: %s", job_id, str(e), exc_info=True)
        job_store[job_id]["status"] = "failed"
        job_store[job_id]["error"] = f"Label analysis failed: {str(e)}"

async def background_scan_barcode(job_id: str, image_bytes: bytes, filename: str):
    try:
        start = time.time()
        logger.info("Background Job %s (scan-barcode) started", job_id)
        clients = {
            "avocavo": avocavo_client,
            "openfoodfacts": openfoodfacts_client,
            "usda": usda_client,
        }
        result = await run_in_threadpool(barcode_pipeline, image_bytes, clients=clients)
        elapsed = time.time() - start

        found = result.get("found", False)
        food = result.get("food", {})
        barcode = food.get("barcode", "") if food else ""

        if found:
            message = f"Barcode {barcode} found (source={result.get('source')})."
        elif barcode:
            message = f"Barcode {barcode} decoded but not found in any cache."
        else:
            message = "No barcode detected in image."

        payload = {
            "success": True,
            "method": "POST",
            "endpoint": "/scan-barcode",
            "feature": "barcode_scan",
            "image": filename,
            "data": result,
            "message": message,
            "time_s": round(elapsed, 2),
        }
        job_store[job_id]["status"] = "completed"
        job_store[job_id]["result"] = payload
    except Exception as e:
        logger.error("Background Job %s failed: %s", job_id, str(e), exc_info=True)
        job_store[job_id]["status"] = "failed"
        job_store[job_id]["error"] = f"Barcode scan failed: {str(e)}"

# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    if os.path.isfile(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/")
async def root():
    hostname: str = socket.gethostname()
    return {
        "status": "ok",
        "server_info": {"hostname": hostname, "ip": get_ip(), "container": os.getenv("HOSTNAME", hostname)},
        "analysist_model": analysist_client.model_id if analysist_client else None,
        "ocrer_model": ocrer_client.model_id if ocrer_client else None,
        "usda_ready": usda_client is not None,
        "avocavo_ready": avocavo_client is not None,
        "openfoodfacts_ready": openfoodfacts_client is not None
    }

@app.get("/health")
async def health_check():
    hostname: str = socket.gethostname()
    return {
        "status": "ok",
        "server_info": {"hostname": hostname, "ip": get_ip(), "container": os.getenv("HOSTNAME", hostname)},
        "analysist_model": analysist_client.model_id if analysist_client else None,
        "ocrer_model": ocrer_client.model_id if ocrer_client else None,
        "usda_ready": usda_client is not None,
        "avocavo_ready": avocavo_client is not None,
        "openfoodfacts_ready": openfoodfacts_client is not None
    }

@app.get("/fly/logs/{app_name}")
def get_fly_logs(app_name: str):
    url: str = f"https://fly.io/apps/{app_name}/monitoring"
    return {"status": "success", "fly_monitoring_url": url, "message": "Check monitoring"}

@app.get("/jobs/{job_id}", summary="Check Job Status")
async def get_job_status(job_id: str):
    """
    Client calls this endpoint periodically to check if their async background job is complete.
    Returns: { "job_id": "...", "status": "processing" } OR the final JSON result.
    """
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    
    return job

@app.post("/analyze-food", status_code=202)
async def analyze_food_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    method: str = Query(
        default="manual",
        description="Analysis method: 'tools' (model-driven) or 'manual' (2-step)",
    ),
):
    if method not in ["tools", "manual"]:
        raise HTTPException(status_code=400, detail="Invalid method. Use 'tools' or 'manual'")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    image_bytes = await file.read()
    filename = file.filename or "upload.jpg"

    if analysist_client is None:
        raise HTTPException(status_code=503, detail="ANALYSIST model not initialized")

    job_id = str(uuid.uuid4())
    job_store[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "task_type": "analyze_food_nutrition",
        "created_at": datetime.utcnow().isoformat()
    }
    cleanup_old_jobs()

    # Pass the heavy async function to background threadpool safely
    background_tasks.add_task(background_analyze_food_nutrition, job_id, method, image_bytes, filename)

    return {
        "success": True,
        "message": "Job accepted and is processing in background.",
        "job_id": job_id,
        "status": "processing",
        "check_url": f"/jobs/{job_id}"
    }

@app.post("/analyze-label", status_code=202)
async def analyze_label_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    image_bytes = await file.read()
    filename = file.filename or "upload.jpg"

    if ocrer_client is None:
        raise HTTPException(status_code=503, detail="OCRER model not initialized")

    job_id = str(uuid.uuid4())
    job_store[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "task_type": "analyze_label",
        "created_at": datetime.utcnow().isoformat()
    }
    cleanup_old_jobs()

    background_tasks.add_task(background_analyze_label, job_id, image_bytes, filename)

    return {
        "success": True,
        "message": "Job accepted and is processing in background.",
        "job_id": job_id,
        "status": "processing",
        "check_url": f"/jobs/{job_id}"
    }

@app.post("/scan-barcode", status_code=202)
async def scan_barcode_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    image_bytes = await file.read()
    filename = file.filename or "upload.png"

    job_id = str(uuid.uuid4())
    job_store[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "task_type": "scan_barcode",
        "created_at": datetime.utcnow().isoformat()
    }
    cleanup_old_jobs()

    background_tasks.add_task(background_scan_barcode, job_id, image_bytes, filename)

    return {
        "success": True,
        "message": "Job accepted and is processing in background.",
        "job_id": job_id,
        "status": "processing",
        "check_url": f"/jobs/{job_id}"
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting uvicorn server...")
    uvicorn.run("templates.api:app", host="0.0.0.0", port=8000, reload=True)
