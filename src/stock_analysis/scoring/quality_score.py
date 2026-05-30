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
    "roe_consistency":      0.20,   # ROE level + consistency penalty
    "roce_vs_wacc_spread":  0.20,   # Capital efficiency vs cost of capital
    "cfo_pat_conversion":   0.20,   # Earnings quality: CFO / PAT
    "fcf_conversion_ratio": 0.20,   # FCF / PAT (after capex)
    "working_capital_trend": 0.10,  # Placeholder — Phase 3
    "cash_to_market_cap":   0.10,   # Balance sheet strength
}

_ASSUMED_WACC = 12.0  # % — reasonable for Indian large/mid caps


def compute(fundamentals: dict) -> Score:
    sub: dict[str, float] = {}

    sub["roe_consistency"] = _roe_score(
        fundamentals.get("roe_5yr_avg"),
        fundamentals.get("roe_ttm"),
        fundamentals.get("roe_annual_series"),
    )
    sub["roce_vs_wacc_spread"] = _roce_score(fundamentals.get("roce"))
    sub["cfo_pat_conversion"] = _cfo_pat_score(
        fundamentals.get("cfo_trailing_cr"), fundamentals.get("pat_ttm_cr")
    )
    sub["fcf_conversion_ratio"] = _fcf_score(
        fundamentals.get("fcf_trailing_cr"), fundamentals.get("pat_ttm_cr")
    )
    sub["working_capital_trend"] = 50.0  # Phase 3: will use historical data
    sub["cash_to_market_cap"] = _cash_score(
        fundamentals.get("cash_cr"), fundamentals.get("market_cap_cr")
    )

    composite = _weighted(sub, _WEIGHTS)
    explanation = _explain(sub, fundamentals)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _roe_score(
    roe_5yr: float | None,
    roe_ttm: float | None,
    roe_series: list | None = None,
) -> float:
    """
    ROE level scored via sigmoid, then penalised for inconsistency.
    Level:       0% → 30, 12% → 55, 20% → 70, 30%+ → 85.
    Consistency: coefficient of variation (std/mean) > 0.3 → up to 20-pt penalty.
    """
    roe = roe_5yr if roe_5yr is not None else roe_ttm
    if roe is None:
        return 40.0
    if roe < 0:
        return max(5.0, 20.0 + roe)

    base = _sigmoid(roe, k=0.09, midpoint=18.0)

    # Apply consistency penalty if we have ≥3 years of data
    if roe_series and len(roe_series) >= 3:
        window = roe_series[:5]
        mean = sum(window) / len(window)
        if mean > 0:
            variance = sum((r - mean) ** 2 for r in window) / len(window)
            std = math.sqrt(variance)
            cv = std / mean  # coefficient of variation
            # CV > 0.3 is moderately inconsistent; > 0.6 is highly inconsistent
            penalty = min(20.0, max(0.0, (cv - 0.3) * 40.0))
            base = max(10.0, base - penalty)

    return base


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


def _cfo_pat_score(cfo: float | None, pat: float | None) -> float:
    """
    CFO / PAT — earnings quality / accruals check.
    Negative CFO → 15, ratio 0.5 → 42, 0.8 → 58, 1.0 → 67, 1.2+ → 78, 1.5+ → 88.
    Companies with CFO < PAT are booking earnings before receiving cash (accruals risk).
    """
    if cfo is None or pat is None:
        return 45.0
    if pat <= 0:
        return 30.0 if cfo > 0 else 15.0
    ratio = cfo / pat
    if ratio < 0:
        return max(10.0, 20.0 + ratio * 10)
    return _sigmoid(ratio, k=2.0, midpoint=0.90)


def _fcf_score(fcf: float | None, pat: float | None) -> float:
    """
    FCF / PAT ratio — cash generation after capex.
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
    cfo = f.get("cfo_trailing_cr")
    pat = f.get("pat_ttm_cr")
    if roe is not None:
        parts.append(f"ROE: {roe:.1f}%")
    if roce is not None:
        parts.append(f"ROCE: {roce:.1f}% (WACC {_ASSUMED_WACC}%)")
    if cfo is not None and pat is not None and pat > 0:
        parts.append(f"CFO/PAT: {cfo/pat:.2f}x")
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
