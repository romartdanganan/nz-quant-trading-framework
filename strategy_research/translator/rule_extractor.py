"""Free, deterministic extraction: matches scraped strategy text against vocabulary.py
to produce a StrategySpec directly, with no LLM call. This is the primary extraction path
(see CLAUDE.md Automated strategy discovery pipeline) — covers the common case of known
indicators/archetypes. Callers should fall through to distiller/gemini_client.py only when
extract() returns spec=None.
"""
from __future__ import annotations

from dataclasses import dataclass

from strategy_research.strategy_spec import (
    Condition,
    Operator,
    StrategySpec,
    StrategySpecError,
)
from strategy_research.vocabulary import ARCHETYPE_KEYWORDS, INDICATOR_PATTERNS, OPERATOR_WORDS

MIN_CONFIDENCE = 0.5


@dataclass
class ExtractionResult:
    spec: StrategySpec | None
    confidence: float


def extract(text: str, source_url: str, name_hint: str = "") -> ExtractionResult:
    archetype, keyword_score = _score_archetype(text)
    conditions = _extract_conditions(text)

    if archetype is None or not conditions:
        return ExtractionResult(spec=None, confidence=0.0)

    confidence = min(1.0, 0.25 * keyword_score + 0.25 * len(conditions))
    if confidence < MIN_CONFIDENCE:
        return ExtractionResult(spec=None, confidence=confidence)

    entry_conditions = [conditions[0]]
    exit_conditions = [conditions[1]] if len(conditions) > 1 else [conditions[0]]

    spec = StrategySpec(
        name=name_hint or f"{archetype.value}_{abs(hash(source_url)) % 10_000}",
        archetype=archetype,
        entry_conditions=entry_conditions,
        exit_conditions=exit_conditions,
        timeframe="unspecified",
        source_url=source_url,
        extraction_method="rule",
        confidence=confidence,
        raw_excerpt=text[:280],
    )
    try:
        spec.validate()
    except StrategySpecError:
        return ExtractionResult(spec=None, confidence=confidence)
    return ExtractionResult(spec=spec, confidence=confidence)


def _score_archetype(text: str):
    text_lower = text.lower()
    best_archetype = None
    best_score = 0
    for archetype, keywords in ARCHETYPE_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text_lower)
        if score > best_score:
            best_archetype, best_score = archetype, score
    return best_archetype, best_score


def _extract_conditions(text: str) -> list[Condition]:
    conditions: list[Condition] = []
    for indicator, pattern in INDICATOR_PATTERNS.items():
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 2:
                op_word, value = groups
                op = OPERATOR_WORDS.get(op_word.lower())
                if op is None:
                    continue
                conditions.append(Condition(indicator, Operator(op), float(value)))
            elif len(groups) == 1:
                op = OPERATOR_WORDS.get(groups[0].lower())
                if op in ("crosses_above", "crosses_below"):
                    conditions.append(Condition(indicator, Operator(op), 0.0))
    return conditions
