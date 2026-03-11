"""
Tests for NutriTrack Pipeline
===============================
Tests the high-level analyze_nutrition() pipeline with both methods:
- "tools": Model drives USDA lookups via tool calling
- "manual": Traditional 2-step flow — Qwen → USDA per ingredient
"""

import os
import sys
import time

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger

logger = get_logger(__name__)

# Test images
COM_TAM_IMG = os.path.join(project_root, "..", "data", "images", "food", "com_tam.jpg")
FAST_FOOD_IMG = os.path.join(project_root, "..", "data", "images", "food", "fast_food.jpg")
STEAK_IMG = os.path.join(project_root, "..", "data", "images", "food", "steak.png")

# Bedrock pricing (approximate — adjust as needed)
PRICE_PER_1K_INPUT = 0.0035
PRICE_PER_1K_OUTPUT = 0.014


def _test_pipeline(qwen, usda_client, image_path: str, image_name: str, method: str) -> dict:
    """Run a single pipeline test and record metrics."""
    result = {
        "method": f"{method}",
        "image": image_name,
        "status": "error",
        "success": False,
        "time_s": 0,
        "dishes": 0,
        "ingredients": 0,
        "bedrock_calls": 0,
        "usda_calls": 0,
        "usda_cache_hits": 0,
        "token_input": 0,
        "price_input": 0,
        "token_output": 0,
        "price_output": 0,
        "raw_output": None,
        "notes": "",
    }

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        logger.warning("Pipeline test skipped: %s", result["notes"])
        return result

    try:
        from scripts.pipeline import analyze_nutrition

        cache_before = usda_client.cache_stats()
        qwen.reset_usage()

        start = time.time()
        data = analyze_nutrition(
            image_path=image_path,
            qwen=qwen,
            usda_client=usda_client,
            method=method
        )
        elapsed = time.time() - start

        cache_after = usda_client.cache_stats()

        result["time_s"] = round(elapsed, 2)
        result["raw_output"] = data

        # Token usage & pricing
        result["token_input"] = qwen.input_tokens
        result["token_output"] = qwen.output_tokens
        result["price_input"] = round(qwen.input_tokens / 1000 * PRICE_PER_1K_INPUT, 4)
        result["price_output"] = round(qwen.output_tokens / 1000 * PRICE_PER_1K_OUTPUT, 4)

        # USDA call estimates from cache delta
        l1_delta = cache_after["l1_entries"] - cache_before["l1_entries"]
        result["usda_calls"] = max(l1_delta, 0)
        result["usda_cache_hits"] = max(0, cache_after["l1_entries"] - l1_delta)

        # Dish & ingredient counts
        dishes = data.get("dishes", [])
        result["dishes"] = len(dishes)
        result["ingredients"] = sum(len(d.get("ingredients", [])) for d in dishes)

        # Validate results
        if len(dishes) > 0:
            # Check that at least one dish has total_estimated_nutritions
            has_nutritions = any(d.get("total_estimated_nutritions") for d in dishes)
            if has_nutritions:
                result["status"] = "pass"
                result["success"] = True
                result["notes"] = f"{len(dishes)} dish(es), {result['ingredients']} ingredient(s)"
            else:
                result["status"] = "partial"
                result["success"] = True
                result["notes"] = f"{len(dishes)} dish(es) detected but no total nutritions calculated"
        else:
            result["status"] = "fail"
            result["notes"] = "No dishes detected"

    except Exception as e:
        result["notes"] = str(e)
        logger.error("Pipeline test failed (%s, %s): %s", method, image_name, e, exc_info=True)

    return result


def run_all(qwen, usda_client) -> list:
    """Run all pipeline tests.

    Args:
        qwen: Pre-initialized Qwen3VL instance
        usda_client: Pre-initialized USDAClient instance

    Returns:
        List of result dicts (4 tests: 2 methods × 2 images)
    """
    logger.info("Running pipeline tests...")
    results = []

    # Test 1: Tools method with com_tam
    logger.info("Pipeline Test 1: method=tools, image=com_tam")
    results.append(_test_pipeline(qwen, usda_client, COM_TAM_IMG, "com_tam", "tools"))

    # Test 2: Manual method with com_tam
    logger.info("Pipeline Test 2: method=manual, image=com_tam")
    results.append(_test_pipeline(qwen, usda_client, COM_TAM_IMG, "com_tam", "manual"))

    # Test 3: Tools method with fast_food
    logger.info("Pipeline Test 3: method=tools, image=fast_food")
    results.append(_test_pipeline(qwen, usda_client, FAST_FOOD_IMG, "fast_food", "tools"))

    # Test 4: Manual method with fast_food
    logger.info("Pipeline Test 4: method=manual, image=fast_food")
    results.append(_test_pipeline(qwen, usda_client, FAST_FOOD_IMG, "fast_food", "manual"))

    passed = sum(1 for r in results if r.get("success", False))
    logger.info("Pipeline tests: %d/%d passed", passed, len(results))

    return results
