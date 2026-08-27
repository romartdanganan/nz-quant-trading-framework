"""Structured strategy schema produced by the discovery pipeline. Both rule_extractor.py
and gemini_client.py (via nl_to_rules.py) must produce a schema-validated StrategySpec
before a candidate can reach the strategy registry — nothing bypasses validate().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Archetype(str, Enum):
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    PAIRS_TRADING = "pairs_trading"
    BREAKOUT = "breakout"


class Indicator(str, Enum):
    RSI = "RSI"
    MACD = "MACD"
    BOLLINGER_BANDS = "BOLLINGER_BANDS"
    ATR = "ATR"
    VWAP = "VWAP"
    ZSCORE = "ZSCORE"
    SMA = "SMA"
    EMA = "EMA"
    VOLUME = "VOLUME"


class Operator(str, Enum):
    LT = "<"
    GT = ">"
    LTE = "<="
    GTE = ">="
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"


CROSSOVER_OPERATORS = (Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW)

# Sanity ranges for threshold-style conditions. Indicators not listed here (crossover-style:
# MACD, VWAP, BOLLINGER_BANDS) aren't range-checked since their conditions carry a sentinel
# threshold rather than a meaningful number.
INDICATOR_RANGES: dict[Indicator, tuple[float, float]] = {
    Indicator.RSI: (0.0, 100.0),
    Indicator.ZSCORE: (-10.0, 10.0),
    Indicator.VOLUME: (0.0, 1000.0),
    Indicator.ATR: (0.0, 1_000_000.0),
}


class StrategySpecError(ValueError):
    """Raised when a candidate strategy fails schema validation."""


@dataclass(frozen=True)
class Condition:
    indicator: Indicator
    operator: Operator
    threshold: float


def condition_to_dict(condition: Condition) -> dict:
    return {
        "indicator": condition.indicator.value,
        "operator": condition.operator.value,
        "threshold": condition.threshold,
    }


def condition_from_dict(data: dict) -> Condition:
    return Condition(
        indicator=Indicator(data["indicator"]),
        operator=Operator(data["operator"]),
        threshold=float(data.get("threshold", 0.0)),
    )


def _validate_condition(condition: Condition) -> None:
    if condition.operator in CROSSOVER_OPERATORS:
        return
    value_range = INDICATOR_RANGES.get(condition.indicator)
    if value_range and not (value_range[0] <= condition.threshold <= value_range[1]):
        raise StrategySpecError(
            f"{condition.indicator.value} threshold {condition.threshold} "
            f"outside valid range {value_range}"
        )


@dataclass
class StrategySpec:
    name: str
    archetype: Archetype
    entry_conditions: list[Condition]
    exit_conditions: list[Condition]
    timeframe: str
    source_url: str
    extraction_method: str  # "rule" | "gemini"
    confidence: float
    raw_excerpt: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate(self) -> None:
        if not self.name.strip():
            raise StrategySpecError("name must not be empty")
        if not self.entry_conditions:
            raise StrategySpecError("must have at least one entry condition")
        if not self.exit_conditions:
            raise StrategySpecError("must have at least one exit condition")
        if not 0.0 <= self.confidence <= 1.0:
            raise StrategySpecError("confidence must be between 0 and 1")
        if self.extraction_method not in ("rule", "gemini"):
            raise StrategySpecError(f"unknown extraction_method: {self.extraction_method}")
        for condition in (*self.entry_conditions, *self.exit_conditions):
            _validate_condition(condition)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "archetype": self.archetype.value,
            "entry_conditions": [condition_to_dict(c) for c in self.entry_conditions],
            "exit_conditions": [condition_to_dict(c) for c in self.exit_conditions],
            "timeframe": self.timeframe,
            "source_url": self.source_url,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "raw_excerpt": self.raw_excerpt,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrategySpec":
        return cls(
            name=data["name"],
            archetype=Archetype(data["archetype"]),
            entry_conditions=[condition_from_dict(c) for c in data["entry_conditions"]],
            exit_conditions=[condition_from_dict(c) for c in data["exit_conditions"]],
            timeframe=data.get("timeframe", "unspecified"),
            source_url=data["source_url"],
            extraction_method=data.get("extraction_method", "rule"),
            confidence=data.get("confidence", 0.0),
            raw_excerpt=data.get("raw_excerpt", ""),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        )
