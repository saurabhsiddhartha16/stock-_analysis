"""Configures loguru with file rotation and structured console output."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path, log_level: str = "INFO", run_date: str = "") -> None:
    """
    Configure loguru sinks:
    - Console: coloured, human-readable
    - File: JSON-structured, rotated daily, retained 30 days
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()

    # Console sink — human-readable
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
        ),
        colorize=True,
    )

    # File sink — structured JSON for log aggregation / post-run review
    suffix = f"_{run_date}" if run_date else ""
    log_file = log_dir / f"stock_analysis{suffix}.log"
    logger.add(
        str(log_file),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
        rotation="00:00",     # New file each midnight
        retention="30 days",
        compression="zip",
        encoding="utf-8",
    )

    logger.info(f"Logging initialised — level={log_level}, file={log_file}")
