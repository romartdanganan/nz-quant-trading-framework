"""ATR-based and Kelly-criterion position sizing, hard-capped by
risk_management.max_position_size_pct — a ceiling this math can never exceed (CLAUDE.md
"Hardcoded risk circuit breakers": never AI-adjusted, never overridden by what the sizing
math outputs). All math here is deterministic Python — no LLM anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings


@dataclass(frozen=True)
class PositionSizeResult:
    shares: float
    position_value: float
    pct_of_equity: float
    capped_by_max_position_size: bool


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Classic Kelly formula: f* = W - (1-W)/R, where R = avg_win / avg_loss (avg_loss and
    avg_win both > 0). Returns 0.0 on bad/no-edge inputs rather than a negative allocation.
    """
    if avg_loss <= 0 or avg_win <= 0 or not (0.0 <= win_rate <= 1.0):
        return 0.0
    reward_risk_ratio = avg_win / avg_loss
    fraction = win_rate - (1 - win_rate) / reward_risk_ratio
    return max(0.0, fraction)


def kelly_fraction_from_trades(trades: list[dict]) -> float:
    """Derives win_rate/avg_win/avg_loss from a closed-trade list (same shape as
    backtester's BacktestResult.trades) and applies kelly_fraction.
    """
    if not trades:
        return 0.0

    pnls = [trade.get("pnl_comm", trade.get("pnl", 0.0)) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [-pnl for pnl in pnls if pnl < 0]

    win_rate = len(wins) / len(pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return kelly_fraction(win_rate, avg_win, avg_loss)


def calculate_position_size(
    equity: float,
    price: float,
    atr: float,
    trades: list[dict] | None = None,
    method: str | None = None,
) -> PositionSizeResult:
    """method: "atr" | "kelly" | "atr_kelly" (default from config). "atr_kelly" takes the
    *smaller* of the two sizes — if the backtested Kelly fraction shows no edge (0.0), the
    combined method sizes to zero rather than trading on ATR risk-normalization alone.
    """
    method = method or settings.get("risk_management.position_sizing_method", "atr_kelly")
    max_risk_per_trade_pct = settings.get("risk_management.max_risk_per_trade_pct", 0.01)
    atr_multiplier = settings.get("risk_management.atr_multiplier", 2.0)
    kelly_fraction_cap = settings.get("risk_management.kelly_fraction_cap", 0.5)
    max_position_size_pct = settings.get("risk_management.max_position_size_pct", 0.05)

    stop_distance = atr * atr_multiplier
    atr_shares = (equity * max_risk_per_trade_pct) / stop_distance if stop_distance > 0 else 0.0

    kelly_shares = 0.0
    if trades and price > 0:
        fraction = min(kelly_fraction_from_trades(trades), kelly_fraction_cap)
        kelly_shares = (equity * fraction) / price

    if method == "atr":
        shares = atr_shares
    elif method == "kelly":
        shares = kelly_shares
    else:
        shares = min(atr_shares, kelly_shares) if trades else atr_shares

    position_value = shares * price
    max_position_value = equity * max_position_size_pct
    capped = position_value > max_position_value

    if capped and price > 0:
        shares = max_position_value / price
        position_value = shares * price

    pct_of_equity = position_value / equity if equity > 0 else 0.0
    return PositionSizeResult(
        shares=shares,
        position_value=position_value,
        pct_of_equity=pct_of_equity,
        capped_by_max_position_size=capped,
    )
