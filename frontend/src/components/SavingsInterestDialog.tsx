import { useState, type FormEvent } from "react";
import { Percent, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountSummary } from "../types";

interface SavingsInterestDialogProps {
  account: AccountSummary;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function SavingsInterestDialog({ account, onClose, onSaved }: SavingsInterestDialogProps) {
  const [walletId, setWalletId] = useState(account.subaccounts[0]?.id ?? "");
  const wallet = account.subaccounts.find((candidate) => candidate.id === walletId);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(rate: string | null, startDate: string | null) {
    if (!wallet) return;
    setSaving(true);
    setError("");
    try {
      await api.updateSubaccountInterest(account.id, wallet.id, {
        annual_interest_rate: rate,
        interest_start_date: startDate,
      });
      await onSaved();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The interest settings could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const percent = Number(form.get("interestPercent"));
    void save(String(percent / 100), String(form.get("interestStart") || localDateValue()));
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card account-dialog" role="dialog" aria-modal="true" aria-labelledby="interest-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">{account.display_name} · economy account</div>
            <h2 id="interest-dialog-title">Monthly interest</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          Set a yearly rate for a wallet. One twelfth of it is credited to the balance each month on the same day of the month, so interest also earns interest.
        </p>
        <form className="goal-form" onSubmit={submit} key={walletId}>
          <label className="form-field">
            <span>Wallet</span>
            <select value={walletId} onChange={(event) => setWalletId(event.target.value)}>
              {account.subaccounts.map((subaccount) => (
                <option value={subaccount.id} key={subaccount.id}>
                  {subaccount.currency}
                  {subaccount.annual_interest_rate
                    ? ` · ${(Number(subaccount.annual_interest_rate) * 100).toFixed(2)}% a year`
                    : " · no interest"}
                </option>
              ))}
            </select>
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Annual interest rate (%)</span>
              <input
                name="interestPercent"
                type="number"
                required
                min="0"
                max="100"
                step="0.01"
                defaultValue={wallet?.annual_interest_rate ? String(Number(wallet.annual_interest_rate) * 100) : ""}
                placeholder="e.g. 3.5"
              />
            </label>
            <label className="form-field">
              <span>Interest counts from</span>
              <input name="interestStart" type="date" defaultValue={wallet?.interest_start_date ?? localDateValue()} />
            </label>
          </div>
          <div className="account-storage-note">
            <Percent size={15} />
            <span>Past months after the start date are credited once, the next time the app loads. Interest is an estimate; it is not read from your bank.</span>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            {wallet?.annual_interest_rate && (
              <button className="button button-secondary" type="button" disabled={saving} onClick={() => void save(null, null)}>
                Stop interest
              </button>
            )}
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving || !wallet}>
              {saving ? "Saving…" : "Save interest"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
