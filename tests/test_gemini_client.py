import pytest

from strategy_research.distiller import gemini_client


class FakeResponse:
    def __init__(self, text: str):
        self.text = text


class FakeModels:
    def __init__(self, text: str = "", exc: Exception | None = None):
        self._text = text
        self._exc = exc

    def generate_content(self, model, contents):
        if self._exc:
            raise self._exc
        return FakeResponse(self._text)


class FakeClient:
    def __init__(self, text: str = "", exc: Exception | None = None):
        self.models = FakeModels(text=text, exc=exc)


def test_distill_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(gemini_client.GeminiNotConfigured):
        gemini_client.distill("some text")


def test_distill_parses_json_array(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    payload = '[{"name": "x", "archetype": "momentum", "entry_conditions": [], "confidence": 0.6}]'
    monkeypatch.setattr(gemini_client, "_get_client", lambda: FakeClient(text=payload))

    result = gemini_client.distill("raw text")

    assert result == [{"name": "x", "archetype": "momentum", "entry_conditions": [], "confidence": 0.6}]


def test_distill_strips_markdown_fences(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    payload = '```json\n[{"name": "x"}]\n```'
    monkeypatch.setattr(gemini_client, "_get_client", lambda: FakeClient(text=payload))

    result = gemini_client.distill("raw text")

    assert result == [{"name": "x"}]


def test_distill_returns_empty_list_on_non_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(gemini_client, "_get_client", lambda: FakeClient(text="not json"))

    assert gemini_client.distill("raw text") == []


def test_distill_raises_quota_exceeded_on_429(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(
        gemini_client, "_get_client", lambda: FakeClient(exc=RuntimeError("429 RESOURCE_EXHAUSTED"))
    )

    with pytest.raises(gemini_client.GeminiQuotaExceeded):
        gemini_client.distill("raw text")
