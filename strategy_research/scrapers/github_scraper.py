"""GitHub Search API scraper — official REST API, never raw HTML scraping (see CLAUDE.md
Guardrails). Works unauthenticated at a low rate limit; set GITHUB_TOKEN in .env for a
higher limit.
"""
from __future__ import annotations

import logging

import requests

from config.settings import get_env
from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"


def search_repositories(query: str, max_results: int = 10) -> list[RawSource]:
    headers = {"Accept": "application/vnd.github+json"}
    token = get_env("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 30)}
    try:
        response = requests.get(GITHUB_SEARCH_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("GitHub search failed for query %r: %s", query, exc)
        return []

    items = response.json().get("items", [])[:max_results]
    return [
        RawSource(
            text=f"{item.get('full_name', '')}: {item.get('description') or ''}",
            url=item.get("html_url", ""),
            title=item.get("full_name", ""),
        )
        for item in items
    ]
