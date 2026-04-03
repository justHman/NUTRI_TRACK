import os
from typing import Optional

from dotenv import load_dotenv

from config.logging_config import get_logger
from config.prompt_config import LABEL_VISION_SYSTEM_PROMPT, LABEL_VISION_USER_PROMPT
from third_apis.Bedrock import BedrockModel
from utils.counter import count_tokens
from utils.schemas import LabelList
from utils.transformer import clean_csv_raw_text, convert_label_csv_to_json

logger = get_logger(__name__)

load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"
    )
)


class OCRER(BedrockModel):
    def __init__(self, model_id=None, region=None):
        if model_id is None:
            model_id = os.getenv("MODEL_ID", "qwen.qwen3-vl-235b-a22b")
        super().__init__(model_id=model_id, region=region)

    def analyze_label(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
    ) -> LabelList:
        logger.info("analyze_label() called for image: %s", image_path or filename)
        raw_text = self.analyze(
            image_path=image_path,
            image_bytes=image_bytes,
            filename=filename,
            prompt=LABEL_VISION_USER_PROMPT,
            system_prompt=LABEL_VISION_SYSTEM_PROMPT,
        )
        logger.info(
            "[Converse] Raw response (~%d tokens):\n%s\n...",
            count_tokens(raw_text),
            str(raw_text)[:500],
        )

        cleaned_text = clean_csv_raw_text(str(raw_text))
        logger.info("[Converse] Cleaned response:\n%s\n...", str(cleaned_text)[:500])

        result = convert_label_csv_to_json(cleaned_text)
        logger.info(
            "[Converse] Convert_label_csv_to_json response:\n%s\n...", str(result)[:500]
        )

        validated_result = LabelList.model_validate(result)
        logger.info(
            "[Converse] Successfully parsed response:\n%s\n...",
            str(validated_result)[:500],
        )
        return validated_result
