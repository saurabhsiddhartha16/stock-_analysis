"""Shared pytest fixtures."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """300 days of synthetic OHLCV data sufficient for all indicators."""
    n = 300
    rng = np.random.default_rng(42)
    close = 1000.0 * (1 + rng.normal(0, 0.01, n)).cumprod()
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(100_000, 1_000_000, n).astype(float)

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
