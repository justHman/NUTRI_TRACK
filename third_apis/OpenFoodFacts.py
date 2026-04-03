import json
import os
import re
import time
import unicodedata
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import requests

from config.logging_config import get_logger
from utils.caculator import calculate_ingredient_nutrition
from utils.transformer import get_mock_nutrition, normalize_query

logger = get_logger(__name__)

from config.client_config import (
    CACHE_TTL_DAYS,
    L1_MAXSIZE,
    NEGATIVE_CACHEABLE_SEARCH_STATUSES,
)
from models.LRUCache import MISSING, LRUCache
from utils.cache_utils import get_now_ts, is_expired, load_disk_cache, save_disk_cache

# ─────────────────────────────────────────────────────────────────────────────
# Disk Cache Path  (Level 2 — Persistent)
# Lives at:  app/data/openfoodfacts_cache.json
# Swap to S3/DynamoDB later by replacing load_disk_cache / save_disk_cache.
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "openfoodfacts_cache.json")


# Only legitimate "not found" statuses should be cached (not HTTP errors)
# Moved _NEGATIVE_CACHEABLE_SEARCH_STATUSES to config

# Module-level L1 caches (shared across all OpenFoodFactsClient instances in one process)
_l1_foods: LRUCache = LRUCache(maxsize=L1_MAXSIZE)
_l1_barcodes: LRUCache = LRUCache(maxsize=L1_MAXSIZE)

# Load once at module import
_l2: dict = load_disk_cache(_CACHE_FILE, _CACHE_DIR, "openfoodfacts_cache.json")


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

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key  # Not required, kept for interface consistency
        self.base_url = "https://world.openfoodfacts.org"
        self.user_agent = "NutriTrack/2.0"
        self._last_search_http_status: Optional[int] = None
        self._last_search_empty_result: bool = False
        logger.info("OpenFoodFactsClient initialized (no API key required)")
        l2_entries = len(_l2["foods"]) + len(_l2["barcodes"])
        l1_entries = len(_l1_foods) + len(_l1_barcodes)
        logger.debug(
            "L1 cache size: %d / %d   |   L2 disk entries: %d",
            l1_entries,
            L1_MAXSIZE * 2,
            l2_entries,
        )

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
        normalized_query = normalize_query(query)

        best = self.search_best(normalized_query, pageSize)
        if best:
            return self._parse_100g_nutritions(best)

        logger.warning(
            "get_nutritions: no result for '%s', falling back to mock", normalized_query
        )
        return get_mock_nutrition(query)

    def get_ingredients(self, query: str, pageSize: int = 5) -> Optional[List[str]]:
        """
        Return ingredient list for a food item.
        Uses two-tier cache before calling Open Food Facts API.
        """
        logger.debug("get_ingredients() called with query='%s'", query)
        normalized_query = normalize_query(query)
        if not normalized_query:
            logger.warning("get_ingredients: empty query")
            return None

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning(
                "get_ingredients: no Open Food Facts result for '%s'", normalized_query
            )
            return None

        ingredients = self._parse_ingredient_string(best)
        logger.info(
            "get_ingredients: %d ingredients for '%s'",
            len(ingredients) if ingredients else 0,
            normalized_query,
        )
        return ingredients

    def get_nutritions_and_ingredients(
        self, query: str, pageSize: int = 5
    ) -> Optional[Dict]:
        """
        Return both PCF nutrition data and ingredients in one dict.
        Calls search_best() once — cache ensures only 1 API call per unique query.
        """
        logger.debug("get_nutritions_and_ingredients() called with query='%s'", query)
        normalized_query = normalize_query(query)
        if not normalized_query:
            logger.warning("get_nutritions_and_ingredients: empty query")
            return None

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning(
                "get_nutritions_and_ingredients: no Open Food Facts result for '%s'",
                normalized_query,
            )
            return None

        description = best.get("product_name", "N/A").lower()
        nutritions = self._parse_100g_nutritions(best)
        ingredients = self._parse_ingredient_string(best)

        result = {
            "description": description,
            "nutritions": nutritions,
            "ingredients": ingredients,
        }
        logger.info(
            "get_nutritions_and_ingredients: '%s' → %d ingredients",
            normalized_query,
            len(ingredients) if ingredients else 0,
        )
        logger.debug("get_nutritions_and_ingredients result: %s", result)
        return result

    def get_nutritions_and_ingredients_by_weight(
        self, query: str, weight_g: float, pageSize: int = 5
    ) -> Optional[Dict]:
        """
        Return actual PCF nutrition data calculated by weight and ingredients in one dict.
        Calls get_nutritions_and_ingredients to get 100g reference and calculates actual nutritions.
        """
        logger.debug(
            "get_nutritions_and_ingredients_by_weight() called with query='%s', weight_g=%.2f",
            query,
            weight_g,
        )

        result = self.get_nutritions_and_ingredients(query, pageSize)
        if not result:
            return None

        nutritions_100g = result["nutritions"]
        actual_nutritions = calculate_ingredient_nutrition(nutritions_100g, weight_g)

        result["nutritions"] = actual_nutritions
        result["weight_g"] = weight_g

        logger.debug(
            "get_nutritions_and_ingredients_by_weight actual result: %s", result
        )
        return result

    def get_batch(self, items: list) -> list:
        """
        - Input: [
            {"name": "Apple", "weight": 100},
            {"name": "Banana", "weight": 100}
        ]
        - Output: [
            ("apple", 52.0, 0.26, 13.84, 0.17, ["apple"], 100),
            ("banana", 89.0, 1.09, 22.84, 0.33, ["banana"], 100)
        ]
        """
        results = []
        for item in items:
            name = item.get("name", "")
            weight = float(item.get("weight", 0.0))
            res = self.get_nutritions_and_ingredients_by_weight(name, weight)
            if res:
                des = res.get("description", "")
                ing = res.get("ingredients", [])
                w = weight

                nut = res.get("nutritions", {})
                pro = nut.get("protein", 0.0)
                cal = nut.get("calories", 0.0)
                fat = nut.get("fat", 0.0)
                carb = nut.get("carbs", 0.0)
                if nut or pro or cal or fat or carb:
                    results.append((des, cal, pro, carb, fat, ing, w))
        return results

    # ─────────────────────────────────────────────────────────────────────
    # Cache-aware search  (two-tier lookup happens here)
    # ─────────────────────────────────────────────────────────────────────

    def _should_cache_negative_search_result(self) -> bool:
        """Return True when a failed search should be negative-cached."""
        if self._last_search_empty_result:
            return True
        return self._last_search_http_status in NEGATIVE_CACHEABLE_SEARCH_STATUSES

    def _cache_negative_barcode_result(
        self, barcode: str, message: str = "product not found"
    ) -> Dict:
        """Helper to cache negative barcode results and return formatted response."""
        _l1_barcodes.set(barcode, None)
        _l2["barcodes"][barcode] = {
            "food": None,
            "found": False,
            "message": message,
            "_ts": get_now_ts(),
        }
        save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "openfoodfacts_cache.json")
        entry = _l2["barcodes"][barcode]
        return {k: v for k, v in entry.items() if k != "_ts"}

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
        save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "openfoodfacts_cache.json")
        logger.info("All caches cleared (L1 + L2)")

    @staticmethod
    def cache_stats() -> dict:
        """Return current cache statistics."""
        foods = _l2["foods"]
        barcodes = _l2["barcodes"]
        expired = sum(1 for e in foods.values() if is_expired(e)) + sum(
            1 for e in barcodes.values() if is_expired(e)
        )
        return {
            "l1_food_entries": len(_l1_foods),
            "l1_barcode_entries": len(_l1_barcodes),
            "l1_entries": len(_l1_foods) + len(_l1_barcodes),
            "l1_maxsize": L1_MAXSIZE,
            "l2_food_entries": len(foods),
            "l2_barcode_entries": len(barcodes),
            "l2_entries": len(foods) + len(barcodes),
            "l2_expired": expired,
            "l2_file": _CACHE_FILE,
            "ttl_days": CACHE_TTL_DAYS,
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
            "action": "process",
            "json": 1,
            "page_size": pageSize,
            "page": 1,
            "fields": "code,product_name,brands,categories,quantity,image_url,image_front_url,countries,nutriments,unique_scans_n,popularity_key,completeness,nutriscore_grade,nova_group,ingredients_text,ingredients_tags,allergens,labels,labels_tags,countries_tags,categories_tags,brands_tags,additives_tags,ingredients_analysis_tags",
        }
        headers = {
            "User-Agent": self.user_agent,
        }
        self._last_search_http_status = None
        self._last_search_empty_result = False

        try:
            logger.info("Open Food Facts API search: query='%s'", normalized_query)
            resp = requests.get(search_url, params=params, timeout=60)
            # Record status immediately so 4xx/5xx can be negative-cached reliably.
            self._last_search_http_status = resp.status_code
            resp.raise_for_status()
            data = resp.json()
            logger.debug(
                "Open Food Facts API: status=%d, count=%s",
                resp.status_code,
                data.get("count", "N/A"),
            )

            products = data.get("products", [])
            if not products:
                logger.warning(
                    "Open Food Facts returned 0 results for '%s'", normalized_query
                )
                self._last_search_empty_result = True
                return None

            logger.info(
                "Open Food Facts found %d result(s) for '%s'",
                len(products),
                normalized_query,
            )
            return products

        except requests.exceptions.Timeout:
            logger.error("Open Food Facts API timeout for query='%s'", normalized_query)
        except requests.exceptions.HTTPError as e:
            self._last_search_http_status = (
                e.response.status_code
                if getattr(e, "response", None) is not None
                else None
            )
            logger.error(
                "Open Food Facts API HTTP error: %s (query='%s')", e, normalized_query
            )
        except Exception as e:
            logger.error(
                "Open Food Facts API unexpected error: %s (query='%s')",
                e,
                normalized_query,
                exc_info=True,
            )

        return None

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
        l1_hit = _l1_foods.get(normalized_query)
        if l1_hit is not MISSING:
            logger.info(
                "search_best: L1 HIT (RAM) for '%s' → '%s'",
                normalized_query,
                l1_hit.get("product_name", "None") if l1_hit else "None",
            )
            return l1_hit

        # ── Level 2: Disk JSON ────────────────────────────────────────────
        if normalized_query in _l2["foods"]:
            entry = _l2["foods"][normalized_query]
            if not is_expired(entry):
                food = entry.get("food")
                logger.info(
                    "search_best: L2 HIT (disk) for '%s' → '%s'",
                    normalized_query,
                    food.get("product_name", "None") if food else "None",
                )
                _l1_foods.set(normalized_query, food)
                return food
            else:
                logger.info(
                    "search_best: L2 EXPIRED for '%s' (age > %d days)",
                    normalized_query,
                    CACHE_TTL_DAYS,
                )

        # ── Level 3: Open Food Facts API ──────────────────────────────────
        logger.debug(
            "search_best: Cache MISS for '%s' → calling Open Food Facts API",
            normalized_query,
        )
        foods = self.search(normalized_query, pageSize)

        if foods is None:
            if self._should_cache_negative_search_result():
                _l1_foods.set(normalized_query, None)
                _l2["foods"][normalized_query] = {
                    "food": None,
                    "found": False,
                    "message": "ingredient not found",
                    "_ts": get_now_ts(),
                }
                save_disk_cache(
                    _l2, _CACHE_FILE, _CACHE_DIR, "openfoodfacts_cache.json"
                )
                logger.info(
                    "search_best: cached negative result for '%s' (http_status=%s, empty_result=%s)",
                    normalized_query,
                    self._last_search_http_status,
                    self._last_search_empty_result,
                )
            else:
                logger.info(
                    "search_best: skip caching for '%s' (last HTTP status=%s)",
                    normalized_query,
                    self._last_search_http_status,
                )
            return None

        if not foods:
            logger.info(
                "search_best: no products returned for '%s'; skip negative caching",
                normalized_query,
            )
            return None

        # Pick the best product based on scoring logic: score = unique_scans_n + popularity_key + completeness
        best_food = self._find_best_product(foods)
        logger.debug(
            "search_best: best='%s' with score=%.2f",
            best_food.get("product_name", "N/A"),
            self._calculate_score(best_food),
        )

        _l1_foods.set(normalized_query, best_food)
        _l2["foods"][normalized_query] = {
            "food": best_food,
            "found": True,
            "message": "ingredient found",
            "_ts": get_now_ts(),
        }
        save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "openfoodfacts_cache.json")

        return best_food

    def search_by_barcode(self, code: str) -> Optional[Dict]:
        """
        Search Open Food Facts by barcode and return a compact parsed response.

        Args:
            code: Barcode string decoded from image (e.g. "3017620422003").

        Returns:
            Parsed product dict from Open Food Facts API, or None on error/invalid input.
        """
        barcode = re.sub(r"\D", "", str(code or "")).strip()
        if not barcode:
            logger.warning(
                "search_by_barcode: invalid or empty barcode input='%s'", code
            )
            return {
                "food": None,
                "found": False,
                "message": "invalid barcode",
            }

        # Level 1: RAM cache
        l1_hit = _l1_barcodes.get(barcode)
        if l1_hit is not MISSING:
            logger.info("search_by_barcode: L1 HIT (RAM) for code='%s'", barcode)
            if l1_hit is not None:
                return {
                    "food": l1_hit,
                    "found": True,
                    "message": "product found",
                }
            else:
                return {
                    "food": None,
                    "found": False,
                    "message": "product not found",
                }

        # Level 2: Disk cache
        if barcode in _l2["barcodes"]:
            entry = _l2["barcodes"][barcode]
            if not is_expired(entry):
                food = entry.get("food")
                entry_found = entry.get("found")
                logger.info("search_by_barcode: L2 HIT (disk) for code='%s'", barcode)
                if entry_found:
                    _l1_barcodes.set(barcode, food)
                else:
                    _l1_barcodes.set(barcode, None)
                return {k: v for k, v in entry.items() if k != "_ts"}
            else:
                logger.info(
                    "search_by_barcode: L2 EXPIRED for code='%s' (age > %d days)",
                    barcode,
                    CACHE_TTL_DAYS,
                )

        # Level 3: API call
        search_url = f"{self.base_url}/api/v2/product/{barcode}"
        headers = {
            "User-Agent": self.user_agent,
        }

        try:
            logger.info("Open Food Facts API barcode search: code='%s'", barcode)
            resp = requests.get(search_url, headers=headers, timeout=60)
            logger.debug(
                "Open Food Facts barcode API: status=%d body=%s",
                resp.status_code,
                resp.text[:120],
            )

            # Handle HTTP errors first (400, 402, 422, etc. should raise exceptions)
            # Only 404/204 are legitimate "not found" responses
            if resp.status_code in NEGATIVE_CACHEABLE_SEARCH_STATUSES:
                logger.info(
                    "Open Food Facts barcode API: code '%s' not found (status=%d)",
                    barcode,
                    resp.status_code,
                )
                return self._cache_negative_barcode_result(barcode)

            # Raise for other HTTP errors (400, 402, 422, 500, etc.)
            resp.raise_for_status()

            # Parse successful response
            raw_data = resp.json()
            logger.debug(
                "Open Food Facts barcode API: status=%d, product_status=%s",
                resp.status_code,
                raw_data.get("status", "N/A"),
            )

            parsed, entry_found = self._parse_barcode_response(raw_data, barcode)

            if not entry_found:
                # Valid response but no product data found
                logger.info(
                    "Open Food Facts barcode API: code '%s' - valid response but no product data",
                    barcode,
                )
                return self._cache_negative_barcode_result(barcode)
            # Success - cache positive result
            _l1_barcodes.set(barcode, parsed)
            _l2["barcodes"][barcode] = {
                "food": parsed,
                "found": entry_found,
                "message": "product found",
                "_ts": get_now_ts(),
            }
            save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "openfoodfacts_cache.json")

            return {
                "food": parsed,
                "found": True,
                "message": "product found",
            }
        except requests.exceptions.Timeout:
            logger.error("Open Food Facts barcode API timeout for code='%s'", barcode)
        except requests.exceptions.HTTPError as e:
            logger.error(
                "Open Food Facts barcode API HTTP error: %s (code='%s')", e, barcode
            )
        except Exception as e:
            logger.error(
                "Open Food Facts barcode API unexpected error: %s (code='%s')",
                e,
                barcode,
                exc_info=True,
            )

        return {
            "food": None,
            "found": False,
            "message": "error during search",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Private: Parse
    # ─────────────────────────────────────────────────────────────────────

    def _parse_barcode_response(self, raw: dict, barcode: str) -> Tuple[dict, bool]:
        """Reduce a verbose Open Food Facts barcode payload to the fields the app actually needs."""
        if not isinstance(raw, dict):
            logger.warning(
                "_parse_barcode_response: invalid payload type for '%s': %s",
                barcode,
                type(raw).__name__,
            )
            return {
                "barcode": barcode,
                "found": False,
                "message": "invalid payload",
            }, False

        product = raw.get("product") or {}
        found = raw.get("status") == 1 and isinstance(product, dict) and bool(product)
        if not found:
            logger.info("_parse_barcode_response: product not found for '%s'", barcode)
            return {
                "barcode": barcode,
                "found": False,
                "message": raw.get("status_verbose") or "product not found",
            }, False

        nutritions = self._parse_100g_nutritions(product)
        ingredients = self._parse_ingredient_string(product)
        allergens = self._clean_taxonomy_list(
            product.get("allergens_tags") or product.get("allergens")
        )
        images = {
            "front": product.get("image_front_url") or product.get("image_url"),
            "ingredients": product.get("image_ingredients_url"),
            "nutrition": product.get("image_nutrition_url"),
        }
        images = {key: value for key, value in images.items() if value}

        labels = {
            "nutriscore": self._normalize_metadata_value(
                product.get("nutriscore_grade")
            ),
            "nova_group": product.get("nova_group"),
            "ecoscore": self._normalize_metadata_value(product.get("ecoscore_grade")),
        }
        labels = {key: value for key, value in labels.items() if value is not None}

        parsed = {
            "barcode": product.get("code") or raw.get("code") or barcode,
            "product_name": product.get("product_name")
            or product.get("product_name_en")
            or "N/A",
            "brands": product.get("brands") or None,
            "quantity": product.get("quantity") or None,
            "category": self._extract_primary_category(product),
            "ingredients_text": product.get("ingredients_text") or None,
            "ingredients": ingredients,
            "allergens": allergens or None,
            "nutritions": nutritions,
            "labels": labels or None,
            "images": images or None,
        }

        compact = {key: value for key, value in parsed.items() if value is not None}
        logger.debug(
            "_parse_barcode_response: compact fields for '%s' -> %s",
            barcode,
            list(compact.keys()),
        )
        return compact, (
            found
            or any(
                key in compact
                for key in (
                    "product_name",
                    "nutritions",
                    "ingredients",
                    "ingredients_text",
                )
            )
        )

    def _extract_primary_category(self, product: dict) -> Optional[str]:
        """Return the most specific category tag in a human-readable format."""
        tags = product.get("categories_tags") or []
        if not tags:
            return None
        return self._normalize_taxonomy_value(tags[-1])

    def _clean_taxonomy_list(self, values) -> List[str]:
        """Normalize taxonomy tags like 'en:fish' into compact values like 'fish'."""
        if not values:
            return []

        if isinstance(values, str):
            items = [item.strip() for item in values.split(",") if item.strip()]
        elif isinstance(values, list):
            items = [str(item).strip() for item in values if str(item).strip()]
        else:
            return []

        cleaned = []
        seen = set()
        for item in items:
            normalized = self._normalize_taxonomy_value(item)
            if normalized and normalized not in seen:
                seen.add(normalized)
                cleaned.append(normalized)
        return cleaned

    def _normalize_taxonomy_value(self, value: str) -> Optional[str]:
        """Convert Open Food Facts taxonomy values into readable labels."""
        if not value:
            return None

        normalized = str(value).strip()
        if ":" in normalized:
            normalized = normalized.split(":", 1)[1]
        normalized = normalized.replace("_", " ").replace("-", " ").strip().lower()

        if normalized in ("unknown", "none", "null", ""):
            return None
        return normalized

    def _normalize_metadata_value(self, value):
        """Normalize optional metadata values, dropping placeholders like 'unknown'."""
        if value in (None, "", "unknown"):
            return None
        return value

    def _parse_100g_nutritions(self, food: dict) -> Dict[str, float]:
        """
        Extract calories, protein, fat, carbs per 100g from an Open Food Facts product dict.

        Enhanced to handle:
        - String and numeric values (e.g. "0.08" vs 0.08)
        - Missing or null values
        - Various energy formats (energy-kcal_100g, energy-kcal)
        - Additional nutrients like fiber, salt, sugar, sodium

        Open Food Facts stores nutriments under:
        food["nutriments"] = {
            "energy-kcal_100g": 539,
            "proteins_100g": 6.3,
            "fat_100g": 30.9,
            "carbohydrates_100g": 57.5,
            "fiber_100g": 2.1,
            "salt_100g": 0.5,
            ...
        }
        """
        name = food.get("product_name", "N/A")
        logger.info("_parse_100g_nutritions: '%s'", name)

        nutriments = food.get("nutriments", {})
        if not nutriments:
            logger.warning("_parse_100g_nutritions: no nutriments data for '%s'", name)
            return self._get_default_nutrition_values()

        def safe_float(value, default=0.0):
            """Safely convert value to float, handling None, empty strings, and strings."""
            if value is None or value == "":
                return default
            try:
                return float(value)
            except (ValueError, TypeError):
                logger.debug(
                    "safe_float: failed to convert '%s' to float, using default %.1f",
                    value,
                    default,
                )
                return default

        # Priority order for energy (calories): _100g first, then fallback
        calories = (
            safe_float(nutriments.get("energy-kcal_100g"))
            or safe_float(nutriments.get("energy-kcal"))
            or safe_float(nutriments.get("energy_100g", 0) / 4.184)
        )  # Convert kJ to kcal if needed

        result = {
            "calories": calories,
            "protein": safe_float(nutriments.get("proteins_100g")),
            "fat": safe_float(nutriments.get("fat_100g")),
            "carbs": safe_float(nutriments.get("carbohydrates_100g")),
            "fiber": safe_float(nutriments.get("fiber_100g")),
            "salt": safe_float(nutriments.get("salt_100g")),
            "sugar": safe_float(nutriments.get("sugars_100g")),
            "sodium": safe_float(nutriments.get("sodium_100g")),
        }

        # Validate basic nutrition data is reasonable
        if all(
            v == 0
            for v in [
                result["calories"],
                result["protein"],
                result["fat"],
                result["carbs"],
            ]
        ):
            logger.warning(
                "_parse_100g_nutritions: all major nutrients are 0 for '%s', might indicate data issues",
                name,
            )

        logger.debug(
            "_parse_100g_nutritions result: %s",
            {k: f"{v:.1f}" for k, v in result.items()},
        )
        return result

    def _get_default_nutrition_values(self) -> Dict[str, float]:
        """Return default nutrition values when nutriments data is missing."""
        return {
            "calories": 0.0,
            "protein": 0.0,
            "fat": 0.0,
            "carbs": 0.0,
            "fiber": 0.0,
            "salt": 0.0,
            "sugar": 0.0,
            "sodium": 0.0,
        }

    def _parse_ingredient_string(self, food: dict) -> Optional[List[str]]:
        """
        Parse Open Food Facts ingredients_text into a clean list.

        Enhanced to handle:
        - Multiple languages (French, German, English, etc.)
        - Percentages (e.g., "NOISETTES 13%", "Filet de poulet 96%")
        - Complex nested parentheses and brackets
        - Colons with descriptions (e.g., "antioxydant: acide ascorbique")
        - Various punctuation and formatting
        - Capital letters normalization

        Examples:
            "MILK CHOCOLATE (SUGAR, COCOA BUTTER), PEANUTS, SALT"
            → ["milk chocolate", "peanuts", "salt"]

            "Sucre, huile de palme, NOISETTES 13%, cacao maigre 7,4%"
            → ["sucre", "huile de palme", "noisettes", "cacao maigre"]

            "Filet de poulet 96%, bouillon (eau, os de poulet, plantes V aromatiques)"
            → ["filet de poulet", "bouillon"]
        """
        raw_ingredients = food.get("ingredients_text", "") or ""
        if not raw_ingredients:
            logger.info(
                "_parse_ingredient_string: no 'ingredients_text' for '%s'",
                food.get("product_name", "N/A"),
            )
            return None

        logger.debug("_parse_ingredient_string: raw text = '%s'", raw_ingredients[:100])

        # Split on top-level commas while respecting parentheses/brackets
        tokens = self._split_preserving_nesting(raw_ingredients)

        cleaned = []
        seen = set()
        for token in tokens:
            # Clean each ingredient token
            clean_ingredient = self._clean_ingredient_token(token)
            if clean_ingredient and clean_ingredient not in seen:
                seen.add(clean_ingredient)
                cleaned.append(clean_ingredient)

        logger.debug(
            "_parse_ingredient_string: parsed %d ingredients: %s",
            len(cleaned),
            cleaned[:5],
        )  # Show first 5 for debugging
        return cleaned if cleaned else None

    def _split_preserving_nesting(self, text: str) -> List[str]:
        """
        Split ingredients text on top-level commas, preserving nested parentheses and brackets.

        Handles: (), [], and mixed nesting
        """
        tokens = []
        depth = 0
        current = []

        for char in text:
            if char in "([":
                depth += 1
                current.append(char)
            elif char in ")]":
                depth -= 1
                current.append(char)
            elif char in ",;" and depth == 0:
                # Top-level comma/semicolon - split here
                token = "".join(current).strip()
                if token:
                    tokens.append(token)
                current = []
            else:
                current.append(char)

        # Don't forget the last token
        token = "".join(current).strip()
        if token:
            tokens.append(token)

        return tokens

    def _clean_ingredient_token(self, token: str) -> str:
        """
        Clean individual ingredient token by removing:
        - Parentheses/brackets and their content
        - Percentages (e.g., "13%", "7,4%")
        - Colon descriptions (e.g., "antioxydant: acide ascorbique" → "antioxydant")
        - Extra punctuation and whitespace
        - Normalize to lowercase
        """
        if not token or not token.strip():
            return ""

        # Remove content within parentheses and brackets
        # e.g., "bouillon (eau, os de poulet)" → "bouillon"
        cleaned = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*", " ", token)

        # Remove percentages
        # e.g., "NOISETTES 13%" → "NOISETTES"
        cleaned = re.sub(r"\s*\d+[,.]?\d*%\s*", " ", cleaned)

        # Remove leftover standalone numeric fragments while keeping additive codes like E621 intact
        cleaned = re.sub(r"(?<![A-Za-z0-9])\d+[,.]?\d*(?![A-Za-z0-9])", " ", cleaned)

        # Handle colon descriptions - take only the part before the colon
        # e.g., "antioxydant: acide ascorbique" → "antioxydant"
        if ":" in cleaned:
            cleaned = cleaned.split(":")[0].strip()

        # Remove extra punctuation (but keep basic letters, numbers, spaces, hyphens)
        cleaned = re.sub(r"[^\w\s\-\']", " ", cleaned)

        # Normalize whitespace and convert to lowercase
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()

        # Filter out very short or meaningless tokens
        if len(cleaned) < 2 or cleaned in [
            "e",
            "de",
            "du",
            "la",
            "le",
            "les",
            "des",
            "en",
            "et",
            "with",
            "and",
            "or",
        ]:
            return ""

        return cleaned

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _calculate_score(self, product: dict) -> float:
        """
        Calculate product score based on: score = unique_scans_n + (popularity_key / 1_000_000) + (completeness * 1000)

        This scoring prioritizes:
        - Products that have been scanned more often (unique_scans_n)
        - Products with higher popularity (popularity_key, normalized)
        - Products with more complete data (completeness, weighted heavily)
        """
        try:
            # Handle unique_scans_n
            unique_scans = product.get("unique_scans_n", 0)
            if isinstance(unique_scans, str):
                unique_scans = float(unique_scans)
            unique_scans = unique_scans or 0

            # Handle popularity_key
            popularity = product.get("popularity_key", 0)
            if isinstance(popularity, str):
                popularity = float(popularity)
            popularity = popularity or 0
            popularity_normalized = popularity / 1_000_000  # Normalize to similar scale

            # Handle completeness
            completeness = product.get("completeness", 0)
            if isinstance(completeness, str):
                completeness = float(completeness)
            completeness = completeness or 0
            completeness_weighted = (
                completeness * 1000
            )  # Weight heavily as it's 0-1 scale

            score = unique_scans + popularity_normalized + completeness_weighted

            logger.debug(
                "_calculate_score: '%s' → scans=%d, popularity=%.2f, completeness=%.2f, total_score=%.2f",
                product.get("product_name", "N/A")[:30],
                int(unique_scans),
                popularity_normalized,
                completeness_weighted,
                score,
            )

            return score

        except (ValueError, TypeError) as e:
            logger.warning(
                "_calculate_score: error calculating score for '%s': %s",
                product.get("product_name", "N/A"),
                e,
            )
            return 0.0

    def _find_best_product(self, products: list) -> dict:
        """
        Find the best product from a list based on scoring logic.
        Returns the product with highest score, or first product if scoring fails.
        """
        if not products:
            return None

        if len(products) == 1:
            return products[0]

        best_product = products[0]
        best_score = self._calculate_score(best_product)

        for product in products[1:]:
            score = self._calculate_score(product)
            if score > best_score:
                best_score = score
                best_product = product

        logger.debug(
            "_find_best_product: selected '%s' (score=%.2f) from %d candidates",
            best_product.get("product_name", "N/A")[:30],
            best_score,
            len(products),
        )

        return best_product
