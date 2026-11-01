import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { amount } from "../format";
import type {
  Dashboard, GoalRecord, RetirementHistory, RetirementInflationSuggestion,
  RetirementInvestment, RetirementProjection, RetirementReturnSuggestion, RetirementSettings,
} from "../types";

interface Props {
  goalId: string;
  data: Dashboard;
  onSaved: () => Promise<void>;
}

function errorMessage(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : String(cause);
}

function initialSettings(goal: GoalRecord, data: Dashboard): RetirementSettings {
  const fresh: RetirementSettings = {
    target_date: goal.target_date ?? "",
    currency: goal.target_currency,
    contribution_amount: "0",
    contribution_frequency: "monthly",
    annual_inflation_rate: "",
    include_taxes: true,
    investments: [
      ...goal.holding_allocations.map(allocation => {
        const holding = data.holdings.find(row => row.id === allocation.id);
        return investment("holding", holding?.symbol ?? "Missing holding", allocation.id);
      }),
      ...goal.fixed_deposit_allocations.map(allocation => {
        const deposit = data.deposits.find(row => row.id === allocation.id);
        const item = investment("deposit", deposit?.name ?? "Missing deposit", allocation.id);
        item.lower_return = deposit?.annual_rate ?? "0";
        item.upper_return = item.lower_return;
        return item;
      }),
    ],
  };
  if (!goal.retirement_settings) return fresh;
  const saved = goal.retirement_settings;
  const retained = saved.investments.filter(item => {
    const stillLinked = item.kind === "holding"
      ? goal.holding_ids.includes(item.asset_id ?? "")
      : item.kind === "deposit" ? goal.fixed_deposit_ids.includes(item.asset_id ?? "") : true;
    return stillLinked || Number(item.contribution_percentage) > 0;
  });
  return {
    ...saved,
    target_date: goal.target_date ?? saved.target_date,
    investments: [...retained, ...fresh.investments.filter(
      item => !retained.some(row => row.kind === item.kind && row.asset_id === item.asset_id),
    )],
  };
}

function investment(kind: RetirementInvestment["kind"], name: string, id: string | null = null): RetirementInvestment {
  return {
    key: id ?? crypto.randomUUID(), kind, name, asset_id: id, history_id: null,
    contribution_percentage: "0", lower_return: "", upper_return: "",
    tax_rate: kind === "holding" || kind === "deposit" ? "0" : "", deposit_term_months: 12,
  };
}

const labels = {
  historical_lower: "Historical minimum", historical_upper: "Historical maximum",
  user_lower: "My lower returns", user_upper: "My upper returns",
};
const colors = {
  historical_lower: "#d97706", historical_upper: "#059669",
  user_lower: "#7c3aed", user_upper: "#0284c7",
};

export function RetirementPanel({ goalId, data, onSaved }: Props) {
  const [settings, setSettings] = useState<RetirementSettings | null>(null);
  const [history, setHistory] = useState<RetirementHistory[]>([]);
  const [result, setResult] = useState<RetirementProjection | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, RetirementReturnSuggestion>>({});
  const [inflation, setInflation] = useState<RetirementInflationSuggestion | null>(null);
  const [real, setReal] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [futureKind, setFutureKind] = useState<"stock" | "etf" | "bond" | "future_deposit">("etf");
  const [futureName, setFutureName] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    setError(""); setResult(null); setSettings(null); setSuggestions({}); setInflation(null);
    Promise.all([api.listGoals(), api.retirementHistory()]).then(async ([goals, datasets]) => {
      if (!active) return;
      const goal = goals.find(row => row.id === goalId);
      if (!goal) throw new Error("Retirement goal is unavailable.");
      setSettings(initialSettings(goal, data)); setHistory(datasets);
      if (goal.retirement_settings) {
        const projection = await api.retirementProjection(goalId);
        if (active) setResult(projection);
      }
    }).catch(cause => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [goalId, data]);

  function change(next: RetirementSettings) {
    setSettings(next); setResult(null); setMessage("");
  }

  function update(key: string, values: Partial<RetirementInvestment>) {
    if (!settings) return;
    change({ ...settings, investments: settings.investments.map(row => row.key === key ? { ...row, ...values } : row) });
    if ("history_id" in values) {
      setSuggestions(current => Object.fromEntries(Object.entries(current).filter(([id]) => id !== key)));
    }
  }

  async function suggestReturns(item: RetirementInvestment) {
    if (!settings?.target_date || !item.history_id) {
      setError("Choose a horizon and a local history dataset first."); return;
    }
    setBusy(true); setError("");
    const date = settings.target_date;
    const historyId = item.history_id;
    try {
      const suggestion = await api.retirementReturnSuggestion(historyId, date);
      setSuggestions(current => ({ ...current, [item.key]: suggestion }));
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function suggestInflation() {
    if (!settings?.target_date) { setError("Choose your retirement horizon first."); return; }
    setBusy(true); setError("");
    try { setInflation(await api.retirementInflation(settings.target_date)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function calculate() {
    if (!settings) return;
    setError(""); setBusy(true);
    if (settings.annual_inflation_rate === "" || settings.investments.some(
      row => row.lower_return === "" || row.upper_return === "",
    )) {
      setError("Enter inflation and both annual return assumptions for every investment.");
      setBusy(false); return;
    }
    if (settings.include_taxes && settings.investments.some(
      row => row.kind !== "holding" && row.kind !== "deposit" && (row.tax_rate === "" || row.tax_rate === null),
    )) {
      setError("Enter an estimated tax rate for every future investment, including 0% if exempt.");
      setBusy(false); return;
    }
    try {
      const projection = await api.saveRetirement(goalId, {
        ...settings, investments: settings.investments.map(row => ({
          ...row, tax_rate: row.tax_rate === "" ? null : row.tax_rate,
        })),
      });
      await onSaved();
      setResult(projection);
      setMessage("Retirement settings saved. No money moved or trades were made.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function importHistory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const file = fields.get("file");
    if (!(file instanceof File) || !settings) return;
    if (file.size > 1000000) { setError("CSV must be at most 1 MB."); return; }
    setBusy(true); setError("");
    try {
      await api.importRetirementHistory({
        name: String(fields.get("name")), currency: settings.currency,
        source: String(fields.get("source")), license: String(fields.get("license")),
        personal_storage_permitted: fields.get("rights") === "on",
        total_return_confirmed: fields.get("total") === "on", csv: await file.text(),
      });
      setHistory(await api.retirementHistory()); form.reset();
      setMessage("Monthly history stored locally for your user. It is not bundled with the code.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function deleteHistory(id: string) {
    if (!window.confirm("Delete this local dataset? Active goal references must be removed first.")) return;
    setBusy(true); setError("");
    try { await api.deleteRetirementHistory(id); setHistory(await api.retirementHistory()); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  if (!settings) return <div className="goal-insights">{error
    ? <p className="inline-error" role="alert">{error}</p>
    : <p>Loading retirement settings…</p>}</div>;
  const visible = settings.investments.filter(row => row.name.toLowerCase().includes(search.toLowerCase()));

  return <section className="goal-insights">
    <h3>Retirement: current investments + future savings</h3>
    <p className="quiet-copy">Your split applies only to future contributions. Existing assets keep their current values and goal-linked shares. No rebalancing, salary assumptions, or automatic reinvestment.</p>
    {!data.goals.find(row => row.id === goalId)?.target_date && <p className="quiet-copy">Set a horizon below. A target amount is optional.</p>}
    <div className="form-row">
      <label className="form-field"><span>Retirement date</span>
        <input type="date" value={settings.target_date} disabled={busy} onChange={e => {
          change({ ...settings, target_date: e.target.value }); setSuggestions({}); setInflation(null);
        }} /></label>
      <label className="form-field"><span>Or years from today</span>
        <input type="number" min="1" max="100" step="1" disabled={busy}
          onChange={e => {
            const years = Number(e.target.value);
            if (!Number.isInteger(years) || years < 1 || years > 100) {
              setError("Choose a whole number of years between 1 and 100, or use the date field.");
              return;
            }
            setError("");
            const date = new Date();
            const originalMonth = date.getMonth();
            date.setFullYear(date.getFullYear() + years);
            if (date.getMonth() !== originalMonth) date.setDate(0);
            const dateString = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
            change({ ...settings, target_date: dateString }); setSuggestions({}); setInflation(null);
          }} /></label>
      <label className="form-field"><span>Projection currency</span>
        <select value={settings.currency} disabled={busy} onChange={e => {
          if (e.target.value === "EUR" || e.target.value === "USD" || e.target.value === "RON") {
            change({ ...settings, currency: e.target.value }); setSuggestions({});
          }
        }}><option>EUR</option><option>USD</option><option>RON</option></select>
      </label>
    </div>
    <div className="form-row">
      <label className="form-field"><span>Future contribution ({settings.currency})</span>
        <input type="number" min="0" step="0.01" value={settings.contribution_amount} disabled={busy}
          onChange={e => change({ ...settings, contribution_amount: e.target.value })} /></label>
      <label className="form-field"><span>Contribution frequency</span>
        <select value={settings.contribution_frequency} disabled={busy} onChange={e => change({
          ...settings, contribution_frequency: e.target.value === "yearly" ? "yearly" : "monthly",
        })}><option value="monthly">Monthly anniversary, after growth</option><option value="yearly">Yearly anniversary, after growth</option></select>
      </label>
    </div>
    <label className="form-field"><span>Worldwide annual inflation for this horizon (%)</span>
      <input type="number" min="-99.99" max="100" step="any" value={settings.annual_inflation_rate === "" ? "" : Number(settings.annual_inflation_rate) * 100}
        disabled={busy} onChange={e => change({ ...settings, annual_inflation_rate: e.target.value === "" ? "" : String(Number(e.target.value) / 100) })} />
    </label>
    <button type="button" className="button button-secondary" disabled={busy} onClick={() => void suggestInflation()}>Suggest inflation from historical worldwide CPI</button>
    {inflation && <div className="quiet-copy">
      {inflation.available && inflation.suggested_rate !== null
        ? <>Suggested: {(inflation.suggested_rate * 100).toFixed(2)}% yearly; observed range {(Number(inflation.lower_rate) * 100).toFixed(2)}%–{(Number(inflation.upper_rate) * 100).toFixed(2)}% ({inflation.windows} windows).
          <button className="button button-secondary" type="button" disabled={busy} onClick={() => change({ ...settings, annual_inflation_rate: String(inflation.suggested_rate) })}>Use suggestion</button></>
        : inflation.reason}
      <p>{inflation.method}</p><p><a href={inflation.source} target="_blank" rel="noreferrer">World Bank source</a> · {inflation.license} · {inflation.sample_start}–{inflation.sample_end}</p>
    </div>}
    <h4>Investments and future contribution split</h4>
    <p className="quiet-copy">Link current assets through Edit goal. Future stocks/ETFs/bonds/deposits can start at zero. Bond assumptions are manually modeled, not a live bond ledger. Existing deposits cannot receive top-ups.</p>
    <label className="form-field"><span>Search selected investments</span><input value={search} onChange={e => setSearch(e.target.value)} /></label>
    <div style={{ maxHeight: 520, overflowY: "auto" }}>
      {visible.map(item => {
        const suggestion = suggestions[item.key];
        const tracked = item.kind === "holding" || item.kind === "deposit";
        return <section className="goal-insight-block" key={item.key}>
          <h4>{item.name} · {tracked ? "current linked asset" : "future purchases"}</h4>
          <div className="form-row">
            <label className="form-field"><span>Share of new contributions (%)</span>
              <input type="number" min="0" max="100" step="0.01" value={item.contribution_percentage} disabled={busy || item.kind === "deposit"}
                onChange={e => update(item.key, { contribution_percentage: e.target.value })} /></label>
            {!tracked && <label className="form-field"><span>Estimated tax on gains / interest (%)</span>
              <input type="number" min="0" max="100" step="any" value={item.tax_rate === "" || item.tax_rate === null ? "" : Number(item.tax_rate) * 100} disabled={busy}
                onChange={e => update(item.key, { tax_rate: e.target.value === "" ? "" : String(Number(e.target.value) / 100) })} /></label>}
          </div>
          <div className="form-row">
            {(["lower_return", "upper_return"] as const).map(key => <label className="form-field" key={key}>
              <span>{key === "lower_return" ? "My lower" : "My upper"} yearly return (%)</span>
              <input type="number" min="-99.99" max="100" step="any" disabled={busy || item.kind === "deposit"}
                value={item[key] === "" ? "" : Number(item[key]) * 100}
                onChange={e => update(item.key, { [key]: e.target.value === "" ? "" : String(Number(e.target.value) / 100) })} />
            </label>)}
          </div>
          {item.kind === "future_deposit" && <label className="form-field"><span>Term for each new deposit (months; no renewal)</span>
            <input type="number" min="1" max="1200" value={item.deposit_term_months} disabled={busy}
              onChange={e => update(item.key, { deposit_term_months: Number(e.target.value) })} /></label>}
          {item.kind !== "deposit" && <>
            <label className="form-field"><span>Local total-return dataset ({settings.currency})</span>
              <select value={item.history_id ?? ""} disabled={busy} onChange={e => update(item.key, { history_id: e.target.value || null })}>
                <option value="">No historical dataset — manual results only</option>
                {history.filter(row => row.currency === settings.currency).map(row => <option value={row.id} key={row.id}>{row.name} ({row.sample_start}–{row.sample_end})</option>)}
              </select></label>
            <button className="button button-secondary" type="button" disabled={busy || !item.history_id} onClick={() => void suggestReturns(item)}>Show historical return recommendation</button>
          </>}
          {suggestion && <div className="quiet-copy">{suggestion.available
            ? <><p>Historical annualized min/max: {(Number(suggestion.lower_return) * 100).toFixed(2)}% / {(Number(suggestion.upper_return) * 100).toFixed(2)}%; median {(Number(suggestion.median_return) * 100).toFixed(2)}% over {suggestion.windows} matching windows.</p>
              <p>{suggestion.dataset?.source} · {suggestion.dataset?.license}. Selected history must match this investment or an explicitly chosen proxy.</p>
              {Number(suggestion.upper_return) > 1 && <p>Historical annualization exceeds the manual calculator's 100% annual planning limit. Enter your own assumptions; historical replay still uses the observed data.</p>}
              <button className="button button-secondary" type="button" disabled={busy || Number(suggestion.upper_return) > 1} onClick={() => update(item.key, {
                lower_return: String(suggestion.lower_return), upper_return: String(suggestion.upper_return),
              })}>Use historical range as my assumptions</button></>
            : <p>{suggestion.reason}</p>}</div>}
          <button type="button" className="button button-secondary" disabled={busy} onClick={() => change({
            ...settings, investments: settings.investments.filter(row => row.key !== item.key),
          })}>Remove from projection settings</button>
          {tracked && <small>To remove a current asset from retirement, unassign it in Edit goal or record its disposal first.</small>}
        </section>;
      })}
    </div>
    <p>Contribution split total: {settings.investments.reduce((total, row) => total + Number(row.contribution_percentage || 0), 0).toFixed(2)}%</p>
    <div className="form-row">
      <label className="form-field"><span>Future investment type</span>
        <select value={futureKind} disabled={busy} onChange={e => {
          const next = e.target.value;
          if (next === "stock" || next === "etf" || next === "bond" || next === "future_deposit") setFutureKind(next);
        }}><option value="stock">Individual stock</option><option value="etf">ETF</option><option value="bond">Bond / bond fund</option><option value="future_deposit">New deposits</option></select></label>
      <label className="form-field"><span>Name / ticker</span><input value={futureName} disabled={busy} onChange={e => setFutureName(e.target.value)} maxLength={100} /></label>
    </div>
    <button className="button button-secondary" type="button" disabled={busy || !futureName.trim()} onClick={() => {
      change({ ...settings, investments: [...settings.investments, investment(futureKind, futureName.trim())] }); setFutureName("");
    }}>Add future investment</button>
    <label className="form-field"><span>Tax view</span><select value={settings.include_taxes ? "net" : "gross"} disabled={busy}
      onChange={e => change({ ...settings, include_taxes: e.target.value === "net" })}>
      <option value="net">After estimated horizon gains / deposit interest tax</option><option value="gross">Before tax</option>
    </select></label>
    <button className="button button-primary" type="button" disabled={busy} onClick={() => void calculate()}>{busy ? "Working…" : "Save and calculate retirement"}</button>
    {message && <p className="quiet-copy" role="status">{message}</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    {result?.lines && <section className="goal-insight-block">
      <h4>Compare historical results with my return assumptions</h4>
      <label><input type="checkbox" checked={real} onChange={e => setReal(e.target.checked)} /> Show today's purchasing power</label>
      <p className="quiet-copy">Inflation: {(Number(result.settings?.annual_inflation_rate) * 100).toFixed(2)}% annually, held constant for this calculation. World CPI is a benchmark, not a personal spending basket.</p>
      <RetirementChart result={result} real={real} currency={settings.currency} />
      <p>Current selected market value: {amount(result.current_value ?? "0", settings.currency)}. Contributions paid: {amount(result.contributions_paid ?? "0", settings.currency)}.</p>
      <p className="quiet-copy">Historical windows: {result.historical_windows}. Endpoint minimum starts {result.historical_min_start ?? "unavailable"}; maximum starts {result.historical_max_start ?? "unavailable"}. Deposit contracts retain their stated terms inside historical comparisons.</p>
      {result.split_suggestion?.available && <p className="quiet-copy">
        Historical reference for your future split: {(Number(result.split_suggestion.lower_return) * 100).toFixed(2)}%–{(Number(result.split_suggestion.upper_return) * 100).toFixed(2)}% annually; median {(Number(result.split_suggestion.median_return) * 100).toFixed(2)}%.
        {" "}{result.split_suggestion.method}
      </p>}
      <details><summary>Exactly how this is calculated</summary>
        {[...(result.assumptions ?? []), ...(result.warnings ?? [])].map(note => <p className="quiet-copy" key={note}>{note}</p>)}
      </details>
      {!result.lines.historical_lower && <p className="inline-error">Historical lines unavailable: select matching licensed history covering the full horizon for each non-contract investment.</p>}
    </section>}
    <details className="goal-insight-block"><summary>Local historical data and usage rights</summary>
      <p className="quiet-copy">Monthly data is compact: at most 2,401 observations per dataset (200 years), 200 datasets per user. It stays in your local database, outside Git. No proprietary market dataset is bundled or redistributed. Personal use does not override a provider's license.</p>
      <p className="quiet-copy">Import a total-return index including reinvested dividends/coupons and historical FX in {settings.currency}. CSV columns: <code>date,total_return_index</code>, ascending month-end dates with no gaps. The app can check format, not certify the source's rights or methodology.</p>
      <form onSubmit={e => void importHistory(e)} className="goal-form">
        <label className="form-field"><span>Dataset name</span><input name="name" required minLength={2} maxLength={100} /></label>
        <label className="form-field"><span>Source / attribution</span><input name="source" required minLength={3} maxLength={500} /></label>
        <label className="form-field"><span>License / permission reference</span><input name="license" required minLength={3} maxLength={200} /></label>
        <label className="form-field"><span>Monthly total-return CSV</span><input name="file" type="file" accept=".csv,text/csv" required /></label>
        <label><input type="checkbox" name="rights" required /> I have permission to retain this data locally. I will not redistribute it unless permitted.</label>
        <label><input type="checkbox" name="total" required /> This is a total-return series, not prices alone, in the selected projection currency.</label>
        <button className="button button-secondary" disabled={busy}>Import local history</button>
      </form>
      {history.map(row => <p className="quiet-copy" key={row.id}>{row.name} · {row.currency} · {row.observations} observations · {row.source} · {row.license} <button type="button" className="button button-secondary" disabled={busy} onClick={() => void deleteHistory(row.id)}>Delete</button></p>)}
    </details>
  </section>;
}

function RetirementChart({ result, real, currency }: { result: RetirementProjection; real: boolean; currency: RetirementSettings["currency"] }) {
  const lines = result.lines;
  if (!lines) return null;
  const entries = (Object.keys(labels) as (keyof typeof labels)[]).map(key => ({
    key, points: lines[key], color: colors[key], label: labels[key],
  }));
  const values = entries.flatMap(row => row.points?.map(point => Number(real ? point.real_value : point.nominal_value)) ?? []);
  const max = Math.max(1, ...values);
  const min = Math.min(0, ...values);
  const x = (index: number, length: number) => 55 + index / Math.max(1, length - 1) * 710;
  const y = (value: number) => 235 - (value - min) / (max - min) * 210;
  return <>
    <svg viewBox="0 0 800 280" role="img" aria-label="Retirement historical minimum and maximum compared with my lower and upper return assumptions" style={{ width: "100%", minHeight: 230 }}>
      {[0, 0.5, 1].map(fraction => <g key={fraction}>
        <line x1="55" x2="765" y1={y(min + fraction * (max - min))} y2={y(min + fraction * (max - min))} stroke="currentColor" opacity="0.15" />
        <text x="5" y={y(min + fraction * (max - min))} fontSize="10" fill="currentColor">{Math.round((min + fraction * (max - min)) / 1000)}k</text>
      </g>)}
      {entries.map(row => row.points && <polyline key={row.key} fill="none" stroke={row.color} strokeWidth="2.5"
        strokeDasharray={row.key.startsWith("historical") ? "6 4" : undefined}
        points={row.points.map((point, index) => `${x(index, row.points?.length ?? 1)},${y(Number(real ? point.real_value : point.nominal_value))}`).join(" ")}>
        <title>{row.label}</title>
      </polyline>)}
      <text x="55" y="260" fontSize="11" fill="currentColor">{lines.user_lower?.[0]?.date}</text>
      <text x="650" y="260" fontSize="11" fill="currentColor">{lines.user_lower?.at(-1)?.date}</text>
    </svg>
    <ul className="goal-insight-list">{entries.map(row => {
      const endpoint = row.points?.at(-1);
      return <li key={row.key}><span style={{ color: row.color }}>{row.label}</span>: {endpoint
        ? amount(real ? endpoint.real_value : endpoint.nominal_value, currency) : "Unavailable"}</li>;
    })}</ul>
  </>;
}
