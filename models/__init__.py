"""
NutriTrack AI Models
====================
    from models import ANALYSIST, OCRER

Available models:
    - ANALYSIST: Food visualization and analysis
    - OCRER: OCR reading of nutrition labels

Pydantic schemas:
    - NutritionInfo: (calories, protein, carbs, fat)
    - Ingredient: (name, vi_name, estimated_weight_g, estimated_nutritions, confidence, note)
    - FoodItem: (name, vi_name, confidence, cooking_method, ingredients, total_estimated_weight_g, total_estimated_nutritions, scale_reference_used)
    - FoodList: (dishes: List[FoodItem], image_quality)
"""

from utils.schemas import (
    FoodItem,
    FoodList,
    Ingredient,
    LabelItem,
    LabelList,
    NutritionInfo,
    NutritionItem,
)

from .ANALYSIST import ANALYSIST
from .OCRER import OCRER
