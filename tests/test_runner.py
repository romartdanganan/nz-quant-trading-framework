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

    # record_pass clears the bar on both universe tickers here, so both become validated
    # (one in-place, one cloned) instead of the pipeline keeping only a single winner.
    assert summary == {"candidates": 2, "validated": 2, "rejected": 1, "errored": 0}
    passed = registry.get(record_pass["id"])
    assert passed["status"] == "validated"
    assert passed["ticker"] in ("SPY", "AAPL")
    assert registry.get(record_fail["id"])["status"] == "rejected"

    clones = [r for r in registry.list(status="validated") if r["id"] != record_pass["id"]]
    assert len(clones) == 1
    assert clones[0]["ticker"] in ("SPY", "AAPL")
    assert clones[0]["ticker"] != passed["ticker"]


def test_run_validation_promotes_every_passing_ticker_best_one_in_place(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("https://example.com/multi"))

    def fake_validate(spec, price_data):
        # both tickers pass; AAPL has the better Sharpe and should be the in-place winner
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

    # both SPY and AAPL passed -> two validated records total (in-place + one clone)
    assert summary["validated"] == 2
    assert registry.get(record["id"])["ticker"] == "AAPL"

    clone = next(r for r in registry.list(status="validated") if r["id"] != record["id"])
    assert clone["ticker"] == "SPY"
    assert clone["name"] == "test [SPY]"


def test_mined_ticker_parses_pattern_mining_source_urls():
    assert runner._mined_ticker("internal://pattern_mining/GAP/RSI/14/bounce") == "GAP"
    assert runner._mined_ticker("internal://pattern_mining/NVDA/ZSCORE/20/bounce") == "NVDA"
    assert runner._mined_ticker("https://example.com/some-repo") is None
    assert runner._mined_ticker("internal://strategies/mean_reversion/classic_rsi_reversion") is None


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


def test_run_validation_always_includes_a_mined_candidates_own_ticker(tmp_path, monkeypatch):
    # A pattern-mined spec's thresholds are calibrated to one specific ticker's own
    # historical distribution (see runner._mined_ticker) — even if that ticker isn't in
    # the configured universe, it must still be loaded and validated against.
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("internal://pattern_mining/GAP/RSI/14/bounce"))

    requested_tickers = []

    def fake_load(ticker, start, end):
        requested_tickers.append(ticker)
        return pd.DataFrame({"close": [1, 2, 3]})

    monkeypatch.setattr(runner, "load_price_data", fake_load)
    monkeypatch.setattr(runner, "validate_strategy", lambda spec, data: ValidationResult(True, "ok", Metrics(2.0, 0.05, 2.0)))

    summary = runner.run_validation(registry=registry, universe=["SPY", "AAPL"])

    # all three tickers pass here -> one in-place + two clones, one of which must be GAP
    assert "GAP" in requested_tickers
    assert summary["validated"] == 3
    validated_tickers = {r["ticker"] for r in registry.list(status="validated")}
    assert validated_tickers == {"SPY", "AAPL", "GAP"}


def test_run_validation_reports_mined_tickers_own_failure_reason(tmp_path, monkeypatch):
    # SPY/AAPL (checked first, per universe order) fail too, but GAP (the mined candidate's
    # own origin ticker) is what its thresholds were actually calibrated to — the recorded
    # rejection reason must cite GAP's own result, not whichever ticker failed first.
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("internal://pattern_mining/GAP/RSI/14/bounce"))

    def fake_load(ticker, start, end):
        df = pd.DataFrame({"close": [1, 2, 3]})
        df.attrs["ticker"] = ticker
        return df

    def fake_validate(spec, price_data):
        ticker = price_data.attrs["ticker"]
        return ValidationResult(False, f"failed for {ticker}", Metrics(0.5, 0.05, 2.0))

    monkeypatch.setattr(runner, "load_price_data", fake_load)
    monkeypatch.setattr(runner, "validate_strategy", fake_validate)

    summary = runner.run_validation(registry=registry, universe=["SPY", "AAPL"])

    assert summary["rejected"] == 1
    reason = registry.get(record["id"])["history"][-1]["reason"]
    assert reason == "[GAP] failed for GAP"


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
