from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.calculations import (
    convert_currency,
    fixed_deposit_value,
    goal_progress,
    rebalance_with_contribution,
    round_money,
    route_funding_to_goals,
)
from app.cash_flow_logic import add_months, occurrence_dates
from app.config import get_settings
from app.models import (
    AccountType,
    AllocationPolicy,
    AssetClass,
    BrokerAccount,
    CashFlow,
    CashFlowSchedule,
    Currency,
    FixedDeposit,
    FlowDirection,
    FlowKind,
    FlowStatus,
    FundingRule,
    FXRate,
    Goal,
    GoalType,
    Holding,
    Instrument,
    MarketPriceCache,
    Recommendation,
    RiskLevel,
    TrancheStatus,
    User,
    ValuationSnapshot,
    VestingGrant,
    VestingTranche,
)
from app.schemas import (
    AllocationSummary,
    BucketAllocation,
    CashFlowScheduleCreate,
    CashFlowScheduleResponse,
    ChartPoint,
    DepositSummary,
    FixedSharesUpdate,
    FlowResponse,
    GoalAllocation,
    GoalCreate,
    GoalResponse,
    GoalSummary,
    HoldingSummary,
    PolicyResponse,
    PolicyUpdate,
    RecommendationRequest,
    RecommendationResponse,
    VestingSummary,
)

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
USER_ID = uuid.UUID(get_settings().demo_user_id)


def _get_user(session: Session) -> User:
    user = session.get(User, USER_ID)
    if user is None:
        raise HTTPException(status_code=503, detail="Demo profile is not initialized")
    return user


def _get_policy(session: Session, user_id: uuid.UUID) -> AllocationPolicy:
    policy = session.scalar(select(AllocationPolicy).where(AllocationPolicy.user_id == user_id))
    if policy is None:
        raise HTTPException(status_code=503, detail="Allocation policy is not configured")
    return policy


def _eur_per_usd(session: Session) -> Decimal:
    rate = session.scalar(
        select(FXRate)
        .where(
            FXRate.base_currency == Currency.EUR,
            FXRate.quote_currency == Currency.USD,
        )
        .order_by(FXRate.observed_at.desc())
        .limit(1)
    )
    if rate is None or rate.rate <= ZERO:
        raise HTTPException(status_code=503, detail="No EUR/USD reference rate is available")
    return rate.rate


def _to_base(
    amount: Decimal, from_currency: Currency, to_currency: Currency, eur_per_usd: Decimal
) -> Decimal:
    try:
        return convert_currency(amount, from_currency.value, to_currency.value, eur_per_usd)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _target_weights(policy: AllocationPolicy) -> dict[str, Decimal]:
    return {key: Decimal(str(value)) for key, value in policy.target_weights.items()}


def get_policy_response(session: Session) -> PolicyResponse:
    user = _get_user(session)
    policy = _get_policy(session, user.id)
    return PolicyResponse(
        funding_rule=policy.funding_rule,
        emergency_reserve=policy.emergency_reserve,
        target_weights=_target_weights(policy),
    )


def _flow_direction(kind: FlowKind) -> FlowDirection:
    if kind == FlowKind.BILL:
        return FlowDirection.OUTFLOW
    if kind == FlowKind.CONTRIBUTION:
        return FlowDirection.TRANSFER
    return FlowDirection.INFLOW


def list_cash_flow_schedules(session: Session) -> list[CashFlowScheduleResponse]:
    user = _get_user(session)
    schedules = session.scalars(
        select(CashFlowSchedule)
        .where(CashFlowSchedule.user_id == user.id, CashFlowSchedule.is_active.is_(True))
        .order_by(CashFlowSchedule.start_date, CashFlowSchedule.label)
    )
    return [CashFlowScheduleResponse.model_validate(schedule) for schedule in schedules]


def create_cash_flow_schedule(
    session: Session, payload: CashFlowScheduleCreate
) -> CashFlowScheduleResponse:
    user = _get_user(session)
    active_count = session.scalar(
        select(func.count())
        .select_from(CashFlowSchedule)
        .where(CashFlowSchedule.user_id == user.id, CashFlowSchedule.is_active.is_(True))
    )
    if (active_count or 0) >= 100:
        raise HTTPException(
            status_code=409, detail="Archive an existing schedule before adding another"
        )
    schedule = CashFlowSchedule(user_id=user.id, **payload.model_dump())
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return CashFlowScheduleResponse.model_validate(schedule)


def archive_cash_flow_schedule(
    session: Session, schedule_id: uuid.UUID
) -> CashFlowScheduleResponse:
    user = _get_user(session)
    schedule = session.scalar(
        select(CashFlowSchedule).where(
            CashFlowSchedule.id == schedule_id,
            CashFlowSchedule.user_id == user.id,
            CashFlowSchedule.is_active.is_(True),
        )
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Active cash-flow schedule not found")
    schedule.is_active = False
    session.commit()
    session.refresh(schedule)
    return CashFlowScheduleResponse.model_validate(schedule)


def _project_cash_flows(
    session: Session,
    user_id: uuid.UUID,
    base_currency: Currency,
    usd_per_eur: Decimal,
    months: int,
) -> list[FlowResponse]:
    today = date.today()
    through_date = add_months(today, months)
    entries: list[FlowResponse] = []

    flow_rows = session.scalars(
        select(CashFlow).where(
            CashFlow.user_id == user_id,
            or_(
                (
                    (CashFlow.status == FlowStatus.FORECAST)
                    & (CashFlow.expected_date >= today)
                    & (CashFlow.expected_date <= through_date)
                ),
                CashFlow.status == FlowStatus.CONFIRMED,
            ),
        )
    )
    for flow in flow_rows:
        entries.append(
            FlowResponse(
                id=flow.id,
                label=flow.label,
                kind=flow.kind,
                direction=_flow_direction(flow.kind),
                status=flow.status,
                amount=flow.amount,
                currency=flow.currency,
                expected_date=flow.expected_date,
                occurred_at=flow.occurred_at,
                reporting_amount=round_money(
                    _to_base(flow.amount, flow.currency, base_currency, usd_per_eur)
                ),
                reporting_currency=base_currency,
            )
        )

    schedules = session.scalars(
        select(CashFlowSchedule).where(
            CashFlowSchedule.user_id == user_id,
            CashFlowSchedule.is_active.is_(True),
        )
    )
    for schedule in schedules:
        for occurrence in occurrence_dates(
            schedule.recurrence,
            schedule.start_date,
            schedule.end_date,
            today,
            through_date,
        ):
            entries.append(
                FlowResponse(
                    id=uuid.uuid5(schedule.id, f"occurrence:{occurrence.isoformat()}"),
                    label=schedule.label,
                    kind=schedule.kind,
                    direction=_flow_direction(schedule.kind),
                    status=FlowStatus.FORECAST,
                    amount=schedule.amount,
                    currency=schedule.currency,
                    expected_date=occurrence,
                    occurred_at=None,
                    reporting_amount=round_money(
                        _to_base(
                            schedule.amount,
                            schedule.currency,
                            base_currency,
                            usd_per_eur,
                        )
                    ),
                    reporting_currency=base_currency,
                    schedule_id=schedule.id,
                    recurrence=schedule.recurrence,
                )
            )

    def event_date(flow: FlowResponse) -> date:
        if flow.expected_date is not None:
            return flow.expected_date
        if flow.occurred_at is not None:
            return flow.occurred_at.date()
        return date.max

    entries.sort(key=lambda flow: (event_date(flow), flow.label, str(flow.id)))
    return entries


def update_policy(session: Session, payload: PolicyUpdate) -> PolicyResponse:
    user = _get_user(session)
    policy = _get_policy(session, user.id)
    active_goals = list(
        session.scalars(select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True)))
    )
    if payload.funding_rule == FundingRule.FIXED_PERCENTAGES:
        percentages = [goal.fixed_percent or ZERO for goal in active_goals]
        if not active_goals or sum(percentages, ZERO) != ONE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Active goals need fixed percentages that sum to 100% "
                    "before selecting this rule"
                ),
            )
    policy.funding_rule = payload.funding_rule
    policy.emergency_reserve = payload.emergency_reserve
    policy.target_weights = {
        asset_class.value: str(weight) for asset_class, weight in payload.target_weights.items()
    }
    policy.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(policy)
    return PolicyResponse(
        funding_rule=policy.funding_rule,
        emergency_reserve=policy.emergency_reserve,
        target_weights=_target_weights(policy),
    )


def list_goals(session: Session) -> list[GoalResponse]:
    user = _get_user(session)
    goals = session.scalars(
        select(Goal).where(Goal.user_id == user.id).order_by(Goal.priority, Goal.name)
    )
    return [GoalResponse.model_validate(goal) for goal in goals]


def create_goal(session: Session, payload: GoalCreate) -> GoalResponse:
    user = _get_user(session)
    policy = _get_policy(session, user.id)
    if policy.funding_rule == FundingRule.FIXED_PERCENTAGES:
        current_total = sum(
            (
                goal.fixed_percent or ZERO
                for goal in session.scalars(
                    select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True))
                )
            ),
            ZERO,
        )
        proposed_total = current_total + (payload.fixed_percent or ZERO)
        if proposed_total != ONE:
            raise HTTPException(
                status_code=422,
                detail="New goal percentages must keep the active fixed allocation at 100%",
            )
    goal = Goal(user_id=user.id, **payload.model_dump())
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return GoalResponse.model_validate(goal)


def update_fixed_shares(session: Session, payload: FixedSharesUpdate) -> dict[str, Decimal]:
    user = _get_user(session)
    goals = list(
        session.scalars(select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True)))
    )
    requested = {item.goal_id: item.percentage for item in payload.shares}
    expected_ids = {goal.id for goal in goals}
    if len(requested) != len(payload.shares) or set(requested) != expected_ids:
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one fixed percentage for every active goal",
        )
    if sum(requested.values(), ZERO) != ONE:
        raise HTTPException(status_code=422, detail="Fixed goal percentages must sum to 100%")
    for goal in goals:
        goal.fixed_percent = requested[goal.id]
    session.commit()
    return {str(goal_id): percentage for goal_id, percentage in requested.items()}


def dashboard(session: Session, requested_currency: Currency | None = None) -> dict[str, Any]:
    user = _get_user(session)
    base_currency = requested_currency or user.base_currency
    eur_per_usd = _eur_per_usd(session)
    policy = _get_policy(session, user.id)
    now = datetime.now(UTC)
    today = date.today()

    quote_rows = session.scalars(
        select(MarketPriceCache).order_by(MarketPriceCache.observed_at.desc())
    )
    latest_quotes: dict[uuid.UUID, MarketPriceCache] = {}
    for quote in quote_rows:
        latest_quotes.setdefault(quote.instrument_id, quote)

    holding_rows = session.execute(
        select(Holding, Instrument, BrokerAccount)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .join(BrokerAccount, BrokerAccount.id == Holding.account_id)
        .where(Holding.user_id == user.id)
    ).all()

    holdings: list[HoldingSummary] = []
    values_by_class = {asset_class.value: ZERO for asset_class in AssetClass}
    annual_dividend_income = ZERO
    unrealized_pnl = ZERO
    sample_data = True
    warnings = [
        (
            "Illustrative demo records only. No broker is connected and no live market "
            "or FX feed is configured."
        ),
        (
            "Demo positions, cost basis, goal earmarks, and history are synthetic; "
            "tax lots, realized P&L, and account reconciliation are not implemented."
        ),
    ]
    for holding, instrument, account in holding_rows:
        quote = latest_quotes.get(instrument.id)
        if quote is None:
            warnings.append(
                f"{instrument.symbol} has no quote and is excluded from portfolio totals."
            )
            sample_data = False
            continue
        native_value = holding.quantity * quote.price
        current_value = _to_base(native_value, quote.currency, base_currency, eur_per_usd)
        cost_value = _to_base(
            holding.quantity * holding.average_cost,
            instrument.currency,
            base_currency,
            eur_per_usd,
        )
        unrealized_pnl += current_value - cost_value
        values_by_class[instrument.asset_class.value] += current_value
        annual_dividend_income += _to_base(
            native_value * instrument.estimated_annual_yield,
            quote.currency,
            base_currency,
            eur_per_usd,
        )
        change_percent = (
            (quote.price - holding.average_cost) * Decimal(100) / holding.average_cost
            if holding.average_cost
            else ZERO
        )
        sample_data = sample_data and instrument.is_demo and quote.feed_type == "SAMPLE"
        holdings.append(
            HoldingSummary(
                symbol=instrument.symbol,
                name=instrument.name,
                account_name=account.display_name,
                asset_class=instrument.asset_class,
                quantity=holding.quantity,
                price=quote.price,
                price_currency=quote.currency,
                market_value=round_money(current_value),
                base_currency=base_currency,
                change_percent=change_percent.quantize(Decimal("0.01")),
                is_demo=instrument.is_demo,
            )
        )

    accounts = list(session.scalars(select(BrokerAccount).where(BrokerAccount.user_id == user.id)))
    available_cash = sum(
        (
            _to_base(account.cash_balance, account.currency, base_currency, eur_per_usd)
            for account in accounts
            if account.account_type
            in {AccountType.BROKERAGE, AccountType.BANK, AccountType.SAVINGS}
        ),
        ZERO,
    )

    deposits: list[DepositSummary] = []
    deposit_value = ZERO
    annual_interest_income = ZERO
    fixed_deposits = session.scalars(select(FixedDeposit).where(FixedDeposit.user_id == user.id))
    for deposit in fixed_deposits:
        valuation_date = min(today, deposit.maturity_date)
        accrued_value = fixed_deposit_value(
            deposit.principal,
            deposit.annual_rate,
            deposit.start_date,
            valuation_date,
            deposit.compounding,
            deposit.rate_basis,
        )
        accrued_interest = max(ZERO, accrued_value - deposit.principal)
        deposit_value += _to_base(accrued_value, deposit.currency, base_currency, eur_per_usd)
        annual_interest_income += _to_base(
            deposit.principal * deposit.annual_rate,
            deposit.currency,
            base_currency,
            eur_per_usd,
        )
        deposits.append(
            DepositSummary(
                name=deposit.name,
                principal=deposit.principal,
                accrued_interest=accrued_interest,
                currency=deposit.currency,
                annual_rate=deposit.annual_rate,
                rate_basis=deposit.rate_basis,
                maturity_date=deposit.maturity_date,
                days_to_maturity=max((deposit.maturity_date - today).days, 0),
            )
        )

    grants = list(session.scalars(select(VestingGrant).where(VestingGrant.user_id == user.id)))
    vesting: list[VestingSummary] = []
    unvested_gross = ZERO
    unvested_net = ZERO
    for grant in grants:
        instrument = session.get(Instrument, grant.instrument_id)
        quote = latest_quotes.get(grant.instrument_id)
        if instrument is None or quote is None:
            continue
        grant_tranches = list(
            session.scalars(select(VestingTranche).where(VestingTranche.grant_id == grant.id))
        )
        future_tranches = [
            tranche
            for tranche in grant_tranches
            if tranche.available_date >= today and tranche.status == TrancheStatus.SCHEDULED
        ]
        vested_units = sum(
            (
                tranche.units
                for tranche in grant_tranches
                if tranche.status in {TrancheStatus.VESTED, TrancheStatus.RELEASED}
            ),
            ZERO,
        )
        units = sum((tranche.units for tranche in future_tranches), ZERO)
        if grant.grant_type.value == "option":
            intrinsic_value = units * max(quote.price - (grant.strike_price or ZERO), ZERO)
        else:
            intrinsic_value = units * quote.price
        gross = _to_base(intrinsic_value, quote.currency, base_currency, eur_per_usd)
        net = gross * (ONE - grant.tax_rate_assumption)
        unvested_gross += gross
        unvested_net += net
        vesting.append(
            VestingSummary(
                symbol=instrument.symbol,
                name=instrument.name,
                grant_type=grant.grant_type.value,
                units=units,
                vested_percent=(
                    min(Decimal(100), vested_units * Decimal(100) / grant.total_units)
                    if grant.total_units
                    else ZERO
                ),
                next_vest_date=min(
                    (tranche.vest_date for tranche in future_tranches), default=None
                ),
                gross_value=round_money(gross),
                estimated_net_value=round_money(net),
                currency=base_currency,
            )
        )

    total_invested = sum(values_by_class.values(), ZERO)
    net_worth = total_invested + available_cash + deposit_value + unvested_gross
    annual_income = annual_dividend_income + annual_interest_income
    goals: list[GoalSummary] = []
    goal_rows = list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.is_active.is_(True))
            .order_by(Goal.priority, Goal.name)
        )
    )
    for goal in goal_rows:
        current_amount = _to_base(
            goal.current_amount, goal.target_currency, base_currency, eur_per_usd
        )
        current_annual_income = _to_base(
            goal.current_annual_income, goal.target_currency, base_currency, eur_per_usd
        )
        target_amount = (
            _to_base(goal.target_amount, goal.target_currency, base_currency, eur_per_usd)
            if goal.target_amount is not None
            else None
        )
        target_annual_income = (
            _to_base(goal.target_annual_income, goal.target_currency, base_currency, eur_per_usd)
            if goal.target_annual_income is not None
            else None
        )
        progress_value, progress_percent = goal_progress(
            goal.goal_type,
            target_amount,
            target_annual_income,
            current_amount,
            current_annual_income,
        )
        goals.append(
            GoalSummary(
                id=goal.id,
                name=goal.name,
                goal_type=goal.goal_type,
                target_amount=target_amount,
                target_annual_income=target_annual_income,
                current_amount=progress_value,
                current_annual_income=current_annual_income,
                currency=base_currency,
                progress_percent=progress_percent.quantize(Decimal("0.01")),
                target_date=goal.target_date,
                priority=goal.priority,
                risk_level=goal.risk_level,
                monthly_contribution=goal.monthly_contribution,
                fixed_percent=goal.fixed_percent,
                flexibility=goal.flexibility,
            )
        )

    cash_flow_responses = _project_cash_flows(
        session, user.id, base_currency, eur_per_usd, months=12
    )[:8]
    cash_flow_schedules = list_cash_flow_schedules(session)

    snapshot_rows = list(
        session.scalars(
            select(ValuationSnapshot)
            .where(ValuationSnapshot.user_id == user.id)
            .order_by(ValuationSnapshot.observed_at)
        )
    )
    chart = [
        ChartPoint(
            label=snapshot.observed_at.strftime("%b"),
            date=snapshot.observed_at.date(),
            value=round_money(
                _to_base(snapshot.total_value, snapshot.currency, base_currency, eur_per_usd)
            ),
        )
        for snapshot in snapshot_rows
    ]
    if chart:
        chart[-1].value = round_money(net_worth)
    else:
        chart = [ChartPoint(label="Today", date=today, value=round_money(net_worth))]
    six_month_change = chart[-1].value - chart[0].value
    six_month_change_percent = (
        six_month_change * Decimal(100) / chart[0].value if chart[0].value else ZERO
    )

    current_allocation = [
        AllocationSummary(
            asset_class=AssetClass(asset_class.value),
            value=round_money(values_by_class[asset_class.value]),
            percentage=(
                values_by_class[asset_class.value] * Decimal(100) / total_invested
                if total_invested
                else ZERO
            ),
            target_percentage=_target_weights(policy).get(asset_class.value, ZERO) * Decimal(100),
        )
        for asset_class in AssetClass
    ]

    return {
        "base_currency": base_currency,
        "as_of": now,
        "sample_data": sample_data,
        "totals": {
            "net_worth": round_money(net_worth),
            "invested_assets": round_money(total_invested),
            "available_cash": round_money(available_cash),
            "fixed_deposits": round_money(deposit_value),
            "unvested_equity_gross": round_money(unvested_gross),
            "unvested_equity_net_estimate": round_money(unvested_net),
            "unrealized_pnl_estimate": round_money(unrealized_pnl),
            "estimated_monthly_income": round_money(annual_income / Decimal(12)),
            "emergency_reserve_target": round_money(policy.emergency_reserve),
            "reserve_shortfall": round_money(
                max(
                    ZERO,
                    _to_base(
                        policy.emergency_reserve,
                        user.base_currency,
                        base_currency,
                        eur_per_usd,
                    )
                    - available_cash,
                )
            ),
        },
        "six_month_change": round_money(six_month_change),
        "six_month_change_percent": six_month_change_percent.quantize(Decimal("0.01")),
        "allocation": current_allocation,
        "chart": chart,
        "holdings": holdings,
        "goals": goals,
        "cash_flows": cash_flow_responses,
        "cash_flow_schedules": cash_flow_schedules,
        "deposits": deposits,
        "vesting": vesting,
        "warnings": warnings,
        "policy": PolicyResponse(
            funding_rule=policy.funding_rule,
            emergency_reserve=_to_base(
                policy.emergency_reserve, user.base_currency, base_currency, eur_per_usd
            ),
            target_weights=_target_weights(policy),
        ),
    }


def list_cash_flows(session: Session, months: int = 12) -> list[FlowResponse]:
    user = _get_user(session)
    eur_per_usd = _eur_per_usd(session)
    return _project_cash_flows(session, user.id, user.base_currency, eur_per_usd, months)


def preview_recommendation(
    session: Session, request: RecommendationRequest
) -> RecommendationResponse:
    user = _get_user(session)
    policy = _get_policy(session, user.id)
    fx = _eur_per_usd(session)
    now = datetime.now(UTC)
    base_currency = user.base_currency
    input_base = _to_base(request.amount, request.currency, base_currency, fx)
    available_cash_base = dashboard(session, base_currency)["totals"]["available_cash"]
    reserve_base = _to_base(policy.emergency_reserve, user.base_currency, base_currency, fx)
    reserve_top_up = min(input_base, max(ZERO, reserve_base - available_cash_base))
    deployable = max(ZERO, input_base - reserve_top_up)

    goals = list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.is_active.is_(True))
            .order_by(Goal.priority, Goal.name)
        )
    )
    try:
        goal_amounts = route_funding_to_goals(deployable, goals, policy.funding_rule, date.today())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    rounded_goal_amounts = {goal: round_money(amount) for goal, amount in goal_amounts.items()}
    goal_residual = round_money(deployable) - sum(rounded_goal_amounts.values(), ZERO)
    if rounded_goal_amounts:
        highest_priority_goal = min(
            rounded_goal_amounts, key=lambda item: (item.priority, item.name)
        )
        rounded_goal_amounts[highest_priority_goal] += goal_residual

    goal_allocations = [
        GoalAllocation(
            goal_id=goal.id,
            goal_name=goal.name,
            amount=amount,
            percentage=(amount * Decimal(100) / deployable if deployable else ZERO).quantize(
                Decimal("0.01")
            ),
            rationale=(
                f"Priority {goal.priority}; "
                f"{goal.monthly_contribution} {goal.target_currency.value}/month planned"
            ),
        )
        for goal, amount in rounded_goal_amounts.items()
    ]
    near_term_goal_amount = ZERO
    warnings: list[str] = []
    for goal, amount in rounded_goal_amounts.items():
        days_to_goal = (
            (goal.target_date - date.today()).days if goal.target_date is not None else None
        )
        is_short_horizon_purchase = (
            goal.goal_type == GoalType.PURCHASE and days_to_goal is not None and days_to_goal <= 730
        )
        if goal.goal_type in {GoalType.PRESERVATION, GoalType.DEBT_REPAYMENT} or (
            is_short_horizon_purchase
        ):
            near_term_goal_amount += amount
        if days_to_goal is not None and days_to_goal < 1095 and goal.risk_level == RiskLevel.HIGH:
            warnings.append(
                f"{goal.name} has a short deadline for its selected high-risk profile; "
                "review suitability."
            )

    investable = max(ZERO, deployable - near_term_goal_amount)
    holding_rows = session.execute(
        select(Holding, Instrument)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .where(Holding.user_id == user.id)
    ).all()
    latest_quotes: dict[uuid.UUID, MarketPriceCache] = {}
    for quote in session.scalars(
        select(MarketPriceCache).order_by(MarketPriceCache.observed_at.desc())
    ):
        latest_quotes.setdefault(quote.instrument_id, quote)
    current_values = {asset_class.value: ZERO for asset_class in AssetClass}
    for holding, instrument in holding_rows:
        quote = latest_quotes.get(instrument.id)
        if quote is None:
            continue
        native_value = holding.quantity * quote.price
        current_values[instrument.asset_class.value] += _to_base(
            native_value, quote.currency, base_currency, fx
        )

    target_weights = _target_weights(policy)
    try:
        asset_amounts = rebalance_with_contribution(current_values, target_weights, investable)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    pre_contribution_total = sum(current_values.values(), ZERO)
    post_total = pre_contribution_total + investable
    rounded_asset_amounts = {key: round_money(amount) for key, amount in asset_amounts.items()}
    asset_residual = round_money(investable) - sum(rounded_asset_amounts.values(), ZERO)
    if rounded_asset_amounts:
        largest_allocation = max(rounded_asset_amounts, key=rounded_asset_amounts.get)
        rounded_asset_amounts[largest_allocation] += asset_residual
    asset_allocations = []
    for asset_class in AssetClass:
        key = asset_class.value
        amount = rounded_asset_amounts.get(key, ZERO)
        post_weight = (current_values[key] + amount) / post_total if post_total else ZERO
        current_weight = (
            current_values[key] / pre_contribution_total if pre_contribution_total else ZERO
        )
        rationale = (
            "Below target; fresh cash moves the portfolio toward policy."
            if current_weight < target_weights[key]
            else "At or above target; buy-only allocation limits further drift."
        )
        asset_allocations.append(
            BucketAllocation(
                asset_class=asset_class,
                amount=amount,
                target_weight=target_weights[key],
                current_value=round_money(current_values[key]),
                post_contribution_weight=(post_weight * Decimal(100)).quantize(Decimal("0.01")),
                rationale=rationale,
            )
        )

    passive_goals = [goal for goal in goals if goal.goal_type == GoalType.PASSIVE_INCOME]
    passive_income_target = max(
        (
            _to_base(goal.target_annual_income or ZERO, goal.target_currency, base_currency, fx)
            for goal in passive_goals
        ),
        default=ZERO,
    )
    estimated_current_income = dashboard(session, base_currency)["totals"][
        "estimated_monthly_income"
    ] * Decimal(12)
    passive_income_gap = max(ZERO, passive_income_target - estimated_current_income)
    if passive_income_gap:
        warnings.append(
            "Passive-income goal remains a separate objective; allocation weights are not "
            "optimized for yield."
        )
    if not goals:
        warnings.append("Create at least one goal to receive goal-specific funding breakdowns.")
    warnings.extend(
        [
            (
                "This is a deterministic, buy-only preview using sample marks; "
                "it is not investment advice or an order."
            ),
            ("Goal progress values are illustrative and are not linked to specific holdings."),
        ]
    )

    snapshot = {
        "reserve_top_up": str(round_money(reserve_top_up)),
        "deployable_amount": str(round_money(deployable)),
        "near_term_goal_amount": str(round_money(near_term_goal_amount)),
        "investable_amount": str(round_money(investable)),
        "target_weights": {key: str(value) for key, value in target_weights.items()},
        "goal_allocations": [
            {"goal_id": str(line.goal_id), "amount": str(line.amount)} for line in goal_allocations
        ],
        "asset_allocations": [
            {"asset_class": line.asset_class.value, "amount": str(line.amount)}
            for line in asset_allocations
        ],
    }
    recommendation = Recommendation(
        user_id=user.id,
        input_amount=request.amount,
        input_currency=request.currency,
        base_currency=base_currency,
        funding_rule=policy.funding_rule,
        result_snapshot=snapshot,
        created_at=now,
    )
    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)

    return RecommendationResponse(
        id=recommendation.id,
        status="PREVIEW_ONLY",
        input_amount=request.amount,
        input_currency=request.currency,
        base_currency=base_currency,
        funding_rule=policy.funding_rule,
        reserve_top_up=round_money(reserve_top_up),
        deployable_amount=round_money(deployable),
        retained_for_near_term_goals=round_money(near_term_goal_amount),
        investable_amount=round_money(investable),
        passive_income_gap=round_money(passive_income_gap),
        goal_allocations=goal_allocations,
        asset_allocations=asset_allocations,
        warnings=warnings,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        explanation=(
            "Cash is reserved first, then divided using your selected goal rule. "
            "Only the remaining amount is routed toward portfolio target weights. "
            "Near-term purchases, debt repayment, and capital-preservation goals are kept out "
            "of the investment allocation."
        ),
    )
