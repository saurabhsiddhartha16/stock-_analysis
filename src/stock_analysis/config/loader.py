"""Pydantic v2 models for all YAML config files. Validates at startup."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


# ── settings.yaml ────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    name: str
    version: str
    timezone: str = "Asia/Kolkata"
    run_time: str = "18:30"
    log_level: str = "INFO"
    log_dir: str = "logs"


class DataConfig(BaseModel):
    cache_dir: str = "data/cache"
    reports_dir: str = "data/reports"
    universe_dir: str = "data/universe"
    ohlcv_ttl_hours: int = 24
    fundamentals_yfinance_ttl_hours: int = 24
    fundamentals_screener_ttl_hours: int = 168
    news_ttl_hours: int = 4
    ai_analysis_ttl_hours: int = 24


class FetchingConfig(BaseModel):
    max_concurrent_requests: int = 10
    request_timeout_seconds: int = 30
    max_retries: int = 3
    retry_backoff_factor: float = 2.0


class AiConfig(BaseModel):
    enabled: bool = True
    gemini_model: str = "gemini-1.5-flash"
    gemini_api_key_env_var: str = "GEMINI_API_KEY"
    top_n_for_analysis: int = 20
    news_days_lookback: int = 30
    qualitative_ttl_hours: float = 48.0


class OutputConfig(BaseModel):
    html_enabled: bool = True
    csv_enabled: bool = True
    email_enabled: bool = True
    top_n_in_report: int = 50
    top_n_in_email: int = 15


class EmailConfig(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_user_env_var: str = "EMAIL_USER"
    smtp_pass_env_var: str = "EMAIL_PASSWORD"
    from_address: str
    to_addresses: list[str]
    subject_template: str = "NSE Daily Analysis — {date} — Top: {top_stocks}"


class ApisConfig(BaseModel):
    gemini_key_env_var: str = "GEMINI_API_KEY"


class Settings(BaseModel):
    app: AppConfig
    data: DataConfig
    fetching: FetchingConfig
    ai: AiConfig
    output: OutputConfig
    email: EmailConfig
    apis: ApisConfig


# ── universe.yaml ─────────────────────────────────────────────────────────────

class IndexShortcuts(BaseModel):
    nifty50: str = ""
    nifty200: str = ""
    nifty500: str = ""


class UniverseConfig(BaseModel):
    version: str = "1.0"
    source: str = "nse_equity_master"
    include_market_cap_tiers: list[str] = ["large_cap", "mid_cap", "small_cap"]
    include_sectors: list[str] = []
    exclude_sectors: list[str] = []
    always_include: list[str] = []
    always_exclude: list[str] = []
    index_shortcuts: IndexShortcuts = IndexShortcuts()
    limit_to_index: str | None = None
    max_stocks: int = 2000


# ── rules.yaml ────────────────────────────────────────────────────────────────

class Rule(BaseModel):
    id: str
    field: str
    op: str
    value: Any
    description: str = ""
    enabled: bool = True

    @field_validator("op")
    @classmethod
    def valid_op(cls, v: str) -> str:
        allowed = {"gt", "lt", "gte", "lte", "eq", "neq", "between", "in", "not_in"}
        if v not in allowed:
            raise ValueError(f"op must be one of {allowed}, got '{v}'")
        return v


class Screen(BaseModel):
    id: str
    name: str
    rules: list[Rule] = []


class RulesConfig(BaseModel):
    version: str = "1.0"
    rules: list[Rule] = []
    sector_overrides: dict[str, dict[str, Any]] = {}
    screens: list[Screen] = []


# ── scoring_weights.yaml ──────────────────────────────────────────────────────

class DefaultWeights(BaseModel):
    growth_score: float = 0.35
    momentum_score: float = 0.25
    quality_score: float = 0.30
    valuation_score: float = 0.20
    risk_score: float = -0.20


class ScoringWeightsConfig(BaseModel):
    version: str = "1.0"
    default_weights: DefaultWeights = DefaultWeights()
    growth_sub_weights: dict[str, float] = {}
    risk_sub_weights: dict[str, float] = {}
    quality_sub_weights: dict[str, float] = {}
    valuation_sub_weights: dict[str, float] = {}
    momentum_sub_weights: dict[str, float] = {}
    sector_overrides: dict[str, Any] = {}


# ── Loader ────────────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: Path = Path("config")) -> Settings:
    return Settings(**_load_yaml(config_dir / "settings.yaml"))


def load_universe(config_dir: Path = Path("config")) -> UniverseConfig:
    return UniverseConfig(**_load_yaml(config_dir / "universe.yaml"))


def load_rules(config_dir: Path = Path("config")) -> RulesConfig:
    return RulesConfig(**_load_yaml(config_dir / "rules.yaml"))


def load_scoring_weights(config_dir: Path = Path("config")) -> ScoringWeightsConfig:
    return ScoringWeightsConfig(**_load_yaml(config_dir / "scoring_weights.yaml"))
