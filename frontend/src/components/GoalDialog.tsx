import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { api, ApiError } from "../api";
import type { Currency, GoalCreatePayload, GoalRecord, GoalType, GoalUpdatePayload } from "../types";

interface GoalDialogProps {
  currency: Currency;
  goal?: GoalRecord;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

export function GoalDialog({ currency, goal, onClose, onCreated }: GoalDialogProps) {
  const [goalType, setGoalType] = useState<GoalType | "">(goal?.goal_type ?? "");
  const [targetCurrency, setTargetCurrency] = useState<Currency>(
    goal?.target_currency ?? currency,
  );
  const [target, setTarget] = useState(
    goal?.goal_type === "passive_income"
      ? goal.target_annual_income ?? ""
      : goal?.target_amount ?? "",
  );
  const [currentAmount, setCurrentAmount] = useState(goal?.current_amount ?? "0");
  const [currentAnnualIncome, setCurrentAnnualIncome] = useState(
    goal?.current_annual_income ?? "0",
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function changeGoalType(nextType: GoalType | "") {
    if (nextType !== goalType) {
      setGoalType(nextType);
      setTarget(
        nextType === "passive_income"
          ? goal?.target_annual_income ?? ""
          : goal?.target_amount ?? "",
      );
      if (nextType === "passive_income") setCurrentAmount("0");
      else setCurrentAnnualIncome("0");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const targetDate = String(form.get("targetDate") ?? "");
    const priority = String(form.get("priority") ?? "");
    const riskLevel = String(form.get("riskLevel") ?? "");
    const flexibility = String(form.get("flexibility") ?? "");
    if (!goalType || !priority || !riskLevel || !flexibility || !target) {
      setError("Complete the goal type, target, priority, risk comfort, and deadline flexibility.");
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
      current_amount: goalType === "passive_income" ? "0" : currentAmount,
      current_annual_income: goalType === "passive_income" ? currentAnnualIncome : "0",
    };
    const fixedPercent = String(form.get("fixedPercent") ?? "").trim();
    if (fixedPercent) payload.fixed_percent = String(Number(fixedPercent) / 100);
    if (goalType === "passive_income") payload.target_annual_income = target;
    else payload.target_amount = target;
    if (targetDate) payload.target_date = targetDate;

    try {
      if (goal) {
        const updatePayload: GoalUpdatePayload = {
          ...payload,
          current_amount: payload.current_amount ?? "0",
          current_annual_income: payload.current_annual_income ?? "0",
        };
        await api.updateGoal(goal.id, updatePayload);
      } else {
        await api.createGoal(payload);
      }
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
            <h2 id="goal-dialog-title">{goal ? "Edit financial goal" : "Add a financial goal"}</h2>
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
            <input name="name" required minLength={2} maxLength={80} defaultValue={goal?.name ?? ""} placeholder="e.g. A home of my own" autoFocus />
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Purpose</span>
              <select value={goalType} required onChange={(event) => changeGoalType(event.target.value as GoalType | "")}>
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
                min="0.01"
                step="0.01"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                placeholder={goalType === "passive_income" ? "Your annual income target" : "Your target amount"}
              />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Current {goalType === "passive_income" ? "annual passive income" : "amount toward goal"}</span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={goalType === "passive_income" ? currentAnnualIncome : currentAmount}
                onChange={(event) =>
                  goalType === "passive_income"
                    ? setCurrentAnnualIncome(event.target.value)
                    : setCurrentAmount(event.target.value)
                }
              />
            </label>
            <label className="form-field">
              <span>Goal currency</span>
              <select value={targetCurrency} onChange={(event) => setTargetCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
                <option value="RON">RON · Romanian leu</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Target date <small>optional</small></span>
              <input name="targetDate" type="date" defaultValue={goal?.target_date ?? ""} />
            </label>
            <label className="form-field">
              <span>Monthly contribution ({targetCurrency}) <small>optional</small></span>
              <input name="monthlyContribution" type="number" min="0" step="0.01" defaultValue={goal?.monthly_contribution ?? "0"} placeholder="Leave blank if not planned" />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Priority</span>
              <select name="priority" required defaultValue={goal ? String(goal.priority) : ""}>
                <option value="" disabled>Choose priority</option>
                <option value="1">1 · Highest</option>
                <option value="2">2</option>
                <option value="3">3 · Standard</option>
                <option value="4">4</option>
                <option value="5">5 · Lowest</option>
                <option value="6">6</option>
                <option value="7">7</option>
                <option value="8">8</option>
                <option value="9">9</option>
                <option value="10">10 · Lowest</option>
              </select>
            </label>
            <label className="form-field">
              <span>Risk comfort</span>
              <select name="riskLevel" required defaultValue={goal?.risk_level ?? ""}>
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
              <select name="flexibility" required defaultValue={goal?.flexibility ?? ""}>
                <option value="" disabled>Choose flexibility</option>
                <option value="essential">Essential date</option>
                <option value="flexible">Can move if needed</option>
              </select>
            </label>
            <label className="form-field">
              <span>Fixed funding share <small>for that rule</small></span>
              <div className="input-suffix">
                <input
                  name="fixedPercent"
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  defaultValue={goal?.fixed_percent === null || goal?.fixed_percent === undefined
                    ? ""
                    : String(Number(goal.fixed_percent) * 100)}
                  placeholder="Optional"
                />
                <span>%</span>
              </div>
            </label>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : goal ? "Save changes" : "Add goal"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
