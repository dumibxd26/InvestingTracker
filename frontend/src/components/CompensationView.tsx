import { useState } from "react";
import {
  CalendarClock,
  CircleHelp,
  Gift,
  LockKeyhole,
  Sparkles,
  Trash2,
} from "lucide-react";
import { ApiError, api } from "../api";
import { amount, dateLabel, number } from "../format";
import type { Currency, Dashboard, Vesting } from "../types";
import { AddGrantDialog } from "./AddGrantDialog";

interface CompensationViewProps {
  data: Dashboard;
  currency: Currency;
  onSaved: () => Promise<void>;
}

function quoteTimestamp(value: string | null): string {
  if (!value) return "Quote unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Quote time unavailable";
  return `Quote ${new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date)}`;
}

function holdingPeriodLabel(days: number): string {
  const months = Math.round(days * 12 / 365);
  return months % 12 === 0
    ? `${months / 12} year${months === 12 ? "" : "s"}`
    : `${months} months`;
}

export function CompensationView({
  data,
  currency,
  onSaved,
}: CompensationViewProps) {
  const totalGross = data.vesting.reduce((sum, grant) => sum + Number(grant.gross_value), 0);
  const totalNet = data.vesting.reduce((sum, grant) => sum + Number(grant.estimated_net_value), 0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function deleteGrant(grant: Vesting) {
    if (!window.confirm(`Remove the ${grant.symbol} ${grant.grant_type.toUpperCase()} grant and its vesting schedule from Northstar? This does not change your employer plan or brokerage account.`)) {
      return;
    }
    setDeletingId(grant.id);
    setError("");
    try {
      await api.deleteVestingGrant(grant.id);
      await onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The equity grant could not be removed.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Future liquidity, clearly labelled</div>
          <h1>Equity & deposits.</h1>
          <p>Unvested awards are estimates—not shares you own or cash available to spend.</p>
        </div>
        <button
          className="button button-primary"
          type="button"
          onClick={() => setDialogOpen(true)}
          disabled={!data.market_data_provider_configured}
          title={data.market_data_provider_configured ? "Add an RSU or option grant" : "Configure TWELVE_DATA_API_KEY to search stocks"}
        >
          <Gift size={16} /> Add a grant
        </button>
      </div>
      <div className="metric-grid portfolio-metrics">
        <Metric label="Unvested grants · gross" value={amount(totalGross, currency)} detail="Latest cached quote; not realized P&L" />
        <Metric label="After assumed tax at vest" value={amount(totalNet, currency)} detail="Sale-period tax scenarios are shown per grant" />
        <Metric label="Deposits at maturity value" value={amount(data.totals.fixed_deposits, currency)} detail="Principal plus accrued estimate" />
        <Metric label="Equity grants" value={String(data.vesting.length)} detail="User-entered RSUs and options" />
      </div>

      {error && <div className="inline-error schedule-error" role="alert">{error}</div>}
      <div className="compensation-grid">
        <section className="panel table-panel vesting-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Compensation</div><h2>Vesting pipeline</h2></div>
            <span className="panel-kicker"><Sparkles size={14} /> Cached quote valuation</span>
          </div>
          <div className="vesting-list">
            {data.vesting.map((grant) => (
              <article className="vesting-card" key={grant.id}>
                <div className="vesting-card-heading">
                  <span className="vesting-company-icon"><Gift size={18} /></span>
                  <span className="vesting-company">
                    <strong>{grant.grant_label || grant.name}</strong>
                    <small>{grant.symbol} · {grant.grant_type.toUpperCase()} · {grant.name}</small>
                  </span>
                  <span className="status-pill status-planned">Unvested</span>
                  <button
                    className="icon-button small"
                    type="button"
                    aria-label={`Remove ${grant.symbol} equity grant`}
                    onClick={() => void deleteGrant(grant)}
                    disabled={deletingId === grant.id}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="vesting-value-row">
                  <div>
                    <strong>{amount(grant.gross_value, currency)}</strong>
                    <small>gross · {number(grant.units)} unvested units</small>
                  </div>
                  <div>
                    <strong>{amount(grant.estimated_net_value, currency)}</strong>
                    <small>after assumed tax at vest</small>
                  </div>
                </div>
                <div className="vesting-sale-scenarios">
                  <div>
                    <small>Sell before {holdingPeriodLabel(grant.long_term_holding_period_days)}</small>
                    <strong>{amount(grant.estimated_short_term_sale_value, currency)}</strong>
                    <small>{(Number(grant.short_term_sale_tax_rate) * 100).toFixed(1)}% illustrative haircut</small>
                  </div>
                  <div>
                    <small>Sell after {holdingPeriodLabel(grant.long_term_holding_period_days)}</small>
                    <strong>{amount(grant.estimated_long_term_sale_value, currency)}</strong>
                    <small>{(Number(grant.long_term_sale_tax_rate) * 100).toFixed(1)}% illustrative haircut</small>
                  </div>
                </div>
                <div className="vesting-price-line">
                  {grant.price !== null && grant.price_currency
                    ? `Underlying ${amount(grant.price, grant.price_currency, 2)}`
                    : "No quote is cached"}
                  {" · "}{quoteTimestamp(grant.quote_observed_at)}
                  {grant.quote_source ? ` · ${grant.quote_source}` : ""}
                </div>
                <div className="vesting-timeline">
                  <span className="timeline-track"><span style={{ width: `${Number(grant.vested_percent)}%` }} /></span>
                  <div>
                    <span>{number(grant.vested_units)} vested<br /><strong>{Number(grant.vested_percent).toFixed(1)}%</strong></span>
                    <span>Next event<br /><strong>{dateLabel(grant.next_vest_date)}</strong></span>
                    <span>{number(grant.units)} remain unvested</span>
                  </div>
                </div>
                {grant.grant_type === "option" && grant.strike_price && grant.strike_currency && (
                  <div className="vesting-price-line">
                    Strike {amount(grant.strike_price, grant.strike_currency, 2)} · estimated value is intrinsic value only.
                  </div>
                )}
                <details className="vesting-schedule-details">
                  <summary>
                    {grant.tranches.length} vesting periods
                    {grant.grant_date ? ` · granted ${dateLabel(grant.grant_date)}` : " · grant date not provided"}
                  </summary>
                  <div className="vesting-tranche-list">
                    {grant.tranches.map((tranche) => (
                      <div className="vesting-tranche-row" key={`${grant.id}-${tranche.vest_date}`}>
                        <span>{dateLabel(tranche.vest_date)}</span>
                        <span>{number(tranche.units)} units</span>
                        <span className={`status-pill ${tranche.status === "scheduled" ? "status-planned" : "status-confirmed"}`}>{tranche.status}</span>
                      </div>
                    ))}
                  </div>
                </details>
              </article>
            ))}
            {data.vesting.length === 0 && <div className="empty-state"><Gift size={22} /><strong>No grants recorded</strong><span>Add RSUs or options and set their grant and vesting terms.</span></div>}
          </div>
          <div className="table-note"><CircleHelp size={15} /> Value includes only future unvested tranches. Once shares vest, add shares you still own under Portfolio; this estimate is not realized or unrealized P&L. Sale-tax scenarios apply each award's short-/long-term percentage to the modeled grant value; they are estimates, not tax calculations on capital gains. The holding-period assumption is counted from the grant date. Refresh market data manually to update cached quotes.</div>
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
      {dialogOpen && (
        <AddGrantDialog
          marketDataConfigured={data.market_data_provider_configured}
          onClose={() => setDialogOpen(false)}
          onCreated={onSaved}
        />
      )}
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <section className="metric-card"><div className="metric-top"><span>{label}</span></div><div className="metric-value metric-value-small">{value}</div><div className="metric-foot"><span>{detail}</span></div></section>;
}
