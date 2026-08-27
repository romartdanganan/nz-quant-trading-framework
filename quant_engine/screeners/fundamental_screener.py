"""Factor-based fundamental screener: P/E, PEG, debt-to-equity, revenue growth, and
earnings-surprise history via yfinance. Deterministic scoring only — no LLM judgment (see
CLAUDE.md Guardrails: "never use the LLM as the trading decision-maker"). This produces a
ranked candidate list; quant_engine/screeners/watchlist.py combines it with sentiment into
the final CLI output, which is advisory-only per CLAUDE.md's Human-in-the-loop section.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yfinance as yf

from config.settings import settings


class FundamentalDataUnavailable(RuntimeError):
    """Raised when yfinance returns no usable fundamental data for a ticker."""


@dataclass(frozen=True)
class FundamentalMetrics:
    ticker: str
    price: float
    pe_ratio: float | None
    peg_ratio: float | None
    debt_to_equity: float | None
    revenue_growth: float | None
    latest_earnings_surprise_pct: float | None


@dataclass(frozen=True)
class ScreenerCriteria:
    max_pe: float = 40.0
    max_peg: float = 3.0
    max_debt_to_equity: float = 150.0
    min_revenue_growth: float = 0.0
    min_earnings_surprise_pct: float = -5.0

    @classmethod
    def from_config(cls) -> "ScreenerCriteria":
        return cls(
            max_pe=settings.get("screener.max_pe", cls.max_pe),
            max_peg=settings.get("screener.max_peg", cls.max_peg),
            max_debt_to_equity=settings.get("screener.max_debt_to_equity", cls.max_debt_to_equity),
            min_revenue_growth=settings.get("screener.min_revenue_growth", cls.min_revenue_growth),
            min_earnings_surprise_pct=settings.get(
                "screener.min_earnings_surprise_pct", cls.min_earnings_surprise_pct
            ),
        )


@dataclass(frozen=True)
class ScreenResult:
    metrics: FundamentalMetrics
    score: float
    passed: bool
    reasons_failed: list[str] = field(default_factory=list)


def fetch_fundamentals(ticker: str) -> FundamentalMetrics:
    info = yf.Ticker(ticker).info
    price = info.get("currentPrice") or info.get("regularMarketPrice") if info else None
    if not price:
        raise FundamentalDataUnavailable(f"No fundamental data returned for {ticker}")

    return FundamentalMetrics(
        ticker=ticker,
        price=float(price),
        pe_ratio=info.get("trailingPE"),
        peg_ratio=info.get("pegRatio") or info.get("trailingPegRatio"),
        debt_to_equity=info.get("debtToEquity"),
        revenue_growth=info.get("revenueGrowth"),
        latest_earnings_surprise_pct=_latest_earnings_surprise(ticker),
    )


def _latest_earnings_surprise(ticker: str) -> float | None:
    try:
        earnings = yf.Ticker(ticker).get_earnings_dates(limit=8)
    except Exception:
        return None
    if earnings is None or earnings.empty or "Surprise(%)" not in earnings.columns:
        return None

    reported = earnings.dropna(subset=["Surprise(%)"])
    if reported.empty:
        return None
    return float(reported.iloc[0]["Surprise(%)"])


def evaluate(metrics: FundamentalMetrics, criteria: ScreenerCriteria = ScreenerCriteria()) -> ScreenResult:
    reasons_failed: list[str] = []

    if metrics.pe_ratio is not None and metrics.pe_ratio > criteria.max_pe:
        reasons_failed.append(f"P/E {metrics.pe_ratio:.1f} > max {criteria.max_pe}")
    if metrics.peg_ratio is not None and metrics.peg_ratio > criteria.max_peg:
        reasons_failed.append(f"PEG {metrics.peg_ratio:.2f} > max {criteria.max_peg}")
    if metrics.debt_to_equity is not None and metrics.debt_to_equity > criteria.max_debt_to_equity:
        reasons_failed.append(f"D/E {metrics.debt_to_equity:.1f} > max {criteria.max_debt_to_equity}")
    if metrics.revenue_growth is not None and metrics.revenue_growth < criteria.min_revenue_growth:
        reasons_failed.append(
            f"revenue growth {metrics.revenue_growth:.1%} < min {criteria.min_revenue_growth:.1%}"
        )
    if (
        metrics.latest_earnings_surprise_pct is not None
        and metrics.latest_earnings_surprise_pct < criteria.min_earnings_surprise_pct
    ):
        reasons_failed.append(
            f"earnings surprise {metrics.latest_earnings_surprise_pct:.1f}% "
            f"< min {criteria.min_earnings_surprise_pct}%"
        )

    return ScreenResult(
        metrics=metrics, score=_score(metrics), passed=not reasons_failed, reasons_failed=reasons_failed
    )


def _score(metrics: FundamentalMetrics) -> float:
    """Composite 0-100 fundamental health score — deterministic, no LLM. Rewards lower
    PE/PEG/debt and higher revenue growth/earnings surprise. A missing field simply
    doesn't contribute (neither helps nor hurts) rather than penalizing incomplete data.
    """
    score = 50.0
    if metrics.pe_ratio is not None:
        score += max(-15.0, min(15.0, (25.0 - metrics.pe_ratio) * 0.5))
    if metrics.peg_ratio is not None:
        score += max(-15.0, min(15.0, (1.5 - metrics.peg_ratio) * 10.0))
    if metrics.debt_to_equity is not None:
        score += max(-10.0, min(10.0, (100.0 - metrics.debt_to_equity) * 0.05))
    if metrics.revenue_growth is not None:
        score += max(-10.0, min(20.0, metrics.revenue_growth * 100.0))
    if metrics.latest_earnings_surprise_pct is not None:
        score += max(-10.0, min(15.0, metrics.latest_earnings_surprise_pct))
    return max(0.0, min(100.0, score))


def screen(tickers: list[str], criteria: ScreenerCriteria = ScreenerCriteria()) -> list[ScreenResult]:
    results = []
    for ticker in tickers:
        try:
            metrics = fetch_fundamentals(ticker)
        except FundamentalDataUnavailable:
            continue
        results.append(evaluate(metrics, criteria))
    return sorted(results, key=lambda result: result.score, reverse=True)
