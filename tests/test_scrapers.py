import requests

from strategy_research.scrapers import blog_scraper, forum_scraper, github_scraper

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Sample</title>
<item><title>Momentum Post</title><link>https://blog.example.com/post</link>
<description>A momentum trading writeup</description></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

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
    monkeypatch.setattr(github_scraper.requests, "get", lambda *a, **k: FakeResponse(payload))

    results = github_scraper.search_repositories("mean reversion", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://github.com/user/repo"
    assert "mean reversion bot" in results[0].text.lower()


def test_github_search_repositories_handles_request_error(monkeypatch):
    def raise_error(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr(github_scraper.requests, "get", raise_error)

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
