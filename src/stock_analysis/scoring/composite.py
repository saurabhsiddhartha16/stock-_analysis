"""Composite scorer — combines five scores into a final ranked list."""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from stock_analysis.config.loader import ScoringWeightsConfig
from stock_analysis.scoring import (
    growth_score,
    momentum_score,
    quality_score,
    risk_score,
    valuation_score,
)


# ── Sector normalisation ──────────────────────────────────────────────────────
# Maps incoming sector strings (from nifty500.csv / yfinance) to the canonical
# keys used in scoring_weights.yaml sector_overrides.
_SECTOR_MAP: dict[str, str] = {
    # Information Technology
    "it": "Information Technology",
    "software": "Information Technology",
    "software & services": "Information Technology",
    "it services": "Information Technology",
    # Financial Services
    "bfsi": "Financial Services",
    "banking": "Financial Services",
    "banks": "Financial Services",
    "nbfc": "Financial Services",
    "insurance": "Financial Services",
    "non-banking financial company": "Financial Services",
    "financial services": "Financial Services",
    # Infrastructure / Construction
    "construction": "Infrastructure",
    "infrastructure": "Infrastructure",
    "engineering": "Infrastructure",
    # Metals & Mining
    "metals": "Metals & Mining",
    "mining": "Metals & Mining",
    "metals & mining": "Metals & Mining",
    # Healthcare / Pharma
    "pharma": "Healthcare",
    "pharmaceuticals": "Healthcare",
    "healthcare": "Healthcare",
    # FMCG / Consumer
    "fmcg": "Fast Moving Consumer Goods",
    "consumer staples": "Fast Moving Consumer Goods",
    "fast moving consumer goods": "Fast Moving Consumer Goods",
}


def _normalise_sector(sector: str) -> str:
    """Map raw sector string to canonical override key (case-insensitive)."""
    return _SECTOR_MAP.get(sector.lower().strip(), sector)


# ── Data completeness floor ───────────────────────────────────────────────────
_KEY_METRICS = [
    "pe_ratio", "pb_ratio", "roe_5yr_avg", "revenue_cagr_3yr",
    "pat_cagr_3yr", "debt_equity", "fcf_trailing_cr", "market_cap_cr",
]


def _completeness_multiplier(fundamentals: dict) -> float:
    """
    Downrank stocks where most fundamental data is missing.
    ≥75% present → 1.0 (no change)
    50-75% present → 0.90 (−10%)
    <50% present   → 0.75 (−25%)
    """
    available = sum(1 for k in _KEY_METRICS if fundamentals.get(k) is not None)
    ratio = available / len(_KEY_METRICS)
    if ratio >= 0.75:
        return 1.0
    if ratio >= 0.50:
        return 0.90
    return 0.75


@dataclass
class StockScore:
    symbol: str
    composite: float
    growth: float    = 0.0
    momentum: float  = 0.0
    quality: float   = 0.0
    valuation: float = 0.0
    risk: float      = 0.0      # higher = riskier
    sub_scores: dict[str, dict]  = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    rank: int = 0


def score_all(
    symbols: list[str],
    stock_data: dict[str, dict],
    weights_cfg: ScoringWeightsConfig,
    nifty_return_3m: float | None = None,
    ai_signals: dict[str, dict] | None = None,
) -> list[StockScore]:
    scored: list[StockScore] = []

    for symbol in symbols:
        data         = stock_data.get(symbol, {})
        fundamentals = data.get("fundamentals", {})
        technicals   = data.get("technicals", {})
        ai           = (ai_signals or {}).get(symbol, {})

        raw_sector = (
            data.get("universe", {}).get("sector", "")
            or fundamentals.get("sector_yf", "")
            or ""
        )
        sector  = _normalise_sector(raw_sector)
        weights = _resolve_weights(weights_cfg, sector)

        try:
            g = growth_score.compute(fundamentals, ai)
            m = momentum_score.compute(technicals, nifty_return_3m)
            q = quality_score.compute(fundamentals)
            v = valuation_score.compute(fundamentals, technicals)
            r = risk_score.compute(fundamentals, ai)

            completeness = _completeness_multiplier(fundamentals)
            composite = (
                weights["growth_score"]    * g.value
                + weights["quality_score"]    * q.value
                + weights["valuation_score"]  * v.value
                + weights["momentum_score"]   * m.value
                + weights["risk_score"]       * r.value   # negative weight
            ) * completeness
            composite = max(0.0, min(100.0, composite))

            scored.append(StockScore(
                symbol    = symbol,
                composite = round(composite, 2),
                growth    = g.value,
                momentum  = m.value,
                quality   = q.value,
                valuation = v.value,
                risk      = r.value,
                sub_scores = {
                    "growth":    g.sub_scores,
                    "momentum":  m.sub_scores,
                    "quality":   q.sub_scores,
                    "valuation": v.sub_scores,
                    "risk":      r.sub_scores,
                },
                explanations = {
                    "growth":    g.explanation,
                    "momentum":  m.explanation,
                    "quality":   q.explanation,
                    "valuation": v.explanation,
                    "risk":      r.explanation,
                },
            ))
        except Exception as e:
            logger.warning(f"Scoring failed for {symbol}: {e}")
            scored.append(StockScore(symbol=symbol, composite=0.0))

    scored.sort(key=lambda s: s.composite, reverse=True)
    for rank, s in enumerate(scored, start=1):
        s.rank = rank

    if scored:
        logger.info(
            f"Scoring complete: {len(scored)} stocks. "
            f"Top: {scored[0].symbol} ({scored[0].composite:.1f}) "
            f"| Bottom: {scored[-1].symbol} ({scored[-1].composite:.1f})"
        )
    return scored


def _resolve_weights(cfg: ScoringWeightsConfig, sector: str) -> dict[str, float]:
    base     = cfg.default_weights.model_dump()
    if not sector:
        return base
    overrides = cfg.sector_overrides.get(sector, {})
    # Only override top-level weight keys
    weight_keys = set(base.keys())
    return {**base, **{k: v for k, v in overrides.items() if k in weight_keys}}
