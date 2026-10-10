import { useState, type FormEvent } from "react";
import { Landmark, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountType, Currency, UserProfile } from "../types";

interface AccountDialogProps {
  profile: UserProfile;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

export function AccountDialog({ profile, onClose, onCreated }: AccountDialogProps) {
  const [currency, setCurrency] = useState<Currency>(profile.base_currency);
  const [accountType, setAccountType] = useState<AccountType>("BROKERAGE");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const providerCode = String(form.get("provider") ?? "MANUAL");

    try {
      await api.createAccount({
        display_name: String(form.get("name") ?? "").trim(),
        provider_code: providerCode,
        account_type: accountType,
        currency,
        opening_cash: String(form.get("openingCash") || "0"),
      });
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The account could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Saved in your local database</div>
            <h2 id="account-dialog-title">Add an account</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          Set up a manual account and opening cash balance. This does not connect to a broker or import holdings.
        </p>
        <form className="goal-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Account name</span>
            <input name="name" required minLength={2} maxLength={80} placeholder="e.g. Main brokerage" autoFocus />
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Institution</span>
              <select name="provider" defaultValue="MANUAL">
                <option value="MANUAL">Manual entry</option>
                <option value="INTERACTIVE_BROKERS">Interactive Brokers</option>
                <option value="TRADE_REPUBLIC">Trade Republic</option>
                <option value="XTB">XTB</option>
                <option value="CHARLES_SCHWAB">Charles Schwab</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
            <label className="form-field">
              <span>Account type</span>
              <select value={accountType} onChange={(event) => setAccountType(event.target.value as AccountType)}>
                <option value="BROKERAGE">Brokerage</option>
                <option value="BANK">Bank account</option>
                <option value="SAVINGS">Savings / deposit</option>
                <option value="EMPLOYER_PLAN">Employer plan</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Account currency</span>
              <select value={currency} onChange={(event) => setCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
                <option value="RON">RON · Romanian leu</option>
              </select>
            </label>
            <label className="form-field">
              <span>{accountType === "EMPLOYER_PLAN" ? "Opening cash balance · unavailable" : "Opening cash balance"}</span>
              {accountType === "EMPLOYER_PLAN" ? (
                <input name="openingCash" type="number" value="0" disabled />
              ) : (
                <input name="openingCash" type="number" min="0" max="100000000" step="0.01" defaultValue="0" />
              )}
            </label>
          </div>
          <div className="account-storage-note">
            <Landmark size={15} />
            <span>Account details and opening cash are stored in this app’s PostgreSQL volume and survive container restarts. No sign-in or broker sync is enabled yet.</span>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save account"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
