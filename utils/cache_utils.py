import json
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.client_config import CACHE_TTL_DAYS
from config.logging_config import get_logger

logger = get_logger(__name__)


def get_now_ts() -> float:
    return time.time()


def is_expired(entry: dict) -> bool:
    ts = entry.get("_ts", 0)
    return (get_now_ts() - ts) > (CACHE_TTL_DAYS * 86400)


def load_disk_cache(cache_file: str, cache_dir=None, cache_key=None) -> dict:
    """Load Level-2 disk cache from JSON file, with optional S3 syncing."""
    s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
    if s3_bucket and cache_dir and cache_key:
        try:
            import boto3

            logger.info("Syncing L2 cache from S3: s3://%s/%s", s3_bucket, cache_key)
            region = (
                os.getenv("AWS_REGION")
                or os.getenv("AWS_DEFAULT_REGION")
                or "us-east-1"
            )
            s3 = boto3.client("s3", region_name=region)

            os.makedirs(cache_dir, exist_ok=True)
            s3.download_file(s3_bucket, cache_key, cache_file)
            logger.debug("Successfully downloaded cache from S3 to %s", cache_file)
        except Exception as e:
            if hasattr(e, "response") and getattr(e, "response", {}).get(
                "Error", {}
            ).get("Code") in ("404", "NoSuchKey"):
                logger.info(
                    "No cache found on S3, starting fresh or using existing local file"
                )
            else:
                logger.warning("Failed to download cache from S3: %s", e)

    if not os.path.exists(cache_file):
        return {"foods": {}, "barcodes": {}}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        logger.debug(
            "%s loaded: %d entries (%d foods, %d barcodes) from %s",
            cache_file,
            len(raw.get("foods", {})) + len(raw.get("barcodes", {})),
            len(raw.get("foods", {})),
            len(raw.get("barcodes", {})),
            cache_file,
        )
        return raw
    except Exception as e:
        logger.warning("L2 cache load failed (%s), starting fresh", e)
        return {"foods": {}, "barcodes": {}}


def save_disk_cache(cache: dict, cache_file: str, cache_dir: str, cache_key=None):
    """Persist Level-2 disk cache to JSON file and sync to S3 if configured."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.debug(
            "L2 cache saved: %d entries (%d foods, %d barcodes) to %s",
            len(cache.get("foods", {})) + len(cache.get("barcodes", {})),
            len(cache.get("foods", {})),
            len(cache.get("barcodes", {})),
            cache_file,
        )

        s3_bucket = os.getenv("AWS_S3_CACHE_BUCKET")
        if s3_bucket and cache_file and cache_key:
            import boto3

            logger.info("Uploading L2 cache to S3: s3://%s/%s", s3_bucket, cache_key)
            region = (
                os.getenv("AWS_REGION")
                or os.getenv("AWS_DEFAULT_REGION")
                or "us-east-1"
            )
            s3 = boto3.client("s3", region_name=region)
            s3.upload_file(cache_file, s3_bucket, cache_key)
            logger.debug("Successfully uploaded cache to S3")

    except Exception as e:
        logger.warning("L2 cache save/sync failed: %s", e)


if __name__ == "__main__":
    data, raw = load_disk_cache(
        r"D:\Project\Code\nutritrack-documentation\app\data\avocavo_cache.json"
    )
    import json

    with open(
        r"D:\Project\Code\nutritrack-documentation\app\data\raw.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    with open(
        r"D:\Project\Code\nutritrack-documentation\app\data\data.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
