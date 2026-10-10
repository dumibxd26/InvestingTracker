import { CalendarClock, CircleHelp, Gift, LockKeyhole, Sparkles } from "lucide-react";
import { amount, dateLabel, number } from "../format";
import type { Currency, Dashboard } from "../types";

export function CompensationView({ data, currency }: { data: Dashboard; currency: Currency }) {
  const totalGross = data.vesting.reduce((sum, grant) => sum + Number(grant.gross_value), 0);
  const totalNet = data.vesting.reduce((sum, grant) => sum + Number(grant.estimated_net_value), 0);
  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Future liquidity, clearly labelled</div>
          <h1>Equity & deposits.</h1>
          <p>See what may vest or mature—and keep estimates separate from money you can use today.</p>
        </div>
        <button className="button button-secondary" type="button" disabled title="Grant and deposit entry is not enabled in this prototype">
          <Gift size={16} /> Add a grant
        </button>
      </div>
      <div className="metric-grid portfolio-metrics">
        <Metric label="Unvested grants · gross" value={amount(totalGross, currency)} detail="Mark-to-market sample estimate" />
        <Metric label="Illustrative after-tax value" value={amount(totalNet, currency)} detail="User-adjustable tax assumption, not tax advice" />
        <Metric label="Deposits at maturity value" value={amount(data.totals.fixed_deposits, currency)} detail="Principal plus accrued estimate" />
        <Metric label="Upcoming vest events" value={String(data.vesting.filter((grant) => grant.next_vest_date).length)} detail="Future dates in the sample plan" />
      </div>

      <div className="compensation-grid">
        <section className="panel table-panel vesting-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Compensation</div><h2>Vesting pipeline</h2></div>
            <span className="panel-kicker"><Sparkles size={14} /> Sample schedule</span>
          </div>
          <div className="vesting-list">
            {data.vesting.map((grant, index) => (
              <article className="vesting-card" key={`${grant.symbol}-${index}`}>
                <div className="vesting-card-heading">
                  <span className="vesting-company-icon"><Gift size={18} /></span>
                  <span className="vesting-company"><strong>{grant.name}</strong><small>{grant.symbol} · {grant.grant_type.toUpperCase()}</small></span>
                  <span className="status-pill status-planned">Unvested</span>
                </div>
                <div className="vesting-value-row">
                  <div><strong>{amount(grant.gross_value, currency)}</strong><small>gross · {number(grant.units)} units</small></div>
                  <div><strong>{amount(grant.estimated_net_value, currency)}</strong><small>estimated after assumed tax</small></div>
                </div>
                <div className="vesting-timeline">
                  <span className="timeline-track"><span style={{ width: `${Number(grant.vested_percent)}%` }} /></span>
                  <div><span>Grant</span><span>Next event<br /><strong>{dateLabel(grant.next_vest_date)}</strong></span><span>Projected release</span></div>
                </div>
              </article>
            ))}
            {data.vesting.length === 0 && <div className="empty-state"><Gift size={22} /><strong>No grants recorded</strong><span>Add a grant to model vesting and release timing.</span></div>}
          </div>
          <div className="table-note"><CircleHelp size={15} /> Option values use intrinsic value only; vesting does not mean the shares are liquid.</div>
        </section>
        <section className="panel deposits-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Savings & fixed income</div><h2>Deposit ladder</h2></div>
            <span className="deposit-icon"><LockKeyhole size={17} /></span>
          </div>
          {data.deposits.map((deposit) => (
            <article className="deposit-card" key={deposit.name}>
              <div className="deposit-card-title"><strong>{deposit.name}</strong><span className="status-pill status-planned">Fixed</span></div>
              <div className="deposit-principal">{amount(deposit.principal, deposit.currency)}</div>
              <div className="deposit-details">
                <div><span>{deposit.rate_basis === "effective_apy" ? "Effective APY" : "Nominal APR"}</span><strong>{(Number(deposit.annual_rate) * 100).toFixed(2)}%</strong></div>
                <div><span>Interest accrued</span><strong>{amount(deposit.accrued_interest, deposit.currency, 2)}</strong></div>
                <div><span>Maturity</span><strong>{dateLabel(deposit.maturity_date)}</strong></div>
              </div>
              <div className="maturity-progress">
                <span className="maturity-caption"><CalendarClock size={14} /> {deposit.days_to_maturity} days remaining</span>
                <span className="progress-track"><span style={{ width: `${Math.max(4, Math.min(100, 100 - (deposit.days_to_maturity / 365) * 100))}%` }} /></span>
              </div>
            </article>
          ))}
          <div className="privacy-note"><CircleHelp size={15} /><span>Deposit accrual follows its stored schedule; actual bank crediting and early withdrawal terms can differ.</span></div>
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <section className="metric-card"><div className="metric-top"><span>{label}</span></div><div className="metric-value metric-value-small">{value}</div><div className="metric-foot"><span>{detail}</span></div></section>;
}
