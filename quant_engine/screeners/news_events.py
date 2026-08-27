"""Deterministic, keyword-based event tagging for headlines — surfaces which recent
articles look material (earnings, guidance, M&A, legal/regulatory, analyst actions) so a
human can prioritize what to actually read. This is categorization by keyword match, not
LLM judgment (CLAUDE.md Guardrails) — the underlying headline text is always shown
alongside the tag so the reader sees the real news themselves, never a paraphrase.

Known limitation: keyword matching is blunt — it will miss headlines that describe the
same event in unexpected phrasing, and can mis-tag on coincidental word overlap. Treat tags
as "worth a second look," not a complete or authoritative classification.
"""
from __future__ import annotations

EVENT_KEYWORDS: dict[str, list[str]] = {
    "earnings_beat": ["beats estimates", "tops estimates", "beat expectations", "record earnings", "beats forecasts"],
    "earnings_miss": ["misses estimates", "falls short", "missed expectations", "misses forecasts"],
    "guidance_raise": ["raises guidance", "raised its forecast", "upgraded outlook", "boosts outlook", "raises forecast"],
    "guidance_cut": ["cuts guidance", "lowers forecast", "cut its outlook", "slashes guidance", "cuts forecast"],
    "ma_activity": ["acquisition", "acquires", "merger", "to buy", "buyout", "takeover"],
    "legal_regulatory": ["lawsuit", "investigation", "probe", "regulatory", "fine", "sec charges", "antitrust"],
    "analyst_action": ["upgrades", "downgrades", "price target", "initiates coverage"],
    "product_news": ["fda approval", "recall", "unveils", "launches"],
}


def tag_headline(headline: str) -> list[str]:
    text = headline.lower()
    return [event for event, keywords in EVENT_KEYWORDS.items() if any(keyword in text for keyword in keywords)]
