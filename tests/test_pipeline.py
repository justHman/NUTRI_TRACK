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
import logging as _stdlib_logging
import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger

logger = get_logger(__name__)


def _require_bedrock_env() -> None:
    required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        pytest.skip(f"Missing AWS credentials for Bedrock tests: {', '.join(missing)}")


# ── Console-silence helpers ──────────────────────────────────────────────────

def _silence_console():
    root = _stdlib_logging.getLogger()
    saved = []
    for h in root.handlers:
        if isinstance(h, _stdlib_logging.StreamHandler) and not isinstance(h, _stdlib_logging.FileHandler):
            saved.append((h, h.level))
            h.setLevel(_stdlib_logging.WARNING)
    return saved


def _restore_console(saved):
    for h, level in saved:
        h.setLevel(level)

# Test images
HUMAN_IMG = os.path.join(project_root, "data", "images", "non_task", "human.jpg")
LABEL_IMG = os.path.join(project_root, "data", "images", "labels", "unknow.png")
FAST_FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "fast_food.jpg")
STEAK_IMG = os.path.join(project_root, "data", "images", "dishes", "steak.png")

# Bedrock pricing (approximate — adjust as needed)
PRICE_PER_1K_INPUT = 0.00053
PRICE_PER_1K_OUTPUT = 0.00266


def _test_pipeline(qwen, client, image_path: str, image_name: str, method: str, expect_dishes: bool = True) -> dict:
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
        return result

    try:
        from scripts.pipeline import analyze_nutrition

        cache_before = client.cache_stats()
        qwen.reset_usage()

        start = time.time()
        data = analyze_nutrition(
            image_path=image_path,
            qwen=qwen,
            client=client,
            method=method
        )
        elapsed = time.time() - start

        cache_after = client.cache_stats()

        result["time_s"] = round(elapsed, 2)
        result["raw_output"] = data

        # Token usage & pricing
        result["bedrock_calls"] = qwen.bedrock_calls
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
            # Check that at least one dish has nutritions
            has_nutritions = any(d.get("nutritions") for d in dishes)
            if has_nutritions:
                if expect_dishes:
                    result["status"] = "pass"
                    result["success"] = True
                    result["notes"] = f"{len(dishes)} dish(es), {result['ingredients']} ingredient(s)"
                else:
                    result["status"] = "fail"
                    result["success"] = False
                    result["notes"] = f"Unexpectedly detected {len(dishes)} dish(es)"
            else:
                if expect_dishes:
                    result["status"] = "partial"
                    result["success"] = True
                    result["notes"] = f"{len(dishes)} dish(es) detected but no total nutritions calculated"
                else:
                    result["status"] = "fail"
                    result["success"] = False
                    result["notes"] = f"Unexpectedly detected {len(dishes)} dish(es)"
        else:
            if expect_dishes:
                result["status"] = "fail"
                result["success"] = False
                result["notes"] = "No dishes detected"
            else:
                result["status"] = "pass"
                result["success"] = True
                result["notes"] = f"Correctly returned no dishes for non-food image at {image_path}"

    except Exception as e:
        result["notes"] = str(e)
        logger.error("Pipeline test failed (%s, %s): %s", method, image_name, e, exc_info=True)

    return result


def run_all(qwen, client) -> list:
    """Run all pipeline tests.

    Args:
        qwen: Pre-initialized Qwen3VL instance
        client: Pre-initialized USDAClient instance

    Returns:
        List of result dicts (4 tests: 2 methods × 2 images)
    """
    _saved = _silence_console()
    try:
        print("\n─── Pipeline Tests ───────────────────────────────────────────────────────")
        all_results = []

        TEST_IMAGES = [
            # (COM_TAM_IMG,   "com_tam"),
            (FAST_FOOD_IMG, "fast_food", True),
            (STEAK_IMG,     "steak", True),
            (HUMAN_IMG,     "human", False),
            (LABEL_IMG,     "label", False),
        ]

        METHODS = [
            ("tools",  "TOOLS PIPELINE"),
            ("manual", "MANUAL PIPELINE"),
        ]

        def _to_case(r):
            detail = r.get("notes", "")
            if r.get("time_s"):
                detail += f"  [{r['time_s']}s]"
            return (r["success"], r["image"], detail)

        def _print_group(tag, cases):
            print(f"\n  ─────[{tag}]─────", flush=True)
            for i, (ok, label, detail) in enumerate(cases, 1):
                icon = "✅" if ok else "❌"
                print(f"    {i}. {label}: {detail} ({icon})", flush=True)
            passed = sum(ok for ok, _, _ in cases)
            total = len(cases)
            s_icon = "✅" if passed == total else "❌"
            print(f"    {passed}/{total} passed {s_icon}", flush=True)

        for method, group_tag in METHODS:
            group_cases = []
            for img_path, img_name, expect_dishes in TEST_IMAGES:
                r = _test_pipeline(qwen, client, img_path, img_name, method, expect_dishes=expect_dishes)
                all_results.append(r)
                group_cases.append(_to_case(r))
            _print_group(group_tag, group_cases)

        passed = sum(1 for r in all_results if r.get("success", False))
        icon = "✅" if passed == len(all_results) else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{len(all_results)} passed {icon}\n", flush=True)
        return all_results
    finally:
        _restore_console(_saved)


@pytest.mark.integration
def test_pipeline_suite():
    _require_bedrock_env()

    from models.QWEN3VL import Qwen3VL
    from third_apis.USDA import USDAClient

    qwen = Qwen3VL()
    client = USDAClient(api_key=os.getenv("USDA_API_KEY", "DEMO_KEY"))
    results = run_all(qwen, client)
    failed = [r for r in results if not r.get("success")]
    assert not failed, f"Pipeline suite failed: {failed}"

if __name__ == "__main__":
    from models.QWEN3VL import Qwen3VL
    from third_apis.USDA import USDAClient
    
    qwen = Qwen3VL()
    client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
    
    run_all(qwen, client)
