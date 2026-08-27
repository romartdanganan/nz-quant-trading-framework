"""Interactive terminal dashboard — entrypoint for the NZ Quant Trading & Research Framework.

Menu actions are wired to their owning modules but not yet implemented (see CLAUDE.md
for the phase roadmap). Run with: python -m cli.main
"""
from __future__ import annotations

from rich.console import Console

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
    console.print("[yellow]Not yet implemented — runs strategy_research/pipeline.py end-to-end[/yellow]")


def backtest_and_validate() -> None:
    console.print("[yellow]Not yet implemented — see backtester/ and quant_engine/validation/[/yellow]")


def run_ai_screener() -> None:
    console.print("[yellow]Not yet implemented — see quant_engine/screeners/[/yellow]")


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
