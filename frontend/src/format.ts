import type { AssetClass, Currency, GoalType } from "./types";

export function amount(value: string | number, currency: Currency, digits = 0): string {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(numericValue);
}

export function number(value: string | number, digits = 0): string {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "—";
  return new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(numericValue);
}

export function dateLabel(value: string | null, options?: Intl.DateTimeFormatOptions): string {
  if (!value) return "Date not set";
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.valueOf())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-GB", options ?? { day: "numeric", month: "short", year: "numeric" }).format(parsed);
}

export function assetLabel(assetClass: AssetClass): string {
  switch (assetClass) {
    case "equities":
      return "Equities";
    case "fixed_income":
      return "Fixed income";
    case "satellite":
      return "Satellite";
  }
}

export function goalLabel(goalType: GoalType): string {
  const labels: Record<GoalType, string> = {
    wealth: "Long-term wealth",
    retirement: "Retirement",
    passive_income: "Passive income",
    purchase: "Planned purchase",
    preservation: "Capital preservation",
    debt_repayment: "Debt repayment",
    custom: "Custom goal",
  };
  return labels[goalType];
}

export function fundingLabel(rule: string): string {
  switch (rule) {
    case "priority_first":
      return "Priority first";
    case "proportional":
      return "Proportional";
    case "fixed_percentages":
      return "Fixed percentages";
    default:
      return rule;
  }
}
