import { useState } from "react";
import { ArrowUpRight, Building2, Clock3, Info, Plus, RefreshCw } from "lucide-react";
import { ApiError, api } from "../api";
import { AccountDialog } from "./AccountDialog";
import { AddHoldingDialog } from "./AddHoldingDialog";
import { amount, assetLabel, number } from "../format";
import type { Currency, Dashboard } from "../types";

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
  const [refreshing, setRefreshing] = useState(false);
  const [marketError, setMarketError] = useState("");
  const [marketMessage, setMarketMessage] = useState("");

  async function refreshMarketData() {
    setRefreshing(true);
    setMarketError("");
    setMarketMessage("");
    try {
      const result = await api.refreshMarketData();
      setMarketMessage(
        `Updated ${result.updated_symbols.length} holding quote(s) and ${result.updated_fx_pairs.length} FX pair(s).`,
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
          label="Invested assets"
          value={amount(data.totals.invested_assets, currency)}
          detail="Latest available market marks"
        />
        <Metric
          label="Unrealized gain estimate"
          value={amount(data.totals.unrealized_pnl_estimate, currency)}
          detail="Based on saved average cost"
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
                  <strong>{amount(account.cash_balance, account.currency, 2)}</strong>
                  <small>Cash balance · {account.position_count} positions</small>
                </span>
                <span className={`status-pill ${account.is_sample ? "status-planned" : "status-confirmed"}`}>
                  {account.is_sample ? "Sample" : "Manual"}
                </span>
              </article>
            ))}
          </div>
        ) : (
          <p className="account-empty">No accounts yet. Add a brokerage account to track investments.</p>
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
                <th className="align-right">Market value</th>
                <th className="align-right">Since refresh</th>
                <th className="align-right">Gain vs. cost</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((holding, index) => (
                <tr key={`${holding.symbol}-${holding.account_name}-${index}`}>
                  <td>
                    <div className="instrument-cell">
                      <span className={`ticker-avatar ticker-${holding.asset_class}`}>{holding.symbol.slice(0, 2)}</span>
                      <span>
                        <strong>{holding.name}</strong>
                        <small>{holding.symbol} · {holding.instrument_type} · {holding.price_currency}</small>
                      </span>
                    </div>
                  </td>
                  <td className="muted-cell">{holding.account_name}</td>
                  <td><span className={`asset-tag asset-${holding.asset_class}`}>{assetLabel(holding.asset_class)}</span></td>
                  <td className="align-right tabular">{number(holding.quantity, 4)}</td>
                  <td className="align-right tabular">
                    <span>{amount(holding.price, holding.price_currency, 2)}</span>
                    <small className="quote-timestamp">
                      {holding.is_market_open === false ? "Market closed · " : ""}
                      {holding.quote_source === "TWELVE_DATA" ? "Twelve Data · " : "Sample · "}
                      {timestamp(holding.quote_observed_at)}
                    </small>
                  </td>
                  <td className="align-right tabular strong-cell">{amount(holding.market_value, currency)}</td>
                  <td className={`align-right tabular ${holding.change_since_refresh_percent === null ? "" : Number(holding.change_since_refresh_percent) >= 0 ? "positive-text" : "negative-text"}`}>
                    {holding.change_since_refresh_percent === null
                      ? "—"
                      : `${Number(holding.change_since_refresh_percent) >= 0 ? "+" : ""}${Number(holding.change_since_refresh_percent).toFixed(2)}%`}
                  </td>
                  <td className={`align-right tabular ${Number(holding.change_percent) >= 0 ? "positive-text" : "negative-text"}`}>
                    {Number(holding.change_percent) >= 0 ? "+" : ""}{Number(holding.change_percent).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-note">
          <Clock3 size={15} />
          <span>
            Provider quote times and plan latency apply. Refresh is manual only; no hourly job or
            background polling runs.
          </span>
        </div>
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
      {holdingDialogOpen && (
        <AddHoldingDialog
          accounts={data.accounts}
          marketDataConfigured={data.market_data_provider_configured}
          onClose={() => setHoldingDialogOpen(false)}
          onCreated={onSaved}
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
