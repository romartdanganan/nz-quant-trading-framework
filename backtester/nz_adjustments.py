"""Bridges backtester equity curves with nz_tax_fx's FX conversion and FIF tax math.
This module orchestrates calls into nz_tax_fx/; it does not duplicate any FX/tax math
itself — that stays the sole responsibility of nz_tax_fx/.

IMPORTANT design notes — two real bugs were found and fixed here after a strategy
comparison showed every backtested strategy converging to nearly the same Sharpe ratio
regardless of how different their raw trading logic was:

1. The equity curve is converted to NZD using a SINGLE fixed rate for the whole series,
   not the daily fluctuating rate. A trading strategy that's flat (no position) most of
   the time holds its capital as uninvested USD cash for most of the backtest —
   re-exposing that idle cash to two years of day-by-day USD/NZD movement injects
   currency-market noise into Sharpe/MaxDD that has nothing to do with the strategy's own
   trading skill (measured empirically at ~140x the volatility of the strategy's own USD
   returns). A constant-factor conversion doesn't change any of those ratios at all
   (percentage returns are scale-invariant to a constant multiplier).

2. FIF tax is NOT folded into the Sharpe/MaxDD/ProfitFactor calculation at all — see
   quant_engine/validation/metrics.py's Metrics.net_return_nzd docstring. It's a once-a-
   year lump-sum liability, not a day-to-day risk phenomenon. Trying to inject it into a
   daily return series — whether as a single lump sum on the final bar (which created a
   real, measured -364-standard-deviation outlier that dominated Sharpe's mean/std
   calculation) or smoothed as a linear ramp across every day (which instead added a
   small but *constant* daily drag against strategies whose *median* day-to-day move is
   exactly $0 — i.e. flat/no-position days, the majority for a low-frequency strategy —
   which persistently biases the mean negative against near-zero variance and produces
   nonsensical Sharpe ratios like -45) is a category error either way. Tax now only
   affects the separately-reported net_return_nzd() bottom-line figure.
"""
from __future__ import annotations

import pandas as pd

from nz_tax_fx.fif_calculator import FIFCalculator
from nz_tax_fx.fx_converter import FXConverter


def convert_equity_curve_to_nzd(equity_curve: pd.Series, fx_converter: FXConverter) -> pd.Series:
    """Converts a USD equity curve to NZD using a single fixed rate (the curve's end
    date) applied uniformly — see module docstring for why this is deliberate: it keeps
    Sharpe/MaxDD/ProfitFactor measuring the strategy's own edge rather than USD/NZD
    currency-market noise on capital that (while the strategy is flat) was never actually
    held as a foreign share subject to day-by-day FX revaluation.
    """
    if equity_curve.empty:
        return equity_curve

    end_date = equity_curve.index.max().date()
    rate = fx_converter.get_rate(end_date)
    return equity_curve * rate


def apply_fx_fee(equity_curve_nzd: pd.Series, fx_fee_pct: float) -> pd.Series:
    """Applies a flat round-trip FX conversion cost as a drag on the whole curve — a
    simplification until execution_ibkr/execution_alpaca report actual per-trade
    conversion spreads (Phase 7). A constant scalar, so this doesn't affect
    Sharpe/MaxDD either (same scale-invariance reasoning as the fixed-rate conversion).
    """
    return equity_curve_nzd * (1 - fx_fee_pct)


def estimate_fif_tax_drag(
    equity_curve_usd: pd.Series,
    fx_converter: FXConverter,
    fif_calculator: FIFCalculator,
    fif_method: str = "auto",
) -> float:
    """Estimates FIF tax on the backtest period as if it were a single NZ tax year:
    opening/closing value = first/last USD equity value, each converted to NZD at its own
    real date's rate (per CLAUDE.md: "realized amounts use the rate at the transaction
    date... never a single blended rate") — no interim purchases/sales/dividends modeled
    (a buy-and-hold approximation — see fif_calculator.py's own not-tax-advice disclaimer,
    which applies here too).

    Takes the raw USD curve (not an already-NZD-converted one) specifically so this can use
    the real dated rate at open/close, independent of the single fixed rate
    convert_equity_curve_to_nzd used for the Sharpe/MaxDD-facing curve.

    Note: this calls FIFCalculator.calculate_fdr_tax/calculate_cv_tax directly rather than
    FIFCalculator.assess() — assess()'s threshold check is holdings-cost-basis-based, which
    a backtest equity curve doesn't have. The opening equity value is used as the threshold
    proxy instead (a backtest-only simplification).
    """
    if equity_curve_usd.empty:
        return 0.0

    start_date = equity_curve_usd.index.min().date()
    end_date = equity_curve_usd.index.max().date()
    opening_value_nzd = fx_converter.convert_to_nzd(float(equity_curve_usd.iloc[0]), start_date)
    closing_value_nzd = fx_converter.convert_to_nzd(float(equity_curve_usd.iloc[-1]), end_date)

    if opening_value_nzd <= fif_calculator.threshold_nzd:
        return 0.0

    fdr_tax = fif_calculator.calculate_fdr_tax(opening_value_nzd)
    cv_tax = fif_calculator.calculate_cv_tax(
        opening_value_nzd, closing_value_nzd, purchases_nzd=0.0, sales_nzd=0.0, dividends_nzd=0.0
    )

    if fif_method == "fdr":
        return fdr_tax
    if fif_method == "cv":
        return cv_tax
    return min(fdr_tax, cv_tax)


def prepare_metrics_curve(
    equity_curve_usd: pd.Series, fx_converter: FXConverter, fx_fee_pct: float
) -> pd.Series:
    """Returns the NZD curve Sharpe/MaxDD/ProfitFactor should be computed from: FX-
    converted at a single fixed rate and fee-adjusted (both scale-invariant, so this
    exactly preserves the strategy's own USD-native risk-adjusted shape) — WITHOUT any FIF
    tax drag baked in. See module docstring for why tax stays out of this curve entirely.
    """
    return apply_fx_fee(convert_equity_curve_to_nzd(equity_curve_usd, fx_converter), fx_fee_pct)


def net_return_nzd(
    equity_curve_usd: pd.Series,
    fx_converter: FXConverter,
    fif_calculator: FIFCalculator,
    fx_fee_pct: float,
) -> float:
    """The real bottom-line figure: the fee-adjusted NZD gain over the period, minus the
    estimated FIF tax — a single total-profitability number, not fed into any day-to-day
    risk ratio. This is where "net of NZ tax and FX" actually belongs (see module
    docstring); quant_engine/validation/metrics.py's Metrics.net_return_nzd carries it.
    """
    if equity_curve_usd.empty:
        return 0.0

    metrics_curve = prepare_metrics_curve(equity_curve_usd, fx_converter, fx_fee_pct)
    gross_gain_nzd = float(metrics_curve.iloc[-1] - metrics_curve.iloc[0])
    tax_drag = estimate_fif_tax_drag(equity_curve_usd, fx_converter, fif_calculator)
    return gross_gain_nzd - tax_drag
