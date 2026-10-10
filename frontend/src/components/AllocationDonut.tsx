import { amount, assetLabel } from "../format";
import type { Allocation, AssetClass, Currency } from "../types";

const COLORS: Record<AssetClass, string> = {
  equities: "#4d8e78",
  fixed_income: "#9ab9a7",
  satellite: "#e0b76d",
};

interface AllocationDonutProps {
  allocation: Allocation[];
  currency: Currency;
}

export function AllocationDonut({ allocation, currency }: AllocationDonutProps) {
  let cursor = 0;
  const stops = allocation.map((item) => {
    const start = cursor;
    cursor += Math.max(0, Number(item.percentage));
    return `${COLORS[item.asset_class]} ${start}% ${cursor}%`;
  });

  return (
    <section className="panel allocation-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">Your mix</div>
          <h2>Allocation</h2>
        </div>
        <span className="panel-kicker">vs. target</span>
      </div>
      <div className="donut-layout">
        <div
          className="allocation-donut"
          role="img"
          aria-label={allocation.map((item) => `${assetLabel(item.asset_class)} ${Number(item.percentage).toFixed(0)}%`).join(", ")}
          style={{ background: `conic-gradient(${stops.join(", ")})` }}
        >
          <div className="donut-inner">
            <span>Invested</span>
            <strong>{amount(allocation.reduce((sum, item) => sum + Number(item.value), 0), currency, 0)}</strong>
          </div>
        </div>
        <div className="allocation-legend">
          {allocation.map((item) => (
            <div className="legend-row" key={item.asset_class}>
              <span className="legend-dot" style={{ backgroundColor: COLORS[item.asset_class] }} />
              <span className="legend-name">{assetLabel(item.asset_class)}</span>
              <span className="legend-values">
                <strong>{Number(item.percentage).toFixed(0)}%</strong>
                <small>{Number(item.target_percentage).toFixed(0)}%</small>
              </span>
            </div>
          ))}
        </div>
      </div>
      <div className="allocation-footnote">
        Targets apply to invested holdings; cash and unvested grants are shown separately.
      </div>
    </section>
  );
}
