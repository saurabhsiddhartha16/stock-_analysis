"""Composite scorer — combines all four scores into a final ranked list."""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from stock_analysis.config.loader import ScoringWeightsConfig
from stock_analysis.scoring import growth_score, momentum_score, quality_score, risk_score


@dataclass
class StockScore:
    symbol: str
    composite: float                         # 0-100, final rank score
    growth: float = 0.0
    momentum: float = 0.0
    quality: float = 0.0
    risk: float = 0.0                        # 0-100, higher = riskier
    sub_scores: dict[str, dict] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    rank: int = 0


def score_all(
    symbols: list[str],
    stock_data: dict[str, dict],
    weights_cfg: ScoringWeightsConfig,
    nifty_return_3m: float | None = None,
    ai_signals: dict[str, dict] | None = None,
) -> list[StockScore]:
    """
    Score every symbol and return a ranked list (best composite first).

    Args:
        symbols:         Ordered list of symbols to score.
        stock_data:      {symbol: {fundamentals: {...}, technicals: {...}}}
        weights_cfg:     Loaded ScoringWeightsConfig.
        nifty_return_3m: Nifty 50 3-month return % for relative strength calc.
        ai_signals:      Optional {symbol: {analyst_revision_signal, auditor_qualification}}
    """
    scored: list[StockScore] = []

    for symbol in symbols:
        data = stock_data.get(symbol, {})
        fundamentals = data.get("fundamentals", {})
        technicals = data.get("technicals", {})
        ai = (ai_signals or {}).get(symbol, {})

        sector = (
            data.get("universe", {}).get("sector", "")
            or fundamentals.get("sector_yf", "")
            or ""
        )
        weights = _resolve_weights(weights_cfg, sector)

        try:
            g = growth_score.compute(fundamentals, ai)
            m = momentum_score.compute(technicals, nifty_return_3m)
            q = quality_score.compute(fundamentals)
            r = risk_score.compute(fundamentals, ai)

            composite = (
                weights["growth_score"] * g.value
                + weights["momentum_score"] * m.value
                + weights["quality_score"] * q.value
                + weights["risk_score"] * r.value  # negative weight
            )
            composite = max(0.0, min(100.0, composite))

            scored.append(StockScore(
                symbol=symbol,
                composite=round(composite, 2),
                growth=g.value,
                momentum=m.value,
                quality=q.value,
                risk=r.value,
                sub_scores={
                    "growth": g.sub_scores,
                    "momentum": m.sub_scores,
                    "quality": q.sub_scores,
                    "risk": r.sub_scores,
                },
                explanations={
                    "growth": g.explanation,
                    "momentum": m.explanation,
                    "quality": q.explanation,
                    "risk": r.explanation,
                },
            ))
        except Exception as e:
            logger.warning(f"Scoring failed for {symbol}: {e}")
            scored.append(StockScore(symbol=symbol, composite=0.0))

    scored.sort(key=lambda s: s.composite, reverse=True)
    for rank, s in enumerate(scored, start=1):
        s.rank = rank

    logger.info(
        f"Scoring complete: {len(scored)} stocks. "
        f"Top: {scored[0].symbol} ({scored[0].composite:.1f}) "
        f"| Bottom: {scored[-1].symbol} ({scored[-1].composite:.1f})"
        if scored else "No stocks scored."
    )
    return scored


def _resolve_weights(cfg: ScoringWeightsConfig, sector: str) -> dict[str, float]:
    """Merge default weights with any sector overrides."""
    base = cfg.default_weights.model_dump()  # {growth_score, momentum_score, quality_score, risk_score}
    if not sector:
        return base
    overrides = cfg.sector_overrides.get(sector, {})
    return {**base, **{k: v for k, v in overrides.items() if k in base}}
