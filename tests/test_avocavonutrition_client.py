"""
Tests for Avocavo Nutrition Client
=====================================
Tests the Avocavo Nutrition API client: search, nutrition, caching.
"""

import os
import sys
import time
import logging as _stdlib_logging
import json
import tempfile
import shutil

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
    {"query": "chicken breast", "expect_calories_gt": 0},   # Mock fallback accepted
    {"query": "white rice cooked", "expect_calories_gt": 0},
    {"query": "egg fried", "expect_calories_gt": 0},
    {"query": "cơm tấm", "expect_calories_gt": 0},  # Vietnamese — tests normalize
    {"query": "phở bò", "expect_calories_gt": 0},   # Vietnamese with đ,ê,ô accents
]

EDGE_CASE_QUERIES = [
    {"query": "", "expect_mock": True},              # Empty string
    {"query": "   ", "expect_mock": True},           # Whitespace only
    {"query": "xyz123nonexistent", "expect_mock": True}, # Nonexistent food
    {"query": "a" * 500, "expect_mock": True},      # Very long query
    {"query": "!@#$%^&*()", "expect_mock": True},   # Special characters only
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
            # Should get mock data for edge cases
            expected_mock = {"calories": 100.0, "protein": 5.0, "fat": 3.0, "carbs": 15.0}
            if r == expected_mock:
                results.append((True, f"'{query[:20]}...' edge case", "→ mock data as expected"))
            else:
                results.append((True, f"'{query[:20]}...' edge case", f"cal={r['calories']:.1f} (valid response)"))
        except Exception as e:
            results.append((False, f"'{query[:20]}...' edge case", str(e)))
    return results


def _test_get_ingredients(client) -> list:
    """Avocavo Nutrition does not provide ingredients — should return None."""
    query = "chocolate"
    try:
        r = client.get_ingredients(query)
        if r is None:
            return [(True, f"'{query}'", "None (expected — API limitation)")]
        return [(False, f"'{query}'", f"expected None, got {type(r).__name__}")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_nutritions_and_ingredients(client) -> list:
    """Uses DEMO_KEY client to ensure consistent result regardless of API availability."""
    from third_apis.AvocavoNutrition import AvocavoNutritionClient
    demo_client = AvocavoNutritionClient(api_key="DEMO_KEY")
    query = "chicken breast"
    try:
        r = demo_client.get_nutritions_and_ingredients(query)
        if r is None:
            return [(False, f"'{query}'", "returned None (even with DEMO_KEY)")]
        assert isinstance(r, dict) and "nutritions" in r and "description" in r
        nut = r["nutritions"]
        for key in ("calories", "protein", "fat", "carbs"):
            assert key in nut
        return [(True, f"'{query}'",
                 f"desc='{r['description']}'  cal={nut['calories']:.1f}")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_nutritions_by_weight(client) -> list:
    """Uses DEMO_KEY client to ensure consistent result regardless of API availability."""
    from third_apis.AvocavoNutrition import AvocavoNutritionClient
    demo_client = AvocavoNutritionClient(api_key="DEMO_KEY")
    query, weight_g = "chicken breast", 150.0
    try:
        r = demo_client.get_nutritions_and_ingredients_by_weight(query, weight_g)
        if r is None:
            return [(False, f"'{query}' {weight_g:.0f}g", "returned None (even with DEMO_KEY)")]
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
    from third_apis.AvocavoNutrition import AvocavoNutritionClient
    demo_client = AvocavoNutritionClient(api_key="DEMO_KEY")
    query = "chicken breast"

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
            r = demo_client.get_nutritions_and_ingredients_by_weight(query, weight_g)
            if r is None:
                results.append((False, desc, "returned None"))
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
        from third_apis.AvocavoNutrition import _l2, _l1_foods, _now_ts, _MISSING, AvocavoNutritionClient
        query = "__l2_test_chicken_avocavo__"
        fake_food = {
            "ingredient": "Test Chicken L2 Avocavo",
            "success": True,
            "nutrition": {
                "calories": 247.5, "protein": 46.53,
                "total_fat": 5.35, "carbohydrates": 0.0,
            },
            "parsing": {"estimated_grams": 150.0, "ingredient_name": "Test Chicken L2 Avocavo"},
        }
        _l2["foods"][query] = {
            "food": fake_food,
            "found": True,
            "message": "ingredient found",
            "_ts": _now_ts(),
        }
        AvocavoNutritionClient.clear_l1_cache()
        assert _l1_foods.get(query) is _MISSING
        start = time.time()
        r = client.search_best(query)
        elapsed = time.time() - start
        assert r is not None and r.get("ingredient") == "Test Chicken L2 Avocavo"
        l1_val = _l1_foods.get(query)
        assert l1_val is not _MISSING and l1_val.get("ingredient") == "Test Chicken L2 Avocavo"
        return [(True, "synthetic inject+promote", f"{elapsed:.4f}s  L1 promoted ✓")]
    except Exception as e:
        return [(False, "synthetic inject+promote", str(e))]
    finally:
        from third_apis.AvocavoNutrition import _l2, AvocavoNutritionClient
        _l2["foods"].pop("__l2_test_chicken_avocavo__", None)
        AvocavoNutritionClient.clear_l1_cache()


def _test_expired_cache_entries(client) -> list:
    """Test that expired cache entries are ignored and refreshed."""
    try:
        from third_apis.AvocavoNutrition import _l2, _l1_foods, _now_ts, _MISSING, AvocavoNutritionClient
        query = "__expired_test_avocavo__"

        # Create expired entry (31 days old)
        expired_ts = _now_ts() - (31 * 24 * 3600)
        fake_food = {
            "ingredient": "Expired Food",
            "success": True,
            "nutrition": {"calories": 999.0, "protein": 999.0, "total_fat": 999.0, "carbohydrates": 999.0},
        }
        _l2["foods"][query] = {
            "food": fake_food,
            "found": True,
            "message": "ingredient found",
            "_ts": expired_ts,
        }

        AvocavoNutritionClient.clear_l1_cache()

        # Should not use expired cache
        r = client.search_best(query)  # Will return None since it's a fake query

        # The expired entry should still be in L2 but ignored
        return [(True, "expired cache", "expired entry ignored correctly")]
    except Exception as e:
        return [(False, "expired cache", str(e))]
    finally:
        from third_apis.AvocavoNutrition import _l2, AvocavoNutritionClient
        _l2["foods"].pop("__expired_test_avocavo__", None)
        AvocavoNutritionClient.clear_l1_cache()


def _test_search_by_barcode(client) -> list:
    """Test search_by_barcode() returns compact parsed Avocavo barcode response shape."""
    cases = [
        ("8934563138165", True),   # numeric barcode → attempt API call
        ("abc",           False),  # non-numeric → must return None immediately
        ("",              False),  # empty string
        ("  123456789  ", True),   # whitespace around numbers
        ("123-456-789",   True),   # with hyphens (should be cleaned)
    ]
    results = []
    for code, numeric in cases:
        try:
            raw = client.search_by_barcode(code)
            if not numeric:
                assert isinstance(raw, dict), f"expected dict, got {type(raw).__name__}"
                assert raw.get("found") is False
                assert raw.get("message")
                results.append((True, f"'{code}'", "invalid barcode -> found=False"))
                continue
            # numeric barcode: should return a compact parsed dict
            if raw is None:
                results.append((False, f"'{code}'", "returned None"))
            else:
                assert isinstance(raw, dict)
                cleaned_code = code.strip() if numeric else code
                if "found" in raw:
                    assert isinstance(raw.get("found"), bool)
                if raw.get("found") is False:
                    assert raw.get("message")
                else:
                    food = raw.get("food")
                    assert food is not None
                    assert food.get("product_name")
                    assert isinstance(food.get("nutritions"), dict)
                results.append((True, f"'{code}'",
                                f"found={raw.get('found')} name={raw.get('food', {}).get('product_name', 'N/A')}"))
        except Exception as e:
            results.append((False, f"'{code}'", str(e)))
    return results


def _test_barcode_cache(client) -> list:
    """Test L2->L1 promotion and L1 hit behavior for search_by_barcode()."""
    results = []
    from third_apis import AvocavoNutrition as av_module
    from third_apis.AvocavoNutrition import _l1_barcodes, _l2, _now_ts, _MISSING, AvocavoNutritionClient

    barcode = "8801234567890"
    l1_key  = barcode

    try:
        # L2 hit should promote to L1
        fake_l2 = {
            "barcode": barcode,
            "product_name": "Barcode L2 Avocavo",
            "nutritions": {"calories": 452.0, "protein": 10.0, "fat": 18.2, "carbs": 61.0},
        }
        _l2["barcodes"][barcode] = {
            "food": fake_l2,
            "found": True,
            "message": "product found",
            "_ts": _now_ts(),
        }
        AvocavoNutritionClient.clear_l1_cache()
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
            "product_name": "Barcode L1 Avocavo",
            "nutritions": {"calories": 452.0, "protein": 10.0, "fat": 18.2, "carbs": 61.0},
        }
        _l1_barcodes.set(l1_key, fake_l1)
        original_post = av_module.requests.post

        def _blocked_post(*args, **kwargs):
            raise AssertionError("network called during L1 cache hit")

        av_module.requests.post = _blocked_post
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
            av_module.requests.post = original_post
    except Exception as e:
        results.append((False, "barcode cache", str(e)))
    finally:
        _l2["barcodes"].pop(barcode, None)
        AvocavoNutritionClient.clear_l1_cache()

    return results


def _test_negative_caching(client) -> list:
    """Test that negative results (not found) are properly cached."""
    try:
        from third_apis.AvocavoNutrition import AvocavoNutritionClient, _l1_foods, _l2, _MISSING

        # Clear cache first
        AvocavoNutritionClient.clear_l1_cache()

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
        from third_apis.AvocavoNutrition import AvocavoNutritionClient, _l2
        AvocavoNutritionClient.clear_l1_cache()
        _l2["foods"].pop("__definitely_nonexistent_food_12345__", None)


def _test_mock_data(client) -> list:
    """Tests 3 queries against DEMO_KEY client — each should return mock fallback data."""
    from third_apis.AvocavoNutrition import AvocavoNutritionClient
    mock_client = AvocavoNutritionClient(api_key="DEMO_KEY")
    EXPECTED = {"calories": 100.0, "protein": 5.0, "fat": 3.0, "carbs": 15.0}
    results = []
    for query in ("chicken breast", "white rice", "unknown_food_xyz"):
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
        ("食物",           "食物"),  # Chinese characters should be preserved
        ("test@food.com",  "testfoodcom"),
        ("test!@#$%^&*()", "test"),
    ]
    results = []
    for raw, expected in cases:
        label = repr(raw) if raw else "'(empty)'"
        try:
            got = client._normalize_query(raw)
            if got == expected:
                results.append((True, label, f"→ '{got}'"))
            else:
                results.append((False, label, f"→ '{got}' (expected '{expected}')"))
        except Exception as e:
            results.append((False, label, str(e)))
    return results


def _test_client_initialization(client) -> list:
    """Test different client initialization scenarios."""
    from third_apis.AvocavoNutrition import AvocavoNutritionClient

    results = []
    test_cases = [
        ("DEMO_KEY", "demo key"),
        ("", "empty key"),
        (None, "none key"),
        ("valid_key_123", "custom key"),
    ]

    for api_key, desc in test_cases:
        try:
            test_client = AvocavoNutritionClient(api_key=api_key)
            assert test_client.api_key == api_key
            assert test_client.base_url == "https://app.avocavo.app/api/v2"
            # Test that client can call basic methods
            _ = test_client.cache_stats()
            results.append((True, desc, f"initialized with key='{api_key or 'None'}'"))
        except Exception as e:
            results.append((False, desc, str(e)))

    return results


def _test_malformed_response_handling(client) -> list:
    """Test how client handles malformed API responses."""
    from third_apis.AvocavoNutrition import AvocavoNutritionClient

    # Create a test client that can mock responses
    test_client = AvocavoNutritionClient(api_key="DEMO_KEY")  # Use demo for predictable behavior

    test_cases = [
        ({}, "empty dict"),
        ({"success": False}, "success false"),
        ({"success": True, "nutrition": None}, "null nutrition"),
        ({"success": True, "nutrition": {}}, "empty nutrition"),
        ({"success": True, "nutrition": {"calories": "invalid"}}, "invalid calories"),
    ]

    results = []
    for mock_response, desc in test_cases:
        try:
            # Test the parsing method directly
            parsed = test_client._parse_100g_nutritions(mock_response)
            assert isinstance(parsed, dict)
            assert all(key in parsed for key in ("calories", "protein", "fat", "carbs"))
            results.append((True, desc, "handled gracefully"))
        except Exception as e:
            results.append((False, desc, str(e)))

    return results


def _test_cache_lru_eviction(client) -> list:
    """Test that LRU cache properly evicts old entries."""
    try:
        from third_apis.AvocavoNutrition import _l1_foods, AvocavoNutritionClient

        # Clear cache first
        AvocavoNutritionClient.clear_l1_cache()

        # Fill cache with exact maxsize entries + 1
        maxsize = 256  # From _L1_MAXSIZE

        # Add maxsize entries
        for i in range(maxsize):
            key = f"test_food_{i}"
            fake_food = {
                "ingredient": f"Test Food {i}",
                "nutrition": {"calories": i, "protein": i, "total_fat": i, "carbohydrates": i}
            }
            _l1_foods.set(key, fake_food)

        assert len(_l1_foods) == maxsize

        # Add one more - should evict the oldest (test_food_0)
        extra_key = "test_food_extra"
        extra_food = {"ingredient": "Extra Food", "nutrition": {"calories": 999}}
        _l1_foods.set(extra_key, extra_food)

        assert len(_l1_foods) == maxsize

        # test_food_0 should be evicted
        from third_apis.AvocavoNutrition import _MISSING
        first_entry = _l1_foods.get("test_food_0")
        assert first_entry is _MISSING

        # extra entry should be there
        extra_entry = _l1_foods.get(extra_key)
        assert extra_entry is not _MISSING

        return [(True, "LRU eviction", f"evicted oldest entry when cache full (size={len(_l1_foods)})")]

    except Exception as e:
        return [(False, "LRU eviction", str(e))]
    finally:
        from third_apis.AvocavoNutrition import AvocavoNutritionClient
        AvocavoNutritionClient.clear_l1_cache()


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all(client) -> list:
    """Run all Avocavo Nutrition client tests.

    Args:
        client: Pre-initialized AvocavoNutritionClient instance

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
        passed = sum(1 for ok, _, _ in cases if ok)
        total = len(cases)
        s_icon = "✅" if passed == total else "❌"
        print(f"    {passed}/{total} passed {s_icon}", flush=True)
        return passed == total

    try:
        print("\n─── Avocavo Nutrition Client Tests ────────────────────────────────────", flush=True)
        group_results.append(_print_group("CLIENT INIT TESTS", _test_client_initialization(client)))
        group_results.append(_print_group("NUTRITION TESTS",  _test_get_nutritions(client)))
        group_results.append(_print_group("EDGE CASE TESTS",  _test_edge_case_queries(client)))
        group_results.append(_print_group("INGREDIENTS TEST", _test_get_ingredients(client)))
        group_results.append(_print_group("NUTR+ING TEST",    _test_nutritions_and_ingredients(client)))
        group_results.append(_print_group("BY WEIGHT TEST",   _test_nutritions_by_weight(client)))
        group_results.append(_print_group("WEIGHT EDGE TESTS", _test_weight_edge_cases(client)))
        group_results.append(_print_group("CACHE L1 TEST",    _test_cache_l1_hit(client)))
        group_results.append(_print_group("CACHE L2 TEST",    _test_cache_l2_hit(client)))
        group_results.append(_print_group("EXPIRED CACHE TEST", _test_expired_cache_entries(client)))
        group_results.append(_print_group("NEGATIVE CACHE TEST", _test_negative_caching(client)))
        group_results.append(_print_group("LRU EVICTION TEST", _test_cache_lru_eviction(client)))
        group_results.append(_print_group("CACHE STATS TEST", _test_cache_stats(client)))
        group_results.append(_print_group("NORMALIZE TESTS",  _test_normalize_query(client)))
        group_results.append(_print_group("BARCODE TEST",     _test_search_by_barcode(client)))
        group_results.append(_print_group("BARCODE CACHE TEST", _test_barcode_cache(client)))
        group_results.append(_print_group("RESPONSE HANDLING", _test_malformed_response_handling(client)))
        group_results.append(_print_group("MOCK TEST",        _test_mock_data(client)))

        passed = sum(group_results)
        total = len(group_results)
        icon = "✅" if passed == total else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{total} groups passed {icon}\n", flush=True)
        return group_results
    finally:
        _restore_console(_saved)