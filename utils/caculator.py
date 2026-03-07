from typing import Dict, Any, List
import copy
from config.logging_config import get_logger

logger = get_logger(__name__)

def calculate_ingredient_nutrition(usda_100g: Dict[str, float], weight_g: float) -> Dict[str, float]:
    """
    Calculate the nutrition of an ingredient given its 100g USDA reference and estimated weight.
    """
    ratio = weight_g / 100.0 if weight_g else 0.0
    
    return {
        "calories": round(usda_100g.get("calories", 0) * ratio, 2),
        "protein": round(usda_100g.get("protein", 0) * ratio, 2),
        "carbs": round(usda_100g.get("carbs", 0) * ratio, 2),
        "fat": round(usda_100g.get("fat", 0) * ratio, 2)
    }

def calculate_total_nutrition(ingredient_nutritions: List[Dict[str, float]]) -> Dict[str, float]:
    """
    Sum up the nutritions from a list of ingredient nutrition dicts.
    """
    total = {
        "calories": 0.0,
        "protein": 0.0,
        "carbs": 0.0,
        "fat": 0.0
    }
    
    for nut in ingredient_nutritions:
        if not nut:
            continue
        total["calories"] += nut.get("calories", 0.0)
        total["protein"] += nut.get("protein", 0.0)
        total["carbs"] += nut.get("carbs", 0.0)
        total["fat"] += nut.get("fat", 0.0)
        
    return {k: round(v, 2) for k, v in total.items()}

def adjust_nutrition_for_cooking_method(total_nutrition: Dict[str, float], cooking_method: str) -> Dict[str, float]:
    """
    Adjust the final dish nutrition based on the cooking method.
    Typically, frying or grilling adds extra calories and fat from oils.
    """
    if not total_nutrition:
        return total_nutrition
        
    adjusted = copy.deepcopy(total_nutrition)
    method = str(cooking_method).lower().strip() if cooking_method else ""
    
    # Adjust multipliers based on common nutrition logic
    if "fried" in method:
        # Frying adds ~30% more calories and fat
        adjusted["calories"] = round(adjusted.get("calories", 0) * 1.3, 2)
        adjusted["fat"] = round(adjusted.get("fat", 0) * 1.3, 2)
        logger.debug("Cooking method 'fried' detected: applied +30% to calories & fat")
    elif "grilled" in method:
        # Grilling with oil brush adds ~10-15% more calories and fat
        adjusted["calories"] = round(adjusted.get("calories", 0) * 1.15, 2)
        adjusted["fat"] = round(adjusted.get("fat", 0) * 1.15, 2)
        logger.debug("Cooking method 'grilled' detected: applied +15% to calories & fat")
    elif method in ["steamed", "boiled", "raw", "mixed"]:
        # No major additions
        logger.debug("Cooking method '%s' detected: no adjustments made", method)
        pass 
    else:
        # Default or unhandled methods
        pass

    return adjusted
