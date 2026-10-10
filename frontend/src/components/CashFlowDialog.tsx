import { useState, type FormEvent } from "react";
import { CalendarClock, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { Currency, FlowKind, Recurrence } from "../types";

interface CashFlowDialogProps {
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
  { value: "windfall", label: "Windfall · income" },
  { value: "dividend", label: "Dividend · income" },
  { value: "interest", label: "Interest · income" },
  { value: "bill", label: "Bill · expense" },
  { value: "contribution", label: "Investment contribution · transfer" },
];

export function CashFlowDialog({ currency, onClose, onCreated }: CashFlowDialogProps) {
  const [kind, setKind] = useState<FlowKind>("salary");
  const [recurrence, setRecurrence] = useState<Recurrence>("monthly");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const endDate = String(form.get("endDate") ?? "");

    try {
      await api.createCashFlowSchedule({
        label: String(form.get("label") ?? "").trim(),
        kind,
        amount: String(form.get("amount") ?? ""),
        currency: String(form.get("currency")) as Currency,
        recurrence,
        start_date: String(form.get("startDate") ?? ""),
        ...(recurrence !== "one_time" && endDate ? { end_date: endDate } : {}),
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
            <div className="eyebrow">Plan it; confirm it later</div>
            <h2 id="cashflow-dialog-title">Add a cash-flow forecast</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          A forecast helps plan ahead. It does not change account balances or count as available cash.
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
              <input name="amount" type="number" required min="0.01" max="100000000" step="0.01" placeholder="5200" />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Currency</span>
              <select name="currency" defaultValue={currency}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
              </select>
            </label>
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
                <span>This forecast appears once and never changes available cash.</span>
              </div>
            )}
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Add forecast"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
