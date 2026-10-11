import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Moon, RefreshCw, Sun } from "lucide-react";
import { api, ApiError, getAccessToken, setAccessToken } from "./api";
import { AssistantView } from "./components/AssistantView";
import { AllocationSimulator } from "./components/AllocationSimulator";
import { AuthView } from "./components/AuthView";
import { CashFlowView } from "./components/CashFlowView";
import { CompensationView } from "./components/CompensationView";
import { GoalDialog } from "./components/GoalDialog";
import { GoalsView } from "./components/GoalsView";
import { Overview } from "./components/Overview";
import { PortfolioView } from "./components/PortfolioView";
import { SettingsView } from "./components/SettingsView";
import { Sidebar } from "./components/Sidebar";
import type { AuthResponse, Currency, Dashboard, UserProfile } from "./types";

export type View =
  | "overview"
  | "portfolio"
  | "goals"
  | "cashflow"
  | "compensation"
  | "assistant"
  | "settings";

const pageTitles: Record<View, string> = {
  overview: "Overview",
  portfolio: "Portfolio",
  goals: "Goals & plan",
  cashflow: "Cash flow",
  compensation: "Equity & deposits",
  assistant: "AI assistant",
  settings: "Profile settings",
};

function hasCurrencyPath(
  from: Currency,
  to: Currency,
  data: Dashboard | null,
  usdPerEur: string | null,
): boolean {
  if (from === to) return true;
  const edges = new Map<Currency, Set<Currency>>();
  function addEdge(base: Currency, quote: Currency) {
    const neighbors = edges.get(base) ?? new Set<Currency>();
    neighbors.add(quote);
    edges.set(base, neighbors);
  }
  for (const rate of data?.market_fx_rates ?? []) {
    addEdge(rate.base_currency, rate.quote_currency);
    addEdge(rate.quote_currency, rate.base_currency);
  }
  if (usdPerEur) {
    addEdge("EUR", "USD");
    addEdge("USD", "EUR");
  }
  const visited = new Set<Currency>([from]);
  const queue = [from];
  while (queue.length) {
    const current = queue.shift();
    if (!current) continue;
    for (const neighbor of edges.get(current) ?? []) {
      if (neighbor === to) return true;
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
  }
  return false;
}

function initialDarkMode(): boolean {
  if (typeof window === "undefined") return false;
  const preference = window.localStorage.getItem("northstar-theme");
  if (preference === "dark") return true;
  if (preference === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export default function App() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [activeView, setActiveView] = useState<View>("overview");
  const [currency, setCurrency] = useState<Currency>("EUR");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [goalDialogOpen, setGoalDialogOpen] = useState(false);
  const [allocationOpen, setAllocationOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(initialDarkMode);
  const hasData = useRef(false);

  useEffect(() => {
    let active = true;
    if (!getAccessToken()) {
      setAuthChecking(false);
      return () => {
        active = false;
      };
    }
    void api.me()
      .then((currentProfile) => {
        if (!active) return;
        setProfile(currentProfile);
        setCurrency(currentProfile.base_currency);
      })
      .catch(() => {
        if (active) setAccessToken(null);
      })
      .finally(() => {
        if (active) setAuthChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? "dark" : "light";
    window.localStorage.setItem("northstar-theme", darkMode ? "dark" : "light");
  }, [darkMode]);

  useEffect(() => {
    function handleExpiredSession() {
      setProfile(null);
      setData(null);
      hasData.current = false;
      setError("Your sign-in session expired. Sign in again to continue.");
      setActiveView("overview");
    }
    window.addEventListener("northstar-auth-expired", handleExpiredSession);
    return () => window.removeEventListener("northstar-auth-expired", handleExpiredSession);
  }, []);

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
    if (!profile) return;
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload, profile]);

  useEffect(() => {
    if (!profile) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [profile, reload]);

  useEffect(() => {
    document.title = `${pageTitles[activeView]} — Northstar`;
  }, [activeView]);

  function handleAuthenticated(response: AuthResponse) {
    setProfile(response.user);
    setCurrency(response.user.base_currency);
    setData(null);
    setError("");
    hasData.current = false;
    setLoading(true);
    setActiveView("overview");
  }

  async function handleLogout() {
    await api.logout();
    setProfile(null);
    setData(null);
    hasData.current = false;
    setError("");
    setActiveView("overview");
    setAuthChecking(false);
  }

  async function handleGoalCreated() {
    await reload();
    setActiveView("goals");
  }

  async function handleProfileSaved(updatedProfile: UserProfile) {
    setProfile(updatedProfile);
    if (currency === updatedProfile.base_currency) {
      await reload();
    } else {
      setCurrency(updatedProfile.base_currency);
    }
  }

  const activeDate = data
    ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(new Date(data.as_of))
    : "";

  if (authChecking) {
    return (
      <div className="auth-loading" role="status">
        <span className="loading-orbit" />
        <strong>Opening your private workspace…</strong>
      </div>
    );
  }

  if (!profile) {
    return (
      <AuthView
        onAuthenticated={handleAuthenticated}
        darkMode={darkMode}
        onToggleTheme={() => setDarkMode((enabled) => !enabled)}
        notice={error}
      />
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        activeView={activeView}
        onNavigate={setActiveView}
        profile={profile}
        onLogout={() => void handleLogout()}
      />
      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>@{profile.username}</span>
            <span className="crumb-divider">/</span>
            <strong>{pageTitles[activeView]}</strong>
          </div>
          <div className="topbar-actions">
            <span className="data-timestamp">{data ? `Snapshot ${activeDate}` : "Your workspace"}</span>
            <button
              className="icon-button theme-toggle"
              type="button"
              aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
              title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
              onClick={() => setDarkMode((enabled) => !enabled)}
            >
              {darkMode ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              className={`icon-button refresh-button ${refreshing ? "is-refreshing" : ""}`}
              type="button"
              aria-label="Refresh wealth snapshot"
              onClick={() => void reload()}
              disabled={refreshing || loading || activeView === "settings"}
            >
              <RefreshCw size={16} />
            </button>
            <label className="currency-select">
              <span className="sr-only">Reporting currency</span>
              <select value={currency} onChange={(event) => setCurrency(event.target.value as Currency)}>
                <option
                  value="EUR"
                  disabled={!hasCurrencyPath(profile.base_currency, "EUR", data, profile.usd_per_eur)}
                >
                  EUR €
                </option>
                <option
                  value="USD"
                  disabled={!hasCurrencyPath(profile.base_currency, "USD", data, profile.usd_per_eur)}
                >
                  USD $
                </option>
                <option
                  value="RON"
                  disabled={!hasCurrencyPath(profile.base_currency, "RON", data, profile.usd_per_eur)}
                >
                  RON
                </option>
              </select>
              <ChevronDown size={13} aria-hidden="true" />
            </label>
            <span className="topbar-avatar" aria-label={`Signed in as ${profile.username}`}>
              {profile.username.slice(0, 1).toUpperCase()}
            </span>
          </div>
        </header>

        <div className="main-scroll">
          {data?.sample_data && (
            <div className="sample-banner">
              <AlertTriangle size={15} />
              <span><strong>Legacy sample data.</strong> These historical demo holdings are not connected to this application account or live data.</span>
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
          {activeView === "settings" ? (
            <SettingsView
              profile={profile}
              onSaved={handleProfileSaved}
              onLogout={() => void handleLogout()}
            />
          ) : loading && !data ? (
            <div className="loading-state" role="status">
              <span className="loading-orbit" />
              <strong>Bringing your picture together…</strong>
              <span>Loading your private workspace</span>
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
                  onOpenPortfolio={() => setActiveView("portfolio")}
                />
              )}
              {activeView === "portfolio" && (
                <PortfolioView data={data} currency={currency} onSaved={reload} />
              )}
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
              {activeView === "compensation" && (
                <CompensationView data={data} currency={currency} onSaved={reload} />
              )}
              {activeView === "assistant" && <AssistantView data={data} currency={currency} />}
            </>
          ) : !error ? (
            <div className="api-error-empty">
              <strong>Your wealth snapshot isn’t available yet.</strong>
              <button className="button button-primary" type="button" onClick={() => void reload()}>Try again</button>
            </div>
          ) : null}
          <footer className="page-footer">
            <span>Northstar Wealth · private personal workspace</span>
            <span>No automatic trades · you control your records</span>
          </footer>
        </div>
      </main>

      {goalDialogOpen && (
        <GoalDialog
          currency={currency}
          accounts={data?.accounts ?? []}
          holdings={data?.holdings ?? []}
          deposits={data?.deposits ?? []}
          onClose={() => setGoalDialogOpen(false)}
          onCreated={handleGoalCreated}
        />
      )}
      {allocationOpen && <AllocationSimulator currency={currency} onClose={() => setAllocationOpen(false)} />}
    </div>
  );
}
