from strategy_research import pipeline
from strategy_research.registry import StrategyRegistry
from strategy_research.scrapers.models import RawSource

MEAN_REVERSION_TEXT = (
    "This mean reversion strategy buys when RSI is below 30 and sells when RSI is above 70."
)
MOMENTUM_TEXT = "This momentum strategy: MACD crosses above signal, exit when MACD crosses below signal."


def _patch_config(monkeypatch, tmp_path, **overrides):
    values = {
        "research_pipeline.max_sources_per_run": 25,
        "research_pipeline.use_gemini_fallback": False,
        "research_pipeline.max_gemini_calls_per_run": 0,
        "research_pipeline.seen_sources_cache": str(tmp_path / "seen.json"),
    }
    values.update(overrides)
    monkeypatch.setattr(pipeline.settings, "get", lambda key, default=None: values.get(key, default))


def test_pipeline_accepts_rule_extractable_source(tmp_path, monkeypatch):
    source = RawSource(text=MEAN_REVERSION_TEXT, url="https://example.com/a", title="idea")
    monkeypatch.setattr(pipeline, "collect_raw_sources", lambda max_sources: [source])
    _patch_config(monkeypatch, tmp_path)

    registry = StrategyRegistry(tmp_path / "registry.json")
    summary = pipeline.run(registry=registry)

    assert summary["candidates_accepted"] == 1
    assert summary["sources_new"] == 1
    assert len(registry.list(status="candidate")) == 1


def test_pipeline_dedups_previously_seen_sources_across_runs(tmp_path, monkeypatch):
    source = RawSource(text=MOMENTUM_TEXT, url="https://example.com/b", title="idea")
    monkeypatch.setattr(pipeline, "collect_raw_sources", lambda max_sources: [source])
    _patch_config(monkeypatch, tmp_path)

    registry = StrategyRegistry(tmp_path / "registry.json")
    first = pipeline.run(registry=registry)
    second = pipeline.run(registry=registry)

    assert first["sources_new"] == 1
    assert second["sources_new"] == 0
    assert len(registry.list(status="candidate")) == 1


def test_pipeline_skips_low_confidence_source_without_gemini(tmp_path, monkeypatch):
    source = RawSource(text="I like turtles.", url="https://example.com/c", title="idea")
    monkeypatch.setattr(pipeline, "collect_raw_sources", lambda max_sources: [source])
    _patch_config(monkeypatch, tmp_path)

    registry = StrategyRegistry(tmp_path / "registry.json")
    summary = pipeline.run(registry=registry)

    assert summary["candidates_accepted"] == 0
    assert summary["sources_skipped"] == 1
    assert registry.list(status="candidate") == []
