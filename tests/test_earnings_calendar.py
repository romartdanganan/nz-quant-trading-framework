from datetime import date, timedelta

import pandas as pd
import pytest

from quant_engine.screeners import earnings_calendar as ec


class FakeTicker:
    def __init__(self, df):
        self._df = df

    def get_earnings_dates(self, limit=8):
        return self._df


def make_earnings_df(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (date, eps_estimate, reported_eps)."""
    idx = pd.DatetimeIndex([r[0] for r in rows], tz="America/New_York")
    return pd.DataFrame(
        {"EPS Estimate": [r[1] for r in rows], "Reported EPS": [r[2] for r in rows], "Surprise(%)": [None] * len(rows)},
        index=idx,
    )


def test_get_upcoming_earnings_within_window(monkeypatch):
    future_date = date.today() + timedelta(days=5)
    df = make_earnings_df([(future_date, 1.98, None), (date.today() - timedelta(days=90), 1.5, 1.6)])
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(df)}))

    result = ec.get_upcoming_earnings("AAPL", within_days=14)

    assert result is not None
    assert result.ticker == "AAPL"
    assert result.earnings_date == future_date
    assert result.eps_estimate == pytest.approx(1.98)
    assert result.days_until == 5


def test_get_upcoming_earnings_outside_window_returns_none(monkeypatch):
    far_future = date.today() + timedelta(days=60)
    df = make_earnings_df([(far_future, 1.98, None)])
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(df)}))

    assert ec.get_upcoming_earnings("AAPL", within_days=14) is None


def test_get_upcoming_earnings_no_future_rows_returns_none(monkeypatch):
    df = make_earnings_df([(date.today() - timedelta(days=90), 1.5, 1.6)])
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(df)}))

    assert ec.get_upcoming_earnings("AAPL") is None


def test_get_upcoming_earnings_handles_empty_dataframe(monkeypatch):
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(pd.DataFrame())}))
    assert ec.get_upcoming_earnings("AAPL") is None


def test_get_upcoming_earnings_handles_fetch_error(monkeypatch):
    def raise_error(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": staticmethod(raise_error)}))
    assert ec.get_upcoming_earnings("AAPL") is None


def test_scan_watchlist_earnings_sorts_by_days_until(monkeypatch):
    soon = date.today() + timedelta(days=3)
    later = date.today() + timedelta(days=10)

    def fake_ticker(ticker):
        if ticker == "SOON":
            return FakeTicker(make_earnings_df([(soon, 1.0, None)]))
        return FakeTicker(make_earnings_df([(later, 2.0, None)]))

    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": staticmethod(fake_ticker)}))

    results = ec.scan_watchlist_earnings(["LATER_TICKER", "SOON"], within_days=14)

    assert [r.ticker for r in results] == ["SOON", "LATER_TICKER"]
