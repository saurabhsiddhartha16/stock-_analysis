"""Fetches the NSE stock universe from NSE's official APIs with browser-like session priming."""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import pandas as pd
from loguru import logger

from stock_analysis.config.loader import UniverseConfig

# NSE requires these headers + a valid session cookie from the homepage visit
_HEADERS_BROWSE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_HEADERS_API = {
    **_HEADERS_BROWSE,
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.nseindia.com/market-data/live-equity-market",
}


# ── Nifty 50 hardcoded fallback (always available, no internet needed) ─────────
_NIFTY50_SYMBOLS = [
    ("ADANIENT", "Adani Enterprises", "Conglomerate", "Diversified"),
    ("ADANIPORTS", "Adani Ports", "Services", "Port & Logistics"),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare", "Hospital"),
    ("ASIANPAINT", "Asian Paints", "Consumer", "Paints"),
    ("AXISBANK", "Axis Bank", "BFSI", "Private Bank"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Auto", "2/3 Wheelers"),
    ("BAJAJFINSV", "Bajaj Finserv", "BFSI", "Financial Services"),
    ("BAJFINANCE", "Bajaj Finance", "BFSI", "NBFC"),
    ("BHARTIARTL", "Bharti Airtel", "Telecom", "Telecom"),
    ("BPCL", "BPCL", "Energy", "Oil & Gas"),
    ("BRITANNIA", "Britannia", "Consumer", "FMCG"),
    ("CIPLA", "Cipla", "Healthcare", "Pharma"),
    ("COALINDIA", "Coal India", "Energy", "Mining"),
    ("DIVISLAB", "Divi's Lab", "Healthcare", "Pharma"),
    ("DRREDDY", "Dr. Reddy's", "Healthcare", "Pharma"),
    ("EICHERMOT", "Eicher Motors", "Auto", "2/3 Wheelers"),
    ("GRASIM", "Grasim Industries", "Conglomerate", "Diversified"),
    ("HCLTECH", "HCL Technologies", "IT", "IT Services"),
    ("HDFCBANK", "HDFC Bank", "BFSI", "Private Bank"),
    ("HDFCLIFE", "HDFC Life", "BFSI", "Insurance"),
    ("HEROMOTOCO", "Hero MotoCorp", "Auto", "2/3 Wheelers"),
    ("HINDALCO", "Hindalco", "Metals", "Aluminium"),
    ("HINDUNILVR", "Hindustan Unilever", "Consumer", "FMCG"),
    ("ICICIBANK", "ICICI Bank", "BFSI", "Private Bank"),
    ("INDUSINDBK", "IndusInd Bank", "BFSI", "Private Bank"),
    ("INFY", "Infosys", "IT", "IT Services"),
    ("ITC", "ITC", "Consumer", "Conglomerate"),
    ("JSWSTEEL", "JSW Steel", "Metals", "Steel"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "BFSI", "Private Bank"),
    ("LT", "L&T", "Infrastructure", "Engineering"),
    ("M&M", "Mahindra & Mahindra", "Auto", "4 Wheelers"),
    ("MARUTI", "Maruti Suzuki", "Auto", "4 Wheelers"),
    ("NESTLEIND", "Nestle India", "Consumer", "FMCG"),
    ("NTPC", "NTPC", "Energy", "Power"),
    ("ONGC", "ONGC", "Energy", "Oil & Gas"),
    ("POWERGRID", "Power Grid", "Energy", "Power"),
    ("RELIANCE", "Reliance Industries", "Conglomerate", "Diversified"),
    ("SBILIFE", "SBI Life", "BFSI", "Insurance"),
    ("SBIN", "State Bank of India", "BFSI", "PSU Bank"),
    ("SUNPHARMA", "Sun Pharma", "Healthcare", "Pharma"),
    ("TATACONSUM", "Tata Consumer", "Consumer", "FMCG"),
    ("TATAMOTORS", "Tata Motors", "Auto", "4 Wheelers"),
    ("TATASTEEL", "Tata Steel", "Metals", "Steel"),
    ("TCS", "Tata Consultancy Services", "IT", "IT Services"),
    ("TECHM", "Tech Mahindra", "IT", "IT Services"),
    ("TITAN", "Titan Company", "Consumer", "Watches/Jewellery"),
    ("ULTRACEMCO", "UltraTech Cement", "Construction", "Cement"),
    ("UPL", "UPL", "Chemicals", "Agrochemicals"),
    ("WIPRO", "Wipro", "IT", "IT Services"),
]


def fetch_universe(cfg: UniverseConfig, universe_dir: Path) -> pd.DataFrame:
    """
    Download the stock universe from NSE and save to universe_dir/nse_all_symbols.csv.
    Falls back to hardcoded Nifty 50 if NSE API is unreachable.
    """
    universe_dir.mkdir(parents=True, exist_ok=True)
    out_path = universe_dir / "nse_all_symbols.csv"

    df = None

    # Try NSE API with proper session priming
    if cfg.limit_to_index:
        index_url = cfg.index_shortcuts.model_dump().get(cfg.limit_to_index)
        if index_url:
            logger.info(f"Fetching universe from NSE index: {cfg.limit_to_index}")
            df = _try_nse_api(index_url)

    if df is None or df.empty:
        logger.warning("NSE API unreachable — using hardcoded Nifty 50 fallback")
        df = _nifty50_fallback()

    df = _normalise_columns(df)
    df.to_csv(out_path, index=False)
    logger.info(f"Universe saved: {len(df)} stocks → {out_path}")
    return df


def _try_nse_api(index_url: str) -> pd.DataFrame | None:
    """Attempt to fetch from NSE API with browser session priming. Returns None on failure."""
    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            # Step 1: prime session by visiting homepage (sets required cookies)
            client.get("https://www.nseindia.com", headers=_HEADERS_BROWSE)
            time.sleep(1.0)
            # Step 2: visit market data page (NSE checks referrer chain)
            client.get(
                "https://www.nseindia.com/market-data/live-equity-market",
                headers=_HEADERS_BROWSE,
            )
            time.sleep(1.0)
            # Step 3: hit the actual API
            resp = client.get(index_url, headers=_HEADERS_API)
            resp.raise_for_status()
            records = resp.json().get("data", [])
            if not records:
                return None
            rows = []
            for r in records:
                meta = r.get("meta", {})
                sym = r.get("symbol", "").strip().upper()
                if sym:
                    rows.append({
                        "symbol": sym,
                        "name": meta.get("companyName", sym),
                        "sector": meta.get("sector", ""),
                        "industry": meta.get("industry", ""),
                    })
            return pd.DataFrame(rows) if rows else None
    except Exception as e:
        logger.debug(f"NSE API attempt failed: {e}")
        return None


def _nifty50_fallback() -> pd.DataFrame:
    return pd.DataFrame(
        _NIFTY50_SYMBOLS,
        columns=["symbol", "name", "sector", "industry"],
    )


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "SYMBOL": "symbol",
        "NAME OF COMPANY": "name",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for col in ("symbol", "name", "sector", "industry"):
        if col not in df.columns:
            df[col] = ""
    df["symbol"] = df["symbol"].str.strip().str.upper()
    df = df[df["symbol"] != ""].drop_duplicates(subset="symbol").reset_index(drop=True)
    return df[["symbol", "name", "sector", "industry"]]


def load_cached_universe(universe_dir: Path) -> pd.DataFrame:
    """Load the previously saved universe CSV without hitting NSE."""
    path = universe_dir / "nse_all_symbols.csv"
    if not path.exists():
        logger.warning("No cached universe found — generating Nifty 50 fallback")
        df = _normalise_columns(_nifty50_fallback())
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return df
    return pd.read_csv(path, dtype=str).fillna("")
