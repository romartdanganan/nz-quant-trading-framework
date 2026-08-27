import pytest

from execution_ibkr import ibkr_connector
from risk_management.circuit_breakers import CircuitBreakerViolation


class FakeAccountValue:
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


class FakeIB:
    def __init__(self, equity):
        self._equity = equity
        self._next_id = 1000
        self.placed_orders = []

    def accountSummary(self):
        return [FakeAccountValue("NetLiquidation", str(self._equity))]

    class _Client:
        def __init__(self, outer):
            self._outer = outer

        def getReqId(self):
            self._outer._next_id += 1
            return self._outer._next_id

    @property
    def client(self):
        return FakeIB._Client(self)

    def placeOrder(self, contract, order):
        self.placed_orders.append((contract, order))


def _patch_max_position_size(monkeypatch, pct):
    from config.settings import settings

    monkeypatch.setattr(
        settings,
        "get",
        lambda key, default=None: {"risk_management.max_position_size_pct": pct}.get(key, default),
    )


def test_build_bracket_order_links_no_connection_needed():
    parent, take_profit, stop_loss = ibkr_connector.build_bracket_order("BUY", 10, 110.0, 95.0)

    assert parent.action == "BUY"
    assert parent.orderType == "MKT"
    assert parent.totalQuantity == 10
    assert take_profit.action == "SELL"
    assert take_profit.lmtPrice == 110.0
    assert stop_loss.action == "SELL"
    assert stop_loss.auxPrice == 95.0


def test_get_account_equity_reads_net_liquidation():
    ib = FakeIB(equity=50_000)
    assert ibkr_connector.get_account_equity(ib) == 50_000.0


def test_submit_bracket_order_enforces_position_size_limit(monkeypatch):
    _patch_max_position_size(monkeypatch, 0.01)
    ib = FakeIB(equity=1_000.0)  # 1% cap = $10; order is 100*$100 = $10,000

    with pytest.raises(CircuitBreakerViolation):
        ibkr_connector.submit_bracket_order("AAPL", 100, 100.0, 95.0, 110.0, ib=ib)

    assert ib.placed_orders == []


def test_submit_bracket_order_places_three_linked_orders(monkeypatch):
    _patch_max_position_size(monkeypatch, 1.0)
    ib = FakeIB(equity=100_000.0)

    result = ibkr_connector.submit_bracket_order("AAPL", 10, 100.0, 95.0, 110.0, ib=ib)

    assert len(ib.placed_orders) == 3
    assert len(result.order_ids) == 3
    parent_order = ib.placed_orders[0][1]
    take_profit_order = ib.placed_orders[1][1]
    stop_loss_order = ib.placed_orders[2][1]
    assert take_profit_order.parentId == parent_order.orderId
    assert stop_loss_order.parentId == parent_order.orderId
