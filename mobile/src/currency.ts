import type { Currency, Dashboard } from "./types";

const currencies: Currency[] = ["EUR", "USD", "RON"];

export function availableCurrencies(
  baseCurrency: Currency,
  dashboard: Dashboard,
): Currency[] {
  const edges = new Map<Currency, Set<Currency>>();
  const addEdge = (from: Currency, to: Currency) => {
    const neighbors = edges.get(from) ?? new Set<Currency>();
    neighbors.add(to);
    edges.set(from, neighbors);
  };

  for (const rate of dashboard.market_fx_rates) {
    addEdge(rate.base_currency, rate.quote_currency);
    addEdge(rate.quote_currency, rate.base_currency);
  }
  if (dashboard.profile.usd_per_eur) {
    addEdge("EUR", "USD");
    addEdge("USD", "EUR");
  }

  return currencies.filter((target) => {
    if (target === baseCurrency) return true;
    const visited = new Set<Currency>([baseCurrency]);
    const queue = [baseCurrency];
    while (queue.length) {
      const current = queue.shift();
      if (!current) continue;
      for (const neighbor of edges.get(current) ?? []) {
        if (neighbor === target) return true;
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          queue.push(neighbor);
        }
      }
    }
    return false;
  });
}
