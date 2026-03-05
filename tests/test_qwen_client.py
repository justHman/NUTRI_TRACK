import sys
import os
import time

# Thêm root vào sys.path để import được app
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger
from models.QWEN3VL import Qwen3VL, FoodList

logger = get_logger(__name__)

def test_qwen_structured_output(image_path: str):
    """Test Qwen3VL parsing capabilities"""
    logger.title(f"Testing Qwen3VL (Image: {os.path.basename(image_path)})")
    
    if not os.path.exists(image_path):
        logger.error("❌ Image not found at: %s", image_path)
        return

    qwen = Qwen3VL()
    
    # --- Phương thức 1: Converse API (Manual JSON) ---
    logger.title("Method 1: Native Converse API")
    try:
        start_time = time.time()
        result1 = qwen.analyze_food(image_path)
        duration = time.time() - start_time
        
        logger.info("✅ SUCCESS (%.1fs)", duration)
        logger.info("Detected %d dish(es)", len(result1.items))
        for i, item in enumerate(result1.items, 1):
            logger.info("   [%d] %s (%s) - Cal: %s", 
                        i, item.name, item.vi_name, item.total_estimated_calories)
            # Log ingredients count
            logger.debug("      - Ingredients count: %d", len(item.ingredients))
    except Exception as e:
        logger.error("❌ Method 1 FAILED: %s", str(e), exc_info=True)

    # --- Phương thức 2: Instructor (Auto Pydantic) ---
    logger.title("Method 2: Instructor[Bedrock]")
    try:
        start_time = time.time()
        result2 = qwen.analyze_food_with_instructor(image_path)
        duration = time.time() - start_time
        
        logger.info("✅ SUCCESS (%.1fs)", duration)
        logger.info("Detected %d dish(es)", len(result2.items))
        for i, item in enumerate(result2.items, 1):
            logger.info("   [%d] %s (%s) - Cal: %s", 
                        i, item.name, item.vi_name, item.total_estimated_calories)
    except Exception as e:
        logger.error("❌ Method 2 FAILED: %s", str(e))

    # --- Phương thức 3: Tool Calling (Function Calling) ---
    logger.title("Method 3: Tool Calling (get_nutrition)")
    try:
        from third_apis.USDA import USDAClient
        
        usda_api_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
        usda_client = USDAClient(api_key=usda_api_key)
        
        start_time = time.time()
        result3 = qwen.analyze_food_with_tools(image_path, usda_client)
        duration = time.time() - start_time
        
        logger.info("✅ SUCCESS (%.1fs)", duration)
        logger.info("Detected %d dish(es)", len(result3.items))
        for i, item in enumerate(result3.items, 1):
            logger.info("   [%d] %s (%s) - Cal: %s", 
                        i, item.name, item.vi_name, item.total_estimated_calories)
            for ing in item.ingredients:
                logger.debug("      - %s: %.1fg (conf: %.2f)", 
                             ing.name, ing.estimated_weight_g or 0, ing.confidence or 0)
    except Exception as e:
        logger.error("❌ Method 3 FAILED: %s", str(e), exc_info=True)


def main(img_path=None):
    # Thử tìm ảnh trong data/nếu không truyền tham số
    # Ưu tiên lấy từ tham số dòng lệnh
    if img_path is None:
        if len(sys.argv) > 1:
            img_path = sys.argv[1]
        else:
            # Tìm file ảnh bất kỳ trong data/ để test tạm
            img_path = os.path.join(project_root, "data", "images", "food", "com_tam.jpg") 
            # Nếu chưa có ảnh, nhắc người dùng
            if not os.path.exists(img_path):
                logger.warning("No test image found at %s", img_path)
                logger.info("Usage: python tests/test_qwen_client.py <path_to_image>")
                return

    test_qwen_structured_output(img_path)

if __name__ == "__main__":
    img_path = r"D:\Project\Code\nutritrack-documentation\data\images\food\fast_food.jpg"
    main(img_path)
