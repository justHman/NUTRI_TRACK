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
from dotenv import load_dotenv

# project_root = app/ directory (this is the package root for Docker)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, "config", ".env"))

from config.logging_config import get_logger
from models.QWEN3VL import Qwen3VL, FoodList
from third_apis.USDA import USDAClient

logger = get_logger(__name__)


def analyze_nutrition(image_path: str, qwen: Qwen3VL = None, usda_client: USDAClient = None,
                      method: str = "tools") -> list[dict]:
    """
    Full pipeline: Image → Qwen3VL → USDA → Nutrition Results
    
    Args:
        image_path: Path to the food image
        qwen: Optional pre-initialized Qwen3VL instance
        usda_client: Optional pre-initialized USDAClient instance
        method: "tools" (model-driven tool calling) or "manual" (2-step flow)
    
    Returns:
        List of dicts, one per detected dish, with full nutrition breakdown
    """
    logger.title("Nutrition Analysis Pipeline")
    logger.info("Image: %s | Method: %s", image_path, method)
    
    pipeline_start = time.time()

    # 1. Load env & init clients if not provided
    env_path = os.path.join(project_root, "config", ".env")
    load_dotenv(env_path)

    if qwen is None:
        logger.info("Initializing Qwen3VL client...")
        qwen = Qwen3VL()
    else:
        logger.debug("Using pre-initialized Qwen3VL client")

    if usda_client is None:
        logger.info("Initializing USDAClient...")
        usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
    else:
        logger.debug("Using pre-initialized USDAClient")

    if method == "tools":
        return _analyze_with_tools(image_path, qwen, usda_client, pipeline_start)
    else:
        return _analyze_manual(image_path, qwen, usda_client, pipeline_start)


def _analyze_with_tools(image_path: str, qwen: Qwen3VL, usda_client: USDAClient,
                         pipeline_start: float) -> list[dict]:
    """
    Tool-calling pipeline: Model drives USDA lookups via get_PCF_and_ingredients + get_PCF.
    The model decides which tools to call and when.

    Output format is enriched to match manual-mode: every ingredient gets
    `usda_100g`, `nutrition`, `weight_g` fields, and every dish gets
    `total_nutrition` + `average_calories`.
    """
    logger.title("Pipeline Mode: Tool Calling")

    step_start = time.time()
    food_list: FoodList = qwen.analyze_food_with_tools(image_path, usda_client)
    logger.info("Tool-calling analysis complete: %d dish(es) in %.1fs",
                len(food_list.items), time.time() - step_start)

    # ── Enrich each dish with USDA nutrition, matching manual-mode output ──
    results = []
    for food in food_list.items:
        food_data = {
            "name": food.name,
            "vi_name": food.vi_name,
            "qwen_estimated_calories": food.total_estimated_calories,
            "ingredients": [],
        }

        total_nutrition = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}

        for ing in food.ingredients:
            weight = ing.estimated_weight_g if ing.estimated_weight_g else 0.0
            ratio = weight / 100.0

            # USDA lookup — cache will serve already-fetched entries instantly
            usda_100g = usda_client.get_PCF(ing.name)

            nutrition = {
                "calories": round(usda_100g["calories"] * ratio, 4),
                "protein":  round(usda_100g["protein"]  * ratio, 4),
                "carbs":    round(usda_100g["carbs"]    * ratio, 4),
                "fat":      round(usda_100g["fat"]      * ratio, 4),
            }

            food_data["ingredients"].append({
                "name":     ing.name,
                "vi_name":  ing.vi_name,
                "weight_g": weight,
                "usda_100g": usda_100g,
                "nutrition": nutrition,
            })

            for k in total_nutrition:
                total_nutrition[k] += nutrition[k]

        food_data["total_nutrition"] = {k: round(v, 4) for k, v in total_nutrition.items()}
        avg_cal = (total_nutrition["calories"] + (food.total_estimated_calories or 0)) / 2
        food_data["average_calories"] = round(avg_cal, 4)

        results.append(food_data)
        logger.info("Dish '%s' (%s) — USDA cal=%.1f, avg_cal=%.1f, ingredients: %d",
                    food.name, food.vi_name or "N/A",
                    total_nutrition["calories"], avg_cal, len(food.ingredients))

    total_time = time.time() - pipeline_start
    logger.info("Pipeline complete in %.1fs (method=tools)", total_time)
    return results



def _analyze_manual(image_path: str, qwen: Qwen3VL, usda_client: USDAClient,
                     pipeline_start: float) -> list[dict]:
    """
    Manual 2-step pipeline: Qwen identifies foods → USDA lookup per ingredient.
    """
    logger.title("Pipeline Mode: Manual (2-step)")

    # Step 1: Qwen image analysis
    logger.title("Step 1/2: Qwen3VL Image Analysis")
    step_start = time.time()
    food_list: FoodList = qwen.analyze_food(image_path)
    logger.info("Step 1/2 complete: detected %d dish(es) in %.1fs",
                len(food_list.items), time.time() - step_start)

    # Step 2: USDA lookup per ingredient
    logger.title("Step 2/2: USDA Nutrition Lookup")
    step_start = time.time()
    final_nutrition_results = []

    for food_idx, food in enumerate(food_list.items, 1):
        logger.info("Processing dish %d/%d: %s (%s)",
                     food_idx, len(food_list.items), food.name, food.vi_name or "N/A")
        
        food_data = {
            "name": food.name,
            "vi_name": food.vi_name,
            "qwen_estimated_calories": food.total_estimated_calories,
            "ingredients": []
        }

        total_nutrition = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}

        for ing_idx, ing in enumerate(food.ingredients, 1):
            logger.debug("  Ingredient %d/%d: %s (weight=%.1fg)",
                         ing_idx, len(food.ingredients), ing.name,
                         ing.estimated_weight_g if ing.estimated_weight_g else 0)

            usda_100g = usda_client.get_PCF(ing.name)

            weight = ing.estimated_weight_g if ing.estimated_weight_g else 0
            ratio = weight / 100.0

            nutrition = {
                "calories": usda_100g["calories"] * ratio,
                "protein": usda_100g["protein"] * ratio,
                "carbs": usda_100g["carbs"] * ratio,
                "fat": usda_100g["fat"] * ratio,
            }

            logger.debug("  USDA per 100g: %s → Scaled (%.1fg): cal=%.1f pro=%.1f carb=%.1f fat=%.1f",
                         usda_100g, weight,
                         nutrition["calories"], nutrition["protein"],
                         nutrition["carbs"], nutrition["fat"])

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

        logger.info("Dish '%s' totals: cal=%.1f pro=%.1f carb=%.1f fat=%.1f (avg_cal=%.1f)",
                     food.name, total_nutrition["calories"], total_nutrition["protein"],
                     total_nutrition["carbs"], total_nutrition["fat"], avg_calories)

    logger.info("Step 2/2 complete: processed %d dish(es) with %d total ingredients in %.1fs",
                len(final_nutrition_results),
                sum(len(f["ingredients"]) for f in final_nutrition_results),
                time.time() - step_start)

    total_time = time.time() - pipeline_start
    logger.info("Pipeline complete in %.1fs (method=manual)", total_time)

    return final_nutrition_results


def print_report(results: list[dict]):
    """Pretty-print the nutrition report to console"""
    logger.info("Generating nutrition report for %d dish(es)...", len(results))

    print(f"\n{'='*95}")
    print(f"📊 BÁO CÁO DINH DƯỠNG CHI TIẾT")
    print(f"{'='*95}\n")

    for food in results:
        name = food.get("name", "Unknown")
        vi_name = food.get("vi_name", "")
        cal = food.get("total_estimated_calories") or food.get("qwen_estimated_calories") or "N/A"
        
        print(f"🍽️  MÓN: {name} ({vi_name})")
        print(f"🔥 Calories: {cal}")
        
        ingredients = food.get("ingredients", [])
        if ingredients and isinstance(ingredients[0], dict) and "usda_100g" in ingredients[0]:
            # Manual mode output
            print(f"{'Ingredient':<20} | {'Weight':>8} | {'USDA(100g) Cal/P/C/F':<24} | {'REAL Cal/P/C/F':<24}")
            print("-" * 95)

            for ing in ingredients:
                u = ing.get("usda_100g", {})
                r = ing.get("nutrition", {})
                u_str = f"{u.get('calories',0):>5.0f}/{u.get('protein',0):>4.1f}/{u.get('carbs',0):>4.1f}/{u.get('fat',0):>4.1f}"
                r_str = f"{r.get('calories',0):>5.0f}/{r.get('protein',0):>4.1f}/{r.get('carbs',0):>4.1f}/{r.get('fat',0):>4.1f}"
                print(f"   {ing.get('name',''):<17} | {ing.get('weight_g',0):>7.1f}g | {u_str:<24} | {r_str:<24}")

            t = food.get("total_nutrition", {})
            avg = food.get("average_calories", 0)
            print("-" * 95)
            print(f"📊 TỔNG CỘNG: Cal={t.get('calories',0):.0f} | Pro={t.get('protein',0):.1f}g | Carb={t.get('carbs',0):.1f}g | Fat={t.get('fat',0):.1f}g | Avg={avg:.0f}")
        else:
            # Tools mode output — ingredients are Pydantic-dumped dicts
            for ing in ingredients:
                if isinstance(ing, dict):
                    print(f"  • {ing.get('name', '?')} — {ing.get('estimated_weight_g', '?')}g (conf: {ing.get('confidence', '?')})")
                else:
                    print(f"  • {ing}")

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
