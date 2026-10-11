import { useEffect, useState, type FormEvent } from "react";
import { Plus, Search, Trash2, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { MarketSymbol, VestingGrantPayload } from "../types";

interface AddGrantDialogProps {
  marketDataConfigured: boolean;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

interface CustomTrancheDraft {
  id: string;
  vestDate: string;
  units: string;
}

export function AddGrantDialog({
  marketDataConfigured,
  onClose,
  onCreated,
}: AddGrantDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSymbol[]>([]);
  const [selected, setSelected] = useState<MarketSymbol | null>(null);
  const [grantType, setGrantType] = useState<"rsu" | "option">("rsu");
  const [scheduleMode, setScheduleMode] = useState<"standard" | "custom">("standard");
  const [grantDate, setGrantDate] = useState(localDateValue());
  const [customTranches, setCustomTranches] = useState<CustomTrancheDraft[]>([
    { id: crypto.randomUUID(), vestDate: "", units: "" },
  ]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const customTotalUnits = customTranches.reduce(
    (total, tranche) => total + (Number(tranche.units) || 0),
    0,
  );
  const invalidCustomSchedule = customTranches.some(
    (tranche) => !tranche.vestDate || !Number.isFinite(Number(tranche.units)) || Number(tranche.units) <= 0,
  );

  useEffect(() => {
    const normalized = query.trim();
    if (!marketDataConfigured || normalized.length < 2 || selected) {
      setResults([]);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setSearching(true);
      setError("");
      void api.searchSymbols(normalized, controller.signal)
        .then((response) => setResults(response.results.filter((result) => result.instrument_type === "STOCK")))
        .catch((cause) => {
          if (!controller.signal.aborted) {
            setResults([]);
            setError(cause instanceof ApiError ? cause.message : "Symbol search failed.");
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 300);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [marketDataConfigured, query, selected]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) {
      setError("Choose a stock listing before saving this grant.");
      return;
    }
    const form = new FormData(event.currentTarget);
    const customSchedule = scheduleMode === "custom";
    const longTermMonths = Number(form.get("longTermMonths"));
    const payload: VestingGrantPayload = {
      symbol: selected.symbol,
      mic_code: selected.mic_code,
      exchange: selected.exchange,
      grant_type: grantType,
      grant_label: String(form.get("grantLabel") ?? "").trim(),
      ...(grantDate ? { grant_date: grantDate } : {}),
      total_units: String(customSchedule ? customTotalUnits.toFixed(8) : form.get("units") ?? ""),
      tax_rate_assumption: String(Number(form.get("taxPercent")) / 100),
      short_term_sale_tax_rate: String(Number(form.get("shortSaleTaxPercent")) / 100),
      long_term_sale_tax_rate: String(Number(form.get("longSaleTaxPercent")) / 100),
      long_term_holding_period_days: Math.round(longTermMonths * 365 / 12),
      ...(customSchedule
        ? {
            tranches: customTranches.map((tranche) => ({
              vest_date: tranche.vestDate,
              units: tranche.units,
            })),
          }
        : {
            duration_months: Number(form.get("durationMonths")),
            cliff_months: Number(form.get("cliffMonths")),
            interval_months: Number(form.get("intervalMonths")),
          }),
      ...(grantType === "option" ? { strike_price: String(form.get("strikePrice") ?? "") } : {}),
    };
    setSaving(true);
    setError("");
    try {
      await api.createVestingGrant(payload);
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The grant could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card grant-dialog" role="dialog" aria-modal="true" aria-labelledby="grant-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Employer equity · mark-to-market estimate</div>
            <h2 id="grant-dialog-title">Add an equity grant</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          Unvested awards stay separate from owned shares and cash. Northstar values future RSU tranches using the latest cached quote; options use intrinsic value only.
        </p>
        {!marketDataConfigured ? (
          <div className="inline-error" role="status">
            Set <code>TWELVE_DATA_API_KEY</code> in the project <code>.env</code> file to search listings and load a quote.
          </div>
        ) : (
          <form className="goal-form" onSubmit={submit}>
            <label className="form-field">
              <span>Award name <small>optional</small></span>
              <input name="grantLabel" maxLength={80} placeholder="e.g. On-Hire or FY26 Annual SA" />
            </label>
            <label className="form-field">
              <span>Underlying stock</span>
              <div className="market-search-input">
                <Search size={16} aria-hidden="true" />
                <input
                  aria-label="Search stocks"
                  value={selected ? `${selected.symbol} · ${selected.name}` : query}
                  onChange={(event) => {
                    setSelected(null);
                    setQuery(event.target.value);
                  }}
                  placeholder="Company or ticker · e.g. Microsoft or MSFT"
                  autoFocus
                />
                {selected && (
                  <button
                    className="icon-button small"
                    type="button"
                    aria-label="Clear selected stock"
                    onClick={() => {
                      setSelected(null);
                      setQuery("");
                    }}
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            </label>
            {searching && <p className="quiet-copy" role="status">Searching stock listings…</p>}
            {results.length > 0 && !selected && (
              <div className="market-search-results" role="listbox" aria-label="Stock search results">
                {results.map((result) => (
                  <button
                    className="market-search-result"
                    type="button"
                    key={`${result.symbol}-${result.mic_code ?? result.exchange}`}
                    onClick={() => {
                      setSelected(result);
                      setQuery(result.symbol);
                      setResults([]);
                      setError("");
                    }}
                  >
                    <span><strong>{result.symbol}</strong><small>{result.name}</small></span>
                    <span><strong>{result.currency}</strong><small>{result.exchange}</small></span>
                  </button>
                ))}
              </div>
            )}
            {query.trim().length >= 2 && !searching && !selected && results.length === 0 && !error && (
              <p className="quiet-copy">No stock listings found for this search.</p>
            )}
            <label className="form-field">
              <span>Grant type</span>
              <select value={grantType} onChange={(event) => setGrantType(event.target.value as "rsu" | "option")}>
                <option value="rsu">RSUs / stock bonus</option>
                <option value="option">Stock options</option>
              </select>
            </label>
            {grantType === "option" && (
              <label className="form-field">
                <span>Strike price per share ({selected?.currency ?? "listing currency"})</span>
                <input name="strikePrice" type="number" required min="0.00000001" max="100000000" step="0.00000001" placeholder="Exercise price" />
              </label>
            )}
            <div className="form-row">
              <label className="form-field">
                <span>Grant date <small>{scheduleMode === "custom" ? "optional if unknown" : "required for generated schedule"}</small></span>
                <input
                  name="grantDate"
                  type="date"
                  value={grantDate}
                  onChange={(event) => setGrantDate(event.target.value)}
                  required={scheduleMode === "standard"}
                />
              </label>
              <label className="form-field">
                <span>Vesting schedule</span>
                <select
                  value={scheduleMode}
                  onChange={(event) => {
                    const mode = event.target.value as "standard" | "custom";
                    setScheduleMode(mode);
                    setGrantDate(mode === "standard" ? localDateValue() : "");
                  }}
                >
                  <option value="standard">Generate from duration / cliff</option>
                  <option value="custom">Enter each vest date and share count</option>
                </select>
              </label>
            </div>
            {scheduleMode === "standard" ? (
              <>
                <label className="form-field">
                  <span>Granted shares/options</span>
                  <input name="units" type="number" required min="0.00000001" max="1000000000" step="0.00000001" placeholder="e.g. 120" />
                </label>
                <div className="form-row">
                  <label className="form-field">
                    <span>Vesting duration (months)</span>
                    <input name="durationMonths" type="number" required min="1" max="600" defaultValue="48" />
                  </label>
                  <label className="form-field">
                    <span>Cliff (months)</span>
                    <input name="cliffMonths" type="number" required min="0" max="600" defaultValue="12" />
                  </label>
                </div>
                <label className="form-field">
                  <span>Vesting interval</span>
                  <select name="intervalMonths" defaultValue="3">
                    <option value="1">Monthly</option>
                    <option value="3">Quarterly</option>
                    <option value="6">Every 6 months</option>
                    <option value="12">Annually</option>
                  </select>
                </label>
              </>
            ) : (
              <div className="custom-tranche-editor">
                <div className="custom-tranche-heading">
                  <strong>Individual vesting periods</strong>
                  <span>{customTotalUnits.toLocaleString("en-US", { maximumFractionDigits: 8 })} shares total</span>
                </div>
                {customTranches.map((tranche, index) => (
                  <div className="custom-tranche-row" key={tranche.id}>
                    <label className="form-field">
                      <span>Vest date {index + 1}</span>
                      <input
                        type="date"
                        required
                        value={tranche.vestDate}
                        onChange={(event) => setCustomTranches((items) =>
                          items.map((item) => item.id === tranche.id ? { ...item, vestDate: event.target.value } : item),
                        )}
                      />
                    </label>
                    <label className="form-field">
                      <span>Shares</span>
                      <input
                        type="number"
                        required
                        min="0.00000001"
                        step="0.00000001"
                        value={tranche.units}
                        onChange={(event) => setCustomTranches((items) =>
                          items.map((item) => item.id === tranche.id ? { ...item, units: event.target.value } : item),
                        )}
                      />
                    </label>
                    <button
                      className="icon-button small"
                      type="button"
                      aria-label={`Remove vesting period ${index + 1}`}
                      disabled={customTranches.length === 1}
                      onClick={() => setCustomTranches((items) => items.filter((item) => item.id !== tranche.id))}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => setCustomTranches((items) => [
                    ...items,
                    { id: crypto.randomUUID(), vestDate: "", units: "" },
                  ])}
                >
                  <Plus size={15} /> Add vesting period
                </button>
              </div>
            )}
            <div className="grant-tax-fields">
              <div className="eyebrow">Illustrative tax assumptions</div>
              <label className="form-field">
                <span>Tax at vest (%)</span>
                <input name="taxPercent" type="number" required min="0" max="100" step="0.1" defaultValue="0" />
              </label>
              <div className="form-row">
                <label className="form-field">
                  <span>Sale tax before threshold (%)</span>
                  <input name="shortSaleTaxPercent" type="number" required min="0" max="100" step="0.1" defaultValue="6" />
                </label>
                <label className="form-field">
                  <span>Sale tax after threshold (%)</span>
                  <input name="longSaleTaxPercent" type="number" required min="0" max="100" step="0.1" defaultValue="3" />
                </label>
              </div>
              <label className="form-field">
                <span>Long-term holding threshold (months)</span>
                <input name="longTermMonths" type="number" required min="1" max="1200" step="1" defaultValue="12" />
              </label>
              <p className="quiet-copy">Sale-rate scenarios are simple percentage haircuts on modeled stock value, not tax on capital gains. Tax at vest is shown separately.</p>
            </div>
            <div className="account-storage-note">
              The selected listing is quoted when saved. Future values use the latest cached provider quote and update when you manually refresh market data.
            </div>
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
              <button className="button button-primary" type="submit" disabled={saving || !selected || (scheduleMode === "custom" && (invalidCustomSchedule || customTotalUnits <= 0))}>
                {saving ? "Saving…" : "Add grant"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
