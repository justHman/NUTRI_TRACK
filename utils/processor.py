"""Image preprocessing utilities for AWS Bedrock API"""
import os
from io import BytesIO
from PIL import Image
from typing import Tuple, Optional
import re
import unicodedata

from config.logging_config import get_logger

logger = get_logger(__name__)


# Bedrock Converse API payload limits can be strict.
# Base64 encoding adds ~33% overhead. Set limit to 2MB to be absolutely safe.
BEDROCK_MAX_RAW_BYTES = 2_000_000

def normalize_query(query: str) -> str:
    """
    Robust multilingual normalize:
    - lowercase, strip
    - remove accents (Vietnamese, French, German, etc.)
    - extract prefix before parentheses (if ≥2 chars)
    - replace hyphens/underscores with spaces
    - remove punctuation
    - collapse multiple spaces
    """
    if not query:
        logger.debug("_normalize_query: empty input, returning ''")
        return ""

    original = query
    query = str(query).strip().lower()

    # Remove accents
    query = unicodedata.normalize('NFKD', query)
    query = ''.join([c for c in query if not unicodedata.combining(c)])

    # Extract prefix before parentheses
    match = re.match(r"^(.*?)\s*\(.*?\)", query)
    if match:
        prefix = match.group(1).strip()
        if len(prefix) >= 2:
            query = prefix
            logger.debug("_normalize_query: extracted prefix '%s' from '%s'", prefix, original)

    query = re.sub(r"[-_]", " ", query)
    query = re.sub(r"[()]", "", query)
    query = re.sub(r"[^\w\s]", "", query)
    query = re.sub(r"\s+", " ", query).strip()

    logger.debug("_normalize_query: '%s' → '%s'", original, query)
    return query

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
        logger.error("Image file not found: %s", image_path)
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    with open(image_path, "rb") as f:
        data = f.read()
    
    logger.debug("Loaded image: %s (%.2f MB)", image_path, len(data) / 1024 / 1024)
    return data


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
    detected = fmt_map.get(ext, "jpeg")
    logger.debug("Detected image format: %s → %s", ext, detected)
    return detected


def compress_image(image_bytes: bytes, max_pixels: int = 1024, quality: int = 85) -> bytes:
    """Compress an image by resizing and converting to JPEG.
    
    Args:
        image_bytes: Raw image bytes (any format PIL supports)
        max_pixels: Max dimension on the longest side
        quality: JPEG compression quality (1-100)
    
    Returns:
        Compressed image bytes in JPEG format
    """
    original_size = len(image_bytes) / 1024 / 1024
    logger.info("Compressing image: %.2f MB (max_pixels=%d, quality=%d)", original_size, max_pixels, quality)

    img = Image.open(BytesIO(image_bytes))
    if img.mode == "RGBA":
        logger.debug("Converting RGBA → RGB for JPEG compression")
        img = img.convert("RGB")
    img.thumbnail((max_pixels, max_pixels), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    compressed = buf.getvalue()

    compressed_size = len(compressed) / 1024 / 1024
    logger.info("Compression complete: %.2f MB → %.2f MB (%.0f%% reduction)",
                original_size, compressed_size,
                (1 - compressed_size / original_size) * 100 if original_size > 0 else 0)
    return compressed


def prepare_image_for_bedrock(image_path: Optional[str] = None, image_bytes: Optional[bytes] = None, filename: Optional[str] = None, max_pixels: int = 1024) -> Tuple[bytes, str]:
    """Load image and ensure it fits within Bedrock's size and dimension limits."""
    if image_bytes is None:
        if not image_path:
            raise ValueError("Either image_path or image_bytes must be provided")
        logger.info("Preparing image for Bedrock: %s", image_path)
        image_bytes = load_image_bytes(image_path)
        img_format = detect_image_format(image_path)
    else:
        logger.info("Preparing image bytes for Bedrock (size: %.2fMB)", len(image_bytes) / 1024 / 1024)
        if filename:
            img_format = detect_image_format(filename)
        elif image_path:
            img_format = detect_image_format(image_path)
        else:
            img_format = "jpeg"

    # Đọc nhanh kích thước ảnh bằng con trỏ BytesIO để không tải lại file
    needs_compression = False
    
    # 1. Check file size
    if len(image_bytes) > BEDROCK_MAX_RAW_BYTES:
        logger.warning(
            "Image too large (%.1f MB > %.1f MB limit), needs compression",
            len(image_bytes) / 1024 / 1024, 
            BEDROCK_MAX_RAW_BYTES / 1024 / 1024
        )
        needs_compression = True
    else:
        # 2. Check dimensions
        try:
            img = Image.open(BytesIO(image_bytes))
            width, height = img.size
            if max(width, height) > max_pixels:
                logger.warning(
                    "Image dimensions too large (%dx%d > %d), needs compression",
                    width, height, max_pixels
                )
                needs_compression = True
        except Exception as e:
            logger.error("Failed to read image dimensions: %s", e)
            # Safe bet is to compress if reading fails to avoid Converse API errors
            needs_compression = True

    if needs_compression:
        image_bytes = compress_image(image_bytes, max_pixels=max_pixels)
        img_format = "jpeg"
        logger.info("Image compressed to %.1f MB, format changed to jpeg",
                     len(image_bytes) / 1024 / 1024)
    else:
        logger.debug("Image size OK: %.2f MB", len(image_bytes) / 1024 / 1024)

    return image_bytes, img_format
