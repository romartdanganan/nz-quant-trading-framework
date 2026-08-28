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


def test_single_condition_mentioned_once_returns_none():
    # A real bug found 2026-08-28: a mean-reversion README that only clearly states one
    # side of the rule (e.g. just describes an overbought exit) used to get that same
    # condition duplicated into both entry AND exit, fabricating a degenerate strategy
    # that can never hold a position sensibly. Must reject instead.
    text = "This mean reversion strategy trades RSI overbought conditions above 70."
    result = extract(text, "https://example.com/single")

    assert result.spec is None


def test_condition_mentioned_twice_with_same_value_returns_none():
    # Same bug, different path: the phrase appears twice in the text (e.g. once in prose,
    # once in an example), producing two IDENTICAL Condition matches rather than a real
    # distinct entry+exit pair.
    text = (
        "This mean reversion strategy is a classic RSI play: RSI below 30 is the signal. "
        "For example, RSI below 30 happened last Tuesday and the stock rallied."
    )
    result = extract(text, "https://example.com/dup")

    assert result.spec is None


def test_pairs_trading_archetype_is_rejected_not_mislabeled():
    # A real bug found 2026-08-28: rule_extractor has no logic to identify two tickers or a
    # hedge ratio/spread from text, so it was building a plain single-ticker StrategySpec
    # (with an arbitrary, unrelated condition) and mislabeling it archetype=pairs_trading —
    # structurally incoherent, since StrategySpec can't represent pairs trading at all.
    text = (
        "This pairs trading strategy trades cointegrated pairs. ATR above 90 triggers a "
        "position, and ATR below 10 closes it."
    )
    result = extract(text, "https://example.com/pairs")

    assert result.spec is None
