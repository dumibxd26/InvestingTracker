import { useEffect, useState, type FormEvent } from "react";
import { ArrowRightLeft, CircleHelp, KeyRound, LogOut, Save, ShieldCheck } from "lucide-react";
import { ApiError, api } from "../api";
import type { Currency, UserProfile } from "../types";

interface SettingsViewProps {
  profile: UserProfile;
  onSaved: (profile: UserProfile) => Promise<void>;
  onLogout: () => void;
}

export function SettingsView({ profile, onSaved, onLogout }: SettingsViewProps) {
  const [displayName, setDisplayName] = useState(profile.display_name);
  const [baseCurrency, setBaseCurrency] = useState<Currency>(profile.base_currency);
  const [usdPerEur, setUsdPerEur] = useState(profile.usd_per_eur ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    setDisplayName(profile.display_name);
    setBaseCurrency(profile.base_currency);
    setUsdPerEur(profile.usd_per_eur ?? "");
  }, [profile]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.updateProfile({
        display_name: displayName,
        base_currency: baseCurrency,
        usd_per_eur: usdPerEur.trim() || null,
      });
      await onSaved(updated);
      setMessage("Your personal settings are saved.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Your settings could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Your application account</div>
          <h1>Profile settings.</h1>
          <p>Manage your sign-in profile and the currency assumptions used to value your own accounts.</p>
        </div>
      </div>
      <div className="settings-grid">
        <section className="panel settings-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">Personal profile</div>
              <h2>Workspace preferences</h2>
            </div>
            <span className="policy-icon"><ArrowRightLeft size={18} /></span>
          </div>
          <form className="settings-form" onSubmit={save}>
            <div className="settings-identity">
              <span className="profile-avatar">{profile.username.slice(0, 2).toUpperCase()}</span>
              <span><strong>@{profile.username}</strong><small>Application username · used to sign in</small></span>
            </div>
            <label className="form-field">
              <span>Display name</span>
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required minLength={2} maxLength={80} />
            </label>
            <label className="form-field">
              <span>Base reporting currency</span>
              <select value={baseCurrency} onChange={(event) => setBaseCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
                <option value="RON">RON · Romanian leu</option>
              </select>
            </label>
            <label className="form-field">
              <span>USD per EUR reference rate <small>optional · manually supplied</small></span>
              <input
                type="number"
                min="0.000001"
                max="100"
                step="0.000001"
                value={usdPerEur}
                onChange={(event) => setUsdPerEur(event.target.value)}
                placeholder="No rate configured"
              />
              <small>Enter how many USD equal 1 EUR. The app does not silently substitute a market rate.</small>
            </label>
            {error && <div className="inline-error" role="alert">{error}</div>}
            {message && <div className="settings-saved" role="status">{message}</div>}
            <div className="settings-save-row">
              <span className="settings-hint">Your settings are saved to your application profile.</span>
              <button className="button button-primary" type="submit" disabled={busy}>
                <Save size={15} /> {busy ? "Saving…" : "Save settings"}
              </button>
            </div>
          </form>
          <div className="settings-logout-row">
            <span>
              <strong>Application account</strong>
              <small>Sign out of @{profile.username} on this browser.</small>
            </span>
            <button className="button button-secondary" type="button" onClick={onLogout}>
              <LogOut size={15} /> Sign out
            </button>
          </div>
        </section>
        <aside className="settings-aside">
          <section className="panel settings-info-panel">
            <span className="next-step-icon"><ShieldCheck size={18} /></span>
            <div className="eyebrow">Account separation</div>
            <h2>Your portfolio belongs to this sign-in.</h2>
            <p>Accounts, goals, cash-flow schedules, policies, and recommendation history are scoped to your registered application user.</p>
          </section>
          <section className="panel settings-info-panel">
            <span className="next-step-icon"><KeyRound size={18} /></span>
            <div className="eyebrow">Password security</div>
            <h2>Passwords are not stored in plain text.</h2>
            <p>Sign-in uses Argon2 password hashing and revocable, expiring login sessions. Password recovery is not enabled in this local prototype.</p>
          </section>
          <div className="privacy-note"><CircleHelp size={15} /><span>Manual bank/broker accounts are separate from this username/password application account. Bank connectivity is not enabled.</span></div>
        </aside>
      </div>
    </div>
  );
}
