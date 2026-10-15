from __future__ import annotations

from pydantic import BaseModel


class TaxProfilePayload(BaseModel):
    annual_inflation_rate: float
    is_target_in_todays_dollars: bool
    index_contributions_to_inflation: bool
    short_term_cap_gains_rate: float
    long_term_cap_gains_rate: float
    dividend_and_interest_tax_rate: float
    annual_tax_free_allowance: float


class GoalPayload(BaseModel):
    goal_id: str
    name: str
    base_currency: str
    target_amount: float
    target_date: str
    monthly_contribution: float
    risk_profile: str
    target_success_probability: float
    tax_profile: TaxProfilePayload
    monthly_contributions: tuple[float, ...] | None = None
    inflation_factors: tuple[float, ...] | None = None


class SlicePayload(BaseModel):
    holding_id: str
    ticker: str
    name: str
    asset_class: str
    macro_bucket: str
    allocated_percentage: float
    value_in_trading_currency: float
    market_value_in_goal: float
    cost_basis_in_goal: float
    local_expected_return: float
    local_volatility: float
    effective_return_in_goal: float
    effective_volatility_in_goal: float
    effective_dividend_yield: float
    fx_volatility_contribution: float
    is_unhedged_foreign_exposure: bool
    unhedged_fx_drift: float
    underlying_currency: str
    sector: str | None
    weight_in_goal: float


class BucketDriftPayload(BaseModel):
    bucket: str
    current_value: float
    current_weight: float
    target_weight: float
    drift: float
    dollar_delta_to_target: float
    is_breached: bool


class RiskWarningPayload(BaseModel):
    holding_id: str
    ticker: str
    current_weight: float
    max_allowed_weight: float
    excess_dollar_amount: float
    reason: str
    message: str
    suggested_fix: str | None


class EvaluationPayload(BaseModel):
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
    bucket_drifts: dict[str, BucketDriftPayload]
    requires_rebalancing: bool
    warnings: list[RiskWarningPayload]
    slices: list[SlicePayload]


class TickerProposalPayload(BaseModel):
    ticker: str
    name: str
    asset_class: str
    action: str
    recommended_amount: float
    score: float
    rationale: str


class ContributionRoutePayload(BaseModel):
    bucket: str
    allocated_contribution: float
    share_of_contribution: float
    post_contribution_weight: float
    target_weight: float
    suggested_tickers: list[TickerProposalPayload]


class LotDisposalPayload(BaseModel):
    lot_id: str
    units_to_sell: float
    proceeds_in_goal_currency: float
    cost_basis_in_goal_currency: float
    realized_gain_or_loss: float
    is_long_term: bool
    applicable_tax_rate: float
    estimated_tax_due: float


class TaxTrimPayload(BaseModel):
    holding_id: str
    ticker: str
    gross_sell_amount: float
    total_realized_gain: float
    total_estimated_tax: float
    net_reinvestable_proceeds: float
    effective_tax_drag_pct: float
    recommendation_type: str
    rationale: str
    lot_disposals: list[LotDisposalPayload]


class ProjectedImpactPayload(BaseModel):
    previous_volatility: float
    new_volatility: float
    previous_median_return: float
    new_median_return: float
    summary_text: str


class RebalancePayload(BaseModel):
    goal_id: str
    monthly_contribution_routing: list[ContributionRoutePayload]
    tax_aware_trim_proposals: list[TaxTrimPayload]
    rebalance_buy_proposals: list[TickerProposalPayload]
    projected_impact: ProjectedImpactPayload


class YearlyPointPayload(BaseModel):
    year: int
    nominal_after_tax: dict[str, float]
    real_todays_dollars: dict[str, float]
    inflated_target_at_year: float
    month_offset: int | None = None


class SimulationPayload(BaseModel):
    success_probability: float
    nominal_target_at_maturity: float
    real_target_in_todays_dollars: float
    terminal_nominal_after_tax_p50: float
    terminal_real_todays_dollars_p10: float
    terminal_real_todays_dollars_p50: float
    terminal_real_todays_dollars_p90: float
    estimated_median_tax_paid_at_liquidation: float
    yearly_schedule: list[YearlyPointPayload]


class ContributionPlanPayload(BaseModel):
    description: str
    resulting_success_probability: float
    required_monthly_contribution: float
    additional_monthly_needed: float


class TimelinePlanPayload(BaseModel):
    description: str
    resulting_success_probability: float
    additional_months_needed: int
    new_target_date: str


class PortfolioPlanPayload(BaseModel):
    description: str
    resulting_success_probability: float
    optimal_expected_return: float
    optimal_volatility: float


class RecoveryPlansPayload(BaseModel):
    increase_contribution_plan: ContributionPlanPayload | None
    extend_timeline_plan: TimelinePlanPayload | None
    optimize_portfolio_plan: PortfolioPlanPayload | None
    unreachable_levers: list[str]


class RecoveryPayload(BaseModel):
    is_goal_on_track: bool
    current_success_probability: float
    target_success_probability: float
    plans: RecoveryPlansPayload


class AnalyticalBandsPayload(BaseModel):
    expected_rate: float
    optimistic_rate: float
    conservative_rate: float
    projected_value_expected: float
    projected_value_optimistic: float
    projected_value_conservative: float
    months_remaining: int


class GoalInsightsResponse(BaseModel):
    available: bool
    unavailable_reason: str | None = None
    goal: GoalPayload | None = None
    remaining_years: float | None = None
    evaluation: EvaluationPayload | None = None
    rebalance_plan: RebalancePayload | None = None
    simulation: SimulationPayload | None = None
    recovery: RecoveryPayload | None = None
    analytical_bands: AnalyticalBandsPayload | None = None
    assumptions: list[str] = []
