from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    AccountType,
    AssetClass,
    CompoundingFrequency,
    Currency,
    FlowDirection,
    FlowKind,
    FlowStatus,
    FundingRule,
    GoalType,
    GrantType,
    RateBasis,
    Recurrence,
    RiskLevel,
)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, min_length=2, max_length=80)
    base_currency: Currency
    usd_per_eur: Decimal | None = Field(default=None, gt=0, le=100)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Display name must contain at least two non-whitespace characters")
        return normalized


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)
    base_currency: Currency
    usd_per_eur: Decimal | None = Field(default=None, gt=0, le=100)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Display name must contain at least two non-whitespace characters")
        return normalized


class UserProfileResponse(BaseModel):
    id: UUID
    username: str
    display_name: str
    base_currency: Currency
    usd_per_eur: Decimal | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserProfileResponse


class AccountCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)
    provider_code: str = Field(default="MANUAL", min_length=2, max_length=40)
    account_type: AccountType
    currency: Currency
    opening_cash: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    annual_interest_rate: Decimal | None = Field(default=None, ge=0, le=1)
    interest_start_date: date | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_account_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Account name must contain at least two non-whitespace characters")
        return normalized

    @field_validator("provider_code")
    @classmethod
    def normalize_provider_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or not normalized.replace("_", "").isalnum():
            raise ValueError("Provider code may contain letters, numbers, and underscores")
        return normalized

    @model_validator(mode="after")
    def validate_opening_cash(self) -> "AccountCreate":
        if self.account_type == AccountType.EMPLOYER_PLAN and self.opening_cash > 0:
            raise ValueError(
                "Employer-plan assets are tracked as holdings or grants, not available cash"
            )
        if (
            self.annual_interest_rate is not None
            and self.account_type == AccountType.EMPLOYER_PLAN
        ):
            raise ValueError("Employer-plan accounts cannot earn cash interest")
        return self


class AccountSubaccountSummary(BaseModel):
    id: UUID
    currency: Currency
    cash_balance: Decimal
    is_primary: bool
    annual_interest_rate: Decimal | None = None
    interest_start_date: date | None = None


class AccountSummary(BaseModel):
    id: UUID
    display_name: str
    provider_code: str
    account_type: AccountType
    currency: Currency
    cash_balance: Decimal
    position_count: int
    is_sample: bool
    subaccounts: list[AccountSubaccountSummary]


class AccountWealthSummary(BaseModel):
    id: UUID
    display_name: str
    account_type: AccountType
    currency: Currency
    cash_value: Decimal
    gross_holdings_value: Decimal
    estimated_sale_tax: Decimal
    after_tax_holdings_value: Decimal
    fixed_deposit_value: Decimal
    total_after_tax_value: Decimal


class AccountSubaccountCreate(BaseModel):
    currency: Currency
    opening_balance: Decimal = Field(
        default=Decimal("0"), ge=0, le=Decimal("100000000")
    )
    annual_interest_rate: Decimal | None = Field(default=None, ge=0, le=1)
    interest_start_date: date | None = None


class SubaccountInterestUpdate(BaseModel):
    annual_interest_rate: Decimal | None = Field(default=None, ge=0, le=1)
    interest_start_date: date | None = None


class InitialPortfolioSubaccount(BaseModel):
    currency: Currency
    opening_balance: Decimal = Field(
        default=Decimal("0"), ge=0, le=Decimal("100000000")
    )


class InitialPortfolioAccount(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)
    provider_code: str = Field(default="MANUAL", min_length=2, max_length=40)
    account_type: AccountType
    subaccounts: list[InitialPortfolioSubaccount] = Field(min_length=1, max_length=3)

    @field_validator("display_name")
    @classmethod
    def normalize_initial_account_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Account name must contain at least two non-whitespace characters")
        return normalized

    @field_validator("provider_code")
    @classmethod
    def normalize_initial_provider_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or not normalized.replace("_", "").isalnum():
            raise ValueError("Provider code may contain letters, numbers, and underscores")
        return normalized

    @model_validator(mode="after")
    def validate_initial_subaccounts(self) -> "InitialPortfolioAccount":
        currencies = [subaccount.currency for subaccount in self.subaccounts]
        if len(currencies) != len(set(currencies)):
            raise ValueError("An account can have only one sub-account per currency")
        if (
            self.account_type == AccountType.EMPLOYER_PLAN
            and any(subaccount.opening_balance > 0 for subaccount in self.subaccounts)
        ):
            raise ValueError("Employer-plan accounts cannot have cash sub-account balances")
        return self


class InitialPortfolioHolding(BaseModel):
    account_index: int = Field(ge=0, le=19)
    symbol: str = Field(min_length=1, max_length=24)
    mic_code: str | None = Field(default=None, max_length=8)
    exchange: str | None = Field(default=None, max_length=80)
    instrument_type: Literal["STOCK", "ETF"]
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"))
    average_cost: Decimal = Field(gt=0, le=Decimal("100000000"))
    average_cost_currency: Currency | None = None
    purchase_date: date = date(2025, 1, 1)
    risk_tier: Literal["X", "Y", "Z"] | None = None
    expected_annual_return: Decimal | None = Field(
        default=None, gt=Decimal("-1"), le=Decimal("1")
    )


class InitialPortfolioRequest(BaseModel):
    accounts: list[InitialPortfolioAccount] = Field(min_length=1, max_length=20)
    holdings: list[InitialPortfolioHolding] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_account_references(self) -> "InitialPortfolioRequest":
        names = [account.display_name.casefold() for account in self.accounts]
        if len(names) != len(set(names)):
            raise ValueError("Account names must be unique in the initial setup")
        for holding in self.holdings:
            if holding.account_index >= len(self.accounts):
                raise ValueError("A holding references an account that does not exist")
            account = self.accounts[holding.account_index]
            if account.account_type == AccountType.SAVINGS:
                raise ValueError("Stocks and ETFs cannot belong to a savings account")
        return self


class GoalCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    goal_type: GoalType
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_annual_income: Decimal | None = Field(default=None, gt=0)
    current_amount: Decimal = Field(default=Decimal("0"), ge=0)
    current_annual_income: Decimal = Field(default=Decimal("0"), ge=0)
    target_currency: Currency = Currency.EUR
    target_date: date | None = None
    priority: int = Field(ge=1, le=10)
    risk_level: RiskLevel
    monthly_contribution: Decimal = Field(ge=0)
    visualization_budget_amount: Decimal | None = Field(default=None, ge=0)
    visualization_budget_period: Literal["monthly", "yearly"] | None = None
    fixed_percent: Decimal | None = Field(default=None, ge=0, le=1)
    flexibility: str = Field(pattern="^(essential|flexible)$")
    linked_account_ids: list[UUID] = Field(default_factory=list, max_length=20)
    holding_ids: list[UUID] = Field(default_factory=list, max_length=100)
    fixed_deposit_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_target(self) -> "GoalCreate":
        if self.target_amount is None and self.target_annual_income is None:
            raise ValueError("Set a target amount or an annual income target")
        if self.goal_type == GoalType.PASSIVE_INCOME and self.target_annual_income is None:
            raise ValueError("Passive income goals need a target annual income")
        if (self.visualization_budget_amount is None) != (
            self.visualization_budget_period is None
        ):
            raise ValueError(
                "A visualization budget needs both an amount and a monthly/yearly period"
            )
        for values, label in (
            (self.linked_account_ids, "linked account"),
            (self.holding_ids, "stock or ETF"),
            (self.fixed_deposit_ids, "deposit"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"A {label} can only be selected once")
        return self


class GoalUpdate(GoalCreate):
    pass


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    goal_type: GoalType
    target_amount: Decimal | None
    target_annual_income: Decimal | None
    current_amount: Decimal
    current_annual_income: Decimal
    target_currency: Currency
    target_date: date | None
    priority: int
    risk_level: RiskLevel
    monthly_contribution: Decimal
    visualization_budget_amount: Decimal | None
    visualization_budget_period: Literal["monthly", "yearly"] | None
    fixed_percent: Decimal | None
    flexibility: str
    is_active: bool
    linked_account_ids: list[UUID]
    holding_ids: list[UUID]
    fixed_deposit_ids: list[UUID]


class FixedShare(BaseModel):
    goal_id: UUID
    percentage: Decimal = Field(ge=0, le=1)


class FixedSharesUpdate(BaseModel):
    shares: list[FixedShare] = Field(min_length=1, max_length=30)


class PolicyUpdate(BaseModel):
    funding_rule: FundingRule
    emergency_reserve: Decimal = Field(ge=0)
    target_weights: dict[AssetClass, Decimal]

    @field_validator("target_weights")
    @classmethod
    def normalize_bucket_keys(cls, value: dict[AssetClass, Decimal]) -> dict[AssetClass, Decimal]:
        if set(value) != set(AssetClass):
            raise ValueError("Provide target weights for equities, fixed income, and satellite")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("Target weights cannot be negative")
        if sum(value.values(), Decimal("0")) != Decimal("1"):
            raise ValueError("Target weights must sum to 100%")
        return value


class PolicyResponse(BaseModel):
    funding_rule: FundingRule | None
    emergency_reserve: Decimal
    target_weights: dict[str, Decimal]


class RecommendationRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    currency: Currency


class GoalAllocation(BaseModel):
    goal_id: UUID
    goal_name: str
    amount: Decimal
    percentage: Decimal
    rationale: str


class BucketAllocation(BaseModel):
    asset_class: AssetClass
    amount: Decimal
    target_weight: Decimal
    current_value: Decimal
    post_contribution_weight: Decimal
    rationale: str


class RecommendationResponse(BaseModel):
    id: UUID
    status: str
    input_amount: Decimal
    input_currency: Currency
    base_currency: Currency
    funding_rule: FundingRule
    reserve_top_up: Decimal
    deployable_amount: Decimal
    retained_for_near_term_goals: Decimal
    investable_amount: Decimal
    passive_income_gap: Decimal
    goal_allocations: list[GoalAllocation]
    asset_allocations: list[BucketAllocation]
    warnings: list[str]
    created_at: datetime
    expires_at: datetime
    explanation: str


class FlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    kind: FlowKind
    direction: FlowDirection
    status: FlowStatus
    amount: Decimal
    currency: Currency
    expected_date: date | None
    occurred_at: datetime | None
    reporting_amount: Decimal | None = None
    reporting_currency: Currency | None = None
    schedule_id: UUID | None = None
    recurrence: Recurrence | None = None
    automatically_posted: bool = False


class CashFlowScheduleCreate(BaseModel):
    label: str = Field(min_length=2, max_length=100)
    kind: FlowKind
    amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    currency: Currency
    recurrence: Recurrence
    start_date: date
    end_date: date | None = None
    account_id: UUID | None = None
    subaccount_id: UUID | None = None
    auto_post: bool = False

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Label must contain at least two non-whitespace characters")
        return normalized

    @model_validator(mode="after")
    def validate_schedule(self) -> "CashFlowScheduleCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Schedule end date cannot be before its start date")
        if self.recurrence == Recurrence.ONE_TIME and self.end_date is not None:
            raise ValueError("A one-time cash flow cannot have a recurring end date")
        if self.auto_post:
            if self.kind not in {FlowKind.SALARY, FlowKind.BONUS}:
                raise ValueError("Only salary and bonus schedules can automatically credit cash")
            if self.account_id is None or self.subaccount_id is None:
                raise ValueError("Automatic credits require a destination account and wallet")
            if self.start_date < date.today():
                raise ValueError("An automatic income schedule cannot start in the past")
        return self


class CashFlowScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    kind: FlowKind
    amount: Decimal
    currency: Currency
    recurrence: Recurrence
    start_date: date
    end_date: date | None
    is_active: bool
    account_id: UUID | None
    subaccount_id: UUID | None
    auto_post: bool


class CashReceiptCreate(BaseModel):
    account_id: UUID
    subaccount_id: UUID | None = None
    source: str = Field(min_length=2, max_length=100)
    amount: Decimal = Field(gt=0, le=Decimal("100000000"), max_digits=20, decimal_places=2)
    received_date: date
    idempotency_key: UUID

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Source must contain at least two non-whitespace characters")
        return normalized


class GoalSummary(BaseModel):
    id: UUID
    name: str
    goal_type: GoalType
    target_amount: Decimal | None
    target_annual_income: Decimal | None
    current_amount: Decimal
    linked_asset_value: Decimal
    current_annual_income: Decimal
    currency: Currency
    progress_percent: Decimal
    target_date: date | None
    priority: int
    risk_level: RiskLevel
    monthly_contribution: Decimal
    visualization_budget_amount: Decimal | None
    visualization_budget_period: Literal["monthly", "yearly"] | None
    fixed_percent: Decimal | None
    flexibility: str
    linked_account_ids: list[UUID]
    holding_ids: list[UUID]
    fixed_deposit_ids: list[UUID]


class HoldingSummary(BaseModel):
    id: UUID
    account_id: UUID
    assigned_goal_id: UUID | None = None
    assigned_goal_name: str | None = None
    symbol: str
    name: str
    account_name: str
    exchange: str
    mic_code: str
    asset_class: AssetClass
    instrument_type: Literal["STOCK", "ETF"]
    quantity: Decimal
    average_cost: Decimal
    purchase_date: date
    risk_tier: Literal["X", "Y", "Z"]
    expected_annual_return: Decimal
    funding_currency: Currency | None
    funding_cost: Decimal
    price: Decimal
    price_currency: Currency
    quote_source: str
    quote_observed_at: datetime
    is_market_open: bool | None
    change_since_refresh_percent: Decimal | None
    market_value: Decimal
    gross_market_value: Decimal
    cost_basis_value: Decimal
    estimated_gain: Decimal
    estimated_gain_percent: Decimal
    estimated_sale_tax: Decimal
    estimated_tax_rate: Decimal
    base_currency: Currency
    is_demo: bool


class MarketSymbolSearchResult(BaseModel):
    symbol: str
    name: str
    exchange: str
    mic_code: str | None
    currency: Currency
    instrument_type: Literal["STOCK", "ETF"]
    country: str


class MarketSymbolSearchResponse(BaseModel):
    results: list[MarketSymbolSearchResult]


class HoldingCreate(BaseModel):
    account_id: UUID
    subaccount_id: UUID
    symbol: str = Field(min_length=1, max_length=24)
    mic_code: str | None = Field(default=None, max_length=8)
    exchange: str | None = Field(default=None, max_length=80)
    instrument_type: Literal["STOCK", "ETF"]
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"))
    average_cost: Decimal = Field(gt=0, le=Decimal("100000000"))
    average_cost_currency: Currency | None = None
    purchase_date: date = Field(default_factory=date.today)
    risk_tier: Literal["X", "Y", "Z"] | None = None
    expected_annual_return: Decimal | None = Field(
        default=None, gt=Decimal("-1"), le=Decimal("1")
    )


class HoldingUpdate(BaseModel):
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"))
    average_cost: Decimal = Field(gt=0, le=Decimal("100000000"))
    average_cost_currency: Currency | None = None
    purchase_date: date | None = None
    risk_tier: Literal["X", "Y", "Z"] | None = None
    expected_annual_return: Decimal | None = Field(
        default=None, gt=Decimal("-1"), le=Decimal("1")
    )


class HoldingCreateResponse(BaseModel):
    symbol: str
    account_name: str
    quantity: Decimal
    quote_price: Decimal
    quote_currency: Currency
    funding_currency: Currency | None
    funding_cost: Decimal


class InitialPortfolioResponse(BaseModel):
    accounts: list[AccountSummary]
    holdings: list[HoldingCreateResponse]


class MarketFXRateSummary(BaseModel):
    base_currency: Currency
    quote_currency: Currency
    rate: Decimal
    provider: str
    observed_at: datetime
    change_percent: Decimal | None


class MarketDataStatusResponse(BaseModel):
    provider: str
    provider_configured: bool
    automatic_refresh_enabled: bool = False


class ProjectionAccountValue(BaseModel):
    account_id: UUID
    account_name: str
    current_value: Decimal
    projected_cash_value: Decimal
    projected_holdings_value: Decimal
    projected_deposit_value: Decimal
    projected_total_value: Decimal


class ProjectionPoint(BaseModel):
    date: date
    label: str
    total_value: Decimal
    accounts: list[ProjectionAccountValue]


class PortfolioProjectionResponse(BaseModel):
    base_currency: Currency
    as_of: datetime
    target_date: date
    current_net_worth: Decimal
    projected_net_worth: Decimal
    estimated_change: Decimal
    accounts: list[ProjectionAccountValue]
    timeline: list[ProjectionPoint]
    warnings: list[str]


class MarketRefreshResponse(BaseModel):
    updated_symbols: list[str]
    updated_fx_pairs: list[str]
    errors: list[str]


class AllocationSummary(BaseModel):
    asset_class: AssetClass
    value: Decimal
    percentage: Decimal
    target_percentage: Decimal


class ChartPoint(BaseModel):
    label: str
    date: date
    value: Decimal


class DepositSummary(BaseModel):
    id: UUID
    account_id: UUID
    source_subaccount_id: UUID | None
    assigned_goal_id: UUID | None
    assigned_goal_name: str | None
    name: str
    principal: Decimal
    accrued_interest: Decimal
    current_value: Decimal
    currency: Currency
    annual_rate: Decimal
    rate_basis: RateBasis
    compounding: CompoundingFrequency
    period_months: int
    start_date: date
    maturity_date: date
    days_to_maturity: int


class FixedDepositCreate(BaseModel):
    account_id: UUID
    subaccount_id: UUID
    name: str = Field(min_length=2, max_length=80)
    principal: Decimal = Field(gt=0, le=Decimal("100000000"))
    start_date: date
    period_months: int = Field(ge=1, le=1200)
    annual_profit_rate: Decimal = Field(ge=0, le=1)
    capitalization: bool = False

    @field_validator("name")
    @classmethod
    def normalize_deposit_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Deposit name must contain at least two non-whitespace characters")
        return normalized

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Deposit start date cannot be in the future")
        return value


class FixedDepositCreateResponse(BaseModel):
    id: UUID
    name: str
    principal: Decimal
    currency: Currency
    start_date: date
    maturity_date: date
    period_months: int
    annual_rate: Decimal
    capitalization: bool


class VestingTrancheSummary(BaseModel):
    vest_date: date
    available_date: date
    units: Decimal
    status: str


class VestingTrancheCreate(BaseModel):
    vest_date: date
    units: Decimal = Field(gt=0, le=Decimal("1000000000"))


class VestingSummary(BaseModel):
    id: UUID
    symbol: str
    name: str
    grant_type: GrantType
    grant_label: str | None
    grant_date: date | None
    total_units: Decimal
    units: Decimal
    vested_units: Decimal
    vested_percent: Decimal
    next_vest_date: date | None
    strike_price: Decimal | None
    strike_currency: Currency | None
    tax_rate_assumption: Decimal
    short_term_sale_tax_rate: Decimal
    long_term_sale_tax_rate: Decimal
    long_term_holding_period_days: int
    gross_value: Decimal
    estimated_net_value: Decimal
    estimated_short_term_sale_value: Decimal
    estimated_long_term_sale_value: Decimal
    currency: Currency
    price: Decimal | None
    price_currency: Currency | None
    quote_source: str | None
    quote_observed_at: datetime | None
    tranches: list[VestingTrancheSummary]


class VestingGrantCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    mic_code: str | None = Field(default=None, max_length=8)
    exchange: str | None = Field(default=None, max_length=80)
    grant_type: GrantType
    grant_label: str | None = Field(default=None, max_length=80)
    grant_date: date | None = None
    total_units: Decimal = Field(gt=0, le=Decimal("1000000000"))
    duration_months: int | None = Field(default=None, ge=1, le=600)
    cliff_months: int | None = Field(default=None, ge=0, le=600)
    interval_months: int | None = Field(default=None, ge=1, le=60)
    tranches: list[VestingTrancheCreate] | None = Field(default=None, min_length=1, max_length=100)
    strike_price: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))
    tax_rate_assumption: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    short_term_sale_tax_rate: Decimal = Field(default=Decimal("0.06"), ge=0, le=1)
    long_term_sale_tax_rate: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    long_term_holding_period_days: int = Field(default=365, ge=1, le=36500)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("Symbol is required")
        return normalized

    @field_validator("grant_label")
    @classmethod
    def normalize_grant_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_grant(self) -> "VestingGrantCreate":
        if self.tranches:
            if sum((tranche.units for tranche in self.tranches), Decimal("0")) != self.total_units:
                raise ValueError("The tranche share amounts must sum to the total grant units")
            vest_dates = [tranche.vest_date for tranche in self.tranches]
            if len(vest_dates) != len(set(vest_dates)):
                raise ValueError("A grant can have only one tranche per vesting date")
            if self.grant_date is not None and any(
                vest_date < self.grant_date for vest_date in vest_dates
            ):
                raise ValueError("Vesting dates cannot be before the grant date")
        elif (
            self.grant_date is None
            or self.duration_months is None
            or self.cliff_months is None
            or self.interval_months is None
        ):
            raise ValueError("Enter a standard vesting duration, cliff, and interval")
        elif self.cliff_months > self.duration_months:
            raise ValueError("Cliff cannot exceed the vesting duration")
        if self.grant_type == GrantType.OPTION and self.strike_price is None:
            raise ValueError("Stock options require a strike price")
        if self.grant_type == GrantType.RSU and self.strike_price is not None:
            raise ValueError("RSUs do not have a strike price")
        return self


class StockSaleCreate(BaseModel):
    idempotency_key: UUID
    sell_date: date
    sell_price: Decimal = Field(gt=0, le=Decimal("100000000"))
    quantity: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"))


class StockSaleResponse(BaseModel):
    id: UUID
    symbol: str
    currency: Currency
    quantity: Decimal
    sell_price: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal
    sell_date: date
    credited_subaccount_id: UUID


class CashTransferCreate(BaseModel):
    idempotency_key: UUID
    source_subaccount_id: UUID
    destination_subaccount_id: UUID
    transfer_date: date
    source_amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    destination_amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))


class CashTransferResponse(BaseModel):
    id: UUID
    source_subaccount_id: UUID
    destination_subaccount_id: UUID
    source_account_name: str
    destination_account_name: str
    source_currency: Currency
    destination_currency: Currency
    source_amount: Decimal
    destination_amount: Decimal
    transfer_date: date


class StockPurchasePlanCreate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    symbol: str = Field(min_length=1, max_length=24)
    mic_code: str | None = Field(default=None, max_length=8)
    exchange: str | None = Field(default=None, max_length=80)
    account_id: UUID
    subaccount_id: UUID
    shares: Decimal = Field(gt=0, le=Decimal("1000000000"))
    purchase_date: date
    discount_rate: Decimal = Field(ge=0, lt=1)
    receipt_tax_rate: Decimal = Field(default=Decimal("0.45"), ge=0, le=1)
    sale_profit_tax_rate: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)
    reference_price: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))

    @field_validator("symbol")
    @classmethod
    def normalize_plan_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("Symbol is required")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_plan_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockPurchasePlanSummary(BaseModel):
    id: UUID
    name: str
    symbol: str
    instrument_name: str
    account_id: UUID
    account_name: str
    funding_currency: Currency
    shares: Decimal
    purchase_date: date
    discount_rate: Decimal
    receipt_tax_rate: Decimal
    sale_profit_tax_rate: Decimal
    status: Literal["scheduled", "executed"]
    price_currency: Currency
    market_price: Decimal
    purchase_price: Decimal
    price_is_estimate: bool
    reporting_currency: Currency
    market_value: Decimal
    purchase_cost: Decimal
    gross_discount_benefit: Decimal
    receipt_tax: Decimal
    net_benefit: Decimal
    holding_id: UUID | None


class DashboardResponse(BaseModel):
    base_currency: Currency
    profile: UserProfileResponse
    as_of: datetime
    sample_data: bool
    market_data_provider_configured: bool
    totals: dict[str, Decimal]
    six_month_change: Decimal
    six_month_change_percent: Decimal
    allocation: list[AllocationSummary]
    chart: list[ChartPoint]
    accounts: list[AccountSummary]
    account_wealth: list[AccountWealthSummary]
    holdings: list[HoldingSummary]
    market_fx_rates: list[MarketFXRateSummary]
    goals: list[GoalSummary]
    cash_flows: list[FlowResponse]
    cash_flow_schedules: list[CashFlowScheduleResponse]
    deposits: list[DepositSummary]
    vesting: list[VestingSummary]
    purchase_plans: list[StockPurchasePlanSummary] = Field(default_factory=list)
    warnings: list[str]
    policy: PolicyResponse


class ChatRequest(BaseModel):
    question: str = Field(min_length=4, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=8)

    @field_validator("history")
    @classmethod
    def validate_history(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        for message in value:
            if message.get("role") not in {"user", "assistant"}:
                raise ValueError("Chat history supports user and assistant messages only")
            content = message.get("content", "")
            if not content or len(content) > 2000:
                raise ValueError("Chat history messages must contain 1 to 2,000 characters")
        return value


class ChatResponse(BaseModel):
    answer: str
    model: str
    data_as_of: datetime
    used_context: list[str]


class ApiError(BaseModel):
    detail: str


class AuditRecommendationPayload(BaseModel):
    snapshot: dict[str, Any]
