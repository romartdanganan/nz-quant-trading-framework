"""Interactive Brokers paper/live trading connector (ib_insync). Every order placed
through here is a bracket order — entry + a mandatory stop-loss + take-profit — same
circuit-breaker enforcement as execution_alpaca/.

Requires TWS or IB Gateway running locally with the API enabled. This cannot be exercised
in a sandboxed environment or CI runner at all — build_bracket_order() (pure order
construction) is unit-tested with no connection; submit_bracket_order() is unit-tested only
against a mocked `ib` object. Neither has been verified against a real TWS/Gateway session.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.settings import get_env
from risk_management.circuit_breakers import OrderRequest, check_order


def _get_connection():
    from ib_insync import IB

    ib = IB()
    host = get_env("IBKR_HOST", "127.0.0.1")
    port = int(get_env("IBKR_PORT", "7497"))
    client_id = int(get_env("IBKR_CLIENT_ID", "1"))
    ib.connect(host, port, clientId=client_id)
    return ib


@dataclass(frozen=True)
class BracketOrderResult:
    order_ids: list[int]


def get_account_equity(ib) -> float:
    values = ib.accountSummary()
    return next((float(v.value) for v in values if v.tag == "NetLiquidation"), 0.0)


def build_bracket_order(action: str, shares: float, take_profit: float, stop_loss: float):
    """Pure construction of the three linked orders (entry, take-profit, stop-loss) — no
    connection needed, so this half is fully unit-testable without TWS/Gateway running.
    orderId/parentId are left as placeholders; submit_bracket_order() fills in real IDs
    from the live connection immediately before placing them.
    """
    from ib_insync import LimitOrder, Order, StopOrder

    exit_action = "SELL" if action == "BUY" else "BUY"
    parent = Order(action=action, orderType="MKT", totalQuantity=shares, transmit=False)
    take_profit_order = LimitOrder(exit_action, shares, take_profit, transmit=False)
    stop_loss_order = StopOrder(exit_action, shares, stop_loss, transmit=True)
    return parent, take_profit_order, stop_loss_order


def submit_bracket_order(
    ticker: str,
    shares: float,
    entry_price_estimate: float,
    stop_loss: float,
    take_profit: float,
    action: str = "BUY",
    daily_loss_tracker=None,
    ib=None,
) -> BracketOrderResult:
    from ib_insync import Stock

    ib = ib or _get_connection()
    equity = get_account_equity(ib)

    order_request = OrderRequest(
        ticker=ticker, shares=shares, price=entry_price_estimate, stop_loss=stop_loss
    )
    check_order(order_request, equity, daily_loss_tracker)

    parent, take_profit_order, stop_loss_order = build_bracket_order(action, shares, take_profit, stop_loss)

    parent.orderId = ib.client.getReqId()
    take_profit_order.orderId = ib.client.getReqId()
    take_profit_order.parentId = parent.orderId
    stop_loss_order.orderId = ib.client.getReqId()
    stop_loss_order.parentId = parent.orderId

    contract = Stock(ticker, "SMART", "USD")
    order_ids = []
    for order in (parent, take_profit_order, stop_loss_order):
        ib.placeOrder(contract, order)
        order_ids.append(order.orderId)

    return BracketOrderResult(order_ids=order_ids)
