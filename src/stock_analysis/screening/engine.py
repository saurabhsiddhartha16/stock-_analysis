"""Screening engine — applies compiled rules to the full stock universe."""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from stock_analysis.config.loader import Rule, RulesConfig
from stock_analysis.screening.rule_parser import compile_rules


@dataclass
class ScreenResult:
    symbol: str
    passed: bool
    passed_rules: list[str] = field(default_factory=list)
    failed_rules: list[str] = field(default_factory=list)
    rule_details: dict[str, bool] = field(default_factory=dict)


def run_screen(
    symbols: list[str],
    stock_data: dict[str, dict],  # {symbol: {fundamentals: {...}, technicals: {...}, universe: {...}}}
    rules_cfg: RulesConfig,
) -> list[ScreenResult]:
    """
    Evaluate all enabled rules against each stock.

    Args:
        symbols:    Ordered list of symbols to evaluate.
        stock_data: Full data dict keyed by symbol.
        rules_cfg:  Loaded RulesConfig (rules + sector_overrides).

    Returns:
        List of ScreenResult for all symbols (passed and failed).
        Sorted: passing stocks first, then by symbol name.
    """
    base_rules = rules_cfg.rules
    compiled_base = compile_rules(base_rules)
    sector_override_cache: dict[str, list] = {}

    results: list[ScreenResult] = []
    pass_count = 0

    for symbol in symbols:
        data = stock_data.get(symbol, {})
        sector = _get_sector(data)
        compiled = _get_compiled_for_sector(
            sector, base_rules, rules_cfg.sector_overrides, sector_override_cache, compiled_base
        )

        result = _evaluate_stock(symbol, data, compiled)
        results.append(result)
        if result.passed:
            pass_count += 1

    results.sort(key=lambda r: (not r.passed, r.symbol))
    logger.info(f"Screening: {pass_count}/{len(symbols)} stocks passed all rules")
    return results


def _evaluate_stock(
    symbol: str,
    data: dict,
    compiled_rules: list,
) -> ScreenResult:
    passed_rules = []
    failed_rules = []
    rule_details: dict[str, bool] = {}

    for rule, evaluator in compiled_rules:
        try:
            ok = evaluator(data)
        except Exception as e:
            logger.debug(f"Rule '{rule.id}' eval error for {symbol}: {e}")
            ok = True  # error → don't exclude
        rule_details[rule.id] = ok
        if ok:
            passed_rules.append(rule.id)
        else:
            failed_rules.append(rule.id)

    return ScreenResult(
        symbol=symbol,
        passed=len(failed_rules) == 0,
        passed_rules=passed_rules,
        failed_rules=failed_rules,
        rule_details=rule_details,
    )


def _get_sector(data: dict) -> str:
    return (
        data.get("universe", {}).get("sector", "")
        or data.get("fundamentals", {}).get("sector_yf", "")
        or ""
    ).strip()


def _get_compiled_for_sector(
    sector: str,
    base_rules: list[Rule],
    sector_overrides: dict,
    cache: dict[str, list],
    default_compiled: list,
) -> list:
    """Apply sector overrides to rules and return compiled rule list."""
    if not sector or sector not in sector_overrides:
        return default_compiled

    if sector in cache:
        return cache[sector]

    overrides = sector_overrides[sector]
    patched_rules = []
    for rule in base_rules:
        if rule.id in overrides:
            override = overrides[rule.id]
            # Build a patched Rule with overridden fields
            patched = rule.model_copy(update={
                k: v for k, v in override.items() if k in ("value", "enabled", "op")
            })
            patched_rules.append(patched)
        else:
            patched_rules.append(rule)

    compiled = compile_rules(patched_rules)
    cache[sector] = compiled
    return compiled


def get_passing_symbols(results: list[ScreenResult]) -> list[str]:
    """Extract symbols that passed all rules, in order."""
    return [r.symbol for r in results if r.passed]
