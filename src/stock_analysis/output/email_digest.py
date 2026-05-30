"""
NSE Stock Analysis Email Digest — comprehensive sectioned report.

Structure:
  1. Header
  2. Market Overview  — index prices + FII/DII buy/sell
  3. Five sections    — top 3 stocks each, with deep-dive per stock
  4. Footer + sources

Sources cited inline:
  Index data  : Yahoo Finance (yfinance)
  FII/DII     : NSE India (nseindia.com)
  Fundamentals: Screener.in + Yahoo Finance
  AI insights : Google News RSS + Gemini 2.5 Flash
"""
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
    market_indices: list[dict] | None = None,
    fii_dii_data: dict | None = None,
    email_sections: list[dict] | None = None,
) -> bool:
    smtp_user = os.environ.get(email_cfg.smtp_user_env_var, "")
    smtp_pass = os.environ.get(email_cfg.smtp_pass_env_var, "")
    if not smtp_user or not smtp_pass:
        logger.warning(
            f"Email credentials not set — skipping. "
            f"Set {email_cfg.smtp_user_env_var} and {email_cfg.smtp_pass_env_var} in .env"
        )
        return False

    top3 = ", ".join(s.symbol for s in scores[:3])
    subject = email_cfg.subject_template.format(date=run_date, top_stocks=top3)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_cfg.from_address
    msg["To"]      = ", ".join(email_cfg.to_addresses)

    html = _build_html(
        run_date        = run_date,
        market_indices  = market_indices or [],
        fii_dii_data    = fii_dii_data,
        email_sections  = email_sections or [],
        stock_data      = stock_data,
        qual            = qualitative_data or {},
    )
    msg.attach(MIMEText(html, "html", "utf-8"))

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
    run_date: str,
    market_indices: list[dict],
    fii_dii_data: dict | None,
    email_sections: list[dict],
    stock_data: dict,
    qual: dict,
) -> str:
    sections_html = "".join(
        _section_block(sec, stock_data, qual)
        for sec in email_sections
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#edf2f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<div style="max-width:800px;margin:16px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.10)">
  {_header(run_date)}
  {_market_overview(market_indices, fii_dii_data)}
  {sections_html}
  {_footer()}
</div>
</body></html>"""


# ── 1. Header ─────────────────────────────────────────────────────────────────

def _header(run_date: str) -> str:
    return f"""
<div style="background:linear-gradient(135deg,#1a202c 0%,#2d3748 100%);padding:20px 24px">
  <table style="width:100%;border-collapse:collapse">
    <tr>
      <td>
        <div style="color:white;font-size:18px;font-weight:700">NSE Stock Analysis</div>
        <div style="color:#a0aec0;font-size:11px;margin-top:3px">{run_date}</div>
      </td>
      <td style="text-align:right;color:#4fd1c5;font-size:22px;font-weight:800">NSE</td>
    </tr>
  </table>
</div>"""


# ── 2. Market Overview ────────────────────────────────────────────────────────

def _market_overview(indices: list[dict], fii_dii: dict | None) -> str:
    if not indices and not fii_dii:
        return ""

    # Index cards
    index_cells = ""
    for idx in indices:
        price = idx.get("price")
        chg   = idx.get("change")
        pct   = idx.get("change_pct")
        if price is None:
            continue
        is_up    = (pct or 0) >= 0
        pct_color = "#276749" if is_up else "#c53030"
        arrow    = "&#9650;" if is_up else "&#9660;"
        sign     = "+" if is_up else ""
        index_cells += f"""
<td style="padding:8px 10px;text-align:center;border-right:1px solid #e2e8f0">
  <div style="font-size:9px;color:#718096;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px">{idx['name']}</div>
  <div style="font-size:13px;font-weight:700;color:#1a202c">{price:,.0f}</div>
  <div style="font-size:10px;font-weight:600;color:{pct_color}">{arrow} {sign}{pct:.2f}%</div>
</td>"""

    # FII/DII row
    fii_html = ""
    if fii_dii:
        def _net_badge(v: float) -> str:
            color = "#276749" if v >= 0 else "#c53030"
            sign  = "+" if v >= 0 else ""
            return f'<span style="color:{color};font-weight:700">{sign}{v:,.0f} Cr</span>'

        fii_html = f"""
<div style="padding:10px 16px;background:#f7fafc;border-top:1px solid #e2e8f0">
  <table style="width:100%;border-collapse:collapse">
    <tr>
      <td style="font-size:10px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.5px">
        FII / DII Activity &nbsp;
        <span style="font-weight:400;color:#a0aec0">(as of {fii_dii.get('date','')})</span>
      </td>
      <td style="text-align:right;font-size:11px">
        FII Net: {_net_badge(fii_dii['fii_net'])}
        &nbsp;&nbsp;|&nbsp;&nbsp;
        DII Net: {_net_badge(fii_dii['dii_net'])}
      </td>
    </tr>
    <tr>
      <td colspan="2" style="padding-top:4px;font-size:10px;color:#a0aec0">
        FII Buy: {fii_dii['fii_buy']:,.0f} Cr &nbsp; Sell: {fii_dii['fii_sell']:,.0f} Cr
        &nbsp;&nbsp;|&nbsp;&nbsp;
        DII Buy: {fii_dii['dii_buy']:,.0f} Cr &nbsp; Sell: {fii_dii['dii_sell']:,.0f} Cr
        &nbsp;&nbsp;
        <span style="color:#cbd5e0">Source: NSE India</span>
      </td>
    </tr>
  </table>
</div>"""

    return f"""
<div style="padding:12px 16px;background:#f7fafc;border-bottom:2px solid #e2e8f0">
  <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:8px">
    Market Overview &nbsp;<span style="color:#cbd5e0;font-weight:400">Source: Yahoo Finance</span>
  </div>
  <table style="width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;border:1px solid #e2e8f0">
    <tr>{index_cells}</tr>
  </table>
</div>
{fii_html}"""


# ── 3. Section block ──────────────────────────────────────────────────────────

def _section_block(sec: dict, stock_data: dict, qual: dict) -> str:
    stocks      = sec.get("stocks", [])
    name        = sec["name"]
    desc        = sec.get("description", "")
    criteria    = sec.get("criteria_note", "")
    color_hdr   = sec.get("color_header", "#2d3748")
    color_bdr   = sec.get("color_border", "#cbd5e0")
    q_count     = sec.get("qualifying_count", 0)

    if not stocks:
        no_picks = f"""
<div style="padding:12px 16px;background:#fffbeb;border-radius:8px;margin:12px 16px;font-size:11px;color:#744210">
  No stocks qualified for this section today.
  ({q_count} met the criteria but were shown recently — check back next run.)
</div>"""
        body = no_picks
    else:
        body = "".join(_stock_card(s, stock_data, qual, color_bdr) for s in stocks)

    return f"""
<div style="border-top:3px solid {color_bdr};margin-top:0">
  <!-- Section header -->
  <div style="background:{color_hdr};padding:12px 20px">
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td>
          <div style="color:white;font-size:14px;font-weight:700">{name}</div>
          <div style="color:rgba(255,255,255,0.65);font-size:10px;margin-top:2px">{desc}</div>
        </td>
        <td style="text-align:right;color:rgba(255,255,255,0.5);font-size:10px">
          {q_count} stocks qualified
        </td>
      </tr>
    </table>
  </div>
  <!-- Criteria note -->
  <div style="padding:6px 20px;background:rgba(0,0,0,0.03);font-size:9px;color:#a0aec0;border-bottom:1px solid #e2e8f0">
    Criteria: {criteria}
  </div>
  <!-- Stock cards -->
  {body}
</div>"""


# ── 4. Per-stock card ─────────────────────────────────────────────────────────

def _stock_card(s: StockScore, stock_data: dict, qual: dict, border_color: str) -> str:
    f    = stock_data.get(s.symbol, {}).get("fundamentals", {})
    t    = stock_data.get(s.symbol, {}).get("technicals", {})
    u    = stock_data.get(s.symbol, {}).get("universe", {})
    q    = qual.get(s.symbol, {})

    name     = f.get("company_name") or s.symbol
    sector   = u.get("sector") or f.get("sector_yf") or ""
    sentiment = q.get("overall_sentiment", "") if q else ""

    sent_color = {"Positive": "#276749", "Negative": "#c53030"}.get(sentiment, "#718096")
    sent_badge = (
        f'<span style="background:{sent_color};color:white;padding:2px 8px;'
        f'border-radius:8px;font-size:9px;font-weight:700">{sentiment}</span>'
        if sentiment else ""
    )

    return f"""
<div style="padding:14px 20px;border-bottom:1px solid #edf2f7">

  <!-- Stock header -->
  <table style="width:100%;border-collapse:collapse;margin-bottom:10px">
    <tr>
      <td>
        <span style="font-size:15px;font-weight:800;color:#1a202c">{s.symbol}</span>
        <span style="font-size:11px;color:#718096;margin-left:6px">{name}</span>
        <span style="font-size:10px;color:#4a90d9;margin-left:6px">{sector}</span>
      </td>
      <td style="text-align:right">
        {sent_badge}
        <span style="background:#edf2f7;color:#2d3748;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;margin-left:4px">
          Score {s.composite:.1f}
        </span>
      </td>
    </tr>
  </table>

  <!-- Data grid: 3 columns -->
  <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
    <tr style="vertical-align:top">
      <td style="width:33%;padding-right:8px">{_box("PRICE", _price_rows(f, t))}</td>
      <td style="width:33%;padding-right:8px">{_box("KEY RATIOS", _ratios_rows(f))}</td>
      <td style="width:34%">{_box("STOCK PERFORMANCE", _perf_rows(t))}</td>
    </tr>
  </table>

  <!-- Growth table -->
  {_growth_table(f)}

  <!-- Quarterly financial performance -->
  {_quarterly_section(f)}

  <!-- AI Qualitative insights -->
  {_qual_section(q, border_color)}

</div>"""


# ── Helper: coloured box ──────────────────────────────────────────────────────

def _box(title: str, content: str) -> str:
    return (
        f'<div style="background:#f7fafc;border-radius:6px;padding:8px 10px">'
        f'<div style="font-size:8px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;color:#a0aec0;margin-bottom:5px">{title}</div>'
        f'{content}</div>'
    )


def _kv(label: str, value: str, vc: str = "#1a202c") -> str:
    return (
        f'<table style="width:100%;border-collapse:collapse;margin-bottom:2px"><tr>'
        f'<td style="font-size:9px;color:#718096">{label}</td>'
        f'<td style="font-size:10px;font-weight:600;color:{vc};text-align:right">{value}</td>'
        f'</tr></table>'
    )


def _color(v: float | None) -> str:
    if v is None:
        return "#a0aec0"
    return "#276749" if v >= 0 else "#c53030"


def _pct(v: float | None, plus: bool = True) -> str:
    if v is None:
        return "—"
    s = "+" if plus and v > 0 else ""
    return f"{s}{v:.1f}%"


# ── Price block ───────────────────────────────────────────────────────────────

def _price_rows(f: dict, t: dict) -> str:
    cmp  = t.get("close")
    pe   = f.get("pe_ratio")
    e50  = t.get("price_vs_ema50_pct")
    e200 = t.get("price_vs_ema200_pct")
    ema50_val  = t.get("EMA_50")
    ema200_val = t.get("EMA_200")

    def _ema_str(pct, val):
        if pct is None:
            return "—"
        lbl = "above" if pct >= 0 else "below"
        sign = "+" if pct >= 0 else ""
        price_part = f" ({val:,.0f})" if val else ""
        return f"{sign}{pct:.1f}% {lbl}{price_part}"

    return (
        _kv("CMP", f"&#8377;{cmp:,.1f}" if cmp else "—")
        + _kv("P/E Ratio", f"{pe:.1f}x" if pe else "—")
        + _kv("vs EMA 50",  _ema_str(e50,  ema50_val),  _color(e50))
        + _kv("vs EMA 200", _ema_str(e200, ema200_val), _color(e200))
    )


# ── Ratios block ──────────────────────────────────────────────────────────────

def _ratios_rows(f: dict) -> str:
    roe  = f.get("roe_5yr_avg") or f.get("roe_ttm")
    roce = f.get("roce_5yr_avg") or f.get("roce")
    roa  = f.get("roa_5yr_avg") or f.get("roa")
    npm  = f.get("npm_ttm") or f.get("npm_q1")
    return (
        _kv("ROE (5yr avg)",  f"{roe:.1f}%"  if roe  else "—")
        + _kv("ROCE (5yr avg)", f"{roce:.1f}%" if roce else "—")
        + _kv("ROA (5yr avg)",  f"{roa:.1f}%"  if roa  else "—")
        + _kv("Net Margin",     f"{npm:.1f}%"  if npm  else "—")
    )


# ── Stock performance block ───────────────────────────────────────────────────

def _perf_rows(t: dict) -> str:
    ytd  = t.get("return_ytd")
    y3   = t.get("return_3yr")
    y5   = t.get("return_5yr")
    y10  = t.get("return_10yr")
    return (
        _kv("YTD",     _pct(ytd), _color(ytd))
        + _kv("3 Year",  _pct(y3),  _color(y3))
        + _kv("5 Year",  _pct(y5),  _color(y5))
        + _kv("10 Year", _pct(y10), _color(y10))
    )


# ── Growth table (Revenue + Net Profit) ──────────────────────────────────────

def _growth_table(f: dict) -> str:
    def _cell(v: float | None) -> str:
        if v is None:
            return '<td style="padding:3px 6px;text-align:center;font-size:10px;color:#a0aec0">—</td>'
        c = "#276749" if v >= 0 else "#c53030"
        s = "+" if v > 0 else ""
        return f'<td style="padding:3px 6px;text-align:center;font-size:10px;font-weight:600;color:{c}">{s}{v:.1f}%</td>'

    return f"""
<div style="background:#f7fafc;border-radius:6px;padding:8px 10px;margin-bottom:8px">
  <div style="font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:5px">
    GROWTH &nbsp;<span style="color:#cbd5e0;font-weight:400">Source: Screener.in / Yahoo Finance</span>
  </div>
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr>
        <th style="padding:3px 6px;font-size:8px;color:#a0aec0;text-align:left;font-weight:600"></th>
        <th style="padding:3px 6px;font-size:8px;color:#a0aec0;text-align:center;font-weight:600">YoY</th>
        <th style="padding:3px 6px;font-size:8px;color:#a0aec0;text-align:center;font-weight:600">3 Year</th>
        <th style="padding:3px 6px;font-size:8px;color:#a0aec0;text-align:center;font-weight:600">5 Year</th>
        <th style="padding:3px 6px;font-size:8px;color:#a0aec0;text-align:center;font-weight:600">10 Year</th>
      </tr>
    </thead>
    <tbody>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:3px 6px;font-size:9px;font-weight:600;color:#4a5568">Revenue</td>
        {_cell(f.get('revenue_yoy'))}{_cell(f.get('revenue_cagr_3yr'))}{_cell(f.get('revenue_cagr_5yr'))}{_cell(f.get('revenue_cagr_10yr'))}
      </tr>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:3px 6px;font-size:9px;font-weight:600;color:#4a5568">Net Profit</td>
        {_cell(f.get('pat_yoy'))}{_cell(f.get('pat_cagr_3yr'))}{_cell(f.get('pat_cagr_5yr'))}{_cell(f.get('pat_cagr_10yr'))}
      </tr>
    </tbody>
  </table>
</div>"""


# ── Quarterly performance (QoQ / YoY) ────────────────────────────────────────

def _quarterly_section(f: dict) -> str:
    q1 = f.get("q1_label") or "Latest Q"
    q2 = f.get("q2_label") or "Prev Q"
    r1  = f.get("rev_q1_cr")
    r2  = f.get("rev_q2_cr")
    rqq = f.get("rev_qoq_pct")
    ryy = f.get("rev_yoy_pct")
    o1, o2, odelta = f.get("opm_q1"), f.get("opm_q2"), f.get("opm_qoq_pts")
    n1, n2, ndelta = f.get("npm_q1"), f.get("npm_q2"), f.get("npm_qoq_pts")

    # Skip if no quarterly data at all
    if not any([r1, o1, n1]):
        return ""

    def _margin_delta(delta: float | None) -> str:
        if delta is None:
            return "—"
        c = "#276749" if delta >= 0 else "#c53030"
        s = "+" if delta > 0 else ""
        return f'<span style="color:{c}">{s}{delta:.1f} pp</span>'

    def _fmt_cr(v: float | None) -> str:
        return f"&#8377;{v:,.0f} Cr" if v else "—"

    return f"""
<div style="background:#f7fafc;border-radius:6px;padding:8px 10px;margin-bottom:8px">
  <div style="font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:5px">
    QUARTERLY PERFORMANCE &nbsp;<span style="color:#cbd5e0;font-weight:400">Source: Yahoo Finance</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:10px">
    <thead>
      <tr>
        <th style="padding:3px 6px;text-align:left;font-size:8px;color:#a0aec0;font-weight:600">Metric</th>
        <th style="padding:3px 6px;text-align:right;font-size:8px;color:#a0aec0;font-weight:600">{q1}</th>
        <th style="padding:3px 6px;text-align:right;font-size:8px;color:#a0aec0;font-weight:600">{q2}</th>
        <th style="padding:3px 6px;text-align:right;font-size:8px;color:#a0aec0;font-weight:600">QoQ</th>
        <th style="padding:3px 6px;text-align:right;font-size:8px;color:#a0aec0;font-weight:600">YoY</th>
      </tr>
    </thead>
    <tbody>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:3px 6px;font-weight:600;color:#4a5568">Revenue</td>
        <td style="padding:3px 6px;text-align:right">{_fmt_cr(r1)}</td>
        <td style="padding:3px 6px;text-align:right;color:#718096">{_fmt_cr(r2)}</td>
        <td style="padding:3px 6px;text-align:right">{_pct(rqq) if rqq else "—"}</td>
        <td style="padding:3px 6px;text-align:right">{_pct(ryy) if ryy else "—"}</td>
      </tr>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:3px 6px;font-weight:600;color:#4a5568">OPM</td>
        <td style="padding:3px 6px;text-align:right">{f"{o1:.1f}%" if o1 else "—"}</td>
        <td style="padding:3px 6px;text-align:right;color:#718096">{f"{o2:.1f}%" if o2 else "—"}</td>
        <td style="padding:3px 6px;text-align:right">{_margin_delta(odelta)}</td>
        <td style="padding:3px 6px;text-align:right;color:#a0aec0">—</td>
      </tr>
      <tr style="border-top:1px solid #e2e8f0">
        <td style="padding:3px 6px;font-weight:600;color:#4a5568">NPM</td>
        <td style="padding:3px 6px;text-align:right">{f"{n1:.1f}%" if n1 else "—"}</td>
        <td style="padding:3px 6px;text-align:right;color:#718096">{f"{n2:.1f}%" if n2 else "—"}</td>
        <td style="padding:3px 6px;text-align:right">{_margin_delta(ndelta)}</td>
        <td style="padding:3px 6px;text-align:right;color:#a0aec0">—</td>
      </tr>
    </tbody>
  </table>
</div>"""


# ── AI Qualitative insights ───────────────────────────────────────────────────

def _qual_section(q: dict, border_color: str) -> str:
    if not q or q.get("management_tone") == "Unknown":
        return ""

    tone     = q.get("management_tone", "")
    rsn      = q.get("tone_reason", "")
    pos_list = q.get("key_positives", [])
    risk_list= q.get("key_risks", [])
    triggers = q.get("recent_triggers", "")

    tone_bg = {"Bullish": "#276749", "Cautious": "#744210", "Mixed": "#2c5282"}.get(tone, "#4a5568")

    pos_html = "".join(
        f'<div style="font-size:9px;color:#2d3748;padding:1px 0">&#10003; {p}</div>'
        for p in pos_list[:3]
    ) or '<div style="font-size:9px;color:#a0aec0">—</div>'

    risk_html = "".join(
        f'<div style="font-size:9px;color:#2d3748;padding:1px 0">&#9650; {r}</div>'
        for r in risk_list[:3]
    ) or '<div style="font-size:9px;color:#a0aec0">—</div>'

    return f"""
<div style="border-left:3px solid {border_color};padding:8px 10px;background:#f7fafc;border-radius:0 6px 6px 0;margin-bottom:2px">
  <div style="font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;margin-bottom:5px">
    AI INSIGHTS &nbsp;<span style="color:#cbd5e0;font-weight:400">Source: Google News RSS + Gemini 2.5 Flash</span>
  </div>
  <div style="margin-bottom:6px">
    <span style="background:{tone_bg};color:white;padding:1px 7px;border-radius:6px;font-size:9px;font-weight:700">{tone}</span>
    <span style="font-size:9px;color:#4a5568;margin-left:6px">{rsn}</span>
  </div>
  <table style="width:100%;border-collapse:collapse">
    <tr style="vertical-align:top">
      <td style="width:50%;padding-right:8px">
        <div style="font-size:8px;font-weight:700;color:#276749;text-transform:uppercase;margin-bottom:3px">Positives</div>
        {pos_html}
      </td>
      <td style="width:50%;padding-left:8px;border-left:1px solid #e2e8f0">
        <div style="font-size:8px;font-weight:700;color:#c53030;text-transform:uppercase;margin-bottom:3px">Risks</div>
        {risk_html}
      </td>
    </tr>
  </table>
  {f'<div style="margin-top:6px;font-size:9px;color:#718096"><strong style="color:#4a5568">Triggers:</strong> {triggers}</div>' if triggers else ""}
</div>"""


# ── Footer ────────────────────────────────────────────────────────────────────

def _footer() -> str:
    return """
<div style="background:#f7fafc;padding:12px 20px;border-top:1px solid #e2e8f0;text-align:center">
  <div style="font-size:9px;color:#a0aec0;margin-bottom:4px">
    <strong>Sources:</strong>
    Index prices: Yahoo Finance &nbsp;|&nbsp;
    FII/DII: NSE India (nseindia.com) &nbsp;|&nbsp;
    Fundamentals: Screener.in + Yahoo Finance &nbsp;|&nbsp;
    AI insights: Google News RSS + Gemini 2.5 Flash
  </div>
  <div style="font-size:9px;color:#cbd5e0">
    NSE Stock Analysis Agent &nbsp;|&nbsp;
    <strong style="color:#a0aec0">Not investment advice. Verify before acting.</strong>
  </div>
</div>"""
