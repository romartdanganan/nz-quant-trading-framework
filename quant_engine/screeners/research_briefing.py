"""Combines the fundamental screener, sentiment scorer, earnings calendar, and news-event
tagging into one per-ticker research briefing for manual, long-term-investor-style
decisions. This is the "AI finds and organizes the information" half of that workflow —
the decision itself is always the user's (CLAUDE.md Human-in-the-loop): nothing here
outputs a buy/sell recommendation, only real, dated facts and the raw headline text.

IMPORTANT for whoever (human or Claude) is answering a "what should I invest in" or "what
should I look out for" question: run build_briefing()/scan_watchlist() and present its real
output. Do not answer such a question from training-data knowledge or general market
opinion — that is exactly the "asking an LLM for picks" failure mode CLAUDE.md's Guardrails
warn against (hallucinated numbers, stale news, chasing hype). This module's whole purpose
is to make sure that question gets answered from fresh, real data instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from nz_tax_fx.fx_converter import FXConverter
from quant_engine.screeners.earnings_calendar import RecentEarnings, UpcomingEarnings, get_last_earnings, get_upcoming_earnings
from quant_engine.screeners.fundamental_screener import FundamentalDataUnavailable, FundamentalMetrics, fetch_fundamentals
from quant_engine.screeners.news_events import tag_headline
from quant_engine.screeners.sentiment_scorer import fetch_headlines, score_headlines

DEFAULT_HEADLINE_LIMIT = 10
DEFAULT_EARNINGS_WITHIN_DAYS = 14


@dataclass(frozen=True)
class HeadlineItem:
    title: str
    sentiment_score: float
    tags: list[str]


@dataclass(frozen=True)
class ResearchBriefing:
    ticker: str
    fundamentals: FundamentalMetrics | None
    price_nzd: float | None
    sentiment_score: float
    upcoming_earnings: UpcomingEarnings | None
    last_earnings: RecentEarnings | None
    headlines: list[HeadlineItem] = field(default_factory=list)


def build_briefing(
    ticker: str,
    fx_converter: FXConverter | None = None,
    headline_limit: int = DEFAULT_HEADLINE_LIMIT,
    earnings_within_days: int = DEFAULT_EARNINGS_WITHIN_DAYS,
) -> ResearchBriefing:
    fx_converter = fx_converter or FXConverter()

    try:
        fundamentals = fetch_fundamentals(ticker)
    except FundamentalDataUnavailable:
        fundamentals = None

    price_nzd = fx_converter.convert_to_nzd(fundamentals.price) if fundamentals else None

    headlines_raw = fetch_headlines(ticker, limit=headline_limit)
    headline_items = [
        HeadlineItem(title=headline, sentiment_score=score_headlines([headline]), tags=tag_headline(headline))
        for headline in headlines_raw
    ]
    overall_sentiment = score_headlines(headlines_raw)
    upcoming = get_upcoming_earnings(ticker, within_days=earnings_within_days)
    last_earnings = get_last_earnings(ticker)

    return ResearchBriefing(
        ticker=ticker,
        fundamentals=fundamentals,
        price_nzd=price_nzd,
        sentiment_score=overall_sentiment,
        upcoming_earnings=upcoming,
        last_earnings=last_earnings,
        headlines=headline_items,
    )


def scan_watchlist(tickers: list[str], **kwargs) -> list[ResearchBriefing]:
    return [build_briefing(ticker, **kwargs) for ticker in tickers]
