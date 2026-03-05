import boto3
import base64
import json
import os
from typing import List, Optional, Type
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import instructor
from instructor import Mode
from utils.processor import prepare_image_for_bedrock
from config.logging_config import get_logger
from config.prompt_config import FOOD_VISION_SYSTEM_PROMPT, FOOD_VISION_USER_PROMPT
from config.nutrition_tool_config import NUTRITION_TOOL_CONFIG

logger = get_logger(__name__)

# Load env from app/config/.env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class Ingredient(BaseModel):
    """A single ingredient with detail"""
    name: str = Field(description="Name of the ingredient (in English)")
    vi_name: Optional[str] = Field(default=None, description="Name in Vietnamese if known")
    estimated_weight_g: Optional[float] = Field(default=None, description="Estimated weight in grams")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0.0 - 1.0")
    note: Optional[str] = Field(default=None, description="Optional note, e.g., 'inferred – typical pho garnish'")


class CalorieRange(BaseModel):
    """Min-max calorie range for a dish"""
    min: float = Field(description="Minimum estimated calories")
    max: float = Field(description="Maximum estimated calories")


class FoodItem(BaseModel):
    """A dish with its ingredient names"""
    name: str = Field(description="Dish name in English")
    vi_name: Optional[str] = Field(default=None, description="Dish name in Vietnamese")
    confidence: Optional[float] = Field(default=None, description="Confidence score for dish identification (0.0-1.0)")
    cooking_method: Optional[str] = Field(default=None, description="Cooking method: grilled | fried | steamed | boiled | raw | mixed")
    ingredients: List[Ingredient] = Field(description="List of detected ingredients")
    total_estimated_calories: Optional[float] = Field(default=None, description="Total estimated calories (rounded to nearest 10)")
    calorie_range: Optional[CalorieRange] = Field(default=None, description="Min-max calorie range estimate")
    scale_reference_used: Optional[str] = Field(default=None, description="What was used as scale reference: chopsticks visible | plate size | no reference")


class FoodList(BaseModel):
    """List of food items detected in the image"""
    items: List[FoodItem] = Field(description="List of dishes with their ingredients")
    image_quality: Optional[str] = Field(default=None, description="Image quality: good | poor_lighting | blurry | partial_view")
    error: Optional[str] = Field(default=None, description="Error message if no food detected, null otherwise")


# ─── Qwen3 VL Client ─────────────────────────────────────────────────────────

class Qwen3VL:
    """Qwen3 VL 235B - Multimodal Vision-Language Model via AWS Bedrock
    
    Supports 2 methods for structured output:
    1. analyze() — Raw Converse API + JSON prompt + manual Pydantic validation
    2. analyze_with_instructor() — instructor[bedrock] + chat.completions + auto Pydantic validation
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
            region_name=self.region
        )
        logger.debug("Bedrock runtime client created for region=%s", self.region)

        # Instructor client (chat.completions style)
        # Mode.BEDROCK_JSON: structured JSON output (no native tool calling required)
        # Qwen3-VL không hỗ trợ BEDROCK_TOOLS, dùng BEDROCK_JSON thay thế
        self.instructor_client = instructor.from_bedrock(
            client=self.client,
            mode=Mode.BEDROCK_JSON
        )
        logger.debug("Instructor client created (mode=BEDROCK_JSON)")

        logger.info("Qwen3VL ready! (model=%s, region=%s)", model_id, self.region)

    # ─── Method 1: Converse API (Manual JSON parsing) ────────────────────

    def analyze(self, image_path: str, prompt: str, response_model: Type[BaseModel],
                system_prompt: str = None) -> BaseModel:
        """Generic image analysis with structured Pydantic output (Converse API)
        
        Uses 2-step approach:
        1. Send image + JSON-formatted prompt to Bedrock Converse API
        2. Parse the raw JSON response with Pydantic for validation
        
        Args:
            image_path: Path to the image file
            prompt: Text prompt describing what to extract
            response_model: Pydantic BaseModel class for structured output
            system_prompt: Optional system prompt for setting AI behavior/role
        
        Returns:
            Instance of response_model with extracted data
        """
        if not os.path.exists(image_path):
            logger.error("Image not found: %s", image_path)
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[Converse] Loading image: %s", image_path)
        image_bytes, img_format = prepare_image_for_bedrock(image_path)
        logger.debug("[Converse] Image loaded: format=%s, size=%.2fMB",
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

        raw_text = response["output"]["message"]["content"][0]["text"]
        logger.debug("[Converse] Raw response length: %d chars", len(raw_text))

        # Strip markdown code blocks if model wraps in ```json ... ```
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0].strip()
            logger.debug("[Converse] Stripped markdown code blocks from response")

        result = response_model.model_validate_json(clean)
        logger.info("[Converse] Successfully parsed response into %s", response_model.__name__)
        return result

    # ─── Method 2: Instructor + chat.completions (Auto Pydantic) ─────────

    def analyze_with_instructor(self, image_path: str, prompt: str, response_model: Type[BaseModel],
                                system_prompt: str = None) -> BaseModel:
        """Generic image analysis with structured Pydantic output (Instructor + chat.completions)
        
        Uses instructor[bedrock] to automatically:
        1. Inject Pydantic schema into the prompt
        2. Parse and validate the response into the response_model
        
        Args:
            image_path: Path to the image file
            prompt: Text prompt describing what to extract
            response_model: Pydantic BaseModel class for structured output
            system_prompt: Optional system prompt for setting AI behavior/role
        
        Returns:
            Instance of response_model with extracted data
        """
        if not os.path.exists(image_path):
            logger.error("Image not found: %s", image_path)
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[Instructor] Loading image: %s", image_path)
        image_bytes, img_format = prepare_image_for_bedrock(image_path)
        logger.debug("[Instructor] Image loaded: format=%s, size=%.2fMB",
                     img_format, len(image_bytes) / 1024 / 1024)

        logger.info("[Instructor] Analyzing with '%s' → %s...", self.model_id, response_model.__name__)

        # Combine system prompt with user prompt for Instructor
        # Bedrock's Converse API 'system' param might not be passed correctly by Instructor,
        # so we merge it into the user prompt to be safe.
        full_user_prompt = prompt
        if system_prompt:
            full_user_prompt = f"{system_prompt}\n\nUSER REQUEST: {prompt}"
            logger.debug("[Instructor] System prompt merged into user prompt")

        # Build create kwargs — same structure as Converse API
        create_kwargs = {
            "modelId": self.model_id,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": img_format,
                            "source": {"bytes": image_bytes}
                        }
                    },
                    {"text": full_user_prompt}
                ]
            }],
            "response_model": response_model,
            "inferenceConfig": {
                "maxTokens": 8192,
                "temperature": 0.2,
                "topP": 0.9
            }
        }

        result = self.instructor_client.create(**create_kwargs)
        logger.info("[Instructor] Successfully parsed response into %s", response_model.__name__)
        return result


    # ─── Method 3: Converse API + Tool Calling (Function Calling) ────────

    # Tool definition for USDA nutrition lookup
    def analyze_with_tool_calling(self, image_path: str, prompt: str,
                                   usda_client, system_prompt: str = None,
                                   max_tool_rounds: int = 5) -> str:
        """Image analysis with tool calling (Converse API + toolConfig)

        The model can request to call get_nutrition() for each food item it detects.
        We handle the tool-use loop until the model produces a final text response.

        Args:
            image_path: Path to the image file
            prompt: Text prompt for analysis
            usda_client: USDAClient instance (provides get_nutrition())
            system_prompt: Optional system prompt
            max_tool_rounds: Max number of tool-use rounds to prevent infinite loops

        Returns:
            Final text response from the model (raw string, caller should parse)
        """
        if not os.path.exists(image_path):
            logger.error("Image not found: %s", image_path)
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[ToolCalling] Loading image: %s", image_path)
        image_bytes, img_format = prepare_image_for_bedrock(image_path)
        logger.debug("[ToolCalling] Image loaded: format=%s, size=%.2fMB",
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

        logger.info("[ToolCalling] Sending initial request to '%s' with toolConfig...", self.model_id)

        # ── Tool-use loop ──
        for round_num in range(1, max_tool_rounds + 1):
            response = self.client.converse(**converse_kwargs)
            stop_reason = response.get("stopReason", "end_turn")
            output_message = response["output"]["message"]

            logger.info("[ToolCalling] Round %d — stopReason: %s", round_num, stop_reason)

            # If model is done (no more tool calls), return the text
            if stop_reason != "tool_use":
                # Extract final text response
                final_text = ""
                for block in output_message.get("content", []):
                    if "text" in block:
                        final_text += block["text"]
                logger.info("[ToolCalling] Final response received (%d chars)", len(final_text))
                return final_text

            # Model requested tool use — process each tool call
            messages.append(output_message)

            tool_results = []
            for block in output_message.get("content", []):
                if "toolUse" not in block:
                    continue

                tool_use = block["toolUse"]
                tool_name = tool_use["name"]
                tool_use_id = tool_use["toolUseId"]
                tool_input = tool_use.get("input", {})

                logger.info("[ToolCalling] Tool request: %s (id=%s, input=%s)",
                            tool_name, tool_use_id, json.dumps(tool_input, ensure_ascii=False))

                if tool_name == "get_nutrition":
                    food_name = tool_input.get("food_name", "unknown")
                    try:
                        nutrition = usda_client.get_nutrition(food_name)
                        logger.info("[ToolCalling] ✅ get_nutrition('%s') → %s", food_name, nutrition)
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"json": nutrition}]
                            }
                        })
                    except Exception as e:
                        logger.error("[ToolCalling] ❌ get_nutrition('%s') failed: %s", food_name, e)
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"text": f"Error looking up nutrition: {str(e)}"}],
                                "status": "error"
                            }
                        })
                else:
                    logger.warning("[ToolCalling] Unknown tool requested: %s", tool_name)
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": f"Unknown tool: {tool_name}"}],
                            "status": "error"
                        }
                    })

            # Append tool results as a user message and continue the loop
            messages.append({"role": "user", "content": tool_results})
            converse_kwargs["messages"] = messages

        logger.warning("[ToolCalling] Exceeded max tool rounds (%d)", max_tool_rounds)
        return ""

    # ─── Food Analysis Wrappers ──────────────────────────────────────────

    def analyze_food(self, image_path: str) -> FoodList:
        """Analyze food using Converse API (Method 1) with professional prompts"""
        logger.info("analyze_food() called for image: %s", image_path)
        return self.analyze(
            image_path,
            prompt=FOOD_VISION_USER_PROMPT,
            response_model=FoodList,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
        )

    def analyze_food_with_instructor(self, image_path: str) -> FoodList:
        """Analyze food using Instructor + chat.completions (Method 2) with professional prompts"""
        logger.info("analyze_food_with_instructor() called for image: %s", image_path)
        return self.analyze_with_instructor(
            image_path,
            prompt=FOOD_VISION_USER_PROMPT,
            response_model=FoodList,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
        )

    def analyze_food_with_tools(self, image_path: str, usda_client) -> FoodList:
        """Analyze food using Converse API + Tool Calling (Method 3)

        The model identifies food items from the image, then calls get_nutrition()
        for each item to enrich the response with real USDA nutrition data.
        """
        logger.info("analyze_food_with_tools() called for image: %s", image_path)

        tool_prompt = (
            f"{FOOD_VISION_USER_PROMPT}\n\n"
            "IMPORTANT: After identifying each food item, you MUST call the get_nutrition tool "
            "for each dish to retrieve accurate nutrition data from USDA. "
            "Use the English name of each dish when calling the tool. "
            "After receiving all nutrition data, compile the final JSON response."
        )

        raw_response = self.analyze_with_tool_calling(
            image_path,
            prompt=tool_prompt,
            usda_client=usda_client,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
        )

        # Parse the final response into FoodList
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0].strip()
            logger.debug("[ToolCalling] Stripped markdown code blocks from response")

        result = FoodList.model_validate_json(clean)
        logger.info("[ToolCalling] Successfully parsed response into FoodList (%d items)", len(result.items))
        return result



if __name__ == "__main__":
    qwen = Qwen3VL()
    img_path = r"data\images\food\fast_food.jpg"

    result = qwen.analyze_food(img_path)
    logger.info("Analysis result: %s", result)

