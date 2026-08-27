"""Orchestrates validation over every single-ticker ("kind": "single") "candidate" in the
strategy registry: fetches price data, runs validate_strategy, and promotes/rejects the
registry record accordingly. Pairs-trading candidates ("kind": "pairs") are handled
separately by pairs_runner.py, since they need two price series, not one. This is what
cli/main.py option [2] calls.

Each candidate is validated against every ticker in config.yaml's
strategy_validation.universe, not one hardcoded ticker (a previously-documented
limitation): a rule like "classic RSI reversion" may work on one ticker and not another, so
this searches the universe and promotes using whichever ticker gave the best passing
result — that ticker is stored on the record as record["ticker"] for
execution_alpaca/paper_trading_engine.py to actually trade during incubation. A candidate
that doesn't pass on any universe ticker is rejected with the best (still-failing) result.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from backtester.data_loader import PriceDataUnavailable, load_price_data
from config.settings import settings
from quant_engine.validation.validator import ValidationResult, validate_strategy
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import StrategySpec

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE = ["SPY"]
DEFAULT_LOOKBACK_DAYS = 730  # ~2 years


def _load_universe_price_data(universe: list[str], lookback_days: int) -> dict[str, object]:
    end = date.today()
    start = end - timedelta(days=lookback_days)
    price_data_by_ticker = {}
    for ticker in universe:
        try:
            price_data_by_ticker[ticker] = load_price_data(ticker, start, end)
        except PriceDataUnavailable as exc:
            logger.warning("Could not load price data for %s: %s", ticker, exc)
    return price_data_by_ticker


def _best_result_across_universe(
    spec: StrategySpec, price_data_by_ticker: dict[str, object]
) -> tuple[str | None, ValidationResult | None, str | None, ValidationResult | None]:
    """Returns (best_pass_ticker, best_pass_result, best_fail_ticker, best_fail_result)."""
    best_pass_ticker = best_fail_ticker = None
    best_pass_result = best_fail_result = None

    for ticker, price_data in price_data_by_ticker.items():
        result = validate_strategy(spec, price_data)
        if result.passed:
            if best_pass_result is None or (
                result.metrics
                and best_pass_result.metrics
                and result.metrics.sharpe_ratio > best_pass_result.metrics.sharpe_ratio
            ):
                best_pass_ticker, best_pass_result = ticker, result
        elif best_fail_result is None:
            best_fail_ticker, best_fail_result = ticker, result

    return best_pass_ticker, best_pass_result, best_fail_ticker, best_fail_result


def run_validation(
    registry: StrategyRegistry | None = None,
    universe: list[str] | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict:
    registry = registry or StrategyRegistry()
    candidates = [r for r in registry.list(status="candidate") if r.get("kind", "single") == "single"]

    if not candidates:
        return {"candidates": 0, "validated": 0, "rejected": 0, "errored": 0}

    universe = universe or settings.get("strategy_validation.universe", DEFAULT_UNIVERSE)
    price_data_by_ticker = _load_universe_price_data(universe, lookback_days)

    if not price_data_by_ticker:
        return {"candidates": len(candidates), "validated": 0, "rejected": 0, "errored": len(candidates)}

    validated = rejected = errored = 0
    for record in candidates:
        try:
            spec = StrategySpec.from_dict(record)
        except (KeyError, ValueError, TypeError) as exc:
            registry.reject(record["id"], f"could not reconstruct StrategySpec: {exc}")
            errored += 1
            continue

        pass_ticker, pass_result, fail_ticker, fail_result = _best_result_across_universe(
            spec, price_data_by_ticker
        )

        if pass_result is not None:
            record["ticker"] = pass_ticker
            metrics_dict = pass_result.metrics.__dict__ if pass_result.metrics else None
            registry.promote_to_validated(record["id"], metrics_dict, f"[{pass_ticker}] {pass_result.reason}")
            validated += 1
        else:
            reason = f"[{fail_ticker}] {fail_result.reason}" if fail_result else "no universe ticker produced a result"
            record["metrics"] = fail_result.metrics.__dict__ if fail_result and fail_result.metrics else None
            registry.reject(record["id"], reason)
            rejected += 1

    registry.save()
    return {
        "candidates": len(candidates),
        "validated": validated,
        "rejected": rejected,
        "errored": errored,
    }
