import pandas as pd

from backtester.data_loader import PriceDataUnavailable
from quant_engine.validation import runner
from quant_engine.validation.metrics import Metrics
from quant_engine.validation.validator import ValidationResult
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def make_spec(url: str) -> StrategySpec:
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


def test_run_validation_promotes_passing_and_rejects_failing(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record_pass = registry.add_candidate(make_spec("https://example.com/pass"))
    record_fail = registry.add_candidate(make_spec("https://example.com/fail"))

    monkeypatch.setattr(runner, "load_price_data", lambda ticker, start, end: pd.DataFrame({"close": [1, 2, 3]}))

    def fake_validate(spec, price_data):
        if spec.source_url.endswith("pass"):
            return ValidationResult(True, "ok", Metrics(2.0, 0.05, 2.0))
        return ValidationResult(False, "Sharpe too low", Metrics(0.5, 0.05, 2.0))

    monkeypatch.setattr(runner, "validate_strategy", fake_validate)

    summary = runner.run_validation(registry=registry)

    assert summary == {"candidates": 2, "validated": 1, "rejected": 1, "errored": 0}
    assert registry.get(record_pass["id"])["status"] == "validated"
    assert registry.get(record_fail["id"])["status"] == "rejected"


def test_run_validation_with_no_candidates_is_a_noop(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    summary = runner.run_validation(registry=registry)
    assert summary == {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}


def test_run_validation_handles_missing_price_data(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(make_spec("https://example.com/a"))

    def raise_unavailable(ticker, start, end):
        raise PriceDataUnavailable("no data")

    monkeypatch.setattr(runner, "load_price_data", raise_unavailable)

    summary = runner.run_validation(registry=registry)

    assert summary == {"candidates": 1, "validated": 0, "rejected": 0, "errored": 1}
