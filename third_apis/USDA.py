import os
import re
from typing import Dict, List, Optional, Tuple

import requests

from config.logging_config import get_logger
from utils.caculator import calculate_ingredient_nutrition
from utils.transformer import normalize_query
from utils.getter import get_mock_nutrition, get_mock_ingredients, get_mock_nutritions_and_ingredients, get_mock_barcode

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
# Lives at:  app/data/usda_cache.json
# Swap to S3/DynamoDB later by replacing load_disk_cache / _save_disk_cache.
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "usda_cache.json")

# Module-level L1 caches (shared across all USDAClient instances in one process)
_l1_foods: LRUCache = LRUCache(maxsize=L1_MAXSIZE)
_l1_barcodes: LRUCache = LRUCache(maxsize=L1_MAXSIZE)

# Load once at module import
_l2: dict = load_disk_cache(_CACHE_FILE, _CACHE_DIR, "usda_cache.json")


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

    Swap Level 2 to S3/DynamoDB by replacing load_disk_cache / _save_disk_cache.
    """

    ENERGY_NUMBERS = {"208", "2047", "2048"}  # kcal only
    TARGET_NUTRIENTS = {
        "203": "protein",  # Protein
        "204": "fat",  # Total lipid (fat)
        "205": "carbs",  # Carbohydrate, by difference
    }

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.nal.usda.gov/fdc/v1"
        self._last_search_http_status: Optional[int] = None
        self._last_search_empty_result: bool = False
        logger.info(
            "USDAClient initialized (api_key=%s)",
            "DEMO_KEY" if api_key == "DEMO_KEY" else "***",
        )
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
        Return Protein/Calories/Fat nutrition data per 100g.
        Uses two-tier cache before calling USDA API.
        Falls back to mock values if api_key is DEMO_KEY.
        """
        logger.debug("get_nutritions() called with query='%s'", query)
        normalized_query = normalize_query(query)

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info(
                "get_nutritions: using mock data (api_key=%s)", self.api_key or "None"
            )
            return get_mock_nutrition(query)

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
        Uses two-tier cache before calling USDA API.
        """
        logger.debug("get_ingredients() called with query='%s'", query)
        normalized_query = normalize_query(query)
        if not normalized_query:
            logger.warning("get_ingredients: empty query")
            return None

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("get_ingredients: using mock data (api_key=%s)", self.api_key or "None")
            return get_mock_ingredients(query)

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning("get_ingredients: no USDA result for '%s'", normalized_query)
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

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("get_nutritions_and_ingredients: using mock data (api_key=%s)", self.api_key or "None")
            return get_mock_nutritions_and_ingredients(query)

        best = self.search_best(normalized_query, pageSize)
        if not best:
            logger.warning(
                "get_nutritions_and_ingredients: no USDA result for '%s'",
                normalized_query,
            )
            return None

        description = best.get("description", "N/A").lower()
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
            ["apple", 52.0, 0.26, 13.84, 0.17, ["apple"], 100],
            ["banana", 89.0, 1.09, 22.84, 0.33, ["banana"], 100]
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
                    results.append([des, cal, pro, carb, fat, ing, w])
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
        save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "usda_cache.json")
        entry = _l2["barcodes"][barcode]
        return {k: v for k, v in entry.items() if k != "_ts"}

    # ─────────────────────────────────────────────────────────────────────
    # Cache utilities
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def clear_l1_cache():
        """Clear Level-1 (RAM) cache only.
        Call at start of each isolated test to get a fair cold-start measurement.
        """
        _l1_foods.clear()
        _l1_barcodes.clear()
        logger.info("L1 RAM cache cleared")

    @staticmethod
    def clear_all_caches():
        """Clear both L1 (RAM) and L2 (disk) caches.
        Use for full reset / test fixture teardown.
        """
        _l1_foods.clear()
        _l1_barcodes.clear()
        _l2["foods"].clear()
        _l2["barcodes"].clear()
        save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "usda_cache.json")
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
        self._last_search_http_status = None
        self._last_search_empty_result = False

        try:
            logger.info("USDA API search: query='%s'", normalized_query)
            resp = requests.get(search_url, params=params, timeout=20)
            # Record status immediately so 4xx/5xx can be negative-cached reliably.
            self._last_search_http_status = resp.status_code
            resp.raise_for_status()
            data = resp.json()
            logger.debug(
                "USDA API: status=%d, totalHits=%s",
                resp.status_code,
                data.get("totalHits", "N/A"),
            )

            foods = data.get("foods", [])
            if not foods:
                logger.warning("USDA returned 0 results for '%s'", normalized_query)
                self._last_search_empty_result = True
                return None

            logger.info(
                "USDA found %d result(s) for '%s'", len(foods), normalized_query
            )
            return foods

        except requests.exceptions.Timeout:
            logger.error("USDA API timeout for query='%s'", normalized_query)
        except requests.exceptions.HTTPError as e:
            self._last_search_http_status = (
                e.response.status_code
                if getattr(e, "response", None) is not None
                else None
            )
            logger.error("USDA API HTTP error: %s (query='%s')", e, normalized_query)
        except Exception as e:
            logger.error(
                "USDA API unexpected error: %s (query='%s')",
                e,
                normalized_query,
                exc_info=True,
            )

        return None

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
        l1_hit = _l1_foods.get(normalized_query)
        if l1_hit is not MISSING:
            logger.info(
                "search_best: L1 HIT (RAM) for '%s' → '%s'",
                normalized_query,
                l1_hit.get("description", "None") if l1_hit else "None",
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
                    food.get("description", "None") if food else "None",
                )
                # Promote to L1
                _l1_foods.set(normalized_query, food)
                return food
            else:
                logger.info(
                    "search_best: L2 EXPIRED for '%s' (age > %d days)",
                    normalized_query,
                    CACHE_TTL_DAYS,
                )

        # ── Level 3: USDA API ─────────────────────────────────────────────
        logger.debug(
            "search_best: Cache MISS for '%s' → calling USDA API", normalized_query
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
                save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "usda_cache.json")
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
                "search_best: no foods returned for '%s'; skip negative caching",
                normalized_query,
            )
            return None

        best_food = max(foods, key=lambda x: x.get("score", 0))
        logger.debug(
            "search_best: best='%s' (score=%.1f)",
            best_food.get("description", "N/A"),
            best_food.get("score", 0),
        )

        # Save to L1 + L2
        _l1_foods.set(normalized_query, best_food)
        _l2["foods"][normalized_query] = {
            "food": best_food,
            "found": True,
            "message": "ingredient found",
            "_ts": get_now_ts(),
        }
        save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "usda_cache.json")

        return best_food

    def search_by_barcode(self, code: str) -> Optional[Dict]:
        """
        Search USDA FoodData Central by barcode and return a compact parsed response.

        Args:
            code: Barcode string decoded from image (e.g. "8938505974191").

        Returns:
            Parsed product dict from USDA API, or None on error/invalid input.
        """
        barcode = re.sub(r"\D", "", str(code or "")).strip()

        if not self.api_key or self.api_key == "DEMO_KEY":
            logger.info("search_by_barcode: using mock data (api_key=%s)", self.api_key or "None")
            return get_mock_barcode(barcode)

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
                    logger.info(
                        "search_by_barcode: L2 HIT (disk) for code='%s' → found",
                        barcode,
                    )
                else:
                    _l1_barcodes.set(barcode, None)
                    logger.info(
                        "search_by_barcode: L2 HIT (disk) for code='%s' → not found",
                        barcode,
                    )

                logger.info("search_by_barcode: L2 > L1 for code='%s'", barcode)
                return {k: v for k, v in entry.items() if k != "_ts"}
            else:
                logger.info(
                    "search_by_barcode: L2 EXPIRED for code='%s' (age > %d days)",
                    barcode,
                    CACHE_TTL_DAYS,
                )

        # Level 3: API call
        search_url = f"{self.base_url}/foods/search"
        params = {
            "query": barcode,
            "api_key": self.api_key,
        }

        try:
            logger.info("USDA API barcode search: code='%s'", barcode)
            resp = requests.get(search_url, params=params, timeout=20)
            logger.debug(
                "USDA barcode API: status=%d body=%s", resp.status_code, resp.text[:120]
            )

            # Handle HTTP errors first (400, 402, 422, etc. should raise exceptions)
            # Only 404/204 are legitimate "not found" responses
            if resp.status_code in NEGATIVE_CACHEABLE_SEARCH_STATUSES:
                logger.info(
                    "USDA barcode API: code '%s' not found (status=%d)",
                    barcode,
                    resp.status_code,
                )
                return self._cache_negative_barcode_result(barcode)

            # Raise for other HTTP errors (400, 402, 422, 500, etc.)
            resp.raise_for_status()

            # Parse successful response
            raw_data = resp.json()
            logger.debug(
                "USDA barcode API: status=%d, totalHits=%s",
                resp.status_code,
                raw_data.get("totalHits", "N/A"),
            )

            parsed, entry_found = self._parse_barcode_response(raw_data, barcode)

            if not entry_found:
                # Valid response but no product data found
                logger.info(
                    "USDA barcode API: code '%s' - valid response but no product data",
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
            save_disk_cache(_l2, _CACHE_FILE, _CACHE_DIR, "usda_cache.json")

            return {
                "food": parsed,
                "found": True,
                "message": "product found",
            }

        except requests.exceptions.Timeout:
            logger.error("USDA barcode API timeout for code='%s'", barcode)
        except requests.exceptions.HTTPError as e:
            logger.error("USDA barcode API HTTP error: %s (code='%s')", e, barcode)
        except Exception as e:
            logger.error(
                "USDA barcode API unexpected error: %s (code='%s')",
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
        """Reduce verbose USDA barcode search payloads to a compact, app-friendly schema."""
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

        foods = raw.get("foods") or []
        if not foods:
            logger.info("_parse_barcode_response: no foods found for '%s'", barcode)
            return {
                "barcode": barcode,
                "found": False,
                "message": "product not found",
            }, False

        best_food = max(foods, key=lambda x: x.get("score", 0))
        nutritions = self._parse_100g_nutritions(best_food)
        ingredients = self._parse_ingredient_string(best_food)

        labels = {
            "data_type": self._normalize_metadata_value(best_food.get("dataType")),
            "market_country": self._normalize_metadata_value(
                best_food.get("marketCountry")
            ),
        }
        labels = {key: value for key, value in labels.items() if value is not None}

        parsed = {
            "barcode": barcode,
            "found": True,
            "product_name": best_food.get("description") or "N/A",
            "brands": best_food.get("brandName") or best_food.get("brandOwner") or None,
            "quantity": best_food.get("packageWeight") or None,
            "category": best_food.get("foodCategory") or None,
            "ingredients_text": best_food.get("ingredients") or None,
            "ingredients": ingredients,
            "nutritions": nutritions,
            "labels": labels or None,
        }

        compact = {key: value for key, value in parsed.items() if value is not None}
        logger.debug(
            "_parse_barcode_response: compact fields for '%s' -> %s",
            barcode,
            list(compact.keys()),
        )
        return compact, any(
            key in compact
            for key in ("product_name", "nutritions", "ingredients", "ingredients_text")
        )

    def _normalize_metadata_value(self, value):
        """Normalize optional metadata values, dropping placeholders like 'unknown'."""
        if value in (None, "", "unknown"):
            return None
        return value

    def _parse_100g_nutritions(self, food: dict) -> Dict[str, float]:
        """
        Extract calories, protein, fat, carbs per 100g from a USDA food dict.
        """
        logger.info(
            "_parse_100g_nutritions: '%s' (fdcId=%s, score=%.1f)",
            food.get("description", "N/A"),
            food.get("fdcId", "N/A"),
            food.get("score", 0),
        )

        result = {
            "calories": 0.0,
            "protein": 0.0,
            "fat": 0.0,
            "carbs": 0.0,
        }

        for n in food.get("foodNutrients", []):
            nutrient_number = str(n.get("nutrientNumber", "")).strip()
            unit = str(n.get("unitName", "")).upper()
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
            logger.info(
                "_parse_ingredient_string: no 'ingredients' for '%s' (fdcId=%s)",
                food.get("description", "N/A"),
                food.get("fdcId", "N/A"),
            )
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
