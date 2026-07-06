from __future__ import annotations

import logging
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "uttate.log"


def configure_logging() -> Path:
    """Configure local file logging without exposing API keys.

    The application logs provider errors, HTTP status bodies, and traceback details to a
    repo-local ignored file. Raw input text and API keys are intentionally not logged here.
    """

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_FILE.resolve()
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    logging.getLogger(__name__).info("Logging configured at %s", log_file)
    return log_file
