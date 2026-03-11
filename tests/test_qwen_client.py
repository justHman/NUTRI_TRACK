"""
Tests for Qwen3VL Model Client
================================
Tests the 3 analysis methods of Qwen3VL against food images.
- Method 1: Converse API (manual JSON parsing) → analyze_food()
- Method 2: Instructor (expected to fail — not implemented)
- Method 3: Tool Calling (Converse + toolConfig) → analyze_food_with_tools()
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
COM_TAM_IMG = os.path.join(project_root, "data", "images", "dishes", "com_tam.jpg")
FAST_FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "fast_food.jpg")

# Bedrock pricing (approximate for Qwen3 VL on Bedrock — adjust as needed)
PRICE_PER_1K_INPUT = 0.0035
PRICE_PER_1K_OUTPUT = 0.014


def _make_result(method: str, image: str) -> dict:
    """Create a blank result dict."""
    return {
        "method": method,
        "image": image,
        "status": "error",
        "success": False,
        "time_s": 0,
        "dishes": 0,
        "ingredients": 0,
        "bedrock_calls": 0,
        "usda_calls": 0,
        "usda_cache_hits": 0,
        "tool_rounds": 0,
        "token_input": 0,
        "token_output": 0,
        "raw_output": None,
        "notes": "",
    }


def _test_method1_converse(qwen, image_path: str, image_name: str) -> dict:
    """Test Method 1: analyze_food() — Converse API with manual JSON parsing."""
    result = _make_result("method1", image_name)

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        logger.warning("Test skipped: %s", result["notes"])
        return result

    try:
        qwen.reset_usage()
        start = time.time()
        food_list = qwen.analyze_food(image_path=image_path)
        elapsed = time.time() - start

        result["time_s"] = round(elapsed, 2)
        result["token_input"] = qwen.input_tokens
        result["token_output"] = qwen.output_tokens
        result["bedrock_calls"] = 1
        result["raw_output"] = food_list.model_dump()

        dishes = food_list.dishes
        result["dishes"] = len(dishes)
        result["ingredients"] = sum(len(d.ingredients) for d in dishes)

        if len(dishes) > 0:
            result["status"] = "pass"
            result["success"] = True
            result["notes"] = f"Detected {len(dishes)} dish(es), {result['ingredients']} ingredient(s)"
        else:
            result["status"] = "fail"
            result["notes"] = "No dishes detected"

    except Exception as e:
        result["notes"] = str(e)
        logger.error("Method 1 failed for %s: %s", image_name, e, exc_info=True)

    return result


def _test_method2_instructor(qwen, image_path: str, image_name: str) -> dict:
    """Test Method 2: analyze_with_instructor() — Expected to fail (not implemented)."""
    result = _make_result("method2", image_name)

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        # Method 2 (instructor) is not implemented in current Qwen3VL
        if not hasattr(qwen, "analyze_with_instructor"):
            result["status"] = "skip"
            result["notes"] = "analyze_with_instructor() not implemented — expected"
            return result

        qwen.reset_usage()
        start = time.time()
        food_list = qwen.analyze_with_instructor(image_path=image_path)
        elapsed = time.time() - start

        result["time_s"] = round(elapsed, 2)
        result["token_input"] = qwen.input_tokens
        result["token_output"] = qwen.output_tokens
        result["bedrock_calls"] = 1
        result["raw_output"] = food_list.model_dump() if hasattr(food_list, "model_dump") else food_list

        dishes = food_list.dishes if hasattr(food_list, "dishes") else []
        result["dishes"] = len(dishes)
        result["ingredients"] = sum(len(d.ingredients) for d in dishes)
        result["status"] = "pass"
        result["success"] = True
        result["notes"] = f"Detected {len(dishes)} dish(es)"

    except Exception as e:
        result["status"] = "expected_fail"
        result["notes"] = f"Expected failure (instructor): {str(e)[:200]}"
        logger.info("Method 2 (instructor) expected failure for %s: %s", image_name, e)

    return result


def _test_method3_tools(qwen, image_path: str, image_name: str) -> dict:
    """Test Method 3: analyze_food_with_tools() — Converse API + Tool Calling."""
    result = _make_result("method3", image_name)

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        logger.warning("Test skipped: %s", result["notes"])
        return result

    try:
        from third_apis.USDA import USDAClient

        usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
        cache_before = usda_client.cache_stats()

        qwen.reset_usage()
        start = time.time()
        food_list = qwen.analyze_food_with_tools(
            image_path=image_path,
            usda_client=usda_client,
            max_tool_rounds=2
        )
        elapsed = time.time() - start

        cache_after = usda_client.cache_stats()

        result["time_s"] = round(elapsed, 2)
        result["token_input"] = qwen.input_tokens
        result["token_output"] = qwen.output_tokens
        result["raw_output"] = food_list.model_dump()

        # Estimate USDA calls from cache delta
        l1_delta = cache_after["l1_entries"] - cache_before["l1_entries"]
        result["usda_calls"] = max(l1_delta, 0)
        result["usda_cache_hits"] = max(0, cache_after["l1_entries"] - l1_delta)

        dishes = food_list.dishes
        result["dishes"] = len(dishes)
        result["ingredients"] = sum(len(d.ingredients) for d in dishes)

        if len(dishes) > 0:
            result["status"] = "pass"
            result["success"] = True
            result["notes"] = f"Detected {len(dishes)} dish(es), {result['ingredients']} ingredient(s)"
        else:
            result["status"] = "fail"
            result["notes"] = "No dishes detected"

    except Exception as e:
        result["notes"] = str(e)
        logger.error("Method 3 failed for %s: %s", image_name, e, exc_info=True)

    return result


def run_all(qwen) -> list:
    """Run all Qwen3VL model tests.

    Args:
        qwen: Pre-initialized Qwen3VL instance

    Returns:
        List of result dicts (6 tests: 3 methods × 2 images)
    """
    logger.info("Running Qwen3VL model tests...")
    results = []

    test_images = [
        (COM_TAM_IMG, "com_tam"),
        (FAST_FOOD_IMG, "fast_food"),
    ]

    for image_path, image_name in test_images:
        # Method 1: Converse API
        logger.info("Test: Method 1 (Converse) with %s", image_name)
        results.append(_test_method1_converse(qwen, image_path, image_name))

        # Method 2: Instructor (expected to fail)
        logger.info("Test: Method 2 (Instructor) with %s", image_name)
        results.append(_test_method2_instructor(qwen, image_path, image_name))

        # Method 3: Tool Calling
        logger.info("Test: Method 3 (Tool Calling) with %s", image_name)
        results.append(_test_method3_tools(qwen, image_path, image_name))

    passed = sum(1 for r in results if r.get("success", False))
    logger.info("Qwen3VL tests: %d/%d passed", passed, len(results))

    return results
