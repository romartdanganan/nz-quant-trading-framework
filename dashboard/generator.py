"""Generates a self-contained local HTML dashboard from the strategy registry: pipeline
status breakdown, Sharpe/MaxDD/Profit Factor per strategy, and equity curves for anything
with incubation history. Regenerate anytime via cli/main.py option [6] — it always reflects
whatever is currently in data/strategy_registry.json.

This is a local file opened directly in a browser, not a claude.ai Artifact — no CSP
restrictions apply here, but colors are drawn from the same validated reference palette
used for Artifacts (see the `dataviz` skill's references/palette.md) for consistency and
accessibility. Charts are rendered as plain inline SVG at generation time (no JS charting
library) so the file is fully self-contained and works offline.
"""
from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from config.settings import settings
from strategy_research.registry import STATUSES, StrategyRegistry

DEFAULT_OUTPUT_PATH = Path("reports/dashboard.html")

# Ordinal ramp (pipeline progress) for in-flight stages, status colors for the two
# terminal outcomes — see dataviz skill references/palette.md.
STATUS_COLOR = {
    "candidate": "#86b6ef",
    "validated": "#3987e5",
    "incubating": "#1c5cab",
    "proven": "#0ca30c",
    "rejected": "#d03b3b",
}
STATUS_COLOR_DARK = {
    "candidate": "#5598e7",
    "validated": "#3987e5",
    "incubating": "#184f95",
    "proven": "#0ca30c",
    "rejected": "#e66767",
}

CHART_WIDTH = 640
BAR_HEIGHT = 28
BAR_GAP = 12


def _ticker_label(record: dict) -> str:
    if record.get("ticker"):
        return record["ticker"]
    if record.get("ticker_a") and record.get("ticker_b"):
        return f"{record['ticker_a']}/{record['ticker_b']}"
    return "—"


def build_dashboard_data(registry: StrategyRegistry) -> dict:
    records = registry.list()
    status_counts = Counter(r.get("status", "unknown") for r in records)

    strategies = []
    for record in records:
        metrics = record.get("metrics") or {}
        history = record.get("history") or []
        strategies.append(
            {
                "id": record.get("id"),
                "name": record.get("name", "unnamed"),
                "kind": record.get("kind", "single"),
                "status": record.get("status", "unknown"),
                "ticker": _ticker_label(record),
                "sharpe": metrics.get("sharpe_ratio"),
                "max_drawdown": metrics.get("max_drawdown_pct"),
                "profit_factor": metrics.get("profit_factor"),
                "net_return_nzd": metrics.get("net_return_nzd"),
                "last_reason": history[-1].get("reason", "") if history else "",
                "incubation_log": record.get("incubation_log") or [],
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_counts": {status: status_counts.get(status, 0) for status in STATUSES},
        "strategies": strategies,
    }


def _status_bar_chart_svg(status_counts: dict) -> str:
    max_count = max(status_counts.values(), default=0) or 1
    rows = []
    y = 10
    for status in STATUSES:
        count = status_counts.get(status, 0)
        bar_width = (count / max_count) * (CHART_WIDTH - 180)
        color = STATUS_COLOR.get(status, "#898781")
        rows.append(
            f'<g><text x="0" y="{y + BAR_HEIGHT / 2 + 4:.1f}" class="chart-label">{html.escape(status)}</text>'
            f'<rect x="140" y="{y}" width="{max(bar_width, 1):.1f}" height="{BAR_HEIGHT}" rx="4" '
            f'fill="{color}"/>'
            f'<text x="{140 + bar_width + 8:.1f}" y="{y + BAR_HEIGHT / 2 + 4:.1f}" class="chart-value">{count}</text></g>'
        )
        y += BAR_HEIGHT + BAR_GAP
    return f'<svg viewBox="0 0 {CHART_WIDTH} {y}" class="chart-svg" role="img" aria-label="Strategy count by pipeline status">{"".join(rows)}</svg>'


def _sharpe_bar_chart_svg(strategies: list[dict], threshold: float) -> str:
    with_sharpe = [s for s in strategies if s.get("sharpe") is not None]
    if not with_sharpe:
        return '<p class="chart-empty">No strategies have completed a backtest yet.</p>'

    with_sharpe = sorted(with_sharpe, key=lambda s: s["sharpe"], reverse=True)
    values = [s["sharpe"] for s in with_sharpe]
    max_value = max(threshold, max(values)) * 1.15
    min_value = min(0.0, min(values))
    span = (max_value - min_value) or 1.0

    chart_left = 190
    chart_width = CHART_WIDTH - chart_left - 20

    def x_for(value: float) -> float:
        return chart_left + ((value - min_value) / span) * chart_width

    zero_x = x_for(0.0)
    threshold_x = x_for(threshold)

    rows = []
    y = 10
    for strategy in with_sharpe:
        value = strategy["sharpe"]
        value_x = x_for(value)
        bar_x = min(zero_x, value_x)
        bar_width = max(abs(value_x - zero_x), 1.0)
        color = STATUS_COLOR["proven"] if value >= threshold else STATUS_COLOR["rejected"]
        label = html.escape(strategy["name"][:24])
        text_anchor = "start" if value >= 0 else "end"
        text_x = value_x + (6 if value >= 0 else -6)
        rows.append(
            f'<g><text x="0" y="{y + BAR_HEIGHT / 2 + 4:.1f}" class="chart-label">{label}</text>'
            f'<rect x="{bar_x:.1f}" y="{y}" width="{bar_width:.1f}" height="{BAR_HEIGHT}" rx="4" fill="{color}"/>'
            f'<text x="{text_x:.1f}" y="{y + BAR_HEIGHT / 2 + 4:.1f}" class="chart-value" '
            f'text-anchor="{text_anchor}">{value:.2f}</text></g>'
        )
        y += BAR_HEIGHT + BAR_GAP

    rows.append(f'<line x1="{threshold_x:.1f}" y1="0" x2="{threshold_x:.1f}" y2="{y}" class="threshold-line"/>')
    rows.append(
        f'<text x="{threshold_x:.1f}" y="-6" class="chart-value" text-anchor="middle">'
        f"required Sharpe: {threshold}</text>"
    )
    return (
        f'<svg viewBox="0 -20 {CHART_WIDTH} {y + 20}" class="chart-svg" role="img" '
        f'aria-label="Sharpe ratio by strategy, colored by pass/fail against the required threshold">'
        f'{"".join(rows)}</svg>'
    )


def _equity_curve_svg(incubation_log: list[dict]) -> str:
    if len(incubation_log) < 2:
        return '<p class="chart-empty">Not enough incubation data yet.</p>'

    values = [entry["equity"] for entry in incubation_log]
    min_value, max_value = min(values), max(values)
    span = (max_value - min_value) or 1.0
    width, height, padding = 560, 160, 20
    n = len(values)

    points = []
    for i, value in enumerate(values):
        x = padding + (i / (n - 1)) * (width - 2 * padding)
        y = height - padding - ((value - min_value) / span) * (height - 2 * padding)
        points.append(f"{x:.1f},{y:.1f}")

    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="Incubation equity curve">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#2a78d6" stroke-width="2"/></svg>'
    )


def _render_table_rows(strategies: list[dict]) -> str:
    order = {status: i for i, status in enumerate(STATUSES)}
    rows_data = sorted(strategies, key=lambda s: order.get(s["status"], 99))

    rows = []
    for s in rows_data:
        color = STATUS_COLOR.get(s["status"], "#898781")
        sharpe = f'{s["sharpe"]:.2f}' if s["sharpe"] is not None else "—"
        maxdd = f'{s["max_drawdown"]:.1%}' if s["max_drawdown"] is not None else "—"
        pf = f'{s["profit_factor"]:.2f}' if s["profit_factor"] is not None else "—"
        net_return = f'${s["net_return_nzd"]:,.0f}' if s.get("net_return_nzd") is not None else "—"
        rows.append(
            "<tr>"
            f'<td>{html.escape(s["name"])}</td>'
            f'<td>{html.escape(s["kind"])}</td>'
            f'<td>{html.escape(s["ticker"])}</td>'
            f'<td><span class="status-badge" style="background:{color}">{html.escape(s["status"])}</span></td>'
            f"<td>{sharpe}</td><td>{maxdd}</td><td>{pf}</td><td>{net_return}</td>"
            f'<td class="reason">{html.escape(s["last_reason"])}</td>'
            "</tr>"
        )
    return "".join(rows)


def _render_equity_sections(strategies: list[dict]) -> str:
    with_log = [s for s in strategies if len(s.get("incubation_log", [])) >= 2]
    if not with_log:
        return '<p class="chart-empty">No strategy has enough incubation history yet to chart.</p>'
    sections = []
    for s in with_log:
        sections.append(
            f'<div class="equity-card"><h3>{html.escape(s["name"])}</h3>'
            f'{_equity_curve_svg(s["incubation_log"])}</div>'
        )
    return f'<div class="equity-grid">{"".join(sections)}</div>'


def _render_html(data: dict, sharpe_threshold: float) -> str:
    status_counts = data["status_counts"]
    strategies = data["strategies"]
    total = sum(status_counts.values())
    tiles = "".join(
        f'<div class="stat-tile"><div class="stat-value" style="color:{STATUS_COLOR[status]}">'
        f'{status_counts[status]}</div><div class="stat-label">{html.escape(status)}</div></div>'
        for status in STATUSES
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NZ Quant Trading Framework — Strategy Dashboard</title>
<style>
  :root {{
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7; --text-primary: #0b0b0b;
    --text-secondary: #52514e; --muted: #898781; --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff;
      --text-secondary: #c3c2b7; --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px; background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 32px 0 12px; color: var(--text-secondary); }}
  h3 {{ font-size: 13px; margin: 0 0 8px; color: var(--text-secondary); }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 24px; }}
  .card {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 20px; margin-bottom: 24px;
  }}
  .stat-tiles {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat-tile {{ flex: 1; min-width: 100px; text-align: center; }}
  .stat-value {{ font-size: 32px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .stat-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .chart-svg {{ width: 100%; height: auto; overflow: visible; }}
  .chart-label {{ font-size: 12px; fill: var(--text-secondary); }}
  .chart-value {{ font-size: 12px; fill: var(--text-primary); font-variant-numeric: tabular-nums; }}
  .chart-empty {{ color: var(--muted); font-size: 13px; }}
  .threshold-line {{ stroke: var(--muted); stroke-width: 1; stroke-dasharray: 4 3; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--grid); }}
  th {{ color: var(--muted); font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: 0.03em; }}
  td.reason {{ color: var(--text-secondary); max-width: 320px; }}
  .status-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px; color: #fff;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
  }}
  .equity-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
  .equity-card {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }}
  details summary {{ cursor: pointer; color: var(--text-secondary); font-size: 12px; margin-top: 24px; }}
  pre {{ overflow-x: auto; font-size: 11px; background: var(--surface-1); padding: 12px; border-radius: 6px; }}
</style>
</head>
<body>
  <h1>NZ Quant Trading Framework — Strategy Dashboard</h1>
  <div class="meta">Generated {html.escape(data["generated_at"])} · {total} strategies tracked · advisory data only, not a recommendation</div>

  <div class="card">
    <div class="stat-tiles">{tiles}</div>
  </div>

  <h2>Pipeline status</h2>
  <div class="card">{_status_bar_chart_svg(status_counts)}</div>

  <h2>Sharpe ratio by strategy</h2>
  <div class="card">{_sharpe_bar_chart_svg(strategies, sharpe_threshold)}</div>

  <h2>Incubation equity curves</h2>
  <div class="card">{_render_equity_sections(strategies)}</div>

  <h2>All strategies</h2>
  <div class="card">
    <table>
      <thead><tr><th>Name</th><th>Kind</th><th>Ticker</th><th>Status</th><th>Sharpe</th><th>MaxDD</th><th>Profit Factor</th><th>Net Return (NZD)</th><th>Last outcome</th></tr></thead>
      <tbody>{_render_table_rows(strategies)}</tbody>
    </table>
  </div>

  <details>
    <summary>Raw registry data (JSON)</summary>
    <pre>{html.escape(json.dumps(data, indent=2))}</pre>
  </details>
</body>
</html>
"""


def generate_dashboard(
    registry: StrategyRegistry | None = None, output_path: Path | str = DEFAULT_OUTPUT_PATH
) -> Path:
    registry = registry or StrategyRegistry()
    data = build_dashboard_data(registry)
    sharpe_threshold = settings.get("validation_thresholds.min_sharpe_ratio", 1.5)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_html(data, sharpe_threshold), encoding="utf-8")
    return output_path
