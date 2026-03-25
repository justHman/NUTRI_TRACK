"""
Tests for USDA Client
======================
Tests the USDA FoodData Central API client: search, nutrition, ingredients, caching.
"""

import os
import sys
import time
import logging as _stdlib_logging

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)


# ── Console-silence helpers ──────────────────────────────────────────────────
# Temporarily raise the root StreamHandler to WARNING so library INFO/DEBUG logs
# (third_apis.USDA, models, etc.) stay in the log file only during test runs.

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
    {"query": "chicken breast", "expect_calories_gt": 100},
    {"query": "white rice cooked", "expect_calories_gt": 80},
    {"query": "egg fried", "expect_calories_gt": 100},
    {"query": "cơm tấm", "expect_calories_gt": 0},  # Vietnamese — tests normalize
]


# ── Individual test functions ─────────────────────────────────────────────────
# Each returns list of (ok: bool|None, label: str, detail: str) — one tuple per case.

def _test_get_nutritions(usda_client) -> list:
    """Tests all QUERIES. Returns list of (ok, label, detail) per query."""
    results = []
    for q in QUERIES:
        query, expect_gt = q["query"], q["expect_calories_gt"]
        try:
            r = usda_client.get_nutritions(query)
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


def _test_get_ingredients(usda_client) -> list:
    query = "chocolate"
    try:
        r = usda_client.get_ingredients(query)
        if r is not None:
            assert isinstance(r, list) and all(isinstance(i, str) for i in r)
            return [(True, f"'{query}'", f"{len(r)} items: {r[:3]}")]
        return [(True, f"'{query}'", "None (no data — acceptable)")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_nutritions_and_ingredients(usda_client) -> list:
    query = "chicken breast"
    try:
        r = usda_client.get_nutritions_and_ingredients(query)
        if r is None:
            return [(False, f"'{query}'", "returned None")]
        assert isinstance(r, dict) and "nutritions" in r and "description" in r
        nut = r["nutritions"]
        for key in ("calories", "protein", "fat", "carbs"):
            assert key in nut
        return [(True, f"'{query}'",
                 f"desc='{r['description']}'  cal={nut['calories']:.1f}")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_nutritions_by_weight(usda_client) -> list:
    query, weight_g = "chicken breast", 150.0
    try:
        r = usda_client.get_nutritions_and_ingredients_by_weight(query, weight_g)
        if r is None:
            return [(False, f"'{query}' {weight_g:.0f}g", "returned None")]
        assert isinstance(r, dict) and "nutritions" in r and "weight_g" in r
        assert r["weight_g"] == weight_g
        nut = r["nutritions"]
        return [(True, f"'{query}' {weight_g:.0f}g",
                 f"cal={nut['calories']:.1f}  pro={nut['protein']:.1f}"
                 f"  fat={nut['fat']:.1f}  carb={nut['carbs']:.1f}")]
    except Exception as e:
        return [(False, f"'{query}' {weight_g:.0f}g", str(e))]


def _test_cache_l1_hit(usda_client) -> list:
    query = "chicken breast"
    try:
        usda_client.get_nutritions(query)  # warm up
        start = time.time()
        r = usda_client.get_nutritions(query)
        elapsed = time.time() - start
        assert isinstance(r, dict)
        return [(True, f"'{query}'", f"{elapsed:.4f}s")]
    except Exception as e:
        return [(False, f"'{query}'", str(e))]


def _test_cache_l2_hit(usda_client) -> list:
    try:
        from third_apis.USDA import _l2, _l1_foods, get_now_ts, _MISSING, USDAClient
        query = "__l2test_chicken__"
        fake_food = {
            "fdcId": 999999, "description": "Test Chicken L2", "score": 100.0,
            "foodNutrients": [
                {"nutrientNumber": "208", "unitName": "KCAL", "value": 165.0},
                {"nutrientNumber": "203", "unitName": "G",    "value": 31.0},
                {"nutrientNumber": "204", "unitName": "G",    "value": 3.6},
                {"nutrientNumber": "205", "unitName": "G",    "value": 0.0},
            ],
        }
        _l2["foods"][query] = {
            "food": fake_food,
            "found": True,
            "message": "ingredient found",
            "_ts": get_now_ts(),
        }
        USDAClient.clear_l1_cache()
        assert _l1_foods.get(query) is _MISSING
        start = time.time()
        r = usda_client.search_best(query)
        elapsed = time.time() - start
        assert r is not None and r.get("description") == "Test Chicken L2"
        l1_val = _l1_foods.get(query)
        assert l1_val is not _MISSING and l1_val.get("description") == "Test Chicken L2"
        return [(True, "synthetic inject+promote", f"{elapsed:.4f}s  L1 promoted ✓")]
    except Exception as e:
        return [(False, "synthetic inject+promote", str(e))]
    finally:
        from third_apis.USDA import _l2, USDAClient
        _l2["foods"].pop("__l2test_chicken__", None)
        USDAClient.clear_l1_cache()


def _test_mock_data() -> list:
    """Tests 3 queries against DEMO_KEY client — each should return mock fallback data."""
    from third_apis.USDA import USDAClient
    mock_client = USDAClient(api_key="DEMO_KEY")
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


def _test_cache_stats(usda_client) -> list:
    try:
        s = usda_client.cache_stats()
        assert isinstance(s, dict)
        for key in ("l1_entries", "l1_maxsize", "l2_entries", "l2_expired", "l2_file", "ttl_days"):
            assert key in s
        return [(True, "cache_stats()",
                 f"L1={s['l1_entries']}/{s['l1_maxsize']}  L2={s['l2_entries']} (expired={s['l2_expired']})")]
    except Exception as e:
        return [(False, "cache_stats()", str(e))]


def _test_normalize_query(usda_client) -> list:
    """Tests all normalization cases. Returns one (ok, label, detail) per case."""
    from utils.transformer import normalize_query
    cases = [
        ("Chicken Breast", "chicken breast"),
        ("  white rice  ", "white rice"),
        ("cơm tấm",        "com tam"),
        ("phở bò",         "pho bo"),
        ("egg (fried)",    "egg"),
        ("fish-sauce",     "fish sauce"),
        ("",               ""),
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


def _test_search_by_barcode(usda_client) -> list:
    """Test search_by_barcode() returns streamlined response format."""
    cases = [
        ("8934563138165", "found=False"),  # numeric barcode not in USDA
        ("abc",           "invalid"),      # non-numeric -> validation error
        ("",              "invalid"),      # empty -> validation error
        ("  123456789  ", "found=False"),  # numeric barcode not in USDA
        ("000000000000", "found=False")    # numeric barcode not in USDA
    ]
    results = []

    for code, expected_type in cases:
        try:
            result = usda_client.search_by_barcode(code)

            # All responses should be dict with consistent format
            assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
            assert "food" in result
            assert "found" in result and isinstance(result["found"], bool)
            assert "message" in result

            if expected_type == "invalid":
                # Invalid barcode should return validation error
                assert result["found"] is False
                assert result["food"] is None
                assert result["message"] == "invalid barcode"
                results.append((True, f"'{code}'", "invalid barcode -> found=False"))
                continue

            # Numeric barcode: should return valid response structure
            if result["found"]:
                assert result["food"] is not None
                assert result["message"] == "product found"
                assert isinstance(result["food"], dict)
                # Should have product info specific to USDA
                expected_fields = ["barcode", "description", "nutritions", "fdcId"]
                found_fields = [field for field in expected_fields if field in result["food"]]
                assert len(found_fields) > 0, f"Expected at least one of {expected_fields}"
                results.append((True, f"'{code}'", f"found=True, food has {found_fields}"))
            else:
                assert result["food"] is None or isinstance(result["food"], dict)
                if isinstance(result["food"], dict):
                    assert result["food"].get("barcode") == code
                assert "not found" in result["message"].lower() or "0 results" in result["message"].lower()
                results.append((True, f"'{code}'", "found=False (no USDA data)"))

        except Exception as e:
            results.append((False, f"'{code}'", str(e)))

    return results


def _test_barcode_cache(usda_client) -> list:
    """Test L2->L1 promotion and L1 hit behavior for search_by_barcode()."""
    results = []
    from third_apis import USDA as usda_module
    from third_apis.USDA import _l1_barcodes, _l2, get_now_ts, _MISSING, USDAClient

    barcode = "8934563138166"

    try:
        # L2 hit should promote to L1
        fake_l2_food = {
            "barcode": barcode,
            "description": "Barcode L2 USDA Test Food",
            "fdcId": 789012,
            "nutritions": {"calories": 165.0, "protein": 31.0, "fat": 3.6, "carbs": 0.0},
        }
        _l2["barcodes"][barcode] = {
            "food": fake_l2_food,
            "found": True,
            "message": "product found",
            "_ts": get_now_ts(),
        }
        USDAClient.clear_l1_cache()
        assert _l1_barcodes.get(barcode) is _MISSING

        # Test L2 -> L1 promotion
        got_l2 = usda_client.search_by_barcode(barcode)
        assert isinstance(got_l2, dict)
        assert got_l2["found"] is True
        assert got_l2["food"] == fake_l2_food
        assert got_l2["message"] == "product found"

        # Verify L1 promotion
        promoted = _l1_barcodes.get(barcode)
        assert promoted is not _MISSING
        assert promoted == fake_l2_food
        results.append((True, "L2->L1 promotion", "barcode cache promoted successfully"))

        # L1 hit should not call network
        fake_l1_food = {
            "barcode": barcode,
            "description": "Barcode L1 USDA Test Food",
            "fdcId": 789013,
            "nutritions": {"calories": 165.0, "protein": 31.0, "fat": 3.6, "carbs": 0.0},
        }
        _l1_barcodes.set(barcode, fake_l1_food)
        original_get = usda_module.requests.get

        def _blocked_get(*args, **kwargs):
            raise AssertionError("network called during L1 cache hit")

        usda_module.requests.get = _blocked_get
        try:
            got_l1 = usda_client.search_by_barcode(barcode)
            assert isinstance(got_l1, dict)
            assert got_l1["found"] is True
            assert got_l1["food"] == fake_l1_food
            assert got_l1["message"] == "product found"
            results.append((True, "L1 hit no network", "returned from RAM cache"))
        finally:
            usda_module.requests.get = original_get

    except Exception as e:
        results.append((False, "barcode cache", str(e)))
    finally:
        _l2["barcodes"].pop(barcode, None)
        USDAClient.clear_l1_cache()

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all(usda_client) -> list:
    """Run all USDA client tests.

    Args:
        usda_client: Pre-initialized USDAClient instance

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
        print("\n─── USDA Client Tests ─────────────────────────────────────────────────", flush=True)
        group_results.append(_print_group("NUTRITION TESTS",  _test_get_nutritions(usda_client)))
        group_results.append(_print_group("INGREDIENTS TEST", _test_get_ingredients(usda_client)))
        group_results.append(_print_group("NUTR+ING TEST",    _test_nutritions_and_ingredients(usda_client)))
        group_results.append(_print_group("BY WEIGHT TEST",   _test_nutritions_by_weight(usda_client)))
        group_results.append(_print_group("CACHE L1 TEST",    _test_cache_l1_hit(usda_client)))
        group_results.append(_print_group("CACHE STATS TEST", _test_cache_stats(usda_client)))
        group_results.append(_print_group("NORMALIZE TESTS",  _test_normalize_query(usda_client)))
        group_results.append(_print_group("BARCODE TEST",     _test_search_by_barcode(usda_client)))
        group_results.append(_print_group("BARCODE CACHE TEST", _test_barcode_cache(usda_client)))
        group_results.append(_print_group("CACHE L2 TEST",    _test_cache_l2_hit(usda_client)))
        group_results.append(_print_group("MOCK TEST",        _test_mock_data()))

        passed = sum(group_results)
        total = len(group_results)
        icon = "✅" if passed == total else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{total} groups passed {icon}\n", flush=True)
        return group_results
    finally:
        _restore_console(_saved)


def test_usda_client_suite():
    from third_apis.USDA import USDAClient

    client = USDAClient(api_key=os.getenv("USDA_API_KEY", "DEMO_KEY"))
    group_results = run_all(client)
    assert all(group_results), f"USDA client suite failed: {group_results}"
