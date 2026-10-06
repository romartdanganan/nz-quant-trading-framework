"""Quant-blog RSS feed scraper — official RSS feeds, never raw HTML scraping (see CLAUDE.md
Guardrails). feedparser can fetch a URL itself, but its internal urllib call has no
timeout at all — a slow/unresponsive feed host can hang the whole scraper (and therefore
the whole discovery cycle) indefinitely, a real bug found 2026-10-06 when the new daily
scheduled discovery task hung for 10+ minutes on nothing. requests.get() with an explicit
timeout fetches the raw bytes instead, and feedparser just parses those — same output,
bounded worst case.
"""
from __future__ import annotations

import logging

import feedparser
import requests

from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://quantocracy.com/feed/",
]

REQUEST_TIMEOUT_SECONDS = 20


def fetch_feed_entries(
    feed_urls: list[str] | None = None, max_results_per_feed: int = 10
) -> list[RawSource]:
    sources: list[RawSource] = []
    for feed_url in feed_urls or DEFAULT_FEEDS:
        try:
            response = requests.get(feed_url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception as exc:
            logger.warning("Failed to parse feed %s: %s", feed_url, exc)
            continue

        for entry in parsed.entries[:max_results_per_feed]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")
            sources.append(RawSource(text=f"{title}: {summary}", url=link, title=title))
    return sources
