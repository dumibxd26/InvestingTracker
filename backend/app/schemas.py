from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
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


class GoalCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    goal_type: GoalType
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_annual_income: Decimal | None = Field(default=None, gt=0)
    current_amount: Decimal = Field(default=Decimal("0"), ge=0)
    current_annual_income: Decimal = Field(default=Decimal("0"), ge=0)
    target_currency: Currency = Currency.EUR
    target_date: date | None = None
    priority: int = Field(default=3, ge=1, le=10)
    risk_level: RiskLevel = RiskLevel.MODERATE
    monthly_contribution: Decimal = Field(default=Decimal("0"), ge=0)
    fixed_percent: Decimal | None = Field(default=None, ge=0, le=1)
    flexibility: str = Field(default="flexible", pattern="^(essential|flexible)$")

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
    funding_rule: FundingRule
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
    symbol: str
    name: str
    account_name: str
    asset_class: AssetClass
    quantity: Decimal
    price: Decimal
    price_currency: Currency
    market_value: Decimal
    base_currency: Currency
    change_percent: Decimal
    is_demo: bool


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
    as_of: datetime
    sample_data: bool
    totals: dict[str, Decimal]
    six_month_change: Decimal
    six_month_change_percent: Decimal
    allocation: list[AllocationSummary]
    chart: list[ChartPoint]
    holdings: list[HoldingSummary]
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
