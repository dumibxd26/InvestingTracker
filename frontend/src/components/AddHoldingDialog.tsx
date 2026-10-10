import { useEffect, useState, type FormEvent } from "react";
import { Search, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountSummary, MarketSymbol } from "../types";

interface AddHoldingDialogProps {
  accounts: AccountSummary[];
  marketDataConfigured: boolean;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

export function AddHoldingDialog({
  accounts,
  marketDataConfigured,
  onClose,
  onCreated,
}: AddHoldingDialogProps) {
  const eligibleAccounts = accounts.filter(
    (account) => account.account_type === "BROKERAGE" || account.account_type === "EMPLOYER_PLAN",
  );
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSymbol[]>([]);
  const [selected, setSelected] = useState<MarketSymbol | null>(null);
  const [accountId, setAccountId] = useState(eligibleAccounts[0]?.id ?? "");
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
        .then((response) => setResults(response.results))
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
    if (!selected || !accountId) {
      setError("Choose a market result and an investment account.");
      return;
    }
    setSaving(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api.addHolding({
        account_id: accountId,
        symbol: selected.symbol,
        mic_code: selected.mic_code,
        exchange: selected.exchange,
        instrument_type: selected.instrument_type,
        quantity: String(form.get("quantity") ?? ""),
        average_cost: String(form.get("averageCost") ?? ""),
      });
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The holding could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="modal-card holding-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="holding-dialog-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Provider-backed quotes · saved to your portfolio</div>
            <h2 id="holding-dialog-title">Add a stock or ETF</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Search by company or ticker, choose the exchange listing, then enter shares and your
          average cost per share. A quote is fetched when you add the position.
        </p>
        {!marketDataConfigured ? (
          <div className="inline-error" role="status">
            Set <code>TWELVE_DATA_API_KEY</code> in the project <code>.env</code> file and restart
            the backend to enable search and quotes.
          </div>
        ) : (
          <form className="goal-form" onSubmit={submit}>
            <label className="form-field">
              <span>Find an investment</span>
              <div className="market-search-input">
                <Search size={16} aria-hidden="true" />
                <input
                  aria-label="Search stocks and ETFs"
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
                    aria-label="Clear selected investment"
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
            {searching && <p className="quiet-copy" role="status">Searching provider listings…</p>}
            {results.length > 0 && !selected && (
              <div className="market-search-results" role="listbox" aria-label="Search results">
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
                    <span className="market-result-symbol">{result.symbol}</span>
                    <span className="market-result-details">
                      <strong>{result.name}</strong>
                      <small>
                        {result.exchange || result.country} · {result.instrument_type} · {result.currency}
                      </small>
                    </span>
                  </button>
                ))}
              </div>
            )}
            {query.trim().length >= 2 && !searching && !selected && results.length === 0 && !error && (
              <p className="quiet-copy">No stock or ETF listings found for that search.</p>
            )}
            {selected && (
              <>
                <div className="selected-instrument">
                  <span>
                    <strong>{selected.symbol}</strong>
                    <small>{selected.name} · {selected.exchange} · {selected.currency}</small>
                  </span>
                  <span className="status-pill status-confirmed">{selected.instrument_type}</span>
                </div>
                <div className="form-row">
                  <label className="form-field">
                    <span>Investment account</span>
                    <select
                      value={accountId}
                      onChange={(event) => setAccountId(event.target.value)}
                      required
                    >
                      {eligibleAccounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.display_name} · {account.currency}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="form-field">
                    <span>Number of shares</span>
                    <input
                      name="quantity"
                      type="number"
                      min="0.00000001"
                      max="1000000000"
                      step="any"
                      required
                      placeholder="e.g. 2.5"
                    />
                  </label>
                </div>
                <label className="form-field">
                  <span>Average cost per share ({selected.currency})</span>
                  <input
                    name="averageCost"
                    type="number"
                    min="0.00000001"
                    max="100000000"
                    step="any"
                    required
                    placeholder="Your average purchase price"
                  />
                </label>
              </>
            )}
            {eligibleAccounts.length === 0 && (
              <div className="inline-error" role="status">
                Add a brokerage or employer-plan account before adding a stock or ETF.
              </div>
            )}
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={onClose}>
                Cancel
              </button>
              <button
                className="button button-primary"
                type="submit"
                disabled={saving || !selected || eligibleAccounts.length === 0}
              >
                {saving ? "Adding position…" : "Add holding"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
