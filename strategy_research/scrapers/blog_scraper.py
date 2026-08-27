"""Quant-blog RSS feed scraper — official RSS feeds, never raw HTML scraping (see CLAUDE.md
Guardrails). feedparser accepts a URL, filename, or raw XML string transparently.
"""
from __future__ import annotations

import logging

import feedparser

from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://quantocracy.com/feed/",
]


def fetch_feed_entries(
    feed_urls: list[str] | None = None, max_results_per_feed: int = 10
) -> list[RawSource]:
    sources: list[RawSource] = []
    for feed_url in feed_urls or DEFAULT_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as exc:
            logger.warning("Failed to parse feed %s: %s", feed_url, exc)
            continue

        for entry in parsed.entries[:max_results_per_feed]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")
            sources.append(RawSource(text=f"{title}: {summary}", url=link, title=title))
    return sources
