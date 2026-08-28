"""Computes entry/exit boolean signal series from a StrategySpec against OHLCV price
data, using pandas-ta for standard indicators and hand-rolled pandas for VWAP/z-score/
channel-high-low (pandas-ta doesn't provide these in the form our vocabulary needs). Pure
pandas, no backtrader dependency — independently testable from engine.py.

The generic BOLLINGER_BANDS tag is rejected rather than guessed at: a single threshold
doesn't disambiguate "distance from upper band" vs "from lower band" vs "band width" — per
CLAUDE.md's "reject rather than guess" principle, callers must catch
UnsupportedIndicatorError and reject the strategy (see quant_engine/validation).
BOLLINGER_UPPER/BOLLINGER_LOWER are the disambiguated, actually-supported form: each names
one specific band line, evaluated the same way CHANNEL_HIGH/CHANNEL_LOW compare close
against a computed line (a crossover, not a fixed numeric threshold).
KELTNER_UPPER/KELTNER_LOWER follow the same pattern using ATR instead of standard
deviation for the band width — a genuinely different volatility measure from Bollinger.
"""
from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from strategy_research.strategy_spec import Condition, Indicator, Operator, StrategySpec

RSI_PERIOD = 14
ATR_PERIOD = 14
VOLUME_AVG_PERIOD = 20
ZSCORE_PERIOD = 20
MA_PERIOD = 20
CHANNEL_PERIOD = 20
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0  # John Bollinger's own standard default; not tuned per-strategy
KELTNER_PERIOD = 20
KELTNER_MULTIPLIER = 2.0  # standard convention; not tuned per-strategy

CROSSOVER_OPERATORS = (Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW)


class UnsupportedIndicatorError(ValueError):
    """Raised when a condition can't be honestly evaluated by this engine."""


def generate_signals(spec: StrategySpec, price_data: pd.DataFrame) -> pd.DataFrame:
    """Returns a DataFrame (same index as price_data) with boolean columns entry_signal
    and exit_signal — True where *all* of the spec's entry/exit conditions hold.
    """
    entry_signal = _combine_conditions(spec.entry_conditions, price_data)
    exit_signal = _combine_conditions(spec.exit_conditions, price_data)
    return pd.DataFrame(
        {"entry_signal": entry_signal, "exit_signal": exit_signal}, index=price_data.index
    )


def _combine_conditions(conditions: list[Condition], df: pd.DataFrame) -> pd.Series:
    result = pd.Series(True, index=df.index)
    for condition in conditions:
        result &= _evaluate_condition(condition, df)
    return result.fillna(False)


def _evaluate_condition(condition: Condition, df: pd.DataFrame) -> pd.Series:
    if condition.indicator == Indicator.MACD:
        return _evaluate_macd(condition, df)
    if condition.indicator == Indicator.VWAP:
        return _evaluate_vwap(condition, df)
    if condition.indicator in (Indicator.CHANNEL_HIGH, Indicator.CHANNEL_LOW):
        return _evaluate_channel(condition, df)
    if condition.indicator in (Indicator.BOLLINGER_UPPER, Indicator.BOLLINGER_LOWER):
        return _evaluate_bollinger(condition, df)
    if condition.indicator in (Indicator.KELTNER_UPPER, Indicator.KELTNER_LOWER):
        return _evaluate_keltner(condition, df)
    if condition.indicator == Indicator.BOLLINGER_BANDS:
        raise UnsupportedIndicatorError(
            "BOLLINGER_BANDS conditions are not supported by the backtest engine (ambiguous "
            "band edge — use BOLLINGER_UPPER/BOLLINGER_LOWER instead, see module docstring)"
        )

    value_line = _get_value_line(condition.indicator, df, condition.period)
    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_threshold(value_line, condition.threshold, condition.operator)
    return _compare(value_line, condition.operator, condition.threshold)


def _get_value_line(indicator: Indicator, df: pd.DataFrame, period: int | None) -> pd.Series:
    if indicator == Indicator.RSI:
        return ta.rsi(df["close"], length=period or RSI_PERIOD)
    if indicator == Indicator.ATR:
        return ta.atr(df["high"], df["low"], df["close"], length=period or ATR_PERIOD)
    if indicator == Indicator.SMA:
        return ta.sma(df["close"], length=period or MA_PERIOD)
    if indicator == Indicator.EMA:
        return ta.ema(df["close"], length=period or MA_PERIOD)
    if indicator == Indicator.ZSCORE:
        window = period or ZSCORE_PERIOD
        rolling_mean = df["close"].rolling(window).mean()
        rolling_std = df["close"].rolling(window).std()
        return (df["close"] - rolling_mean) / rolling_std
    if indicator == Indicator.VOLUME:
        avg_volume = df["volume"].rolling(period or VOLUME_AVG_PERIOD).mean()
        return df["volume"] / avg_volume
    raise UnsupportedIndicatorError(f"No value line defined for {indicator}")


def _evaluate_channel(condition: Condition, df: pd.DataFrame) -> pd.Series:
    """CHANNEL_HIGH/CHANNEL_LOW: the classic breakout signal — close crossing the rolling
    N-day high/low. Shifted by 1 bar so "today's high" never counts toward "today's
    breakout level" (that would be lookahead: the high isn't known until the bar closes).
    """
    period = condition.period or CHANNEL_PERIOD
    if condition.indicator == Indicator.CHANNEL_HIGH:
        channel_line = df["high"].rolling(period).max().shift(1)
    else:
        channel_line = df["low"].rolling(period).min().shift(1)

    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_lines(df["close"], channel_line, condition.operator)
    return _compare(channel_line, condition.operator, condition.threshold)


def _evaluate_bollinger(condition: Condition, df: pd.DataFrame) -> pd.Series:
    """BOLLINGER_UPPER/BOLLINGER_LOWER: close crossing a specific band line, the same
    crossover-vs-computed-line pattern as _evaluate_channel. pandas-ta's bbands() column
    order is fixed (lower, mid, upper, bandwidth, %b), so select by position rather than by
    name to avoid coupling to its exact naming scheme across versions.
    """
    period = condition.period or BOLLINGER_PERIOD
    bands = ta.bbands(df["close"], length=period, std=BOLLINGER_STD)
    band_line = bands.iloc[:, 0] if condition.indicator == Indicator.BOLLINGER_LOWER else bands.iloc[:, 2]

    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_lines(df["close"], band_line, condition.operator)
    return _compare(band_line, condition.operator, condition.threshold)


def _evaluate_keltner(condition: Condition, df: pd.DataFrame) -> pd.Series:
    """KELTNER_UPPER/KELTNER_LOWER: EMA +/- ATR*multiplier, the volatility-adjusted cousin of
    a Bollinger band (uses ATR instead of standard deviation) — same close-crosses-the-line
    pattern as _evaluate_bollinger/_evaluate_channel. pandas-ta's kc() column order is fixed
    (lower, basis, upper), so select by position rather than by name.
    """
    period = condition.period or KELTNER_PERIOD
    bands = ta.kc(df["high"], df["low"], df["close"], length=period, scalar=KELTNER_MULTIPLIER)
    band_line = bands.iloc[:, 0] if condition.indicator == Indicator.KELTNER_LOWER else bands.iloc[:, 2]

    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_lines(df["close"], band_line, condition.operator)
    return _compare(band_line, condition.operator, condition.threshold)


def _evaluate_macd(condition: Condition, df: pd.DataFrame) -> pd.Series:
    macd_df = ta.macd(df["close"])
    macd_line, signal_line = macd_df.iloc[:, 0], macd_df.iloc[:, 2]
    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_lines(macd_line, signal_line, condition.operator)
    return _compare(macd_line, condition.operator, condition.threshold)


def _evaluate_vwap(condition: Condition, df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vwap_line = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_lines(df["close"], vwap_line, condition.operator)
    return _compare(vwap_line, condition.operator, condition.threshold)


def _compare(line: pd.Series, operator: Operator, threshold: float) -> pd.Series:
    if operator == Operator.LT:
        return line < threshold
    if operator == Operator.GT:
        return line > threshold
    if operator == Operator.LTE:
        return line <= threshold
    if operator == Operator.GTE:
        return line >= threshold
    raise UnsupportedIndicatorError(f"{operator} requires a value-line comparison, not crossover")


def _crosses_threshold(line: pd.Series, threshold: float, operator: Operator) -> pd.Series:
    previous = line.shift(1)
    if operator == Operator.CROSSES_ABOVE:
        return (previous <= threshold) & (line > threshold)
    return (previous >= threshold) & (line < threshold)


def _crosses_lines(line_a: pd.Series, line_b: pd.Series, operator: Operator) -> pd.Series:
    prev_a, prev_b = line_a.shift(1), line_b.shift(1)
    if operator == Operator.CROSSES_ABOVE:
        return (prev_a <= prev_b) & (line_a > line_b)
    return (prev_a >= prev_b) & (line_a < line_b)
