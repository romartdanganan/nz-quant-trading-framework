import pytest

from strategy_research.registry import StrategyNotFound, StrategyRegistry
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def make_spec(url: str = "https://example.com/x") -> StrategySpec:
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


def test_add_candidate_and_persist_round_trip(tmp_path):
    path = tmp_path / "registry.json"
    registry = StrategyRegistry(path)
    registry.add_candidate(make_spec())
    registry.save()

    reloaded = StrategyRegistry(path)
    candidates = reloaded.list(status="candidate")

    assert len(candidates) == 1
    assert candidates[0]["name"] == "test"
    assert candidates[0]["status"] == "candidate"


def test_seen_source_urls(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(make_spec(url="https://example.com/y"))

    assert "https://example.com/y" in registry.seen_source_urls()


def test_list_filters_by_status(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(make_spec(url="https://example.com/a"))

    assert len(registry.list(status="candidate")) == 1
    assert len(registry.list(status="proven")) == 0


def test_promote_to_validated_updates_status_metrics_and_history(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec())

    registry.promote_to_validated(record["id"], {"sharpe_ratio": 2.0}, "passed all thresholds")

    updated = registry.get(record["id"])
    assert updated["status"] == "validated"
    assert updated["metrics"] == {"sharpe_ratio": 2.0}
    assert updated["history"][-1] == {"status": "validated", "reason": "passed all thresholds"}


def test_reject_updates_status_and_appends_history(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec())

    registry.reject(record["id"], "Sharpe too low")

    updated = registry.get(record["id"])
    assert updated["status"] == "rejected"
    assert updated["history"][-1] == {"status": "rejected", "reason": "Sharpe too low"}


def test_get_unknown_id_raises(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    with pytest.raises(StrategyNotFound):
        registry.get("does-not-exist")
