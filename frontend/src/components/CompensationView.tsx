import { useState } from "react";
import {
  CalendarClock,
  CircleHelp,
  Gift,
  LockKeyhole,
  ShoppingCart,
  Sparkles,
  Trash2,
} from "lucide-react";
import { ApiError, api } from "../api";
import { amount, dateLabel, number } from "../format";
import type { Currency, Dashboard, StockPurchasePlan, Vesting } from "../types";
import { AddGrantDialog } from "./AddGrantDialog";
import { AddPurchasePlanDialog } from "./AddPurchasePlanDialog";

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
  const [purchaseDialogOpen, setPurchaseDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const scheduledPlans = data.purchase_plans.filter((plan) => plan.status === "scheduled");
  const scheduledNetBenefit = scheduledPlans.reduce((sum, plan) => sum + Number(plan.net_benefit), 0);

  async function deletePlan(plan: StockPurchasePlan) {
    const message = plan.status === "scheduled"
      ? `Remove the planned ${plan.symbol} purchase “${plan.name}”? Nothing has been bought or deducted yet.`
      : `Remove the record of the executed ${plan.symbol} purchase “${plan.name}”? The shares and the cash already deducted stay as they are; only this plan history is deleted.`;
    if (!window.confirm(message)) return;
    setDeletingId(plan.id);
    setError("");
    try {
      await api.deleteStockPurchasePlan(plan.id);
      await onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The share purchase could not be removed.");
    } finally {
      setDeletingId(null);
    }
  }

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
        <div className="portfolio-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={() => setPurchaseDialogOpen(true)}
            disabled={!data.market_data_provider_configured}
            title={data.market_data_provider_configured ? "Plan a discounted share purchase" : "Configure TWELVE_DATA_API_KEY to search stocks"}
          >
            <ShoppingCart size={16} /> Plan share purchase
          </button>
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
      </div>
      <div className="metric-grid portfolio-metrics">
        <Metric label="Unvested grants · gross" value={amount(totalGross, currency)} detail="Latest cached quote; not realized P&L" />
        <Metric label="After assumed tax at vest" value={amount(totalNet, currency)} detail="Sale-period tax scenarios are shown per grant" />
        <Metric label="Deposits at maturity value" value={amount(data.totals.fixed_deposits, currency)} detail="Principal plus accrued estimate" />
        <Metric label="Planned purchases · net benefit" value={amount(scheduledNetBenefit, currency)} detail={`${scheduledPlans.length} scheduled · after tax when received`} />
      </div>

      {error && <div className="inline-error schedule-error" role="alert">{error}</div>}
      {data.purchase_plans.length > 0 && (
        <section className="panel purchase-plan-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Discounted share purchases</div><h2>Purchase plans</h2></div>
            <span className="panel-kicker"><ShoppingCart size={14} /> Not in wealth until bought</span>
          </div>
          <div className="purchase-plan-list">
            {data.purchase_plans.map((plan) => (
              <article className="purchase-plan-card" key={plan.id}>
                <div className="purchase-plan-heading">
                  <span className="purchase-plan-title">
                    <strong>{plan.name}</strong>
                    <small>{number(plan.shares)} × {plan.symbol} · {plan.account_name} · {dateLabel(plan.purchase_date)}</small>
                  </span>
                  <span className={`status-pill ${plan.status === "executed" ? "status-confirmed" : "status-planned"}`}>
                    {plan.status === "executed" ? "Bought" : "Scheduled"}
                  </span>
                  <button
                    className="icon-button small"
                    type="button"
                    aria-label={`Remove ${plan.name}`}
                    onClick={() => void deletePlan(plan)}
                    disabled={deletingId === plan.id}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="purchase-plan-values">
                  <div><small>Market value</small><strong>{amount(plan.market_value, plan.reporting_currency)}</strong></div>
                  <div><small>You pay · {(Number(plan.discount_rate) * 100).toFixed(1)}% off</small><strong>{amount(plan.purchase_cost, plan.reporting_currency)}</strong></div>
                  <div><small>Discount received</small><strong>{amount(plan.gross_discount_benefit, plan.reporting_currency)}</strong></div>
                  <div><small>Tax when received · {(Number(plan.receipt_tax_rate) * 100).toFixed(1)}%</small><strong>{amount(plan.receipt_tax, plan.reporting_currency)}</strong></div>
                  <div><small>Net benefit</small><strong>{amount(plan.net_benefit, plan.reporting_currency)}</strong></div>
                </div>
                <div className="vesting-price-line">
                  Market price {amount(plan.market_price, plan.price_currency, 2)}{plan.price_is_estimate ? " (latest cached quote, updates until the date)" : ""} · price paid {amount(plan.purchase_price, plan.price_currency, 2)} · {(Number(plan.sale_profit_tax_rate) * 100).toFixed(1)}% tax on later profit · paid from {plan.funding_currency} wallet
                </div>
              </article>
            ))}
          </div>
          <div className="table-note"><CircleHelp size={15} /> Once the purchase date arrives, the price paid plus the tax when received is deducted from the paying wallet and the shares appear in Portfolio with the market price that day as their cost basis. Later gains use the profit tax. These are your own assumptions, not tax advice.</div>
        </section>
      )}
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
            <article className="deposit-card" key={deposit.id}>
              <div className="deposit-card-title"><strong>{deposit.name}</strong><span className="status-pill status-planned">Fixed</span></div>
              <div className="deposit-principal">{amount(deposit.principal, deposit.currency)}</div>
              <div className="deposit-details">
                <div><span>{deposit.rate_basis === "effective_apy" ? "Effective APY" : "Nominal APR"}</span><strong>{(Number(deposit.annual_rate) * 100).toFixed(2)}%</strong></div>
                <div><span>Interest accrued</span><strong>{amount(deposit.accrued_interest, deposit.currency, 2)}</strong></div>
                <div><span>Term</span><strong>{deposit.period_months} months</strong></div>
                <div><span>Capitalization</span><strong>{deposit.compounding === "at_maturity" ? "No · simple interest" : "Yes · monthly"}</strong></div>
                <div><span>Maturity</span><strong>{dateLabel(deposit.maturity_date)}</strong></div>
              </div>
              <div className="maturity-progress">
                <span className="maturity-caption"><CalendarClock size={14} /> {deposit.days_to_maturity} days remaining</span>
                <span className="progress-track"><span style={{ width: `${Math.max(4, Math.min(100, 100 - (deposit.days_to_maturity / 365) * 100))}%` }} /></span>
              </div>
            </article>
          ))}
          <div className="privacy-note"><CircleHelp size={15} /><span>Deposit accrual follows its stored term/rate/capitalization; actual bank crediting, tax and early-withdrawal terms can differ.</span></div>
        </section>
      </div>
      {purchaseDialogOpen && (
        <AddPurchasePlanDialog
          accounts={data.accounts}
          marketDataConfigured={data.market_data_provider_configured}
          onClose={() => setPurchaseDialogOpen(false)}
          onCreated={onSaved}
        />
      )}
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
