from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.taxes.rules import get_country_tax_rules

ZERO = Decimal("0")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class TaxEstimate:
    event_type: str
    status: str
    gross_amount: Decimal
    cost_basis: Decimal
    taxable_amount: Decimal
    rate: Decimal | None
    tax_amount: Decimal | None
    net_amount: Decimal | None
    rule_version: str | None
    source_urls: tuple[str, ...]
    warnings: tuple[str, ...]


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def estimate_capital_gain_tax(
    *,
    gross_proceeds: Decimal,
    cost_basis: Decimal,
    acquired_on: date,
    sold_on: date,
    country_code: str | None,
    tax_year: int | None,
    intermediary_country_code: str | None = None,
    reporting_method: str,
    manual_rate: Decimal | None,
    legacy_rate: Decimal,
    tax_exempt: bool = False,
) -> TaxEstimate:
    gain = gross_proceeds - cost_basis
    taxable_gain = max(ZERO, gain)
    pack = get_country_tax_rules(country_code, tax_year)
    method = reporting_method.strip().lower()
    if tax_exempt or method == "tax_exempt":
        return TaxEstimate(
            "capital_gain",
            "tax_exempt",
            gross_proceeds,
            cost_basis,
            ZERO,
            ZERO,
            ZERO,
            gross_proceeds,
            None,
            (),
            (),
        )

    if manual_rate is not None and method == "legacy_manual":
        rate = manual_rate
        status = "manual_override"
        sources = ()
        warning = (
            "A per-holding manual rate overrides the country rule pack."
            if pack is not None
            else "A per-holding manual rate is being used because no supported country rule "
            "pack applies."
        )
        warnings = (warning,)
    else:
        intermediary_country = (
            intermediary_country_code.strip().upper()
            if intermediary_country_code is not None
            else None
        )
        if (
            pack is not None
            and method == "withholding_agent"
            and intermediary_country == pack.country_code
        ):
            holding_days = (sold_on - acquired_on).days
            rate = (
                pack.local_withholding_long_gain_rate
                if holding_days >= pack.local_long_term_days
                else pack.local_withholding_short_gain_rate
            )
            status = "country_rule_estimate"
            sources = pack.source_urls
            warnings = (
                "Gain and holding period use the tracked average cost and purchase date as one "
                "tax lot; this is not FIFO lot accounting.",
            )
        elif pack is not None and method == "withholding_agent":
            rate = manual_rate if manual_rate is not None else legacy_rate
            status = "legacy_assumption"
            sources = ()
            warnings = (
                f"The broker country is {intermediary_country or 'unknown'}; the "
                f"{pack.country_code} local-withholding rate is not applied without a "
                "matching intermediary country.",
            )
        elif pack is not None and method == "annual_self_assessment":
            rate = pack.annual_self_assessment_gain_rate
            status = "country_rule_estimate"
            sources = pack.source_urls
            warnings = (
                "This per-position estimate does not aggregate the user's annual gains, losses, "
                "allowances, or tax credits.",
            )
        else:
            rate = manual_rate if manual_rate is not None else legacy_rate
            status = "legacy_assumption"
            sources = ()
            if country_code is not None and tax_year is not None and pack is None:
                message = (
                    f"No built-in capital-gains rules support {country_code}/{tax_year}; "
                    "the legacy/manual estimate is not country-specific."
                )
            else:
                message = (
                    "No applicable country rule was selected for this account; the "
                    "legacy/manual capital-gains estimate is being used."
                )
            warnings = (message,)

    tax = _rounded(taxable_gain * rate)
    return TaxEstimate(
        "capital_gain",
        status,
        gross_proceeds,
        cost_basis,
        taxable_gain,
        rate,
        tax,
        gross_proceeds - tax,
        pack.version if pack is not None and status == "country_rule_estimate" else None,
        sources,
        warnings,
    )


def estimate_income_tax(
    *,
    event_type: str,
    gross_amount: Decimal,
    country_code: str | None,
    tax_year: int | None,
    source_country_code: str | None,
    reporting_method: str,
    legacy_rate: Decimal,
    tax_exempt: bool = False,
) -> TaxEstimate:
    if tax_exempt or reporting_method.strip().lower() == "tax_exempt":
        return TaxEstimate(
            event_type,
            "tax_exempt",
            gross_amount,
            ZERO,
            ZERO,
            ZERO,
            ZERO,
            gross_amount,
            None,
            (),
            (),
        )

    pack = get_country_tax_rules(country_code, tax_year)
    source_country = (
        source_country_code.strip().upper() if source_country_code is not None else None
    )
    residence = country_code.strip().upper() if country_code is not None else None

    if pack is not None and event_type == "dividend" and source_country == "RO":
        rate = pack.dividend_final_rate
        status = "country_rule_estimate"
        warnings = ()
        source_urls = pack.source_urls
    elif pack is not None and event_type == "interest" and source_country == "RO":
        rate = pack.domestic_bank_interest_final_rate
        status = "country_rule_estimate"
        warnings = ()
        source_urls = pack.source_urls
    elif pack is not None and source_country not in (None, residence):
        rate = legacy_rate
        status = "legacy_assumption"
        warnings = (
            "Source-country withholding and treaty credits are not in this rule pack; the "
            "legacy/manual rate is not a cross-border tax determination.",
        )
        source_urls = ()
    elif pack is not None and source_country is None:
        rate = legacy_rate
        status = "legacy_assumption"
        warnings = (
            "The asset's tax domicile is unknown; the legacy/manual rate is shown as an "
            "estimate, not a country-specific result.",
        )
        source_urls = ()
    else:
        rate = legacy_rate
        status = "legacy_assumption"
        if country_code is not None and tax_year is not None and pack is None:
            warning = (
                f"No built-in income-tax rules support {country_code}/{tax_year}; the "
                "legacy/manual estimate is not country-specific."
            )
        else:
            warning = (
                "No applicable country rule was selected; the legacy/manual income-tax "
                "estimate is being used."
            )
        warnings = (warning,)
        source_urls = ()

    tax = _rounded(gross_amount * rate)
    return TaxEstimate(
        event_type,
        status,
        gross_amount,
        ZERO,
        gross_amount,
        rate,
        tax,
        gross_amount - tax,
        pack.version if pack is not None and status == "country_rule_estimate" else None,
        source_urls,
        warnings,
    )


def estimate_country_cass(
    *,
    annual_qualifying_investment_income: Decimal,
    minimum_monthly_wage: Decimal | None,
    country_code: str | None,
    tax_year: int | None,
) -> TaxEstimate:
    pack = get_country_tax_rules(country_code, tax_year)
    if pack is None:
        return TaxEstimate(
            "cass",
            "unsupported",
            annual_qualifying_investment_income,
            ZERO,
            ZERO,
            None,
            None,
            None,
            pack.version if pack else None,
            pack.source_urls if pack else (),
            ("No supported CASS rule pack is available for this country and tax year.",),
        )
    applied_minimum_wage = (
        minimum_monthly_wage
        if minimum_monthly_wage is not None
        else pack.minimum_monthly_wage_at_year_start
    )
    if applied_minimum_wage is None or applied_minimum_wage <= ZERO:
        return TaxEstimate(
            "cass",
            "incomplete",
            annual_qualifying_investment_income,
            ZERO,
            ZERO,
            pack.cass_rate,
            None,
            None,
            pack.version,
            pack.source_urls,
            (
                "Enter the statutory minimum gross monthly wage applicable on 1 January of "
                "the tax year and aggregate realized eligible income before calculating CASS.",
            ),
        )

    threshold_bases = sorted(
        {applied_minimum_wage * multiple for multiple in pack.cass_threshold_wages}
    )
    if not threshold_bases:
        return TaxEstimate(
            "cass",
            "unsupported",
            annual_qualifying_investment_income,
            ZERO,
            ZERO,
            None,
            None,
            None,
            pack.version,
            pack.source_urls,
            ("The country rule pack does not define CASS income thresholds.",),
        )
    taxable_base = max(
        (
            threshold
            for threshold in threshold_bases
            if annual_qualifying_investment_income >= threshold
        ),
        default=ZERO,
    )
    tax = _rounded(taxable_base * pack.cass_rate)
    return TaxEstimate(
        "cass",
        "country_rule_estimate",
        annual_qualifying_investment_income,
        ZERO,
        taxable_base,
        pack.cass_rate,
        tax,
        annual_qualifying_investment_income - tax,
        pack.version,
        pack.source_urls,
        (
            "CASS is only an estimate until all taxable income categories and exemptions for "
            "the tax year are included.",
            (
                "The country pack's minimum wage applicable on 1 January was used."
                if minimum_monthly_wage is None
                else "A user-entered minimum wage overrides the country pack value."
            ),
        ),
    )


estimate_ro_cass = estimate_country_cass
