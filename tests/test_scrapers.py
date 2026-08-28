import feedparser
import requests

from strategy_research.scrapers import arxiv_scraper, blog_scraper, forum_scraper, github_scraper

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Sample</title>
<item><title>Momentum Post</title><link>https://blog.example.com/post</link>
<description>A momentum trading writeup</description></item>
</channel></rss>"""

SAMPLE_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<id>http://arxiv.org/abs/1234.5678</id>
<title>A Mean Reversion Strategy for Equity Pairs</title>
<summary>We propose a z-score based mean reversion strategy with entry at 2.0 std dev.</summary>
<link href="http://arxiv.org/abs/1234.5678" rel="alternate"/>
</entry>
</feed>"""


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_github_search_repositories_parses_items(monkeypatch):
    payload = {
        "items": [
            {
                "full_name": "user/repo",
                "description": "A mean reversion bot",
                "html_url": "https://github.com/user/repo",
            }
        ]
    }
    # README fetch hits the same mocked requests.get with no payload/text configured —
    # defaults to an empty README, so this test's assertions only cover the description.
    monkeypatch.setattr(github_scraper.requests, "get", lambda *a, **k: FakeResponse(payload))

    results = github_scraper.search_repositories("mean reversion", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://github.com/user/repo"
    assert "mean reversion bot" in results[0].text.lower()


def test_github_search_repositories_appends_readme_content(monkeypatch):
    payload = {
        "items": [
            {
                "full_name": "user/repo",
                "description": "A mean reversion bot",
                "html_url": "https://github.com/user/repo",
            }
        ]
    }

    def dispatched_get(url, headers=None, params=None, timeout=None):
        if "readme" in url:
            return FakeResponse(status_code=200, text="Buy when RSI(14) < 30, sell when RSI(14) > 70.")
        return FakeResponse(payload)

    monkeypatch.setattr(github_scraper.requests, "get", dispatched_get)

    results = github_scraper.search_repositories("mean reversion", max_results=5)

    assert "rsi(14) < 30" in results[0].text.lower()


def test_github_search_repositories_degrades_gracefully_without_readme(monkeypatch):
    payload = {
        "items": [
            {
                "full_name": "user/repo",
                "description": "A mean reversion bot",
                "html_url": "https://github.com/user/repo",
            }
        ]
    }

    def dispatched_get(url, headers=None, params=None, timeout=None):
        if "readme" in url:
            return FakeResponse(status_code=404)  # no README on this repo
        return FakeResponse(payload)

    monkeypatch.setattr(github_scraper.requests, "get", dispatched_get)

    results = github_scraper.search_repositories("mean reversion", max_results=5)

    assert results[0].text == "user/repo: A mean reversion bot"


def test_github_search_repositories_degrades_gracefully_on_readme_fetch_error(monkeypatch):
    payload = {
        "items": [
            {
                "full_name": "user/repo",
                "description": "A mean reversion bot",
                "html_url": "https://github.com/user/repo",
            }
        ]
    }

    def dispatched_get(url, headers=None, params=None, timeout=None):
        if "readme" in url:
            raise requests.RequestException("boom")
        return FakeResponse(payload)

    monkeypatch.setattr(github_scraper.requests, "get", dispatched_get)

    results = github_scraper.search_repositories("mean reversion", max_results=5)

    assert results[0].text == "user/repo: A mean reversion bot"


def test_github_search_repositories_handles_request_error(monkeypatch):
    def raise_error(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr(github_scraper.requests, "get", raise_error)

    assert github_scraper.search_repositories("mean reversion") == []


def test_github_search_repositories_retries_once_on_timeout_then_succeeds(monkeypatch):
    payload = {"items": [{"full_name": "user/repo", "description": "x", "html_url": "https://github.com/user/repo"}]}
    calls = {"search": 0}

    def flaky_get(url, headers=None, params=None, timeout=None):
        if "readme" in url:
            return FakeResponse(status_code=404)  # isolate this test to the search retry behavior
        calls["search"] += 1
        if calls["search"] == 1:
            raise requests.Timeout("timed out")
        return FakeResponse(payload)

    monkeypatch.setattr(github_scraper.requests, "get", flaky_get)

    results = github_scraper.search_repositories("mean reversion")

    assert calls["search"] == 2
    assert len(results) == 1


def test_github_search_repositories_gives_up_after_repeated_timeouts(monkeypatch):
    def always_timeout(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(github_scraper.requests, "get", always_timeout)

    assert github_scraper.search_repositories("mean reversion") == []


def test_fetch_feed_entries_parses_local_feed():
    results = blog_scraper.fetch_feed_entries(feed_urls=[SAMPLE_RSS])

    assert len(results) == 1
    assert results[0].title == "Momentum Post"
    assert results[0].url == "https://blog.example.com/post"


def test_forum_search_posts_returns_empty_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    assert forum_scraper.search_posts("momentum") == []


def test_arxiv_search_papers_parses_entries(monkeypatch):
    real_parse = feedparser.parse  # capture before patching — feedparser is a shared module
    monkeypatch.setattr(arxiv_scraper.feedparser, "parse", lambda url: real_parse(SAMPLE_ARXIV_ATOM))

    results = arxiv_scraper.search_papers("mean reversion", max_results=5)

    assert len(results) == 1
    assert results[0].url == "http://arxiv.org/abs/1234.5678"
    assert "z-score based mean reversion" in results[0].text.lower()


def test_arxiv_search_papers_handles_parse_error(monkeypatch):
    def raise_error(url):
        raise Exception("boom")

    monkeypatch.setattr(arxiv_scraper.feedparser, "parse", raise_error)

    assert arxiv_scraper.search_papers("mean reversion") == []
