"""
Fundamental data fetcher — two layers:
  Layer 1 (fast, 24h TTL):  yfinance Ticker.info + financials
  Layer 2 (deep, 7d TTL):   Screener.in HTML scraper
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from loguru import logger

from stock_analysis.data.cache import DiskCache

_SCREENER_BASE = "https://www.screener.in/company/{symbol}/"
_SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
}
_SCREENER_DELAY = 1.5   # seconds between requests to avoid rate-limiting


def fetch_fundamentals(
    symbols: list[str],
    cache: DiskCache,
    yf_ttl_hours: float = 24,
    screener_ttl_hours: float = 168,
) -> dict[str, dict]:
    """
    Fetch fundamentals for all symbols. Returns {symbol: metrics_dict}.
    Merges yfinance (fast) and Screener.in (deep) data.
    """
    results: dict[str, dict] = {}
    for symbol in symbols:
        try:
            data = _get_symbol_fundamentals(symbol, cache, yf_ttl_hours, screener_ttl_hours)
            results[symbol] = data
        except Exception as e:
            logger.warning(f"Fundamentals failed for {symbol}: {e}")
            results[symbol] = _empty_fundamentals()
    return results


def _get_symbol_fundamentals(
    symbol: str,
    cache: DiskCache,
    yf_ttl: float,
    screener_ttl: float,
) -> dict:
    cached = cache.get_json("fundamentals", symbol)
    if cached is not None:
        return cached

    yf_data = _fetch_yfinance(symbol)
    screener_data = _fetch_screener(symbol, cache, screener_ttl)

    merged = {**_empty_fundamentals(), **yf_data, **screener_data}

    # Compute ROA time-series from PAT / Total Assets each year
    pat_series    = merged.get("pat_annual_series", [])
    assets_series = merged.get("total_assets_series", [])
    roa_series: list[float] = []
    for pat, assets in zip(pat_series, assets_series):
        if pat is not None and assets and assets > 0:
            roa_series.append(round(pat / assets * 100, 2))
    if roa_series:
        merged["roa"]         = roa_series[0]
        merged["roa_5yr_avg"] = round(sum(roa_series[:5]) / len(roa_series[:5]), 2) if len(roa_series) >= 5 else round(sum(roa_series) / len(roa_series), 2)
        merged["roa_10yr_avg"]= round(sum(roa_series[:10]) / len(roa_series[:10]), 2) if len(roa_series) >= 10 else round(sum(roa_series) / len(roa_series), 2)

    cache.set_json("fundamentals", symbol, merged, yf_ttl)
    return merged


# ── yfinance layer ─────────────────────────────────────────────────────────────

def _fetch_yfinance(symbol: str) -> dict:
    ticker_sym = f"{symbol}.NS"
    try:
        t = yf.Ticker(ticker_sym)
        info = t.info or {}
        fins = t.financials  # annual income statement

        market_cap = info.get("marketCap", 0)
        market_cap_cr = round(market_cap / 1e7, 2) if market_cap else None  # convert to crore

        # Revenue from financials DataFrame (rows are metrics, cols are dates)
        rev_series = _extract_series(fins, "Total Revenue")
        pat_series = _extract_series(fins, "Net Income")
        eps_series = _extract_eps(t)

        # Quarterly income statement for QoQ/YoY margins
        q_data = _fetch_quarterly(t)

        return {
            "market_cap_cr": market_cap_cr,
            "pe_ratio": _safe(info.get("trailingPE")),
            "pb_ratio": _safe(info.get("priceToBook")),
            "eps_ttm": _safe(info.get("trailingEps")),
            "dividend_yield": _safe(info.get("dividendYield")),
            "beta": _safe(info.get("beta")),
            "revenue_cagr_3yr": _cagr(rev_series, 3),
            "pat_cagr_3yr": _cagr(pat_series, 3),
            "eps_cagr_3yr": _cagr(eps_series, 3),
            "revenue_ttm_cr": _to_crore(rev_series[0] if rev_series else None),
            "pat_ttm_cr": _to_crore(pat_series[0] if pat_series else None),
            "sector_yf": info.get("sector", ""),
            "industry_yf": info.get("industry", ""),
            "company_name": info.get("longName", symbol),
            **q_data,
        }
    except Exception as e:
        logger.debug(f"yfinance fetch failed for {symbol}: {e}")
        return {}


def _fetch_quarterly(t: yf.Ticker) -> dict:
    """
    Fetch quarterly income statement for QoQ/YoY revenue and margin comparison.
    Returns flat dict with keys: rev_q1_cr, rev_q2_cr, rev_qoq_pct, rev_yoy_pct,
                                  opm_q1, opm_q2, opm_qoq_pts,
                                  npm_q1, npm_q2, npm_qoq_pts,
                                  q1_label, q2_label
    Source: Yahoo Finance quarterly_financials
    """
    try:
        qf = t.quarterly_financials
        if qf is None or qf.empty or qf.shape[1] < 2:
            return {}

        # Columns are quarters newest → oldest
        cols = qf.columns.tolist()
        q1_col, q2_col = cols[0], cols[1]

        def _row(name: str) -> list[float]:
            matches = [r for r in qf.index if name.lower() in str(r).lower()]
            if not matches:
                return []
            row = qf.loc[matches[0]]
            return [_safe(row.get(c)) for c in cols]

        rev_row = _row("Total Revenue")
        oi_row  = _row("Operating Income")  # Operating Profit
        ni_row  = _row("Net Income")

        result: dict = {}

        # Quarter labels (e.g. "Q3 FY26")
        try:
            result["q1_label"] = _quarter_label(q1_col)
            result["q2_label"] = _quarter_label(q2_col)
        except Exception:
            pass

        # Revenue QoQ and YoY
        if len(rev_row) >= 2 and rev_row[0] and rev_row[1]:
            r1, r2 = rev_row[0], rev_row[1]
            result["rev_q1_cr"]   = _to_crore(r1)
            result["rev_q2_cr"]   = _to_crore(r2)
            result["rev_qoq_pct"] = round((r1 / r2 - 1) * 100, 1) if r2 else None
        # YoY: compare q1 with q5 (same quarter last year = 4 quarters back)
        if len(rev_row) >= 5 and rev_row[0] and rev_row[4]:
            result["rev_yoy_pct"] = round((rev_row[0] / rev_row[4] - 1) * 100, 1)

        # Operating Profit Margin (OPM)
        if oi_row and rev_row and oi_row[0] is not None and rev_row[0]:
            opm1 = round(oi_row[0] / rev_row[0] * 100, 1)
            result["opm_q1"] = opm1
            if len(oi_row) >= 2 and oi_row[1] is not None and rev_row[1]:
                opm2 = round(oi_row[1] / rev_row[1] * 100, 1)
                result["opm_q2"]      = opm2
                result["opm_qoq_pts"] = round(opm1 - opm2, 1)

        # Net Profit Margin (NPM)
        if ni_row and rev_row and ni_row[0] is not None and rev_row[0]:
            npm1 = round(ni_row[0] / rev_row[0] * 100, 1)
            result["npm_q1"] = npm1
            if len(ni_row) >= 2 and ni_row[1] is not None and rev_row[1]:
                npm2 = round(ni_row[1] / rev_row[1] * 100, 1)
                result["npm_q2"]      = npm2
                result["npm_qoq_pts"] = round(npm1 - npm2, 1)
            # NPM TTM (trailing)
            result["npm_ttm"] = round(ni_row[0] / rev_row[0] * 100, 1)

        return result
    except Exception as e:
        logger.debug(f"Quarterly fetch failed: {e}")
        return {}


def _quarter_label(ts) -> str:
    """Convert a pandas Timestamp column to 'Q3 FY26' style label."""
    import pandas as pd
    if isinstance(ts, pd.Timestamp):
        m, y = ts.month, ts.year
        fy = y + 1 if m >= 4 else y   # Indian FY: April–March
        q  = ((m - 4) % 12) // 3 + 1
        return f"Q{q} FY{str(fy)[-2:]}"
    return str(ts)[:10]


def _extract_series(fins: pd.DataFrame | None, row_name: str) -> list[float]:
    """Return list of annual values [latest, ..., oldest] from financials DataFrame."""
    if fins is None or fins.empty:
        return []
    matches = [r for r in fins.index if row_name.lower() in str(r).lower()]
    if not matches:
        return []
    row = fins.loc[matches[0]].dropna().sort_index(ascending=False)
    return [float(v) for v in row.values if pd.notna(v)]


def _extract_eps(t: yf.Ticker) -> list[float]:
    try:
        fins = t.financials
        shares = t.info.get("sharesOutstanding", 0)
        if fins is None or fins.empty or not shares:
            return []
        pat_series = _extract_series(fins, "Net Income")
        return [v / shares for v in pat_series]
    except Exception:
        return []


def _cagr(values: list[float], years: int) -> float | None:
    """Compute CAGR over `years` from a [latest→oldest] list of annual values."""
    if len(values) <= years:
        return None
    end, start = values[0], values[years]
    if start <= 0 or end <= 0:
        return None
    return round((math.pow(end / start, 1 / years) - 1) * 100, 2)


def _to_crore(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 1e7, 2)


def _safe(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Screener.in layer ──────────────────────────────────────────────────────────

def _fetch_screener(symbol: str, cache: DiskCache, ttl_hours: float) -> dict:
    cached = cache.get_json("screener", symbol)
    if cached is not None:
        return cached

    url = _SCREENER_BASE.format(symbol=symbol)
    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            resp = client.get(url, headers=_SCREENER_HEADERS)
            if resp.status_code == 404:
                logger.debug(f"Screener: 404 for {symbol}")
                return {}
            resp.raise_for_status()
        time.sleep(_SCREENER_DELAY)
        data = _parse_screener_html(resp.text, symbol)
        cache.set_json("screener", symbol, data, ttl_hours)
        return data
    except Exception as e:
        logger.debug(f"Screener fetch failed for {symbol}: {e}")
        return {}


def _parse_screener_html(html: str, symbol: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    result: dict = {}

    # ── Key ratios (top summary bar) ─────────────────────────────────────────
    # Screener renders key metrics in <li> items inside #top-ratios
    top_ratios = soup.select("#top-ratios li")
    for li in top_ratios:
        name_el = li.select_one(".name")
        val_el = li.select_one(".number, .value")
        if not name_el or not val_el:
            continue
        name = name_el.get_text(strip=True).lower()
        val_text = val_el.get_text(strip=True)
        val = _parse_number(val_text)
        if "market cap" in name:
            result["market_cap_cr"] = val
        elif "pe" in name or "p/e" in name:
            result["pe_ratio"] = val
        elif "pb" in name or "p/b" in name:
            result["pb_ratio"] = val
        elif "div yield" in name:
            result["dividend_yield"] = val
        elif "roce" in name:
            result["roce"] = val
        elif "roe" in name:
            result["roe_ttm"] = val
        elif "face value" in name:
            result["face_value"] = val
        elif "book value" in name:
            result["book_value_per_share"] = val
        elif "debt" in name and "equity" in name:
            result["debt_equity"] = val

    # ── Ratio tables (10-year data) ───────────────────────────────────────────
    result.update(_parse_ratio_table(soup))

    # ── Profit & Loss table ───────────────────────────────────────────────────
    result.update(_parse_pl_table(soup))

    # ── Balance sheet ─────────────────────────────────────────────────────────
    result.update(_parse_balance_sheet(soup))

    # ── Cash flow ─────────────────────────────────────────────────────────────
    result.update(_parse_cash_flow(soup))

    return result


def _parse_ratio_table(soup: BeautifulSoup) -> dict:
    """Parse the Ratios section for ROE, ROCE history."""
    result: dict = {}
    section = soup.find("section", {"id": "ratios"})
    if not section:
        return result

    table = section.find("table")
    if not table:
        return result

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        label = cells[0].get_text(strip=True).lower()
        values = [_parse_number(c.get_text(strip=True)) for c in cells[1:]]
        values = [v for v in values if v is not None]
        if not values:
            continue
        if "roe" in label:
            result["roe_ttm"] = values[0]
            result["roe_5yr_avg"] = round(sum(values[:5]) / len(values[:5]), 2) if len(values) >= 5 else values[0]
            result["roe_annual_series"] = values  # full series for consistency scoring
        elif "roce" in label:
            result["roce"] = values[0]
            result["roce_5yr_avg"] = round(sum(values[:5]) / len(values[:5]), 2) if len(values) >= 5 else values[0]
            result["roce_10yr_avg"] = round(sum(values) / len(values), 2) if values else None
        elif "debt" in label and "equity" in label:
            result["debt_equity"] = values[0]
        elif "interest coverage" in label:
            result["interest_coverage"] = values[0]
        elif "promoter" in label and "pledg" in label:
            result["promoter_pledge_pct"] = values[0]

    return result


def _parse_pl_table(soup: BeautifulSoup) -> dict:
    """Parse Profit & Loss for revenue and PAT history → compute CAGRs."""
    result: dict = {}
    section = soup.find("section", {"id": "profit-loss"})
    if not section:
        return result

    table = section.find("table")
    if not table:
        return result

    rev_values: list[float] = []
    pat_values: list[float] = []

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        label = cells[0].get_text(strip=True).lower()
        values = [_parse_number(c.get_text(strip=True)) for c in cells[1:]]
        values = [v for v in values if v is not None]

        if ("sales" in label or "revenue" in label) and "growth" not in label and not rev_values:
            rev_values = values
        elif ("net profit" in label or "pat" in label) and "growth" not in label and not pat_values:
            pat_values = values

    # Screener shows oldest→latest, so reverse
    if rev_values:
        rev_rev = list(reversed(rev_values))
        result["revenue_cagr_3yr"]  = _cagr(rev_rev, 3)
        result["revenue_cagr_5yr"]  = _cagr(rev_rev, 5)
        result["revenue_cagr_10yr"] = _cagr(rev_rev, 10)
        if len(rev_rev) >= 2 and rev_rev[1] and rev_rev[1] != 0:
            result["revenue_yoy"] = round((rev_rev[0] / rev_rev[1] - 1) * 100, 2)
        result["revenue_ttm_cr"]        = rev_rev[0] if rev_rev else None
        result["revenue_annual_series"] = rev_rev
    if pat_values:
        pat_rev = list(reversed(pat_values))
        result["pat_cagr_3yr"]  = _cagr(pat_rev, 3)
        result["pat_cagr_5yr"]  = _cagr(pat_rev, 5)
        result["pat_cagr_10yr"] = _cagr(pat_rev, 10)
        if len(pat_rev) >= 2 and pat_rev[1] and pat_rev[1] != 0:
            result["pat_yoy"] = round((pat_rev[0] / pat_rev[1] - 1) * 100, 2)
        result["pat_ttm_cr"]       = pat_rev[0] if pat_rev else None
        result["pat_annual_series"] = pat_rev

    # Annual net profit margin (PAT / Revenue)
    if rev_values and pat_values:
        rr = list(reversed(rev_values))
        pr = list(reversed(pat_values))
        if rr[0] and rr[0] > 0:
            result["npm_ttm"] = round(pr[0] / rr[0] * 100, 2)

    return result


def _parse_balance_sheet(soup: BeautifulSoup) -> dict:
    result: dict = {}
    section = soup.find("section", {"id": "balance-sheet"})
    if not section:
        return result

    table = section.find("table")
    if not table:
        return result

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        label = cells[0].get_text(strip=True).lower()
        values = [_parse_number(c.get_text(strip=True)) for c in cells[1:]]
        values = [v for v in values if v is not None]
        if not values:
            continue
        if "borrowing" in label or "total debt" in label:
            result["total_debt_cr"] = list(reversed(values))[0]
        elif "reserves" in label:
            result["reserves_cr"] = list(reversed(values))[0]
        elif "equity capital" in label or "share capital" in label:
            result["equity_capital_cr"] = list(reversed(values))[0]
        elif "cash" in label and "equivalent" in label:
            result["cash_cr"] = list(reversed(values))[0]
        elif "total assets" in label:
            assets_series = list(reversed(values))
            result["total_assets_cr"]     = assets_series[0] if assets_series else None
            result["total_assets_series"] = assets_series

    return result


def _parse_cash_flow(soup: BeautifulSoup) -> dict:
    result: dict = {}
    section = soup.find("section", {"id": "cash-flow"})
    if not section:
        return result

    table = section.find("table")
    if not table:
        return result

    cfo_values: list[float] = []
    capex_values: list[float] = []

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        label = cells[0].get_text(strip=True).lower()
        values = [_parse_number(c.get_text(strip=True)) for c in cells[1:]]
        values = [v for v in values if v is not None]

        if "operating" in label and not cfo_values:
            cfo_values = list(reversed(values))
        elif "investing" in label or "capex" in label:
            capex_values = list(reversed(values))

    if cfo_values:
        result["cfo_trailing_cr"] = cfo_values[0]  # store CFO for earnings quality check

    if cfo_values and capex_values and len(cfo_values) == len(capex_values):
        # FCF = CFO + investing (investing is typically negative for capex)
        fcf_series = [c + i for c, i in zip(cfo_values, capex_values)]
        result["fcf_trailing_cr"] = fcf_series[0] if fcf_series else None
    elif cfo_values:
        result["fcf_trailing_cr"] = cfo_values[0]  # rough proxy when no capex data

    return result


def _parse_number(text: str) -> float | None:
    """Parse Screener number strings like '1,23,456.78' or '12.3%' or '2.5x'."""
    if not text or text in ("-", "—", ""):
        return None
    text = text.replace(",", "").replace("%", "").replace("x", "").strip()
    # Handle crore/lakh suffixes
    multiplier = 1
    if text.endswith("Cr"):
        text = text[:-2].strip()
        multiplier = 1
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _empty_fundamentals() -> dict:
    """Return a dict with all expected keys set to None."""
    return {
        "market_cap_cr": None,
        "pe_ratio": None,
        "pb_ratio": None,
        "eps_ttm": None,
        "dividend_yield": None,
        "beta": None,
        "revenue_cagr_3yr": None,
        "revenue_cagr_5yr": None,
        "pat_cagr_3yr": None,
        "pat_cagr_5yr": None,
        "eps_cagr_3yr": None,
        "revenue_ttm_cr": None,
        "pat_ttm_cr": None,
        "roe_ttm": None,
        "roe_5yr_avg": None,
        "roce": None,
        "debt_equity": None,
        "interest_coverage": None,
        "fcf_trailing_cr": None,
        "total_debt_cr": None,
        "cash_cr": None,
        "promoter_pledge_pct": None,
        "sector_yf": None,
        "industry_yf": None,
        "company_name": None,
        "roa": None,
        "roa_5yr_avg": None,
        "roa_10yr_avg": None,
        "total_assets_cr": None,
        "total_assets_series": None,
        "revenue_annual_series": None,
        "pat_annual_series": None,
        "roce_5yr_avg": None,
        "roce_10yr_avg": None,
        "cfo_trailing_cr": None,
        "roe_annual_series": None,
        # Extended growth fields
        "revenue_cagr_10yr": None,
        "revenue_yoy": None,
        "pat_cagr_10yr": None,
        "pat_yoy": None,
        "npm_ttm": None,
        # Quarterly financial comparison (from yfinance quarterly_financials)
        "q1_label": None,
        "q2_label": None,
        "rev_q1_cr": None,
        "rev_q2_cr": None,
        "rev_qoq_pct": None,
        "rev_yoy_pct": None,
        "opm_q1": None,
        "opm_q2": None,
        "opm_qoq_pts": None,
        "npm_q1": None,
        "npm_q2": None,
        "npm_qoq_pts": None,
    }
