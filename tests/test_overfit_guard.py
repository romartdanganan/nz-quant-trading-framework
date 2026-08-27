import pandas as pd

from backtester.engine import BacktestResult
from quant_engine.validation import overfit_guard


def _fake_result(n: int = 2) -> BacktestResult:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return BacktestResult(equity_curve=pd.Series(range(100, 100 + n), index=idx), trades=[])


def test_walk_forward_passes_when_out_of_sample_holds_up(monkeypatch):
    price_data = pd.DataFrame({"close": range(100)})
    monkeypatch.setattr(overfit_guard, "run_backtest", lambda spec, data: _fake_result())

    sharpe_values = iter([2.0, 1.6])  # 20% decay, within default 50% tolerance
    monkeypatch.setattr(overfit_guard, "compute_sharpe_ratio", lambda equity: next(sharpe_values))

    result = overfit_guard.walk_forward_check(spec=object(), price_data=price_data)

    assert result.passed is True
    assert result.in_sample_sharpe == 2.0
    assert result.out_of_sample_sharpe == 1.6


def test_walk_forward_fails_when_out_of_sample_not_positive(monkeypatch):
    price_data = pd.DataFrame({"close": range(100)})
    monkeypatch.setattr(overfit_guard, "run_backtest", lambda spec, data: _fake_result())
    sharpe_values = iter([2.0, -0.5])
    monkeypatch.setattr(overfit_guard, "compute_sharpe_ratio", lambda equity: next(sharpe_values))

    result = overfit_guard.walk_forward_check(spec=object(), price_data=price_data)

    assert result.passed is False
    assert "not positive" in result.reason


def test_walk_forward_fails_on_severe_decay(monkeypatch):
    price_data = pd.DataFrame({"close": range(100)})
    monkeypatch.setattr(overfit_guard, "run_backtest", lambda spec, data: _fake_result())
    sharpe_values = iter([2.0, 0.5])  # 75% decay > default 50% tolerance
    monkeypatch.setattr(overfit_guard, "compute_sharpe_ratio", lambda equity: next(sharpe_values))

    result = overfit_guard.walk_forward_check(spec=object(), price_data=price_data)

    assert result.passed is False
    assert "decayed" in result.reason


def test_walk_forward_uses_configured_split_ratio(monkeypatch):
    price_data = pd.DataFrame({"close": range(100)})
    seen_lengths = []

    def fake_run_backtest(spec, data):
        seen_lengths.append(len(data))
        return _fake_result()

    monkeypatch.setattr(overfit_guard, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(overfit_guard, "compute_sharpe_ratio", lambda equity: 1.0)

    overfit_guard.walk_forward_check(spec=object(), price_data=price_data, split_ratio=0.8)

    assert seen_lengths == [80, 20]
