from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CountryTaxRulePack:
    country_code: str
    tax_year: int
    version: str
    status: str
    dividend_final_rate: Decimal
    domestic_bank_interest_final_rate: Decimal
    local_withholding_short_gain_rate: Decimal
    local_withholding_long_gain_rate: Decimal
    local_long_term_days: int
    annual_self_assessment_gain_rate: Decimal
    cass_rate: Decimal
    cass_threshold_wages: tuple[int, int, int]
    source_urls: tuple[str, ...]
    limitations: tuple[str, ...]


ROMANIA_2026 = CountryTaxRulePack(
    country_code="RO",
    tax_year=2026,
    version="RO-2026.partial.1",
    status="partial",
    dividend_final_rate=Decimal("0.16"),
    domestic_bank_interest_final_rate=Decimal("0.10"),
    local_withholding_short_gain_rate=Decimal("0.06"),
    local_withholding_long_gain_rate=Decimal("0.03"),
    local_long_term_days=365,
    annual_self_assessment_gain_rate=Decimal("0.16"),
    cass_rate=Decimal("0.10"),
    cass_threshold_wages=(6, 12, 24),
    source_urls=(
        "https://legislatie.just.ro/Public/DetaliiDocument/300022",
        "https://legislatie.just.ro/Public/DetaliiDocument/305208",
        "https://legislatie.just.ro/Public/DetaliiDocument/171282",
    ),
    limitations=(
        "Foreign dividend withholding and treaty credits are not calculated.",
        "The annual self-assessment capital-gains estimate does not net transactions or losses "
        "across the tax year.",
        "CASS requires annual realized-income aggregation and the official minimum wage for "
        "the tax year; it is not included in per-holding estimates.",
        "RSU, stock-option, and ESPP taxation remains an explicit grant/plan assumption until "
        "the user's employment and plan facts are modelled.",
        "Unrealized holdings use the tracked average cost as one approximate tax lot.",
    ),
)

COUNTRY_TAX_RULES: dict[tuple[str, int], CountryTaxRulePack] = {
    (ROMANIA_2026.country_code, ROMANIA_2026.tax_year): ROMANIA_2026,
}


def get_country_tax_rules(
    country_code: str | None, tax_year: int | None
) -> CountryTaxRulePack | None:
    if country_code is None or tax_year is None:
        return None
    return COUNTRY_TAX_RULES.get((country_code.strip().upper(), tax_year))


def country_rule_status(country_code: str | None, tax_year: int | None) -> str:
    if country_code is None or tax_year is None:
        return "not_configured"
    pack = get_country_tax_rules(country_code, tax_year)
    return pack.status if pack is not None else "unsupported"
