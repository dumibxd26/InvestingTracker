import { useEffect, useState } from "react";
import { api } from "../api";
import { newRule, ruleExplanation } from "../planning";
import type { ContributionRule, Currency, IncomeSource } from "../types";
import { PercentField, PlanField, PlanSelect, recurrences } from "./PlanningEditor";

export function ContributionRulesEditor({ rules, onChange, currency, monthlyAmount, onMonthlyAmountChange, incomeRevision = 0 }: {
  rules: ContributionRule[] | null; onChange: (rules: ContributionRule[] | null) => void; currency: Currency; incomeRevision?: number;
  monthlyAmount: string; onMonthlyAmountChange: (amount: string) => void;
}) {
  const [sources, setSources] = useState<IncomeSource[]>([]);
  const [error, setError] = useState("");
  const [scheduledDraft, setScheduledDraft] = useState<ContributionRule[]>(rules ?? [newRule()]);
  useEffect(() => {
    let active = true;
    api.financialPlan().then(p => { if (active) { setSources(p.income_sources); setError(""); } })
      .catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [incomeRevision]);
  function update(i: number, patch: Partial<ContributionRule>) {
    onChange((rules ?? []).map((r, j) => j === i ? { ...r, ...patch } : r));
  }
  function hasSourceKind(kind: "salary" | "bonus") {
    return sources.some(source => source.kind === kind);
  }
  return <section className="planning-source">
    <h3>Contribution timeline</h3><p className="quiet-copy">{ruleExplanation}</p>
    <PlanField label="How will you contribute to this goal?">
      <select value={rules === null ? "fixed" : "scheduled"} onChange={event => {
        if (event.target.value === "fixed") {
          setScheduledDraft(rules ?? []);
          onChange(null);
        } else {
          onChange(scheduledDraft);
        }
      }}>
        <option value="fixed">Fixed amount each month</option>
        <option value="scheduled">Salary/bonus percentages or scheduled amounts</option>
      </select>
    </PlanField>
    {rules === null ? <>
      <PlanField label={`Monthly contribution (${currency})`}>
        <input required type="number" min="0" step="0.01" value={monthlyAmount} onChange={event => onMonthlyAmountChange(event.target.value)} />
      </PlanField>
      <p className="quiet-copy">This fixed nominal amount feeds the contribution preview and projected value chart. Salary and bonus changes do not change a fixed contribution. Choose percentages above to follow income growth.</p>
      {Number(monthlyAmount) === 0 && <p role="status">No new money is assigned to this goal. Its projection uses existing savings and investments only. Enter a monthly amount or choose salary/bonus percentages.</p>}
    </> : <p className="quiet-copy">Only the rules below feed this goal's projection; a fixed monthly amount from the other mode is not added. Income in the financial timeline is not automatically invested.</p>}
    {error && <p role="alert">{error}</p>}
    {rules !== null && <>
      {rules.map((r, i) => <fieldset className="planning-source" key={i}><legend>Rule {i + 1}</legend>
        <div className="planning-fields">
          <PlanField label="Income source"><select value={r.source_kind ? `kind:${r.source_kind}` : r.source_id ?? ""} onChange={e => {
            const value = e.target.value;
            update(i, {
              source_id: value.startsWith("kind:") ? null : value || null,
              source_kind: value.startsWith("kind:") ? value.slice(5) as "salary" | "bonus" : null,
              ...(value ? { recurrence: "monthly" as const } : { calculation: "fixed" as const }),
            });
          }}>
            <option value="">Independent fixed contribution</option>
            {r.source_kind && !hasSourceKind(r.source_kind) && <option value={`kind:${r.source_kind}`}>Unavailable income type ({r.source_kind})</option>}
            {hasSourceKind("salary") && <option value="kind:salary">All salary income (including future jobs)</option>}
            {hasSourceKind("bonus") && <option value="kind:bonus">All bonus income</option>}
            {r.source_id && !sources.some(s => s.id === r.source_id) && <option value={r.source_id}>Unavailable source ({r.source_id})</option>}
            {sources.map(s => <option key={s.id} value={s.id}>{s.name} · {s.start_date}</option>)}
          </select></PlanField>
          {r.source_kind && !hasSourceKind(r.source_kind) && <p className="quiet-copy">No {r.source_kind} income is saved in the financial timeline. Add and save one there, or choose Independent fixed contribution.</p>}
          {!r.source_id && !r.source_kind && !sources.length && <p className="quiet-copy">No salary or bonus income is saved in the financial timeline yet. Save one before choosing an income-linked contribution.</p>}
          <PlanSelect label="Calculation" value={r.calculation} options={r.source_id || r.source_kind ? ["fixed", "percentage"] : ["fixed"]} onChange={v => update(i, { calculation: v as ContributionRule["calculation"], value: "0" })} />
          {r.calculation === "percentage" ? <PercentField label="Share of income event (%)" min={0} rate={r.value} onChange={v => update(i, { value: v })} /> : <PlanField label={`Fixed amount (${currency})`}><input required type="number" min="0" step="any" value={r.value} onChange={e => update(i, { value: e.target.value })} /></PlanField>}
          {!r.source_id && !r.source_kind && <PlanSelect label="Recurrence" value={r.recurrence} options={recurrences} onChange={v => update(i, { recurrence: v as ContributionRule["recurrence"], ...(v === "one_time" ? { end_date: null } : {}) })} />}
          {(r.source_id || r.source_kind) && <p>Applies on every matching income source event; recurrence is ignored. All-salary rules follow future job changes.</p>}
          <PlanField label="Start date"><input required type="date" value={r.start_date} onChange={e => update(i, { start_date: e.target.value })} /></PlanField>
          {r.recurrence !== "one_time" && <PlanField label="End date (inclusive; optional)"><input type="date" min={r.start_date} value={r.end_date ?? ""} onChange={e => update(i, { end_date: e.target.value || null })} /></PlanField>}
          {r.calculation === "fixed" && <PlanSelect label="Fixed amount basis" value={r.money_basis} options={["real", "nominal"]} onChange={v => update(i, { money_basis: v as ContributionRule["money_basis"] })} />}
        </div><button type="button" onClick={() => onChange(rules.filter((_, j) => j !== i))}>Remove rule</button>
      </fieldset>)}
      {(rules.length === 0 || rules.every(rule => Number(rule.value) === 0)) && <p role="status">No new money is assigned by these rules. Add a positive amount or salary/bonus percentage to include future contributions in the chart.</p>}
      <button type="button" onClick={() => onChange([...rules, newRule()])}>Add contribution rule</button>
    </>}
    <p className="quiet-copy">Save the goal to update its contribution table and projected value chart.</p>
  </section>;
}
