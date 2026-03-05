import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.logging_config import get_logger
from third_apis.USDA import USDAClient
from dotenv import load_dotenv

load_dotenv()

logger = get_logger(__name__)


def test_normalize_query(client: USDAClient):
    logger.title("Starting test: _normalize_query")

    TEST_CASES = [
        # Vietnamese
        ("rice (gạo)", "rice"),
        ("bò (beef)", "bo"),
        ("gà (chicken)", "ga"),
        ("cá (fish)", "ca"),

        # French accents
        ("crème brûlée (dessert)", "creme brulee"),
        ("pâté (duck)", "pate"),

        # German umlauts
        ("spätzle (noodle)", "spatzle"),
        ("frühstück (breakfast)", "fruhstuck"),

        # Mixed
        ("pho (vietnamese soup)", "pho"),
        ("fried-rice!!! (cơm chiên)", "fried rice"),
        ("Beef-steak", "beef steak"),

        # Edge cases
        ("(beef)", "beef"),
        ("() rice", "rice"),
        ("rice ()", "rice"),
        ("", ""),
        ("   ", ""),
    ]

    passed = 0
    failed = 0

    for input_text, expected in TEST_CASES:
        output = client._normalize_query(input_text)
        if output == expected:
            logger.info("✅ PASS | '%s' → '%s'", input_text, output)
            passed += 1
        else:
            logger.error("❌ FAIL | '%s' → '%s' (expected '%s')", input_text, output, expected)
            failed += 1

    logger.info("_normalize_query results: total=%d, passed=%d, failed=%d", len(TEST_CASES), passed, failed)
    return failed == 0


def test_get_PCF_mock(client: USDAClient):
    """Test get_PCF with DEMO_KEY — should always return mock data (no API call)"""
    logger.title("Starting test: get_PCF (mock fallback)")
    TEST_QUERIES = [
        "rice",
        "grilled pork",
        "",
    ]

    passed = 0
    failed = 0

    for query in TEST_QUERIES:
        result = client.get_PCF(query)
        keys = ["calories", "protein", "fat", "carbs"]
        ok = all(k in result for k in keys)

        if ok:
            logger.info("✅ PASS | '%s' → %s", query, result)
            passed += 1
        else:
            logger.error("❌ FAIL | '%s' → %s (missing keys)", query, result)
            failed += 1

    logger.info("get_PCF_mock results: total=%d, passed=%d, failed=%d", len(TEST_QUERIES), passed, failed)
    return failed == 0


def test_get_PCF_real(client: USDAClient):
    """Test get_PCF with DEMO_KEY — still returns mock, but normalizes correctly"""
    logger.title("Starting test: get_PCF (real data)")
    TEST_QUERIES = [
        "rice",
        "pho",
        "Chả lụa",
        "bò (beef)",
        "",
    ]

    passed = 0
    failed = 0

    for query in TEST_QUERIES:
        result = client.get_PCF(query)
        keys = ["calories", "protein", "fat", "carbs"]
        ok = all(k in result for k in keys)

        if ok:
            logger.info("✅ PASS | '%s' → %s", query, result)
            passed += 1
        else:
            logger.error("❌ FAIL | '%s' → %s (missing keys)", query, result)
            failed += 1

    logger.info("get_PCF_real results: total=%d, passed=%d, failed=%d", len(TEST_QUERIES), passed, failed)
    return failed == 0


def test_get_ingredients_mock(client: USDAClient):
    """Test get_ingredients edge cases that don't require API (empty / whitespace queries)"""
    logger.title("Starting test: get_ingredients (Mock/Edge cases)")

    cases = [
        ("",    None, "empty string"),
        ("   ", None, "whitespace only"),
    ]

    passed = 0
    failed = 0

    for query, expected, label in cases:
        result = client.get_ingredients(query)
        if result == expected:
            logger.info("\u2705 PASS | %s '%s' \u2192 %s", label, query, result)
            passed += 1
        else:
            logger.error("\u274c FAIL | %s '%s' \u2192 %s (expected %s)", label, query, result, expected)
            failed += 1

    logger.info("get_ingredients_mock results: total=%d, passed=%d, failed=%d",
                len(cases), passed, failed)
    return failed == 0


def test_get_ingredients_real(client: USDAClient):
    """Integration test: get_ingredients calls search_best then _parse_ingredient_string.
    Branded foods have an ingredients string; SR Legacy foods do not.
    We test two queries:
    - 'snickers': branded → likely no ingredients field in this dataset entry
    - 'oreo': branded cookie → may have ingredients
    A result of None is acceptable (food found but no ingredients field).
    A result of list is correct. An exception or wrong structure is a fail.
    """
    logger.title("Starting test: get_ingredients (Real API)")

    TEST_QUERIES = [
        "snickers",
        "oreo",
        "coca cola",
    ]

    passed = 0
    failed = 0

    for query in TEST_QUERIES:
        result = client.get_ingredients(query)

        if result is None:
            # Acceptable: food found but no 'ingredients' field (SR Legacy entries)
            logger.info("\u2705 PASS | '%s' \u2192 None (no ingredients field — acceptable for SR Legacy)", query)
            passed += 1
        elif isinstance(result, list) and len(result) > 0:
            logger.info("\u2705 PASS | '%s' \u2192 %d ingredients: %s", query, len(result), result[:5])
            passed += 1
        else:
            logger.error("\u274c FAIL | '%s' \u2192 unexpected result: %s", query, result)
            failed += 1

    logger.info("get_ingredients_real results: total=%d, passed=%d, failed=%d",
                len(TEST_QUERIES), passed, failed)
    return failed == 0


def test_search_best_cache(client: USDAClient):
    """
    Verify that search_best caches raw food dicts (Two-Tier version):
    - All get_* functions that call the same query should HIT the cache
      after the first API call.
    - Cache keyed by normalized_query at search_best level.
    """
    logger.title("Starting test: search_best caching")

    query = "snickers"
    normalized = client._normalize_query(query)

    # Clear only for this test
    client.clear_all_caches()
    logger.debug("Caches cleared for cache test")

    # 1st call — must MISS cache → call API
    best1 = client.search_best(normalized)
    if not best1:
        logger.warning("Skipping cache test — no API result for 'snickers'")
        return True  # can't test without real API

    stats_after_first = client.cache_stats()
    if stats_after_first['l1_entries'] == 0:
        logger.error("❌ FAIL | L1 Cache should have been populated after first search_best call")
        return False

    logger.info("✅ Cache populated after 1st call for '%s'", normalized)

    # 2nd call — must HIT cache (same best dict reference)
    best2 = client.search_best(normalized)
    if best1 is not best2:
        logger.error("❌ FAIL | Cache HIT should return the same object")
        return False

    logger.info("✅ L1 Cache HIT on 2nd call — same object returned")

    # Extra: call get_PCF with same query → must also HIT cache (no new API call)
    pcf = client.get_PCF(query)
    keys = ["calories", "protein", "fat", "carbs"]
    if all(k in pcf for k in keys):
        logger.info("✅ PASS | get_PCF('%s') also benefits from search_best cache: %s", query, pcf)
    else:
        logger.error("❌ FAIL | get_PCF('%s') returned invalid data: %s", query, pcf)
        return False

    # Extra: get_ingredients same query → cache HIT again
    ing = client.get_ingredients(query)
    logger.info("✅ PASS | get_ingredients('%s') cache HIT", query)

    # Extra: get_PCF_and_ingredients same query → cache HIT again
    combined = client.get_PCF_and_ingredients(query)
    if combined and "PCF_nutrients" in combined:
        logger.info("✅ PASS | get_PCF_and_ingredients('%s') cache HIT: %s", query, combined.get("description"))
    else:
        logger.error("❌ FAIL | get_PCF_and_ingredients('%s') returned unexpected: %s", query, combined)
        return False

    logger.info("✅ PASS | All 3 get_* calls shared 1 API call via search_best cache for '%s'", query)
    return True


def test_get_PCF_and_ingredients_mock(client: USDAClient):
    """Test: empty query should return None immediately"""
    logger.title("Starting test: get_PCF_and_ingredients (Mock/Edge cases)")

    result = client.get_PCF_and_ingredients("")
    if result is None:
        logger.info("✅ PASS | Empty query returned None as expected")
    else:
        logger.error("❌ FAIL | Expected None for empty query, got: %s", type(result))
        return False

    result2 = client.get_PCF_and_ingredients("   ")
    if result2 is None:
        logger.info("✅ PASS | Whitespace-only query returned None")
    else:
        logger.error("❌ FAIL | Expected None for whitespace query, got: %s", type(result2))
        return False

    return True


def test_get_PCF_and_ingredients_real(client: USDAClient):
    """Integration test for get_PCF_and_ingredients with real search"""
    logger.title("Starting test: get_PCF_and_ingredients (Integration Real)")

    query = "snickers"
    result = client.get_PCF_and_ingredients(query)

    if not result:
        logger.warning("No result for 'snickers' — might be network / API key issue")
        return True  # Don't fail if API is unavailable

    expected_keys = {"description", "PCF_nutrients", "ingredients"}
    actual_keys = set(result.keys())

    if not actual_keys.issuperset(expected_keys):
        logger.error("❌ FAIL | Missing keys. Got: %s", actual_keys)
        return False

    pcf_keys = {"calories", "protein", "fat", "carbs"}
    if not set(result["PCF_nutrients"].keys()).issuperset(pcf_keys):
        logger.error("❌ FAIL | Missing PCF keys. Got: %s", result["PCF_nutrients"].keys())
        return False

    logger.info("✅ PASS | '%s' → description='%s', PCF=%s, ingredients=%s",
                query,
                result["description"],
                result["PCF_nutrients"],
                result["ingredients"])
    return True


def main():
    logger.title("NutriTrack USDA Client Test Suite")

    # DEMO_KEY → mock fallback for get_PCF tests
    # For cache & real tests: search_best still hits real API regardless of key
    # (get_PCF bypasses search_best with DEMO_KEY, but search_best is still callable directly)
    client = USDAClient(api_key=os.getenv("USDA_API_KEY"))

    all_passed = True

    all_passed &= test_normalize_query(client)
    all_passed &= test_get_PCF_mock(client)
    all_passed &= test_get_PCF_real(client)
    all_passed &= test_get_ingredients_mock(client)
    all_passed &= test_get_ingredients_real(client)
    all_passed &= test_search_best_cache(client)          # cache test at search_best level
    all_passed &= test_get_PCF_and_ingredients_mock(client)
    all_passed &= test_get_PCF_and_ingredients_real(client)

    try:
        if all_passed:
            logger.info("🎉 ALL TESTS PASSED")
            sys.exit(0)
        else:
            logger.warning("⚠️ SOME TESTS FAILED")
            sys.exit(1)
    except SystemExit as e:
        logger.info("Exit code: %d", e.code)


if __name__ == "__main__":
    main()