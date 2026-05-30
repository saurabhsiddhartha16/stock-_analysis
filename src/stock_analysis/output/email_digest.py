"""Sends the daily email digest with HTML inline and CSV attachment."""
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
    """
    Send the daily digest email.
    Returns True on success, False on failure (non-raising so the pipeline continues).
    """
    smtp_user = os.environ.get(email_cfg.smtp_user_env_var, "")
    smtp_pass = os.environ.get(email_cfg.smtp_pass_env_var, "")

    if not smtp_user or not smtp_pass:
        logger.warning(
            "Email credentials not set — skipping email. "
            f"Set {email_cfg.smtp_user_env_var} and {email_cfg.smtp_pass_env_var} in .env"
        )
        return False

    top_stocks_str = ", ".join(s.symbol for s in scores[:3])
    subject = email_cfg.subject_template.format(
        date=run_date, top_stocks=top_stocks_str
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_cfg.from_address
    msg["To"]      = ", ".join(email_cfg.to_addresses)

    html_body = _build_email_html(
        scores[:top_n], stock_data, run_date,
        screen_results, qualitative_data or {}
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if csv_path and csv_path.exists():
        with csv_path.open("rb") as f:
            attachment = MIMEApplication(f.read(), Name=csv_path.name)
        attachment["Content-Disposition"] = f'attachment; filename="{csv_path.name}"'
        msg.attach(attachment)

    try:
        with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port) as server:
            if email_cfg.smtp_use_tls:
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(email_cfg.from_address, email_cfg.to_addresses, msg.as_string())
        logger.info(f"Email sent to {email_cfg.to_addresses}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


# ── HTML builder ──────────────────────────────────────────────────────────────

def _build_email_html(
    scores: list[StockScore],
    stock_data: dict[str, dict],
    run_date: str,
    screen_results: list[dict] | None = None,
    qualitative_data: dict[str, dict] | None = None,
) -> str:
    qual = qualitative_data or {}

    ranking_rows   = _build_ranking_table(scores, stock_data)
    qualitative_html = _build_qualitative_section(scores, stock_data, qual)
    screen_html    = _build_screen_sections(screen_results or [])

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:900px;margin:24px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:24px 28px;color:white">
    <h1 style="font-size:20px;font-weight:700;margin:0">NSE Stock Analysis</h1>
    <p style="color:#a0aec0;font-size:13px;margin:6px 0 0">
      {run_date} &nbsp;·&nbsp; Top {len(scores)} picks from quantitative screen
    </p>
  </div>

  <!-- Ranking Table -->
  <div style="padding:24px 28px 8px">
    <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#4a5568;margin-bottom:12px">
      Quantitative Rankings
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f7faff">
          <th style="padding:8px 10px;text-align:left;color:#718096;font-size:10px;text-transform:uppercase">#</th>
          <th style="padding:8px 10px;text-align:left;color:#718096;font-size:10px;text-transform:uppercase">Stock</th>
          <th style="padding:8px 10px;text-align:left;color:#718096;font-size:10px;text-transform:uppercase">Sector</th>
          <th style="padding:8px 10px;text-align:right;color:#718096;font-size:10px;text-transform:uppercase">Score</th>
          <th style="padding:8px 10px;text-align:right;color:#48bb78;font-size:10px;text-transform:uppercase">Growth</th>
          <th style="padding:8px 10px;text-align:right;color:#9f7aea;font-size:10px;text-transform:uppercase">Quality</th>
          <th style="padding:8px 10px;text-align:right;color:#667eea;font-size:10px;text-transform:uppercase">Value</th>
          <th style="padding:8px 10px;text-align:right;color:#ed8936;font-size:10px;text-transform:uppercase">Momentum</th>
          <th style="padding:8px 10px;text-align:right;color:#fc8181;font-size:10px;text-transform:uppercase">Risk</th>
          <th style="padding:8px 10px;text-align:right;color:#718096;font-size:10px;text-transform:uppercase">P/E</th>
          <th style="padding:8px 10px;text-align:right;color:#718096;font-size:10px;text-transform:uppercase">ROE</th>
        </tr>
      </thead>
      <tbody>{ranking_rows}</tbody>
    </table>
  </div>

  <!-- Qualitative Insights -->
  {qualitative_html}

  <!-- Named Screens -->
  {screen_html}

  <!-- Footer -->
  <div style="background:#f7faff;padding:14px 28px;font-size:11px;color:#718096;text-align:center">
    Full details in the attached CSV &nbsp;·&nbsp; NSE Stock Analysis Agent &nbsp;·&nbsp;
    <strong>Not investment advice.</strong>
  </div>

</div>
</body></html>"""


def _build_ranking_table(scores: list[StockScore], stock_data: dict) -> str:
    rows = ""
    for i, s in enumerate(scores, 1):
        f      = stock_data.get(s.symbol, {}).get("fundamentals", {})
        u      = stock_data.get(s.symbol, {}).get("universe", {})
        name   = f.get("company_name") or s.symbol
        sector = u.get("sector") or f.get("sector_yf") or ""
        pe     = f"{f['pe_ratio']:.1f}"    if f.get("pe_ratio")    else "—"
        roe    = f"{f['roe_5yr_avg']:.1f}%" if f.get("roe_5yr_avg") else "—"

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        score_color = (
            "#276749" if s.composite >= 55 else
            "#744210" if s.composite >= 40 else "#742a2a"
        )
        rows += f"""
        <tr style="border-bottom:1px solid #f0f2f5">
          <td style="padding:8px 10px;font-weight:700;font-size:12px">{medal}</td>
          <td style="padding:8px 10px">
            <div style="font-weight:700;font-size:12px">{s.symbol}</div>
            <div style="font-size:10px;color:#718096">{name}</div>
          </td>
          <td style="padding:8px 10px;font-size:10px;color:#2b6cb0">{sector}</td>
          <td style="padding:8px 10px;font-weight:800;font-size:15px;color:{score_color};text-align:right">{s.composite:.1f}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px">{s.growth:.0f}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px">{s.quality:.0f}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px">{s.valuation:.0f}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px">{s.momentum:.0f}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px;color:#c53030">{s.risk:.0f}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px">{pe}</td>
          <td style="padding:8px 10px;text-align:right;font-size:11px">{roe}</td>
        </tr>"""
    return rows


def _build_qualitative_section(
    scores: list[StockScore],
    stock_data: dict,
    qual: dict[str, dict],
) -> str:
    if not qual:
        return ""

    cards = ""
    for i, s in enumerate(scores, 1):
        q = qual.get(s.symbol)
        if not q:
            continue

        f    = stock_data.get(s.symbol, {}).get("fundamentals", {})
        name = f.get("company_name") or s.symbol

        sentiment = q.get("overall_sentiment", "Neutral")
        tone      = q.get("management_tone", "Unknown")
        tone_rsn  = q.get("tone_reason", "")
        triggers  = q.get("recent_triggers", "")
        positives = q.get("key_positives", [])
        risks     = q.get("key_risks", [])

        # Colour scheme by sentiment
        sentiment_color, badge_bg, border_color = {
            "Positive": ("#276749", "#276749", "#68d391"),
            "Negative": ("#742a2a", "#742a2a", "#fc8181"),
        }.get(sentiment, ("#2d3748", "#718096", "#cbd5e0"))

        tone_badge_bg = {
            "Bullish":  "#276749",
            "Cautious": "#744210",
            "Mixed":    "#2b6cb0",
        }.get(tone, "#718096")

        pos_items = "".join(
            f'<div style="font-size:11px;color:#2d3748;padding:2px 0">&#10003; {p}</div>'
            for p in positives[:3]
        ) or '<div style="font-size:11px;color:#a0aec0">No positives identified</div>'

        risk_items = "".join(
            f'<div style="font-size:11px;color:#2d3748;padding:2px 0">&#9888; {r}</div>'
            for r in risks[:3]
        ) or '<div style="font-size:11px;color:#a0aec0">No risks identified</div>'

        cards += f"""
<div style="margin:8px 0;padding:14px;background:#f8faff;border-radius:8px;border-left:4px solid {border_color}">
  <!-- Card header -->
  <table style="width:100%;border-collapse:collapse">
    <tr>
      <td style="font-weight:700;font-size:13px;color:#1a1a2e">
        {i}. {s.symbol} &nbsp;
        <span style="font-weight:400;font-size:11px;color:#718096">{name}</span>
      </td>
      <td style="text-align:right">
        <span style="background:{badge_bg};color:white;padding:3px 9px;border-radius:10px;font-size:10px;font-weight:700">
          {sentiment}
        </span>
      </td>
    </tr>
  </table>
  <!-- Tone -->
  <div style="margin-top:6px;font-size:11px;color:#4a5568">
    <span style="background:{tone_badge_bg};color:white;padding:2px 7px;border-radius:8px;font-size:10px;font-weight:600;margin-right:6px">{tone}</span>
    {tone_rsn}
  </div>
  <!-- Positives + Risks side by side -->
  <table style="width:100%;border-collapse:collapse;margin-top:10px">
    <tr>
      <td style="width:50%;vertical-align:top;padding-right:10px">
        <div style="font-size:10px;font-weight:700;color:#276749;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Positives</div>
        {pos_items}
      </td>
      <td style="width:50%;vertical-align:top;padding-left:10px;border-left:1px solid #e2e8f0">
        <div style="font-size:10px;font-weight:700;color:#c53030;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Risks</div>
        {risk_items}
      </td>
    </tr>
  </table>
  <!-- Triggers -->
  {f'<div style="margin-top:8px;font-size:11px;color:#718096;font-style:italic"><strong style="color:#4a5568">Recent triggers:</strong> {triggers}</div>' if triggers else ""}
</div>"""

    if not cards:
        return ""

    return f"""
  <div style="padding:16px 28px 8px">
    <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#4a5568;margin-bottom:12px">
      Qualitative Insights (AI-synthesised from recent news)
    </div>
    {cards}
    <div style="font-size:10px;color:#a0aec0;margin-top:8px">
      Powered by Gemini 1.5 Flash &nbsp;·&nbsp; Based on publicly available news. Not investment advice.
    </div>
  </div>"""


def _build_screen_sections(screen_results: list[dict]) -> str:
    html = ""
    for screen in screen_results:
        sym_list = screen.get("symbols", [])
        if not sym_list:
            continue
        name        = screen.get("name", screen.get("id", ""))
        count       = len(sym_list)
        sym_display = ", ".join(sym_list[:20])
        if count > 20:
            sym_display += f" ... +{count - 20} more"
        html += f"""
<div style="margin-top:16px;padding:0 28px 16px">
  <div style="font-weight:700;font-size:12px;color:#1a1a2e;border-left:3px solid #63b3ed;padding-left:10px;margin-bottom:8px">
    {name} &mdash; {count} stocks
  </div>
  <div style="font-size:11px;color:#4a5568;line-height:1.8">{sym_display}</div>
</div>"""
    return html
