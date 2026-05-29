"""Risk score — 0-100, higher = riskier. Penalises composite score."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Score:
    value: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


_WEIGHTS = {
    "debt_equity_normalized": 0.25,
    "interest_coverage_inverted": 0.20,
    "beta_normalized": 0.20,
    "promoter_pledge_pct": 0.20,
    "auditor_qualification_flag": 0.15,
}


def compute(fundamentals: dict, ai_signals: dict | None = None) -> Score:
    """
    Args:
        fundamentals: dict from data/fundamentals.py
        ai_signals:   optional dict with key 'auditor_qualification' in {none, minor, material}
    """
    sub: dict[str, float] = {}

    sub["debt_equity_normalized"] = _de_risk(fundamentals.get("debt_equity"))
    sub["interest_coverage_inverted"] = _ic_risk(fundamentals.get("interest_coverage"))
    sub["beta_normalized"] = _beta_risk(fundamentals.get("beta"))
    sub["promoter_pledge_pct"] = _pledge_risk(fundamentals.get("promoter_pledge_pct"))
    sub["auditor_qualification_flag"] = _audit_risk(
        (ai_signals or {}).get("auditor_qualification", "none")
    )

    composite = _weighted(sub, _WEIGHTS)
    explanation = _explain(sub, fundamentals)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _de_risk(de: float | None) -> float:
    """D/E 0 → 5, 0.5 → 20, 1 → 40, 2 → 65, 3+ → 85."""
    if de is None:
        return 30.0
    if de < 0:
        return 10.0  # net-cash company
    return min(95.0, _sigmoid(de, k=1.2, midpoint=1.5))


def _ic_risk(ic: float | None) -> float:
    """Interest coverage: >10 → 10, 5 → 30, 2 → 60, <1 → 90."""
    if ic is None:
        return 40.0
    if ic >= 10:
        return 10.0
    if ic <= 0:
        return 90.0
    # Invert: low IC = high risk
    return min(90.0, _sigmoid(-ic, k=0.6, midpoint=-3.0) + 10)


def _beta_risk(beta: float | None) -> float:
    """Beta 0.3 → 10, 0.8 → 30, 1.2 → 55, 1.8+ → 80."""
    if beta is None:
        return 35.0
    return min(95.0, max(5.0, _sigmoid(beta, k=2.5, midpoint=1.0)))


def _pledge_risk(pledge: float | None) -> float:
    """Promoter pledge %: 0 → 5, 10 → 30, 30 → 60, 50+ → 85."""
    if pledge is None:
        return 10.0
    return min(95.0, max(5.0, _sigmoid(pledge, k=0.07, midpoint=25.0)))


def _audit_risk(qualification: str) -> float:
    mapping = {"none": 5.0, "minor": 30.0, "material": 80.0}
    return mapping.get(str(qualification).lower(), 10.0)


def _explain(sub: dict, f: dict) -> str:
    parts = []
    de = f.get("debt_equity")
    ic = f.get("interest_coverage")
    if de is not None:
        parts.append(f"D/E: {de:.2f}")
    if ic is not None:
        parts.append(f"Int. coverage: {ic:.1f}x")
    pledge = f.get("promoter_pledge_pct")
    if pledge is not None:
        parts.append(f"Pledge: {pledge:.1f}%")
    return "; ".join(parts) if parts else "Insufficient data"


def _weighted(sub: dict[str, float], weights: dict[str, float]) -> float:
    total_w = sum(weights.get(k, 0) for k in sub)
    if total_w == 0:
        return 35.0
    return sum(sub[k] * weights.get(k, 0) for k in sub) / total_w * (
        sum(weights.values()) / total_w if total_w else 1
    )


def _sigmoid(x: float, k: float, midpoint: float) -> float:
    return 100.0 / (1.0 + math.exp(-k * (x - midpoint)))
