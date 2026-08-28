"""Classic RSI mean-reversion reference strategy: buy when RSI drops into oversold
territory, sell when it climbs into overbought territory. Produces a schema-validated
StrategySpec consumed by the same generic backtester/signals.py pipeline used for
discovered strategies — single-ticker archetypes need no separate execution path.
"""
from __future__ import annotations

from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec

INTERNAL_SOURCE_URL = "internal://strategies/mean_reversion/classic_rsi_reversion"
RSI2_SOURCE_URL = "internal://strategies/mean_reversion/classic_rsi2_reversion"
BOLLINGER_SOURCE_URL = "internal://strategies/mean_reversion/classic_bollinger_reversion"


def classic_rsi_reversion(
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    timeframe: str = "1d",
) -> StrategySpec:
    return StrategySpec(
        name=f"classic_rsi_reversion_{period}_{int(oversold)}_{int(overbought)}",
        archetype=Archetype.MEAN_REVERSION,
        entry_conditions=[Condition(Indicator.RSI, Operator.LT, oversold, period=period)],
        exit_conditions=[Condition(Indicator.RSI, Operator.GT, overbought, period=period)],
        timeframe=timeframe,
        source_url=INTERNAL_SOURCE_URL,
        extraction_method="rule",
        confidence=1.0,
        raw_excerpt=(
            f"Classic RSI({period}) mean reversion: buy below {oversold:.0f}, "
            f"sell above {overbought:.0f} (hand-designed reference strategy)."
        ),
    )


def classic_rsi2_reversion(timeframe: str = "1d") -> StrategySpec:
    """Larry Connors' published short-term mean-reversion rule: RSI(2) < 10 to buy, RSI(2) >
    70 to sell — a genuinely different, well-known parameterization from classic_rsi_reversion
    above, not fit to any specific backtest. Its own dedicated source_url, distinct from
    classic_rsi_reversion's, since that function's source_url is deliberately
    period-independent (see test_classic_strategies_have_stable_internal_source_urls) — reusing
    it here would collide and silently drop this candidate at registry dedup time.
    """
    period, oversold, overbought = 2, 10.0, 70.0
    return StrategySpec(
        name=f"classic_rsi2_reversion_{int(oversold)}_{int(overbought)}",
        archetype=Archetype.MEAN_REVERSION,
        entry_conditions=[Condition(Indicator.RSI, Operator.LT, oversold, period=period)],
        exit_conditions=[Condition(Indicator.RSI, Operator.GT, overbought, period=period)],
        timeframe=timeframe,
        source_url=RSI2_SOURCE_URL,
        extraction_method="rule",
        confidence=1.0,
        raw_excerpt=(
            "Larry Connors' RSI(2) mean reversion: buy below 10, sell above 70 "
            "(hand-designed reference strategy)."
        ),
    )


def classic_bollinger_reversion(period: int = 20, timeframe: str = "1d") -> StrategySpec:
    """John Bollinger's own standard construction (20-period, 2 std dev — not tuned to any
    particular backtest): buy when price closes below the lower band, sell when it closes
    back above the upper band.
    """
    return StrategySpec(
        name=f"classic_bollinger_reversion_{period}",
        archetype=Archetype.MEAN_REVERSION,
        entry_conditions=[Condition(Indicator.BOLLINGER_LOWER, Operator.CROSSES_BELOW, 0.0, period=period)],
        exit_conditions=[Condition(Indicator.BOLLINGER_UPPER, Operator.CROSSES_ABOVE, 0.0, period=period)],
        timeframe=timeframe,
        source_url=BOLLINGER_SOURCE_URL,
        extraction_method="rule",
        confidence=1.0,
        raw_excerpt=(
            f"Classic Bollinger Band({period}, 2std) mean reversion: buy when close crosses "
            "below the lower band, sell when it crosses back above the upper band "
            "(hand-designed reference strategy)."
        ),
    )
