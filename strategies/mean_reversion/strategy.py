"""Classic RSI mean-reversion reference strategy: buy when RSI drops into oversold
territory, sell when it climbs into overbought territory. Produces a schema-validated
StrategySpec consumed by the same generic backtester/signals.py pipeline used for
discovered strategies — single-ticker archetypes need no separate execution path.
"""
from __future__ import annotations

from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec

INTERNAL_SOURCE_URL = "internal://strategies/mean_reversion/classic_rsi_reversion"


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
