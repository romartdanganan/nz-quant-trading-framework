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
