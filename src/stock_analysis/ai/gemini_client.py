"""
Gemini 1.5 Flash client for qualitative synthesis.
Uses Google AI Studio free tier: 15 RPM, 1M tokens/day — zero cost.
"""
from __future__ import annotations

import json
import os
import time
from loguru import logger

try:
    from google import genai as google_genai
    _HAS_GENAI = True
except ImportError:
    _HAS_GENAI = False

_client = None
_RATE_LIMIT_DELAY = 4.5   # 15 RPM free tier → 1 req / 4s; 4.5 adds buffer
_MODEL_NAME       = "gemini-2.5-flash"


# ── Client initialisation ─────────────────────────────────────────────────────

def _get_client(api_key_env_var: str = "GEMINI_API_KEY"):
    global _client
    if _client is None:
        if not _HAS_GENAI:
            raise ImportError(
                "google-genai is not installed. "
                "Run: pip install google-genai"
            )
        key = os.environ.get(api_key_env_var, "").strip()
        if not key:
            raise ValueError(
                f"Gemini API key not found. "
                f"Set {api_key_env_var} in your .env file. "
                f"Get a free key at https://aistudio.google.com/app/apikey"
            )
        _client = google_genai.Client(api_key=key)
        logger.info("Gemini 1.5 Flash client initialised (google-genai SDK)")
    return _client


# ── Main synthesis function ───────────────────────────────────────────────────

def synthesize(
    company_name: str,
    symbol: str,
    news_items: list[dict],
    fundamentals: dict,
    api_key_env_var: str = "GEMINI_API_KEY",
) -> dict:
    """
    Call Gemini to produce a structured qualitative brief for a stock.

    Returns a dict with keys:
      management_tone     : Bullish | Neutral | Cautious | Mixed
      tone_reason         : one-sentence explanation
      key_positives       : list[str] — 2-3 bullet points
      key_risks           : list[str] — 2-3 bullet points
      recent_triggers     : str — 1-2 sentences on recent drivers
      overall_sentiment   : Positive | Neutral | Negative
    """
    if not news_items:
        return _empty("No recent news available for analysis")

    try:
        client = _get_client(api_key_env_var)
    except Exception as e:
        logger.warning(f"Gemini unavailable: {e}")
        return _empty(str(e))

    prompt = _build_prompt(company_name, symbol, news_items, fundamentals)

    try:
        time.sleep(_RATE_LIMIT_DELAY)
        response = client.models.generate_content(model=_MODEL_NAME, contents=prompt)
        raw      = response.text.strip()

        # Strip markdown code fences if Gemini wraps in ```json ... ```
        if "```" in raw:
            parts = raw.split("```")
            raw   = parts[1] if len(parts) >= 2 else raw
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw.strip())

        # Ensure all required keys exist
        defaults = _empty("")
        for key, default_val in defaults.items():
            if key not in result:
                result[key] = default_val

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"Gemini JSON parse failed for {symbol}: {e}")
        return _empty("Analysis parse error — will retry on next run")
    except Exception as e:
        logger.warning(f"Gemini call failed for {symbol}: {type(e).__name__}: {e}")
        return _empty(f"Synthesis error: {type(e).__name__}")


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    company_name: str,
    symbol: str,
    news_items: list[dict],
    fundamentals: dict,
) -> str:
    news_block = _format_news(news_items)
    fin_block  = _format_financials(fundamentals)

    return f"""You are a concise financial analyst covering Indian stocks listed on NSE.

Analyze the following information about {company_name} (NSE: {symbol}):

RECENT NEWS & DEVELOPMENTS (last 30 days):
{news_block}

KEY FINANCIAL CONTEXT:
{fin_block}

Reply with ONLY a valid JSON object — no markdown, no code fences, no explanation outside the JSON:
{{
  "management_tone": "Bullish|Neutral|Cautious|Mixed",
  "tone_reason": "one sentence explaining the tone",
  "key_positives": ["point 1", "point 2", "point 3"],
  "key_risks": ["risk 1", "risk 2"],
  "recent_triggers": "1-2 sentences on what has driven this stock recently",
  "overall_sentiment": "Positive|Neutral|Negative"
}}

Rules:
- Base analysis ONLY on the provided information above
- If news coverage is thin, say "Limited recent coverage" in tone_reason
- Keep each bullet point under 12 words
- overall_sentiment must be exactly: Positive, Neutral, or Negative"""


def _format_news(items: list[dict]) -> str:
    lines = []
    for item in items:
        date = f"[{item['published']}] " if item.get("published") else ""
        src  = f"  ({item['source']})"   if item.get("source")    else ""
        lines.append(f"• {date}{item['title']}{src}")
        if item.get("snippet"):
            lines.append(f"  {item['snippet'][:250]}")
    return "\n".join(lines) if lines else "No recent news found."


def _format_financials(f: dict) -> str:
    parts = []
    for label, key, fmt in [
        ("Rev CAGR 3yr",  "revenue_cagr_3yr", "{:.1f}%"),
        ("PAT CAGR 3yr",  "pat_cagr_3yr",     "{:.1f}%"),
        ("Rev CAGR 5yr",  "revenue_cagr_5yr", "{:.1f}%"),
        ("ROE 5yr avg",   "roe_5yr_avg",       "{:.1f}%"),
        ("ROCE",          "roce",              "{:.1f}%"),
        ("Debt/Equity",   "debt_equity",       "{:.2f}x"),
        ("P/E",           "pe_ratio",          "{:.1f}"),
    ]:
        val = f.get(key)
        if val is not None:
            try:
                parts.append(f"{label}: {fmt.format(val)}")
            except (TypeError, ValueError):
                pass
    return " | ".join(parts) if parts else "Financial data limited"


# ── Fallback ──────────────────────────────────────────────────────────────────

def _empty(reason: str = "") -> dict:
    msg = reason or "Insufficient data"
    return {
        "management_tone":   "Unknown",
        "tone_reason":        msg,
        "key_positives":      [],
        "key_risks":          [],
        "recent_triggers":    msg,
        "overall_sentiment": "Neutral",
    }
