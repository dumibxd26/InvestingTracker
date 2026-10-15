from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.calculations import round_allocations
from app.models import Currency, Recurrence
from app.planning import (
    ContributionRule,
    FinancialPlanPayload,
    IncomeSource,
    InflationChange,
    contribution_months,
    income_amount,
    inflation_factor,
)

D = Decimal
ANCHOR = date(2026, 1, 1)


def convert(value: Decimal, source: Currency, target: Currency) -> Decimal:
    rates = {Currency.EUR: D("1"), Currency.USD: D("0.9"), Currency.RON: D("0.2")}
    return value * rates[source] / rates[target]


def salary(**changes) -> IncomeSource:
    return IncomeSource.model_validate(
        {
            "id": "salary",
            "name": "Net salary",
            "kind": "salary",
            "amount": "4000",
            "currency": "EUR",
            "start_date": ANCHOR,
            **changes,
        }
    )


def rule(**changes) -> ContributionRule:
    return ContributionRule.model_validate(
        {
            "calculation": "fixed",
            "value": "500",
            "start_date": ANCHOR,
            **changes,
        }
    )


def test_salary_growth_is_nominal_not_an_addition_to_inflation() -> None:
    source = salary(annual_growth_rate="0.05")
    plan = FinancialPlanPayload(
        anchor_date=ANCHOR, annual_inflation_rate=D("0.03"), income_sources=[source]
    )
    future = date(2027, 1, 1)
    nominal = income_amount(source, future, plan, convert)
    assert float(nominal) == pytest.approx(4200, abs=0.2)
    real = nominal / inflation_factor(plan, future)
    assert float(real) == pytest.approx(4077.67, abs=0.2)
    assert nominal < D("4300")  # Not a 5% raise plus another 3% inflation increase.


def test_zero_salary_growth_loses_purchasing_power() -> None:
    source = salary()
    plan = FinancialPlanPayload(anchor_date=ANCHOR, income_sources=[source])
    future = date(2027, 1, 1)
    assert income_amount(source, future, plan, convert) == D("4000")
    assert float(D("4000") / inflation_factor(plan, future)) == pytest.approx(3883.50, abs=0.2)


def test_future_salary_in_todays_money_is_inflated_once_then_nominal_growth_applies() -> None:
    start = date(2030, 1, 1)
    old = salary(end_date=date(2029, 12, 31), annual_growth_rate="0.20")
    new = salary(id="new_job", amount="5000", start_date=start, annual_growth_rate="0.05")
    plan = FinancialPlanPayload(anchor_date=ANCHOR, income_sources=[old, new])
    nominal = income_amount(new, start, plan, convert)
    assert nominal == D("5000") * inflation_factor(plan, start)
    assert float(nominal) == pytest.approx(5627.54, abs=0.1)
    later = income_amount(new, date(2031, 1, 1), plan, convert)
    assert float(later / nominal) == pytest.approx(1.05, abs=0.0001)
    explicit = new.model_copy(update={"money_basis": "nominal"})
    assert income_amount(explicit, start, plan, convert) == D("5000")


def test_inflation_rate_changes_compound_piecewise() -> None:
    change = date(2027, 1, 1)
    end = date(2028, 1, 1)
    plan = FinancialPlanPayload(
        anchor_date=ANCHOR,
        annual_inflation_rate=D("0.03"),
        inflation_changes=[InflationChange(effective_date=change, annual_rate=D("0.05"))],
    )
    expected = D("1.03") ** (D("365") / D("365.25"))
    expected *= D("1.05") ** (D("365") / D("365.25"))
    assert inflation_factor(plan, end) == expected


def test_bonus_is_in_payment_month_and_percentage_bonus_is_not_inflated_twice() -> None:
    source = salary()
    bonus = IncomeSource(
        id="bonus",
        name="Annual bonus",
        kind="bonus",
        amount=ZERO,
        currency=Currency.EUR,
        recurrence=Recurrence.ANNUAL,
        start_date=date(2026, 12, 15),
        salary_source_id="salary",
        salary_percentage=D("0.1"),
    )
    plan = FinancialPlanPayload(anchor_date=ANCHOR, income_sources=[source, bonus])
    rules = [
        rule(source_id="salary", calculation="percentage", value="0.15"),
        rule(source_id="bonus", calculation="percentage", value="0.5"),
        rule(value="200", money_basis="nominal"),
    ]
    points = contribution_months(plan, rules, D("9999"), Currency.EUR, ANCHOR, 12, convert)
    assert all(point.nominal_contribution == D("800") for point in points[:11])
    assert points[11].nominal_contribution == D("3200")
    assert income_amount(bonus, date(2026, 12, 15), plan, convert) == D("4800")


ZERO = D("0")


def test_dated_investment_changes_and_one_time_contributions() -> None:
    plan = FinancialPlanPayload(anchor_date=ANCHOR, annual_inflation_rate=ZERO)
    rules = [
        rule(value="500", end_date=date(2026, 6, 30)),
        rule(value="900", start_date=date(2026, 7, 1)),
        rule(value="10000", start_date=date(2026, 8, 15), recurrence="one_time"),
    ]
    points = contribution_months(plan, rules, ZERO, Currency.EUR, ANCHOR, 12, convert)
    assert [point.nominal_contribution for point in points[:5]] == [D("500")] * 5
    assert points[5].nominal_contribution == D("900")
    assert points[7].nominal_contribution == D("10900")
    assert points[8].nominal_contribution == D("900")


def test_today_one_time_cash_is_in_first_month_but_never_repeated() -> None:
    plan = FinancialPlanPayload(anchor_date=ANCHOR, annual_inflation_rate=ZERO)
    points = contribution_months(
        plan, [rule(recurrence="one_time")], ZERO, Currency.EUR, ANCHOR, 2, convert
    )
    assert [point.nominal_contribution for point in points] == [D("500"), ZERO]


def test_indexed_and_nominal_contributions_and_legacy_are_distinct() -> None:
    plan = FinancialPlanPayload(anchor_date=ANCHOR)
    indexed = contribution_months(plan, [rule()], ZERO, Currency.EUR, ANCHOR, 12, convert)
    nominal = contribution_months(
        plan, [rule(money_basis="nominal")], ZERO, Currency.EUR, ANCHOR, 12, convert
    )
    legacy = contribution_months(plan, None, D("500"), Currency.EUR, ANCHOR, 12, convert)
    assert indexed[-1].nominal_contribution > D("514")
    assert indexed[-1].nominal_contribution < D("516")
    assert indexed[-1].real_contribution == pytest.approx(D("500"))
    assert nominal == legacy
    assert (
        contribution_months(plan, [], D("500"), Currency.EUR, ANCHOR, 1, convert)[
            0
        ].nominal_contribution
        == ZERO
    )


def test_percentage_income_is_converted_once_but_fixed_values_use_goal_currency() -> None:
    source = salary(currency="USD", amount="1000")
    plan = FinancialPlanPayload(
        anchor_date=ANCHOR, annual_inflation_rate=ZERO, income_sources=[source]
    )
    points = contribution_months(
        plan,
        [rule(source_id="salary", calculation="percentage", value="0.2"), rule()],
        ZERO,
        Currency.EUR,
        ANCHOR,
        1,
        convert,
    )
    assert points[0].nominal_contribution == D("680")
    assert points[0].nominal_income == D("900")


def test_plan_rejects_overlapping_salaries_and_missing_bonus_salary() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        FinancialPlanPayload(anchor_date=ANCHOR, income_sources=[salary(), salary(id="other")])
    with pytest.raises(ValidationError, match="reference a salary"):
        FinancialPlanPayload(
            anchor_date=ANCHOR,
            income_sources=[
                IncomeSource(
                    id="bonus",
                    name="Bonus",
                    kind="bonus",
                    amount=ZERO,
                    currency=Currency.EUR,
                    start_date=ANCHOR,
                    salary_source_id="missing",
                    salary_percentage=D("0.1"),
                )
            ],
        )
    with pytest.raises(ValidationError, match="0-100%"):
        rule(source_id="salary", calculation="percentage", value="1.01")


def test_month_boundaries_do_not_duplicate_or_drop_recurring_payments() -> None:
    source = salary(start_date=date(2026, 1, 31))
    plan = FinancialPlanPayload(anchor_date=ANCHOR, income_sources=[source])
    rules = [rule(source_id="salary", calculation="percentage", value="0.1")]
    points = contribution_months(plan, rules, ZERO, Currency.EUR, date(2026, 1, 30), 4, convert)
    # Jan 31 and Feb 28 are both received in the first rolling month.
    assert float(sum((point.nominal_contribution for point in points), ZERO)) == pytest.approx(
        1600 * float(inflation_factor(plan, source.start_date)), abs=0.01
    )
    assert points[1].nominal_contribution == ZERO
    assert points[3].nominal_contribution == ZERO


def test_many_small_goal_shares_round_without_negative_allocations() -> None:
    rounded = round_allocations({str(index): D("0.005") for index in range(10)})
    assert sum(rounded.values(), ZERO) == D("0.05")
    assert all(value >= ZERO for value in rounded.values())
    assert list(rounded.values()) == [D("0.01")] * 5 + [ZERO] * 5
