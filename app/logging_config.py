"""
Process-wide logging.

One `logging` configuration, level from LOG_LEVEL, plain text to stderr so
it reads the same under uvicorn, in a container and in the desktop bundle's
log file. Modules take `logging.getLogger(__name__)` and never print.
"""
from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Third-party chatter that drowns out our own lines at INFO.
    for noisy in ("httpx", "httpcore", "fastembed", "onnxruntime"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
