from strategy_research.strategy_spec import Archetype, Indicator, Operator
from strategy_research.translator.rule_extractor import extract


def test_extracts_mean_reversion_rsi_with_entry_and_exit():
    text = (
        "This mean reversion strategy buys when RSI is below 30 (oversold) and sells "
        "when RSI is above 70, confirmed with bollinger bands."
    )
    result = extract(text, "https://example.com/a")

    assert result.spec is not None
    assert result.spec.archetype == Archetype.MEAN_REVERSION
    entry = result.spec.entry_conditions[0]
    exit_ = result.spec.exit_conditions[0]
    assert entry.indicator == Indicator.RSI and entry.operator == Operator.LT and entry.threshold == 30.0
    assert exit_.indicator == Indicator.RSI and exit_.operator == Operator.GT and exit_.threshold == 70.0


def test_extracts_momentum_macd_crossover():
    text = (
        "This momentum trend following strategy uses a moving average crossover: enter "
        "when MACD crosses above signal and exit when MACD crosses below signal."
    )
    result = extract(text, "https://example.com/b")

    assert result.spec is not None
    assert result.spec.archetype == Archetype.MOMENTUM
    assert result.spec.entry_conditions[0].operator == Operator.CROSSES_ABOVE
    assert result.spec.exit_conditions[0].operator == Operator.CROSSES_BELOW


def test_unrelated_text_returns_none():
    text = "I like turtles and sometimes trade stocks for fun."
    result = extract(text, "https://example.com/c")

    assert result.spec is None
    assert result.confidence == 0.0


def test_archetype_detected_but_no_numeric_rule_returns_none():
    text = "This is a breakout strategy that trades range breakouts with volume confirmation."
    result = extract(text, "https://example.com/d")

    assert result.spec is None


def test_extracts_breakout_channel_high_before_later_conditions():
    text = (
        "This breakout strategy enters when price breaks above the 20-day high, "
        "with volume above 2x average, and exits on a 10-day low."
    )
    result = extract(text, "https://example.com/e")

    assert result.spec is not None
    assert result.spec.archetype == Archetype.BREAKOUT
    entry = result.spec.entry_conditions[0]
    assert entry.indicator == Indicator.CHANNEL_HIGH
    assert entry.operator == Operator.CROSSES_ABOVE
    assert entry.period == 20
