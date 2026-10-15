import type { AssetClass, Currency, GoalType, MarketFxRate } from "./types";

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

export function convertAmount(
  value: string | number,
  from: Currency,
  to: Currency,
  rates: MarketFxRate[],
  usdPerEur: string | null,
): number | null {
  const amountValue = Number(value);
  if (!Number.isFinite(amountValue)) return null;
  if (from === to) return amountValue;

  const edges = new Map<Currency, Map<Currency, number>>();
  function addEdge(base: Currency, quote: Currency, rate: number) {
    const neighbors = edges.get(base) ?? new Map<Currency, number>();
    neighbors.set(quote, rate);
    edges.set(base, neighbors);
  }
  for (const item of rates) {
    const rate = Number(item.rate);
    if (Number.isFinite(rate) && rate > 0) {
      addEdge(item.base_currency, item.quote_currency, rate);
      addEdge(item.quote_currency, item.base_currency, 1 / rate);
    }
  }
  const manual = Number(usdPerEur);
  if (Number.isFinite(manual) && manual > 0) {
    if (!edges.get("EUR")?.has("USD")) addEdge("EUR", "USD", manual);
    if (!edges.get("USD")?.has("EUR")) addEdge("USD", "EUR", 1 / manual);
  }

  const queue: { currency: Currency; rate: number }[] = [{ currency: from, rate: 1 }];
  const visited = new Set<Currency>([from]);
  while (queue.length) {
    const current = queue.shift();
    if (!current) continue;
    for (const [next, rate] of edges.get(current.currency) ?? []) {
      if (visited.has(next)) continue;
      const convertedRate = current.rate * rate;
      if (next === to) return amountValue * convertedRate;
      visited.add(next);
      queue.push({ currency: next, rate: convertedRate });
    }
  }
  return null;
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
    case "proportional":
      return "Proportional";
    case "fixed_percentages":
      return "Fixed percentages";
    default:
      return rule;
  }
}
