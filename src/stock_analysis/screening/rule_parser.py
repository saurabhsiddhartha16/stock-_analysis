"""Parses the rules.yaml DSL into callable evaluators."""
from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from stock_analysis.config.loader import Rule


def compile_rules(rules: list[Rule]) -> list[tuple[Rule, Callable[[dict], bool]]]:
    """
    Compile enabled rules into (rule, evaluator_fn) pairs.
    evaluator_fn(stock_data: dict) -> bool
    """
    compiled = []
    for rule in rules:
        if not rule.enabled:
            continue
        try:
            fn = _build_evaluator(rule)
            compiled.append((rule, fn))
        except Exception as e:
            logger.warning(f"Could not compile rule '{rule.id}': {e} — skipping")
    return compiled


def _build_evaluator(rule: Rule) -> Callable[[dict], bool]:
    """Return a function that extracts the field value and applies the operator."""
    field_path = rule.field.split(".")  # e.g. ["fundamentals", "pe_ratio"]
    op = rule.op
    threshold = rule.value

    def evaluate(stock_data: dict) -> bool:
        value = _get_nested(stock_data, field_path)
        if value is None:
            # Missing data: pass the rule (don't exclude stock due to data gap)
            return True
        return _apply_op(value, op, threshold)

    return evaluate


def _get_nested(data: dict, path: list[str]) -> Any:
    """Traverse dot-notation path through nested dict. Returns None if missing."""
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def _apply_op(value: Any, op: str, threshold: Any) -> bool:
    """Apply a comparison operator. Handles numeric and string/list types."""
    try:
        if op == "gt":
            return float(value) > float(threshold)
        elif op == "gte":
            return float(value) >= float(threshold)
        elif op == "lt":
            return float(value) < float(threshold)
        elif op == "lte":
            return float(value) <= float(threshold)
        elif op == "eq":
            return str(value).lower() == str(threshold).lower()
        elif op == "neq":
            return str(value).lower() != str(threshold).lower()
        elif op == "between":
            lo, hi = float(threshold[0]), float(threshold[1])
            return lo <= float(value) <= hi
        elif op == "in":
            return str(value).lower() in [str(t).lower() for t in threshold]
        elif op == "not_in":
            return str(value).lower() not in [str(t).lower() for t in threshold]
        else:
            logger.warning(f"Unknown operator '{op}' — treating as pass")
            return True
    except (TypeError, ValueError, IndexError) as e:
        logger.debug(f"Rule eval error (op={op}, value={value}, threshold={threshold}): {e}")
        return True  # Data type mismatch → don't exclude
