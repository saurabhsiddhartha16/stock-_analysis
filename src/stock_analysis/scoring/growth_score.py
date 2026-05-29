"""Growth score — measures revenue, profit and EPS trajectory (0-100, higher = better)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Score:
    value: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


_WEIGHTS = {
    "revenue_cagr_3yr": 0.35,
    "pat_cagr_3yr": 0.35,
    "eps_cagr_3yr": 0.30,
}


def compute(fundamentals: dict, ai_signals: dict | None = None) -> Score:
    """ai_signals kept for API compatibility but no longer used."""
    sub: dict[str, float] = {}
    sub["revenue_cagr_3yr"] = _cagr_score(fundamentals.get("revenue_cagr_3yr"))
    sub["pat_cagr_3yr"]     = _cagr_score(fundamentals.get("pat_cagr_3yr"))
    sub["eps_cagr_3yr"]     = _cagr_score(fundamentals.get("eps_cagr_3yr"))

    composite  = _weighted(sub, _WEIGHTS)
    explanation = _explain(sub, fundamentals)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _cagr_score(cagr: float | None) -> float:
    """Sigmoid: 0%→40, 15%→60, 30%→75, 50%→88. Negative CAGR → capped at 20."""
    if cagr is None:
        return 50.0
    if cagr < 0:
        return max(5.0, 20.0 + cagr)
    return _sigmoid(cagr, k=0.08, midpoint=18.0)


def _explain(sub: dict, f: dict) -> str:
    parts = []
    rev = f.get("revenue_cagr_3yr")
    pat = f.get("pat_cagr_3yr")
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
