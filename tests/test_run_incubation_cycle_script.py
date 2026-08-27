from scripts import run_incubation_cycle


def test_main_calls_every_step_and_regenerates_dashboard(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        "quant_engine.validation.incubation.start_incubation_for_validated",
        lambda: calls.append("start") or {"started": 0},
    )
    monkeypatch.setattr(
        "execution_alpaca.paper_trading_engine.run_incubation_cycle",
        lambda: calls.append("single") or {"records": 0, "processed": 0, "errored": 0},
    )
    monkeypatch.setattr(
        "execution_alpaca.pairs_paper_trading_engine.run_pairs_incubation_cycle",
        lambda: calls.append("pairs") or {"records": 0, "processed": 0, "errored": 0},
    )
    monkeypatch.setattr(
        "quant_engine.validation.incubation.process_incubating_strategies",
        lambda: calls.append("evaluate")
        or {"records": 0, "promoted": 0, "rejected": 0, "still_incubating": 0},
    )
    monkeypatch.setattr(
        "dashboard.generator.generate_dashboard",
        lambda: calls.append("dashboard") or (tmp_path / "dashboard.html"),
    )

    run_incubation_cycle.main()

    assert calls == ["start", "single", "pairs", "evaluate", "dashboard"]
