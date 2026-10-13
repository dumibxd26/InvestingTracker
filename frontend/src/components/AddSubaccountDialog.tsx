import { useState, type FormEvent } from "react";
import { WalletCards, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountSummary, Currency } from "../types";

interface AddSubaccountDialogProps {
  account: AccountSummary;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

const currencyLabels: Record<Currency, string> = {
  EUR: "EUR · Euro",
  USD: "USD · US dollar",
  RON: "RON · Romanian leu",
};

export function AddSubaccountDialog({
  account,
  onClose,
  onCreated,
}: AddSubaccountDialogProps) {
  const [currency, setCurrency] = useState<Currency | "">("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const supportsInterest = account.account_type !== "EMPLOYER_PLAN";
  const availableCurrencies = (["EUR", "USD", "RON"] as Currency[]).filter(
    (candidate) => !account.subaccounts.some((subaccount) => subaccount.currency === candidate),
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!currency) {
      setError("Choose a currency for the new sub-account.");
      return;
    }
    setSaving(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const interestPercent = supportsInterest ? String(form.get("interestPercent") ?? "").trim() : "";
    try {
      await api.createAccountSubaccount(account.id, {
        currency,
        opening_balance: String(form.get("openingBalance") || "0"),
        ...(interestPercent
          ? {
              annual_interest_rate: String(Number(interestPercent) / 100),
              interest_start_date: String(form.get("interestStart") || ""),
            }
          : {}),
      });
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The currency sub-account could not be added.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="modal-card account-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="subaccount-dialog-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">{account.display_name} · currency wallet</div>
            <h2 id="subaccount-dialog-title">Add a sub-account</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Add another currency wallet under this bank or broker. Each account can have one
          sub-account per currency.
        </p>
        {availableCurrencies.length === 0 ? (
          <div className="inline-error" role="status">
            This account already has EUR, USD, and RON sub-accounts.
          </div>
        ) : (
          <form className="goal-form" onSubmit={submit}>
            <label className="form-field">
              <span>Currency</span>
              <select
                value={currency}
                onChange={(event) => setCurrency(event.target.value as Currency | "")}
                required
              >
                <option value="" disabled>Choose a currency</option>
                {availableCurrencies.map((candidate) => (
                  <option key={candidate} value={candidate}>{currencyLabels[candidate]}</option>
                ))}
              </select>
            </label>
            {account.account_type !== "EMPLOYER_PLAN" && (
              <label className="form-field">
                <span>Opening cash balance</span>
                <input
                  name="openingBalance"
                  type="number"
                  min="0"
                  max="100000000"
                  step="0.01"
                  defaultValue="0"
                  required
                />
              </label>
            )}
            {supportsInterest && (
              <div className="grant-tax-fields">
                <div className="eyebrow">Monthly interest · optional</div>
                <div className="form-row">
                  <label className="form-field">
                    <span>Annual interest rate (%)</span>
                    <input name="interestPercent" type="number" min="0" max="100" step="0.01" placeholder="e.g. 3.5" />
                  </label>
                  <label className="form-field">
                    <span>Interest counts from</span>
                    <input name="interestStart" type="date" defaultValue={new Date().toLocaleDateString("sv-SE")} />
                  </label>
                </div>
              </div>
            )}
            <div className="account-storage-note">
              <WalletCards size={15} />
              <span>Balances are tracked separately per currency. When adding a stock, choose any currency wallet; the purchase cost is converted and deducted from that wallet.</span>
            </div>
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
              <button className="button button-primary" type="submit" disabled={saving}>
                {saving ? "Adding…" : "Add sub-account"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
