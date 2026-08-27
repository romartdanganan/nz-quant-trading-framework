"""Computes entry/exit boolean signal series from a StrategySpec against OHLCV price
data, using pandas-ta for standard indicators and hand-rolled pandas for VWAP/z-score
(pandas-ta doesn't provide these in the form our vocabulary needs). Pure pandas, no
backtrader dependency — independently testable from the execution simulation in engine.py.

BOLLINGER_BANDS conditions are rejected rather than guessed at: the schema only carries a
single threshold, which doesn't disambiguate "distance from upper band" vs "from lower
band" vs "band width" — per CLAUDE.md's "reject rather than guess" principle, callers must
catch UnsupportedIndicatorError and reject the strategy (see quant_engine/validation).
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
    if condition.indicator == Indicator.BOLLINGER_BANDS:
        raise UnsupportedIndicatorError(
            "BOLLINGER_BANDS conditions are not supported by the backtest engine "
            "(ambiguous band edge — see module docstring)"
        )

    value_line = _get_value_line(condition.indicator, df)
    if condition.operator in CROSSOVER_OPERATORS:
        return _crosses_threshold(value_line, condition.threshold, condition.operator)
    return _compare(value_line, condition.operator, condition.threshold)


def _get_value_line(indicator: Indicator, df: pd.DataFrame) -> pd.Series:
    if indicator == Indicator.RSI:
        return ta.rsi(df["close"], length=RSI_PERIOD)
    if indicator == Indicator.ATR:
        return ta.atr(df["high"], df["low"], df["close"], length=ATR_PERIOD)
    if indicator == Indicator.SMA:
        return ta.sma(df["close"], length=MA_PERIOD)
    if indicator == Indicator.EMA:
        return ta.ema(df["close"], length=MA_PERIOD)
    if indicator == Indicator.ZSCORE:
        rolling_mean = df["close"].rolling(ZSCORE_PERIOD).mean()
        rolling_std = df["close"].rolling(ZSCORE_PERIOD).std()
        return (df["close"] - rolling_mean) / rolling_std
    if indicator == Indicator.VOLUME:
        avg_volume = df["volume"].rolling(VOLUME_AVG_PERIOD).mean()
        return df["volume"] / avg_volume
    raise UnsupportedIndicatorError(f"No value line defined for {indicator}")


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
