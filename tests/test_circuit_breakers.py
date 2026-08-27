from datetime import date

import pytest

from config.settings import settings
from risk_management.circuit_breakers import (
    CircuitBreakerViolation,
    DailyLossTracker,
    OrderRequest,
    check_order,
    enforce_position_size_limit,
    enforce_stop_loss_required,
)


def test_enforce_stop_loss_required_raises_without_stop():
    order = OrderRequest(ticker="AAPL", shares=10, price=100.0, stop_loss=None)
    with pytest.raises(CircuitBreakerViolation):
        enforce_stop_loss_required(order)


def test_enforce_stop_loss_required_passes_with_stop():
    order = OrderRequest(ticker="AAPL", shares=10, price=100.0, stop_loss=95.0)
    enforce_stop_loss_required(order)


def test_enforce_position_size_limit_raises_when_exceeded(monkeypatch):
    monkeypatch.setattr(
        settings, "get", lambda key, default=None: {"risk_management.max_position_size_pct": 0.05}.get(key, default)
    )
    order = OrderRequest(ticker="AAPL", shares=100, price=100.0, stop_loss=95.0)  # value 10,000 > 5,000 cap

    with pytest.raises(CircuitBreakerViolation):
        enforce_position_size_limit(order, equity=100_000)


def test_enforce_position_size_limit_passes_within_cap(monkeypatch):
    monkeypatch.setattr(
        settings, "get", lambda key, default=None: {"risk_management.max_position_size_pct": 0.05}.get(key, default)
    )
    order = OrderRequest(ticker="AAPL", shares=40, price=100.0, stop_loss=95.0)  # value 4,000 < 5,000 cap

    enforce_position_size_limit(order, equity=100_000)


def test_daily_loss_tracker_halts_after_breach(monkeypatch):
    monkeypatch.setattr(
        settings, "get", lambda key, default=None: {"circuit_breakers.max_daily_loss_pct": 0.02}.get(key, default)
    )
    tracker = DailyLossTracker(starting_equity=100_000, trading_day=date(2026, 1, 1))

    assert tracker.is_halted() is False
    tracker.update(-1500)
    assert tracker.is_halted() is False
    tracker.update(-600)  # cumulative -2100 >= 2% of 100,000
    assert tracker.is_halted() is True


def test_daily_loss_tracker_resets_for_new_day():
    tracker = DailyLossTracker(
        starting_equity=100_000, trading_day=date(2026, 1, 1), current_pnl=-5000, halted=True
    )
    tracker.reset_for_new_day(date(2026, 1, 2), starting_equity=95_000)

    assert tracker.is_halted() is False
    assert tracker.current_pnl == 0.0
    assert tracker.starting_equity == 95_000


def test_check_order_blocks_when_daily_loss_halted(monkeypatch):
    monkeypatch.setattr(
        settings,
        "get",
        lambda key, default=None: {
            "circuit_breakers.max_daily_loss_pct": 0.02,
            "circuit_breakers.require_stop_loss_on_every_order": True,
            "risk_management.max_position_size_pct": 0.05,
        }.get(key, default),
    )
    tracker = DailyLossTracker(starting_equity=100_000, trading_day=date(2026, 1, 1))
    tracker.update(-3000)
    order = OrderRequest(ticker="AAPL", shares=1, price=100.0, stop_loss=95.0)

    with pytest.raises(CircuitBreakerViolation):
        check_order(order, equity=100_000, daily_loss_tracker=tracker)
