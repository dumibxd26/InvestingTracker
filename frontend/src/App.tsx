import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, RefreshCw } from "lucide-react";
import { api, ApiError } from "./api";
import { AssistantView } from "./components/AssistantView";
import { AllocationSimulator } from "./components/AllocationSimulator";
import { CashFlowView } from "./components/CashFlowView";
import { CompensationView } from "./components/CompensationView";
import { GoalDialog } from "./components/GoalDialog";
import { GoalsView } from "./components/GoalsView";
import { Overview } from "./components/Overview";
import { PortfolioView } from "./components/PortfolioView";
import { Sidebar } from "./components/Sidebar";
import type { Currency, Dashboard } from "./types";

export type View = "overview" | "portfolio" | "goals" | "cashflow" | "compensation" | "assistant";

const pageTitles: Record<View, string> = {
  overview: "Overview",
  portfolio: "Portfolio",
  goals: "Goals & plan",
  cashflow: "Cash flow",
  compensation: "Equity & deposits",
  assistant: "AI assistant",
};

export default function App() {
  const [activeView, setActiveView] = useState<View>("overview");
  const [currency, setCurrency] = useState<Currency>("EUR");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [goalDialogOpen, setGoalDialogOpen] = useState(false);
  const [allocationOpen, setAllocationOpen] = useState(false);
  const hasData = useRef(false);

  const reload = useCallback(async (signal?: AbortSignal) => {
    setError("");
    setRefreshing(hasData.current);
    if (!hasData.current) setLoading(true);
    try {
      const result = await api.dashboard(currency, signal);
      if (!signal?.aborted) {
        setData(result);
        hasData.current = true;
      }
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof ApiError ? cause.message : "The wealth snapshot could not be loaded.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [currency]);

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    document.title = `${pageTitles[activeView]} — Northstar`;
  }, [activeView]);

  const handleGoalCreated = async () => {
    await reload();
    setActiveView("goals");
  };

  const activeDate = data
    ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(new Date(data.as_of))
    : "";

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} onNavigate={setActiveView} />
      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Personal workspace</span>
            <span className="crumb-divider">/</span>
            <strong>{pageTitles[activeView]}</strong>
          </div>
          <div className="topbar-actions">
            <span className="data-timestamp">{data ? `Snapshot ${activeDate}` : "Connecting…"}</span>
            <button
              className={`icon-button refresh-button ${refreshing ? "is-refreshing" : ""}`}
              type="button"
              aria-label="Refresh wealth snapshot"
              onClick={() => void reload()}
              disabled={refreshing || loading}
            >
              <RefreshCw size={16} />
            </button>
            <label className="currency-select">
              <span className="sr-only">Reporting currency</span>
              <select value={currency} onChange={(event) => setCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR €</option>
                <option value="USD">USD $</option>
              </select>
              <ChevronDown size={13} aria-hidden="true" />
            </label>
            <span className="topbar-avatar" aria-label="Demo profile">D</span>
          </div>
        </header>

        <div className="main-scroll">
          {data?.sample_data && (
            <div className="sample-banner">
              <AlertTriangle size={15} />
              <span><strong>Sample workspace.</strong> Balances, prices, FX, goals, and history are illustrative—not connected to your accounts or live data.</span>
              <button type="button" onClick={() => setActiveView("portfolio")}>What’s included?</button>
            </div>
          )}
          {error && (
            <div className="api-error-banner" role="alert">
              <AlertTriangle size={17} />
              <span>{error}</span>
              <button type="button" onClick={() => void reload()}>Retry</button>
            </div>
          )}
          {loading && !data ? (
            <div className="loading-state" role="status">
              <span className="loading-orbit" />
              <strong>Bringing your picture together…</strong>
              <span>Connecting to the local wealth API</span>
            </div>
          ) : data ? (
            <>
              {activeView === "overview" && (
                <Overview
                  data={data}
                  currency={currency}
                  onAddGoal={() => setGoalDialogOpen(true)}
                  onPreview={() => setAllocationOpen(true)}
                  onOpenGoals={() => setActiveView("goals")}
                  onOpenCashFlow={() => setActiveView("cashflow")}
                />
              )}
              {activeView === "portfolio" && <PortfolioView data={data} currency={currency} />}
              {activeView === "goals" && (
                <GoalsView
                  data={data}
                  currency={currency}
                  onAddGoal={() => setGoalDialogOpen(true)}
                  onSaved={reload}
                />
              )}
              {activeView === "cashflow" && (
                <CashFlowView data={data} currency={currency} onChanged={reload} />
              )}
              {activeView === "compensation" && <CompensationView data={data} currency={currency} />}
              {activeView === "assistant" && <AssistantView data={data} currency={currency} />}
            </>
          ) : !error ? (
            <div className="api-error-empty">
              <strong>Your wealth snapshot isn’t available yet.</strong>
              <button className="button button-primary" type="button" onClick={() => void reload()}>Try again</button>
            </div>
          ) : null}
          <footer className="page-footer">
            <span>Northstar Wealth · personal decision support</span>
            <span>No automatic trades · illustrative data only</span>
          </footer>
        </div>
      </main>

      {goalDialogOpen && (
        <GoalDialog currency={currency} onClose={() => setGoalDialogOpen(false)} onCreated={handleGoalCreated} />
      )}
      {allocationOpen && <AllocationSimulator currency={currency} onClose={() => setAllocationOpen(false)} />}
    </div>
  );
}
