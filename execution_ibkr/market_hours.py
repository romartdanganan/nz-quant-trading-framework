"""Converts the US market session (America/New_York, regular session 09:30-16:00 ET) into
NZST/NZDT. Per CLAUDE.md: NZ and US switch daylight saving on different dates, so the NZT
offset to US market hours shifts by an hour twice a year at different times than the US
does — always re-derive the session window with a tz-aware library, never a fixed offset.

Known limitation: this has no market-holiday calendar (Thanksgiving, Christmas, etc.) — it
only knows about weekends and the regular session clock. Don't rely on it alone to decide
whether the market is open on a specific date without cross-checking a trading calendar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

US_MARKET_TZ = ZoneInfo("America/New_York")
NZ_TZ = ZoneInfo("Pacific/Auckland")
UTC = ZoneInfo("UTC")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


@dataclass(frozen=True)
class MarketSession:
    open_utc: datetime
    close_utc: datetime
    open_nzt: datetime
    close_nzt: datetime


def us_market_session_nzt(session_date: date) -> MarketSession:
    """Returns the US regular session's open/close for a given US calendar trading date,
    converted to NZT. Does not check whether session_date is actually a trading day (see
    module limitation note) — callers should skip weekends/holidays before calling this.
    """
    open_us = datetime.combine(session_date, MARKET_OPEN, tzinfo=US_MARKET_TZ)
    close_us = datetime.combine(session_date, MARKET_CLOSE, tzinfo=US_MARKET_TZ)

    return MarketSession(
        open_utc=open_us.astimezone(UTC),
        close_utc=close_us.astimezone(UTC),
        open_nzt=open_us.astimezone(NZ_TZ),
        close_nzt=close_us.astimezone(NZ_TZ),
    )


def is_us_market_open(check_time_utc: datetime) -> bool:
    """Naive session check (weekday + regular-session clock only, no holiday calendar —
    see module limitation note). check_time_utc must be timezone-aware.
    """
    local = check_time_utc.astimezone(US_MARKET_TZ)
    if local.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    session = us_market_session_nzt(local.date())
    return session.open_utc <= check_time_utc <= session.close_utc
