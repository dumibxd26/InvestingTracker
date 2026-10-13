import { useEffect, useState, type FormEvent } from "react";
import { Building2, Plus, Search, Trash2, WalletCards, X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount, convertAmount } from "../format";
import type {
  AccountType,
  Currency,
  InitialPortfolioAccountPayload,
  InitialPortfolioHoldingPayload,
  MarketFxRate,
  MarketSymbol,
} from "../types";

interface InitialPortfolioDialogProps {
  baseCurrency: Currency;
  marketDataConfigured: boolean;
  marketFxRates: MarketFxRate[];
  usdPerEur: string | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

interface WalletDraft {
  id: string;
  currency: Currency;
  openingBalance: string;
}

interface AccountDraft {
  id: string;
  name: string;
  provider: string;
  type: AccountType;
  wallets: WalletDraft[];
}

interface HoldingDraft {
  id: string;
  accountIndex: number;
  instrument: MarketSymbol | null;
  quantity: string;
  averageCost: string;
  averageCostCurrency: Currency | null;
  purchaseDate: string;
}

const currencies: Currency[] = ["EUR", "USD", "RON"];
const providerChoices = [
  ["MANUAL", "Manual entry"],
  ["INTERACTIVE_BROKERS", "Interactive Brokers"],
  ["TRADE_REPUBLIC", "Trade Republic"],
  ["XTB", "XTB"],
  ["CHARLES_SCHWAB", "Charles Schwab"],
  ["OTHER", "Other"],
] as const;

const currencyLabels: Record<Currency, string> = {
  EUR: "EUR · Euro",
  USD: "USD · US dollar",
  RON: "RON · Romanian leu",
};

const accountTypeLabels: Record<AccountType, string> = {
  BROKERAGE: "Brokerage",
  BANK: "Bank",
  SAVINGS: "Savings",
  EMPLOYER_PLAN: "Employer plan",
};

function createWallet(currency: Currency): WalletDraft {
  return { id: crypto.randomUUID(), currency, openingBalance: "0" };
}

function createAccount(currency: Currency): AccountDraft {
  return {
    id: crypto.randomUUID(),
    name: "",
    provider: "MANUAL",
    type: "BROKERAGE",
    wallets: [createWallet(currency)],
  };
}

function createHolding(accounts: AccountDraft[]): HoldingDraft {
  const firstBroker = accounts.findIndex(
    (account) => account.type !== "SAVINGS",
  );
  return {
    id: crypto.randomUUID(),
    accountIndex: Math.max(0, firstBroker),
    instrument: null,
    quantity: "",
    averageCost: "",
    averageCostCurrency: null,
    purchaseDate: "2025-01-01",
  };
}

export function InitialPortfolioDialog({
  baseCurrency,
  marketDataConfigured,
  marketFxRates,
  usdPerEur,
  onClose,
  onCreated,
}: InitialPortfolioDialogProps) {
  const [accounts, setAccounts] = useState<AccountDraft[]>([createAccount(baseCurrency)]);
  const [holdings, setHoldings] = useState<HoldingDraft[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function updateAccount(accountId: string, update: Partial<AccountDraft>) {
    setAccounts((current) =>
      current.map((account) => (account.id === accountId ? { ...account, ...update } : account)),
    );
  }

  function updateWallet(accountId: string, walletId: string, update: Partial<WalletDraft>) {
    setAccounts((current) =>
      current.map((account) =>
        account.id === accountId
          ? {
              ...account,
              wallets: account.wallets.map((wallet) =>
                wallet.id === walletId ? { ...wallet, ...update } : wallet,
              ),
            }
          : account,
      ),
    );
  }

  function addAccount() {
    if (accounts.length >= 20) return;
    setAccounts((current) => [...current, createAccount(baseCurrency)]);
  }

  function addWallet(account: AccountDraft, currency: Currency) {
    if (account.wallets.length >= currencies.length) return;
    updateAccount(account.id, { wallets: [...account.wallets, createWallet(currency)] });
  }

  function addHolding() {
    if (holdings.length >= 50) return;
    setHoldings((current) => [...current, createHolding(accounts)]);
  }

  function updateHolding(holdingId: string, update: Partial<HoldingDraft>) {
    setHoldings((current) =>
      current.map((holding) => (holding.id === holdingId ? { ...holding, ...update } : holding)),
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const invalidAccount = accounts.find(
      (account) => account.name.trim().length < 2 || account.wallets.length === 0,
    );
    if (invalidAccount) {
      setError("Give every account a name and at least one currency balance.");
      return;
    }
    if (accounts.some((account) => account.type === "EMPLOYER_PLAN" && account.wallets.some((wallet) => Number(wallet.openingBalance) > 0))) {
      setError("Employer-plan accounts cannot have cash balances. Add those shares as holdings instead.");
      return;
    }
    if (holdings.some((holding) => !holding.instrument || !holding.quantity || !holding.averageCost)) {
      setError("Choose an instrument and enter the share quantity and average cost for every holding.");
      return;
    }
    if (holdings.some((holding) => !holding.averageCostCurrency)) {
      setError("Choose the currency used for each average cost.");
      return;
    }
    for (const holding of holdings) {
      const account = accounts[holding.accountIndex];
      if (
        !account ||
        account.type === "SAVINGS"
      ) {
        setError("Every stock or ETF must be assigned to a brokerage, bank, or employer-plan account.");
        return;
      }
    }
    setSaving(true);
    const accountPayload: InitialPortfolioAccountPayload[] = accounts.map((account) => ({
      display_name: account.name.trim(),
      provider_code: account.provider,
      account_type: account.type,
      subaccounts: account.wallets.map((wallet) => ({
        currency: wallet.currency,
        opening_balance: wallet.openingBalance || "0",
      })),
    }));
    const holdingPayload: InitialPortfolioHoldingPayload[] = holdings.map((holding) => ({
      account_index: holding.accountIndex,
      symbol: holding.instrument!.symbol,
      mic_code: holding.instrument!.mic_code,
      exchange: holding.instrument!.exchange,
      instrument_type: holding.instrument!.instrument_type,
      quantity: holding.quantity,
      average_cost: holding.averageCost,
      average_cost_currency: holding.averageCostCurrency!,
      purchase_date: holding.purchaseDate,
    }));
    try {
      await api.initializePortfolio(accountPayload, holdingPayload);
      await onCreated();
      onClose();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The initial portfolio could not be saved. No changes were made.",
      );
    } finally {
      setSaving(false);
    }
  }

  const stockAccounts = accounts
    .map((account, index) => ({ account, index }))
    .filter(({ account }) => account.type !== "SAVINGS");

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}
    >
      <section
        className="modal-card initial-portfolio-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="initial-portfolio-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">One guided setup · saved together</div>
            <h2 id="initial-portfolio-title">Set up your portfolio</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={saving}
          >
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Add your banks and brokers, enter opening balances for each currency, then list the
          positions you already own. This records your current portfolio in Northstar; it does not
          connect to institutions or submit trades.
        </p>
        <form className="initial-portfolio-form" onSubmit={submit}>
          <section className="setup-section">
            <div className="setup-section-heading">
              <div>
                <div className="eyebrow">Step 1</div>
                <h3>Accounts and cash</h3>
              </div>
              <button
                className="button button-secondary button-small"
                type="button"
                onClick={addAccount}
                disabled={accounts.length >= 20 || saving}
              >
                <Plus size={14} /> Add institution
              </button>
            </div>
            <div className="setup-account-list">
              {accounts.map((account, accountIndex) => {
                const availableCurrencies = currencies.filter(
                  (currency) => !account.wallets.some((wallet) => wallet.currency === currency),
                );
                return (
                  <article className="setup-account-card" key={account.id}>
                    <div className="setup-account-title">
                      <span className="setup-account-number">{accountIndex + 1}</span>
                      <strong>Institution</strong>
                      {accounts.length > 1 && (
                        <button
                          className="icon-button small setup-remove-button"
                          type="button"
                          aria-label={`Remove account ${accountIndex + 1}`}
                          onClick={() => {
                            setAccounts((current) => current.filter((item) => item.id !== account.id));
                            setHoldings((current) =>
                              current
                                .filter((holding) => holding.accountIndex !== accountIndex)
                                .map((holding) => ({
                                  ...holding,
                                  accountIndex:
                                    holding.accountIndex > accountIndex
                                      ? holding.accountIndex - 1
                                      : holding.accountIndex,
                                })),
                            );
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                    <div className="form-row">
                      <label className="form-field">
                        <span>Account name</span>
                        <input
                          value={account.name}
                          onChange={(event) => updateAccount(account.id, { name: event.target.value })}
                          required
                          minLength={2}
                          maxLength={80}
                          placeholder="e.g. Main brokerage"
                        />
                      </label>
                      <label className="form-field">
                        <span>Account type</span>
                        <select
                          value={account.type}
                          onChange={(event) =>
                            updateAccount(account.id, { type: event.target.value as AccountType })
                          }
                        >
                          {Object.entries(accountTypeLabels).map(([value, label]) => (
                            <option key={value} value={value}>{label}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="form-row">
                      <label className="form-field">
                        <span>Institution/provider</span>
                        <select
                          value={account.provider}
                          onChange={(event) => updateAccount(account.id, { provider: event.target.value })}
                        >
                          {providerChoices.map(([value, label]) => (
                            <option key={value} value={value}>{label}</option>
                          ))}
                        </select>
                      </label>
                      <div className="setup-wallets">
                        <div className="setup-wallet-heading">
                          <span>Opening currency balances</span>
                          {availableCurrencies.length > 0 && (
                            <select
                              aria-label={`Add currency balance to ${account.name || `account ${accountIndex + 1}`}`}
                              value=""
                              onChange={(event) => {
                                if (event.target.value) {
                                  addWallet(account, event.target.value as Currency);
                                }
                              }}
                            >
                              <option value="">Add currency</option>
                              {availableCurrencies.map((currency) => (
                                <option value={currency} key={currency}>{currencyLabels[currency]}</option>
                              ))}
                            </select>
                          )}
                        </div>
                        {account.wallets.map((wallet, walletIndex) => (
                          <div className="setup-wallet-block" key={wallet.id}>
                            <label className="setup-wallet-row">
                              <span>{wallet.currency}{walletIndex === 0 ? " · primary" : ""}</span>
                              <input
                                type="number"
                                min="0"
                                max="100000000"
                                step="0.01"
                                value={wallet.openingBalance}
                                onChange={(event) =>
                                  updateWallet(account.id, wallet.id, { openingBalance: event.target.value })
                                }
                                aria-label={`${wallet.currency} opening balance`}
                                disabled={account.type === "EMPLOYER_PLAN"}
                              />
                              {walletIndex > 0 && (
                                <button
                                  className="icon-button small setup-remove-button"
                                  type="button"
                                  aria-label={`Remove ${wallet.currency} balance`}
                                  onClick={() =>
                                    updateAccount(account.id, {
                                      wallets: account.wallets.filter((item) => item.id !== wallet.id),
                                    })
                                  }
                                >
                                  <X size={13} />
                                </button>
                              )}
                            </label>
                          </div>
                        ))}
                        {account.type === "EMPLOYER_PLAN" && (
                          <small className="setup-help-text">Employer plan balances are represented by holdings, not cash.</small>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="setup-section">
            <div className="setup-section-heading">
              <div>
                <div className="eyebrow">Step 2 · optional</div>
                <h3>Stocks and ETFs you already own</h3>
              </div>
              <button
                className="button button-secondary button-small"
                type="button"
                onClick={addHolding}
                disabled={
                  holdings.length >= 50 ||
                  saving ||
                  stockAccounts.length === 0 ||
                  !marketDataConfigured
                }
              >
                <Plus size={14} /> Add position
              </button>
            </div>
            {!marketDataConfigured && (
              <div className="setup-market-note">
                <InfoIcon />
                <span>
                  Accounts can be entered now. To add stock/ETF positions, configure Twelve Data.
                  Foreign-currency opening balances also need a usable FX rate, such as a saved
                  USD-per-EUR reference or a provider rate.
                </span>
              </div>
            )}
            {stockAccounts.length === 0 && (
              <p className="quiet-copy">Add a brokerage or employer-plan account to include owned shares.</p>
            )}
            {holdings.length === 0 && stockAccounts.length > 0 && (
              <p className="quiet-copy">No positions to add yet. Add them now or do it later from the Portfolio page.</p>
            )}
            <div className="setup-holding-list">
              {holdings.map((holding) => (
                <InitialHoldingRow
                  key={holding.id}
                  holding={holding}
                  accounts={accounts}
                  marketFxRates={marketFxRates}
                  usdPerEur={usdPerEur}
                  onChange={(update) => updateHolding(holding.id, update)}
                  onRemove={() => setHoldings((current) => current.filter((item) => item.id !== holding.id))}
                  disabled={!marketDataConfigured || saving}
                />
              ))}
            </div>
          </section>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="initial-setup-disclaimer">
            <WalletCards size={15} />
            <span>
              These are your current balances and existing holdings; adding a holding here does
              not spend the cash a second time. Average costs are stored in the listing currency.
            </span>
          </div>
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button className="button button-primary" type="submit" disabled={saving}>
              <Building2 size={15} />
              {saving ? "Saving portfolio…" : "Save initial portfolio"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

interface InitialHoldingRowProps {
  holding: HoldingDraft;
  accounts: AccountDraft[];
  marketFxRates: MarketFxRate[];
  usdPerEur: string | null;
  onChange: (update: Partial<HoldingDraft>) => void;
  onRemove: () => void;
  disabled: boolean;
}

function InitialHoldingRow({
  holding,
  accounts,
  marketFxRates,
  usdPerEur,
  onChange,
  onRemove,
  disabled,
}: InitialHoldingRowProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSymbol[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const availableAccounts = accounts
    .map((account, index) => ({ account, index }))
    .filter(({ account }) => account.type !== "SAVINGS");
  const normalizedAverageCost =
    holding.instrument && holding.averageCost && holding.averageCostCurrency
      ? convertAmount(
          holding.averageCost,
          holding.averageCostCurrency,
          holding.instrument.currency,
          marketFxRates,
          usdPerEur,
        )
      : null;

  useEffect(() => {
    const normalized = query.trim();
    if (disabled || normalized.length < 2 || holding.instrument) {
      setResults([]);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      setSearchError("");
      void api.searchSymbols(normalized, controller.signal)
        .then((response) => setResults(response.results))
        .catch((cause) => {
          if (!controller.signal.aborted) {
            setResults([]);
            setSearchError(cause instanceof ApiError ? cause.message : "Symbol lookup failed.");
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [disabled, holding.instrument, query]);

  return (
    <article className="setup-holding-row">
      <div className="setup-holding-topline">
        <strong>Owned position</strong>
        <button className="icon-button small setup-remove-button" type="button" aria-label="Remove position" onClick={onRemove}>
          <Trash2 size={14} />
        </button>
      </div>
      <label className="form-field">
        <span>Search by company or ticker</span>
        <div className="market-search-input">
          <Search size={15} aria-hidden="true" />
          <input
            value={holding.instrument ? `${holding.instrument.symbol} · ${holding.instrument.name}` : query}
            onChange={(event) => {
              onChange({ instrument: null });
              setQuery(event.target.value);
            }}
            placeholder="e.g. Microsoft or MSFT"
            disabled={disabled}
          />
          {holding.instrument && (
            <button
              className="icon-button small"
              type="button"
              aria-label="Clear selected investment"
              onClick={() => {
                onChange({ instrument: null });
                setQuery("");
              }}
            >
              <X size={13} />
            </button>
          )}
        </div>
      </label>
      {searching && <p className="quiet-copy" role="status">Searching market listings…</p>}
      {results.length > 0 && !holding.instrument && (
        <div className="market-search-results" role="listbox" aria-label="Matching stocks and ETFs">
          {results.map((result) => (
            <button
              className="market-search-result"
              type="button"
              key={`${result.symbol}-${result.mic_code ?? result.exchange}`}
              onClick={() => {
                onChange({
                  instrument: result,
                  averageCostCurrency: result.currency,
                });
                setQuery("");
                setResults([]);
                if (availableAccounts[0]) {
                  onChange({
                    instrument: result,
                    accountIndex: availableAccounts[0].index,
                  });
                }
              }}
            >
              <span className="market-result-symbol">{result.symbol}</span>
              <span className="market-result-details">
                <strong>{result.name}</strong>
                <small>{result.exchange} · {result.instrument_type} · {result.currency}</small>
              </span>
            </button>
          ))}
        </div>
      )}
      {searchError && <div className="inline-error" role="alert">{searchError}</div>}
      {holding.instrument && (
        <>
          <div className="form-row">
            <label className="form-field">
              <span>Brokerage / employer account</span>
              <select
                value={holding.accountIndex}
                onChange={(event) => {
                  const accountIndex = Number(event.target.value);
                  onChange({ accountIndex });
                }}
                disabled={disabled}
              >
                {availableAccounts.map(({ account, index }) => (
                  <option value={index} key={account.id}>{account.name || `Account ${index + 1}`}</option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Number of shares</span>
              <input
                type="number"
                min="0.00000001"
                max="1000000000"
                step="any"
                value={holding.quantity}
                onChange={(event) => onChange({ quantity: event.target.value })}
                required
              />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Average cost per share</span>
              <div className="average-cost-input">
                <input
                  type="number"
                  min="0.00000001"
                  max="100000000"
                  step="any"
                  value={holding.averageCost}
                  onChange={(event) => onChange({ averageCost: event.target.value })}
                  required
                />
                <select
                  aria-label="Average cost currency"
                  value={holding.averageCostCurrency ?? holding.instrument.currency}
                  onChange={(event) =>
                    onChange({ averageCostCurrency: event.target.value as Currency })
                  }
                >
                  {currencies.map((currency) => (
                    <option value={currency} key={currency}>{currency}</option>
                  ))}
                </select>
              </div>
            </label>
            <div className="initial-funding-indicator">
              <small>Cost basis shown in listing currency ({holding.instrument.currency})</small>
              <strong>
                {normalizedAverageCost !== null
                  ? amount(String(normalizedAverageCost), holding.instrument.currency, 4)
                  : "FX rate resolved when saved"}
              </strong>
            </div>
          </div>
          <label className="form-field">
            <span>Purchase date <small>defaults to 1 Jan 2025</small></span>
            <input
              type="date"
              value={holding.purchaseDate}
              onChange={(event) => onChange({ purchaseDate: event.target.value })}
              required
              disabled={disabled}
            />
          </label>
        </>
      )}
    </article>
  );
}

function InfoIcon() {
  return <span className="market-status-dot" aria-hidden="true" />;
}
