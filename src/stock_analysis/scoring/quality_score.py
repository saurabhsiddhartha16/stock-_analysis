"""Quality score — balance sheet and capital efficiency (0-100, higher = better)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Score:
    value: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


_WEIGHTS = {
    "roe_consistency": 0.25,
    "roce_vs_wacc_spread": 0.25,
    "fcf_conversion_ratio": 0.25,
    "working_capital_trend": 0.15,
    "cash_to_market_cap": 0.10,
}

_ASSUMED_WACC = 12.0  # % — reasonable for Indian large/mid caps


def compute(fundamentals: dict) -> Score:
    sub: dict[str, float] = {}

    sub["roe_consistency"] = _roe_score(
        fundamentals.get("roe_5yr_avg"), fundamentals.get("roe_ttm")
    )
    sub["roce_vs_wacc_spread"] = _roce_score(fundamentals.get("roce"))
    sub["fcf_conversion_ratio"] = _fcf_score(
        fundamentals.get("fcf_trailing_cr"), fundamentals.get("pat_ttm_cr")
    )
    sub["working_capital_trend"] = 50.0  # Phase 3: will use AI/historical data
    sub["cash_to_market_cap"] = _cash_score(
        fundamentals.get("cash_cr"), fundamentals.get("market_cap_cr")
    )

    composite = _weighted(sub, _WEIGHTS)
    explanation = _explain(sub, fundamentals)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _roe_score(roe_5yr: float | None, roe_ttm: float | None) -> float:
    """
    Use 5yr avg ROE if available (consistency reward), else TTM.
    ROE 0% → 30, 12% → 55, 20% → 70, 30%+ → 85.
    """
    roe = roe_5yr if roe_5yr is not None else roe_ttm
    if roe is None:
        return 40.0
    if roe < 0:
        return max(5.0, 20.0 + roe)
    return _sigmoid(roe, k=0.09, midpoint=18.0)


def _roce_score(roce: float | None) -> float:
    """
    ROCE - WACC spread.
    spread < 0 → 20, 0 → 45, 5% → 60, 15% → 75, 25%+ → 88.
    """
    if roce is None:
        return 40.0
    spread = roce - _ASSUMED_WACC
    if spread < 0:
        return max(10.0, 45.0 + spread * 2)
    return _sigmoid(spread, k=0.12, midpoint=8.0)


def _fcf_score(fcf: float | None, pat: float | None) -> float:
    """
    FCF / PAT ratio.
    Negative FCF → 20, ratio 0.5 → 50, 0.8 → 65, 1.0 → 72, 1.2+ → 82.
    """
    if fcf is None or pat is None:
        return 45.0
    if pat <= 0:
        return 30.0 if fcf > 0 else 15.0
    ratio = fcf / pat
    if ratio < 0:
        return max(10.0, 20.0 + ratio * 10)
    return _sigmoid(ratio, k=2.5, midpoint=0.85)


def _cash_score(cash_cr: float | None, market_cap_cr: float | None) -> float:
    """
    Cash as % of market cap.
    0% → 40, 5% → 55, 15% → 70, 25%+ → 80.
    """
    if cash_cr is None or market_cap_cr is None or market_cap_cr <= 0:
        return 40.0
    pct = (cash_cr / market_cap_cr) * 100
    return _sigmoid(pct, k=0.12, midpoint=10.0)


def _explain(sub: dict, f: dict) -> str:
    parts = []
    roe = f.get("roe_5yr_avg") or f.get("roe_ttm")
    roce = f.get("roce")
    if roe is not None:
        parts.append(f"ROE: {roe:.1f}%")
    if roce is not None:
        parts.append(f"ROCE: {roce:.1f}% (WACC {_ASSUMED_WACC}%)")
    return "; ".join(parts) if parts else "Insufficient data"


def _weighted(sub: dict[str, float], weights: dict[str, float]) -> float:
    total_w = sum(weights.get(k, 0) for k in sub)
    if total_w == 0:
        return 45.0
    return sum(sub[k] * weights.get(k, 0) for k in sub) / total_w * (
        sum(weights.values()) / total_w if total_w else 1
    )


def _sigmoid(x: float, k: float, midpoint: float) -> float:
    return 100.0 / (1.0 + math.exp(-k * (x - midpoint)))
