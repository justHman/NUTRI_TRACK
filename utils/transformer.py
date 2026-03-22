import re
import unicodedata
from typing import Dict
import sys
import os
import csv
import io

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import get_logger

logger = get_logger(__name__)

def clean_csv_raw_text(raw_text: str) -> str:
    text = raw_text.strip()
    text = re.sub(r"```(?:csv)?\s*([\s\S]*?)```", r"\1", text, flags=re.IGNORECASE)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\s*,\s*', ',', text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r'\n{2,}', '\n\n', text)
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) >= 2:
        cleaned_text = "\n\n".join(parts)
    elif parts:
        cleaned_text = parts[0]
    return cleaned_text

def safe_float(value, default=0.0):
    """Safely convert value to float, handling None, empty strings, and strings."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def normalize_query(query: str) -> str:
    """
    Robust multilingual normalize:
    - lowercase, strip
    - remove accents (Vietnamese, French, German, etc.)
    - extract prefix before parentheses (if =2 chars)
    - replace hyphens/underscores with spaces
    - remove punctuation
    - collapse multiple spaces
    """
    if not query:
        logger.debug("normalize_query: empty input, returning ''")
        return ""

    original = query
    query = str(query).strip().lower()

    # Remove common trademark symbols before normalization so they don't expand to letters like 'TM'
    query = re.sub(r"[\u2122\u00ae\u00a9]", "", query)

    query = unicodedata.normalize('NFKD', query)
    query = ''.join([c for c in query if not unicodedata.combining(c)])

    match = re.match(r"^(.*?)\s*\(.*?\)", query)
    if match:
        prefix = match.group(1).strip()
        if len(prefix) >= 2:
            query = prefix
            logger.debug("normalize_query: extracted prefix '%s' from '%s'", prefix, original)

    query = re.sub(r"[-_]", " ", query)
    query = re.sub(r"[()]", "", query)
    query = re.sub(r"[^\w\s]", "", query)
    query = re.sub(r"\s+", " ", query).strip()

    logger.debug("normalize_query: '%s' → '%s'", original, query)
    return query

def get_mock_nutrition(query: str) -> Dict[str, float]:
    """Safe mock fallback when no API key or no result."""
    logger.warning("Using MOCK nutrition for query='%s'", query)
    return {
        "calories": 100.0,
        "protein": 5.0,
        "fat": 3.0,
        "carbs": 15.0,
    }

def batch_to_csv(batch):
    """
    Input:[
            ["apple", 52.0, 0.26, 13.84, 0.17, ["apple"], 100], 
            ["banana", 89.0, 1.09, 22.84, 0.33, ["banana"], 100]
        ]
    Output:
        name|calories|protein|carbs|fat|ingredients|weight;
        apple|52|0.26|13.84|0.17|apple|100;
        banana|100|1.09|27|0.33|banana|100;
    """
    lines = ["name|calories|protein|carbs|fat|ingredients|weight"]
    
    def _opt(x):
        return int(x) if isinstance(x, float) and x.is_integer() else x

    for name, cal, pro, car, fat, ings, w in batch:
        # tối ưu token: bỏ .0 nếu là int
        cal, pro, car, fat, w = map(_opt, [cal, pro, car, fat, w])

        # Handle None or empty ingredients
        ing_str = ",".join(ings) if ings else ""

        line = f"{name}|{cal}|{pro}|{car}|{fat}|{ing_str}|{w}"
        lines.append(line)

    return ";".join(lines)

def normalize_number(x):
    """Convert number: 19.0 -> 19"""
    try:
        x = float(x)
        return int(x) if x.is_integer() else round(x, 2)
    except:
        return x

def parse_csv_block(csv_text):
    """Parse CSV string to list of dict"""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    return [dict(row) for row in reader]

def convert_food_csv_to_json(text):
    """
    Input: raw text chứa 2 bảng CSV (có thể dính nhau hoặc cách nhau bởi dòng trống)
    Output: JSON format cũ
    """
    text = text.strip()

    # 🔹 Tìm vị trí bắt đầu của bảng 2 (Ingredient table)
    # Cả 2 bảng đều bắt đầu bằng header 'dish_id,', ta tìm lần xuất hiện thứ 2 ở đầu dòng.
    matches = list(re.finditer(r"^dish_id,", text, re.MULTILINE))

    if len(matches) < 2:
        # Fallback cho trường hợp format không chuẩn hoặc chỉ có 1 bảng
        parts = text.split("\n\n")
        if len(parts) < 2:
            raise ValueError("Không tìm thấy đủ 2 bảng CSV")
        dish_csv = parts[0]
        ingredient_csv = parts[1]
    else:
        # Bảng 2 bắt đầu tại matches[1].start()
        dish_csv = text[:matches[1].start()].strip()
        ingredient_csv = text[matches[1].start():].strip()

    dishes_raw = parse_csv_block(dish_csv)
    ingredients_raw = parse_csv_block(ingredient_csv)

    # 🔹 Group ingredients theo dish_id
    ingredient_map = {}
    for ing in ingredients_raw:
        dish_id = ing["dish_id"]
        ingredient_map.setdefault(dish_id, []).append(ing)

    dishes = []

    for d in dishes_raw:
        dish_id = d["dish_id"]

        ingredients = []
        for ing in ingredient_map.get(dish_id, []):
            ingredients.append({
                "name": ing["name"],
                "vi_name": ing["vi_name"],
                "weight": normalize_number(ing["weight"]),
                "nutritions": {
                    "calories": normalize_number(ing["calories"]),
                    "protein": normalize_number(ing["protein"]),
                    "carbs": normalize_number(ing["carbs"]),
                    "fat": normalize_number(ing["fat"]),
                },
                "confidence": safe_float(ing.get("confidence"), 0.9),
                "note": ing.get("note", "")
            })

        dishes.append({
            "name": d.get("name", ""),
            "vi_name": d.get("vi_name", ""),
            "confidence": safe_float(d.get("confidence"), 0.9),
            "cooking_method": d.get("cooking_method", ""),
            "ingredients": ingredients,
            "weight": normalize_number(d.get("weight", 0)),
            "nutritions": {
                "calories": normalize_number(d.get("calories", 0)),
                "protein": normalize_number(d.get("protein", 0)),
                "carbs": normalize_number(d.get("carbs", 0)),
                "fat": normalize_number(d.get("fat", 0)),
            },
            "scale_reference": d.get("scale_reference_used", "")
        })

    return {
        "dishes": dishes,
        "image_quality": dishes_raw[0].get("image_quality", "unknown")
    }

def convert_label_csv_to_json(text: str):
    """
    Convert multi-section CSV format to JSON.

    Input: raw text with 4 CSV sections separated by blank lines:
        1. Product info (product_id, name, brand, serving_value, serving_unit, confidence, note)
        2. Nutrition facts (product_id, nutrient, value, unit, dv_percentage)
        3. Ingredients (product_id, ingredient) - ingredient is list format "[item1, item2, ...]"
        4. Allergens (product_id, allergen) - allergen is list format "[item1, item2, ...]"

    Output: JSON with structure:
        {
            "labels": [
                {
                    "product_id": int,
                    "name": str,
                    "brand": str,
                    "serving_value": float,
                    "serving_unit": str,
                    "nutrition": [{"nutrient": str, "value": float, "unit": str}, ...],
                    "ingredients": [str, ...],
                    "allergens": [str, ...],
                    "confidence": float,
                    "note": str
                }
            ]
        }
    """
    text = text.strip()

    # Split into sections by double newline
    sections = [s.strip() for s in text.split("\n\n") if s.strip()]

    if len(sections) < 4:
        logger.error(f"Expected 4 CSV sections, found {len(sections)}")
        raise ValueError(f"Need 4 CSV sections, found {len(sections)}")

    # Parse each section
    products_data = parse_csv_block(sections[0])
    nutrition_data = parse_csv_block(sections[1])

    logger.debug(f"Parsed {len(products_data)} products, {len(nutrition_data)} nutrition rows")

    # Group nutrition by product_id
    nutrition_map = {}
    for row in nutrition_data:
        product_id = row["product_id"]
        nutrition_map.setdefault(product_id, []).append(row)

    # Helper function to parse list format "[item1, item2, ...]"
    def parse_list_field(field_str):
        """Extract items from bracket-notation list"""
        if not field_str:
            return []
        field_str = field_str.strip()
        if field_str.startswith("[") and field_str.endswith("]"):
            field_str = field_str[1:-1]
        return [item.strip() for item in field_str.split(",") if item.strip()]

    # Parse ingredients manually (CSV parser splits on commas inside brackets)
    def parse_ingredient_section(section_text):
        """Parse ingredient section manually due to bracket notation"""
        result = {}
        lines = section_text.split("\n")
        header = lines[0].split(",")  # ["product_id", "ingredient"]

        for line in lines[1:]:
            if not line.strip():
                continue
            # Split only on first comma to preserve bracket notation
            parts = line.split(",", 1)
            if len(parts) == 2:
                product_id = parts[0].strip()
                ingredient_str = parts[1].strip()
                result[product_id] = parse_list_field(ingredient_str)
        return result

    # Parse allergens manually (same reason as ingredients)
    def parse_allergen_section(section_text):
        """Parse allergen section manually due to bracket notation"""
        result = {}
        lines = section_text.split("\n")
        header = lines[0].split(",")  # ["product_id", "allergen"]

        for line in lines[1:]:
            if not line.strip():
                continue
            # Split only on first comma to preserve bracket notation
            parts = line.split(",", 1)
            if len(parts) == 2:
                product_id = parts[0].strip()
                allergen_str = parts[1].strip()
                result[product_id] = parse_list_field(allergen_str)
        return result

    # Group ingredients by product_id
    ingredients_map = parse_ingredient_section(sections[2])

    # Group allergens by product_id
    allergens_map = parse_allergen_section(sections[3])

    # Build output
    labels = []
    for product in products_data:
        product_id = product["product_id"]

        # Build nutrition array
        nutrition = []
        for n in nutrition_map.get(product_id, []):
            nutrition.append({
                "nutrient": n.get("nutrient", ""),
                "value": safe_float(n.get("value")),
                "unit": n.get("unit", "")
            })

        label = {
            "product_id": int(product_id),
            "name": product.get("name", ""),
            "brand": product.get("brand", ""),
            "serving_value": safe_float(product.get("serving_value")),
            "serving_unit": product.get("serving_unit", ""),
            "nutrition": nutrition,
            "ingredients": ingredients_map.get(product_id, []),
            "allergens": allergens_map.get(product_id, []),
            "confidence": safe_float(product.get("confidence")),
            "note": product.get("note", "")
        }

        labels.append(label)

    logger.info(f"Successfully converted {len(labels)} labels to JSON")
    return {"labels": labels}
    
if __name__ == "__main__":
    raw = """
product_id,name,brand,serving_value,serving_unit,confidence,note
1,Mì Ăn Liền,Doraemon,75,g,0.9,Per serving size

product_id,nutrient,value,unit,dv_percentage
1,Calories,350,kcal,1.5
1,Protein,6.9,g,3.2
1,Carbohydrate,51.4,g,1.8
1,Fat,13.0,g,2.0

product_id,ingredient
1,[bột mì, dầu thực vật, chất chống oxy hóa, chất điều chỉnh độ acid, bột nghệ, chất tạo màu tự nhiên, chất tạo ngọt tổng hợp]

product_id,allergen
1,[wheat, soy]
"""

    clean = clean_csv_raw_text(raw)
    print(clean)
    result = convert_label_csv_to_json(clean)
    print(result)
    with open("test_output.json", "w", encoding="utf-8") as f:
        import json
        print(json.dump(result, f, ensure_ascii=True, indent=2))