import { useEffect, useState } from "react";
import { Text } from "react-native";
import { api } from "../api";
import { ActionButton, Card, ChoiceGroup, DateField, Field, Notice } from "../ui";
import type { ContributionRule, Currency, IncomeSource } from "../types";
import { newRule, ruleExplanation } from "../planning";
import { basisOptions, PercentField, recurrenceOptions } from "./PlanningEditor";

export function ContributionRulesEditor({ rules, onChange, currency }: {
  rules: ContributionRule[] | null; onChange: (rules: ContributionRule[] | null) => void; currency: Currency;
}) {
  const [sources, setSources] = useState<IncomeSource[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api.financialPlan().then(p => { if (active) setSources(p.income_sources); }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, []);
  function update(i: number, patch: Partial<ContributionRule>) {
    onChange((rules ?? []).map((r, j) => j === i ? { ...r, ...patch } : r));
  }
  return <>
    <Text>{ruleExplanation}</Text>
    <ChoiceGroup label="Contribution mode" value={rules === null ? "legacy" : "scheduled"} options={[{ label: "Fixed monthly amount", value: "legacy" }, { label: "Scheduled contribution rules", value: "scheduled" }]} onChange={v => onChange(v === "legacy" ? null : [])} />
    {error ? <Notice>{error}</Notice> : null}
    {rules !== null && <>
      {rules.map((r, i) => <Card key={i}>
        <Text>Contribution rule {i + 1}</Text>
        <ChoiceGroup label="Income source" value={r.source_kind ? `kind:${r.source_kind}` : r.source_id ?? ""} options={[
          { label: "Independent fixed contribution", value: "" },
          { label: "All salary income (including future jobs)", value: "kind:salary" },
          { label: "All bonus income", value: "kind:bonus" },
          ...(r.source_id && !sources.some(s => s.id === r.source_id) ? [{ label: `Unavailable source (${r.source_id})`, value: r.source_id }] : []),
          ...sources.map(s => ({ label: `${s.name} · ${s.start_date}`, value: s.id })),
        ]} onChange={v => update(i, {
          source_id: v.startsWith("kind:") ? null : v || null,
          source_kind: v.startsWith("kind:") ? v.slice(5) as "salary" | "bonus" : null,
          ...(v ? { recurrence: "monthly" as const } : { calculation: "fixed" as const }),
        })} />
        <ChoiceGroup label="Calculation" value={r.calculation} options={(r.source_id || r.source_kind ? ["fixed", "percentage"] : ["fixed"]).map(v => ({ label: v === "fixed" ? "Fixed amount" : "Percentage of source event", value: v }))} onChange={v => update(i, { calculation: v as ContributionRule["calculation"], value: "0" })} />
        {r.calculation === "percentage" ? <PercentField label="Share of source event (%)" rate={r.value} onChange={v => update(i, { value: v })} /> : <Field label={`Fixed amount (${currency})`} keyboardType="decimal-pad" value={r.value} onChangeText={v => update(i, { value: v })} />}
        {r.source_id || r.source_kind ? <Text>Applies on every matching source event; rule recurrence is ignored. All-salary rules follow future job changes.</Text> : <ChoiceGroup label="Recurrence" value={r.recurrence} options={recurrenceOptions} onChange={v => update(i, { recurrence: v as ContributionRule["recurrence"], ...(v === "one_time" ? { end_date: null } : {}) })} />}
        <DateField label="Start date" value={r.start_date} onChange={v => update(i, { start_date: v })} />
        {r.recurrence !== "one_time" && <DateField optional label="End date (inclusive)" value={r.end_date ?? ""} onChange={v => update(i, { end_date: v || null })} />}
        {r.calculation === "fixed" && <ChoiceGroup label="Fixed amount basis" value={r.money_basis} options={basisOptions} onChange={v => update(i, { money_basis: v as ContributionRule["money_basis"] })} />}
        <ActionButton label="Remove rule" onPress={() => onChange(rules.filter((_, j) => j !== i))} />
      </Card>)}
      {!rules.length && <Text>No scheduled contributions; the fixed monthly amount is not used.</Text>}
      <ActionButton label="Add contribution rule" onPress={() => onChange([...rules, newRule()])} />
    </>}
  </>;
}
