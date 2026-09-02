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

_MINED_SOURCE_PREFIX = "internal://pattern_mining/"


def _mined_ticker(source_url: str) -> str | None:
    """A pattern-mined candidate's source_url encodes the exact ticker its entry/exit
    thresholds were calibrated against (see strategy_research/generator/pattern_miner.py):
    "internal://pattern_mining/{ticker}/{indicator}/{period}/{direction}". Unlike a
    scraped/classic StrategySpec (genuinely ticker-agnostic, meant to be searched across
    the whole universe), a mined spec's thresholds are meaningless on any ticker other than
    the one they were derived from — validating it only against the generic fixed universe
    (which may not even contain that ticker) would silently test the wrong thing. Returns
    None for any non-mined source_url.
    """
    if not source_url.startswith(_MINED_SOURCE_PREFIX):
        return None
    parts = source_url[len(_MINED_SOURCE_PREFIX):].split("/")
    return parts[0] if parts and parts[0] else None


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


def _all_results_across_universe(
    spec: StrategySpec, price_data_by_ticker: dict[str, object], preferred_fail_ticker: str | None = None
) -> tuple[list[tuple[str, ValidationResult]], str | None, ValidationResult | None]:
    """Returns (passing_results, best_fail_ticker, best_fail_result).

    passing_results holds *every* universe ticker that cleared validation, not just the
    single best one — a rule that genuinely works on several tickers should be able to
    incubate on all of them concurrently instead of the pipeline arbitrarily picking one
    winner and discarding the rest (CLAUDE.md: don't waste a candidate that already
    cleared every threshold on a second instrument).

    preferred_fail_ticker (a mined candidate's own origin ticker, see _mined_ticker) always
    wins the reported failing reason over whichever ticker merely happened to be checked
    first — otherwise the registry's rejection reason could cite an arbitrary universe
    ticker's failure (e.g. SPY) for a strategy whose thresholds were never calibrated to
    SPY at all, which is a meaningless reason to keep as the permanent record of why a
    mined candidate failed.
    """
    passing: list[tuple[str, ValidationResult]] = []
    best_fail_ticker = best_fail_result = None

    for ticker, price_data in price_data_by_ticker.items():
        result = validate_strategy(spec, price_data)
        if result.passed:
            passing.append((ticker, result))
        elif best_fail_result is None or ticker == preferred_fail_ticker:
            best_fail_ticker, best_fail_result = ticker, result

    passing.sort(key=lambda item: item[1].metrics.sharpe_ratio, reverse=True)
    return passing, best_fail_ticker, best_fail_result


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
    mined_tickers = {t for r in candidates for t in [_mined_ticker(r.get("source_url", ""))] if t}
    universe = list(dict.fromkeys([*universe, *mined_tickers]))  # dedupe, keep order, always include mined origins
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

        preferred_fail_ticker = _mined_ticker(record.get("source_url", ""))
        passing, fail_ticker, fail_result = _all_results_across_universe(
            spec, price_data_by_ticker, preferred_fail_ticker
        )

        if passing:
            best_ticker, best_result = passing[0]
            record["ticker"] = best_ticker
            metrics_dict = best_result.metrics.__dict__ if best_result.metrics else None
            registry.promote_to_validated(record["id"], metrics_dict, f"[{best_ticker}] {best_result.reason}")
            validated += 1

            # Every other passing ticker becomes its own validated record so it can
            # incubate at the same time as the best one, rather than being discarded.
            for extra_ticker, extra_result in passing[1:]:
                clone = registry.add_candidate(spec)
                clone["ticker"] = extra_ticker
                clone["name"] = f"{clone['name']} [{extra_ticker}]"
                extra_metrics = extra_result.metrics.__dict__ if extra_result.metrics else None
                registry.promote_to_validated(clone["id"], extra_metrics, f"[{extra_ticker}] {extra_result.reason}")
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
