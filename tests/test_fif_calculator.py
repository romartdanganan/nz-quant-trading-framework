from datetime import date

import pytest

from nz_tax_fx.fif_calculator import FIFCalculator, Holding


class FakeFX:
    def __init__(self, rate: float = 1.6):
        self.rate = rate

    def convert_to_nzd(self, amount_usd, as_of=None):
        return amount_usd * self.rate


def test_under_threshold_no_tax():
    calc = FIFCalculator(fx_converter=FakeFX(rate=1.6), threshold_nzd=50_000)
    holdings = [Holding("AAPL", 10, 1_000, date(2024, 1, 1))]  # 1,000 * 1.6 = 1,600 NZD

    result = calc.assess(
        holdings, opening_value_nzd=1_500, closing_value_nzd=1_600,
        purchases_nzd=0, sales_nzd=0, dividends_nzd=0,
    )

    assert result.exceeds_threshold is False
    assert result.recommended_method == "none"
    assert result.recommended_tax_nzd == 0.0


def test_over_threshold_auto_picks_lower_of_fdr_and_cv():
    # marginal_tax_rate=1.0 isolates the FDR-vs-CV assessable-income comparison from the
    # rate multiplier itself, which has its own dedicated test below.
    calc = FIFCalculator(fx_converter=FakeFX(rate=1.6), threshold_nzd=50_000, marginal_tax_rate=1.0)
    holdings = [Holding("AAPL", 1_000, 40_000, date(2024, 1, 1))]  # 64,000 NZD > threshold

    result = calc.assess(
        holdings, opening_value_nzd=60_000, closing_value_nzd=61_000,  # small actual gain
        purchases_nzd=0, sales_nzd=0, dividends_nzd=0,
    )

    assert result.exceeds_threshold is True
    assert result.fdr_tax_nzd == 3_000.0  # 5% of 60,000
    assert result.cv_tax_nzd == 1_000.0   # 61,000 - 60,000
    assert result.recommended_method == "cv"
    assert result.recommended_tax_nzd == 1_000.0


def test_forced_fdr_method_ignores_cv():
    calc = FIFCalculator(fx_converter=FakeFX(rate=1.6), threshold_nzd=50_000, marginal_tax_rate=1.0)
    holdings = [Holding("AAPL", 1_000, 40_000, date(2024, 1, 1))]

    result = calc.assess(
        holdings, opening_value_nzd=60_000, closing_value_nzd=61_000,
        purchases_nzd=0, sales_nzd=0, dividends_nzd=0, method="fdr",
    )

    assert result.recommended_method == "fdr"
    assert result.recommended_tax_nzd == 3_000.0


def test_marginal_tax_rate_is_applied_to_assessable_income():
    # the actual bug this guards against: assessable income (5% of opening value, or the
    # real gain) must be taxed at the investor's marginal rate, not treated as the tax
    # itself — that would be an implicit (and wrong) 100% tax rate.
    calc = FIFCalculator(fx_converter=FakeFX(rate=1.6), threshold_nzd=50_000, marginal_tax_rate=0.33)
    holdings = [Holding("AAPL", 1_000, 40_000, date(2024, 1, 1))]

    result = calc.assess(
        holdings, opening_value_nzd=60_000, closing_value_nzd=61_000,
        purchases_nzd=0, sales_nzd=0, dividends_nzd=0, method="fdr",
    )

    assert result.fdr_tax_nzd == pytest.approx(3_000.0 * 0.33)
    assert result.recommended_tax_nzd < 3_000.0  # never the full assessable income


def test_cv_tax_floors_at_zero_on_a_loss():
    calc = FIFCalculator(fx_converter=FakeFX(rate=1.6), threshold_nzd=50_000)
    holdings = [Holding("AAPL", 1_000, 40_000, date(2024, 1, 1))]

    result = calc.assess(
        holdings, opening_value_nzd=60_000, closing_value_nzd=40_000,  # big loss
        purchases_nzd=0, sales_nzd=0, dividends_nzd=0,
    )

    assert result.cv_tax_nzd == 0.0
    assert result.recommended_method == "cv"
    assert result.recommended_tax_nzd == 0.0


def test_total_cost_nzd_converts_each_holding_at_its_own_purchase_date_rate():
    class VaryingFX:
        def convert_to_nzd(self, amount_usd, as_of=None):
            return amount_usd * (1.5 if as_of == date(2023, 1, 1) else 1.7)

    calc = FIFCalculator(fx_converter=VaryingFX())
    holdings = [
        Holding("AAPL", 100, 10_000, date(2023, 1, 1)),
        Holding("MSFT", 50, 10_000, date(2024, 1, 1)),
    ]

    assert calc.total_cost_nzd(holdings) == 10_000 * 1.5 + 10_000 * 1.7
