import os
from typing import Optional
from dotenv import load_dotenv

from third_apis.Bedrock import BedrockModel
from utils.transformer import convert_food_csv_to_json, clean_csv_raw_text
from utils.counter import count_tokens
from config.logging_config import get_logger
from config.prompt_config import FOOD_VISION_SYSTEM_PROMPT, FOOD_VISION_USER_PROMPT, FOOD_VISION_TOOLS_PROMPT
from utils.schemas import FoodList

logger = get_logger(__name__)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

class ANALYSIST(BedrockModel):
    def __init__(self, model_id=None, region=None):
        if model_id is None:
            model_id = os.getenv("MODEL_ID", "qwen.qwen3-vl-235b-a22b")
        super().__init__(model_id=model_id, region=region)

    def analyze_food(self, image_path: Optional[str] = None, image_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> FoodList:
        logger.info("analyze_food() called for image: %s", image_path or filename)
        raw_text = self.analyze(
            image_path=image_path,
            image_bytes=image_bytes,
            filename=filename,
            prompt=FOOD_VISION_USER_PROMPT,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
        )
        logger.info("[Converse] Raw response (~%d tokens):\n%s\n...", count_tokens(raw_text), str(raw_text)[:500])

        cleaned_text = clean_csv_raw_text(str(raw_text))
        logger.info("[Converse] Cleaned response:\n%s\n...", str(cleaned_text)[:500])

        result = convert_food_csv_to_json(cleaned_text)
        logger.info("[Converse] Convert_food_csv_to_json response:\n%s\n...", str(result)[:500])

        validated_result = FoodList.model_validate(result)
        logger.info("[Converse] Successfully parsed response:\n%s\n...", str(validated_result)[:500])
        return validated_result

    def analyze_food_with_tools(self, image_path: Optional[str] = None, client=None, max_tool_rounds: int = 1, image_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> FoodList:
        logger.info("analyze_food_with_tools() called for image: %s", image_path or filename)

        formatted_tools_prompt = FOOD_VISION_TOOLS_PROMPT.replace("{max_tool_rounds}", str(max_tool_rounds))
        tool_prompt = FOOD_VISION_USER_PROMPT + "\n" + formatted_tools_prompt

        raw_text = self.analyze_with_tool_calling(
            image_path=image_path,
            image_bytes=image_bytes,
            filename=filename,
            prompt=tool_prompt,
            client=client,
            system_prompt=FOOD_VISION_SYSTEM_PROMPT,
            max_tool_rounds=max_tool_rounds
        )
        logger.info("[ToolCalling] Raw response (~%d tokens):\n%s\n...", count_tokens(raw_text), str(raw_text))

        cleaned_text = clean_csv_raw_text(str(raw_text))
        logger.info("[ToolCalling] Clean response:\n%s\n...", str(cleaned_text)[:500])

        result = convert_food_csv_to_json(cleaned_text)
        logger.info("[ToolCalling] Convert_food_csv_to_json response:\n%s\n...", str(result)[:500])

        validated_result = FoodList.model_validate(result)
        logger.info("[ToolCalling] Successfully parsed response into FoodList (%d dishes):\n%s\n...", len(validated_result.dishes), str(validated_result)[:500])
        return validated_result

if __name__ == "__main__":
    analysist = ANALYSIST()
    img_path = r"data\images\food\fast_food.jpg"

    result = analysist.analyze_food(img_path)
    logger.info("Analysis result: %s", result)
