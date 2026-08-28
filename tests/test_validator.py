import pandas as pd

from backtester.engine import BacktestResult
from backtester.signals import UnsupportedIndicatorError
from quant_engine.validation import validator
from quant_engine.validation.metrics import Metrics
from quant_engine.validation.overfit_guard import OverfitCheckResult


def _fake_backtest_result() -> BacktestResult:
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    return BacktestResult(
        equity_curve=pd.Series([100, 101, 102, 103, 104], index=idx),
        trades=[{"pnl_comm": 10}] * 20,  # >= min_trades so these tests exercise later gates
    )


def _patch_common(monkeypatch, metrics: Metrics, overfit_passed: bool = True):
    monkeypatch.setattr(validator, "run_backtest", lambda spec, data: _fake_backtest_result())
    monkeypatch.setattr(validator, "prepare_metrics_curve", lambda equity, *a, **kwargs: equity)
    monkeypatch.setattr(validator, "net_return_nzd", lambda *a, **kwargs: 0.0)
    monkeypatch.setattr(validator, "compute_metrics", lambda equity, trades: metrics)
    monkeypatch.setattr(
        validator,
        "walk_forward_check",
        lambda spec, data: OverfitCheckResult(2.0, 1.8, overfit_passed, "ok" if overfit_passed else "decayed"),
    )


def _run(monkeypatch, metrics: Metrics, overfit_passed: bool = True):
    _patch_common(monkeypatch, metrics, overfit_passed)
    return validator.validate_strategy(spec=object(), price_data=pd.DataFrame({"close": [1, 2, 3]}))


def test_validate_strategy_passes_all_gates(monkeypatch):
    result = _run(monkeypatch, Metrics(sharpe_ratio=2.0, max_drawdown_pct=0.05, profit_factor=2.0))
    assert result.passed is True


def test_validate_strategy_fails_on_low_sharpe(monkeypatch):
    result = _run(monkeypatch, Metrics(sharpe_ratio=0.5, max_drawdown_pct=0.05, profit_factor=2.0))
    assert result.passed is False
    assert "Sharpe" in result.reason


def test_validate_strategy_fails_on_high_drawdown(monkeypatch):
    result = _run(monkeypatch, Metrics(sharpe_ratio=2.0, max_drawdown_pct=0.20, profit_factor=2.0))
    assert result.passed is False
    assert "MaxDD" in result.reason


def test_validate_strategy_fails_on_low_profit_factor(monkeypatch):
    result = _run(monkeypatch, Metrics(sharpe_ratio=2.0, max_drawdown_pct=0.05, profit_factor=1.0))
    assert result.passed is False
    assert "Profit factor" in result.reason


def test_validate_strategy_fails_on_overfit_guard(monkeypatch):
    result = _run(
        monkeypatch, Metrics(sharpe_ratio=2.0, max_drawdown_pct=0.05, profit_factor=2.0), overfit_passed=False
    )
    assert result.passed is False
    assert "overfit guard" in result.reason


def test_validate_strategy_rejects_unsupported_indicator(monkeypatch):
    def raise_unsupported(spec, data):
        raise UnsupportedIndicatorError("BOLLINGER_BANDS not supported")

    monkeypatch.setattr(validator, "run_backtest", raise_unsupported)

    result = validator.validate_strategy(spec=object(), price_data=pd.DataFrame({"close": [1, 2, 3]}))

    assert result.passed is False
    assert "unsupported indicator" in result.reason


def test_validate_strategy_rejects_too_few_trades_even_with_good_metrics(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    monkeypatch.setattr(
        validator,
        "run_backtest",
        lambda spec, data: BacktestResult(
            equity_curve=pd.Series([100, 105, 110, 115, 120], index=idx),
            trades=[{"pnl_comm": 10}] * 3,  # well under the default min_trades
        ),
    )

    result = validator.validate_strategy(spec=object(), price_data=pd.DataFrame({"close": [1, 2, 3]}))

    assert result.passed is False
    assert "trades" in result.reason
    assert result.metrics is None  # rejected before any ratio is even computed


def test_validate_strategy_rejects_no_trades(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    monkeypatch.setattr(
        validator,
        "run_backtest",
        lambda spec, data: BacktestResult(equity_curve=pd.Series([100, 100, 100], index=idx), trades=[]),
    )

    result = validator.validate_strategy(spec=object(), price_data=pd.DataFrame({"close": [1, 2, 3]}))

    assert result.passed is False
    assert "no trades" in result.reason
