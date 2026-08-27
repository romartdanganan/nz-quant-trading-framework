"""Drives pairs_validator.py over every "kind": "pairs" candidate in the registry — the
pairs-trading counterpart to runner.py. Wired into cli/main.py option [2] alongside the
single-ticker runner.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from backtester.data_loader import PriceDataUnavailable, load_price_data
from quant_engine.validation.pairs_validator import validate_pairs_strategy
from strategies.pairs_trading.strategy import PairsSpec
from strategy_research.registry import StrategyRegistry

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 730  # ~2 years


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

        result = validate_pairs_strategy(spec, price_a, price_b)
        metrics_dict = result.metrics.__dict__ if result.metrics else None

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
