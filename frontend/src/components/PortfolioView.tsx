import { useState } from "react";
import {
  ArrowUpRight,
  Building2,
  CircleDollarSign,
  Clock3,
  Info,
  Pencil,
  Percent,
  Plus,
  Landmark,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { ApiError, api } from "../api";
import { AccountDialog } from "./AccountDialog";
import { AddDepositDialog } from "./AddDepositDialog";
import { AddHoldingDialog } from "./AddHoldingDialog";
import { AddSubaccountDialog } from "./AddSubaccountDialog";
import { EditHoldingDialog } from "./EditHoldingDialog";
import { ExtraCashDialog } from "./ExtraCashDialog";
import { InitialPortfolioDialog } from "./InitialPortfolioDialog";
import { SavingsInterestDialog } from "./SavingsInterestDialog";
import { amount, assetLabel, dateLabel, number } from "../format";
import type { AccountSummary, Currency, Dashboard, HoldingSummary } from "../types";

interface PortfolioViewProps {
  data: Dashboard;
  currency: Currency;
  onSaved: () => Promise<void>;
}

const accountTypeLabels = {
  BROKERAGE: "Brokerage",
  BANK: "Bank account",
  SAVINGS: "Savings / deposit",
  EMPLOYER_PLAN: "Employer plan",
} as const;

const providerLabels: Record<string, string> = {
  MANUAL: "Manual entry",
  INTERACTIVE_BROKERS: "Interactive Brokers",
  TRADE_REPUBLIC: "Trade Republic",
  XTB: "XTB",
  CHARLES_SCHWAB: "Charles Schwab",
  OTHER: "Other",
  SAMPLE: "Sample data",
};

function timestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Time unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

export function PortfolioView({ data, currency, onSaved }: PortfolioViewProps) {
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [holdingDialogOpen, setHoldingDialogOpen] = useState(false);
  const [initialSetupOpen, setInitialSetupOpen] = useState(false);
  const [addingSubaccountFor, setAddingSubaccountFor] = useState<AccountSummary | null>(null);
  const [addingDepositFor, setAddingDepositFor] = useState<AccountSummary | null>(null);
  const [addingFundsFor, setAddingFundsFor] = useState<AccountSummary | null>(null);
  const [editingInterestFor, setEditingInterestFor] = useState<AccountSummary | null>(null);
  const [deletingDepositId, setDeletingDepositId] = useState<string | null>(null);
  const [editingHolding, setEditingHolding] = useState<HoldingSummary | null>(null);
  const [mutatingHoldingId, setMutatingHoldingId] = useState<string | null>(null);
  const [mutatingAccountId, setMutatingAccountId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [marketError, setMarketError] = useState("");
  const [marketMessage, setMarketMessage] = useState("");
  const [holdingError, setHoldingError] = useState("");
  const [holdingMessage, setHoldingMessage] = useState("");
  const [accountError, setAccountError] = useState("");
  const [accountMessage, setAccountMessage] = useState("");
  const [depositError, setDepositError] = useState("");
  const [depositMessage, setDepositMessage] = useState("");

  async function refreshMarketData() {
    setRefreshing(true);
    setMarketError("");
    setMarketMessage("");
    try {
      const result = await api.refreshMarketData();
      setMarketMessage(
        `Updated ${result.updated_symbols.length} holding or grant quote(s) and ${result.updated_fx_pairs.length} FX pair(s).`,
      );
      if (result.errors.length) setMarketError(result.errors.join(" "));
      await onSaved();
    } catch (cause) {
      setMarketError(
        cause instanceof ApiError ? cause.message : "Market data could not be refreshed.",
      );
    } finally {
      setRefreshing(false);
    }
  }

  async function deleteHolding(holding: HoldingSummary) {
    if (
      !window.confirm(
        holding.funding_currency
          ? `Remove ${holding.quantity} shares of ${holding.symbol} from ${holding.account_name} and restore ${amount(holding.funding_cost, holding.funding_currency, 2)} to its ${holding.funding_currency} funding wallet?\n\nThis is a bookkeeping reversal at recorded acquisition cost, not a market-price sale, and does not affect your actual brokerage account.`
          : `Remove the imported ${holding.quantity} shares of ${holding.symbol} from ${holding.account_name}?\n\nThis removes only the holding record; it does not change the account's current cash balance or your actual brokerage account.`,
      )
    ) {
      return;
    }
    setMutatingHoldingId(holding.id);
    setHoldingError("");
    setHoldingMessage("");
    try {
      await api.deleteHolding(holding.id);
      await onSaved();
      setHoldingMessage(`${holding.symbol} position removed from this tracker.`);
    } catch (cause) {
      setHoldingError(
        cause instanceof ApiError ? cause.message : "The holding could not be deleted.",
      );
    } finally {
      setMutatingHoldingId(null);
    }
  }

  async function deleteAccount(account: AccountSummary) {
    if (account.is_sample) return;
    const balances = account.subaccounts
      .map((subaccount) => `${amount(subaccount.cash_balance, subaccount.currency, 2)}${subaccount.is_primary ? " (primary)" : ""}`)
      .join(", ");
    if (
      !window.confirm(
        `Remove "${account.display_name}" (${account.account_type}) and its currency balances (${balances}) from Northstar?\n\nAny stocks/ETFs and fixed deposits attached to it will also be removed from this tracker. Active automatic salary/bonus schedules for this account will stop. Cash-flow history will be kept but detached from this account. This does not change your actual bank or broker account.`,
      )
    ) {
      return;
    }
    setMutatingAccountId(account.id);
    setAccountError("");
    setAccountMessage("");
    try {
      await api.deleteAccount(account.id);
      await onSaved();
      setAccountMessage(`"${account.display_name}" was removed from this tracker.`);
    } catch (cause) {
      setAccountError(
        cause instanceof ApiError ? cause.message : "The account could not be deleted.",
      );
    } finally {
      setMutatingAccountId(null);
    }
  }

  async function deleteDeposit(depositId: string, depositName: string) {
    if (!window.confirm(`Remove “${depositName}” from this tracker and restore its principal to the source wallet? Interest is an estimate and will not be credited.`)) {
      return;
    }
    setDeletingDepositId(depositId);
    setDepositError("");
    setDepositMessage("");
    try {
      await api.deleteDeposit(depositId);
      await onSaved();
      setDepositMessage(`“${depositName}” was removed from the tracker.`);
    } catch (cause) {
      setDepositError(cause instanceof ApiError ? cause.message : "The deposit could not be removed.");
    } finally {
      setDeletingDepositId(null);
    }
  }

  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Positions & exposure</div>
          <h1>Your portfolio.</h1>
          <p>Track brokerage positions and manually refresh quotes and EUR, USD, and RON FX rates.</p>
        </div>
        <div className="portfolio-actions">
          <button
            className={data.accounts.length === 0 ? "button button-primary" : "button button-secondary"}
            type="button"
            onClick={() => setInitialSetupOpen(true)}
          >
            <Building2 size={16} />
            {data.accounts.length === 0 ? "Set up your portfolio" : "Quick portfolio setup"}
          </button>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => setAccountDialogOpen(true)}
          >
            <Plus size={16} /> Add an account
          </button>
          <button
            className="button button-primary"
            type="button"
            onClick={() => setHoldingDialogOpen(true)}
            title={
              data.market_data_provider_configured
                ? "Search the configured market-data provider"
                : "Configure TWELVE_DATA_API_KEY in .env first"
            }
          >
            <Plus size={16} /> Add stock or ETF
          </button>
        </div>
      </div>
      <div className="metric-grid portfolio-metrics">
        <Metric
          label="Invested assets · estimated after-tax"
          value={amount(data.totals.invested_assets, currency)}
          detail="After 3% tax estimate on positive gain"
        />
        <Metric
          label="Available cash"
          value={amount(data.totals.available_cash, currency)}
          detail="Across tracked accounts"
        />
        <Metric
          label="Monthly income estimate"
          value={amount(data.totals.estimated_monthly_income, currency)}
          detail="Gross indicated income"
        />
      </div>
      <section className="panel market-control-panel">
        <div className="market-control-copy">
          <span className={`market-status-dot ${data.market_data_provider_configured ? "is-ready" : ""}`} />
          <div>
            <div className="eyebrow">Market data · {data.market_data_provider_configured ? "configured" : "not configured"}</div>
            <strong>{data.market_data_provider_configured ? "Twelve Data is ready" : "Provider API key required"}</strong>
            <small>
              {data.market_data_provider_configured
                ? "Quotes and FX update only when you request a refresh. Hourly automatic refresh is off."
                : "Set TWELVE_DATA_API_KEY in the project .env file and restart the backend."}
            </small>
          </div>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => void refreshMarketData()}
          disabled={!data.market_data_provider_configured || refreshing}
        >
          <RefreshCw size={15} className={refreshing ? "spin-icon" : ""} />
          {refreshing ? "Refreshing…" : "Refresh quotes & FX"}
        </button>
      </section>
      {marketMessage && <div className="market-feedback" role="status">{marketMessage}</div>}
      {marketError && <div className="inline-error market-feedback" role="alert">{marketError}</div>}
      {holdingMessage && <div className="market-feedback" role="status">{holdingMessage}</div>}
      {holdingError && <div className="inline-error market-feedback" role="alert">{holdingError}</div>}
      {accountMessage && <div className="market-feedback" role="status">{accountMessage}</div>}
      {accountError && <div className="inline-error market-feedback" role="alert">{accountError}</div>}
      {depositMessage && <div className="market-feedback" role="status">{depositMessage}</div>}
      {depositError && <div className="inline-error market-feedback" role="alert">{depositError}</div>}

      <section className="panel account-list-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">Accounts</div>
            <h2>{data.accounts.length} tracked accounts</h2>
          </div>
          <span className="panel-kicker">Balances persist in PostgreSQL</span>
        </div>
        {data.accounts.length > 0 ? (
          <div className="account-card-grid">
            {data.accounts.map((account) => (
              <article className="account-card" key={account.id}>
                <span className={`account-card-icon ${account.is_sample ? "account-sample-icon" : ""}`}>
                  <Building2 size={17} />
                </span>
                <span className="account-card-copy">
                  <strong>{account.display_name}</strong>
                  <small>
                    {providerLabels[account.provider_code] ?? account.provider_code} ·{" "}
                    {accountTypeLabels[account.account_type]}
                  </small>
                </span>
                <span className="account-card-balance">
                  {account.subaccounts.map((subaccount) => (
                    <strong key={subaccount.id}>
                      {subaccount.currency} {amount(subaccount.cash_balance, subaccount.currency, 2)}
                      {subaccount.is_primary ? " · primary" : ""}
                      {subaccount.annual_interest_rate
                        ? ` · ${(Number(subaccount.annual_interest_rate) * 100).toFixed(2)}%/yr monthly`
                        : ""}
                    </strong>
                  ))}
                  {data.deposits.filter((deposit) => deposit.account_id === account.id).map((deposit) => (
                    <span className="account-deposit-balance" key={deposit.id}>
                      <strong>Deposit · {amount(deposit.current_value, deposit.currency, 2)}</strong>
                      <small>{deposit.name} · matures {dateLabel(deposit.maturity_date, { month: "short", year: "numeric" })}</small>
                      <button
                        className="icon-button small account-delete-button"
                        type="button"
                        aria-label={`Remove deposit ${deposit.name}`}
                        title="Remove deposit and restore its principal"
                        onClick={() => void deleteDeposit(deposit.id, deposit.name)}
                        disabled={deletingDepositId === deposit.id}
                      >
                        <Trash2 size={13} />
                      </button>
                    </span>
                  ))}
                  <small>{account.subaccounts.length} currency wallet(s) · {account.position_count} positions</small>
                </span>
                <span className="account-card-actions">
                  {account.account_type !== "EMPLOYER_PLAN" && (
                    <button
                      className="button button-quiet button-small"
                      type="button"
                      onClick={() => setAddingFundsFor(account)}
                      disabled={account.is_sample || account.subaccounts.length === 0}
                      title="Record a bonus, refund, or other money received into this account"
                    >
                      <CircleDollarSign size={13} /> Add funds
                    </button>
                  )}
                  {account.account_type !== "EMPLOYER_PLAN" && (
                    <button
                      className="button button-quiet button-small"
                      type="button"
                      onClick={() => setEditingInterestFor(account)}
                      disabled={account.is_sample || account.subaccounts.length === 0}
                      title="Set a yearly interest rate credited monthly"
                    >
                      <Percent size={13} /> Interest
                    </button>
                  )}
                  <button
                    className="button button-quiet button-small"
                    type="button"
                    aria-label={`Add a currency sub-account to ${account.display_name}`}
                    title={account.subaccounts.length >= 3
                      ? "This account already has EUR, USD, and RON wallets"
                      : "Add a EUR, USD, or RON wallet to this account"}
                    onClick={() => setAddingSubaccountFor(account)}
                    disabled={account.is_sample || account.subaccounts.length >= 3}
                  >
                    <Plus size={13} /> Currency
                  </button>
                  {(account.account_type === "BANK" || account.account_type === "SAVINGS") && (
                    <button
                      className="button button-quiet button-small"
                      type="button"
                      onClick={() => setAddingDepositFor(account)}
                      disabled={account.is_sample || account.subaccounts.length === 0}
                      title={account.subaccounts.length
                        ? "Add a fixed deposit funded from one of this account's wallets"
                        : "Add a currency wallet first"}
                    >
                      <Landmark size={13} /> Deposit
                    </button>
                  )}
                  <span className={`status-pill ${account.is_sample ? "status-planned" : "status-confirmed"}`}>
                    {account.is_sample ? "Sample" : "Manual"}
                  </span>
                  <button
                    className="icon-button small account-delete-button"
                    type="button"
                    aria-label={`Remove ${account.display_name}`}
                    title={
                      account.is_sample
                        ? "Legacy sample accounts cannot be deleted"
                        : "Remove this account from Northstar"
                    }
                    onClick={() => void deleteAccount(account)}
                    disabled={account.is_sample || mutatingAccountId === account.id}
                  >
                    <Trash2 size={14} />
                  </button>
                </span>
              </article>
            ))}
          </div>
        ) : (
          <p className="account-empty">No accounts yet. Add a brokerage account to track investments.</p>
        )}

        {addingDepositFor && (
          <AddDepositDialog
            account={addingDepositFor}
            onClose={() => setAddingDepositFor(null)}
            onCreated={onSaved}
          />
        )}
      </section>

      {data.market_fx_rates.length > 0 && (
        <section className="panel fx-rates-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">Foreign exchange</div>
              <h2>Latest provider rates</h2>
            </div>
            <span className="panel-kicker">Timestamps are supplied by the provider</span>
          </div>
          <div className="fx-rate-grid">
            {data.market_fx_rates.map((rate) => (
              <article className="fx-rate-card" key={`${rate.base_currency}-${rate.quote_currency}`}>
                <span>
                  <strong>{rate.base_currency} / {rate.quote_currency}</strong>
                  <small>1 {rate.base_currency} = {number(rate.rate, 5)} {rate.quote_currency}</small>
                </span>
                <span className="fx-rate-meta">
                  {rate.change_percent !== null && (
                    <strong className={Number(rate.change_percent) >= 0 ? "positive-text" : "negative-text"}>
                      {Number(rate.change_percent) >= 0 ? "+" : ""}{Number(rate.change_percent).toFixed(2)}%
                    </strong>
                  )}
                  <small>{timestamp(rate.observed_at)}</small>
                </span>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">Holdings registry</div>
            <h2>Positions</h2>
          </div>
          <span className="table-count">{data.holdings.length} positions</span>
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Investment</th>
                <th>Account</th>
                <th>Asset class</th>
                <th className="align-right">Units</th>
                <th className="align-right">Latest quote</th>
                <th>Purchase date</th>
                <th className="align-right">Est. after-tax value</th>
                <th className="align-right">Since refresh</th>
                <th><span className="sr-only">Position actions</span></th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((holding) => (
                <tr key={holding.id}>
                  <td>
                    <div className="instrument-cell">
                      <span className={`ticker-avatar ticker-${holding.asset_class}`}>{holding.symbol.slice(0, 2)}</span>
                      <span>
                        <strong>{holding.name}</strong>
                        <small>{holding.symbol} · {holding.instrument_type} · {holding.price_currency}</small>
                      </span>
                    </div>
                  </td>
                  <td className="muted-cell">
                    {holding.account_name}
                    {holding.assigned_goal_name && (
                      <small className="quote-timestamp">Goal · {holding.assigned_goal_name}</small>
                    )}
                    {holding.funding_currency && (
                      <small className="quote-timestamp">
                        Paid from {holding.funding_currency} wallet · {amount(holding.funding_cost, holding.funding_currency, 2)}
                      </small>
                    )}
                  </td>
                  <td><span className={`asset-tag asset-${holding.asset_class}`}>{assetLabel(holding.asset_class)}</span></td>
                  <td className="align-right tabular">{number(holding.quantity, 4)}</td>
                  <td className="align-right tabular">
                    <span>{amount(holding.price, holding.price_currency, 2)}</span>
                    <small className="quote-timestamp">
                      {holding.is_market_open === false ? "Market closed · " : ""}
                      {holding.quote_source === "TWELVE_DATA"
                        ? "Twelve Data · "
                        : holding.quote_source === "XTB_SCREENSHOT"
                          ? "XTB screenshot mark · "
                          : "Sample · "}
                      {timestamp(holding.quote_observed_at)}
                    </small>
                  </td>
                  <td>{dateLabel(holding.purchase_date, { day: "numeric", month: "short", year: "numeric" })}</td>
                  <td className="align-right tabular strong-cell">
                    {amount(holding.market_value, currency)}
                    <small className="quote-timestamp">
                      Gross {amount(holding.gross_market_value, currency)} · est. tax {amount(holding.estimated_sale_tax, currency)} ({(Number(holding.estimated_tax_rate) * 100).toFixed(0)}% of positive gain)
                    </small>
                  </td>
                  <td className={`align-right tabular ${holding.change_since_refresh_percent === null ? "" : Number(holding.change_since_refresh_percent) >= 0 ? "positive-text" : "negative-text"}`}>
                    {holding.change_since_refresh_percent === null
                      ? "—"
                      : `${Number(holding.change_since_refresh_percent) >= 0 ? "+" : ""}${Number(holding.change_since_refresh_percent).toFixed(2)}%`}
                  </td>
                  <td className="holding-row-actions">
                    <button
                      className="icon-button small"
                      type="button"
                      aria-label={`Edit ${holding.symbol} position`}
                      title="Edit position"
                      onClick={() => setEditingHolding(holding)}
                      disabled={mutatingHoldingId === holding.id}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      className="icon-button small holding-delete-button"
                      type="button"
                      aria-label={`Delete ${holding.symbol} position`}
                      title="Delete position"
                      onClick={() => void deleteHolding(holding)}
                      disabled={mutatingHoldingId === holding.id}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-note">
          <Clock3 size={15} />
          <span>
            Estimated after-tax value subtracts 3% of positive gain over average cost. Purchase dates use the recorded position date; values are estimates, not tax advice. Provider quote times and plan latency apply; manual refresh only.
          </span>
        </div>
        {data.holdings.some((holding) => holding.quote_source === "XTB_SCREENSHOT") && (
          <div className="table-note screenshot-mark-note">
            <Info size={15} />
            <span>
              XTB screenshot marks were reconstructed from the shown account market values using
              locally cached FX. They are approximate historical imports; refresh quotes to replace
              them with provider data.
            </span>
          </div>
        )}
      </section>

      <section className="panel concentration-panel">
        <div className="concentration-icon"><ArrowUpRight size={19} /></div>
        <div>
          <div className="eyebrow">Connection status</div>
          <h2>Broker sync and statement imports are not connected.</h2>
          <p>
            Positions you add are saved in PostgreSQL and marked with market data from the configured
            provider. Account balances remain manual; no trades are placed.
          </p>
        </div>
        <span className="status-pill status-planned">Manual only</span>
      </section>
      <div className="table-note portfolio-disclaimer">
        <Info size={15} />
        <span>Market prices and FX are informational and may be delayed according to provider plan and listing.</span>
      </div>
      {accountDialogOpen && (
        <AccountDialog
          profile={data.profile}
          onClose={() => setAccountDialogOpen(false)}
          onCreated={onSaved}
        />
      )}
      {initialSetupOpen && (
        <InitialPortfolioDialog
          baseCurrency={data.base_currency}
          marketDataConfigured={data.market_data_provider_configured}
          marketFxRates={data.market_fx_rates}
          usdPerEur={data.profile.usd_per_eur}
          onClose={() => setInitialSetupOpen(false)}
          onCreated={onSaved}
        />
      )}
      {addingSubaccountFor && (
        <AddSubaccountDialog
          account={addingSubaccountFor}
          onClose={() => setAddingSubaccountFor(null)}
          onCreated={onSaved}
        />
      )}
      {addingFundsFor && (
        <ExtraCashDialog
          accounts={data.accounts}
          baseCurrency={data.base_currency}
          initialAccountId={addingFundsFor.id}
          onClose={() => setAddingFundsFor(null)}
          onSaved={onSaved}
        />
      )}
      {editingInterestFor && (
        <SavingsInterestDialog
          account={editingInterestFor}
          onClose={() => setEditingInterestFor(null)}
          onSaved={onSaved}
        />
      )}
      {holdingDialogOpen && (
        <AddHoldingDialog
          accounts={data.accounts}
          marketDataConfigured={data.market_data_provider_configured}
          marketFxRates={data.market_fx_rates}
          usdPerEur={data.profile.usd_per_eur}
          onClose={() => setHoldingDialogOpen(false)}
          onCreated={onSaved}
        />
      )}
      {editingHolding && (
        <EditHoldingDialog
          holding={editingHolding}
          onClose={() => setEditingHolding(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <section className="metric-card">
      <div className="metric-top"><span>{label}</span></div>
      <div className="metric-value metric-value-small">{value}</div>
      <div className="metric-foot"><span>{detail}</span></div>
    </section>
  );
}
