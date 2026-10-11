import { useState, type FormEvent } from "react";
import { CalendarClock, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountSummary, Currency, FlowKind, Recurrence } from "../types";

interface CashFlowDialogProps {
  accounts: AccountSummary[];
  currency: Currency;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

function localDateValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

const flowKinds: { value: FlowKind; label: string }[] = [
  { value: "salary", label: "Salary · income" },
  { value: "bonus", label: "Bonus · income" },
  { value: "windfall", label: "Extra cash · forecast" },
  { value: "dividend", label: "Dividend · income" },
  { value: "interest", label: "Interest · income" },
  { value: "bill", label: "Bill · expense" },
  { value: "contribution", label: "Investment contribution · transfer" },
];

export function CashFlowDialog({ accounts, currency, onClose, onCreated }: CashFlowDialogProps) {
  const liquidAccounts = accounts.filter((account) => account.account_type !== "EMPLOYER_PLAN");
  const wallets = liquidAccounts.flatMap((account) =>
    account.subaccounts.map((subaccount) => ({ account, subaccount })),
  );
  const defaultWallet =
    wallets.find(({ subaccount }) => subaccount.currency === currency) ?? wallets[0];
  const [kind, setKind] = useState<FlowKind>("salary");
  const [recurrence, setRecurrence] = useState<Recurrence>("monthly");
  const [autoPost, setAutoPost] = useState(wallets.length > 0);
  const [subaccountId, setSubaccountId] = useState(defaultWallet?.subaccount.id ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const isSalaryOrBonus = kind === "salary" || kind === "bonus";
  const shouldAutoPost = isSalaryOrBonus && autoPost;
  const selectedWallet = wallets.find(({ subaccount }) => subaccount.id === subaccountId);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (shouldAutoPost && !selectedWallet) {
      setError("Add a bank, savings, or brokerage currency wallet before scheduling an automatic credit.");
      return;
    }
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const endDate = String(form.get("endDate") ?? "");

    try {
      await api.createCashFlowSchedule({
        label: String(form.get("label") ?? "").trim(),
        kind,
        amount: String(form.get("amount") ?? ""),
        currency: shouldAutoPost && selectedWallet
          ? selectedWallet.subaccount.currency
          : String(form.get("currency")) as Currency,
        recurrence,
        start_date: String(form.get("startDate") ?? ""),
        ...(recurrence !== "one_time" && endDate ? { end_date: endDate } : {}),
        auto_post: shouldAutoPost,
        ...(shouldAutoPost && selectedWallet
          ? {
              account_id: selectedWallet.account.id,
              subaccount_id: selectedWallet.subaccount.id,
            }
          : {}),
      });
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The cash-flow schedule could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card cashflow-dialog" role="dialog" aria-modal="true" aria-labelledby="cashflow-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">{shouldAutoPost ? "Schedule a tracked balance credit" : "Forecast · does not change balances"}</div>
            <h2 id="cashflow-dialog-title">Add a cash-flow schedule</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          {shouldAutoPost
            ? "On or after each scheduled date, Northstar adds the amount to your selected wallet once the app next refreshes. This is bookkeeping only—not a bank transfer."
            : "A forecast helps plan ahead. It does not change account balances or count as available cash."}
        </p>
        <form className="goal-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>What is this for?</span>
            <input name="label" required minLength={2} maxLength={100} placeholder="e.g. Monthly salary" autoFocus />
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Type</span>
              <select value={kind} onChange={(event) => setKind(event.target.value as FlowKind)}>
                {flowKinds.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="form-field">
              <span>Amount</span>
              <input name="amount" type="number" required min="0.01" max="100000000" step="0.01" placeholder="Enter amount" />
            </label>
          </div>
          {isSalaryOrBonus && (
            <>
              <label className="form-field">
                <span>Deposit into</span>
                <select
                  value={subaccountId}
                  onChange={(event) => setSubaccountId(event.target.value)}
                  required={shouldAutoPost}
                  disabled={wallets.length === 0}
                >
                  {wallets.map(({ account, subaccount }) => (
                    <option value={subaccount.id} key={subaccount.id}>
                      {account.display_name} · {subaccount.currency} · {account.account_type.toLowerCase().replace("_", " ")}
                    </option>
                  ))}
                  {wallets.length === 0 && <option value="">Add a liquid account first</option>}
                </select>
              </label>
              <label className="form-checkbox cashflow-auto-post">
                <input
                  type="checkbox"
                  checked={autoPost}
                  onChange={(event) => setAutoPost(event.target.checked)}
                />
                <span>Automatically credit this wallet on each scheduled date</span>
              </label>
            </>
          )}
          <div className="form-row">
            {!shouldAutoPost && (
              <label className="form-field">
                <span>Forecast currency</span>
                <select name="currency" defaultValue={currency}>
                  <option value="EUR">EUR · Euro</option>
                  <option value="USD">USD · US dollar</option>
                  <option value="RON">RON · Romanian leu</option>
                </select>
              </label>
            )}
            <label className="form-field">
              <span>How often?</span>
              <select value={recurrence} onChange={(event) => setRecurrence(event.target.value as Recurrence)}>
                <option value="one_time">One time</option>
                <option value="monthly">Every month</option>
                <option value="quarterly">Every 3 months</option>
                <option value="annual">Every year</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>{recurrence === "one_time" ? "Expected date" : "First expected date"}</span>
              <input name="startDate" type="date" defaultValue={localDateValue()} required />
            </label>
            {recurrence !== "one_time" ? (
              <label className="form-field">
                <span>Last expected date <small>optional</small></span>
                <input name="endDate" type="date" />
              </label>
            ) : (
              <div className="cashflow-one-time-note">
                <CalendarClock size={15} />
                <span>{shouldAutoPost ? "One credit on this date." : "This forecast appears once."}</span>
              </div>
            )}
          </div>
          {shouldAutoPost && (
            <div className="account-storage-note">
              The entered amount is credited exactly as scheduled; variable or uncertain bonuses should remain forecast-only until known.
            </div>
          )}
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving || (shouldAutoPost && !selectedWallet)}>
              {saving ? "Saving…" : shouldAutoPost ? "Save auto-credit" : "Add forecast"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
