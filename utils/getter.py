from jose import jwt
from dotenv import load_dotenv
import os
import time
import urllib.request
import json
import socket

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))


def get_container_ip() -> str:
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

if __name__ == "__main__":
    token = jwt.encode(
        {
            'service': 'backend',
            'exp': int(time.time()) + 24 * 3600
        },
        os.getenv('NUTRITRACK_API_KEY'),
        algorithm='HS256'
    )
    print(token)