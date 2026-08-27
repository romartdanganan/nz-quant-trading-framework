"""Controlled vocabulary of known indicators and strategy archetypes that
rule_extractor.py matches scraped text against. Anything outside this vocabulary must fall
through to the Gemini fallback (or be rejected) rather than guessed — see CLAUDE.md
Guardrails on never letting extraction hallucinate trading logic.
"""
from __future__ import annotations

import re

from strategy_research.strategy_spec import Archetype, Indicator

ARCHETYPE_KEYWORDS: dict[Archetype, list[str]] = {
    Archetype.MEAN_REVERSION: [
        "mean reversion",
        "reverts to the mean",
        "bollinger band",
        "oversold",
        "overbought",
        "z-score",
    ],
    Archetype.MOMENTUM: [
        "momentum",
        "trend following",
        "moving average crossover",
        "macd cross",
    ],
    Archetype.PAIRS_TRADING: [
        "pairs trading",
        "cointegration",
        "spread trading",
        "statistical arbitrage",
    ],
    Archetype.BREAKOUT: [
        "breakout",
        "range breakout",
        "channel breakout",
        "volume confirmation",
        "new high",
    ],
}

# Words mapped to the Operator values they represent (see strategy_spec.Operator).
OPERATOR_WORDS: dict[str, str] = {
    "below": "<",
    "above": ">",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
    "crosses above": "crosses_above",
    "crosses below": "crosses_below",
}

# Each pattern captures either (operator_word, numeric_value) for threshold-style
# indicators, or (operator_word,) alone for crossover-style indicators (threshold is a
# sentinel 0.0 in that case — see strategy_spec.CROSSOVER_OPERATORS).
INDICATOR_PATTERNS: dict[Indicator, re.Pattern] = {
    Indicator.RSI: re.compile(
        r"\brsi\b(?:\s*\(\d+\))?\s*(?:is\s*)?(below|above|<=|>=|<|>)\s*(\d{1,3}(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    Indicator.ZSCORE: re.compile(
        r"z[- ]?score\s*(?:is\s*)?(below|above|<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    Indicator.ATR: re.compile(
        r"\batr\b\s*(?:is\s*)?(below|above|<=|>=|<|>)\s*(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    Indicator.VOLUME: re.compile(
        r"\bvolume\s*(?:is\s*)?(above|below|<=|>=|<|>)\s*(\d+(?:\.\d+)?)\s*x?\b",
        re.IGNORECASE,
    ),
    Indicator.MACD: re.compile(
        r"\bmacd\b\s*(crosses above|crosses below)",
        re.IGNORECASE,
    ),
    Indicator.VWAP: re.compile(
        r"\bvwap\b\s*(crosses above|crosses below)",
        re.IGNORECASE,
    ),
}

# Channel breakout patterns capture a lookback period (an integer), not an operator+value
# pair — e.g. "20-day high", "breaks above the 55-day high". Handled separately in
# rule_extractor.py since the capture shape differs from INDICATOR_PATTERNS above.
CHANNEL_HIGH_PATTERN = re.compile(r"(\d+)[- ]day high", re.IGNORECASE)
CHANNEL_LOW_PATTERN = re.compile(r"(\d+)[- ]day low", re.IGNORECASE)
