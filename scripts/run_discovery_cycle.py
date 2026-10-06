"""Non-interactive entrypoint for the daily discovery cycle — the same steps as cli/main.py
options [1] (scrape) and [8] (mine), run back-to-back against a single, non-interactive
trigger (e.g. a Windows Scheduled Task). Also runs validation afterward so anything that
clears the bar is promoted the same day, and regenerates the dashboard.

Run from the repo root: python -m scripts.run_discovery_cycle
Logs to data/logs/discovery_cycle.log (gitignored — a runtime log, not source).

Per-step errors are caught and reported in that step's own summary dict (pipeline.run(),
pattern_miner.run(), etc. already degrade gracefully per CLAUDE.md — a bad source, a
rate-limited API, a missing ticker's data must never crash the run) rather than raised —
this script exits 0 on a normal run even if an individual source/ticker failed that day.

The mining universe is deliberately broader than strategy_validation.universe alone:
opportunity_finder.discover_candidate_tickers()'s live small/mid-cap screener output is
merged in every run (2026-10-06) so a recurring cadence doesn't just rescan the same fixed
list every day — see CLAUDE.md's "Data-driven strategy generation" for why mega-caps are
the hardest place to find an edge and small/mid-caps are a genuinely different source of
candidates.
"""
from __future__ import annotations

import logging
from pathlib import Path

LOG_PATH = Path("data/logs/discovery_cycle.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def main() -> None:
    from config.settings import settings
    from dashboard.generator import generate_dashboard
    from quant_engine.screeners.opportunity_finder import discover_candidate_tickers
    from quant_engine.validation import pairs_runner, runner
    from scripts.notify import send_toast
    from strategies.library import seed_classic_strategies
    from strategy_research import pipeline
    from strategy_research.generator import pattern_miner

    logger.info("=== discovery cycle run started ===")

    seeded = seed_classic_strategies()
    logger.info("seed_classic_strategies: %s", seeded)

    scrape_summary = pipeline.run()
    logger.info("pipeline.run (scraping): %s", scrape_summary)

    base_universe = settings.get("strategy_validation.universe", [])
    try:
        fresh_tickers = discover_candidate_tickers()
    except Exception as exc:  # pragma: no cover - live screener call, must never crash the cycle
        logger.warning("discover_candidate_tickers failed, mining base universe only: %s", exc)
        fresh_tickers = []
    mining_universe = list(dict.fromkeys([*base_universe, *fresh_tickers]))
    mine_summary = pattern_miner.run(universe=mining_universe)
    logger.info("pattern_miner.run (universe size %d): %s", len(mining_universe), mine_summary)

    single_summary = runner.run_validation()
    logger.info("run_validation (single): %s", single_summary)

    pairs_summary = pairs_runner.run_pairs_validation()
    logger.info("run_pairs_validation: %s", pairs_summary)

    dashboard_path = generate_dashboard()
    logger.info("dashboard regenerated: %s", dashboard_path.resolve())

    notable_lines = []
    accepted = scrape_summary.get("candidates_accepted", 0) + mine_summary.get("candidates_accepted", 0)
    if accepted:
        notable_lines.append(f"{accepted} new candidate(s) found (scrape+mine)")
    if single_summary.get("validated"):
        notable_lines.append(f"{single_summary['validated']} single-ticker candidate(s) validated")
    if pairs_summary.get("validated"):
        notable_lines.append(f"{pairs_summary['validated']} pair(s) validated")

    if notable_lines:
        send_toast("NZ Quant Trader — discovery update", "\n".join(notable_lines))
        logger.info("Sent toast notification: %s", notable_lines)

    logger.info("=== discovery cycle run finished ===")


if __name__ == "__main__":
    main()
