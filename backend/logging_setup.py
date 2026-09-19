from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import db

_CONFIGURED = False


def configure_logging() -> Path:
    """Configure console + bounded persistent logs for overnight diagnostics."""
    global _CONFIGURED

    log_dir = db.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "backend.log"

    if _CONFIGURED:
        return log_path

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Keep the existing console diagnostics visible.
    if not any(getattr(handler, "_xhs_console", False) for handler in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        console._xhs_console = True  # type: ignore[attr-defined]
        root.addHandler(console)

    if not any(getattr(handler, "_xhs_file", False) for handler in root.handlers):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        file_handler._xhs_file = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    # High-frequency local polling is not useful for overnight diagnosis.
    # Keep warnings/errors, but avoid filling the file with HTTP 200 access lines.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger(__name__).info(
        "Persistent backend logging enabled: %s (5 MiB x 6 files max)",
        log_path,
    )
    return log_path
