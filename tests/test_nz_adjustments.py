import pandas as pd
import pytest

from backtester.nz_adjustments import (
    apply_fx_fee,
    convert_equity_curve_to_nzd,
    estimate_fif_tax_drag,
    net_return_nzd,
    prepare_metrics_curve,
)
from nz_tax_fx.fif_calculator import FIFCalculator


class FakeFX:
    """rates: dict[date-iso-string, float]. get_rate/convert_to_nzd look up by date;
    get_rate(None) (no as_of) returns the latest entry, matching real FXConverter.
    """

    def __init__(self, rates: dict):
        self.rates = rates

    def get_rate(self, as_of=None):
        if as_of is None:
            return list(self.rates.values())[-1]
        return self.rates[as_of.isoformat()]

    def convert_to_nzd(self, amount_usd, as_of=None):
        return amount_usd * self.get_rate(as_of)


def test_convert_equity_curve_to_nzd_uses_a_single_fixed_rate():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    equity_usd = pd.Series([100.0, 200.0, 300.0], index=idx)
    fake_fx = FakeFX({"2024-01-03": 1.7})  # only the end date's rate should be used

    equity_nzd = convert_equity_curve_to_nzd(equity_usd, fake_fx)

    # every value scaled by the SAME rate (1.7) — not a different rate per day
    assert list(equity_nzd) == pytest.approx([170.0, 340.0, 510.0])


def test_convert_equity_curve_to_nzd_preserves_pct_returns_exactly():
    # the whole point of the fix: a constant-factor conversion must not introduce any
    # volatility of its own — % returns before and after conversion must match exactly.
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    equity_usd = pd.Series([100.0, 105.0, 98.0, 110.0, 108.0], index=idx)
    fake_fx = FakeFX({"2024-01-05": 1.65})

    equity_nzd = convert_equity_curve_to_nzd(equity_usd, fake_fx)

    usd_returns = equity_usd.pct_change().dropna()
    nzd_returns = equity_nzd.pct_change().dropna()
    assert list(nzd_returns) == pytest.approx(list(usd_returns))


def test_apply_fx_fee_reduces_equity_by_flat_pct():
    equity = pd.Series([100.0, 200.0])
    result = apply_fx_fee(equity, fx_fee_pct=0.01)
    assert list(result) == pytest.approx([99.0, 198.0])


def test_estimate_fif_tax_drag_under_threshold_is_zero():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([1_000.0, 1_100.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.6, "2024-01-02": 1.6})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000)

    assert estimate_fif_tax_drag(equity_usd, fake_fx, calc) == 0.0


def test_estimate_fif_tax_drag_uses_each_dates_own_rate():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([40_000.0, 40_000.0], index=idx)  # no USD gain at all
    # but the FX rate itself moved a lot between the two dates -> a real NZD-denominated
    # gain/loss under CV, exactly as real NZ tax law would assess it
    fake_fx = FakeFX({"2024-01-01": 1.5, "2024-01-02": 1.8})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000, marginal_tax_rate=1.0)

    # opening 60,000 NZD, closing 72,000 NZD -> FDR = 5%*60,000 = 3,000; CV = 12,000 -> FDR wins
    assert estimate_fif_tax_drag(equity_usd, fake_fx, calc) == pytest.approx(3_000.0)


def test_estimate_fif_tax_drag_applies_marginal_tax_rate():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([40_000.0, 40_000.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.5, "2024-01-02": 1.8})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000, marginal_tax_rate=0.33)

    assert estimate_fif_tax_drag(equity_usd, fake_fx, calc) == pytest.approx(3_000.0 * 0.33)


def test_estimate_fif_tax_drag_empty_series_is_zero():
    fake_fx = FakeFX({"2024-01-01": 1.6})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000)
    assert estimate_fif_tax_drag(pd.Series(dtype=float), fake_fx, calc) == 0.0


def test_prepare_metrics_curve_matches_usd_returns_exactly():
    # prepare_metrics_curve must never distort the return series (no daily FX noise, no
    # tax baked in) — this is the curve Sharpe/MaxDD/ProfitFactor are computed from.
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    equity_usd = pd.Series([100_000.0, 100_010.0, 99_995.0, 100_020.0, 100_015.0], index=idx)
    fake_fx = FakeFX(
        {
            "2024-01-01": 1.5,
            "2024-01-02": 1.9,  # large swings that would dominate a daily-rate conversion
            "2024-01-03": 1.2,
            "2024-01-04": 1.8,
            "2024-01-05": 1.6,
        }
    )

    result = prepare_metrics_curve(equity_usd, fake_fx, fx_fee_pct=0.0)

    usd_returns = equity_usd.pct_change().dropna()
    nzd_returns = result.pct_change().dropna()
    assert list(nzd_returns) == pytest.approx(list(usd_returns))


def test_prepare_metrics_curve_flat_strategy_has_zero_median_move_preserved():
    # regression test for the second bug: a mostly-flat strategy's near-all-zero daily
    # moves must stay exactly zero — no constant per-day tax drag leaking in anymore.
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    equity_usd = pd.Series([100_000.0] * 9 + [100_050.0], index=idx)  # one real move, at the end
    fake_fx = FakeFX({d.date().isoformat(): 1.6 for d in idx})

    result = prepare_metrics_curve(equity_usd, fake_fx, fx_fee_pct=0.0)

    changes = result.diff().dropna()
    assert (changes.iloc[:-1] == 0).all()  # every day except the real move is exactly flat


def test_net_return_nzd_subtracts_tax_from_the_fee_adjusted_gain():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([40_000.0, 45_000.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.6, "2024-01-02": 1.6})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000, marginal_tax_rate=0.33)

    result = net_return_nzd(equity_usd, fake_fx, calc, fx_fee_pct=0.0)

    # gross NZD gain (single fixed rate 1.6): 72,000 - 64,000 = 8,000
    # FDR assessable = 5%*64,000=3,200, taxed at .33=1,056; CV assessable=8,000, taxed at .33=2,640
    # -> FDR (1,056) is lower and wins
    assert result == pytest.approx(8_000.0 - 1_056.0)


def test_net_return_nzd_under_threshold_has_no_tax_drag():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    equity_usd = pd.Series([1_000.0, 1_100.0], index=idx)
    fake_fx = FakeFX({"2024-01-01": 1.5, "2024-01-02": 1.5})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000)

    result = net_return_nzd(equity_usd, fake_fx, calc, fx_fee_pct=0.01)

    assert result == pytest.approx((1_100.0 - 1_000.0) * 1.5 * 0.99)


def test_net_return_nzd_empty_series_is_zero():
    fake_fx = FakeFX({"2024-01-01": 1.6})
    calc = FIFCalculator(fx_converter=fake_fx, threshold_nzd=50_000)
    assert net_return_nzd(pd.Series(dtype=float), fake_fx, calc, fx_fee_pct=0.0) == 0.0
