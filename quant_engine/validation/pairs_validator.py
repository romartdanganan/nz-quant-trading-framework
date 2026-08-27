"""Validation gate for pairs-trading candidates — mirrors validator.py's role for
single-ticker strategies. Pairs trading needs its own first gate: cointegration must hold
(CLAUDE.md Guardrails on backtest overfitting apply here too — trading two uncointegrated
tickers as a "pair" is curve-fitting, not a real relationship) before the same
Sharpe/MaxDD/ProfitFactor thresholds and NZ tax/FX drag apply.

Known limitation: unlike validator.py, this has no walk-forward overfit_guard equivalent
yet — the cointegration test is the only overfitting guard for pairs so far.
"""
from __future__ import annotations

import pandas as pd

from backtester.nz_adjustments import apply_nz_costs
from backtester.pairs_engine import run_pairs_backtest
from config.settings import settings
from nz_tax_fx.fif_calculator import FIFCalculator
from nz_tax_fx.fx_converter import FXConverter
from quant_engine.validation.metrics import compute_metrics
from quant_engine.validation.validator import ValidationResult
from strategies.pairs_trading.strategy import PairsSpec, align_price_series, check_cointegration

DEFAULT_COINTEGRATION_SIGNIFICANCE = 0.05


def validate_pairs_strategy(
    spec: PairsSpec,
    price_a: pd.Series,
    price_b: pd.Series,
    fx_converter: FXConverter | None = None,
    fif_calculator: FIFCalculator | None = None,
) -> ValidationResult:
    fx_converter = fx_converter or FXConverter()
    fif_calculator = fif_calculator or FIFCalculator(fx_converter=fx_converter)
    significance = settings.get(
        "pairs_trading.cointegration_significance", DEFAULT_COINTEGRATION_SIGNIFICANCE
    )

    price_a, price_b = align_price_series(price_a, price_b)
    p_value = check_cointegration(price_a, price_b)
    if p_value >= significance:
        return ValidationResult(False, f"not cointegrated (p-value {p_value:.3f} >= {significance})")

    result = run_pairs_backtest(spec, price_a, price_b)
    if result.equity_curve.empty or not result.trades:
        return ValidationResult(False, "pairs strategy produced no trades over the backtest period")

    min_sharpe = settings.get("validation_thresholds.min_sharpe_ratio", 1.5)
    max_drawdown = settings.get("validation_thresholds.max_drawdown_pct", 0.15)
    min_profit_factor = settings.get("validation_thresholds.min_profit_factor", 1.3)
    apply_tax = settings.get("validation_thresholds.apply_nz_tax_drag", True)
    apply_fx = settings.get("validation_thresholds.apply_fx_fees", True)
    fx_fee_pct = settings.get("validation_thresholds.fx_fee_pct", 0.005)

    equity_curve = result.equity_curve
    if apply_tax or apply_fx:
        equity_curve = apply_nz_costs(
            equity_curve,
            fx_converter=fx_converter,
            fif_calculator=fif_calculator,
            fx_fee_pct=fx_fee_pct if apply_fx else 0.0,
        )

    metrics = compute_metrics(equity_curve, result.trades)

    if metrics.sharpe_ratio <= min_sharpe:
        return ValidationResult(False, f"Sharpe {metrics.sharpe_ratio:.2f} <= required {min_sharpe}", metrics)
    if metrics.max_drawdown_pct >= max_drawdown:
        return ValidationResult(
            False, f"MaxDD {metrics.max_drawdown_pct:.1%} >= limit {max_drawdown:.1%}", metrics
        )
    if metrics.profit_factor <= min_profit_factor:
        return ValidationResult(
            False, f"Profit factor {metrics.profit_factor:.2f} <= required {min_profit_factor}", metrics
        )

    return ValidationResult(True, f"passed all thresholds (cointegration p-value {p_value:.4f})", metrics)
