"""Downloads and caches OHLCV data for NSE stocks via yfinance."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

from stock_analysis.data.cache import DiskCache

_BATCH_SIZE = 50          # yfinance handles ~50 tickers per download call well
_HISTORY_PERIOD = "1y"   # 1 year of daily OHLCV
_TTL_HOURS = 24


def _nse_ticker(symbol: str) -> str:
    """Convert bare NSE symbol to yfinance format (append .NS)."""
    symbol = symbol.strip().upper()
    if not symbol.endswith(".NS"):
        return f"{symbol}.NS"
    return symbol


def fetch_ohlcv(
    symbols: list[str],
    cache: DiskCache,
    ttl_hours: float = _TTL_HOURS,
    period: str = _HISTORY_PERIOD,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV for all symbols. Returns {symbol: DataFrame} with columns:
    Open, High, Low, Close, Volume (date index).
    Uses cache; only downloads missing/stale tickers.
    """
    results: dict[str, pd.DataFrame] = {}
    to_download: list[str] = []

    for symbol in symbols:
        cached = cache.get_df("ohlcv", symbol)
        if cached is not None:
            results[symbol] = cached
        else:
            to_download.append(symbol)

    if not to_download:
        logger.info("OHLCV: all symbols served from cache")
        return results

    logger.info(f"OHLCV: downloading {len(to_download)} symbols in batches of {_BATCH_SIZE}")
    batches = [to_download[i : i + _BATCH_SIZE] for i in range(0, len(to_download), _BATCH_SIZE)]

    for batch_idx, batch in enumerate(batches):
        tickers = [_nse_ticker(s) for s in batch]
        logger.debug(f"Batch {batch_idx + 1}/{len(batches)}: {tickers[:5]}...")
        try:
            raw = yf.download(
                tickers,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            _unpack_batch(raw, batch, tickers, results, cache, ttl_hours)
        except Exception as e:
            logger.error(f"Batch download failed: {e}. Falling back to per-ticker fetch.")
            _fetch_one_by_one(batch, results, cache, ttl_hours, period)

    logger.info(f"OHLCV: {len(results)}/{len(symbols)} symbols loaded")
    return results


def _unpack_batch(
    raw: pd.DataFrame,
    symbols: list[str],
    tickers: list[str],
    results: dict[str, pd.DataFrame],
    cache: DiskCache,
    ttl_hours: float,
) -> None:
    """Parse yfinance multi-ticker download result into per-symbol DataFrames."""
    if len(tickers) == 1:
        # Single ticker: yfinance returns a flat DataFrame
        symbol = symbols[0]
        df = _clean(raw)
        if df is not None:
            cache.set_df("ohlcv", symbol, df, ttl_hours)
            results[symbol] = df
        return

    # yfinance 1.x returns MultiIndex columns: (Ticker, Price) — ticker at level 0
    col_level0 = raw.columns.get_level_values(0).tolist()

    for symbol, ticker in zip(symbols, tickers):
        try:
            if ticker not in col_level0:
                logger.warning(f"No OHLCV data returned for {symbol}")
                continue
            df = raw[ticker].copy()
            if df is None or df.empty:
                logger.warning(f"Empty OHLCV for {symbol}")
                continue
            df = _clean(df)
            if df is not None:
                cache.set_df("ohlcv", symbol, df, ttl_hours)
                results[symbol] = df
        except Exception as e:
            logger.warning(f"Failed to unpack {symbol}: {e}")


def _fetch_one_by_one(
    symbols: list[str],
    results: dict[str, pd.DataFrame],
    cache: DiskCache,
    ttl_hours: float,
    period: str,
) -> None:
    """Per-ticker fallback when batch download fails."""
    for symbol in symbols:
        try:
            ticker = _nse_ticker(symbol)
            raw = yf.download(ticker, period=period, interval="1d",
                              auto_adjust=True, progress=False)
            df = _clean(raw)
            if df is not None:
                cache.set_df("ohlcv", symbol, df, ttl_hours)
                results[symbol] = df
        except Exception as e:
            logger.error(f"Per-ticker fetch failed for {symbol}: {e}")


def _clean(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.dropna(how="all")
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        return None
    df = df[list(required)].copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df.sort_index()


def get_latest_price(symbol: str, cache: DiskCache) -> float | None:
    """Return the most recent closing price from cache."""
    df = cache.get_df("ohlcv", symbol)
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])
