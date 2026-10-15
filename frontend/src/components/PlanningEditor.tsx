import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { newIncome, planningExplanation } from "../planning";
import type { Currency, FinancialPlanPayload, IncomeSource } from "../types";

export function PlanField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="form-field"><span>{label}</span>{children}</label>;
}
export function PlanSelect({ label, value, options, onChange }: {
  label: string; value: string; options: readonly string[]; onChange: (value: string) => void;
}) {
  return <PlanField label={label}><select value={value} onChange={e => onChange(e.target.value)}>
    {options.map(value => <option key={value} value={value}>{({
      real: "Today's money (reference date)",
      nominal: "Nominal future amount",
      legacy: "Fixed monthly amount",
      scheduled: "Scheduled contribution rules",
      salary: "Salary",
      bonus: "Bonus",
      one_time: "One-time payment",
      monthly: "Monthly",
      quarterly: "Quarterly",
      annual: "Annually",
      fixed: "Fixed amount",
      percentage: "Percentage of source event",
    } as Record<string, string>)[value] ?? value}</option>)}
  </select></PlanField>;
}
export const recurrences = ["one_time", "monthly", "quarterly", "annual"] as const;
export function PercentField({ label, rate, onChange, min = -50, max = 100 }: {
  label: string; rate: string | null; onChange: (ratio: string) => void; min?: number; max?: number;
}) {
  const [entry, setEntry] = useState<{ rate: string | null; text: string } | null>(null);
  const text = entry?.rate === rate ? entry.text : String(Math.round(Number(rate ?? 0) * 1e10) / 1e8);
  return <PlanField label={label}><input type="number" required min={min} max={max} step="any" value={text} onChange={e => {
    const next = e.target.value === "" ? "" : String(Number(e.target.value) / 100);
    setEntry({ rate: next, text: e.target.value }); onChange(next);
  }} /></PlanField>;
}
export function PlanningEditor({ currency, onSaved }: { currency: Currency; onSaved: () => Promise<void> }) {
  const [plan, setPlan] = useState<FinancialPlanPayload | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api.financialPlan().then(value => { if (active) setPlan(value); })
      .catch(error => { if (active) setError(String(error)); });
    return () => { active = false; };
  }, []);
  function update(patch: Partial<FinancialPlanPayload>) { setPlan(p => p && ({ ...p, ...patch })); }
  function source(index: number, patch: Partial<IncomeSource>) {
    if (plan) update({ income_sources: plan.income_sources.map((s, i) => i === index ? { ...s, ...patch } : s) });
  }
  async function save() {
    if (!plan) return;
    setBusy(true); setError(""); setMessage("");
    try { setPlan(await api.saveFinancialPlan(plan)); await onSaved(); setMessage("Financial timeline saved."); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return <details className="panel planning-editor"><summary>Financial timeline · income, expenses & inflation</summary>
    <p className="quiet-copy">{planningExplanation}</p>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {!plan ? <p>Loading timeline…</p> : <form onSubmit={e => { e.preventDefault(); void save(); }}>
      <div className="planning-fields">
        <PlanField label="Today's-money reference date (locked when saved)"><input type="date" readOnly value={plan.anchor_date} /></PlanField>
        <PercentField label="Annual inflation (%)" rate={plan.annual_inflation_rate} onChange={v => update({ annual_inflation_rate: v })} />
        <PlanField label="Monthly expenses (today's money; optional)"><input type="number" min="0" step="any" value={plan.monthly_expenses ?? ""} onChange={e => update({ monthly_expenses: e.target.value || null })} /></PlanField>
        <PlanSelect label="Expenses currency" value={plan.expenses_currency} options={["EUR", "USD", "RON"]} onChange={v => update({ expenses_currency: v as Currency })} />
      </div>
      <h4>Effective-dated inflation changes</h4>
      {plan.inflation_changes.map((change, i) => <div className="planning-fields" key={i}>
        <PlanField label="Effective date"><input required type="date" min={plan.anchor_date} value={change.effective_date} onChange={e => update({ inflation_changes: plan.inflation_changes.map((c, j) => j === i ? { ...c, effective_date: e.target.value } : c) })} /></PlanField>
        <PercentField label="Annual inflation (%)" rate={change.annual_rate} onChange={v => update({ inflation_changes: plan.inflation_changes.map((c, j) => j === i ? { ...c, annual_rate: v } : c) })} />
        <button type="button" onClick={() => update({ inflation_changes: plan.inflation_changes.filter((_, j) => j !== i) })}>Remove inflation change</button>
      </div>)}
      <button type="button" onClick={() => update({ inflation_changes: [...plan.inflation_changes, { effective_date: plan.anchor_date, annual_rate: plan.annual_inflation_rate }] })}>Add inflation change</button>
      <h4>Salary / job segments and bonuses</h4>
      {plan.income_sources.map((s, i) => <fieldset key={s.id} className="planning-source"><legend>{s.name}</legend>
        <div className="planning-fields">
          <PlanField label="Name"><input required minLength={2} maxLength={100} value={s.name} onChange={e => source(i, { name: e.target.value })} /></PlanField>
          <PlanSelect label="Kind" value={s.kind} options={["salary", "bonus"]} onChange={v => source(i, { kind: v as IncomeSource["kind"], salary_source_id: null, salary_percentage: null })} />
          <PlanSelect label="Currency" value={s.currency} options={["EUR", "USD", "RON"]} onChange={v => source(i, { currency: v as Currency })} />
          <PlanSelect label="Recurrence" value={s.recurrence} options={recurrences} onChange={v => source(i, { recurrence: v as IncomeSource["recurrence"], ...(v === "one_time" ? { end_date: null } : {}) })} />
          <PlanField label="Start / payment date"><input required type="date" value={s.start_date} onChange={e => source(i, { start_date: e.target.value })} /></PlanField>
          {s.recurrence !== "one_time" && <PlanField label="End date (inclusive; optional)"><input type="date" min={s.start_date} value={s.end_date ?? ""} onChange={e => source(i, { end_date: e.target.value || null })} /></PlanField>}
          {s.kind === "bonus" && <PlanField label="Bonus basis"><select value={s.salary_source_id ?? ""} onChange={e => source(i, { salary_source_id: e.target.value || null, salary_percentage: e.target.value ? "0.1" : null, annual_growth_rate: "0" })}>
            <option value="">Fixed amount</option>{plan.income_sources.filter(p => p.kind === "salary").map(p => <option key={p.id} value={p.id}>{p.name} · {p.start_date}</option>)}
          </select></PlanField>}
          {s.salary_source_id ? <PercentField label="Annualized salary share (%)" min={0.01} rate={s.salary_percentage} onChange={v => source(i, { salary_percentage: v })} /> : <>
            <PlanField label="Amount per event"><input type="number" required min="0" step="any" value={s.amount} onChange={e => source(i, { amount: e.target.value })} /></PlanField>
            <PlanSelect label="Amount basis" value={s.money_basis} options={["real", "nominal"]} onChange={v => source(i, { money_basis: v as IncomeSource["money_basis"] })} />
            <PercentField label="Total annual nominal raise (%)" rate={s.annual_growth_rate} onChange={v => source(i, { annual_growth_rate: v })} />
          </>}
        </div>
        <button type="button" onClick={() => update({ income_sources: plan.income_sources.filter((_, j) => j !== i) })}>Remove source</button>
      </fieldset>)}
      <button type="button" onClick={() => update({ income_sources: [...plan.income_sources, newIncome(currency, plan.anchor_date)] })}>Add salary or bonus</button>
      <button className="button button-primary" disabled={busy} type="submit">{busy ? "Saving…" : "Save financial timeline"}</button>
      {message && <p role="status">{message}</p>}
    </form>}
  </details>;
}
