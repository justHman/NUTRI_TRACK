"""
NutriTrack AI Models
====================
    from models import Qwen3VL, SAM3Segmenter

Available models:
    - Qwen3VL: Multimodal Vision-Language (AWS Bedrock)
    - SAM3Segmenter: Segment Anything Model 3 (Ultralytics, GPU)

Pydantic schemas:
    - Ingredient: (name, vi_name, estimated_weight_g, confidence)
    - FoodItem: (name, vi_name, ingredients: List[Ingredient], total_estimated_calories)
    - FoodList: (items: List[FoodItem])
"""

from models.QWEN3VL import (
    Qwen3VL,
    Ingredient,
    FoodItem,
    FoodList,
)
from models.SAM3 import SAM3Segmenter
