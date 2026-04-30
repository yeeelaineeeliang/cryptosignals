"""Typed environment config via pydantic-settings.

Loaded once at startup; passed around explicitly. No global mutable state.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_service_role_key: str

    # Coinbase
    coinbase_base_url: str = "https://api.exchange.coinbase.com"

    # Pairs + granularity
    watched_pairs: str = "BTC-USD,ETH-USD"
    candle_granularity: int = 300  # seconds per bar (5-min default)

    # Cadences (seconds unless noted)
    poll_interval_seconds: int = 5
    candle_interval_seconds: int = 60
    inference_interval_seconds: int = 30
    evaluate_interval_minutes: int = 60
    refit_interval_hours: int = 6
    rolling_train_days: int = 30

    # Feature flags
    enable_paper_trading: bool = True
    enable_llm_features: bool = False

    # Prediction horizon (bars ahead the model targets)
    prediction_bars_ahead: int = 3        # 3 × 5min = 15-min cumulative return

    # VIF elimination tuning
    # Widened from 0.005 → 0.01 to prevent soft-zone boundary features
    # (f_momentum_10, f_rsi_14) from flipping in/out across 30-day windows.
    # See CLAUDE.md § VIF tuning for the full rationale.
    soft_osr2_tolerance: float = 0.01
    vif_hard_threshold: float = 10.0  # override with VIF_HARD_THRESHOLD env var

    # Optimization loop
    optimize_interval_minutes: int = 60   # runs after every evaluate cycle

    # Observability
    log_level: str = "INFO"
    build_sha: str = Field(default="", description="Railway auto-injects this.")

    @property
    def pairs(self) -> list[str]:
        return [p.strip() for p in self.watched_pairs.split(",") if p.strip()]
