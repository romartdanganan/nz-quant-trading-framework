from datetime import date, timedelta

import pytest

from config.settings import settings
from quant_engine.validation.incubation import (
    evaluate_incubation,
    process_incubating_strategies,
    record_snapshot,
    start_incubation_for_validated,
)
from strategy_research.registry import InvalidTransition, StrategyRegistry
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def _patch_incubation_config(monkeypatch, **overrides):
    defaults = {
        "min_days": 60,
        "min_trades": 20,
        "max_sharpe_decay_pct": 0.30,
        "max_drawdown_overshoot_pct": 0.05,
    }
    merged = {**defaults, **overrides}
    values = {f"incubation.{key}": value for key, value in merged.items()}
    monkeypatch.setattr(settings, "get", lambda key, default=None: values.get(key, default))


def make_spec(url="https://example.com/x") -> StrategySpec:
    return StrategySpec(
        name="test",
        archetype=Archetype.MOMENTUM,
        entry_conditions=[Condition(Indicator.MACD, Operator.CROSSES_ABOVE, 0.0)],
        exit_conditions=[Condition(Indicator.MACD, Operator.CROSSES_BELOW, 0.0)],
        timeframe="1d",
        source_url=url,
        extraction_method="rule",
        confidence=0.9,
    )


def test_record_snapshot_appends_log_and_trade():
    record = {}
    record_snapshot(record, equity_value=101_000.0, as_of=date(2026, 1, 1), trade={"pnl": 500})

    assert record["incubation_log"] == [{"date": "2026-01-01", "equity": 101_000.0}]
    assert record["incubation_trades"] == [{"pnl": 500}]


def test_record_snapshot_without_trade_does_not_touch_trades_list():
    record = {}
    record_snapshot(record, equity_value=100_000.0, as_of=date(2026, 1, 1))
    assert "incubation_trades" not in record


def test_evaluate_incubation_continues_with_insufficient_data():
    record = {"incubation_log": [{"date": "2026-01-01", "equity": 100_000.0}]}
    decision = evaluate_incubation(record)
    assert decision.action == "continue"


def test_evaluate_incubation_rejects_on_sharpe_decay(monkeypatch):
    _patch_incubation_config(monkeypatch, max_sharpe_decay_pct=0.30)
    start = (date.today() - timedelta(days=5)).isoformat()
    # flat/declining equity -> ~zero or negative Sharpe, well below 70% of a strong baseline
    record = {
        "incubation_start_date": start,
        "baseline_metrics": {"sharpe_ratio": 2.0, "max_drawdown_pct": 0.05},
        "incubation_log": [
            {"date": "2026-01-01", "equity": 100_000.0},
            {"date": "2026-01-02", "equity": 99_500.0},
            {"date": "2026-01-03", "equity": 99_000.0},
        ],
        "incubation_trades": [],
    }
    decision = evaluate_incubation(record)
    assert decision.action == "reject"
    assert "Sharpe" in decision.reason


def test_evaluate_incubation_rejects_on_drawdown_overshoot(monkeypatch):
    _patch_incubation_config(monkeypatch, max_drawdown_overshoot_pct=0.05)
    start = (date.today() - timedelta(days=5)).isoformat()
    record = {
        "incubation_start_date": start,
        "baseline_metrics": {"sharpe_ratio": 0.0, "max_drawdown_pct": 0.05},
        "incubation_log": [
            {"date": "2026-01-01", "equity": 100_000.0},
            {"date": "2026-01-02", "equity": 80_000.0},  # 20% drawdown >> 5%+5% tolerance
        ],
        "incubation_trades": [],
    }
    decision = evaluate_incubation(record)
    assert decision.action == "reject"
    assert "MaxDD" in decision.reason


def test_evaluate_incubation_continues_when_healthy_but_not_enough_time(monkeypatch):
    _patch_incubation_config(monkeypatch, min_days=60, min_trades=20)
    start = (date.today() - timedelta(days=5)).isoformat()
    record = {
        "incubation_start_date": start,
        "baseline_metrics": {"sharpe_ratio": 0.0, "max_drawdown_pct": 0.05},
        "incubation_log": [
            {"date": "2026-01-01", "equity": 100_000.0},
            {"date": "2026-01-02", "equity": 100_500.0},
        ],
        "incubation_trades": [],
    }
    decision = evaluate_incubation(record)
    assert decision.action == "continue"
    assert "5/60 days" in decision.reason


def test_evaluate_incubation_promotes_when_criteria_met(monkeypatch):
    _patch_incubation_config(monkeypatch, min_days=30, min_trades=1)
    start = (date.today() - timedelta(days=45)).isoformat()
    record = {
        "incubation_start_date": start,
        "baseline_metrics": {"sharpe_ratio": 0.0, "max_drawdown_pct": 0.05},
        "incubation_log": [
            {"date": "2026-01-01", "equity": 100_000.0},
            {"date": "2026-01-02", "equity": 100_500.0},
            {"date": "2026-01-03", "equity": 101_000.0},
        ],
        "incubation_trades": [{"pnl": 500}],
    }
    decision = evaluate_incubation(record)
    assert decision.action == "promote"


def test_registry_start_incubation_requires_validated_status(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec())  # status is "candidate", not "validated"

    with pytest.raises(InvalidTransition):
        registry.start_incubation(record["id"])


def test_registry_start_incubation_captures_baseline(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec())
    registry.promote_to_validated(record["id"], {"sharpe_ratio": 2.0}, "ok")

    updated = registry.start_incubation(record["id"])

    assert updated["status"] == "incubating"
    assert updated["baseline_metrics"] == {"sharpe_ratio": 2.0}
    assert updated["incubation_log"] == []


def test_start_incubation_for_validated_processes_all(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record_a = registry.add_candidate(make_spec("https://example.com/a"))
    record_b = registry.add_candidate(make_spec("https://example.com/b"))
    registry.promote_to_validated(record_a["id"], {"sharpe_ratio": 2.0}, "ok")
    registry.promote_to_validated(record_b["id"], {"sharpe_ratio": 1.8}, "ok")

    summary = start_incubation_for_validated(registry)

    assert summary == {"started": 2}
    assert registry.get(record_a["id"])["status"] == "incubating"
    assert registry.get(record_b["id"])["status"] == "incubating"


def test_process_incubating_strategies_dispatches_by_decision(tmp_path, monkeypatch):
    _patch_incubation_config(monkeypatch, min_days=30, min_trades=1)
    registry = StrategyRegistry(tmp_path / "registry.json")

    promote_record = registry.add_candidate(make_spec("https://example.com/promote"))
    registry.promote_to_validated(promote_record["id"], {"sharpe_ratio": 0.0, "max_drawdown_pct": 0.05}, "ok")
    registry.start_incubation(promote_record["id"])
    promote_record = registry.get(promote_record["id"])
    promote_record["incubation_start_date"] = (date.today() - timedelta(days=45)).isoformat()
    record_snapshot(promote_record, 100_000.0, date.today() - timedelta(days=2))
    record_snapshot(promote_record, 101_000.0, date.today() - timedelta(days=1), trade={"pnl": 1000})

    reject_record = registry.add_candidate(make_spec("https://example.com/reject"))
    registry.promote_to_validated(reject_record["id"], {"sharpe_ratio": 3.0, "max_drawdown_pct": 0.05}, "ok")
    registry.start_incubation(reject_record["id"])
    reject_record = registry.get(reject_record["id"])
    record_snapshot(reject_record, 100_000.0, date.today() - timedelta(days=2))
    record_snapshot(reject_record, 50_000.0, date.today() - timedelta(days=1))  # catastrophic drawdown

    summary = process_incubating_strategies(registry)

    assert summary["promoted"] == 1
    assert summary["rejected"] == 1
    assert registry.get(promote_record["id"])["status"] == "proven"
    assert registry.get(reject_record["id"])["status"] == "rejected"
