"""
Entry point for Windows Task Scheduler.
Runs the full stock analysis pipeline and sends email.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

# Ensure project src is on the path when run by Task Scheduler
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from loguru import logger
from stock_analysis.main import run
from stock_analysis.utils.logging_config import setup_logging

_NSE_HOLIDAYS_2025_26 = {
    "2026-01-26",  # Republic Day
    "2026-02-18",  # Mahashivratri
    "2026-03-13",  # Holi
    "2026-04-02",  # Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-26",  # Diwali Laxmi Pujan (approx)
    "2026-11-25",  # Gurunanak Jayanti (approx)
    "2026-12-25",  # Christmas
}


def is_trading_day(dt: date) -> bool:
    """Return False on NSE holidays (weekends included — scheduler runs every day)."""
    if dt.isoformat() in _NSE_HOLIDAYS_2025_26:
        return False
    return True


if __name__ == "__main__":
    today = date.today()

    setup_logging(
        log_dir=_PROJECT_ROOT / "logs",
        log_level="INFO",
        run_date=today.isoformat(),
    )

    if not is_trading_day(today):
        logger.info(f"{today} is not a trading day — skipping run.")
        sys.exit(0)

    logger.info(f"Daily run starting — {today} {datetime.now().strftime('%H:%M')}")
    try:
        run(run_date=today.isoformat(), mode="full", resume=True)
        logger.info("Daily run completed successfully.")
    except Exception as e:
        logger.exception(f"Daily run failed: {e}")
        sys.exit(1)
