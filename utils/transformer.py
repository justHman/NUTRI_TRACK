import re
import unicodedata
from typing import Dict, List, Any
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import get_logger

logger = get_logger(__name__)

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

if __name__ == "__main__":
    batch = [
        ["apple", 52.0, 0.26, 13.84, 0.17, ["apple", "banana"], 100], 
        ["banana", 89.0, 1.09, 22.84, 0.33, ["banana"], 100]
    ]
    print(batch_to_csv(batch))