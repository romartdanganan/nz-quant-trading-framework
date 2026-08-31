"""Drives pairs_validator.py over every "kind": "pairs" candidate in the registry — the
pairs-trading counterpart to runner.py. Wired into cli/main.py option [2] alongside the
single-ticker runner.

Multiple-testing correction: cointegration is tested at alpha=0.05 per pair
(pairs_trading.cointegration_significance), but the pairs universe keeps growing as more
candidates get added over time (CLAUDE.md's "Broaden pairs universe" history) — treating
each pair as an independent test at the same alpha means the family-wise false-positive
rate climbs with the number of pairs ever tried (~5% per pair), so eventually a pair could
clear the bar by pure chance rather than a real relationship. This applies a Bonferroni
correction: the significance threshold actually used is the configured alpha divided by
the total number of "kind": "pairs" records in the registry (every status, not just this
run's candidates — the family is "every pair this project has ever tested", since that's
the actual multiple-comparisons exposure), so the bar gets stricter as the universe grows.
Set pairs_trading.multiple_testing_correction: "none" to disable and use the raw alpha.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from backtester.data_loader import PriceDataUnavailable, load_price_data
from config.settings import settings
from quant_engine.validation.pairs_validator import DEFAULT_COINTEGRATION_SIGNIFICANCE, validate_pairs_strategy
from strategies.pairs_trading.strategy import PairsSpec
from strategy_research.registry import StrategyRegistry

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 730  # ~2 years


def _corrected_significance(registry: StrategyRegistry) -> float:
    base = settings.get("pairs_trading.cointegration_significance", DEFAULT_COINTEGRATION_SIGNIFICANCE)
    correction = settings.get("pairs_trading.multiple_testing_correction", "bonferroni")
    if correction == "none":
        return base
    family_size = sum(1 for r in registry.list() if r.get("kind") == "pairs")
    return base / max(family_size, 1)


def run_pairs_validation(
    registry: StrategyRegistry | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict:
    registry = registry or StrategyRegistry()
    candidates = [r for r in registry.list(status="candidate") if r.get("kind") == "pairs"]

    if not candidates:
        return {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}

    end = date.today()
    start = end - timedelta(days=lookback_days)
    significance = _corrected_significance(registry)

    validated = rejected = errored = 0
    for record in candidates:
        try:
            spec = PairsSpec.from_dict(record)
            price_a = load_price_data(spec.ticker_a, start, end)["close"]
            price_b = load_price_data(spec.ticker_b, start, end)["close"]
        except (KeyError, ValueError, TypeError, PriceDataUnavailable) as exc:
            registry.reject(record["id"], f"could not prepare pairs backtest: {exc}")
            errored += 1
            continue

        result = validate_pairs_strategy(spec, price_a, price_b, significance=significance)
        metrics_dict = result.metrics.__dict__ if result.metrics else None
        record["cointegration_p_value"] = result.p_value
        record["cointegration_significance_used"] = significance

        if result.passed:
            registry.promote_to_validated(record["id"], metrics_dict, result.reason)
            validated += 1
        else:
            record["metrics"] = metrics_dict
            registry.reject(record["id"], result.reason)
            rejected += 1

    registry.save()
    return {
        "candidates": len(candidates),
        "validated": validated,
        "rejected": rejected,
        "errored": errored,
    }
