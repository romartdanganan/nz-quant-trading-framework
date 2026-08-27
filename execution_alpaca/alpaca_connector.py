"""Alpaca paper/live trading connector (alpaca-py). Every order placed through here is a
bracket order — entry + a mandatory stop-loss + take-profit — this module refuses to place
a naked order, enforcing CLAUDE.md's hardcoded circuit breakers at the one place orders
actually leave the system. Defaults to paper trading (config broker.alpaca.account_type);
requires ALPACA_API_KEY/ALPACA_SECRET_KEY in .env.

Not live-tested: this repo has no Alpaca API credentials configured. The connector is unit-
tested against a mocked TradingClient; verifying it against a real paper account is up to
whoever configures ALPACA_API_KEY/ALPACA_SECRET_KEY.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.settings import get_env, settings
from risk_management.circuit_breakers import OrderRequest, check_order


class AlpacaNotConfigured(RuntimeError):
    """Raised when ALPACA_API_KEY/ALPACA_SECRET_KEY are not set in .env."""


def _get_client():
    api_key = get_env("ALPACA_API_KEY")
    secret_key = get_env("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise AlpacaNotConfigured("ALPACA_API_KEY/ALPACA_SECRET_KEY are not set in .env")

    from alpaca.trading.client import TradingClient

    is_paper = settings.get("broker.alpaca.account_type", "paper") != "live"
    return TradingClient(api_key=api_key, secret_key=secret_key, paper=is_paper)


@dataclass(frozen=True)
class BracketOrderResult:
    order_id: str
    status: str


def get_account_equity(client=None) -> float:
    client = client or _get_client()
    return float(client.get_account().equity)


def get_positions(client=None) -> list:
    client = client or _get_client()
    return client.get_all_positions()


def submit_bracket_order(
    ticker: str,
    shares: float,
    entry_price_estimate: float,
    stop_loss: float,
    take_profit: float,
    side: str = "buy",
    daily_loss_tracker=None,
    client=None,
) -> BracketOrderResult:
    """Places a market-entry bracket order. Runs the hardcoded circuit breakers (position
    size ceiling, mandatory stop-loss, and — if a tracker is supplied — the daily-loss
    halt) before submitting anything to Alpaca.
    """
    client = client or _get_client()
    equity = get_account_equity(client)

    order_request = OrderRequest(
        ticker=ticker, shares=shares, price=entry_price_estimate, stop_loss=stop_loss
    )
    check_order(order_request, equity, daily_loss_tracker)

    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest

    request = MarketOrderRequest(
        symbol=ticker,
        qty=shares,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        stop_loss=StopLossRequest(stop_price=stop_loss),
        take_profit=TakeProfitRequest(limit_price=take_profit),
    )
    order = client.submit_order(order_data=request)
    return BracketOrderResult(order_id=str(order.id), status=str(order.status))
