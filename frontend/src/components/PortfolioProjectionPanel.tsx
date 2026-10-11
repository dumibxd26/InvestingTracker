import { useMemo, useState } from "react";
import { CalendarRange, Info, TrendingUp } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { Currency, PortfolioProjection } from "../types";

interface PortfolioProjectionPanelProps {
  currency: Currency;
}

function localDateValue(value: Date): string {
  const date = new Date(value);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 10);
}

function dateAfterYears(years: number): string {
  const target = new Date();
  target.setFullYear(target.getFullYear() + years);
  return localDateValue(target);
}

function projectionValueAtPoint(
  projection: PortfolioProjection,
  pointIndex: number,
  selectedAccountId: string,
): number {
  const point = projection.timeline[pointIndex];
  if (!point) return 0;
  if (!selectedAccountId) return Number(point.total_value);
  return Number(
    point.accounts.find((account) => account.account_id === selectedAccountId)
      ?.projected_total_value ?? "0",
  );
}

export function PortfolioProjectionPanel({
  currency,
}: PortfolioProjectionPanelProps) {
  const [preset, setPreset] = useState("10");
  const [targetDate, setTargetDate] = useState(() => dateAfterYears(10));
  const [projection, setProjection] = useState<PortfolioProjection | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const chartValues = useMemo(
    () => projection?.timeline.map((_, index) =>
      projectionValueAtPoint(projection, index, selectedAccountId),
    ) ?? [],
    [projection, selectedAccountId],
  );
  const chartCoordinates = useMemo(() => {
    if (chartValues.length < 2) return [];
    const width = 900;
    const height = 260;
    const maximum = Math.max(...chartValues, 1) * 1.08;
    return chartValues.map((value, index) => ({
      x: 20 + index * (width - 40) / (chartValues.length - 1),
      y: height - 28 - value / maximum * (height - 50),
      value,
    }));
  }, [chartValues]);

  function handlePresetChange(value: string) {
    setPreset(value);
    if (value !== "custom") setTargetDate(dateAfterYears(Number(value)));
  }

  async function calculate() {
    setError("");
    setLoading(true);
    try {
      const result = await api.portfolioProjection(targetDate, currency);
      setProjection(result);
      if (
        selectedAccountId
        && !result.accounts.some((account) => account.account_id === selectedAccountId)
      ) {
        setSelectedAccountId("");
      }
    } catch (cause) {
      setProjection(null);
      setError(cause instanceof ApiError ? cause.message : "The portfolio projection could not be calculated.");
    } finally {
      setLoading(false);
    }
  }

  const currentValue = selectedAccountId
    ? Number(projection?.accounts.find((account) => account.account_id === selectedAccountId)?.current_value ?? "0")
    : Number(projection?.current_net_worth ?? "0");
  const projectedValue = selectedAccountId
    ? Number(projection?.accounts.find((account) => account.account_id === selectedAccountId)?.projected_total_value ?? "0")
    : Number(projection?.projected_net_worth ?? "0");

  return (
    <section className="panel portfolio-projection-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">Illustrative scenario</div>
          <h2>What could my accounts be worth?</h2>
        </div>
        <span className="projection-icon"><TrendingUp size={17} /></span>
      </div>
      <div className="projection-controls">
        <label className="form-field">
          <span>Projection period</span>
          <select value={preset} onChange={(event) => handlePresetChange(event.target.value)}>
            <option value="1">1 year</option>
            <option value="5">5 years</option>
            <option value="10">10 years</option>
            <option value="custom">Custom date</option>
          </select>
        </label>
        <label className="form-field">
          <span>End date</span>
          <input
            type="date"
            value={targetDate}
            onChange={(event) => {
              setPreset("custom");
              setTargetDate(event.target.value);
            }}
          />
        </label>
        <button className="button button-primary" type="button" onClick={() => void calculate()} disabled={loading || !targetDate}>
          <CalendarRange size={15} /> {loading ? "Calculating…" : "Calculate projection"}
        </button>
      </div>
      {error && <div className="inline-error projection-error" role="alert">{error}</div>}
      {projection && (
        <>
          <div className="projection-summary">
            <div>
              <span>{selectedAccountId ? "Selected account now" : "Tracked wealth now"}</span>
              <strong>{amount(currentValue, currency)}</strong>
            </div>
            <div>
              <span>Projected by {new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(projection.target_date))}</span>
              <strong>{amount(projectedValue, currency)}</strong>
            </div>
            <div>
              <span>Illustrative change</span>
              <strong className={projectedValue >= currentValue ? "positive-text" : "negative-text"}>
                {amount(projectedValue - currentValue, currency)}
              </strong>
            </div>
            <label className="form-field projection-account-select">
              <span>Show series</span>
              <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value)}>
                <option value="">All accounts</option>
                {projection.accounts.map((account) => (
                  <option value={account.account_id} key={account.account_id}>{account.account_name}</option>
                ))}
              </select>
            </label>
          </div>
          {chartCoordinates.length > 1 && (
            <div className="projection-chart-wrap">
              <svg viewBox="0 0 900 260" preserveAspectRatio="none" role="img" aria-label="Projected account value by date">
                <line x1="20" y1="232" x2="880" y2="232" className="projection-axis" />
                <polyline
                  points={chartCoordinates.map((point) => `${point.x},${point.y}`).join(" ")}
                  className="projection-line"
                />
                {chartCoordinates.map((point, index) => (
                  <g key={`${projection.timeline[index]?.date ?? index}`}>
                    <circle cx={point.x} cy={point.y} r="4" className="projection-point" />
                    <title>
                      {projection.timeline[index]?.label}: {amount(point.value, currency)}
                    </title>
                  </g>
                ))}
              </svg>
              <div className="projection-chart-labels">
                <span>{projection.timeline[0]?.label}</span>
                <span>{projection.timeline[projection.timeline.length - 1]?.label}</span>
              </div>
            </div>
          )}
          <div className="projection-account-list">
            {projection.accounts.map((account) => (
              <div className="projection-account-row" key={account.account_id}>
                <strong>{account.account_name}</strong>
                <span>{amount(account.current_value, currency)}</span>
                <span>→ {amount(account.projected_total_value, currency)}</span>
              </div>
            ))}
          </div>
          <div className="projection-warning">
            <Info size={15} />
            <ul>
              {projection.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </div>
        </>
      )}
      {!projection && !error && (
        <p className="projection-intro">
          Holdings use the editable annual-return assumption in Portfolio. Cash stays flat;
          fixed deposits accrue to their maturity date.
        </p>
      )}
    </section>
  );
}
