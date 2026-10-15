import { useState, type FormEvent } from "react";
import { ArrowUpRight, X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { AccountSummary } from "../types";

interface SpendCashDialogProps {
  account: AccountSummary;
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function SpendCashDialog({ account, onClose, onSaved }: SpendCashDialogProps) {
  const [subaccountId, setSubaccountId] = useState(
    account.subaccounts.find((subaccount) => subaccount.is_primary)?.id ??
      account.subaccounts[0]?.id ??
      "",
  );
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const selectedWallet = account.subaccounts.find(
    (subaccount) => subaccount.id === subaccountId,
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWallet) {
      setError("Choose a currency wallet before recording spending.");
      return;
    }
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    try {
      const record = await api.spendCash({
        idempotency_key: idempotencyKey,
        subaccount_id: selectedWallet.id,
        amount: String(form.get("amount") ?? ""),
        spend_date: String(form.get("spendDate") ?? ""),
      });
      await onSaved(
        `Spent ${amount(record.amount, record.currency, 2)} from ${record.account_name}.`,
      );
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The spending could not be recorded.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card extra-cash-dialog" role="dialog" aria-modal="true" aria-labelledby="spend-cash-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Spending · deducted from your balance</div>
            <h2 id="spend-cash-title">Spend from {account.display_name}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Record money spent from this bank account. This reduces tracked cash only; it does not create a transfer, trade, or forecast.
        </p>
        <form className="goal-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Spend from</span>
            <select
              value={subaccountId}
              onChange={(event) => setSubaccountId(event.target.value)}
              required={account.subaccounts.length > 0}
              disabled={account.subaccounts.length === 0}
            >
              {account.subaccounts.map((subaccount) => (
                <option value={subaccount.id} key={subaccount.id}>
                  {subaccount.currency} · {amount(subaccount.cash_balance, subaccount.currency, 2)} available
                </option>
              ))}
              {account.subaccounts.length === 0 && <option value="">No currency wallets available</option>}
            </select>
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Amount spent ({selectedWallet?.currency ?? account.currency})</span>
              <input
                name="amount"
                type="number"
                required
                min="0.01"
                max={selectedWallet?.cash_balance}
                step="0.01"
                placeholder="Enter amount spent"
              />
            </label>
            <label className="form-field">
              <span>Spent on</span>
              <input name="spendDate" type="date" defaultValue={localDateValue()} required />
            </label>
          </div>
          <div className="account-storage-note">
            <ArrowUpRight size={15} />
            <span>The spending record and reduced wallet balance are saved together. You cannot spend more than the available balance.</span>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving || !selectedWallet}>
              {saving ? "Recording…" : "Record spend"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
