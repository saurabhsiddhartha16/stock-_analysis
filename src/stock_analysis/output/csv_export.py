"""Exports the ranked stock list to a dated CSV file."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from loguru import logger

from stock_analysis.scoring.composite import StockScore


def export(
    scores: list[StockScore],
    stock_data: dict[str, dict],
    reports_dir: Path,
    run_date: str | None = None,
) -> Path:
    """
    Write a CSV with all scored stocks, their scores, and key fundamentals/technicals.

    Args:
        scores:      Ranked list from composite.score_all().
        stock_data:  Full data dict {symbol: {fundamentals, technicals, universe}}.
        reports_dir: Root reports directory (will create csv/ subdirectory).
        run_date:    Date string for filename (defaults to today).

    Returns:
        Path to the written CSV file.
    """
    run_date = run_date or date.today().isoformat()
    out_dir = reports_dir / "csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_date}.csv"

    rows = []
    for s in scores:
        f = stock_data.get(s.symbol, {}).get("fundamentals", {})
        t = stock_data.get(s.symbol, {}).get("technicals", {})
        u = stock_data.get(s.symbol, {}).get("universe", {})

        rows.append({
            # Identity
            "rank": s.rank,
            "symbol": s.symbol,
            "company_name": f.get("company_name", s.symbol),
            "sector": u.get("sector", "") or f.get("sector_yf", ""),
            "industry": u.get("industry", "") or f.get("industry_yf", ""),
            # Composite scores
            "composite_score": s.composite,
            "growth_score": s.growth,
            "momentum_score": s.momentum,
            "quality_score": s.quality,
            "risk_score": s.risk,
            # Fundamentals
            "market_cap_cr": f.get("market_cap_cr"),
            "pe_ratio": f.get("pe_ratio"),
            "pb_ratio": f.get("pb_ratio"),
            "roe_5yr_avg": f.get("roe_5yr_avg"),
            "roe_ttm": f.get("roe_ttm"),
            "roce": f.get("roce"),
            "revenue_cagr_3yr_pct": f.get("revenue_cagr_3yr"),
            "pat_cagr_3yr_pct": f.get("pat_cagr_3yr"),
            "eps_cagr_3yr_pct": f.get("eps_cagr_3yr"),
            "debt_equity": f.get("debt_equity"),
            "interest_coverage": f.get("interest_coverage"),
            "fcf_trailing_cr": f.get("fcf_trailing_cr"),
            "beta": f.get("beta"),
            "dividend_yield_pct": f.get("dividend_yield"),
            "promoter_pledge_pct": f.get("promoter_pledge_pct"),
            # Technicals
            "close_price": t.get("close"),
            "rsi_14": t.get("RSI_14"),
            "price_vs_sma50_pct": t.get("price_vs_sma50_pct"),
            "price_vs_sma200_pct": t.get("price_vs_sma200_pct"),
            "pct_from_52w_high": t.get("pct_from_52w_high"),
            "volume_sma_20": t.get("volume_sma_20"),
            # Score explanations
            "growth_explanation": s.explanations.get("growth", ""),
            "quality_explanation": s.explanations.get("quality", ""),
            "momentum_explanation": s.explanations.get("momentum", ""),
            "risk_explanation": s.explanations.get("risk", ""),
        })

    df = pd.DataFrame(rows)
    df = df.round(2)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")  # utf-8-sig for Excel compatibility
    logger.info(f"CSV exported: {len(df)} stocks → {out_path}")
    return out_path
