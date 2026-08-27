"""Pairs-trading backtest simulation: long-spread when the z-score drops far below zero,
short-spread when it rises far above, flat once it reverts toward zero. This is a direct
P&L simulation on the spread itself, not a two-leg backtrader order simulation — a
documented simplification (single-instrument engine.py's Cerebro model doesn't map cleanly
onto a two-instrument spread position). Phase 7's execution engine places the two real
broker legs; this backtest only needs to prove the spread relationship is tradeable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from strategies.pairs_trading.strategy import (
    PairsSpec,
    align_price_series,
    compute_hedge_ratio,
    compute_spread,
    compute_zscore,
)


@dataclass
class PairsBacktestResult:
    equity_curve: pd.Series
    trades: list[dict] = field(default_factory=list)


def run_pairs_backtest(
    spec: PairsSpec,
    price_a: pd.Series,
    price_b: pd.Series,
    initial_cash: float = 100_000.0,
) -> PairsBacktestResult:
    price_a, price_b = align_price_series(price_a, price_b)
    hedge_ratio = compute_hedge_ratio(price_a, price_b)
    spread = compute_spread(price_a, price_b, hedge_ratio)
    zscore = compute_zscore(spread, spec.lookback_period)
    spread_diff = spread.diff().fillna(0.0)

    position = 0  # +1 long spread (long A, short hedge_ratio*B), -1 short spread, 0 flat
    entry_spread_value: float | None = None
    equity = initial_cash
    equity_values: list[float] = []
    trades: list[dict] = []

    for i in range(len(spread)):
        if position != 0:
            equity += position * spread_diff.iloc[i]

        z = zscore.iloc[i]
        if pd.notna(z):
            if position == 0:
                if z <= -spec.entry_zscore:
                    position = 1
                    entry_spread_value = spread.iloc[i]
                elif z >= spec.entry_zscore:
                    position = -1
                    entry_spread_value = spread.iloc[i]
            elif abs(z) <= spec.exit_zscore:
                pnl = position * (spread.iloc[i] - entry_spread_value)
                trades.append({"pnl": pnl, "pnl_comm": pnl})
                position = 0
                entry_spread_value = None

        equity_values.append(equity)

    return PairsBacktestResult(
        equity_curve=pd.Series(equity_values, index=spread.index, name="equity"),
        trades=trades,
    )
