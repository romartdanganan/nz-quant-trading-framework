import numpy as np
import pandas as pd

from backtester.pairs_engine import run_pairs_backtest
from strategies.pairs_trading.strategy import build_pairs_spec


def test_run_pairs_backtest_produces_equity_curve_and_trades():
    rng = np.random.default_rng(0)
    n = 150
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    price_b = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), index=idx)
    # spread oscillates around a mean, cointegrated by construction, with a clear
    # oscillation so the z-score actually crosses the entry/exit thresholds
    oscillation = 5 * np.sin(np.linspace(0, 6 * np.pi, n))
    price_a = 1.0 * price_b + 50 + oscillation

    spec = build_pairs_spec("A", "B", lookback_period=20, entry_zscore=1.0, exit_zscore=0.3)
    result = run_pairs_backtest(spec, price_a, price_b, initial_cash=100_000.0)

    assert len(result.equity_curve) == n
    assert isinstance(result.trades, list)
    assert len(result.trades) > 0  # the oscillation should trigger at least one round trip


def test_run_pairs_backtest_flat_spread_never_trades():
    idx = pd.date_range("2023-01-01", periods=60, freq="D")
    price_b = pd.Series([100.0] * 60, index=idx)
    price_a = pd.Series([150.0] * 60, index=idx)  # perfectly flat spread, zscore always ~0/NaN

    spec = build_pairs_spec("A", "B", lookback_period=10, entry_zscore=2.0, exit_zscore=0.5)
    result = run_pairs_backtest(spec, price_a, price_b, initial_cash=50_000.0)

    assert result.trades == []
    assert all(value == 50_000.0 for value in result.equity_curve)


def test_run_pairs_backtest_aligns_mismatched_indices():
    idx_a = pd.date_range("2023-01-01", periods=60, freq="D")
    idx_b = pd.date_range("2023-01-03", periods=60, freq="D")
    rng = np.random.default_rng(1)
    price_b = pd.Series(100 + np.cumsum(rng.normal(0, 1, 60)), index=idx_b)
    price_a = pd.Series((1.2 * price_b.values) + 20, index=idx_a)

    spec = build_pairs_spec("A", "B", lookback_period=10)
    result = run_pairs_backtest(spec, price_a, price_b)

    assert len(result.equity_curve) == 58  # only the overlapping days
