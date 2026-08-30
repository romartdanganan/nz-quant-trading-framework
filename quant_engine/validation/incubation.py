"""Incubation forward-test decision logic (CLAUDE.md Strategy Lifecycle): a "validated"
strategy must clear a live-but-unfunded forward test — proving it holds up outside its own
backtest window — before it is "proven" and allowed real paper-trading capital. This module
is the decision logic; strategy_research/registry.py owns the storage/status transitions it
calls into.

Decay is checked on every evaluation, regardless of elapsed time: a strategy that's clearly
blowing through its drawdown/Sharpe tolerance doesn't get to wait out the full incubation
window before being rejected. Promotion, by contrast, requires both the minimum elapsed
duration AND the minimum trade count.

Known limitation: this only evaluates whatever's already in a record's incubation_log — it
does not itself run continuously over the 60+ day incubation window. Something else (a
paper-trading engine invoked on a recurring schedule, e.g. once daily) has to keep calling
record_snapshot() as real time passes; a single Claude Code session isn't a suitable place
to run a multi-week continuous process.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from config.settings import settings
from quant_engine.validation.metrics import compute_metrics
from strategy_research.registry import StrategyRegistry


@dataclass(frozen=True)
class IncubationDecision:
    action: str  # "continue" | "promote" | "reject"
    reason: str


def record_snapshot(
    record: dict, equity_value: float, as_of: date | None = None, trade: dict | None = None
) -> None:
    as_of = as_of or date.today()
    record.setdefault("incubation_log", []).append({"date": as_of.isoformat(), "equity": equity_value})
    if trade is not None:
        record.setdefault("incubation_trades", []).append(trade)


def _equity_curve_from_log(log: list[dict]) -> pd.Series:
    if not log:
        return pd.Series(dtype=float)
    index = pd.to_datetime([entry["date"] for entry in log])
    values = [entry["equity"] for entry in log]
    return pd.Series(values, index=index).sort_index()


def evaluate_incubation(record: dict) -> IncubationDecision:
    min_days = settings.get("incubation.min_days", 60)
    min_trades = settings.get("incubation.min_trades", 20)
    max_sharpe_decay_pct = settings.get("incubation.max_sharpe_decay_pct", 0.30)
    max_drawdown_overshoot_pct = settings.get("incubation.max_drawdown_overshoot_pct", 0.05)

    incubation_log = record.get("incubation_log") or []
    incubation_trades = record.get("incubation_trades") or []
    baseline_metrics = record.get("baseline_metrics") or {}

    if len(incubation_log) < 2:
        return IncubationDecision("continue", "not enough incubation data yet")

    equity_curve = _equity_curve_from_log(incubation_log)
    current_metrics = compute_metrics(equity_curve, incubation_trades)

    baseline_sharpe = baseline_metrics.get("sharpe_ratio", 0.0) or 0.0
    baseline_maxdd = baseline_metrics.get("max_drawdown_pct", 0.0) or 0.0

    # An equity curve with zero variance (no signal has fired yet, so equity has sat
    # exactly flat) makes compute_sharpe_ratio return a literal 0.0 as its "insufficient
    # data" sentinel — indistinguishable from genuine decay. Only compare against the
    # decay threshold once the curve has actually moved; a real declining/volatile curve
    # (even pre-trade, e.g. an open position's mark-to-market) still produces a nonzero
    # std and must still be caught.
    has_moved = equity_curve.pct_change().dropna().std() != 0

    if (
        has_moved
        and baseline_sharpe > 0
        and current_metrics.sharpe_ratio < baseline_sharpe * (1 - max_sharpe_decay_pct)
    ):
        return IncubationDecision(
            "reject",
            f"incubation Sharpe {current_metrics.sharpe_ratio:.2f} decayed more than "
            f"{max_sharpe_decay_pct:.0%} vs backtest Sharpe {baseline_sharpe:.2f}",
        )

    if current_metrics.max_drawdown_pct > baseline_maxdd + max_drawdown_overshoot_pct:
        return IncubationDecision(
            "reject",
            f"incubation MaxDD {current_metrics.max_drawdown_pct:.1%} exceeds backtest MaxDD "
            f"{baseline_maxdd:.1%} by more than {max_drawdown_overshoot_pct:.1%}",
        )

    start_date = datetime.fromisoformat(record["incubation_start_date"]).date()
    elapsed_days = (date.today() - start_date).days
    trade_count = len(incubation_trades)

    if elapsed_days >= min_days and trade_count >= min_trades:
        return IncubationDecision(
            "promote",
            f"cleared incubation after {elapsed_days} days and {trade_count} trades "
            f"(Sharpe {current_metrics.sharpe_ratio:.2f}, MaxDD {current_metrics.max_drawdown_pct:.1%})",
        )

    return IncubationDecision("continue", f"{elapsed_days}/{min_days} days, {trade_count}/{min_trades} trades")


def start_incubation_for_validated(registry: StrategyRegistry | None = None) -> dict:
    registry = registry or StrategyRegistry()
    validated = registry.list(status="validated")
    for record in validated:
        registry.start_incubation(record["id"])
    registry.save()
    return {"started": len(validated)}


def process_incubating_strategies(registry: StrategyRegistry | None = None) -> dict:
    """Evaluates every "incubating" record and applies promote/reject decisions. Does not
    itself add new incubation data — see module limitation note above.
    """
    registry = registry or StrategyRegistry()
    records = registry.list(status="incubating")

    promoted = rejected = still_incubating = 0
    events: list[dict] = []
    for record in records:
        decision = evaluate_incubation(record)
        if decision.action == "promote":
            equity_curve = _equity_curve_from_log(record.get("incubation_log") or [])
            metrics = compute_metrics(equity_curve, record.get("incubation_trades") or [])
            registry.promote_to_proven(record["id"], metrics.__dict__, decision.reason)
            promoted += 1
            events.append({"event": "promoted", "name": record.get("name"), "reason": decision.reason})
        elif decision.action == "reject":
            registry.reject(record["id"], decision.reason)
            rejected += 1
            events.append({"event": "rejected", "name": record.get("name"), "reason": decision.reason})
        else:
            still_incubating += 1

    registry.save()
    return {
        "records": len(records),
        "promoted": promoted,
        "rejected": rejected,
        "still_incubating": still_incubating,
        "events": events,
    }
