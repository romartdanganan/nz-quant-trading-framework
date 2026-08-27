import pandas as pd
import pytest

from backtester.nz_adjustments import (
    apply_fx_fee,
    apply_nz_costs,
    convert_equity_curve_to_nzd,
    estimate_fif_tax_drag,
)
from nz_tax_fx.fif_calculator import FIFCalculator


class FakeFX:
    def __init__(self, rate_series: dict):
        self.rate_series = rate_series

    def get_rate_series(self, start, end):
        return self.rate_series


def test_convert_equity_curve_to_nzd_applies_daily_rates():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    equity_usd = pd.Series([100.0, 200.0, 300.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.5, "2024-01-02": 1.6, "2024-01-03": 1.7})

    equity_nzd = convert_equity_curve_to_nzd(equity_usd, fake_fx)

    assert list(equity_nzd) == pytest.approx([150.0, 320.0, 510.0])


def test_convert_equity_curve_forward_fills_missing_days():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    equity_usd = pd.Series([100.0, 200.0, 300.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.5})  # days 2 and 3 must forward-fill

    equity_nzd = convert_equity_curve_to_nzd(equity_usd, fake_fx)

    assert list(equity_nzd) == pytest.approx([150.0, 300.0, 450.0])


def test_apply_fx_fee_reduces_equity_by_flat_pct():
    equity = pd.Series([100.0, 200.0])
    result = apply_fx_fee(equity, fx_fee_pct=0.01)
    assert list(result) == pytest.approx([99.0, 198.0])


def test_estimate_fif_tax_drag_under_threshold_is_zero():
    calc = FIFCalculator(fx_converter=FakeFX({}), threshold_nzd=50_000)
    equity_nzd = pd.Series([1_000.0, 1_100.0])

    assert estimate_fif_tax_drag(equity_nzd, calc) == 0.0


def test_estimate_fif_tax_drag_over_threshold_picks_lower_of_fdr_cv():
    calc = FIFCalculator(fx_converter=FakeFX({}), threshold_nzd=50_000)
    equity_nzd = pd.Series([60_000.0, 61_000.0])  # small gain -> CV (1,000) beats FDR (3,000)

    assert estimate_fif_tax_drag(equity_nzd, calc) == pytest.approx(1_000.0)


def test_estimate_fif_tax_drag_empty_series_is_zero():
    calc = FIFCalculator(fx_converter=FakeFX({}), threshold_nzd=50_000)
    assert estimate_fif_tax_drag(pd.Series(dtype=float), calc) == 0.0


def test_apply_nz_costs_subtracts_tax_from_final_bar_only():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([40_000.0, 45_000.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.6, "2024-01-02": 1.6})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000)

    result = apply_nz_costs(equity_usd, fake_fx, calc, fx_fee_pct=0.0)

    # opening 64,000 NZD, closing 72,000 NZD -> FDR = 5% * 64,000 = 3,200; CV = 8,000 -> picks FDR
    assert result.iloc[0] == pytest.approx(64_000.0)
    assert result.iloc[-1] == pytest.approx(72_000.0 - 3_200.0)


def test_apply_nz_costs_under_threshold_leaves_equity_untouched_besides_fx():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([1_000.0, 1_100.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.5, "2024-01-02": 1.5})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000)

    result = apply_nz_costs(equity_usd, fake_fx, calc, fx_fee_pct=0.01)

    assert result.iloc[0] == pytest.approx(1_000.0 * 1.5 * 0.99)
    assert result.iloc[-1] == pytest.approx(1_100.0 * 1.5 * 0.99)
