"""Reddit API scraper (official, via praw) for forum-style strategy discussion — never raw
HTML scraping of forum pages (see CLAUDE.md Guardrails). Requires REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET in .env; without them this returns an empty list rather than failing
the pipeline run.
"""
from __future__ import annotations

import logging

from config.settings import get_env
from strategy_research.scrapers.models import RawSource

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = ["algotrading"]


def search_posts(
    query: str, max_results: int = 10, subreddits: list[str] | None = None
) -> list[RawSource]:
    client_id = get_env("REDDIT_CLIENT_ID")
    client_secret = get_env("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.info("Reddit credentials not configured — skipping forum scraper")
        return []

    import praw  # lazy import: optional dependency until configured

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="nz-quant-trading-framework/0.1",
    )

    sources: list[RawSource] = []
    for subreddit_name in subreddits or DEFAULT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(subreddit_name)
            for submission in subreddit.search(query, limit=max_results):
                sources.append(
                    RawSource(
                        text=f"{submission.title}: {submission.selftext}",
                        url=f"https://reddit.com{submission.permalink}",
                        title=submission.title,
                    )
                )
        except Exception as exc:
            logger.warning("Reddit search failed for r/%s: %s", subreddit_name, exc)
    return sources
