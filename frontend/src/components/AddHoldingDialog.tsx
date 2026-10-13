import { useEffect, useState, type FormEvent } from "react";
import { Search, X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount, convertAmount } from "../format";
import type { AccountSummary, Currency, MarketFxRate, MarketSymbol } from "../types";

interface AddHoldingDialogProps {
  accounts: AccountSummary[];
  marketDataConfigured: boolean;
  marketFxRates: MarketFxRate[];
  usdPerEur: string | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function AddHoldingDialog({
  accounts,
  marketDataConfigured,
  marketFxRates,
  usdPerEur,
  onClose,
  onCreated,
}: AddHoldingDialogProps) {
  const eligibleAccounts = accounts.filter(
    (account) => account.account_type !== "SAVINGS" && !account.is_sample,
  );
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSymbol[]>([]);
  const [selected, setSelected] = useState<MarketSymbol | null>(null);
  const [accountId, setAccountId] = useState(eligibleAccounts[0]?.id ?? "");
  const [subaccountId, setSubaccountId] = useState("");
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [quantity, setQuantity] = useState("");
  const [averageCost, setAverageCost] = useState("");
  const [averageCostCurrency, setAverageCostCurrency] = useState<Currency | null>(null);
  const [purchaseDate, setPurchaseDate] = useState(localDateValue());
  const selectedAccount = eligibleAccounts.find((account) => account.id === accountId);
  const selectedSubaccount = selectedAccount?.subaccounts.find(
    (subaccount) => subaccount.id === subaccountId,
  );
  const estimatedDebit =
    selected && selectedSubaccount && quantity && averageCost
      ? convertAmount(
          Number(quantity) * Number(averageCost),
          averageCostCurrency ?? selected.currency,
          selectedSubaccount.currency,
          marketFxRates,
          usdPerEur,
        )
      : null;

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
    if (!selected || !selectedAccount || !selectedSubaccount) {
      setError("Choose a market result, broker account, and funding wallet.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.addHolding({
        account_id: accountId,
        subaccount_id: subaccountId,
        symbol: selected.symbol,
        mic_code: selected.mic_code,
        exchange: selected.exchange,
        instrument_type: selected.instrument_type,
        quantity,
        average_cost: averageCost,
        average_cost_currency: averageCostCurrency ?? selected.currency,
        purchase_date: purchaseDate,
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
          Search by company or ticker, enter your shares and average cost, then choose a wallet.
          Average-cost currency defaults to the listing currency, but you can change it. The cost
          basis is converted to the chosen wallet currency for the balance check and debit.
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
                    setAverageCostCurrency(null);
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
                      setAverageCostCurrency(result.currency);
                      setQuery(result.symbol);
                      const matchingAccount =
                        eligibleAccounts.find((account) =>
                          account.subaccounts.some(
                            (subaccount) => subaccount.currency === result.currency,
                          ),
                        ) ?? eligibleAccounts.find((account) => account.subaccounts.length > 0);
                      if (matchingAccount) {
                        setAccountId(matchingAccount.id);
                        setSubaccountId(
                          matchingAccount.subaccounts.find(
                            (subaccount) => subaccount.currency === result.currency,
                          )?.id ?? matchingAccount.subaccounts[0]?.id ?? "",
                        );
                      } else {
                        setSubaccountId("");
                      }
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
                      onChange={(event) => {
                        const nextAccountId = event.target.value;
                        const nextAccount = eligibleAccounts.find(
                          (account) => account.id === nextAccountId,
                        );
                        setAccountId(nextAccountId);
                        setSubaccountId(nextAccount?.subaccounts[0]?.id ?? "");
                      }}
                      required
                    >
                      {eligibleAccounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.display_name} · {account.subaccounts.map((wallet) => wallet.currency).join("/")}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="form-field">
                    <span>Funded from</span>
                    <select
                      value={subaccountId}
                      onChange={(event) => setSubaccountId(event.target.value)}
                      required
                      disabled={!selectedAccount?.subaccounts.length}
                    >
                      {selectedAccount?.subaccounts.map((subaccount) => (
                        <option key={subaccount.id} value={subaccount.id}>
                          {subaccount.currency} cash · {amount(subaccount.cash_balance, subaccount.currency, 2)}
                        </option>
                      ))}
                      {!selectedAccount?.subaccounts.length && (
                        <option value="">Add a currency sub-account first</option>
                      )}
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
                      value={quantity}
                      onChange={(event) => setQuantity(event.target.value)}
                    />
                  </label>
                </div>
                <label className="form-field">
                  <span>Average cost per share</span>
                  <div className="average-cost-input">
                    <input
                      type="number"
                      min="0.00000001"
                      max="100000000"
                      step="any"
                      required
                      placeholder="Your average purchase price"
                      value={averageCost}
                      onChange={(event) => setAverageCost(event.target.value)}
                    />
                    <select
                      aria-label="Average cost currency"
                      value={averageCostCurrency ?? selected.currency}
                      onChange={(event) =>
                        setAverageCostCurrency(event.target.value as Currency)
                      }
                    >
                      {(["EUR", "USD", "RON"] as Currency[]).map((currency) => (
                        <option value={currency} key={currency}>{currency}</option>
                      ))}
                    </select>
                  </div>
                </label>
                <label className="form-field">
                  <span>Purchase date <small>tax estimate basis</small></span>
                  <input
                    type="date"
                    required
                    value={purchaseDate}
                    onChange={(event) => setPurchaseDate(event.target.value)}
                  />
                </label>
                {(!selectedAccount || selectedAccount.subaccounts.length === 0) && (
                  <div className="inline-error" role="status">
                    Add a currency sub-account to this broker before recording this purchase.
                  </div>
                )}
                <p className="quiet-copy">
                  {estimatedDebit !== null && selectedSubaccount
                    ? `Estimated debit: ${amount(String(estimatedDebit), selectedSubaccount.currency, 2)} from the ${selectedSubaccount.currency} wallet.`
                    : selectedSubaccount
                      ? `The ${selected.currency} purchase cost will be converted to ${selectedSubaccount.currency} when saved.`
                      : "Choose a funding wallet."}
                </p>
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
                disabled={
                  saving ||
                  !selected ||
                  eligibleAccounts.length === 0 ||
                  !selectedSubaccount ||
                  !quantity ||
                  !averageCost
                }
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
