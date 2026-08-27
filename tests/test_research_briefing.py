from datetime import date

import pytest

from quant_engine.screeners import research_briefing as rb
from quant_engine.screeners.earnings_calendar import UpcomingEarnings
from quant_engine.screeners.fundamental_screener import FundamentalDataUnavailable, FundamentalMetrics


class FakeFX:
    def convert_to_nzd(self, amount_usd, as_of=None):
        return amount_usd * 1.6


def make_metrics(ticker="AAPL", price=100.0) -> FundamentalMetrics:
    return FundamentalMetrics(
        ticker=ticker, price=price, pe_ratio=20.0, peg_ratio=1.0, debt_to_equity=50.0,
        revenue_growth=0.1, latest_earnings_surprise_pct=5.0,
    )


def test_build_briefing_combines_all_sources(monkeypatch):
    monkeypatch.setattr(rb, "fetch_fundamentals", lambda ticker: make_metrics(ticker))
    monkeypatch.setattr(rb, "fetch_headlines", lambda ticker, limit=10: ["Company beats estimates this quarter"])
    monkeypatch.setattr(rb, "score_headlines", lambda headlines: 0.5 if headlines else 0.0)
    monkeypatch.setattr(
        rb, "get_upcoming_earnings",
        lambda ticker, within_days=14: UpcomingEarnings(ticker, date(2026, 9, 1), 1.5, 4),
    )

    briefing = rb.build_briefing("AAPL", fx_converter=FakeFX())

    assert briefing.ticker == "AAPL"
    assert briefing.fundamentals.price == 100.0
    assert briefing.price_nzd == pytest.approx(160.0)
    assert briefing.sentiment_score == 0.5
    assert briefing.upcoming_earnings.days_until == 4
    assert len(briefing.headlines) == 1
    assert briefing.headlines[0].tags == ["earnings_beat"]


def test_build_briefing_handles_missing_fundamentals(monkeypatch):
    def raise_unavailable(ticker):
        raise FundamentalDataUnavailable("no data")

    monkeypatch.setattr(rb, "fetch_fundamentals", raise_unavailable)
    monkeypatch.setattr(rb, "fetch_headlines", lambda ticker, limit=10: [])
    monkeypatch.setattr(rb, "score_headlines", lambda headlines: 0.0)
    monkeypatch.setattr(rb, "get_upcoming_earnings", lambda ticker, within_days=14: None)

    briefing = rb.build_briefing("BADTICKER", fx_converter=FakeFX())

    assert briefing.fundamentals is None
    assert briefing.price_nzd is None
    assert briefing.upcoming_earnings is None
    assert briefing.headlines == []


def test_scan_watchlist_builds_one_briefing_per_ticker(monkeypatch):
    monkeypatch.setattr(rb, "fetch_fundamentals", lambda ticker: make_metrics(ticker))
    monkeypatch.setattr(rb, "fetch_headlines", lambda ticker, limit=10: [])
    monkeypatch.setattr(rb, "score_headlines", lambda headlines: 0.0)
    monkeypatch.setattr(rb, "get_upcoming_earnings", lambda ticker, within_days=14: None)

    briefings = rb.scan_watchlist(["AAPL", "MSFT"], fx_converter=FakeFX())

    assert [b.ticker for b in briefings] == ["AAPL", "MSFT"]
