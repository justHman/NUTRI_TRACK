import json
import os
import socket
import time
import urllib.request
from typing import Dict, List
from dotenv import load_dotenv
from jose import jwt
import os, sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logging_config import get_logger

logger = get_logger(__name__)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))


def get_ip() -> str:
    """
    Lấy IP container theo thứ tự ưu tiên:
    1. ECS Task Metadata Endpoint v4 (Fargate awsvpc) — link-local, không cần internet
    2. socket.gethostbyname fallback
    """
    # --- ECS Task Metadata Endpoint v4 ---
    metadata_uri = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
    if metadata_uri:
        try:
            with urllib.request.urlopen(f"{metadata_uri}/task", timeout=2) as resp:
                task_meta = json.loads(resp.read().decode())
            # Lấy IPv4 từ attachment ENI
            for attachment in task_meta.get("Attachments", []):
                if attachment.get("Type") == "ElasticNetworkInterface":
                    for detail in attachment.get("Details", []):
                        if detail.get("Name") == "privateIPv4Address":
                            return detail["Value"]
            # Fallback: IPv4 từ container đầu tiên trong task
            for container in task_meta.get("Containers", []):
                for net in container.get("Networks", []):
                    ipv4_addrs = net.get("IPv4Addresses", [])
                    if ipv4_addrs:
                        return ipv4_addrs[0]
        except Exception:
            pass  # fallback sang socket

    # --- Socket fallback (local / non-ECS) ---
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "unknown"


def get_mock_nutrition(query: str = "") -> Dict[str, float]:
    """Safe mock fallback when no API key or no result."""
    logger.warning("Using MOCK nutrition for query='%s'", query)
    return {
        "calories": 100.0,
        "protein": 5.0,
        "fat": 3.0,
        "carbs": 15.0,
    }

def get_mock_ingredients(query: str = "") -> List[str]:
    """Safe mock fallback for ingredients."""
    logger.warning("Using MOCK ingredients for query='%s'", query)
    return [""]

def get_mock_nutritions_and_ingredients(query: str = "") -> dict:
    """Safe mock fallback for nutritions and ingredients."""
    logger.warning("Using MOCK nutritions and ingredients for query='%s'", query)
    return {
        "description": "",
        "nutritions": get_mock_nutrition(query),
        "ingredients": get_mock_ingredients(query),
    }

def get_mock_barcode(barcode: str = "") -> dict:
    """Safe mock fallback for barcode search."""
    logger.warning("Using MOCK barcode for code='%s'", barcode)
    return {
        "found": True,
        "message": "product found",
        "food": {
            "barcode": barcode,
            "product_name": "",
            "brands": "",
            "quantity": "",
            "category": "",
            "ingredients_text": "",
            "ingredients": get_mock_ingredients(barcode),
            "allergens": [""],
            "nutritions": get_mock_nutrition(barcode),
            "labels": {
                 "vegan": "",
                 "vegetarian": "",
                 "gluten_free": "",
                 "organic": "",
                 "additives": "",
                 "packaging": "",
                 "ecoscore": "",
                 "nutriscore": "",
                 "nova_group": "",
                 "origin": "",
                 "processing_type": "",
                 "market_country": ""
            },
            "images": {
                 "front": "",
                 "ingredients": "",
                 "nutrition": ""
            }
        }
    }


if __name__ == "__main__":
    import pyperclip
    token = jwt.encode(
        {"service": "backend", "exp": int(time.time()) + 3600},
        os.getenv("NUTRITRACK_API_KEY"),
        algorithm="HS256",
    )
    pyperclip.copy(token)
    print(token)
