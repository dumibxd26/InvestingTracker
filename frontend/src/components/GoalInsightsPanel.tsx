import { useState } from "react";
import { amount } from "../format";
import type {
  Currency,
  GoalInsights,
  GoalInsightsRecovery,
  GoalInsightsTickerProposal,
  GoalInsightsTrimProposal,
  GoalInsightsYearPoint,
} from "../types";

const BUCKET_ORDER = ["CASH", "BONDS", "EQUITIES"] as const;
const BUCKET_LABELS: Record<string, string> = { CASH: "Cash", BONDS: "Bonds", EQUITIES: "Equities" };
const RECOMMENDATION_LABELS: Record<GoalInsightsTrimProposal["recommendation_type"], string> = {
  EXECUTE_TAX_FREE_OR_TLH: "Sell, no tax",
  EXECUTE_LOW_TAX_DRAG: "Sell, low tax",
  DEFER_USE_INFLOWS_INSTEAD: "Wait for deposits",
};

function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function compact(value: number): string {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (absolute >= 1_000) return `${Math.round(value / 1_000)}k`;
  return `${Math.round(value)}`;
}

interface GoalInsightsPanelProps {
  insights: GoalInsights;
}

export function GoalInsightsPanel({ insights }: GoalInsightsPanelProps) {
  const { goal, evaluation, simulation, recovery, rebalance_plan: rebalance, analytical_bands: bands } =
    insights;
  if (!insights.available || !goal || !evaluation || !simulation || !recovery || !rebalance || !bands) {
    return (
      <div className="goal-insights">
        <p className="quiet-copy">{insights.unavailable_reason ?? "Insights are not available for this goal yet."}</p>
      </div>
    );
  }
  const currency: Currency = goal.base_currency;
  const routedBuckets = rebalance.monthly_contribution_routing.filter((item) => item.allocated_contribution > 0);

  return (
    <div className="goal-insights">
      <div className="goal-insight-stats">
        <Stat label="Chance of reaching target" value={pct(simulation.success_probability, 0)} hint={`Goal: ${pct(goal.target_success_probability, 0)}`} />
        <Stat label="Value today after est. sale tax" value={amount(evaluation.after_tax_value, currency)} hint={`${evaluation.remaining_years.toFixed(1)} years left`} />
        <Stat label="Target in today's money" value={amount(simulation.real_target_in_todays_dollars, currency)} hint={`Nominal at deadline ${amount(simulation.nominal_target_at_maturity, currency)}`} />
        <Stat label="Expected return / volatility" value={`${pct(evaluation.expected_return_mu)} / ${pct(evaluation.portfolio_volatility_sigma)}`} hint={`Median compounding ${pct(evaluation.median_compounding_rate)}`} />
      </div>

      <section className="goal-insight-block">
        <h4>Projected value range</h4>
        <FanChart
          points={simulation.yearly_schedule}
          inflation={goal.tax_profile.annual_inflation_rate}
          currency={currency}
        />
        <p className="quiet-copy">
          Simple projection at {pct(bands.expected_rate)} a year: {amount(bands.projected_value_expected, currency)}
          {" "}(range {amount(bands.projected_value_conservative, currency)} to {amount(bands.projected_value_optimistic, currency)}).
        </p>
      </section>

      <section className="goal-insight-block">
        <h4>Allocation against glide path</h4>
        <table className="goal-insight-table">
          <thead>
            <tr><th>Bucket</th><th>Now</th><th>Target</th><th>Action</th></tr>
          </thead>
          <tbody>
            {BUCKET_ORDER.map((bucket) => {
              const drift = evaluation.bucket_drifts[bucket];
              if (!drift) return null;
              const delta = drift.dollar_delta_to_target;
              return (
                <tr key={bucket} className={drift.is_breached ? "is-breached" : ""}>
                  <td>{BUCKET_LABELS[bucket]}</td>
                  <td>{pct(drift.current_weight, 0)}</td>
                  <td>{pct(drift.target_weight, 0)}</td>
                  <td>
                    {Math.abs(delta) < 1
                      ? "On target"
                      : delta > 0
                        ? `Buy ${amount(delta, currency)}`
                        : `Sell ${amount(-delta, currency)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="goal-insight-block">
        <h4>Next monthly contribution</h4>
        {routedBuckets.length === 0 && <p className="quiet-copy">No contribution is planned for this goal.</p>}
        <ul className="goal-insight-list">
          {routedBuckets.map((item) => (
            <li key={item.bucket}>
              <strong>{amount(item.allocated_contribution, currency)}</strong> to {BUCKET_LABELS[item.bucket]}
              <span className="quiet-copy"> ({pct(item.share_of_contribution, 0)} of contribution)</span>
              {item.suggested_tickers.length > 0 && (
                <TickerList proposals={item.suggested_tickers} />
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="goal-insight-block">
        <h4>Risk warnings</h4>
        {evaluation.warnings.length === 0 && <p className="quiet-copy">No concentration or currency warnings.</p>}
        <ul className="goal-insight-list">
          {evaluation.warnings.map((warning) => (
            <li key={`${warning.reason}-${warning.holding_id}`}>
              <strong>{warning.ticker}</strong> {warning.message}
              {warning.suggested_fix && <span className="quiet-copy"> {warning.suggested_fix}</span>}
            </li>
          ))}
        </ul>
      </section>

      {rebalance.tax_aware_trim_proposals.length > 0 && (
        <section className="goal-insight-block">
          <h4>Sales to consider</h4>
          <ul className="goal-insight-list">
            {rebalance.tax_aware_trim_proposals.map((trim) => (
              <TrimItem key={trim.holding_id} trim={trim} currency={currency} />
            ))}
          </ul>
        </section>
      )}

      {rebalance.rebalance_buy_proposals.length > 0 && (
        <section className="goal-insight-block">
          <h4>Rebalancing buys</h4>
          <TickerList proposals={rebalance.rebalance_buy_proposals} />
        </section>
      )}

      <section className="goal-insight-block">
        <h4>Recovery options</h4>
        <RecoveryOptions recovery={recovery} />
      </section>

      <section className="goal-insight-block">
        <h4>Assumptions</h4>
        <ul className="goal-insight-list quiet-copy">
          {insights.assumptions.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="goal-insight-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  );
}

function TickerList({ proposals }: { proposals: GoalInsightsTickerProposal[] }) {
  return (
    <ul className="goal-insight-tickers">
      {proposals.map((proposal) => (
        <li key={proposal.ticker}>
          <strong>{proposal.ticker}</strong> {proposal.name}
          <span className="quiet-copy"> · {proposal.rationale}</span>
        </li>
      ))}
    </ul>
  );
}

function TrimItem({ trim, currency }: { trim: GoalInsightsTrimProposal; currency: Currency }) {
  return (
    <li>
      <strong>{trim.ticker}</strong> · {RECOMMENDATION_LABELS[trim.recommendation_type]}
      <span className="quiet-copy">
        {" "}· sell {amount(trim.gross_sell_amount, currency)}, tax {amount(trim.total_estimated_tax, currency)}
        {" "}({pct(trim.effective_tax_drag_pct)} drag)
      </span>
      <div className="quiet-copy">{trim.rationale}</div>
    </li>
  );
}

const RECOVERY_TITLES = {
  increase_contribution_plan: "Save more each month",
  extend_timeline_plan: "Extend the deadline",
  optimize_portfolio_plan: "Adjust the portfolio mix",
} as const;

const UNREACHABLE_LABELS: Record<string, string> = {
  INCREASE_CONTRIBUTION: "saving more",
  EXTEND_TIMELINE: "extending the deadline",
};

function RecoveryOptions({ recovery }: { recovery: GoalInsightsRecovery }) {
  if (recovery.is_goal_on_track) {
    return (
      <p className="goal-insight-ok">
        On track: {pct(recovery.current_success_probability, 0)} chance against a {pct(recovery.target_success_probability, 0)} goal.
      </p>
    );
  }
  const cards = [
    { key: "increase_contribution_plan" as const, plan: recovery.plans.increase_contribution_plan },
    { key: "extend_timeline_plan" as const, plan: recovery.plans.extend_timeline_plan },
    { key: "optimize_portfolio_plan" as const, plan: recovery.plans.optimize_portfolio_plan },
  ];
  return (
    <>
      <div className="goal-recovery-grid">
        {cards.map(({ key, plan }) =>
          plan ? (
            <article className="goal-recovery-card" key={key}>
              <strong>{RECOVERY_TITLES[key]}</strong>
              <p>{plan.description}</p>
              <small>Chance after change: {pct(plan.resulting_success_probability, 0)}</small>
            </article>
          ) : null,
        )}
      </div>
      {recovery.plans.unreachable_levers.length > 0 && (
        <p className="quiet-copy">
          No solution within the search range for {recovery.plans.unreachable_levers
            .map((lever) => UNREACHABLE_LABELS[lever] ?? lever.toLowerCase())
            .join(" or ")}.
        </p>
      )}
      <p className="quiet-copy">Current chance: {pct(recovery.current_success_probability, 0)} (target {pct(recovery.target_success_probability, 0)}).</p>
    </>
  );
}

interface FanChartProps {
  points: GoalInsightsYearPoint[];
  inflation: number;
  currency: Currency;
}

function FanChart({ points, inflation, currency }: FanChartProps) {
  const [basis, setBasis] = useState<"real" | "nominal">("real");
  if (points.length < 2) return <p className="quiet-copy">Not enough years to draw a projection.</p>;

  const width = 640;
  const height = 240;
  const margin = { top: 14, right: 18, bottom: 28, left: 56 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const lastYear = points[points.length - 1].year;

  const series = points.map((point) => {
    const deflator = (1 + inflation) ** point.year;
    const values = basis === "real" ? point.real_todays_dollars : point.nominal_after_tax;
    return {
      year: point.year,
      p10: values.p10,
      p50: values.p50,
      p90: values.p90,
      target: basis === "real" ? point.inflated_target_at_year / deflator : point.inflated_target_at_year,
    };
  });
  const top = Math.max(1, ...series.map((item) => Math.max(item.p90, item.target))) * 1.05;
  const x = (year: number) => margin.left + (year / lastYear) * innerWidth;
  const y = (value: number) => margin.top + innerHeight - (value / top) * innerHeight;
  const path = (valueOf: (item: (typeof series)[number]) => number) =>
    series
      .map((item, index) => `${index === 0 ? "M" : "L"}${x(item.year).toFixed(1)},${y(valueOf(item)).toFixed(1)}`)
      .join(" ");
  const band = [
    ...series.map((item) => `${x(item.year).toFixed(1)},${y(item.p90).toFixed(1)}`),
    ...[...series].reverse().map((item) => `${x(item.year).toFixed(1)},${y(item.p10).toFixed(1)}`),
  ].join(" ");
  const yTicks = [0, 0.5, 1].map((fraction) => (top / 1.05) * fraction);
  const step = Math.max(1, Math.ceil(lastYear / 6));
  const xTicks = series.filter((item) => item.year % step === 0);

  return (
    <div className="goal-fan-chart">
      <div className="goal-insights-toggle" role="group" aria-label="Value basis">
        <button type="button" aria-pressed={basis === "real"} onClick={() => setBasis("real")}>
          Today&apos;s money
        </button>
        <button type="button" aria-pressed={basis === "nominal"} onClick={() => setBasis("nominal")}>
          Nominal
        </button>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Projected after-tax value range by year">
        {yTicks.map((tick) => (
          <g key={tick}>
            <line className="fan-grid" x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} />
            <text className="fan-axis" x={margin.left - 6} y={y(tick) + 4} textAnchor="end">{compact(tick)}</text>
          </g>
        ))}
        {xTicks.map((item) => (
          <text className="fan-axis" key={item.year} x={x(item.year)} y={height - 8} textAnchor="middle">
            {item.year === 0 ? "Now" : `Y${item.year}`}
          </text>
        ))}
        <polygon className="fan-band" points={band} />
        <path className="fan-median" d={path((item) => item.p50)} />
        <path className="fan-target" d={path((item) => item.target)} />
      </svg>
      <div className="fan-legend">
        <span><i className="swatch band" /> 10th–90th percentile</span>
        <span><i className="swatch median" /> Median</span>
        <span><i className="swatch target" /> Target</span>
        <span className="quiet-copy">{basis === "real" ? "Values in today's money" : `Values in ${currency}, not adjusted for inflation`}</span>
      </div>
    </div>
  );
}
