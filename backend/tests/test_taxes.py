from datetime import date
from decimal import Decimal

import pytest

from app.taxes.engine import (
    estimate_capital_gain_tax,
    estimate_income_tax,
    estimate_ro_cass,
)
from app.taxes.rules import country_rule_status, get_country_tax_rules


def test_rule_registry_only_marks_the_verified_country_year_as_partial() -> None:
    rules = get_country_tax_rules("ro", 2026)

    assert rules is not None
    assert rules.status == "partial"
    assert rules.version == "RO-2026.partial.1"
    assert country_rule_status("RO", 2026) == "partial"
    assert get_country_tax_rules("US", 2026) is None
    assert country_rule_status("US", 2026) == "unsupported"


@pytest.mark.parametrize(
    ("acquired_on", "expected_rate"),
    [
        (date(2025, 12, 1), Decimal("0.06")),
        (date(2025, 1, 1), Decimal("0.03")),
    ],
)
def test_romania_withholding_uses_holding_period_rate_and_discloses_lot_limit(
    acquired_on: date, expected_rate: Decimal
) -> None:
    estimate = estimate_capital_gain_tax(
        gross_proceeds=Decimal("200"),
        cost_basis=Decimal("100"),
        acquired_on=acquired_on,
        sold_on=date(2026, 10, 14),
        country_code="RO",
        tax_year=2026,
        intermediary_country_code="RO",
        reporting_method="withholding_agent",
        manual_rate=None,
        legacy_rate=Decimal("0.10"),
    )

    assert estimate.status == "country_rule_estimate"
    assert estimate.rate == expected_rate
    assert estimate.tax_amount == Decimal("6.00" if expected_rate == Decimal("0.06") else "3.00")
    assert estimate.rule_version == "RO-2026.partial.1"
    assert any("one tax lot" in warning for warning in estimate.warnings)


def test_local_withholding_rule_requires_a_matching_intermediary_country() -> None:
    estimate = estimate_capital_gain_tax(
        gross_proceeds=Decimal("200"),
        cost_basis=Decimal("100"),
        acquired_on=date(2025, 1, 1),
        sold_on=date(2026, 10, 14),
        country_code="RO",
        tax_year=2026,
        intermediary_country_code="US",
        reporting_method="withholding_agent",
        manual_rate=None,
        legacy_rate=Decimal("0.10"),
    )

    assert estimate.status == "legacy_assumption"
    assert estimate.rate == Decimal("0.10")
    assert estimate.rule_version is None
    assert any("matching intermediary country" in warning for warning in estimate.warnings)


def test_annual_self_assessment_is_labeled_as_a_position_level_estimate() -> None:
    estimate = estimate_capital_gain_tax(
        gross_proceeds=Decimal("200"),
        cost_basis=Decimal("100"),
        acquired_on=date(2025, 1, 1),
        sold_on=date(2026, 10, 14),
        country_code="RO",
        tax_year=2026,
        reporting_method="annual_self_assessment",
        manual_rate=None,
        legacy_rate=Decimal("0.10"),
    )

    assert estimate.rate == Decimal("0.16")
    assert estimate.tax_amount == Decimal("16.00")
    assert estimate.status == "country_rule_estimate"
    assert any("annual gains, losses" in warning for warning in estimate.warnings)


def test_manual_override_does_not_claim_official_rule_sources() -> None:
    estimate = estimate_capital_gain_tax(
        gross_proceeds=Decimal("200"),
        cost_basis=Decimal("100"),
        acquired_on=date(2025, 1, 1),
        sold_on=date(2026, 10, 14),
        country_code="RO",
        tax_year=2026,
        reporting_method="legacy_manual",
        manual_rate=Decimal("0.07"),
        legacy_rate=Decimal("0.10"),
    )

    assert estimate.status == "manual_override"
    assert estimate.rate == Decimal("0.07")
    assert estimate.rule_version is None
    assert estimate.source_urls == ()


def test_unsupported_country_uses_an_explicit_legacy_assumption() -> None:
    estimate = estimate_capital_gain_tax(
        gross_proceeds=Decimal("200"),
        cost_basis=Decimal("100"),
        acquired_on=date(2025, 1, 1),
        sold_on=date(2026, 10, 14),
        country_code="US",
        tax_year=2026,
        reporting_method="annual_self_assessment",
        manual_rate=None,
        legacy_rate=Decimal("0.10"),
    )

    assert estimate.status == "legacy_assumption"
    assert estimate.rate == Decimal("0.10")
    assert estimate.rule_version is None
    assert any("US/2026" in warning for warning in estimate.warnings)


def test_tax_exempt_account_has_no_estimated_tax() -> None:
    estimate = estimate_capital_gain_tax(
        gross_proceeds=Decimal("200"),
        cost_basis=Decimal("100"),
        acquired_on=date(2025, 1, 1),
        sold_on=date(2026, 10, 14),
        country_code="RO",
        tax_year=2026,
        reporting_method="tax_exempt",
        manual_rate=None,
        legacy_rate=Decimal("0.10"),
    )

    assert estimate.status == "tax_exempt"
    assert estimate.rate == Decimal("0")
    assert estimate.tax_amount == Decimal("0")
    assert estimate.net_amount == Decimal("200")
    assert estimate.rule_version is None
    assert estimate.source_urls == ()


@pytest.mark.parametrize(
    ("event_type", "expected_rate"),
    [
        ("dividend", Decimal("0.16")),
        ("interest", Decimal("0.10")),
    ],
)
def test_romania_domestic_investment_income_uses_event_specific_rule(
    event_type: str, expected_rate: Decimal
) -> None:
    estimate = estimate_income_tax(
        event_type=event_type,
        gross_amount=Decimal("100"),
        country_code="RO",
        tax_year=2026,
        source_country_code="RO",
        reporting_method="withholding_agent",
        legacy_rate=Decimal("0.05"),
    )

    assert estimate.status == "country_rule_estimate"
    assert estimate.rate == expected_rate
    assert estimate.tax_amount == expected_rate * Decimal("100")
    assert estimate.rule_version == "RO-2026.partial.1"


def test_foreign_dividend_is_not_misrepresented_as_a_romanian_rule_estimate() -> None:
    estimate = estimate_income_tax(
        event_type="dividend",
        gross_amount=Decimal("100"),
        country_code="RO",
        tax_year=2026,
        source_country_code="US",
        reporting_method="withholding_agent",
        legacy_rate=Decimal("0.05"),
    )

    assert estimate.status == "legacy_assumption"
    assert estimate.rate == Decimal("0.05")
    assert estimate.rule_version is None
    assert estimate.source_urls == ()
    assert any("treaty credits" in warning for warning in estimate.warnings)


@pytest.mark.parametrize(
    ("annual_income", "expected_tax"),
    [
        (Decimal("23999.99"), Decimal("0.00")),
        (Decimal("24000"), Decimal("2400.00")),
        (Decimal("48000"), Decimal("4800.00")),
        (Decimal("96000"), Decimal("9600.00")),
    ],
)
def test_romania_cass_uses_six_twelve_and_twenty_four_wage_bases(
    annual_income: Decimal, expected_tax: Decimal
) -> None:
    estimate = estimate_ro_cass(
        annual_qualifying_investment_income=annual_income,
        minimum_monthly_wage=Decimal("4000"),
        country_code="ro",
        tax_year=2026,
    )

    assert estimate.status == "country_rule_estimate"
    assert estimate.tax_amount == expected_tax


def test_cass_uses_the_rule_pack_minimum_wage_without_a_manual_override() -> None:
    estimate = estimate_ro_cass(
        annual_qualifying_investment_income=Decimal("30000"),
        minimum_monthly_wage=None,
        country_code="RO",
        tax_year=2026,
    )

    assert estimate.status == "country_rule_estimate"
    assert estimate.taxable_amount == Decimal("24300")
    assert estimate.tax_amount == Decimal("2430.00")
    assert any("minimum wage applicable" in warning for warning in estimate.warnings)
