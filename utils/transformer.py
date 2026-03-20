import re
import unicodedata
from typing import Dict, List, Any
import sys
import os
import csv
import io

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import get_logger
from utils.schemas import Product, NutritionItem, FoodLabel

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

def parse_list_field(s: str):
    """
    Convert "[milk, sugar]" → ["milk", "sugar"]
    """
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip() for x in s.split(",") if x.strip()]

def convert_label_csv_to_json(text: str):
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not parts:
        return FoodLabel(
            product=Product(product_id=0, name="No label detected", serving_value=0, serving_unit="", package_value=0, package_unit=""),
            nutrition=[], ingredients=[], allergens=[]
        )

    product_block = parts[0]
    nutrition_block = parts[1] if len(parts) > 1 else ""
    ingredient_block = parts[2] if len(parts) > 2 else None
    allergen_block = parts[3] if len(parts) > 3 else None

    # 🔹 Product
    product_rows = parse_csv_block(product_block)
    if not product_rows:
         return FoodLabel(
            product=Product(product_id=0, name="No label detected", serving_value=0, serving_unit="", package_value=0, package_unit=""),
            nutrition=[], ingredients=[], allergens=[]
        )
    product_row = product_rows[0]
    product = Product(
        product_id=int(product_row.get("product_id", 0)),
        name=product_row.get("name", "Unknown"),
        brand=product_row.get("brand", ""),
        serving_value=safe_float(product_row.get("serving_value")),
        serving_unit=product_row.get("serving_unit", ""),
        package_value=safe_float(product_row.get("package_value")),
        package_unit=product_row.get("package_unit", ""),
    )

    # 🔹 Nutrition
    nutrition_rows = parse_csv_block(nutrition_block)
    nutrition = [
        NutritionItem(
            nutrient=row.get("nutrient", ""),
            value=safe_float(row.get("value")),
            unit=row.get("unit", ""),
        )
        for row in nutrition_rows
    ]

    # 🔹 Ingredients
    ingredients = []
    if ingredient_block:
        for pid, raw_val in _parse_bracket_table(ingredient_block):
            ingredients.extend(parse_list_field(raw_val))

    # 🔹 Allergens
    allergens = []
    if allergen_block:
        for pid, raw_val in _parse_bracket_table(allergen_block):
            allergens.extend(parse_list_field(raw_val))

    return FoodLabel(
        product=product,
        nutrition=nutrition,
        ingredients=ingredients,
        allergens=allergens
    )

def _parse_bracket_table(csv_text: str) -> list:
    """Parse bảng CSV dạng 'product_id,[item1, item2]'
    csv.DictReader không xử lý được dấu phẩy bên trong [...],
    nên ta split thủ công trên dấu phẩy đầu tiên.
    Returns: list of (product_id, raw_bracket_value)
    """
    lines = csv_text.strip().split("\n")
    if len(lines) < 2:
        return []
    results = []
    for line in lines[1:]:  # Bỏ header
        line = line.strip()
        if not line:
            continue
        # Split tại dấu phẩy đầu tiên: "1,[milk, sugar]" → ("1", "[milk, sugar]")
        parts = line.split(",", 1)
        if len(parts) == 2:
            pid = parts[0].strip()
            raw_val = parts[1].strip()
            results.append((pid, raw_val))
    return results

if __name__ == "__main__":
    raw = """product_id,name,brand,serving_value,serving_unit,package_value,package_unit
1,Milk,Vinamilk,100,ml,1000,ml

product_id,nutrient,value,unit
1,Calories,75.9,kcal
1,Protein,3.1,g

product_id,ingredient
1,[milk, sugar]

product_id,allergen
1,[milk, soy]
"""

    clean = clean_csv_raw_text(raw)
    print(clean)
    result = convert_label_csv_to_json(clean)
    print(result.model_dump())