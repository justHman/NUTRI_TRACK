"""
NutriTrack Qwen3VL Test Suite
==============================
Tests all 3 analysis methods:
  Method 1: analyze_food() — Converse API (manual JSON)
  Method 2: analyze_food_with_instructor() — Instructor (auto Pydantic)
  Method 3: analyze_food_with_tools() — Tool Calling (USDA function calling)

Test images:
  - fast_food.jpg → expected ~12 dishes
  - com_tam.jpg   → expected 1 dish
"""

import sys
import os
import time
import json
import re
from datetime import datetime

# Thêm root vào sys.path để import được app
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger
from models.QWEN3VL import Qwen3VL, FoodList

logger = get_logger(__name__)

# ─── Test Images ─────────────────────────────────────────────────────────────

FAST_FOOD_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\fast_food.jpg"
COM_TAM_IMG   = r"D:\Project\Code\nutritrack-documentation\data\images\food\com_tam.jpg"
STEAK_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\steak.png"

# ─── Helpers ─────────────────────────────────────────────────────────────────

SESSION_LOG = os.path.join(project_root, "logs", "session.log")

def get_timestamp_str() -> str:
    """Get current timestamp string for log filtering"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def count_log_pattern(pattern: str, since_time: str) -> int:
    """Count occurrences of a regex pattern in session.log after since_time"""
    count = 0
    try:
        with open(SESSION_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                if ts_match and ts_match.group(1) < since_time:
                    continue
                if re.search(pattern, line):
                    count += 1
    except FileNotFoundError:
        pass
    return count

def validate_food_list(result: FoodList, min_items: int, label: str) -> bool:
    """Validate FoodList result meets basic requirements"""
    if not isinstance(result, FoodList):
        logger.error("❌ FAIL | %s: result is not FoodList, got %s", label, type(result))
        return False
    
    if len(result.dishes) < min_items:
        logger.error("❌ FAIL | %s: expected >= %d items, got %d", label, min_items, len(result.dishes))
        return False
    
    for i, item in enumerate(result.dishes, 1):
        if not item.name:
            logger.error("❌ FAIL | %s: item %d has no name", label, i)
            return False
        if not item.ingredients:
            logger.warning("⚠️ WARN | %s: item %d '%s' has no ingredients", label, i, item.name)
    
    logger.info("✅ PASS | %s: %d items detected", label, len(result.dishes))
    return True


def print_food_list(result: FoodList, label: str):
    """Pretty print a FoodList for debugging"""
    logger.info("─── %s ───", label)
    for i, item in enumerate(result.dishes, 1):
        logger.info("  [%d] %s (%s) — Cal: %s, Ingredients: %d",
                     i, item.name, item.vi_name or "N/A",
                     item.total_estimated_nutritions.calories if item.total_estimated_nutritions else "N/A", len(item.ingredients))
        for ing in item.ingredients[:5]:  # Show max 5 per dish
            logger.debug("      • %s — %.1fg (conf: %.2f)",
                         ing.name,
                         ing.estimated_weight_g or 0,
                         ing.confidence or 0)


# ─── Method 1: Converse API ─────────────────────────────────────────────────

def test_analyze_food(qwen: Qwen3VL, image_path: str, expected_min: int, label: str) -> dict:
    """Test analyze_food() — Method 1 (Converse API)"""
    logger.title(f"Method 1: analyze_food [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return True  # Don't fail if image missing

    try:
        with open(image_path, "rb") as f:
            img_bytes = f.read()

        start = time.time()
        result = qwen.analyze_food(image_bytes=img_bytes, filename=os.path.basename(image_path))
        duration = time.time() - start
        
        logger.info("Method 1 completed in %.1fs", duration)
        print_food_list(result, f"Method 1 [{label}]")
        passed = validate_food_list(result, expected_min, f"Method1-{label}")
        return {
            "success": passed,
            "status": "✅ PASS" if passed else "❌ FAIL",
            "time_s": round(duration, 1),
            "dishes": len(result.dishes),
            "ingredients": sum(len(i.ingredients) for i in result.dishes),
            "bedrock_calls": 1,
            "usda_calls": 0,
            "usda_cache_hits": 0,
            "tool_rounds": 0,
            "raw_output": result.model_dump()
        }
    
    except Exception as e:
        logger.error("❌ FAIL | Method 1 [%s]: %s", label, str(e), exc_info=True)
        return {"success": False, "status": "❌ ERROR", "time_s": 0, "raw_output": None}


# ─── Method 2: Instructor ───────────────────────────────────────────────────

def test_analyze_food_with_instructor(qwen: Qwen3VL, image_path: str, expected_min: int, label: str) -> dict:
    """Test analyze_food_with_instructor() — Method 2 (Instructor)"""
    logger.title(f"Method 2: analyze_food_with_instructor [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return True

    try:
        with open(image_path, "rb") as f:
            img_bytes = f.read()

        start = time.time()
        result = qwen.analyze_food_with_instructor(image_bytes=img_bytes, filename=os.path.basename(image_path))
        duration = time.time() - start
        
        logger.info("Method 2 completed in %.1fs", duration)
        print_food_list(result, f"Method 2 [{label}]")
        passed = validate_food_list(result, expected_min, f"Method2-{label}")
        
        return {
            "success": passed,
            "status": "✅ PASS" if passed else "⚠️ KNOWN",
            "time_s": round(duration, 1),
            "dishes": len(result.dishes),
            "ingredients": sum(len(i.ingredients) for i in result.dishes),
            "bedrock_calls": 1,
            "usda_calls": 0,
            "usda_cache_hits": 0,
            "tool_rounds": 0,
            "notes": "BEDROCK_JSON limit / Empty results" if not passed else "",
            "raw_output": result.model_dump()
        }
    
    except Exception as e:
        logger.error("❌ FAIL | Method 2 [%s]: %s", label, str(e), exc_info=True)
        return {"success": False, "status": "❌ ERROR", "time_s": 0, "raw_output": None}


# ─── Method 3: Tool Calling ─────────────────────────────────────────────────

def test_analyze_food_with_tools(qwen: Qwen3VL, image_path: str, expected_min: int, label: str) -> dict:
    """Test analyze_food_with_tools() — Method 3 (Tool Calling + USDA)"""
    logger.title(f"Method 3: analyze_food_with_tools [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return True

    try:
        from third_apis.USDA import USDAClient
        usda_api_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
        usda_client = USDAClient(api_key=usda_api_key)
        
        # 🧹 Clear L1 RAM cache for a fair cold-start measurement
        USDAClient.clear_l1_cache()
        
        with open(image_path, "rb") as f:
            img_bytes = f.read()

        ts_before = get_timestamp_str()
        start = time.time()
        result = qwen.analyze_food_with_tools(image_bytes=img_bytes, filename=os.path.basename(image_path), usda_client=usda_client)
        duration = time.time() - start
        
        logger.info("Method 3 completed in %.1fs", duration)
        print_food_list(result, f"Method 3 [{label}]")
        
        # Extra check: log raw JSON for debugging
        result_json = result.model_dump_json(indent=2)
        logger.debug("Method 3 raw output:\n%s", result_json[:2000])
        
        passed = validate_food_list(result, expected_min, f"Method3-{label}")
        
        # Exact calls from log
        bedrock_calls = count_log_pattern(r'\[ToolCalling\] Round \d+', ts_before)
        if bedrock_calls == 0 and result.dishes: bedrock_calls = 1 # Fallback
        usda_calls = count_log_pattern(r'USDA API search: query=', ts_before)
        usda_cache_hits = count_log_pattern(r'search_best: Cache HIT', ts_before)

        return {
            "success": passed,
            "status": "✅ PASS" if passed else "❌ FAIL",
            "time_s": round(duration, 1),
            "dishes": len(result.dishes),
            "ingredients": sum(len(i.ingredients) for i in result.dishes),
            "bedrock_calls": bedrock_calls,
            "usda_calls": usda_calls,
            "usda_cache_hits": usda_cache_hits,
            "tool_rounds": bedrock_calls,
            "notes": f"L2 disk hits: {usda_cache_hits}" if usda_cache_hits > 0 else "",
            "raw_output": result.model_dump()
        }
    
    except Exception as e:
        logger.error("❌ FAIL | Method 3 [%s]: %s", label, str(e), exc_info=True)
        return {"success": False, "status": "❌ ERROR", "time_s": 0, "raw_output": None}


# ─── Main ────────────────────────────────────────────────────────────────────


# ─── Automated Execution ────────────────────────────────────────────────────

DEFAULT_TEST_CONFIGS = [
    {"image": STEAK_IMG, "expected_min": 1, "label": "steak"},
    {"image": FAST_FOOD_IMG, "expected_min": 10, "label": "fast_food"},
]

def run_all(qwen: Qwen3VL, configs: list = None, run_instructor: bool = False) -> list[dict]:
    """Run all Qwen analysis methods on specified configs and return result list."""
    if configs is None:
        configs = DEFAULT_TEST_CONFIGS
    
    results = []
    
    for cfg in configs:
        img = cfg["image"]
        exp = cfg["expected_min"]
        lbl = cfg["label"]
        
        # Method 1
        res1 = test_analyze_food(qwen, img, exp, lbl)
        res1["method"] = "Converse"
        res1["image"] = lbl
        results.append(res1)
        
        # Method 2
        if run_instructor:
            res2 = test_analyze_food_with_instructor(qwen, img, exp, lbl)
            res2["method"] = "Instructor"
            res2["image"] = lbl
            results.append(res2)
            
        # Method 3
        res3 = test_analyze_food_with_tools(qwen, img, exp, lbl)
        res3["method"] = "Tools"
        res3["image"] = lbl
        results.append(res3)
        
    return results


def main():
    logger.title("NutriTrack Qwen3VL Complete Test Suite")
    
    qwen = Qwen3VL()
    results = run_all(qwen, run_instructor=False)
    all_passed = all(r["success"] for r in results)

    try:
        if all_passed:
            logger.info("🎉 ALL QWEN3VL TESTS PASSED")
            sys.exit(0)
        else:
            logger.warning("⚠️ SOME QWEN3VL TESTS FAILED")
            sys.exit(1)
    except SystemExit as e:
        logger.info("Exit code: %d", e.code)


if __name__ == "__main__":
    main()
