"""Orchestrates the end-to-end automated discovery pipeline (see CLAUDE.md "Automated
strategy discovery pipeline"): scrape -> rule_extractor (primary, free) -> gemini_client
(fallback, quota-capped) -> nl_to_rules (schema validation) -> strategy registry
("candidate"). Single entrypoint, triggered on-demand from cli/main.py option [1] — never
runs on a schedule per the user's explicit choice.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config.settings import settings
from strategy_research.distiller import gemini_client
from strategy_research.registry import StrategyRegistry
from strategy_research.scrapers import arxiv_scraper, blog_scraper, forum_scraper, github_scraper
from strategy_research.scrapers.models import RawSource
from strategy_research.translator import nl_to_rules, rule_extractor

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    # Archetype-level queries (original set) — kept for broad coverage.
    "mean reversion trading strategy",
    "momentum trading strategy",
    "pairs trading strategy",
    "breakout trading strategy",
    # Indicator-level queries — these surface genuinely different repos than the archetype
    # queries above (GitHub's search ranks by relevance to the literal query text, so a
    # fixed small set of generic queries converges on the same top-starred repos every run;
    # varying the terms is what actually broadens candidate coverage, not just having more
    # API quota to re-run the same queries with).
    "RSI mean reversion strategy python",
    "bollinger bands trading strategy python",
    "MACD crossover strategy backtest",
    "keltner channel trading strategy",
    "VWAP trading strategy python",
    "z-score mean reversion strategy",
    "moving average crossover strategy python",
    "channel breakout strategy backtest",
    "cointegration pairs trading python",
    "statistical arbitrage strategy python",
]


def collect_raw_sources(max_sources: int) -> list[RawSource]:
    sources: list[RawSource] = []
    for query in SEARCH_QUERIES:
        sources.extend(github_scraper.search_repositories(query, max_results=5))
    sources.extend(blog_scraper.fetch_feed_entries())
    for query in SEARCH_QUERIES:
        sources.extend(forum_scraper.search_posts(query, max_results=5))
    for query in SEARCH_QUERIES:
        sources.extend(arxiv_scraper.search_papers(query, max_results=3))
    return sources[:max_sources]


def _load_seen(cache_path: Path) -> set[str]:
    if not cache_path.exists():
        return set()
    with open(cache_path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_seen(cache_path: Path, seen: set[str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def run(registry: StrategyRegistry | None = None) -> dict:
    max_sources = settings.get("research_pipeline.max_sources_per_run", 25)
    use_gemini = settings.get("research_pipeline.use_gemini_fallback", True)
    max_gemini_calls = settings.get("research_pipeline.max_gemini_calls_per_run", 10)
    gemini_model = settings.get("research_pipeline.gemini_model", "gemini-3.6-flash")
    cache_path = Path(
        settings.get("research_pipeline.seen_sources_cache", "data/cache/seen_sources.json")
    )

    registry = registry or StrategyRegistry()
    seen = _load_seen(cache_path) | registry.seen_source_urls()

    raw_sources = collect_raw_sources(max_sources)
    new_sources = [source for source in raw_sources if source.url and source.url not in seen]

    accepted = rejected = skipped = gemini_calls_used = 0

    for source in new_sources:
        result = rule_extractor.extract(source.text, source.url, name_hint=source.title)

        if result.spec is not None:
            registry.add_candidate(nl_to_rules.normalize_from_rule_extractor(result.spec))
            accepted += 1
            seen.add(source.url)
        elif use_gemini and gemini_calls_used < max_gemini_calls:
            gemini_calls_used += 1
            try:
                raw_candidates = gemini_client.distill(source.text, model=gemini_model)
            except gemini_client.GeminiNotConfigured:
                # Not a real evaluation — don't mark seen, or this source would never get a
                # fair shot once a key is configured later.
                logger.info("Gemini fallback unavailable (no API key) — skipping %s", source.url)
                skipped += 1
                continue
            except gemini_client.GeminiQuotaExceeded:
                # Same reasoning — quota resets, so don't permanently blacklist this source.
                logger.warning("Gemini quota exhausted — disabling fallback for the rest of this run")
                use_gemini = False
                skipped += 1
                continue

            # We got a real response back (even if it yielded zero usable candidates) —
            # this source was genuinely evaluated, so remember it either way.
            seen.add(source.url)
            promoted_any = False
            for raw_candidate in raw_candidates:
                spec = nl_to_rules.normalize_from_gemini(raw_candidate, source.url)
                if spec is not None:
                    registry.add_candidate(spec)
                    promoted_any = True
            if promoted_any:
                accepted += 1
            else:
                rejected += 1
        else:
            # Never actually evaluated — either Gemini fallback is off, or this run's
            # max_gemini_calls_per_run budget is exhausted. Don't mark seen: a per-run
            # budget cap is meant to spread evaluation across runs over time, not
            # permanently blacklist whatever didn't fit in today's budget.
            skipped += 1

    registry.save()
    _save_seen(cache_path, seen)

    return {
        "sources_seen": len(raw_sources),
        "sources_new": len(new_sources),
        "candidates_accepted": accepted,
        "candidates_rejected": rejected,
        "sources_skipped": skipped,
        "gemini_calls_used": gemini_calls_used,
    }
