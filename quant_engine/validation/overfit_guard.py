"""Walk-forward / out-of-sample overfitting guard: splits historical price data into an
in-sample and out-of-sample window and checks that a strategy's edge survives on data it
wasn't discovered against. Per CLAUDE.md Guardrails: a strategy that only works in-sample
is rejected outright, never "fixed" by relaxing thresholds or retrying.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtester.engine import run_backtest
from quant_engine.validation.metrics import compute_sharpe_ratio
from strategy_research.strategy_spec import StrategySpec

DEFAULT_SPLIT_RATIO = 0.7
DEFAULT_MAX_SHARPE_DECAY_PCT = 0.5  # out-of-sample Sharpe may fall at most 50% vs in-sample


@dataclass(frozen=True)
class OverfitCheckResult:
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    passed: bool
    reason: str


def walk_forward_check(
    spec: StrategySpec,
    price_data: pd.DataFrame,
    split_ratio: float = DEFAULT_SPLIT_RATIO,
    max_sharpe_decay_pct: float = DEFAULT_MAX_SHARPE_DECAY_PCT,
) -> OverfitCheckResult:
    split_index = int(len(price_data) * split_ratio)
    in_sample = price_data.iloc[:split_index]
    out_of_sample = price_data.iloc[split_index:]

    in_sample_result = run_backtest(spec, in_sample)
    out_of_sample_result = run_backtest(spec, out_of_sample)

    in_sharpe = compute_sharpe_ratio(in_sample_result.equity_curve)
    out_sharpe = compute_sharpe_ratio(out_of_sample_result.equity_curve)

    if out_sharpe <= 0:
        return OverfitCheckResult(in_sharpe, out_sharpe, False, "out-of-sample Sharpe is not positive")

    if in_sharpe > 0 and out_sharpe < in_sharpe * (1 - max_sharpe_decay_pct):
        return OverfitCheckResult(
            in_sharpe,
            out_sharpe,
            False,
            f"out-of-sample Sharpe {out_sharpe:.2f} decayed more than "
            f"{max_sharpe_decay_pct:.0%} vs in-sample {in_sharpe:.2f}",
        )

    return OverfitCheckResult(in_sharpe, out_sharpe, True, "out-of-sample performance holds up")
