"""
NutriTrack Centralized Logging Configuration
=============================================
Provides a consistent logging setup for all modules.

Usage:
    from config.logging_config import get_logger
    logger = get_logger(__name__)

Log Levels (ascending):
    DEBUG    - Detailed diagnostic info (normalization steps, cache ops)
    INFO     - General operational events (API calls, model loading)
    TITLE    - Section headers (box format, no timestamp on console)
    WARNING  - Unexpected but recoverable (mock fallback, image compression)
    ERROR    - Something failed (API errors, file not found)
    CRITICAL - Application cannot continue

Custom Methods:
    logger.title(msg) - Print a framed section title box, no prefix on console:
        ╔══════════════════════════════╗
        ║   Your Section Title Here    ║
        ╚══════════════════════════════╝
"""

import logging
import os
import sys
import re
from datetime import datetime
from concurrent_log_handler import ConcurrentRotatingFileHandler


# ─── Constants ───────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").strip().lower() in ("1", "true", "yes", "on")

TITLE_MIN_INNER    = 44    # Minimum inner width
TITLE_TOTAL_WIDTH  = 100   # Total width of the terminal line for centering
TITLE_LEVEL        = 25    # Between INFO (20) and WARNING (30)

# Rotation Settings
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5               # Keep old 5 files


# ─── Custom Level ────────────────────────────────────────────────────────────

logging.addLevelName(TITLE_LEVEL, "TITLE")


# ─── Custom Formatter ────────────────────────────────────────────────────────

class NutriBaseFormatter(logging.Formatter):
    """
    Base formatter that truncates long byte strings (b'\\x...')
    and extremely long text messages to prevent log bloat.
    """
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        
        # 1. Truncate byte strings (b'...') that are longer than 100 chars
        # Supports both b'\\x...' and b'ABC...' formats
        if "b'" in formatted or 'b"' in formatted:
            formatted = re.sub(r"(b['\"][^'\"]{20,})['\"]", r"b'<TRUNCATED BYTES>'", formatted)
            
        # 2. Hard limit for any extremely long log message (safety net)
        # If any log record is > 10,000 chars, truncate the middle
        if len(formatted) > 10000:
            formatted = formatted[:1000] + "\n... [MESSAGE TRUNCATED DUE TO LENGTH] ...\n" + formatted[-1000:]
            
        return formatted


class NutriConsoleFormatter(NutriBaseFormatter):
    """
    Console formatter that strips timestamp/level/name prefix for TITLE records,
    so the box is printed clean to the terminal. All other levels use normal format.
    """
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno == TITLE_LEVEL:
            # Return the raw box message, no prefix at all
            return record.getMessage()
        return super().format(record)


# ─── Custom Logger ────────────────────────────────────────────────────────────

class NutriLogger(logging.Logger):
    """
    Extended Logger with logger.title() for visual section headers.

    Console output (Centered, no prefix):
                                ╔══════════════════════╗
                                ║   Starting Suite     ║
                                ╚══════════════════════╝
    """

    def title(self, msg: str, *args, **kwargs) -> None:
        """
        Log a section title at TITLE level (25).
        Centered across TITLE_TOTAL_WIDTH.
        """
        if not self.isEnabledFor(TITLE_LEVEL):
            return

        if args:
            msg = msg % args

        # 1. Calculate box size
        inner_width = max(len(msg) + 6, TITLE_MIN_INNER)
        
        # 2. Build box lines
        top    = f"╔{'═' * inner_width}╗"
        middle = f"║{msg.center(inner_width)}║"
        bottom = f"╚{'═' * inner_width}╝"

        # 3. Center each line relative to terminal width
        for line in ("", top, middle, bottom):
            centered_line = line.center(TITLE_TOTAL_WIDTH)
            self._log(TITLE_LEVEL, centered_line, args=(), **kwargs)


# Register NutriLogger so ALL logging.getLogger() calls return our subclass
logging.setLoggerClass(NutriLogger)


# ─── Setup ───────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    """
    Configure root logger with both console and rotating file handlers.
    Call once at application startup (auto-called by get_logger).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

    # Avoid duplicate handlers on re-import
    if root_logger.handlers:
        return

    running_on_ecs = bool(
        os.getenv("ECS_CONTAINER_METADATA_URI_V4")
        or os.getenv("ECS_CONTAINER_METADATA_URI")
        or os.getenv("AWS_EXECUTION_ENV", "").startswith("AWS_ECS")
    )
    enable_file_logging = LOG_TO_FILE and (not running_on_ecs)

    log_filepath = ""
    session_log_filepath = ""
    if enable_file_logging:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_filename = "nutritrack.log"  # Fixed name since it will rotate automatically
        log_filepath = os.path.join(LOG_DIR, log_filename)
        session_log_filepath = os.path.join(LOG_DIR, "session.log")

        # Try to clean up previous session log if we are the first process starting
        # This maintains the "overwrite per session" feature safely
        import contextlib
        with contextlib.suppress(OSError):
            os.remove(session_log_filepath)

    # 1. Console handler (INFO+) — clean boxes on terminal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        NutriConsoleFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )

    root_logger.addHandler(console_handler)

    if enable_file_logging:
        # 2. Rotating File handler (DEBUG+) — ConcurrentRotatingFileHandler is multi-process
        #    safe on Windows (uses portalocker/file locking instead of os.rename)
        file_handler = ConcurrentRotatingFileHandler(
            log_filepath,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            delay=True,      # Don't open the file until the first write
            use_gzip=False   # Keep .log.1 .log.2 ... readable without decompression
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(NutriConsoleFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

        # 3. Session File Handler (DEBUG+) — Safe concurrent writes per session
        session_handler = ConcurrentRotatingFileHandler(
            session_log_filepath,
            maxBytes=MAX_LOG_SIZE,
            backupCount=0,   # No backups needed for session logs
            encoding="utf-8",
            delay=True
        )
        session_handler.setLevel(logging.DEBUG)
        session_handler.setFormatter(NutriConsoleFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

        root_logger.addHandler(file_handler)
        root_logger.addHandler(session_handler)

    # 4. Capture unhandled exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        root_logger.critical("Unhandled Exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    # 5. Log a "New Session" marker only once per process run
    # This helps visually separate different runs in log files.
    if enable_file_logging:
        session_start_msg = f" NEW SESSION STARTED AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "

        # Temporarily remove console handler so it only prints to .log files
        root_logger.removeHandler(console_handler)
        root_logger.info("")
        root_logger.info("=" * 100)
        root_logger.info(session_start_msg.center(100, "#"))
        root_logger.info("=" * 100)
        root_logger.info("")
        root_logger.addHandler(console_handler)

    # Suppress noisy third-party loggers
    for noisy_logger in (
        "urllib3", "httpcore", "httpx",
        "python_multipart", "python_multipart.multipart", "multipart",
        # botocore — suppress both the top-level and its most verbose sub-loggers
        "botocore", "botocore.hooks", "botocore.loaders",
        "botocore.utils", "botocore.configprovider",
        "botocore.regions", "botocore.endpoint",
        "botocore.client",
        "boto3",
        "ultralytics",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str) -> NutriLogger:
    """
    Get a named NutriLogger. Auto-initializes logging on first call.

    Args:
        name: Usually __name__ of the calling module.

    Returns:
        NutriLogger supporting all standard methods + .title().
    """
    setup_logging()
    return logging.getLogger(name)  # type: ignore[return-value]

