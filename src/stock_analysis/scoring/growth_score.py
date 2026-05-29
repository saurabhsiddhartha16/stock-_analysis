"""Growth score — measures revenue, profit and EPS trajectory (0-100, higher = better)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Score:
    value: float                          # 0-100 composite
    sub_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


_WEIGHTS = {
    "revenue_cagr_3yr": 0.30,
    "pat_cagr_3yr": 0.30,
    "eps_cagr_3yr": 0.25,
    "analyst_revision_signal": 0.15,
}


def compute(fundamentals: dict, ai_signals: dict | None = None) -> Score:
    """
    Args:
        fundamentals: dict from data/fundamentals.py
        ai_signals:   optional dict with key 'analyst_revision_signal' in {-1, 0, 1}
    """
    sub: dict[str, float] = {}

    sub["revenue_cagr_3yr"] = _cagr_score(fundamentals.get("revenue_cagr_3yr"))
    sub["pat_cagr_3yr"] = _cagr_score(fundamentals.get("pat_cagr_3yr"))
    sub["eps_cagr_3yr"] = _cagr_score(fundamentals.get("eps_cagr_3yr"))
    sub["analyst_revision_signal"] = _revision_score(
        (ai_signals or {}).get("analyst_revision_signal", 0)
    )

    composite = _weighted(sub, _WEIGHTS)
    explanation = _explain(sub, fundamentals)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _cagr_score(cagr: float | None) -> float:
    """
    Map CAGR % → 0-100 using sigmoid.
    Calibration: 0% → 40, 15% → 60, 30% → 75, 50% → 88, negative → capped at 20.
    """
    if cagr is None:
        return 50.0  # neutral for missing data
    if cagr < 0:
        return max(5.0, 20.0 + cagr)  # negative CAGR rapidly approaches 0
    return _sigmoid(cagr, k=0.08, midpoint=18.0)


def _revision_score(signal: int | float) -> float:
    """+1 upgrade → 70, 0 neutral → 55, -1 downgrade → 30."""
    mapping = {1: 70.0, 0: 55.0, -1: 30.0}
    return mapping.get(int(signal), 55.0)


def _explain(sub: dict, f: dict) -> str:
    rev = f.get("revenue_cagr_3yr")
    pat = f.get("pat_cagr_3yr")
    parts = []
    if rev is not None:
        parts.append(f"Revenue CAGR 3yr: {rev:.1f}%")
    if pat is not None:
        parts.append(f"PAT CAGR 3yr: {pat:.1f}%")
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
