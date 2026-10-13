export type Currency = "EUR" | "USD" | "RON";
export type AssetClass = "equities" | "fixed_income" | "satellite";
export type FundingRule = "priority_first" | "proportional" | "fixed_percentages";
export type AccountType = "BROKERAGE" | "BANK" | "SAVINGS" | "EMPLOYER_PLAN";
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
  is_active: boolean;
  linked_account_ids: string[];
  holding_ids: string[];
  fixed_deposit_ids: string[];
}

export interface UserProfile {
  id: string;
  username: string;
  display_name: string;
  base_currency: Currency;
  usd_per_eur: string | null;
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
}

export interface HoldingSummary {
  id: string;
  account_id: string;
  assigned_goal_id: string | null;
  assigned_goal_name: string | null;
  symbol: string;
  name: string;
  account_name: string;
  exchange: string;
  mic_code: string;
  asset_class: AssetClass;
  instrument_type: "STOCK" | "ETF";
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
  holding_ids: string[];
  fixed_deposit_ids: string[];
}

export interface GoalUpdatePayload extends GoalCreatePayload {
  current_amount: string;
  current_annual_income: string;
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
  currency: Currency;
  opening_cash: string;
  annual_interest_rate?: string;
  interest_start_date?: string;
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
