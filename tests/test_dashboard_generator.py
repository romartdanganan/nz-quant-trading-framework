import json

from dashboard.generator import build_dashboard_data, generate_dashboard
from strategy_research.registry import StrategyRegistry
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def make_spec(name="test", url="https://example.com/x") -> StrategySpec:
    return StrategySpec(
        name=name,
        archetype=Archetype.MOMENTUM,
        entry_conditions=[Condition(Indicator.MACD, Operator.CROSSES_ABOVE, 0.0)],
        exit_conditions=[Condition(Indicator.MACD, Operator.CROSSES_BELOW, 0.0)],
        timeframe="1d",
        source_url=url,
        extraction_method="rule",
        confidence=0.9,
    )


def test_build_dashboard_data_counts_all_statuses(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    a = registry.add_candidate(make_spec("a", "https://example.com/a"))
    b = registry.add_candidate(make_spec("b", "https://example.com/b"))
    registry.promote_to_validated(b["id"], {"sharpe_ratio": 2.0, "max_drawdown_pct": 0.05, "profit_factor": 2.0}, "ok")

    data = build_dashboard_data(registry)

    assert data["status_counts"]["candidate"] == 1
    assert data["status_counts"]["validated"] == 1
    assert data["status_counts"]["rejected"] == 0
    names = {s["name"] for s in data["strategies"]}
    assert names == {"a", "b"}


def test_build_dashboard_data_extracts_metrics_and_ticker(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("a"))
    record["ticker"] = "AAPL"
    registry.promote_to_validated(record["id"], {"sharpe_ratio": 1.8, "max_drawdown_pct": 0.1, "profit_factor": 1.5}, "ok")

    data = build_dashboard_data(registry)
    strategy = data["strategies"][0]

    assert strategy["ticker"] == "AAPL"
    assert strategy["sharpe"] == 1.8
    assert strategy["last_reason"] == "ok"


def test_build_dashboard_data_formats_pairs_ticker(tmp_path):
    from strategies.pairs_trading.strategy import build_pairs_spec

    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(build_pairs_spec("KO", "PEP"))

    data = build_dashboard_data(registry)

    assert data["strategies"][0]["ticker"] == "KO/PEP"


def test_generate_dashboard_writes_valid_html_and_escapes_reasons(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    record = registry.add_candidate(make_spec("dangerous"))
    # this exact reason text contains "<=" — a real registry reason string that would
    # break raw HTML injection if not escaped
    registry.reject(record["id"], "Sharpe 0.05 <= required 1.5")

    output_path = generate_dashboard(registry=registry, output_path=tmp_path / "dashboard.html")

    html_content = output_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_content.lower()
    assert "&lt;=" in html_content  # escaped, not raw "<="
    assert "<= required" not in html_content  # the raw unescaped form must not appear
    assert "dangerous" in html_content


def test_generate_dashboard_embeds_valid_json_snapshot(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.add_candidate(make_spec("a"))

    output_path = generate_dashboard(registry=registry, output_path=tmp_path / "dashboard.html")
    html_content = output_path.read_text(encoding="utf-8")

    start = html_content.index("<pre>") + len("<pre>")
    end = html_content.index("</pre>")
    raw_json = html_content[start:end]
    import html as html_module

    parsed = json.loads(html_module.unescape(raw_json))
    assert parsed["strategies"][0]["name"] == "a"


def test_generate_dashboard_handles_empty_registry(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    output_path = generate_dashboard(registry=registry, output_path=tmp_path / "dashboard.html")

    html_content = output_path.read_text(encoding="utf-8")
    assert "No strategies have completed a backtest yet." in html_content
