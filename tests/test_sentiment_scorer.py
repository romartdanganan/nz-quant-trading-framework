import pytest

from quant_engine.screeners import sentiment_scorer as ss
from quant_engine.screeners.sentiment_scorer import (
    SentimentUnavailable,
    fetch_headlines,
    score_headlines,
    score_ticker,
)


class FakeTicker:
    def __init__(self, news):
        self.news = news


def test_fetch_headlines_parses_nested_content_format(monkeypatch):
    news = [{"content": {"title": "Stock soars on strong earnings"}}, {"content": {"title": "Shares dip slightly"}}]
    monkeypatch.setattr(ss, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(news)}))

    headlines = fetch_headlines("AAPL")

    assert headlines == ["Stock soars on strong earnings", "Shares dip slightly"]


def test_fetch_headlines_parses_flat_format(monkeypatch):
    news = [{"title": "Flat format headline"}]
    monkeypatch.setattr(ss, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(news)}))

    assert fetch_headlines("AAPL") == ["Flat format headline"]


def test_fetch_headlines_respects_limit(monkeypatch):
    news = [{"content": {"title": f"Headline {i}"}} for i in range(20)]
    monkeypatch.setattr(ss, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(news)}))

    assert len(fetch_headlines("AAPL", limit=5)) == 5


def test_fetch_headlines_handles_error_gracefully(monkeypatch):
    def raise_error(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(ss, "yf", type("M", (), {"Ticker": staticmethod(raise_error)}))

    assert fetch_headlines("AAPL") == []


def test_score_headlines_empty_list_is_zero():
    assert score_headlines([]) == 0.0


def test_score_headlines_distinguishes_positive_and_negative():
    positive = score_headlines(["Company crushes earnings expectations, stock soars on great news"])
    negative = score_headlines(["Company faces massive fraud lawsuit, shares plunge on terrible news"])
    assert positive > 0
    assert negative < 0


def test_score_ticker_combines_fetch_and_score(monkeypatch):
    news = [{"content": {"title": "Great news, stock rallies on excellent results"}}]
    monkeypatch.setattr(ss, "yf", type("M", (), {"Ticker": lambda t: FakeTicker(news)}))

    result = score_ticker("AAPL")

    assert result.ticker == "AAPL"
    assert result.headline_count == 1
    assert result.label == "bullish"
    assert result.mean_compound_score > 0


def test_score_ticker_no_headlines_is_neutral(monkeypatch):
    monkeypatch.setattr(ss, "yf", type("M", (), {"Ticker": lambda t: FakeTicker([])}))

    result = score_ticker("AAPL")

    assert result.headline_count == 0
    assert result.mean_compound_score == 0.0
    assert result.label == "neutral"


def test_sentiment_unavailable_when_lexicon_cannot_be_obtained(monkeypatch):
    monkeypatch.setattr(ss, "_analyzer", None)

    def raise_lookup(*args, **kwargs):
        raise LookupError("not found")

    def raise_download(*args, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(ss.nltk.data, "find", raise_lookup)
    monkeypatch.setattr(ss.nltk, "download", raise_download)

    with pytest.raises(SentimentUnavailable):
        score_headlines(["some headline"])
