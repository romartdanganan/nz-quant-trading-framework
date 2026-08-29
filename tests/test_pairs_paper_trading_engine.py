import numpy as np
import pandas as pd
import pytest

from backtester.data_loader import PriceDataUnavailable
from execution_alpaca import pairs_paper_trading_engine as engine
from strategies.pairs_trading.strategy import build_pairs_spec
from strategy_research.registry import StrategyRegistry


def make_price_series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx)


def test_run_pairs_incubation_cycle_with_no_records_is_noop(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    assert engine.run_pairs_incubation_cycle(registry=registry) == {"records": 0, "processed": 0, "errored": 0, "events": []}


def test_run_pairs_incubation_cycle_ignores_single_ticker_candidates(tmp_path):
    from strategies.mean_reversion.strategy import classic_rsi_reversion

    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(classic_rsi_reversion())

    assert engine.run_pairs_incubation_cycle(registry=registry) == {"records": 0, "processed": 0, "errored": 0, "events": []}


def test_run_pairs_incubation_cycle_handles_missing_price_data(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(build_pairs_spec("KO", "PEP"))
    registry.promote_to_validated(record["id"], {"sharpe_ratio": 2.0, "max_drawdown_pct": 0.05}, "ok")
    registry.start_incubation(record["id"])

    def raise_unavailable(ticker, start, end):
        raise PriceDataUnavailable("no data")

    monkeypatch.setattr(engine, "load_price_data", raise_unavailable)

    summary = engine.run_pairs_incubation_cycle(registry=registry)
    assert summary == {"records": 1, "processed": 0, "errored": 1, "events": []}


def test_process_one_cycle_opens_position_on_entry_zscore():
    spec = build_pairs_spec("A", "B", lookback_period=5, entry_zscore=1.0, exit_zscore=0.3)
    # spread trending down hard at the end -> strongly negative z-score -> long-spread entry
    price_b = make_price_series([100.0] * 10)
    price_a = make_price_series([150.0] * 8 + [140.0, 130.0])

    record = {}
    engine._process_one_cycle(record, spec, price_a, price_b)

    assert record["incubation_position"] is not None
    assert record["incubation_position"]["direction"] == 1
    assert record["incubation_log"][-1]["equity"] == pytest.approx(engine.SIMULATED_STARTING_EQUITY)


def test_process_one_cycle_holds_position_when_zscore_stays_extreme():
    spec = build_pairs_spec("A", "B", lookback_period=5, entry_zscore=1.0, exit_zscore=0.3)
    price_b = make_price_series([100.0] * 10)
    price_a = make_price_series([150.0] * 8 + [140.0, 130.0])

    record = {"incubation_position": {"direction": 1, "entry_spread": 20.0, "hedge_ratio": 1.5}}
    engine._process_one_cycle(record, spec, price_a, price_b)

    assert record["incubation_position"] is not None  # still open, z-score still extreme


def test_process_one_cycle_holds_when_zscore_is_nan(monkeypatch):
    # a perfectly flat/degenerate spread has zero variance -> NaN z-score (0/0), which
    # must neither open nor force-close a position — it means "can't tell," not "flat."
    spec = build_pairs_spec("A", "B", lookback_period=5, entry_zscore=2.0, exit_zscore=0.3)
    price_a = make_price_series([100.0] * 10)
    price_b = make_price_series([100.0] * 10)

    monkeypatch.setattr(engine, "compute_hedge_ratio", lambda a, b: 1.0)
    monkeypatch.setattr(engine, "compute_spread", lambda a, b, h: pd.Series([0.0] * len(a), index=a.index))
    monkeypatch.setattr(engine, "compute_zscore", lambda spread, lookback: pd.Series([float("nan")] * len(spread), index=spread.index))

    record = {"incubation_position": {"direction": 1, "entry_spread": 45.0, "hedge_ratio": 1.5}}
    engine._process_one_cycle(record, spec, price_a, price_b)

    assert record["incubation_position"] == {"direction": 1, "entry_spread": 45.0, "hedge_ratio": 1.5}


def test_process_one_cycle_closes_and_realizes_pnl_on_revert(monkeypatch):
    spec = build_pairs_spec("A", "B", lookback_period=5, entry_zscore=2.0, exit_zscore=0.3)
    price_a = make_price_series([100.0] * 10)
    price_b = make_price_series([100.0] * 10)

    monkeypatch.setattr(engine, "compute_hedge_ratio", lambda a, b: 1.0)
    monkeypatch.setattr(engine, "compute_spread", lambda a, b, h: pd.Series([5.0] * len(a), index=a.index))
    monkeypatch.setattr(engine, "compute_zscore", lambda spread, lookback: pd.Series([0.1] * len(spread), index=spread.index))

    record = {
        "incubation_position": {"direction": 1, "entry_spread": 20.0, "hedge_ratio": 1.5},
        "incubation_starting_equity": 100_000.0,
        "incubation_realized_pnl": 0.0,
    }
    engine._process_one_cycle(record, spec, price_a, price_b)

    assert record["incubation_position"] is None
    assert record["incubation_trades"][-1]["pnl"] == pytest.approx(1 * (5.0 - 20.0))
    assert record["incubation_realized_pnl"] == pytest.approx(-15.0)
