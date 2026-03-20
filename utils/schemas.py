from pydantic import BaseModel, Field
from typing import List, Optional

# ─── Label Schemas ────────────────────────────────────────────────────────
class NutritionItem(BaseModel):
    nutrient: str
    value: float
    unit: str


class Product(BaseModel):
    product_id: int
    name: str
    brand: Optional[str] = ""
    serving_value: float
    serving_unit: str
    package_value: float
    package_unit: str


class FoodLabel(BaseModel):
    product: Product
    nutrition: List[NutritionItem]
    ingredients: List[str]
    allergens: List[str]


# ─── Food Schemas ────────────────────────────────────────────────────────
class NutritionInfo(BaseModel):
    """PCF of an ingredient"""
    calories: float = Field(description="Calories value (kcal)")
    protein: float = Field(description="Protein value (g)")
    carbs: float = Field(description="Carbohydrate value (g)")
    fat: float = Field(description="Fat value (g)")

class Ingredient(BaseModel):
    """A single ingredient with detail"""
    name: str = Field(description="Name of the ingredient (in English)")
    vi_name: Optional[str] = Field(default=None, description="Name in Vietnamese if known")
    weight: Optional[float] = Field(default=None, description="Estimated weight in grams")
    nutritions: Optional[NutritionInfo] = Field(default=None, description="Estimated nutrition")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0.0 - 1.0")
    note: Optional[str] = Field(default=None, description="Optional note, e.g., 'inferred – typical pho garnish'")

class FoodItem(BaseModel):
    """A dish with its ingredient names"""
    name: str = Field(description="Dish name in English")
    vi_name: Optional[str] = Field(default=None, description="Dish name in Vietnamese")
    confidence: Optional[float] = Field(default=None, description="Confidence score for dish identification (0.0-1.0)")
    cooking_method: Optional[str] = Field(default=None, description="Cooking method: grilled | fried | steamed | boiled | raw | mixed")
    ingredients: List[Ingredient] = Field(description="List of detected ingredients")
    weight: Optional[float] = Field(default=None, description="Estimated weight in grams")
    nutritions: Optional[NutritionInfo] = Field(default=None, description="Total estimated nutrition")
    scale_reference: Optional[str] = Field(default=None, description="What was used as scale reference: chopsticks visible | plate size | no reference")

class FoodList(BaseModel):
    """List of food items detected in the image"""
    dishes: List[FoodItem] = Field(description="List of dishes with their ingredients")
    image_quality: Optional[str] = Field(default=None, description="Image quality: good | poor_lighting | blurry | partial_view")
