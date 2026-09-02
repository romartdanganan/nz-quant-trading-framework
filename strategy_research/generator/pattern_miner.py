"""Data-driven strategy generation — a second discovery path alongside strategy_research/
scrapers/ (CLAUDE.md "Automated strategy discovery pipeline"). Where scrapers/ pulls
strategy *concept text* other people already published, this module analyses real
historical OHLCV data directly and formalizes whatever it finds into candidates itself —
nothing here is copied from anyone.

Method: for each (ticker, indicator, period) combination, compute the indicator's value
line and the forward return N days later, bucket bars into deciles by indicator value, and
test whether the most extreme decile's mean forward return is significantly higher than
the rest of the sample (one-sided Welch's t-test). A significant bottom-decile result
("after this indicator is unusually low, the price tends to bounce") becomes a
mean-reversion candidate; a significant top-decile result ("after this indicator is
unusually high, the price tends to keep going") becomes a momentum candidate — both
long-only, since StrategySpec has no short side yet. Thresholds are calibrated from the
ticker's own empirical distribution (the actual decile boundary / median), not textbook
30/70-style defaults.

Still bound by CLAUDE.md's Guardrails like every other part of this pipeline: no LLM ever
decides a rule — every hypothesis here is generated and tested by plain deterministic
statistics (numpy/scipy). And because scanning many indicator/period/direction
combinations across a universe is a textbook multiple-comparisons problem — the same one
strategies/pairs_trading needed a Bonferroni correction for — every hypothesis here shares
one, persistent, ever-growing family-wise error rate (see
pattern_mining.multiple_testing_correction / _hypothesis_family_size below), not just a
per-run one; re-running this module many times must not be a backdoor to eventually
clearing the bar by chance.

Honest limitation, not silently papered over: forward-return windows overlap (a
forward_return_horizon_days=5 window advances one bar at a time), so consecutive samples
are not independent — this inflates the effective sample size the t-test sees, understating
the true p-value to some degree. The Bonferroni correction and the downstream
min_trades/overfit_guard/incubation gates (this module's output is a plain "candidate" —
it still has to clear every one of those, same as any scraped strategy) are the mitigations
in place; a full Newey-West-style autocorrelation-robust test would be a further
improvement, not yet implemented.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandas_ta as ta
from scipy import stats

from backtester.data_loader import PriceDataUnavailable, load_price_data
from config.settings import settings
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import (
    Archetype,
    Condition,
    Indicator,
    Operator,
    StrategySpec,
    StrategySpecError,
)

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE = ["SPY"]
DEFAULT_LOOKBACK_DAYS = 730  # ~2 years, matches runner.py/pairs_runner.py's convention
DEFAULT_FORWARD_RETURN_DAYS = 5
DEFAULT_DECILE_COUNT = 10
DEFAULT_MIN_BUCKET_SIZE = 30   # need a real sample per decile for the t-test to mean anything
DEFAULT_SIGNIFICANCE = 0.05
DEFAULT_STATS_CACHE = Path("data/cache/pattern_mining_stats.json")

# indicator -> lookback periods to test. RSI and ZSCORE are the only two threshold-style
# indicators in strategy_spec.INDICATOR_RANGES that are single numeric "how extreme is the
# market right now" value lines with a natural percentile interpretation, rather than a
# volume/volatility filter or a crossover-style computed line (MACD/VWAP/CHANNEL/BOLLINGER/
# KELTNER) — those don't decile-bucket the same way and are left for a future extension of
# this module.
INDICATOR_PERIODS: dict[Indicator, list[int]] = {
    Indicator.RSI: [2, 5, 10, 14],
    Indicator.ZSCORE: [10, 20, 50],
}

DIRECTIONS = ("bounce", "continuation")


@dataclass(frozen=True)
class Hypothesis:
    ticker: str
    indicator: Indicator
    period: int
    direction: str  # "bounce" (buy after an extreme-low reading) | "continuation" (buy after an extreme-high reading)
    p_value: float
    entry_threshold: float
    exit_threshold: float
    extreme_mean_return: float
    baseline_mean_return: float
    sample_size: int


def _value_line(indicator: Indicator, period: int, close: pd.Series) -> pd.Series:
    if indicator == Indicator.RSI:
        return ta.rsi(close, length=period)
    if indicator == Indicator.ZSCORE:
        rolling_mean = close.rolling(period).mean()
        rolling_std = close.rolling(period).std()
        return (close - rolling_mean) / rolling_std
    raise ValueError(f"pattern_miner has no value-line definition for {indicator}")


def _bucket_hypotheses(
    value: pd.Series,
    forward_return: pd.Series,
    ticker: str,
    indicator: Indicator,
    period: int,
    decile_count: int,
    min_bucket_size: int,
) -> list[Hypothesis]:
    frame = pd.DataFrame({"value": value, "forward_return": forward_return}).dropna()
    if len(frame) < decile_count * min_bucket_size:
        return []

    frame["decile"] = pd.qcut(frame["value"], decile_count, labels=False, duplicates="drop")
    baseline_mean = float(frame["forward_return"].mean())
    lowest, highest = frame["decile"].min(), frame["decile"].max()

    hypotheses = []
    for decile, direction in ((lowest, "bounce"), (highest, "continuation")):
        bucket = frame[frame["decile"] == decile]
        if len(bucket) < min_bucket_size:
            continue
        rest = frame[frame["decile"] != decile]["forward_return"]

        # One-sided Welch's t-test: is this extreme bucket's forward return significantly
        # *higher* than the rest of the sample? Both directions are long-only positive-edge
        # hypotheses (StrategySpec has no short side yet).
        t_stat, two_sided_p = stats.ttest_ind(bucket["forward_return"], rest, equal_var=False)
        one_sided_p = two_sided_p / 2 if t_stat > 0 else 1.0

        entry_threshold = bucket["value"].max() if direction == "bounce" else bucket["value"].min()
        exit_threshold = frame["value"].median()

        hypotheses.append(
            Hypothesis(
                ticker=ticker,
                indicator=indicator,
                period=period,
                direction=direction,
                p_value=float(one_sided_p),
                entry_threshold=float(entry_threshold),
                exit_threshold=float(exit_threshold),
                extreme_mean_return=float(bucket["forward_return"].mean()),
                baseline_mean_return=baseline_mean,
                sample_size=len(bucket),
            )
        )
    return hypotheses


def _test_hypotheses_for_series(
    ticker: str,
    indicator: Indicator,
    period: int,
    close: pd.Series,
    forward_days: int,
    decile_count: int,
    min_bucket_size: int,
) -> list[Hypothesis]:
    value = _value_line(indicator, period, close)
    forward_return = close.pct_change(forward_days).shift(-forward_days)
    return _bucket_hypotheses(value, forward_return, ticker, indicator, period, decile_count, min_bucket_size)


def _spec_from_hypothesis(hypothesis: Hypothesis) -> StrategySpec:
    archetype = Archetype.MEAN_REVERSION if hypothesis.direction == "bounce" else Archetype.MOMENTUM
    entry_operator = Operator.LT if hypothesis.direction == "bounce" else Operator.GT
    exit_operator = Operator.GT if hypothesis.direction == "bounce" else Operator.LT

    name = f"mined_{hypothesis.indicator.value.lower()}{hypothesis.period}_{hypothesis.direction}_{hypothesis.ticker}"
    source_url = (
        f"internal://pattern_mining/{hypothesis.ticker}/{hypothesis.indicator.value}/"
        f"{hypothesis.period}/{hypothesis.direction}"
    )
    raw_excerpt = (
        f"Mined from {hypothesis.ticker} price history: {hypothesis.indicator.value}({hypothesis.period}) "
        f"in its most extreme {hypothesis.direction} decile preceded a mean forward return of "
        f"{hypothesis.extreme_mean_return:.2%} vs. {hypothesis.baseline_mean_return:.2%} baseline "
        f"(n={hypothesis.sample_size}, one-sided p={hypothesis.p_value:.5f})."
    )
    return StrategySpec(
        name=name,
        archetype=archetype,
        entry_conditions=[
            Condition(hypothesis.indicator, entry_operator, hypothesis.entry_threshold, period=hypothesis.period)
        ],
        exit_conditions=[
            Condition(hypothesis.indicator, exit_operator, hypothesis.exit_threshold, period=hypothesis.period)
        ],
        timeframe="1d",
        source_url=source_url,
        extraction_method="rule",
        confidence=1.0 - hypothesis.p_value,
        raw_excerpt=raw_excerpt,
    )


def _load_family_size(cache_path: Path) -> int:
    if not cache_path.exists():
        return 0
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f).get("hypotheses_tested_total", 0)


def _save_family_size(cache_path: Path, total: int) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"hypotheses_tested_total": total}, f, indent=2)


def _corrected_significance(base: float, family_size: int, correction: str) -> float:
    if correction == "none":
        return base
    return base / max(family_size, 1)


def run(
    registry: StrategyRegistry | None = None,
    universe: list[str] | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    stats_cache_path: Path | str = DEFAULT_STATS_CACHE,
) -> dict:
    registry = registry or StrategyRegistry()
    universe = universe or settings.get(
        "pattern_mining.universe", settings.get("strategy_validation.universe", DEFAULT_UNIVERSE)
    )
    forward_days = settings.get("pattern_mining.forward_return_horizon_days", DEFAULT_FORWARD_RETURN_DAYS)
    decile_count = settings.get("pattern_mining.decile_count", DEFAULT_DECILE_COUNT)
    min_bucket_size = settings.get("pattern_mining.min_bucket_size", DEFAULT_MIN_BUCKET_SIZE)
    base_significance = settings.get("pattern_mining.significance_level", DEFAULT_SIGNIFICANCE)
    correction = settings.get("pattern_mining.multiple_testing_correction", "bonferroni")
    stats_cache_path = Path(stats_cache_path)

    end = date.today()
    start = end - timedelta(days=lookback_days)

    all_hypotheses: list[Hypothesis] = []
    tickers_scanned = errored = 0
    for ticker in universe:
        try:
            close = load_price_data(ticker, start, end)["close"]
        except PriceDataUnavailable as exc:
            logger.warning("pattern_miner: could not load price data for %s: %s", ticker, exc)
            errored += 1
            continue
        tickers_scanned += 1
        for indicator, periods in INDICATOR_PERIODS.items():
            for period in periods:
                all_hypotheses.extend(
                    _test_hypotheses_for_series(
                        ticker, indicator, period, close, forward_days, decile_count, min_bucket_size
                    )
                )

    # Family-wise error rate grows across every run this module has ever done, not just
    # this one — otherwise simply re-running the miner repeatedly would be a backdoor to
    # eventually clearing the bar by chance, exactly the p-hacking CLAUDE.md warns against.
    family_size = _load_family_size(stats_cache_path) + len(all_hypotheses)
    significance = _corrected_significance(base_significance, family_size, correction)
    _save_family_size(stats_cache_path, family_size)

    seen = registry.seen_source_urls()
    accepted = 0
    for hypothesis in all_hypotheses:
        if hypothesis.p_value >= significance:
            continue
        spec = _spec_from_hypothesis(hypothesis)
        if spec.source_url in seen:
            continue
        try:
            spec.validate()
        except StrategySpecError as exc:
            logger.warning("pattern_miner: mined spec failed schema validation, skipping: %s", exc)
            continue
        registry.add_candidate(spec)
        seen.add(spec.source_url)
        accepted += 1

    registry.save()
    return {
        "tickers_scanned": tickers_scanned,
        "hypotheses_tested": len(all_hypotheses),
        "significance_used": significance,
        "candidates_accepted": accepted,
        "errored": errored,
    }
