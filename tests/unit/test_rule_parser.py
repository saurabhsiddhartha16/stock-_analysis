"""Unit tests for screening/rule_parser.py and screening/engine.py."""
from __future__ import annotations

import pytest

from stock_analysis.config.loader import Rule
from stock_analysis.screening.rule_parser import _apply_op, compile_rules


# ── _apply_op ────────────────────────────────────────────────────────────────

class TestApplyOp:
    def test_gt(self):
        assert _apply_op(10, "gt", 5) is True
        assert _apply_op(5, "gt", 5) is False

    def test_gte(self):
        assert _apply_op(5, "gte", 5) is True
        assert _apply_op(4, "gte", 5) is False

    def test_lt(self):
        assert _apply_op(3, "lt", 5) is True
        assert _apply_op(5, "lt", 5) is False

    def test_lte(self):
        assert _apply_op(5, "lte", 5) is True
        assert _apply_op(6, "lte", 5) is False

    def test_eq_numeric(self):
        assert _apply_op(5, "eq", 5) is True
        assert _apply_op(6, "eq", 5) is False

    def test_eq_string_case_insensitive(self):
        assert _apply_op("BFSI", "eq", "bfsi") is True
        assert _apply_op("IT", "eq", "BFSI") is False

    def test_neq(self):
        assert _apply_op("IT", "neq", "BFSI") is True
        assert _apply_op("IT", "neq", "IT") is False

    def test_between(self):
        assert _apply_op(5, "between", [3, 7]) is True
        assert _apply_op(5, "between", [5, 10]) is True
        assert _apply_op(2, "between", [3, 7]) is False

    def test_in(self):
        assert _apply_op("BFSI", "in", ["BFSI", "IT"]) is True
        assert _apply_op("Healthcare", "in", ["BFSI", "IT"]) is False

    def test_not_in(self):
        assert _apply_op("Healthcare", "not_in", ["BFSI", "IT"]) is True
        assert _apply_op("BFSI", "not_in", ["BFSI", "IT"]) is False

    def test_unknown_op_passes(self):
        # Unknown op should not block a stock
        assert _apply_op(5, "unknown_op", 3) is True

    def test_type_mismatch_passes(self):
        # Can't compare string to float — should not exclude
        assert _apply_op("abc", "gt", 5) is True


# ── compile_rules ─────────────────────────────────────────────────────────────

class TestCompileRules:
    def _make_rule(self, id, field, op, value, enabled=True):
        return Rule(id=id, field=field, op=op, value=value, enabled=enabled)

    def test_disabled_rule_excluded(self):
        rules = [self._make_rule("r1", "fundamentals.pe_ratio", "lte", 50, enabled=False)]
        compiled = compile_rules(rules)
        assert len(compiled) == 0

    def test_enabled_rule_included(self):
        rules = [self._make_rule("r1", "fundamentals.pe_ratio", "lte", 50, enabled=True)]
        compiled = compile_rules(rules)
        assert len(compiled) == 1

    def test_evaluator_passes_when_value_ok(self):
        rules = [self._make_rule("pe", "fundamentals.pe_ratio", "lte", 50)]
        _, evaluator = compile_rules(rules)[0]
        stock = {"fundamentals": {"pe_ratio": 30.0}}
        assert evaluator(stock) is True

    def test_evaluator_fails_when_value_exceeds(self):
        rules = [self._make_rule("pe", "fundamentals.pe_ratio", "lte", 50)]
        _, evaluator = compile_rules(rules)[0]
        stock = {"fundamentals": {"pe_ratio": 80.0}}
        assert evaluator(stock) is False

    def test_missing_value_passes(self):
        """Missing data should not exclude a stock."""
        rules = [self._make_rule("pe", "fundamentals.pe_ratio", "lte", 50)]
        _, evaluator = compile_rules(rules)[0]
        stock = {"fundamentals": {}}  # no pe_ratio key
        assert evaluator(stock) is True

    def test_nested_field_access(self):
        rules = [self._make_rule("rsi", "technicals.RSI_14", "lte", 70)]
        _, evaluator = compile_rules(rules)[0]
        assert evaluator({"technicals": {"RSI_14": 60}}) is True
        assert evaluator({"technicals": {"RSI_14": 80}}) is False

    def test_sector_not_in(self):
        rules = [self._make_rule("sector", "universe.sector", "not_in", ["Gambling"])]
        _, evaluator = compile_rules(rules)[0]
        assert evaluator({"universe": {"sector": "IT"}}) is True
        assert evaluator({"universe": {"sector": "Gambling"}}) is False

    def test_multiple_rules_all_must_pass(self):
        """Compile two rules and verify both are independently callable."""
        rules = [
            self._make_rule("pe", "fundamentals.pe_ratio", "lte", 50),
            self._make_rule("roe", "fundamentals.roe_5yr_avg", "gte", 12),
        ]
        compiled = compile_rules(rules)
        assert len(compiled) == 2
        stock_good = {"fundamentals": {"pe_ratio": 30, "roe_5yr_avg": 15}}
        for _, ev in compiled:
            assert ev(stock_good) is True

        stock_bad_roe = {"fundamentals": {"pe_ratio": 30, "roe_5yr_avg": 5}}
        results = [ev(stock_bad_roe) for _, ev in compiled]
        assert results == [True, False]  # PE passes, ROE fails
