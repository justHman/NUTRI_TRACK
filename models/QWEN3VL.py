import boto3
import json
import os
from typing import List, Optional, Type
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from utils.processor import prepare_image_for_bedrock

# Load env from app/config/.env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

class Ingredient(BaseModel):
    """A single ingredient with detail"""
    name: str = Field(description="Name of the ingredient (in English)")
    vi_name: Optional[str] = Field(default=None, description="Name in Vietnamese if known")
    estimated_weight_g: Optional[float] = Field(default=None, description="Estimated weight in grams")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0.0 - 1.0")

class FoodItem(BaseModel):
    """A dish with its ingredient names"""
    name: str = Field(description="Dish name in English")
    vi_name: Optional[str] = Field(default=None, description="Dish name in Vietnamese")
    ingredients: List[Ingredient] = Field(description="List of detected ingredients")
    total_estimated_calories: Optional[float] = Field(default=None, description="Total estimated calories")

class FoodList(BaseModel):
    """List of food items detected in the image"""
    items: List[FoodItem] = Field(description="List of dishes with their ingredients")


# ─── Qwen3 VL Client ─────────────────────────────────────────────────────────

class Qwen3VL:
    """Qwen3 VL 235B - Multimodal Vision-Language Model via AWS Bedrock
    
    Uses raw Converse API + JSON prompt + Pydantic validation for structured output.
    (Note: instructor.from_bedrock() is NOT compatible with Qwen3 VL for structured output)
    """

    def __init__(self, region="us-east-1", model_id="qwen.qwen3-vl-235b-a22b"):
        self.model_id = model_id
        self.region = region
        self.client = boto3.client("bedrock-runtime", region_name=region)
        print(f"✅ Qwen3 VL Ready! (model: {model_id}, region: {region})")

    # ─── Generic analyze method ──────────────────────────────────────────

    def analyze(self, image_path: str, prompt: str, response_model: Type[BaseModel]) -> BaseModel:
        """Generic image analysis with structured Pydantic output
        
        Uses 2-step approach:
        1. Send image + JSON-formatted prompt to Bedrock Converse API
        2. Parse the raw JSON response with Pydantic for validation
        
        Args:
            image_path: Path to the image file
            prompt: Text prompt describing what to extract
            response_model: Pydantic BaseModel class for structured output
        
        Returns:
            Instance of response_model with extracted data
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        print(f"🔄 Loading image from {image_path}...")
        image_bytes, img_format = prepare_image_for_bedrock(image_path)

        # NOTE: Do NOT dump the Pydantic schema here — it confuses Qwen3 VL
        # and causes empty results. Use a simple instruction instead.
        full_prompt = (
            f"{prompt}\n\n"
            f"Return ONLY valid JSON, no markdown, no explanation."
        )

        print(f"🚀 Analyzing with '{self.model_id}' → {response_model.__name__}...")

        response = self.client.converse(
            modelId=self.model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"image": {"format": img_format, "source": {"bytes": image_bytes}}},
                    {"text": full_prompt}
                ]
            }],
            inferenceConfig={"maxTokens": 2048}
        )

        raw_text = response["output"]["message"]["content"][0]["text"]

        # Strip markdown code blocks if model wraps in ```json ... ```
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0].strip()

        return response_model.model_validate_json(clean)

    def analyze_food(self, image_path: str) -> FoodList:
        """Analyze a food image and return detailed ingredient info
        
        Returns:
            FoodList: { items: [{ name, vi_name, ingredients: [{ name, vi_name, estimated_weight_g, confidence }] }] }
        """
        prompt = (
            "Look at this food image carefully. "
            "Identify all visible ingredients in the dish. "
            "For each ingredient, estimate its weight in grams "
            "and your confidence level (0.0 to 1.0). "
            "Hint: Use visible utensils as a reference scale to estimate ingredient weights more accurately. "
            "For reference, typical utensil weights are approximately: "
            "Dinner Knife (~70g), Spoon (~40g), Fork (~35g), Chopsticks (~15g). "
            "Also identify the dish name in both English and Vietnamese, "
            "and estimate total calories.\n\n"
            'Use this exact JSON format:\n'
            '{"items": [{"name": "...", "vi_name": "...", '
            '"ingredients": [{"name": "...", "vi_name": "...", '
            '"estimated_weight_g": 100, "confidence": 0.9}], '
            '"total_estimated_calories": 500}]}'
        )
        return self.analyze(image_path, prompt, FoodList)   


if __name__ == "__main__":
    qwen = Qwen3VL()
    img_path = r"data\images\food\fast_food.jpg"

    result = qwen.analyze_food(img_path)
    print(result)
