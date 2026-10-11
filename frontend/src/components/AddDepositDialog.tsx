import { useState, type FormEvent } from "react";
import { Landmark, X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { AccountSummary } from "../types";

interface AddDepositDialogProps {
  account: AccountSummary;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function AddDepositDialog({ account, onClose, onCreated }: AddDepositDialogProps) {
  const [subaccountId, setSubaccountId] = useState(
    account.subaccounts.find((wallet) => wallet.is_primary)?.id
      ?? account.subaccounts[0]?.id
      ?? "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    try {
      await api.createDeposit({
        account_id: account.id,
        subaccount_id: subaccountId,
        name: String(form.get("name") ?? "").trim(),
        principal: String(form.get("principal") ?? ""),
        start_date: String(form.get("startDate") ?? ""),
        period_months: Number(form.get("periodMonths")),
        annual_profit_rate: String(Number(form.get("annualRatePercent")) / 100),
        capitalization: form.get("capitalization") === "on",
      });
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The fixed deposit could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="deposit-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Fixed deposit · {account.display_name}</div>
            <h2 id="deposit-dialog-title">Add a term deposit</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          The principal will be moved from the selected account wallet into the tracked deposit.
          Interest is an estimate, not a bank confirmation.
        </p>
        <form className="goal-form" onSubmit={submit}>
          <label className="form-field">
            <span>Deposit name</span>
            <input name="name" required minLength={2} maxLength={80} placeholder="e.g. 12-month EUR deposit" autoFocus />
          </label>
          <label className="form-field">
            <span>Fund from</span>
            <select
              value={subaccountId}
              onChange={(event) => setSubaccountId(event.target.value)}
              required
            >
              {account.subaccounts.map((wallet) => (
                <option value={wallet.id} key={wallet.id}>
                  {wallet.currency} · available {amount(wallet.cash_balance, wallet.currency, 2)}
                </option>
              ))}
            </select>
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Principal ({account.subaccounts.find((wallet) => wallet.id === subaccountId)?.currency ?? account.currency})</span>
              <input name="principal" type="number" required min="0.01" step="0.01" placeholder="Amount" />
            </label>
            <label className="form-field">
              <span>Annual profit rate (%)</span>
              <input name="annualRatePercent" type="number" required min="0" max="100" step="0.01" placeholder="e.g. 5.25" />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Start date</span>
              <input name="startDate" type="date" defaultValue={localDateValue()} required />
            </label>
            <label className="form-field">
              <span>Term (months)</span>
              <input name="periodMonths" type="number" required min="1" max="1200" step="1" defaultValue="12" />
            </label>
          </div>
          <label className="form-checkbox cashflow-auto-post">
            <input name="capitalization" type="checkbox" />
            <span>Capitalize interest monthly (add it to principal)</span>
          </label>
          <div className="account-storage-note">
            {account.subaccounts.length === 0
              ? "Add a currency wallet to this account first."
              : "If capitalization is off, interest is calculated as simple interest and paid at maturity. The principal is debited from the selected wallet once."}
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose} disabled={saving}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving || !subaccountId}>
              <Landmark size={15} /> {saving ? "Saving…" : "Add deposit"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
