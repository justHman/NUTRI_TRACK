"""
NutriTrack Pipeline Script
==========================
Pipeline: Image → Qwen3VL (analyze_food) → USDA Nutrition Lookup → Final Results

Supports 2 modes:
- "tools": Model drives USDA lookups via tool calling (Method 3)
- "manual": Traditional 2-step flow — Qwen → USDA per ingredient (Method 1 + USDA)

Usage:
    python -m app.scripts.pipeline <image_path> [--method tools|manual]
"""

import os
import sys
import time
import json
from typing import Optional
from dotenv import load_dotenv

# project_root = app/ directory (this is the package root for Docker)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger
from models.QWEN3VL import Qwen3VL
from utils.schemas import FoodList, NutritionInfo
from third_apis.USDA import USDAClient
from utils.caculator import calculate_ingredient_nutrition, calculate_total_nutrition, adjust_nutrition_for_cooking_method

logger = get_logger(__name__)


def analyze_nutrition(image_path: Optional[str] = None, qwen: Optional[Qwen3VL] = None, client: Optional[USDAClient] = None,
                      method: str = "tools", image_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> dict:
    """
    Full pipeline: Image → Qwen3VL → USDA → Nutrition Results
    """
    logger.title("Nutrition Analysis Pipeline")
    logger.info("Image: %s | Method: %s", image_path or filename, method)
    
    pipeline_start = time.time()

    # 1. Load env & init clients if not provided
    env_path = os.path.join(project_root, "config", ".env")
    load_dotenv(env_path)

    if qwen is None:
        logger.info("Initializing Qwen3VL client...")
        qwen = Qwen3VL()
    else:
        logger.debug("Using pre-initialized Qwen3VL client")

    if client is None:
        logger.info("Initializing USDAClient...")
        client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
    else:
        logger.debug("Using pre-initialized USDAClient")

    if method == "tools":
        return _analyze_with_tools(image_path, image_bytes, filename, qwen, client, pipeline_start)
    else:
        return _analyze_manual(image_path, image_bytes, filename, qwen, client, pipeline_start)


def _analyze_with_tools(image_path: Optional[str], image_bytes: Optional[bytes], filename: Optional[str],
                         qwen: Qwen3VL, client: USDAClient, pipeline_start: float) -> dict:
    """Tool-calling pipeline"""
    logger.title("Pipeline Mode: Tool Calling")

    step_start = time.time()
    food_list: FoodList = qwen.analyze_food_with_tools(image_path=image_path, image_bytes=image_bytes, filename=filename, client=client, max_tool_rounds=1)
    logger.info("Pipeline tool-calling analysis complete: %d dish(es) in %.1fs",
                len(food_list.dishes), time.time() - step_start)
    
    return food_list.model_dump()



def _analyze_manual(image_path: Optional[str], image_bytes: Optional[bytes], filename: Optional[str],
                     qwen: Qwen3VL, client: USDAClient, pipeline_start: float) -> dict:
    """Manual 2-step pipeline"""
    logger.title("Pipeline Mode: Manual (2-step)")

    # Step 1: Qwen image analysis
    logger.title("Step 1/2: Qwen3VL Image Analysis")
    step_start = time.time()
    food_list: FoodList = qwen.analyze_food(image_path=image_path, image_bytes=image_bytes, filename=filename)
    logger.info("Step 1/2 complete: detected %d dish(es) in %.1fs",
                len(food_list.dishes), time.time() - step_start)
    logger.info("Food list: %s", food_list.model_dump_json(indent=2))

    # Step 2: USDA lookup per ingredient
    logger.title("Step 2/2: USDA Nutrition Lookup")
    step_start = time.time()

    for food_idx, food in enumerate(food_list.dishes, 1):
        logger.info("Processing dish %d/%d: %s (%s)",
                     food_idx, len(food_list.dishes), food.name, food.vi_name or "N/A")
                     
        ingredient_nutritions = []

        for ing_idx, ing in enumerate(food.ingredients, 1):
            weight = ing.weight if ing.weight else 0.0
            logger.debug("  Ingredient %d/%d: %s (weight=%.1fg)",
                         ing_idx, len(food.ingredients), ing.name, weight)

            usda_100g = client.get_nutritions(ing.name)
            
            # If USDA returned data, override the model's estimated_nutritions
            if usda_100g and any(usda_100g.get(k, 0) > 0 for k in ["calories", "protein", "carbs", "fat"]):
                calculated_nutrition = calculate_ingredient_nutrition(usda_100g, weight)
                ing.nutritions = NutritionInfo(**calculated_nutrition)
                logger.debug("  USDA calculation used: %s", calculated_nutrition)
            else:
                logger.debug("  USDA data unavailable/zeros. Keeping model's estimated_nutritions.")
                
            if ing.nutritions:
                ingredient_nutritions.append(ing.nutritions.model_dump())

            time.sleep(0.2)  # USDA rate limit

        # Calculate dish total
        dish_total_raw = calculate_total_nutrition(ingredient_nutritions)
        dish_total_adjusted = adjust_nutrition_for_cooking_method(dish_total_raw, food.cooking_method)
        
        food.nutritions = NutritionInfo(**dish_total_adjusted)

        logger.info("Dish '%s' total: cal=%.1f pro=%.1f carb=%.1f fat=%.1f",
                     food.name, dish_total_adjusted["calories"], dish_total_adjusted["protein"],
                     dish_total_adjusted["carbs"], dish_total_adjusted["fat"])

    total_time = time.time() - pipeline_start
    logger.info("Pipeline complete in %.1fs (method=manual)", total_time)

    return food_list.model_dump()


def print_report(results: dict):
    """Pretty-print the FoodList nutrition report to console"""
    dishes = results.get("dishes", [])
    logger.info("Generating nutrition report for %d dish(es)...", len(dishes))

    print(f"\n{'='*95}")
    print(f"📊 BÁO CÁO DINH DƯỠNG CHI TIẾT (FoodList Model)")
    print(f"{'='*95}\n")
    
    if results.get("error"):
        print(f"⚠️ Error: {results['error']}")
        return

    for food in dishes:
        name = food.get("name", "Unknown")
        vi_name = food.get("vi_name", "")
        cooking_method = food.get("cooking_method", "N/A")
        
        print(f"🍽️  MÓN: {name} ({vi_name}) | Cách chế biến: {cooking_method}")
        
        ingredients = food.get("ingredients", [])
        if ingredients:
            print(f"{'Ingredient':<28} | {'Weight':>8} | {'Estimated (Cal/P/C/F)':<28}")
            print("-" * 95)

            for ing in ingredients:
                n = ing.get("nutritions") or {}
                n_str = f"{n.get('calories',0):>5.0f}/{n.get('protein',0):>4.1f}/{n.get('carbs',0):>4.1f}/{n.get('fat',0):>4.1f}"
                weight = ing.get('weight', 0)
                ing_name = ing.get('name', '')[:26]
                print(f"   {ing_name:<25} | {weight:>7.1f}g | {n_str:<28}")

            t = food.get("nutritions", {})
            total_weight = food.get("weight", 0)
            print("-" * 95)
            print(f"📊 TỔNG CỘNG: Cân nặng={total_weight}g | Cal={t.get('calories',0):.1f} | Pro={t.get('protein',0):.1f}g | Carb={t.get('carbs',0):.1f}g | Fat={t.get('fat',0):.1f}g")
        else:
            print("  Không có thành phần nào.")

        print("\n" + "=" * 95 + "\n")

    logger.info("Report generation complete")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("No image path provided")
        print("Usage: python -m app.scripts.pipeline <image_path> [--method tools|manual]")
        sys.exit(1)

    img = sys.argv[1]
    if not os.path.isabs(img):
        img = os.path.join(project_root, img)

    method = "tools"
    if "--method" in sys.argv:
        idx = sys.argv.index("--method")
        if idx + 1 < len(sys.argv):
            method = sys.argv[idx + 1]

    logger.info("CLI invocation: image_path=%s, method=%s", img, method)
    results = analyze_nutrition(img, method=method)
    print_report(results)

    # Also save JSON output
    output_path = os.path.join(project_root, "data", "output", "nutrition_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("JSON results saved to: %s", output_path)
