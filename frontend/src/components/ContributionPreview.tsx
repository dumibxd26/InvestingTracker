import { useEffect, useState } from "react";
import { api } from "../api";
import { amount } from "../format";
import type { ContributionSchedule } from "../types";

export function ContributionPreview({ goalId, revision }: { goalId: string; revision: unknown }) {
  const [schedule, setSchedule] = useState<ContributionSchedule | null>(null);
  const [error, setError] = useState("");
  const [months, setMonths] = useState(120);
  useEffect(() => {
    let active = true;
    setSchedule(null); setError("");
    api.goalContributions(goalId, months).then(s => { if (active) setSchedule(s); })
      .catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [goalId, revision, months]);
  const max = Math.max(1, ...(schedule?.months.map(m => Number(m.nominal_contribution)) ?? []));
  return <section className="goal-insight-block"><h3>Contribution schedule preview</h3>
    <label>Projection months (1–1200) <input type="number" min="1" max="1200" value={months} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= 1200) setMonths(n); }} /></label>
    {error && <p role="alert">{error}</p>}
    {!schedule && !error && <p>Loading contribution schedule…</p>}
    {schedule && <>
      <p>Today's-money reference: {schedule.anchor_date}. Each row covers (today, +1 month], then the following monthly window. Forecast only; no wallet transactions.</p>
      {schedule.warnings.map((w, i) => <p className="inline-error" role="alert" key={i}>{w}</p>)}
      <svg className="contribution-chart" role="img" aria-label="Nominal monthly contribution forecast; exact values in table below" viewBox="0 0 600 120" preserveAspectRatio="none">
        <polyline fill="none" stroke="currentColor" strokeWidth="2" points={schedule.months.map((m, i) => `${i * 600 / Math.max(1, schedule.months.length - 1)},${115 - Number(m.nominal_contribution) / max * 110}`).join(" ")} />
      </svg>
      <div className="contribution-table"><table className="goal-insight-table"><thead><tr><th>Month</th><th>Nominal contribution</th><th>Today's-money contribution</th><th>Income</th><th>Expenses</th></tr></thead>
        <tbody>{schedule.months.map(m => <tr key={m.date}><td>{m.date}</td><td>{amount(m.nominal_contribution, schedule.currency)}</td><td>{amount(m.real_contribution, schedule.currency)}</td><td>{amount(m.nominal_income, schedule.currency)}</td><td>{amount(m.nominal_expenses, schedule.currency)}</td></tr>)}</tbody>
      </table></div>
    </>}
  </section>;
}
