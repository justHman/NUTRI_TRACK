from pydantic import BaseModel, Field
from typing import List, Optional

# ─── Label Schemas ────────────────────────────────────────────────────────
class NutritionItem(BaseModel):
    nutrient: str
    value: float
    unit: str
    dv_percentage: Optional[float] = Field(default=None, description="Daily value percentage, if available")

class LabelItem(BaseModel):
    product_id: int
    name: str
    brand: str
    serving_value: float
    serving_unit: str
    nutrition: List[NutritionItem]
    ingredients: List[str]
    allergens: List[str]
    expiry_days: Optional[int] = Field(default=None, description="Number of days the food can be used before expiration, measured in days")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0.0 - 1.0 for the overall label analysis")
    note: Optional[str] = Field(default=None, description="Optional note, e.g., 'inferred from similar product'")

class LabelList(BaseModel):
    labels: List[LabelItem]
    image_quality: Optional[str] = Field(default=None, description="Image quality: good | poor_lighting | blurry | partial_view")


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
    weight: Optional[float] = Field(default=None, description="Estimated weight in grams")
    nutritions: Optional[NutritionInfo] = Field(default=None, description="Estimated nutrition")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0.0 - 1.0")
    note: Optional[str] = Field(default=None, description="Optional note, e.g., 'inferred – typical pho garnish'")

class FoodItem(BaseModel):
    """A dish with its ingredient names"""
    name: str = Field(description="Dish name in English")
    serving_value: float = Field(description="Serving size value")
    serving_unit: str = Field(description="Serving size unit, e.g., g, ml, piece")
    confidence: Optional[float] = Field(default=None, description="Confidence score for dish identification (0.0-1.0)")
    cooking_method: Optional[str] = Field(default=None, description="Cooking method: grilled | fried | steamed | boiled | raw | mixed")
    ingredients: List[Ingredient] = Field(description="List of detected ingredients")
    weight: Optional[float] = Field(default=None, description="Estimated weight in grams")
    nutritions: Optional[NutritionInfo] = Field(default=None, description="Total estimated nutrition")
    expiry_days: Optional[int] = Field(description="Number of days the food can be used before expiration, measured in days")
    scale_reference: Optional[str] = Field(default=None, description="What was used as scale reference: chopsticks visible | plate size | no reference")

class FoodList(BaseModel):
    """List of food items detected in the image"""
    dishes: List[FoodItem] = Field(description="List of dishes with their ingredients")
    image_quality: Optional[str] = Field(default=None, description="Image quality: good | poor_lighting | blurry | partial_view")

if __name__ == "__main__":
    # Example usage
    print(2)
