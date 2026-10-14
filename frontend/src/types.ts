export type Currency = "EUR" | "USD" | "RON";
export type AssetClass = "equities" | "fixed_income" | "satellite";
export type FundingRule = "priority_first" | "proportional" | "fixed_percentages";
export type AccountType = "BROKERAGE" | "BANK" | "SAVINGS" | "EMPLOYER_PLAN";
export type TaxReportingMethod =
  | "legacy_manual"
  | "withholding_agent"
  | "annual_self_assessment"
  | "tax_exempt";
export type Recurrence = "one_time" | "monthly" | "quarterly" | "annual";
export type FlowKind =
  | "salary"
  | "bonus"
  | "windfall"
  | "dividend"
  | "interest"
  | "bill"
  | "contribution";
export type GoalType =
  | "wealth"
  | "retirement"
  | "passive_income"
  | "purchase"
  | "preservation"
  | "debt_repayment"
  | "custom";

export interface GoalSummary {
  id: string;
  name: string;
  goal_type: GoalType;
  target_amount: string | null;
  target_annual_income: string | null;
  current_amount: string;
  linked_asset_value: string;
  current_annual_income: string;
  currency: Currency;
  progress_percent: string;
  target_date: string | null;
  priority: number;
  risk_level: "low" | "moderate" | "high";
  monthly_contribution: string;
  visualization_budget_amount: string | null;
  visualization_budget_period: "monthly" | "yearly" | null;
  fixed_percent: string | null;
  flexibility: "essential" | "flexible";
  linked_account_ids: string[];
  holding_ids: string[];
  fixed_deposit_ids: string[];
}

export interface GoalSourceAllocation {
  id: string;
  allocated_percentage: string;
}

export interface GoalRecord {
  id: string;
  name: string;
  goal_type: GoalType;
  target_amount: string | null;
  target_annual_income: string | null;
  current_amount: string;
  current_annual_income: string;
  target_currency: Currency;
  target_date: string | null;
  priority: number;
  risk_level: "low" | "moderate" | "high";
  monthly_contribution: string;
  visualization_budget_amount: string | null;
  visualization_budget_period: "monthly" | "yearly" | null;
  fixed_percent: string | null;
  flexibility: "essential" | "flexible";
  linked_account_ids: string[];
  holding_ids: string[];
  fixed_deposit_ids: string[];
  holding_allocations: GoalSourceAllocation[];
  fixed_deposit_allocations: GoalSourceAllocation[];
}

export interface UserProfile {
  id: string;
  username: string;
  display_name: string;
  base_currency: Currency;
  usd_per_eur: string | null;
  tax_residence_country_code: string | null;
  tax_year: number | null;
  tax_minimum_monthly_wage: string | null;
  tax_rules_status: string;
  tax_rule_version: string | null;
  tax_rule_sources: string[];
  tax_rule_limitations: string[];
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: UserProfile;
}

export interface RegisterPayload {
  username: string;
  password: string;
  display_name?: string;
  base_currency: Currency;
  usd_per_eur?: string;
}

export interface ProfileUpdatePayload {
  display_name: string;
  base_currency: Currency;
  usd_per_eur: string | null;
  tax_residence_country_code: string | null;
  tax_year: number | null;
  tax_minimum_monthly_wage: string | null;
}

export interface HoldingSummary {
  id: string;
  account_id: string;
  assigned_goal_id: string | null;
  assigned_goal_name: string | null;
  allocated_percentage: string;
  symbol: string;
  name: string;
  account_name: string;
  exchange: string;
  mic_code: string;
  asset_class: AssetClass;
  instrument_type: "STOCK" | "ETF";
  tax_domicile_country_code: string | null;
  quantity: string;
  average_cost: string;
  purchase_date: string;
  risk_tier: "X" | "Y" | "Z";
  expected_annual_return: string;
  funding_currency: Currency | null;
  funding_cost: string;
  price: string;
  price_currency: Currency;
  quote_source: string;
  quote_observed_at: string;
  is_market_open: boolean | null;
  change_since_refresh_percent: string | null;
  market_value: string;
  gross_market_value: string;
  cost_basis_value: string;
  estimated_gain: string;
  estimated_gain_percent: string;
  estimated_sale_tax: string;
  estimated_tax_rate: string;
  estimated_tax_status: string;
  base_currency: Currency;
  is_demo: boolean;
}

export interface MarketSymbol {
  symbol: string;
  name: string;
  exchange: string;
  mic_code: string | null;
  currency: Currency;
  instrument_type: "STOCK" | "ETF";
  country: string;
}

export interface MarketFxRate {
  base_currency: Currency;
  quote_currency: Currency;
  rate: string;
  provider: string;
  observed_at: string;
  change_percent: string | null;
}

export interface MarketDataStatus {
  provider: string;
  provider_configured: boolean;
  automatic_refresh_enabled: boolean;
}

export interface MarketRefreshResult {
  updated_symbols: string[];
  updated_fx_pairs: string[];
  errors: string[];
}

export interface HoldingCreatePayload {
  account_id: string;
  subaccount_id: string;
  symbol: string;
  mic_code: string | null;
  exchange: string;
  instrument_type: "STOCK" | "ETF";
  tax_domicile_country_code?: string | null;
  quantity: string;
  average_cost: string;
  average_cost_currency: Currency;
  purchase_date: string;
}

export interface HoldingUpdatePayload {
  quantity: string;
  average_cost: string;
  average_cost_currency: Currency;
  purchase_date?: string;
  tax_domicile_country_code?: string | null;
  risk_tier?: "X" | "Y" | "Z";
  expected_annual_return?: string;
  short_term_sale_tax_rate?: string;
  long_term_sale_tax_rate?: string;
  long_term_holding_period_days?: number;
}

export interface StockSalePayload {
  idempotency_key: string;
  sell_date: string;
  sell_price: string;
  quantity?: string;
}

export interface StockSaleRecord {
  id: string;
  symbol: string;
  currency: Currency;
  quantity: string;
  sell_price: string;
  proceeds: string;
  cost_basis: string;
  realized_pnl: string;
  sell_date: string;
  credited_subaccount_id: string;
}

export interface BrokerTransactionPreview {
  row_number: number;
  event_type: "closed_position" | "cash_operation";
  event_at: string;
  opened_at: string | null;
  closed_at: string | null;
  symbol: string | null;
  description: string | null;
  direction: string | null;
  asset_type: string | null;
  quantity: string | null;
  open_price: string | null;
  close_price: string | null;
  amount: string | null;
  currency_code: string;
  commission: string | null;
  swap: string | null;
  taxes: string | null;
  reported_profit: string | null;
}

export interface BrokerImportPreview {
  content_sha256: string;
  source_format: string;
  transaction_count: number;
  closed_position_count: number;
  cash_operation_count: number;
  duplicate_count: number;
  stocks_etfs_only: boolean;
  warnings: string[];
  sample: BrokerTransactionPreview[];
}

export interface BrokerImportResult {
  batch_id: string;
  imported_count: number;
  duplicate_count: number;
  stocks_etfs_only: boolean;
  warnings: string[];
}

export interface BrokerTransactionRecord extends Omit<BrokerTransactionPreview, "row_number"> {
  id: string;
  import_batch_id: string;
  source_sheet: string;
  broker_reference: string | null;
  balance_after: string | null;
  estimated_tax: string | null;
  estimated_tax_rate: string | null;
  estimated_tax_status: string;
  tax_estimate_warnings: string[];
}

export interface BrokerTransactionList {
  total: number;
  offset: number;
  limit: number;
  transactions: BrokerTransactionRecord[];
}

export type TransferFeeSide = "SOURCE" | "DESTINATION";

export interface TransferFeePayload {
  fee_amount?: string;
  fee_currency?: Currency;
  fee_side?: TransferFeeSide;
}

export interface CashTransferPayload extends TransferFeePayload {
  idempotency_key: string;
  source_subaccount_id: string;
  destination_subaccount_id: string;
  transfer_date: string;
  source_amount: string;
  destination_amount?: string;
}

export interface CashTransferRecord {
  id: string;
  source_subaccount_id: string;
  destination_subaccount_id: string;
  source_account_name: string;
  destination_account_name: string;
  source_currency: Currency;
  destination_currency: Currency;
  source_amount: string;
  destination_amount: string;
  transfer_date: string;
  fee_amount: string | null;
  fee_currency: Currency | null;
  fee_side: TransferFeeSide | null;
}

export interface StockTransferPayload extends TransferFeePayload {
  idempotency_key: string;
  destination_account_id: string;
  transfer_date: string;
  quantity?: string;
}

export interface StockTransferRecord {
  id: string;
  symbol: string;
  source_account_id: string;
  destination_account_id: string;
  source_account_name: string;
  destination_account_name: string;
  quantity: string;
  average_cost: string;
  cost_basis: string;
  transfer_date: string;
  fee_amount: string | null;
  fee_currency: Currency | null;
  fee_side: TransferFeeSide | null;
}

export interface HoldingCreated {
  symbol: string;
  account_name: string;
  quantity: string;
  quote_price: string;
  quote_currency: Currency;
  funding_currency: Currency | null;
  funding_cost: string;
}

export interface AccountSummary {
  id: string;
  display_name: string;
  provider_code: string;
  account_type: AccountType;
  broker_country_code: string | null;
  tax_reporting_method: TaxReportingMethod;
  currency: Currency;
  cash_balance: string;
  position_count: number;
  is_sample: boolean;
  subaccounts: AccountSubaccount[];
}

export interface AccountWealthSummary {
  id: string;
  display_name: string;
  account_type: AccountType;
  currency: Currency;
  cash_value: string;
  gross_holdings_value: string;
  estimated_sale_tax: string;
  after_tax_holdings_value: string;
  fixed_deposit_value: string;
  total_after_tax_value: string;
}

export interface AccountSubaccount {
  id: string;
  currency: Currency;
  cash_balance: string;
  is_primary: boolean;
  annual_interest_rate: string | null;
  interest_start_date: string | null;
}

export interface StockPurchasePlan {
  id: string;
  name: string;
  symbol: string;
  instrument_name: string;
  account_id: string;
  account_name: string;
  funding_currency: Currency;
  shares: string;
  purchase_date: string;
  discount_rate: string;
  receipt_tax_rate: string;
  sale_profit_tax_rate: string;
  status: "scheduled" | "executed";
  price_currency: Currency;
  market_price: string;
  purchase_price: string;
  price_is_estimate: boolean;
  reporting_currency: Currency;
  market_value: string;
  purchase_cost: string;
  gross_discount_benefit: string;
  receipt_tax: string;
  net_benefit: string;
  holding_id: string | null;
}

export interface StockPurchasePlanPayload {
  name?: string;
  symbol: string;
  mic_code: string | null;
  exchange: string;
  account_id: string;
  subaccount_id: string;
  shares: string;
  purchase_date: string;
  discount_rate: string;
  receipt_tax_rate: string;
  sale_profit_tax_rate: string;
  reference_price?: string;
}

export interface SubaccountInterestPayload {
  annual_interest_rate: string | null;
  interest_start_date: string | null;
}

export interface InitialPortfolioAccountPayload {
  display_name: string;
  provider_code: string;
  account_type: AccountType;
  subaccounts: { currency: Currency; opening_balance: string }[];
}

export interface InitialPortfolioHoldingPayload {
  account_index: number;
  symbol: string;
  mic_code: string | null;
  exchange: string;
  instrument_type: "STOCK" | "ETF";
  tax_domicile_country_code?: string | null;
  quantity: string;
  average_cost: string;
  average_cost_currency: Currency;
  purchase_date: string;
}

export interface InitialPortfolioResponse {
  accounts: AccountSummary[];
  holdings: HoldingCreated[];
}

export interface CashFlow {
  id: string;
  label: string;
  kind: FlowKind;
  direction: "inflow" | "outflow" | "transfer";
  status: "forecast" | "confirmed" | "cancelled";
  amount: string;
  currency: Currency;
  expected_date: string | null;
  occurred_at: string | null;
  reporting_amount: string | null;
  reporting_currency: Currency | null;
  schedule_id: string | null;
  recurrence: Recurrence | null;
  automatically_posted: boolean;
}

export interface CashFlowSchedule {
  id: string;
  label: string;
  kind: FlowKind;
  amount: string;
  currency: Currency;
  recurrence: Recurrence;
  start_date: string;
  end_date: string | null;
  is_active: boolean;
  account_id: string | null;
  subaccount_id: string | null;
  auto_post: boolean;
}

export interface VestingTranche {
  vest_date: string;
  available_date: string;
  units: string;
  status: "scheduled" | "vested" | "released" | "forfeited";
}

export interface Allocation {
  asset_class: AssetClass;
  value: string;
  percentage: string;
  target_percentage: string;
}

export interface ChartPoint {
  label: string;
  date: string;
  value: string;
}

export interface Deposit {
  id: string;
  account_id: string;
  source_subaccount_id: string | null;
  assigned_goal_id: string | null;
  assigned_goal_name: string | null;
  allocated_percentage: string;
  name: string;
  principal: string;
  accrued_interest: string;
  current_value: string;
  currency: Currency;
  annual_rate: string;
  rate_basis: "nominal_apr" | "effective_apy";
  compounding: "daily" | "monthly" | "quarterly" | "annual" | "at_maturity";
  period_months: number;
  start_date: string;
  maturity_date: string;
  days_to_maturity: number;
}

export interface Vesting {
  id: string;
  symbol: string;
  name: string;
  grant_type: "rsu" | "option";
  grant_label: string | null;
  grant_date: string | null;
  total_units: string;
  units: string;
  vested_units: string;
  vested_percent: string;
  next_vest_date: string | null;
  strike_price: string | null;
  strike_currency: Currency | null;
  tax_rate_assumption: string;
  short_term_sale_tax_rate: string;
  long_term_sale_tax_rate: string;
  long_term_holding_period_days: number;
  gross_value: string;
  estimated_net_value: string;
  estimated_short_term_sale_value: string;
  estimated_long_term_sale_value: string;
  currency: Currency;
  price: string | null;
  price_currency: Currency | null;
  quote_source: string | null;
  quote_observed_at: string | null;
  tranches: VestingTranche[];
}

export interface Policy {
  funding_rule: FundingRule | null;
  emergency_reserve: string;
  target_weights: Record<AssetClass, string>;
}

export interface Dashboard {
  base_currency: Currency;
  profile: UserProfile;
  as_of: string;
  sample_data: boolean;
  totals: {
    net_worth: string;
    invested_assets: string;
    available_cash: string;
    fixed_deposits: string;
    unvested_equity_gross: string;
    unvested_equity_net_estimate: string;
    unvested_equity_short_term_sale_estimate: string;
    unvested_equity_long_term_sale_estimate: string;
    estimated_monthly_income: string;
    emergency_reserve_target: string;
    reserve_shortfall: string;
  };
  six_month_change: string;
  six_month_change_percent: string;
  allocation: Allocation[];
  chart: ChartPoint[];
  accounts: AccountSummary[];
  account_wealth: AccountWealthSummary[];
  holdings: HoldingSummary[];
  market_fx_rates: MarketFxRate[];
  market_data_provider_configured: boolean;
  goals: GoalSummary[];
  cash_flows: CashFlow[];
  cash_flow_schedules: CashFlowSchedule[];
  deposits: Deposit[];
  vesting: Vesting[];
  purchase_plans: StockPurchasePlan[];
  warnings: string[];
  policy: Policy;
}

export interface GoalAllocation {
  goal_id: string;
  goal_name: string;
  amount: string;
  percentage: string;
  rationale: string;
}

export interface BucketAllocation {
  asset_class: AssetClass;
  amount: string;
  target_weight: string;
  current_value: string;
  post_contribution_weight: string;
  rationale: string;
}

export interface RecommendationPreview {
  id: string;
  status: "PREVIEW_ONLY";
  input_amount: string;
  input_currency: Currency;
  base_currency: Currency;
  funding_rule: FundingRule;
  reserve_top_up: string;
  deployable_amount: string;
  retained_for_near_term_goals: string;
  investable_amount: string;
  passive_income_gap: string;
  goal_allocations: GoalAllocation[];
  asset_allocations: BucketAllocation[];
  warnings: string[];
  created_at: string;
  expires_at: string;
  explanation: string;
}

export interface ProjectionAccountValue {
  account_id: string;
  account_name: string;
  current_value: string;
  projected_cash_value: string;
  projected_holdings_value: string;
  projected_deposit_value: string;
  projected_total_value: string;
}

export interface ProjectionPoint {
  date: string;
  label: string;
  total_value: string;
  accounts: ProjectionAccountValue[];
}

export interface PortfolioProjection {
  base_currency: Currency;
  as_of: string;
  target_date: string;
  current_net_worth: string;
  projected_net_worth: string;
  estimated_change: string;
  accounts: ProjectionAccountValue[];
  timeline: ProjectionPoint[];
  warnings: string[];
}

export interface ProjectionScenarioInvestmentInput {
  holding_id: string;
  contribution_percentage: string;
  assumed_annual_return: string;
}

export interface PortfolioProjectionScenarioPayload {
  target_date: string;
  currency: Currency;
  monthly_contribution: string;
  scope_account_id: string | null;
  investments: ProjectionScenarioInvestmentInput[];
}

export interface ProjectionScenarioInvestment {
  holding_id: string;
  symbol: string;
  name: string;
  account_id: string;
  account_name: string;
  exchange: string;
  risk_tier: "X" | "Y" | "Z";
  current_value: string;
  current_weight: string;
  contribution_percentage: string;
  monthly_contribution: string;
  assumed_annual_return: string;
  contribution_principal: string;
  projected_gross_value: string;
  estimated_tax: string;
  projected_after_tax_value: string;
}

export interface ProjectionScenarioRiskSummary {
  scope_account_id: string | null;
  scope_account_name: string;
  current_invested_value: string;
  risk_mix: Record<"X" | "Y" | "Z", string>;
  weighted_risk_score: string | null;
  contribution_weighted_risk_score: string;
  methodology: string;
}

export interface PortfolioProjectionScenario {
  baseline: PortfolioProjection;
  with_contributions: PortfolioProjection;
  monthly_contribution: string;
  monthly_contribution_currency: Currency;
  weighted_annual_return_assumption: string;
  risk_summary: ProjectionScenarioRiskSummary;
  investments: ProjectionScenarioInvestment[];
  assumptions: string[];
}

export interface GoalCreatePayload {
  name: string;
  goal_type: GoalType;
  target_amount?: string;
  target_annual_income?: string;
  target_currency: Currency;
  target_date?: string;
  priority: number;
  risk_level: "low" | "moderate" | "high";
  monthly_contribution: string;
  fixed_percent?: string;
  flexibility: "essential" | "flexible";
  current_amount?: string;
  current_annual_income?: string;
  visualization_budget_amount?: string | null;
  visualization_budget_period?: "monthly" | "yearly" | null;
  linked_account_ids: string[];
  holding_allocations: GoalSourceAllocation[];
  fixed_deposit_allocations: GoalSourceAllocation[];
}

export interface GoalUpdatePayload extends GoalCreatePayload {
  current_amount: string;
  current_annual_income: string;
}

export interface GoalInsightsTaxProfile {
  annual_inflation_rate: number;
  is_target_in_todays_dollars: boolean;
  index_contributions_to_inflation: boolean;
  short_term_cap_gains_rate: number;
  long_term_cap_gains_rate: number;
  dividend_and_interest_tax_rate: number;
  annual_tax_free_allowance: number;
}

export interface GoalInsightsGoal {
  goal_id: string;
  name: string;
  base_currency: Currency;
  target_amount: number;
  target_date: string;
  monthly_contribution: number;
  risk_profile: "CONSERVATIVE" | "MODERATE" | "AGGRESSIVE";
  target_success_probability: number;
  tax_profile: GoalInsightsTaxProfile;
}

export interface GoalInsightsBucketDrift {
  bucket: "CASH" | "BONDS" | "EQUITIES";
  current_value: number;
  current_weight: number;
  target_weight: number;
  drift: number;
  dollar_delta_to_target: number;
  is_breached: boolean;
}

export interface GoalInsightsWarning {
  holding_id: string;
  ticker: string;
  current_weight: number;
  max_allowed_weight: number;
  excess_dollar_amount: number;
  reason: string;
  message: string;
  suggested_fix: string | null;
}

export interface GoalInsightsSlice {
  holding_id: string;
  ticker: string;
  name: string;
  asset_class: string;
  macro_bucket: string;
  allocated_percentage: number;
  market_value_in_goal: number;
  cost_basis_in_goal: number;
  local_expected_return: number;
  local_volatility: number;
  effective_return_in_goal: number;
  effective_volatility_in_goal: number;
  effective_dividend_yield: number;
  is_unhedged_foreign_exposure: boolean;
  underlying_currency: string;
  sector: string | null;
  weight_in_goal: number;
}

export interface GoalInsightsEvaluation {
  goal_id: string;
  base_currency: Currency;
  remaining_years: number;
  total_current_value: number;
  total_cost_basis: number;
  after_tax_value: number;
  expected_return_mu: number;
  weighted_dividend_yield: number;
  portfolio_volatility_sigma: number;
  unhedged_foreign_weight: number;
  median_compounding_rate: number;
  sharpe_ratio: number;
  max_single_stock_weight: number;
  max_unhedged_fx_weight: number;
  target_weights: Record<string, number>;
  bucket_drifts: Record<string, GoalInsightsBucketDrift>;
  requires_rebalancing: boolean;
  warnings: GoalInsightsWarning[];
  slices: GoalInsightsSlice[];
}

export interface GoalInsightsTickerProposal {
  ticker: string;
  name: string;
  asset_class: string;
  action: "BUY_WITH_CONTRIBUTION" | "REBALANCE_INTO";
  recommended_amount: number;
  score: number;
  rationale: string;
}

export interface GoalInsightsRouteItem {
  bucket: "CASH" | "BONDS" | "EQUITIES";
  allocated_contribution: number;
  share_of_contribution: number;
  post_contribution_weight: number;
  target_weight: number;
  suggested_tickers: GoalInsightsTickerProposal[];
}

export interface GoalInsightsLotDisposal {
  lot_id: string;
  units_to_sell: number;
  proceeds_in_goal_currency: number;
  realized_gain_or_loss: number;
  is_long_term: boolean;
  applicable_tax_rate: number;
  estimated_tax_due: number;
}

export interface GoalInsightsTrimProposal {
  holding_id: string;
  ticker: string;
  gross_sell_amount: number;
  total_realized_gain: number;
  total_estimated_tax: number;
  net_reinvestable_proceeds: number;
  effective_tax_drag_pct: number;
  recommendation_type: "EXECUTE_TAX_FREE_OR_TLH" | "EXECUTE_LOW_TAX_DRAG" | "DEFER_USE_INFLOWS_INSTEAD";
  rationale: string;
  lot_disposals: GoalInsightsLotDisposal[];
}

export interface GoalInsightsRebalance {
  goal_id: string;
  monthly_contribution_routing: GoalInsightsRouteItem[];
  tax_aware_trim_proposals: GoalInsightsTrimProposal[];
  rebalance_buy_proposals: GoalInsightsTickerProposal[];
  projected_impact: {
    previous_volatility: number;
    new_volatility: number;
    previous_median_return: number;
    new_median_return: number;
    summary_text: string;
  };
}

export interface GoalInsightsYearPoint {
  year: number;
  nominal_after_tax: Record<"p10" | "p25" | "p50" | "p75" | "p90", number>;
  real_todays_dollars: Record<"p10" | "p25" | "p50" | "p75" | "p90", number>;
  inflated_target_at_year: number;
}

export interface GoalInsightsSimulation {
  success_probability: number;
  nominal_target_at_maturity: number;
  real_target_in_todays_dollars: number;
  terminal_real_todays_dollars_p10: number;
  terminal_real_todays_dollars_p50: number;
  terminal_real_todays_dollars_p90: number;
  estimated_median_tax_paid_at_liquidation: number;
  yearly_schedule: GoalInsightsYearPoint[];
}

export interface GoalInsightsRecovery {
  is_goal_on_track: boolean;
  current_success_probability: number;
  target_success_probability: number;
  plans: {
    increase_contribution_plan: {
      description: string;
      resulting_success_probability: number;
      required_monthly_contribution: number;
      additional_monthly_needed: number;
    } | null;
    extend_timeline_plan: {
      description: string;
      resulting_success_probability: number;
      additional_months_needed: number;
      new_target_date: string;
    } | null;
    optimize_portfolio_plan: {
      description: string;
      resulting_success_probability: number;
      optimal_expected_return: number;
      optimal_volatility: number;
    } | null;
    unreachable_levers: string[];
  };
}

export interface GoalInsightsBands {
  expected_rate: number;
  optimistic_rate: number;
  conservative_rate: number;
  projected_value_expected: number;
  projected_value_optimistic: number;
  projected_value_conservative: number;
  months_remaining: number;
}

export interface GoalInsights {
  available: boolean;
  unavailable_reason: string | null;
  goal: GoalInsightsGoal | null;
  remaining_years: number | null;
  evaluation: GoalInsightsEvaluation | null;
  rebalance_plan: GoalInsightsRebalance | null;
  simulation: GoalInsightsSimulation | null;
  recovery: GoalInsightsRecovery | null;
  analytical_bands: GoalInsightsBands | null;
  assumptions: string[];
}

export interface FixedDepositCreatePayload {
  account_id: string;
  subaccount_id: string;
  name: string;
  principal: string;
  start_date: string;
  period_months: number;
  annual_profit_rate: string;
  capitalization: boolean;
}

export interface FixedDepositCreated {
  id: string;
  name: string;
  principal: string;
  currency: Currency;
  start_date: string;
  maturity_date: string;
  period_months: number;
  annual_rate: string;
  capitalization: boolean;
}

export interface AccountCreatePayload {
  display_name: string;
  provider_code: string;
  account_type: AccountType;
  broker_country_code?: string | null;
  tax_reporting_method?: TaxReportingMethod;
  currency: Currency;
  opening_cash: string;
  annual_interest_rate?: string;
  interest_start_date?: string;
}

export interface AccountTaxProfileUpdatePayload {
  broker_country_code: string | null;
  tax_reporting_method: TaxReportingMethod;
}

export interface CashFlowSchedulePayload {
  label: string;
  kind: FlowKind;
  amount: string;
  currency: Currency;
  recurrence: Recurrence;
  start_date: string;
  end_date?: string;
  account_id?: string;
  subaccount_id?: string;
  auto_post?: boolean;
}

export interface VestingGrantPayload {
  symbol: string;
  mic_code: string | null;
  exchange: string;
  grant_type: "rsu" | "option";
  grant_label?: string;
  grant_date?: string;
  total_units: string;
  duration_months?: number;
  cliff_months?: number;
  interval_months?: number;
  tranches?: { vest_date: string; units: string }[];
  strike_price?: string;
  tax_rate_assumption: string;
  short_term_sale_tax_rate: string;
  long_term_sale_tax_rate: string;
  long_term_holding_period_days: number;
}

export interface CashReceiptPayload {
  account_id: string;
  subaccount_id: string;
  source: string;
  amount: string;
  received_date: string;
  idempotency_key: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatReply {
  answer: string;
  model: string;
  data_as_of: string;
  used_context: string[];
}
