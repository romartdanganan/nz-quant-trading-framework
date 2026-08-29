import pytest

from strategy_research.distiller import gemini_client


class FakeResponse:
    def __init__(self, text: str):
        self.text = text


class FakeModels:
    def __init__(self, text: str = "", exc: Exception | None = None, exc_sequence: list | None = None):
        self._text = text
        self._exc = exc
        self._exc_sequence = exc_sequence
        self.calls = 0

    def generate_content(self, model, contents):
        self.calls += 1
        if self._exc_sequence is not None:
            outcome = self._exc_sequence[min(self.calls, len(self._exc_sequence)) - 1]
            if outcome is not None:
                raise outcome
            return FakeResponse(self._text)
        if self._exc:
            raise self._exc
        return FakeResponse(self._text)


class FakeClient:
    def __init__(self, text: str = "", exc: Exception | None = None, exc_sequence: list | None = None):
        self.models = FakeModels(text=text, exc=exc, exc_sequence=exc_sequence)


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


def test_distill_raises_transient_error_on_503_after_retry(monkeypatch):
    # A real bug found 2026-08-30: this used to fall through to the generic except branch
    # and silently return [], which the pipeline then treated as "genuinely evaluated,
    # nothing found" and permanently blacklisted the source.
    client = FakeClient(exc=RuntimeError("503 UNAVAILABLE: high demand"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(gemini_client, "_get_client", lambda: client)

    with pytest.raises(gemini_client.GeminiTransientError):
        gemini_client.distill("raw text")

    assert client.models.calls == 2  # one retry attempted before giving up


def test_distill_retries_transient_error_then_succeeds(monkeypatch):
    payload = '[{"name": "x", "archetype": "momentum", "entry_conditions": [], "confidence": 0.6}]'
    client = FakeClient(text=payload, exc_sequence=[RuntimeError("503 UNAVAILABLE"), None])
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(gemini_client, "_get_client", lambda: client)

    result = gemini_client.distill("raw text")

    assert client.models.calls == 2
    assert result == [{"name": "x", "archetype": "momentum", "entry_conditions": [], "confidence": 0.6}]


def test_distill_does_not_retry_quota_exceeded(monkeypatch):
    # Retrying a 429 immediately is pointless — a free-tier daily quota won't clear in the
    # 1-second fixed wait. Only genuinely transient errors are worth a retry.
    client = FakeClient(exc=RuntimeError("429 RESOURCE_EXHAUSTED"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(gemini_client, "_get_client", lambda: client)

    with pytest.raises(gemini_client.GeminiQuotaExceeded):
        gemini_client.distill("raw text")

    assert client.models.calls == 1
