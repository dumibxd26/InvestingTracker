import {
  ArrowRight,
  ArrowUpRight,
  CalendarClock,
  CircleDollarSign,
  Clock3,
  Plus,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import { amount, dateLabel, goalLabel } from "../format";
import type { Currency, Dashboard, GoalSummary } from "../types";
import { AllocationDonut } from "./AllocationDonut";
import { PortfolioChart } from "./PortfolioChart";

interface OverviewProps {
  data: Dashboard;
  currency: Currency;
  onAddGoal: () => void;
  onPreview: () => void;
  onOpenGoals: () => void;
  onOpenCashFlow: () => void;
}

function GoalCard({ goal, currency }: { goal: GoalSummary; currency: Currency }) {
  const incomeGoal = goal.goal_type === "passive_income";
  const target = incomeGoal ? goal.target_annual_income : goal.target_amount;
  const current = goal.current_amount;
  const progress = Math.min(100, Number(goal.progress_percent));
  return (
    <article className="goal-card">
      <div className="goal-card-top">
        <span className={`goal-icon goal-${goal.goal_type}`}>
          {incomeGoal ? <CircleDollarSign size={18} /> : <Sparkles size={18} />}
        </span>
        <span className="goal-priority">P{goal.priority}</span>
      </div>
      <div className="goal-title-row">
        <h3>{goal.name}</h3>
        <span className="goal-type">{goalLabel(goal.goal_type)}</span>
      </div>
      <div className="goal-progress-copy">
        <strong>{amount(current, currency)}</strong>
        <span>of {target ? amount(target, currency) : "no target set"}</span>
      </div>
      <div className="progress-track" aria-label={`${progress.toFixed(0)} percent complete`}>
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="goal-card-footer">
        <span>{progress.toFixed(0)}% funded</span>
        <span>{goal.target_date ? `Target ${dateLabel(goal.target_date, { month: "short", year: "numeric" })}` : "Ongoing"}</span>
      </div>
    </article>
  );
}

export function Overview({
  data,
  currency,
  onAddGoal,
  onPreview,
  onOpenGoals,
  onOpenCashFlow,
}: OverviewProps) {
  const total = data.totals;
  const reserveGap = Number(total.reserve_shortfall);
  const greeting = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" }).format(new Date());

  return (
    <div className="page-content">
      <div className="page-intro">
        <div>
          <div className="eyebrow">{greeting}</div>
          <h1>Your wealth, in focus.</h1>
          <p>A clearer view of what you have, what you’re building, and what comes next.</p>
        </div>
        <button className="button button-primary" onClick={onPreview}>
          <Sparkles size={17} />
          Plan fresh cash
        </button>
      </div>

      <div className="metric-grid">
        <section className="metric-card metric-primary">
          <div className="metric-top">
            <span>Total tracked wealth</span>
            <span className="metric-icon"><Wallet size={17} /></span>
          </div>
          <div className="metric-value">{amount(total.net_worth, currency)}</div>
          <div className="metric-foot">
            <span className="metric-trend"><ArrowUpRight size={15} /> {amount(data.six_month_change, currency)} <small>illustrative · 6 months</small></span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-top">
            <span>Invested assets</span>
            <span className="metric-icon soft-green"><ArrowUpRight size={17} /></span>
          </div>
          <div className="metric-value">{amount(total.invested_assets, currency)}</div>
          <div className="metric-foot"><span>{data.holdings.length} sample positions</span><span>Across 3 classes</span></div>
        </section>
        <section className="metric-card">
          <div className="metric-top">
            <span>Available cash</span>
            <span className="metric-icon soft-blue"><CircleDollarSign size={17} /></span>
          </div>
          <div className="metric-value">{amount(total.available_cash, currency)}</div>
          <div className={`metric-foot ${reserveGap > 0 ? "text-warning" : ""}`}>
            <span>{reserveGap > 0 ? `${amount(reserveGap, currency)} reserve shortfall` : "Reserve target on track"}</span>
            <span>{amount(total.emergency_reserve_target, currency)} target</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-top">
            <span>Unvested equity</span>
            <span className="metric-icon soft-gold"><Sparkles size={17} /></span>
          </div>
          <div className="metric-value">{amount(total.unvested_equity_gross, currency)}</div>
          <div className="metric-foot"><span>Gross estimate</span><span>{amount(total.unvested_equity_net_estimate, currency)} after assumed tax</span></div>
        </section>
      </div>

      <div className="dashboard-grid dashboard-grid-top">
        <PortfolioChart
          points={data.chart}
          currency={currency}
          change={data.six_month_change}
          changePercent={data.six_month_change_percent}
        />
        <AllocationDonut allocation={data.allocation} currency={currency} />
      </div>

      <div className="section-heading">
        <div>
          <div className="eyebrow">Your priorities</div>
          <h2>Goals that move you forward</h2>
        </div>
        <div className="section-actions">
          <button className="text-button" onClick={onOpenGoals}>All goals <ArrowRight size={15} /></button>
          <button className="button button-quiet" onClick={onAddGoal}><Plus size={16} /> Add goal</button>
        </div>
      </div>
      <div className="goal-grid">
        {data.goals.slice(0, 3).map((goal) => <GoalCard key={goal.id} goal={goal} currency={currency} />)}
        {data.goals.length === 0 && (
          <div className="empty-state panel">
            <TargetIcon />
            <strong>Start with what matters to you.</strong>
            <span>Add a goal; you can change its priority or target later.</span>
            <button className="button button-primary" onClick={onAddGoal}><Plus size={16} /> Add a goal</button>
          </div>
        )}
      </div>

      <div className="dashboard-grid dashboard-grid-bottom">
        <section className="panel cash-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">Coming up</div>
              <h2>Cash flow</h2>
            </div>
            <button className="icon-button small" aria-label="View cash flow" onClick={onOpenCashFlow}><ArrowRight size={17} /></button>
          </div>
          <div className="flow-list">
            {data.cash_flows.slice(0, 3).map((flow) => {
              const expected = flow.status === "forecast";
              return (
                <div className="flow-row" key={flow.id}>
                  <span className={`flow-icon ${expected ? "flow-forecast" : "flow-confirmed"}`}>
                    {expected ? <CalendarClock size={17} /> : <CircleDollarSign size={17} />}
                  </span>
                  <span className="flow-copy">
                    <strong>{flow.label.replace(" · forecast", "").replace(" · sample", "")}</strong>
                    <small>{expected ? `Expected ${dateLabel(flow.expected_date)}` : "Received"}</small>
                  </span>
                  <span className={flow.kind === "bill" ? "flow-negative" : "flow-positive"}>
                    {flow.kind === "bill" ? "−" : "+"}{amount(flow.amount, flow.currency)}
                  </span>
                </div>
              );
            })}
            {data.cash_flows.length === 0 && <p className="quiet-copy">Add cash-flow schedules to see upcoming liquidity.</p>}
          </div>
          <button className="panel-link" onClick={onOpenCashFlow}>View cash calendar <ArrowRight size={14} /></button>
        </section>

        <section className="panel next-step-panel">
          <span className="next-step-icon"><ShieldCheck size={19} /></span>
          <div className="eyebrow">A thoughtful next step</div>
          <h2>Your plan stays in your hands.</h2>
          <p>Preview how new money could support your goals and bring your invested mix closer to its targets. Nothing is traded automatically.</p>
          <button className="button button-dark" onClick={onPreview}>Preview an allocation <ArrowRight size={16} /></button>
          <div className="next-step-note"><Clock3 size={14} /> Takes a moment · review before you decide</div>
        </section>
      </div>
    </div>
  );
}

function TargetIcon() {
  return <Sparkles size={22} aria-hidden="true" />;
}
