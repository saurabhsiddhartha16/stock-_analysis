"""
Orchestrates qualitative analysis for top-ranked stocks:
  1. Fetch recent news via Google News RSS
  2. Synthesize via Gemini 1.5 Flash (free tier)
  3. Cache results (TTL configurable — default 48 hours)

Cost: $0 — runs entirely on Gemini free tier (1,500 req/day, 1M tokens/day).
"""
from __future__ import annotations

from loguru import logger

from stock_analysis.ai import gemini_client
from stock_analysis.ai.news_fetcher import fetch_news
from stock_analysis.data.cache import DiskCache


def run(
    symbols: list[str],
    stock_data: dict[str, dict],
    cache: DiskCache,
    top_n: int = 20,
    ttl_hours: float = 48.0,
    news_days: int = 30,
    api_key_env_var: str = "GEMINI_API_KEY",
) -> dict[str, dict]:
    """
    Run qualitative analysis for the top N ranked symbols.

    Args:
        symbols:         Ordered list of symbols (highest-ranked first).
        stock_data:      {symbol: {fundamentals, technicals, universe}}.
        cache:           DiskCache instance for caching results.
        top_n:           Analyse only the first top_n symbols.
        ttl_hours:       Cache TTL in hours (48h default = runs twice before refresh).
        news_days:       How many days back to fetch news.
        api_key_env_var: Environment variable name holding the Gemini API key.

    Returns:
        {symbol: qualitative_analysis_dict}
    """
    results: dict[str, dict] = {}
    targets     = symbols[:top_n]
    fresh_count = 0

    logger.info(f"Qualitative analysis: {len(targets)} stocks (top_n={top_n})")

    for i, symbol in enumerate(targets):
        # ── Cache hit ─────────────────────────────────────────────────────────
        cached = cache.get_json("qualitative", symbol)
        if cached is not None:
            results[symbol] = cached
            logger.debug(f"  Qualitative cached: {symbol}")
            continue

        # ── Fresh analysis ────────────────────────────────────────────────────
        data         = stock_data.get(symbol, {})
        fundamentals = data.get("fundamentals", {})
        company_name = fundamentals.get("company_name") or symbol

        logger.info(f"  [{i+1}/{len(targets)}] Analysing: {company_name} ({symbol})")

        # Step 1: fetch news
        news = fetch_news(company_name, symbol, days_lookback=news_days)

        # Step 2: synthesize
        analysis = gemini_client.synthesize(
            company_name    = company_name,
            symbol          = symbol,
            news_items      = news,
            fundamentals    = fundamentals,
            api_key_env_var = api_key_env_var,
        )

        # Step 3: cache
        cache.set_json("qualitative", symbol, analysis, ttl_hours)
        results[symbol] = analysis
        fresh_count += 1

    cached_count = len(targets) - fresh_count
    logger.info(
        f"  Qualitative done: {fresh_count} fresh synthesised, "
        f"{cached_count} served from cache"
    )
    return results
