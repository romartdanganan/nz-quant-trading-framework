"""Classic N-day channel breakout reference strategy, with volume confirmation: buy when
price closes above its N-day high on above-average volume, sell when it closes below its
M-day low. Produces a schema-validated StrategySpec consumed by the same generic
backtester/signals.py pipeline used for discovered strategies.
"""
from __future__ import annotations

from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec

INTERNAL_SOURCE_URL = "internal://strategies/breakout/classic_channel_breakout"


def classic_channel_breakout(
    breakout_period: int = 20,
    exit_period: int = 10,
    volume_multiplier: float = 1.5,
    timeframe: str = "1d",
) -> StrategySpec:
    return StrategySpec(
        name=f"classic_channel_breakout_{breakout_period}_{exit_period}",
        archetype=Archetype.BREAKOUT,
        entry_conditions=[
            Condition(Indicator.CHANNEL_HIGH, Operator.CROSSES_ABOVE, 0.0, period=breakout_period),
            Condition(Indicator.VOLUME, Operator.GT, volume_multiplier),
        ],
        exit_conditions=[Condition(Indicator.CHANNEL_LOW, Operator.CROSSES_BELOW, 0.0, period=exit_period)],
        timeframe=timeframe,
        source_url=INTERNAL_SOURCE_URL,
        extraction_method="rule",
        confidence=1.0,
        raw_excerpt=(
            f"Classic {breakout_period}-day channel breakout with volume confirmation, "
            f"exit on a {exit_period}-day low (hand-designed reference strategy)."
        ),
    )
