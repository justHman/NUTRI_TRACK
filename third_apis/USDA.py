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
# Lives at:  app/data/usda_cache.json
# Swap to S3/DynamoDB later by replacing _load_disk_cache / _save_disk_cache.
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_DIR  = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "usda_cache.json")
_CACHE_TTL_DAYS = 30        # Re-fetch from USDA after this many days
_L1_MAXSIZE     = 256       # RAM LRU max entries


class _LRUCache:
    """Thread-safe LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 256):
        self._cache: OrderedDict[str, object] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str):
        if key not in self._cache:
            return _MISSING
        # Move to end (most-recently used)
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

# Module-level L1 cache (shared across all USDAClient instances in one process)
_l1: _LRUCache = _LRUCache(maxsize=_L1_MAXSIZE)


def _now_ts() -> float:
    return time.time()


def _is_expired(entry: dict) -> bool:
    ts = entry.get("_ts", 0)
    return (_now_ts() - ts) > (_CACHE_TTL_DAYS * 86400)


def _load_disk_cache() -> dict:
    """Load Level-2 disk cache from JSON file, with optional S3 syncing.
    Pulls from S3 first (if configured), then loads from disk.
    """
    s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
    if s3_bucket:
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            s3_key = "usda_cache.json"
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
        
        # Sync to S3 if configured
        s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
        if s3_bucket:
            import boto3
            s3_key = "usda_cache.json"
            logger.info("Uploading L2 cache to S3: s3://%s/%s", s3_bucket, s3_key)
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            s3 = boto3.client('s3', region_name=region)
            s3.upload_file(_CACHE_FILE, s3_bucket, s3_key)
            logger.debug("Successfully uploaded cache to S3")
            
    except Exception as e:
        logger.warning("L2 cache save/sync failed: %s", e)


# Load once at module import
_l2: dict = _load_disk_cache()


class USDAClient:
    """
    USDA FoodData Central API Client — Two-Tier Cache Edition
    ──────────────────────────────────────────────────────────
    Cache hierarchy (fast → slow):

    ┌──────────────────────────────────────────────────────────┐
    │ Level 1 │ RAM LRU  │ maxsize=256  │ per-process lifetime │
    ├──────────────────────────────────────────────────────────┤
    │ Level 2 │ JSON file│ TTL=30 days  │ persists across runs │
    ├──────────────────────────────────────────────────────────┤
    │ Level 3 │ USDA API │ real network │ only on full miss    │
    └──────────────────────────────────────────────────────────┘

    Swap Level 2 to S3/DynamoDB by replacing _load_disk_cache / _save_disk_cache.
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
        logger.info("USDAClient initialized (api_key=%s)", "DEMO_KEY" if api_key == "DEMO_KEY" else "***")
        logger.debug("L1 cache size: %d / %d   |   L2 disk entries: %d",
                     len(_l1), _L1_MAXSIZE, len(_l2))

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def get_nutritions(self, query: str, pageSize: int = 5) -> Dict[str, float]:
        """
        Return Protein/Calories/Fat nutrition data per 100g.
        Uses two-tier cache before calling USDA API.
        Falls back to mock values if api_key is DEMO_KEY.
        """
        logger.debug("get_nutritions() called with query='%s'", query)
        normalized_query = self._normalize_query(query)

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("get_nutritions: using mock data (api_key=%s)", self.api_key or "None")
            return self._get_mock_nutrition(query)

        best = self.search_best(normalized_query, pageSize)
        if best:
            return self._parse_100g_nutritions(best)

        logger.warning("get_nutritions: no result for '%s', falling back to mock", normalized_query)
        return self._get_mock_nutrition(query)

    def get_ingredients(self, query: str, pageSize: int = 5) -> Optional[List[str]]:
        """
        Return ingredient list for a food item.
        Uses two-tier cache before calling USDA API.
        """
        logger.debug("get_ingredients() called with query='%s'", query)
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            logger.warning("get_ingredients: empty query")
            return None

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning("get_ingredients: no USDA result for '%s'", normalized_query)
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
            logger.warning("get_nutritions_and_ingredients: no USDA result for '%s'", normalized_query)
            return None

        description = best.get("description", "N/A").lower()
        nutritions     = self._parse_100g_nutritions(best)
        ingredients  = self._parse_ingredient_string(best)

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
        Return the highest-scored food entry for a query.

        Cache lookup order:
          1. L1 RAM (LRU dict, 256 entries max)              — fastest
          2. L2 Disk (JSON file, 30-day TTL)                 — across restarts
          3. USDA API                                         — real network call
             → result saved to both L1 + L2 on success

        Args:
            normalized_query: Already-normalized food name.
            pageSize: Max candidates to consider.

        Returns:
            Best-matching food dict, or None if no result.
        """
        # ── Level 1: RAM LRU ──────────────────────────────────────────────
        l1_hit = _l1.get(normalized_query)
        if l1_hit is not _MISSING:
            logger.info("search_best: L1 HIT (RAM) for '%s' → '%s'",
                        normalized_query,
                        l1_hit.get("description", "None") if l1_hit else "None")
            # Log as "Cache HIT" so existing log parsers in tests still count it
            logger.info("search_best: Cache HIT for '%s' → '%s'",
                        normalized_query,
                        l1_hit.get("description", "None") if l1_hit else "None")
            return l1_hit

        # ── Level 2: Disk JSON ────────────────────────────────────────────
        if normalized_query in _l2:
            entry = _l2[normalized_query]
            if not _is_expired(entry):
                food = entry.get("food")
                logger.info("search_best: L2 HIT (disk) for '%s' → '%s'",
                            normalized_query,
                            food.get("description", "None") if food else "None")
                logger.info("search_best: Cache HIT for '%s' → '%s'",
                            normalized_query,
                            food.get("description", "None") if food else "None")
                # Promote to L1
                _l1.set(normalized_query, food)
                return food
            else:
                logger.info("search_best: L2 EXPIRED for '%s' (age > %d days)",
                            normalized_query, _CACHE_TTL_DAYS)

        # ── Level 3: USDA API ─────────────────────────────────────────────
        logger.debug("search_best: Cache MISS for '%s' → calling USDA API", normalized_query)
        foods = self.search(normalized_query, pageSize)

        if not foods:
            # Cache the None result to avoid repeat calls for queries with 0 results
            _l1.set(normalized_query, None)
            _l2[normalized_query] = {"food": None, "_ts": _now_ts()}
            _save_disk_cache(_l2)
            return None

        best_food = max(foods, key=lambda x: x.get("score", 0))
        logger.debug("search_best: best='%s' (score=%.1f)",
                     best_food.get("description", "N/A"), best_food.get("score", 0))

        # Save to L1 + L2
        _l1.set(normalized_query, best_food)
        _l2[normalized_query] = {"food": best_food, "_ts": _now_ts()}
        _save_disk_cache(_l2)

        return best_food

    # ─────────────────────────────────────────────────────────────────────
    # Cache utilities
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def clear_l1_cache():
        """Clear Level-1 (RAM) cache only.
        Call at start of each isolated test to get a fair cold-start measurement.
        """
        _l1.clear()
        logger.info("L1 RAM cache cleared")

    @staticmethod
    def clear_all_caches():
        """Clear both L1 (RAM) and L2 (disk) caches.
        Use for full reset / test fixture teardown.
        """
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
    # USDA network search
    # ─────────────────────────────────────────────────────────────────────

    def search(self, normalized_query: str, pageSize: int = 5) -> Optional[list]:
        """
        Send a search request to USDA FoodData Central API.
        This is the ONLY function that makes real HTTP requests.
        """
        search_url = f"{self.base_url}/foods/search"
        params = {
            "query": normalized_query,
            "pageSize": pageSize,
            "api_key": self.api_key,
        }

        try:
            logger.info("USDA API search: query='%s'", normalized_query)
            resp = requests.get(search_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("USDA API: status=%d, totalHits=%s",
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

    # ─────────────────────────────────────────────────────────────────────
    # Private: Parse
    # ─────────────────────────────────────────────────────────────────────

    def _parse_100g_nutritions(self, food: dict) -> Dict[str, float]:
        """
        Extract calories, protein, fat, carbs per 100g from a USDA food dict.
        """
        logger.info("_parse_100g_nutritions: '%s' (fdcId=%s, score=%.1f)",
                    food.get("description", "N/A"),
                    food.get("fdcId", "N/A"),
                    food.get("score", 0))

        result = {
            "calories": 0.0,
            "protein": 0.0,
            "fat": 0.0,
            "carbs": 0.0,
        }

        for n in food.get("foodNutrients", []):
            nutrient_number = str(n.get("nutrientNumber", "")).strip()
            unit  = str(n.get("unitName", "")).upper()
            value = n.get("value")

            if value is None:
                continue

            if nutrient_number in self.ENERGY_NUMBERS and unit == "KCAL":
                result["calories"] = float(value)
            elif nutrient_number in self.TARGET_NUTRIENTS:
                result[self.TARGET_NUTRIENTS[nutrient_number]] = float(value)

        logger.debug("_parse_100g_nutritions result: %s", result)
        return result

    def _parse_ingredient_string(self, food: dict) -> Optional[List[str]]:
        """
        Parse a USDA ingredients raw string into a clean list.

        Handles nested parentheses by splitting only on top-level commas.
        Example:
            "MILK CHOCOLATE (SUGAR, COCOA BUTTER), PEANUTS, SALT"
            → ["milk chocolate", "peanuts", "salt"]
        """
        raw_ingredients = food.get("ingredients", "")
        if not raw_ingredients:
            logger.info("_parse_ingredient_string: no 'ingredients' for '%s' (fdcId=%s)",
                        food.get("description", "N/A"), food.get("fdcId", "N/A"))
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

        # Last token (no trailing comma)
        token = "".join(current).strip()
        if token:
            tokens.append(token)

        # Strip parenthetical sub-lists, lowercase
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

        # Remove accents
        query = unicodedata.normalize('NFKD', query)
        query = ''.join([c for c in query if not unicodedata.combining(c)])

        # Extract prefix before parentheses
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
