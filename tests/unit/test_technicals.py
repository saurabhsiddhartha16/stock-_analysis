"""Unit tests for data/technicals.py — validates indicator computation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stock_analysis.data.technicals import compute_indicators, get_latest_indicators


class TestComputeIndicators:
    def test_returns_dataframe(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert isinstance(result, pd.DataFrame)

    def test_does_not_modify_input(self, sample_ohlcv):
        original_cols = list(sample_ohlcv.columns)
        compute_indicators(sample_ohlcv)
        assert list(sample_ohlcv.columns) == original_cols

    def test_ohlcv_columns_preserved(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            assert col in result.columns

    def test_sma_columns_present(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        for col in ("SMA_20", "SMA_50", "SMA_200"):
            assert col in result.columns, f"Missing {col}"

    def test_ema_columns_present(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        for col in ("EMA_20", "EMA_50"):
            assert col in result.columns, f"Missing {col}"

    def test_rsi_bounds(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert "RSI_14" in result.columns
        valid = result["RSI_14"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all(), "RSI out of [0, 100]"

    def test_macd_columns_present(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        for col in ("MACD", "MACD_signal", "MACD_hist"):
            assert col in result.columns, f"Missing {col}"

    def test_bollinger_bands_order(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert "BB_upper" in result.columns and "BB_lower" in result.columns
        valid = result[["BB_upper", "BB_lower"]].dropna()
        assert (valid["BB_upper"] >= valid["BB_lower"]).all()

    def test_52w_high_gte_close(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert "52w_high" in result.columns
        valid = result[["Close", "52w_high"]].dropna()
        assert (valid["52w_high"] >= valid["Close"]).all()

    def test_52w_low_lte_close(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert "52w_low" in result.columns
        valid = result[["Close", "52w_low"]].dropna()
        assert (valid["52w_low"] <= valid["Close"]).all()

    def test_price_vs_sma200_pct_sign(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert "price_vs_sma200_pct" in result.columns
        last = result.iloc[-1]
        if pd.notna(last["SMA_200"]) and pd.notna(last["price_vs_sma200_pct"]):
            expected_sign = 1 if last["Close"] >= last["SMA_200"] else -1
            actual_sign = 1 if last["price_vs_sma200_pct"] >= 0 else -1
            assert expected_sign == actual_sign

    def test_volume_sma_20_positive(self, sample_ohlcv):
        result = compute_indicators(sample_ohlcv)
        assert "volume_sma_20" in result.columns
        valid = result["volume_sma_20"].dropna()
        assert (valid > 0).all()

    def test_sma_monotone_smoothing(self, sample_ohlcv):
        """SMA_200 should have lower variance than raw close."""
        result = compute_indicators(sample_ohlcv)
        close_std = sample_ohlcv["Close"].std()
        sma200_std = result["SMA_200"].dropna().std()
        assert sma200_std < close_std, "SMA_200 should smooth price variability"


class TestGetLatestIndicators:
    def test_returns_dict(self, sample_ohlcv):
        indicators = get_latest_indicators(sample_ohlcv)
        assert isinstance(indicators, dict)

    def test_expected_keys_present(self, sample_ohlcv):
        indicators = get_latest_indicators(sample_ohlcv)
        expected_keys = {
            "SMA_20", "SMA_50", "SMA_200", "EMA_20", "EMA_50",
            "RSI_14", "MACD", "MACD_signal", "MACD_hist",
            "BB_upper", "BB_lower", "ATR_14", "volume_sma_20",
            "52w_high", "52w_low", "price_vs_sma50_pct", "price_vs_sma200_pct",
            "pct_from_52w_high", "close", "volume",
        }
        missing = expected_keys - set(indicators.keys())
        assert not missing, f"Missing indicator keys: {missing}"

    def test_values_are_float_or_none(self, sample_ohlcv):
        indicators = get_latest_indicators(sample_ohlcv)
        for k, v in indicators.items():
            assert v is None or isinstance(v, float), f"{k}: expected float|None, got {type(v)}"

    def test_empty_dataframe_returns_empty_dict(self):
        empty_df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        result = get_latest_indicators(empty_df)
        assert result == {}

    def test_none_input_returns_empty_dict(self):
        result = get_latest_indicators(None)
        assert result == {}

    def test_close_matches_last_row(self, sample_ohlcv):
        indicators = get_latest_indicators(sample_ohlcv)
        expected_close = float(sample_ohlcv["Close"].iloc[-1])
        assert abs(indicators["close"] - expected_close) < 1e-6
