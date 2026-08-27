import pytest

from config.settings import settings
from risk_management.position_sizing import calculate_position_size, kelly_fraction, kelly_fraction_from_trades


def test_kelly_fraction_positive_edge():
    assert kelly_fraction(0.6, 100, 50) == pytest.approx(0.4)  # R=2, f=0.6-0.4/2


def test_kelly_fraction_no_edge_clamped_to_zero():
    assert kelly_fraction(0.4, 50, 50) == 0.0  # f would be -0.2


def test_kelly_fraction_invalid_inputs_are_zero():
    assert kelly_fraction(0.6, 0, 50) == 0.0
    assert kelly_fraction(0.6, 100, 0) == 0.0
    assert kelly_fraction(1.5, 100, 50) == 0.0


def test_kelly_fraction_from_trades():
    trades = [{"pnl_comm": 100}, {"pnl_comm": -50}, {"pnl_comm": 100}, {"pnl_comm": -50}]
    assert kelly_fraction_from_trades(trades) == pytest.approx(0.25)  # win_rate=0.5, R=2


def test_kelly_fraction_from_no_trades_is_zero():
    assert kelly_fraction_from_trades([]) == 0.0


def _patch_config(monkeypatch, **overrides):
    # kwarg names are short (e.g. max_position_size_pct=1.0); map each to its dotted
    # config key so a typo'd/mismatched key can't silently fail to override anything.
    defaults = {
        "position_sizing_method": "atr_kelly",
        "max_risk_per_trade_pct": 0.01,
        "atr_multiplier": 2.0,
        "kelly_fraction_cap": 0.5,
        "max_position_size_pct": 0.05,
    }
    merged = {**defaults, **overrides}
    values = {f"risk_management.{key}": value for key, value in merged.items()}
    monkeypatch.setattr(settings, "get", lambda key, default=None: values.get(key, default))


def test_atr_sizing_respects_max_risk_per_trade(monkeypatch):
    _patch_config(monkeypatch, max_position_size_pct=1.0)  # disable cap for this test

    result = calculate_position_size(equity=100_000, price=50.0, atr=2.0, method="atr")

    assert result.shares == pytest.approx(250.0)  # (100,000*0.01) / (2*2)
    assert result.capped_by_max_position_size is False


def test_position_size_is_capped_by_max_position_size_pct(monkeypatch):
    _patch_config(monkeypatch, max_risk_per_trade_pct=0.10, atr_multiplier=1.0, max_position_size_pct=0.05)

    result = calculate_position_size(equity=100_000, price=50.0, atr=1.0, method="atr")

    assert result.capped_by_max_position_size is True
    assert result.position_value == pytest.approx(5_000.0)


def test_atr_kelly_sizes_to_zero_when_kelly_shows_no_edge(monkeypatch):
    _patch_config(monkeypatch, max_position_size_pct=1.0)
    trades = [{"pnl_comm": -10}, {"pnl_comm": -10}]

    result = calculate_position_size(equity=100_000, price=50.0, atr=1.0, trades=trades, method="atr_kelly")

    assert result.shares == 0.0


def test_atr_kelly_without_trades_falls_back_to_atr(monkeypatch):
    _patch_config(monkeypatch, max_position_size_pct=1.0)

    result = calculate_position_size(equity=100_000, price=50.0, atr=2.0, trades=None, method="atr_kelly")

    assert result.shares == pytest.approx(250.0)
