import numpy as np
import pandas as pd
import pytest

from backtester.data_loader import PriceDataUnavailable
from strategy_research.generator import pattern_miner
from strategy_research.generator.pattern_miner import Hypothesis
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import Archetype, Indicator, Operator


def test_bucket_hypotheses_detects_real_bounce_relationship():
    rng = np.random.default_rng(42)
    n = 500
    value = pd.Series(rng.normal(size=n))
    # Strong deterministic negative relationship (return falls as value rises) plus tiny
    # noise: the bottom decile (lowest value) should show a clearly significant bounce, and
    # the top decile should show no continuation edge (forward return is actually lower there).
    forward_return = pd.Series(-0.02 * value + rng.normal(scale=0.001, size=n))

    hypotheses = pattern_miner._bucket_hypotheses(
        value, forward_return, "TEST", Indicator.ZSCORE, 20, decile_count=10, min_bucket_size=20
    )

    bounce = next(h for h in hypotheses if h.direction == "bounce")
    continuation = next(h for h in hypotheses if h.direction == "continuation")

    assert bounce.p_value < 0.01
    assert bounce.entry_threshold < 0  # bottom decile of a standard normal is negative
    assert bounce.extreme_mean_return > bounce.baseline_mean_return
    assert continuation.p_value == 1.0  # forward return is lower there, not higher — no false signal


def test_bucket_hypotheses_returns_nothing_with_too_few_samples():
    value = pd.Series(np.arange(50, dtype=float))
    forward_return = pd.Series(np.arange(50, dtype=float))

    hypotheses = pattern_miner._bucket_hypotheses(
        value, forward_return, "TEST", Indicator.RSI, 14, decile_count=10, min_bucket_size=30
    )

    assert hypotheses == []


def _hypothesis(**overrides) -> Hypothesis:
    defaults = dict(
        ticker="GOOGL",
        indicator=Indicator.RSI,
        period=2,
        direction="bounce",
        p_value=0.001,
        entry_threshold=8.0,
        exit_threshold=50.0,
        extreme_mean_return=0.03,
        baseline_mean_return=0.005,
        sample_size=40,
    )
    defaults.update(overrides)
    return Hypothesis(**defaults)


def test_spec_from_hypothesis_bounce_is_mean_reversion():
    spec = pattern_miner._spec_from_hypothesis(_hypothesis())

    spec.validate()  # must not raise
    assert spec.archetype == Archetype.MEAN_REVERSION
    assert spec.entry_conditions[0].operator == Operator.LT
    assert spec.entry_conditions[0].threshold == 8.0
    assert spec.exit_conditions[0].operator == Operator.GT
    assert spec.exit_conditions[0].threshold == 50.0
    assert spec.source_url == "internal://pattern_mining/GOOGL/RSI/2/bounce"
    assert spec.confidence == pytest.approx(0.999)


def test_spec_from_hypothesis_continuation_is_momentum():
    spec = pattern_miner._spec_from_hypothesis(_hypothesis(direction="continuation", entry_threshold=92.0))

    spec.validate()
    assert spec.archetype == Archetype.MOMENTUM
    assert spec.entry_conditions[0].operator == Operator.GT
    assert spec.exit_conditions[0].operator == Operator.LT


def test_corrected_significance_bonferroni_and_none():
    assert pattern_miner._corrected_significance(0.05, 10, "bonferroni") == pytest.approx(0.005)
    assert pattern_miner._corrected_significance(0.05, 10, "none") == 0.05
    assert pattern_miner._corrected_significance(0.05, 0, "bonferroni") == 0.05  # never divide by zero


def test_run_accepts_significant_hypotheses_and_persists_family_size(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    stats_cache = tmp_path / "pattern_mining_stats.json"

    monkeypatch.setattr(pattern_miner, "load_price_data", lambda ticker, start, end: pd.DataFrame({"close": [1.0] * 5}))

    significant = _hypothesis(p_value=0.0001)
    insignificant = _hypothesis(period=5, p_value=0.9)

    def fake_test_hypotheses(ticker, indicator, period, close, forward_days, decile_count, min_bucket_size):
        return [significant] if period == 2 else [insignificant]

    monkeypatch.setattr(pattern_miner, "_test_hypotheses_for_series", fake_test_hypotheses)
    monkeypatch.setattr(
        pattern_miner.settings,
        "get",
        lambda key, default=None: "none" if key == "pattern_mining.multiple_testing_correction" else default,
    )

    summary = pattern_miner.run(registry=registry, universe=["GOOGL"], stats_cache_path=stats_cache)

    assert summary["candidates_accepted"] == 1
    assert summary["errored"] == 0
    assert summary["tickers_scanned"] == 1
    candidates = registry.list(status="candidate")
    assert len(candidates) == 1
    assert candidates[0]["source_url"] == "internal://pattern_mining/GOOGL/RSI/2/bounce"
    assert json_family_size(stats_cache) == summary["hypotheses_tested"]


def test_run_skips_already_seen_hypotheses(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    spec = pattern_miner._spec_from_hypothesis(_hypothesis())
    registry.add_candidate(spec)  # already registered under this exact source_url

    monkeypatch.setattr(pattern_miner, "load_price_data", lambda ticker, start, end: pd.DataFrame({"close": [1.0] * 5}))
    monkeypatch.setattr(
        pattern_miner, "_test_hypotheses_for_series", lambda *a, **k: [_hypothesis(p_value=0.0001)]
    )

    summary = pattern_miner.run(registry=registry, universe=["GOOGL"], stats_cache_path=tmp_path / "stats.json")

    assert summary["candidates_accepted"] == 0
    assert len(registry.list(status="candidate")) == 1  # unchanged


def test_run_handles_missing_price_data(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")

    def raise_unavailable(ticker, start, end):
        raise PriceDataUnavailable("no data")

    monkeypatch.setattr(pattern_miner, "load_price_data", raise_unavailable)

    summary = pattern_miner.run(registry=registry, universe=["GOOGL"], stats_cache_path=tmp_path / "stats.json")

    assert summary == {
        "tickers_scanned": 0,
        "hypotheses_tested": 0,
        "significance_used": pytest.approx(0.05),
        "candidates_accepted": 0,
        "errored": 1,
    }


def test_run_family_size_grows_across_runs_when_bonferroni_enabled(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    stats_cache = tmp_path / "stats.json"

    monkeypatch.setattr(pattern_miner, "load_price_data", lambda ticker, start, end: pd.DataFrame({"close": [1.0] * 5}))
    monkeypatch.setattr(
        pattern_miner, "_test_hypotheses_for_series", lambda *a, **k: [_hypothesis(p_value=0.9)]
    )

    first = pattern_miner.run(registry=registry, universe=["GOOGL"], stats_cache_path=stats_cache)
    second = pattern_miner.run(registry=registry, universe=["GOOGL"], stats_cache_path=stats_cache)

    assert second["significance_used"] < first["significance_used"]


def json_family_size(path) -> int:
    import json

    with open(path) as f:
        return json.load(f)["hypotheses_tested_total"]
