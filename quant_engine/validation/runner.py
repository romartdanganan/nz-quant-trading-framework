"""Orchestrates validation over every single-ticker ("kind": "single") "candidate" in the
strategy registry: fetches price data, runs validate_strategy, and promotes/rejects the
registry record accordingly. Pairs-trading candidates ("kind": "pairs") are handled
separately by pairs_runner.py, since they need two price series, not one. This is what
cli/main.py option [2] calls.

Known limitation: every single-ticker candidate is currently backtested against the same
`ticker` argument (default SPY) regardless of what ticker it was actually discovered
for — StrategySpec has no ticker field of its own (a strategy is a rule; today nothing
tracks which ticker(s) that rule should run against). Fine for now since there's no
watchlist-to-strategy mapping yet, but worth revisiting before this matters for real
capital allocation.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from backtester.data_loader import PriceDataUnavailable, load_price_data
from quant_engine.validation.validator import validate_strategy
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import StrategySpec

logger = logging.getLogger(__name__)

DEFAULT_TICKER = "SPY"
DEFAULT_LOOKBACK_DAYS = 730  # ~2 years


def run_validation(
    registry: StrategyRegistry | None = None,
    ticker: str = DEFAULT_TICKER,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict:
    registry = registry or StrategyRegistry()
    candidates = [r for r in registry.list(status="candidate") if r.get("kind", "single") == "single"]

    if not candidates:
        return {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}

    end = date.today()
    start = end - timedelta(days=lookback_days)
    try:
        price_data = load_price_data(ticker, start, end)
    except PriceDataUnavailable as exc:
        logger.warning("Could not load price data for %s: %s", ticker, exc)
        return {"candidates": len(candidates), "validated": 0, "rejected": 0, "errored": len(candidates)}

    validated = rejected = errored = 0
    for record in candidates:
        try:
            spec = StrategySpec.from_dict(record)
        except (KeyError, ValueError, TypeError) as exc:
            registry.reject(record["id"], f"could not reconstruct StrategySpec: {exc}")
            errored += 1
            continue

        result = validate_strategy(spec, price_data)
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
