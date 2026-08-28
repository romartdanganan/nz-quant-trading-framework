import numpy as np
import pandas as pd
import pytest

from backtester.signals import (
    UnsupportedIndicatorError,
    _compare,
    _crosses_lines,
    _crosses_threshold,
    generate_signals,
)
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def make_ohlcv(n: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), index=dates)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.integers(1000, 5000, n),
        },
        index=dates,
    )


def make_spec(entry, exit_, archetype=Archetype.MEAN_REVERSION) -> StrategySpec:
    return StrategySpec(
        name="t",
        archetype=archetype,
        entry_conditions=entry,
        exit_conditions=exit_,
        timeframe="1d",
        source_url="https://example.com",
        extraction_method="rule",
        confidence=0.9,
    )


def test_compare_operators():
    line = pd.Series([10, 20, 30])
    assert list(_compare(line, Operator.LT, 25)) == [True, True, False]
    assert list(_compare(line, Operator.GT, 15)) == [False, True, True]
    assert list(_compare(line, Operator.LTE, 20)) == [True, True, False]
    assert list(_compare(line, Operator.GTE, 20)) == [False, True, True]


def test_crosses_threshold_above_and_below():
    line = pd.Series([28, 29, 31, 29, 27])
    above = _crosses_threshold(line, 30, Operator.CROSSES_ABOVE).fillna(False)
    below = _crosses_threshold(line, 30, Operator.CROSSES_BELOW).fillna(False)
    assert list(above) == [False, False, True, False, False]
    # crosses back below 30 the bar it drops from 31 to 29 (index 3), not later
    assert list(below) == [False, False, False, True, False]


def test_crosses_lines_above_and_below():
    line_a = pd.Series([1, 2, 4, 2, 1])
    line_b = pd.Series([3, 3, 3, 3, 3])
    above = _crosses_lines(line_a, line_b, Operator.CROSSES_ABOVE).fillna(False)
    below = _crosses_lines(line_a, line_b, Operator.CROSSES_BELOW).fillna(False)
    assert list(above) == [False, False, True, False, False]
    assert list(below) == [False, False, False, True, False]


def test_generate_signals_rsi_shape_and_dtype():
    df = make_ohlcv()
    spec = make_spec(
        entry=[Condition(Indicator.RSI, Operator.LT, 30)],
        exit_=[Condition(Indicator.RSI, Operator.GT, 70)],
    )
    signals = generate_signals(spec, df)

    assert list(signals.columns) == ["entry_signal", "exit_signal"]
    assert signals.index.equals(df.index)
    assert signals["entry_signal"].dtype == bool
    assert signals["exit_signal"].dtype == bool


def test_generate_signals_macd_crossover_runs():
    df = make_ohlcv(seed=1)
    spec = make_spec(
        entry=[Condition(Indicator.MACD, Operator.CROSSES_ABOVE, 0.0)],
        exit_=[Condition(Indicator.MACD, Operator.CROSSES_BELOW, 0.0)],
        archetype=Archetype.MOMENTUM,
    )
    signals = generate_signals(spec, df)
    assert signals["entry_signal"].dtype == bool


def test_generate_signals_vwap_crossover_runs():
    df = make_ohlcv(seed=2)
    spec = make_spec(
        entry=[Condition(Indicator.VWAP, Operator.CROSSES_ABOVE, 0.0)],
        exit_=[Condition(Indicator.VWAP, Operator.CROSSES_BELOW, 0.0)],
        archetype=Archetype.MOMENTUM,
    )
    signals = generate_signals(spec, df)
    assert signals["entry_signal"].dtype == bool


def test_generate_signals_zscore_and_volume_run():
    df = make_ohlcv(seed=3)
    spec = make_spec(
        entry=[Condition(Indicator.ZSCORE, Operator.LT, -2.0)],
        exit_=[Condition(Indicator.VOLUME, Operator.GT, 2.0)],
    )
    signals = generate_signals(spec, df)
    assert signals["entry_signal"].dtype == bool
    assert signals["exit_signal"].dtype == bool


def test_bollinger_bands_condition_raises_unsupported():
    df = make_ohlcv()
    spec = make_spec(
        entry=[Condition(Indicator.BOLLINGER_BANDS, Operator.GT, 1.0)],
        exit_=[Condition(Indicator.BOLLINGER_BANDS, Operator.LT, 1.0)],
    )
    with pytest.raises(UnsupportedIndicatorError):
        generate_signals(spec, df)


def test_bollinger_lower_crosses_below_detects_a_real_dip():
    dates = pd.date_range("2023-01-01", periods=25, freq="D")
    close = pd.Series([100.0] * 20 + [100, 100, 100, 70, 100], index=dates)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000}, index=dates
    )
    spec = make_spec(
        entry=[Condition(Indicator.BOLLINGER_LOWER, Operator.CROSSES_BELOW, 0.0, period=20)],
        exit_=[Condition(Indicator.BOLLINGER_UPPER, Operator.CROSSES_ABOVE, 0.0, period=20)],
    )

    signals = generate_signals(spec, df)

    # index 23 is the bar where close plunges to 70, well outside a flat-100 band
    assert signals["entry_signal"].iloc[23] == True  # noqa: E712 - explicit bool check on a numpy bool
    assert not signals["entry_signal"].iloc[:23].any()


def test_bollinger_upper_crosses_above_detects_a_real_spike():
    dates = pd.date_range("2023-01-01", periods=25, freq="D")
    close = pd.Series([100.0] * 20 + [100, 100, 100, 130, 100], index=dates)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000}, index=dates
    )
    spec = make_spec(
        entry=[Condition(Indicator.BOLLINGER_LOWER, Operator.CROSSES_BELOW, 0.0, period=20)],
        exit_=[Condition(Indicator.BOLLINGER_UPPER, Operator.CROSSES_ABOVE, 0.0, period=20)],
    )

    signals = generate_signals(spec, df)

    assert signals["exit_signal"].iloc[23] == True  # noqa: E712
    assert not signals["exit_signal"].iloc[:23].any()


def test_keltner_upper_crosses_above_detects_a_real_spike():
    dates = pd.date_range("2023-01-01", periods=25, freq="D")
    close = pd.Series([100.0] * 20 + [100, 100, 100, 130, 100], index=dates)
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000}, index=dates
    )
    spec = make_spec(
        entry=[Condition(Indicator.KELTNER_UPPER, Operator.CROSSES_ABOVE, 0.0, period=20)],
        exit_=[Condition(Indicator.KELTNER_LOWER, Operator.CROSSES_BELOW, 0.0, period=20)],
        archetype=Archetype.BREAKOUT,
    )

    signals = generate_signals(spec, df)

    assert signals["entry_signal"].iloc[23] == True  # noqa: E712
    assert not signals["entry_signal"].iloc[:23].any()


def test_keltner_lower_crosses_below_detects_a_real_dip():
    dates = pd.date_range("2023-01-01", periods=25, freq="D")
    close = pd.Series([100.0] * 20 + [100, 100, 100, 70, 100], index=dates)
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000}, index=dates
    )
    spec = make_spec(
        entry=[Condition(Indicator.KELTNER_UPPER, Operator.CROSSES_ABOVE, 0.0, period=20)],
        exit_=[Condition(Indicator.KELTNER_LOWER, Operator.CROSSES_BELOW, 0.0, period=20)],
        archetype=Archetype.BREAKOUT,
    )

    signals = generate_signals(spec, df)

    assert signals["exit_signal"].iloc[23] == True  # noqa: E712
    assert not signals["exit_signal"].iloc[:23].any()


def test_channel_high_breakout_detects_close_crossing_rolling_high():
    dates = pd.date_range("2023-01-01", periods=10, freq="D")
    close = pd.Series([100, 100, 100, 100, 100, 100, 100, 100, 150, 100], index=dates)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000}, index=dates
    )
    spec = make_spec(
        entry=[Condition(Indicator.CHANNEL_HIGH, Operator.CROSSES_ABOVE, 0.0, period=5)],
        exit_=[Condition(Indicator.CHANNEL_LOW, Operator.CROSSES_BELOW, 0.0, period=5)],
        archetype=Archetype.BREAKOUT,
    )

    signals = generate_signals(spec, df)

    assert signals["entry_signal"].iloc[8] == True  # noqa: E712 — the 150 spike bar
    assert signals["entry_signal"].sum() == 1


def test_channel_high_never_leaks_todays_own_high():
    # a single huge spike bar must never trigger its own breakout: the rolling max used
    # for comparison is shifted by 1, so a spike can only be "broken out of" on a later bar.
    dates = pd.date_range("2023-01-01", periods=6, freq="D")
    close = pd.Series([100, 100, 500, 100, 100, 100], index=dates)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000}, index=dates
    )
    spec = make_spec(
        entry=[Condition(Indicator.CHANNEL_HIGH, Operator.CROSSES_ABOVE, 0.0, period=2)],
        exit_=[Condition(Indicator.CHANNEL_LOW, Operator.CROSSES_BELOW, 0.0, period=2)],
        archetype=Archetype.BREAKOUT,
    )

    signals = generate_signals(spec, df)

    assert signals["entry_signal"].iloc[2] == False  # noqa: E712 — the spike bar itself


def test_condition_period_override_changes_rsi_window(monkeypatch):
    df = make_ohlcv()
    captured_lengths = []

    import backtester.signals as signals_module

    original_rsi = signals_module.ta.rsi

    def spy_rsi(close, length):
        captured_lengths.append(length)
        return original_rsi(close, length=length)

    monkeypatch.setattr(signals_module.ta, "rsi", spy_rsi)

    spec = make_spec(
        entry=[Condition(Indicator.RSI, Operator.LT, 30, period=21)],
        exit_=[Condition(Indicator.RSI, Operator.GT, 70)],
    )
    generate_signals(spec, df)

    assert 21 in captured_lengths
    assert signals_module.RSI_PERIOD in captured_lengths  # the exit condition used the default
