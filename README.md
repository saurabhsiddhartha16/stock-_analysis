# NSE Daily Stock Analysis Agent

A fully-automated daily stock analysis pipeline for NSE India. Every morning it fetches OHLCV data and fundamentals for the Nifty 50 universe, screens stocks against configurable rules, scores each stock across four dimensions, and delivers a ranked HTML report + CSV + email digest.

---

## How it works

```
NSE Universe (49 stocks)
        |
        v
  Data Ingestion          yfinance (OHLCV + basic fundamentals)
  (cached to disk)   +    Screener.in (ROE, ROCE, CAGRs, D/E, FCF)
        |
        v
   Screening              Applies rules from config/rules.yaml
   (~6 pass)              e.g. PE <= 60, ROE >= 12%, Rev CAGR >= 10%
        |
        v
  Numerical Scoring       Growth (35%) + Quality (30%)
  (0-100 per stock)       + Momentum (25%) - Risk (20%)
        |
        v
    Output                HTML report  →  data/reports/html/
                          CSV export   →  data/reports/csv/
                          Email digest →  your Gmail inbox
```

---

## Prerequisites

- **Python 3.12** (requires <3.14 due to pandas-ta/numba)
- A **Gmail account** with an [App Password](https://myaccount.google.com/apppasswords) generated

---

## Setup

### 1. Clone and create virtual environment

```powershell
cd "C:\Users\saura\Claude playground\Local repos\stock-_analysis"
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

### 2. Configure email credentials

Copy `.env.example` to `.env` and fill in your Gmail details:

```
EMAIL_USER=your.email@gmail.com
EMAIL_PASSWORD=yourgmailapppasword   # 16-char App Password, no spaces
```

> Get an App Password at: Google Account → Security → 2-Step Verification → App passwords

### 3. Review config files (optional)

| File | What it controls |
|---|---|
| `config/settings.yaml` | SMTP settings, data TTLs, output flags |
| `config/rules.yaml` | Screening rules (PE, ROE, CAGR thresholds, etc.) |
| `config/scoring_weights.yaml` | Score weights per dimension + sector overrides |
| `config/universe.yaml` | Stock universe source and filters |

---

## Running manually

```powershell
# Full pipeline (recommended)
python -m stock_analysis.main --mode full

# Re-run from scratch (ignores cached run state)
python -m stock_analysis.main --mode full --no-resume

# Stop after data ingestion (no scoring/email)
python -m stock_analysis.main --mode data-only

# Stop after screening + scoring (no email)
python -m stock_analysis.main --mode screen
```

Reports are saved to:
- `data/reports/html/YYYY-MM-DD.html` — open in any browser
- `data/reports/csv/YYYY-MM-DD.csv` — open in Excel

---

## Scheduling (Windows Task Scheduler)

Run once from the project root to register the daily job:

```powershell
.\scripts\setup_scheduler.ps1
```

This creates a task called `NSE-StockAnalysis-Daily` that runs every day at **8:00 AM**.

```powershell
# Verify it registered
Get-ScheduledTask -TaskName "NSE-StockAnalysis-Daily" | Select-Object TaskName, State

# Trigger a manual run immediately
Start-ScheduledTask -TaskName "NSE-StockAnalysis-Daily"

# Remove the task
.\scripts\setup_scheduler.ps1 -Uninstall
```

> The pipeline automatically skips NSE public holidays.

---

## Scoring methodology

All sub-scores are normalised to 0–100 using sigmoid scaling.

| Dimension | Weight | Key inputs |
|---|---|---|
| Growth | 35% | Revenue CAGR 3yr, PAT CAGR 3yr, EPS CAGR 3yr |
| Quality | 30% | ROE 5yr avg, ROCE vs WACC spread, FCF/PAT conversion |
| Momentum | 25% | RSI, price vs SMA50/200, % from 52-week high |
| Risk | -20% | Debt/Equity, interest coverage, beta, promoter pledge |

**Composite score** = Growth×0.35 + Quality×0.30 + Momentum×0.25 − Risk×0.20

Sector overrides in `config/scoring_weights.yaml` adjust weights automatically — e.g. BFSI stocks get a lower debt penalty, IT stocks get a higher cash weighting.

---

## Screening rules (defaults)

Rules are fully customisable in `config/rules.yaml`. Defaults:

| Rule | Threshold |
|---|---|
| Market cap | ≥ 500 Cr |
| PE ratio | ≤ 60 |
| ROE (5yr avg) | ≥ 12% |
| Revenue CAGR 3yr | ≥ 10% |
| PAT CAGR 3yr | ≥ 8% |
| Debt / Equity | ≤ 2.0 (relaxed to 10.0 for BFSI) |
| Free cash flow | Positive (trailing 12 months) |
| Price vs SMA200 | ≥ -5% |
| Avg daily volume | ≥ 50,000 shares |

---

## Project structure

```
stock-_analysis/
├── config/
│   ├── rules.yaml              # Screening rules (edit to customise)
│   ├── scoring_weights.yaml    # Score weights + sector overrides
│   ├── settings.yaml           # App settings, SMTP config
│   └── universe.yaml           # Stock universe definition
├── data/
│   ├── cache/                  # TTL-aware disk cache (OHLCV, fundamentals)
│   ├── reports/
│   │   ├── html/               # Generated HTML reports
│   │   └── csv/                # Generated CSV exports
│   └── universe/               # NSE symbol list
├── scripts/
│   ├── run_daily.py            # Task Scheduler entry point
│   └── setup_scheduler.ps1    # Registers the Windows scheduled task
├── src/stock_analysis/
│   ├── main.py                 # 5-stage resumable orchestrator
│   ├── config/loader.py        # Pydantic config models
│   ├── data/                   # OHLCV, fundamentals, technicals, cache
│   ├── scoring/                # Growth, quality, momentum, risk scorers
│   ├── screening/              # Rule parser + screening engine
│   ├── output/                 # HTML report, CSV export, email digest
│   ├── universe/               # NSE fetcher + filters
│   └── utils/                  # Logging, retry helpers
├── templates/
│   └── report.html.j2          # Jinja2 HTML report template
├── tests/
│   └── unit/                   # 60+ unit tests
├── .env                        # Your secrets (gitignored)
├── .env.example                # Template for .env
└── pyproject.toml
```

---

## Troubleshooting

**NSE API unreachable** — Normal. NSE blocks automated requests. The pipeline falls back to a hardcoded Nifty 50 list automatically.

**Email not sending** — Check that `EMAIL_USER` and `EMAIL_PASSWORD` are set in `.env` with no inline comments. Use a Gmail App Password (not your account password).

**0 stocks passing screening** — Your cached fundamentals data may be missing. Run with `--no-resume` to force a fresh data fetch.

**pandas-ta install fails** — You need Python 3.12. Python 3.13+ is not supported due to a numba dependency.

---

## Logs

Dated log files are written to `logs/stock_analysis_YYYY-MM-DD.log` after each run.

---

*Data sources: yfinance, Screener.in · Not investment advice.*
