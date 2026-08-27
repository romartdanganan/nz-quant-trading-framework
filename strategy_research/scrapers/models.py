"""Shared data shape returned by every scraper in this package, so pipeline.py can treat
GitHub/Reddit/RSS results uniformly regardless of source.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawSource:
    text: str
    url: str
    title: str
