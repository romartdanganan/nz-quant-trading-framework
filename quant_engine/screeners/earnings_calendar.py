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
