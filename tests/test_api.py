"""
NutriTrack API Test Suite
==========================
Tests the FastAPI /health and /analyze endpoints.

Usage:
    1. Start the server: python templates/api.py   (from app/ directory)
    2. Run tests:        python tests/test_api.py  (from app/ directory)
"""

import sys
import os
import time
import requests

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "http://localhost:8000"
COM_TAM_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\com_tam.jpg"
FAST_FOOD_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\fast_food.jpg"


def test_health_check() -> bool:
    """Test GET /health"""
    logger.title("API Test: GET /health")
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        if resp.status_code != 200:
            logger.error("❌ FAIL | /health returned status %d", resp.status_code)
            return False
        
        data = resp.json()
        if data.get("status") != "ok":
            logger.error("❌ FAIL | /health status != 'ok': %s", data)
            return False
        
        logger.info("✅ PASS | /health: %s", data)
        return True
    except requests.exceptions.ConnectionError:
        logger.error("❌ FAIL | Cannot connect to %s — is the server running?", BASE_URL)
        return False
    except Exception as e:
        logger.error("❌ FAIL | /health: %s", str(e))
        return False


def test_analyze_tools(image_path: str, label: str, expected_min: int = 1) -> bool:
    """Test POST /analyze?method=tools"""
    logger.title(f"API Test: POST /analyze?method=tools [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return True

    try:
        with open(image_path, "rb") as f:
            start = time.time()
            resp = requests.post(
                f"{BASE_URL}/analyze?method=tools",
                files={"file": (os.path.basename(image_path), f, "image/jpeg")},
                timeout=300,  # Tool calling can be slow
            )
            duration = time.time() - start
        
        if resp.status_code != 200:
            logger.error("❌ FAIL | /analyze (tools) [%s]: status %d — %s", label, resp.status_code, resp.text[:500])
            return False
        
        data = resp.json()
        if not data.get("success"):
            logger.error("❌ FAIL | /analyze (tools) [%s]: success=false — %s", label, data)
            return False
        
        results = data.get("data", [])
        if len(results) < expected_min:
            logger.error("❌ FAIL | /analyze (tools) [%s]: expected >= %d dishes, got %d", label, expected_min, len(results))
            return False
        
        logger.info("✅ PASS | /analyze (tools) [%s]: %d dish(es) in %.1fs", label, len(results), duration)
        return True
    
    except Exception as e:
        logger.error("❌ FAIL | /analyze (tools) [%s]: %s", label, str(e), exc_info=True)
        return False


def test_analyze_manual(image_path: str, label: str, expected_min: int = 1) -> bool:
    """Test POST /analyze?method=manual"""
    logger.title(f"API Test: POST /analyze?method=manual [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return True

    try:
        with open(image_path, "rb") as f:
            start = time.time()
            resp = requests.post(
                f"{BASE_URL}/analyze?method=manual",
                files={"file": (os.path.basename(image_path), f, "image/jpeg")},
                timeout=300,
            )
            duration = time.time() - start
        
        if resp.status_code != 200:
            logger.error("❌ FAIL | /analyze (manual) [%s]: status %d — %s", label, resp.status_code, resp.text[:500])
            return False
        
        data = resp.json()
        if not data.get("success"):
            logger.error("❌ FAIL | /analyze (manual) [%s]: success=false — %s", label, data)
            return False
        
        results = data.get("data", [])
        if len(results) < expected_min:
            logger.error("❌ FAIL | /analyze (manual) [%s]: expected >= %d dishes, got %d", label, expected_min, len(results))
            return False
        
        logger.info("✅ PASS | /analyze (manual) [%s]: %d dish(es) in %.1fs", label, len(results), duration)
        return True
    
    except Exception as e:
        logger.error("❌ FAIL | /analyze (manual) [%s]: %s", label, str(e), exc_info=True)
        return False


def test_analyze_invalid_file() -> bool:
    """Test POST /analyze with non-image file → should 400"""
    logger.title("API Test: POST /analyze with invalid file")
    try:
        resp = requests.post(
            f"{BASE_URL}/analyze",
            files={"file": ("test.txt", b"hello world", "text/plain")},
            timeout=10,
        )
        if resp.status_code == 400:
            logger.info("✅ PASS | Invalid file correctly rejected (400)")
            return True
        else:
            logger.error("❌ FAIL | Expected 400, got %d", resp.status_code)
            return False
    except Exception as e:
        logger.error("❌ FAIL | %s", str(e))
        return False


def main():
    logger.title("NutriTrack API Test Suite")
    logger.info("Target: %s", BASE_URL)
    logger.info("Make sure the API server is running before running these tests.")
    
    all_passed = True
    
    all_passed &= test_health_check()
    all_passed &= test_analyze_invalid_file()
    all_passed &= test_analyze_tools(COM_TAM_IMG, label="com_tam", expected_min=1)
    all_passed &= test_analyze_manual(COM_TAM_IMG, label="com_tam", expected_min=1)
    
    try:
        if all_passed:
            logger.info("🎉 ALL API TESTS PASSED")
            sys.exit(0)
        else:
            logger.warning("⚠️ SOME API TESTS FAILED")
            sys.exit(1)
    except SystemExit as e:
        logger.info("Exit code: %d", e.code)


if __name__ == "__main__":
    main()
