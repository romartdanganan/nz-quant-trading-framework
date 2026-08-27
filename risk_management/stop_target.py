"""Computes trailing stop-loss and target-profit prices for a trade, from entry price and
ATR (volatility). Per CLAUDE.md's hardcoded circuit breakers, every order must carry a
stop-loss computed here (or an equivalent) before it reaches execution_ibkr/execution_alpaca.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.settings import settings


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class StopTarget:
    entry_price: float
    stop_loss: float
    target_price: float
    stop_distance: float


def calculate_stop_target(
    entry_price: float,
    atr: float,
    direction: Direction = Direction.LONG,
    atr_multiplier: float | None = None,
    reward_risk_ratio: float | None = None,
) -> StopTarget:
    atr_multiplier = atr_multiplier if atr_multiplier is not None else settings.get(
        "risk_management.atr_multiplier", 2.0
    )
    reward_risk_ratio = reward_risk_ratio if reward_risk_ratio is not None else settings.get(
        "screener.reward_risk_ratio", 2.0
    )

    stop_distance = atr * atr_multiplier
    if direction == Direction.LONG:
        stop_loss = entry_price - stop_distance
        target_price = entry_price + stop_distance * reward_risk_ratio
    else:
        stop_loss = entry_price + stop_distance
        target_price = entry_price - stop_distance * reward_risk_ratio

    return StopTarget(entry_price, stop_loss, target_price, stop_distance)


def update_trailing_stop(
    current_stop: float,
    current_price: float,
    atr: float,
    direction: Direction = Direction.LONG,
    atr_multiplier: float | None = None,
) -> float:
    """Ratchets the stop in the trade's favor only — never loosens it, even if the new ATR-
    implied stop would be worse than the existing one.
    """
    atr_multiplier = atr_multiplier if atr_multiplier is not None else settings.get(
        "risk_management.atr_multiplier", 2.0
    )
    stop_distance = atr * atr_multiplier

    if direction == Direction.LONG:
        return max(current_stop, current_price - stop_distance)
    return min(current_stop, current_price + stop_distance)
