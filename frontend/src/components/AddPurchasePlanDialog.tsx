import { useEffect, useState, type FormEvent } from "react";
import { Search, ShoppingCart, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountSummary, MarketSymbol, StockPurchasePlanPayload } from "../types";

interface AddPurchasePlanDialogProps {
  accounts: AccountSummary[];
  marketDataConfigured: boolean;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function AddPurchasePlanDialog({
  accounts,
  marketDataConfigured,
  onClose,
  onCreated,
}: AddPurchasePlanDialogProps) {
  const shareAccounts = accounts.filter(
    (account) =>
      account.account_type !== "SAVINGS" &&
      !account.is_sample,
  );
  const wallets = accounts
    .filter((account) => account.account_type !== "EMPLOYER_PLAN" && !account.is_sample)
    .flatMap((account) => account.subaccounts.map((subaccount) => ({ account, subaccount })));
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSymbol[]>([]);
  const [selected, setSelected] = useState<MarketSymbol | null>(null);
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
      setError("Choose a stock listing before saving this purchase.");
      return;
    }
    const form = new FormData(event.currentTarget);
    const referencePrice = String(form.get("referencePrice") ?? "").trim();
    const name = String(form.get("planName") ?? "").trim();
    const payload: StockPurchasePlanPayload = {
      ...(name ? { name } : {}),
      symbol: selected.symbol,
      mic_code: selected.mic_code,
      exchange: selected.exchange,
      account_id: String(form.get("shareAccount") ?? ""),
      subaccount_id: String(form.get("walletId") ?? ""),
      shares: String(form.get("shares") ?? ""),
      purchase_date: String(form.get("purchaseDate") ?? ""),
      discount_rate: String(Number(form.get("discountPercent")) / 100),
      receipt_tax_rate: String(Number(form.get("receiptTaxPercent")) / 100),
      sale_profit_tax_rate: String(Number(form.get("profitTaxPercent")) / 100),
      ...(referencePrice ? { reference_price: referencePrice } : {}),
    };
    setSaving(true);
    setError("");
    try {
      await api.createStockPurchasePlan(payload);
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The share purchase could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const blocked = !marketDataConfigured || shareAccounts.length === 0 || wallets.length === 0;

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card grant-dialog" role="dialog" aria-modal="true" aria-labelledby="purchase-plan-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Employer share purchase · estimate</div>
            <h2 id="purchase-plan-title">Plan a discounted share purchase</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          On the purchase date you pay the discounted price. The discount is taxed when received (for example as salary income in Romania), and later gains above the market price on that day use the profit tax. Nothing is counted in your wealth until the purchase date.
        </p>
        {blocked ? (
          <div className="inline-error" role="status">
            {!marketDataConfigured
              ? <>Set <code>TWELVE_DATA_API_KEY</code> in the project <code>.env</code> file to search listings.</>
              : "Add a brokerage or employer-plan account for the shares and a bank or brokerage wallet that pays for them."}
          </div>
        ) : (
          <form className="goal-form" onSubmit={submit}>
            <label className="form-field">
              <span>Plan name <small>optional</small></span>
              <input name="planName" maxLength={80} placeholder="e.g. Q1 ESPP purchase" />
            </label>
            <label className="form-field">
              <span>Stock</span>
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
            <div className="form-row">
              <label className="form-field">
                <span>Shares to buy</span>
                <input name="shares" type="number" required min="0.00000001" max="1000000000" step="0.00000001" placeholder="e.g. 10" />
              </label>
              <label className="form-field">
                <span>Purchase date</span>
                <input name="purchaseDate" type="date" required defaultValue={localDateValue()} />
              </label>
            </div>
            <div className="form-row">
              <label className="form-field">
                <span>Discount (%)</span>
                <input name="discountPercent" type="number" required min="0" max="99.99" step="0.01" defaultValue="15" />
              </label>
              <label className="form-field">
                <span>Market price that day <small>optional · {selected?.currency ?? "listing currency"}</small></span>
                <input name="referencePrice" type="number" min="0.00000001" step="0.00000001" placeholder="Latest cached quote if blank" />
              </label>
            </div>
            <div className="grant-tax-fields">
              <div className="eyebrow">Illustrative tax assumptions</div>
              <div className="form-row">
                <label className="form-field">
                  <span>Tax when received (%)</span>
                  <input name="receiptTaxPercent" type="number" required min="0" max="100" step="0.1" defaultValue="45" />
                </label>
                <label className="form-field">
                  <span>Tax on later profit (%)</span>
                  <input name="profitTaxPercent" type="number" required min="0" max="100" step="0.1" defaultValue="10" />
                </label>
              </div>
              <p className="quiet-copy">Tax when received applies to the discount (market price minus what you pay). The profit tax applies only to gains above the market price on the purchase date.</p>
            </div>
            <div className="form-row">
              <label className="form-field">
                <span>Shares are held in</span>
                <select name="shareAccount" required defaultValue={shareAccounts[0]?.id}>
                  {shareAccounts.map((account) => (
                    <option value={account.id} key={account.id}>{account.display_name}</option>
                  ))}
                </select>
              </label>
              <label className="form-field">
                <span>Paid from</span>
                <select name="walletId" required defaultValue={wallets[0]?.subaccount.id}>
                  {wallets.map(({ account, subaccount }) => (
                    <option value={subaccount.id} key={subaccount.id}>
                      {account.display_name} · {subaccount.currency}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="account-storage-note">
              <ShoppingCart size={15} />
              <span>On the purchase date the price paid plus the tax when received is deducted once from the paying wallet and the shares are added to your portfolio. If the wallet has too little cash, the purchase waits and you will see a warning.</span>
            </div>
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
              <button className="button button-primary" type="submit" disabled={saving || !selected}>
                {saving ? "Saving…" : "Save share purchase"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
