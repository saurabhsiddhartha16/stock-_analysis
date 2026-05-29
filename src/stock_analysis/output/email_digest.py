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
) -> bool:
    """
    Send the daily digest email.

    Returns True on success, False on failure (non-raising so the pipeline
    continues even if email fails).
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
    msg["From"] = email_cfg.from_address
    msg["To"] = ", ".join(email_cfg.to_addresses)

    html_body = _build_email_html(scores[:top_n], stock_data, run_date, screen_results)
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
            server.sendmail(
                email_cfg.from_address,
                email_cfg.to_addresses,
                msg.as_string(),
            )
        logger.info(f"Email sent to {email_cfg.to_addresses}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def _build_email_html(
    scores: list[StockScore],
    stock_data: dict[str, dict],
    run_date: str,
    screen_results: list[dict] | None = None,
) -> str:
    rows = ""
    for i, s in enumerate(scores, 1):
        f = stock_data.get(s.symbol, {}).get("fundamentals", {})
        u = stock_data.get(s.symbol, {}).get("universe", {})
        name = f.get("company_name") or s.symbol
        sector = u.get("sector") or f.get("sector_yf") or ""
        pe = f"{f['pe_ratio']:.1f}" if f.get("pe_ratio") else "—"
        roe = f"{f['roe_5yr_avg']:.1f}%" if f.get("roe_5yr_avg") else "—"
        rev = f"{f['revenue_cagr_3yr']:.1f}%" if f.get("revenue_cagr_3yr") else "—"

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        score_color = "#276749" if s.composite >= 55 else "#744210" if s.composite >= 40 else "#742a2a"

        rows += f"""
        <tr style="border-bottom:1px solid #f0f2f5">
          <td style="padding:10px 14px;font-weight:700;font-size:13px">{medal}</td>
          <td style="padding:10px 14px">
            <div style="font-weight:700;font-size:13px">{s.symbol}</div>
            <div style="font-size:11px;color:#718096">{name}</div>
          </td>
          <td style="padding:10px 14px;font-size:11px;color:#2b6cb0;background:#ebf4ff;border-radius:8px">{sector}</td>
          <td style="padding:10px 14px;font-weight:800;font-size:16px;color:{score_color};text-align:right">{s.composite:.1f}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px">{s.growth:.0f}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px">{s.quality:.0f}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px">{s.momentum:.0f}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px;color:#c53030">{s.risk:.0f}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px">{pe}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px">{roe}</td>
          <td style="padding:10px 14px;text-align:right;font-size:12px">{rev}</td>
        </tr>"""

    # Build named screen sections HTML
    screen_sections_html = ""
    for screen in (screen_results or []):
        sym_list = screen.get("symbols", [])
        if not sym_list:
            continue
        screen_name = screen.get("name", screen.get("id", ""))
        count = len(sym_list)
        sym_display = ", ".join(sym_list[:20])
        if count > 20:
            sym_display += f" ... +{count - 20} more"
        screen_sections_html += f"""
<div style="margin-top:20px; padding: 0 28px 20px">
  <div style="font-weight:700; font-size:13px; color:#1a1a2e; border-left:3px solid #63b3ed; padding-left:10px; margin-bottom:10px">
    {screen_name} &mdash; {count} stocks
  </div>
  <div style="font-size:12px; color:#4a5568; line-height:1.8">{sym_display}</div>
</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:900px;margin:24px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:24px 28px;color:white">
    <h1 style="font-size:20px;font-weight:700;margin:0">NSE Daily Stock Analysis</h1>
    <p style="color:#a0aec0;font-size:13px;margin:6px 0 0">{run_date} &nbsp;·&nbsp; Top {len(scores)} picks from quantitative screen</p>
  </div>
  <div style="padding:24px 28px">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#f7faff">
          <th style="padding:8px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">#</th>
          <th style="padding:8px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">Stock</th>
          <th style="padding:8px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">Sector</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">Score</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#48bb78">Growth</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#9f7aea">Quality</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#ed8936">Momentum</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#fc8181">Risk</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">PE</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">ROE</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#4a5568">Rev CAGR</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>{screen_sections_html}
  <div style="background:#f7faff;padding:16px 28px;font-size:11px;color:#718096;text-align:center">
    Full details in the attached CSV &nbsp;·&nbsp; NSE Stock Analysis Agent &nbsp;·&nbsp; Not investment advice.
  </div>
</div>
</body></html>"""
