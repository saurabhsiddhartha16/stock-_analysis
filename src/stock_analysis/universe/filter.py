"""Applies universe.yaml inclusion/exclusion rules to the raw symbol list."""
from __future__ import annotations

import pandas as pd
from loguru import logger

from stock_analysis.config.loader import UniverseConfig

_MARKET_CAP_TIERS = {
    "large_cap": (20_000, float("inf")),
    "mid_cap": (5_000, 20_000),
    "small_cap": (500, 5_000),
    "micro_cap": (0, 500),
}


def apply_filters(df: pd.DataFrame, cfg: UniverseConfig) -> pd.DataFrame:
    """
    Filter a universe DataFrame according to universe.yaml rules.

    Args:
        df: Raw universe DataFrame with columns: symbol, name, sector, industry.
            Optionally includes market_cap_cr for cap-tier filtering.
        cfg: Loaded UniverseConfig.

    Returns:
        Filtered DataFrame, capped at cfg.max_stocks rows.
    """
    original_count = len(df)

    # Always-exclude takes highest priority
    if cfg.always_exclude:
        excluded = set(s.upper() for s in cfg.always_exclude)
        df = df[~df["symbol"].isin(excluded)]
        logger.debug(f"After always_exclude: {len(df)} stocks")

    # Sector exclusions
    if cfg.exclude_sectors:
        excluded_sectors = set(s.lower() for s in cfg.exclude_sectors)
        df = df[~df["sector"].str.lower().isin(excluded_sectors)]
        logger.debug(f"After sector exclusions: {len(df)} stocks")

    # Sector inclusions (if specified — empty list means include all)
    if cfg.include_sectors:
        included_sectors = set(s.lower() for s in cfg.include_sectors)
        always_in = set(s.upper() for s in cfg.always_include)
        df = df[
            df["sector"].str.lower().isin(included_sectors) | df["symbol"].isin(always_in)
        ]
        logger.debug(f"After sector inclusions: {len(df)} stocks")

    # Market-cap tier filter (only applies if market_cap_cr column exists)
    if "market_cap_cr" in df.columns and cfg.include_market_cap_tiers:
        low, high = _combined_cap_range(cfg.include_market_cap_tiers)
        always_in = set(s.upper() for s in cfg.always_include)
        df = df[
            (df["market_cap_cr"].between(low, high)) | df["symbol"].isin(always_in)
        ]
        logger.debug(f"After market-cap filter: {len(df)} stocks")

    # Always-include: add back any that were removed
    if cfg.always_include:
        always_in_symbols = set(s.upper() for s in cfg.always_include)
        missing = always_in_symbols - set(df["symbol"])
        if missing:
            logger.warning(f"always_include symbols not in universe: {missing}")

    # Cap total
    if len(df) > cfg.max_stocks:
        df = df.iloc[: cfg.max_stocks]
        logger.warning(f"Universe capped at max_stocks={cfg.max_stocks}")

    logger.info(f"Universe filtered: {original_count} → {len(df)} stocks")
    return df.reset_index(drop=True)


def _combined_cap_range(tiers: list[str]) -> tuple[float, float]:
    """Return (min, max) market cap range covering all requested tiers."""
    low = float("inf")
    high = float("-inf")
    for tier in tiers:
        if tier not in _MARKET_CAP_TIERS:
            logger.warning(f"Unknown market cap tier '{tier}' — skipping")
            continue
        t_low, t_high = _MARKET_CAP_TIERS[tier]
        low = min(low, t_low)
        high = max(high, t_high)
    if low == float("inf"):
        return (0, float("inf"))
    return (low, high)
