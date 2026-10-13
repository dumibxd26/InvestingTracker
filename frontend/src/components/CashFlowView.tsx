import { useState } from "react";
import { ApiError, api } from "../api";
import {
  Archive,
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUpRight,
  CalendarClock,
  CalendarDays,
  CircleDollarSign,
  Info,
  LockKeyhole,
} from "lucide-react";
import { amount, dateLabel } from "../format";
import type { CashFlowSchedule, Currency, Dashboard, Recurrence } from "../types";
import { CashFlowDialog } from "./CashFlowDialog";
import { ExtraCashDialog } from "./ExtraCashDialog";

interface CashFlowViewProps {
  data: Dashboard;
  currency: Currency;
  onChanged: () => Promise<void>;
}

const recurrenceLabel: Record<Recurrence, string> = {
  one_time: "Once",
  monthly: "Monthly",
  quarterly: "Every 3 months",
  annual: "Yearly",
};

export function CashFlowView({ data, currency, onChanged }: CashFlowViewProps) {
  const forecast = data.cash_flows.filter((flow) => flow.status === "forecast");
  const nextSalary = forecast.find((flow) => flow.kind === "salary");
  const forecastInflows = forecast
    .filter((flow) => flow.direction === "inflow")
    .reduce((sum, flow) => sum + Number(flow.reporting_amount ?? "0"), 0);
  const forecastOutflows = forecast
    .filter((flow) => flow.direction === "outflow")
    .reduce((sum, flow) => sum + Number(flow.reporting_amount ?? "0"), 0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [extraCashDialogOpen, setExtraCashDialogOpen] = useState(false);
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function archiveSchedule(schedule: CashFlowSchedule) {
    const action = schedule.auto_post ? "automatic credits and forecasts" : "future forecasts";
    if (!window.confirm(`Stop future ${action} for “${schedule.label}”? Already posted entries will remain.`)) return;
    setArchivingId(schedule.id);
    setError("");
    try {
      await api.archiveCashFlowSchedule(schedule.id);
      await onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The schedule could not be stopped.");
    } finally {
      setArchivingId(null);
    }
  }

  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Plan for money in motion</div>
          <h1>Cash flow.</h1>
          <p>Forecast money ahead, or schedule a salary/bonus credit to a chosen currency wallet.</p>
        </div>
        <div className="cashflow-intro-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={() => setDialogOpen(true)}
          >
            <CalendarDays size={16} /> Add a schedule
          </button>
          <button
            className="button button-primary"
            type="button"
            onClick={() => setExtraCashDialogOpen(true)}
            disabled={!data.accounts.some((account) => account.account_type !== "EMPLOYER_PLAN")}
            title={
              data.accounts.some((account) => account.account_type !== "EMPLOYER_PLAN")
                ? "Record extra cash you have received"
                : "Add a bank, savings, or brokerage account first"
            }
          >
            <CircleDollarSign size={16} /> Record extra cash
          </button>
        </div>
      </div>
      <div className="metric-grid portfolio-metrics">
        <Metric label="Available cash" value={amount(data.totals.available_cash, currency)} detail="Forecasts are excluded" />
        <Metric label="Emergency reserve" value={amount(data.totals.emergency_reserve_target, currency)} detail="Your selected floor" />
        <Metric label="Upcoming inflows" value={amount(forecastInflows, currency)} detail="Visible forecast events" />
        <Metric label="Upcoming bills" value={amount(forecastOutflows, currency)} detail="Visible forecast events" />
      </div>
      {error && <div className="inline-error schedule-error" role="alert">{error}</div>}
      <div className="cashflow-grid">
        <section className="panel table-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Planned & recorded</div><h2>Cash-flow ledger</h2></div>
            <span className="panel-kicker">Forecast ≠ available cash</span>
          </div>
          <div className="cashflow-items">
            {data.cash_flows.map((flow) => {
              const isForecast = flow.status === "forecast";
              const isOutflow = flow.direction === "outflow";
              const isTransfer = flow.direction === "transfer";
              const FlowIcon = isOutflow
                ? ArrowUpRight
                : isTransfer
                  ? ArrowLeftRight
                  : ArrowDownLeft;
              const sign = isOutflow ? "−" : isTransfer ? "↔" : "+";
              return (
                <div className="cashflow-item" key={flow.id}>
                  <span className={`flow-icon ${isOutflow ? "flow-expense" : isForecast ? "flow-forecast" : "flow-confirmed"}`}>
                    <FlowIcon size={17} />
                  </span>
                  <span className="cashflow-copy">
                    <strong>{flow.kind === "windfall" ? flow.label.replace("Extra cash · ", "") : flow.label}</strong>
                    <small>
                            {isForecast
                              ? `Expected ${dateLabel(flow.expected_date)}`
                              : flow.automatically_posted
                                ? `Auto-posted to tracker ${dateLabel(flow.occurred_at)}`
                                : `Received ${dateLabel(flow.occurred_at)}`}
                            {flow.recurrence ? ` · ${recurrenceLabel[flow.recurrence]}` : ""}
                          </small>
                  </span>
                  <span className={`cashflow-amount ${isOutflow ? "negative-text" : isForecast ? "forecast-text" : "positive-text"}`}>
                    {sign}{amount(flow.amount, flow.currency)}
                  </span>
                  <span className={`status-pill ${isForecast ? "status-planned" : "status-confirmed"}`}>{isForecast ? "Forecast" : flow.automatically_posted ? "Auto-posted" : "Confirmed"}</span>
                </div>
              );
            })}
            {data.cash_flows.length === 0 && <p className="quiet-copy empty-cashflows">No upcoming or recorded cash flows yet.</p>}
          </div>
          <div className="table-note"><Info size={15} /> Forecasts never enter available cash. Automatic salary/bonus entries update only InvestingTracker's tracked balance—not your bank—and are posted once when the app refreshes on or after the scheduled date.</div>
        </section>
        <aside className="cashflow-aside">
          <section className="panel next-income-card">
            <span className="next-step-icon"><CircleDollarSign size={19} /></span>
            <div className="eyebrow">Next expected inflow</div>
            {nextSalary ? (
              <>
                <h2>{amount(nextSalary.amount, nextSalary.currency)}</h2>
                <p>{nextSalary.label}</p>
                <div className="next-income-date"><CalendarDays size={14} /> {dateLabel(nextSalary.expected_date)}</div>
              </>
            ) : <p>No salary inflow is scheduled.</p>}
          </section>
          {data.deposits.map((deposit) => (
            <section className="panel deposit-mini-card" key={deposit.name}>
              <div className="deposit-mini-top"><span className="deposit-icon"><LockKeyhole size={17} /></span><span className="status-pill status-planned">Locked</span></div>
              <div className="eyebrow">Term deposit</div>
              <h3>{amount(deposit.principal, deposit.currency)}</h3>
              <div className="deposit-mini-meta">
                <span>{(Number(deposit.annual_rate) * 100).toFixed(2)}% {deposit.rate_basis === "effective_apy" ? "APY" : "APR"}</span>
                <span>Matures {dateLabel(deposit.maturity_date, { month: "short", day: "numeric" })}</span>
              </div>
              <div className="deposit-interest">Accrued interest <strong>{amount(deposit.accrued_interest, deposit.currency, 2)}</strong></div>
            </section>
          ))}
          <div className="privacy-note"><Info size={15} /><span>InvestingTracker does not connect to payroll or your bank. Automatic credits are tracker-only estimates; stop or adjust them if your actual pay differs.</span></div>
        </aside>
      </div>
      <section className="panel schedule-panel">
        <div className="panel-heading">
          <div><div className="eyebrow">Recurring rules</div><h2>{data.cash_flow_schedules.length} active schedules</h2></div>
          <span className="panel-kicker">Auto-credit applies only to salary and bonus rules</span>
        </div>
        {data.cash_flow_schedules.length > 0 ? (
          <div className="schedule-list">
            {data.cash_flow_schedules.map((schedule) => (
              <div className="schedule-row" key={schedule.id}>
                <span className={`flow-icon ${schedule.kind === "bill" ? "flow-expense" : "flow-forecast"}`}>
                  {schedule.kind === "bill" ? <ArrowUpRight size={17} /> : <CalendarClock size={17} />}
                </span>
                <span className="schedule-copy">
                  <strong>{schedule.label}</strong>
                  <small>
                    {schedule.kind} · {recurrenceLabel[schedule.recurrence]} · starts {dateLabel(schedule.start_date)}
                    {schedule.end_date ? ` · through ${dateLabel(schedule.end_date)}` : ""}
                    {schedule.auto_post
                      ? ` · credits ${data.accounts.find((account) => account.id === schedule.account_id)?.display_name ?? "selected account"}`
                      : " · forecast only"}
                  </small>
                </span>
                <strong className="schedule-amount">{amount(schedule.amount, schedule.currency)}</strong>
                <button
                  className="schedule-stop-button"
                  type="button"
                  onClick={() => void archiveSchedule(schedule)}
                  disabled={archivingId === schedule.id}
                  aria-label={`Stop schedule ${schedule.label}`}
                >
                  <Archive size={14} /> {archivingId === schedule.id ? "Stopping…" : "Stop"}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="schedule-empty">No active rules yet. Add salary or bonus to auto-credit a wallet, or create forecast-only rules for bills and other expected flows.</p>
        )}
      </section>
      {dialogOpen && (
        <CashFlowDialog
          accounts={data.accounts}
          currency={currency}
          onClose={() => setDialogOpen(false)}
          onCreated={onChanged}
        />
      )}
      {extraCashDialogOpen && (
        <ExtraCashDialog
          accounts={data.accounts}
          baseCurrency={currency}
          onClose={() => setExtraCashDialogOpen(false)}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <section className="metric-card"><div className="metric-top"><span>{label}</span></div><div className="metric-value metric-value-small">{value}</div><div className="metric-foot"><span>{detail}</span></div></section>;
}
