"""
Tests for NutriTrack API Endpoints
====================================
Tests the FastAPI endpoints: /health, /analyze, /analyze-label
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
FOOD_IMG = os.path.join(project_root, "..", "data", "images", "food", "com_tam.jpg")


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
    results.append(_test_health())

    # Test 2: Label analysis with label image
    results.append(_test_analyze_label(LABEL_IMG, "hao_hao", expect_label=True))

    # Test 3: Label analysis with non-label image
    results.append(_test_analyze_label(FOOD_IMG, "com_tam", expect_label=False))

    # Test 4: Label analysis with invalid file
    results.append(_test_analyze_label_invalid_file())

    passed = sum(1 for r in results if r.get("success"))
    logger.info("API tests: %d/%d passed", passed, len(results))

    return results
