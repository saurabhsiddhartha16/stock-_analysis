"""
Fetches market overview data for the email header:
  - Index prices + day change (SENSEX, Nifty 50, Bank Nifty, Midcap, Smallcap)
  - FII / DII net buy/sell data from NSE

Sources:
  Index data : Yahoo Finance via yfinance (free)
  FII/DII    : NSE India public API — nseindia.com/api/fiidiiTradeReact
"""
from __future__ import annotations

import time

import httpx
import yfinance as yf
from loguru import logger

from stock_analysis.data.index_members import INDEX_DISPLAY

_NSE_HEADERS_BROWSE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_NSE_HEADERS_API = {
    **_NSE_HEADERS_BROWSE,
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.nseindia.com/market-data/live-equity-market",
}


# ── Index prices ──────────────────────────────────────────────────────────────

def fetch_index_data() -> list[dict]:
    """
    Fetch latest close + day change for key NSE/BSE indices.
    Returns list of dicts: {name, price, change, change_pct, source}.
    Falls back gracefully — missing indices show None values.

    Source: Yahoo Finance via yfinance
    """
    results: list[dict] = []
    for key, (display_name, yf_ticker) in INDEX_DISPLAY.items():
        entry = {
            "name":       display_name,
            "price":      None,
            "change":     None,
            "change_pct": None,
            "source":     "Yahoo Finance (yfinance)",
        }
        try:
            hist = yf.download(
                yf_ticker, period="5d", interval="1d",
                auto_adjust=True, progress=False
            )
            if hist is not None and len(hist) >= 2:
                close = hist["Close"]
                # Handle yfinance MultiIndex columns
                if hasattr(close, "columns"):
                    close = close.iloc[:, 0]
                curr = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                chg  = curr - prev
                entry["price"]      = round(curr, 2)
                entry["change"]     = round(chg, 2)
                entry["change_pct"] = round((chg / prev) * 100, 2)
        except Exception as e:
            logger.debug(f"Index fetch failed for {display_name} ({yf_ticker}): {e}")
        results.append(entry)
    return results


# ── FII / DII data ────────────────────────────────────────────────────────────

def fetch_fii_dii() -> dict | None:
    """
    Fetch latest FII and DII net buy/sell data from NSE public API.
    Returns dict with keys: date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net
    All values in INR Crore.

    Source: NSE India — https://www.nseindia.com/api/fiidiiTradeReact
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            # Step 1: prime session
            client.get("https://www.nseindia.com", headers=_NSE_HEADERS_BROWSE)
            time.sleep(1.0)
            # Step 2: visit market page
            client.get(
                "https://www.nseindia.com/market-data/live-equity-market",
                headers=_NSE_HEADERS_BROWSE,
            )
            time.sleep(1.0)
            # Step 3: fetch FII/DII data
            resp = client.get(
                "https://www.nseindia.com/api/fiidiiTradeReact",
                headers=_NSE_HEADERS_API,
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return None

        # Take most recent day
        latest = data[0]
        return {
            "date":     latest.get("date", ""),
            "fii_buy":  _safe_float(latest.get("fiiBuyValue",  0)),
            "fii_sell": _safe_float(latest.get("fiiSellValue", 0)),
            "fii_net":  _safe_float(latest.get("fiiNetValue",  0)),
            "dii_buy":  _safe_float(latest.get("diiBuyValue",  0)),
            "dii_sell": _safe_float(latest.get("diiSellValue", 0)),
            "dii_net":  _safe_float(latest.get("diiNetValue",  0)),
            "source":   "NSE India (nseindia.com/api/fiidiiTradeReact)",
        }
    except Exception as e:
        logger.warning(f"FII/DII fetch failed (non-fatal): {e}")
        return None


def _safe_float(v) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0
