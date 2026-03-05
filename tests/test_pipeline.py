"""
NutriTrack Pipeline Test Suite
===============================
Tests the full pipeline with both methods:
  - "tools" mode: model-driven tool calling
  - "manual" mode: traditional 2-step flow

Test image: com_tam.jpg (1 dish — simpler, faster)
"""

import sys
import os
import time
import json

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger
from scripts.pipeline import analyze_nutrition
from models.QWEN3VL import Qwen3VL
from third_apis.USDA import USDAClient
from tests.test_qwen_client import get_timestamp_str, count_log_pattern

logger = get_logger(__name__)

COM_TAM_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\com_tam.jpg"
FAST_FOOD_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\fast_food.jpg"


def test_pipeline_tools(qwen: Qwen3VL, usda_client: USDAClient, image_path: str, expected_min: int, label: str) -> dict:
    """Test pipeline with method='tools' (tool-calling mode)"""
    logger.title(f"Pipeline Test: method='tools' [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return {"success": False, "status": "⚠️ SKIP", "time_s": 0, "raw_output": None}

    try:
        # 🧹 Clear L1 RAM cache for fair cold-start measurement
        USDAClient.clear_l1_cache()
        ts_before = get_timestamp_str()
        start = time.time()
        results = analyze_nutrition(image_path, qwen=qwen, usda_client=usda_client, method="tools")
        duration = time.time() - start
        
        passed = True
        if not results or len(results) < expected_min:
            logger.error("❌ FAIL | Pipeline (tools) [%s]: expected >= %d dish, got %d", label, expected_min, len(results) if results else 0)
            passed = False
        else:
            logger.info("✅ PASS | Pipeline (tools) [%s]: %d dish(es) in %.1fs", label, len(results), duration)
            logger.debug("Pipeline result: %s", json.dumps(results, ensure_ascii=False, indent=2)[:2000])
        
        ingredients_count = sum(len(dish.get("ingredients", [])) for dish in results) if results else 0
        bedrock_calls = count_log_pattern(r'\[ToolCalling\] Round \d+', ts_before)
        if bedrock_calls == 0 and results: bedrock_calls = 1
        usda_calls = count_log_pattern(r'USDA API search: query=', ts_before)
        usda_cache_hits = count_log_pattern(r'search_best: Cache HIT', ts_before)

        return {
            "success": passed,
            "status": "✅ PASS" if passed else "❌ FAIL",
            "time_s": round(duration, 1),
            "dishes": len(results) if results else 0,
            "ingredients": ingredients_count,
            "bedrock_calls": bedrock_calls,
            "usda_calls": usda_calls,
            "usda_cache_hits": usda_cache_hits,
            "tool_rounds": bedrock_calls,
            "notes": "",
            "raw_output": results
        }
        
    except Exception as e:
        logger.error("❌ FAIL | Pipeline (tools) [%s]: %s", label, str(e), exc_info=True)
        return {"success": False, "status": "❌ ERROR", "time_s": 0, "raw_output": None}


def test_pipeline_manual(qwen: Qwen3VL, usda_client: USDAClient, image_path: str, expected_min: int, label: str) -> dict:
    """Test pipeline with method='manual' (2-step mode)"""
    logger.title(f"Pipeline Test: method='manual' [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return {"success": False, "status": "⚠️ SKIP", "time_s": 0, "raw_output": None}

    try:
        # 🧹 Clear L1 RAM cache for fair cold-start measurement
        USDAClient.clear_l1_cache()
        ts_before = get_timestamp_str()
        start = time.time()
        results = analyze_nutrition(image_path, qwen=qwen, usda_client=usda_client, method="manual")
        duration = time.time() - start
        
        passed = True
        if not results or len(results) < expected_min:
            logger.error("❌ FAIL | Pipeline (manual) [%s]: expected >= %d dish, got %d", label, expected_min, len(results) if results else 0)
            passed = False
        else:
            # Manual mode should have total_nutrition and ingredients with usda_100g
            first_dish = results[0]
            if "total_nutrition" not in first_dish:
                logger.error("❌ FAIL | Pipeline (manual) [%s]: missing 'total_nutrition'", label)
                passed = False
            else:
                logger.info("✅ PASS | Pipeline (manual) [%s]: %d dish(es) in %.1fs", label, len(results), duration)
        
        ingredients_count = sum(len(dish.get("ingredients", [])) for dish in results) if results else 0
        bedrock_calls = 1 if results else 0  # Manual mode uses 1 single prompt + json parsing
        usda_calls = count_log_pattern(r'USDA API search: query=', ts_before)
        usda_cache_hits = count_log_pattern(r'search_best: Cache HIT', ts_before)

        return {
            "success": passed,
            "status": "✅ PASS" if passed else "❌ FAIL",
            "time_s": round(duration, 1),
            "dishes": len(results) if results else 0,
            "ingredients": ingredients_count,
            "bedrock_calls": bedrock_calls,
            "usda_calls": usda_calls,
            "usda_cache_hits": usda_cache_hits,
            "tool_rounds": 0, # Manual mode doesn't loop tools
            "notes": "",
            "raw_output": results
        }
        
    except Exception as e:
        logger.error("❌ FAIL | Pipeline (manual) [%s]: %s", label, str(e), exc_info=True)
        return {"success": False, "status": "❌ ERROR", "time_s": 0, "raw_output": None}


def main():
    logger.title("NutriTrack Pipeline Test Suite")
    
    qwen = Qwen3VL()
    usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
    
    all_passed = True
    all_passed &= test_pipeline_tools(qwen, usda_client, COM_TAM_IMG, expected_min=1, label="com_tam").get("success")
    all_passed &= test_pipeline_manual(qwen, usda_client, COM_TAM_IMG, expected_min=1, label="com_tam").get("success")
    
    try:
        if all_passed:
            logger.info("🎉 ALL PIPELINE TESTS PASSED")
            sys.exit(0)
        else:
            logger.warning("⚠️ SOME PIPELINE TESTS FAILED")
            sys.exit(1)
    except SystemExit as e:
        logger.info("Exit code: %d", e.code)


if __name__ == "__main__":
    main()
