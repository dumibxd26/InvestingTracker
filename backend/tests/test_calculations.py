from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.calculations import (
    compound_growth_factor,
    compound_value_over_years,
    convert_currency,
    fixed_deposit_value,
    generate_vesting_schedule,
    project_to_simplex,
    rebalance_with_contribution,
    required_monthly_contribution,
    route_funding_to_goals,
)
from app.cash_flow_logic import occurrence_dates
from app.models import CompoundingFrequency, FundingRule, RateBasis, Recurrence

D = Decimal


def test_compound_growth_factor_preserves_partial_year_precision() -> None:
    factor = compound_growth_factor(D("0.05"), D("0.5"))
    assert D("1.024") < factor < D("1.025")
    assert compound_value_over_years(D("1000"), D("0.05"), D("1")) == D("1050.00")


@dataclass(eq=False)
class GoalStub:
    name: str
    monthly_contribution: Decimal = D("0")
    current_amount: Decimal = D("0")
    target_amount: Decimal | None = None
    target_date: date | None = None
    fixed_percent: Decimal | None = None
    is_active: bool = True


def test_water_filling_corrects_underweight_buckets_without_selling() -> None:
    values = {
        "equities": D("80000"),
        "fixed_income": D("10000"),
        "satellite": D("10000"),
    }
    targets = {"equities": D("0.70"), "fixed_income": D("0.15"), "satellite": D("0.15")}

    allocations = rebalance_with_contribution(values, targets, D("10000"))

    assert allocations == {
        "equities": D("0"),
        "fixed_income": D("5000"),
        "satellite": D("5000"),
    }
    assert sum(allocations.values(), D("0")) == D("10000")
    assert all(value >= 0 for value in allocations.values())


def test_simplex_projection_assigns_exact_budget_when_all_gaps_are_negative() -> None:
    allocations = project_to_simplex(
        {"equities": D("-10"), "fixed_income": D("-20"), "satellite": D("-30")},
        D("0.03"),
    )

    assert sum(allocations.values(), D("0")) == D("0.03")
    assert all(value >= 0 for value in allocations.values())


def test_proportional_rule_funds_each_goal_without_priority() -> None:
    urgent = GoalStub("Home", monthly_contribution=D("300"))
    flexible = GoalStub("Wealth", monthly_contribution=D("800"))

    allocation = route_funding_to_goals(
        D("500"), [flexible, urgent], FundingRule.PROPORTIONAL, date(2026, 1, 1)
    )

    assert allocation[urgent] == D("500") * D("300") / D("1100")
    assert allocation[flexible] == D("500") - allocation[urgent]


def test_proportional_rule_and_fixed_rule_conserve_every_cent() -> None:
    first = GoalStub("First", monthly_contribution=D("600"), fixed_percent=D("0.6"))
    second = GoalStub("Second", monthly_contribution=D("400"), fixed_percent=D("0.4"))

    proportional = route_funding_to_goals(
        D("1000"), [first, second], FundingRule.PROPORTIONAL, date(2026, 1, 1)
    )
    fixed = route_funding_to_goals(
        D("999.99"), [first, second], FundingRule.FIXED_PERCENTAGES, date(2026, 1, 1)
    )

    assert proportional == {first: D("600"), second: D("400")}
    assert sum(fixed.values(), D("0")) == D("999.99")


def test_fixed_rule_rejects_unconfigured_weights() -> None:
    with pytest.raises(ValueError, match="sum to 100%"):
        route_funding_to_goals(D("100"), [GoalStub("Unweighted")], FundingRule.FIXED_PERCENTAGES)


def test_monthly_contribution_handles_zero_return_and_growth() -> None:
    assert required_monthly_contribution(D("10000"), D("1000"), D("0"), 12) == D("750.00")
    contribution = required_monthly_contribution(D("10000"), D("1000"), D("0.05"), 12)
    assert contribution > D("700")
    assert contribution < D("750")


def test_monthly_compounding_fixed_deposit_matches_annual_formula() -> None:
    value = fixed_deposit_value(
        D("10000"),
        D("0.04"),
        date(2025, 1, 1),
        date(2026, 1, 1),
        CompoundingFrequency.MONTHLY,
        RateBasis.NOMINAL_APR,
    )

    assert value == D("10407.42")


def test_effective_apy_is_not_compounded_as_nominal_apr() -> None:
    value = fixed_deposit_value(
        D("10000"),
        D("0.04"),
        date(2025, 1, 1),
        date(2026, 1, 1),
        CompoundingFrequency.MONTHLY,
        RateBasis.EFFECTIVE_APY,
    )

    assert value == D("10400.00")


def test_four_year_cliff_schedule_allocates_every_unit_once() -> None:
    schedule = generate_vesting_schedule(
        D("160"), date(2024, 1, 31), duration_months=48, cliff_months=12, interval_months=3
    )

    assert schedule[0] == (date(2025, 1, 31), D("40.00000000"))
    assert schedule[-1] == (date(2028, 1, 31), D("10.00000000"))
    assert len(schedule) == 13
    assert sum((units for _, units in schedule), D("0")) == D("160")
    assert all(schedule[index][0] < schedule[index + 1][0] for index in range(len(schedule) - 1))


def test_currency_conversion_uses_quote_currency_per_base_currency_rate() -> None:
    assert convert_currency(D("108"), "USD", "EUR", D("1.08")) == D("100")
    assert convert_currency(D("100"), "EUR", "USD", D("1.08")) == D("108")
    with pytest.raises(ValueError, match="No FX conversion"):
        convert_currency(D("1"), "GBP", "EUR", D("1.08"))


def test_monthly_cash_flow_schedule_preserves_end_of_month_dates() -> None:
    dates = occurrence_dates(
        Recurrence.MONTHLY,
        date(2027, 1, 31),
        None,
        date(2027, 2, 1),
        date(2027, 4, 30),
    )

    assert dates == [date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]


def test_quarterly_schedule_skips_past_dates_without_drifting() -> None:
    dates = occurrence_dates(
        Recurrence.QUARTERLY,
        date(2026, 1, 15),
        None,
        date(2026, 4, 20),
        date(2026, 10, 20),
    )

    assert dates == [date(2026, 7, 15), date(2026, 10, 15)]


def test_one_time_schedule_respects_date_window() -> None:
    assert occurrence_dates(
        Recurrence.ONE_TIME,
        date(2027, 6, 1),
        None,
        date(2027, 1, 1),
        date(2027, 12, 31),
    ) == [date(2027, 6, 1)]
    assert (
        occurrence_dates(
            Recurrence.ONE_TIME,
            date(2026, 6, 1),
            None,
            date(2027, 1, 1),
            date(2027, 12, 31),
        )
        == []
    )


def test_annual_schedule_handles_leap_day_without_accumulating_drift() -> None:
    dates = occurrence_dates(
        Recurrence.ANNUAL,
        date(2024, 2, 29),
        None,
        date(2025, 1, 1),
        date(2028, 12, 31),
    )

    assert dates == [
        date(2025, 2, 28),
        date(2026, 2, 28),
        date(2027, 2, 28),
        date(2028, 2, 29),
    ]
