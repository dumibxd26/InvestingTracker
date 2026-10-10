import { ArrowUpRight, Info, Search } from "lucide-react";
import { amount, assetLabel, number } from "../format";
import type { Currency, Dashboard } from "../types";

export function PortfolioView({ data, currency }: { data: Dashboard; currency: Currency }) {
  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Positions & exposure</div>
          <h1>Your portfolio.</h1>
          <p>One view across the example brokerage accounts and asset classes.</p>
        </div>
        <button className="button button-secondary" type="button" disabled title="Broker imports are not connected in this prototype">
          <Search size={16} /> Connect an account
        </button>
      </div>
      <div className="metric-grid portfolio-metrics">
        <Metric label="Invested assets" value={amount(data.totals.invested_assets, currency)} detail="Quoted sample positions" />
        <Metric label="Unrealized gain estimate" value={amount(data.totals.unrealized_pnl_estimate, currency)} detail="Uses current sample FX" />
        <Metric label="Available cash" value={amount(data.totals.available_cash, currency)} detail="Across sample accounts" />
        <Metric label="Monthly income estimate" value={amount(data.totals.estimated_monthly_income, currency)} detail="Gross indicated income" />
      </div>
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
                <th className="align-right">Last sample mark</th>
                <th className="align-right">Market value</th>
                <th className="align-right">Change vs. cost</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((holding) => (
                <tr key={holding.symbol}>
                  <td>
                    <div className="instrument-cell">
                      <span className={`ticker-avatar ticker-${holding.asset_class}`}>{holding.symbol.slice(0, 2)}</span>
                      <span><strong>{holding.name}</strong><small>{holding.symbol} · {holding.price_currency}</small></span>
                    </div>
                  </td>
                  <td className="muted-cell">{holding.account_name}</td>
                  <td><span className={`asset-tag asset-${holding.asset_class}`}>{assetLabel(holding.asset_class)}</span></td>
                  <td className="align-right tabular">{number(holding.quantity, 4)}</td>
                  <td className="align-right tabular">{amount(holding.price, holding.price_currency, 2)}</td>
                  <td className="align-right tabular strong-cell">{amount(holding.market_value, currency)}</td>
                  <td className={`align-right tabular ${Number(holding.change_percent) >= 0 ? "positive-text" : "negative-text"}`}>
                    {Number(holding.change_percent) >= 0 ? "+" : ""}{Number(holding.change_percent).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-note"><Info size={15} /> These are synthetic sample positions, not linked brokerage holdings or current quotes.</div>
      </section>
      <section className="panel concentration-panel">
        <div className="concentration-icon"><ArrowUpRight size={19} /></div>
        <div>
          <div className="eyebrow">A useful next connection</div>
          <h2>Bring accounts together when you’re ready.</h2>
          <p>Broker connections and statement imports are not enabled yet. Use the demo only to explore goals and allocation logic.</p>
        </div>
        <span className="status-pill status-planned">Planned</span>
      </section>
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
