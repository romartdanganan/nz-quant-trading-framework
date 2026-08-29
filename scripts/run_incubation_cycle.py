"""Non-interactive entrypoint for the daily incubation cycle — the same steps as
cli/main.py option [4], callable directly (e.g. from a Windows Scheduled Task) without
going through the interactive menu. Also regenerates the visual dashboard afterward so
opening reports/dashboard.html always shows today's data.

Run from the repo root: python -m scripts.run_incubation_cycle
Logs to data/logs/incubation_cycle.log (gitignored — a runtime log, not source).

Per-record errors inside each step are caught and reported in that step's own summary
dict (see execution_alpaca/paper_trading_engine.py etc.) rather than raised — this script
exits 0 on a normal run even if some individual strategy's data fetch failed that day, so
a transient data-provider hiccup doesn't get treated as a failed scheduled task.
"""
from __future__ import annotations

import logging
from pathlib import Path

LOG_PATH = Path("data/logs/incubation_cycle.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def _describe_event(event: dict) -> str:
    name = event.get("name", "?")
    kind = event["event"]
    if kind == "opened" and "pair" in event:
        return f"Opened {name}: {event['pair']} (z={event['zscore']:.2f})"
    if kind == "closed" and "pair" in event:
        return f"Closed {name}: {event['pair']} P&L ${event['pnl']:+.2f}"
    if kind == "opened":
        return f"Opened {name}: {event.get('ticker')} x{event.get('shares'):.2f} @ ${event.get('entry_price'):.2f}"
    if kind == "closed":
        return f"Closed {name}: {event.get('ticker')} P&L ${event['pnl']:+.2f}"
    if kind == "promoted":
        return f"PROMOTED to proven: {name} - {event['reason']}"
    if kind == "rejected":
        return f"Rejected: {name} - {event['reason']}"
    return f"{kind}: {name}"


def main() -> None:
    from dashboard.generator import generate_dashboard
    from execution_alpaca.pairs_paper_trading_engine import run_pairs_incubation_cycle
    from execution_alpaca.paper_trading_engine import run_incubation_cycle
    from quant_engine.validation.incubation import process_incubating_strategies, start_incubation_for_validated
    from scripts.notify import send_toast

    logger.info("=== incubation cycle run started ===")

    started = start_incubation_for_validated()
    logger.info("start_incubation_for_validated: %s", started)

    single_summary = run_incubation_cycle()
    logger.info("run_incubation_cycle: %s", single_summary)

    pairs_summary = run_pairs_incubation_cycle()
    logger.info("run_pairs_incubation_cycle: %s", pairs_summary)

    decision_summary = process_incubating_strategies()
    logger.info("process_incubating_strategies: %s", decision_summary)

    dashboard_path = generate_dashboard()
    logger.info("dashboard regenerated: %s", dashboard_path.resolve())

    notable_lines = []
    if started["started"] > 0:
        notable_lines.append(f"{started['started']} strategy(ies) started incubation")
    notable_lines += [_describe_event(e) for e in single_summary.get("events", [])]
    notable_lines += [_describe_event(e) for e in pairs_summary.get("events", [])]
    notable_lines += [_describe_event(e) for e in decision_summary.get("events", [])]

    if notable_lines:
        send_toast("NZ Quant Trader — incubation update", "\n".join(notable_lines))
        logger.info("Sent toast notification: %s", notable_lines)

    logger.info("=== incubation cycle run finished ===")


if __name__ == "__main__":
    main()
