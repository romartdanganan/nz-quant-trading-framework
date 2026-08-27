"""Bridges backtester equity curves with nz_tax_fx's FX conversion and FIF tax math, so
validation metrics reflect what an NZ trader actually keeps — never a pre-cost, pre-tax
figure (see CLAUDE.md Guardrails). This module orchestrates calls into nz_tax_fx/; it does
not duplicate any FX/tax math itself — that stays the sole responsibility of nz_tax_fx/.
"""
from __future__ import annotations

import pandas as pd

from nz_tax_fx.fif_calculator import FIFCalculator
from nz_tax_fx.fx_converter import FXConverter


def convert_equity_curve_to_nzd(equity_curve: pd.Series, fx_converter: FXConverter) -> pd.Series:
    """Converts a USD equity curve to NZD day-by-day using the real historical USD/NZD
    rate for each date — never a single blended rate across the period (CLAUDE.md).
    """
    if equity_curve.empty:
        return equity_curve

    start = equity_curve.index.min().date()
    end = equity_curve.index.max().date()
    rate_series = fx_converter.get_rate_series(start, end)

    rates = pd.Series({pd.Timestamp(date_str): rate for date_str, rate in rate_series.items()}).sort_index()
    aligned_rates = rates.reindex(equity_curve.index, method="ffill").bfill()

    return equity_curve * aligned_rates


def apply_fx_fee(equity_curve_nzd: pd.Series, fx_fee_pct: float) -> pd.Series:
    """Applies a flat round-trip FX conversion cost as a drag on the whole curve — a
    simplification until execution_ibkr/execution_alpaca report actual per-trade
    conversion spreads (Phase 7).
    """
    return equity_curve_nzd * (1 - fx_fee_pct)


def estimate_fif_tax_drag(
    equity_curve_nzd: pd.Series,
    fif_calculator: FIFCalculator,
    fif_method: str = "auto",
) -> float:
    """Estimates FIF tax on the backtest period as if it were a single NZ tax year:
    opening/closing value = first/last NZD equity value, no interim purchases/sales/
    dividends modeled (a buy-and-hold approximation — see fif_calculator.py's own
    not-tax-advice disclaimer, which applies here too).

    Note: this calls FIFCalculator.calculate_fdr_tax/calculate_cv_tax directly rather than
    FIFCalculator.assess() — assess()'s threshold check is holdings-cost-basis-based, which
    a backtest equity curve doesn't have. The opening equity value is used as the threshold
    proxy instead (a backtest-only simplification).
    """
    if equity_curve_nzd.empty:
        return 0.0

    opening_value_nzd = float(equity_curve_nzd.iloc[0])
    closing_value_nzd = float(equity_curve_nzd.iloc[-1])

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


def apply_nz_costs(
    equity_curve_usd: pd.Series,
    fx_converter: FXConverter,
    fif_calculator: FIFCalculator,
    fx_fee_pct: float,
) -> pd.Series:
    """Full pipeline: USD equity curve -> NZD (real daily rates) -> minus FX fee -> minus
    FIF tax (applied as a single deduction at the final bar, since FIF is an annual
    assessment, not a daily one). Returns the net-of-cost NZD curve that
    quant_engine/validation/metrics.py should compute Sharpe/MaxDD/ProfitFactor from.
    """
    equity_nzd = convert_equity_curve_to_nzd(equity_curve_usd, fx_converter)
    equity_nzd = apply_fx_fee(equity_nzd, fx_fee_pct)

    tax_drag = estimate_fif_tax_drag(equity_nzd, fif_calculator)
    if tax_drag <= 0:
        return equity_nzd

    net_equity = equity_nzd.copy()
    net_equity.iloc[-1] = net_equity.iloc[-1] - tax_drag
    return net_equity
