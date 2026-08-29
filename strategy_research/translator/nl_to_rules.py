"""Normalizes any pipeline candidate — rule_extractor.py output or raw Gemini JSON — into
a schema-validated StrategySpec. This is the single validation gate before a candidate can
reach the strategy registry: nothing bypasses StrategySpec.validate(), and an unrecognized
indicator/archetype/operator from Gemini is rejected outright rather than guessed at.
"""
from __future__ import annotations

from strategy_research.strategy_spec import (
    Archetype,
    StrategySpec,
    StrategySpecError,
    condition_from_dict,
)


def normalize_from_rule_extractor(spec: StrategySpec) -> StrategySpec:
    spec.validate()
    return spec


def normalize_from_gemini(candidate: dict, source_url: str) -> StrategySpec | None:
    """candidate is one parsed-JSON strategy idea from gemini_client.distill(). Returns
    None (rejected) if it doesn't map cleanly onto the controlled vocabulary.

    Same two structural rejections as rule_extractor.py's normalize_from_rule_extractor
    sibling (fixed there 2026-08-28, found unfixed here 2026-08-30 when the Gemini path
    produced both failure modes in one run):
    1. "pairs_trading" archetype can't be a StrategySpec at all — it needs two tickers and
       a hedge ratio (see strategies/pairs_trading/strategy.py's PairsSpec), not a
       single-ticker indicator condition.
    2. Missing/empty exit_conditions must be rejected, not silently filled in by reusing
       entry_conditions — that fabricates a degenerate entry==exit spec that can never
       sensibly hold a position. Also reject if Gemini explicitly returned identical
       entry/exit condition sets.
    """
    try:
        archetype = Archetype(candidate["archetype"])
        if archetype == Archetype.PAIRS_TRADING:
            return None

        entry_conditions = [condition_from_dict(c) for c in candidate["entry_conditions"]]
        exit_conditions_raw = candidate.get("exit_conditions")
        if not exit_conditions_raw:
            return None
        exit_conditions = [condition_from_dict(c) for c in exit_conditions_raw]

        if set(entry_conditions) == set(exit_conditions):
            return None

        spec = StrategySpec(
            name=candidate.get("name") or "unnamed_gemini_candidate",
            archetype=archetype,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            timeframe=candidate.get("timeframe", "unspecified"),
            source_url=source_url,
            extraction_method="gemini",
            confidence=float(candidate.get("confidence", 0.5)),
            raw_excerpt=str(candidate.get("raw_excerpt", ""))[:280],
        )
        spec.validate()
    except (KeyError, ValueError, TypeError, StrategySpecError):
        return None
    return spec
