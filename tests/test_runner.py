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


def _patch_flat_universe_price_data(monkeypatch):
    monkeypatch.setattr(
        runner, "load_price_data", lambda ticker, start, end: pd.DataFrame({"close": [1, 2, 3]})
    )


def test_run_validation_promotes_using_best_passing_ticker(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record_pass = registry.add_candidate(make_spec("https://example.com/pass"))
    record_fail = registry.add_candidate(make_spec("https://example.com/fail"))

    _patch_flat_universe_price_data(monkeypatch)

    def fake_validate(spec, price_data):
        if spec.source_url.endswith("pass"):
            return ValidationResult(True, "ok", Metrics(2.0, 0.05, 2.0))
        return ValidationResult(False, "Sharpe too low", Metrics(0.5, 0.05, 2.0))

    monkeypatch.setattr(runner, "validate_strategy", fake_validate)

    summary = runner.run_validation(registry=registry, universe=["SPY", "AAPL"])

    assert summary == {"candidates": 2, "validated": 1, "rejected": 1, "errored": 0}
    passed = registry.get(record_pass["id"])
    assert passed["status"] == "validated"
    assert passed["ticker"] in ("SPY", "AAPL")
    assert registry.get(record_fail["id"])["status"] == "rejected"


def test_run_validation_picks_highest_sharpe_ticker_when_multiple_pass(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("https://example.com/multi"))

    def fake_validate(spec, price_data):
        # both tickers pass; AAPL has the better Sharpe and should be chosen
        sharpe = 1.6 if price_data is runner_price_data["SPY"] else 2.5
        return ValidationResult(True, "ok", Metrics(sharpe, 0.05, 2.0))

    # capture which DataFrame object corresponds to which ticker via load_price_data
    runner_price_data = {}

    def fake_load(ticker, start, end):
        df = pd.DataFrame({"close": [1, 2, 3]})
        runner_price_data[ticker] = df
        return df

    monkeypatch.setattr(runner, "load_price_data", fake_load)
    monkeypatch.setattr(runner, "validate_strategy", fake_validate)

    summary = runner.run_validation(registry=registry, universe=["SPY", "AAPL"])

    assert summary["validated"] == 1
    assert registry.get(record["id"])["ticker"] == "AAPL"


def test_run_validation_with_no_candidates_is_a_noop(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    summary = runner.run_validation(registry=registry)
    assert summary == {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}


def test_run_validation_ignores_pairs_candidates(tmp_path):
    from strategies.pairs_trading.strategy import build_pairs_spec

    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(build_pairs_spec("KO", "PEP"))  # kind="pairs" — must be skipped here

    summary = runner.run_validation(registry=registry)

    assert summary == {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}


def test_run_validation_handles_missing_price_data_for_entire_universe(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(make_spec("https://example.com/a"))

    def raise_unavailable(ticker, start, end):
        raise PriceDataUnavailable("no data")

    monkeypatch.setattr(runner, "load_price_data", raise_unavailable)

    summary = runner.run_validation(registry=registry, universe=["SPY", "AAPL"])

    assert summary == {"candidates": 1, "validated": 0, "rejected": 0, "errored": 1}


def test_run_validation_skips_tickers_with_missing_data_but_uses_the_rest(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("https://example.com/a"))

    def flaky_load(ticker, start, end):
        if ticker == "SPY":
            raise PriceDataUnavailable("no data for SPY")
        return pd.DataFrame({"close": [1, 2, 3]})

    monkeypatch.setattr(runner, "load_price_data", flaky_load)
    monkeypatch.setattr(runner, "validate_strategy", lambda spec, data: ValidationResult(True, "ok", Metrics(2.0, 0.05, 2.0)))

    summary = runner.run_validation(registry=registry, universe=["SPY", "AAPL"])

    assert summary["validated"] == 1
    assert registry.get(record["id"])["ticker"] == "AAPL"
