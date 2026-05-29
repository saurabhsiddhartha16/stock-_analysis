"""Renders the HTML report using Jinja2."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger

from stock_analysis.scoring.composite import StockScore


def _fmt_num(val: Any, decimals: int = 1) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_cr(val: Any) -> str:
    """Format crore value with K suffix for large numbers."""
    if val is None:
        return "—"
    try:
        v = float(val)
        if v >= 100_000:
            return f"₹{v/100_000:.1f}L Cr"
        if v >= 1_000:
            return f"₹{v/1_000:.1f}K Cr"
        return f"₹{v:.0f} Cr"
    except (TypeError, ValueError):
        return "—"


def _build_stock_context(s: StockScore, stock_data: dict) -> dict:
    f = stock_data.get(s.symbol, {}).get("fundamentals", {})
    t = stock_data.get(s.symbol, {}).get("technicals", {})
    u = stock_data.get(s.symbol, {}).get("universe", {})
    return {
        "symbol": s.symbol,
        "company_name": f.get("company_name") or s.symbol,
        "sector": u.get("sector") or f.get("sector_yf") or "",
        "composite": s.composite,
        "growth": s.growth,
        "quality": s.quality,
        "momentum": s.momentum,
        "risk": s.risk,
        "market_cap_cr": f.get("market_cap_cr"),
        "pe_ratio": f.get("pe_ratio"),
        "roe_5yr": f.get("roe_5yr_avg"),
        "rev_cagr": f.get("revenue_cagr_3yr"),
        "pat_cagr": f.get("pat_cagr_3yr"),
        "debt_equity": f.get("debt_equity"),
        "rsi": t.get("RSI_14"),
        "vs_sma200": t.get("price_vs_sma200_pct"),
        "pct_52w": t.get("pct_from_52w_high"),
        "growth_expl": s.explanations.get("growth", ""),
        "quality_expl": s.explanations.get("quality", ""),
        "roce": f.get("roce"),
        "roa": f.get("roa"),
        "rev_cagr_5yr": f.get("revenue_cagr_5yr"),
    }


def render(
    scores: list[StockScore],
    stock_data: dict[str, dict],
    total_universe: int,
    reports_dir: Path,
    templates_dir: Path,
    run_date: str | None = None,
    card_limit: int = 20,
    screen_results: list[dict] | None = None,
) -> Path:
    """
    Render the HTML report and write to reports_dir/html/YYYY-MM-DD.html.
    Returns the path to the written file.
    """
    run_date = run_date or date.today().isoformat()
    out_dir = reports_dir / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_date}.html"

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["fmt_num"] = _fmt_num
    env.filters["fmt_pct"] = _fmt_pct
    env.filters["fmt_cr"] = _fmt_cr

    template = env.get_template("report.html.j2")
    stocks_ctx = [_build_stock_context(s, stock_data) for s in scores]

    html = template.render(
        run_date=run_date,
        total_universe=total_universe,
        passed_screen=len(scores),
        top_stock=scores[0].symbol if scores else "—",
        top_score=f"{scores[0].composite:.1f}" if scores else "—",
        stocks=stocks_ctx,
        card_limit=card_limit,
        screen_results=screen_results or [],
    )

    out_path.write_text(html, encoding="utf-8")
    logger.info(f"HTML report written: {out_path}")
    return out_path
