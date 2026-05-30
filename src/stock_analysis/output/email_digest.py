"""Sends the daily email digest — comprehensive per-stock cards + qualitative insights."""
from __future__ import annotations

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from loguru import logger

from stock_analysis.config.loader import EmailConfig
from stock_analysis.scoring.composite import StockScore


# ── Public API ────────────────────────────────────────────────────────────────

def send(
    scores: list[StockScore],
    stock_data: dict[str, dict],
    csv_path: Path | None,
    email_cfg: EmailConfig,
    run_date: str,
    top_n: int = 15,
    screen_results: list[dict] | None = None,
    qualitative_data: dict[str, dict] | None = None,
) -> bool:
    smtp_user = os.environ.get(email_cfg.smtp_user_env_var, "")
    smtp_pass = os.environ.get(email_cfg.smtp_pass_env_var, "")
    if not smtp_user or not smtp_pass:
        logger.warning(
            "Email credentials not set — skipping. "
            f"Set {email_cfg.smtp_user_env_var} and {email_cfg.smtp_pass_env_var} in .env"
        )
        return False

    subject = email_cfg.subject_template.format(
        date=run_date,
        top_stocks=", ".join(s.symbol for s in scores[:3]),
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_cfg.from_address
    msg["To"]      = ", ".join(email_cfg.to_addresses)

    html_body = _build_html(
        scores[:top_n], stock_data, run_date,
        screen_results or [], qualitative_data or {}
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if csv_path and csv_path.exists():
        with csv_path.open("rb") as f:
            att = MIMEApplication(f.read(), Name=csv_path.name)
        att["Content-Disposition"] = f'attachment; filename="{csv_path.name}"'
        msg.attach(att)

    try:
        with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port) as srv:
            if email_cfg.smtp_use_tls:
                srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(email_cfg.from_address, email_cfg.to_addresses, msg.as_string())
        logger.info(f"Email sent to {email_cfg.to_addresses}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


# ── Master HTML builder ───────────────────────────────────────────────────────

def _build_html(
    scores: list[StockScore],
    stock_data: dict,
    run_date: str,
    screen_results: list[dict],
    qual: dict[str, dict],
) -> str:
    leaderboard  = _leaderboard(scores, stock_data)
    stock_cards  = "".join(_stock_card(i + 1, s, stock_data, qual) for i, s in enumerate(scores))
    screen_html  = _screens_section(screen_results)
    n_qual       = sum(1 for s in scores if s.symbol in qual)

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#edf2f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<div style="max-width:860px;margin:20px auto;background:white;border-radius:14px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.10)">

  {_header(run_date, len(scores), n_qual)}
  {leaderboard}
  {stock_cards}
  {screen_html}
  {_footer()}

</div>
</body></html>"""


# ── Header ────────────────────────────────────────────────────────────────────

def _header(run_date: str, n_stocks: int, n_qual: int) -> str:
    qual_note = f" &nbsp;·&nbsp; {n_qual} AI insights" if n_qual else ""
    return f"""
  <div style="background:linear-gradient(135deg,#1a202c 0%,#2d3748 100%);padding:24px 28px">
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td>
          <div style="color:white;font-size:20px;font-weight:700;letter-spacing:-0.3px">
            NSE Stock Analysis
          </div>
          <div style="color:#a0aec0;font-size:12px;margin-top:4px">
            {run_date} &nbsp;·&nbsp; Top {n_stocks} picks{qual_note}
          </div>
        </td>
        <td style="text-align:right;color:#4fd1c5;font-size:28px;font-weight:800;letter-spacing:-1px">
          NSE
        </td>
      </tr>
    </table>
  </div>"""


# ── Leaderboard table ─────────────────────────────────────────────────────────

def _leaderboard(scores: list[StockScore], stock_data: dict) -> str:
    rows = ""
    for i, s in enumerate(scores, 1):
        f      = stock_data.get(s.symbol, {}).get("fundamentals", {})
        u      = stock_data.get(s.symbol, {}).get("universe", {})
        t      = stock_data.get(s.symbol, {}).get("technicals", {})
        name   = (f.get("company_name") or s.symbol)[:28]
        sector = (u.get("sector") or f.get("sector_yf") or "")[:20]
        cmp    = t.get("close")
        pe     = f.get("pe_ratio")
        roe    = f.get("roe_5yr_avg")
        rev3   = f.get("revenue_cagr_3yr")

        medal = "#1" if i == 1 else "#2" if i == 2 else "#3" if i == 3 else f"#{i}"
        sc    = s.composite
        sc_bg = "#276749" if sc >= 55 else "#744210" if sc >= 40 else "#742a2a"

        def _f(v, fmt=":.1f", suffix=""):
            return f"{v{fmt}}{suffix}" if v is not None else "—"

        rows += f"""
      <tr style="border-bottom:1px solid #f0f2f5">
        <td style="padding:7px 12px;font-weight:700;font-size:11px;color:#718096">{medal}</td>
        <td style="padding:7px 12px">
          <div style="font-weight:700;font-size:12px;color:#1a202c">{s.symbol}</div>
          <div style="font-size:10px;color:#718096">{name}</div>
        </td>
        <td style="padding:7px 12px;font-size:10px;color:#4a90d9">{sector}</td>
        <td style="padding:7px 12px;text-align:right">
          <span style="background:{sc_bg};color:white;padding:2px 8px;border-radius:8px;font-size:12px;font-weight:700">{sc:.1f}</span>
        </td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{s.growth:.0f}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{s.quality:.0f}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{s.valuation:.0f}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{s.momentum:.0f}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px;color:#e53e3e">{s.risk:.0f}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{f"{cmp:,.0f}" if cmp else "—"}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{f"{pe:.1f}x" if pe else "—"}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{f"{roe:.1f}%" if roe else "—"}</td>
        <td style="padding:7px 12px;text-align:right;font-size:11px">{f"{rev3:.1f}%" if rev3 else "—"}</td>
      </tr>"""

    return f"""
  <div style="padding:20px 28px 4px">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#718096;margin-bottom:10px">
      Rankings
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f7fafc">
          <th style="padding:6px 12px;text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">#</th>
          <th style="padding:6px 12px;text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">Stock</th>
          <th style="padding:6px 12px;text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">Sector</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">Score</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#68d391">Growth</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#b794f4">Quality</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#63b3ed">Value</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#f6ad55">Mom.</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#fc8181">Risk</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">CMP</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">P/E</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">ROE</th>
          <th style="padding:6px 12px;text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#a0aec0">Rev 3yr</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>"""


# ── Per-stock detailed card ───────────────────────────────────────────────────

def _stock_card(rank: int, s: StockScore, stock_data: dict, qual: dict) -> str:
    f    = stock_data.get(s.symbol, {}).get("fundamentals", {})
    t    = stock_data.get(s.symbol, {}).get("technicals", {})
    u    = stock_data.get(s.symbol, {}).get("universe", {})
    q    = qual.get(s.symbol, {})

    name   = f.get("company_name") or s.symbol
    sector = u.get("sector") or f.get("sector_yf") or ""

    # Sentiment colours
    sentiment = q.get("overall_sentiment", "") if q else ""
    sent_bg, border = {
        "Positive": ("#276749", "#68d391"),
        "Negative": ("#742a2a", "#fc8181"),
    }.get(sentiment, ("#4a5568", "#cbd5e0"))

    return f"""
  <div style="margin:0;padding:16px 28px;border-top:2px solid #edf2f7">

    <!-- Card header -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
      <tr>
        <td>
          <span style="font-size:11px;color:#a0aec0;font-weight:600">#{rank}</span>
          <span style="font-size:16px;font-weight:800;color:#1a202c;margin-left:6px">{s.symbol}</span>
          <span style="font-size:12px;color:#718096;margin-left:6px">{name}</span>
        </td>
        <td style="text-align:right">
          {f'<span style="background:{sent_bg};color:white;padding:3px 10px;border-radius:10px;font-size:10px;font-weight:700">{sentiment}</span>' if sentiment else ""}
          <span style="background:#edf2f7;color:#4a5568;padding:3px 10px;border-radius:10px;font-size:10px;font-weight:700;margin-left:6px">
            Score {s.composite:.1f}
          </span>
        </td>
      </tr>
      <tr>
        <td colspan="2">
          <span style="font-size:10px;color:#718096">{sector}</span>
        </td>
      </tr>
    </table>

    <!-- Data grid: 3 columns -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:10px">
      <tr style="vertical-align:top">
        <!-- Col 1: Price -->
        <td style="width:33%;padding-right:12px">
          {_section_box("PRICE", _price_rows(f, t))}
        </td>
        <!-- Col 2: Ratios -->
        <td style="width:33%;padding-right:12px">
          {_section_box("KEY RATIOS", _ratios_rows(f))}
        </td>
        <!-- Col 3: Stock Performance -->
        <td style="width:34%">
          {_section_box("STOCK PERFORMANCE", _perf_rows(t))}
        </td>
      </tr>
    </table>

    <!-- Growth table: full width -->
    {_growth_section(f)}

    <!-- Qualitative insights -->
    {_qualitative_card(q, border) if q else ""}

  </div>"""


def _section_box(title: str, content: str) -> str:
    return f"""<div style="background:#f7fafc;border-radius:8px;padding:10px 12px">
  <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:6px">{title}</div>
  {content}
</div>"""


def _row(label: str, value: str, value_color: str = "#1a202c") -> str:
    return f"""<table style="width:100%;border-collapse:collapse;margin-bottom:3px">
  <tr>
    <td style="font-size:10px;color:#718096">{label}</td>
    <td style="font-size:11px;font-weight:600;color:{value_color};text-align:right">{value}</td>
  </tr>
</table>"""


def _signed_color(v: float | None) -> str:
    if v is None:
        return "#718096"
    return "#276749" if v >= 0 else "#c53030"


def _fmt_pct(v: float | None, plus: bool = True) -> str:
    if v is None:
        return "—"
    sign = "+" if plus and v > 0 else ""
    return f"{sign}{v:.1f}%"


def _fmt_vs(v: float | None) -> str:
    """Format price vs EMA as +X.X% with color label."""
    if v is None:
        return "—"
    sign  = "+" if v >= 0 else ""
    label = "above" if v >= 0 else "below"
    return f"{sign}{v:.1f}% {label}"


def _price_rows(f: dict, t: dict) -> str:
    cmp   = t.get("close")
    pe    = f.get("pe_ratio")
    e50   = t.get("price_vs_ema50_pct")
    e200  = t.get("price_vs_ema200_pct")
    return (
        _row("CMP", f"&#8377;{cmp:,.1f}" if cmp else "—")
        + _row("P/E Ratio", f"{pe:.1f}x" if pe else "—")
        + _row("vs EMA 50", _fmt_vs(e50), _signed_color(e50))
        + _row("vs EMA 200", _fmt_vs(e200), _signed_color(e200))
    )


def _ratios_rows(f: dict) -> str:
    roe  = f.get("roe_5yr_avg") or f.get("roe_ttm")
    roce = f.get("roce_5yr_avg") or f.get("roce")
    roa  = f.get("roa_5yr_avg") or f.get("roa")
    npm  = f.get("npm_ttm")
    return (
        _row("ROE (5yr avg)", f"{roe:.1f}%"  if roe  else "—")
        + _row("ROCE (5yr avg)", f"{roce:.1f}%" if roce else "—")
        + _row("ROA (5yr avg)", f"{roa:.1f}%"  if roa  else "—")
        + _row("Net Margin", f"{npm:.1f}%"  if npm  else "—")
    )


def _perf_rows(t: dict) -> str:
    ytd  = t.get("return_ytd")
    r3yr = t.get("return_3yr")
    r5yr = t.get("return_5yr")
    r10y = t.get("return_10yr")
    return (
        _row("YTD",  _fmt_pct(ytd),  _signed_color(ytd))
        + _row("3 Year",  _fmt_pct(r3yr), _signed_color(r3yr))
        + _row("5 Year",  _fmt_pct(r5yr), _signed_color(r5yr))
        + _row("10 Year", _fmt_pct(r10y), _signed_color(r10y))
    )


def _growth_section(f: dict) -> str:
    # Revenue row
    rev_yoy  = f.get("revenue_yoy")
    rev_3yr  = f.get("revenue_cagr_3yr")
    rev_5yr  = f.get("revenue_cagr_5yr")
    rev_10yr = f.get("revenue_cagr_10yr")

    # PAT row
    pat_yoy  = f.get("pat_yoy")
    pat_3yr  = f.get("pat_cagr_3yr")
    pat_5yr  = f.get("pat_cagr_5yr")
    pat_10yr = f.get("pat_cagr_10yr")

    def _cell(v: float | None) -> str:
        if v is None:
            return '<td style="padding:4px 8px;text-align:center;font-size:11px;color:#a0aec0">—</td>'
        color = "#276749" if v >= 0 else "#c53030"
        sign  = "+" if v > 0 else ""
        return f'<td style="padding:4px 8px;text-align:center;font-size:11px;font-weight:600;color:{color}">{sign}{v:.1f}%</td>'

    return f"""<div style="background:#f7fafc;border-radius:8px;padding:10px 12px;margin-bottom:10px">
  <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:6px">GROWTH</div>
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr>
        <th style="padding:4px 8px;text-align:left;font-size:9px;color:#a0aec0;font-weight:600"></th>
        <th style="padding:4px 8px;text-align:center;font-size:9px;color:#a0aec0;font-weight:600">YoY</th>
        <th style="padding:4px 8px;text-align:center;font-size:9px;color:#a0aec0;font-weight:600">3 Year</th>
        <th style="padding:4px 8px;text-align:center;font-size:9px;color:#a0aec0;font-weight:600">5 Year</th>
        <th style="padding:4px 8px;text-align:center;font-size:9px;color:#a0aec0;font-weight:600">10 Year</th>
      </tr>
    </thead>
    <tbody>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:4px 8px;font-size:10px;color:#4a5568;font-weight:600">Revenue</td>
        {_cell(rev_yoy)}{_cell(rev_3yr)}{_cell(rev_5yr)}{_cell(rev_10yr)}
      </tr>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:4px 8px;font-size:10px;color:#4a5568;font-weight:600">Net Profit</td>
        {_cell(pat_yoy)}{_cell(pat_3yr)}{_cell(pat_5yr)}{_cell(pat_10yr)}
      </tr>
    </tbody>
  </table>
</div>"""


def _qualitative_card(q: dict, border_color: str = "#cbd5e0") -> str:
    if not q:
        return ""
    tone     = q.get("management_tone", "")
    rsn      = q.get("tone_reason", "")
    pos_list = q.get("key_positives", [])
    risk_list= q.get("key_risks", [])
    triggers = q.get("recent_triggers", "")

    tone_bg = {
        "Bullish":  "#276749",
        "Cautious": "#744210",
        "Mixed":    "#2c5282",
    }.get(tone, "#4a5568")

    pos_html = "".join(
        f'<div style="font-size:10px;color:#2d3748;padding:2px 0">&#10003; {p}</div>'
        for p in pos_list[:3]
    ) or '<div style="font-size:10px;color:#a0aec0">—</div>'

    risk_html = "".join(
        f'<div style="font-size:10px;color:#2d3748;padding:2px 0">&#9650; {r}</div>'
        for r in risk_list[:3]
    ) or '<div style="font-size:10px;color:#a0aec0">—</div>'

    return f"""<div style="border-left:3px solid {border_color};background:#f7fafc;border-radius:0 8px 8px 0;padding:10px 12px;margin-bottom:2px">
  <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:6px">AI INSIGHTS</div>
  <div style="margin-bottom:8px">
    <span style="background:{tone_bg};color:white;padding:2px 8px;border-radius:6px;font-size:10px;font-weight:700">{tone}</span>
    <span style="font-size:10px;color:#4a5568;margin-left:6px">{rsn}</span>
  </div>
  <table style="width:100%;border-collapse:collapse">
    <tr style="vertical-align:top">
      <td style="width:50%;padding-right:10px">
        <div style="font-size:9px;font-weight:700;color:#276749;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Positives</div>
        {pos_html}
      </td>
      <td style="width:50%;padding-left:10px;border-left:1px solid #e2e8f0">
        <div style="font-size:9px;font-weight:700;color:#c53030;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Risks</div>
        {risk_html}
      </td>
    </tr>
  </table>
  {f'<div style="margin-top:8px;font-size:10px;color:#718096"><strong style="color:#4a5568">Triggers:</strong> {triggers}</div>' if triggers else ""}
</div>"""


# ── Named screens ─────────────────────────────────────────────────────────────

def _screens_section(screen_results: list[dict]) -> str:
    if not screen_results:
        return ""
    items = ""
    for screen in screen_results:
        syms = screen.get("symbols", [])
        if not syms:
            continue
        name    = screen.get("name", screen.get("id", ""))
        display = ", ".join(syms[:20]) + (f" +{len(syms)-20} more" if len(syms) > 20 else "")
        items += f"""
    <div style="margin-bottom:14px">
      <div style="font-size:11px;font-weight:700;color:#2d3748;border-left:3px solid #63b3ed;padding-left:8px;margin-bottom:6px">
        {name} &mdash; {len(syms)} stocks
      </div>
      <div style="font-size:11px;color:#4a5568;line-height:1.7">{display}</div>
    </div>"""
    return f"""
  <div style="padding:16px 28px;border-top:2px solid #edf2f7">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#718096;margin-bottom:12px">
      Named Screens
    </div>
    {items}
  </div>"""


# ── Footer ────────────────────────────────────────────────────────────────────

def _footer() -> str:
    return """
  <div style="background:#f7fafc;padding:14px 28px;text-align:center;border-top:1px solid #e2e8f0">
    <span style="font-size:10px;color:#a0aec0">
      Full data in attached CSV &nbsp;·&nbsp;
      AI insights: Gemini 2.5 Flash + Google News &nbsp;·&nbsp;
      <strong>Not investment advice</strong>
    </span>
  </div>"""
