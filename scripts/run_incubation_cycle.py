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


def main() -> None:
    from dashboard.generator import generate_dashboard
    from execution_alpaca.pairs_paper_trading_engine import run_pairs_incubation_cycle
    from execution_alpaca.paper_trading_engine import run_incubation_cycle
    from quant_engine.validation.incubation import process_incubating_strategies, start_incubation_for_validated

    logger.info("=== incubation cycle run started ===")
    logger.info("start_incubation_for_validated: %s", start_incubation_for_validated())
    logger.info("run_incubation_cycle: %s", run_incubation_cycle())
    logger.info("run_pairs_incubation_cycle: %s", run_pairs_incubation_cycle())
    logger.info("process_incubating_strategies: %s", process_incubating_strategies())

    dashboard_path = generate_dashboard()
    logger.info("dashboard regenerated: %s", dashboard_path.resolve())
    logger.info("=== incubation cycle run finished ===")


if __name__ == "__main__":
    main()
