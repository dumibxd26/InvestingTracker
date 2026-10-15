from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from typing import Any


def validate_schedules(
    monthly_contributions: tuple[float, ...] | None,
    inflation_factors: tuple[float, ...] | None,
) -> None:
    """Validate nominal month-end deposits and positive today-relative price indices."""
    if monthly_contributions is not None and any(
        not math.isfinite(value) or value < 0 for value in monthly_contributions
    ):
        raise ValueError("monthly_contributions must contain finite nonnegative amounts")
    if inflation_factors is not None:
        if not inflation_factors or inflation_factors[0] != 1.0:
            raise ValueError("inflation_factors must start with 1.0 at month zero")
        if any(not math.isfinite(value) or value <= 0 for value in inflation_factors):
            raise ValueError("inflation_factors must contain finite positive factors")


@dataclass(frozen=True)
class TaxLot:
    lot_id: str
    purchase_date: date
    units: float
    cost_basis_per_unit: float
    purchase_fx_rate_to_goal: float


@dataclass
class Holding:
    holding_id: str
    ticker: str
    name: str
    asset_class: str
    total_units: float
    current_price: float
    trading_currency: str
    underlying_currency: str
    is_currency_hedged: bool
    tax_lots: list[TaxLot] = field(default_factory=list)
    sector: str | None = None
    beta: float | None = None
    custom_yield: float | None = None
    dividend_yield: float | None = None
    distribution_tax_rate: float | None = None
    is_tax_advantaged: bool = False
    capital_gains_rate: float | None = None
    short_term_capital_gains_rate: float | None = None
    long_term_capital_gains_rate: float | None = None
    long_term_holding_period_days: int = 365


@dataclass(frozen=True)
class AllocatedHolding:
    holding: Holding
    allocated_percentage: float


@dataclass(frozen=True)
class TaxInflationProfile:
    annual_inflation_rate: float
    is_target_in_todays_dollars: bool = True
    index_contributions_to_inflation: bool = False
    short_term_cap_gains_rate: float = 0.03
    long_term_cap_gains_rate: float = 0.03
    dividend_and_interest_tax_rate: float = 0.10
    annual_tax_free_allowance: float = 0.0


@dataclass(frozen=True)
class GoalSpec:
    """A scalar savings plan or explicit nominal month-end deposits (month one at index zero).

    Inflation factors are relative to today: index zero is 1.0, index k is month k.
    Explicit schedules are never indexed again or extrapolated beyond supplied months.
    """

    goal_id: str
    name: str
    base_currency: str
    target_amount: float
    target_date: date
    monthly_contribution: float
    risk_profile: str
    tax_profile: TaxInflationProfile
    target_success_probability: float = 0.80
    monthly_contributions: tuple[float, ...] | None = None
    inflation_factors: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        validate_schedules(self.monthly_contributions, self.inflation_factors)


@dataclass
class EvaluatedSlice:
    holding_id: str
    ticker: str
    name: str
    asset_class: str
    macro_bucket: str
    allocated_percentage: float
    value_in_trading_currency: float
    market_value_in_goal: float
    cost_basis_in_goal: float
    after_tax_market_value: float
    local_expected_return: float
    local_volatility: float
    effective_return_in_goal: float
    effective_volatility_in_goal: float
    effective_dividend_yield: float
    fx_volatility_contribution: float
    is_unhedged_foreign_exposure: bool
    unhedged_fx_drift: float
    underlying_currency: str
    sector: str | None = None
    weight_in_goal: float = 0.0


@dataclass
class BucketDrift:
    bucket: str
    current_value: float
    current_weight: float
    target_weight: float
    drift: float
    dollar_delta_to_target: float
    is_breached: bool


@dataclass
class RiskWarning:
    holding_id: str
    ticker: str
    current_weight: float
    max_allowed_weight: float
    excess_dollar_amount: float
    reason: str
    message: str
    suggested_fix: str | None = None


@dataclass
class GoalEvaluation:
    goal_id: str
    base_currency: str
    remaining_years: float
    total_current_value: float
    total_cost_basis: float
    after_tax_value: float
    expected_return_mu: float
    weighted_local_return_mu: float
    weighted_dividend_yield: float
    weighted_local_volatility_sigma: float
    portfolio_volatility_sigma: float
    unhedged_foreign_weight: float
    unhedged_fx_drift: float
    median_compounding_rate: float
    sharpe_ratio: float
    max_single_stock_weight: float
    max_unhedged_fx_weight: float
    target_weights: dict[str, float]
    bucket_drifts: dict[str, BucketDrift]
    requires_rebalancing: bool
    warnings: list[RiskWarning]
    slices: list[EvaluatedSlice]


@dataclass
class LotDisposal:
    lot_id: str
    units_to_sell: float
    proceeds_in_goal_currency: float
    cost_basis_in_goal_currency: float
    realized_gain_or_loss: float
    is_long_term: bool
    applicable_tax_rate: float
    estimated_tax_due: float


@dataclass
class TaxTrimProposal:
    holding_id: str
    ticker: str
    gross_sell_amount: float
    total_realized_gain: float
    total_estimated_tax: float
    net_reinvestable_proceeds: float
    effective_tax_drag_pct: float
    recommendation_type: str
    rationale: str
    lot_disposals: list[LotDisposal]


@dataclass
class TickerProposal:
    ticker: str
    name: str
    asset_class: str
    action: str
    recommended_amount: float
    score: float
    rationale: str


@dataclass
class ContributionRouteItem:
    bucket: str
    allocated_contribution: float
    share_of_contribution: float
    post_contribution_weight: float
    target_weight: float
    suggested_tickers: list[TickerProposal]


@dataclass
class ProjectedImpact:
    previous_volatility: float
    new_volatility: float
    previous_median_return: float
    new_median_return: float
    summary_text: str


@dataclass
class RebalancePlan:
    goal_id: str
    monthly_contribution_routing: list[ContributionRouteItem]
    tax_aware_trim_proposals: list[TaxTrimProposal]
    rebalance_buy_proposals: list[TickerProposal]
    projected_impact: ProjectedImpact


@dataclass
class YearlyPercentileSchedulePoint:
    year: int
    nominal_after_tax: dict[str, float]
    real_todays_dollars: dict[str, float]
    inflated_target_at_year: float
    month_offset: int | None = None


@dataclass
class MonteCarloResult:
    success_probability: float
    nominal_target_at_maturity: float
    real_target_in_todays_dollars: float
    terminal_nominal_after_tax_p50: float
    terminal_real_todays_dollars_p10: float
    terminal_real_todays_dollars_p50: float
    terminal_real_todays_dollars_p90: float
    estimated_median_tax_paid_at_liquidation: float
    yearly_schedule: list[YearlyPercentileSchedulePoint]


@dataclass
class RecoveryLeverPlan:
    description: str
    resulting_success_probability: float


@dataclass
class ContributionLeverPlan(RecoveryLeverPlan):
    required_monthly_contribution: float = 0.0
    additional_monthly_needed: float = 0.0


@dataclass
class TimelineLeverPlan(RecoveryLeverPlan):
    additional_months_needed: int = 0
    new_target_date: str = ""


@dataclass
class PortfolioLeverPlan(RecoveryLeverPlan):
    optimal_expected_return: float = 0.0
    optimal_volatility: float = 0.0


@dataclass
class RecoveryPlans:
    increase_contribution_plan: ContributionLeverPlan | None = None
    extend_timeline_plan: TimelineLeverPlan | None = None
    optimize_portfolio_plan: PortfolioLeverPlan | None = None
    unreachable_levers: list[str] = field(default_factory=list)


@dataclass
class GoalRecovery:
    is_goal_on_track: bool
    current_success_probability: float
    target_success_probability: float
    plans: RecoveryPlans


@dataclass
class AnalyticalBands:
    expected_rate: float
    optimistic_rate: float
    conservative_rate: float
    projected_value_expected: float
    projected_value_optimistic: float
    projected_value_conservative: float
    months_remaining: int


@dataclass
class GoalInsights:
    goal: GoalSpec
    remaining_years: float
    evaluation: GoalEvaluation
    rebalance_plan: RebalancePlan
    simulation: MonteCarloResult
    recovery: GoalRecovery
    analytical_bands: AnalyticalBands
    assumptions: list[str]


def to_plain(value: Any) -> Any:
    """Convert engine dataclasses into JSON-ready dicts keyed by their field names."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_plain(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value
