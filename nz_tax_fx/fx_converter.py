"""Fetches real-time and historical USD/NZD exchange rates (via the free, keyless
Frankfurter API — ECB-sourced) and converts USD amounts into NZD. Per CLAUDE.md: realized
amounts must use the rate at the transaction date; unrealized/opening-value figures use
period-end rates — never a single blended rate across a tax year. Rates are cached to disk
per calendar date since a given date's historical rate never changes.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"
DEFAULT_CACHE_PATH = Path("data/cache/fx_rates.json")


class FXRateUnavailable(RuntimeError):
    """Raised when a USD/NZD rate can't be obtained — callers must never substitute a guess."""


class FXConverter:
    def __init__(self, cache_path: Path | str = DEFAULT_CACHE_PATH):
        self.cache_path = Path(cache_path)
        self._cache: dict[str, float] = self._load_cache()
        self._fetched_ranges: list[tuple[str, str]] = []  # in-memory only, this process

    def _load_cache(self) -> dict[str, float]:
        if not self.cache_path.exists():
            return {}
        with open(self.cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2)

    def get_rate(self, as_of: date | None = None) -> float:
        """USD -> NZD rate. as_of=None means the latest available rate. "latest" is never
        cached across process runs (only within one converter instance) since it changes.
        """
        cache_key = as_of.isoformat() if as_of else "latest"
        if cache_key in self._cache:
            return self._cache[cache_key]

        endpoint = as_of.isoformat() if as_of else "latest"
        url = f"{FRANKFURTER_BASE_URL}/{endpoint}"
        try:
            response = requests.get(url, params={"base": "USD", "symbols": "NZD"}, timeout=10)
            response.raise_for_status()
            rate = float(response.json()["rates"]["NZD"])
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            raise FXRateUnavailable(f"Could not fetch USD/NZD rate for {cache_key}: {exc}") from exc

        self._cache[cache_key] = rate
        if as_of is not None:
            self._save_cache()
        return rate

    def convert_to_nzd(self, amount_usd: float, as_of: date | None = None) -> float:
        return amount_usd * self.get_rate(as_of)

    def get_rate_series(self, start: date, end: date) -> dict[str, float]:
        """Bulk-fetches USD/NZD rates for every FX trading day in [start, end] in a single
        request (Frankfurter's range endpoint) — used to convert a whole equity curve to
        NZD without one API call per day. Keys are ISO date strings; weekends/FX holidays
        are simply absent (forex doesn't trade every calendar day) — callers should
        forward-fill against their own index. Repeated calls with a range already covered
        by a prior call in this process are served from memory.
        """
        start_str, end_str = start.isoformat(), end.isoformat()
        already_covered = any(
            cached_start <= start_str and end_str <= cached_end
            for cached_start, cached_end in self._fetched_ranges
        )

        if not already_covered:
            url = f"{FRANKFURTER_BASE_URL}/{start_str}..{end_str}"
            try:
                response = requests.get(url, params={"base": "USD", "symbols": "NZD"}, timeout=15)
                response.raise_for_status()
                rates = response.json()["rates"]
            except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
                raise FXRateUnavailable(
                    f"Could not fetch USD/NZD rate series for {start}..{end}: {exc}"
                ) from exc

            for date_str, rate_obj in rates.items():
                self._cache[date_str] = float(rate_obj["NZD"])
            self._fetched_ranges.append((start_str, end_str))
            self._save_cache()

        return {
            date_str: rate
            for date_str, rate in self._cache.items()
            if date_str != "latest" and start_str <= date_str <= end_str
        }
