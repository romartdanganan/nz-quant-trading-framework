"""Upcoming earnings-date tracking via yfinance — deterministic, no LLM (CLAUDE.md
Guardrails). Surfaces real, dated facts (a reporting date and an analyst EPS estimate),
not a prediction of what the report will say.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import yfinance as yf

DEFAULT_WITHIN_DAYS = 14


@dataclass(frozen=True)
class UpcomingEarnings:
    ticker: str
    earnings_date: date
    eps_estimate: float | None
    days_until: int


@dataclass(frozen=True)
class RecentEarnings:
    ticker: str
    earnings_date: date
    eps_estimate: float | None
    reported_eps: float | None
    surprise_pct: float | None
    days_since: int


def get_upcoming_earnings(ticker: str, within_days: int = DEFAULT_WITHIN_DAYS) -> UpcomingEarnings | None:
    try:
        earnings = yf.Ticker(ticker).get_earnings_dates(limit=8)
    except Exception:
        return None
    if earnings is None or earnings.empty or "Reported EPS" not in earnings.columns:
        return None

    today = date.today()
    future_rows = earnings[earnings["Reported EPS"].isna()]
    upcoming_dates = sorted({idx.date() for idx in future_rows.index if idx.date() >= today})
    if not upcoming_dates:
        return None

    next_date = upcoming_dates[0]
    days_until = (next_date - today).days
    if days_until > within_days:
        return None

    row = future_rows.loc[[idx for idx in future_rows.index if idx.date() == next_date][0]]
    eps_estimate = row.get("EPS Estimate")
    return UpcomingEarnings(
        ticker=ticker,
        earnings_date=next_date,
        eps_estimate=float(eps_estimate) if eps_estimate == eps_estimate else None,  # NaN != NaN
        days_until=days_until,
    )


def scan_watchlist_earnings(tickers: list[str], within_days: int = DEFAULT_WITHIN_DAYS) -> list[UpcomingEarnings]:
    results = [get_upcoming_earnings(ticker, within_days) for ticker in tickers]
    return sorted((r for r in results if r is not None), key=lambda r: r.days_until)


def get_last_earnings(ticker: str) -> RecentEarnings | None:
    """Most recent ALREADY-REPORTED earnings (actual EPS + surprise%), regardless of how
    long ago — callers decide what counts as "recent enough" via days_since.
    """
    try:
        earnings = yf.Ticker(ticker).get_earnings_dates(limit=8)
    except Exception:
        return None
    if earnings is None or earnings.empty or "Reported EPS" not in earnings.columns:
        return None

    today = date.today()
    reported_rows = earnings.dropna(subset=["Reported EPS"])
    past_dates = sorted({idx.date() for idx in reported_rows.index if idx.date() <= today}, reverse=True)
    if not past_dates:
        return None

    most_recent_date = past_dates[0]
    row = reported_rows.loc[[idx for idx in reported_rows.index if idx.date() == most_recent_date][0]]
    eps_estimate = row.get("EPS Estimate")
    reported_eps = row.get("Reported EPS")
    surprise_pct = row.get("Surprise(%)")

    def _clean(value):
        return float(value) if value == value else None  # NaN != NaN

    return RecentEarnings(
        ticker=ticker,
        earnings_date=most_recent_date,
        eps_estimate=_clean(eps_estimate),
        reported_eps=_clean(reported_eps),
        surprise_pct=_clean(surprise_pct),
        days_since=(today - most_recent_date).days,
    )
