import numpy as np
import pandas as pd

from backtester.engine import run_backtest
from strategy_research.strategy_spec import Archetype, Condition, Indicator, Operator, StrategySpec


def make_ohlcv(n: int = 60, seed: int = 0) -> pd.DataFrame:
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


def test_run_backtest_produces_equity_curve_matching_price_data_length():
    df = make_ohlcv()
    spec = StrategySpec(
        name="rsi-reversion",
        archetype=Archetype.MEAN_REVERSION,
        entry_conditions=[Condition(Indicator.RSI, Operator.LT, 40)],
        exit_conditions=[Condition(Indicator.RSI, Operator.GT, 60)],
        timeframe="1d",
        source_url="https://example.com",
        extraction_method="rule",
        confidence=0.9,
    )

    result = run_backtest(spec, df)

    assert len(result.equity_curve) == len(df)
    assert result.equity_curve.iloc[0] > 0
    assert isinstance(result.trades, list)


def test_run_backtest_with_never_true_entry_never_trades():
    df = make_ohlcv(seed=5)
    spec = StrategySpec(
        name="never-enters",
        archetype=Archetype.MEAN_REVERSION,
        entry_conditions=[Condition(Indicator.RSI, Operator.LT, -1.0)],  # RSI in [0,100]: never true
        exit_conditions=[Condition(Indicator.RSI, Operator.GT, 100)],
        timeframe="1d",
        source_url="https://example.com",
        extraction_method="rule",
        confidence=0.9,
    )

    result = run_backtest(spec, df, initial_cash=50_000.0)

    assert result.trades == []
    assert all(value == 50_000.0 for value in result.equity_curve)
