import os
import pytest
import logging as _stdlib_logging

def require_api_integration_env() -> None:
    required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        pytest.skip(f"Missing AWS credentials for API integration tests: {', '.join(missing)}")

def silence_console():
    root = _stdlib_logging.getLogger()
    saved = []
    for h in root.handlers:
        if isinstance(h, _stdlib_logging.StreamHandler) and not isinstance(h, _stdlib_logging.FileHandler):
            saved.append((h, h.level))
            h.setLevel(_stdlib_logging.WARNING)
    return saved

def restore_console(saved):
    for h, level in saved:
        h.setLevel(level)
