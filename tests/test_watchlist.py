from quant_engine.screeners import watchlist as wl
from quant_engine.screeners.fundamental_screener import FundamentalMetrics, ScreenResult
from quant_engine.screeners.sentiment_scorer import SentimentResult


def make_result(ticker, score, passed=True, reasons=None):
    metrics = FundamentalMetrics(
        ticker=ticker,
        price=100.0,
        pe_ratio=20.0,
        peg_ratio=1.0,
        debt_to_equity=50.0,
        revenue_growth=0.1,
        latest_earnings_surprise_pct=5.0,
    )
    return ScreenResult(metrics=metrics, score=score, passed=passed, reasons_failed=reasons or [])


def test_build_watchlist_filters_out_failed_screens(monkeypatch):
    monkeypatch.setattr(
        wl,
        "screen",
        lambda tickers, criteria: [make_result("GOOD", 80.0), make_result("BAD", 10.0, passed=False, reasons=["P/E too high"])],
    )
    monkeypatch.setattr(wl, "score_ticker", lambda ticker, limit=10: SentimentResult(ticker, 5, 0.3, "bullish"))
    monkeypatch.setattr(wl, "_suggest_levels", lambda ticker, price, atr_mult, rr: (95.0, 110.0))

    entries = wl.build_watchlist(["GOOD", "BAD"])

    assert [entry.ticker for entry in entries] == ["GOOD"]


def test_build_watchlist_sorts_by_fundamental_score_descending(monkeypatch):
    monkeypatch.setattr(
        wl, "screen", lambda tickers, criteria: [make_result("LOW", 40.0), make_result("HIGH", 90.0)]
    )
    monkeypatch.setattr(wl, "score_ticker", lambda ticker, limit=10: SentimentResult(ticker, 5, 0.0, "neutral"))
    monkeypatch.setattr(wl, "_suggest_levels", lambda ticker, price, atr_mult, rr: (95.0, 110.0))

    entries = wl.build_watchlist(["LOW", "HIGH"])

    assert [entry.ticker for entry in entries] == ["HIGH", "LOW"]


def test_build_watchlist_includes_stop_and_target_levels(monkeypatch):
    monkeypatch.setattr(wl, "screen", lambda tickers, criteria: [make_result("GOOD", 80.0)])
    monkeypatch.setattr(wl, "score_ticker", lambda ticker, limit=10: SentimentResult(ticker, 3, 0.4, "bullish"))
    monkeypatch.setattr(wl, "_suggest_levels", lambda ticker, price, atr_mult, rr: (price - 5.0, price + 10.0))

    entries = wl.build_watchlist(["GOOD"])

    assert entries[0].entry_price == 100.0
    assert entries[0].stop_loss == 95.0
    assert entries[0].target_price == 110.0
    assert entries[0].sentiment_label == "bullish"


def test_suggest_levels_falls_back_when_history_unavailable(monkeypatch):
    class RaisingTicker:
        def history(self, period):
            raise RuntimeError("no data")

    monkeypatch.setattr(wl, "yf", type("M", (), {"Ticker": lambda t: RaisingTicker()}))

    stop_loss, target_price = wl._suggest_levels("XYZ", price=100.0, atr_multiplier=2.0, reward_risk_ratio=2.0)

    # fallback: 2% of price as stop distance
    assert stop_loss == 100.0 - (100.0 * 0.02 * 2.0)
    assert target_price == 100.0 + (100.0 * 0.02 * 2.0 * 2.0)
