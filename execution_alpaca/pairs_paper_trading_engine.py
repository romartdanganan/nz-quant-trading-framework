"""Pairs-trading counterpart to paper_trading_engine.py's one-polling-cycle incubation
driver: for every "incubating" pairs candidate, recomputes the hedge ratio/spread/z-score
from the latest price data (same math as backtester/pairs_engine.py) and opens, holds, or
closes a spread position, tracked statefully on the registry record between cycles —
mirrors execution_alpaca/paper_trading_engine.py's design exactly, one indicator set
swapped for another.

Stays shadow-only (tracked P&L, no broker order placed): a pairs position needs two linked
legs sized by the hedge ratio (long ticker_a, short ticker_b), which
execution_alpaca/alpaca_connector.py's submit_bracket_order() doesn't support — it places
one instrument per call. Real two-leg execution is future work, not hidden here.

Same scheduling caveat as paper_trading_engine.py: this is one cycle, not a continuous
process — something needs to invoke it on a recurring schedule for incubation to progress.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from backtester.data_loader import PriceDataUnavailable, load_price_data
from quant_engine.validation.incubation import record_snapshot
from strategies.pairs_trading.strategy import (
    PairsSpec,
    align_price_series,
    compute_hedge_ratio,
    compute_spread,
    compute_zscore,
)
from strategy_research.registry import StrategyRegistry

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 100
SIMULATED_STARTING_EQUITY = 100_000.0  # incubation is unfunded — sizing/tracking is on paper


def run_pairs_incubation_cycle(registry: StrategyRegistry | None = None) -> dict:
    registry = registry or StrategyRegistry()
    records = [r for r in registry.list(status="incubating") if r.get("kind") == "pairs"]

    if not records:
        return {"records": 0, "processed": 0, "errored": 0, "events": []}

    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)

    processed = errored = 0
    events: list[dict] = []
    for record in records:
        try:
            spec = PairsSpec.from_dict(record)
            price_a = load_price_data(spec.ticker_a, start, end)["close"]
            price_b = load_price_data(spec.ticker_b, start, end)["close"]
            event = _process_one_cycle(record, spec, price_a, price_b)
            if event is not None:
                events.append({"name": record.get("name"), **event})
            processed += 1
        except (PriceDataUnavailable, ValueError, KeyError) as exc:
            logger.warning("Skipping pairs %r this cycle: %s", record.get("name"), exc)
            errored += 1

    registry.save()
    return {"records": len(records), "processed": processed, "errored": errored, "events": events}


def _process_one_cycle(record: dict, spec: PairsSpec, price_a: pd.Series, price_b: pd.Series) -> dict | None:
    price_a, price_b = align_price_series(price_a, price_b)
    hedge_ratio = compute_hedge_ratio(price_a, price_b)
    spread = compute_spread(price_a, price_b, hedge_ratio)
    zscore = compute_zscore(spread, spec.lookback_period)

    latest_z = float(zscore.iloc[-1])
    latest_spread = float(spread.iloc[-1])

    position = record.get("incubation_position")
    starting_equity = record.setdefault("incubation_starting_equity", SIMULATED_STARTING_EQUITY)
    realized_pnl = record.get("incubation_realized_pnl", 0.0)
    closed_trade = None
    event = None

    if pd.notna(latest_z):
        if position is None:
            if latest_z <= -spec.entry_zscore:
                position = {"direction": 1, "entry_spread": latest_spread, "hedge_ratio": hedge_ratio}
            elif latest_z >= spec.entry_zscore:
                position = {"direction": -1, "entry_spread": latest_spread, "hedge_ratio": hedge_ratio}
            if position is not None:
                event = {
                    "event": "opened",
                    "pair": f"{spec.ticker_a}/{spec.ticker_b}",
                    "direction": position["direction"],
                    "zscore": latest_z,
                }
        elif abs(latest_z) <= spec.exit_zscore:
            trade_pnl = position["direction"] * (latest_spread - position["entry_spread"])
            realized_pnl += trade_pnl
            closed_trade = {"pnl": trade_pnl, "pnl_comm": trade_pnl}
            event = {"event": "closed", "pair": f"{spec.ticker_a}/{spec.ticker_b}", "pnl": trade_pnl}
            position = None

    equity = starting_equity + realized_pnl
    if position is not None:
        equity += position["direction"] * (latest_spread - position["entry_spread"])

    record["incubation_position"] = position
    record["incubation_realized_pnl"] = realized_pnl
    record_snapshot(record, equity_value=equity, as_of=date.today(), trade=closed_trade)
    return event
