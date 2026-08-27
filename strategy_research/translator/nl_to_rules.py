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
    """
    try:
        archetype = Archetype(candidate["archetype"])
        entry_conditions = [condition_from_dict(c) for c in candidate["entry_conditions"]]
        exit_conditions = [
            condition_from_dict(c) for c in (candidate.get("exit_conditions") or candidate["entry_conditions"])
        ]
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
