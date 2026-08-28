"""Classic N-day channel breakout reference strategy, with volume confirmation: buy when
price closes above its N-day high on above-average volume, sell when it closes below its
M-day low. Produces a schema-validated StrategySpec consumed by the same generic
backtester/signals.py pipeline used for discovered strategies.
"""
from __future__ import annotations

from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec

INTERNAL_SOURCE_URL = "internal://strategies/breakout/classic_channel_breakout"
KELTNER_SOURCE_URL = "internal://strategies/breakout/classic_keltner_breakout"


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


def classic_keltner_breakout(period: int = 20, timeframe: str = "1d") -> StrategySpec:
    """Volatility-adjusted breakout using the standard 20-period/2x-ATR Keltner Channel
    construction (not tuned to any particular backtest): buy when price closes above the
    upper channel, exit when it closes back below the lower channel. Distinct from
    classic_channel_breakout — that uses raw N-day price extremes, this uses ATR-scaled
    volatility bands, so the two can diverge meaningfully in choppy vs trending regimes.
    """
    return StrategySpec(
        name=f"classic_keltner_breakout_{period}",
        archetype=Archetype.BREAKOUT,
        entry_conditions=[Condition(Indicator.KELTNER_UPPER, Operator.CROSSES_ABOVE, 0.0, period=period)],
        exit_conditions=[Condition(Indicator.KELTNER_LOWER, Operator.CROSSES_BELOW, 0.0, period=period)],
        timeframe=timeframe,
        source_url=KELTNER_SOURCE_URL,
        extraction_method="rule",
        confidence=1.0,
        raw_excerpt=(
            f"Classic Keltner Channel({period}, 2x ATR) breakout: buy when close crosses "
            "above the upper channel, exit when it crosses below the lower channel "
            "(hand-designed reference strategy)."
        ),
    )
