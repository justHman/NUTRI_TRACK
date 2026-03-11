import boto3
from botocore.config import Config
import json
import os
import re
from typing import List, Optional, Type
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from utils.processor import prepare_image_for_bedrock
from config.logging_config import get_logger
from config.prompt_config import (FOOD_VISION_SYSTEM_PROMPT, FOOD_VISION_USER_PROMPT, FOOD_VISION_TOOLS_PROMPT,
                                  LABEL_VISION_SYSTEM_PROMPT, LABEL_VISION_USER_PROMPT)

logger = get_logger(__name__)

# Load env from app/config/.env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

# Load tool config from JSON
_config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
with open(os.path.join(_config_dir, "nutrition_tool_config.json"), "r", encoding="utf-8") as f:
    NUTRITION_TOOL_CONFIG = json.load(f)
logger.debug("Loaded nutrition_tool_config.json: %d tools", len(NUTRITION_TOOL_CONFIG.get("tools", [])))


# ─── Pydantic Schemas ────────────────────────────────────────────────────────
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
    estimated_weight_g: Optional[float] = Field(default=None, description="Estimated weight in grams")
    estimated_nutritions: Optional[NutritionInfo] = Field(default=None, description="Estimated nutrition")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0.0 - 1.0")
    note: Optional[str] = Field(default=None, description="Optional note, e.g., 'inferred – typical pho garnish'")

class FoodItem(BaseModel):
    """A dish with its ingredient names"""
    name: str = Field(description="Dish name in English")
    vi_name: Optional[str] = Field(default=None, description="Dish name in Vietnamese")
    confidence: Optional[float] = Field(default=None, description="Confidence score for dish identification (0.0-1.0)")
    cooking_method: Optional[str] = Field(default=None, description="Cooking method: grilled | fried | steamed | boiled | raw | mixed")
    ingredients: List[Ingredient] = Field(description="List of detected ingredients")
    total_estimated_weight_g: Optional[float] = Field(default=None, description="Estimated weight in grams")
    total_estimated_nutritions: Optional[NutritionInfo] = Field(default=None, description="Total estimated nutrition")
    scale_reference_used: Optional[str] = Field(default=None, description="What was used as scale reference: chopsticks visible | plate size | no reference")

class FoodList(BaseModel):
    """List of food items detected in the image"""
    dishes: List[FoodItem] = Field(description="List of dishes with their ingredients")
    image_quality: Optional[str] = Field(default=None, description="Image quality: good | poor_lighting | blurry | partial_view")


# ─── Qwen3 VL Client ─────────────────────────────────────────────────────────

class Qwen3VL:
    """Qwen3 VL 235B - Multimodal Vision-Language Model via AWS Bedrock
    
    Supports 3 methods for structured output:
    1. analyze() — Raw Converse API + JSON prompt + manual Pydantic validation
    2. analyze_with_instructor() — instructor[bedrock] + chat.completions + auto Pydantic validation
    3. analyze_with_tool_calling() — Converse API + toolConfig (function calling loop)
    """

    def __init__(self, region=None, model_id="qwen.qwen3-vl-235b-a22b"):
        self.model_id = model_id
        # Ưu tiên lấy từ biến môi trường, nếu không có thì dùng mặc định us-east-1
        self.region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        logger.title("Initializing Qwen3VL")
        logger.info("model=%s, region=%s", model_id, self.region)

        # Boto3 sẽ tự động tìm AWS_ACCESS_KEY_ID và AWS_SECRET_ACCESS_KEY 
        # trong biến môi trường hệ thống.
        self.client = boto3.client(
            "bedrock-runtime", 
            region_name=self.region,
            config=Config(read_timeout=300)
        )
        logger.debug("Bedrock runtime client created for region=%s", self.region)

        self.input_tokens = 0
        self.output_tokens = 0

    def reset_usage(self):
        """Reset the token usage counters."""
        self.input_tokens = 0
        self.output_tokens = 0

        logger.info("Qwen3VL ready! (model=%s, region=%s)", self.model_id, self.region)

    # ─── Method 1: Converse API (Manual JSON parsing) ────────────────────

    def analyze(self, image_path: Optional[str] = None, prompt: str = "", response_model: Type[BaseModel] = None,
                system_prompt: str = None, image_bytes: Optional[bytes] = None, filename: str = None) -> BaseModel:
        """Generic image analysis with structured Pydantic output (Converse API)"""
        if image_bytes is None:
            if not image_path or not os.path.exists(image_path):
                logger.error("Image not found: %s", image_path)
                raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[Converse] Setup image processing...")
        image_bytes, img_format = prepare_image_for_bedrock(image_path, image_bytes, filename)
        logger.debug("[Converse] Image ready: format=%s, size=%.2fMB",
                     img_format, len(image_bytes) / 1024 / 1024)

        logger.info("[Converse] Analyzing with '%s' → %s...", self.model_id, response_model.__name__)
        if system_prompt:
            logger.debug("[Converse] System prompt: %d chars", len(system_prompt))

        # Build API kwargs
        converse_kwargs = {
            "modelId": self.model_id,
            "messages": [{
                "role": "user",
                "content": [
                    {"image": {"format": img_format, "source": {"bytes": image_bytes}}},
                    {"text": prompt}
                ]
            }],
            "inferenceConfig": {
                "maxTokens": 8192,
                "temperature": 0.2,
                "topP": 0.9
            }
        }

        # Add system prompt if provided
        if system_prompt:
            converse_kwargs["system"] = [{"text": system_prompt}]

        response = self.client.converse(**converse_kwargs)

        if "usage" in response:
            self.input_tokens += response["usage"].get("inputTokens", 0)
            self.output_tokens += response["usage"].get("outputTokens", 0)

        raw_text = response["output"]["message"]["content"][0]["text"]
        logger.debug("[Converse] Raw response length: %d chars", len(raw_text))

        # Robust JSON extraction
        clean = raw_text.strip()
        
        # Try to find a JSON block ```json ... ```
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', clean, re.DOTALL)
        if match:
            clean = match.group(1).strip()
            logger.debug("[Converse] Extracted JSON from markdown block")
        else:
            # If no markdown blocks, try finding the outermost {...}
            start_idx = clean.find('{')
            end_idx = clean.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                clean = clean[start_idx:end_idx+1]
                logger.debug("[Converse] Guesstimated JSON boundaries from text")

        result = response_model.model_validate_json(clean)
        logger.info("[Converse] Successfully parsed response into %s", response_model.__name__)
        return result

    # ─── Method 2: Converse API + Tool Calling (Function Calling) ────────

    # Tool definition for USDA nutrition lookup
    def analyze_with_tool_calling(self, image_path: Optional[str] = None, prompt: str = "",
                                   usda_client=None, system_prompt: str = None,
                                   max_tool_rounds: int = 2, image_bytes: Optional[bytes] = None, filename: str = None) -> str:
        """Image analysis with tool calling (Converse API + toolConfig)"""
        if image_bytes is None:
            if not image_path or not os.path.exists(image_path):
                logger.error("Image not found: %s", image_path)
                raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[ToolCalling] Setup image processing...")
        image_bytes, img_format = prepare_image_for_bedrock(image_path, image_bytes, filename)
        logger.debug("[ToolCalling] Image ready: format=%s, size=%.2fMB",
                     img_format, len(image_bytes) / 1024 / 1024)

        # Build initial messages
        messages = [{
            "role": "user",
            "content": [
                {"image": {"format": img_format, "source": {"bytes": image_bytes}}},
                {"text": prompt}
            ]
        }]

        # Build converse kwargs
        converse_kwargs = {
            "modelId": self.model_id,
            "messages": messages,
            "toolConfig": NUTRITION_TOOL_CONFIG,
            "inferenceConfig": {
                "maxTokens": 8192,
                "temperature": 0.2,
                "topP": 0.9
            }
        }
        if system_prompt:
            converse_kwargs["system"] = [{"text": system_prompt}]
            logger.debug("[ToolCalling] System prompt: %d chars", len(system_prompt))

        logger.info("[ToolCalling] Sending initial request to '%s' with %d tools...",
                    self.model_id, len(NUTRITION_TOOL_CONFIG.get("tools", [])))

        # ── Tool-use loop ──
        for round_num in range(1, max_tool_rounds + 2):
            response = self.client.converse(**converse_kwargs)

            if "usage" in response:
                self.input_tokens += response["usage"].get("inputTokens", 0)
                self.output_tokens += response["usage"].get("outputTokens", 0)

            stop_reason = response.get("stopReason", "end_turn")
            output_message = response["output"]["message"]
            logger.info("[ToolCalling] Output message: %s", str(output_message)[:1000])

            logger.info("[ToolCalling] Round %d — stopReason: %s", round_num, stop_reason)

            # If model is done (no more tool calls), return the text
            if stop_reason != "tool_use":
                final_text = ""
                for block in output_message.get("content", []):
                    if "text" in block:
                        final_text += block["text"]
                logger.info("[ToolCalling] Final response received (%d chars)", len(final_text))
                logger.debug("[ToolCalling] Final response preview: %s", final_text[:500])
                return final_text

            # Model requested tool use — process each tool call
            # ── Sanitize assistant message to avoid ParamValidationError in next round ──
            clean_content = []
            for block in output_message.get("content", []):
                if "toolUse" in block:
                    if not block["toolUse"].get("name"):
                        logger.warning("[ToolCalling] Dropping toolUse with empty name")
                        continue
                    tool_input = block["toolUse"].get("input", {})
                    if "food_name" not in tool_input or "weight_g" not in tool_input:
                        logger.warning("[ToolCalling] Dropping toolUse with missing food_name or weight_g: %s", tool_input)
                        continue
                    if not tool_input.get("food_name", "unknown") or not tool_input.get("weight_g", 0):
                        logger.warning("[ToolCalling] Dropping toolUse with empty food_name or weight_g: %s", tool_input)
                        continue
                clean_content.append(block)
            output_message["content"] = clean_content
            
            messages.append(output_message)

            tool_results = []
            for block in output_message.get("content", []):
                if "toolUse" not in block:
                    continue

                tool_use = block["toolUse"]
                tool_name = tool_use["name"]
                tool_use_id = tool_use["toolUseId"]
                tool_input = tool_use.get("input", {})

                logger.info("[ToolCalling] Tool request: %s(input=%s)",
                            tool_name, json.dumps(tool_input, ensure_ascii=False))

                # ── Tool dispatcher ──
                try:
                    food_name = tool_input.get("food_name", "unknown")
                    
                    # ── Robust name matching ──
                    if tool_name.startswith("get_nutritions_and") and tool_name != "get_nutritions_and_ingredients_by_weight":
                        logger.warning("[ToolCalling] Normalizing '%s' → 'get_nutritions_and_ingredients_by_weight'", tool_name)
                        tool_name = "get_nutritions_and_ingredients_by_weight"

                    if tool_name == "get_nutritions":
                        result = usda_client.get_nutritions(food_name)
                        if result is None:
                            raise ValueError(f"No nutrition data found for '{food_name}'")
                        logger.info("[ToolCalling] ✅ get_nutritions('%s') → %s", food_name, result)
                    
                    elif tool_name == "get_ingredients":
                        result = usda_client.get_ingredients(food_name)
                        if result is None:
                            raise ValueError(f"No ingredient data available for '{food_name}'")
                        logger.info("[ToolCalling] ✅ get_ingredients('%s') → %d items",
                                    food_name, len(result.get("ingredients") or []))
                    
                    elif tool_name == "get_nutritions_and_ingredients":
                        result = usda_client.get_nutritions_and_ingredients(food_name)
                        if result is None:
                            raise ValueError(f"No USDA data found for '{food_name}'")
                        logger.info("[ToolCalling] ✅ get_nutritions_and_ingredients('%s') → %s",
                                    food_name, result.get("description", "N/A"))
                    
                    elif tool_name == "get_nutritions_and_ingredients_by_weight":
                        weight_g = tool_input.get("weight_g", 0.0)
                        result = usda_client.get_nutritions_and_ingredients_by_weight(food_name, weight_g)
                        if result is None:
                            raise ValueError(f"No USDA data found for '{food_name}'")
                        logger.info("[ToolCalling] ✅ get_nutritions_and_ingredients_by_weight('%s', %.2fg) → %s",
                                    food_name, weight_g, result.get("description", "N/A"))

                    else:
                        raise ValueError(f"Unknown tool: {tool_name}")
                    
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": result}],
                            "status": "success"
                        }
                    })

                except Exception as e:
                    logger.error("[ToolCalling] ❌ %s('%s') failed: %s", tool_name, food_name, e)
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": f"Error: {str(e)}"}],
                            "status": "error"
                        }
                    })

            # Append tool results as a user message and continue the loop
            messages.append({"role": "user", "content": tool_results})
            converse_kwargs["messages"] = messages

        # ── Final attempt to get response after exhausting rounds ──
        logger.warning("[ToolCalling] Round limit reached (%d), attempting one final turn...", max_tool_rounds)
        
        max_tool_rounds_prompt = "SYSTEM INSTRUCTION: You have reached the maximum number of tool use rounds. Please provide the final JSON answer now based on the information you have gathered."
        
        # Append to the LAST message instead of creating a new one (to preserve alternating roles)
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"].append({"text": max_tool_rounds_prompt})
            converse_kwargs["messages"] = messages
            
        # Optional: Disable tools for the last turn so it's forced to generate text/JSON
        if "toolConfig" in converse_kwargs:
            del converse_kwargs["toolConfig"]
            
        response = self.client.converse(**converse_kwargs)
        if "usage" in response:
            self.input_tokens += response["usage"].get("inputTokens", 0)
            self.output_tokens += response["usage"].get("outputTokens", 0)
            
        output_message = response["output"]["message"]
        final_text = ""
        for block in output_message.get("content", []):
            if "text" in block:
                final_text += block["text"]
        
        logger.info("[ToolCalling] Final attempt received (%d chars)", len(final_text))
        return final_text

    # ─── Food Analysis Wrappers ──────────────────────────────────────────

    def analyze_food(self, image_path: Optional[str] = None, image_bytes: Optional[bytes] = None, filename: str = None) -> FoodList:
        """Analyze food using Converse API (Method 1) with professional prompts"""
        logger.info("analyze_food() called for image: %s", image_path or filename)
        return self.analyze(
            image_path=image_path,
            image_bytes=image_bytes,
            filename=filename,
            prompt=FOOD_VISION_USER_PROMPT,
            response_model=FoodList,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
        )

    def analyze_label(self, image_path: Optional[str] = None, image_bytes: Optional[bytes] = None, filename: str = None) -> FoodList:
        """Analyze nutrition label on product packaging using OCR (Method 1 Converse API)
        
        Returns FoodList with product as dish and nutritional info as ingredients.
        If no label detected, returns FoodList with empty dishes list.
        """
        logger.info("analyze_label() called for image: %s", image_path or filename)
        return self.analyze(
            image_path=image_path,
            image_bytes=image_bytes,
            filename=filename,
            prompt=LABEL_VISION_USER_PROMPT,
            response_model=FoodList,
            system_prompt=LABEL_VISION_SYSTEM_PROMPT,
        )

    def analyze_food_with_tools(self, image_path: Optional[str] = None, usda_client=None, max_tool_rounds: int = 2, image_bytes: Optional[bytes] = None, filename: str = None) -> FoodList:
        """Analyze food using Converse API + Tool Calling (Method 3)

        The model identifies food items from the image, then calls USDA tools:
        1. get_PCF_and_ingredients for each dish (RAG hint for dish-level data)
        2. get_PCF for each ingredient (RAG hint for ingredient-level data)
        3. Compiles final FoodList JSON using all USDA data as reference
        """
        logger.info("analyze_food_with_tools() called for image: %s", image_path or filename)

        formatted_tools_prompt = FOOD_VISION_TOOLS_PROMPT.replace("{max_tool_rounds}", str(max_tool_rounds))

        # Combine user prompt + tool instructions (careful formatting)
        tool_prompt = FOOD_VISION_USER_PROMPT + "\n" + formatted_tools_prompt

        logger.debug("[ToolCalling] tool_prompt length: %d chars", len(tool_prompt))

        raw_response = self.analyze_with_tool_calling(
            image_path=image_path,
            image_bytes=image_bytes,
            filename=filename,
            prompt=tool_prompt,
            usda_client=usda_client,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
            max_tool_rounds=max_tool_rounds
        )

        # Parse the final response into FoodList
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0].strip()
            logger.debug("[ToolCalling] Stripped markdown code blocks from response")

        result = FoodList.model_validate_json(clean)
        logger.info("[ToolCalling] Successfully parsed response into FoodList (%d dishes)", len(result.dishes))
        return result



if __name__ == "__main__":
    qwen = Qwen3VL()
    img_path = r"data\images\food\fast_food.jpg"

    result = qwen.analyze_food(img_path)
    logger.info("Analysis result: %s", result)
