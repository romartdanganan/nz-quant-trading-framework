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
