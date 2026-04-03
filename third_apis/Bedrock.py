import boto3
from botocore.config import Config
import json
import os
from typing import Any, List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel
from utils.processor import prepare_image_for_bedrock
from utils.transformer import batch_to_csv, convert_food_csv_to_json, clean_csv_raw_text, convert_label_csv_to_json
from utils.counter import count_tokens
from config.logging_config import get_logger
from config.prompt_config import (FOOD_VISION_SYSTEM_PROMPT, FOOD_VISION_USER_PROMPT, FOOD_VISION_TOOLS_PROMPT,
                                  LABEL_VISION_SYSTEM_PROMPT, LABEL_VISION_USER_PROMPT)
from utils.schemas import LabelList, FoodList

logger = get_logger(__name__)

# Load env from app/config/.env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

# Load tool config from JSON
_config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
with open(os.path.join(_config_dir, "nutrition_tool_config.json"), "r", encoding="utf-8") as f:
    NUTRITION_TOOL_CONFIG = json.load(f)
logger.debug("Loaded nutrition_tool_config.json: %d tools", len(NUTRITION_TOOL_CONFIG.get("tools", [])))


PRICE_PER_1K_INPUT: float = float(os.getenv("PRICE_PER_1K_INPUT", 0.00053))
PRICE_PER_1K_OUTPUT: float = float(os.getenv("PRICE_PER_1K_OUTPUT", 0.00266))

# ─── Qwen3 VL Client ─────────────────────────────────────────────────────────

class MODEL:
    """Model via AWS Bedrock
    
    Supports 3 methods for structured output:
    1. analyze() — Raw Converse API + JSON prompt + manual Pydantic validation
    2. analyze_with_instructor() — instructor[bedrock] + chat.completions + auto Pydantic validation
    3. analyze_with_tool_calling() — Converse API + toolConfig (function calling loop)
    """

    def __init__(self, region=None, model_id=None)):
        if model_id is None:
            logger.info("Set your MODEL ID")
        self.model_id = model_id
        # Ưu tiên lấy từ biến môi trường, nếu không có thì dùng mặc định us-east-1
        self.region = region or os.getenv("AWS_REGION") or "ap-southeast-2"
        logger.title("Initializing " + model_id)
        logger.info("model=%s, region=%s", model_id, self.region)

        # Boto3 sẽ tự động tìm AWS_ACCESS_KEY_ID và AWS_SECRET_ACCESS_KEY 
        # trong biến môi trường hệ thống.
        self.client = boto3.client(
            "bedrock-runtime", 
            region_name=self.region,
            config=Config(read_timeout=300)
        )
        logger.debug("Bedrock runtime client created for region=%s", self.region)

        self.token_input = 0
        self.price_input = 0.0
        self.token_output = 0
        self.price_output = 0.0
        self.bedrock_calls = 0

    def reset_usage(self):
        """Reset the token usage counters."""
        self.token_input = 0
        self.price_input = 0.0
        self.token_output = 0
        self.price_output = 0.0
        self.bedrock_calls = 0

        logger.info("%s ready! (model=%s, region=%s)",os.getenv("MODEL_ID", "qwen.qwen3-vl-235b-a22b"), self.model_id, self.region)

    def _compute_price(self):
        """Recalculate input/output price from current token counts."""
        self.price_input = float(self.token_input * PRICE_PER_1K_INPUT / 1000)
        self.price_output = float(self.token_output * PRICE_PER_1K_OUTPUT / 1000)

    # ─── Method 1: Converse API (Manual JSON parsing) ────────────────────

    def analyze(self, image_path: Optional[str] = None, prompt: str = "",
                system_prompt: Optional[str] = None, image_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> BaseModel:
        """Generic image analysis with structured Pydantic output (Converse API)"""
        self.reset_usage()
        if image_bytes is None:
            if not image_path or not os.path.exists(image_path):
                logger.error("Image not found: %s", image_path)
                raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[Converse] Setup image processing...")
        image_bytes, img_format = prepare_image_for_bedrock(image_path, image_bytes, filename)
        logger.debug("[Converse] Image ready: format=%s, size=%.2fMB",
                     img_format, len(image_bytes) / 1024 / 1024)

        logger.info("[Converse] Analyzing with '%s'", self.model_id)
        if system_prompt:
            logger.info("[Converse] System prompt (%d tokens): %s...", count_tokens(system_prompt), str(system_prompt)[:500])
        logger.info("[Converse] User prompt (%d tokens): %s...", count_tokens(prompt), str(prompt)[:500])

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
        self.bedrock_calls += 1

        if "usage" in response:
            self.token_input += response["usage"].get("inputTokens", 0)
            self.token_output += response["usage"].get("outputTokens", 0)

        raw_text = response["output"]["message"]["content"][0]["text"]
        self._compute_price()
        return raw_text
    # ─── Method 2: Converse API + Tool Calling (Function Calling) ────────

    # Tool definition for USDA nutrition lookup
    def analyze_with_tool_calling(self, image_path: Optional[str] = None, prompt: str = "",
                                   client=None, system_prompt: Optional[str] = None,
                                   max_tool_rounds: int = 1, image_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> str:
        """Image analysis with tool calling (Converse API + toolConfig)"""
        self.reset_usage()
        if image_bytes is None:
            if not image_path or not os.path.exists(image_path):
                logger.error("Image not found: %s", image_path)
                raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("[ToolCalling] Setup image processing...")
        image_bytes, img_format = prepare_image_for_bedrock(image_path, image_bytes, filename)
        logger.debug("[ToolCalling] Image ready: format=%s, size=%.2fMB",
                     img_format, len(image_bytes) / 1024 / 1024)

        # Build initial messages
        messages: List[Any] = [{
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
            logger.info("[ToolCalling] System prompt (%d tokens): %s...", count_tokens(str(system_prompt)), str(system_prompt)[:500])
        logger.info("[ToolCalling] User prompt (%d tokens): %s...", count_tokens(str(prompt)), str(prompt)[:500])

        logger.info("[ToolCalling] Sending initial request to '%s' with %d tools...",
                    self.model_id, len(NUTRITION_TOOL_CONFIG.get("tools", [])))

        # ── Tool-use loop ──
        for round_num in range(1, max_tool_rounds + 2):
            response = self.client.converse(**converse_kwargs)
            self.bedrock_calls += 1

            if "usage" in response:
                self.token_input += response["usage"].get("inputTokens", 0)
                self.token_output += response["usage"].get("outputTokens", 0)

            stop_reason = response.get("stopReason", "end_turn")
            output_message = response["output"]["message"]
            logger.info("[ToolCalling] Round %d — stopReason: %s", round_num, stop_reason)
            logger.info("[ToolCalling] Output message: %s", str(output_message)[:1000])

            # If model is done (no more tool calls), return the text
            if stop_reason != "tool_use":
                final_text = "".join(block.get("text", "") for block in output_message.get("content", []) if "text" in block)
                self._compute_price()
                logger.info("[ToolCalling] Final response received (%d tokens): %s\n...", count_tokens(str(final_text)), str(final_text)[:500])
                return final_text

            # Model requested tool use — process each tool call
            # ── Sanitize assistant message to avoid ParamValidationError in next round ──
            clean_content: List[Any] = []
            for block in output_message.get("content", []):
                if "toolUse" in block:
                    t_name = block["toolUse"].get("name", "")
                    if not t_name:
                        logger.warning("[ToolCalling] Dropping toolUse with empty name")
                        continue

                    tool_input = block["toolUse"].get("input", {})

                    if t_name == "get_batch":
                        items = tool_input.get("items", [])
                        if not items or not isinstance(items, list):
                            logger.warning("[ToolCalling] Dropping toolUse get_batch with missing items: %s", tool_input)
                            continue
                        for item in items:
                            name = item.get("name", None)
                            weight = item.get("weight", 0.0)
                            if not name or not weight:
                                logger.warning("[ToolCalling] Dropping toolUse get_batch with empty food_name or weight_g: %s", item)
                                continue
                    else:    
                        continue
                clean_content.append(block)
            output_message["content"] = clean_content
            
            messages.append(output_message)

            tool_results: List[Any] = []
            for block in output_message.get("content", []):
                if "toolUse" not in block:
                    continue

                tool_use = block["toolUse"]
                tool_use_id = tool_use.get("toolUseId", "")
                tool_name = tool_use.get("name", "")
                tool_input = tool_use.get("input", {})

                logger.info("[ToolCalling] Tool request: %s(input=%s)",
                            tool_name, json.dumps(tool_input, ensure_ascii=False))

                # ── Tool dispatcher ──
                try:
                    if tool_name.startswith("get_batch"):
                        items = tool_input.get("items", [])
                        result = client.get_batch(items)
                        if result is None:
                            raise ValueError(f"No batch data found for '{items}'")
                        logger.info("[ToolCalling] ✅ get_batch() → processed %d items", len(items))
                    else:
                        raise ValueError(f"Unknown tool: {tool_name}")
                    
                    # Convert to CSV format
                    processed_result = batch_to_csv(result)
                    logger.info("[ToolCalling] ✅ get_batch() → processed \n%s", processed_result)

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": {"csv_data": processed_result}}], # Phải là dict, không được là string
                            "status": "success"
                        }
                    })

                except Exception as e:
                    logger.error("[ToolCalling] ❌ %s failed: %s", tool_name, e)
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
        
        max_tool_rounds_prompt = "[SYSTEM] You have reached the maximum number of tool use rounds. Please provide the final JSON answer now based on the information you have gathered."
        # Append to the LAST message instead of creating a new one (to preserve alternating roles)
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"].append({"text": max_tool_rounds_prompt})
            converse_kwargs["messages"] = messages
            
        response = self.client.converse(**converse_kwargs)
        self.bedrock_calls += 1
        if "usage" in response:
            self.token_input += response["usage"].get("inputTokens", 0)
            self.token_output += response["usage"].get("outputTokens", 0)
            
        output_message = response["output"]["message"]
        final_text = "".join(block.get("text", "") for block in output_message.get("content", []) if "text" in block)
        
        self._compute_price()
        logger.info("[ToolCalling] Final attempt received (%d tokens): %s", count_tokens(final_text), str(final_text)[:500])
        return final_text


if __name__ == "__main__":
    qwen = Qwen3VL()
    img_path = r"data\images\food\fast_food.jpg"

    result = qwen.analyze_food(img_path)
    logger.info("Analysis result: %s", result)
