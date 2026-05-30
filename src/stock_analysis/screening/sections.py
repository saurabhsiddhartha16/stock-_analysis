"""
Defines the 5 email report sections with qualifying criteria and top-3 selection.

Section logic:
  1. Large Cap | Underrated  — mkt_cap >= 10,000 Cr, ROCE>=10%, RevCAGR5yr>=10%, below EMA200
  2. Finance | Underrated    — Financial sector stocks + same criteria above
  3. Mid Cap | Underrated    — mkt_cap 5,000-10,000 Cr, ROCE>=15%, RevCAGR5yr>=15%, below EMA50
  4. Tech | High Growth      — Nifty Digital constituent + 1yr rev growth >= 15%
  5. Momentum                — 1yr rev growth >= 20% AND 1yr stock price return >= 20%

No-repeat rule: stocks shown in a section are blocked for 7 days in THAT section only.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from stock_analysis.data.index_members import FINANCIAL_STOCKS, NIFTY_DIGITAL_SYMBOLS

_HISTORY_FILENAME = "section_history.json"


# ── Helper ─────────────────────────────────────────────────────────────────────

def _roce(f: dict) -> float | None:
    return f.get("roce_5yr_avg") or f.get("roce_10yr_avg") or f.get("roce")


# ── Filter functions (defined BEFORE SECTIONS list) ───────────────────────────

def _filter_large_cap_underrated(sym: str, f: dict, t: dict) -> bool:
    """Market cap >= 10,000 Cr | ROCE 5yr >= 10% | Rev CAGR 5yr >= 10% | below EMA50."""
    return (
        (f.get("market_cap_cr") or 0) >= 10_000
        and (_roce(f) or 0) >= 10
        and (f.get("revenue_cagr_5yr") or 0) >= 10
        and (t.get("price_vs_ema50_pct") is not None)
        and t["price_vs_ema50_pct"] < 0
    )


def _filter_finance_underrated(sym: str, f: dict, t: dict) -> bool:
    """Financial sector (any NSE financial index) | ROCE >= 10% | Rev CAGR 5yr >= 10% | below EMA200.
    No market cap floor — covers small/mid financial stocks too."""
    is_financial = (
        sym in FINANCIAL_STOCKS
        or (f.get("sector_yf") or "").lower() in ("financial services", "financialservices")
        or (f.get("industry_yf") or "").lower() in ("banks", "financial services")
    )
    return (
        is_financial
        and (_roce(f) or 0) >= 10
        and (f.get("revenue_cagr_5yr") or 0) >= 10
        and (t.get("price_vs_ema200_pct") is not None)
        and t["price_vs_ema200_pct"] < 0
    )


def _filter_midcap_underrated(sym: str, f: dict, t: dict) -> bool:
    """Market cap 1,000-10,000 Cr | ROCE 5yr >= 15% | Rev CAGR 5yr >= 15% | below EMA50."""
    mkt = f.get("market_cap_cr") or 0
    return (
        1_000 <= mkt < 10_000
        and (_roce(f) or 0) >= 15
        and (f.get("revenue_cagr_5yr") or 0) >= 15
        and (t.get("price_vs_ema50_pct") is not None)
        and t["price_vs_ema50_pct"] < 0
    )


def _filter_tech_high_growth(sym: str, f: dict, t: dict) -> bool:
    """Nifty India Digital constituent — no revenue threshold."""
    return sym in NIFTY_DIGITAL_SYMBOLS


def _filter_momentum(sym: str, f: dict, t: dict) -> bool:
    """1yr revenue growth >= 20% AND 1yr stock price return >= 20%."""
    rev_1yr   = f.get("revenue_yoy") or f.get("revenue_cagr_3yr") or 0
    price_1yr = t.get("return_1yr") or t.get("return_ytd") or 0
    return rev_1yr >= 20 and price_1yr >= 20


# ── Section definitions ────────────────────────────────────────────────────────

SECTIONS: list[dict] = [
    {
        "id":           "large_cap_underrated",
        "name":         "Large Cap | Underrated",
        "description":  "Large-cap stocks below 50-day EMA — quality at a short-term discount",
        "color_header": "#2c5282",
        "color_border": "#63b3ed",
        "filter":       _filter_large_cap_underrated,
        "criteria_note": "Mkt Cap >= 10,000 Cr | ROCE 5yr >= 10% | Rev CAGR 5yr >= 10% | Price < EMA50",
    },
    {
        "id":           "finance_underrated",
        "name":         "Finance | Underrated",
        "description":  "Financial stocks (BankNifty/FinNifty/Pvt-PSU Bank) below 200-day EMA",
        "color_header": "#276749",
        "color_border": "#68d391",
        "filter":       _filter_finance_underrated,
        "criteria_note": "Financial sector (any size) | ROCE 5yr >= 10% | Rev CAGR 5yr >= 10% | Price < EMA200",
    },
    {
        "id":           "midcap_underrated",
        "name":         "Mid Cap | Underrated",
        "description":  "Small & mid-cap stocks below 50-day EMA — high quality at a discount",
        "color_header": "#744210",
        "color_border": "#f6ad55",
        "filter":       _filter_midcap_underrated,
        "criteria_note": "Mkt Cap 1,000-10,000 Cr | ROCE 5yr >= 15% | Rev CAGR 5yr >= 15% | Price < EMA50",
    },
    {
        "id":           "tech_high_growth",
        "name":         "Tech Stocks | High Growth",
        "description":  "Nifty India Digital constituents — ranked by composite score",
        "color_header": "#553c9a",
        "color_border": "#b794f4",
        "filter":       _filter_tech_high_growth,
        "criteria_note": "Nifty India Digital Index constituents",
    },
    {
        "id":           "momentum",
        "name":         "Momentum",
        "description":  "High-growth stocks with strong price momentum",
        "color_header": "#9b2c2c",
        "color_border": "#fc8181",
        "filter":       _filter_momentum,
        "criteria_note": "1yr Revenue Growth >= 20% | 1yr Stock Price Return >= 20%",
    },
]


# ── Top-3 selection with no-repeat weekly filter ──────────────────────────────

def run_sections(
    symbols: list[str],
    stock_data: dict[str, dict],
    scores: list,
    cache_dir: Path,
    run_date: str,
    top_n: int = 3,
    no_repeat_days: int = 7,
) -> list[dict]:
    """
    For each section:
      1. Filter qualifying symbols using the section's criteria
      2. Remove symbols shown in last no_repeat_days (per section independently)
      3. Sort by composite score (descending)
      4. Take top_n (falls back to recently-shown if not enough fresh picks)

    Returns list of section dicts with 'stocks' key holding top StockScore objects.
    """
    score_map = {s.symbol: s for s in scores}
    history   = _load_history(cache_dir)
    cutoff    = (date.fromisoformat(run_date) - timedelta(days=no_repeat_days)).isoformat()

    results = []
    for sec in SECTIONS:
        sec_id    = sec["id"]
        filter_fn = sec["filter"]

        # Symbols recently shown in this section
        recent: set[str] = {
            sym
            for entry in history.get(sec_id, [])
            if entry.get("date", "") >= cutoff
            for sym in entry.get("symbols", [])
        }

        # Apply filter
        qualifying: list[str] = []
        for sym in symbols:
            d = stock_data.get(sym, {})
            try:
                if filter_fn(sym, d.get("fundamentals", {}), d.get("technicals", {})):
                    qualifying.append(sym)
            except Exception:
                pass

        # Sort qualifying by composite score
        def _score(s: str) -> float:
            return score_map[s].composite if s in score_map else 0.0

        fresh = sorted([s for s in qualifying if s not in recent], key=_score, reverse=True)
        shown = sorted([s for s in qualifying if s in recent],     key=_score, reverse=True)
        top   = (fresh + shown)[:top_n]

        # Update history
        if top:
            history.setdefault(sec_id, []).append({"date": run_date, "symbols": top})
            # Prune to last 30 days
            keep_from = (date.fromisoformat(run_date) - timedelta(days=30)).isoformat()
            history[sec_id] = [e for e in history[sec_id] if e.get("date", "") >= keep_from]

        logger.info(
            f"  Section '{sec['name']}': "
            f"{len(qualifying)} qualify, {len(fresh)} fresh, selected {len(top)}"
        )

        results.append({
            **{k: v for k, v in sec.items() if k != "filter"},
            "qualifying_count": len(qualifying),
            "stocks": [score_map[s] for s in top if s in score_map],
        })

    _save_history(cache_dir, history)
    return results


# ── History I/O ───────────────────────────────────────────────────────────────

def _load_history(cache_dir: Path) -> dict:
    path = cache_dir / _HISTORY_FILENAME
    if path.exists():
        try:
            with path.open() as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_history(cache_dir: Path, history: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / _HISTORY_FILENAME).write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )
