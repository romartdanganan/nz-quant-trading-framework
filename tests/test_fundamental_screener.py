import pandas as pd
import pytest

from quant_engine.screeners import fundamental_screener as fs
from quant_engine.screeners.fundamental_screener import (
    FundamentalDataUnavailable,
    FundamentalMetrics,
    ScreenerCriteria,
    evaluate,
    fetch_fundamentals,
    screen,
)


class FakeTicker:
    def __init__(self, info=None, earnings_df=None, earnings_error=None):
        self.info = info or {}
        self._earnings_df = earnings_df
        self._earnings_error = earnings_error

    def get_earnings_dates(self, limit=8):
        if self._earnings_error:
            raise self._earnings_error
        return self._earnings_df


def make_earnings_df(surprise_values):
    return pd.DataFrame({"Surprise(%)": surprise_values})


def test_fetch_fundamentals_parses_info_and_latest_surprise(monkeypatch):
    info = {
        "currentPrice": 150.0,
        "trailingPE": 22.0,
        "pegRatio": 1.2,
        "debtToEquity": 80.0,
        "revenueGrowth": 0.15,
    }
    earnings = make_earnings_df([6.5, 3.0, None])
    monkeypatch.setattr(fs, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(info, earnings)}))

    metrics = fetch_fundamentals("AAPL")

    assert metrics.ticker == "AAPL"
    assert metrics.price == 150.0
    assert metrics.pe_ratio == 22.0
    assert metrics.peg_ratio == 1.2
    assert metrics.latest_earnings_surprise_pct == 6.5


def test_fetch_fundamentals_raises_when_no_price(monkeypatch):
    monkeypatch.setattr(fs, "yf", type("M", (), {"Ticker": lambda t: FakeTicker({})}))

    with pytest.raises(FundamentalDataUnavailable):
        fetch_fundamentals("BADTICKER")


def test_fetch_fundamentals_handles_earnings_error_gracefully(monkeypatch):
    info = {"currentPrice": 100.0}
    monkeypatch.setattr(
        fs, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(info, earnings_error=RuntimeError("boom"))})
    )

    metrics = fetch_fundamentals("XYZ")
    assert metrics.latest_earnings_surprise_pct is None


def make_metrics(**overrides) -> FundamentalMetrics:
    defaults = dict(
        ticker="T",
        price=100.0,
        pe_ratio=20.0,
        peg_ratio=1.0,
        debt_to_equity=50.0,
        revenue_growth=0.1,
        latest_earnings_surprise_pct=5.0,
    )
    defaults.update(overrides)
    return FundamentalMetrics(**defaults)


def test_evaluate_passes_healthy_metrics():
    result = evaluate(make_metrics())
    assert result.passed is True
    assert result.reasons_failed == []
    assert result.score > 50.0  # healthier than the neutral baseline


def test_evaluate_fails_high_pe():
    result = evaluate(make_metrics(pe_ratio=100.0), ScreenerCriteria(max_pe=40.0))
    assert result.passed is False
    assert any("P/E" in reason for reason in result.reasons_failed)


def test_evaluate_fails_high_debt_to_equity():
    result = evaluate(make_metrics(debt_to_equity=500.0), ScreenerCriteria(max_debt_to_equity=150.0))
    assert result.passed is False
    assert any("D/E" in reason for reason in result.reasons_failed)


def test_evaluate_missing_fields_do_not_fail():
    metrics = make_metrics(pe_ratio=None, peg_ratio=None, debt_to_equity=None, revenue_growth=None,
                            latest_earnings_surprise_pct=None)
    result = evaluate(metrics)
    assert result.passed is True
    assert result.score == 50.0  # neutral baseline, nothing to reward or penalize


def test_screen_skips_unavailable_and_sorts_by_score(monkeypatch):
    def fake_ticker(ticker):
        if ticker == "BAD":
            return FakeTicker({})  # no price -> FundamentalDataUnavailable
        info = {"currentPrice": 100.0, "trailingPE": 10.0 if ticker == "GOOD" else 90.0}
        return FakeTicker(info, make_earnings_df([]))

    monkeypatch.setattr(fs, "yf", type("M", (), {"Ticker": staticmethod(fake_ticker)}))

    results = screen(["BAD", "OK", "GOOD"])

    assert [r.metrics.ticker for r in results] == ["GOOD", "OK"]
    assert results[0].score > results[1].score
