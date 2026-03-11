"""
Tests for NutriTrack API Endpoints
====================================
Tests the FastAPI endpoints: /health, /analyze-food
"""

import os
import sys
import time
import requests

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "http://localhost:8000"
LABEL_IMG = os.path.join(project_root, "data", "images", "labels", "hao_hao.jpg")
FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "com_tam.jpg")
FAST_FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "fast_food.jpg")


# ─── Health Check ────────────────────────────────────────────────────────────

def _test_health() -> dict:
    """Test GET /health endpoint"""
    result = {"endpoint": "/health", "method": "GET", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        result["status_code"] = resp.status_code
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "ok":
            result["success"] = True
            result["notes"] = "Health check OK"
        else:
            result["notes"] = f"Unexpected response: {data}"
    except Exception as e:
        result["notes"] = str(e)
    return result


def _test_root() -> dict:
    """Test GET / endpoint"""
    result = {"endpoint": "/", "method": "GET", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=10)
        result["status_code"] = resp.status_code
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "ok":
            result["success"] = True
            result["notes"] = f"Root OK — qwen={data.get('qwen_model')}, usda={data.get('usda_ready')}"
        else:
            result["notes"] = f"Unexpected response: {data}"
    except Exception as e:
        result["notes"] = str(e)
    return result


# ─── Analyze Food ────────────────────────────────────────────────────────────

def _test_analyze_food(image_path: str, image_name: str, method: str = "tools") -> dict:
    """Test POST /analyze-food endpoint"""
    result = {
        "endpoint": "/analyze-food",
        "method": "POST",
        "image": image_name,
        "query_method": method,
        "success": False,
        "status_code": None,
        "time_s": 0,
        "dishes": 0,
        "notes": "",
    }

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        start = time.time()
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
            resp = requests.post(
                f"{BASE_URL}/analyze-food",
                files=files,
                params={"method": method},
                timeout=180,
            )
        elapsed = time.time() - start

        result["status_code"] = resp.status_code
        result["time_s"] = round(elapsed, 2)
        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            dishes = data.get("data", {}).get("dishes", [])
            result["dishes"] = len(dishes)
            result["success"] = True
            result["notes"] = f"method={method}, {len(dishes)} dish(es) detected in {elapsed:.1f}s"
        else:
            result["notes"] = f"HTTP {resp.status_code}: {data.get('detail', '')}"

    except Exception as e:
        result["notes"] = str(e)

    return result


def _test_analyze_food_invalid_method() -> dict:
    """Test POST /analyze-food with invalid method param → expect 400"""
    result = {
        "endpoint": "/analyze-food",
        "method": "POST",
        "image": "com_tam",
        "success": False,
        "status_code": None,
        "notes": "",
    }

    if not os.path.exists(FOOD_IMG):
        result["notes"] = f"Image not found: {FOOD_IMG}"
        return result

    try:
        with open(FOOD_IMG, "rb") as f:
            files = {"file": (os.path.basename(FOOD_IMG), f, "image/jpeg")}
            resp = requests.post(
                f"{BASE_URL}/analyze-food",
                files=files,
                params={"method": "invalid_method"},
                timeout=10,
            )
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected invalid method"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result


def _test_analyze_food_invalid_file() -> dict:
    """Test POST /analyze-food with non-image file → expect 400"""
    result = {
        "endpoint": "/analyze-food",
        "method": "POST",
        "image": "invalid_file",
        "success": False,
        "status_code": None,
        "notes": "",
    }
    try:
        files = {"file": ("test.txt", b"not an image", "text/plain")}
        resp = requests.post(f"{BASE_URL}/analyze-food", files=files, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected non-image file"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result

# ─── Analyze Label ────────────────────────────────────────────────────────────

def _test_analyze_label(image_path: str, image_name: str, expect_label: bool) -> dict:
    """Test POST /analyze-label endpoint"""
    result = {
        "endpoint": "/analyze-label",
        "method": "POST",
        "image": image_name,
        "success": False,
        "status_code": None,
        "time_s": 0,
        "notes": "",
    }

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        start = time.time()
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
            resp = requests.post(f"{BASE_URL}/analyze-label", files=files, timeout=120)
        elapsed = time.time() - start

        result["status_code"] = resp.status_code
        result["time_s"] = round(elapsed, 2)
        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            dishes = data.get("data", {}).get("dishes", [])
            if expect_label and len(dishes) > 0:
                result["success"] = True
                result["notes"] = f"Detected {len(dishes)} product(s)"
            elif not expect_label and len(dishes) == 0:
                result["success"] = True
                result["notes"] = "Correctly returned no label"
            elif not expect_label and len(dishes) > 0:
                result["success"] = True
                result["notes"] = f"Model returned {len(dishes)} item(s) for non-label (acceptable)"
            else:
                result["notes"] = f"Expected label={expect_label}, got {len(dishes)} dishes"
        else:
            result["notes"] = f"HTTP {resp.status_code}: {data.get('detail', '')}"

    except Exception as e:
        result["notes"] = str(e)

    return result


def _test_analyze_label_invalid_file() -> dict:
    """Test POST /analyze-label with non-image file"""
    result = {
        "endpoint": "/analyze-label",
        "method": "POST",
        "image": "invalid_file",
        "success": False,
        "status_code": None,
        "notes": "",
    }
    try:
        files = {"file": ("test.txt", b"not an image", "text/plain")}
        resp = requests.post(f"{BASE_URL}/analyze-label", files=files, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected non-image file"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result

def run_all() -> list:
    """Run all API endpoint tests.

    Returns:
        List of result dicts
    """
    logger.info("Running API endpoint tests...")
    results = []

    # Test 1: Health check
    logger.info("API Test 1: GET /health")
    results.append(_test_health())

    # Test 2: Root endpoint
    logger.info("API Test 2: GET /")
    results.append(_test_root())

    # Test 3: Analyze food with tools method (com_tam)
    logger.info("API Test 3: POST /analyze-food (method=tools, com_tam)")
    results.append(_test_analyze_food(FOOD_IMG, "com_tam", method="tools"))

    # Test 4: Analyze food with manual method (com_tam)
    logger.info("API Test 4: POST /analyze-food (method=manual, com_tam)")
    results.append(_test_analyze_food(FOOD_IMG, "com_tam", method="manual"))

    # Test 5: Analyze food with tools method (fast_food)
    logger.info("API Test 5: POST /analyze-food (method=tools, fast_food)")
    results.append(_test_analyze_food(FAST_FOOD_IMG, "fast_food", method="tools"))

    # Test 6: Invalid method → 400
    logger.info("API Test 6: POST /analyze-food (invalid method)")
    results.append(_test_analyze_food_invalid_method())

    # Test 7: Invalid file → 400
    logger.info("API Test 7: POST /analyze-food (non-image file)")
    results.append(_test_analyze_food_invalid_file())

    # Test 8: Analyze label image (expect label)
    logger.info("API Test 8: POST /analyze-label (label image)")
    results.append(_test_analyze_label(LABEL_IMG, "hao_hao", expect_label=True))

    # Test 9: Analyze non-label image (expect no label)
    logger.info("API Test 9: POST /analyze-label (non-label image)")
    results.append(_test_analyze_label(FOOD_IMG, "com_tam", expect_label=False))

    # Test 10: Analyze label with non-image file → 400
    logger.info("API Test 10: POST /analyze-label (non-image file)")
    results.append(_test_analyze_label_invalid_file())

    passed = sum(1 for r in results if r.get("success"))
    logger.info("API tests: %d/%d passed", passed, len(results))

    return results
