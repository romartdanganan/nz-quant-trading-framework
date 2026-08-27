"""News headline sentiment scoring via NLTK's VADER lexicon — deterministic and local, no
LLM call (see CLAUDE.md Guardrails: the model never picks trades, and no free-text
"opinion" call should ever produce a trading input). This is advisory input to the
fundamental screener only; per CLAUDE.md's Human-in-the-loop section, sentiment never
auto-triggers a trade at any stage.

Known limitation: VADER is a general-purpose lexicon, not finance-tuned — it can misread
financial jargon (e.g. "beats guidance", "misses estimates" read as roughly neutral).
Treat scores as a rough directional signal, not a precise measure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import nltk
import yfinance as yf

logger = logging.getLogger(__name__)

BULLISH_THRESHOLD = 0.2
BEARISH_THRESHOLD = -0.2

_analyzer = None


class SentimentUnavailable(RuntimeError):
    """Raised when the VADER lexicon can't be loaded or downloaded."""


def _get_analyzer():
    global _analyzer
    if _analyzer is not None:
        return _analyzer

    from nltk.sentiment import SentimentIntensityAnalyzer

    try:
        nltk.data.find("sentiment/vader_lexicon.zip")
    except LookupError:
        try:
            nltk.download("vader_lexicon", quiet=True)
        except Exception as exc:
            raise SentimentUnavailable(f"Could not obtain the VADER lexicon: {exc}") from exc

    _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


@dataclass(frozen=True)
class SentimentResult:
    ticker: str
    headline_count: int
    mean_compound_score: float  # -1 (very negative) to +1 (very positive)
    label: str  # "bullish" | "neutral" | "bearish"


def fetch_headlines(ticker: str, limit: int = 10) -> list[str]:
    try:
        news_items = yf.Ticker(ticker).news or []
    except Exception as exc:
        logger.warning("Failed to fetch news for %s: %s", ticker, exc)
        return []

    headlines = []
    for item in news_items[:limit]:
        content = item.get("content", item)
        title = content.get("title")
        if title:
            headlines.append(title)
    return headlines


def score_headlines(headlines: list[str]) -> float:
    if not headlines:
        return 0.0
    analyzer = _get_analyzer()
    scores = [analyzer.polarity_scores(headline)["compound"] for headline in headlines]
    return sum(scores) / len(scores)


def _label(score: float) -> str:
    if score >= BULLISH_THRESHOLD:
        return "bullish"
    if score <= BEARISH_THRESHOLD:
        return "bearish"
    return "neutral"


def score_ticker(ticker: str, limit: int = 10) -> SentimentResult:
    headlines = fetch_headlines(ticker, limit=limit)
    mean_score = score_headlines(headlines)
    return SentimentResult(
        ticker=ticker,
        headline_count=len(headlines),
        mean_compound_score=mean_score,
        label=_label(mean_score),
    )
