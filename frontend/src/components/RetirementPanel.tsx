import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, CheckCircle2, ChevronRight, LoaderCircle, Plus, Search, Target } from "lucide-react";
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
  onEditGoal: () => void;
  editingGoal: boolean;
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

export function RetirementPanel({ goalId, data, onSaved, onEditGoal, editingGoal }: Props) {
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
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const loadedGoal = useRef<string | null>(null);
  const [snapshotNotice, setSnapshotNotice] = useState("");
  const [retry, setRetry] = useState(0);
  const [pending, setPending] = useState("");
  const historyDetails = useRef<HTMLDetailsElement>(null);
  const errorNotice = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (error) errorNotice.current?.scrollIntoView({
      block: "center",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  }, [error]);

  useEffect(() => {
    const newGoal = loadedGoal.current !== goalId;
    loadedGoal.current = goalId;
    if (!newGoal && dirtyRef.current) {
      setSnapshotNotice("Your account snapshot refreshed. Your edits are safe; calculating will use the latest linked assets.");
    }
    let active = true;
    if (newGoal) {
      dirtyRef.current = false; setDirty(false); setResult(null); setSettings(null);
      setSuggestions({}); setInflation(null); setMessage(""); setSnapshotNotice("");
    }
    setError("");
    Promise.all([api.listGoals(), api.retirementHistory()]).then(async ([goals, datasets]) => {
      if (!active) return;
      const goal = goals.find(row => row.id === goalId);
      if (!goal) throw new Error("Retirement goal is unavailable.");
      setHistory(datasets);
      if (dirtyRef.current) {
        setSettings(current => current ? {
          ...initialSettings({ ...goal, retirement_settings: current }, data),
          target_date: current.target_date,
        } : initialSettings(goal, data));
        return;
      }
      setSettings(initialSettings(goal, data));
      if (goal.retirement_settings) {
        const projection = await api.retirementProjection(goalId);
        if (active && !dirtyRef.current) setResult(projection);
      }
    }).catch(cause => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [goalId, data, retry]);

  function change(next: RetirementSettings) {
    dirtyRef.current = true; setDirty(true);
    setSettings(next); setMessage(""); setError("");
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
    setBusy(true); setPending(`Loading history for ${item.name}…`); setError(""); setMessage("");
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
    setBusy(true); setPending("Finding matching inflation history…"); setError(""); setMessage("");
    try { setInflation(await api.retirementInflation(settings.target_date)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function calculate() {
    if (!settings) return;
    setError(""); setMessage(""); setBusy(true); setPending("Saving and calculating your projection…");
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
      dirtyRef.current = false; setDirty(false); setSnapshotNotice("");
      setSettings(projection.settings ?? settings);
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
    setBusy(true); setPending("Importing your local dataset…"); setError(""); setMessage("");
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
    if (settings?.investments.some(item => item.history_id === id)) {
      setMessage(""); setError("Remove this dataset from your investments and save the plan before deleting it."); return;
    }
    if (!window.confirm("Delete this local dataset? Active goal references must be removed first.")) return;
    setBusy(true); setPending("Deleting the dataset…"); setError(""); setMessage("");
    try {
      await api.deleteRetirementHistory(id); setHistory(await api.retirementHistory());
      setMessage("Local history dataset deleted.");
    }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  if (!settings) return <div className="goal-insights retirement-panel">{error
    ? <><p className="inline-error" role="alert" ref={errorNotice}>{error}</p><button className="button button-secondary" type="button" onClick={() => setRetry(value => value + 1)}>Retry loading</button></>
    : <p className="retirement-status" role="status"><LoaderCircle className="is-spinning" size={18} /> Loading your retirement plan…</p>}</div>;
  const visible = settings.investments.filter(row => row.name.toLowerCase().includes(search.toLowerCase()));
  const splitTotal = settings.investments.reduce((total, row) => total + Number(row.contribution_percentage || 0), 0);
  function openHistory() {
    if (!historyDetails.current) return;
    historyDetails.current.open = true;
    historyDetails.current.scrollIntoView({
      block: "start",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  }
  const addFutureInvestment = () => {
    const name = futureName.trim();
    if (!name) { setError("Enter a name or ticker before adding a future investment."); return; }
    change({ ...settings, investments: [...settings.investments, investment(futureKind, name)] });
    setFutureName("");
  };

  return <section className="goal-insights retirement-panel" aria-label="Retirement planner" aria-busy={busy}>
    <header className="retirement-heading">
      <span className="retirement-heading-icon"><Target size={24} /></span>
      <div><div className="eyebrow">Plan, compare, understand</div><h3>Your retirement, one step at a time</h3>
      <p>Build on what you own today. Choose how to invest future savings, then compare possible outcomes.</p></div>
      <span className="retirement-badge">{dirty ? "Unsaved changes" : "No automatic trades"}</span>
    </header>
    {error && <p className="inline-error" role="alert" ref={errorNotice}>{error}</p>}
    {message && <p className="retirement-status success" role="status"><CheckCircle2 size={18} />{message}</p>}
    {snapshotNotice && <p className="retirement-status" role="status">{snapshotNotice}</p>}
    {busy && <p className="retirement-status" role="status"><LoaderCircle className="is-spinning" size={18} />{pending}</p>}
    <form className="retirement-form" onSubmit={event => { event.preventDefault(); void calculate(); }}>
    <section className="retirement-step">
    <div className="retirement-step-heading"><span>1</span><div><h4>Choose your horizon</h4><p>When will you need this money, and how much can you add?</p></div></div>
    <div className="form-row retirement-horizon">
      <label className="form-field"><span>Retirement date</span>
        <input type="date" required value={settings.target_date} disabled={busy} onChange={e => {
          change({ ...settings, target_date: e.target.value }); setSuggestions({}); setInflation(null);
        }} /></label>
      <label className="form-field"><span>Or years from today</span>
        <input type="number" min="1" max="100" step="1" placeholder="e.g. 20" disabled={busy}
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
        <input type="number" required min="0" max="100000000" step="0.01" value={settings.contribution_amount} disabled={busy}
          onChange={e => change({ ...settings, contribution_amount: e.target.value })} /></label>
      <label className="form-field"><span>Contribution frequency</span>
        <select value={settings.contribution_frequency} disabled={busy} onChange={e => change({
          ...settings, contribution_frequency: e.target.value === "yearly" ? "yearly" : "monthly",
        })}><option value="monthly">Every month</option><option value="yearly">Every year</option></select>
      </label>
    </div>
    <p className="quiet-copy">Payments are added after growth on each monthly or yearly anniversary. Your existing investments are not rebalanced.</p>
    </section>
    <section className="retirement-step">
    <div className="retirement-step-heading"><span>2</span><div><h4>Allow for inflation</h4><p>See what your future money could buy in today's terms.</p></div></div>
    <div className="retirement-inline-controls">
    <label className="form-field"><span>Annual worldwide inflation (%)</span>
      <input type="number" required min="-99.99" max="100" step="any" placeholder="Enter or use a suggestion" value={settings.annual_inflation_rate === "" ? "" : Number(settings.annual_inflation_rate) * 100}
        disabled={busy} onChange={e => change({ ...settings, annual_inflation_rate: e.target.value === "" ? "" : String(Number(e.target.value) / 100) })} />
    </label>
    <button type="button" className="button button-secondary" disabled={busy || !settings.target_date} onClick={() => void suggestInflation()}>Suggest from history <ArrowRight size={15} /></button>
    </div>
    {!settings.target_date && <p className="quiet-copy">Choose a retirement date above to unlock the historical inflation suggestion.</p>}
    {inflation && <div className="retirement-suggestion">
      {inflation.available && inflation.suggested_rate !== null
        ? <>Suggested: {(inflation.suggested_rate * 100).toFixed(2)}% yearly; observed range {(Number(inflation.lower_rate) * 100).toFixed(2)}%–{(Number(inflation.upper_rate) * 100).toFixed(2)}% ({inflation.windows} windows).
          <button className="button button-secondary" type="button" disabled={busy} onClick={() => change({ ...settings, annual_inflation_rate: String(inflation.suggested_rate) })}>Use suggestion</button></>
        : inflation.reason}
      <p>{inflation.method}</p><p><a href={inflation.source} target="_blank" rel="noreferrer">World Bank source</a> · {inflation.license} · {inflation.sample_start}–{inflation.sample_end}</p>
    </div>}
    </section>
    <section className="retirement-step">
    <div className="retirement-step-heading"><span>3</span><div><h4>Choose investments and your split</h4><p>Percentages apply to new contributions, not your current portfolio.</p></div>
    <button className="button button-secondary" type="button" disabled={busy || editingGoal} onClick={onEditGoal}>{editingGoal ? "Opening…" : "Manage linked assets"}</button></div>
    <label className="form-field retirement-search"><span>Search selected investments</span><div><Search size={16} aria-hidden="true" /><input placeholder="Find a stock, ETF or deposit…" value={search} onChange={e => setSearch(e.target.value)} /></div></label>
    <div className="retirement-investment-list" tabIndex={0} aria-label="Selected investments">
      {visible.length === 0 && <div className="retirement-empty"><strong>{settings.investments.length ? "No matching investments" : "Start with an investment"}</strong><p>{settings.investments.length ? "Try a different search or clear the filter." : "Link an existing asset above, or add a future investment below."}</p>{search && <button type="button" className="button button-secondary" onClick={() => setSearch("")}>Clear search</button>}</div>}
      {visible.map(item => {
        const suggestion = suggestions[item.key];
        const tracked = item.kind === "holding" || item.kind === "deposit";
        const linkedGoal = data.goals.find(row => row.id === goalId);
        const stillLinked = item.kind === "holding" ? linkedGoal?.holding_ids.includes(item.asset_id ?? "") : item.kind === "deposit" ? linkedGoal?.fixed_deposit_ids.includes(item.asset_id ?? "") : false;
        return <section className="retirement-investment" key={item.key}>
          <div className="retirement-investment-heading"><h4>{item.name}</h4><span className="retirement-badge">{tracked ? "Linked asset" : "Future purchases"}</span></div>
          <div className="form-row">
            <label className="form-field"><span>Share of new contributions (%)</span>
              <input type="number" required min="0" max="100" step="0.01" value={item.contribution_percentage} disabled={busy || item.kind === "deposit"}
                onChange={e => update(item.key, { contribution_percentage: e.target.value })} /></label>
            {!tracked && <label className="form-field"><span>Estimated tax on gains / interest (%)</span>
              <input type="number" required={settings.include_taxes} min="0" max="100" step="any" placeholder="Enter 0 if exempt" value={item.tax_rate === "" || item.tax_rate === null ? "" : Number(item.tax_rate) * 100} disabled={busy}
                onChange={e => update(item.key, { tax_rate: e.target.value === "" ? "" : String(Number(e.target.value) / 100) })} /></label>}
          </div>
          <div className="form-row">
            {(["lower_return", "upper_return"] as const).map(key => <label className="form-field" key={key}>
              <span>{key === "lower_return" ? "My lower" : "My upper"} yearly return (%)</span>
              <input type="number" required min="-99.99" max="100" step="any" placeholder={key === "lower_return" ? "Conservative assumption" : "Optimistic assumption"} disabled={busy || item.kind === "deposit"}
                value={item[key] === "" ? "" : Number(item[key]) * 100}
                onChange={e => update(item.key, { [key]: e.target.value === "" ? "" : String(Number(e.target.value) / 100) })} />
            </label>)}
          </div>
          {item.kind === "future_deposit" && <label className="form-field"><span>Term for each new deposit (months; no renewal)</span>
            <input type="number" min="1" max="1200" value={item.deposit_term_months} disabled={busy}
              onChange={e => update(item.key, { deposit_term_months: Number(e.target.value) })} /></label>}
          {item.kind === "deposit" && <p className="quiet-copy">This deposit uses its contractual rate and maturity. To invest more in deposits, add a new-deposit destination below.</p>}
          {item.kind !== "deposit" && <details className="retirement-history-picker"><summary>Historical return suggestions <ChevronRight size={14} /></summary>
            <label className="form-field"><span>Local total-return dataset ({settings.currency})</span>
              <select value={item.history_id ?? ""} disabled={busy} onChange={e => update(item.key, { history_id: e.target.value || null })}>
                <option value="">No historical dataset — manual results only</option>
                {history.filter(row => row.currency === settings.currency).map(row => <option value={row.id} key={row.id}>{row.name} ({row.sample_start}–{row.sample_end})</option>)}
              </select></label>
            <button className="button button-secondary" type="button" disabled={busy || !item.history_id} onClick={() => void suggestReturns(item)}>Show historical return recommendation</button>
            {!item.history_id && <p className="quiet-copy">Select a compatible dataset to enable this button, or <button className="text-button" type="button" onClick={openHistory}>import local history</button>. You can also enter your own return assumptions without history.</p>}
          </details>}
          {suggestion && <div className="retirement-suggestion">{suggestion.available
            ? <><p>Historical annualized min/max: {(Number(suggestion.lower_return) * 100).toFixed(2)}% / {(Number(suggestion.upper_return) * 100).toFixed(2)}%; median {(Number(suggestion.median_return) * 100).toFixed(2)}% over {suggestion.windows} matching windows.</p>
              <p>{suggestion.dataset?.source} · {suggestion.dataset?.license}. Selected history must match this investment or an explicitly chosen proxy.</p>
              {Number(suggestion.upper_return) > 1 && <p>Historical annualization exceeds the manual calculator's 100% annual planning limit. Enter your own assumptions; historical replay still uses the observed data.</p>}
              <button className="button button-secondary" type="button" disabled={busy || Number(suggestion.upper_return) > 1} onClick={() => update(item.key, {
                lower_return: String(suggestion.lower_return), upper_return: String(suggestion.upper_return),
              })}>Use historical range as my assumptions</button></>
            : <p>{suggestion.reason}</p>}</div>}
          {tracked && stillLinked ? <button className="text-button" type="button" disabled={busy || editingGoal} onClick={onEditGoal}>Edit this goal's asset links <ArrowRight size={14} /></button> : <button type="button" className="text-button retirement-remove" disabled={busy} onClick={() => change({
            ...settings, investments: settings.investments.filter(row => row.key !== item.key),
          })}>Remove from plan</button>}
          {tracked && !stillLinked && <p className="inline-error">This asset is no longer available. Remove it from the plan and choose a replacement for future contributions.</p>}
        </section>;
      })}
    </div>
    <div className={`retirement-split ${splitTotal === 100 ? "is-complete" : ""}`}><strong>Future contribution split</strong><span>{splitTotal.toFixed(2)}% / 100%</span></div>
    {Number(settings.contribution_amount) > 0 && splitTotal !== 100 && <p className="quiet-copy">Assign all new contributions before calculating. {splitTotal < 100 ? `${(100 - splitTotal).toFixed(2)}% remains to allocate.` : `Reduce the split by ${(splitTotal - 100).toFixed(2)}%.`}</p>}
    <div className="retirement-add-investment">
    <div className="form-row">
      <label className="form-field"><span>Future investment type</span>
        <select value={futureKind} disabled={busy} onChange={e => {
          const next = e.target.value;
          if (next === "stock" || next === "etf" || next === "bond" || next === "future_deposit") setFutureKind(next);
        }}><option value="stock">Individual stock</option><option value="etf">ETF</option><option value="bond">Bond / bond fund</option><option value="future_deposit">New deposits</option></select></label>
      <label className="form-field"><span>Name / ticker</span><input value={futureName} disabled={busy} onChange={e => setFutureName(e.target.value)} maxLength={100}
        onKeyDown={event => { if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); addFutureInvestment(); } }} /></label>
    </div>
    <button className="button button-secondary" type="button" disabled={busy || !futureName.trim()} onClick={addFutureInvestment}><Plus size={16} /> Add future investment</button>
    {!futureName.trim() && <small className="quiet-copy">Enter a name or ticker to enable Add. New investments start at zero; no purchase is recorded.</small>}
    </div>
    </section>
    <section className="retirement-step retirement-calculate">
    <div className="retirement-step-heading"><span>4</span><div><h4>Compare your possibilities</h4><p>Historical extremes are observations, not guarantees.</p></div></div>
    <label className="form-field"><span>Tax view</span><select value={settings.include_taxes ? "net" : "gross"} disabled={busy}
      onChange={e => change({ ...settings, include_taxes: e.target.value === "net" })}>
      <option value="net">After estimated horizon gains / deposit interest tax</option><option value="gross">Before tax</option>
    </select></label>
    <button className="button button-primary" type="submit" disabled={busy}>{busy ? <><LoaderCircle size={16} className="is-spinning" /> Please wait…</> : <>Save & compare outcomes <ArrowRight size={16} /></>}</button>
    </section>
    </form>
    {result?.lines && <section className="retirement-step retirement-results">
      <h4>Compare historical results with my return assumptions</h4>
      {dirty && <p className="retirement-status">These are your last calculated results. Save & compare to apply your changes.</p>}
      <label><input type="checkbox" checked={real} onChange={e => setReal(e.target.checked)} /> Show today's purchasing power</label>
      <p className="quiet-copy">Inflation: {(Number(result.settings?.annual_inflation_rate) * 100).toFixed(2)}% annually, held constant for this calculation. World CPI is a benchmark, not a personal spending basket.</p>
      <RetirementChart result={result} real={real} currency={result.settings?.currency ?? settings.currency} />
      <p>Current selected market value: {amount(result.current_value ?? "0", result.settings?.currency ?? settings.currency)}. Contributions paid: {amount(result.contributions_paid ?? "0", result.settings?.currency ?? settings.currency)}.</p>
      <p className="quiet-copy">Historical windows: {result.historical_windows}. Endpoint minimum starts {result.historical_min_start ?? "unavailable"}; maximum starts {result.historical_max_start ?? "unavailable"}. Deposit contracts retain their stated terms inside historical comparisons.</p>
      {result.split_suggestion?.available && <p className="quiet-copy">
        Historical reference for your future split: {(Number(result.split_suggestion.lower_return) * 100).toFixed(2)}%–{(Number(result.split_suggestion.upper_return) * 100).toFixed(2)}% annually; median {(Number(result.split_suggestion.median_return) * 100).toFixed(2)}%.
        {" "}{result.split_suggestion.method}
      </p>}
      <details><summary>Exactly how this is calculated</summary>
        {[...(result.assumptions ?? []), ...(result.warnings ?? [])].map(note => <p className="quiet-copy" key={note}>{note}</p>)}
      </details>
      {!result.lines.historical_lower && <div className="retirement-status"><span>Your personal scenarios are ready. Historical comparisons need matching history for each investment.</span><button className="text-button" type="button" onClick={openHistory}>Set up history <ArrowRight size={14} /></button></div>}
    </section>}
    <details className="retirement-step retirement-history" ref={historyDetails}><summary>Local historical data and usage rights <ChevronRight size={18} /></summary>
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
        <text x="5" y={y(min + fraction * (max - min))} fontSize="10" fill="currentColor">{new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(min + fraction * (max - min))}</text>
      </g>)}
      {entries.map(row => row.points && <polyline key={row.key} fill="none" stroke={row.color} strokeWidth="2.5"
        strokeDasharray={row.key.startsWith("historical") ? "6 4" : undefined}
        points={row.points.map((point, index) => `${x(index, row.points?.length ?? 1)},${y(Number(real ? point.real_value : point.nominal_value))}`).join(" ")}>
        <title>{row.label}</title>
      </polyline>)}
      <text x="55" y="260" fontSize="11" fill="currentColor">{lines.user_lower?.[0]?.date}</text>
      <text x="650" y="260" fontSize="11" fill="currentColor">{lines.user_lower?.at(-1)?.date}</text>
    </svg>
    <ul className="retirement-result-cards">{entries.map(row => {
      const endpoint = row.points?.at(-1);
      return <li key={row.key} style={{ borderTopColor: row.color }}><span>{row.label}</span><strong>{endpoint
        ? amount(real ? endpoint.real_value : endpoint.nominal_value, currency) : "Needs history"}</strong></li>;
    })}</ul>
  </>;
}
