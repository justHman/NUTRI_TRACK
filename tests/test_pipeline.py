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
STEAK_IMG = r"D:\Project\Code\nutritrack-documentation\data\images\food\steak.png"

# Bedrock pricing for Qwen3-VL-235B
INPUT_PRICE_PER_1K = 0.00053
OUTPUT_PRICE_PER_1K = 0.00266


def test_pipeline_tools(qwen: Qwen3VL, usda_client: USDAClient, image_path: str, expected_min: int, label: str) -> dict:
    """Test pipeline with method='tools' (tool-calling mode)"""
    logger.title(f"Pipeline Test: method='tools' [{label}]")
    
    if not os.path.exists(image_path):
        logger.error("❌ SKIP | Image not found: %s", image_path)
        return {"success": False, "status": "⚠️ SKIP", "time_s": 0, "raw_output": None}

    try:
        # 🧹 Clear L1 RAM cache for fair cold-start measurement
        USDAClient.clear_l1_cache()
        qwen.reset_usage()
        
        ts_before = get_timestamp_str()
        start = time.time()
        
        # Load image bytes to test in-memory processing
        with open(image_path, "rb") as f:
            img_bytes = f.read()
            
        results = analyze_nutrition(
            image_bytes=img_bytes,
            filename=os.path.basename(image_path),
            qwen=qwen,
            usda_client=usda_client,
            method="tools"
        )
        duration = time.time() - start
        
        passed = True
        items = results.get("dishes", []) if results else []
        if not items or len(items) < expected_min:
            logger.error("❌ FAIL | Pipeline (tools) [%s]: expected >= %d dish, got %d", label, expected_min, len(items))
            passed = False
        else:
            logger.info("✅ PASS | Pipeline (tools) [%s]: %d dish(es) in %.1fs", label, len(items), duration)
            logger.debug("Pipeline result: %s", json.dumps(results, ensure_ascii=False, indent=2)[:2000])
        
        ingredients_count = sum(len(dish.get("ingredients", [])) for dish in items)
        bedrock_calls = count_log_pattern(r'\[ToolCalling\] Round \d+', ts_before)
        if bedrock_calls == 0 and results: bedrock_calls = 1
        usda_calls = count_log_pattern(r'USDA API search: query=', ts_before)
        usda_cache_hits = count_log_pattern(r'search_best: Cache HIT', ts_before)

        token_input = qwen.input_tokens
        token_output = qwen.output_tokens
        price_input = (token_input / 1000) * INPUT_PRICE_PER_1K
        price_output = (token_output / 1000) * OUTPUT_PRICE_PER_1K

        return {
            "success": passed,
            "status": "✅ PASS" if passed else "❌ FAIL",
            "time_s": round(duration, 1),
            "dishes": len(items),
            "ingredients": ingredients_count,
            "bedrock_calls": bedrock_calls,
            "usda_calls": usda_calls,
            "usda_cache_hits": usda_cache_hits,
            "tool_rounds": bedrock_calls,
            "token_input": token_input,
            "price_input": round(price_input, 4),
            "token_output": token_output,
            "price_output": round(price_output, 4),
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
        qwen.reset_usage()
        
        ts_before = get_timestamp_str()
        start = time.time()
        
        # Load image bytes to test in-memory processing
        with open(image_path, "rb") as f:
            img_bytes = f.read()
            
        results = analyze_nutrition(
            image_bytes=img_bytes,
            filename=os.path.basename(image_path),
            qwen=qwen,
            usda_client=usda_client,
            method="manual"
        )
        duration = time.time() - start
        
        passed = True
        items = results.get("dishes", []) if results else []
        if not items or len(items) < expected_min:
            logger.error("❌ FAIL | Pipeline (manual) [%s]: expected >= %d dish, got %d", label, expected_min, len(items))
            passed = False
        else:
            # Manual mode should have total_estimated_nutritions and ingredients with estimated_nutritions
            first_dish = items[0]
            if "total_estimated_nutritions" not in first_dish:
                logger.error("❌ FAIL | Pipeline (manual) [%s]: missing 'total_estimated_nutritions'", label)
                passed = False
            else:
                logger.info("✅ PASS | Pipeline (manual) [%s]: %d dish(es) in %.1fs", label, len(items), duration)
        
        ingredients_count = sum(len(dish.get("ingredients", [])) for dish in items)
        bedrock_calls = 1 if results else 0  # Manual mode uses 1 single prompt + json parsing
        usda_calls = count_log_pattern(r'USDA API search: query=', ts_before)
        usda_cache_hits = count_log_pattern(r'search_best: Cache HIT', ts_before)

        token_input = qwen.input_tokens
        token_output = qwen.output_tokens
        price_input = (token_input / 1000) * INPUT_PRICE_PER_1K
        price_output = (token_output / 1000) * OUTPUT_PRICE_PER_1K

        return {
            "success": passed,
            "status": "✅ PASS" if passed else "❌ FAIL",
            "time_s": round(duration, 1),
            "dishes": len(items),
            "ingredients": ingredients_count,
            "bedrock_calls": bedrock_calls,
            "usda_calls": usda_calls,
            "usda_cache_hits": usda_cache_hits,
            "tool_rounds": 0, # Manual mode doesn't loop tools
            "token_input": token_input,
            "price_input": round(price_input, 4),
            "token_output": token_output,
            "price_output": round(price_output, 4),
            "notes": "",
            "raw_output": results
        }
        
    except Exception as e:
        logger.error("❌ FAIL | Pipeline (manual) [%s]: %s", label, str(e), exc_info=True)
        return {"success": False, "status": "❌ ERROR", "time_s": 0, "raw_output": None}



# ─── Automated Execution ────────────────────────────────────────────────────

DEFAULT_TEST_CONFIGS = [
    {"image": STEAK_IMG, "expected_min": 1, "label": "steak"},
    {"image": FAST_FOOD_IMG, "expected_min": 10, "label": "fast_food"},
]

def run_all(qwen: Qwen3VL, usda_client: USDAClient, configs: list = None) -> list[dict]:
    """Run all pipeline methods on specified configs and return result list."""
    if configs is None:
        configs = DEFAULT_TEST_CONFIGS
        
    results = []
    
    for cfg in configs:
        img = cfg["image"]
        exp = cfg["expected_min"]
        lbl = cfg["label"]
        
        # Method: tools
        res_tools = test_pipeline_tools(qwen, usda_client, img, exp, lbl)
        res_tools["method"] = "tools"
        res_tools["image"] = lbl
        results.append(res_tools)
        
        # Method: manual
        res_manual = test_pipeline_manual(qwen, usda_client, img, exp, lbl)
        res_manual["method"] = "manual"
        res_manual["image"] = lbl
        results.append(res_manual)
            
    return results


def main():
    logger.title("NutriTrack Pipeline Test Suite")
    
    qwen = Qwen3VL()
    api_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
    usda_client = USDAClient(api_key=api_key)
    
    results = run_all(qwen, usda_client)
    all_passed = all(r["success"] for r in results)
    
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
