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
  [4] Launch IBKR Paper Trading Engine
  [0] Exit
"""


def search_online_strategies() -> None:
    from strategy_research import pipeline

    console.print("[cyan]Running strategy discovery pipeline (scrape -> extract -> distill)...[/cyan]")
    summary = pipeline.run()
    console.print(summary)


def backtest_and_validate() -> None:
    from quant_engine.validation import runner

    console.print("[cyan]Backtesting registry candidates (net of NZ tax + FX)...[/cyan]")
    summary = runner.run_validation()
    console.print(summary)


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
    console.print("[yellow]Not yet implemented — see execution_ibkr/ and execution_alpaca/[/yellow]")


ACTIONS = {
    "1": search_online_strategies,
    "2": backtest_and_validate,
    "3": run_ai_screener,
    "4": launch_paper_trading,
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
