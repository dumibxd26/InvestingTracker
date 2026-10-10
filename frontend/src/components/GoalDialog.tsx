import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { api, ApiError } from "../api";
import type { Currency, GoalCreatePayload, GoalType } from "../types";

interface GoalDialogProps {
  currency: Currency;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

export function GoalDialog({ currency, onClose, onCreated }: GoalDialogProps) {
  const [goalType, setGoalType] = useState<GoalType | "">("");
  const [targetCurrency, setTargetCurrency] = useState<Currency>(currency);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const target = String(form.get("target") ?? "");
    const targetDate = String(form.get("targetDate") ?? "");
    const priority = String(form.get("priority") ?? "");
    const riskLevel = String(form.get("riskLevel") ?? "");
    const flexibility = String(form.get("flexibility") ?? "");
    if (!goalType || !priority || !riskLevel || !flexibility) {
      setError("Choose a goal type, priority, risk comfort, and deadline flexibility.");
      setSaving(false);
      return;
    }
    const payload: GoalCreatePayload = {
      name,
      goal_type: goalType,
      target_currency: targetCurrency,
      priority: Number(priority),
      risk_level: riskLevel as GoalCreatePayload["risk_level"],
      monthly_contribution: String(form.get("monthlyContribution") || "0"),
      flexibility: flexibility as GoalCreatePayload["flexibility"],
    };
    const fixedPercent = String(form.get("fixedPercent") ?? "").trim();
    if (fixedPercent) {
      payload.fixed_percent = String(Number(fixedPercent) / 100);
    }
    if (goalType === "passive_income") {
      payload.target_annual_income = target;
    } else {
      payload.target_amount = target;
    }
    if (targetDate) payload.target_date = targetDate;

    try {
      await api.createGoal(payload);
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The goal could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="goal-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Your plan, your priorities</div>
            <h2 id="goal-dialog-title">Add a financial goal</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Goals describe what the money is for. You choose the deadline, priority, and risk comfort.
        </p>
        <form className="goal-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Goal name</span>
            <input name="name" required minLength={2} maxLength={80} placeholder="e.g. A home of my own" autoFocus />
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Purpose</span>
              <select value={goalType} required onChange={(event) => setGoalType(event.target.value as GoalType | "")}>
                <option value="" disabled>Choose a goal</option>
                <option value="wealth">Long-term wealth</option>
                <option value="retirement">Retirement</option>
                <option value="passive_income">Passive income</option>
                <option value="purchase">Planned purchase</option>
                <option value="preservation">Capital preservation</option>
                <option value="debt_repayment">Debt repayment</option>
                <option value="custom">Custom goal</option>
              </select>
            </label>
            <label className="form-field">
              <span>{goalType === "passive_income" ? "Annual income target" : "Target amount"}</span>
              <input
                name="target"
                type="number"
                required
                min="1"
                step="0.01"
                placeholder={goalType === "passive_income" ? "Your annual income target" : "Your target amount"}
              />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Goal currency</span>
              <select value={targetCurrency} onChange={(event) => setTargetCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
                <option value="RON">RON · Romanian leu</option>
              </select>
            </label>
            <label className="form-field">
              <span>Target date <small>optional</small></span>
              <input name="targetDate" type="date" />
            </label>
            <label className="form-field">
              <span>Monthly contribution ({targetCurrency}) <small>optional</small></span>
              <input name="monthlyContribution" type="number" min="0" step="0.01" placeholder="Leave blank if not planned" />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Priority</span>
              <select name="priority" required defaultValue="">
                <option value="" disabled>Choose priority</option>
                <option value="1">1 · Highest</option>
                <option value="2">2</option>
                <option value="3">3 · Standard</option>
                <option value="4">4</option>
                <option value="5">5 · Lowest</option>
              </select>
            </label>
            <label className="form-field">
              <span>Risk comfort</span>
              <select name="riskLevel" required defaultValue="">
                <option value="" disabled>Choose risk comfort</option>
                <option value="low">Lower</option>
                <option value="moderate">Moderate</option>
                <option value="high">Higher</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Deadline flexibility</span>
              <select name="flexibility" required defaultValue="">
                <option value="" disabled>Choose flexibility</option>
                <option value="essential">Essential date</option>
                <option value="flexible">Can move if needed</option>
              </select>
            </label>
            <label className="form-field">
              <span>Fixed funding share <small>for that rule</small></span>
              <div className="input-suffix">
                <input name="fixedPercent" type="number" min="0" max="100" step="1" placeholder="Optional" />
                <span>%</span>
              </div>
            </label>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Add goal"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
