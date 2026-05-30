"""Momentum score — price trend and relative strength (0-100, higher = better)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Score:
    value: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


_WEIGHTS = {
    "price_vs_sma200_pct":          0.15,  # Long-term trend confirmation
    "price_vs_sma50_pct":           0.10,  # Short-term trend
    "rsi_positioning":              0.10,  # Oscillator positioning
    "macd_signal_alignment":        0.10,  # Trend momentum signal
    "return_1m":                    0.15,  # Recent price momentum
    "return_3m":                    0.20,  # Medium-term momentum
    "relative_strength_vs_nifty50": 0.20,  # Outperformance vs index (3m)
}


def compute(technicals: dict, nifty_return_3m: float | None = None) -> Score:
    """
    Args:
        technicals:         dict from data/technicals.get_latest_indicators()
        nifty_return_3m:    Nifty 50 3-month return % (used for relative strength calc)
    """
    sub: dict[str, float] = {}

    sub["price_vs_sma200_pct"]   = _vs_ma_score(technicals.get("price_vs_sma200_pct"))
    sub["price_vs_sma50_pct"]    = _vs_ma_score(technicals.get("price_vs_sma50_pct"))
    sub["rsi_positioning"]       = _rsi_score(technicals.get("RSI_14"))
    sub["macd_signal_alignment"] = _macd_score(
        technicals.get("MACD"), technicals.get("MACD_signal"), technicals.get("MACD_hist")
    )
    sub["return_1m"] = _price_return_score(technicals.get("return_1m"))
    sub["return_3m"] = _price_return_score(technicals.get("return_3m"))
    sub["relative_strength_vs_nifty50"] = _rel_strength_score(
        technicals.get("return_3m"), nifty_return_3m
    )

    composite = _weighted(sub, _WEIGHTS)
    explanation = _explain(sub, technicals)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _vs_ma_score(pct: float | None) -> float:
    """
    % above/below MA → score.
    -20% → 20, -5% → 40, 0% → 52, +10% → 65, +30% → 80.
    """
    if pct is None:
        return 50.0
    pct = max(-50.0, min(100.0, pct))
    return _sigmoid(pct, k=0.06, midpoint=5.0)


def _price_return_score(ret: float | None) -> float:
    """
    Absolute price return % → score.
    -20% → 22, -5% → 38, 0% → 50, +10% → 63, +25% → 78, +50%+ → 90.
    """
    if ret is None:
        return 50.0
    ret = max(-60.0, min(150.0, ret))
    return _sigmoid(ret, k=0.07, midpoint=5.0)


def _rsi_score(rsi: float | None) -> float:
    """
    RSI < 30 (oversold) → 25, 30-50 → 35-55, 50-65 → 55-75, 65-75 → 75-70,
    > 75 (overbought) → 55 (fading momentum, not confirmed).
    """
    if rsi is None:
        return 50.0
    if rsi < 30:
        return 25.0
    if rsi < 50:
        return 35.0 + (rsi - 30) * 1.0    # 35-55
    if rsi < 65:
        return 55.0 + (rsi - 50) * 1.33   # 55-75
    if rsi < 75:
        return 75.0 - (rsi - 65) * 0.5    # 75-70 (slightly fading)
    return 55.0  # Overbought — momentum may be exhausted


def _macd_score(macd: float | None, signal: float | None, hist: float | None) -> float:
    """
    Bullish crossover (hist flipped positive) → 70
    MACD above signal → 62
    MACD below signal → 38
    Bearish crossover → 30
    """
    if macd is None or signal is None:
        return 50.0
    if hist is None:
        hist = macd - signal
    if macd > signal and hist > 0:
        return 70.0
    if macd > signal and hist <= 0:
        return 62.0
    if macd <= signal and hist < 0:
        return 38.0
    return 30.0


def _rel_strength_score(return_3m: float | None, nifty_3m: float | None) -> float:
    """
    Relative strength = stock 3m return − Nifty 3m return.
    Spread +0% → 50, +10% → 73, +20% → 88, -10% → 27, -20% → 12.
    """
    if return_3m is None or nifty_3m is None:
        return 50.0
    spread = return_3m - nifty_3m
    return _sigmoid(spread, k=0.10, midpoint=0.0)


def _explain(sub: dict, t: dict) -> str:
    parts = []
    rsi = t.get("RSI_14")
    sma200 = t.get("price_vs_sma200_pct")
    r1m = t.get("return_1m")
    r3m = t.get("return_3m")
    if rsi is not None:
        parts.append(f"RSI: {rsi:.1f}")
    if sma200 is not None:
        parts.append(f"vs SMA200: {sma200:+.1f}%")
    if r1m is not None:
        parts.append(f"1m: {r1m:+.1f}%")
    if r3m is not None:
        parts.append(f"3m: {r3m:+.1f}%")
    return "; ".join(parts) if parts else "Insufficient data"


def _weighted(sub: dict[str, float], weights: dict[str, float]) -> float:
    total_w = sum(weights.get(k, 0) for k in sub)
    if total_w == 0:
        return 50.0
    return sum(sub[k] * weights.get(k, 0) for k in sub) / total_w * (
        sum(weights.values()) / total_w if total_w else 1
    )


def _sigmoid(x: float, k: float, midpoint: float) -> float:
    return 100.0 / (1.0 + math.exp(-k * (x - midpoint)))
