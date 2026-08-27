"""Pairs trading: a fundamentally different shape from the single-ticker StrategySpec
(strategy_research/strategy_spec.py) used by the other three archetypes — it needs two
tickers and a spread relationship, not a set of indicator conditions on one price series.
This module owns that math (hedge ratio, spread, z-score, cointegration test);
backtester/pairs_engine.py owns the simulation.

Cointegration matters here the way overfit_guard.py matters for single-ticker strategies
(CLAUDE.md Guardrails): trading two tickers that just happen to have moved together in a
backtest window, without a real statistical relationship, is curve-fitting dressed up as a
strategy. quant_engine/validation/pairs_validator.py rejects any pair that fails the
Engle-Granger cointegration test before it can be considered "validated."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

DEFAULT_LOOKBACK_PERIOD = 30
DEFAULT_ENTRY_ZSCORE = 2.0
DEFAULT_EXIT_ZSCORE = 0.5


class PairsSpecError(ValueError):
    """Raised when a candidate pairs strategy fails schema validation."""


@dataclass(frozen=True)
class PairsSpec:
    ticker_a: str
    ticker_b: str
    lookback_period: int = DEFAULT_LOOKBACK_PERIOD
    entry_zscore: float = DEFAULT_ENTRY_ZSCORE
    exit_zscore: float = DEFAULT_EXIT_ZSCORE
    name: str = ""
    source_url: str = "internal://strategies/pairs_trading/classic_pairs"
    extraction_method: str = "rule"
    confidence: float = 1.0
    raw_excerpt: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate(self) -> None:
        if self.ticker_a == self.ticker_b:
            raise PairsSpecError("ticker_a and ticker_b must differ")
        if self.lookback_period < 2:
            raise PairsSpecError("lookback_period must be >= 2")
        if self.entry_zscore <= self.exit_zscore:
            raise PairsSpecError("entry_zscore must be greater than exit_zscore")
        if self.exit_zscore < 0:
            raise PairsSpecError("exit_zscore must be >= 0")

    def to_dict(self) -> dict:
        return {
            "kind": "pairs",  # distinguishes from StrategySpec records in the shared registry
            "name": self.name or f"pairs_{self.ticker_a}_{self.ticker_b}",
            "ticker_a": self.ticker_a,
            "ticker_b": self.ticker_b,
            "lookback_period": self.lookback_period,
            "entry_zscore": self.entry_zscore,
            "exit_zscore": self.exit_zscore,
            "source_url": self.source_url,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "raw_excerpt": self.raw_excerpt,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PairsSpec":
        return cls(
            ticker_a=data["ticker_a"],
            ticker_b=data["ticker_b"],
            lookback_period=data.get("lookback_period", DEFAULT_LOOKBACK_PERIOD),
            entry_zscore=data.get("entry_zscore", DEFAULT_ENTRY_ZSCORE),
            exit_zscore=data.get("exit_zscore", DEFAULT_EXIT_ZSCORE),
            name=data.get("name", ""),
            source_url=data.get("source_url", ""),
            extraction_method=data.get("extraction_method", "rule"),
            confidence=data.get("confidence", 1.0),
            raw_excerpt=data.get("raw_excerpt", ""),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        )


def build_pairs_spec(ticker_a: str, ticker_b: str, **overrides) -> PairsSpec:
    # PairsSpec's class-level source_url default is generic (dataclass defaults can't
    # reference sibling fields) — every pair needs its own, or the registry's
    # dedup-by-source_url would treat a second configured pair as a duplicate of the first.
    overrides.setdefault(
        "source_url", f"internal://strategies/pairs_trading/classic_pairs/{ticker_a}_{ticker_b}"
    )
    spec = PairsSpec(ticker_a=ticker_a, ticker_b=ticker_b, **overrides)
    spec.validate()
    return spec


def align_price_series(price_a: pd.Series, price_b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Inner-joins two price series on their date index — different tickers can have
    slightly different trading-halt/listing histories, and a spread needs matching dates.
    """
    combined = pd.concat([price_a.rename("a"), price_b.rename("b")], axis=1, join="inner").dropna()
    return combined["a"], combined["b"]


def check_cointegration(price_a: pd.Series, price_b: pd.Series) -> float:
    """Engle-Granger cointegration test p-value. Callers should reject the pair if this is
    >= their significance threshold — see module docstring.
    """
    _, p_value, _ = coint(price_a, price_b)
    return float(p_value)


def compute_hedge_ratio(price_a: pd.Series, price_b: pd.Series) -> float:
    """OLS hedge ratio: price_a ~= hedge_ratio * price_b (+ intercept)."""
    slope, _ = np.polyfit(price_b, price_a, 1)
    return float(slope)


def compute_spread(price_a: pd.Series, price_b: pd.Series, hedge_ratio: float) -> pd.Series:
    return price_a - hedge_ratio * price_b


def compute_zscore(spread: pd.Series, lookback: int) -> pd.Series:
    rolling_mean = spread.rolling(lookback).mean()
    rolling_std = spread.rolling(lookback).std()
    return (spread - rolling_mean) / rolling_std
