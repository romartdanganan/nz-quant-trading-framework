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
    """rows: list of (date, eps_estimate, reported_eps) or (date, eps_estimate, reported_eps, surprise_pct)."""
    idx = pd.DatetimeIndex([r[0] for r in rows], tz="America/New_York")
    surprises = [r[3] if len(r) > 3 else None for r in rows]
    return pd.DataFrame(
        {"EPS Estimate": [r[1] for r in rows], "Reported EPS": [r[2] for r in rows], "Surprise(%)": surprises},
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


def test_get_last_earnings_returns_most_recent_reported(monkeypatch):
    older = date.today() - timedelta(days=120)
    newer = date.today() - timedelta(days=30)
    df = make_earnings_df([(older, 1.5, 1.6, 6.7), (newer, 2.0, 2.2, 10.0)])
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(df)}))

    result = ec.get_last_earnings("AAPL")

    assert result is not None
    assert result.ticker == "AAPL"
    assert result.earnings_date == newer
    assert result.eps_estimate == pytest.approx(2.0)
    assert result.reported_eps == pytest.approx(2.2)
    assert result.surprise_pct == pytest.approx(10.0)
    assert result.days_since == 30


def test_get_last_earnings_ignores_unreported_future_rows(monkeypatch):
    future = date.today() + timedelta(days=5)
    past = date.today() - timedelta(days=10)
    df = make_earnings_df([(future, 1.98, None), (past, 1.5, 1.6, 6.7)])
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(df)}))

    result = ec.get_last_earnings("AAPL")

    assert result is not None
    assert result.earnings_date == past


def test_get_last_earnings_no_reported_rows_returns_none(monkeypatch):
    future = date.today() + timedelta(days=5)
    df = make_earnings_df([(future, 1.98, None)])
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(df)}))

    assert ec.get_last_earnings("AAPL") is None


def test_get_last_earnings_handles_empty_dataframe(monkeypatch):
    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(pd.DataFrame())}))
    assert ec.get_last_earnings("AAPL") is None


def test_get_last_earnings_handles_fetch_error(monkeypatch):
    def raise_error(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(ec, "yf", type("M", (), {"Ticker": staticmethod(raise_error)}))
    assert ec.get_last_earnings("AAPL") is None
