import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "../api";
import { formatMoney } from "../format";
import { ActionButton, Field, Notice, ProgressBar } from "../ui";
import type { ContributionSchedule } from "../types";

export function ContributionPreview({ goalId, revision }: { goalId: string; revision: unknown }) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<{ key: string; schedule?: ContributionSchedule; error?: string } | null>(null);
  const [months, setMonths] = useState("120");
  const [visible, setVisible] = useState(12);
  const key = `${goalId}:${months}:${String(revision)}`;
  const valid = Number.isInteger(Number(months)) && Number(months) >= 1 && Number(months) <= 1200;
  const schedule = result?.key === key ? result.schedule : undefined;
  const error = !valid ? "Choose 1–1200 months." : result?.key === key ? result.error : undefined;
  useEffect(() => {
    let active = true;
    if (!open) return () => { active = false; };
    const count = Number(months);
    if (!valid) return () => { active = false; };
    api.goalContributions(goalId, count).then(s => { if (active) setResult({ key, schedule: s }); }).catch(e => { if (active) setResult({ key, error: String(e) }); });
    return () => { active = false; };
  }, [goalId, months, open, key, valid]);
  const max = Math.max(1, ...(schedule?.months.map(m => Number(m.nominal_contribution)) ?? []));
  return <>
    <ActionButton label={open ? "Hide contribution insights" : "Contribution insights & schedule"} onPress={() => setOpen(v => !v)} />
    {open && <>
      <Field label="Projection months (1–1200)" value={months} keyboardType="number-pad" onChangeText={v => { setMonths(v); setVisible(12); }} />
      {error ? <Notice>{error}</Notice> : null}
      {!schedule && !error && <Text>Loading schedule…</Text>}
      {schedule && <>
        <Text>Today&apos;s-money reference: {schedule.anchor_date}. Windows are (today, +1 month], then following months. Forecast only, no wallet transactions. Bars show nominal contributions.</Text>
        {schedule.warnings.map((w, i) => <Notice key={i}>{w}</Notice>)}
        {schedule.months.slice(0, visible).map(m => <View key={m.date} style={{ gap: 5, marginVertical: 8 }}>
          <Text>{m.date} · Nominal: {formatMoney(m.nominal_contribution, schedule.currency)}</Text>
          <ProgressBar value={Number(m.nominal_contribution) / max * 100} />
          <Text>Today&apos;s money: {formatMoney(m.real_contribution, schedule.currency)}</Text>
          <Text>Income: {formatMoney(m.nominal_income, schedule.currency)} · Expenses: {formatMoney(m.nominal_expenses, schedule.currency)}</Text>
        </View>)}
        {visible < schedule.months.length && <ActionButton label="Show next 12 months" onPress={() => setVisible(n => n + 12)} />}
      </>}
    </>}
  </>;
}
