"""Computes Sharpe Ratio, Max Drawdown, and Profit Factor from a backtest equity curve and
trade list. Pure functions on plain pandas/lists — independent of backtrader and of how the
equity curve was produced, so validator.py can feed these the same metrics whether or not
NZ tax/FX drag has already been applied (see backtester/nz_adjustments.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
# Cap for "no losing trades yet" rather than true float("inf") — the registry is
# serialized to JSON (strategy_registry.json, read by the dashboard's JS JSON.parse), and
# JSON has no Infinity token; Python's json module would silently write the non-standard
# `Infinity` literal, which breaks in any strict JSON consumer.
UNCAPPED_PROFIT_FACTOR = 999.0


@dataclass(frozen=True)
class Metrics:
    sharpe_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    # Informational only — NOT folded into sharpe_ratio/max_drawdown_pct. See
    # backtester/nz_adjustments.py's module docstring for why: FIF tax is a once-a-year
    # lump-sum event, not a day-to-day risk phenomenon, and injecting it into a volatility-
    # based ratio (as either a single-day shock or a smoothed daily ramp) manufactures
    # statistically meaningless results that have nothing to do with the strategy's actual
    # trading risk. This field carries the real bottom-line "what you'd actually keep"
    # figure for transparency (CLAUDE.md: never hide costs) without corrupting the gate.
    net_return_nzd: float | None = None


def compute_sharpe_ratio(
    equity_curve: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    returns = equity_curve.pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return 0.0
    period_risk_free = risk_free_rate / periods_per_year
    excess_returns = returns - period_risk_free
    return float(excess_returns.mean() / excess_returns.std() * np.sqrt(periods_per_year))


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Returns the maximum peak-to-trough drawdown as a positive fraction (0.12 = 12%)."""
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(-drawdown.min())


def compute_profit_factor(trades: list[dict]) -> float:
    """Gross profit / gross loss across closed trades. Returns 0.0 with no losing trades
    and no winning trades either (nothing to divide); returns UNCAPPED_PROFIT_FACTOR (not
    literal infinity — see that constant's docstring) if there are wins but zero losses.
    """
    pnls = [trade.get("pnl_comm", trade.get("pnl", 0.0)) for trade in trades]
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = -sum(pnl for pnl in pnls if pnl < 0)

    if gross_loss == 0:
        return UNCAPPED_PROFIT_FACTOR if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_metrics(equity_curve: pd.Series, trades: list[dict]) -> Metrics:
    return Metrics(
        sharpe_ratio=compute_sharpe_ratio(equity_curve),
        max_drawdown_pct=compute_max_drawdown(equity_curve),
        profit_factor=compute_profit_factor(trades),
    )
