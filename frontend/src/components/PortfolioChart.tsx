import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { amount } from "../format";
import type { ChartPoint, Currency } from "../types";

interface PortfolioChartProps {
  points: ChartPoint[];
  currency: Currency;
  change: string;
  changePercent: string;
}

export function PortfolioChart({ points, currency, change, changePercent }: PortfolioChartProps) {
  const width = 720;
  const height = 220;
  const padding = { top: 16, right: 12, bottom: 28, left: 12 };
  const values = points.map((point) => Number(point.value));
  const low = Math.min(...values);
  const high = Math.max(...values);
  const spread = Math.max(high - low, 1);
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const coordinates = points.map((point, index) => ({
    x: padding.left + (points.length <= 1 ? 0 : (index / (points.length - 1)) * innerWidth),
    y: padding.top + innerHeight - ((Number(point.value) - low) / spread) * innerHeight,
  }));
  const line = coordinates.map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`).join(" ");
  const area = `${line} L${coordinates.at(-1)?.x ?? 0},${height - padding.bottom} L${coordinates[0]?.x ?? 0},${height - padding.bottom} Z`;
  const positive = Number(change) >= 0;
  const ChangeIcon = positive ? ArrowUpRight : ArrowDownRight;

  return (
    <section className="panel portfolio-chart-panel">
      <div className="panel-heading chart-heading">
        <div>
          <div className="eyebrow">Tracked wealth</div>
          <h2>More clarity, month by month.</h2>
        </div>
        <div className={`change-pill ${positive ? "positive" : "negative"}`}>
          <ChangeIcon size={14} />
          <span>{amount(change, currency)} <small>({Number(changePercent).toFixed(1)}%)</small></span>
        </div>
      </div>
      {points.length > 1 ? (
        <>
          <div className="chart-subtitle">
            <span>Illustrative six-month view</span>
            <span className="sample-caption"><span className="sample-dot" /> Sample history</span>
          </div>
          <div className="chart-wrap">
            <svg
              className="portfolio-chart"
              viewBox={`0 0 ${width} ${height}`}
              preserveAspectRatio="none"
              role="img"
              aria-label="Illustrative six-month tracked wealth trend"
            >
              <defs>
                <linearGradient id="wealth-area" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#397d68" stopOpacity="0.19" />
                  <stop offset="100%" stopColor="#397d68" stopOpacity="0.015" />
                </linearGradient>
              </defs>
              {[0, 1, 2].map((lineNumber) => {
                const y = padding.top + (innerHeight / 2) * lineNumber;
                return <line key={lineNumber} x1={padding.left} x2={width - padding.right} y1={y} y2={y} className="chart-grid-line" />;
              })}
              <path d={area} fill="url(#wealth-area)" />
              <path d={line} className="chart-line" />
              {coordinates.map((point, index) => (
                <circle key={index} cx={point.x} cy={point.y} r={index === coordinates.length - 1 ? 4 : 2.5} className="chart-point" />
              ))}
            </svg>
          </div>
          <div className="chart-labels">
            <span>{points[0]?.label}</span>
            <span>{points[Math.floor((points.length - 1) / 2)]?.label}</span>
            <span>{points.at(-1)?.label}</span>
          </div>
        </>
      ) : (
        <div className="chart-empty">History will appear as valuations are recorded.</div>
      )}
    </section>
  );
}
