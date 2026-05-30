"""
NSE index constituent lists — used for section filtering.
Updated as of May 2026. Refresh quarterly when NSE rebalances.

Sources:
  BankNifty:  https://www.nseindia.com/products-services/indices-nifty-bank-index
  FinNifty:   https://www.nseindia.com/products-services/indices-nifty-financial-services-index
  Pvt Bank:   https://www.nseindia.com/products-services/indices-nifty-pvt-bank-index
  PSU Bank:   https://www.nseindia.com/products-services/indices-nifty-psu-bank-index
  FinEx-Bank: https://www.nseindia.com/products-services/indices-nifty-financial-services-ex-bank-index
  Digital:    https://www.nseindia.com/products-services/indices-nifty-india-digital-index
"""

# ── Banking indices ────────────────────────────────────────────────────────────

BANKNIFTY_SYMBOLS: set[str] = {
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
    "BANKBARODA", "INDUSINDBK", "PNB", "FEDERALBNK", "IDFCFIRSTB",
    "AUBANK", "BANDHANBNK",
}

NIFTY_PVT_BANK: set[str] = {
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK",
    "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "RBLBANK",
    "CSBBANK", "KTKBANK",
}

NIFTY_PSU_BANK: set[str] = {
    "SBIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK",
    "BANKINDIA", "MAHABANK", "UCOBANK", "IOB", "CENTRALBANK",
    "INDIANB", "PSB",
}

# ── Financial services indices ─────────────────────────────────────────────────

FINNIFTY_SYMBOLS: set[str] = {
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
    "BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "ICICIGI",
    "ICICIPRULI", "CHOLAFIN", "MUTHOOTFIN", "SHRIRAMFIN", "ABCAPITAL",
    "MANAPPURAM", "LICHSGFIN", "RECLTD", "PFC", "IDFCFIRSTB",
}

NIFTY_FIN_EX_BANK: set[str] = {
    "BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "ICICIGI",
    "ICICIPRULI", "CHOLAFIN", "MUTHOOTFIN", "SHRIRAMFIN", "ABCAPITAL",
    "MANAPPURAM", "LICHSGFIN", "RECLTD", "PFC", "POONAWALLA",
    "CANFINHOME", "IIFL", "STARHEALTH", "NIACL", "SBFC",
}

# Union of all financial index constituents
FINANCIAL_STOCKS: set[str] = (
    BANKNIFTY_SYMBOLS
    | FINNIFTY_SYMBOLS
    | NIFTY_PVT_BANK
    | NIFTY_PSU_BANK
    | NIFTY_FIN_EX_BANK
)

# ── Technology / Digital index ─────────────────────────────────────────────────

NIFTY_DIGITAL_SYMBOLS: set[str] = {
    # IT Services
    "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM",
    "COFORGE", "PERSISTENT", "MPHASIS", "KPITTECH", "LTTS",
    "TATAELXSI", "HAPPSTMNDS", "TANLA", "ROUTE",
    # Internet / Consumer Tech
    "ZOMATO", "FSN",        # Nykaa
    "POLICYBZR",            # PB Fintech
    "ONE97",                # Paytm
    "DELHIVERY",
    "MAPMYINDIA",           # CE Info Systems
    "INDIAMART",
    "NAUKRI",               # Info Edge
    "NAZARA",
    "RATEGAIN",
}

# ── Index metadata for display ─────────────────────────────────────────────────

INDEX_DISPLAY: dict[str, tuple[str, str]] = {
    # symbol: (display_name, yfinance_ticker)
    "SENSEX":      ("SENSEX",        "^BSESN"),
    "NIFTY 50":    ("Nifty 50",      "^NSEI"),
    "BANK NIFTY":  ("Bank Nifty",    "^NSEBANK"),
    "NIFTY MID":   ("Nifty Midcap",  "^NSMIDCP"),
    "NIFTY SMALL": ("Nifty Smallcap","^CNXSC"),
}
