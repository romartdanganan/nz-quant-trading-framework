"""Generates a per-NZ-tax-year (1 April - 31 March) summary: FIF liability and net
after-tax return in NZD. NOT TAX ADVICE — decision-support only, see fif_calculator.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from config.settings import settings
from nz_tax_fx.fif_calculator import FIFCalculator, FIFTaxResult, Holding


def tax_year_bounds(as_of: date) -> tuple[date, date]:
    """NZ tax year runs 1 April - 31 March."""
    year_start = as_of.year if as_of.month >= 4 else as_of.year - 1
    return date(year_start, 4, 1), date(year_start + 1, 3, 31)


@dataclass(frozen=True)
class TaxYearReport:
    tax_year_start: date
    tax_year_end: date
    fif_result: FIFTaxResult
    gross_return_nzd: float
    net_return_nzd: float


def generate_report(
    holdings: list[Holding],
    opening_value_nzd: float,
    closing_value_nzd: float,
    purchases_nzd: float,
    sales_nzd: float,
    dividends_nzd: float,
    as_of: date,
    calculator: FIFCalculator | None = None,
    fif_method: str = "auto",
) -> TaxYearReport:
    calculator = calculator or FIFCalculator(marginal_tax_rate=settings.get("nz_tax.marginal_tax_rate", 0.33))
    tax_year_start, tax_year_end = tax_year_bounds(as_of)

    fif_result = calculator.assess(
        holdings,
        opening_value_nzd,
        closing_value_nzd,
        purchases_nzd,
        sales_nzd,
        dividends_nzd,
        method=fif_method,
    )

    gross_return_nzd = closing_value_nzd - opening_value_nzd - purchases_nzd + sales_nzd + dividends_nzd
    net_return_nzd = gross_return_nzd - fif_result.recommended_tax_nzd

    return TaxYearReport(
        tax_year_start=tax_year_start,
        tax_year_end=tax_year_end,
        fif_result=fif_result,
        gross_return_nzd=gross_return_nzd,
        net_return_nzd=net_return_nzd,
    )
