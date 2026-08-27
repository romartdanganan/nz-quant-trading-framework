"""Hardcoded, non-negotiable risk circuit breakers (CLAUDE.md "Hardcoded risk circuit
breakers"): a hard position-size ceiling, a mandatory stop-loss on every order, and a
max-daily-loss halt. These are plain deterministic checks — never AI-adjusted — applied
identically in paper and live trading. Nothing in execution_ibkr/ or execution_alpaca/
should place an order without passing through check_order() first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from config.settings import settings


class CircuitBreakerViolation(RuntimeError):
    """Raised when an order would violate a hardcoded risk limit. Callers must not place
    the order and must not silently resize/retry it — sizing decisions belong to
    risk_management/position_sizing.py, called *before* this check, not inferred here.
    """


@dataclass(frozen=True)
class OrderRequest:
    ticker: str
    shares: float
    price: float
    stop_loss: float | None


def enforce_stop_loss_required(order: OrderRequest) -> None:
    if settings.get("circuit_breakers.require_stop_loss_on_every_order", True) and order.stop_loss is None:
        raise CircuitBreakerViolation(f"{order.ticker}: order has no stop-loss attached")


def enforce_position_size_limit(order: OrderRequest, equity: float) -> None:
    max_pct = settings.get("risk_management.max_position_size_pct", 0.05)
    position_value = order.shares * order.price
    max_position_value = equity * max_pct
    if equity > 0 and position_value > max_position_value:
        raise CircuitBreakerViolation(
            f"{order.ticker}: position value {position_value:.2f} exceeds "
            f"{max_pct:.1%} of equity ({max_position_value:.2f})"
        )


@dataclass
class DailyLossTracker:
    """Tracks one trading day's realized+unrealized P&L against
    circuit_breakers.max_daily_loss_pct. Once breached, halted stays True for the rest of
    that day regardless of any subsequent recovery — callers must check is_halted() before
    allowing any new entry, and call reset_for_new_day() at the start of each session.
    """

    starting_equity: float
    trading_day: date
    current_pnl: float = 0.0
    halted: bool = False

    def update(self, pnl_change: float) -> None:
        self.current_pnl += pnl_change
        max_daily_loss_pct = settings.get("circuit_breakers.max_daily_loss_pct", 0.02)
        if self.starting_equity > 0 and -self.current_pnl >= self.starting_equity * max_daily_loss_pct:
            self.halted = True

    def is_halted(self) -> bool:
        return self.halted

    def reset_for_new_day(self, new_day: date, starting_equity: float) -> None:
        self.trading_day = new_day
        self.starting_equity = starting_equity
        self.current_pnl = 0.0
        self.halted = False


def check_order(
    order: OrderRequest, equity: float, daily_loss_tracker: DailyLossTracker | None = None
) -> None:
    """Runs every hardcoded circuit breaker. Raises CircuitBreakerViolation on the first
    failure — callers must not place the order.
    """
    if daily_loss_tracker is not None and daily_loss_tracker.is_halted():
        raise CircuitBreakerViolation(f"{order.ticker}: daily loss circuit breaker is halted for today")
    enforce_stop_loss_required(order)
    enforce_position_size_limit(order, equity)
