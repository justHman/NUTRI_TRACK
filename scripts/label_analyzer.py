"""
NutriTrack Label Analyzer Script
=================================
Analyze nutrition labels on product packaging using OCRER.

Pipeline: Image → OCRER (analyze_label) → LabelList JSON

Usage:
    python -m app.scripts.label_analyzer <image_path>
"""

import json
import os
import sys
import time

from dotenv import load_dotenv

# project_root = app/ directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, "config", ".env"))

from typing import Optional

from config.logging_config import get_logger
from models.OCRER import OCRER
from utils.schemas import LabelList

logger = get_logger(__name__)


def analyze_label(
    image_path: Optional[str] = None,
    ocrer: Optional[OCRER] = None,
    image_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
) -> dict:
    """
    Analyze a nutrition label image and return structured LabelList data.
    """
    logger.title("Label Analysis Pipeline")
    logger.info("Image: %s", image_path or filename)

    if ocrer is None:
        logger.info("Initializing OCRER client...")
        ocrer = OCRER()
    else:
        logger.debug("Using pre-initialized OCRER client")

    step_start = time.time()
    label_result: LabelList = ocrer.analyze_label(
        image_path=image_path, image_bytes=image_bytes, filename=filename
    )
    logger.info(
        "Label analysis complete %s product in %.1fs",
        len(label_result.labels),
        time.time() - step_start,
    )

    return label_result.model_dump()


def print_label_report(results: dict):
    """Pretty-print the label analysis report to console"""
    product = results.get("product")
    nutrition = results.get("nutrition", [])
    ingredients = results.get("ingredients", [])
    allergens = results.get("allergens", [])

    print(f"\n{'=' * 95}")
    print(f"🏷️  BÁO CÁO PHÂN TÍCH NHÃN DINH DƯỠNG")
    print(f"{'=' * 95}\n")

    if not product:
        print("⚠️  Không phát hiện thông tin sản phẩm.")
        return

    name = product.get("name", "Unknown")
    brand = product.get("brand", "")
    pid = product.get("product_id", "")

    print(f"📦 SẢN PHẨM: {name} ({brand}) | ID: {pid}")

    print(f"   Khẩu phần: {product.get('serving_value')} {product.get('serving_unit')}")
    print(f"   Đóng gói:  {product.get('package_value')} {product.get('package_unit')}")

    if nutrition:
        print("\n   GIÁ TRỊ DINH DƯỠNG (mỗi khẩu phần):")
        for item in nutrition:
            nut_name = item.get("nutrient", "")
            val = item.get("value", 0)
            unit = item.get("unit", "")
            print(f"     • {nut_name:15}: {val:>6} {unit}")

    if ingredients:
        print(f"\n   DANH SÁCH THÀNH PHẦN:")
        print(f"     {', '.join(ingredients)}")

    if allergens:
        print(f"\n   CẢNH BÁO DỊ ỨNG:")
        print(f"     ⚠️  Có chứa: {', '.join(allergens)}")

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
