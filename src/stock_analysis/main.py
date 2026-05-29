"""
Main orchestrator for the NSE daily stock analysis agent.

Stages (run sequentially, resumable via run-state file):
  UNIVERSE          → fetch + filter stock universe
  DATA_INGESTION    → OHLCV + technicals + fundamentals
  SCREENING         → apply rules.yaml filters
  NUMERICAL_SCORING → growth / momentum / quality / risk scores + CSV output
  AI_ANALYSIS       → filing analysis + news sentiment + thesis (Phase 3)
  OUTPUT            → HTML report + email (Phase 4)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Load .env from project root (two levels up from src/stock_analysis/)
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from stock_analysis.config.loader import (
    load_rules,
    load_scoring_weights,
    load_settings,
    load_universe,
)
from stock_analysis.data.cache import DiskCache
from stock_analysis.data.fundamentals import fetch_fundamentals
from stock_analysis.data.ohlcv import fetch_ohlcv
from stock_analysis.data.technicals import get_latest_indicators
from stock_analysis.output.csv_export import export as export_csv
from stock_analysis.output.email_digest import send as send_email
from stock_analysis.output.html_report import render as render_html
from stock_analysis.scoring.composite import StockScore, score_all
from stock_analysis.screening.engine import get_passing_symbols, run_screen, run_screens
from stock_analysis.universe.fetcher import fetch_universe, load_cached_universe
from stock_analysis.universe.filter import apply_filters
from stock_analysis.utils.logging_config import setup_logging

_CONFIG_DIR = Path("config")


def _load_run_state(path: Path) -> dict:
    if path.exists():
        with path.open() as f:
            return json.load(f)
    return {"completed_stages": []}


def _save_run_state(path: Path, state: dict) -> None:
    with path.open("w") as f:
        json.dump(state, f)


def run(run_date: str, mode: str = "full", resume: bool = True) -> None:
    settings = load_settings(_CONFIG_DIR)
    universe_cfg = load_universe(_CONFIG_DIR)
    rules_cfg = load_rules(_CONFIG_DIR)
    weights_cfg = load_scoring_weights(_CONFIG_DIR)

    setup_logging(
        log_dir=Path(settings.app.log_dir),
        log_level=settings.app.log_level,
        run_date=run_date,
    )

    cache = DiskCache(Path(settings.data.cache_dir))
    reports_dir = Path(settings.data.reports_dir)
    state_path = Path(settings.data.cache_dir) / f"run_state_{run_date}.json"
    state = _load_run_state(state_path) if resume else {"completed_stages": []}
    completed = set(state["completed_stages"])

    logger.info(f"=== NSE Analysis | date={run_date} | mode={mode} ===")

    # ── Stage 1: Universe ─────────────────────────────────────────────────────
    if "UNIVERSE" not in completed:
        logger.info("▶ Stage 1: UNIVERSE")
        universe_dir = Path(settings.data.universe_dir)
        try:
            raw_universe = fetch_universe(universe_cfg, universe_dir, config_dir=_CONFIG_DIR)
        except Exception as e:
            logger.warning(f"Live fetch failed ({e}); using cached universe")
            raw_universe = load_cached_universe(universe_dir, config_dir=_CONFIG_DIR)
        universe_df = apply_filters(raw_universe, universe_cfg)
        symbols = universe_df["symbol"].tolist()
        universe_meta = universe_df.set_index("symbol").to_dict("index")
        cache.set_json("run", f"universe_{run_date}", symbols, ttl_hours=48)
        cache.set_json("run", f"universe_meta_{run_date}", universe_meta, ttl_hours=48)
        completed.add("UNIVERSE")
        _save_run_state(state_path, {"completed_stages": list(completed)})
        logger.info(f"  ✓ {len(symbols)} stocks in universe")
    else:
        symbols = cache.get_json("run", f"universe_{run_date}") or []
        universe_meta = cache.get_json("run", f"universe_meta_{run_date}") or {}
        logger.info(f"  ✓ Universe (cached): {len(symbols)} stocks")

    if mode == "universe-only":
        return

    # ── Stage 2: Data Ingestion ────────────────────────────────────────────────
    if "DATA_INGESTION" not in completed:
        logger.info("▶ Stage 2: DATA_INGESTION")

        ohlcv_data = fetch_ohlcv(
            symbols, cache, ttl_hours=settings.data.ohlcv_ttl_hours
        )
        logger.info(f"  OHLCV: {len(ohlcv_data)}/{len(symbols)} symbols")

        tech_data: dict[str, dict] = {
            sym: get_latest_indicators(df) for sym, df in ohlcv_data.items()
        }
        cache.set_json("run", f"technicals_{run_date}", tech_data, ttl_hours=24)

        fund_data = fetch_fundamentals(
            symbols,
            cache,
            yf_ttl_hours=settings.data.fundamentals_yfinance_ttl_hours,
            screener_ttl_hours=settings.data.fundamentals_screener_ttl_hours,
        )
        logger.info(f"  Fundamentals: {len(fund_data)} symbols")

        completed.add("DATA_INGESTION")
        _save_run_state(state_path, {"completed_stages": list(completed)})
        logger.info(f"  ✓ Data ingestion complete")
    else:
        tech_data = cache.get_json("run", f"technicals_{run_date}") or {}
        fund_data = {}
        for sym in symbols:
            fund_data[sym] = cache.get_json("fundamentals", sym) or {}
        logger.info(f"  ✓ Data (cached): {len(tech_data)} stocks with technicals")

    # Build unified stock_data dict for screening + scoring
    stock_data: dict[str, dict] = {
        sym: {
            "fundamentals": fund_data.get(sym, {}),
            "technicals": tech_data.get(sym, {}),
            "universe": universe_meta.get(sym, {}),
        }
        for sym in symbols
    }

    if mode == "data-only":
        return

    # ── Stage 3: Screening ────────────────────────────────────────────────────
    if "SCREENING" not in completed:
        logger.info("▶ Stage 3: SCREENING")
        screen_results = run_screen(symbols, stock_data, rules_cfg)
        passing = get_passing_symbols(screen_results)
        cache.set_json("run", f"screened_{run_date}", passing, ttl_hours=24)
        completed.add("SCREENING")
        _save_run_state(state_path, {"completed_stages": list(completed)})
        logger.info(f"  ✓ {len(passing)}/{len(symbols)} stocks passed screening")
    else:
        passing = cache.get_json("run", f"screened_{run_date}") or []
        logger.info(f"  ✓ Screening (cached): {len(passing)} passed")

    if mode == "universe-only":
        return

    # ── Stage 4: Numerical Scoring ────────────────────────────────────────────
    if "NUMERICAL_SCORING" not in completed:
        logger.info("▶ Stage 4: NUMERICAL_SCORING")

        # Compute Nifty 50 3-month return for relative strength
        nifty_3m = _get_nifty_3m_return(cache)

        ranked = score_all(
            symbols=passing,
            stock_data=stock_data,
            weights_cfg=weights_cfg,
            nifty_return_3m=nifty_3m,
        )

        # Persist scores (store full fields for cache-resume reconstruction)
        scores_payload = [
            {
                "symbol": s.symbol,
                "rank": s.rank,
                "composite": s.composite,
                "growth": s.growth,
                "momentum": s.momentum,
                "quality": s.quality,
                "valuation": s.valuation,
                "risk": s.risk,
                "sub_scores": s.sub_scores,
                "explanations": s.explanations,
            }
            for s in ranked
        ]
        cache.set_json("run", f"scores_{run_date}", scores_payload, ttl_hours=24)

        # Run named screens across ALL symbols (not just screened subset)
        screen_results = run_screens(symbols, stock_data, rules_cfg)
        cache.set_json("run", f"screen_sections_{run_date}", screen_results, ttl_hours=24)

        # Export CSV immediately
        csv_path: Path | None = None
        if settings.output.csv_enabled:
            csv_path = export_csv(ranked, stock_data, reports_dir, run_date)
            logger.info(f"  CSV: {csv_path}")

        completed.add("NUMERICAL_SCORING")
        _save_run_state(state_path, {"completed_stages": list(completed)})

        top5 = ranked[:5]
        logger.info(
            "  ✓ Top 5: " +
            ", ".join(f"{s.symbol} ({s.composite:.1f})" for s in top5)
        )
    else:
        scores_payload = cache.get_json("run", f"scores_{run_date}") or []
        ranked = _reconstruct_scores(scores_payload)
        csv_path = reports_dir / "csv" / f"{run_date}.csv"
        if not csv_path.exists():
            csv_path = None
        screen_results = cache.get_json("run", f"screen_sections_{run_date}") or []
        logger.info(f"  ✓ Scoring (cached): {len(ranked)} stocks ranked")

    if mode == "screen":
        logger.info("Mode=screen: stopping after scoring.")
        return

    # ── Stage 5: Output ───────────────────────────────────────────────────────
    if "OUTPUT" not in completed:
        logger.info("▶ Stage 5: OUTPUT")

        templates_dir = Path(__file__).resolve().parent.parent.parent.parent / "templates"
        if not templates_dir.exists():
            templates_dir = Path("templates")

        if settings.output.html_enabled and ranked:
            html_path = render_html(
                scores=ranked,
                stock_data=stock_data,
                total_universe=len(symbols),
                reports_dir=reports_dir,
                templates_dir=templates_dir,
                run_date=run_date,
                card_limit=settings.output.top_n_in_report,
                screen_results=screen_results,
            )
            logger.info(f"  HTML: {html_path}")

        if settings.output.email_enabled and ranked:
            send_email(
                scores=ranked,
                stock_data=stock_data,
                csv_path=csv_path,
                email_cfg=settings.email,
                run_date=run_date,
                top_n=settings.output.top_n_in_email,
                screen_results=screen_results,
            )

        completed.add("OUTPUT")
        _save_run_state(state_path, {"completed_stages": list(completed)})

    logger.info("=== Run complete ===")


def _reconstruct_scores(payload: list[dict]) -> list[StockScore]:
    """Rebuild StockScore list from cached scores_payload."""
    scores = []
    for p in payload:
        scores.append(StockScore(
            symbol=p["symbol"],
            composite=p["composite"],
            growth=p.get("growth", 0.0),
            momentum=p.get("momentum", 0.0),
            quality=p.get("quality", 0.0),
            valuation=p.get("valuation", 0.0),
            risk=p.get("risk", 0.0),
            sub_scores=p.get("sub_scores", {}),
            explanations=p.get("explanations", {}),
            rank=p.get("rank", 0),
        ))
    return scores


def _get_nifty_3m_return(cache: DiskCache) -> float | None:
    """Fetch Nifty 50 3-month return for relative strength calculation."""
    try:
        import yfinance as yf
        nifty = yf.download("^NSEI", period="6mo", interval="1d",
                            auto_adjust=True, progress=False)
        if nifty is not None and not nifty.empty and len(nifty) >= 63:
            close = nifty["Close"]
            ret = float((close.iloc[-1] / close.iloc[-63] - 1) * 100)
            return round(ret, 2)
    except Exception as e:
        logger.debug(f"Nifty 3m return fetch failed: {e}")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="NSE Stock Analysis Agent")
    parser.add_argument(
        "--date", default=date.today().isoformat(),
        help="Run date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "data-only", "universe-only", "screen"],
        default="full",
        help="Pipeline mode",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Ignore saved run state and start fresh",
    )
    args = parser.parse_args()

    try:
        run(run_date=args.date, mode=args.mode, resume=not args.no_resume)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Run failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
