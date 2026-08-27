from datetime import date

from nz_tax_fx.fif_calculator import FIFCalculator, Holding
from nz_tax_fx.tax_report import generate_report, tax_year_bounds


class FakeFX:
    def convert_to_nzd(self, amount_usd, as_of=None):
        return amount_usd * 1.6


def test_tax_year_bounds_after_april_starts_same_calendar_year():
    start, end = tax_year_bounds(date(2026, 8, 28))
    assert start == date(2026, 4, 1)
    assert end == date(2027, 3, 31)


def test_tax_year_bounds_before_april_starts_previous_calendar_year():
    start, end = tax_year_bounds(date(2026, 2, 1))
    assert start == date(2025, 4, 1)
    assert end == date(2026, 3, 31)


def test_generate_report_net_return_subtracts_recommended_tax():
    calc = FIFCalculator(fx_converter=FakeFX(), threshold_nzd=50_000)
    holdings = [Holding("AAPL", 1_000, 40_000, date(2025, 4, 1))]

    report = generate_report(
        holdings,
        opening_value_nzd=60_000,
        closing_value_nzd=66_000,
        purchases_nzd=0,
        sales_nzd=0,
        dividends_nzd=0,
        as_of=date(2026, 3, 15),
        calculator=calc,
    )

    assert report.fif_result.exceeds_threshold is True
    assert report.gross_return_nzd == 6_000.0
    assert report.net_return_nzd == report.gross_return_nzd - report.fif_result.recommended_tax_nzd
    assert report.tax_year_start == date(2025, 4, 1)
    assert report.tax_year_end == date(2026, 3, 31)


def test_generate_report_under_threshold_has_no_tax_drag():
    calc = FIFCalculator(fx_converter=FakeFX(), threshold_nzd=50_000)
    holdings = [Holding("AAPL", 10, 1_000, date(2025, 4, 1))]

    report = generate_report(
        holdings,
        opening_value_nzd=1_500,
        closing_value_nzd=1_800,
        purchases_nzd=0,
        sales_nzd=0,
        dividends_nzd=0,
        as_of=date(2026, 1, 1),
        calculator=calc,
    )

    assert report.fif_result.exceeds_threshold is False
    assert report.net_return_nzd == report.gross_return_nzd
