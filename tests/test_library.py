from strategies.library import classic_pairs_strategies, classic_single_ticker_strategies, seed_classic_strategies
from strategy_research.registry import StrategyRegistry


def test_seed_classic_strategies_adds_all_on_first_run(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")

    summary = seed_classic_strategies(registry)

    expected_count = len(classic_single_ticker_strategies()) + len(classic_pairs_strategies())
    assert summary["added"] == expected_count
    assert summary["skipped"] == 0
    assert len(registry.list(status="candidate")) == expected_count


def test_seed_classic_strategies_is_idempotent(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")

    seed_classic_strategies(registry)
    second_summary = seed_classic_strategies(registry)

    assert second_summary["added"] == 0
    expected_count = len(classic_single_ticker_strategies()) + len(classic_pairs_strategies())
    assert len(registry.list(status="candidate")) == expected_count  # no duplicates


def test_configured_pairs_produce_distinct_registry_entries():
    # regression test for the source_url collision bug: two different configured pairs
    # must not be treated as duplicates of each other.
    pairs = classic_pairs_strategies()
    source_urls = [spec.source_url for spec in pairs]
    assert len(source_urls) == len(set(source_urls))
