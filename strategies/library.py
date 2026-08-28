"""Registers the hand-designed classic reference strategies — one per archetype — into the
strategy registry as new "candidate"s, alongside whatever the discovery pipeline finds
online. Idempotent: add_candidate dedups via each spec's own internal:// source_url, so
running this repeatedly never creates duplicates. Pairs candidates are seeded from
config.yaml's watchlists.pairs_trading list.
"""
from __future__ import annotations

from config.settings import settings
from strategies.breakout.strategy import classic_channel_breakout
from strategies.mean_reversion.strategy import (
    classic_bollinger_reversion,
    classic_rsi2_reversion,
    classic_rsi_reversion,
)
from strategies.momentum.strategy import classic_macd_momentum
from strategies.pairs_trading.strategy import build_pairs_spec
from strategy_research.registry import StrategyRegistry


def classic_single_ticker_strategies() -> list:
    return [
        classic_rsi_reversion(),
        classic_rsi2_reversion(),
        classic_macd_momentum(),
        classic_channel_breakout(),
        classic_bollinger_reversion(),
    ]


def classic_pairs_strategies() -> list:
    pairs = settings.get("watchlists.pairs_trading", [])
    lookback_period = settings.get("pairs_trading.lookback_period", 30)
    entry_zscore = settings.get("pairs_trading.entry_zscore", 2.0)
    exit_zscore = settings.get("pairs_trading.exit_zscore", 0.5)

    specs = []
    for pair in pairs:
        if len(pair) != 2:
            continue
        ticker_a, ticker_b = pair
        specs.append(
            build_pairs_spec(
                ticker_a,
                ticker_b,
                lookback_period=lookback_period,
                entry_zscore=entry_zscore,
                exit_zscore=exit_zscore,
            )
        )
    return specs


def seed_classic_strategies(registry: StrategyRegistry | None = None) -> dict:
    registry = registry or StrategyRegistry()
    seen = registry.seen_source_urls()

    candidates = classic_single_ticker_strategies() + classic_pairs_strategies()
    added = 0
    for spec in candidates:
        spec.validate()
        if spec.source_url in seen:
            continue
        registry.add_candidate(spec)
        added += 1

    registry.save()
    return {"added": added, "skipped": len(candidates) - added}
