import os
import sys
import dotenv
from models.QWEN3VL import Qwen3VL
from third_apis.USDA import USDAClient

dotenv.load_dotenv()

def test():
    qwen = Qwen3VL()
    usda_client = USDAClient(api_key=os.getenv("USDA_API_KEY", "DEMO_KEY"))
    
    # Path to fast_food.jpg
    image_path = os.path.join("data", "fast_food.jpg")
    if not os.path.exists(image_path):
        # try search from project root
        image_path = os.path.join(os.getcwd(), "app", "data", "fast_food.jpg")
    
    print(f"Testing Method 3 on {image_path}...")
    
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    
    try:
        result = qwen.analyze_food_with_tools(
            image_bytes=img_bytes, 
            filename="fast_food.jpg", 
            usda_client=usda_client
        )
        print(f"Success! Found {len(result.dishes)} dishes.")
        for dish in result.dishes:
            print(f" - {dish.name} ({dish.weight_g}g)")
    except Exception as e:
        print(f"Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Add project root to sys.path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    # Also 'app' directory
    app_dir = os.path.join(project_root, "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
        
    test()
