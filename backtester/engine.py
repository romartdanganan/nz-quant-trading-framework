"""Backtrader-based execution simulation: takes signals.py's entry/exit boolean columns
and simulates realistic order execution, commission, and portfolio value tracking via
Cerebro. Indicator math lives in signals.py (pure pandas, independently testable) — this
module's only job is the simulation itself.

Known Phase 4 limitation: no stop-loss/position-sizing is modeled here (that's
risk_management/, Phase 7) — metrics from this engine reflect the raw strategy edge on a
single full-position long/flat basis. Incubation (paper trading with real risk controls
active) is what actually proves the strategy is trustworthy with those controls in place.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import backtrader as bt
import pandas as pd

from backtester.signals import generate_signals
from strategy_research.strategy_spec import StrategySpec

DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_COMMISSION = 0.001  # 0.1% per trade — a conservative default, not a broker quote


class _SignalData(bt.feeds.PandasData):
    lines = ("entry_signal", "exit_signal")
    params = (("entry_signal", -1), ("exit_signal", -1))


class _SignalStrategy(bt.Strategy):
    def __init__(self):
        self.trade_log: list[dict] = []

    def next(self):
        if not self.position and self.data.entry_signal[0]:
            self.buy()
        elif self.position and self.data.exit_signal[0]:
            self.close()

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({"pnl": trade.pnl, "pnl_comm": trade.pnlcomm})


class _EquityTracker(bt.Analyzer):
    def start(self):
        self.values: list[float] = []
        self.dates: list = []

    def next(self):
        self.values.append(self.strategy.broker.getvalue())
        self.dates.append(self.strategy.datetime.date(0))


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[dict] = field(default_factory=list)


def run_backtest(
    spec: StrategySpec,
    price_data: pd.DataFrame,
    initial_cash: float = DEFAULT_INITIAL_CASH,
    commission: float = DEFAULT_COMMISSION,
) -> BacktestResult:
    signals = generate_signals(spec, price_data)
    combined = price_data.join(signals)
    combined[["entry_signal", "exit_signal"]] = combined[["entry_signal", "exit_signal"]].fillna(False)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.adddata(_SignalData(dataname=combined))
    cerebro.addstrategy(_SignalStrategy)
    cerebro.addanalyzer(_EquityTracker, _name="equity")

    results = cerebro.run()
    strategy = results[0]
    equity = strategy.analyzers.equity

    equity_curve = pd.Series(
        equity.values, index=pd.DatetimeIndex(equity.dates), name="equity"
    )
    return BacktestResult(equity_curve=equity_curve, trades=strategy.trade_log)
