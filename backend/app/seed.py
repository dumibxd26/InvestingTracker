import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.calculations import fixed_deposit_value, generate_vesting_schedule, round_money
from app.models import (
    AccountType,
    AllocationPolicy,
    AssetClass,
    BrokerAccount,
    CashFlow,
    CompoundingFrequency,
    Currency,
    FixedDeposit,
    FlowKind,
    FlowStatus,
    FundingRule,
    FXRate,
    Goal,
    GoalType,
    GrantType,
    Holding,
    Instrument,
    MarketPriceCache,
    RateBasis,
    RiskLevel,
    TrancheStatus,
    User,
    ValuationSnapshot,
    VestingGrant,
    VestingTranche,
)

SAMPLE_USER_ID = uuid.UUID("95c9d74b-24aa-4c82-b13c-3fc45412c5c6")


def seed_demo_data(session: Session, user_id: uuid.UUID = SAMPLE_USER_ID) -> None:
    if session.get(User, user_id) is not None:
        return

    today = date.today()
    now = datetime.now(UTC)
    user = User(id=user_id, display_name="Demo Portfolio", base_currency=Currency.EUR)
    brokerage = BrokerAccount(
        user_id=user_id,
        provider_code="SAMPLE",
        display_name="Brokerage · sample",
        account_type=AccountType.BROKERAGE,
        currency=Currency.EUR,
        cash_balance=Decimal("6200"),
    )
    bank = BrokerAccount(
        user_id=user_id,
        provider_code="SAMPLE",
        display_name="Everyday cash · sample",
        account_type=AccountType.BANK,
        currency=Currency.EUR,
        cash_balance=Decimal("4300"),
    )
    usd_brokerage = BrokerAccount(
        user_id=user_id,
        provider_code="SAMPLE",
        display_name="USD brokerage · sample",
        account_type=AccountType.BROKERAGE,
        currency=Currency.USD,
        cash_balance=Decimal("2100"),
    )
    savings = BrokerAccount(
        user_id=user_id,
        provider_code="SAMPLE",
        display_name="Term deposit · sample",
        account_type=AccountType.SAVINGS,
        currency=Currency.EUR,
        cash_balance=Decimal("0"),
    )

    global_equity = Instrument(
        symbol="DEMO-GLBL",
        name="Global equity fund · sample",
        asset_class=AssetClass.EQUITIES,
        currency=Currency.EUR,
        mic="XDEM",
        estimated_annual_yield=Decimal("0.018"),
    )
    bond_fund = Instrument(
        symbol="DEMO-BOND",
        name="Investment-grade bond fund · sample",
        asset_class=AssetClass.FIXED_INCOME,
        currency=Currency.EUR,
        mic="XDEM",
        estimated_annual_yield=Decimal("0.032"),
    )
    employer_stock = Instrument(
        symbol="DEMO-CO",
        name="Employer stock · sample",
        asset_class=AssetClass.SATELLITE,
        currency=Currency.USD,
        mic="XDEM",
        estimated_annual_yield=Decimal("0.004"),
    )

    session.add(user)
    session.flush()
    session.add_all([brokerage, bank, usd_brokerage, savings])
    session.flush()
    session.add_all([global_equity, bond_fund, employer_stock])
    session.flush()

    session.add_all(
        [
            Holding(
                user_id=user_id,
                account_id=brokerage.id,
                instrument_id=global_equity.id,
                quantity=Decimal("86"),
                average_cost=Decimal("112.50"),
            ),
            Holding(
                user_id=user_id,
                account_id=brokerage.id,
                instrument_id=bond_fund.id,
                quantity=Decimal("230"),
                average_cost=Decimal("5.10"),
            ),
            Holding(
                user_id=user_id,
                account_id=usd_brokerage.id,
                instrument_id=employer_stock.id,
                quantity=Decimal("44"),
                average_cost=Decimal("142.00"),
            ),
        ]
    )
    session.add_all(
        [
            MarketPriceCache(
                instrument_id=global_equity.id,
                price=Decimal("136.20"),
                currency=Currency.EUR,
                source="SAMPLE_DATA",
                feed_type="SAMPLE",
                observed_at=now,
            ),
            MarketPriceCache(
                instrument_id=bond_fund.id,
                price=Decimal("5.04"),
                currency=Currency.EUR,
                source="SAMPLE_DATA",
                feed_type="SAMPLE",
                observed_at=now,
            ),
            MarketPriceCache(
                instrument_id=employer_stock.id,
                price=Decimal("182.60"),
                currency=Currency.USD,
                source="SAMPLE_DATA",
                feed_type="SAMPLE",
                observed_at=now,
            ),
            FXRate(
                base_currency=Currency.EUR,
                quote_currency=Currency.USD,
                rate=Decimal("1.0800000000"),
                source="SAMPLE_DATA",
                observed_at=now,
            ),
        ]
    )

    deposit_start = today - timedelta(days=150)
    maturity_date = today + timedelta(days=210)
    deposit = FixedDeposit(
        user_id=user_id,
        account_id=savings.id,
        name="12-month fixed deposit · sample",
        principal=Decimal("15000"),
        currency=Currency.EUR,
        annual_rate=Decimal("0.033"),
        rate_basis=RateBasis.NOMINAL_APR,
        compounding=CompoundingFrequency.MONTHLY,
        start_date=deposit_start,
        maturity_date=maturity_date,
    )
    session.add(deposit)

    salary_month = today.month + 1
    salary_year = today.year + (salary_month - 1) // 12
    salary_month = (salary_month - 1) % 12 + 1
    salary_date = date(salary_year, salary_month, min(today.day, 28))
    bonus_date = date(today.year + 1, 2, 15)
    session.add_all(
        [
            CashFlow(
                user_id=user_id,
                account_id=bank.id,
                label="Monthly salary · forecast",
                kind=FlowKind.SALARY,
                status=FlowStatus.FORECAST,
                amount=Decimal("5400"),
                currency=Currency.EUR,
                expected_date=salary_date,
            ),
            CashFlow(
                user_id=user_id,
                account_id=bank.id,
                label="Annual bonus · forecast",
                kind=FlowKind.BONUS,
                status=FlowStatus.FORECAST,
                amount=Decimal("8500"),
                currency=Currency.EUR,
                expected_date=bonus_date,
            ),
            CashFlow(
                user_id=user_id,
                account_id=brokerage.id,
                label="Distribution received · sample",
                kind=FlowKind.DIVIDEND,
                status=FlowStatus.CONFIRMED,
                amount=Decimal("72.55"),
                currency=Currency.EUR,
                occurred_at=now - timedelta(days=7),
            ),
        ]
    )

    grant = VestingGrant(
        user_id=user_id,
        instrument_id=employer_stock.id,
        grant_type=GrantType.RSU,
        grant_date=today - timedelta(days=730),
        total_units=Decimal("160"),
        tax_rate_assumption=Decimal("0.32"),
    )
    session.add(grant)
    session.flush()
    schedule = generate_vesting_schedule(
        total_units=grant.total_units,
        grant_date=grant.grant_date,
        duration_months=48,
        cliff_months=12,
        interval_months=3,
    )
    session.add_all(
        [
            VestingTranche(
                grant_id=grant.id,
                vest_date=vest_date,
                available_date=vest_date + timedelta(days=2),
                units=units,
                status=TrancheStatus.RELEASED if vest_date <= today else TrancheStatus.SCHEDULED,
            )
            for vest_date, units in schedule
        ]
    )

    wealth_goal = Goal(
        user_id=user_id,
        name="Long-term wealth",
        goal_type=GoalType.WEALTH,
        target_amount=Decimal("300000"),
        target_annual_income=None,
        current_amount=Decimal("42000"),
        current_annual_income=Decimal("0"),
        target_currency=Currency.EUR,
        target_date=today.replace(year=today.year + 15),
        priority=1,
        risk_level=RiskLevel.MODERATE,
        monthly_contribution=Decimal("600"),
        fixed_percent=Decimal("0.60"),
        flexibility="flexible",
    )
    home_goal = Goal(
        user_id=user_id,
        name="Home deposit",
        goal_type=GoalType.PURCHASE,
        target_amount=Decimal("65000"),
        target_annual_income=None,
        current_amount=Decimal("20000"),
        current_annual_income=Decimal("0"),
        target_currency=Currency.EUR,
        target_date=today.replace(year=today.year + 4),
        priority=2,
        risk_level=RiskLevel.LOW,
        monthly_contribution=Decimal("500"),
        fixed_percent=Decimal("0.30"),
        flexibility="essential",
    )
    income_goal = Goal(
        user_id=user_id,
        name="Passive income",
        goal_type=GoalType.PASSIVE_INCOME,
        target_amount=None,
        target_annual_income=Decimal("12000"),
        current_amount=Decimal("0"),
        current_annual_income=Decimal("2900"),
        target_currency=Currency.EUR,
        target_date=today.replace(year=today.year + 12),
        priority=3,
        risk_level=RiskLevel.MODERATE,
        monthly_contribution=Decimal("200"),
        fixed_percent=Decimal("0.10"),
        flexibility="flexible",
    )
    session.add_all(
        [
            wealth_goal,
            home_goal,
            income_goal,
            AllocationPolicy(
                user_id=user_id,
                funding_rule=FundingRule.PRIORITY_FIRST,
                emergency_reserve=Decimal("9000"),
                target_weights={
                    "equities": "0.70",
                    "fixed_income": "0.15",
                    "satellite": "0.15",
                },
                updated_at=now,
            ),
        ]
    )
    session.flush()

    invested_value = (
        Decimal("86") * Decimal("136.20")
        + Decimal("230") * Decimal("5.04")
        + Decimal("44") * Decimal("182.60") / Decimal("1.08")
    )
    cash_value = Decimal("6200") + Decimal("4300") + Decimal("2100") / Decimal("1.08")
    deposit_value = fixed_deposit_value(
        deposit.principal,
        deposit.annual_rate,
        deposit.start_date,
        today,
        deposit.compounding,
        deposit.rate_basis,
    )
    unvested_units = sum(
        (units for vest_date, units in schedule if vest_date + timedelta(days=2) > today),
        Decimal("0"),
    )
    unvested_value = unvested_units * Decimal("182.60") / Decimal("1.08")
    current_net_worth = round_money(invested_value + cash_value + deposit_value + unvested_value)
    history_factors = [
        Decimal("0.91"),
        Decimal("0.93"),
        Decimal("0.955"),
        Decimal("0.94"),
        Decimal("0.975"),
        Decimal("1"),
    ]
    for months_ago, factor in enumerate(history_factors[::-1]):
        session.add(
            ValuationSnapshot(
                user_id=user_id,
                total_value=round_money(current_net_worth * factor),
                currency=Currency.EUR,
                observed_at=now - timedelta(days=30 * months_ago),
                is_synthetic=True,
            )
        )

    session.commit()
