"""
NutriTrack Label Analyzer Script
=================================
Analyze nutrition labels on product packaging using Qwen3VL OCR.

Pipeline: Image → Qwen3VL (analyze_label) → FoodList JSON

Usage:
    python -m app.scripts.label_analyzer <image_path>
"""

import os
import sys
import time
import json
from dotenv import load_dotenv

# project_root = app/ directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger
from models.QWEN3VL import Qwen3VL, FoodList

logger = get_logger(__name__)


def analyze_label(image_path: str = None, qwen: Qwen3VL = None,
                  image_bytes: bytes = None, filename: str = None) -> dict:
    """
    Analyze a nutrition label image and return structured FoodList data.

    Returns:
        dict with FoodList schema. Empty dishes list if no label detected.
    """
    logger.title("Label Analysis Pipeline")
    logger.info("Image: %s", image_path or filename)

    pipeline_start = time.time()

    if qwen is None:
        logger.info("Initializing Qwen3VL client...")
        qwen = Qwen3VL()
    else:
        logger.debug("Using pre-initialized Qwen3VL client")

    step_start = time.time()
    food_list: FoodList = qwen.analyze_label(
        image_path=image_path,
        image_bytes=image_bytes,
        filename=filename
    )
    logger.info("Label analysis complete: %d product(s) in %.1fs",
                len(food_list.dishes), time.time() - step_start)

    total_time = time.time() - pipeline_start

    if not food_list.dishes:
        logger.warning("No nutrition label detected in image")
    else:
        logger.info("Pipeline complete in %.1fs", total_time)

    return food_list.model_dump()


def print_label_report(results: dict):
    """Pretty-print the label analysis report to console"""
    dishes = results.get("dishes", [])
    image_quality = results.get("image_quality", "N/A")

    print(f"\n{'='*95}")
    print(f"🏷️  BÁO CÁO PHÂN TÍCH NHÃN DINH DƯỠNG")
    print(f"{'='*95}\n")

    if not dishes:
        print("⚠️  Không phát hiện nhãn dinh dưỡng trong ảnh.")
        print(f"   Chất lượng ảnh: {image_quality}")
        return

    for product in dishes:
        name = product.get("name", "Unknown")
        vi_name = product.get("vi_name", "")
        confidence = product.get("confidence", 0)

        print(f"📦 SẢN PHẨM: {name} ({vi_name}) | Confidence: {confidence:.0%}")

        total_nut = product.get("total_estimated_nutritions") or {}
        total_weight = product.get("total_estimated_weight_g", 0)
        print(f"   Khối lượng: {total_weight}g")
        print(f"   Calories: {total_nut.get('calories', 0):.1f} kcal")
        print(f"   Protein:  {total_nut.get('protein', 0):.1f} g")
        print(f"   Carbs:    {total_nut.get('carbs', 0):.1f} g")
        print(f"   Fat:      {total_nut.get('fat', 0):.1f} g")

        ingredients = product.get("ingredients", [])
        if ingredients:
            print(f"\n   Thành phần ({len(ingredients)} nguyên liệu):")
            for ing in ingredients:
                ing_name = ing.get("name", "")
                vi = ing.get("vi_name", "")
                note = ing.get("note", "")
                display = f"{ing_name} ({vi})" if vi else ing_name
                if note:
                    display += f" — {note}"
                print(f"     • {display}")

        print("\n" + "=" * 95 + "\n")

    logger.info("Label report generation complete")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("No image path provided")
        print("Usage: python -m app.scripts.label_analyzer <image_path>")
        sys.exit(1)

    img = sys.argv[1]
    if not os.path.isabs(img):
        img = os.path.join(project_root, img)

    logger.info("CLI invocation: image_path=%s", img)
    results = analyze_label(img)
    print_label_report(results)

    # Save JSON output
    output_path = os.path.join(project_root, "data", "output", "label_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("JSON results saved to: %s", output_path)
