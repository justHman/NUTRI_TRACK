"""
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
from jose import jwt
import concurrent.futures

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger
from utils.test_helpers import require_api_integration_env, silence_console, restore_console
from utils.getter import get_ip

logger = get_logger(__name__)

BASE_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

SECRET_KEY = os.getenv("NUTRITRACK_API_KEY", "")
VALID_TOKEN = jwt.encode(
    {
        "service": "backend",
        "exp": int(time.time()) + 3600
    }, 
    SECRET_KEY, 
    algorithm="HS256"
)
AUTH_HEADERS = {"Authorization": f"Bearer {VALID_TOKEN}"}

LABEL_IMG = os.path.join(project_root, "data", "images", "labels", "hao_hao.jpg")
FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "com_tam.jpg")
FAST_FOOD_IMG = os.path.join(project_root, "data", "images", "dishes", "fast_food.jpg")
BARCODE_IMG = os.path.join(project_root, "data", "images", "barcodes", "barcode.png")

# ─── Helper for Polling ──────────────────────────────────────────────────────

def _poll_job(job_id: str, timeout: int = 180) -> dict:
    """Poll the /jobs/{job_id} endpoint until completed or failed."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=AUTH_HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "completed":
                    # Mocks the old response format {"success": True, "data": ...}
                    return {"success": True, "data": data.get("result", {}).get("data", {})}
                elif data.get("status") == "failed":
                    return {"success": False, "detail": data.get("error")}
            elif resp.status_code == 404:
                return {"success": False, "detail": "Job not found"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "detail": str(e)}
        time.sleep(2)
    return {"success": False, "detail": "Polling timeout"}

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
            result["notes"] = str(data)
        else:
            result["notes"] = f"Unexpected response: {data}"
    except Exception as e:
        result["notes"] = str(e)
    return result

def _test_root() -> dict:
    result = {"endpoint": "/", "method": "GET", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=10)
        result["status_code"] = resp.status_code
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "ok":
            result["success"] = True
            result["notes"] = str(data)
        else:
            result["notes"] = f"Unexpected response: {data}"
    except Exception as e:
        result["notes"] = str(e)
    return result

# ─── Analyze Food ────────────────────────────────────────────────────────────

def _test_analyze_food(image_path: str, image_name: str, method: str = "tools") -> dict:
    """Test POST /analyze-food endpoint"""
    result = {"endpoint": "/analyze-food", "method": "POST", "image": image_name, "query_method": method, "success": False, "status_code": None, "time_s": 0, "dishes": 0, "notes": ""}
    if not os.path.exists(image_path): return {**result, "notes": f"Image not found: {image_path}"}
    try:
        start = time.time()
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{BASE_URL}/analyze-food", headers=AUTH_HEADERS, files={"file": (os.path.basename(image_path), f, "image/jpeg")}, params={"method": method}, timeout=30
            )
        result["status_code"] = resp.status_code
        if resp.status_code == 202:
            data = resp.json()
            poll_resp = _poll_job(data.get("job_id"))
            elapsed = time.time() - start
            result["time_s"] = round(elapsed, 2)
            if poll_resp.get("success"):
                dishes = poll_resp.get("data", {}).get("dishes", [])
                result["dishes"] = len(dishes)
                result["success"] = True
                result["notes"] = f"method={method}, {len(dishes)} dish(es) detected in {elapsed:.1f}s"
            else:
                result["notes"] = f"Job failed: {poll_resp.get('detail')}"
        elif resp.status_code == 400:
            result["notes"] = f"Expected 202, got 400"
        else:
            result["notes"] = f"Expected 202, got {resp.status_code}"
    except Exception as e: result["notes"] = str(e)
    return result

def _test_analyze_food_invalid_method() -> dict:
    result = {"endpoint": "/analyze-food", "method": "POST", "image": "com_tam", "success": False, "status_code": None, "notes": ""}
    try:
        with open(FOOD_IMG, "rb") as f:
            resp = requests.post(f"{BASE_URL}/analyze-food", headers=AUTH_HEADERS, files={"file": ("com_tam.jpg", f, "image/jpeg")}, params={"method": "invalid_method"}, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400: result["success"] = True; result["notes"] = "Correctly rejected invalid method"
        else: result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e: result["notes"] = str(e)
    return result

def _test_analyze_food_invalid_file() -> dict:
    result = {"endpoint": "/analyze-food", "method": "POST", "image": "invalid_file", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.post(f"{BASE_URL}/analyze-food", headers=AUTH_HEADERS, files={"file": ("test.txt", b"not an image", "text/plain")}, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400: result["success"] = True; result["notes"] = "Correctly rejected non-image file"
        else: result["notes"] = f"Expected 400, got {resp.status_code}"
    except Exception as e: result["notes"] = str(e)
    return result

# ─── Analyze Label ────────────────────────────────────────────────────────────

def _test_analyze_label(image_path: str, image_name: str, expect_label: bool) -> dict:
    result = {"endpoint": "/analyze-label", "method": "POST", "image": image_name, "success": False, "status_code": None, "time_s": 0, "notes": ""}
    if not os.path.exists(image_path): return {**result, "notes": f"Image not found"}
    try:
        start = time.time()
        with open(image_path, "rb") as f:
            resp = requests.post(f"{BASE_URL}/analyze-label", headers=AUTH_HEADERS, files={"file": (os.path.basename(image_path), f, "image/jpeg")}, timeout=30)
        result["status_code"] = resp.status_code
        if resp.status_code == 202:
            data = resp.json()
            poll_resp = _poll_job(data.get("job_id"))
            elapsed = time.time() - start
            result["time_s"] = round(elapsed, 2)
            if poll_resp.get("success"):
                dishes = poll_resp.get("data", {}).get("labels", [])
                if expect_label and len(dishes) > 0:
                    result["success"] = True
                    result["notes"] = f"Detected {len(dishes)} product(s) in {elapsed:.1f}s"
                elif not expect_label:
                    result["success"] = True
                    result["notes"] = f"Detected {len(dishes)} product(s) in {elapsed:.1f}s"
            else:
                result["notes"] = f"Job failed: {poll_resp.get('detail')}"
        else: result["notes"] = f"HTTP {resp.status_code}"
    except Exception as e: result["notes"] = str(e)
    return result

def _test_analyze_label_invalid_file() -> dict:
    result = {"endpoint": "/analyze-label", "method": "POST", "image": "invalid_file", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.post(f"{BASE_URL}/analyze-label", headers=AUTH_HEADERS, files={"file": ("test.txt", b"not", "text/plain")}, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400: result["success"] = True; result["notes"] = "Ok"
    except Exception as e: result["notes"] = str(e)
    return result

# ─── Scan Barcode ────────────────────────────────────────────────────────────

def _test_scan_barcode(image_path: str, image_name: str) -> dict:
    result = {"endpoint": "/scan-barcode", "method": "POST", "image": image_name, "success": False, "status_code": None, "time_s": 0, "notes": ""}
    if not os.path.exists(image_path): return {**result, "notes": "No image"}
    try:
        start = time.time()
        with open(image_path, "rb") as f:
            resp = requests.post(f"{BASE_URL}/scan-barcode", headers=AUTH_HEADERS, files={"file": (os.path.basename(image_path), f, "image/png")}, timeout=30)
        result["status_code"] = resp.status_code
        if resp.status_code == 202:
            data = resp.json()
            poll_resp = _poll_job(data.get("job_id"))
            elapsed = time.time() - start
            result["time_s"] = round(elapsed, 2)
            if poll_resp.get("success"):
                scan_data = poll_resp.get("data", {})
                barcode = scan_data.get("barcode")
                found = scan_data.get("found", False)
                result["success"] = True
                result["notes"] = f"barcode={barcode}, found={found}"
            else: result["notes"] = "Polling failed"
    except Exception as e: result["notes"] = str(e)
    return result

def _test_scan_barcode_invalid_file() -> dict:
    result = {"endpoint": "/scan-barcode", "method": "POST", "image": "invalid", "success": False, "status_code": None, "notes": ""}
    try:
        resp = requests.post(f"{BASE_URL}/scan-barcode", headers=AUTH_HEADERS, files={"file": ("t.txt", b"a", "text/plain")}, timeout=10)
        result["status_code"] = resp.status_code
        if resp.status_code == 400: result["success"] = True; result["notes"] = "Ok"
    except Exception as e: result["notes"] = str(e)
    return result

def _test_scan_barcode_no_barcode() -> dict:
    return _test_scan_barcode(FOOD_IMG, "no_barcode")


# ─── Multi-threading Test ────────────────────────────────────────────────────

def _test_multithreading() -> dict:
    """Test POST /scan-barcode with multiple threads to verify concurrency."""
    result = {
        "endpoint": "MULTITHREADING",
        "method": "POST",
        "image": "Multiple Barcodes",
        "success": False,
        "status_code": None,
        "time_s": 0,
        "notes": "",
    }
    num_requests = 10
    if not os.path.exists(BARCODE_IMG):
        return {**result, "notes": "No image"}
        
    start = time.time()
    
    def fire_request(i):
        try:
            with open(BARCODE_IMG, "rb") as f:
                resp = requests.post(f"{BASE_URL}/scan-barcode", headers=AUTH_HEADERS, files={"file": (f"dup_{i}_{os.path.basename(BARCODE_IMG)}", f, "image/png")}, timeout=10)
            if resp.status_code == 202:
                data = resp.json()
                # Use a larger polling timeout for multithread to not fail due to bedrock queue
                return _poll_job(data.get("job_id"), timeout=120)
            return {"success": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "detail": str(e)}

    # Send 10 concurrent requests at exactly the same time
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fire_request, i): i for i in range(num_requests)}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
    elapsed = time.time() - start
    result["time_s"] = round(elapsed, 2)
    success_count = sum(1 for r in results if r.get("success", False))
    
    if success_count == num_requests:
        result["success"] = True
        result["notes"] = f"Successfully handled {num_requests} concurrent requests in {elapsed:.1f}s!"
    else:
        result["notes"] = f"Only {success_count}/{num_requests} succeeded. Fails: {[r for r in results if not r.get('success')]}"
        
    return result


def run_all() -> list:
    """Run all API endpoint tests."""
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

        r = _test_health(); all_results.append(r); _print_group("HEALTH TEST", [_to_case(r)])
        r = _test_root(); all_results.append(r); _print_group("ROOT TEST", [_to_case(r)])

        multi_cases = []
        r = _test_multithreading(); all_results.append(r); multi_cases.append(_to_case(r))
        _print_group("MULTITHREADING TEST", multi_cases)

        food_cases = []
        for args in [(FOOD_IMG, "com_tam", "tools"), (FOOD_IMG, "com_tam", "manual"), (FAST_FOOD_IMG, "fast_food", "tools")]:
            r = _test_analyze_food(*args); all_results.append(r); food_cases.append(_to_case(r))
        r = _test_analyze_food(LABEL_IMG, "hao_hao", "manual"); all_results.append(r); food_cases.append(_to_case(r))
        r = _test_analyze_food_invalid_method(); all_results.append(r); food_cases.append(_to_case(r))
        r = _test_analyze_food_invalid_file(); all_results.append(r); food_cases.append(_to_case(r))
        _print_group("FOOD ENDPOINT TESTS", food_cases)

        label_cases = []
        r = _test_analyze_label(LABEL_IMG, "hao_hao", expect_label=True); all_results.append(r); label_cases.append(_to_case(r))
        r = _test_analyze_label(FOOD_IMG, "com_tam", expect_label=False); all_results.append(r); label_cases.append(_to_case(r))
        r = _test_analyze_label_invalid_file(); all_results.append(r); label_cases.append(_to_case(r))
        _print_group("LABEL ENDPOINT TESTS", label_cases)

        barcode_cases = []
        r = _test_scan_barcode(BARCODE_IMG, "barcode"); all_results.append(r); barcode_cases.append(_to_case(r))
        r = _test_scan_barcode_no_barcode(); all_results.append(r); barcode_cases.append(_to_case(r))
        r = _test_scan_barcode_invalid_file(); all_results.append(r); barcode_cases.append(_to_case(r))
        _print_group("BARCODE ENDPOINT TESTS", barcode_cases)


        passed = sum(1 for r in all_results if r.get("success"))
        icon = "✅" if passed == len(all_results) else "❌"
        print(f"\n───────────────────────────────────────────────────────────────────────", flush=True)
        print(f"  {passed}/{len(all_results)} passed {icon}\n", flush=True)
        return all_results
    finally:
        pass

def _is_server_ready() -> bool:
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False

@pytest.fixture(scope="module")
def ensure_api_server():
    if _is_server_ready(): yield; return
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "templates.api:app", "--host", "127.0.0.1", "--port", "8000"], cwd=project_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 180
    while time.time() < deadline:
        if _is_server_ready(): break
        time.sleep(1)
    else:
        proc.terminate()
        raise RuntimeError("Cannot start API server")
    try:
        yield
    finally:
        proc.terminate()
        try: proc.wait(timeout=10)
        except Exception: proc.kill()

@pytest.mark.integration
def test_api_endpoints_suite(ensure_api_server):
    require_api_integration_env()
    results = run_all()
    failed = [r for r in results if not r.get("success")]
    assert not failed, f"API endpoint suite failed: {failed}"

if __name__ == "__main__":
    if not _is_server_ready():
        print("Starting dev server for local run...")
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "templates.api:app", "--host", "127.0.0.1", "--port", "8000"], cwd=project_root)
        while not _is_server_ready(): time.sleep(1)
        try: run_all()
        finally: proc.terminate()
    else:
        run_all()
