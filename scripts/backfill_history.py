"""
One-time backfill of 10 years of daily OHLCV data for the full universe.

Saves per-symbol Parquet files to data/cache/ohlcv_history/<SYMBOL>.parquet
so they do not interfere with the daily pipeline cache (data/cache/ohlcv/).

Usage:
    python scripts/backfill_history.py              # all symbols, 10 years
    python scripts/backfill_history.py --years 5    # 5 years instead
    python scripts/backfill_history.py --symbols RELIANCE INFY TCS
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Make sure src/ is on the path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

import pandas as pd
import yfinance as yf
from loguru import logger

from stock_analysis.universe.fetcher import load_cached_universe
from stock_analysis.utils.logging_config import setup_logging

_BATCH_SIZE = 20    # smaller batches for long-range downloads (more stable)
_OUT_DIR    = _PROJECT_ROOT / "data" / "cache" / "ohlcv_history"


def _nse(symbol: str) -> str:
    s = symbol.strip().upper()
    return s if s.endswith(".NS") else f"{s}.NS"


def _clean(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.dropna(how="all")
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return None
    df = df[list(required)].copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df.sort_index()


def _save(symbol: str, df: pd.DataFrame) -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"{symbol}.parquet"
    df.to_parquet(path, index=True)


def backfill(symbols: list[str], years: int) -> None:
    end   = date.today()
    start = end - timedelta(days=years * 365 + 10)  # small buffer for weekends
    start_str = start.isoformat()
    end_str   = end.isoformat()

    logger.info(f"Backfill: {len(symbols)} symbols | {start_str} to {end_str} ({years}yr)")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Skip symbols that already have a valid file
    todo = []
    skipped = 0
    for sym in symbols:
        path = _OUT_DIR / f"{sym}.parquet"
        if path.exists():
            skipped += 1
        else:
            todo.append(sym)

    if skipped:
        logger.info(f"Skipping {skipped} already-backfilled symbols. Use --force to re-download.")

    if not todo:
        logger.info("All symbols already backfilled.")
        return

    batches = [todo[i : i + _BATCH_SIZE] for i in range(0, len(todo), _BATCH_SIZE)]
    ok, fail = 0, 0

    for batch_idx, batch in enumerate(batches):
        tickers = [_nse(s) for s in batch]
        logger.info(f"Batch {batch_idx + 1}/{len(batches)}: {batch}")

        try:
            raw = yf.download(
                tickers,
                start=start_str,
                end=end_str,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )

            if len(batch) == 1:
                # Single ticker: flat DataFrame
                df = _clean(raw)
                if df is not None:
                    _save(batch[0], df)
                    ok += 1
                    logger.info(f"  {batch[0]}: {len(df)} rows")
                else:
                    logger.warning(f"  {batch[0]}: no data returned")
                    fail += 1
            else:
                # Multi-ticker: MultiIndex columns, ticker at level 0
                col_level0 = raw.columns.get_level_values(0).tolist()
                for symbol, ticker in zip(batch, tickers):
                    if ticker not in col_level0:
                        logger.warning(f"  {symbol}: no data returned")
                        fail += 1
                        continue
                    df = _clean(raw[ticker].copy())
                    if df is not None:
                        _save(symbol, df)
                        ok += 1
                        logger.info(f"  {symbol}: {len(df)} rows")
                    else:
                        logger.warning(f"  {symbol}: empty after cleaning")
                        fail += 1

        except Exception as e:
            logger.error(f"Batch {batch_idx + 1} failed: {e} — retrying one-by-one")
            for symbol in batch:
                try:
                    ticker = _nse(symbol)
                    raw = yf.download(
                        ticker,
                        start=start_str,
                        end=end_str,
                        interval="1d",
                        auto_adjust=True,
                        progress=False,
                    )
                    df = _clean(raw)
                    if df is not None:
                        _save(symbol, df)
                        ok += 1
                        logger.info(f"  {symbol}: {len(df)} rows (single fallback)")
                    else:
                        fail += 1
                except Exception as e2:
                    logger.error(f"  {symbol}: failed ({e2})")
                    fail += 1

        # Brief pause between batches to avoid hammering yfinance
        if batch_idx < len(batches) - 1:
            time.sleep(1.5)

    logger.info(f"Backfill complete: {ok} succeeded, {fail} failed, {skipped} skipped")
    logger.info(f"Files saved to: {_OUT_DIR}")


def main() -> None:
    setup_logging(
        log_dir=_PROJECT_ROOT / "logs",
        log_level="INFO",
        run_date=date.today().isoformat(),
    )

    parser = argparse.ArgumentParser(description="Backfill OHLCV history for NSE stocks")
    parser.add_argument("--years",   type=int, default=10, help="Years of history to fetch (default: 10)")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to backfill (default: full universe)")
    parser.add_argument("--force",   action="store_true", help="Re-download even if file already exists")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        universe_dir = _PROJECT_ROOT / "data" / "universe"
        df = load_cached_universe(universe_dir)
        symbols = df["symbol"].tolist()

    if args.force:
        # Remove existing files so backfill re-downloads them
        removed = 0
        for sym in symbols:
            p = _OUT_DIR / f"{sym}.parquet"
            if p.exists():
                p.unlink()
                removed += 1
        if removed:
            logger.info(f"--force: removed {removed} existing files")

    backfill(symbols, years=args.years)


if __name__ == "__main__":
    main()
