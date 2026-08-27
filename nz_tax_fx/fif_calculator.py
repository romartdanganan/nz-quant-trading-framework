"""Tracks foreign equity cost basis (NZD) against the FIF de minimis threshold and computes
projected tax under the Fair Dividend Rate (FDR) and Comparative Value (CV) methods.

NOT TAX ADVICE — decision-support only (see CLAUDE.md "NZ tax & timezone rules": the same
AI/tooling-assists, human-verifies principle that applies to trading signals applies here).
This is a simplified model for backtesting/validation net-of-tax return estimates; it does
not handle every IRD edge case (e.g. quick-sale adjustments, attributing interest
exclusions). Verify actual filings with a qualified tax professional or the IRD.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from nz_tax_fx.fx_converter import FXConverter


@dataclass(frozen=True)
class Holding:
    ticker: str
    shares: float
    cost_basis_usd: float
    purchase_date: date


@dataclass(frozen=True)
class FIFTaxResult:
    total_cost_nzd: float
    exceeds_threshold: bool
    fdr_tax_nzd: float
    cv_tax_nzd: float | None
    recommended_method: str  # "fdr" | "cv" | "none"
    recommended_tax_nzd: float


class FIFCalculator:
    def __init__(
        self,
        fx_converter: FXConverter | None = None,
        threshold_nzd: float = 50_000.0,
        fdr_rate: float = 0.05,
    ):
        self.fx = fx_converter or FXConverter()
        self.threshold_nzd = threshold_nzd
        self.fdr_rate = fdr_rate

    def total_cost_nzd(self, holdings: list[Holding]) -> float:
        return sum(
            self.fx.convert_to_nzd(holding.cost_basis_usd, holding.purchase_date)
            for holding in holdings
        )

    def calculate_fdr_tax(self, opening_value_nzd: float) -> float:
        return max(0.0, opening_value_nzd) * self.fdr_rate

    def calculate_cv_tax(
        self,
        opening_value_nzd: float,
        closing_value_nzd: float,
        purchases_nzd: float,
        sales_nzd: float,
        dividends_nzd: float,
    ) -> float:
        taxable_gain = (
            (closing_value_nzd - opening_value_nzd) - purchases_nzd + sales_nzd + dividends_nzd
        )
        return max(0.0, taxable_gain)

    def assess(
        self,
        holdings: list[Holding],
        opening_value_nzd: float,
        closing_value_nzd: float,
        purchases_nzd: float,
        sales_nzd: float,
        dividends_nzd: float,
        method: str = "auto",
    ) -> FIFTaxResult:
        total_cost = self.total_cost_nzd(holdings)
        exceeds = total_cost > self.threshold_nzd

        if not exceeds:
            return FIFTaxResult(total_cost, False, 0.0, None, "none", 0.0)

        fdr_tax = self.calculate_fdr_tax(opening_value_nzd)
        cv_tax = self.calculate_cv_tax(
            opening_value_nzd, closing_value_nzd, purchases_nzd, sales_nzd, dividends_nzd
        )

        if method == "fdr":
            chosen_method, chosen_tax = "fdr", fdr_tax
        elif method == "cv":
            chosen_method, chosen_tax = "cv", cv_tax
        elif cv_tax < fdr_tax:
            chosen_method, chosen_tax = "cv", cv_tax
        else:
            chosen_method, chosen_tax = "fdr", fdr_tax

        return FIFTaxResult(total_cost, True, fdr_tax, cv_tax, chosen_method, chosen_tax)
