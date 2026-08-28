"""Discovers a candidate universe of smaller, less-followed tickers via Yahoo Finance's
real screener queries (yfinance.screen), for feeding into the existing deterministic
fundamental_screener/watchlist pipeline (CLAUDE.md Guardrails: no LLM judgment in the
trading math). A hardcoded or memorized list of "promising small caps" would go stale
immediately and risks a hallucinated ticker; querying Yahoo's screener live avoids both.

This module only discovers candidate tickers — it does not score or rank anything itself.
quant_engine/screeners/fundamental_screener.py and watchlist.py still do all scoring.
"""
from __future__ import annotations

import logging

import yfinance as yf

from config.settings import settings
from quant_engine.screeners.fundamental_screener import ScreenerCriteria
from quant_engine.screeners.watchlist import WatchlistEntry, build_watchlist

logger = logging.getLogger(__name__)

DEFAULT_QUERIES = ["aggressive_small_caps", "small_cap_gainers", "undervalued_growth_stocks"]
DEFAULT_COUNT_PER_QUERY = 25
DEFAULT_MAX_MARKET_CAP_USD = 10_000_000_000  # excludes mega-caps already on the main watchlist


def discover_candidate_tickers(
    queries: list[str] | None = None,
    count_per_query: int = DEFAULT_COUNT_PER_QUERY,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP_USD,
) -> list[str]:
    queries = queries or settings.get("opportunity_screener.queries", DEFAULT_QUERIES)
    seen: dict[str, float] = {}
    for query in queries:
        try:
            response = yf.screen(query, count=count_per_query)
        except Exception as exc:
            logger.warning("Screener query %s failed: %s", query, exc)
            continue
        for quote in (response or {}).get("quotes", []):
            symbol = quote.get("symbol")
            market_cap = quote.get("marketCap")
            if not symbol or market_cap is None or market_cap > max_market_cap:
                continue
            seen.setdefault(symbol, market_cap)
    return list(seen.keys())


def find_opportunities(
    criteria: ScreenerCriteria | None = None,
    queries: list[str] | None = None,
    count_per_query: int = DEFAULT_COUNT_PER_QUERY,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP_USD,
) -> list[WatchlistEntry]:
    tickers = discover_candidate_tickers(queries, count_per_query, max_market_cap)
    return build_watchlist(tickers, criteria)
