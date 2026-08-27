"""Classic MACD-crossover momentum reference strategy: buy when MACD crosses above its
signal line, sell when it crosses below. Produces a schema-validated StrategySpec
consumed by the same generic backtester/signals.py pipeline used for discovered strategies.
"""
from __future__ import annotations

from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec

INTERNAL_SOURCE_URL = "internal://strategies/momentum/classic_macd_momentum"


def classic_macd_momentum(timeframe: str = "1d") -> StrategySpec:
    return StrategySpec(
        name="classic_macd_momentum",
        archetype=Archetype.MOMENTUM,
        entry_conditions=[Condition(Indicator.MACD, Operator.CROSSES_ABOVE, 0.0)],
        exit_conditions=[Condition(Indicator.MACD, Operator.CROSSES_BELOW, 0.0)],
        timeframe=timeframe,
        source_url=INTERNAL_SOURCE_URL,
        extraction_method="rule",
        confidence=1.0,
        raw_excerpt=(
            "Classic MACD crossover momentum: buy on bullish cross, sell on bearish cross "
            "(hand-designed reference strategy)."
        ),
    )
