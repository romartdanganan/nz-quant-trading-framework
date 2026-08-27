"""Combines the fundamental screener and sentiment scorer into a ranked daily watchlist
with suggested entry/stop/target levels — the "Signal Generation" step of the Recommended
Safe Workflow in CLAUDE.md. This is the final output of Phase 5: advisory only. Per
CLAUDE.md's Human-in-the-loop section, nothing in this module places an order — a human
reviews and approves before any entry here becomes a real trade, in paper or live.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas_ta as ta
import yfinance as yf

from config.settings import settings
from quant_engine.screeners.fundamental_screener import ScreenerCriteria, screen
from quant_engine.screeners.sentiment_scorer import score_ticker

logger = logging.getLogger(__name__)

ATR_PERIOD = 14
ATR_LOOKBACK_DAYS = 60
FALLBACK_STOP_PCT = 0.02  # used only if price history/ATR can't be fetched


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    fundamental_score: float
    sentiment_score: float
    sentiment_label: str
    entry_price: float
    stop_loss: float
    target_price: float
    reasons_failed: list[str] = field(default_factory=list)


def _suggest_levels(ticker: str, price: float, atr_multiplier: float, reward_risk_ratio: float) -> tuple[float, float]:
    try:
        history = yf.Ticker(ticker).history(period=f"{ATR_LOOKBACK_DAYS}d")
        atr_value = float(ta.atr(history["High"], history["Low"], history["Close"], length=ATR_PERIOD).iloc[-1])
    except Exception as exc:
        logger.warning("Could not compute ATR for %s, using fallback stop distance: %s", ticker, exc)
        atr_value = price * FALLBACK_STOP_PCT

    stop_distance = atr_value * atr_multiplier
    stop_loss = price - stop_distance
    target_price = price + stop_distance * reward_risk_ratio
    return stop_loss, target_price


def build_watchlist(tickers: list[str], criteria: ScreenerCriteria | None = None) -> list[WatchlistEntry]:
    criteria = criteria or ScreenerCriteria.from_config()
    atr_multiplier = settings.get("risk_management.atr_multiplier", 2.0)
    reward_risk_ratio = settings.get("screener.reward_risk_ratio", 2.0)
    headline_limit = settings.get("screener.sentiment_headline_limit", 10)

    entries = []
    for result in screen(tickers, criteria):
        if not result.passed:
            continue

        sentiment = score_ticker(result.metrics.ticker, limit=headline_limit)
        stop_loss, target_price = _suggest_levels(
            result.metrics.ticker, result.metrics.price, atr_multiplier, reward_risk_ratio
        )
        entries.append(
            WatchlistEntry(
                ticker=result.metrics.ticker,
                fundamental_score=result.score,
                sentiment_score=sentiment.mean_compound_score,
                sentiment_label=sentiment.label,
                entry_price=result.metrics.price,
                stop_loss=stop_loss,
                target_price=target_price,
                reasons_failed=result.reasons_failed,
            )
        )
    return sorted(entries, key=lambda entry: entry.fundamental_score, reverse=True)
