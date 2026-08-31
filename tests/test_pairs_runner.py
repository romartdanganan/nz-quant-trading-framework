import pandas as pd
import pytest

from backtester.data_loader import PriceDataUnavailable
from quant_engine.validation import pairs_runner
from quant_engine.validation.metrics import Metrics
from quant_engine.validation.validator import ValidationResult
from strategies.pairs_trading.strategy import build_pairs_spec
from strategy_research.registry import StrategyRegistry


def _fake_price_df():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    return pd.DataFrame({"close": range(5)}, index=idx)


def test_run_pairs_validation_promotes_and_rejects(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record_pass = registry.add_candidate(build_pairs_spec("KO", "PEP"))
    record_fail = registry.add_candidate(build_pairs_spec("XOM", "CVX"))

    monkeypatch.setattr(pairs_runner, "load_price_data", lambda ticker, start, end: _fake_price_df())

    def fake_validate(spec, price_a, price_b, significance=None):
        if spec.ticker_a == "KO":
            return ValidationResult(True, "ok", Metrics(2.0, 0.05, 2.0), p_value=0.01)
        return ValidationResult(False, "not cointegrated", None, p_value=0.5)

    monkeypatch.setattr(pairs_runner, "validate_pairs_strategy", fake_validate)

    summary = pairs_runner.run_pairs_validation(registry=registry)

    assert summary == {"candidates": 2, "validated": 1, "rejected": 1, "errored": 0}
    assert registry.get(record_pass["id"])["status"] == "validated"
    assert registry.get(record_fail["id"])["status"] == "rejected"


def test_run_pairs_validation_ignores_single_ticker_candidates(tmp_path, monkeypatch):
    from strategies.mean_reversion.strategy import classic_rsi_reversion

    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(classic_rsi_reversion())  # kind="single" — must be skipped here

    summary = pairs_runner.run_pairs_validation(registry=registry)

    assert summary == {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}


def test_run_pairs_validation_handles_missing_price_data(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(build_pairs_spec("KO", "PEP"))

    def raise_unavailable(ticker, start, end):
        raise PriceDataUnavailable("no data")

    monkeypatch.setattr(pairs_runner, "load_price_data", raise_unavailable)

    summary = pairs_runner.run_pairs_validation(registry=registry)

    assert summary == {"candidates": 1, "validated": 0, "rejected": 0, "errored": 1}


def test_run_pairs_validation_applies_bonferroni_correction_across_family(tmp_path, monkeypatch):
    registry = StrategyRegistry(tmp_path / "registry.json")
    # 3 pairs already tried and rejected, plus 1 new candidate -> family size 4
    for ticker_a, ticker_b in [("MA", "V"), ("JPM", "BAC"), ("HD", "LOW")]:
        rec = registry.add_candidate(build_pairs_spec(ticker_a, ticker_b))
        registry.reject(rec["id"], "not cointegrated")
    new_candidate = registry.add_candidate(build_pairs_spec("KO", "PEP"))

    monkeypatch.setattr(pairs_runner, "load_price_data", lambda ticker, start, end: _fake_price_df())
    seen_significance = {}

    def fake_validate(spec, price_a, price_b, significance=None):
        seen_significance["value"] = significance
        return ValidationResult(False, "not cointegrated", None, p_value=0.02)

    monkeypatch.setattr(pairs_runner, "validate_pairs_strategy", fake_validate)

    pairs_runner.run_pairs_validation(registry=registry)

    assert seen_significance["value"] == pytest.approx(0.05 / 4)
    assert registry.get(new_candidate["id"])["cointegration_p_value"] == 0.02
    assert registry.get(new_candidate["id"])["cointegration_significance_used"] == pytest.approx(0.05 / 4)


def test_run_pairs_validation_correction_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pairs_runner.settings, "get", lambda key, default=None: "none" if key.endswith("correction") else default
    )
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(build_pairs_spec("KO", "PEP"))

    monkeypatch.setattr(pairs_runner, "load_price_data", lambda ticker, start, end: _fake_price_df())
    seen_significance = {}

    def fake_validate(spec, price_a, price_b, significance=None):
        seen_significance["value"] = significance
        return ValidationResult(False, "not cointegrated", None, p_value=0.02)

    monkeypatch.setattr(pairs_runner, "validate_pairs_strategy", fake_validate)

    pairs_runner.run_pairs_validation(registry=registry)

    assert seen_significance["value"] == pairs_runner.DEFAULT_COINTEGRATION_SIGNIFICANCE
