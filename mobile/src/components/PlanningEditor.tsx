import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "../api";
import { ActionButton, Card, ChoiceGroup, DateField, Field, Notice } from "../ui";
import type { Currency, FinancialPlanPayload, IncomeSource } from "../types";
import { newIncome, planningExplanation } from "../planning";

export const recurrenceOptions = [
  { label: "One-time payment", value: "one_time" },
  { label: "Monthly", value: "monthly" },
  { label: "Quarterly", value: "quarterly" },
  { label: "Annually", value: "annual" },
];
export const basisOptions = [{ label: "Today's money (reference date)", value: "real" }, { label: "Nominal future amount", value: "nominal" }];
export const currencyOptions = ["EUR", "USD", "RON"].map(value => ({ label: value, value }));
export function PercentField({ label, rate, onChange }: {
  label: string; rate: string | null; onChange: (ratio: string) => void;
}) {
  const [entry, setEntry] = useState<{ rate: string | null; text: string } | null>(null);
  const text = entry?.rate === rate ? entry.text : String(Math.round(Number(rate ?? 0) * 1e10) / 1e8);
  return <Field label={label} value={text} keyboardType="numbers-and-punctuation" onChangeText={v => {
    const normalized = v.replace(/,/g, ".");
    const next = normalized === "" ? "" : String(Number(normalized) / 100);
    setEntry({ rate: next, text: normalized }); onChange(next);
  }} />;
}

export function PlanningEditor({ currency, onSaved }: { currency: Currency; onSaved: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<FinancialPlanPayload | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api.financialPlan().then(p => { if (active) setPlan(p); }).catch(e => { if (active) setError(String(e)); });
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
  return <Card>
    <ActionButton label={open ? "Hide financial timeline" : "Edit financial timeline"} onPress={() => setOpen(v => !v)} />
    {open && <>
      <Text>{planningExplanation}</Text>
      {error ? <Notice>{error}</Notice> : null}
      {!plan ? <Text>Loading timeline…</Text> : <>
        <Text>Today&apos;s-money reference date (locked when saved): {plan.anchor_date}</Text>
        <PercentField label="Annual inflation (%)" rate={plan.annual_inflation_rate} onChange={v => update({ annual_inflation_rate: v })} />
        <Field label="Monthly expenses (today's money; optional)" keyboardType="decimal-pad" value={plan.monthly_expenses ?? ""} onChangeText={v => update({ monthly_expenses: v || null })} />
        <ChoiceGroup label="Expenses currency" value={plan.expenses_currency} options={currencyOptions} onChange={v => update({ expenses_currency: v as Currency })} />
        <Text>Effective-dated inflation changes</Text>
        {plan.inflation_changes.map((c, i) => <View key={i}>
          <DateField label="Effective date" value={c.effective_date} onChange={v => update({ inflation_changes: plan.inflation_changes.map((x, j) => j === i ? { ...x, effective_date: v } : x) })} />
          <PercentField label="Annual inflation (%)" rate={c.annual_rate} onChange={v => update({ inflation_changes: plan.inflation_changes.map((x, j) => j === i ? { ...x, annual_rate: v } : x) })} />
          <ActionButton label="Remove inflation change" onPress={() => update({ inflation_changes: plan.inflation_changes.filter((_, j) => j !== i) })} />
        </View>)}
        <ActionButton label="Add inflation change" onPress={() => update({ inflation_changes: [...plan.inflation_changes, { effective_date: plan.anchor_date, annual_rate: plan.annual_inflation_rate }] })} />
        {plan.income_sources.map((s, i) => <Card key={s.id}>
          <Field label="Source name" value={s.name} onChangeText={v => source(i, { name: v })} />
          <ChoiceGroup label="Kind" value={s.kind} options={[{ label: "Salary / job segment", value: "salary" }, { label: "Bonus", value: "bonus" }]} onChange={v => source(i, { kind: v as IncomeSource["kind"], salary_source_id: null, salary_percentage: null })} />
          <ChoiceGroup label="Currency" value={s.currency} options={currencyOptions} onChange={v => source(i, { currency: v as Currency })} />
          <ChoiceGroup label="Recurrence" value={s.recurrence} options={recurrenceOptions} onChange={v => source(i, { recurrence: v as IncomeSource["recurrence"], ...(v === "one_time" ? { end_date: null } : {}) })} />
          <DateField label="Start / payment date" value={s.start_date} onChange={v => source(i, { start_date: v })} />
          {s.recurrence !== "one_time" && <DateField optional label="End date (inclusive)" value={s.end_date ?? ""} onChange={v => source(i, { end_date: v || null })} />}
          {s.kind === "bonus" && <ChoiceGroup label="Bonus basis" value={s.salary_source_id ?? ""} options={[{ label: "Fixed amount", value: "" }, ...plan.income_sources.filter(p => p.kind === "salary").map(p => ({ label: `${p.name} · ${p.start_date}`, value: p.id }))]} onChange={v => source(i, { salary_source_id: v || null, salary_percentage: v ? "0.1" : null, annual_growth_rate: "0" })} />}
          {s.salary_source_id ? <PercentField label="Annualized salary share (%)" rate={s.salary_percentage} onChange={v => source(i, { salary_percentage: v })} /> : <>
            <Field label="Amount per event" keyboardType="decimal-pad" value={s.amount} onChangeText={v => source(i, { amount: v })} />
            <ChoiceGroup label="Amount basis" value={s.money_basis} options={basisOptions} onChange={v => source(i, { money_basis: v as IncomeSource["money_basis"] })} />
            <PercentField label="Total annual nominal raise (%)" rate={s.annual_growth_rate} onChange={v => source(i, { annual_growth_rate: v })} />
          </>}
          <ActionButton label="Remove source" onPress={() => update({ income_sources: plan.income_sources.filter((_, j) => j !== i) })} />
        </Card>)}
        <ActionButton label="Add salary or bonus" onPress={() => update({ income_sources: [...plan.income_sources, newIncome(currency, plan.anchor_date)] })} />
        <ActionButton label="Save financial timeline" loading={busy} onPress={() => void save()} />
        {message ? <Text accessibilityRole="alert">{message}</Text> : null}
      </>}
    </>}
  </Card>;
}
