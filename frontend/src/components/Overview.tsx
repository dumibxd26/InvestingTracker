import {
  ArrowRight,
  ArrowUpRight,
  Building2,
  CalendarClock,
  CircleDollarSign,
  Clock3,
  Plus,
  ShieldCheck,
  Sparkles,
  Wallet,
  WalletCards,
} from "lucide-react";
import { amount, dateLabel, goalLabel } from "../format";
import type { Currency, Dashboard, GoalSummary } from "../types";
import { AllocationDonut } from "./AllocationDonut";
import { InvestmentHeatmap } from "./InvestmentHeatmap";
import { PortfolioChart } from "./PortfolioChart";
import { PortfolioProjectionPanel } from "./PortfolioProjectionPanel";

interface OverviewProps {
  data: Dashboard;
  currency: Currency;
  onAddGoal: () => void;
  onPreview: () => void;
  onOpenGoals: () => void;
  onOpenCashFlow: () => void;
  onOpenPortfolio: () => void;
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
  onOpenPortfolio,
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

      {data.accounts.length === 0 && (
        <section className="portfolio-setup-banner">
          <span className="portfolio-setup-icon"><WalletCards size={19} /></span>
          <div>
            <strong>Bring your accounts and investments together</strong>
            <p>
              Enter your banks and brokers, opening balances for each currency, and the stocks or
              ETFs you already own in one guided setup.
            </p>
          </div>
          <button className="button button-primary" type="button" onClick={onOpenPortfolio}>
            Set up portfolio <ArrowRight size={15} />
          </button>
        </section>
      )}

      <div className="metric-grid">
        <section className="metric-card metric-primary">
          <div className="metric-top">
            <span>Total tracked wealth · after tax estimate</span>
            <span className="metric-icon"><Wallet size={17} /></span>
          </div>
          <div className="metric-value">{amount(total.net_worth, currency)}</div>
          <div className="metric-foot">
            <span className="metric-trend"><ArrowUpRight size={15} /> {amount(data.six_month_change, currency)} <small>illustrative · 6 months</small></span>
            <span>Excludes unvested awards and future income</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-top">
            <span>Owned investments · after tax</span>
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
            <span>Unvested awards · excluded</span>
            <span className="metric-icon soft-gold"><Sparkles size={17} /></span>
          </div>
          <div className="metric-value">{amount(total.unvested_equity_gross, currency)}</div>
          <div className="metric-foot unvested-scenario-foot">
            <span>Sell before one year · {amount(total.unvested_equity_short_term_sale_estimate, currency)}</span>
            <span>Sell after one year · {amount(total.unvested_equity_long_term_sale_estimate, currency)}</span>
          </div>
        </section>
      </div>

      {data.account_wealth.length > 0 && (
        <section className="panel account-wealth-overview">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">Your accounts</div>
              <h2>Account values after estimated tax</h2>
            </div>
            <button className="text-button" type="button" onClick={onOpenPortfolio}>
              Account details <ArrowRight size={15} />
            </button>
          </div>
          <div className="account-wealth-grid">
            {data.account_wealth.map((account) => (
              <article className="account-wealth-card" key={account.id}>
                <div className="account-wealth-heading">
                  <span className="account-wealth-icon"><Building2 size={17} /></span>
                  <span className="account-wealth-name">
                    <strong>{account.display_name}</strong>
                    <small>{account.account_type.toLowerCase().replace("_", " ")}</small>
                  </span>
                  <strong className="account-wealth-total">
                    {amount(account.total_after_tax_value, currency)}
                  </strong>
                </div>
                <div className="account-wealth-lines">
                  <div><span>Owned holdings · gross</span><strong>{amount(account.gross_holdings_value, currency)}</strong></div>
                  <div><span>Estimated tax on gains</span><strong>−{amount(account.estimated_sale_tax, currency)}</strong></div>
                  <div><span>Holdings · after tax</span><strong>{amount(account.after_tax_holdings_value, currency)}</strong></div>
                  <div><span>Cash</span><strong>{amount(account.cash_value, currency)}</strong></div>
                  <div><span>Fixed deposits</span><strong>{amount(account.fixed_deposit_value, currency)}</strong></div>
                </div>
              </article>
            ))}
          </div>
          <div className="table-note">
            Account totals include owned holdings after the estimated gain-tax haircut, tracked cash, and deposit accruals. Cash/deposits have no tax estimate. Unvested awards and future income are shown separately and are not included; vested awards only count here after they are recorded as owned holdings.
          </div>
        </section>
      )}

      <InvestmentHeatmap holdings={data.holdings} currency={currency} />
      <PortfolioProjectionPanel
        currency={currency}
        accounts={data.accounts}
        holdings={data.holdings}
        deposits={data.deposits}
      />

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
          <div className="eyebrow">Your goals</div>
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
            <span>Add a goal; you can change its timeline or target later.</span>
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
