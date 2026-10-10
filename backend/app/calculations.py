from __future__ import annotations

from calendar import monthrange
from collections.abc import Hashable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.models import CompoundingFrequency, FundingRule, GoalType, RateBasis

CENT = Decimal("0.01")
ZERO = Decimal("0")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def convert_currency(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    usd_per_eur: Decimal,
) -> Decimal:
    if from_currency == to_currency:
        return amount
    if (from_currency, to_currency) == ("EUR", "USD"):
        return amount * usd_per_eur
    if (from_currency, to_currency) == ("USD", "EUR"):
        return amount / usd_per_eur
    raise ValueError(f"No FX conversion is configured for {from_currency}/{to_currency}")


def project_to_simplex(values: dict[str, Decimal], total: Decimal) -> dict[str, Decimal]:
    """Project class funding gaps onto non-negative allocations summing to ``total``."""
    if total < ZERO:
        raise ValueError("Allocation budget cannot be negative")
    if not values:
        if total:
            raise ValueError("Cannot allocate a positive budget without target buckets")
        return {}
    if total == ZERO:
        return {key: ZERO for key in values}

    ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
    running = ZERO
    threshold = ZERO
    for index, (_, value) in enumerate(ordered, start=1):
        running += value
        candidate = (running - total) / Decimal(index)
        if value > candidate:
            threshold = candidate

    result = {key: max(value - threshold, ZERO) for key, value in values.items()}
    keys = list(result)
    if keys:
        result[keys[-1]] += total - sum(result.values(), ZERO)
    return result


def rebalance_with_contribution(
    current_values: dict[str, Decimal],
    target_weights: dict[str, Decimal],
    contribution: Decimal,
) -> dict[str, Decimal]:
    if contribution < ZERO:
        raise ValueError("Contribution cannot be negative")
    if not target_weights:
        if contribution:
            raise ValueError("At least one target allocation is required")
        return {}
    weight_total = sum(target_weights.values(), ZERO)
    if any(weight < ZERO for weight in target_weights.values()) or weight_total != Decimal(1):
        raise ValueError("Target weights must be non-negative and sum to 1")
    current_total = sum(current_values.values(), ZERO)
    post_contribution_total = current_total + contribution
    gaps = {
        bucket: weight * post_contribution_total - current_values.get(bucket, ZERO)
        for bucket, weight in target_weights.items()
    }
    return project_to_simplex(gaps, contribution)


def _months_until(start: date, end: date) -> int:
    return max(1, (end.year - start.year) * 12 + end.month - start.month)


def _goal_need(goal: object, today: date) -> Decimal:
    monthly = getattr(goal, "monthly_contribution", ZERO) or ZERO
    if monthly > ZERO:
        return monthly
    target = getattr(goal, "target_amount", None)
    current = getattr(goal, "current_amount", ZERO) or ZERO
    due = getattr(goal, "target_date", None)
    if target is not None and due is not None:
        return max(ZERO, target - current) / Decimal(_months_until(today, due))
    return Decimal(1)


def route_funding_to_goals[T: Hashable](
    amount: Decimal,
    goals: list[T],
    funding_rule: FundingRule,
    today: date | None = None,
) -> dict[T, Decimal]:
    active_goals = [goal for goal in goals if getattr(goal, "is_active", True)]
    if amount < ZERO:
        raise ValueError("Funding amount cannot be negative")
    if not active_goals or amount == ZERO:
        return {goal: ZERO for goal in active_goals}
    today = today or date.today()
    needs = {goal: _goal_need(goal, today) for goal in active_goals}

    if funding_rule == FundingRule.PRIORITY_FIRST:
        result = {goal: ZERO for goal in active_goals}
        remaining = amount
        for goal in sorted(active_goals, key=lambda item: (item.priority, item.name)):
            allocation = min(remaining, needs[goal])
            result[goal] = allocation
            remaining -= allocation
        if remaining > ZERO:
            first_goal = min(active_goals, key=lambda item: (item.priority, item.name))
            result[first_goal] += remaining
        return result

    if funding_rule == FundingRule.FIXED_PERCENTAGES:
        weights = {goal: (goal.fixed_percent or ZERO) for goal in active_goals}
        if sum(weights.values(), ZERO) != Decimal(1):
            raise ValueError("Fixed goal percentages must be configured and sum to 100%")
    else:
        need_total = sum(needs.values(), ZERO)
        weights = (
            {goal: need / need_total for goal, need in needs.items()}
            if need_total
            else {goal: Decimal(1) / Decimal(len(active_goals)) for goal in active_goals}
        )

    result = {goal: amount * weight for goal, weight in weights.items()}
    result[max(result, key=lambda item: item.name)] += amount - sum(result.values(), ZERO)
    return result


def required_monthly_contribution(
    target: Decimal,
    current: Decimal,
    annual_effective_return: Decimal,
    months: int,
) -> Decimal:
    if target < ZERO or current < ZERO or annual_effective_return <= Decimal(-1):
        raise ValueError("Goal amounts must be non-negative and return must exceed -100%")
    if months <= 0:
        raise ValueError("Investment period must be at least one month")
    if current >= target:
        return ZERO

    with localcontext() as context:
        context.prec = 32
        monthly_rate = (Decimal(1) + annual_effective_return).ln() / Decimal(12)
        monthly_rate = monthly_rate.exp() - Decimal(1)
        growth = (Decimal(1) + monthly_rate) ** months
        if monthly_rate == ZERO:
            return round_money((target - current) / Decimal(months))
        needed = (target - current * growth) * monthly_rate / (growth - Decimal(1))
        return round_money(max(ZERO, needed))


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def generate_vesting_schedule(
    total_units: Decimal,
    grant_date: date,
    duration_months: int = 48,
    cliff_months: int = 12,
    interval_months: int = 3,
) -> list[tuple[date, Decimal]]:
    if total_units <= ZERO:
        raise ValueError("Grant units must be positive")
    if duration_months <= 0 or interval_months <= 0:
        raise ValueError("Vesting duration and interval must be positive")
    if cliff_months < 0 or cliff_months > duration_months:
        raise ValueError("Cliff must be between zero and the vesting duration")

    vest_months = list(range(cliff_months or interval_months, duration_months + 1, interval_months))
    if not vest_months or vest_months[-1] != duration_months:
        vest_months.append(duration_months)

    previous_vest_months = [0, *vest_months[:-1]]
    tranches: list[tuple[date, Decimal]] = []
    allocated = ZERO
    quantum = Decimal("0.00000001")
    for previous_month, vest_month in zip(previous_vest_months, vest_months, strict=True):
        fraction = Decimal(vest_month - previous_month) / Decimal(duration_months)
        units = (total_units * fraction).quantize(quantum, rounding=ROUND_HALF_UP)
        if vest_month == duration_months:
            units = total_units - allocated
        allocated += units
        tranches.append((_add_months(grant_date, vest_month), units))
    return tranches


def fixed_deposit_value(
    principal: Decimal,
    annual_rate: Decimal,
    start_date: date,
    as_of: date,
    compounding: CompoundingFrequency,
    rate_basis: RateBasis,
) -> Decimal:
    if principal < ZERO or annual_rate < ZERO or as_of < start_date:
        raise ValueError(
            "Deposit principal/rate must be non-negative and valuation cannot predate start"
        )
    days = Decimal((as_of - start_date).days)
    if days == ZERO:
        return round_money(principal)

    with localcontext() as context:
        context.prec = 32
        elapsed_years = days / Decimal(365)
        if rate_basis == RateBasis.EFFECTIVE_APY:
            factor = ((Decimal(1) + annual_rate).ln() * elapsed_years).exp()
            return round_money(principal * factor)

        periods_per_year = {
            CompoundingFrequency.DAILY: Decimal(365),
            CompoundingFrequency.MONTHLY: Decimal(12),
            CompoundingFrequency.QUARTERLY: Decimal(4),
            CompoundingFrequency.ANNUAL: Decimal(1),
            CompoundingFrequency.AT_MATURITY: Decimal(1),
        }[compounding]
        periodic_rate = annual_rate / periods_per_year
        periods_elapsed = elapsed_years * periods_per_year
        full_periods = int(periods_elapsed)
        partial_period = periods_elapsed - Decimal(full_periods)
        if compounding == CompoundingFrequency.AT_MATURITY:
            factor = Decimal(1) + annual_rate * elapsed_years
        else:
            factor = (Decimal(1) + periodic_rate) ** full_periods
            factor *= Decimal(1) + periodic_rate * partial_period
        return round_money(principal * factor)


def goal_progress(
    goal_type: GoalType,
    target_amount: Decimal | None,
    target_annual_income: Decimal | None,
    current_amount: Decimal,
    current_annual_income: Decimal,
) -> tuple[Decimal, Decimal]:
    if goal_type == GoalType.PASSIVE_INCOME and target_annual_income:
        progress_amount, target = current_annual_income, target_annual_income
    else:
        progress_amount, target = current_amount, target_amount or ZERO
    if target <= ZERO:
        return progress_amount, ZERO
    return progress_amount, min(Decimal(100), progress_amount * Decimal(100) / target)
