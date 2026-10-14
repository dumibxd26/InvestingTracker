import { useMemo, useState } from "react";
import { CalendarRange, Info, TrendingUp } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type {
  AccountSummary,
  Currency,
  HoldingSummary,
  PortfolioProjection,
  PortfolioProjectionScenario,
} from "../types";

interface PortfolioProjectionPanelProps {
  currency: Currency;
  accounts: AccountSummary[];
  holdings: HoldingSummary[];
}

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

function projectionValueAtPoint(
  projection: PortfolioProjection,
  pointIndex: number,
  selectedAccountId: string,
): number {
  const point = projection.timeline[pointIndex];
  if (!point) return 0;
  if (!selectedAccountId) return Number(point.total_value);
  return Number(
    point.accounts.find((account) => account.account_id === selectedAccountId)
      ?.projected_total_value ?? "0",
  );
}

function proportionalPercentages(holdings: HoldingSummary[]): Record<string, string> {
  if (holdings.length === 0) return {};
  const values = holdings.map((holding) => Math.max(0, Number(holding.market_value)));
  const total = values.reduce((sum, value) => sum + value, 0);
  const weights = total > 0 ? values.map((value) => value / total) : values.map(() => 1 / values.length);
  const exactUnits = weights.map((weight) => weight * 10000);
  const units = exactUnits.map(Math.floor);
  let remainder = 10000 - units.reduce((sum, value) => sum + value, 0);
  const remainderOrder = exactUnits
    .map((value, index) => ({ index, fractional: value - units[index] }))
    .sort((left, right) => right.fractional - left.fractional);
  for (let index = 0; index < remainder; index += 1) {
    units[remainderOrder[index].index] += 1;
  }
  return Object.fromEntries(
    holdings.map((holding, index) => [holding.id, (units[index] / 100).toFixed(2)]),
  );
}

export function PortfolioProjectionPanel({
  currency,
  accounts,
  holdings,
}: PortfolioProjectionPanelProps) {
  const [preset, setPreset] = useState("10");
  const [targetDate, setTargetDate] = useState(() => dateAfterYears(10));
  const [projection, setProjection] = useState<PortfolioProjection | null>(null);
  const [scenario, setScenario] = useState<PortfolioProjectionScenario | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [scenarioAccountId, setScenarioAccountId] = useState("");
  const [monthlyContribution, setMonthlyContribution] = useState("");
  const [contributionShares, setContributionShares] = useState<Record<string, string>>({});
  const [returnAssumptions, setReturnAssumptions] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const chartValues = useMemo(
    () => projection?.timeline.map((_, index) =>
      projectionValueAtPoint(projection, index, selectedAccountId),
    ) ?? [],
    [projection, selectedAccountId],
  );
  const scenarioChartValues = useMemo(
    () => scenario?.with_contributions.timeline.map((_, index) =>
      projectionValueAtPoint(scenario.with_contributions, index, selectedAccountId),
    ) ?? [],
    [scenario, selectedAccountId],
  );
  const chartLines = useMemo(() => {
    if (chartValues.length < 2) return { baseline: [], scenario: [] };
    const width = 900;
    const height = 260;
    const maximum = Math.max(...chartValues, ...scenarioChartValues, 1) * 1.08;
    const points = (values: number[]) => values.map((value, index) => ({
      x: 20 + index * (width - 40) / (values.length - 1),
      y: height - 28 - value / maximum * (height - 50),
      value,
    }));
    return {
      baseline: points(chartValues),
      scenario: scenarioChartValues.length === chartValues.length
        ? points(scenarioChartValues)
        : [],
    };
  }, [chartValues, scenarioChartValues]);

  const scenarioHoldings = useMemo(
    () => holdings.filter((holding) =>
      accounts.some(
        (account) =>
          account.id === holding.account_id && account.account_type !== "EMPLOYER_PLAN",
      )
      && (!scenarioAccountId || holding.account_id === scenarioAccountId),
    ),
    [accounts, holdings, scenarioAccountId],
  );
  const selectedScenarioHoldings = scenarioHoldings.filter(
    (holding) => holding.id in contributionShares,
  );
  const contributionPercentageTotal = selectedScenarioHoldings.reduce(
    (sum, holding) => sum + Number(contributionShares[holding.id] ?? 0),
    0,
  );

  function handlePresetChange(value: string) {
    setPreset(value);
    if (value !== "custom") setTargetDate(dateAfterYears(Number(value)));
  }

  function toggleScenarioHolding(holding: HoldingSummary, checked: boolean) {
    const selected = scenarioHoldings.filter((item) => item.id in contributionShares);
    const nextHoldings = checked
      ? [...selected, holding]
      : selected.filter((item) => item.id !== holding.id);
    setContributionShares(proportionalPercentages(nextHoldings));
    setReturnAssumptions((current) => {
      if (!checked) {
        const next = { ...current };
        delete next[holding.id];
        return next;
      }
      return {
        ...current,
        [holding.id]: (Number(holding.expected_annual_return) * 100).toFixed(2),
      };
    });
    setScenario(null);
  }

  async function calculate() {
    setError("");
    setLoading(true);
    try {
      const monthlyAmount = Number(monthlyContribution);
      if (!Number.isFinite(monthlyAmount) || monthlyAmount < 0) {
        setError("Enter a non-negative monthly contribution.");
        setLoading(false);
        return;
      }
      let baseline: PortfolioProjection;
      if (monthlyAmount > 0) {
        const totalPercentage = selectedScenarioHoldings.reduce(
          (sum, holding) => sum + Number(contributionShares[holding.id] ?? 0),
          0,
        );
        if (
          selectedScenarioHoldings.length === 0
          || Math.abs(totalPercentage - 100) > 0.001
        ) {
          setError("Select one or more investments and allocate exactly 100% of the monthly contribution.");
          setLoading(false);
          return;
        }
        if (selectedScenarioHoldings.some((holding) => {
          const annualReturn = Number(returnAssumptions[holding.id]);
          return !Number.isFinite(annualReturn) || annualReturn <= -100 || annualReturn > 100;
        })) {
          setError("Each investment's assumed annual return must be greater than −100% and no more than 100%.");
          setLoading(false);
          return;
        }
        const result = await api.portfolioProjectionScenario({
          target_date: targetDate,
          currency,
          monthly_contribution: String(monthlyAmount),
          scope_account_id: scenarioAccountId || null,
          investments: selectedScenarioHoldings.map((holding) => ({
            holding_id: holding.id,
            contribution_percentage: contributionShares[holding.id],
            assumed_annual_return: String(Number(returnAssumptions[holding.id]) / 100),
          })),
        });
        baseline = result.baseline;
        setProjection(baseline);
        setScenario(result);
      } else {
        baseline = await api.portfolioProjection(targetDate, currency);
        setProjection(baseline);
        setScenario(null);
      }
      if (
        selectedAccountId
        && !baseline.accounts.some((account) => account.account_id === selectedAccountId)
      ) {
        setSelectedAccountId("");
      }
    } catch (cause) {
      setProjection(null);
      setScenario(null);
      setError(cause instanceof ApiError ? cause.message : "The portfolio projection could not be calculated.");
    } finally {
      setLoading(false);
    }
  }

  const currentValue = selectedAccountId
    ? Number(projection?.accounts.find((account) => account.account_id === selectedAccountId)?.current_value ?? "0")
    : Number(projection?.current_net_worth ?? "0");
  const baselineProjectedValue = selectedAccountId
    ? Number(projection?.accounts.find((account) => account.account_id === selectedAccountId)?.projected_total_value ?? "0")
    : Number(projection?.projected_net_worth ?? "0");
  const projectedValue = scenario
    ? selectedAccountId
      ? Number(scenario.with_contributions.accounts.find(
        (account) => account.account_id === selectedAccountId,
      )?.projected_total_value ?? "0")
      : Number(scenario.with_contributions.projected_net_worth)
    : baselineProjectedValue;
  const chartBaseline = chartLines.baseline;
  const chartScenario = chartLines.scenario;

  return (
    <section className="panel portfolio-projection-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">Illustrative scenario</div>
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
            }}
          />
        </label>
        <button className="button button-primary" type="button" onClick={() => void calculate()} disabled={loading || !targetDate}>
          <CalendarRange size={15} /> {loading ? "Calculating…" : "Calculate projection"}
        </button>
      </div>
      <div className="projection-scenario-controls">
        <div className="projection-scenario-heading">
          <div>
            <h3>What if I invest every month?</h3>
            <p>Choose tracked stocks/ETFs and enter a monthly amount. This is hypothetical and does not change your balances.</p>
          </div>
        </div>
        <div className="projection-scenario-inputs">
          <label className="form-field">
            <span>Monthly amount ({currency})</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={monthlyContribution}
              onChange={(event) => {
                setMonthlyContribution(event.target.value);
                setScenario(null);
              }}
              placeholder="e.g. 500"
            />
          </label>
          <label className="form-field">
            <span>Calculate current risk for</span>
            <select
              value={scenarioAccountId}
              onChange={(event) => {
                setScenarioAccountId(event.target.value);
                setContributionShares({});
                setScenario(null);
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
        </div>
        {scenarioHoldings.length > 0 ? (
          <div className="projection-investment-list">
            <div className="projection-investment-header">
              <strong>Allocate 100% of new monthly contributions</strong>
              {selectedScenarioHoldings.length > 0 && (
                <span className={
                  Math.abs(contributionPercentageTotal - 100) <= 0.001
                    ? "projection-allocation-valid"
                    : "projection-allocation-invalid"
                }>
                  {contributionPercentageTotal.toFixed(2)}% allocated
                </span>
              )}
            </div>
            {scenarioHoldings.map((holding) => {
              const selected = holding.id in contributionShares;
              return (
                <div className="projection-investment-row" key={holding.id}>
                  <label className="projection-investment-choice">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={(event) => toggleScenarioHolding(holding, event.target.checked)}
                    />
                    <span>
                      <strong>{holding.symbol} · {holding.account_name}</strong>
                      <small>
                        {amount(holding.market_value, currency)} current · risk {holding.risk_tier}
                      </small>
                    </span>
                  </label>
                  {selected && (
                    <div className="projection-investment-assumptions">
                      <label>
                        <span>Monthly share</span>
                        <span className="projection-number-with-unit">
                          <input
                            type="number"
                            min="0.01"
                            max="100"
                            step="0.01"
                            value={contributionShares[holding.id]}
                            onChange={(event) => {
                              setContributionShares((current) => ({
                                ...current,
                                [holding.id]: event.target.value,
                              }));
                              setScenario(null);
                            }}
                            aria-label={`Monthly contribution share for ${holding.symbol}`}
                          />
                          %
                        </span>
                      </label>
                      <label>
                        <span>Annual return assumption</span>
                        <span className="projection-number-with-unit">
                          <input
                            type="number"
                            min="-99.99"
                            max="100"
                            step="0.1"
                            value={returnAssumptions[holding.id] ?? ""}
                            onChange={(event) => {
                              setReturnAssumptions((current) => ({
                                ...current,
                                [holding.id]: event.target.value,
                              }));
                              setScenario(null);
                            }}
                            aria-label={`Annual return assumption for ${holding.symbol}`}
                          />
                          %
                        </span>
                      </label>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="quiet-copy">
            No quoted stock or ETF positions are available in this scope. Add or quote an investment first.
          </p>
        )}
        <p className="projection-scenario-note">
          The current X/Y/Z tiers are qualitative labels, not measured volatility. The scenario
          reports their value-weighted mix and lets you edit each selected investment&apos;s return.
        </p>
      </div>
      {error && <div className="inline-error projection-error" role="alert">{error}</div>}
      {projection && (
        <>
          <div className="projection-summary">
            <div>
              <span>{selectedAccountId ? "Selected account now" : "Tracked wealth now"}</span>
              <strong>{amount(currentValue, currency)}</strong>
            </div>
            <div>
              <span>{scenario ? "With monthly contributions" : "Projected"} by {new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(projection.target_date))}</span>
              <strong>{amount(projectedValue, currency)}</strong>
              {scenario && (
                <small className="projection-baseline-caption">
                  Without new contributions: {amount(baselineProjectedValue, currency)}
                </small>
              )}
            </div>
            <div>
              <span>Illustrative change</span>
              <strong className={projectedValue >= currentValue ? "positive-text" : "negative-text"}>
                {amount(projectedValue - currentValue, currency)}
              </strong>
            </div>
            <label className="form-field projection-account-select">
              <span>Show series</span>
              <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value)}>
                <option value="">All accounts</option>
                {projection.accounts.map((account) => (
                  <option value={account.account_id} key={account.account_id}>{account.account_name}</option>
                ))}
              </select>
            </label>
          </div>
          {chartBaseline.length > 1 && (
            <div className="projection-chart-wrap">
              <svg viewBox="0 0 900 260" preserveAspectRatio="none" role="img" aria-label="Projected account value by date">
                <line x1="20" y1="232" x2="880" y2="232" className="projection-axis" />
                <polyline
                  points={chartBaseline.map((point) => `${point.x},${point.y}`).join(" ")}
                  className="projection-line"
                />
                {chartScenario.length > 1 && (
                  <polyline
                    points={chartScenario.map((point) => `${point.x},${point.y}`).join(" ")}
                    className="projection-scenario-line"
                  />
                )}
                {chartBaseline.map((point, index) => (
                  <g key={`${projection.timeline[index]?.date ?? index}`}>
                    <circle cx={point.x} cy={point.y} r="4" className="projection-point" />
                    <title>
                      Baseline · {projection.timeline[index]?.label}: {amount(point.value, currency)}
                    </title>
                  </g>
                ))}
                {chartScenario.map((point, index) => (
                  <g key={`scenario-${scenario?.with_contributions.timeline[index]?.date ?? index}`}>
                    <circle cx={point.x} cy={point.y} r="3.5" className="projection-scenario-point" />
                    <title>
                      With contributions · {scenario?.with_contributions.timeline[index]?.label}: {amount(point.value, currency)}
                    </title>
                  </g>
                ))}
              </svg>
              <div className="projection-chart-labels">
                <span>{projection.timeline[0]?.label}</span>
                <span>{projection.timeline[projection.timeline.length - 1]?.label}</span>
              </div>
              {scenario && (
                <div className="projection-chart-legend">
                  <span><i className="projection-legend-baseline" /> Existing portfolio</span>
                  <span><i className="projection-legend-scenario" /> With monthly investments</span>
                </div>
              )}
            </div>
          )}
          <div className="projection-account-list">
            {projection.accounts.map((account) => (
              <div className="projection-account-row" key={account.account_id}>
                <strong>{account.account_name}</strong>
                <span>{amount(account.current_value, currency)}</span>
                <span>
                  → {amount(
                    scenario?.with_contributions.accounts.find(
                      (scenarioAccount) => scenarioAccount.account_id === account.account_id,
                    )?.projected_total_value ?? account.projected_total_value,
                    currency,
                  )}
                  {scenario && (
                    <small className="projection-baseline-caption">
                      baseline {amount(account.projected_total_value, currency)}
                    </small>
                  )}
                </span>
              </div>
            ))}
          </div>
          {scenario && (
            <div className="projection-scenario-results">
              <div className="projection-scenario-results-heading">
                <div>
                  <div className="eyebrow">Monthly investment what-if</div>
                  <h3>Current risk mix and contribution assumptions</h3>
                  <p className="projection-weighted-return">
                    Contribution-weighted annual return assumption:
                    {" "}{(Number(scenario.weighted_annual_return_assumption) * 100).toFixed(2)}%
                  </p>
                </div>
                <div className="projection-risk-score">
                  <span>Qualitative risk score</span>
                  <strong>
                    {scenario.risk_summary.weighted_risk_score === null
                      ? "—"
                      : `${Number(scenario.risk_summary.weighted_risk_score).toFixed(2)} / 3`}
                  </strong>
                  <small>
                    New contribution mix: {Number(scenario.risk_summary.contribution_weighted_risk_score).toFixed(2)} / 3
                  </small>
                </div>
              </div>
              <p className="quiet-copy">
                {scenario.risk_summary.scope_account_name}: value-weighted risk mix of existing
                quoted investments; not a statistical volatility estimate.
              </p>
              <div className="projection-risk-mix">
                {(["X", "Y", "Z"] as const).map((tier) => (
                  <div className={`projection-risk-tier projection-risk-${tier.toLowerCase()}`} key={tier}>
                    <strong>Tier {tier}</strong>
                    <span>{(Number(scenario.risk_summary.risk_mix[tier]) * 100).toFixed(1)}%</span>
                    <small>{amount(
                      Number(scenario.risk_summary.current_invested_value)
                        * Number(scenario.risk_summary.risk_mix[tier]),
                      currency,
                    )}</small>
                  </div>
                ))}
              </div>
              <div className="projection-investment-results">
                {scenario.investments.map((investment) => (
                  <div className="projection-investment-result" key={investment.holding_id}>
                    <strong>{investment.symbol} · {investment.account_name}</strong>
                    <span>{investment.contribution_percentage}% of monthly sum · risk {investment.risk_tier}</span>
                    <span>
                      {amount(investment.monthly_contribution, currency)}/mo at
                      {" "}{(Number(investment.assumed_annual_return) * 100).toFixed(2)}%/yr
                    </span>
                    <small>
                      Contributions {amount(investment.contribution_principal, currency)} ·
                      {" "}projected after-tax value {amount(investment.projected_after_tax_value, currency)} ·
                      {" "}estimated tax {amount(investment.estimated_tax, currency)}
                    </small>
                  </div>
                ))}
              </div>
              <details className="projection-methodology">
                <summary>Exact scenario assumptions and formulas</summary>
                <ul>
                  {scenario.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
                </ul>
                <p>
                  For annual return r and monthly growth factor g = (1 + r)<sup>1/12</sup>, the
                  gross future value is monthly amount × (g<sup>n</sup> − 1) / (g − 1), where n
                  is the number of scheduled monthly contributions before the target date. If g
                  equals 1, it is monthly amount × n. The net value subtracts the current
                  estimated tax rate applied to positive growth above total contributions.
                </p>
              </details>
            </div>
          )}
          <div className="projection-warning">
            <Info size={15} />
            <ul>
              {(scenario?.with_contributions.warnings ?? projection.warnings)
                .map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </div>
          <details className="projection-methodology">
            <summary>How the baseline projection is calculated</summary>
            <ul>
              <li>
                For each existing quoted stock/ETF: current quantity × current quote ×
                (1 + that holding&apos;s saved annual return assumption)<sup>days / 365</sup>.
                Return is nominal, includes assumed reinvested distributions, and is compounded
                using an effective annual rate.
              </li>
              <li>
                Positive projected gains are reduced by that holding&apos;s current estimated
                sale-tax rate, applied to max(0, projected gross value − current cost basis);
                losses do not receive a tax credit.
              </li>
              <li>
                FX uses the latest available rates and is held constant through the projection.
                A savings wallet projects as current balance × (1 + annual rate / 12)<sup>future
                monthly periods</sup>; ordinary cash stays flat.
              </li>
              <li>
                Fixed deposits accrue under their configured rate basis and compounding frequency
                only until maturity; matured proceeds do not earn a further return. Effective APY
                uses principal × (1 + APY)<sup>days / 365</sup>. Nominal APR uses its configured
                periodic rate, compounds full periods, and prorates a partial period; at-maturity
                products use simple APR over elapsed days.
              </li>
              <li>
                Other cash remains flat. Future salary/bonuses, scheduled share purchases,
                unvested awards, and new monthly investment contributions are excluded unless
                you run the separate contribution scenario above.
              </li>
              <li>
                Risk tiers are qualitative placeholders. This is a deterministic scenario, not
                a volatility model, probability of loss, prediction, or investment advice.
              </li>
            </ul>
          </details>
        </>
      )}
      {!projection && !error && (
        <p className="projection-intro">
          Calculate the existing-portfolio projection, or enter a monthly amount and choose
          specific holdings above to compare a contribution scenario.
        </p>
      )}
    </section>
  );
}
