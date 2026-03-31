"""
Barcode Scanning Pipeline
=========================
Scan barcode from image bytes using pyrxing, then look up product info
in the three-tier cache hierarchy:

    L1 (RAM _LRUCache) → L2 (disk JSON) → L3 (API call)

L2 cache sources checked in order:
    1. OpenFoodFacts  (app/data/openfoodfacts_cache.json)
    2. Avocavo        (app/data/avocavo_cache.json)
    3. USDA           (app/data/usda_cache.json)

L3 API search fallback (barcode_pipeline, on full L1+L2 miss):
    1. Avocavo        → POST /upc/ingredient
    2. OpenFoodFacts  → GET  /api/v2/product/{barcode}
    3. USDA           → GET  /foods/search?query={barcode}

    Each client's search_by_barcode() is called in order.
    The first successful hit short-circuits the remaining clients.

Usage:
    from scripts.scan_barcode import barcode_pipeline, scan_barcode_from_image, lookup_barcode
"""

import os
import re
import json
import time
from collections import OrderedDict
from typing import Dict, Optional

import pyrxing

from config.logging_config import get_logger

logger = get_logger(__name__)


# ─── L1 RAM Cache ────────────────────────────────────────────────────────────

_MISSING = object()


class _LRUCache:
    """Thread-safe LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 256):
        self._cache: OrderedDict[str, object] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str):
        if key not in self._cache:
            return _MISSING
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key: str, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
                logger.debug("L1 barcode cache evicted LRU entry: '%s'", oldest)
        self._cache[key] = value

    def clear(self):
        self._cache.clear()

    def __contains__(self, key: str):
        return key in self._cache

    def __len__(self):
        return len(self._cache)


_l1_barcodes = _LRUCache(maxsize=256)


# ─── L2 Disk Cache Helpers ───────────────────────────────────────────────────

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_TTL_DAYS = 30

_CACHE_FILES = {
    "openfoodfacts": os.path.join(_DATA_DIR, "openfoodfacts_cache.json"),
    "avocavo": os.path.join(_DATA_DIR, "avocavo_cache.json"),
    "usda": os.path.join(_DATA_DIR, "usda_cache.json"),
}

# L2 disk cache lookup order — OpenFoodFacts has the best barcode coverage
_LOOKUP_ORDER = ["openfoodfacts", "avocavo", "usda"]

# L3 API call order — Avocavo first (faster), then OpenFoodFacts, then USDA
_L3_LOOKUP_ORDER = ["avocavo", "openfoodfacts", "usda"]


def _now_ts() -> float:
    return time.time()


def _is_expired(entry: dict) -> bool:
    ts = entry.get("_ts", 0)
    return (_now_ts() - ts) > (_CACHE_TTL_DAYS * 86400)


def _load_cache_file(path: str) -> dict:
    """Load a single cache JSON file. Returns {"foods": {}, "barcodes": {}} on failure."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug("Loaded cache file: %s (%d barcode entries)",
                         os.path.basename(path), len(data.get("barcodes", {})))
            return data
    except Exception as e:
        logger.warning("Failed to load cache file %s: %s", path, e)
    return {"foods": {}, "barcodes": {}}


def _lookup_in_disk_caches(barcode: str) -> Optional[Dict]:
    first_negative = None
    for source in _LOOKUP_ORDER:
        cache_path = _CACHE_FILES.get(source)
        if not cache_path:
            continue

        cache_data = _load_cache_file(cache_path)
        barcodes = cache_data.get("barcodes", {})

        if barcode in barcodes:
            entry = barcodes[barcode].copy()  # Copy to avoid mutating cache data
            if not _is_expired(entry):
                food = entry.get("food")
                entry_found = entry.get("found") is True
                entry["source"] = source
                entry = {k: v for k, v in entry.items() if k != "_ts"}
                if entry_found:
                    _l1_barcodes.set(barcode, food)
                    logger.info("L2 cache hit for barcode '%s' in %s", barcode, source)
                    return entry

                # Keep the first negative hit as a fallback while continuing to
                # scan later providers for any positive hit.
                if first_negative is None:
                    first_negative = entry
            else:
                logger.debug("L2 entry expired for barcode '%s' in %s", barcode, source)

    if first_negative is not None:
        _l1_barcodes.set(barcode, None)
        logger.info(
            "L2 negative cache fallback for barcode '%s' from source=%s",
            barcode,
            first_negative.get("source"),
        )
        return first_negative

    logger.debug("No L2 cache hit for barcode '%s' across all sources", barcode)
    return None


def lookup_via_api(barcode: str, clients: Dict) -> Optional[Dict]:
    for source in _L3_LOOKUP_ORDER:
        client = clients.get(source)
        if client is None:
            logger.debug("L3: no client available for '%s', skipping", source)
            continue

        try:
            logger.info("L3: calling %s.search_by_barcode('%s')", source, barcode)
            api_result = client.search_by_barcode(barcode)

            if api_result and api_result.get("found", False) is True:
                result = api_result.copy()
                result["source"] = source
                result["cache_level"] = "L3"
                logger.info("L3 API hit for barcode '%s' from %s", barcode, source)
                return result

            logger.debug("L3: %s returned found=False for barcode '%s'", source, barcode)

        except Exception as e:
            logger.warning("L3: %s.search_by_barcode failed for '%s': %s",
                           source, barcode, e)

    logger.info("L3: no API hit for barcode '%s' across all clients", barcode)
    return {
        "food": None,
        "found": False,
        "message": "product not found via API search",
        "source": "api miss",
        "cache_level": "MISS",
    }


# ─── Barcode Scanning ────────────────────────────────────────────────────────

def scan_barcode_from_image(image_source) -> Optional[str]:
    """Decode barcode from image using pyrxing.

    Args:
        image_source: File path (str) or image bytes.

    Returns:
        Decoded barcode string, or None if no barcode found.
    """
    logger.info("Scanning barcode from image (type=%s)", type(image_source).__name__)

    try:
        if isinstance(image_source, (bytes, bytearray)):
            # Write bytes to a temp file for pyrxing
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_source)
                tmp_path = tmp.name
            try:
                results = pyrxing.read_barcodes(tmp_path)
            finally:
                os.unlink(tmp_path)
        elif isinstance(image_source, str):
            if not os.path.exists(image_source):
                logger.error("Image file not found: %s", image_source)
                return None
            results = pyrxing.read_barcodes(image_source)
        else:
            logger.error("Unsupported image source type: %s", type(image_source).__name__)
            return None

        if not results:
            logger.warning("No barcode detected in image: ", results)
            return None

        code = results[0].text
        logger.info("Barcode decoded: %s (format=%s)", code, getattr(results[0], 'format', 'unknown'))
        return code

    except Exception as e:
        logger.error("Barcode scanning failed: %s", e, exc_info=True)
        return None


# ─── Barcode Lookup ──────────────────────────────────────────────────────────

def lookup_barcode(code: str) -> Dict:

    barcode = re.sub(r"\D", "", str(code or "")).strip()

    if not barcode or len(barcode) < 8:
        logger.warning("lookup_barcode: invalid or empty barcode input='%s'", code)
        return {
            "food": None,
            "found": False,
            "message": "invalid barcode",
            "source": "invalid_input",
            "cache_level": None,
        }

    logger.info("Looking up barcode: %s", barcode)

    # Level 1: RAM cache
    l1_hit = _l1_barcodes.get(barcode)
    if l1_hit is not _MISSING:
        food_data = l1_hit if l1_hit is not None else None
        final_result = {
            "food": food_data,
        }
        # Flatten food fields to top-level for easier access
        if isinstance(food_data, dict):
            final_result.update({k: v for k, v in food_data.items() if k not in final_result})
        if l1_hit is not None:
            logger.info("L1 cache hit for barcode '%s'", barcode)
            final_result["found"] = True
            final_result["message"] = "product found"
        else:
            logger.info("L1 cache hit for barcode '%s' with negative result", barcode)
            final_result["found"] = False
            final_result["message"] = "product not found"

        final_result["source"] = "L1 RAM cache"
        final_result["cache_level"] = "L1"
        return final_result

    # Level 2: Disk caches (OpenFoodFacts → Avocavo → USDA)
    l2_hit = _lookup_in_disk_caches(barcode)
    if l2_hit is not None:
        # Promote to L1
        _l1_barcodes.set(barcode, l2_hit.get("food", None))
        logger.info("Promoted barcode '%s' from L2 to L1 (source=%s)",
                     barcode, l2_hit.get("source"))
        final_result = l2_hit.copy()
        final_result["cache_level"] = "L2"
        return final_result

    logger.info("Barcode '%s' not found in any cache or API", barcode)
    return {
        "food": None,
        "found": False,
        "message": "product not found in caches",
        "source": "cache miss",
        "cache_level": "MISS",
    }


# ─── Full Pipeline ───────────────────────────────────────────────────────────

def barcode_pipeline(image_source, clients: Optional[Dict] = None) -> Dict:
    """
    - Input: image bytes or file path
    - Output:
    {
        "image_path": str or None,
        "food": dict,
        "found": bool,
        "message": str,
        "source": str (e.g. "L1 RAM cache", "openfoodfacts", "avocavo", "usda", "api miss"),
        "cache_level": str (e.g. "L1", "L2", "L3", "MISS"),
        "scan_time_s": float,
        "total_time_s": float,
    }
    """
    start = time.time()
    logger.info("Starting barcode pipeline")

    result = {}
    # Step 1: Scan barcode from image
    code = scan_barcode_from_image(image_source)
    elapsed_scan = time.time() - start

    if not code:
        result["food"] = None
        result["found"] = False
        result["message"] = "No barcode detected in image"
        result["scan_time_s"] = round(elapsed_scan, 3)
        result["total_time_s"] = round(time.time() - start, 3)
        logger.warning("Pipeline finished: no barcode detected (%.3fs)", elapsed_scan)
        return result

    # Step 2: Lookup barcode in L1 → L2 caches
    lookup_result = lookup_barcode(code)

    # Step 3: If not found in cache, search via API clients (L3)
    if not lookup_result.get("found") and clients and lookup_result.get("cache_level") == "MISS":
        barcode = re.sub(r"\D", "", str(code or "")).strip()
        logger.info("Cache miss for barcode '%s', starting API search fallback", barcode)

        api_hit = lookup_via_api(barcode, clients)
        lookup_result = api_hit
        if api_hit.get("found", False):
            _l1_barcodes.set(barcode, lookup_result.get("food", None))
            logger.info("Promoted barcode '%s' from L3 to L1 (source=%s)",
                        barcode, lookup_result.get("source"))

    elapsed_total = time.time() - start

    result.update(lookup_result)
    result["scan_time_s"] = round(elapsed_scan, 3)
    result["total_time_s"] = round(elapsed_total, 3)

    if result.get("found"):
        logger.info("Pipeline complete: barcode=%s found=%s source=%s level=%s (%.3fs)",
                     code, True, result.get("source"), result.get("cache_level"), elapsed_total)
    else:
        logger.info("Pipeline complete: barcode=%s not found in caches or APIs (%.3fs)",
                     code, elapsed_total)

    return result
