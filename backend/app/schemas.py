from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    AccountType,
    AssetClass,
    Currency,
    FlowDirection,
    FlowKind,
    FlowStatus,
    FundingRule,
    GoalType,
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
        return self


class AccountSummary(BaseModel):
    id: UUID
    display_name: str
    provider_code: str
    account_type: AccountType
    currency: Currency
    cash_balance: Decimal
    position_count: int
    is_sample: bool


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
    fixed_percent: Decimal | None = Field(default=None, ge=0, le=1)
    flexibility: str = Field(pattern="^(essential|flexible)$")

    @model_validator(mode="after")
    def validate_target(self) -> "GoalCreate":
        if self.target_amount is None and self.target_annual_income is None:
            raise ValueError("Set a target amount or an annual income target")
        if self.goal_type == GoalType.PASSIVE_INCOME and self.target_annual_income is None:
            raise ValueError("Passive income goals need a target annual income")
        return self


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
    fixed_percent: Decimal | None
    flexibility: str
    is_active: bool


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


class CashFlowScheduleCreate(BaseModel):
    label: str = Field(min_length=2, max_length=100)
    kind: FlowKind
    amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    currency: Currency
    recurrence: Recurrence
    start_date: date
    end_date: date | None = None

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


class CashReceiptCreate(BaseModel):
    account_id: UUID
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
    current_annual_income: Decimal
    currency: Currency
    progress_percent: Decimal
    target_date: date | None
    priority: int
    risk_level: RiskLevel
    monthly_contribution: Decimal
    fixed_percent: Decimal | None
    flexibility: str


class HoldingSummary(BaseModel):
    id: UUID
    symbol: str
    name: str
    account_name: str
    asset_class: AssetClass
    instrument_type: Literal["STOCK", "ETF"]
    quantity: Decimal
    average_cost: Decimal
    price: Decimal
    price_currency: Currency
    quote_source: str
    quote_observed_at: datetime
    is_market_open: bool | None
    change_since_refresh_percent: Decimal | None
    market_value: Decimal
    base_currency: Currency
    change_percent: Decimal
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
    symbol: str = Field(min_length=1, max_length=24)
    mic_code: str | None = Field(default=None, max_length=8)
    exchange: str | None = Field(default=None, max_length=80)
    instrument_type: Literal["STOCK", "ETF"]
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"))
    average_cost: Decimal = Field(gt=0, le=Decimal("100000000"))


class HoldingUpdate(BaseModel):
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"))
    average_cost: Decimal = Field(gt=0, le=Decimal("100000000"))


class HoldingCreateResponse(BaseModel):
    symbol: str
    account_name: str
    quantity: Decimal
    quote_price: Decimal
    quote_currency: Currency


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
    name: str
    principal: Decimal
    accrued_interest: Decimal
    currency: Currency
    annual_rate: Decimal
    rate_basis: RateBasis
    maturity_date: date
    days_to_maturity: int


class VestingSummary(BaseModel):
    symbol: str
    name: str
    grant_type: str
    units: Decimal
    vested_percent: Decimal
    next_vest_date: date | None
    gross_value: Decimal
    estimated_net_value: Decimal
    currency: Currency


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
    holdings: list[HoldingSummary]
    market_fx_rates: list[MarketFXRateSummary]
    goals: list[GoalSummary]
    cash_flows: list[FlowResponse]
    cash_flow_schedules: list[CashFlowScheduleResponse]
    deposits: list[DepositSummary]
    vesting: list[VestingSummary]
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
