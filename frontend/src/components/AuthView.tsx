import { useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, Moon, ShieldCheck, Sparkles, Sun } from "lucide-react";
import { api, ApiError } from "../api";
import type { AuthResponse, Currency } from "../types";

interface AuthViewProps {
  onAuthenticated: (response: AuthResponse) => void;
  darkMode: boolean;
  onToggleTheme: () => void;
  notice?: string;
}

export function AuthView({
  onAuthenticated,
  darkMode,
  onToggleTheme,
  notice,
}: AuthViewProps) {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [currency, setCurrency] = useState<Currency | "">("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") ?? "").trim().toLowerCase();
    const password = String(form.get("password") ?? "");
    try {
      if (mode === "login") {
        onAuthenticated(await api.login(username, password));
        return;
      }
      if (!currency) {
        setError("Choose your base reporting currency to continue.");
        return;
      }
      const displayName = String(form.get("displayName") ?? "").trim();
      const usdPerEur = String(form.get("usdPerEur") ?? "").trim();
      onAuthenticated(
        await api.register({
          username,
          password,
          ...(displayName ? { display_name: displayName } : {}),
          base_currency: currency,
          ...(usdPerEur ? { usd_per_eur: usdPerEur } : {}),
        }),
      );
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "We could not complete sign-in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-brand-panel">
        <a className="brand auth-brand" href="#" aria-label="Northstar home">
          <span className="brand-mark"><span /></span>
          <span className="brand-name">northstar</span>
        </a>
        <div className="auth-brand-content">
          <span className="auth-glow-icon"><Sparkles size={20} /></span>
          <div className="eyebrow">A clearer relationship with money</div>
          <h1>Your whole financial picture.<br /><em>Finally in one place.</em></h1>
          <p>Bring your accounts, goals, and future cash flows together. Start with a private application account, then add the financial accounts you want to track.</p>
          <div className="auth-promise"><ShieldCheck size={16} /><span>Your data stays in your local PostgreSQL database.</span></div>
        </div>
        <div className="auth-brand-footer">Personal financial workspace · No automatic trades</div>
      </section>

      <section className="auth-form-panel">
        <button
          className="icon-button auth-theme-toggle"
          type="button"
          aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
          title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
          onClick={onToggleTheme}
        >
          {darkMode ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <div className="auth-form-wrap">
          <div className="auth-eyebrow">YOUR PRIVATE WORKSPACE</div>
          <h2>{mode === "register" ? "Create your account" : "Welcome back"}</h2>
          <p className="auth-description">
            {mode === "register"
              ? "Set up your personal sign-in. Your workspace starts empty—add only what you want to track."
              : "Sign in to open your financial workspace."}
          </p>
          {notice && <div className="auth-notice" role="status">{notice}</div>}

          <form className="auth-form" onSubmit={submit}>
            {mode === "register" && (
              <>
                <label className="form-field">
                  <span>Display name <small>optional</small></span>
                  <input name="displayName" autoComplete="name" maxLength={80} placeholder="What should we call you?" />
                </label>
                <label className="form-field">
                  <span>Reporting currency</span>
                  <select
                    value={currency}
                    required
                    onChange={(event) => setCurrency(event.target.value as Currency | "")}
                  >
                    <option value="" disabled>Choose your base currency</option>
                    <option value="EUR">EUR · Euro</option>
                    <option value="USD">USD · US dollar</option>
                    <option value="RON">RON · Romanian leu</option>
                  </select>
                </label>
              </>
            )}
            <label className="form-field">
              <span>Username</span>
              <input
                name="username"
                autoComplete="username"
                required
                minLength={3}
                maxLength={32}
                placeholder="Choose a username"
              />
              {mode === "register" && <small>3–32 letters, numbers, dots, dashes, or underscores</small>}
            </label>
            <label className="form-field">
              <span>Password</span>
              <div className="auth-password-wrap">
                <input
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  required
                  minLength={mode === "register" ? 12 : 1}
                  maxLength={128}
                  placeholder={mode === "register" ? "At least 12 characters" : "Your password"}
                />
                <button
                  type="button"
                  className="icon-button small"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((visible) => !visible)}
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              {mode === "register" && <small>Choose a long, unique password. It will be stored as a one-way hash.</small>}
            </label>
            {mode === "register" && (
              <label className="form-field">
                <span>Manual USD per EUR reference <small>optional</small></span>
                <input
                  name="usdPerEur"
                  type="number"
                  min="0.000001"
                  max="100"
                  step="0.000001"
                  placeholder="Leave blank until you set a rate"
                />
                <small>Only needed when valuing USD and EUR together. No exchange rate is prefilled.</small>
              </label>
            )}
            {error && <div className="inline-error" role="alert">{error}</div>}
            <button className="button button-primary auth-submit" type="submit" disabled={busy}>
              {busy
                ? mode === "register" ? "Creating your account…" : "Signing in…"
                : mode === "register" ? "Create personal account" : "Sign in"}
              <ArrowRight size={16} />
            </button>
          </form>

          <div className="auth-mode-switch">
            {mode === "register" ? "Already have an account?" : "New to Northstar?"}
            <button
              type="button"
              onClick={() => {
                setError("");
                setMode(mode === "register" ? "login" : "register");
              }}
            >
              {mode === "register" ? "Sign in" : "Create an account"}
            </button>
          </div>
          <p className="auth-local-note">This local prototype has no email recovery or cloud backup yet. Keep your password safe.</p>
        </div>
      </section>
    </main>
  );
}
