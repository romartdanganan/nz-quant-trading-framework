import pandas as pd
import pytest
from datetime import date

from backtester import data_loader
from backtester.data_loader import PriceDataUnavailable, load_price_data


def _fake_multiindex_download(*args, **kwargs):
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    columns = pd.MultiIndex.from_product([["Close", "High", "Low", "Open", "Volume"], ["AAPL"]])
    return pd.DataFrame(
        [[100, 101, 99, 100, 1000], [101, 102, 100, 100, 1100], [102, 103, 101, 101, 1200]],
        index=dates,
        columns=columns,
    )


def test_load_price_data_normalizes_multiindex_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(data_loader.yf, "download", _fake_multiindex_download)

    df = load_price_data("AAPL", date(2024, 1, 1), date(2024, 1, 3), historical_dir=tmp_path)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3


def test_load_price_data_uses_cache_on_second_call(tmp_path, monkeypatch):
    calls = {"n": 0}

    def counting_download(*args, **kwargs):
        calls["n"] += 1
        return _fake_multiindex_download()

    monkeypatch.setattr(data_loader.yf, "download", counting_download)

    load_price_data("AAPL", date(2024, 1, 1), date(2024, 1, 3), historical_dir=tmp_path)
    load_price_data("AAPL", date(2024, 1, 1), date(2024, 1, 3), historical_dir=tmp_path)

    assert calls["n"] == 1


def test_load_price_data_raises_on_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(data_loader.yf, "download", lambda *a, **k: pd.DataFrame())

    with pytest.raises(PriceDataUnavailable):
        load_price_data("BADTICKER", date(2024, 1, 1), date(2024, 1, 3), historical_dir=tmp_path)


def test_load_price_data_raises_on_download_error(tmp_path, monkeypatch):
    def raise_error(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(data_loader.yf, "download", raise_error)

    with pytest.raises(PriceDataUnavailable):
        load_price_data("AAPL", date(2024, 1, 1), date(2024, 1, 3), historical_dir=tmp_path)
