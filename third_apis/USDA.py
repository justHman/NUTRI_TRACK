import requests
import re
from typing import Dict
import unicodedata

from config.logging_config import get_logger

logger = get_logger(__name__)


class USDAClient:
    """
    USDA FoodData Central API Client
    Production-ready version:
    - Query normalization
    - Response caching
    - Best-score food selection
    - Safe fallback
    """

    ENERGY_NUMBERS = {"208", "2047", "2048"}  # kcal only
    TARGET_NUTRIENTS = {
        "203": "protein",   # Protein
        "204": "fat",       # Total lipid (fat)
        "205": "carbs",     # Carbohydrate, by difference
    }

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.nal.usda.gov/fdc/v1"
        self.cache: Dict[str, Dict[str, float]] = {}
        logger.info("USDAClient initialized (api_key=%s)", "DEMO_KEY" if api_key == "DEMO_KEY" else "***")

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------
    def get_nutrition(self, query: str) -> Dict[str, float]:
        """
        Main entry point for nutrition lookup.
        Orchestrates: normalize → cache → search → parse → cache → return.
        """
        logger.debug("get_nutrition() called with query='%s'", query)
        normalized_query = self._normalize_query(query)

        # 1️⃣ Check cache first
        if normalized_query in self.cache:
            logger.info("Cache HIT for '%s'", normalized_query)
            return self.cache[normalized_query]

        logger.debug("Cache MISS for '%s'", normalized_query)

        # 2️⃣ Fetch data (API or Mock)
        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("Using mock nutrition data (api_key=%s)", self.api_key or "None")
            result = self._get_mock_nutrition(query)
        else:
            foods = self._search(normalized_query)
            if foods:
                result = self._parse_nutrients(foods)
            else:
                result = self._get_mock_nutrition(query)

        # 3️⃣ Save to cache
        self.cache[normalized_query] = result
        logger.debug("Cached result for '%s': %s", normalized_query, result)
        return result

    # --------------------------------------------------
    # Private: Search
    # --------------------------------------------------

    def _search(self, normalized_query: str) -> list | None:
        """
        Send a search request to the USDA FoodData Central API.

        Args:
            normalized_query: Already-normalized food name string.

        Returns:
            List of food dicts from the API response,
            or None if the request fails or returns no results.
        """
        search_url = f"{self.base_url}/foods/search"
        params = {
            "query": normalized_query,
            "pageSize": 5,
            "api_key": self.api_key,
        }

        try:
            logger.info("USDA API search: query='%s'", normalized_query)
            resp = requests.get(search_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("USDA API response: status=%d, totalHits=%s",
                         resp.status_code, data.get("totalHits", "N/A"))

            foods = data.get("foods", [])
            if not foods:
                logger.warning("USDA returned 0 results for '%s'", normalized_query)
                return None

            logger.info("USDA found %d result(s) for '%s'", len(foods), normalized_query)
            return foods

        except requests.exceptions.Timeout:
            logger.error("USDA API timeout for query='%s'", normalized_query)
        except requests.exceptions.HTTPError as e:
            logger.error("USDA API HTTP error: %s (query='%s')", e, normalized_query)
        except Exception as e:
            logger.error("USDA API unexpected error: %s (query='%s')", e, normalized_query, exc_info=True)

        return None

    # --------------------------------------------------
    # Private: Parse
    # --------------------------------------------------

    def _parse_nutrients(self, foods: list) -> Dict[str, float]:
        """
        Select the best-scored food from the USDA results list
        and extract calories, protein, fat, carbs per 100g.

        Args:
            foods: List of food dicts from USDA API response.

        Returns:
            Dict with keys: calories, protein, fat, carbs (all floats, per 100g).
        """
        best_food = max(foods, key=lambda x: x.get("score", 0))
        logger.info("Best match: '%s' (fdcId=%s, score=%.1f)",
                    best_food.get("description", "N/A"),
                    best_food.get("fdcId", "N/A"),
                    best_food.get("score", 0))

        result = {
            "calories": 0.0,
            "protein": 0.0,
            "fat": 0.0,
            "carbs": 0.0,
        }

        for n in best_food.get("foodNutrients", []):
            nutrient_number = str(n.get("nutrientNumber", "")).strip()
            unit  = str(n.get("unitName", "")).upper()
            value = n.get("value")

            if value is None:
                continue

            # Calories (kcal only)
            if nutrient_number in self.ENERGY_NUMBERS and unit == "KCAL":
                result["calories"] = float(value)

            # Protein / Fat / Carbs
            elif nutrient_number in self.TARGET_NUTRIENTS:
                result[self.TARGET_NUTRIENTS[nutrient_number]] = float(value)

        logger.debug("Parsed nutrients: %s", result)
        return result

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _normalize_query(self, query: str) -> str:
        """
        Robust multilingual normalize:
        - lowercase
        - strip
        - prioritize prefix before parentheses
        - if prefix too short (<2 chars), keep full string
        - replace hyphens/underscores with spaces
        - remove punctuation
        - remove accents (Vietnamese, French, German)
        - collapse multiple spaces
        """

        if not query:
            logger.debug("_normalize_query: empty input, returning ''")
            return ""

        original = query
        query = query.strip().lower()

        # Remove accents (normalize unicode)
        query = unicodedata.normalize('NFKD', query)
        query = ''.join([c for c in query if not unicodedata.combining(c)])

        # Extract prefix before parentheses
        match = re.match(r"^(.*?)\s*\(.*?\)", query)
        if match:
            prefix = match.group(1).strip()
            if len(prefix) >= 2:
                query = prefix
                logger.debug("_normalize_query: extracted prefix '%s' from '%s'", prefix, original)

        # Replace hyphens and underscores with space BEFORE punctuation removal
        query = re.sub(r"[-_]", " ", query)

        # Remove any remaining parentheses
        query = re.sub(r"[()]", "", query)

        # Remove punctuation (keep letters & numbers & spaces)
        query = re.sub(r"[^\w\s]", "", query)

        # Collapse multiple spaces
        query = re.sub(r"\s+", " ", query).strip()

        logger.debug("_normalize_query: '%s' → '%s'", original, query)
        return query

    def _get_mock_nutrition(self, query: str) -> Dict[str, float]:
        """
        Simple mock fallback (safe default values)
        """
        logger.warning("Using MOCK nutrition for query='%s'", query)
        return {
            "calories": 100.0,
            "protein": 5.0,
            "fat": 3.0,
            "carbs": 15.0,
        }
