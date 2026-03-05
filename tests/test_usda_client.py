import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.logging_config import get_logger
from third_apis.USDA import USDAClient

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


def test_get_nutrition_mock(client: USDAClient):
    logger.title("Starting test: get_nutrition (mock fallback)")
    TEST_QUERIES = [
        "rice",
        "grilled pork",
        "",
    ]

    passed = 0
    failed = 0

    for query in TEST_QUERIES:
        result = client.get_nutrition(query)
        keys = ["calories", "protein", "fat", "carbs"]
        ok = all(k in result for k in keys)

        if ok:
            logger.info("✅ PASS | '%s' → %s", query, result)
            passed += 1
        else:
            logger.error("❌ FAIL | '%s' → %s (missing keys)", query, result)
            failed += 1

    logger.info("get_nutrition_mock results: total=%d, passed=%d, failed=%d", len(TEST_QUERIES), passed, failed)
    return failed == 0

def test_get_nutrition_real(client: USDAClient):
    logger.title("Starting test: get_nutrition (real data)")
    TEST_QUERIES = [
        "rice",
        "grilled pork",
        "pho",
        "com tam",
        "bún chả",
        "Chả lụa",
        "bánh tét",
        "bò (beef)",
        "",
    ]

    passed = 0
    failed = 0

    for query in TEST_QUERIES:
        result = client.get_nutrition(query)
        keys = ["calories", "protein", "fat", "carbs"]
        ok = all(k in result for k in keys)

        if ok:
            logger.info("✅ PASS | '%s' → %s", query, result)
            passed += 1
        else:
            logger.error("❌ FAIL | '%s' → %s (missing keys)", query, result)
            failed += 1

    logger.info("get_nutrition_real results: total=%d, passed=%d, failed=%d", len(TEST_QUERIES), passed, failed)
    return failed == 0

def test_caching(client: USDAClient):
    logger.title("Starting test: caching")
    query = "rice"
    client.cache.clear()
    logger.debug("Cache cleared")

    # Lần 1 → gọi _get_mock_nutrition
    result1 = client.get_nutrition(query)
    logger.debug("First call result: %s", result1)
    
    # Lần 2 → phải lấy từ cache
    result2 = client.get_nutrition(query)
    logger.debug("Second call result (should be cached): %s", result2)

    if result1 == result2 and query.lower() in client.cache:
        logger.info("✅ PASS | Cache working correctly for '%s'", query)
        return True
    else:
        logger.error("❌ FAIL | Cache not working for '%s' (result1=%s, result2=%s, in_cache=%s)",
                      query, result1, result2, query.lower() in client.cache)
        return False

def main():
    logger.title("NutriTrack USDA Client Test Suite")

    # Khởi tạo client với DEMO_KEY để ép fallback mock
    client = USDAClient(api_key="DEMO_KEY")

    all_passed = True

    all_passed &= test_normalize_query(client)
    all_passed &= test_get_nutrition_mock(client)
    all_passed &= test_get_nutrition_real(client)
    all_passed &= test_caching(client)

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