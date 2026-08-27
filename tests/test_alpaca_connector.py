import pytest

from execution_alpaca import alpaca_connector
from risk_management.circuit_breakers import CircuitBreakerViolation


class FakeAccount:
    def __init__(self, equity):
        self.equity = equity


class FakeOrder:
    def __init__(self, id_, status):
        self.id = id_
        self.status = status


class FakeClient:
    def __init__(self, equity):
        self._equity = equity
        self.submitted_orders = []

    def get_account(self):
        return FakeAccount(self._equity)

    def submit_order(self, order_data):
        self.submitted_orders.append(order_data)
        return FakeOrder("order-123", "accepted")

    def get_all_positions(self):
        return []


def _patch_max_position_size(monkeypatch, pct):
    monkeypatch.setattr(
        alpaca_connector.settings,
        "get",
        lambda key, default=None: {"risk_management.max_position_size_pct": pct}.get(key, default),
    )


def test_get_account_equity_reads_from_client():
    client = FakeClient(equity=100_000)
    assert alpaca_connector.get_account_equity(client) == 100_000.0


def test_submit_bracket_order_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(alpaca_connector, "get_env", lambda key, default=None: None)

    with pytest.raises(alpaca_connector.AlpacaNotConfigured):
        alpaca_connector.submit_bracket_order("AAPL", 10, 100.0, 95.0, 110.0)


def test_submit_bracket_order_enforces_position_size_limit(monkeypatch):
    _patch_max_position_size(monkeypatch, 0.01)
    client = FakeClient(equity=1_000.0)  # 1% cap = $10; order is 100*$100 = $10,000

    with pytest.raises(CircuitBreakerViolation):
        alpaca_connector.submit_bracket_order("AAPL", 100, 100.0, 95.0, 110.0, client=client)

    assert client.submitted_orders == []  # never reached the broker


def test_submit_bracket_order_places_bracket_with_stop_and_target(monkeypatch):
    _patch_max_position_size(monkeypatch, 1.0)
    client = FakeClient(equity=100_000.0)

    result = alpaca_connector.submit_bracket_order("AAPL", 10, 100.0, 95.0, 110.0, client=client)

    assert result.order_id == "order-123"
    assert len(client.submitted_orders) == 1
    request = client.submitted_orders[0]
    assert request.symbol == "AAPL"
    assert request.qty == 10
    assert request.stop_loss.stop_price == 95.0
    assert request.take_profit.limit_price == 110.0
