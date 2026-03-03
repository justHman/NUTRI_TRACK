"""Image preprocessing utilities for AWS Bedrock API"""
import os
from io import BytesIO
from PIL import Image
from typing import Tuple


# Bedrock Converse API: max request body = 10MB
# Base64 encoding adds ~33% overhead, so raw image should be < 7.5MB
BEDROCK_MAX_RAW_BYTES = 7_500_000


def load_image_bytes(image_path: str) -> bytes:
    """Load raw bytes from an image file.
    
    Args:
        image_path: Absolute or relative path to the image
    
    Returns:
        Raw image bytes
    
    Raises:
        FileNotFoundError: If image_path doesn't exist
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    with open(image_path, "rb") as f:
        return f.read()


def detect_image_format(image_path: str) -> str:
    """Detect Bedrock-compatible image format from file extension.
    
    Args:
        image_path: Path to the image file
    
    Returns:
        One of: 'jpeg', 'png', 'gif', 'webp'
    """
    ext = os.path.splitext(image_path)[1].lower()
    fmt_map = {
        ".jpg": "jpeg", ".jpeg": "jpeg",
        ".png": "png",
        ".gif": "gif",
        ".webp": "webp",
    }
    return fmt_map.get(ext, "jpeg")


def compress_image(image_bytes: bytes, max_pixels: int = 2048, quality: int = 85) -> bytes:
    """Compress an image by resizing and converting to JPEG.
    
    Args:
        image_bytes: Raw image bytes (any format PIL supports)
        max_pixels: Max dimension on the longest side
        quality: JPEG compression quality (1-100)
    
    Returns:
        Compressed image bytes in JPEG format
    """
    img = Image.open(BytesIO(image_bytes))
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.thumbnail((max_pixels, max_pixels), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def prepare_image_for_bedrock(image_path: str) -> Tuple[bytes, str]:
    """Load image and ensure it fits within Bedrock's size limit.
    
    Automatically compresses the image if it exceeds ~7.5MB
    (to account for base64 overhead in the API request).
    
    Args:
        image_path: Path to the image file
    
    Returns:
        Tuple of (image_bytes, format_string)
    """
    image_bytes = load_image_bytes(image_path)
    img_format = detect_image_format(image_path)

    if len(image_bytes) > BEDROCK_MAX_RAW_BYTES:
        original_mb = len(image_bytes) / 1024 / 1024
        print(f"⚠️ Image too large ({original_mb:.1f}MB), compressing...")
        image_bytes = compress_image(image_bytes)
        img_format = "jpeg"
        print(f"✅ Compressed to {len(image_bytes) / 1024 / 1024:.1f}MB")

    return image_bytes, img_format
