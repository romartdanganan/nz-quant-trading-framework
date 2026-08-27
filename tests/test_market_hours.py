from datetime import date, datetime
from zoneinfo import ZoneInfo

from execution_ibkr.market_hours import is_us_market_open, us_market_session_nzt


def test_us_market_session_converts_to_utc_correctly():
    # 2026-01-15 is US winter (EST, UTC-5): 09:30 ET = 14:30 UTC
    session = us_market_session_nzt(date(2026, 1, 15))
    assert session.open_utc == datetime(2026, 1, 15, 14, 30, tzinfo=ZoneInfo("UTC"))
    assert session.close_utc == datetime(2026, 1, 15, 21, 0, tzinfo=ZoneInfo("UTC"))


def test_us_market_session_converts_to_nzt_correctly():
    # NZ is in NZDT (UTC+13) in January (southern summer) — session rolls into the next NZ day
    session = us_market_session_nzt(date(2026, 1, 15))
    assert session.open_nzt == datetime(2026, 1, 16, 3, 30, tzinfo=ZoneInfo("Pacific/Auckland"))


def test_is_us_market_open_true_during_session():
    check_time = datetime(2026, 1, 15, 14, 35, tzinfo=ZoneInfo("UTC"))  # 09:35 ET
    assert is_us_market_open(check_time) is True


def test_is_us_market_open_false_outside_session():
    check_time = datetime(2026, 1, 15, 5, 0, tzinfo=ZoneInfo("UTC"))  # 00:00 ET — too early
    assert is_us_market_open(check_time) is False


def test_is_us_market_open_false_on_weekend():
    check_time = datetime(2026, 1, 17, 15, 0, tzinfo=ZoneInfo("UTC"))  # 2026-01-17 is a Saturday
    assert is_us_market_open(check_time) is False


def test_dst_offset_differs_between_january_and_july():
    # US: EST (UTC-5) in Jan vs EDT (UTC-4) in Jul. NZ: NZDT (UTC+13) in Jan vs NZST (UTC+12) in Jul.
    # The NZT clock-time of the open should differ between the two even though the local
    # US open time (09:30 ET) never changes — proving DST is re-derived, not hardcoded.
    jan_session = us_market_session_nzt(date(2026, 1, 15))
    jul_session = us_market_session_nzt(date(2026, 7, 15))
    assert jan_session.open_nzt.hour != jul_session.open_nzt.hour
