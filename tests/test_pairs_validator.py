import pandas as pd

from backtester.pairs_engine import PairsBacktestResult
from quant_engine.validation import pairs_validator
from quant_engine.validation.metrics import Metrics
from strategies.pairs_trading.strategy import build_pairs_spec


def _fake_backtest_result() -> PairsBacktestResult:
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    return PairsBacktestResult(
        equity_curve=pd.Series([100_000, 100_500, 101_000, 100_800, 101_500], index=idx),
        trades=[{"pnl_comm": 500}],
    )


def _patch_common(monkeypatch, p_value, metrics: Metrics):
    monkeypatch.setattr(pairs_validator, "check_cointegration", lambda a, b: p_value)
    monkeypatch.setattr(pairs_validator, "run_pairs_backtest", lambda spec, a, b: _fake_backtest_result())
    monkeypatch.setattr(pairs_validator, "prepare_metrics_curve", lambda equity, *a, **kwargs: equity)
    monkeypatch.setattr(pairs_validator, "net_return_nzd", lambda *a, **kwargs: 0.0)
    monkeypatch.setattr(pairs_validator, "compute_metrics", lambda equity, trades: metrics)


def _series():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    return pd.Series(range(5), index=idx, dtype=float), pd.Series(range(5), index=idx, dtype=float)


def test_rejects_when_not_cointegrated(monkeypatch):
    _patch_common(monkeypatch, p_value=0.5, metrics=Metrics(2.0, 0.05, 2.0))
    price_a, price_b = _series()

    result = pairs_validator.validate_pairs_strategy(build_pairs_spec("A", "B"), price_a, price_b)

    assert result.passed is False
    assert "not cointegrated" in result.reason


def test_passes_when_cointegrated_and_thresholds_met(monkeypatch):
    _patch_common(monkeypatch, p_value=0.01, metrics=Metrics(2.0, 0.05, 2.0))
    price_a, price_b = _series()

    result = pairs_validator.validate_pairs_strategy(build_pairs_spec("A", "B"), price_a, price_b)

    assert result.passed is True


def test_rejects_on_low_sharpe_even_if_cointegrated(monkeypatch):
    _patch_common(monkeypatch, p_value=0.01, metrics=Metrics(0.5, 0.05, 2.0))
    price_a, price_b = _series()

    result = pairs_validator.validate_pairs_strategy(build_pairs_spec("A", "B"), price_a, price_b)

    assert result.passed is False
    assert "Sharpe" in result.reason


def test_rejects_no_trades(monkeypatch):
    monkeypatch.setattr(pairs_validator, "check_cointegration", lambda a, b: 0.01)
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    monkeypatch.setattr(
        pairs_validator,
        "run_pairs_backtest",
        lambda spec, a, b: PairsBacktestResult(equity_curve=pd.Series([100, 100, 100], index=idx), trades=[]),
    )
    price_a, price_b = _series()

    result = pairs_validator.validate_pairs_strategy(build_pairs_spec("A", "B"), price_a, price_b)

    assert result.passed is False
    assert "no trades" in result.reason
