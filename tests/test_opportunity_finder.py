from quant_engine.screeners import opportunity_finder as of


def _fake_response(quotes):
    return {"quotes": quotes}


def test_discover_candidate_tickers_dedupes_and_filters_by_market_cap(monkeypatch):
    def fake_screen(query, count=None):
        if query == "aggressive_small_caps":
            return _fake_response(
                [
                    {"symbol": "SMALL1", "marketCap": 500_000_000},
                    {"symbol": "BIG1", "marketCap": 50_000_000_000},
                ]
            )
        return _fake_response([{"symbol": "SMALL1", "marketCap": 500_000_000}, {"symbol": "SMALL2", "marketCap": 1_000_000_000}])

    monkeypatch.setattr(of.yf, "screen", fake_screen)

    tickers = of.discover_candidate_tickers(queries=["aggressive_small_caps", "small_cap_gainers"], max_market_cap=10_000_000_000)

    assert sorted(tickers) == ["SMALL1", "SMALL2"]


def test_discover_candidate_tickers_skips_missing_fields(monkeypatch):
    def fake_screen(query, count=None):
        return _fake_response([{"symbol": None, "marketCap": 1}, {"symbol": "OK", "marketCap": None}])

    monkeypatch.setattr(of.yf, "screen", fake_screen)

    assert of.discover_candidate_tickers(queries=["q"]) == []


def test_discover_candidate_tickers_handles_query_failure(monkeypatch):
    def fake_screen(query, count=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(of.yf, "screen", fake_screen)

    assert of.discover_candidate_tickers(queries=["q"]) == []


def test_find_opportunities_feeds_discovered_tickers_into_build_watchlist(monkeypatch):
    monkeypatch.setattr(of, "discover_candidate_tickers", lambda *a, **kw: ["A", "B"])
    captured = {}

    def fake_build_watchlist(tickers, criteria=None):
        captured["tickers"] = tickers
        return ["entry-for-" + t for t in tickers]

    monkeypatch.setattr(of, "build_watchlist", fake_build_watchlist)

    result = of.find_opportunities()

    assert captured["tickers"] == ["A", "B"]
    assert result == ["entry-for-A", "entry-for-B"]
