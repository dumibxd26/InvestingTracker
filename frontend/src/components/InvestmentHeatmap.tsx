import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Maximize2, Minimize2, X } from "lucide-react";
import { createPortal } from "react-dom";
import { amount, number } from "../format";
import type { Currency, HoldingSummary } from "../types";

interface TreemapRect {
  symbol: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface TickerGroup {
  symbol: string;
  name: string;
  holdings: HoldingSummary[];
  marketValue: number;
  grossValue: number;
  saleTax: number;
  costBasis: number;
  estimatedGain: number;
  estimatedGainPercent: number;
}

const riskStyles = {
  X: { label: "X · Lower relative risk" },
  Y: { label: "Y · Moderate / concentrated" },
  Z: { label: "Z · High volatility / speculative" },
} as const;

function listingVenue(holding: HoldingSummary): string {
  const exchange = holding.exchange.trim();
  const mic = holding.mic_code.trim();
  const values = [
    exchange && exchange.toUpperCase() !== "UNKNOWN" ? exchange : "",
    mic && mic.toUpperCase() !== "UNKNOWN" && mic !== exchange ? mic : "",
  ].filter(Boolean);
  return values.join(" · ") || "Exchange not recorded";
}

function groupByTicker(holdings: HoldingSummary[]): TickerGroup[] {
  const groups = new Map<string, TickerGroup>();
  for (const holding of holdings) {
    const symbol = holding.symbol.trim().toUpperCase();
    const group = groups.get(symbol) ?? {
      symbol,
      name: holding.name,
      holdings: [],
      marketValue: 0,
      grossValue: 0,
      saleTax: 0,
      costBasis: 0,
      estimatedGain: 0,
      estimatedGainPercent: 0,
    };
    group.holdings.push(holding);
    group.marketValue += Number(holding.market_value);
    group.grossValue += Number(holding.gross_market_value);
    group.saleTax += Number(holding.estimated_sale_tax);
    group.costBasis += Number(holding.cost_basis_value);
    group.estimatedGain += Number(holding.estimated_gain);
    groups.set(symbol, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    estimatedGainPercent: group.costBasis > 0
      ? group.estimatedGain * 100 / group.costBasis
      : 0,
  }));
}

function treemap(
  groups: TickerGroup[],
  x: number,
  y: number,
  width: number,
  height: number,
): TreemapRect[] {
  if (groups.length === 0) return [];
  if (groups.length === 1) {
    return [{ symbol: groups[0].symbol, x, y, width, height }];
  }
  const total = groups.reduce((sum, group) => sum + group.marketValue, 0);
  let leftTotal = 0;
  let splitIndex = 1;
  let closestDifference = Number.POSITIVE_INFINITY;
  for (let index = 1; index < groups.length; index += 1) {
    leftTotal += groups[index - 1].marketValue;
    const difference = Math.abs(total / 2 - leftTotal);
    if (difference < closestDifference) {
      closestDifference = difference;
      splitIndex = index;
    }
  }
  leftTotal = groups.slice(0, splitIndex)
    .reduce((sum, group) => sum + group.marketValue, 0);
  const ratio = total > 0 ? leftTotal / total : 0.5;
  if (width >= height) {
    const leftWidth = width * ratio;
    return [
      ...treemap(groups.slice(0, splitIndex), x, y, leftWidth, height),
      ...treemap(groups.slice(splitIndex), x + leftWidth, y, width - leftWidth, height),
    ];
  }
  const topHeight = height * ratio;
  return [
    ...treemap(groups.slice(0, splitIndex), x, y, width, topHeight),
    ...treemap(groups.slice(splitIndex), x, y + topHeight, width, height - topHeight),
  ];
}

function gainColor(gainPercent: number, maxMagnitude: number): string {
  const neutral = [118, 130, 122];
  const target = gainPercent >= 0 ? [28, 139, 78] : [191, 49, 45];
  const strength = Math.min(1, Math.max(0.12, Math.abs(gainPercent) / maxMagnitude));
  const channel = (index: number) =>
    Math.round(neutral[index] + (target[index] - neutral[index]) * strength);
  return `rgb(${channel(0)} ${channel(1)} ${channel(2)})`;
}

interface TooltipPosition {
  symbol: string;
  left: number;
  top: number;
}

function HeatmapCanvas({
  groups,
  currency,
  maxGainMagnitude,
  large = false,
  onSelect,
}: {
  groups: TickerGroup[];
  currency: Currency;
  maxGainMagnitude: number;
  large?: boolean;
  onSelect: (symbol: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipPosition | null>(null);
  const rectangles = treemap(groups, 0, 0, 1000, 560);
  const groupsBySymbol = new Map(groups.map((group) => [group.symbol, group]));

  function showTooltip(event: ReactPointerEvent<SVGGElement>, symbol: string) {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const tooltipWidth = large ? 280 : 255;
    const tooltipHeight = large ? 155 : 145;
    setTooltip({
      symbol,
      left: Math.max(8, Math.min(event.clientX - rect.left + 14, rect.width - tooltipWidth - 8)),
      top: Math.max(8, Math.min(event.clientY - rect.top + 14, rect.height - tooltipHeight - 8)),
    });
  }

  const hoveredGroup = tooltip ? groupsBySymbol.get(tooltip.symbol) : undefined;
  const hoveredReturn = hoveredGroup && hoveredGroup.marketValue > 0
    ? hoveredGroup.holdings.reduce(
      (sum, holding) => sum + Number(holding.market_value) * Number(holding.expected_annual_return),
      0,
    ) / hoveredGroup.marketValue
    : 0;
  const hoveredTiers = hoveredGroup
    ? [...new Set(hoveredGroup.holdings.map((holding) => holding.risk_tier))].sort().join(", ")
    : "";
  const hoveredListings = hoveredGroup
    ? [...new Set(hoveredGroup.holdings.map(
      (holding) => `${holding.account_name} · ${listingVenue(holding)}`,
    ))]
    : [];

  return (
    <div
      className={`investment-treemap${large ? " investment-treemap-large" : ""}`}
      ref={containerRef}
      onPointerLeave={() => setTooltip(null)}
    >
      <svg
        viewBox="0 0 1000 560"
        preserveAspectRatio={large ? "xMidYMid meet" : "none"}
        role="group"
        aria-label="Investment heatmap grouped by ticker"
      >
        {rectangles.map(({ symbol, x, y, width, height }) => {
          const group = groupsBySymbol.get(symbol);
          if (!group) return null;
          const color = gainColor(group.estimatedGainPercent, maxGainMagnitude);
          const showSymbol = width > 50 && height > 33;
          const showValue = width > 105 && height > 57;
          return (
            <g
              key={symbol}
              className="treemap-clickable"
              role="button"
              tabIndex={0}
              aria-label={`${symbol}: ${amount(group.marketValue, currency)}, estimated gain ${amount(group.estimatedGain, currency)} (${group.estimatedGainPercent.toFixed(1)}%). Open listings and accounts.`}
              onPointerEnter={(event) => showTooltip(event, symbol)}
              onPointerMove={(event) => showTooltip(event, symbol)}
              onFocus={() => setTooltip({ symbol, left: 12, top: 12 })}
              onBlur={() => setTooltip(null)}
              onClick={() => onSelect(symbol)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(symbol);
                }
              }}
            >
              <rect
                x={x + 2}
                y={y + 2}
                width={Math.max(0, width - 4)}
                height={Math.max(0, height - 4)}
                rx="8"
                fill={color}
                className="treemap-tile"
              />
              {showSymbol && (
                <>
                  <text x={x + 12} y={y + 20} className="treemap-symbol">
                    {symbol}
                  </text>
                  {showValue && (
                    <>
                      <text x={x + 12} y={y + 39} className="treemap-value">
                        {amount(group.marketValue, currency)}
                      </text>
                      <text x={x + 12} y={y + 55} className="treemap-gain">
                        {group.estimatedGain >= 0 ? "+" : ""}
                        {group.estimatedGainPercent.toFixed(1)}%
                      </text>
                    </>
                  )}
                </>
              )}
            </g>
          );
        })}
      </svg>
      {hoveredGroup && tooltip && (
        <div
          className="heatmap-stock-tooltip"
          role="tooltip"
          style={{ left: tooltip.left, top: tooltip.top }}
        >
          <strong>{hoveredGroup.symbol} · {hoveredGroup.name}</strong>
          <span>After-tax value: {amount(hoveredGroup.marketValue, currency)}</span>
          <span className={hoveredGroup.estimatedGain >= 0 ? "positive-text" : "negative-text"}>
            Estimated gain/loss: {hoveredGroup.estimatedGain >= 0 ? "+" : ""}
            {amount(hoveredGroup.estimatedGain, currency)} ({hoveredGroup.estimatedGainPercent.toFixed(1)}%)
          </span>
          <span>Risk tier(s): {hoveredTiers || "not assigned"} · assumed return: {(hoveredReturn * 100).toFixed(1)}%/yr</span>
          <small>{hoveredListings.join("; ")}</small>
        </div>
      )}
    </div>
  );
}

export function InvestmentHeatmap({
  holdings,
  currency,
}: {
  holdings: HoldingSummary[];
  currency: Currency;
}) {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [fullScreen, setFullScreen] = useState(false);
  useEffect(() => {
    if (!fullScreen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullScreen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [fullScreen]);
  const groups = useMemo(
    () => groupByTicker(holdings)
      .filter((group) => group.marketValue > 0)
      .sort((a, b) => b.marketValue - a.marketValue),
    [holdings],
  );
  const totalValue = groups.reduce((sum, group) => sum + group.marketValue, 0);
  const maxGainMagnitude = Math.max(
    1,
    ...groups.map((group) => Math.abs(group.estimatedGainPercent)),
  );
  const riskTotals = {
    X: holdings.filter((holding) => holding.risk_tier === "X")
      .reduce((sum, holding) => sum + Number(holding.market_value), 0),
    Y: holdings.filter((holding) => holding.risk_tier === "Y")
      .reduce((sum, holding) => sum + Number(holding.market_value), 0),
    Z: holdings.filter((holding) => holding.risk_tier === "Z")
      .reduce((sum, holding) => sum + Number(holding.market_value), 0),
  };
  const selected = groups.find((group) => group.symbol === selectedTicker) ?? null;

  return (
    <>
      <section className="panel investment-heatmap-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">Where invested value sits</div>
            <h2>Investment heatmap</h2>
          </div>
          <div className="heatmap-heading-actions">
            <span className="panel-kicker">Area = combined after-tax holding value</span>
            {groups.length > 0 && (
              <button
                className="text-button heatmap-expand-button"
                type="button"
                onClick={() => setFullScreen(true)}
                aria-label="Expand investment heatmap to full screen"
              >
                <Maximize2 size={14} /> Full screen
              </button>
            )}
          </div>
        </div>
        {groups.length > 0 ? (
          <>
            <HeatmapCanvas
              groups={groups}
              currency={currency}
              maxGainMagnitude={maxGainMagnitude}
              onSelect={setSelectedTicker}
            />
            <div className="heatmap-legend" aria-label="Gain and loss color legend">
              <span>Estimated loss</span>
              <span className="heatmap-legend-scale" />
              <span>Break-even</span>
              <span className="heatmap-legend-scale heatmap-legend-scale-positive" />
              <span>Estimated profit</span>
              <small>Color strength is scaled to the largest absolute percentage change in this portfolio.</small>
            </div>
            <div className="risk-exposure-grid">
              {(["X", "Y", "Z"] as const).map((tier) => (
                <div className="risk-exposure-item" key={tier}>
                  <span className={`risk-exposure-dot risk-tier-${tier.toLowerCase()}`} />
                  <span>{riskStyles[tier].label}</span>
                  <strong>{amount(riskTotals[tier], currency)}</strong>
                  <small>{totalValue ? `${(riskTotals[tier] * 100 / totalValue).toFixed(1)}%` : "0%"}</small>
                </div>
              ))}
            </div>
            <div className="table-note">
              Heatmap colors show estimated gain/loss from average cost after the app’s 3% positive-gain tax estimate. This is not tax-lot or realized P&amp;L accounting. Risk tiers are qualitative placeholders, not measured volatility or safety grades. ETFs default to X and stocks to Y; existing positions start at 5% and new ETFs at 6% nominal return. Both fields are editable per holding.
            </div>
          </>
        ) : (
          <div className="empty-state"><strong>No quoted holdings to display</strong><span>Add holdings and refresh their quotes to populate the heatmap.</span></div>
        )}
      </section>
      {fullScreen && createPortal(
        <div
          className="heatmap-fullscreen-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setFullScreen(false);
          }}
        >
          <section
            className="heatmap-fullscreen-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="heatmap-fullscreen-title"
          >
            <header className="heatmap-fullscreen-heading">
              <div>
                <div className="eyebrow">Area = combined after-tax holding value</div>
                <h2 id="heatmap-fullscreen-title">Investment heatmap</h2>
                <p>Hover over a tile for position details. Select a tile to see each account and listing.</p>
              </div>
              <button
                className="icon-button"
                type="button"
                aria-label="Exit full-screen heatmap"
                onClick={() => setFullScreen(false)}
              >
                <Minimize2 size={18} />
              </button>
            </header>
            <HeatmapCanvas
              groups={groups}
              currency={currency}
              maxGainMagnitude={maxGainMagnitude}
              large
              onSelect={setSelectedTicker}
            />
            <div className="heatmap-legend" aria-label="Gain and loss color legend">
              <span>Estimated loss</span>
              <span className="heatmap-legend-scale" />
              <span>Break-even</span>
              <span className="heatmap-legend-scale heatmap-legend-scale-positive" />
              <span>Estimated profit</span>
              <small>Color strength is scaled to the largest absolute percentage change in this portfolio.</small>
            </div>
          </section>
        </div>,
        document.body,
      )}
      {selected && createPortal(
        <div className={`modal-backdrop${fullScreen ? " heatmap-detail-backdrop-on-top" : ""}`} onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelectedTicker(null);
        }}>
          <section className="modal-card ticker-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="ticker-detail-title">
            <div className="modal-heading">
              <div>
                <div className="eyebrow">{selected.name}</div>
                <h2 id="ticker-detail-title">{selected.symbol} · all tracked listings</h2>
              </div>
              <button className="icon-button" type="button" aria-label="Close" onClick={() => setSelectedTicker(null)}>
                <X size={19} />
              </button>
            </div>
            <div className="ticker-detail-summary">
              <div><span>Combined estimated after-tax value</span><strong>{amount(selected.marketValue, currency)}</strong></div>
              <div>
                <span>Estimated gain/loss after current tax assumption</span>
                <strong className={selected.estimatedGain >= 0 ? "positive-text" : "negative-text"}>
                  {selected.estimatedGain >= 0 ? "+" : ""}{amount(selected.estimatedGain, currency)}
                  {" "}({selected.estimatedGainPercent.toFixed(1)}%)
                </strong>
              </div>
            </div>
            <div className="ticker-listing-table">
              <div className="ticker-listing-header">
                <span>Account / exchange</span><span>Units / quote</span><span>Value / gain</span>
              </div>
              {selected.holdings.map((holding) => (
                <div className="ticker-listing-row" key={holding.id}>
                  <span>
                    <strong>{holding.account_name}</strong>
                    <small>
                      {listingVenue(holding)}
                      {" · "}{holding.price_currency}
                    </small>
                  </span>
                  <span>
                    <strong>{number(holding.quantity, 4)} shares</strong>
                    <small>Quote {amount(holding.price, holding.price_currency, 2)}</small>
                    <small>
                      Cost {amount(holding.average_cost, holding.price_currency, 2)}/share · bought {holding.purchase_date}
                    </small>
                  </span>
                  <span>
                    <strong>{amount(holding.market_value, currency)}</strong>
                    <small className={Number(holding.estimated_gain) >= 0 ? "positive-text" : "negative-text"}>
                      {Number(holding.estimated_gain) >= 0 ? "+" : ""}
                      {amount(holding.estimated_gain, currency)} ({Number(holding.estimated_gain_percent).toFixed(1)}%)
                    </small>
                    <small>
                      Risk {holding.risk_tier} · assumed return {(Number(holding.expected_annual_return) * 100).toFixed(1)}%
                    </small>
                  </span>
                </div>
              ))}
            </div>
            <p className="table-note">
              Listings with the same normalized ticker are combined here. Each exchange/account position remains separately shown above.
            </p>
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}
