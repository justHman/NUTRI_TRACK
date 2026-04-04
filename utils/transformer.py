import csv
import io
import json
import os
import re
import sys
import unicodedata
from typing import Dict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import get_logger

logger = get_logger(__name__)


def clean_csv_raw_text(raw_text: str) -> str:
    text = raw_text.strip()
    text = re.sub(r"```(?:csv)?\s*([\s\S]*?)```", r"\1", text, flags=re.IGNORECASE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s*,\s*", ",", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{2,}", "\n\n", text)
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

    query = unicodedata.normalize("NFKD", query)
    query = "".join([c for c in query if not unicodedata.combining(c)])

    match = re.match(r"^(.*?)\s*\(.*?\)", query)
    if match:
        prefix = match.group(1).strip()
        if len(prefix) >= 2:
            query = prefix
            logger.debug(
                "normalize_query: extracted prefix '%s' from '%s'", prefix, original
            )

    query = re.sub(r"[-_]", " ", query)
    query = re.sub(r"[()]", "", query)
    query = re.sub(r"[^\w\s]", "", query)
    query = re.sub(r"\s+", " ", query).strip()

    logger.debug("normalize_query: '%s' → '%s'", original, query)
    return query


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
        return 0.0


def parse_table_block(block_text, delimiter=None):
    """Parse a table block into list[dict] with configurable/auto delimiter."""
    lines = [ln for ln in block_text.splitlines() if ln.strip()]
    if not lines:
        return []

    header_line = lines[0]
    delim = delimiter if delimiter is not None else ("|" if "|" in header_line else ",")
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)

    parsed_rows = []
    for row in reader:
        normalized_row = {}
        for k, v in row.items():
            if k is None:
                continue
            # Normalize header/value to avoid KeyError from spaces or BOM in keys.
            nk = str(k).strip().lstrip("\ufeff")
            nv = v.strip() if isinstance(v, str) else v
            normalized_row[nk] = nv
        parsed_rows.append(normalized_row)
    return parsed_rows


def parse_list_field_with_nesting(field_str):
    """Extract list items, preserving commas inside paired (), [] or {}."""
    if not field_str:
        return []
    field_str = field_str.strip()
    if field_str.startswith("[") and field_str.endswith("]"):
        field_str = field_str[1:-1]

    items = []
    buf = []
    paren_depth = 0
    square_depth = 0
    curly_depth = 0

    for ch in field_str:
        if ch == "(":
            paren_depth += 1
        elif ch == ")" and paren_depth > 0:
            paren_depth -= 1
        elif ch == "[":
            square_depth += 1
        elif ch == "]" and square_depth > 0:
            square_depth -= 1
        elif ch == "{":
            curly_depth += 1
        elif ch == "}" and curly_depth > 0:
            curly_depth -= 1

        # Split only when comma is not nested in paired delimiters.
        if ch == "," and paren_depth == 0 and square_depth == 0 and curly_depth == 0:
            item = "".join(buf).strip()
            if item:
                items.append(item)
            buf = []
            continue

        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        items.append(tail)

    return items


def parse_key_value_section(section_text, value_parser=None):
    """Parse lines in format key|value with only first pipe as splitter."""
    parser = value_parser or (lambda x: x)
    result = {}
    lines = section_text.split("\n")

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("|", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            result[key] = parser(value)
    return result


def convert_food_csv_to_json(text):
    """
    Input: raw text chứa 2 bảng CSV (có thể dính nhau hoặc cách nhau bởi dòng trống)
    Output: JSON format cũ
    """
    text = (text or "").strip()

    if not text:
        return {"dishes": [], "image_quality": None}

    # Non-food / no-dish shortcut contract:
    # {
    #   "dishes": [],
    #   "image_quality": null
    # }
    if text.startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and isinstance(payload.get("dishes"), list):
                dishes = payload.get("dishes") or []
                if len(dishes) == 0:
                    logger.info("Detected non-food JSON payload with empty dishes")
                    return {"dishes": [], "image_quality": None}
                # Keep compatibility if upstream starts returning non-empty dishes as JSON.
                return {"dishes": dishes, "image_quality": payload.get("image_quality")}
        except json.JSONDecodeError:
            logger.debug(
                "Input starts with '{' but is not valid JSON, fallback to CSV parsing"
            )

    # Find the second table start. Both table headers start with dish_id
    # and can be either pipe-delimited or comma-delimited.
    matches = list(re.finditer(r"^dish_id[|,]", text, re.MULTILINE))

    if len(matches) < 2:
        # Fallback cho trường hợp format không chuẩn hoặc chỉ có 1 bảng
        parts = text.split("\n\n")
        if len(parts) < 2:
            raise ValueError("Không tìm thấy đủ 2 bảng CSV")
        dish_csv = parts[0]
        ingredient_csv = parts[1]
    else:
        # Bảng 2 bắt đầu tại matches[1].start()
        dish_csv = text[: matches[1].start()].strip()
        ingredient_csv = text[matches[1].start() :].strip()

    dishes_raw = parse_table_block(dish_csv)
    ingredients_raw = parse_table_block(ingredient_csv)

    # 🔹 Group ingredients theo dish_id
    ingredient_map = {}
    for ing in ingredients_raw:
        dish_id = (ing.get("dish_id") or "").strip()
        if not dish_id:
            logger.debug(
                "convert_food_csv_to_json: skip ingredient row without dish_id: %s", ing
            )
            continue
        ingredient_map.setdefault(dish_id, []).append(ing)

    dishes = []

    def parse_optional_int(value):
        """Parse optional integer values; return None for empty/non-numeric placeholders."""
        if value is None:
            return None
        s = str(value).strip()
        if not s or s == "-":
            return None
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return None

    # New prompt format may store this in header: scale_reference/image_quality
    # We expose only image_quality at top-level and keep per-dish scale_reference.
    image_quality = "unknown"

    for d in dishes_raw:
        dish_id = (d.get("dish_id") or "").strip()
        if not dish_id:
            logger.debug(
                "convert_food_csv_to_json: skip dish row without dish_id: %s", d
            )
            continue

        ingredients = []
        for ing in ingredient_map.get(dish_id, []):
            ingredients.append(
                {
                    "name": ing.get("name", ""),
                    "weight": normalize_number(ing.get("weight", 0)),
                    "nutritions": {
                        "calories": normalize_number(ing.get("calories", 0)),
                        "protein": normalize_number(ing.get("protein", 0)),
                        "carbs": normalize_number(ing.get("carbs", 0)),
                        "fat": normalize_number(ing.get("fat", 0)),
                    },
                    "confidence": safe_float(ing.get("confidence"), 0.9),
                }
            )

        dishes.append(
            {
                "name": d.get("name", ""),
                "serving_value": normalize_number(d.get("serving_value", 0)),
                "serving_unit": d.get("serving_unit", ""),
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
                "expiry_days": parse_optional_int(d.get("expiry_days")),
                "scale_reference": d.get("scale_reference", ""),
            }
        )

        # Backward/forward compatibility for merged column naming.
        merged_scale_quality = d.get("scale_reference/image_quality", "")
        if merged_scale_quality and image_quality == "unknown":
            image_quality = merged_scale_quality

        if d.get("image_quality") and image_quality == "unknown":
            image_quality = d.get("image_quality")

    return {"dishes": dishes, "image_quality": image_quality}


def convert_label_csv_to_json(text: str):
    """
    Convert multi-section CSV format to JSON.

    Input: raw text with 4 CSV sections separated by blank lines (pipe-delimited):
        1. Product info (product_id|name|brand|serving_value|serving_unit|confidence)
        2. Nutrition facts (product_id|nutrient|value|unit|dv_percentage)
        3. Ingredients (product_id|ingredients) - ingredients is comma-separated list "item1,item2,..."
        4. Allergens (product_id|allergens) - allergens is comma-separated list "item1,item2,..."

    Output: JSON with structure:
        {
            "labels": [
                {
                    "product_id": int,
                    "name": str,
                    "brand": str,
                    "serving_value": float,
                    "serving_unit": str,
                    "nutrition": [{"nutrient": str, "value": float, "unit": str, "dv_percentage": float}, ...],
                    "ingredients": [str, ...],
                    "allergens": [str, ...],
                    "expiry_days": Optional[int],
                    "confidence": float
                },
                "image_quality": str
            ]
        }
    """
    text = (text or "").strip()

    if not text:
        return {"labels": []}

    if text.startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and isinstance(payload.get("labels"), list):
                labels = payload.get("labels") or []
                image_quality = payload.get("image_quality")
                if len(labels) == 0:
                    logger.info("Detected non-label JSON payload with empty labels")
                    return {"labels": []}
                # If upstream returns non-empty labels as JSON, keep compatibility.
                return {"labels": labels, "image_quality": image_quality}
        except json.JSONDecodeError:
            logger.debug(
                "Input starts with '{' but is not valid JSON, fallback to CSV parsing"
            )

    # Split into sections by double newline
    sections = [s.strip() for s in text.split("\n\n") if s.strip()]

    if len(sections) < 1:
        logger.warning("No sections found in label CSV text, returning empty labels")
        return {"labels": []}

    # Parse each section (pipe-delimited)
    products_data = parse_table_block(sections[0], delimiter="|")
    nutrition_data = parse_table_block(sections[1], delimiter="|")

    logger.debug(
        f"Parsed {len(products_data)} products, {len(nutrition_data)} nutrition rows"
    )

    # Group nutrition by product_id
    nutrition_map = {}
    for row in nutrition_data:
        product_id = (row.get("product_id") or "").strip()
        if not product_id:
            continue
        nutrition_map.setdefault(product_id, []).append(row)

    # Group ingredients/allergens by product_id (optional sections)
    ingredients_map = (
        parse_key_value_section(sections[2], value_parser=parse_list_field_with_nesting)
        if len(sections) >= 3
        else {}
    )
    allergens_map = (
        parse_key_value_section(sections[3], value_parser=parse_list_field_with_nesting)
        if len(sections) >= 4
        else {}
    )

    # Build output
    labels = []
    for product in products_data:
        product_id = (
            (product.get("product_id") or "").strip()
            if isinstance(product.get("product_id"), str)
            else product.get("product_id")
        )
        if not product_id:
            continue

        # Build nutrition array
        nutrition = []
        for n in nutrition_map.get(product_id, []):
            nutrition.append(
                {
                    "nutrient": n.get("nutrient", ""),
                    "value": safe_float(n.get("value")),
                    "unit": n.get("unit", ""),
                    "dv_percentage": safe_float(n.get("dv_percentage")),
                }
            )

        label = {
            "product_id": int(product_id) if product_id.isdigit() else product_id,
            "name": product.get("name", ""),
            "brand": product.get("brand", ""),
            "serving_value": safe_float(product.get("serving_value")),
            "serving_unit": product.get("serving_unit", ""),
            "nutrition": nutrition,
            "ingredients": ingredients_map.get(product_id, []),
            "allergens": allergens_map.get(product_id, []),
            "expiry_days": int(product.get("expiry_days"))
            if str(product.get("expiry_days", "")).isdigit()
            else None,
            "confidence": safe_float(product.get("confidence")),
        }

        labels.append(label)

    logger.info(f"Successfully converted {len(labels)} labels to JSON")
    return {"labels": labels}


if __name__ == "__main__":
    raw = """
product_id|name|brand|serving_value|serving_unit|expiry_days|confidence|image_quality
1|||30|g||0.9|high

product_id|nutrient|value|unit|dv_percentage
1|Calories|150|kcal|0
1|Total Fat|7.0|g|9
1|Saturated Fat|3.0|g|15
1|Sodium|240|mg|10
1|Total Carbohydrate|20.0|g|7
1|Sugars|3.0|g|0
1|Protein|2.0|g|0
"""

    clean = clean_csv_raw_text(raw)
    print(clean)
    result = convert_label_csv_to_json(clean)
    print(result)
