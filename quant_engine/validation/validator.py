"""Top-level validation gate: runs a full backtest, checks the Sharpe/MaxDD/ProfitFactor
thresholds (computed on an FX-fee-adjusted-but-not-tax-adjusted curve — see
backtester/nz_adjustments.py's module docstring for why FIF tax stays out of these ratios),
surfaces the real NZ-tax-adjusted bottom line separately via Metrics.net_return_nzd, and
runs the walk-forward overfit guard. This is the single place that decides
candidate -> validated/rejected (CLAUDE.md Strategy Lifecycle) — validation logic must
never be duplicated ad hoc elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from backtester.engine import run_backtest
from backtester.nz_adjustments import net_return_nzd, prepare_metrics_curve
from backtester.signals import UnsupportedIndicatorError
from config.settings import settings
from nz_tax_fx.fif_calculator import FIFCalculator
from nz_tax_fx.fx_converter import FXConverter
from quant_engine.validation.metrics import Metrics, compute_metrics
from quant_engine.validation.overfit_guard import walk_forward_check
from strategy_research.strategy_spec import StrategySpec


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str
    metrics: Metrics | None = None
    p_value: float | None = None  # pairs-trading cointegration p-value; unused for single-ticker


def validate_strategy(
    spec: StrategySpec,
    price_data: pd.DataFrame,
    fx_converter: FXConverter | None = None,
    fif_calculator: FIFCalculator | None = None,
) -> ValidationResult:
    fx_converter = fx_converter or FXConverter()
    fif_calculator = fif_calculator or FIFCalculator(
        fx_converter=fx_converter,
        marginal_tax_rate=settings.get("nz_tax.marginal_tax_rate", 0.33),
    )

    min_sharpe = settings.get("validation_thresholds.min_sharpe_ratio", 1.5)
    max_drawdown = settings.get("validation_thresholds.max_drawdown_pct", 0.15)
    min_profit_factor = settings.get("validation_thresholds.min_profit_factor", 1.3)
    min_trades = settings.get("validation_thresholds.min_trades", 20)
    apply_tax = settings.get("validation_thresholds.apply_nz_tax_drag", True)
    apply_fx = settings.get("validation_thresholds.apply_fx_fees", True)
    fx_fee_pct = settings.get("validation_thresholds.fx_fee_pct", 0.005)

    try:
        result = run_backtest(spec, price_data)
    except UnsupportedIndicatorError as exc:
        return ValidationResult(False, f"unsupported indicator in backtest engine: {exc}")

    if result.equity_curve.empty or not result.trades:
        return ValidationResult(False, "strategy produced no trades over the backtest period")
    if len(result.trades) < min_trades:
        return ValidationResult(
            False,
            f"only {len(result.trades)} trades over the backtest period "
            f"(need >= {min_trades} for the Sharpe/ProfitFactor estimate to be meaningful)",
        )

    equity_curve = result.equity_curve
    if apply_fx:
        equity_curve = prepare_metrics_curve(equity_curve, fx_converter, fx_fee_pct)

    metrics = compute_metrics(equity_curve, result.trades)
    if apply_tax:
        net_return = net_return_nzd(
            result.equity_curve, fx_converter, fif_calculator, fx_fee_pct if apply_fx else 0.0
        )
        metrics = replace(metrics, net_return_nzd=net_return)

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

    overfit_result = walk_forward_check(spec, price_data)
    if not overfit_result.passed:
        return ValidationResult(False, f"overfit guard: {overfit_result.reason}", metrics)

    return ValidationResult(True, "passed all validation thresholds", metrics)
