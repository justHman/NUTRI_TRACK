"""
NutriTrack AI Models
====================
    from models import Qwen3VL

Available models:
    - Qwen3VL: Multimodal Vision-Language (AWS Bedrock)

Pydantic schemas:
    - NutritionInfo: (calories, protein, carbs, fat)
    - Ingredient: (name, vi_name, estimated_weight_g, estimated_nutritions, confidence, note)
    - FoodItem: (name, vi_name, confidence, cooking_method, ingredients, total_estimated_weight_g, total_estimated_nutritions, scale_reference_used)
    - FoodList: (dishes: List[FoodItem], image_quality)
"""

from utils.schemas import (
    NutritionItem,
    LabelItem,
    LabelList,
    NutritionInfo,
    Ingredient,
    FoodItem,
    FoodList,
)
from .QWEN3VL import Qwen3VL
