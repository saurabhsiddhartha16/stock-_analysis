"""
Fetches recent news for NSE stocks via Google News RSS.
Uses feedparser — no API key required, completely free.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
from loguru import logger

_GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)
_REQUEST_DELAY = 1.2   # seconds between RSS calls — polite rate limit


def fetch_news(
    company_name: str,
    symbol: str,
    days_lookback: int = 30,
    max_articles: int = 6,
) -> list[dict]:
    """
    Fetch recent news for a stock from Google News RSS.

    Returns a list of dicts:
      {title, snippet, published (str "DD Mon YYYY"), source}
    """
    cutoff   = datetime.now(timezone.utc) - timedelta(days=days_lookback)
    articles: list[dict] = []
    seen_titles: set[str] = set()

    # Two queries: symbol-focused first, company-name second
    queries = [
        f"{symbol} NSE results",
        f'"{company_name}" quarterly results India',
    ]

    for query in queries:
        if len(articles) >= max_articles:
            break
        try:
            url  = _GOOGLE_NEWS_RSS.format(query=query.replace(" ", "+"))
            feed = feedparser.parse(url)
            time.sleep(_REQUEST_DELAY)

            for entry in feed.entries:
                if len(articles) >= max_articles:
                    break

                # Filter by date
                pub_str = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    pub_str = pub_dt.strftime("%d %b %Y")

                title   = entry.get("title", "").strip()
                snippet = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()[:400]
                source  = getattr(getattr(entry, "source", None), "title", "")

                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                articles.append({
                    "title":     title,
                    "snippet":   snippet,
                    "published": pub_str,
                    "source":    source,
                })

        except Exception as e:
            logger.debug(f"News RSS failed for {symbol} | query='{query}': {e}")

    logger.debug(f"News fetched for {symbol}: {len(articles)} articles")
    return articles
