import type { ContributionRule, Currency, IncomeSource } from "./types";

export const planningExplanation = "Forecast only: never posts money to wallets or changes cash-flow schedules. Enter net/take-home income, not gross pay; payroll taxes are not calculated. All today's-money amounts refer to the reference date. A future job's salary is inflated once to its start, then grows only by the nominal annual raise you enter. A 5% raise means payslip +5% total, not inflation +5%; 0% keeps pay fixed in nominal money. End the old salary before starting a new job; the new amount overrides it. Nominal amounts skip the initial inflation adjustment. Salary-based bonuses are a share of annualized salary and only pay while that salary is active.";
export const ruleExplanation = "Fixed monthly mode uses a constant nominal amount. Scheduled contribution rules replace that amount (an empty list means no contributions). Fixed values use the goal currency. Source-linked rules run on every source event, ignoring rule recurrence; percentages are shares of that event. Independent fixed rules follow their recurrence. Combine rules and date ranges to plan future increases. Today's-money fixed amounts retain reference-date purchasing power; nominal amounts stay fixed.";
export const today = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
export function newIncome(currency: Currency, start: string): IncomeSource {
  return { id: `income_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, name: "Salary", kind: "salary",
    amount: "0", currency, recurrence: "monthly", start_date: start, end_date: null,
    money_basis: "real", annual_growth_rate: "0", salary_source_id: null, salary_percentage: null };
}
export function newRule(start = today()): ContributionRule {
  return { source_id: null, calculation: "fixed", value: "0", recurrence: "monthly",
    start_date: start, end_date: null, money_basis: "real" };
}
