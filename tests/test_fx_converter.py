from datetime import date

import pytest
import requests

from nz_tax_fx.fx_converter import FXConverter, FXRateUnavailable


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_latest_rate_is_cached_within_instance(tmp_path, monkeypatch):
    converter = FXConverter(cache_path=tmp_path / "fx.json")
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return FakeResponse({"rates": {"NZD": 1.64}})

    monkeypatch.setattr("nz_tax_fx.fx_converter.requests.get", fake_get)

    assert converter.get_rate() == 1.64
    assert converter.get_rate() == 1.64
    assert len(calls) == 1


def test_get_historical_rate(tmp_path, monkeypatch):
    converter = FXConverter(cache_path=tmp_path / "fx.json")
    monkeypatch.setattr(
        "nz_tax_fx.fx_converter.requests.get",
        lambda url, params=None, timeout=None: FakeResponse({"rates": {"NZD": 1.58}}),
    )

    assert converter.get_rate(date(2024, 1, 15)) == 1.58


def test_convert_to_nzd(tmp_path, monkeypatch):
    converter = FXConverter(cache_path=tmp_path / "fx.json")
    monkeypatch.setattr(
        "nz_tax_fx.fx_converter.requests.get",
        lambda url, params=None, timeout=None: FakeResponse({"rates": {"NZD": 1.6}}),
    )

    assert converter.convert_to_nzd(100) == pytest.approx(160.0)


def test_get_rate_raises_when_api_fails(tmp_path, monkeypatch):
    converter = FXConverter(cache_path=tmp_path / "fx.json")

    def raise_error(url, params=None, timeout=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr("nz_tax_fx.fx_converter.requests.get", raise_error)

    with pytest.raises(FXRateUnavailable):
        converter.get_rate()


def test_get_rate_raises_on_malformed_response(tmp_path, monkeypatch):
    converter = FXConverter(cache_path=tmp_path / "fx.json")
    monkeypatch.setattr(
        "nz_tax_fx.fx_converter.requests.get",
        lambda url, params=None, timeout=None: FakeResponse({"unexpected": "shape"}),
    )

    with pytest.raises(FXRateUnavailable):
        converter.get_rate(date(2024, 1, 15))


def test_historical_rate_cache_persists_to_disk_across_instances(tmp_path, monkeypatch):
    cache_path = tmp_path / "fx.json"
    converter1 = FXConverter(cache_path=cache_path)
    monkeypatch.setattr(
        "nz_tax_fx.fx_converter.requests.get",
        lambda url, params=None, timeout=None: FakeResponse({"rates": {"NZD": 1.7}}),
    )
    converter1.get_rate(date(2024, 6, 1))

    def fail_if_called(*a, **k):
        raise AssertionError("should be served from the persisted cache, not the API")

    converter2 = FXConverter(cache_path=cache_path)
    monkeypatch.setattr("nz_tax_fx.fx_converter.requests.get", fail_if_called)

    assert converter2.get_rate(date(2024, 6, 1)) == 1.7
