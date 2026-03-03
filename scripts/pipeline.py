"""
NutriTrack Pipeline Script
==========================
Pipeline: Image → Qwen3VL (analyze_food) → USDA Nutrition Lookup → Final Results

Usage:
    python -m app.scripts.pipeline <image_path>
    python -m app.scripts.pipeline data/images/food/com_tam.jpg
"""

import os
import sys
import time
import json
from dotenv import load_dotenv

# project_root = app/ directory (this is the package root for Docker)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, "config", ".env"))

from models.QWEN3VL import Qwen3VL, FoodList
from third_apis.USAD import USDAClient


def analyze_nutrition(image_path: str, qwen: Qwen3VL = None, usda_client: USDAClient = None) -> list[dict]:
    """
    Full pipeline: Image → Qwen3VL → USDA → Nutrition Results
    
    Args:
        image_path: Path to the food image
        qwen: Optional pre-initialized Qwen3VL instance
        usda_client: Optional pre-initialized USDAClient instance
    
    Returns:
        List of dicts, one per detected dish, with full nutrition breakdown
    """
    # 1. Load env & init clients if not provided
    env_path = os.path.join(project_root, "config", ".env")
    load_dotenv(env_path)

    if qwen is None:
        qwen = Qwen3VL()
    if usda_client is None:
        usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))

    # 2. Analyze image with Qwen3VL
    print(f"📸 Phân tích ảnh: {image_path}")
    food_list: FoodList = qwen.analyze_food(image_path)
    print(f"✅ Phát hiện {len(food_list.items)} món ăn.")

    # 3. Lookup USDA & calculate real nutrition
    final_nutrition_results = []

    for food in food_list.items:
        food_data = {
            "name": food.name,
            "vi_name": food.vi_name,
            "qwen_estimated_calories": food.total_estimated_calories,
            "ingredients": []
        }

        total_nutrition = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}

        for ing in food.ingredients:
            # Lookup USDA (always returns per 100g)
            usda_100g = usda_client.get_nutrition(ing.name)

            # Calculate based on estimated weight
            weight = ing.estimated_weight_g if ing.estimated_weight_g else 0
            ratio = weight / 100.0

            nutrition = {
                "calories": usda_100g["calories"] * ratio,
                "protein": usda_100g["protein"] * ratio,
                "carbs": usda_100g["carbs"] * ratio,
                "fat": usda_100g["fat"] * ratio,
            }

            food_data["ingredients"].append({
                "name": ing.name,
                "vi_name": ing.vi_name,
                "weight_g": weight,
                "usda_100g": usda_100g,
                "nutrition": nutrition,
            })

            for k in total_nutrition:
                total_nutrition[k] += nutrition[k]

            time.sleep(0.2)  # USDA rate limit

        food_data["total_nutrition"] = total_nutrition
        avg_calories = (total_nutrition["calories"] + (food.total_estimated_calories or 0)) / 2
        food_data["average_calories"] = avg_calories
        final_nutrition_results.append(food_data)

    return final_nutrition_results


def print_report(results: list[dict]):
    """Pretty-print the nutrition report to console"""
    print(f"\n{'='*95}")
    print(f"📊 BÁO CÁO DINH DƯỠNG CHI TIẾT")
    print(f"{'='*95}\n")

    for food in results:
        print(f"🍽️  MÓN: {food['name']} ({food['vi_name']})")
        print(f"🔥 Calories (AI ước tính): {food['qwen_estimated_calories']} kcal")
        print(f"{'Ingredient':<20} | {'Weight':>8} | {'USDA(100g) Cal/P/C/F':<24} | {'REAL Cal/P/C/F':<24}")
        print("-" * 95)

        for ing in food["ingredients"]:
            u = ing["usda_100g"]
            r = ing["nutrition"]

            u_str = f"{u['calories']:>5.0f}/{u['protein']:>4.1f}/{u['carbs']:>4.1f}/{u['fat']:>4.1f}"
            r_str = f"{r['calories']:>5.0f}/{r['protein']:>4.1f}/{r['carbs']:>4.1f}/{r['fat']:>4.1f}"

            print(f"   {ing['name']:<17} | {ing['weight_g']:>7.1f}g | {u_str:<24} | {r_str:<24}")

        t = food["total_nutrition"]
        avg = food["average_calories"]
        print("-" * 95)
        print(f"📊 TỔNG CỘNG THỰC TẾ: {'':>10} | Avg Cal: {avg:>5.1f} | Cal: {t['calories']:>5.0f} | Pro: {t['protein']:>4.1f}g | Carb: {t['carbs']:>4.1f}g | Fat: {t['fat']:>4.1f}g")
        print("\n" + "=" * 95 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.scripts.pipeline <image_path>")
        print("Example: python -m app.scripts.pipeline data/images/food/com_tam.jpg")
        sys.exit(1)

    img = sys.argv[1]
    if not os.path.isabs(img):
        img = os.path.join(project_root, img)

    results = analyze_nutrition(img)
    print_report(results)

    # Also save JSON output
    output_path = os.path.join(project_root, "data", "output", "nutrition_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON saved to: {output_path}")
