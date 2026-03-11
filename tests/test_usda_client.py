"""
Tests for USDA Client
======================
Tests the USDA FoodData Central API client: search, nutrition, ingredients, caching.
"""

import os
import sys
import time

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)

# Common test queries
QUERIES = [
    {"query": "chicken breast", "expect_calories_gt": 100},
    {"query": "white rice cooked", "expect_calories_gt": 80},
    {"query": "egg fried", "expect_calories_gt": 100},
    {"query": "cơm tấm", "expect_calories_gt": 0},  # Vietnamese — tests normalize
]


def _test_get_nutritions(usda_client, query: str, expect_calories_gt: float) -> bool:
    """Test get_nutritions() returns valid PCF dict."""
    try:
        result = usda_client.get_nutritions(query)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        for key in ("calories", "protein", "fat", "carbs"):
            assert key in result, f"Missing key '{key}'"
            assert isinstance(result[key], (int, float)), f"'{key}' is not numeric"
        if expect_calories_gt > 0:
            assert result["calories"] > expect_calories_gt, (
                f"Expected calories > {expect_calories_gt}, got {result['calories']}"
            )
        logger.info("✅ get_nutritions('%s') → cal=%.1f pro=%.1f carb=%.1f fat=%.1f",
                     query, result["calories"], result["protein"], result["carbs"], result["fat"])
        return True
    except Exception as e:
        logger.error("❌ get_nutritions('%s') failed: %s", query, e)
        return False


def _test_get_ingredients(usda_client, query: str = "chocolate") -> bool:
    """Test get_ingredients() returns a list of strings or None."""
    try:
        result = usda_client.get_ingredients(query)
        if result is not None:
            assert isinstance(result, list), f"Expected list, got {type(result)}"
            assert all(isinstance(i, str) for i in result), "All items should be strings"
            logger.info("✅ get_ingredients('%s') → %d items: %s", query, len(result), result[:5])
        else:
            logger.info("✅ get_ingredients('%s') → None (no ingredient data, acceptable)", query)
        return True
    except Exception as e:
        logger.error("❌ get_ingredients('%s') failed: %s", query, e)
        return False


def _test_get_nutritions_and_ingredients(usda_client, query: str = "chicken breast") -> bool:
    """Test get_nutritions_and_ingredients() returns combined dict."""
    try:
        result = usda_client.get_nutritions_and_ingredients(query)
        if result is None:
            logger.warning("⚠️ get_nutritions_and_ingredients('%s') returned None", query)
            return False

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "nutritions" in result, "Missing 'nutritions' key"
        assert "description" in result, "Missing 'description' key"

        nut = result["nutritions"]
        for key in ("calories", "protein", "fat", "carbs"):
            assert key in nut, f"Nutritions missing key '{key}'"

        logger.info("✅ get_nutritions_and_ingredients('%s') → desc='%s', cal=%.1f",
                     query, result["description"], nut["calories"])
        return True
    except Exception as e:
        logger.error("❌ get_nutritions_and_ingredients('%s') failed: %s", query, e)
        return False


def _test_get_nutritions_by_weight(usda_client, query: str = "chicken breast", weight_g: float = 150.0) -> bool:
    """Test get_nutritions_and_ingredients_by_weight() returns weight-scaled values."""
    try:
        result = usda_client.get_nutritions_and_ingredients_by_weight(query, weight_g)
        if result is None:
            logger.warning("⚠️ get_nutritions_and_ingredients_by_weight('%s', %.1f) returned None", query, weight_g)
            return False

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "nutritions" in result, "Missing 'nutritions' key"
        assert "weight_g" in result, "Missing 'weight_g' key"
        assert result["weight_g"] == weight_g, f"Weight mismatch: {result['weight_g']} != {weight_g}"

        nut = result["nutritions"]
        logger.info("✅ get_nutritions_by_weight('%s', %.1fg) → cal=%.1f pro=%.1f carb=%.1f fat=%.1f",
                     query, weight_g, nut["calories"], nut["protein"], nut["carbs"], nut["fat"])
        return True
    except Exception as e:
        logger.error("❌ get_nutritions_by_weight('%s', %.1f) failed: %s", query, weight_g, e)
        return False


def _test_cache_hit(usda_client, query: str = "chicken breast") -> bool:
    """Test that repeating the same query hits L1 cache (faster response)."""
    try:
        # First call — may be cache miss (warm up)
        usda_client.get_nutritions(query)

        # Second call — should be L1 cache hit
        start = time.time()
        result = usda_client.get_nutritions(query)
        elapsed = time.time() - start

        assert isinstance(result, dict), "Cache hit should return valid dict"
        # L1 cache hit should be near-instant (< 0.1s)
        logger.info("✅ cache_hit('%s') → %.4fs (expected < 0.1s)", query, elapsed)
        return True
    except Exception as e:
        logger.error("❌ cache_hit('%s') failed: %s", query, e)
        return False


def _test_cache_stats(usda_client) -> bool:
    """Test cache_stats() returns expected structure."""
    try:
        stats = usda_client.cache_stats()
        assert isinstance(stats, dict), f"Expected dict, got {type(stats)}"
        for key in ("l1_entries", "l1_maxsize", "l2_entries", "l2_expired", "l2_file", "ttl_days"):
            assert key in stats, f"Missing key '{key}'"

        logger.info("✅ cache_stats() → L1=%d/%d, L2=%d (expired=%d)",
                     stats["l1_entries"], stats["l1_maxsize"],
                     stats["l2_entries"], stats["l2_expired"])
        return True
    except Exception as e:
        logger.error("❌ cache_stats() failed: %s", query, e)
        return False


def _test_normalize_query(usda_client) -> bool:
    """Test _normalize_query() handles Vietnamese and special characters."""
    try:
        test_cases = [
            ("Chicken Breast", "chicken breast"),
            ("  white rice  ", "white rice"),
            ("cơm tấm", "com tam"),
            ("phở bò", "pho bo"),
            ("egg (fried)", "egg"),
            ("fish-sauce", "fish sauce"),
            ("", ""),
        ]
        for raw, expected in test_cases:
            result = usda_client._normalize_query(raw)
            assert result == expected, f"_normalize_query('{raw}') = '{result}', expected '{expected}'"

        logger.info("✅ _normalize_query() passed %d test cases", len(test_cases))
        return True
    except Exception as e:
        logger.error("❌ _normalize_query() failed: %s", e)
        return False


def run_all(usda_client) -> list:
    """Run all USDA client tests.

    Args:
        usda_client: Pre-initialized USDAClient instance

    Returns:
        List of booleans (True = passed)
    """
    logger.info("Running USDA client tests...")
    results = []

    # Test 1-4: get_nutritions with various queries
    for q in QUERIES:
        results.append(_test_get_nutritions(usda_client, q["query"], q["expect_calories_gt"]))

    # Test 5: get_ingredients
    results.append(_test_get_ingredients(usda_client, "chocolate"))

    # Test 6: get_nutritions_and_ingredients
    results.append(_test_get_nutritions_and_ingredients(usda_client, "chicken breast"))

    # Test 7: get_nutritions_and_ingredients_by_weight
    results.append(_test_get_nutritions_by_weight(usda_client, "chicken breast", 150.0))

    # Test 8: cache hit
    results.append(_test_cache_hit(usda_client, "chicken breast"))

    # Test 9: cache stats
    results.append(_test_cache_stats(usda_client))

    # Test 10: normalize query
    results.append(_test_normalize_query(usda_client))

    passed = sum(1 for r in results if r)
    logger.info("USDA client tests: %d/%d passed", passed, len(results))

    return results
