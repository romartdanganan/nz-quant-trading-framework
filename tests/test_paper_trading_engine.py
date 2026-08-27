import pandas as pd
import pytest

from backtester.data_loader import PriceDataUnavailable
from execution_alpaca import paper_trading_engine as engine
from risk_management.circuit_breakers import CircuitBreakerViolation
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def make_spec() -> StrategySpec:
    return StrategySpec(
        name="test",
        archetype=Archetype.MOMENTUM,
        entry_conditions=[Condition(Indicator.MACD, Operator.CROSSES_ABOVE, 0.0)],
        exit_conditions=[Condition(Indicator.MACD, Operator.CROSSES_BELOW, 0.0)],
        timeframe="1d",
        source_url="https://example.com",
        extraction_method="rule",
        confidence=0.9,
    )


def make_price_data(close_price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=30, freq="D")
    return pd.DataFrame(
        {"open": close_price, "high": close_price + 1, "low": close_price - 1, "close": close_price, "volume": 1000},
        index=idx,
    )


def _patch_signals(monkeypatch, entry: bool, exit_: bool):
    def fake_generate_signals(spec, price_data):
        return pd.DataFrame(
            {"entry_signal": [entry] * len(price_data), "exit_signal": [exit_] * len(price_data)},
            index=price_data.index,
        )

    monkeypatch.setattr(engine, "generate_signals", fake_generate_signals)


def test_run_incubation_cycle_with_no_records_is_noop(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    assert engine.run_incubation_cycle(registry=registry) == {"records": 0, "processed": 0, "errored": 0}


def test_run_incubation_cycle_handles_missing_price_data(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec())
    registry.promote_to_validated(record["id"], {"sharpe_ratio": 2.0, "max_drawdown_pct": 0.05}, "ok")
    registry.start_incubation(record["id"])

    def raise_unavailable(ticker, start, end):
        raise PriceDataUnavailable("no data")

    monkeypatch.setattr(engine, "load_price_data", raise_unavailable)

    summary = engine.run_incubation_cycle(registry=registry)
    assert summary == {"records": 1, "processed": 0, "errored": 1}


def test_process_one_cycle_opens_position_on_entry_signal(monkeypatch):
    _patch_signals(monkeypatch, entry=True, exit_=False)
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: None)  # no Alpaca -> shadow mode

    record = make_spec().to_dict()
    price_data = make_price_data(close_price=100.0)

    engine._process_one_cycle(record, price_data)

    assert record["incubation_position"] is not None
    assert record["incubation_position"]["entry_price"] == 100.0
    assert record["incubation_log"][-1]["equity"] == pytest.approx(engine.SIMULATED_STARTING_EQUITY)


def test_process_one_cycle_holds_position_when_no_exit_signal(monkeypatch):
    _patch_signals(monkeypatch, entry=False, exit_=False)
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: None)

    record = make_spec().to_dict()
    record["incubation_position"] = {"shares": 10.0, "entry_price": 100.0, "stop_loss": 90.0, "target_price": 120.0}
    record["incubation_starting_equity"] = 100_000.0
    record["incubation_realized_pnl"] = 0.0
    price_data = make_price_data(close_price=105.0)

    engine._process_one_cycle(record, price_data)

    assert record["incubation_position"] is not None
    assert record["incubation_log"][-1]["equity"] == pytest.approx(100_000.0 + 10 * (105 - 100))


def test_process_one_cycle_closes_on_strategy_exit_signal(monkeypatch):
    _patch_signals(monkeypatch, entry=False, exit_=True)
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: None)

    record = make_spec().to_dict()
    record["incubation_position"] = {"shares": 10.0, "entry_price": 100.0, "stop_loss": 90.0, "target_price": 120.0}
    record["incubation_starting_equity"] = 100_000.0
    record["incubation_realized_pnl"] = 0.0
    price_data = make_price_data(close_price=110.0)

    engine._process_one_cycle(record, price_data)

    assert record["incubation_position"] is None
    assert record["incubation_realized_pnl"] == pytest.approx(100.0)
    assert record["incubation_trades"][-1]["pnl"] == pytest.approx(100.0)


def test_process_one_cycle_closes_on_stop_loss_hit(monkeypatch):
    _patch_signals(monkeypatch, entry=False, exit_=False)  # no strategy exit signal at all
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: None)

    record = make_spec().to_dict()
    record["incubation_position"] = {"shares": 10.0, "entry_price": 100.0, "stop_loss": 90.0, "target_price": 120.0}
    record["incubation_starting_equity"] = 100_000.0
    record["incubation_realized_pnl"] = 0.0
    price_data = make_price_data(close_price=88.0)  # below stop

    engine._process_one_cycle(record, price_data)

    assert record["incubation_position"] is None
    assert record["incubation_realized_pnl"] == pytest.approx(-120.0)


def test_process_one_cycle_does_not_open_without_entry_signal(monkeypatch):
    _patch_signals(monkeypatch, entry=False, exit_=False)
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: None)

    record = make_spec().to_dict()
    price_data = make_price_data(close_price=100.0)

    engine._process_one_cycle(record, price_data)

    assert record.get("incubation_position") is None


def test_open_position_places_real_order_when_alpaca_configured(monkeypatch):
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: "fake-key")
    calls = []
    monkeypatch.setattr(engine, "submit_bracket_order", lambda **kwargs: calls.append(kwargs))

    record = {"incubation_starting_equity": 100_000.0, "incubation_realized_pnl": 0.0, "ticker": "AAPL"}
    position = engine._open_position(record, close_price=100.0, atr=2.0)

    assert position is not None
    assert len(calls) == 1
    assert calls[0]["ticker"] == "AAPL"


def test_open_position_blocked_by_circuit_breaker_returns_none(monkeypatch):
    monkeypatch.setattr(engine, "get_env", lambda key, default=None: "fake-key")

    def raise_violation(**kwargs):
        raise CircuitBreakerViolation("blocked")

    monkeypatch.setattr(engine, "submit_bracket_order", raise_violation)

    record = {"incubation_starting_equity": 100_000.0, "incubation_realized_pnl": 0.0, "ticker": "AAPL"}
    position = engine._open_position(record, close_price=100.0, atr=2.0)

    assert position is None
