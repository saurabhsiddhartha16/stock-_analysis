"""
Valuation score — 0-100, higher = cheaper / better value.

Metrics (all inverted: lower ratio → higher score):
  PEG ratio  = trailing PE / revenue_cagr_3yr   weight 50%
  P/FCF      = market_cap_cr / fcf_trailing_cr  weight 35%
  P/B        = price-to-book                    weight 15%

Missing metrics are excluded from the weighted average so the score
is still meaningful when only some data is available.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Score:
    value: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


_WEIGHTS = {
    "peg_score":  0.50,
    "p_fcf_score": 0.35,
    "pb_score":   0.15,
}


def compute(fundamentals: dict, technicals: dict | None = None) -> Score:
    sub: dict[str, float] = {}

    # ── PEG ratio ─────────────────────────────────────────────────────────────
    pe     = fundamentals.get("pe_ratio")
    growth = fundamentals.get("revenue_cagr_3yr") or fundamentals.get("pat_cagr_3yr")
    if pe and growth and pe > 0 and growth > 1:
        peg = pe / growth
        sub["peg_score"] = _inv_sigmoid(peg, k=0.8, midpoint=2.5)
    # Negative PE (loss-making) or no growth → very poor valuation
    elif pe and pe < 0:
        sub["peg_score"] = 5.0
    # No PE data → neutral
    # (omitted from sub so it doesn't drag down the average)

    # ── P / FCF ───────────────────────────────────────────────────────────────
    mkt_cap = fundamentals.get("market_cap_cr")
    fcf     = fundamentals.get("fcf_trailing_cr")
    if mkt_cap and fcf and fcf > 0 and mkt_cap > 0:
        p_fcf = mkt_cap / fcf
        sub["p_fcf_score"] = _inv_sigmoid(p_fcf, k=0.07, midpoint=28.0)
    elif fcf and fcf < 0:
        sub["p_fcf_score"] = 5.0   # negative FCF → poor

    # ── P / B ─────────────────────────────────────────────────────────────────
    pb = fundamentals.get("pb_ratio")
    if pb and pb > 0:
        sub["pb_score"] = _inv_sigmoid(pb, k=0.25, midpoint=5.0)

    if not sub:
        return Score(value=50.0, sub_scores={}, explanation="Insufficient valuation data")

    composite   = _weighted(sub, _WEIGHTS)
    explanation = _explain(fundamentals, sub)
    return Score(value=round(composite, 1), sub_scores=sub, explanation=explanation)


def _inv_sigmoid(x: float, k: float, midpoint: float) -> float:
    """Inverse sigmoid: high x → low score (expensive). Low x → high score (cheap)."""
    return 100.0 / (1.0 + math.exp(k * (x - midpoint)))


def _weighted(sub: dict[str, float], weights: dict[str, float]) -> float:
    available = {k: v for k, v in sub.items() if k in weights}
    total_w   = sum(weights[k] for k in available)
    if total_w == 0:
        return 50.0
    raw = sum(available[k] * weights[k] for k in available) / total_w
    # Scale so that using a subset of metrics maps to full 0-100 range
    return raw


def _explain(f: dict, sub: dict) -> str:
    parts = []
    pe     = f.get("pe_ratio")
    growth = f.get("revenue_cagr_3yr")
    fcf    = f.get("fcf_trailing_cr")
    mkt    = f.get("market_cap_cr")
    pb     = f.get("pb_ratio")
    if pe and growth and growth > 1:
        parts.append(f"PEG: {pe/growth:.1f}")
    if mkt and fcf and fcf > 0:
        parts.append(f"P/FCF: {mkt/fcf:.1f}x")
    if pb:
        parts.append(f"P/B: {pb:.1f}x")
    return "; ".join(parts) if parts else "No valuation data"
