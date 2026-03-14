import os
import json
import time
import requests
import re
from collections import OrderedDict
from typing import Dict, List, Optional

import unicodedata

from config.logging_config import get_logger
from utils.caculator import calculate_ingredient_nutrition

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Disk Cache Path  (Level 2 — Persistent)
# Lives at:  app/data/openfoodfacts_cache.json
# Swap to S3/DynamoDB later by replacing _load_disk_cache / _save_disk_cache.
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_DIR  = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "openfoodfacts_cache.json")
_CACHE_TTL_DAYS = 30        # Re-fetch after this many days
_L1_MAXSIZE     = 256       # RAM LRU max entries


class _LRUCache:
    """Thread-safe LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 256):
        self._cache: OrderedDict[str, object] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str):
        if key not in self._cache:
            return _MISSING
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key: str, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
                logger.debug("L1 cache evicted LRU entry: '%s'", oldest)
        self._cache[key] = value

    def clear(self):
        self._cache.clear()

    def __contains__(self, key: str):
        return key in self._cache

    def __len__(self):
        return len(self._cache)


_MISSING = object()  # Sentinel — distinguishes "key absent" from "value is None"

# Module-level L1 cache (shared across all OpenFoodFactsClient instances in one process)
_l1: _LRUCache = _LRUCache(maxsize=_L1_MAXSIZE)


def _now_ts() -> float:
    return time.time()


def _is_expired(entry: dict) -> bool:
    ts = entry.get("_ts", 0)
    return (_now_ts() - ts) > (_CACHE_TTL_DAYS * 86400)


def _load_disk_cache() -> dict:
    """Load Level-2 disk cache from JSON file, with optional S3 syncing."""
    s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
    if s3_bucket:
        try:
            import boto3

            s3_key = "openfoodfacts_cache.json"
            logger.info("Syncing L2 cache from S3: s3://%s/%s", s3_bucket, s3_key)
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            s3 = boto3.client('s3', region_name=region)

            os.makedirs(_CACHE_DIR, exist_ok=True)
            s3.download_file(s3_bucket, s3_key, _CACHE_FILE)
            logger.debug("Successfully downloaded cache from S3 to %s", _CACHE_FILE)
        except Exception as e:
            if hasattr(e, 'response') and getattr(e, 'response', {}).get('Error', {}).get('Code') in ('404', 'NoSuchKey'):
                logger.info("No cache found on S3, starting fresh or using existing local file")
            else:
                logger.warning("Failed to download cache from S3: %s", e)

    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("L2 cache loaded: %d entries from %s", len(data), _CACHE_FILE)
        return data
    except Exception as e:
        logger.warning("L2 cache load failed (%s), starting fresh", e)
        return {}


def _save_disk_cache(cache: dict):
    """Persist Level-2 disk cache to JSON file and sync to S3 if configured."""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.debug("L2 cache saved: %d entries to %s", len(cache), _CACHE_FILE)

        s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
        if s3_bucket:
            import boto3
            s3_key = "openfoodfacts_cache.json"
            logger.info("Uploading L2 cache to S3: s3://%s/%s", s3_bucket, s3_key)
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            s3 = boto3.client('s3', region_name=region)
            s3.upload_file(_CACHE_FILE, s3_bucket, s3_key)
            logger.debug("Successfully uploaded cache to S3")

    except Exception as e:
        logger.warning("L2 cache save/sync failed: %s", e)


# Load once at module import
_l2: dict = _load_disk_cache()


class OpenFoodFactsClient:
    """
    Open Food Facts API Client — Two-Tier Cache Edition
    ────────────────────────────────────────────────────
    Cache hierarchy (fast → slow):

    ┌──────────────────────────────────────────────────────────────┐
    │ Level 1 │ RAM LRU  │ maxsize=256  │ per-process lifetime    │
    ├──────────────────────────────────────────────────────────────┤
    │ Level 2 │ JSON file│ TTL=30 days  │ persists across runs    │
    ├──────────────────────────────────────────────────────────────┤
    │ Level 3 │ API call │ real network │ only on full miss       │
    └──────────────────────────────────────────────────────────────┘

    API docs: https://wiki.openfoodfacts.org/API
    Base URL: https://world.openfoodfacts.org
    Auth: No API key required (open data). User-Agent header recommended.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key  # Not required, kept for interface consistency
        self.base_url = "https://world.openfoodfacts.org"
        self.user_agent = "NutriTrack/2.0 (nutritrack@example.com)"
        logger.info("OpenFoodFactsClient initialized (no API key required)")
        logger.debug("L1 cache size: %d / %d   |   L2 disk entries: %d",
                     len(_l1), _L1_MAXSIZE, len(_l2))

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def get_nutritions(self, query: str, pageSize: int = 5) -> Dict[str, float]:
        """
        Return Protein/Calories/Fat/Carbs nutrition data per 100g.
        Uses two-tier cache before calling Open Food Facts API.
        Falls back to mock values if no result found.
        """
        logger.debug("get_nutritions() called with query='%s'", query)
        normalized_query = self._normalize_query(query)

        best = self.search_best(normalized_query, pageSize)
        if best:
            return self._parse_100g_nutritions(best)

        logger.warning("get_nutritions: no result for '%s', falling back to mock", normalized_query)
        return self._get_mock_nutrition(query)

    def get_ingredients(self, query: str, pageSize: int = 5) -> Optional[List[str]]:
        """
        Return ingredient list for a food item.
        Uses two-tier cache before calling Open Food Facts API.
        """
        logger.debug("get_ingredients() called with query='%s'", query)
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            logger.warning("get_ingredients: empty query")
            return None

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning("get_ingredients: no Open Food Facts result for '%s'", normalized_query)
            return None

        ingredients = self._parse_ingredient_string(best)
        logger.info("get_ingredients: %d ingredients for '%s'",
                    len(ingredients) if ingredients else 0, normalized_query)
        return ingredients

    def get_nutritions_and_ingredients(self, query: str, pageSize: int = 5) -> Optional[Dict]:
        """
        Return both PCF nutrition data and ingredients in one dict.
        Calls search_best() once — cache ensures only 1 API call per unique query.
        """
        logger.debug("get_nutritions_and_ingredients() called with query='%s'", query)
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            logger.warning("get_nutritions_and_ingredients: empty query")
            return None

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning("get_nutritions_and_ingredients: no Open Food Facts result for '%s'", normalized_query)
            return None

        description = best.get("product_name", "N/A").lower()
        nutritions  = self._parse_100g_nutritions(best)
        ingredients = self._parse_ingredient_string(best)

        result = {
            "description": description,
            "nutritions": nutritions,
            "ingredients": ingredients,
        }
        logger.info("get_nutritions_and_ingredients: '%s' → %d ingredients",
                    normalized_query, len(ingredients) if ingredients else 0)
        logger.debug("get_nutritions_and_ingredients result: %s", result)
        return result

    def get_nutritions_and_ingredients_by_weight(self, query: str, weight_g: float, pageSize: int = 5) -> Optional[Dict]:
        """
        Return actual PCF nutrition data calculated by weight and ingredients in one dict.
        Calls get_nutritions_and_ingredients to get 100g reference and calculates actual nutritions.
        """
        logger.debug("get_nutritions_and_ingredients_by_weight() called with query='%s', weight_g=%.2f", query, weight_g)

        result = self.get_nutritions_and_ingredients(query, pageSize)
        if not result:
            return None

        nutritions_100g = result["nutritions"]
        actual_nutritions = calculate_ingredient_nutrition(nutritions_100g, weight_g)

        result["nutritions"] = actual_nutritions
        result["weight_g"] = weight_g

        logger.debug("get_nutritions_and_ingredients_by_weight actual result: %s", result)
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Cache-aware search  (two-tier lookup happens here)
    # ─────────────────────────────────────────────────────────────────────

    def search_best(self, normalized_query: str, pageSize: int = 5) -> Optional[dict]:
        """
        Return the best-matching product for a query.

        Cache lookup order:
          1. L1 RAM (LRU dict, 256 entries max)              — fastest
          2. L2 Disk (JSON file, 30-day TTL)                 — across restarts
          3. Open Food Facts API                              — real network call
             → result saved to both L1 + L2 on success
        """
        # ── Level 1: RAM LRU ──────────────────────────────────────────────
        l1_hit = _l1.get(normalized_query)
        if l1_hit is not _MISSING:
            logger.info("search_best: L1 HIT (RAM) for '%s' → '%s'",
                        normalized_query,
                        l1_hit.get("product_name", "None") if l1_hit else "None")
            logger.info("search_best: Cache HIT for '%s' → '%s'",
                        normalized_query,
                        l1_hit.get("product_name", "None") if l1_hit else "None")
            return l1_hit

        # ── Level 2: Disk JSON ────────────────────────────────────────────
        if normalized_query in _l2:
            entry = _l2[normalized_query]
            if not _is_expired(entry):
                food = entry.get("food")
                logger.info("search_best: L2 HIT (disk) for '%s' → '%s'",
                            normalized_query,
                            food.get("product_name", "None") if food else "None")
                logger.info("search_best: Cache HIT for '%s' → '%s'",
                            normalized_query,
                            food.get("product_name", "None") if food else "None")
                _l1.set(normalized_query, food)
                return food
            else:
                logger.info("search_best: L2 EXPIRED for '%s' (age > %d days)",
                            normalized_query, _CACHE_TTL_DAYS)

        # ── Level 3: Open Food Facts API ──────────────────────────────────
        logger.debug("search_best: Cache MISS for '%s' → calling Open Food Facts API", normalized_query)
        products = self.search(normalized_query, pageSize)

        if not products:
            _l1.set(normalized_query, None)
            _l2[normalized_query] = {"food": None, "_ts": _now_ts()}
            _save_disk_cache(_l2)
            return None

        # Pick the first product (best match from Open Food Facts)
        best_food = products[0]
        logger.debug("search_best: best='%s'",
                     best_food.get("product_name", "N/A"))

        _l1.set(normalized_query, best_food)
        _l2[normalized_query] = {"food": best_food, "_ts": _now_ts()}
        _save_disk_cache(_l2)

        return best_food

    # ─────────────────────────────────────────────────────────────────────
    # Cache utilities
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def clear_l1_cache():
        """Clear Level-1 (RAM) cache only."""
        _l1.clear()
        logger.info("L1 RAM cache cleared")

    @staticmethod
    def clear_all_caches():
        """Clear both L1 (RAM) and L2 (disk) caches."""
        _l1.clear()
        _l2.clear()
        _save_disk_cache(_l2)
        logger.info("All caches cleared (L1 + L2)")

    @staticmethod
    def cache_stats() -> dict:
        """Return current cache statistics."""
        expired = sum(1 for e in _l2.values() if _is_expired(e))
        return {
            "l1_entries": len(_l1),
            "l1_maxsize": _L1_MAXSIZE,
            "l2_entries": len(_l2),
            "l2_expired": expired,
            "l2_file": _CACHE_FILE,
            "ttl_days": _CACHE_TTL_DAYS,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Open Food Facts network search
    # ─────────────────────────────────────────────────────────────────────

    def search(self, normalized_query: str, pageSize: int = 5) -> Optional[list]:
        """
        Send a search request to Open Food Facts API.
        This is the ONLY function that makes real HTTP requests for text search.

        Open Food Facts search response structure:
        {
          "count": 1234,
          "page": 1,
          "page_size": 5,
          "products": [
            {
              "product_name": "Nutella",
              "ingredients_text": "Sugar, palm oil, ...",
              "nutriments": {
                "energy-kcal_100g": 539,
                "proteins_100g": 6.3,
                "fat_100g": 30.9,
                "carbohydrates_100g": 57.5
              },
              ...
            }
          ]
        }
        """
        search_url = f"{self.base_url}/cgi/search.pl"
        params = {
            "search_terms": normalized_query,
            "search_simple": 1,
            "json": 1,
            "page_size": pageSize,
            "page": 1,
        }
        headers = {
            "User-Agent": self.user_agent,
        }

        try:
            logger.info("Open Food Facts API search: query='%s'", normalized_query)
            resp = requests.get(search_url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("Open Food Facts API: status=%d, count=%s",
                         resp.status_code, data.get("count", "N/A"))

            products = data.get("products", [])
            if not products:
                logger.warning("Open Food Facts returned 0 results for '%s'", normalized_query)
                return None

            logger.info("Open Food Facts found %d result(s) for '%s'", len(products), normalized_query)
            return products

        except requests.exceptions.Timeout:
            logger.error("Open Food Facts API timeout for query='%s'", normalized_query)
        except requests.exceptions.HTTPError as e:
            logger.error("Open Food Facts API HTTP error: %s (query='%s')", e, normalized_query)
        except Exception as e:
            logger.error("Open Food Facts API unexpected error: %s (query='%s')", e, normalized_query, exc_info=True)

        return None

    def search_by_barcode(self, code: str) -> Optional[Dict]:
        """
        Search Open Food Facts by barcode and return raw JSON response.

        Args:
            code: Barcode string decoded from image (e.g. "3017620422003").

        Returns:
            Raw JSON dict from Open Food Facts API, or None on error/invalid input.
        """
        barcode = re.sub(r"\D", "", str(code or "")).strip()
        if not barcode:
            logger.warning("search_by_barcode: invalid or empty barcode input='%s'", code)
            return None

        search_url = f"{self.base_url}/api/v2/product/{barcode}"
        headers = {
            "User-Agent": self.user_agent,
        }

        try:
            logger.info("Open Food Facts API barcode search: code='%s'", barcode)
            resp = requests.get(search_url, headers=headers, timeout=10)
            logger.debug("Open Food Facts barcode API raw response: status=%d, content=%s",
                         resp.status_code, resp.text)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("Open Food Facts barcode API: status=%d, product_status=%s",
                         resp.status_code, data.get("status", "N/A"))
            return data
        except requests.exceptions.Timeout:
            logger.error("Open Food Facts barcode API timeout for code='%s'", barcode)
        except requests.exceptions.HTTPError as e:
            logger.error("Open Food Facts barcode API HTTP error: %s (code='%s')", e, barcode)
        except Exception as e:
            logger.error("Open Food Facts barcode API unexpected error: %s (code='%s')", e, barcode, exc_info=True)

        return None

    # ─────────────────────────────────────────────────────────────────────
    # Private: Parse
    # ─────────────────────────────────────────────────────────────────────

    def _parse_100g_nutritions(self, food: dict) -> Dict[str, float]:
        """
        Extract calories, protein, fat, carbs per 100g from an Open Food Facts product dict.

        Open Food Facts stores nutriments under:
        food["nutriments"] = {
            "energy-kcal_100g": 539,
            "proteins_100g": 6.3,
            "fat_100g": 30.9,
            "carbohydrates_100g": 57.5,
            ...
        }
        """
        name = food.get("product_name", "N/A")
        logger.info("_parse_100g_nutritions: '%s'", name)

        nutriments = food.get("nutriments", {})

        result = {
            "calories": float(nutriments.get("energy-kcal_100g", 0) or 0),
            "protein":  float(nutriments.get("proteins_100g", 0) or 0),
            "fat":      float(nutriments.get("fat_100g", 0) or 0),
            "carbs":    float(nutriments.get("carbohydrates_100g", 0) or 0),
        }

        logger.debug("_parse_100g_nutritions result: %s", result)
        return result

    def _parse_ingredient_string(self, food: dict) -> Optional[List[str]]:
        """
        Parse Open Food Facts ingredients_text into a clean list.

        Handles nested parentheses by splitting only on top-level commas.
        Example:
            "MILK CHOCOLATE (SUGAR, COCOA BUTTER), PEANUTS, SALT"
            → ["milk chocolate", "peanuts", "salt"]
        """
        raw_ingredients = food.get("ingredients_text", "") or ""
        if not raw_ingredients:
            logger.info("_parse_ingredient_string: no 'ingredients_text' for '%s'",
                        food.get("product_name", "N/A"))
            return None

        tokens = []
        depth = 0
        current = []

        for char in raw_ingredients:
            if char == "(":
                depth += 1
                current.append(char)
            elif char == ")":
                depth -= 1
                current.append(char)
            elif char == "," and depth == 0:
                token = "".join(current).strip()
                if token:
                    tokens.append(token)
                current = []
            else:
                current.append(char)

        token = "".join(current).strip()
        if token:
            tokens.append(token)

        cleaned = []
        for tok in tokens:
            name = re.sub(r"\s*\(.*", "", tok).strip().lower()
            if name:
                cleaned.append(name)

        return cleaned

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _normalize_query(self, query: str) -> str:
        """
        Robust multilingual normalize:
        - lowercase, strip
        - remove accents (Vietnamese, French, German, etc.)
        - extract prefix before parentheses (if ≥2 chars)
        - replace hyphens/underscores with spaces
        - remove punctuation
        - collapse multiple spaces
        """
        if not query:
            logger.debug("_normalize_query: empty input, returning ''")
            return ""

        original = query
        query = str(query).strip().lower()

        query = unicodedata.normalize('NFKD', query)
        query = ''.join([c for c in query if not unicodedata.combining(c)])

        match = re.match(r"^(.*?)\s*\(.*?\)", query)
        if match:
            prefix = match.group(1).strip()
            if len(prefix) >= 2:
                query = prefix
                logger.debug("_normalize_query: extracted prefix '%s' from '%s'", prefix, original)

        query = re.sub(r"[-_]", " ", query)
        query = re.sub(r"[()]", "", query)
        query = re.sub(r"[^\w\s]", "", query)
        query = re.sub(r"\s+", " ", query).strip()

        logger.debug("_normalize_query: '%s' → '%s'", original, query)
        return query

    def _get_mock_nutrition(self, query: str) -> Dict[str, float]:
        """Safe mock fallback when no API key or no result."""
        logger.warning("Using MOCK nutrition for query='%s'", query)
        return {
            "calories": 100.0,
            "protein": 5.0,
            "fat": 3.0,
            "carbs": 15.0,
        }
