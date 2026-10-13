import { useState, type FormEvent } from "react";
import { CircleDollarSign, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountSummary, Currency } from "../types";

interface ExtraCashDialogProps {
  accounts: AccountSummary[];
  baseCurrency: Currency;
  initialAccountId?: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function ExtraCashDialog({
  accounts,
  baseCurrency,
  initialAccountId,
  onClose,
  onSaved,
}: ExtraCashDialogProps) {
  const liquidAccounts = accounts.filter((account) => account.account_type !== "EMPLOYER_PLAN");
  const liquidSubaccounts = liquidAccounts.flatMap((account) =>
    account.subaccounts.map((subaccount) => ({ account, subaccount })),
  );
  const preferredWallets = initialAccountId
    ? liquidSubaccounts.filter(({ account }) => account.id === initialAccountId)
    : liquidSubaccounts;
  const [subaccountId, setSubaccountId] = useState(
    preferredWallets.find(({ subaccount }) => subaccount.currency === baseCurrency)?.subaccount.id ??
      preferredWallets[0]?.subaccount.id ??
      liquidSubaccounts[0]?.subaccount.id ??
      "",
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const selectedWallet = liquidSubaccounts.find(
    ({ subaccount }) => subaccount.id === subaccountId,
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWallet) {
      setError("Add a bank, savings, or brokerage currency sub-account before recording extra cash.");
      return;
    }
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    try {
      await api.recordExtraCash({
        account_id: selectedWallet.account.id,
        subaccount_id: selectedWallet.subaccount.id,
        source: String(form.get("source") ?? "").trim(),
        amount: String(form.get("amount") ?? ""),
        received_date: String(form.get("receivedDate") ?? ""),
        idempotency_key: crypto.randomUUID(),
      });
      await onSaved();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The received cash could not be recorded.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card extra-cash-dialog" role="dialog" aria-modal="true" aria-labelledby="extra-cash-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Received · saved to your balance</div>
            <h2 id="extra-cash-title">Add extra cash</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Record a bonus, refund, gift, or other money that has already arrived. We’ll add it once to the selected account and list it as received—not as a forecast.
        </p>
        <form className="goal-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Where did it come from?</span>
            <input
              name="source"
              required
              minLength={2}
              maxLength={100}
              placeholder="e.g. Annual bonus, tax refund, or gift"
              autoFocus
            />
          </label>
          <label className="form-field">
            <span>Deposit into</span>
            <select
              value={subaccountId}
              onChange={(event) => setSubaccountId(event.target.value)}
              required={liquidSubaccounts.length > 0}
              disabled={liquidSubaccounts.length === 0}
            >
              {liquidSubaccounts.map(({ account, subaccount }) => (
                <option value={subaccount.id} key={subaccount.id}>
                  {account.display_name} · {subaccount.currency} · {account.account_type.toLowerCase().replace("_", " ")}
                </option>
              ))}
              {liquidSubaccounts.length === 0 && <option value="">Add a liquid currency sub-account first</option>}
            </select>
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Amount received ({selectedWallet?.subaccount.currency ?? baseCurrency})</span>
              <input name="amount" type="number" required min="0.01" max="100000000" step="0.01" placeholder="Enter amount received" />
            </label>
            <label className="form-field">
              <span>Received on</span>
              <input name="receivedDate" type="date" defaultValue={localDateValue()} required />
            </label>
          </div>
          <div className="account-storage-note">
            <CircleDollarSign size={15} />
            <span>This receipt and the selected currency sub-account balance are saved together in one database transaction. Submitting the same entry twice is protected against duplicate posting.</span>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving || liquidSubaccounts.length === 0}>
              {saving ? "Recording…" : "Record received cash"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
