from strategy_research.translator import nl_to_rules


def test_normalize_from_gemini_valid_candidate():
    candidate = {
        "name": "gap fade",
        "archetype": "mean_reversion",
        "entry_conditions": [{"indicator": "RSI", "operator": "<", "threshold": 25}],
        "exit_conditions": [{"indicator": "RSI", "operator": ">", "threshold": 75}],
        "timeframe": "5m",
        "confidence": 0.7,
    }
    spec = nl_to_rules.normalize_from_gemini(candidate, "https://example.com")

    assert spec is not None
    assert spec.archetype.value == "mean_reversion"
    assert spec.extraction_method == "gemini"


def test_normalize_from_gemini_rejects_unknown_indicator():
    candidate = {
        "name": "bad",
        "archetype": "mean_reversion",
        "entry_conditions": [{"indicator": "MOON_PHASE", "operator": "<", "threshold": 1}],
        "timeframe": "5m",
        "confidence": 0.7,
    }
    assert nl_to_rules.normalize_from_gemini(candidate, "https://example.com") is None


def test_normalize_from_gemini_rejects_unknown_archetype():
    candidate = {
        "name": "bad",
        "archetype": "astrology",
        "entry_conditions": [{"indicator": "RSI", "operator": "<", "threshold": 30}],
        "timeframe": "5m",
        "confidence": 0.7,
    }
    assert nl_to_rules.normalize_from_gemini(candidate, "https://example.com") is None


def test_normalize_from_gemini_rejects_out_of_range_threshold():
    candidate = {
        "name": "bad",
        "archetype": "mean_reversion",
        "entry_conditions": [{"indicator": "RSI", "operator": "<", "threshold": 500}],
        "timeframe": "5m",
        "confidence": 0.7,
    }
    assert nl_to_rules.normalize_from_gemini(candidate, "https://example.com") is None


def test_normalize_from_gemini_missing_fields_rejected():
    assert nl_to_rules.normalize_from_gemini({}, "https://example.com") is None


def test_normalize_from_gemini_rejects_pairs_trading_archetype():
    # StrategySpec is structurally single-ticker and can't represent pairs trading (needs
    # two tickers + a hedge ratio — see PairsSpec). A real bug found 2026-08-30: Gemini
    # returned a "pairs_trading" archetype candidate that got built as a plain
    # single-ticker spec with an arbitrary ZSCORE condition duplicated into entry/exit.
    candidate = {
        "name": "Pair Trading Cointegration Strategy",
        "archetype": "pairs_trading",
        "entry_conditions": [{"indicator": "ZSCORE", "operator": ">", "threshold": 1.0}],
        "exit_conditions": [{"indicator": "ZSCORE", "operator": ">", "threshold": 1.0}],
        "timeframe": "1d",
        "confidence": 0.8,
    }
    assert nl_to_rules.normalize_from_gemini(candidate, "https://example.com") is None


def test_normalize_from_gemini_rejects_missing_exit_conditions():
    # A real bug found 2026-08-30: falling back to entry_conditions when exit_conditions
    # was missing/empty fabricated a degenerate entry==exit spec that can never sensibly
    # hold a position (the same failure mode fixed in rule_extractor.py 2026-08-28).
    candidate = {
        "name": "Alpaca Opening Range Momentum",
        "archetype": "momentum",
        "entry_conditions": [{"indicator": "MACD", "operator": ">", "threshold": 0.0}],
        "timeframe": "1d",
        "confidence": 0.85,
    }
    assert nl_to_rules.normalize_from_gemini(candidate, "https://example.com") is None


def test_normalize_from_gemini_rejects_identical_entry_and_exit_conditions():
    candidate = {
        "name": "bad",
        "archetype": "momentum",
        "entry_conditions": [{"indicator": "MACD", "operator": ">", "threshold": 0.0}],
        "exit_conditions": [{"indicator": "MACD", "operator": ">", "threshold": 0.0}],
        "timeframe": "1d",
        "confidence": 0.85,
    }
    assert nl_to_rules.normalize_from_gemini(candidate, "https://example.com") is None
