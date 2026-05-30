"""Computes technical indicators from OHLCV DataFrames using pandas-ta."""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta  # type: ignore
    _HAS_PANDAS_TA = True
except ImportError:
    _HAS_PANDAS_TA = False


def compute_indicators(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators for a single stock's OHLCV DataFrame.

    Args:
        ohlcv: DataFrame with columns Open, High, Low, Close, Volume (date index).

    Returns:
        Copy of ohlcv with additional indicator columns appended.
        The last row contains the most current values for screening.
    """
    df = ohlcv.copy()

    if _HAS_PANDAS_TA:
        _compute_with_pandas_ta(df)
    else:
        _compute_manual(df)

    _compute_derived(df)
    return df


def get_latest_indicators(ohlcv: pd.DataFrame) -> dict:
    """
    Return a flat dict of the most recent indicator values — used by the screener.
    All values are plain Python floats (or None if unavailable).
    """
    if ohlcv is None or ohlcv.empty:
        return {}
    df = compute_indicators(ohlcv)
    last = df.iloc[-1]

    def _val(col: str) -> float | None:
        if col not in df.columns:
            return None
        v = last[col]
        return float(v) if pd.notna(v) else None

    return {
        "SMA_20": _val("SMA_20"),
        "SMA_50": _val("SMA_50"),
        "SMA_200": _val("SMA_200"),
        "EMA_20": _val("EMA_20"),
        "EMA_50": _val("EMA_50"),
        "RSI_14": _val("RSI_14"),
        "MACD": _val("MACD"),
        "MACD_signal": _val("MACD_signal"),
        "MACD_hist": _val("MACD_hist"),
        "BB_upper": _val("BB_upper"),
        "BB_lower": _val("BB_lower"),
        "ATR_14": _val("ATR_14"),
        "volume_sma_20": _val("volume_sma_20"),
        "52w_high": _val("52w_high"),
        "52w_low": _val("52w_low"),
        "price_vs_sma50_pct": _val("price_vs_sma50_pct"),
        "price_vs_sma200_pct": _val("price_vs_sma200_pct"),
        "pct_from_52w_high": _val("pct_from_52w_high"),
        "return_1m": _val("return_1m"),
        "return_3m": _val("return_3m"),
        "close": _val("Close"),
        "volume": _val("Volume"),
    }


# ── pandas-ta implementation ──────────────────────────────────────────────────

def _compute_with_pandas_ta(df: pd.DataFrame) -> None:
    """Add indicators using pandas-ta (preferred path)."""
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.atr(length=14, append=True)

    # Normalise column names from pandas-ta defaults
    _rename_ta_cols(df)

    # Volume SMA
    df["volume_sma_20"] = df["Volume"].rolling(20).mean()


def _rename_ta_cols(df: pd.DataFrame) -> None:
    """pandas-ta uses names like SMA_20, EMA_20, RSI_14, MACD_12_26_9, etc."""
    rename = {}
    for col in list(df.columns):
        if col.startswith("MACD_12_26_9"):
            rename[col] = "MACD"
        elif col.startswith("MACDh_12_26_9"):
            rename[col] = "MACD_hist"
        elif col.startswith("MACDs_12_26_9"):
            rename[col] = "MACD_signal"
        elif col.startswith("BBU_20_2.0"):
            rename[col] = "BB_upper"
        elif col.startswith("BBL_20_2.0"):
            rename[col] = "BB_lower"
        elif col.startswith("ATRr_14"):
            rename[col] = "ATR_14"
    if rename:
        df.rename(columns=rename, inplace=True)


# ── Manual fallback (no pandas-ta) ───────────────────────────────────────────

def _compute_manual(df: pd.DataFrame) -> None:
    """Pure-pandas fallback for environments without pandas-ta."""
    close = df["Close"]
    volume = df["Volume"]
    high = df["High"]
    low = df["Low"]

    for n in (20, 50, 200):
        df[f"SMA_{n}"] = close.rolling(n).mean()
    for n in (20, 50):
        df[f"EMA_{n}"] = close.ewm(span=n, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["BB_upper"] = sma20 + 2 * std20
    df["BB_lower"] = sma20 - 2 * std20

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    df["ATR_14"] = tr.rolling(14).mean()

    df["volume_sma_20"] = volume.rolling(20).mean()


# ── Derived ratio columns ─────────────────────────────────────────────────────

def _compute_derived(df: pd.DataFrame) -> None:
    """Add ratio columns that are useful for screening."""
    close = df["Close"]

    if "SMA_50" in df.columns:
        df["price_vs_sma50_pct"] = (close / df["SMA_50"] - 1) * 100
    if "SMA_200" in df.columns:
        df["price_vs_sma200_pct"] = (close / df["SMA_200"] - 1) * 100

    # Rolling 52-week (252 trading days) high/low
    df["52w_high"] = close.rolling(252, min_periods=50).max()
    df["52w_low"] = close.rolling(252, min_periods=50).min()
    df["pct_from_52w_high"] = (close / df["52w_high"] - 1) * 100

    # Price returns (1m ≈ 21 trading days, 3m ≈ 63 trading days)
    df["return_1m"] = (close / close.shift(21) - 1) * 100
    df["return_3m"] = (close / close.shift(63) - 1) * 100
