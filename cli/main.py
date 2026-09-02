"""Interactive terminal dashboard — entrypoint for the NZ Quant Trading & Research Framework.

Menu actions are wired to their owning modules but not yet implemented (see CLAUDE.md
for the phase roadmap). Run with: python -m cli.main
"""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

console = Console()

MENU = """
[bold cyan]NZ Quant Trading & Research Framework[/bold cyan]
  [1] Search Online Strategies
  [2] Backtest & Validate (with FIF Tax)
  [3] Run AI Screener
  [4] Run Incubation Cycle (paper trading forward-test)
  [5] Research Briefing (news, earnings, fundamentals — for manual decisions)
  [6] Generate Dashboard (visual status of all strategies)
  [7] Discover Small/Mid-Cap Opportunities (real screener, not just mega-caps)
  [8] Mine Strategies from Market Data (data-driven discovery, no scraping)
  [0] Exit
"""


def search_online_strategies() -> None:
    from strategy_research import pipeline
    from strategies.library import seed_classic_strategies

    console.print("[cyan]Seeding classic reference strategies (mean reversion, momentum, breakout, pairs)...[/cyan]")
    console.print(seed_classic_strategies())

    console.print("[cyan]Running strategy discovery pipeline (scrape -> extract -> distill)...[/cyan]")
    summary = pipeline.run()
    console.print(summary)


def backtest_and_validate() -> None:
    from quant_engine.validation import pairs_runner, runner

    console.print("[cyan]Backtesting single-ticker candidates (net of NZ tax + FX)...[/cyan]")
    console.print(runner.run_validation())

    console.print("[cyan]Backtesting pairs-trading candidates (cointegration + NZ tax/FX)...[/cyan]")
    console.print(pairs_runner.run_pairs_validation())


def run_ai_screener() -> None:
    from config.settings import settings
    from quant_engine.screeners.watchlist import build_watchlist

    tickers = settings.get("watchlists.swing_trading", [])
    console.print(f"[cyan]Screening {len(tickers)} tickers (fundamentals + sentiment)...[/cyan]")
    entries = build_watchlist(tickers)

    table = Table(title="Watchlist — for review only, not auto-traded")
    for column in ["Ticker", "Fund. Score", "Sentiment", "Entry", "Stop", "Target"]:
        table.add_column(column)
    for entry in entries:
        table.add_row(
            entry.ticker,
            f"{entry.fundamental_score:.0f}",
            f"{entry.sentiment_label} ({entry.sentiment_score:+.2f})",
            f"{entry.entry_price:.2f}",
            f"{entry.stop_loss:.2f}",
            f"{entry.target_price:.2f}",
        )
    console.print(table)
    console.print(
        "[yellow]Advisory only — review each idea and verify no breaking news before "
        "approving any trade manually.[/yellow]"
    )


def launch_paper_trading() -> None:
    from execution_alpaca.pairs_paper_trading_engine import run_pairs_incubation_cycle
    from execution_alpaca.paper_trading_engine import run_incubation_cycle
    from quant_engine.validation.incubation import process_incubating_strategies, start_incubation_for_validated

    console.print("[cyan]Promoting any newly-validated strategies into incubation...[/cyan]")
    console.print(start_incubation_for_validated())

    console.print("[cyan]Running one single-ticker incubation polling cycle (paper, not live)...[/cyan]")
    console.print(run_incubation_cycle())

    console.print("[cyan]Running one pairs-trading incubation polling cycle (shadow only — see CLAUDE.md)...[/cyan]")
    console.print(run_pairs_incubation_cycle())

    console.print("[cyan]Evaluating incubation progress (promote/reject)...[/cyan]")
    console.print(process_incubating_strategies())

    console.print(
        "[yellow]Note: incubation needs this option run on a recurring schedule (e.g. daily) "
        "to actually progress over its full window — see CLAUDE.md.[/yellow]"
    )


def run_research_briefing() -> None:
    from config.settings import settings
    from quant_engine.screeners.research_briefing import scan_watchlist

    tickers = settings.get("watchlists.swing_trading", [])
    console.print(f"[cyan]Building research briefings for {len(tickers)} tickers (fundamentals, sentiment, earnings, news)...[/cyan]")
    briefings = scan_watchlist(tickers)

    table = Table(title="Research Briefing — real data only, no recommendation")
    for column in ["Ticker", "Price (NZD)", "Fund. Score", "Sentiment", "Last Earnings", "Next Earnings"]:
        table.add_column(column)
    for briefing in briefings:
        fund = briefing.fundamentals
        last = briefing.last_earnings
        if last is None:
            last_earnings_cell = "no reported earnings found"
        elif last.surprise_pct is not None:
            last_earnings_cell = f"{last.earnings_date} ({last.days_since}d ago), surprise {last.surprise_pct:+.1f}%"
        else:
            last_earnings_cell = f"{last.earnings_date} ({last.days_since}d ago)"
        table.add_row(
            briefing.ticker,
            f"${briefing.price_nzd:,.2f}" if briefing.price_nzd is not None else "n/a",
            f"P/E {fund.pe_ratio:.1f}" if fund and fund.pe_ratio is not None else "n/a",
            f"{briefing.sentiment_score:+.2f}",
            last_earnings_cell,
            f"{briefing.upcoming_earnings.earnings_date} ({briefing.upcoming_earnings.days_until}d)"
            if briefing.upcoming_earnings
            else "none within window",
        )
    console.print(table)

    for briefing in briefings:
        tagged = [h for h in briefing.headlines if h.tags]
        if not tagged:
            continue
        console.print(f"\n[bold]{briefing.ticker}[/bold] — headlines worth a second look:")
        for headline in tagged:
            console.print(f"  [{','.join(headline.tags)}] {headline.title}")

    console.print(
        "\n[yellow]This is real fundamentals/sentiment/earnings/news data, not a "
        "recommendation — read the actual headlines above and decide for yourself before "
        "any manual buy.[/yellow]"
    )


def discover_opportunities() -> None:
    from quant_engine.screeners.opportunity_finder import discover_candidate_tickers, find_opportunities

    console.print("[cyan]Pulling small/mid-cap candidates from Yahoo Finance's real screener queries...[/cyan]")
    tickers = discover_candidate_tickers()
    console.print(f"[cyan]{len(tickers)} candidates found, scoring on fundamentals + sentiment...[/cyan]")
    entries = find_opportunities()

    table = Table(title="Small/Mid-Cap Opportunities — for review only, not auto-traded")
    for column in ["Ticker", "Fund. Score", "Sentiment", "Entry", "Stop", "Target"]:
        table.add_column(column)
    for entry in entries:
        table.add_row(
            entry.ticker,
            f"{entry.fundamental_score:.0f}",
            f"{entry.sentiment_label} ({entry.sentiment_score:+.2f})",
            f"{entry.entry_price:.2f}",
            f"{entry.stop_loss:.2f}",
            f"{entry.target_price:.2f}",
        )
    console.print(table)
    console.print(
        "[yellow]Ranked purely by the documented fundamental-score formula (P/E, PEG, D/E, "
        "revenue growth, earnings surprise) + sentiment — not a recommendation. These are "
        "smaller, less-covered companies: verify the actual business and read recent "
        "filings/news yourself before considering any of them.[/yellow]"
    )


def mine_strategies_from_market_data() -> None:
    from strategy_research.generator import pattern_miner

    console.print(
        "[cyan]Mining historical price data for statistically significant indicator/"
        "forward-return relationships (no scraping, no LLM) ...[/cyan]"
    )
    summary = pattern_miner.run()
    console.print(summary)
    console.print(
        "[yellow]Mined candidates still have to clear the same backtest/validation/"
        "incubation gate as everything else — this only proposes hypotheses.[/yellow]"
    )


def generate_dashboard() -> None:
    from dashboard.generator import generate_dashboard as build_dashboard

    output_path = build_dashboard()
    console.print(f"[cyan]Dashboard written to {output_path.resolve()}[/cyan]")
    console.print("[yellow]Open that file in a browser to view it — regenerate anytime by running this option again.[/yellow]")


ACTIONS = {
    "1": search_online_strategies,
    "2": backtest_and_validate,
    "3": run_ai_screener,
    "4": launch_paper_trading,
    "5": run_research_briefing,
    "6": generate_dashboard,
    "7": discover_opportunities,
    "8": mine_strategies_from_market_data,
}


def main() -> None:
    while True:
        console.print(MENU)
        choice = console.input("[bold]Select an option: [/bold]").strip()
        if choice == "0":
            console.print("Goodbye.")
            break
        action = ACTIONS.get(choice)
        if action is None:
            console.print("[red]Invalid option.[/red]")
            continue
        action()


if __name__ == "__main__":
    main()
