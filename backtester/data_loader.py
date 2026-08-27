"""Loads and caches historical OHLCV data via yfinance for backtesting. Cached to
data/historical/ as CSV — gitignored, since market data is a runtime artifact, not source
(see CLAUDE.md Guardrails: standardized market-data APIs only, never scraped).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DEFAULT_HISTORICAL_DIR = Path("data/historical")
REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


class PriceDataUnavailable(RuntimeError):
    """Raised when historical price data can't be obtained — callers must not substitute
    synthetic/guessed data for a real backtest.
    """


def _cache_path(ticker: str, start: date, end: date, interval: str, historical_dir: Path) -> Path:
    return historical_dir / f"{ticker}_{interval}_{start.isoformat()}_{end.isoformat()}.csv"


def load_price_data(
    ticker: str,
    start: date,
    end: date,
    interval: str = "1d",
    historical_dir: Path | str = DEFAULT_HISTORICAL_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Returns a DataFrame indexed by date with lowercase columns: open, high, low, close, volume."""
    historical_dir = Path(historical_dir)
    cache_file = _cache_path(ticker, start, end, interval, historical_dir)

    if cache_file.exists() and not force_refresh:
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    try:
        raw = yf.download(
            ticker, start=start, end=end, interval=interval, auto_adjust=True, progress=False
        )
    except Exception as exc:
        raise PriceDataUnavailable(f"Failed to download {ticker} {start}..{end}: {exc}") from exc

    if raw is None or raw.empty:
        raise PriceDataUnavailable(f"No price data returned for {ticker} {start}..{end}")

    df = _normalize_columns(raw)

    historical_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_file)
    return df


def _normalize_columns(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    df.index.name = "date"
    return df[REQUIRED_COLUMNS]
