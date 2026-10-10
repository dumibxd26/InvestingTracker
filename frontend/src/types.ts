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
  current_annual_income: string;
  currency: Currency;
  progress_percent: string;
  target_date: string | null;
  priority: number;
  risk_level: "low" | "moderate" | "high";
  monthly_contribution: string;
  fixed_percent: string | null;
  flexibility: "essential" | "flexible";
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
  symbol: string;
  name: string;
  account_name: string;
  asset_class: AssetClass;
  instrument_type: "STOCK" | "ETF";
  quantity: string;
  price: string;
  price_currency: Currency;
  quote_source: string;
  quote_observed_at: string;
  is_market_open: boolean | null;
  change_since_refresh_percent: string | null;
  market_value: string;
  base_currency: Currency;
  change_percent: string;
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
  symbol: string;
  mic_code: string | null;
  exchange: string;
  instrument_type: "STOCK" | "ETF";
  quantity: string;
  average_cost: string;
}

export interface HoldingCreated {
  symbol: string;
  account_name: string;
  quantity: string;
  quote_price: string;
  quote_currency: Currency;
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
  name: string;
  principal: string;
  accrued_interest: string;
  currency: Currency;
  annual_rate: string;
  rate_basis: "nominal_apr" | "effective_apy";
  maturity_date: string;
  days_to_maturity: number;
}

export interface Vesting {
  symbol: string;
  name: string;
  grant_type: "rsu" | "option";
  units: string;
  vested_percent: string;
  next_vest_date: string | null;
  gross_value: string;
  estimated_net_value: string;
  currency: Currency;
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
    unrealized_pnl_estimate: string;
    estimated_monthly_income: string;
    emergency_reserve_target: string;
    reserve_shortfall: string;
  };
  six_month_change: string;
  six_month_change_percent: string;
  allocation: Allocation[];
  chart: ChartPoint[];
  accounts: AccountSummary[];
  holdings: HoldingSummary[];
  market_fx_rates: MarketFxRate[];
  market_data_provider_configured: boolean;
  goals: GoalSummary[];
  cash_flows: CashFlow[];
  cash_flow_schedules: CashFlowSchedule[];
  deposits: Deposit[];
  vesting: Vesting[];
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
}

export interface AccountCreatePayload {
  display_name: string;
  provider_code: string;
  account_type: AccountType;
  currency: Currency;
  opening_cash: string;
}

export interface CashFlowSchedulePayload {
  label: string;
  kind: FlowKind;
  amount: string;
  currency: Currency;
  recurrence: Recurrence;
  start_date: string;
  end_date?: string;
}

export interface CashReceiptPayload {
  account_id: string;
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
