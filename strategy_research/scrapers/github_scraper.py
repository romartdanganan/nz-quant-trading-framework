"""GitHub Search API scraper — official REST API, never raw HTML scraping (see CLAUDE.md
Guardrails). Works unauthenticated at a low rate limit; set GITHUB_TOKEN in .env for a
higher limit. Unauthenticated requests are noticeably slower/flakier than authenticated
ones in practice, so this retries once on a timeout before giving up on that query.

Also fetches each repo's README (real bug found 2026-08-28: search results only carry
GitHub's one-line repo description, e.g. "RSI mean-reversion strategy. Built for small
accounts." — never enough concrete detail (actual threshold numbers, entry/exit logic) for
either the free rule_extractor or Gemini to extract a real rule from; every extraction
attempt was correctly rejecting this thin text as not "concrete, testable"). README fetch
failures (no README, rate-limited, private repo quirks) degrade gracefully to the
description-only text rather than dropping the source.
"""
from __future__ import annotations

import logging

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from config.settings import get_env
from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_README_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/readme"
REQUEST_TIMEOUT_SECONDS = 20
README_MAX_CHARS = 8000


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(requests.Timeout),
)
def _get(url: str, headers: dict, params: dict):
    return requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)


def _fetch_readme(full_name: str, headers: dict) -> str:
    readme_headers = {**headers, "Accept": "application/vnd.github.raw+json"}
    try:
        response = _get(GITHUB_README_URL_TEMPLATE.format(full_name=full_name), readme_headers, {})
    except requests.RequestException as exc:
        logger.info("Could not fetch README for %s: %s", full_name, exc)
        return ""
    if response.status_code != 200:
        return ""  # no README, private/renamed repo, rate-limited, etc. — degrade gracefully
    return response.text[:README_MAX_CHARS]


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
    sources = []
    for item in items:
        full_name = item.get("full_name", "")
        description = item.get("description") or ""
        readme = _fetch_readme(full_name, headers) if full_name else ""
        text = f"{full_name}: {description}"
        if readme:
            text = f"{text}\n\n{readme}"
        sources.append(RawSource(text=text, url=item.get("html_url", ""), title=full_name))
    return sources
