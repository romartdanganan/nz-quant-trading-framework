import pandas as pd
import pytest

from quant_engine.validation.metrics import (
    UNCAPPED_PROFIT_FACTOR,
    compute_max_drawdown,
    compute_metrics,
    compute_profit_factor,
    compute_sharpe_ratio,
)


def test_compute_max_drawdown_known_series():
    equity = pd.Series([100, 120, 90, 110, 80, 130])
    # peak 120 -> trough 80 => drawdown magnitude 40/120
    assert compute_max_drawdown(equity) == pytest.approx(40 / 120, rel=1e-4)


def test_compute_max_drawdown_monotonic_up_is_zero():
    equity = pd.Series([100, 110, 120, 130])
    assert compute_max_drawdown(equity) == 0.0


def test_compute_max_drawdown_empty_series():
    assert compute_max_drawdown(pd.Series(dtype=float)) == 0.0


def test_compute_profit_factor_mixed_trades():
    trades = [{"pnl_comm": 100}, {"pnl_comm": -50}, {"pnl_comm": 200}, {"pnl_comm": -25}]
    assert compute_profit_factor(trades) == pytest.approx(4.0)  # 300 / 75


def test_compute_profit_factor_no_losses_is_capped_not_infinite():
    trades = [{"pnl_comm": 100}, {"pnl_comm": 50}]
    # capped rather than float("inf") so the value survives JSON round-tripping
    # (the registry file is read by the dashboard's JS JSON.parse)
    assert compute_profit_factor(trades) == UNCAPPED_PROFIT_FACTOR
    import json
    json.dumps(compute_profit_factor(trades))  # must not produce the non-standard Infinity token


def test_compute_profit_factor_no_trades_is_zero():
    assert compute_profit_factor([]) == 0.0


def test_compute_profit_factor_falls_back_to_pnl_key():
    trades = [{"pnl": 100}, {"pnl": -20}]
    assert compute_profit_factor(trades) == pytest.approx(5.0)


def test_compute_sharpe_ratio_positive_trend_is_positive():
    equity = pd.Series([100, 101, 102, 103, 104, 105])
    assert compute_sharpe_ratio(equity) > 0


def test_compute_sharpe_ratio_flat_equity_is_zero():
    equity = pd.Series([100, 100, 100, 100])
    assert compute_sharpe_ratio(equity) == 0.0


def test_compute_metrics_bundles_all_three():
    equity = pd.Series([100, 105, 103, 108])
    trades = [{"pnl_comm": 10}, {"pnl_comm": -5}]
    metrics = compute_metrics(equity, trades)

    assert metrics.sharpe_ratio == compute_sharpe_ratio(equity)
    assert metrics.max_drawdown_pct == compute_max_drawdown(equity)
    assert metrics.profit_factor == compute_profit_factor(trades)
