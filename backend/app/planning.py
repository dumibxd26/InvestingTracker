from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cash_flow_logic import add_months, occurrence_dates
from app.models import Currency, Recurrence

ZERO = Decimal("0")
ONE = Decimal("1")
MoneyBasis = Literal["real", "nominal"]
Convert = Callable[[Decimal, Currency, Currency], Decimal]


class InflationChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_date: date
    annual_rate: Decimal = Field(ge=Decimal("-0.5"), le=Decimal("1"))


class IncomeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=100)
    kind: Literal["salary", "bonus"]
    amount: Decimal = Field(ge=0, le=Decimal("100000000"))
    currency: Currency
    recurrence: Recurrence = Recurrence.MONTHLY
    start_date: date
    end_date: date | None = None
    money_basis: MoneyBasis = "real"
    annual_growth_rate: Decimal = Field(default=ZERO, ge=Decimal("-0.5"), le=ONE)
    salary_source_id: str | None = None
    salary_percentage: Decimal | None = Field(default=None, gt=0, le=ONE)

    @model_validator(mode="after")
    def validate_income(self) -> IncomeSource:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Income end date cannot precede its start date")
        if (self.salary_source_id is None) != (self.salary_percentage is None):
            raise ValueError("A salary-based bonus needs a salary source and percentage")
        if self.salary_source_id is not None and self.kind != "bonus":
            raise ValueError("Only bonuses may be a percentage of salary")
        if self.salary_source_id is not None and self.annual_growth_rate:
            raise ValueError("Salary-based bonuses already grow with salary")
        if self.recurrence == Recurrence.ONE_TIME and self.end_date is not None:
            raise ValueError("One-time income cannot have an end date")
        return self


class FinancialPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_date: date
    annual_inflation_rate: Decimal = Field(default=Decimal("0.03"), ge=Decimal("-0.5"), le=ONE)
    inflation_changes: list[InflationChange] = Field(default_factory=list, max_length=100)
    income_sources: list[IncomeSource] = Field(default_factory=list, max_length=100)
    monthly_expenses: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    expenses_currency: Currency = Currency.EUR

    @model_validator(mode="after")
    def validate_timeline(self) -> FinancialPlanPayload:
        ids = [source.id for source in self.income_sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Income source identifiers must be unique")
        changes = [change.effective_date for change in self.inflation_changes]
        if len(changes) != len(set(changes)):
            raise ValueError("Only one inflation change is allowed on a date")
        if any(change < self.anchor_date for change in changes):
            raise ValueError("Inflation changes cannot precede the planning reference date")
        sources = {source.id: source for source in self.income_sources}
        for source in self.income_sources:
            if source.salary_source_id is not None:
                salary = sources.get(source.salary_source_id)
                if salary is None or salary.kind != "salary":
                    raise ValueError("A salary-based bonus must reference a salary in this plan")
        salaries = [source for source in self.income_sources if source.kind == "salary"]
        for index, first in enumerate(salaries):
            for second in salaries[index + 1 :]:
                if max(first.start_date, second.start_date) <= min(
                    first.end_date or date.max, second.end_date or date.max
                ):
                    raise ValueError(
                        "Salary periods overlap. End the previous salary before a job change."
                    )
        return self


class ContributionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    source_kind: Literal["salary", "bonus"] | None = None
    calculation: Literal["fixed", "percentage"] = "fixed"
    value: Decimal = Field(ge=0, le=Decimal("100000000"))
    recurrence: Recurrence = Recurrence.MONTHLY
    start_date: date
    end_date: date | None = None
    money_basis: MoneyBasis = "real"

    @model_validator(mode="after")
    def validate_rule(self) -> ContributionRule:
        if self.source_id is not None and self.source_kind is not None:
            raise ValueError("Choose a specific income source or an income category, not both")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Contribution end date cannot precede its start date")
        if self.calculation == "percentage":
            if (self.source_id is None and self.source_kind is None) or self.value > ONE:
                raise ValueError(
                    "Percentage contributions need an income source and a 0-100% share"
                )
        if self.recurrence == Recurrence.ONE_TIME and self.end_date is not None:
            raise ValueError("One-time contributions cannot have an end date")
        return self


def matching_sources(rule: ContributionRule, plan: FinancialPlanPayload) -> list[IncomeSource]:
    return [
        source
        for source in plan.income_sources
        if source.id == rule.source_id
        or (rule.source_kind is not None and source.kind == rule.source_kind)
    ]


class ContributionMonth(BaseModel):
    date: date
    nominal_contribution: Decimal
    real_contribution: Decimal
    nominal_income: Decimal
    nominal_expenses: Decimal
    inflation_factor: Decimal


class ContributionSchedule(BaseModel):
    anchor_date: date
    currency: Currency
    months: list[ContributionMonth]
    warnings: list[str] = Field(default_factory=list)


def inflation_factor(plan: FinancialPlanPayload, target: date) -> Decimal:
    if target < plan.anchor_date:
        raise ValueError("Inflation target cannot precede the planning reference date")
    factor = ONE
    start = plan.anchor_date
    rate = plan.annual_inflation_rate
    for change in sorted(plan.inflation_changes, key=lambda item: item.effective_date):
        if change.effective_date > target:
            break
        factor *= (ONE + rate) ** (
            Decimal((change.effective_date - start).days) / Decimal("365.25")
        )
        start, rate = change.effective_date, change.annual_rate
    return factor * (ONE + rate) ** (Decimal((target - start).days) / Decimal("365.25"))


def income_amount(
    source: IncomeSource, at: date, plan: FinancialPlanPayload, convert: Convert
) -> Decimal:
    if source.salary_source_id is not None:
        salary = next(item for item in plan.income_sources if item.id == source.salary_source_id)
        if not salary.start_date <= at <= (salary.end_date or date.max):
            return ZERO
        salary_value = income_amount(salary, at, plan, convert)
        annual_multiplier = {
            Recurrence.MONTHLY: 12,
            Recurrence.QUARTERLY: 4,
            Recurrence.ANNUAL: 1,
            Recurrence.ONE_TIME: 1,
        }[salary.recurrence]
        return convert(
            salary_value * annual_multiplier * (source.salary_percentage or ZERO),
            salary.currency,
            source.currency,
        )
    growth_start = max(source.start_date, plan.anchor_date)
    years = max(ZERO, Decimal((at - growth_start).days) / Decimal("365.25"))
    value = source.amount * (ONE + source.annual_growth_rate) ** years
    if source.money_basis == "real":
        value *= inflation_factor(plan, max(plan.anchor_date, source.start_date))
    return value


def contribution_months(
    plan: FinancialPlanPayload,
    rules: list[ContributionRule] | None,
    legacy_monthly: Decimal,
    currency: Currency,
    today: date,
    months: int,
    convert: Convert,
) -> list[ContributionMonth]:
    if not 1 <= months <= 1320:
        raise ValueError("Projection must cover between 1 and 1320 months")
    sources = {source.id: source for source in plan.income_sources}
    result: list[ContributionMonth] = []
    base_factor = inflation_factor(plan, today)
    for offset in range(months):
        at = add_months(today, offset + 1)
        previous = add_months(today, offset)
        first = previous + timedelta(days=1)
        factor = inflation_factor(plan, at)
        events: list[tuple[str, date, Decimal]] = []
        for source in plan.income_sources:
            for event_date in occurrence_dates(
                source.recurrence,
                source.start_date,
                source.end_date,
                today if offset == 0 and source.recurrence == Recurrence.ONE_TIME else first,
                at,
            ):
                events.append(
                    (source.id, event_date, income_amount(source, event_date, plan, convert))
                )
        total = legacy_monthly if rules is None else ZERO
        for rule in rules or []:
            if rule.source_id is not None or rule.source_kind is not None:
                applicable = {source.id for source in matching_sources(rule, plan)}
                for source_id, event_date, value in events:
                    if source_id not in applicable or not (
                        rule.start_date <= event_date <= (rule.end_date or date.max)
                    ):
                        continue
                    total += (
                        convert(value, sources[source_id].currency, currency) * rule.value
                        if rule.calculation == "percentage"
                        else rule.value
                        * (
                            inflation_factor(plan, event_date)
                            if rule.money_basis == "real"
                            else ONE
                        )
                    )
            else:
                for event_date in occurrence_dates(
                    rule.recurrence,
                    rule.start_date,
                    rule.end_date,
                    today if offset == 0 and rule.recurrence == Recurrence.ONE_TIME else first,
                    at,
                ):
                    total += rule.value * (
                        inflation_factor(plan, event_date) if rule.money_basis == "real" else ONE
                    )
        income = sum(
            (convert(value, sources[key].currency, currency) for key, _, value in events), ZERO
        )
        expenses = convert(
            (plan.monthly_expenses or ZERO) * factor, plan.expenses_currency, currency
        )
        result.append(
            ContributionMonth(
                date=at,
                nominal_contribution=total,
                real_contribution=total / factor,
                nominal_income=income,
                nominal_expenses=expenses,
                inflation_factor=factor / base_factor,
            )
        )
    return result
