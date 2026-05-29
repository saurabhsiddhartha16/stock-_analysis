"""Unit tests for scoring modules."""
from __future__ import annotations

import pytest

from stock_analysis.scoring import growth_score, momentum_score, quality_score, risk_score


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(**kwargs):
    """Build a fundamentals dict with all keys defaulting to None."""
    base = {
        "market_cap_cr": None, "pe_ratio": None, "pb_ratio": None,
        "roe_5yr_avg": None, "roe_ttm": None, "roce": None,
        "revenue_cagr_3yr": None, "pat_cagr_3yr": None, "eps_cagr_3yr": None,
        "debt_equity": None, "interest_coverage": None, "fcf_trailing_cr": None,
        "pat_ttm_cr": None, "cash_cr": None, "beta": None, "promoter_pledge_pct": None,
    }
    base.update(kwargs)
    return base


def _t(**kwargs):
    """Build a technicals dict."""
    base = {
        "RSI_14": None, "MACD": None, "MACD_signal": None, "MACD_hist": None,
        "price_vs_sma50_pct": None, "price_vs_sma200_pct": None,
        "pct_from_52w_high": None, "close": None, "volume": None,
    }
    base.update(kwargs)
    return base


# ── Growth score ──────────────────────────────────────────────────────────────

class TestGrowthScore:
    def test_returns_score_object(self):
        result = growth_score.compute(_f())
        assert hasattr(result, "value")
        assert hasattr(result, "sub_scores")

    def test_value_in_range(self):
        for cagr in [-20, 0, 10, 25, 50]:
            result = growth_score.compute(_f(revenue_cagr_3yr=cagr, pat_cagr_3yr=cagr))
            assert 0 <= result.value <= 100, f"Score out of range for CAGR={cagr}"

    def test_higher_cagr_higher_score(self):
        low = growth_score.compute(_f(revenue_cagr_3yr=5, pat_cagr_3yr=5))
        high = growth_score.compute(_f(revenue_cagr_3yr=30, pat_cagr_3yr=30))
        assert high.value > low.value

    def test_negative_cagr_scores_below_50(self):
        result = growth_score.compute(_f(revenue_cagr_3yr=-10, pat_cagr_3yr=-5))
        assert result.value < 50

    def test_missing_data_returns_neutral(self):
        result = growth_score.compute(_f())
        assert 40 <= result.value <= 65, "Missing data should give near-neutral score"

    def test_analyst_upgrade_boosts_score(self):
        base = growth_score.compute(_f(revenue_cagr_3yr=15), ai_signals={"analyst_revision_signal": 0})
        upgraded = growth_score.compute(_f(revenue_cagr_3yr=15), ai_signals={"analyst_revision_signal": 1})
        assert upgraded.value >= base.value

    def test_analyst_downgrade_lowers_score(self):
        base = growth_score.compute(_f(revenue_cagr_3yr=15), ai_signals={"analyst_revision_signal": 0})
        downgraded = growth_score.compute(_f(revenue_cagr_3yr=15), ai_signals={"analyst_revision_signal": -1})
        assert downgraded.value <= base.value


# ── Risk score ────────────────────────────────────────────────────────────────

class TestRiskScore:
    def test_value_in_range(self):
        for de in [0, 0.5, 1.0, 2.0, 5.0]:
            result = risk_score.compute(_f(debt_equity=de))
            assert 0 <= result.value <= 100

    def test_zero_debt_is_low_risk(self):
        result = risk_score.compute(_f(debt_equity=0, interest_coverage=20, beta=0.5))
        assert result.value < 40, "Zero debt should score low risk"

    def test_high_debt_is_high_risk(self):
        result = risk_score.compute(_f(debt_equity=5.0, interest_coverage=0.8, beta=1.8))
        assert result.value > 60, "High debt + low coverage should be high risk"

    def test_material_audit_raises_risk(self):
        no_issue = risk_score.compute(_f(), ai_signals={"auditor_qualification": "none"})
        material = risk_score.compute(_f(), ai_signals={"auditor_qualification": "material"})
        assert material.value > no_issue.value

    def test_high_pledge_raises_risk(self):
        low = risk_score.compute(_f(promoter_pledge_pct=0))
        high = risk_score.compute(_f(promoter_pledge_pct=60))
        assert high.value > low.value


# ── Momentum score ────────────────────────────────────────────────────────────

class TestMomentumScore:
    def test_value_in_range(self):
        for rsi in [20, 35, 50, 65, 80]:
            result = momentum_score.compute(_t(RSI_14=rsi))
            assert 0 <= result.value <= 100

    def test_above_sma_scores_higher(self):
        below = momentum_score.compute(_t(price_vs_sma200_pct=-15))
        above = momentum_score.compute(_t(price_vs_sma200_pct=15))
        assert above.value > below.value

    def test_rsi_oversold_low_score(self):
        oversold = momentum_score.compute(_t(RSI_14=25))
        neutral = momentum_score.compute(_t(RSI_14=55))
        assert neutral.value > oversold.value

    def test_bullish_macd_boosts_score(self):
        bearish = momentum_score.compute(_t(MACD=-1.0, MACD_signal=0.5, MACD_hist=-1.5))
        bullish = momentum_score.compute(_t(MACD=1.0, MACD_signal=0.5, MACD_hist=0.5))
        assert bullish.value > bearish.value


# ── Quality score ─────────────────────────────────────────────────────────────

class TestQualityScore:
    def test_value_in_range(self):
        result = quality_score.compute(_f(roe_5yr_avg=18, roce=22))
        assert 0 <= result.value <= 100

    def test_high_roe_roce_scores_well(self):
        low = quality_score.compute(_f(roe_5yr_avg=5, roce=8))
        high = quality_score.compute(_f(roe_5yr_avg=25, roce=30))
        assert high.value > low.value

    def test_negative_roe_low_score(self):
        result = quality_score.compute(_f(roe_5yr_avg=-5))
        assert result.value < 45

    def test_good_fcf_conversion_boosts_score(self):
        low = quality_score.compute(_f(fcf_trailing_cr=20, pat_ttm_cr=100))   # 20% conversion
        high = quality_score.compute(_f(fcf_trailing_cr=100, pat_ttm_cr=100)) # 100% conversion
        assert high.value > low.value

    def test_missing_data_neutral(self):
        result = quality_score.compute(_f())
        assert 30 <= result.value <= 70
