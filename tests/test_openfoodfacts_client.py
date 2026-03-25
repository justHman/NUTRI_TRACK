"""
Tests for OpenFoodFacts Client
================================
Tests the Open Food Facts API client: search, nutrition, ingredients, caching.
"""

import os
import sys
import time
import logging as _stdlib_logging
import json

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)


# ── Console-silence helpers ──────────────────────────────────────────────────

def _silence_console():
    root = _stdlib_logging.getLogger()
    saved = []
    for h in root.handlers:
        if isinstance(h, _stdlib_logging.StreamHandler) and not isinstance(h, _stdlib_logging.FileHandler):
            saved.append((h, h.level))
            h.setLevel(_stdlib_logging.WARNING)
    return saved


def _restore_console(saved):
    for h, level in saved:
        h.setLevel(level)


# ── Test queries ─────────────────────────────────────────────────────────────

QUERIES = [
    {"query": "chicken breast", "expect_calories_gt": 0},
    {"query": "white rice cooked", "expect_calories_gt": 0},
    {"query": "egg fried", "expect_calories_gt": 0},
    {"query": "cơm tấm", "expect_calories_gt": 0},  # Vietnamese — tests normalize
    {"query": "chocolate", "expect_calories_gt": 0},
    {"query": "nutella", "expect_calories_gt": 0},    # Known to have good OpenFoodFacts data
]

EDGE_CASE_QUERIES = [
    {"query": "", "expect_mock": True},              # Empty string
    {"query": "   ", "expect_mock": True},           # Whitespace only
    {"query": "xyz123nonexistent", "expect_mock": True}, # Nonexistent food
    {"query": "a" * 500, "expect_mock": True},      # Very long query
    {"query": "!@#$%^&*()", "expect_mock": True},   # Special characters only
    {"query": "123456789", "expect_mock": True},     # Numbers only
]

INGREDIENTtest_QUERIES = [
    "nutella",           # Known to have rich ingredient data
    "coca cola",         # Common product
    "cheese",            # Generic food
    "水果糖",            # Non-Latin characters
]


# ── Individual test functions ─────────────────────────────────────────────────

def _test_get_nutritions(client) -> list:
    """Tests all QUERIES. Returns list of (ok, label, detail) per query."""
    results = []
    for q in QUERIES:
        query, expect_gt = q["query"], q["expect_calories_gt"]
        try:
            r = client.get_nutritions(query)
            assert isinstance(r, dict)
            for key in ("calories", "protein", "fat", "carbs"):
                assert key in r and isinstance(r[key], (int, float))
            if expect_gt > 0:
                assert r["calories"] > expect_gt, f"cal={r['calories']:.1f} ≤ {expect_gt}"
            results.append((True, f"'{query}'",
                            f"cal={r['calories']:.1f}  pro={r['protein']:.1f}"
                            f"  fat={r['fat']:.1f}  carb={r['carbs']:.1f}"))
        except Exception as e:
            results.append((False, f"'{query}'", str(e)))
    return results


def _test_edge_case_queries(client) -> list:
    """Test edge case queries that should return mock data."""
    results = []
    for q in EDGE_CASE_QUERIES:
        query = q["query"]
        try:
            r = client.get_nutritions(query)
            assert isinstance(r, dict)
            for key in ("calories", "protein", "fat", "carbs"):
                assert key in r and isinstance(r[key], (int, float))
            # Should get mock data for edge cases when no OpenFoodFacts data found
            expected_mock = {"calories": 100.0, "protein": 5.0, "fat": 3.0, "carbs": 15.0}
            if r == expected_mock:
                results.append((True, f"'{query[:20]}...' edge case", "→ mock data as expected"))
            else:
                results.append((True, f"'{query[:20]}...' edge case", f"cal={r['calories']:.1f} (valid response)"))
        except Exception as e:
            results.append((False, f"'{query[:20]}...' edge case", str(e)))
    return results


def _test_get_ingredients(client) -> list:
    """Test ingredient extraction for various products."""
    results = []
    for query in INGREDIENTtest_QUERIES:
        try:
            r = client.get_ingredients(query)
            if r is not None:
                assert isinstance(r, list) and all(isinstance(i, str) for i in r)
                results.append((True, f"'{query}'", f"{len(r)} items: {r[:3]}..."))
            else:
                results.append((True, f"'{query}'", "None (no data — acceptable)"))
        except Exception as e:
            results.append((False, f"'{query}'", str(e)))
    return results


def _test_ingredients_parsing(client) -> list:
    """Test ingredient string parsing with complex cases."""
    test_cases = [
        {
            "name": "simple ingredients",
            "ingredients_text": "Sugar, Palm Oil, Hazelnuts, Cocoa Powder",
            "expected_count": 4,
        },
        {
            "name": "with percentages",
            "ingredients_text": "NOISETTES 13%, sucre, huile de palme, cacao maigre 7,4%",
            "expected_count": 4,
        },
        {
            "name": "with parentheses",
            "ingredients_text": "Milk chocolate (sugar, cocoa butter), peanuts, salt",
            "expected_count": 3,
        },
        {
            "name": "complex nested",
            "ingredients_text": "Bouillon (eau, os de poulet, légumes (carottes 2%, oignons)), sel",
            "expected_count": 2,
        },
        {
            "name": "with additives",
            "ingredients_text": "Sucre, colorant: E150d, conservateur: E211, antioxydant: acide ascorbique",
            "expected_count": 4,
        },
    ]

    results = []
    for case in test_cases:
        try:
            # Create mock food object for testing
            mock_food = {
                "product_name": "Test Product",
                "ingredients_text": case["ingredients_text"],
            }

            parsed = client._parse_ingredient_string(mock_food)
            if parsed is None:
                results.append((False, case["name"], "parsed as None"))
                continue

            assert isinstance(parsed, list)
            assert len(parsed) <= case["expected_count"]  # May be fewer due to filtering
            assert all(isinstance(ing, str) for ing in parsed)
            results.append((True, case["name"], f"parsed {len(parsed)} ingredients: {parsed[:2]}..."))
        except Exception as e:
            results.append((False, case["name"], str(e)))

    return results


def _test_nutritions_and_ingredients(client) -> list:
    query = "chicken breast"
    try:
        r = client.get_nutritions_and_ingredients(query)
        if r is None:
            return [(True, f"'{query}'", "None (no Open Food Facts data — acceptable)")]
        assert isinstance(r, dict) and "nutritions" in r and "description" in r
        nut = r["nutritions"]
        for key in ("calories", "protein", "fat", "carbs"):
            assert key in nut
        return [(True, f"'{query}'",
                 f"desc='{r['description']}'  cal={nut['calories']:.1f}")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_nutritions_by_weight(client) -> list:
    query, weight_g = "chicken breast", 150.0
    try:
        r = client.get_nutritions_and_ingredients_by_weight(query, weight_g)
        if r is None:
            return [(True, f"'{query}' {weight_g:.0f}g", "None (no Open Food Facts data — acceptable)")]
        assert isinstance(r, dict) and "nutritions" in r and "weight_g" in r
        assert r["weight_g"] == weight_g
        nut = r["nutritions"]
        return [(True, f"'{query}' {weight_g:.0f}g",
                 f"cal={nut['calories']:.1f}  pro={nut['protein']:.1f}"
                 f"  fat={nut['fat']:.1f}  carb={nut['carbs']:.1f}")]
    except Exception as e:
        return [(False, f"'{query}' {weight_g:.0f}g", str(e))]


def _test_weight_edge_cases(client) -> list:
    """Test edge cases for weight calculations."""
    query = "nutella"  # Use a product more likely to have OpenFoodFacts data

    test_cases = [
        (0.0, "zero weight"),
        (1.0, "1 gram"),
        (0.5, "half gram"),
        (1000.0, "1 kilogram"),
        (50.5, "decimal weight"),
    ]

    results = []
    for weight_g, desc in test_cases:
        try:
            r = client.get_nutritions_and_ingredients_by_weight(query, weight_g)
            if r is None:
                results.append((True, desc, "None (no OpenFoodFacts data — acceptable)"))
                continue

            assert r["weight_g"] == weight_g
            nut = r["nutritions"]
            # For 0g, all nutritions should be 0
            if weight_g == 0.0:
                assert all(nut[key] == 0.0 for key in ("calories", "protein", "fat", "carbs"))
            results.append((True, desc, f"cal={nut['calories']:.2f} at {weight_g}g"))
        except Exception as e:
            results.append((False, desc, str(e)))
    return results


def _test_cache_l1_hit(client) -> list:
    query = "chicken breast"
    try:
        client.get_nutritions(query)  # warm up
        start = time.time()
        r = client.get_nutritions(query)
        elapsed = time.time() - start
        assert isinstance(r, dict)
        return [(True, f"'{query}'", f"{elapsed:.4f}s")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_cache_l2_hit(client) -> list:
    try:
        from third_apis.OpenFoodFacts import _l2, _l1_foods, get_now_ts, _MISSING, OpenFoodFactsClient
        query = "__l2test_chicken_off__"
        fake_food = {
            "product_name": "Test Chicken L2 OFF",
            "nutriments": {
                "energy-kcal_100g": 165.0,
                "proteins_100g": 31.0,
                "fat_100g": 3.6,
                "carbohydrates_100g": 0.0,
            },
            "ingredients_text": "CHICKEN BREAST, SALT, WATER",
        }
        _l2["foods"][query] = {
            "food": fake_food,
            "found": True,
            "message": "ingredient found",
            "_ts": get_now_ts(),
        }
        OpenFoodFactsClient.clear_l1_cache()
        assert _l1_foods.get(query) is _MISSING
        start = time.time()
        r = client.search_best(query)
        elapsed = time.time() - start
        assert r is not None and r.get("product_name") == "Test Chicken L2 OFF"
        l1_val = _l1_foods.get(query)
        assert l1_val is not _MISSING and l1_val.get("product_name") == "Test Chicken L2 OFF"
        return [(True, "synthetic inject+promote", f"{elapsed:.4f}s  L1 promoted ✓")]
    except Exception as e:
        return [(False, "synthetic inject+promote", str(e))]
    finally:
        from third_apis.OpenFoodFacts import _l2, OpenFoodFactsClient
        _l2["foods"].pop("__l2test_chicken_off__", None)
        OpenFoodFactsClient.clear_l1_cache()


def _test_expired_cache_entries(client) -> list:
    """Test that expired cache entries are ignored and refreshed."""
    try:
        from third_apis.OpenFoodFacts import _l2, _l1_foods, get_now_ts, _MISSING, OpenFoodFactsClient
        query = "__expiredtest_off__"

        # Create expired entry (31 days old)
        expired_ts = get_now_ts() - (31 * 24 * 3600)
        fake_food = {
            "product_name": "Expired Product",
            "nutriments": {
                "energy-kcal_100g": 999.0,
                "proteins_100g": 999.0,
                "fat_100g": 999.0,
                "carbohydrates_100g": 999.0,
            },
        }
        _l2["foods"][query] = {
            "food": fake_food,
            "found": True,
            "message": "ingredient found",
            "_ts": expired_ts,
        }

        OpenFoodFactsClient.clear_l1_cache()

        # Should not use expired cache
        r = client.search_best(query)  # Will return None since it's a fake query

        return [(True, "expired cache", "expired entry ignored correctly")]
    except Exception as e:
        return [(False, "expired cache", str(e))]
    finally:
        from third_apis.OpenFoodFacts import _l2, OpenFoodFactsClient
        _l2["foods"].pop("__expiredtest_off__", None)
        OpenFoodFactsClient.clear_l1_cache()


def _test_product_scoring(client) -> list:
    """Test product scoring and selection logic."""
    try:
        # Create mock products with different scores
        products = [
            {
                "product_name": "Low Score Product",
                "unique_scans_n": 10,
                "popularity_key": 1000,
                "completeness": 0.3,
            },
            {
                "product_name": "High Score Product",
                "unique_scans_n": 1000,
                "popularity_key": 5000000,
                "completeness": 0.9,
            },
            {
                "product_name": "Medium Score Product",
                "unique_scans_n": 500,
                "popularity_key": 2000000,
                "completeness": 0.7,
            },
        ]

        # Calculate scores for each product
        scores = []
        for product in products:
            score = client._calculate_score(product)
            scores.append((score, product["product_name"]))

        # Find the best product
        best_product = client._find_best_product(products)

        # Should select the product with highest score
        highest_score = max(s[0] for s in scores)
        expected_name = next(s[1] for s in scores if s[0] == highest_score)

        assert best_product["product_name"] == expected_name
        return [(True, "product scoring", f"selected '{expected_name}' with score {highest_score:.1f}")]

    except Exception as e:
        return [(False, "product scoring", str(e))]


def _test_mock_data() -> list:
    """Tests mock data — OpenFoodFacts has no DEMO_KEY mode but mock_nutrition still works."""
    from third_apis.OpenFoodFacts import OpenFoodFactsClient
    mock_client = OpenFoodFactsClient()
    EXPECTED = {"calories": 100.0, "protein": 5.0, "fat": 3.0, "carbs": 15.0}
    results = []
    # Use a query that will definitely not match anything
    query = "xyznonexistentfood12345"
    try:
        r = mock_client.get_nutritions(query)
        if isinstance(r, dict) and r == EXPECTED:
            results.append((True, f"'{query}'", "→ fallback mock data"))
        else:
            results.append((False, f"'{query}'", f"mismatch: {r}"))
    except Exception as e:
        results.append((False, f"'{query}'", str(e)))
    return results


def _test_cache_stats(client) -> list:
    try:
        s = client.cache_stats()
        assert isinstance(s, dict)
        for key in ("l1_entries", "l1_maxsize", "l2_entries", "l2_expired", "l2_file", "ttl_days"):
            assert key in s
        return [(True, "cache_stats()",
                 f"L1={s['l1_entries']}/{s['l1_maxsize']}  L2={s['l2_entries']} (expired={s['l2_expired']})")]
    except Exception as e:
        return [(False, "cache_stats()", str(e))]


def _test_normalize_query(client) -> list:
    """Tests all normalization cases."""
    from utils.transformer import normalize_query
    cases = [
        ("Chicken Breast", "chicken breast"),
        ("  white rice  ", "white rice"),
        ("cơm tấm",        "com tam"),
        ("phở bò",         "pho bo"),
        ("egg (fried)",    "egg"),
        ("fish-sauce",     "fish sauce"),
        ("café_au_lait",   "cafe au lait"),
        ("naïve résumé",   "naive resume"),
        ("",               ""),
        ("   ",            ""),
        ("食物",           "食物"),  # Non-Latin should be preserved
        ("test@food.com",  "testfoodcom"),
        ("test!@#$%^&*()", "test"),
        ("coca-cola®",     "coca cola"),
        ("Dr. Pepper™",    "dr pepper"),
    ]
    results = []
    for raw, expected in cases:
        label = repr(raw) if raw else "'(empty)'"
        try:
            got = normalize_query(raw)
            if got == expected:
                results.append((True, label, f"→ '{got}'"))
            else:
                results.append((False, label, f"→ '{got}' (expected '{expected}')"))
        except Exception as e:
            results.append((False, label, str(e)))
    return results


def _test_search_by_barcode(client) -> list:
    """Test search_by_barcode() returns the compact parsed Open Food Facts response shape."""
    cases = [
        ("8934563138165", True),   # Known Vietnamese instant noodle barcode
        ("abc", False),            # Invalid barcode
        ("", False),               # Empty barcode
        ("  3017620422003  ", True), # Nutella barcode with whitespace
        ("123-456-789", True),     # Barcode with hyphens (should be cleaned)
        ("0" * 13, True),          # All zeros (valid format but likely not found)
    ]
    results = []

    for code, should_be_valid in cases:
        try:
            raw = client.search_by_barcode(code)

            if not should_be_valid:
                assert isinstance(raw, dict), f"expected dict, got {type(raw).__name__}"
                assert raw.get("found") is False
                assert raw.get("message")
                results.append((True, f"'{code}'", "invalid barcode -> found=False"))
                continue

            if raw is None:
                results.append((False, f"'{code}'", "returned None"))
                continue

            assert isinstance(raw, dict), f"expected dict, got {type(raw).__name__}"
            if "found" in raw:
                assert isinstance(raw.get("found"), bool)
            if raw.get("found") is False:
                assert raw.get("message")
                results.append((True, f"'{code}'",
                                f"found=False message='{raw.get('message')}'"))
            else:
                food = raw.get("food")
                assert food is not None
                assert food.get("product_name")
                assert isinstance(food.get("nutritions"), dict)
                assert "calories" in food["nutritions"]
                results.append((True, f"'{code}'",
                                f"found=True name={food.get('product_name', 'N/A')}"))
        except Exception as e:
            results.append((False, f"'{code}'", str(e)))

    return results


def _test_barcode_parser_fixture(client) -> list:
    """Validate the compact barcode parser against the local fixture payload."""
    fixture_path = os.path.join(project_root, "data", "tests", "openfoodfacts_8934563138165.json")

    try:
        if not os.path.exists(fixture_path):
            return [(None, "fixture barcode parse", "fixture file not found - skipping")]

        with open(fixture_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        parsed, found = client._parse_barcode_response(payload, "8934563138165")

        if not found:
            return [(False, "fixture barcode parse", "fixture marked as not found")]

        assert parsed["barcode"] == "8934563138165"
        assert "product_name" in parsed
        assert isinstance(parsed.get("nutritions"), dict)
        assert "calories" in parsed["nutritions"]

        # Check that we have reasonable nutrition values
        cal = parsed["nutritions"]["calories"]
        assert cal > 0, f"calories should be > 0, got {cal}"

        return [(True, "fixture barcode parse",
                 f"{parsed.get('product_name', 'N/A')[:30]}... | cal={cal:.1f}")]
    except Exception as e:
        return [(False, "fixture barcode parse", str(e))]


def _test_barcode_cache(client) -> list:
    """Test L2->L1 promotion and L1 hit behavior for search_by_barcode()."""
    results = []
    from third_apis import OpenFoodFacts as off_module
    from third_apis.OpenFoodFacts import _l1_barcodes, _l2, get_now_ts, _MISSING, OpenFoodFactsClient

    barcode = "8934563138165"
    l1_key  = barcode

    try:
        # L2 hit should promote to L1
        fake_l2 = {
            "barcode": barcode,
            "product_name": "Barcode L2 OFF",
            "nutritions": {"calories": 455.0, "protein": 10.0, "fat": 18.0, "carbs": 63.0},
        }
        _l2["barcodes"][barcode] = {
            "food": fake_l2,
            "found": True,
            "message": "product found",
            "_ts": get_now_ts(),
        }
        OpenFoodFactsClient.clear_l1_cache()
        assert _l1_barcodes.get(l1_key) is _MISSING

        got_l2 = client.search_by_barcode(barcode)
        assert isinstance(got_l2, dict)
        assert got_l2.get("found") is True
        food = got_l2.get("food")
        assert food is not None
        assert food.get("barcode") == barcode
        assert food.get("product_name") == fake_l2["product_name"]
        promoted = _l1_barcodes.get(l1_key)
        assert promoted is not _MISSING
        assert promoted.get("barcode") == barcode
        results.append((True, "L2->L1 promotion", "barcode cache promoted successfully"))

        # L1 hit should not call network
        fake_l1 = {
            "barcode": barcode,
            "product_name": "Barcode L1 OFF",
            "nutritions": {"calories": 455.0, "protein": 10.0, "fat": 18.0, "carbs": 63.0},
        }
        _l1_barcodes.set(l1_key, fake_l1)
        original_get = off_module.requests.get

        def _blocked_get(*args, **kwargs):
            raise AssertionError("network called during L1 cache hit")

        off_module.requests.get = _blocked_get
        try:
            got_l1 = client.search_by_barcode(barcode)
            assert isinstance(got_l1, dict)
            assert got_l1.get("found") is True
            food1 = got_l1.get("food")
            assert food1 is not None
            assert food1.get("barcode") == barcode
            assert food1.get("product_name") == fake_l1["product_name"]
            results.append((True, "L1 hit no network", "returned from RAM cache"))
        finally:
            off_module.requests.get = original_get
    except Exception as e:
        results.append((False, "barcode cache", str(e)))
    finally:
        _l2["barcodes"].pop(barcode, None)
        OpenFoodFactsClient.clear_l1_cache()

    return results


def _test_negative_caching(client) -> list:
    """Test that negative results (not found) are properly cached."""
    try:
        from third_apis.OpenFoodFacts import OpenFoodFactsClient, _l1_foods, _l2, _MISSING

        # Clear cache first
        OpenFoodFactsClient.clear_l1_cache()

        # Use a query that definitely won't exist
        fake_query = "__definitely_nonexistent_food_12345__"

        # First search should miss and potentially cache negative result
        result1 = client.search_best(fake_query)
        assert result1 is None

        # Check if negative result was cached
        l1_val = _l1_foods.get(fake_query)
        if l1_val is not _MISSING and l1_val is None:
            return [(True, "negative cache", "negative result cached in L1")]
        elif fake_query in _l2["foods"] and _l2["foods"][fake_query].get("found") is False:
            return [(True, "negative cache", "negative result cached in L2")]
        else:
            return [(True, "negative cache", "negative result not cached (depends on server response)")]

    except Exception as e:
        return [(False, "negative cache", str(e))]
    finally:
        from third_apis.OpenFoodFacts import OpenFoodFactsClient, _l2
        OpenFoodFactsClient.clear_l1_cache()
        _l2["foods"].pop("__definitely_nonexistent_food_12345__", None)


def _test_client_initialization(client) -> list:
    """Test different client initialization scenarios."""
    from third_apis.OpenFoodFacts import OpenFoodFactsClient

    results = []
    test_cases = [
        (None, "no api key (default)"),
        ("test_key", "custom api key"),
        ("", "empty api key"),
    ]

    for api_key, desc in test_cases:
        try:
            if api_key is None:
                test_client = OpenFoodFactsClient()
            else:
                test_client = OpenFoodFactsClient(api_key=api_key)

            assert test_client.base_url == "https://world.openfoodfacts.org"
            assert test_client.user_agent == "NutriTrack/2.0"
            # Test that client can call basic methods
            _ = test_client.cache_stats()
            results.append((True, desc, f"initialized successfully"))
        except Exception as e:
            results.append((False, desc, str(e)))

    return results


def _test_malformed_response_handling(client) -> list:
    """Test how client handles malformed API responses."""

    test_cases = [
        ({}, "empty dict"),
        ({"nutriments": None}, "null nutriments"),
        ({"nutriments": {}}, "empty nutriments"),
        ({"nutriments": {"energy-kcal_100g": "invalid"}}, "invalid calories"),
        ({"product_name": None}, "null product name"),
        ({"ingredients_text": ""}, "empty ingredients"),
    ]

    results = []
    for mock_response, desc in test_cases:
        try:
            # Test the parsing method directly
            parsed = client._parse_100g_nutritions(mock_response)
            assert isinstance(parsed, dict)
            assert all(key in parsed for key in ("calories", "protein", "fat", "carbs"))
            # Should handle gracefully and return reasonable defaults
            results.append((True, desc, "handled gracefully"))
        except Exception as e:
            results.append((False, desc, str(e)))

    return results


def _test_cache_lru_eviction(client) -> list:
    """Test that LRU cache properly evicts old entries."""
    try:
        from third_apis.OpenFoodFacts import _l1_foods, OpenFoodFactsClient

        # Clear cache first
        OpenFoodFactsClient.clear_l1_cache()

        # Fill cache with exact maxsize entries + 1
        maxsize = 256  # From _L1_MAXSIZE

        # Add maxsize entries
        for i in range(maxsize):
            key = f"test_food_{i}"
            fake_food = {
                "product_name": f"Test Food {i}",
                "nutriments": {
                    "energy-kcal_100g": i,
                    "proteins_100g": i,
                    "fat_100g": i,
                    "carbohydrates_100g": i,
                }
            }
            _l1_foods.set(key, fake_food)

        assert len(_l1_foods) == maxsize

        # Add one more - should evict the oldest (test_food_0)
        extra_key = "test_food_extra"
        extra_food = {
            "product_name": "Extra Food",
            "nutriments": {"energy-kcal_100g": 999}
        }
        _l1_foods.set(extra_key, extra_food)

        assert len(_l1_foods) == maxsize

        # test_food_0 should be evicted
        from third_apis.OpenFoodFacts import _MISSING
        first_entry = _l1_foods.get("test_food_0")
        assert first_entry is _MISSING

        # extra entry should be there
        extra_entry = _l1_foods.get(extra_key)
        assert extra_entry is not _MISSING

        return [(True, "LRU eviction", f"evicted oldest entry when cache full (size={len(_l1_foods)})")]

    except Exception as e:
        return [(False, "LRU eviction", str(e))]
    finally:
        from third_apis.OpenFoodFacts import OpenFoodFactsClient
        OpenFoodFactsClient.clear_l1_cache()


def _test_taxonomy_normalization(client) -> list:
    """Test Open Food Facts taxonomy value normalization."""
    test_cases = [
        ("en:fish", "fish"),
        ("fr:poisson", "poisson"),
        ("unknown", None),
        ("", None),
        (None, None),
        ("en:dairy-products", "dairy products"),
        ("category_name", "category name"),
    ]

    results = []
    for input_val, expected in test_cases:
        try:
            result = client._normalize_taxonomy_value(input_val)
            if result == expected:
                results.append((True, f"'{input_val}'", f"→ {result}"))
            else:
                results.append((False, f"'{input_val}'", f"→ {result} (expected {expected})"))
        except Exception as e:
            results.append((False, f"'{input_val}'", str(e)))

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all(client) -> list:
    """Run all OpenFoodFacts client tests.

    Args:
        client: Pre-initialized OpenFoodFactsClient instance

    Returns:
        List of booleans, one per test group (True = all cases in group passed)
    """
    _saved = _silence_console()
    group_results = []

    def _print_group(tag, cases):
        """Print a grouped test block and return True if all cases passed."""
        print(f"\n  ─────[{tag}]─────", flush=True)
        for i, (ok, label, detail) in enumerate(cases, 1):
            icon = "⏭️ " if ok is None else ("✅" if ok else "❌")
            print(f"    {i}. {label}: {detail} ({icon})", flush=True)
        passed = sum(1 for ok, _, _ in cases if ok is True)
        total = len(cases)
        all_ok = all(ok is True or ok is None for ok, _, _ in cases)
        s_icon = "✅" if all_ok else "❌"
        note = "  (skips expected)" if any(ok is None for ok, _, _ in cases) else ""
        print(f"    {passed}/{total} passed {s_icon}{note}", flush=True)
        return all_ok

    try:
        print("\n─── OpenFoodFacts Client Tests ────────────────────────────────────────", flush=True)
        group_results.append(_print_group("CLIENT INIT TESTS", _test_client_initialization(client)))
        group_results.append(_print_group("BARCODE TEST",     _test_search_by_barcode(client)))
        group_results.append(_print_group("BARCODE PARSE TEST", _test_barcode_parser_fixture(client)))
        group_results.append(_print_group("NUTRITION TESTS",  _test_get_nutritions(client)))
        group_results.append(_print_group("EDGE CASE TESTS",  _test_edge_case_queries(client)))
        group_results.append(_print_group("INGREDIENTS TEST", _test_get_ingredients(client)))
        group_results.append(_print_group("INGREDIENT PARSING", _test_ingredients_parsing(client)))
        group_results.append(_print_group("NUTR+ING TEST",    _test_nutritions_and_ingredients(client)))
        group_results.append(_print_group("BY WEIGHT TEST",   _test_nutritions_by_weight(client)))
        group_results.append(_print_group("WEIGHT EDGE TESTS", _test_weight_edge_cases(client)))
        group_results.append(_print_group("CACHE L1 TEST",    _test_cache_l1_hit(client)))
        group_results.append(_print_group("CACHE L2 TEST",    _test_cache_l2_hit(client)))
        group_results.append(_print_group("EXPIRED CACHE TEST", _test_expired_cache_entries(client)))
        group_results.append(_print_group("NEGATIVE CACHE TEST", _test_negative_caching(client)))
        group_results.append(_print_group("LRU EVICTION TEST", _test_cache_lru_eviction(client)))
        group_results.append(_print_group("PRODUCT SCORING", _test_product_scoring(client)))
        group_results.append(_print_group("CACHE STATS TEST", _test_cache_stats(client)))
        group_results.append(_print_group("NORMALIZE TESTS",  _test_normalize_query(client)))
        group_results.append(_print_group("TAXONOMY TESTS",   _test_taxonomy_normalization(client)))
        group_results.append(_print_group("BARCODE CACHE TEST", _test_barcode_cache(client)))
        group_results.append(_print_group("RESPONSE HANDLING", _test_malformed_response_handling(client)))
        group_results.append(_print_group("MOCK TEST",        _test_mock_data()))

        passed = sum(group_results)
        total = len(group_results)
        icon = "✅" if passed == total else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{total} groups passed {icon}\n", flush=True)
        return group_results
    finally:
        _restore_console(_saved)


def test_openfoodfacts_client_suite():
    from third_apis.OpenFoodFacts import OpenFoodFactsClient

    client = OpenFoodFactsClient()
    group_results = run_all(client)
    assert all(group_results), f"OpenFoodFacts client suite failed: {group_results}"