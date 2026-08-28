"""arXiv API scraper — official Atom feed API (export.arxiv.org), never raw HTML scraping
(see CLAUDE.md Guardrails). Keyless and free. Uses feedparser the same way blog_scraper.py
does, since arXiv's export API returns a standard Atom feed — paper abstracts often carry
genuinely concrete, numeric strategy detail (specific parameter values from a backtested
study) that a one-line GitHub repo description or forum post title never does.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import feedparser

from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"


def search_papers(query: str, max_results: int = 5) -> list[RawSource]:
    url = f"{ARXIV_API_URL}?search_query=all:{quote(query)}&start=0&max_results={max_results}"
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:
        logger.warning("arXiv search failed for query %r: %s", query, exc)
        return []

    sources = []
    for entry in parsed.entries[:max_results]:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        link = entry.get("link", "") or entry.get("id", "")
        sources.append(RawSource(text=f"{title}: {summary}", url=link, title=title))
    return sources
