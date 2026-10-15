import { useMemo, useState } from "react";
import { CalendarRange, Info, Plus, Search, TrendingUp, Trash2 } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type {
  AccountSummary,
  Currency,
  Deposit,
  HoldingSummary,
  PortfolioProjectionRange,
  ProjectionRangeAssetType,
  ProjectionRangeLine,
} from "../types";

interface PortfolioProjectionPanelProps {
  currency: Currency;
  accounts: AccountSummary[];
  holdings: HoldingSummary[];
  deposits: Deposit[];
}

interface CustomInvestment {
  key: string;
  name: string;
  currentValue: string;
  costBasis: string;
}

interface InvestmentAssumption {
  worst: string;
  best: string;
  contributionPercentage: string;
  taxRate: string;
}

interface ProjectionOption {
  key: string;
  assetType: ProjectionRangeAssetType;
  assetId?: string;
  title: string;
  accountId: string | null;
  accountName: string;
  currentValue: number;
  expectedReturn: number;
  volatility: number;
  riskTier: "X" | "Y" | "Z" | null;
}

interface ChartPoint {
  x: number;
  y: number;
  value: number;
}

const CHART_COLORS = [
  "#3878a8",
  "#a45d9d",
  "#d18a32",
  "#398b68",
  "#bd5b52",
  "#6975b9",
  "#65853c",
  "#a56e44",
];

function localDateValue(value: Date): string {
  const date = new Date(value);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 10);
}

function dateAfterYears(years: number): string {
  const target = new Date();
  target.setFullYear(target.getFullYear() + years);
  return localDateValue(target);
}

function defaultReturnRange(expectedReturn: number, volatility: number): Pick<InvestmentAssumption, "worst" | "best"> {
  return {
    worst: (Math.max(-0.99, expectedReturn - volatility) * 100).toFixed(2),
    best: (Math.min(1, expectedReturn + volatility) * 100).toFixed(2),
  };
}

function proportionalPercentages(options: ProjectionOption[]): Record<string, string> {
  if (options.length === 0) return {};
  const values = options.map((option) => Math.max(0, option.currentValue));
  const total = values.reduce((sum, value) => sum + value, 0);
  const weights = total > 0 ? values.map((value) => value / total) : values.map(() => 1 / values.length);
  const exactUnits = weights.map((weight) => weight * 10000);
  const units = exactUnits.map(Math.floor);
  const remainder = 10000 - units.reduce((sum, value) => sum + value, 0);
  const remainderOrder = exactUnits
    .map((value, index) => ({ index, fractional: value - units[index] }))
    .sort((left, right) => right.fractional - left.fractional);
  for (let index = 0; index < remainder; index += 1) {
    units[remainderOrder[index].index] += 1;
  }
  return Object.fromEntries(
    options.map((option, index) => [option.key, (units[index] / 100).toFixed(2)]),
  );
}

function lineColor(lines: ProjectionRangeLine[], line: ProjectionRangeLine): string {
  const index = lines.findIndex((item) => item.asset_key === line.asset_key);
  return CHART_COLORS[(index < 0 ? 0 : index) % CHART_COLORS.length];
}

export function PortfolioProjectionPanel({
  currency,
  accounts,
  holdings,
  deposits,
}: PortfolioProjectionPanelProps) {
  const [preset, setPreset] = useState("10");
  const [targetDate, setTargetDate] = useState(() => dateAfterYears(10));
  const [monthlyContribution, setMonthlyContribution] = useState("");
  const [scopeAccountId, setScopeAccountId] = useState("");
  const [includeTaxes, setIncludeTaxes] = useState(true);
  const [inflationPercent, setInflationPercent] = useState("");
  const [investmentSearch, setInvestmentSearch] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [assumptions, setAssumptions] = useState<Record<string, InvestmentAssumption>>({});
  const [customInvestments, setCustomInvestments] = useState<CustomInvestment[]>([]);
  const [projection, setProjection] = useState<PortfolioProjectionRange | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const accountsById = useMemo(
    () => new Map(accounts.map((account) => [account.id, account])),
    [accounts],
  );
  const options = useMemo<ProjectionOption[]>(() => [
    ...holdings
      .filter((holding) => {
        const account = accountsById.get(holding.account_id);
        return account?.account_type !== "EMPLOYER_PLAN"
          && (!scopeAccountId || holding.account_id === scopeAccountId);
      })
      .map((holding) => ({
        key: `holding:${holding.id}`,
        assetType: "holding" as const,
        assetId: holding.id,
        title: `${holding.symbol} · ${holding.name}`,
        accountId: holding.account_id,
        accountName: holding.account_name,
        currentValue: Number(holding.gross_market_value),
        expectedReturn: Number(holding.expected_annual_return),
        volatility: Number(holding.annual_return_volatility_assumption),
        riskTier: holding.risk_tier,
      })),
    ...deposits
      .filter((deposit) => !scopeAccountId || deposit.account_id === scopeAccountId)
      .map((deposit) => ({
        key: `deposit:${deposit.id}`,
        assetType: "deposit" as const,
        assetId: deposit.id,
        title: deposit.name,
        accountId: deposit.account_id,
        accountName: accountsById.get(deposit.account_id)?.display_name ?? "Deposit account",
        currentValue: Number(deposit.current_value_base),
        expectedReturn: Number(deposit.annual_rate),
        volatility: Number(deposit.annual_return_volatility_assumption),
        riskTier: null,
      })),
    ...customInvestments.map((investment) => ({
      key: investment.key,
      assetType: "other" as const,
      title: investment.name || "Other investment",
      accountId: scopeAccountId || null,
      accountName: scopeAccountId
        ? accountsById.get(scopeAccountId)?.display_name ?? "Selected account"
        : "Projection only",
      currentValue: Math.max(0, Number(investment.currentValue) || 0),
      expectedReturn: 0,
      volatility: 0,
      riskTier: null,
    })),
  ], [accountsById, customInvestments, deposits, holdings, scopeAccountId]);

  const selectedOptions = options.filter((option) => selectedKeys.includes(option.key));
  const monthlyAmount = Number(monthlyContribution || 0);
  const contributionPercentageTotal = selectedOptions.reduce(
    (sum, option) => sum + Number(assumptions[option.key]?.contributionPercentage ?? 0),
    0,
  );

  const chart = useMemo(() => {
    if (!projection || projection.scenario_baseline_timeline.length < 2) return null;
    const baseline = projection.scenario_baseline_timeline.map((point) => Number(point.real_value));
    const series = projection.lines.map((line) => ({
      line,
      values: line.points.map((point) => Number(point.real_value)),
    }));
    const maximum = Math.max(1, ...baseline, ...series.flatMap((item) => item.values)) * 1.08;
    const points = (values: number[]): ChartPoint[] => values.map((value, index) => ({
      x: 20 + index * 860 / (values.length - 1),
      y: 232 - value / maximum * 204,
      value,
    }));
    return {
      baseline: points(baseline),
      lines: series.map((item) => ({
        line: item.line,
        points: points(item.values),
      })),
    };
  }, [projection]);

  function invalidateProjection() {
    setProjection(null);
    setError("");
  }

  function handlePresetChange(value: string) {
    setPreset(value);
    if (value !== "custom") {
      setTargetDate(dateAfterYears(Number(value)));
    }
    setInflationPercent("");
    invalidateProjection();
  }

  function toggleInvestment(option: ProjectionOption, checked: boolean) {
    const nextKeys = checked
      ? [...selectedKeys, option.key]
      : selectedKeys.filter((key) => key !== option.key);
    const nextOptions = options.filter((item) => nextKeys.includes(item.key));
    const percentages = proportionalPercentages(nextOptions);
    setSelectedKeys(nextKeys);
    setAssumptions((current) => {
      const next = { ...current };
      for (const item of nextOptions) {
        if (!(item.key in next)) {
          const range = defaultReturnRange(item.expectedReturn, item.volatility);
          next[item.key] = {
            ...range,
            contributionPercentage: "0.00",
            taxRate: "0",
          };
        }
        next[item.key] = {
          ...next[item.key],
          contributionPercentage: percentages[item.key] ?? "0.00",
        };
      }
      if (!checked) delete next[option.key];
      return next;
    });
    invalidateProjection();
  }

  function updateAssumption(
    key: string,
    field: keyof InvestmentAssumption,
    value: string,
  ) {
    setAssumptions((current) => ({
      ...current,
      [key]: {
        ...(current[key] ?? {
          worst: "0",
          best: "0",
          contributionPercentage: "0",
          taxRate: "0",
        }),
        [field]: value,
      },
    }));
    invalidateProjection();
  }

  function updateCustomInvestment(key: string, field: keyof CustomInvestment, value: string) {
    setCustomInvestments((current) => current.map((investment) => {
      if (investment.key !== key) return investment;
      if (field === "currentValue" && investment.costBasis === investment.currentValue) {
        return { ...investment, currentValue: value, costBasis: value };
      }
      return { ...investment, [field]: value };
    }));
    invalidateProjection();
  }

  function addOtherInvestment() {
    const key = `other:${crypto.randomUUID()}`;
    const next: CustomInvestment = {
      key,
      name: "Other investment",
      currentValue: "0",
      costBasis: "0",
    };
    const nextCustom = [...customInvestments, next];
    const option: ProjectionOption = {
      key,
      assetType: "other",
      title: next.name,
      accountId: scopeAccountId || null,
      accountName: "Projection only",
      currentValue: 0,
      expectedReturn: 0,
      volatility: 0,
      riskTier: null,
    };
    const nextOptions = [...options, option];
    setCustomInvestments(nextCustom);
    setSelectedKeys((current) => [...current, key]);
    const percentages = proportionalPercentages(nextOptions.filter(
      (item) => selectedKeys.includes(item.key) || item.key === key,
    ));
    setAssumptions((current) => ({
      ...current,
      [key]: {
        worst: "0",
        best: "0",
        contributionPercentage: percentages[key] ?? "0.00",
        taxRate: "0",
      },
      ...Object.fromEntries(
        selectedKeys.map((selectedKey) => [
          selectedKey,
          {
            ...current[selectedKey],
            contributionPercentage: percentages[selectedKey] ?? "0.00",
          },
        ]),
      ),
    }));
    invalidateProjection();
  }

  function removeOtherInvestment(key: string) {
    setCustomInvestments((current) => current.filter((investment) => investment.key !== key));
    setSelectedKeys((current) => current.filter((selectedKey) => selectedKey !== key));
    setAssumptions((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    invalidateProjection();
  }

  async function calculate() {
    setError("");
    setLoading(true);
    try {
      if (!Number.isFinite(monthlyAmount) || monthlyAmount < 0) {
        setError("Enter a non-negative monthly contribution.");
        return;
      }
      if (!inflationPercent.trim()) {
        setError("Enter an annual inflation assumption.");
        return;
      }
      const inflation = Number(inflationPercent);
      if (!Number.isFinite(inflation) || inflation <= -99 || inflation > 1000) {
        setError("Enter an annual inflation assumption greater than −99% and no more than 1,000%.");
        return;
      }
      if (monthlyAmount > 0 && selectedOptions.length === 0) {
        setError("Select investments before allocating a monthly contribution.");
        return;
      }
      if (
        monthlyAmount > 0
        && Math.abs(contributionPercentageTotal - 100) > 0.001
      ) {
        setError("Allocate exactly 100% of the monthly contribution across selected investments.");
        return;
      }
      for (const option of selectedOptions) {
        const assumption = assumptions[option.key];
        const worst = Number(assumption?.worst);
        const best = Number(assumption?.best);
        if (
          !Number.isFinite(worst)
          || !Number.isFinite(best)
          || worst <= -100
          || best <= -100
          || worst > best
          || best > 100
        ) {
          setError(`Enter a valid worst and best annual return range for ${option.title}.`);
          return;
        }
        if (option.assetType === "other") {
          const custom = customInvestments.find((item) => item.key === option.key);
          const currentValue = Number(custom?.currentValue);
          const costBasis = Number(custom?.costBasis);
          const taxRate = Number(assumption?.taxRate);
          if (
            !custom?.name.trim()
            || !Number.isFinite(currentValue)
            || currentValue < 0
            || !Number.isFinite(costBasis)
            || costBasis < 0
            || !Number.isFinite(taxRate)
            || taxRate < 0
            || taxRate > 100
          ) {
            setError(`Enter a name, non-negative values, and a tax rate from 0% to 100% for ${option.title}.`);
            return;
          }
        }
      }

      const result = await api.portfolioProjectionRange({
        target_date: targetDate,
        currency,
        monthly_contribution: String(monthlyAmount),
        scope_account_id: scopeAccountId || null,
        include_taxes: includeTaxes,
        annual_inflation_rate: String(inflation / 100),
        investments: selectedOptions.map((option) => {
          const assumption = assumptions[option.key];
          const common = {
            asset_key: option.key,
            asset_type: option.assetType,
            contribution_percentage: monthlyAmount > 0
              ? assumption.contributionPercentage
              : "0",
            worst_annual_return: String(Number(assumption.worst) / 100),
            best_annual_return: String(Number(assumption.best) / 100),
          };
          if (option.assetType === "other") {
            const custom = customInvestments.find((item) => item.key === option.key);
            if (!custom) throw new Error("A selected custom investment could not be found.");
            return {
              ...common,
              name: custom.name.trim(),
              current_value: custom.currentValue,
              cost_basis: custom.costBasis,
              tax_rate: String(Number(assumption.taxRate) / 100),
            };
          }
          return { ...common, asset_id: option.assetId };
        }),
      });
      setProjection(result);
    } catch (cause) {
      setProjection(null);
      setError(cause instanceof ApiError ? cause.message : "The portfolio projection could not be calculated.");
    } finally {
      setLoading(false);
    }
  }

  const visibleOptions = options.filter((option) => {
    const query = investmentSearch.trim().toLocaleLowerCase();
    return !query || `${option.title} ${option.accountName} ${option.assetType}`
      .toLocaleLowerCase()
      .includes(query);
  });
  const baseYear = projection?.baseline.timeline.at(-1)?.label;

  return (
    <section className="panel portfolio-projection-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">Illustrative scenarios · not a prediction</div>
          <h2>What could my accounts be worth?</h2>
        </div>
        <span className="projection-icon"><TrendingUp size={17} /></span>
      </div>

      <div className="projection-controls">
        <label className="form-field">
          <span>Projection period</span>
          <select value={preset} onChange={(event) => handlePresetChange(event.target.value)}>
            <option value="1">1 year</option>
            <option value="5">5 years</option>
            <option value="10">10 years</option>
            <option value="custom">Custom date</option>
          </select>
        </label>
        <label className="form-field">
          <span>End date</span>
          <input
            type="date"
            value={targetDate}
            onChange={(event) => {
              setPreset("custom");
              setTargetDate(event.target.value);
              setInflationPercent("");
              invalidateProjection();
            }}
          />
        </label>
        <label className="form-field">
          <span>Annual inflation for this projection (%)</span>
          <input
            type="number"
            min="-99"
            max="1000"
            step="0.01"
            value={inflationPercent}
            onChange={(event) => {
              setInflationPercent(event.target.value);
              invalidateProjection();
            }}
            placeholder="Enter an annual rate"
          />
        </label>
        <div className="form-field projection-tax-toggle">
          <span>Tax view</span>
          <div role="group" aria-label="Projection tax treatment">
            <button
              className={includeTaxes ? "is-selected" : ""}
              type="button"
              aria-pressed={includeTaxes}
              onClick={() => {
                setIncludeTaxes(true);
                invalidateProjection();
              }}
            >
              After tax
            </button>
            <button
              className={!includeTaxes ? "is-selected" : ""}
              type="button"
              aria-pressed={!includeTaxes}
              onClick={() => {
                setIncludeTaxes(false);
                invalidateProjection();
              }}
            >
              Before tax
            </button>
          </div>
        </div>
        <button
          className="button button-primary"
          type="button"
          onClick={() => void calculate()}
          disabled={loading || !targetDate}
        >
          <CalendarRange size={15} /> {loading ? "Calculating…" : "Calculate projection"}
        </button>
      </div>
      <div className="projection-inflation-note">
        Enter an annual inflation assumption for the selected period. It is held constant within
        this projection; changing the period or end date clears it so you can enter a different rate.
      </div>

      <div className="projection-scenario-controls">
        <div className="projection-scenario-heading">
          <div>
            <h3>Investment return ranges</h3>
            <p>
              Choose tracked stocks, ETFs, deposits, or add a projection-only investment.
              Each selected asset gets a worst and best annual-return line.
            </p>
          </div>
          <button className="text-button projection-add-other" type="button" onClick={addOtherInvestment}>
            <Plus size={14} /> Add other investment
          </button>
        </div>
        <div className="projection-scenario-inputs">
          <label className="form-field">
            <span>Monthly contribution ({currency})</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={monthlyContribution}
              onChange={(event) => {
                setMonthlyContribution(event.target.value);
                invalidateProjection();
              }}
              placeholder="Optional · e.g. 500"
            />
          </label>
          <label className="form-field">
            <span>Project for</span>
            <select
              value={scopeAccountId}
              onChange={(event) => {
                setScopeAccountId(event.target.value);
                setSelectedKeys([]);
                setAssumptions({});
                invalidateProjection();
              }}
            >
              <option value="">All tracked accounts</option>
              {accounts
                .filter((account) => account.account_type !== "EMPLOYER_PLAN")
                .map((account) => (
                  <option value={account.id} key={account.id}>{account.display_name}</option>
                ))}
            </select>
          </label>
          {selectedOptions.length > 0 && monthlyAmount > 0 && (
            <div className="projection-allocation-status" role="status">
              {contributionPercentageTotal.toFixed(2)}% of the monthly amount allocated
            </div>
          )}
        </div>

        <label className="projection-investment-search">
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            value={investmentSearch}
            onChange={(event) => setInvestmentSearch(event.target.value)}
            placeholder="Search stocks, ETFs, deposits, or other investments"
            aria-label="Search projection investments"
          />
        </label>

        {visibleOptions.length > 0 ? (
          <div className="projection-investment-list-scroll">
            <div className="projection-investment-list">
              {visibleOptions.map((option) => {
                const selected = selectedKeys.includes(option.key);
                const assumption = assumptions[option.key];
                const custom = option.assetType === "other"
                  ? customInvestments.find((item) => item.key === option.key)
                  : undefined;
                return (
                  <div className="projection-investment-row" key={option.key}>
                    <div className="projection-investment-choice">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={(event) => toggleInvestment(option, event.target.checked)}
                        aria-label={`Include ${option.title} in projection scenarios`}
                      />
                      <div className="projection-investment-label">
                        {custom ? (
                          <input
                            type="text"
                            value={custom.name}
                            maxLength={100}
                            onChange={(event) => updateCustomInvestment(option.key, "name", event.target.value)}
                            aria-label="Other investment name"
                          />
                        ) : (
                          <strong>{option.title}</strong>
                        )}
                        <small>
                          {option.accountName} · {amount(option.currentValue, currency)} current
                          {option.riskTier ? ` · risk ${option.riskTier}` : ""}
                        </small>
                      </div>
                      {custom && (
                        <button
                          className="icon-button projection-remove-other"
                          type="button"
                          onClick={() => removeOtherInvestment(option.key)}
                          aria-label={`Remove ${custom.name || "other investment"}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                    {selected && assumption && (
                      <div className="projection-investment-fields">
                        {custom && (
                          <>
                            <label>
                              <span>Current value ({currency})</span>
                              <input
                                type="number"
                                min="0"
                                step="0.01"
                                value={custom.currentValue}
                                onChange={(event) => updateCustomInvestment(option.key, "currentValue", event.target.value)}
                              />
                            </label>
                            <label>
                              <span>Cost basis ({currency})</span>
                              <input
                                type="number"
                                min="0"
                                step="0.01"
                                value={custom.costBasis}
                                onChange={(event) => updateCustomInvestment(option.key, "costBasis", event.target.value)}
                              />
                            </label>
                            <label>
                              <span>Tax rate (%)</span>
                              <input
                                type="number"
                                min="0"
                                max="100"
                                step="0.1"
                                value={assumption.taxRate}
                                onChange={(event) => updateAssumption(option.key, "taxRate", event.target.value)}
                              />
                            </label>
                          </>
                        )}
                        <label>
                          <span>Worst annual return (%)</span>
                          <input
                            type="number"
                            min="-99.99"
                            max="100"
                            step="0.1"
                            value={assumption.worst}
                            onChange={(event) => updateAssumption(option.key, "worst", event.target.value)}
                          />
                        </label>
                        <label>
                          <span>Best annual return (%)</span>
                          <input
                            type="number"
                            min="-99.99"
                            max="100"
                            step="0.1"
                            value={assumption.best}
                            onChange={(event) => updateAssumption(option.key, "best", event.target.value)}
                          />
                        </label>
                        {monthlyAmount > 0 && (
                          <label>
                            <span>Monthly share (%)</span>
                            <input
                              type="number"
                              min="0"
                              max="100"
                              step="0.01"
                              value={assumption.contributionPercentage}
                              onChange={(event) => updateAssumption(option.key, "contributionPercentage", event.target.value)}
                            />
                          </label>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <p className="quiet-copy">
            {investmentSearch
              ? "No investments match this search."
              : "No quoted holdings or fixed deposits are available in this scope. Add a custom investment or track an asset first."}
          </p>
        )}
        <p className="projection-scenario-note">
          Existing stock/ETF return bands start from each saved annual-return assumption plus or
          minus the app&apos;s asset-class volatility assumption. Deposit ranges start around the
          contract rate. Both are editable sensitivity assumptions, not probabilities.
        </p>
      </div>

      {error && <div className="inline-error projection-error" role="alert">{error}</div>}
      {projection && (
        <>
          <div className="projection-summary projection-range-summary">
            <div>
              <span>Current value{projection.include_taxes ? " · after tax" : " · before tax"}</span>
              <strong>{amount(projection.scenario_current_net_worth, currency)}</strong>
            </div>
            <div>
              <span>Baseline by {baseYear} · today&apos;s money</span>
              <strong>{amount(projection.baseline_real_projected_net_worth, currency)}</strong>
              <small>Nominal: {amount(projection.baseline_projected_net_worth, currency)}</small>
            </div>
            <div>
              <span>All selected · worst to best · today&apos;s money</span>
              <strong>
                {amount(projection.worst_case_real_projected_net_worth, currency)}
                {" – "}
                {amount(projection.best_case_real_projected_net_worth, currency)}
              </strong>
              <small>
                Nominal: {amount(projection.worst_case_projected_net_worth, currency)}
                {" – "}
                {amount(projection.best_case_projected_net_worth, currency)}
              </small>
            </div>
          </div>

          {chart && (
            <div className="projection-chart-wrap">
              <svg
                viewBox="0 0 900 260"
                preserveAspectRatio="none"
                role="img"
                aria-label="Inflation-adjusted baseline and investment best and worst case account value projections"
              >
                <line x1="20" y1="232" x2="880" y2="232" className="projection-axis" />
                <polyline
                  points={chart.baseline.map((point) => `${point.x},${point.y}`).join(" ")}
                  className="projection-line"
                />
                {chart.lines.map(({ line, points }) => (
                  <polyline
                    key={`${line.asset_key}-${line.case}`}
                    points={points.map((point) => `${point.x},${point.y}`).join(" ")}
                    className="projection-range-line"
                    style={{
                      stroke: lineColor(projection.lines, line),
                      strokeDasharray: line.case === "worst" ? "7 5" : undefined,
                      opacity: line.case === "worst" ? 0.68 : 0.95,
                    }}
                  >
                    <title>
                      {line.asset_name} · {line.case} case · {line.annual_return_assumption
                        ? `${(Number(line.annual_return_assumption) * 100).toFixed(2)}% annual return`
                        : ""}
                    </title>
                  </polyline>
                ))}
              </svg>
              <div className="projection-chart-labels">
                <span>{projection.scenario_baseline_timeline[0]?.label}</span>
                <span>{projection.scenario_baseline_timeline.at(-1)?.label}</span>
              </div>
              <div className="projection-chart-legend-scroll">
                <div className="projection-chart-legend">
                  <span><i className="projection-legend-baseline" /> Baseline</span>
                  {projection.lines.map((line) => (
                    <span key={`${line.asset_key}-${line.case}`}>
                      <i
                        className={line.case === "worst"
                          ? "projection-legend-range-worst"
                          : "projection-legend-range-best"}
                        style={{ backgroundColor: lineColor(projection.lines, line) }}
                      />
                      {line.asset_name} · {line.case}
                    </span>
                  ))}
                </div>
              </div>
              <p className="projection-chart-caption">
                Chart values are in today&apos;s purchasing power after the selected tax setting.
                Each asset&apos;s pair varies that asset alone; the combined range above varies all
                selected assets at once.
              </p>
            </div>
          )}

          {projection.investments.length > 0 && (
            <div className="projection-scenario-results">
              <div className="projection-scenario-results-heading">
                <div>
                  <div className="eyebrow">Selected investment results</div>
                  <h3>Best and worst case at the projection date</h3>
                </div>
                <div className="projection-risk-score">
                  <span>Current qualitative risk score</span>
                  <strong>
                    {projection.risk_summary.weighted_risk_score === null
                      ? "—"
                      : `${Number(projection.risk_summary.weighted_risk_score).toFixed(2)} / 3`}
                  </strong>
                  <small>Only tracked stock/ETF holdings are included</small>
                </div>
              </div>
              <p className="quiet-copy">
                {projection.risk_summary.scope_account_name}: value-weighted X/Y/Z mix across
                current quoted stocks/ETFs; this is qualitative, not measured volatility.
              </p>
              <div className="projection-risk-mix">
                {(["X", "Y", "Z"] as const).map((tier) => (
                  <div className={`projection-risk-tier projection-risk-${tier.toLowerCase()}`} key={tier}>
                    <strong>Tier {tier}</strong>
                    <span>
                      {(Number(projection.risk_summary.risk_mix[tier]) * 100).toFixed(1)}%
                    </span>
                    <small>
                      {amount(
                        Number(projection.risk_summary.current_invested_value)
                          * Number(projection.risk_summary.risk_mix[tier]),
                        currency,
                      )}
                    </small>
                  </div>
                ))}
              </div>
              <div className="projection-range-results-list">
                {projection.investments.map((investment) => (
                  <div className="projection-range-result" key={investment.asset_key}>
                    <strong>{investment.name}</strong>
                    <span>
                      {investment.contribution_percentage}% of monthly amount ·
                      {" "}returns {(Number(investment.worst_annual_return) * 100).toFixed(2)}%
                      {" "}to {(Number(investment.best_annual_return) * 100).toFixed(2)}%/yr
                      {investment.risk_tier ? ` · risk ${investment.risk_tier}` : ""}
                    </span>
                    <small>
                      Contributions {amount(investment.contribution_principal, currency)} · tax
                      {" "}{(Number(investment.estimated_tax_rate) * 100).toFixed(2)}% · estimated
                      {" "}worst tax {amount(investment.worst_estimated_tax, currency)} · best tax
                      {" "}{amount(investment.best_estimated_tax, currency)}
                    </small>
                    <small>
                      Worst: {amount(investment.worst_real_projected_value, currency)} real
                      {" "}({amount(investment.worst_projected_value, currency)} nominal) ·
                      {" "}best: {amount(investment.best_real_projected_value, currency)} real
                      {" "}({amount(investment.best_projected_value, currency)} nominal)
                    </small>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="projection-warning">
            <Info size={15} />
            <ul>
              {[...projection.assumptions, ...projection.warnings].map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
          <details className="projection-methodology">
            <summary>Exact formulas used</summary>
            <p>
              The result is deterministic and treats each entered annual return as constant over
              the full projection period; the best/worst inputs are sensitivity assumptions, not
              probabilities or forecasts.
            </p>
            <ul>
              <li>
                For annual return r and elapsed time t days, an existing stock/ETF balance grows
                by current value × (1 + r)<sup>t / 365</sup>. Cash stays flat except for savings
                interest; fixed deposits earn through maturity and stay flat afterward.
              </li>
              <li>
                For monthly contribution P, monthly growth g = (1 + r)<sup>1 / 12</sup>, and n
                end-of-month payments, future contributions equal P × (g<sup>n</sup> − 1) / (g − 1),
                or P × n when g = 1. The first payment is one month after today. Contributions
                after a deposit's maturity are modelled as flat cash.
              </li>
              <li>
                Each asset's two chart lines change only that asset against the same baseline.
                The combined worst/best totals change all selected assets to their respective
                worst/best assumptions at once. Monthly allocation percentages must total 100%.
              </li>
              <li>
                With taxes enabled, each displayed date is treated as a hypothetical liquidation:
                estimated tax = max(0, gross value − cost basis − contribution principal) × tax
                rate. Holdings use average cost and the saved estimated sale-tax rate; deposits
                use principal and the account's estimated interest-tax rate; other investments use
                the entered cost basis and tax rate. The before-tax option omits these estimates.
              </li>
              <li>
                Real value is nominal value ÷ (1 + annual inflation)<sup>elapsed days / 365</sup>.
                The annual rate is the assumption entered for this calculation and is held
                constant across its selected horizon.
              </li>
            </ul>
          </details>
        </>
      )}
      {!projection && !error && (
        <p className="projection-intro">
          Choose a period and inflation assumption, then calculate the baseline and any selected
          best/worst investment scenarios. Monthly contributions are optional.
        </p>
      )}
    </section>
  );
}
