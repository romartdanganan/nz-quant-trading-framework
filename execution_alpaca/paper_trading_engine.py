"""One polling-cycle driver for the incubation forward-test: for every "incubating"
single-ticker strategy, fetches the latest price data, generates today's signal via the
same backtester/signals.py logic used in backtesting, and either opens, holds, or closes a
paper position — sized and stopped through risk_management/, and placed as a real Alpaca
bracket order when ALPACA_API_KEY is configured (nothing is placed otherwise; the position
is still tracked and its equity still recorded, so the whole pipeline is exercisable
without live credentials).

In production this needs to run on a recurring schedule (e.g. once daily after the US
close) for incubation to actually progress over its 60+ day window — a single Claude Code
session isn't a suitable place to run a multi-week continuous process (see
quant_engine/validation/incubation.py's own limitation note).

Each record trades whichever ticker runner.py recorded it as validated on
(record["ticker"]) — falls back to DEFAULT_TICKER only for older/manually-seeded records
that predate that field. Price data is fetched once per unique ticker needed this cycle,
not once per record.

Known limitation: long-only (StrategySpec doesn't model short-side direction yet).
Pairs-trading incubation is handled separately by
execution_alpaca/pairs_paper_trading_engine.py, since it needs a spread position, not a
single-instrument one.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas_ta as ta

from backtester.data_loader import PriceDataUnavailable, load_price_data
from backtester.signals import UnsupportedIndicatorError, generate_signals
from config.settings import get_env
from execution_alpaca.alpaca_connector import AlpacaNotConfigured, submit_bracket_order
from quant_engine.validation.incubation import record_snapshot
from risk_management.circuit_breakers import CircuitBreakerViolation
from risk_management.position_sizing import calculate_position_size
from risk_management.stop_target import Direction, calculate_stop_target
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import StrategySpec

logger = logging.getLogger(__name__)

ATR_PERIOD = 14
LOOKBACK_DAYS = 100
DEFAULT_TICKER = "SPY"
SIMULATED_STARTING_EQUITY = 100_000.0  # incubation is unfunded — sizing/tracking is on paper


def run_incubation_cycle(registry: StrategyRegistry | None = None) -> dict:
    registry = registry or StrategyRegistry()
    records = [r for r in registry.list(status="incubating") if r.get("kind", "single") == "single"]

    if not records:
        return {"records": 0, "processed": 0, "errored": 0, "events": []}

    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    price_data_cache: dict[str, object] = {}

    processed = errored = 0
    events: list[dict] = []
    for record in records:
        ticker = record.get("ticker", DEFAULT_TICKER)
        if ticker not in price_data_cache:
            try:
                price_data_cache[ticker] = load_price_data(ticker, start, end)
            except PriceDataUnavailable as exc:
                logger.warning("Could not load price data for %s: %s", ticker, exc)
                price_data_cache[ticker] = None

        price_data = price_data_cache[ticker]
        if price_data is None:
            errored += 1
            continue

        try:
            event = _process_one_cycle(record, price_data)
            if event is not None:
                events.append({"name": record.get("name"), **event})
            processed += 1
        except (UnsupportedIndicatorError, ValueError, KeyError) as exc:
            logger.warning("Skipping %r this cycle: %s", record.get("name"), exc)
            errored += 1

    registry.save()
    return {"records": len(records), "processed": processed, "errored": errored, "events": events}


def _process_one_cycle(record: dict, price_data) -> dict | None:
    spec = StrategySpec.from_dict(record)
    signals = generate_signals(spec, price_data)
    latest_signal = signals.iloc[-1]
    close_price = float(price_data["close"].iloc[-1])

    atr_series = ta.atr(price_data["high"], price_data["low"], price_data["close"], length=ATR_PERIOD)
    atr = float(atr_series.iloc[-1])

    position = record.get("incubation_position")
    starting_equity = record.setdefault("incubation_starting_equity", SIMULATED_STARTING_EQUITY)
    realized_pnl = record.get("incubation_realized_pnl", 0.0)
    closed_trade = None
    event = None

    if position is None and bool(latest_signal["entry_signal"]):
        position = _open_position(record, close_price, atr)
        if position is not None:
            event = {
                "event": "opened",
                "ticker": record.get("ticker"),
                "shares": position["shares"],
                "entry_price": position["entry_price"],
                "stop_loss": position["stop_loss"],
                "target_price": position["target_price"],
            }
    elif position is not None:
        exit_triggered = bool(latest_signal["exit_signal"])
        stop_hit = close_price <= position["stop_loss"]
        target_hit = close_price >= position["target_price"]
        if exit_triggered or stop_hit or target_hit:
            trade_pnl = position["shares"] * (close_price - position["entry_price"])
            realized_pnl += trade_pnl
            closed_trade = {"pnl": trade_pnl, "pnl_comm": trade_pnl}
            event = {"event": "closed", "ticker": record.get("ticker"), "pnl": trade_pnl}
            position = None

    equity = starting_equity + realized_pnl
    if position is not None:
        equity += position["shares"] * (close_price - position["entry_price"])

    record["incubation_position"] = position
    record["incubation_realized_pnl"] = realized_pnl
    record_snapshot(record, equity_value=equity, as_of=date.today(), trade=closed_trade)
    return event


def _open_position(record: dict, close_price: float, atr: float) -> dict | None:
    stop_target = calculate_stop_target(close_price, atr, direction=Direction.LONG)
    equity = record.get("incubation_starting_equity", SIMULATED_STARTING_EQUITY) + record.get(
        "incubation_realized_pnl", 0.0
    )
    sizing = calculate_position_size(equity=equity, price=close_price, atr=atr, trades=None, method="atr")

    if sizing.shares <= 0:
        return None

    ticker = record.get("ticker", "SPY")
    if get_env("ALPACA_API_KEY"):
        try:
            submit_bracket_order(
                ticker=ticker,
                shares=sizing.shares,
                entry_price_estimate=close_price,
                stop_loss=stop_target.stop_loss,
                take_profit=stop_target.target_price,
            )
        except (AlpacaNotConfigured, CircuitBreakerViolation) as exc:
            logger.warning("Order blocked this cycle for %s: %s", ticker, exc)
            return None

    return {
        "shares": sizing.shares,
        "entry_price": close_price,
        "stop_loss": stop_target.stop_loss,
        "target_price": stop_target.target_price,
    }
