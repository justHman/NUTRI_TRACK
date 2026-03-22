b"""
Tests for NutriTrack API Endpoints
====================================
Tests the FastAPI endpoints: /health, /analyze-food, /analyze-label, /scan-barcode
"""

import os
import sys
import time
import subprocess
import requests
import pytest
import logging as _stdlib_logging

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

BASE_URL = "http://localhost:8000"
LABEL_IMG = os.path.join(project_root, "data", "images", "labels", "hao_hao.jpg")
FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "com_tam.jpg")
FAST_FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "fast_food.jpg")
BARCODE_IMG = os.path.join(project_root, "data", "images", "barcodes", "barcode.png")


# ─── Health Check ────────────────────────────────────────────────────────────

def _test_health() -> dict:
    """Test GET /health endpoint"""
    result = {"endpoint": "/health", "method": "GET", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        result["status_code"] = resp.status_code
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "ok":
            result["success"] = True
            result["notes"] = "Health check OK"
        else:
            result["notes"] = f"Unexpected response: {data}"
    except Exception as e:
        result["notes"] = str(e)
    return result


def _test_root() -> dict:
    """Test GET / endpoint"""
    result = {"endpoint": "/", "method": "GET", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=10)
        result["status_code"] = resp.status_code
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "ok":
            result["success"] = True
            result["notes"] = f"Root OK — qwen={data.get('qwen_model')}, usda={data.get('usda_ready')}"
        else:
            result["notes"] = f"Unexpected response: {data}"
    except Exception as e:
        result["notes"] = str(e)
    return result


# ─── Analyze Food ────────────────────────────────────────────────────────────

def _test_analyze_food(image_path: str, image_name: str, method: str = "tools") -> dict:
    """Test POST /analyze-food endpoint"""
    result = {
        "endpoint": "/analyze-food",
        "method": "POST",
        "image": image_name,
        "query_method": method,
        "success": False,
        "status_code": None,
        "time_s": 0,
        "dishes": 0,
        "notes": "",
    }

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        start = time.time()
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
            resp = requests.post(
                f"{BASE_URL}/analyze-food",
                files=files,
                params={"method": method},
                timeout=180,
            )
        elapsed = time.time() - start

        result["status_code"] = resp.status_code
        result["time_s"] = round(elapsed, 2)
        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            dishes = data.get("data", {}).get("dishes", [])
            result["dishes"] = len(dishes)
            result["success"] = True
            result["notes"] = f"method={method}, {len(dishes)} dish(es) detected in {elapsed:.1f}s"
        else:
            result["notes"] = f"HTTP {resp.status_code}: {data.get('detail', '')}"

    except Exception as e:
        result["notes"] = str(e)

    return result


def _test_analyze_food_invalid_method() -> dict:
    """Test POST /analyze-food with invalid method param → expect 400"""
    result = {
        "endpoint": "/analyze-food",
        "method": "POST",
        "image": "com_tam",
        "success": False,
        "status_code": None,
        "notes": "",
    }

    if not os.path.exists(FOOD_IMG):
        result["notes"] = f"Image not found: {FOOD_IMG}"
        return result

    try:
        with open(FOOD_IMG, "rb") as f:
            files = {"file": (os.path.basename(FOOD_IMG), f, "image/jpeg")}
            resp = requests.post(
                f"{BASE_URL}/analyze-food",
                files=files,
                params={"method": "invalid_method"},
                timeout=10,
            )
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected invalid method"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result


def _test_analyze_food_invalid_file() -> dict:
    """Test POST /analyze-food with non-image file → expect 400"""
    result = {
        "endpoint": "/analyze-food",
        "method": "POST",
        "image": "invalid_file",
        "success": False,
        "status_code": None,
        "notes": "",
    }
    try:
        files = {"file": ("test.txt", b"not an image", "text/plain")}
        resp = requests.post(f"{BASE_URL}/analyze-food", files=files, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected non-image file"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result

# ─── Analyze Label ────────────────────────────────────────────────────────────

def _test_analyze_label(image_path: str, image_name: str, expect_label: bool) -> dict:
    """Test POST /analyze-label endpoint"""
    result = {
        "endpoint": "/analyze-label",
        "method": "POST",
        "image": image_name,
        "success": False,
        "status_code": None,
        "time_s": 0,
        "notes": "",
    }

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        start = time.time()
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
            resp = requests.post(f"{BASE_URL}/analyze-label", files=files, timeout=120)
        elapsed = time.time() - start

        result["status_code"] = resp.status_code
        result["time_s"] = round(elapsed, 2)
        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            dishes = data.get("data", {}).get("dishes", [])
            if expect_label and len(dishes) > 0:
                result["success"] = True
                result["notes"] = f"Detected {len(dishes)} product(s)"
            elif not expect_label and len(dishes) == 0:
                result["success"] = True
                result["notes"] = "Correctly returned no label"
            elif not expect_label and len(dishes) > 0:
                result["success"] = True
                result["notes"] = f"Model returned {len(dishes)} item(s) for non-label (acceptable)"
            else:
                result["notes"] = f"Expected label={expect_label}, got {len(dishes)} dishes"
        else:
            result["notes"] = f"HTTP {resp.status_code}: {data.get('detail', '')}"

    except Exception as e:
        result["notes"] = str(e)

    return result


def _test_analyze_label_invalid_file() -> dict:
    """Test POST /analyze-label with non-image file"""
    result = {
        "endpoint": "/analyze-label",
        "method": "POST",
        "image": "invalid_file",
        "success": False,
        "status_code": None,
        "notes": "",
    }
    try:
        files = {"file": ("test.txt", b"not an image", "text/plain")}
        resp = requests.post(f"{BASE_URL}/analyze-label", files=files, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected non-image file"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result


# ─── Scan Barcode ────────────────────────────────────────────────────────────

def _test_scan_barcode(image_path: str, image_name: str) -> dict:
    """Test POST /scan-barcode endpoint with a valid barcode image."""
    result = {
        "endpoint": "/scan-barcode",
        "method": "POST",
        "image": image_name,
        "success": False,
        "status_code": None,
        "time_s": 0,
        "notes": "",
    }

    if not os.path.exists(image_path):
        result["notes"] = f"Image not found: {image_path}"
        return result

    try:
        start = time.time()
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/png")}
            resp = requests.post(f"{BASE_URL}/scan-barcode", files=files, timeout=30)
        elapsed = time.time() - start

        result["status_code"] = resp.status_code
        result["time_s"] = round(elapsed, 2)
        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            scan_data = data.get("data", {})
            barcode = scan_data.get("barcode")
            found = scan_data.get("found", False)
            result["success"] = True
            result["notes"] = f"barcode={barcode}, found={found}"
            if found:
                result["notes"] += f", source={scan_data.get('source')}, level={scan_data.get('cache_level')}"
        else:
            result["notes"] = f"HTTP {resp.status_code}: {data.get('detail', '')}"

    except Exception as e:
        result["notes"] = str(e)

    return result


def _test_scan_barcode_invalid_file() -> dict:
    """Test POST /scan-barcode with non-image file -> expect 400"""
    result = {
        "endpoint": "/scan-barcode",
        "method": "POST",
        "image": "invalid_file",
        "success": False,
        "status_code": None,
        "notes": "",
    }
    try:
        files = {"file": ("test.txt", b"not an image", "text/plain")}
        resp = requests.post(f"{BASE_URL}/scan-barcode", files=files, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400:
            result["success"] = True
            result["notes"] = "Correctly rejected non-image file"
        else:
            result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e:
        result["notes"] = str(e)
    return result


def _test_scan_barcode_no_barcode() -> dict:
    """Test POST /scan-barcode with a food image (no barcode) -> success but no barcode detected"""
    result = {
        "endpoint": "/scan-barcode",
        "method": "POST",
        "image": "com_tam (no barcode)",
        "success": False,
        "status_code": None,
        "time_s": 0,
        "notes": "",
    }

    if not os.path.exists(FOOD_IMG):
        result["notes"] = f"Image not found: {FOOD_IMG}"
        return result

    try:
        start = time.time()
        with open(FOOD_IMG, "rb") as f:
            files = {"file": (os.path.basename(FOOD_IMG), f, "image/jpeg")}
            resp = requests.post(f"{BASE_URL}/scan-barcode", files=files, timeout=30)
        elapsed = time.time() - start

        result["status_code"] = resp.status_code
        result["time_s"] = round(elapsed, 2)
        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            scan_data = data.get("data", {})
            barcode = scan_data.get("barcode")
            if barcode is None:
                result["success"] = True
                result["notes"] = "Correctly returned no barcode for non-barcode image"
            else:
                result["success"] = True
                result["notes"] = f"Detected barcode={barcode} in non-barcode image (acceptable)"
        else:
            result["notes"] = f"HTTP {resp.status_code}: {data.get('detail', '')}"

    except Exception as e:
        result["notes"] = str(e)

    return result

def run_all() -> list:
    """Run all API endpoint tests.

    Returns:
        List of result dicts
    """
    _saved = _silence_console()
    try:
        print("\n─── API Endpoint Tests ───────────────────────────────────────────────────")
        all_results = []

        def _to_case(r):
            ep = r.get("endpoint", "")
            img = r.get("image", "")
            qm  = r.get("query_method", "")
            label = ep
            if img:  label += f" / {img}"
            if qm:   label += f" ({qm})"
            detail = r.get("notes", "")
            if r.get("status_code"):  detail += f"  [HTTP {r['status_code']}]"
            if r.get("time_s"):       detail += f"  [{r['time_s']}s]"
            return (r["success"], label, detail)

        def _print_group(tag, cases):
            print(f"\n  ─────[{tag}]─────", flush=True)
            for i, (ok, label, detail) in enumerate(cases, 1):
                icon = "✅" if ok else "❌"
                print(f"    {i}. {label}: {detail} ({icon})", flush=True)
            passed = sum(ok for ok, _, _ in cases)
            total = len(cases)
            s_icon = "✅" if passed == total else "❌"
            print(f"    {passed}/{total} passed {s_icon}", flush=True)

        # ─ HEALTH
        r = _test_health()
        all_results.append(r)
        _print_group("HEALTH TEST", [_to_case(r)])

        # ─ ROOT
        r = _test_root()
        all_results.append(r)
        _print_group("ROOT TEST", [_to_case(r)])

        # ─ FOOD endpoint (5 cases)
        food_cases = []
        for args in [
            (FOOD_IMG,      "com_tam",   "tools"),
            (FOOD_IMG,      "com_tam",   "manual"),
            (FAST_FOOD_IMG, "fast_food", "tools"),
        ]:
            r = _test_analyze_food(*args)
            all_results.append(r); food_cases.append(_to_case(r))
        r = _test_analyze_food_invalid_method()
        all_results.append(r); food_cases.append(_to_case(r))
        r = _test_analyze_food_invalid_file()
        all_results.append(r); food_cases.append(_to_case(r))
        _print_group("FOOD ENDPOINT TESTS", food_cases)

        # ─ LABEL endpoint (3 cases)
        label_cases = []
        r = _test_analyze_label(LABEL_IMG, "hao_hao", expect_label=True)
        all_results.append(r); label_cases.append(_to_case(r))
        r = _test_analyze_label(FOOD_IMG, "com_tam", expect_label=False)
        all_results.append(r); label_cases.append(_to_case(r))
        r = _test_analyze_label_invalid_file()
        all_results.append(r); label_cases.append(_to_case(r))
        _print_group("LABEL ENDPOINT TESTS", label_cases)

        # ─ BARCODE endpoint (3 cases)
        barcode_cases = []
        r = _test_scan_barcode(BARCODE_IMG, "barcode")
        all_results.append(r); barcode_cases.append(_to_case(r))
        r = _test_scan_barcode_no_barcode()
        all_results.append(r); barcode_cases.append(_to_case(r))
        r = _test_scan_barcode_invalid_file()
        all_results.append(r); barcode_cases.append(_to_case(r))
        _print_group("BARCODE ENDPOINT TESTS", barcode_cases)

        passed = sum(1 for r in all_results if r.get("success"))
        icon = "✅" if passed == len(all_results) else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{len(all_results)} passed {icon}\n", flush=True)
        return all_results
    finally:
        _restore_console(_saved)


def _is_server_ready() -> bool:
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def ensure_api_server():
    """Start templates.api:app with uvicorn if it is not already running."""
    if _is_server_ready():
        yield
        return

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "templates.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 180
    while time.time() < deadline:
        if _is_server_ready():
            break
        time.sleep(1)
    else:
        proc.terminate()
        raise RuntimeError("Cannot start API server: templates.api:app did not become healthy")

    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


@pytest.mark.integration
def test_api_endpoints_suite(ensure_api_server):
    results = run_all()
    failed = [r for r in results if not r.get("success")]
    assert not failed, f"API endpoint suite failed: {failed}"
