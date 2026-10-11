import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_cls]


class Currency(StrEnum):
    EUR = "EUR"
    USD = "USD"
    RON = "RON"


class AccountType(StrEnum):
    BROKERAGE = "BROKERAGE"
    BANK = "BANK"
    SAVINGS = "SAVINGS"
    EMPLOYER_PLAN = "EMPLOYER_PLAN"


class AssetClass(StrEnum):
    EQUITIES = "equities"
    FIXED_INCOME = "fixed_income"
    SATELLITE = "satellite"


class GoalType(StrEnum):
    WEALTH = "wealth"
    RETIREMENT = "retirement"
    PASSIVE_INCOME = "passive_income"
    PURCHASE = "purchase"
    PRESERVATION = "preservation"
    DEBT_REPAYMENT = "debt_repayment"
    CUSTOM = "custom"


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class FundingRule(StrEnum):
    PRIORITY_FIRST = "priority_first"
    PROPORTIONAL = "proportional"
    FIXED_PERCENTAGES = "fixed_percentages"


class FlowKind(StrEnum):
    SALARY = "salary"
    BONUS = "bonus"
    WINDFALL = "windfall"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    BILL = "bill"
    CONTRIBUTION = "contribution"


class FlowStatus(StrEnum):
    FORECAST = "forecast"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class FlowDirection(StrEnum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"
    TRANSFER = "transfer"


class Recurrence(StrEnum):
    ONE_TIME = "one_time"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class GrantType(StrEnum):
    RSU = "rsu"
    OPTION = "option"


class TrancheStatus(StrEnum):
    SCHEDULED = "scheduled"
    VESTED = "vested"
    RELEASED = "released"
    FORFEITED = "forfeited"


class CompoundingFrequency(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    AT_MATURITY = "at_maturity"


class RateBasis(StrEnum):
    NOMINAL_APR = "nominal_apr"
    EFFECTIVE_APY = "effective_apy"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    base_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"),
        nullable=False,
    )
    usd_per_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class BrokerAccount(Base):
    __tablename__ = "accounts_brokers"
    __table_args__ = (UniqueConstraint("user_id", "display_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SqlEnum(AccountType, values_callable=enum_values, name="account_type"), nullable=False
    )


class AccountSubaccount(Base):
    __tablename__ = "account_subaccounts"
    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_account_subaccounts_currency"),
        Index(
            "uq_account_subaccounts_primary",
            "account_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts_brokers.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "mic", name="uq_instruments_symbol_mic"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        SqlEnum(AssetClass, values_callable=enum_values, name="asset_class"), nullable=False
    )
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    mic: Mapped[str] = mapped_column(String(8), default="XNAS", nullable=False)
    exchange: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    instrument_type: Mapped[str] = mapped_column(
        String(16), default="STOCK", server_default="STOCK", nullable=False
    )
    estimated_annual_yield: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), default=Decimal("0"), nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id"),
        Index("ix_holdings_user_account", "user_id", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts_brokers.id", ondelete="CASCADE"), nullable=False
    )
    funding_subaccount_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account_subaccounts.id", ondelete="CASCADE"), nullable=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    purchase_date: Mapped[date] = mapped_column(
        Date,
        default=date(2025, 1, 1),
        server_default=text("'2025-01-01'"),
        nullable=False,
    )
    funding_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0"), nullable=False
    )
class MarketPriceCache(Base):
    __tablename__ = "market_prices_cache"
    __table_args__ = (Index("ix_market_prices_latest", "instrument_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    feed_type: Mapped[str] = mapped_column(String(20), default="SAMPLE", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    is_market_open: Mapped[bool | None] = mapped_column(Boolean)


class FXRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("base_currency", "quote_currency", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    quote_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class MarketFXRate(Base):
    __tablename__ = "market_fx_rates"
    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", "provider", "observed_at"),
        Index("ix_market_fx_latest", "base_currency", "quote_currency", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    quote_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    previous_rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))


class Goal(Base):
    __tablename__ = "financial_goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    goal_type: Mapped[GoalType] = mapped_column(
        SqlEnum(GoalType, values_callable=enum_values, name="goal_type"), nullable=False
    )
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    target_annual_income: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    current_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0"), nullable=False
    )
    current_annual_income: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0"), nullable=False
    )
    target_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    target_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        SqlEnum(RiskLevel, values_callable=enum_values, name="risk_level"), nullable=False
    )
    monthly_contribution: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0"), nullable=False
    )
    fixed_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    flexibility: Mapped[str] = mapped_column(String(16), default="flexible", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AllocationPolicy(Base):
    __tablename__ = "allocation_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    funding_rule: Mapped[FundingRule] = mapped_column(
        SqlEnum(FundingRule, values_callable=enum_values, name="funding_rule"), nullable=True
    )
    emergency_reserve: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0"), nullable=False
    )
    target_weights: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class CashFlowSchedule(Base):
    __tablename__ = "cash_flow_schedules"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_cash_flow_schedules_positive_amount"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_cash_flow_schedules_end_after_start",
        ),
        CheckConstraint(
            "NOT auto_post OR (kind IN ('salary', 'bonus') "
            "AND account_id IS NOT NULL AND subaccount_id IS NOT NULL)",
            name="ck_cash_flow_schedules_auto_post_destination",
        ),
        Index("ix_cash_flow_schedules_user_active", "user_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts_brokers.id", ondelete="SET NULL")
    )
    subaccount_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account_subaccounts.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[FlowKind] = mapped_column(
        SqlEnum(FlowKind, values_callable=enum_values, name="cash_flow_kind"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    recurrence: Mapped[Recurrence] = mapped_column(
        SqlEnum(Recurrence, values_callable=enum_values, name="cash_flow_recurrence"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_post: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class CashFlow(Base):
    __tablename__ = "cash_flows"
    __table_args__ = (
        UniqueConstraint("user_id", "source_system", "source_event_id"),
        Index("ix_cash_flows_user_expected", "user_id", "expected_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts_brokers.id", ondelete="SET NULL")
    )
    subaccount_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account_subaccounts.id", ondelete="SET NULL")
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cash_flow_schedules.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[FlowKind] = mapped_column(
        SqlEnum(FlowKind, values_callable=enum_values, name="cash_flow_kind"), nullable=False
    )
    status: Mapped[FlowStatus] = mapped_column(
        SqlEnum(FlowStatus, values_callable=enum_values, name="cash_flow_status"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    expected_date: Mapped[date | None] = mapped_column(Date)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_system: Mapped[str | None] = mapped_column(String(40))
    source_event_id: Mapped[str | None] = mapped_column(String(120))


class FixedDeposit(Base):
    __tablename__ = "fixed_deposits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts_brokers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    rate_basis: Mapped[RateBasis] = mapped_column(
        SqlEnum(RateBasis, values_callable=enum_values, name="rate_basis"), nullable=False
    )
    compounding: Mapped[CompoundingFrequency] = mapped_column(
        SqlEnum(
            CompoundingFrequency,
            values_callable=enum_values,
            name="compounding_frequency",
        ),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)


class VestingGrant(Base):
    __tablename__ = "vesting_grants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    grant_type: Mapped[GrantType] = mapped_column(
        SqlEnum(GrantType, values_callable=enum_values, name="grant_type"), nullable=False
    )
    grant_label: Mapped[str | None] = mapped_column(String(80))
    grant_date: Mapped[date | None] = mapped_column(Date)
    total_units: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    strike_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    strike_currency: Mapped[Currency | None] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code")
    )
    expiration_date: Mapped[date | None] = mapped_column(Date)
    tax_rate_assumption: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0"), nullable=False
    )
    short_term_sale_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0.06"), nullable=False
    )
    long_term_sale_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0.03"), nullable=False
    )
    long_term_holding_period_days: Mapped[int] = mapped_column(
        Integer, default=365, nullable=False
    )


class VestingTranche(Base):
    __tablename__ = "vesting_tranches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vesting_grants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vest_date: Mapped[date] = mapped_column(Date, nullable=False)
    available_date: Mapped[date] = mapped_column(Date, nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    status: Mapped[TrancheStatus] = mapped_column(
        SqlEnum(TrancheStatus, values_callable=enum_values, name="tranche_status"),
        default=TrancheStatus.SCHEDULED,
        nullable=False,
    )


class ValuationSnapshot(Base):
    __tablename__ = "valuation_snapshots"
    __table_args__ = (Index("ix_valuation_snapshot_user_time", "user_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    input_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    base_currency: Mapped[Currency] = mapped_column(
        SqlEnum(Currency, values_callable=enum_values, name="currency_code"), nullable=False
    )
    funding_rule: Mapped[FundingRule] = mapped_column(
        SqlEnum(FundingRule, values_callable=enum_values, name="funding_rule"), nullable=False
    )
    result_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
