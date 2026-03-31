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
import logging as _stdlib_logging
import pytest
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from config.logging_config import get_logger
from utils.test_helpers import silence_console, restore_console, require_api_integration_env

logger = get_logger(__name__)
load_dotenv(os.path.join(project_root, "config", ".env"))

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
        return result

    try:
        qwen.reset_usage()
        start = time.time()
        food_list = qwen.analyze_food(image_path=image_path)
        elapsed = time.time() - start

        result["time_s"] = round(elapsed, 2)
        result["token_input"] = qwen.token_input
        result["token_output"] = qwen.token_output
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


def _test_method3_tools(qwen, image_path: str, image_name: str) -> dict:
    """Test Method 3: analyze_food_with_tools() — Converse API + Tool Calling."""
    result = _make_result("method3", image_name)

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        from third_apis.USDA import USDAClient

        client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
        cache_before = client.cache_stats()

        qwen.reset_usage()
        start = time.time()
        food_list = qwen.analyze_food_with_tools(
            image_path=image_path,
            client=client,
            max_tool_rounds=2
        )
        elapsed = time.time() - start

        cache_after = client.cache_stats()

        result["time_s"] = round(elapsed, 2)
        result["token_input"] = qwen.token_input
        result["token_output"] = qwen.token_output
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
    _saved = silence_console()
    try:
        print("\n─── Qwen3VL Model Tests ───────────────────────────────────────────────")
        all_results = []

        TEST_IMAGES = [
            (COM_TAM_IMG,   "com_tam"),
            (FAST_FOOD_IMG, "fast_food"),
        ]

        METHOD_GROUPS = [
            ("method1", "CONVERSE METHOD",   _test_method1_converse),
            ("method3", "TOOLS METHOD",      _test_method3_tools),
        ]

        def _to_case(r):
            if r["status"] in ("skip", "expected_fail"):
                ok = None
            elif r["success"]:
                ok = True
            else:
                ok = False
            detail = r.get("notes", "")
            if r.get("time_s"):
                detail += f"  [{r['time_s']}s]"
            return (ok, r["image"], detail)

        def _print_group(tag, cases):
            print(f"\n  ─────[{tag}]─────", flush=True)
            for i, (ok, label, detail) in enumerate(cases, 1):
                icon = "⏭️ " if ok is None else ("✅" if ok else "❌")
                print(f"    {i}. {label}: {detail} ({icon})", flush=True)
            passed = sum(1 for ok, _, _ in cases if ok)
            total = len(cases)
            s_icon = "✅" if passed == total else "❌"
            note = "  (skips expected)" if any(ok is None for ok, _, _ in cases) else ""
            print(f"    {passed}/{total} passed {s_icon}{note}", flush=True)

        for _mkey, group_tag, test_fn in METHOD_GROUPS:
            group_cases = []
            for img_path, img_name in TEST_IMAGES:
                r = test_fn(qwen, img_path, img_name)
                all_results.append(r)
                group_cases.append(_to_case(r))
            _print_group(group_tag, group_cases)

        passed = sum(1 for r in all_results if r.get("success", False))
        icon = "✅" if passed == len(all_results) else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{len(all_results)} passed {icon}  (instructor skip is expected)\n", flush=True)
        return all_results
    finally:
        restore_console(_saved)


@pytest.mark.integration
def test_qwen_client_suite():
    require_api_integration_env()

    from models.QWEN3VL import Qwen3VL

    qwen = Qwen3VL()
    results = run_all(qwen)
    failed = [r for r in results if not r.get("success") and r.get("status") not in ("skip", "expected_fail")]
    assert not failed, f"Qwen client suite failed: {failed}"
