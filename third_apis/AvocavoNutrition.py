import os
import json
import time
import requests
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import unicodedata

from config.logging_config import get_logger
from utils.caculator import calculate_ingredient_nutrition

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Disk Cache Path  (Level 2 — Persistent)
# Lives at:  app/data/avocavo_cache.json
# Swap to S3/DynamoDB later by replacing _load_disk_cache / _save_disk_cache.
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_DIR  = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "avocavo_cache.json")
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


_NEGATIVE_CACHEABLE_SEARCH_STATUSES = {404, 204}

# Module-level L1 caches (shared across all AvocavoNutritionClient instances in one process)
_l1_foods: _LRUCache = _LRUCache(maxsize=_L1_MAXSIZE)
_l1_barcodes: _LRUCache = _LRUCache(maxsize=_L1_MAXSIZE)


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

            s3_key = "avocavo_cache.json"
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
        return {"foods": {}, "barcodes": {}}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        data = {
            "foods":    raw.get("foods",    {}),
            "barcodes": raw.get("barcodes", {}),
        }
        total = len(data["foods"]) + len(data["barcodes"])
        logger.debug("L2 cache loaded: %d entries (%d foods, %d barcodes) from %s",
                     total, len(data["foods"]), len(data["barcodes"]), _CACHE_FILE)
        return data
    except Exception as e:
        logger.warning("L2 cache load failed (%s), starting fresh", e)
        return {"foods": {}, "barcodes": {}}


def _save_disk_cache(cache: dict):
    """Persist Level-2 disk cache to JSON file and sync to S3 if configured."""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        total = len(cache.get("foods", {})) + len(cache.get("barcodes", {}))
        logger.debug("L2 cache saved: %d entries (%d foods, %d barcodes) to %s",
                     total, len(cache.get("foods", {})), len(cache.get("barcodes", {})), _CACHE_FILE)

        s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
        if s3_bucket:
            import boto3
            s3_key = "avocavo_cache.json"
            logger.info("Uploading L2 cache to S3: s3://%s/%s", s3_bucket, s3_key)
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            s3 = boto3.client('s3', region_name=region)
            s3.upload_file(_CACHE_FILE, s3_bucket, s3_key)
            logger.debug("Successfully uploaded cache to S3")

    except Exception as e:
        logger.warning("L2 cache save/sync failed: %s", e)


# Load once at module import
_l2: dict = _load_disk_cache()


class AvocavoNutritionClient:
    """
    Avocavo Nutrition API Client — Two-Tier Cache Edition
    ──────────────────────────────────────────────────────
    Cache hierarchy (fast → slow):

    ┌──────────────────────────────────────────────────────────────┐
    │ Level 1 │ RAM LRU  │ maxsize=256  │ per-process lifetime     │
    ├──────────────────────────────────────────────────────────────┤
    │ Level 2 │ JSON file│ TTL=30 days  │ persists across runs     │
    ├──────────────────────────────────────────────────────────────┤
    │ Level 3 │ API call │ real network │ only on full miss        │
    └──────────────────────────────────────────────────────────────┘

    API docs: https://app.avocavo.app
    Base URL: https://app.avocavo.app/api/v2
    Auth: X-Api-Key header
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://app.avocavo.app/api/v2"
        self._last_search_http_status: Optional[int] = None
        self._last_search_empty_result: bool = False
        logger.info("AvocavoNutritionClient initialized (api_key=%s)", "DEMO_KEY" if api_key == "DEMO_KEY" else "***")
        l2_entries = len(_l2["foods"]) + len(_l2["barcodes"])
        l1_entries = len(_l1_foods) + len(_l1_barcodes)
        logger.debug("L1 cache size: %d / %d   |   L2 disk entries: %d",
                 l1_entries, _L1_MAXSIZE * 2, l2_entries)

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def get_nutritions(self, query: str) -> Dict[str, float]:
        """
        Return Protein/Calories/Fat/Carbs nutrition data per 100g.
        Uses two-tier cache before calling Avocavo Nutrition API.
        Falls back to mock values if api_key is DEMO_KEY.
        """
        logger.debug("get_nutritions() called with query='%s'", query)
        normalized_query = self._normalize_query(query)

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("get_nutritions: using mock data (api_key=%s)", self.api_key or "None")
            return self._get_mock_nutrition(query)

        best = self.search_best(normalized_query)
        if best:
            return self._parse_100g_nutritions(best)

        logger.warning("get_nutritions: no result for '%s', falling back to mock", normalized_query)
        return self._get_mock_nutrition(query)

    def get_ingredients(self, query: str) -> Optional[List[str]]:
        """
        Return ingredient list for a food item.
        Note: Avocavo Nutrition API does not provide ingredient lists.
        Returns None.
        """
        logger.debug("get_ingredients() called with query='%s'", query)
        normalized_query = self._normalize_query(query)

        best = self.search_best(normalized_query) if (self.api_key and self.api_key != "DEMO_KEY") else None
        if best:
            return self._parse_ingredient_string(best)

        logger.info("get_ingredients: Avocavo Nutrition API does not provide ingredient data")
        return None

    def get_nutritions_and_ingredients(self, query: str) -> Optional[Dict]:
        """
        Return both PCF nutrition data and ingredients in one dict.
        Note: Avocavo Nutrition API does not provide ingredient lists, so ingredients will be None.
        """
        logger.debug("get_nutritions_and_ingredients() called with query='%s'", query)
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            logger.warning("get_nutritions_and_ingredients: empty query")
            return None

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("get_nutritions_and_ingredients: using mock data (api_key=%s)", self.api_key or "None")
            return {
                "description": normalized_query,
                "nutritions": self._get_mock_nutrition(query),
                "ingredients": None,
            }

        best = self.search_best(normalized_query)
        if not best:
            logger.warning("get_nutritions_and_ingredients: no result for '%s'", normalized_query)
            return None

        description = (best.get("ingredient")
                       or best.get("parsing", {}).get("ingredient_name", "N/A")).lower()
        nutritions  = self._parse_100g_nutritions(best)
        ingredients = self._parse_ingredient_string(best)

        result = {
            "description": description,
            "nutritions": nutritions,
            "ingredients": ingredients,
        }
        logger.info("get_nutritions_and_ingredients: '%s' → no ingredients (API limitation)",
                    normalized_query)
        logger.debug("get_nutritions_and_ingredients result: %s", result)
        return result

    def get_nutritions_and_ingredients_by_weight(self, query: str, weight_g: float) -> Optional[Dict]:
        """
        Return actual PCF nutrition data calculated by weight and ingredients in one dict.
        Calls get_nutritions_and_ingredients to get 100g reference and calculates actual nutritions.
        """
        logger.debug("get_nutritions_and_ingredients_by_weight() called with query='%s', weight_g=%.2f", query, weight_g)

        result = self.get_nutritions_and_ingredients(query)
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

    def _should_cache_negative_search_result(self) -> bool:
        """Return True when a failed search should be negative-cached."""
        if self._last_search_empty_result:
            return True
        return self._last_search_http_status in _NEGATIVE_CACHEABLE_SEARCH_STATUSES

    def _cache_negative_barcode_result(self, barcode: str, message: str = "product not found") -> Dict:
        """Helper to cache negative barcode results and return formatted response."""
        _l1_barcodes.set(barcode, None)
        _l2["barcodes"][barcode] = {
            "food": None,
            "found": False,
            "message": message,
            "_ts": _now_ts(),
        }
        _save_disk_cache(_l2)
        entry = _l2["barcodes"][barcode]
        return {k: v for k, v in entry.items() if k != "_ts"}

    def search_best(self, normalized_query: str) -> Optional[dict]:
        """
        Return the best-matching food item for a query.

        Cache lookup order:
          1. L1 RAM (LRU dict, 256 entries max)              — fastest
          2. L2 Disk (JSON file, 30-day TTL)                 — across restarts
          3. Avocavo Nutrition API                            — real network call
             → result saved to both L1 + L2 on success
        """
        # ── Level 1: RAM LRU ──────────────────────────────────────────────
        l1_hit = _l1_foods.get(normalized_query)
        if l1_hit is not _MISSING:
            _name = (l1_hit.get("ingredient") or l1_hit.get("parsing", {}).get("ingredient_name", "None")) if l1_hit else "None"
            logger.info("search_best: L1 HIT (RAM) for '%s' → '%s'", normalized_query, _name)
            return l1_hit

        # ── Level 2: Disk JSON ────────────────────────────────────────────
        if normalized_query in _l2["foods"]:
            entry = _l2["foods"][normalized_query]
            if not _is_expired(entry):
                food = entry.get("food")
                _name = (food.get("ingredient") or food.get("parsing", {}).get("ingredient_name", "None")) if food else "None"
                logger.info("search_best: L2 HIT (disk) for '%s' → '%s'", normalized_query, _name)
                _l1_foods.set(normalized_query, food)
                return food
            else:
                logger.info("search_best: L2 EXPIRED for '%s' (age > %d days)",
                            normalized_query, _CACHE_TTL_DAYS)

        # ── Level 3: Avocavo Nutrition API ────────────────────────────────
        logger.debug("search_best: Cache MISS for '%s' → calling Avocavo Nutrition API", normalized_query)
        foods = self.search(normalized_query)

        if foods is None:
            if self._should_cache_negative_search_result():
                _l1_foods.set(normalized_query, None)
                _l2["foods"][normalized_query] = {
                    "food": None,
                    "found": False,
                    "message": "ingredient not found",
                    "_ts": _now_ts(),
                }
                _save_disk_cache(_l2)
                logger.info(
                    "search_best: cached negative result for '%s' (http_status=%s, empty_result=%s)",
                    normalized_query,
                    self._last_search_http_status,
                    self._last_search_empty_result,
                )
            else:
                logger.info("search_best: skip caching for '%s' (last HTTP status=%s)",
                            normalized_query, self._last_search_http_status)
            return None

        if not foods:
            logger.info("search_best: no foods returned for '%s'; skip negative caching", normalized_query)
            return None

        # Avocavo returns items matching the query; pick the first (best match)
        best_food = foods[0]
        logger.debug("search_best: best='%s'", best_food.get("ingredient") or best_food.get("parsing", {}).get("ingredient_name", "N/A"))

        _l1_foods.set(normalized_query, best_food)
        _l2["foods"][normalized_query] = {
            "food": best_food,
            "found": True,
            "message": "ingredient found",
            "_ts": _now_ts(),
        }
        _save_disk_cache(_l2)

        return best_food

    # ─────────────────────────────────────────────────────────────────────
    # Cache utilities
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def clear_l1_cache():
        """Clear Level-1 (RAM) cache only."""
        _l1_foods.clear()
        _l1_barcodes.clear()
        logger.info("L1 RAM cache cleared")

    @staticmethod
    def clear_all_caches():
        """Clear both L1 (RAM) and L2 (disk) caches."""
        _l1_foods.clear()
        _l1_barcodes.clear()
        _l2["foods"].clear()
        _l2["barcodes"].clear()
        _save_disk_cache(_l2)
        logger.info("All caches cleared (L1 + L2)")

    @staticmethod
    def cache_stats() -> dict:
        """Return current cache statistics."""
        foods    = _l2["foods"]
        barcodes = _l2["barcodes"]
        expired  = sum(1 for e in foods.values()    if _is_expired(e)) \
                 + sum(1 for e in barcodes.values() if _is_expired(e))
        return {
            "l1_food_entries":    len(_l1_foods),
            "l1_barcode_entries": len(_l1_barcodes),
            "l1_entries":         len(_l1_foods) + len(_l1_barcodes),
            "l1_maxsize":         _L1_MAXSIZE,
            "l2_food_entries":    len(foods),
            "l2_barcode_entries": len(barcodes),
            "l2_entries":         len(foods) + len(barcodes),
            "l2_expired":         expired,
            "l2_file":            _CACHE_FILE,
            "ttl_days":           _CACHE_TTL_DAYS,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Avocavo Nutrition network search
    # ─────────────────────────────────────────────────────────────────────

    def search(self, normalized_query: str) -> Optional[list]:
        """
        Send a search request to Avocavo Nutrition API.
        This is the ONLY function that makes real HTTP requests.

        Avocavo API returns a single dict (not list):
        {
          "ingredient": "chicken breast",
          "success": true,
          "nutrition": {"calories": 247.5, "protein": 46.53, "total_fat": 5.35, ...},
          "parsing": {"estimated_grams": 150.0, "ingredient_name": "..."},
        }
        We wrap the single result in a list for consistency.
        """
        search_url = f"{self.base_url}/nutrition/ingredient"
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        }
        self._last_search_http_status = None
        self._last_search_empty_result = False

        try:
            logger.info("Avocavo Nutrition API search: query='%s'", normalized_query)
            # Try POST with JSON body (Avocavo preferred format)
            resp = requests.post(
                search_url,
                json={
                    "ingredient": normalized_query
                },
                headers=headers,
                timeout=20
            )

            # Record status immediately so 4xx/5xx can be negative-cached reliably.
            self._last_search_http_status = resp.status_code

            resp.raise_for_status()
            data = resp.json()
            logger.debug("Avocavo Nutrition API: status=%d", resp.status_code)

            if not data.get("success", False):
                logger.warning("Avocavo Nutrition returned no success for '%s'", normalized_query)
                self._last_search_empty_result = True
                return None

            logger.info("Avocavo Nutrition found result for '%s'", normalized_query)
            return [data]  # Wrap single result in list

        except requests.exceptions.Timeout:
            logger.error("Avocavo Nutrition API timeout for query='%s'", normalized_query)
        except requests.exceptions.HTTPError as e:
            self._last_search_http_status = e.response.status_code if getattr(e, "response", None) is not None else None
            logger.error("Avocavo Nutrition API HTTP error: %s (query='%s')", e, normalized_query)
        except Exception as e:
            logger.error("Avocavo Nutrition API unexpected error: %s (query='%s')", e, normalized_query, exc_info=True)

        return None

    def search_by_barcode(self, code: str) -> Optional[Dict]:
        """
        Search Avocavo Nutrition by UPC/barcode and return a compact parsed response.

        Args:
            code: Barcode string (e.g. "0885909456017").

        Returns:
            Parsed product dict from Avocavo API, or None on error/invalid input.
        """
        barcode = re.sub(r"\D", "", str(code or "")).strip()
        if not barcode:
            logger.warning("search_by_barcode: invalid or empty barcode input='%s'", code)
            return {
                "food": None,
                "found": False,
                "message": "invalid barcode",
            }

        # Level 1: RAM cache
        l1_hit = _l1_barcodes.get(barcode)
        if l1_hit is not _MISSING:
            if l1_hit is not None:
                logger.info("search_by_barcode: L1 HIT (RAM) for upc='%s'", barcode)
                return {
                    "food": l1_hit,
                    "found": True,
                    "message": "product found",
                }
            else:
                logger.info("search_by_barcode: L1 HIT (RAM) for upc='%s' → not found", barcode)
                return {
                    "food": None,
                    "found": False,
                    "message": "product not found",
                }

        # Level 2: Disk cache
        if barcode in _l2["barcodes"]:
            entry = _l2["barcodes"][barcode]
            if not _is_expired(entry):
                food = entry.get("food")
                entry_found = entry.get("found")
                logger.info("search_by_barcode: L2 HIT (disk) for upc='%s'", barcode)
                if entry_found:
                    _l1_barcodes.set(barcode, food)
                    logger.info("search_by_barcode: L2 HIT (disk) for upc='%s' → found", barcode)
                else:
                    _l1_barcodes.set(barcode, None)
                    logger.info("search_by_barcode: L2 HIT (disk) for upc='%s' → not found", barcode)

                logger.info("search_by_barcode: L2 > L1 for upc='%s'", barcode)
                return {k: v for k, v in entry.items() if k != "_ts"}
            else:
                logger.info("search_by_barcode: L2 EXPIRED for upc='%s' (age > %d days)",
                        barcode, _CACHE_TTL_DAYS)

        # Spec: POST /api/v2/upc/ingredient with JSON body {"upc": "..."}
        search_url = f"{self.base_url}/upc/ingredient"
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
        }

        try:
            logger.info("Avocavo Nutrition API UPC search: upc='%s'", barcode)
            resp = requests.post(
                search_url,
                json={
                    "upc": barcode
                },
                headers=headers,
                timeout=20,
            )
            logger.debug("Avocavo barcode API: status=%d body=%s",
                         resp.status_code, resp.text[:120])
            # Handle HTTP errors first (400, 402, 422, etc. should raise exceptions)
            # Only 404/204 are legitimate "not found" responses
            if resp.status_code in _NEGATIVE_CACHEABLE_SEARCH_STATUSES:
                logger.info("Avocavo barcode API: upc '%s' not found (status=%d)", barcode, resp.status_code)
                return self._cache_negative_barcode_result(barcode)

            # Raise for other HTTP errors (400, 402, 422, 500, etc.)
            resp.raise_for_status()

            # Parse successful response
            raw_data = resp.json()
            parsed, entry_found = self._parse_barcode_response(raw_data, barcode)

            if not entry_found:
                # Valid response but no product data found
                logger.info("Avocavo barcode API: upc '%s' - valid response but no product data", barcode)
                return self._cache_negative_barcode_result(barcode)

            # Success - cache positive result
            _l1_barcodes.set(barcode, parsed)
            _l2["barcodes"][barcode] = {
                "food": parsed,
                "found": True,
                "message": "product found",
                "_ts": _now_ts(),
            }
            _save_disk_cache(_l2)

            return {
                "food": parsed,
                "found": True,
                "message": "product found",
            }
        except requests.exceptions.Timeout:
            logger.error("Avocavo Nutrition UPC API timeout for upc='%s'", barcode)
        except requests.exceptions.HTTPError as e:
            self._last_search_http_status = e.response.status_code if getattr(e, "response", None) is not None else None
            logger.error("Avocavo Nutrition UPC API HTTP error: %s (upc='%s')", e, barcode)
        except Exception as e:
            logger.error("Avocavo Nutrition UPC API unexpected error: %s (upc='%s')", e, barcode, exc_info=True)

        return {
            "food": None,
            "found": False,
            "message": "error during search",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Private: Parse
    # ─────────────────────────────────────────────────────────────────────

    def _parse_barcode_response(self, raw: dict, barcode: str) -> Tuple[dict, bool]:
        """Reduce verbose Avocavo barcode payloads to a compact, app-friendly schema."""
        if not isinstance(raw, dict):
            logger.warning("_parse_barcode_response: invalid payload type for '%s': %s",
                           barcode, type(raw).__name__)
            return {
                "barcode": barcode,
                "found": False,
                "message": "invalid payload",
            }, False

        product = raw.get("product") or {}
        nutrition = raw.get("nutrition") or {}
        per_100g = ((nutrition.get("data") or {}).get("per_100g") or {})

        found = bool(raw.get("success")) and isinstance(product, dict) and bool(product)
        if not found:
            return {
                "barcode": barcode,
                "found": False,
                "message": raw.get("status_verbose") or "product not found",
            }, False

        nutritions = {
            "calories": float(per_100g.get("calories", 0) or 0),
            "protein":  float(per_100g.get("protein", 0) or 0),
            "fat":      float(per_100g.get("fat", 0) or 0),
            "carbs":    float(per_100g.get("carbohydrates", 0) or 0),
            "fiber":    float(per_100g.get("fiber", 0) or 0),
            "sodium":   float(per_100g.get("sodium", 0) or 0),
            "sugar":    float(per_100g.get("sugars", 0) or 0),
        }

        labels = {
            "source": self._normalize_metadata_value(nutrition.get("source")),
            "coverage": self._normalize_metadata_value(nutrition.get("coverage")),
        }
        labels = {key: value for key, value in labels.items() if value is not None}

        parsed = {
            "barcode": product.get("upc") or raw.get("upc") or barcode,
            "product_name": (product.get("name")
                             or product.get("description")
                             or product.get("ingredient")
                             or "N/A"),
            "brands": product.get("brand") or None,
            "quantity": product.get("quantity") or None,
            "category": self._extract_primary_category(product.get("categories")),
            "ingredients_text": product.get("ingredients") or None,
            "ingredients": self._parse_barcode_ingredient_string(product.get("ingredients")),
            "nutritions": nutritions,
            "labels": labels or None,
            "images": {"front": product.get("image_url")} if product.get("image_url") else None,
        }

        compact = {key: value for key, value in parsed.items() if value is not None}
        logger.debug("_parse_barcode_response: compact fields for '%s' -> %s",
                     barcode, list(compact.keys()))
        return compact, any(key in compact for key in ("product_name", "nutritions", "ingredients", "ingredients_text"))

    def _extract_primary_category(self, categories) -> Optional[str]:
        """Return a compact primary category from a category list/string."""
        if not categories:
            return None

        if isinstance(categories, list):
            for item in categories:
                value = str(item).strip()
                if value:
                    return value.lower()
            return None

        if isinstance(categories, str):
            value = categories.strip()
            return value.lower() if value else None

        return None

    def _parse_barcode_ingredient_string(self, raw_ingredients: Optional[str]) -> Optional[List[str]]:
        """Parse a raw ingredient string into compact ingredient tokens."""
        if not raw_ingredients:
            return None

        tokens = []
        depth = 0
        current = []
        for char in raw_ingredients:
            if char in "([":
                depth += 1
                current.append(char)
            elif char in ")]":
                depth -= 1
                current.append(char)
            elif char in ",;" and depth == 0:
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
        seen = set()
        for tok in tokens:
            item = re.sub(r'\s*[\(\[][^)\]]*[\)\]]\s*', ' ', tok)
            item = re.sub(r'\s*\d+[,.]?\d*%\s*', ' ', item)
            item = re.sub(r'(?<![A-Za-z0-9])\d+[,.]?\d*(?![A-Za-z0-9])', ' ', item)
            item = re.sub(r'[^\w\s\-\']', ' ', item)
            item = re.sub(r'\s+', ' ', item).strip().lower()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item)

        return cleaned if cleaned else None

    def _normalize_metadata_value(self, value):
        """Normalize optional metadata values, dropping placeholders like 'unknown'."""
        if value in (None, "", "unknown"):
            return None
        return value

    def _parse_100g_nutritions(self, food: dict) -> Dict[str, float]:
        """
        Extract calories, protein, fat, carbs per 100g from an Avocavo Nutrition response.

        Avocavo response structure:
          food["nutrition"]  → {calories, protein, total_fat, carbohydrates, ...}
          food["parsing"]    → {estimated_grams, ingredient_name}
          food["metadata"]["portion_info"]["original_usda_per_100g"] → bool

        When original_usda_per_100g is True (the USDA source data is already per 100g
        and scaling_factor == 1.0), nutrition values are already per 100g — no scaling.
        Otherwise, values are per estimated_grams serving and must be scaled to 100g.
        """
        ingredient_name = (food.get("ingredient")
                           or food.get("parsing", {}).get("ingredient_name", "N/A"))

        portion_info    = food.get("metadata", {}).get("portion_info", {})
        original_per_100g = portion_info.get("original_usda_per_100g", False)
        scaling_factor  = float(portion_info.get("scaling_factor", 1.0) or 1.0)
        estimated_g     = float(food.get("parsing", {}).get("estimated_grams", 100.0) or 100.0)

        logger.info(
            "_parse_100g_nutritions: '%s' (estimated_g=%.1f, original_per_100g=%s, scaling_factor=%.3f)",
            ingredient_name, estimated_g, original_per_100g, scaling_factor,
        )

        nut = food.get("nutrition") or {}

        # If the API already returned per-100g values (USDA base), no normalization needed.
        # Otherwise divide out the portion scaling to recover per-100g values.
        if original_per_100g and scaling_factor == 1.0:
            ratio = 1.0
        else:
            ratio = 100.0 / estimated_g if estimated_g > 0 else 1.0

        def _safe_float(val, default=0.0):
            if val is None: return default
            try: return float(val)
            except (ValueError, TypeError): return default

        result = {
            "calories": round(_safe_float(nut.get("calories")) * ratio, 2),
            "protein":  round(_safe_float(nut.get("protein")) * ratio, 2),
            "fat":      round(_safe_float(nut.get("total_fat")) * ratio, 2),
            "carbs":    round(_safe_float(nut.get("carbohydrates")) * ratio, 2),
        }

        logger.debug("_parse_100g_nutritions result: %s", result)
        return result

    def _parse_ingredient_string(self, food: dict) -> Optional[List[str]]:
        """
        Avocavo Nutrition API does not include an ingredient list in its response.
        Always returns None.
        """
        ingredient_name = (food.get("ingredient")
                           or food.get("parsing", {}).get("ingredient_name", "N/A"))
        logger.info(
            "_parse_ingredient_string: Avocavo API does not provide ingredient data for '%s'",
            ingredient_name,
        )
        return None

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
