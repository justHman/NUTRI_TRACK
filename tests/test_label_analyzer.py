"""
Tests for Label Analyzer
=========================
Tests the label analysis pipeline with label and non-label images.
"""

import os
import sys
import time
import logging as _stdlib_logging

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)


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
LABEL_IMG = os.path.join(project_root, "data", "images", "labels", "unknow.png")
HUMAN_IMG = os.path.join(project_root, "data", "images", "non_task", "human.jpg")
FAST_FOOD_IMG = os.path.join(project_root, "..", "data", "images", "food", "fast_food.jpg")
STEAK_IMG = os.path.join(project_root, "..", "data", "images", "food", "steak.png")

# Bedrock pricing (approximate — adjust as needed)
PRICE_PER_1K_INPUT = 0.00053
PRICE_PER_1K_OUTPUT = 0.00266


def test_label_image(qwen, image_path: str, image_name: str, expect_label: bool) -> dict:
    """Run a single label analysis test"""
    result = {
        "method": "label_ocr",
        "image": image_name,
        "status": "error",
        "success": False,
        "time_s": 0,
        "dishes": 0,
        "ingredients": 0,
        "bedrock_calls": 0,
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
        from scripts.label_analyzer import analyze_label

        qwen.reset_usage()

        start = time.time()
        data = analyze_label(image_path=image_path, qwen=qwen)
        elapsed = time.time() - start

        result["time_s"] = round(elapsed, 2)
        result["raw_output"] = data

        # Token usage & pricing
        result["bedrock_calls"] = qwen.bedrock_calls
        result["token_input"] = qwen.input_tokens
        result["token_output"] = qwen.output_tokens
        result["price_input"] = round(qwen.input_tokens / 1000 * PRICE_PER_1K_INPUT, 4)
        result["price_output"] = round(qwen.output_tokens / 1000 * PRICE_PER_1K_OUTPUT, 4)

        # Label analyzer now returns LabelList schema: {"labels": [ ... ]}
        labels = data.get("labels", []) if isinstance(data, dict) else []

        # Backward-compatibility for older format: {"product": ..., "ingredients": ..., "allergens": ...}
        note = ""
        nutrition = []
        if labels:
            first_label = labels[0]
            product = {
                "name": first_label.get("name", ""),
                "brand": first_label.get("brand", ""),
            }
            ingredients = first_label.get("ingredients", [])
            allergens = first_label.get("allergens", [])
            nutrition = first_label.get("nutrition", [])
            note = str(first_label.get("note", "") or "")
        else:
            product = data.get("product") if isinstance(data, dict) else None
            ingredients = data.get("ingredients", []) if isinstance(data, dict) else []
            allergens = data.get("allergens", []) if isinstance(data, dict) else []

        # Heuristic: inferred/no-official-label outputs should count as non-label detections.
        note_lc = note.lower()
        inferred_non_label = any(k in note_lc for k in [
            "no label detected",
            "no official",
            "inferred",
            "visual meal",
            "meal composition",
        ])

        has_label_evidence = bool(product) and (len(nutrition) > 0 or len(ingredients) > 0 or len(allergens) > 0) and not inferred_non_label

        result["dishes"] = 1 if has_label_evidence else 0
        result["ingredients"] = len(ingredients)

        if expect_label:
            if has_label_evidence:
                result["status"] = "pass"
                result["success"] = True
                result["notes"] = f"Detected product: {product.get('name')}"
            else:
                result["status"] = "fail"
                result["notes"] = "Expected label detection but got no product"
        else:
            # For non-label images, no product is the expected result (strict)
            if not has_label_evidence:
                result["status"] = "pass"
                result["success"] = True
                result["notes"] = "Correctly returned no product for non-label image"
            else:
                result["status"] = "fail"
                result["success"] = False
                result["notes"] = f"Unexpectedly detected product: {product.get('name')}"

    except Exception as e:
        result["status"] = "error"
        result["notes"] = str(e)
        logger.error("Test failed for %s: %s", image_name, e, exc_info=True)

    return result


def run_all(qwen) -> dict:
    """Run all label analyzer tests.

    Args:
        qwen: Pre-initialized Qwen3VL instance

    Returns:
        List of result dicts
    """
    _saved = _silence_console()
    try:
        print("\n─── Label Analyzer Tests ─────────────────────────────────────────────────")
        all_results = []
        group_cases = []

        TEST_CASES = [
            (LABEL_IMG,     "hao_hao", True),
            (HUMAN_IMG,     "human", False),
            (FAST_FOOD_IMG, "fast_food", False),
            (STEAK_IMG,     "steak", False),
        ]

        def _print_group(tag, cases):
            print(f"\n  ─────[{tag}]─────", flush=True)
            for i, (ok, label, detail) in enumerate(cases, 1):
                icon = "✅" if ok else "❌"
                print(f"    {i}. {label}: {detail} ({icon})", flush=True)
            passed = sum(ok for ok, _, _ in cases)
            total = len(cases)
            s_icon = "✅" if passed == total else "❌"
            print(f"    {passed}/{total} passed {s_icon}", flush=True)

        for img_path, img_name, expect_label in TEST_CASES:
            r = test_label_image(qwen, img_path, img_name, expect_label)
            all_results.append(r)
            detail = r.get("notes", "")
            if r.get("time_s"):
                detail += f"  [{r['time_s']}s]"
            group_cases.append((r["success"], img_name, detail))

        _print_group("LABEL OCR TESTS", group_cases)

        passed = sum(1 for r in all_results if r.get("success"))
        icon = "✅" if passed == len(all_results) else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{len(all_results)} passed {icon}\n", flush=True)
        return all_results
    finally:
        _restore_console(_saved)

if __name__ == "__main__":
    from models.QWEN3VL import Qwen3VL
    qwen = Qwen3VL()
    run_all(qwen)
