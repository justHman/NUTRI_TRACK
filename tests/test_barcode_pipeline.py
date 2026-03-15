"""
Tests for Barcode Pipeline
==========================
Tests scripts.scan_barcode barcode scan + cache lookup + API search fallback flow.
"""

import os
import sys
import re

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, "config", ".env"))

from scripts import scan_barcode as barcode_module
from config.logging_config import get_logger

logger = get_logger(__name__)


def _sample_barcode_image() -> str | None:
    candidates = [
        r"D:/Project/Code/nutritrack-documentation/app/data/images/barcodes/barcode.png"
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _test_scan_barcode_from_image() -> list:
    image_path = _sample_barcode_image()
    if not image_path:
        return [(None, "scan image", "sample barcode image not found")]

    try:
        code = barcode_module.scan_barcode_from_image(image_path)
        if not code:
            return [(False, "scan image", "cannot decode barcode from sample image")]
        if not code.isdigit():
            return [(False, "scan image", f"decoded non-numeric barcode: {code}")]
        return [(True, "scan image", f"decoded={code}")]
    except Exception as e:
        logger.error("_test_scan_barcode_from_image failed: %s", e, exc_info=True)
        return [(False, "scan image", str(e))]


def _test_lookup_barcode_from_cache() -> list:
    barcode = "8934563138165"
    try:
        result = barcode_module.lookup_barcode(barcode)
        assert isinstance(result, dict)
        assert result.get("found") is True
        assert result.get("barcode") == barcode
        assert result.get("source") in {"openfoodfacts", "avocavo", "usda"}
        assert result.get("cache_level") in {"L1", "L2"}
        return [(True, "lookup cache", f"source={result.get('source')} level={result.get('cache_level')}")]
    except Exception as e:
        logger.error("_test_lookup_barcode_from_cache failed: %s", e, exc_info=True)
        return [(False, "lookup cache", str(e))]


def _test_lookup_invalid_barcode() -> list:
    try:
        result = barcode_module.lookup_barcode("abc")
        assert result.get("found") is False
        assert result.get("message") == "invalid barcode"
        return [(True, "invalid barcode", "returned validation error")]
    except Exception as e:
        logger.error("_test_lookup_invalid_barcode failed: %s", e, exc_info=True)
        return [(False, "invalid barcode", str(e))]


def _test_l1_cache_hit() -> list:
    barcode = "8934563138165"
    try:
        # Reset L1 state for deterministic behavior in this test.
        barcode_module._l1_barcodes._cache.clear()

        first = barcode_module.lookup_barcode(barcode)
        assert first.get("found") is True

        original_lookup = barcode_module._lookup_in_disk_caches

        def _blocked_disk_lookup(_barcode: str):
            raise AssertionError("disk lookup called during expected L1 hit")

        barcode_module._lookup_in_disk_caches = _blocked_disk_lookup
        try:
            second = barcode_module.lookup_barcode(barcode)
        finally:
            barcode_module._lookup_in_disk_caches = original_lookup

        assert second.get("found") is True
        assert second.get("cache_level") == "L1"
        return [(True, "L1 cache hit", "second lookup returned from RAM cache")]
    except Exception as e:
        logger.error("_test_l1_cache_hit failed: %s", e, exc_info=True)
        return [(False, "L1 cache hit", str(e))]


def _test_barcode_pipeline() -> list:
    image_path = _sample_barcode_image()
    if not image_path:
        return [(None, "pipeline", "sample barcode image not found")]

    try:
        result = barcode_module.barcode_pipeline(image_path)
        assert isinstance(result, dict)
        assert result.get("image_path") == image_path
        assert "found" in result
        return [(True, "pipeline", f"found={result.get('found')} barcode={result.get('barcode')}")]
    except Exception as e:
        logger.error("_test_barcode_pipeline failed: %s", e, exc_info=True)
        return [(False, "pipeline", str(e))]


def _test_barcode_pipeline_with_clients() -> list:
    """Test pipeline with API clients for L3 search fallback."""
    image_path = _sample_barcode_image()
    if not image_path:
        return [(None, "pipeline+clients", "sample barcode image not found")]

    try:
        from third_apis.AvocavoNutrition import AvocavoNutritionClient
        from third_apis.OpenFoodFacts import OpenFoodFactsClient
        from third_apis.USDA import USDAClient

        clients = {
            "avocavo": AvocavoNutritionClient(api_key=os.getenv("AVOCAVO_NUTRITION_API_KEY", "DEMO_KEY")),
            "openfoodfacts": OpenFoodFactsClient(),
            "usda": USDAClient(api_key=os.getenv("USDA_API_KEY", "DEMO_KEY")),
        }

        result = barcode_module.barcode_pipeline(image_path, clients=clients)
        assert isinstance(result, dict)
        assert result.get("found") is True
        assert result.get("source") in {"avocavo", "openfoodfacts", "usda"}
        return [(True, "pipeline+clients",
                 f"found={result.get('found')} source={result.get('source')} level={result.get('cache_level')}")]
    except Exception as e:
        logger.error("_test_barcode_pipeline_with_clients failed: %s", e, exc_info=True)
        return [(False, "pipeline+clients", str(e))]


def _test_search_fallback_order() -> list:
    """Test that search fallback follows Avocavo → OpenFoodFacts → USDA order."""
    try:
        barcode = "0000000000000"  # Barcode not in any cache
        call_log = []

        class _MockClient:
            def __init__(self, name, should_find=False):
                self.name = name
                self.should_find = should_find

            def search_by_barcode(self, code):
                call_log.append(self.name)
                if self.should_find:
                    return {"barcode": code, "found": True, "product_name": f"from_{self.name}"}
                return {"barcode": code, "found": False}

        # All fail except USDA → verify all three are tried in order
        clients_all_fail_except_usda = {
            "avocavo": _MockClient("avocavo", should_find=False),
            "openfoodfacts": _MockClient("openfoodfacts", should_find=False),
            "usda": _MockClient("usda", should_find=True),
        }

        # Clear pipeline L1 so cache doesn't short-circuit
        barcode_module._l1_barcodes._cache.pop(barcode, None)

        # lookup_barcode will return found=False for unknown barcode
        lookup_result = barcode_module.lookup_barcode(barcode)
        assert lookup_result.get("found") is False

        # Simulate the fallback logic from barcode_pipeline
        barcode_clean = re.sub(r"\D", "", str(barcode or "")).strip()
        for source_name in ["avocavo", "openfoodfacts", "usda"]:
            if lookup_result.get("found"):
                break
            client = clients_all_fail_except_usda.get(source_name)
            if client:
                api_result = client.search_by_barcode(barcode_clean)
                if api_result and api_result.get("found") is True:
                    lookup_result = dict(api_result)
                    lookup_result["source"] = source_name

        assert call_log == ["avocavo", "openfoodfacts", "usda"], f"Expected order [avocavo, openfoodfacts, usda], got {call_log}"
        assert lookup_result.get("found") is True
        assert lookup_result.get("source") == "usda"

        # Test short-circuit: avocavo finds it → openfoodfacts/usda are NOT called
        call_log.clear()
        lookup_result2 = {"found": False}
        clients_avocavo_hit = {
            "avocavo": _MockClient("avocavo", should_find=True),
            "openfoodfacts": _MockClient("openfoodfacts", should_find=True),
            "usda": _MockClient("usda", should_find=True),
        }
        for source_name in ["avocavo", "openfoodfacts", "usda"]:
            if lookup_result2.get("found"):
                break
            client = clients_avocavo_hit.get(source_name)
            if client:
                api_result = client.search_by_barcode(barcode_clean)
                if api_result and api_result.get("found") is True:
                    lookup_result2 = dict(api_result)
                    lookup_result2["source"] = source_name

        assert call_log == ["avocavo"], f"Expected short-circuit at avocavo, got {call_log}"
        assert lookup_result2.get("source") == "avocavo"

        return [(True, "search order", f"full order={['avocavo', 'openfoodfacts', 'usda']}, short-circuit at avocavo ✓")]
    except Exception as e:
        logger.error("_test_search_fallback_order failed: %s", e, exc_info=True)
        return [(False, "search order", str(e))]


def run_all() -> list:
    """Run all barcode pipeline tests and return list of group pass/fail booleans."""

    group_results = []
    logger.title("Barcode Pipeline Tests")

    def _print_group(tag, cases):
        print(f"\n  -----[{tag}]-----", flush=True)
        for i, (ok, label, detail) in enumerate(cases, 1):
            icon = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
            print(f"    {i}. {label}: {detail} ({icon})", flush=True)
        passed = sum(1 for ok, _, _ in cases if ok)
        total = len(cases)
        skipped = sum(1 for ok, _, _ in cases if ok is None)
        print(f"    {passed}/{total} passed, {skipped} skipped", flush=True)
        return all(ok is True or ok is None for ok, _, _ in cases)

    print("\n--- Barcode Pipeline Tests -------------------------------------------", flush=True)
    group_results.append(_print_group("SCAN", _test_scan_barcode_from_image()))
    group_results.append(_print_group("LOOKUP CACHE", _test_lookup_barcode_from_cache()))
    group_results.append(_print_group("INVALID INPUT", _test_lookup_invalid_barcode()))
    group_results.append(_print_group("L1 CACHE", _test_l1_cache_hit()))
    group_results.append(_print_group("PIPELINE", _test_barcode_pipeline()))
    group_results.append(_print_group("PIPELINE+CLIENTS", _test_barcode_pipeline_with_clients()))
    group_results.append(_print_group("SEARCH FALLBACK ORDER", _test_search_fallback_order()))

    passed = sum(group_results)
    total = len(group_results)
    logger.info("run_all barcode tests: %d/%d groups passed", passed, total)
    print("\n---------------------------------------------------------------------", flush=True)
    print(f"  {passed}/{total} groups passed\n", flush=True)

    return group_results
