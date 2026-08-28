"""GitHub Search API scraper — official REST API, never raw HTML scraping (see CLAUDE.md
Guardrails). Works unauthenticated at a low rate limit; set GITHUB_TOKEN in .env for a
higher limit. Unauthenticated requests are noticeably slower/flakier than authenticated
ones in practice, so this retries once on a timeout before giving up on that query.
"""
from __future__ import annotations

import logging

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from config.settings import get_env
from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
REQUEST_TIMEOUT_SECONDS = 20


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(requests.Timeout),
)
def _get(url: str, headers: dict, params: dict):
    return requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)


def search_repositories(query: str, max_results: int = 10) -> list[RawSource]:
    headers = {"Accept": "application/vnd.github+json"}
    token = get_env("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 30)}
    try:
        response = _get(GITHUB_SEARCH_URL, headers, params)
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
