"""
Unit tests for scan_barcode pipeline — 3-level caching logic
=============================================================
Tests the complete cache flow: L1 → L2 → L3 and write-back.
Runs WITHOUT a live API server (all external calls are mocked).
"""
import os
import sys
import json
import time
import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.scan_barcode import (
    _l1_barcodes,
    _MISSING,
    _lookup_in_disk_caches,
    lookup_barcode,
    lookup_via_api,
    barcode_pipeline,
    scan_barcode_from_image,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

FAKE_FOOD = {
    "barcode": "1234567890128",
    "product_name": "Test Product",
    "brands": "Test Brand",
    "nutritions": {"calories": 100.0, "protein": 5.0, "fat": 3.0, "carbs": 15.0},
}

FAKE_BARCODE = "1234567890128"
UNKNOWN_BARCODE = "9999999999999"


def _clear_l1():
    _l1_barcodes.clear()


# ─── Mock clients ─────────────────────────────────────────────────────────────

class MockClientHit:
    """Simulates a client that always finds the product."""
    def search_by_barcode(self, code: str):
        return {"food": FAKE_FOOD.copy(), "found": True, "message": "product found"}


class MockClientMiss:
    """Simulates a client that never finds the product."""
    def search_by_barcode(self, code: str):
        return {"food": None, "found": False, "message": "product not found"}


class MockClientError:
    """Simulates a client that always raises an exception."""
    def search_by_barcode(self, code: str):
        raise RuntimeError("Simulated API error")


def _make_clients(avocavo=None, openfoodfacts=None, usda=None):
    return {
        "avocavo": avocavo,
        "openfoodfacts": openfoodfacts,
        "usda": usda,
    }


# ─── Tests: lookup_via_api ────────────────────────────────────────────────────

class TestLookupViaApi:

    def test_l3_hit_returns_food_with_source_and_level(self):
        """L3 hit: result must contain food data, found=True, cache_level=L3."""
        clients = _make_clients(avocavo=MockClientHit())
        result = lookup_via_api(FAKE_BARCODE, clients)

        assert result["found"] is True
        assert result["cache_level"] == "L3"
        assert result["source"] == "avocavo"
        assert result["food"] is not None
        assert result["food"]["product_name"] == "Test Product"

    def test_l3_miss_all_clients_return_miss(self):
        """L3 miss: all clients found=False → cache_level=MISS, not ERROR."""
        clients = _make_clients(
            avocavo=MockClientMiss(),
            openfoodfacts=MockClientMiss(),
            usda=MockClientMiss(),
        )
        result = lookup_via_api(FAKE_BARCODE, clients)

        assert result["found"] is False
        assert result["cache_level"] == "MISS"
        assert result["source"] == "api miss"

    def test_l3_error_all_clients_raise_exception(self):
        """L3 error: all clients raise → cache_level=ERROR, distinguishable from MISS."""
        clients = _make_clients(
            avocavo=MockClientError(),
            openfoodfacts=MockClientError(),
            usda=MockClientError(),
        )
        result = lookup_via_api(FAKE_BARCODE, clients)

        assert result["found"] is False
        assert result["cache_level"] == "ERROR", (
            "Should return ERROR (not MISS) when all APIs raise exceptions"
        )
        assert result["source"] == "api error"

    def test_l3_partial_error_then_hit(self):
        """L3: first client errors, second client hits → should succeed."""
        clients = _make_clients(
            avocavo=MockClientError(),
            openfoodfacts=MockClientHit(),
        )
        result = lookup_via_api(FAKE_BARCODE, clients)

        assert result["found"] is True
        assert result["cache_level"] == "L3"
        assert result["source"] == "openfoodfacts"

    def test_l3_no_clients(self):
        """L3: no clients at all → cache_level=MISS."""
        result = lookup_via_api(FAKE_BARCODE, {})
        assert result["found"] is False
        assert result["cache_level"] == "MISS"


# ─── Tests: barcode_pipeline (THE MAIN BUG FIX) ──────────────────────────────

class TestBarcodePipeline:

    def test_food_data_preserved_on_l3_hit(self, tmp_path, monkeypatch):
        """
        THE MAIN BUG: food dict must NOT be overwritten with just {barcode}.
        After L3 hit, food must contain full product data AND the barcode field.
        """
        _clear_l1()

        # Patch scan to skip real image decoding
        monkeypatch.setattr(
            "scripts.scan_barcode.scan_barcode_from_image",
            lambda _: FAKE_BARCODE,
        )

        clients = _make_clients(avocavo=MockClientHit())
        result = barcode_pipeline(b"fake_image", clients=clients)

        assert result["found"] is True, "Should be found"
        food = result.get("food")
        assert isinstance(food, dict), f"food must be a dict, got: {food}"
        # THE CRITICAL CHECK: product_name must survive
        assert "product_name" in food, (
            f"BUG: food was overwritten! food keys: {list(food.keys())}"
        )
        assert food["product_name"] == "Test Product"
        # Barcode should also be present
        assert "barcode" in food
        assert food["barcode"] == FAKE_BARCODE

    def test_food_barcode_field_on_miss(self, monkeypatch):
        """Not found: food must still contain the decoded barcode."""
        _clear_l1()
        monkeypatch.setattr(
            "scripts.scan_barcode.scan_barcode_from_image",
            lambda _: UNKNOWN_BARCODE,
        )

        clients = _make_clients(
            avocavo=MockClientMiss(),
            openfoodfacts=MockClientMiss(),
            usda=MockClientMiss(),
        )
        result = barcode_pipeline(b"fake_image", clients=clients)

        assert result["found"] is False
        food = result.get("food")
        assert isinstance(food, dict)
        assert food.get("barcode") == UNKNOWN_BARCODE

    def test_food_barcode_when_no_barcode_decoded(self, monkeypatch):
        """No barcode decoded from image → food = {barcode: None}, found = False."""
        _clear_l1()
        monkeypatch.setattr(
            "scripts.scan_barcode.scan_barcode_from_image",
            lambda _: None,
        )

        result = barcode_pipeline(b"fake_image", clients={})

        assert result["found"] is False, "found must be False (bool), not a dict!"
        assert isinstance(result["found"], bool), (
            f"BUG: found is {type(result['found'])}, expected bool"
        )
        food = result.get("food")
        assert isinstance(food, dict)
        assert food.get("barcode") is None

    def test_l1_cache_promoted_after_l3_hit(self, monkeypatch):
        """After L3 hit, barcode must be in L1 cache for next call."""
        _clear_l1()
        monkeypatch.setattr(
            "scripts.scan_barcode.scan_barcode_from_image",
            lambda _: FAKE_BARCODE,
        )
        clients = _make_clients(avocavo=MockClientHit())

        # First call → L3
        barcode_pipeline(b"fake_image", clients=clients)

        # L1 should now have the food data
        l1_val = _l1_barcodes.get(FAKE_BARCODE)
        assert l1_val is not _MISSING, "Barcode should be in L1 after L3 hit"
        assert l1_val is not None, "L1 value should be food data, not None"

    def test_l3_error_distinguished_in_result(self, monkeypatch):
        """When all L3 APIs are down, cache_level=ERROR (not MISS)."""
        _clear_l1()
        monkeypatch.setattr(
            "scripts.scan_barcode.scan_barcode_from_image",
            lambda _: FAKE_BARCODE,
        )
        clients = _make_clients(
            avocavo=MockClientError(),
            openfoodfacts=MockClientError(),
            usda=MockClientError(),
        )

        result = barcode_pipeline(b"fake_image", clients=clients)

        assert result["found"] is False
        assert result["cache_level"] == "ERROR", (
            "API errors should produce cache_level=ERROR, not MISS"
        )
        # Even on total API failure, barcode should be returned
        food = result.get("food")
        assert isinstance(food, dict)
        assert food.get("barcode") == FAKE_BARCODE

    def test_cache_level_l2_data_preserved(self, monkeypatch):
        """
        L2 cache hit (via L1 pre-population): food data from disk must not be overwritten.
        Uses L1 promotion path (lookup_barcode → _lookup_in_disk_caches).
        The decoded barcode is injected into food only if food doesn't already have one.
        """
        _clear_l1()
        fake_barcode = "8934563138165"

        # Pre-populate L1 with product data that has NO barcode field yet
        food_without_barcode = {
            "product_name": "Test Product",
            "brands": "Test Brand",
            "nutritions": {"calories": 100.0, "protein": 5.0, "fat": 3.0, "carbs": 15.0},
        }
        _l1_barcodes.set(fake_barcode, food_without_barcode.copy())

        monkeypatch.setattr(
            "scripts.scan_barcode.scan_barcode_from_image",
            lambda _: fake_barcode,
        )

        result = barcode_pipeline(b"fake_image", clients={})

        assert result["found"] is True
        food = result.get("food")
        assert isinstance(food, dict)
        # product_name must survive (THE BUG was overwriting it)
        assert "product_name" in food, (
            f"BUG: food data was overwritten! Keys: {list(food.keys())}"
        )
        assert food["product_name"] == "Test Product"
        # Barcode should be injected from decoded scan code
        assert food.get("barcode") == fake_barcode


# ─── Tests: lookup_barcode ────────────────────────────────────────────────────

class TestLookupBarcode:

    def test_invalid_barcode(self):
        result = lookup_barcode("abc")
        assert result["found"] is False
        assert result["cache_level"] is None
        assert result["source"] == "invalid_input"

    def test_l1_hit_returns_food(self):
        _clear_l1()
        _l1_barcodes.set(FAKE_BARCODE, FAKE_FOOD.copy())
        result = lookup_barcode(FAKE_BARCODE)
        assert result["found"] is True
        assert result["cache_level"] == "L1"

    def test_l1_negative_hit(self):
        _clear_l1()
        _l1_barcodes.set(FAKE_BARCODE, None)  # Negative cache
        result = lookup_barcode(FAKE_BARCODE)
        assert result["found"] is False
        assert result["cache_level"] == "L1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
