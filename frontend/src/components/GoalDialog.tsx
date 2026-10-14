import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { api, ApiError } from "../api";
import { amount, dateLabel, number } from "../format";
import type {
  AccountSummary,
  Currency,
  Deposit,
  GoalCreatePayload,
  GoalRecord,
  GoalSourceAllocation,
  GoalType,
  GoalUpdatePayload,
  HoldingSummary,
} from "../types";

type ShareMap = Record<string, string>;

function accountName(accounts: AccountSummary[], accountId: string): string {
  return accounts.find((account) => account.id === accountId)?.display_name ?? "Account";
}

function sharesFromAllocations(allocations: GoalSourceAllocation[] = []): ShareMap {
  return Object.fromEntries(
    allocations.map((allocation) => [allocation.id, String(Number(allocation.allocated_percentage))]),
  );
}

function allocationsFromShares(shares: ShareMap): GoalSourceAllocation[] {
  return Object.entries(shares).map(([id, percentage]) => ({ id, allocated_percentage: percentage }));
}

function withoutIds(shares: ShareMap, ids: Set<string>): ShareMap {
  return Object.fromEntries(Object.entries(shares).filter(([id]) => !ids.has(id)));
}

function toggledShare(shares: ShareMap, id: string, checked: boolean, available: number): ShareMap {
  if (!checked) return withoutIds(shares, new Set([id]));
  return { ...shares, [id]: String(Math.round(Math.min(100, available) * 100) / 100) };
}

// Percent already taken by other active goals, excluding this goal's own saved share.
function shareUsedByOtherGoals(
  allocatedTotal: string,
  id: string,
  ownAllocations: GoalSourceAllocation[] = [],
): number {
  const ownShare = Number(
    ownAllocations.find((allocation) => allocation.id === id)?.allocated_percentage ?? 0,
  );
  return Math.max(0, Number(allocatedTotal) - ownShare);
}

interface GoalDialogProps {
  currency: Currency;
  accounts: AccountSummary[];
  holdings: HoldingSummary[];
  deposits: Deposit[];
  goal?: GoalRecord;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

export function GoalDialog({
  currency,
  accounts,
  holdings,
  deposits,
  goal,
  onClose,
  onCreated,
}: GoalDialogProps) {
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
  const [linkedAccountIds, setLinkedAccountIds] = useState<string[]>(
    goal?.linked_account_ids ?? [],
  );
  const [holdingShares, setHoldingShares] = useState<ShareMap>(() =>
    sharesFromAllocations(goal?.holding_allocations),
  );
  const [depositShares, setDepositShares] = useState<ShareMap>(() =>
    sharesFromAllocations(goal?.fixed_deposit_allocations),
  );
  const [visualizationBudgetAmount, setVisualizationBudgetAmount] = useState(
    goal?.visualization_budget_amount ?? "",
  );
  const [visualizationBudgetPeriod, setVisualizationBudgetPeriod] = useState<
    "monthly" | "yearly" | ""
  >(goal?.visualization_budget_period ?? "");
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

  function toggleAccount(accountId: string) {
    const isLinked = linkedAccountIds.includes(accountId);
    const nextAccountIds = isLinked
      ? linkedAccountIds.filter((id) => id !== accountId)
      : [...linkedAccountIds, accountId];
    setLinkedAccountIds(nextAccountIds);
    if (isLinked) {
      const accountHoldingIds = new Set(
        holdings.filter((holding) => holding.account_id === accountId).map((holding) => holding.id),
      );
      const accountDepositIds = new Set(
        deposits.filter((deposit) => deposit.account_id === accountId).map((deposit) => deposit.id),
      );
      setHoldingShares((current) => withoutIds(current, accountHoldingIds));
      setDepositShares((current) => withoutIds(current, accountDepositIds));
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
    if (visualizationBudgetAmount && !visualizationBudgetPeriod) {
      setError("Choose whether the visualization-only budget is monthly or yearly.");
      setSaving(false);
      return;
    }

    const sharedAssets = [
      ...allocationsFromShares(holdingShares),
      ...allocationsFromShares(depositShares),
    ];
    if (sharedAssets.some((item) => !(Number(item.allocated_percentage) > 0 && Number(item.allocated_percentage) <= 100))) {
      setError("Each linked stock or deposit needs a share above 0% and at most 100%.");
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
      visualization_budget_amount: visualizationBudgetAmount || null,
      visualization_budget_period:
        visualizationBudgetAmount && visualizationBudgetPeriod
          ? visualizationBudgetPeriod
          : null,
      linked_account_ids: linkedAccountIds,
      holding_allocations: allocationsFromShares(holdingShares),
      fixed_deposit_allocations: allocationsFromShares(depositShares),
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
          <label className="form-field">
            <span>Progress already saved outside selected assets ({targetCurrency})</span>
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
            <small>This is added to selected stocks and deposits. Don’t repeat an amount that is already linked below.</small>
          </label>
          <section className="goal-source-picker">
            <div className="goal-source-heading">
              <strong>Link accounts and choose goal assets</strong>
              <small>Links are virtual earmarks; no cash or investments move.</small>
            </div>
            <div className="goal-source-accounts">
              {accounts.map((account) => (
                <label className="goal-source-account" key={account.id}>
                  <input
                    type="checkbox"
                    checked={linkedAccountIds.includes(account.id)}
                    onChange={() => toggleAccount(account.id)}
                  />
                  <span>
                    <strong>{account.display_name}</strong>
                    <small>{account.account_type.toLowerCase().replace("_", " ")}</small>
                  </span>
                </label>
              ))}
              {accounts.length === 0 && <p className="quiet-copy">Add an account first to link existing assets.</p>}
            </div>
            {linkedAccountIds.length > 0 && (
              <div className="goal-source-assets">
                {holdings
                  .filter((holding) => linkedAccountIds.includes(holding.account_id))
                  .map((holding) => {
                    const usedElsewhere = shareUsedByOtherGoals(
                      holding.allocated_percentage,
                      holding.id,
                      goal?.holding_allocations,
                    );
                    const available = Math.max(0, 100 - usedElsewhere);
                    const selected = holding.id in holdingShares;
                    const blocked = !selected && available <= 0;
                    return (
                      <label
                        className={`goal-source-asset ${blocked ? "is-disabled" : ""}`}
                        key={holding.id}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={blocked}
                          onChange={(event) =>
                            setHoldingShares((current) =>
                              toggledShare(current, holding.id, event.target.checked, available),
                            )
                          }
                        />
                        <span>
                          <strong>{holding.symbol} · {holding.account_name}</strong>
                          <small>
                            {number(holding.quantity)} shares · {amount(holding.market_value, currency)}
                            {usedElsewhere > 0 ? ` · ${number(usedElsewhere, 2)}% used by other goals` : ""}
                          </small>
                        </span>
                        {selected && (
                          <span className="goal-share-field">
                            <input
                              type="number"
                              min="0.01"
                              max={available}
                              step="0.01"
                              aria-label={`Share of ${holding.symbol} for this goal`}
                              value={holdingShares[holding.id]}
                              onChange={(event) =>
                                setHoldingShares((current) => ({
                                  ...current,
                                  [holding.id]: event.target.value,
                                }))
                              }
                            />
                            <small>%</small>
                          </span>
                        )}
                      </label>
                    );
                  })}
                {deposits
                  .filter((deposit) => linkedAccountIds.includes(deposit.account_id))
                  .map((deposit) => {
                    const usedElsewhere = shareUsedByOtherGoals(
                      deposit.allocated_percentage,
                      deposit.id,
                      goal?.fixed_deposit_allocations,
                    );
                    const available = Math.max(0, 100 - usedElsewhere);
                    const selected = deposit.id in depositShares;
                    const blocked = !selected && available <= 0;
                    return (
                      <label
                        className={`goal-source-asset ${blocked ? "is-disabled" : ""}`}
                        key={deposit.id}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={blocked}
                          onChange={(event) =>
                            setDepositShares((current) =>
                              toggledShare(current, deposit.id, event.target.checked, available),
                            )
                          }
                        />
                        <span>
                          <strong>{deposit.name} · {accountName(accounts, deposit.account_id)}</strong>
                          <small>
                            {amount(deposit.current_value, deposit.currency)} · matures {dateLabel(deposit.maturity_date)}
                            {usedElsewhere > 0 ? ` · ${number(usedElsewhere, 2)}% used by other goals` : ""}
                          </small>
                        </span>
                        {selected && (
                          <span className="goal-share-field">
                            <input
                              type="number"
                              min="0.01"
                              max={available}
                              step="0.01"
                              aria-label={`Share of ${deposit.name} for this goal`}
                              value={depositShares[deposit.id]}
                              onChange={(event) =>
                                setDepositShares((current) => ({
                                  ...current,
                                  [deposit.id]: event.target.value,
                                }))
                              }
                            />
                            <small>%</small>
                          </span>
                        )}
                      </label>
                    );
                  })}
                {holdings.filter((holding) => linkedAccountIds.includes(holding.account_id)).length === 0
                  && deposits.filter((deposit) => linkedAccountIds.includes(deposit.account_id)).length === 0
                  && <p className="quiet-copy">No stocks or term deposits in selected accounts yet. Cash is not earmarked by this asset selector.</p>}
              </div>
            )}
          </section>
          <div className="form-row">
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
              <span>Monthly contribution for cash-allocation rules ({targetCurrency}) <small>optional</small></span>
              <input name="monthlyContribution" type="number" min="0" step="0.01" defaultValue={goal?.monthly_contribution ?? "0"} placeholder="Leave blank if not planned" />
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Visualization-only budget <small>optional</small></span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={visualizationBudgetAmount}
                onChange={(event) => setVisualizationBudgetAmount(event.target.value)}
                placeholder="Planned saving amount"
              />
            </label>
            <label className="form-field">
              <span>Budget period</span>
              <select
                value={visualizationBudgetPeriod}
                onChange={(event) =>
                  setVisualizationBudgetPeriod(event.target.value as "monthly" | "yearly" | "")
                }
                disabled={!visualizationBudgetAmount}
              >
                <option value="">Choose a period</option>
                <option value="monthly">Monthly</option>
                <option value="yearly">Yearly</option>
              </select>
            </label>
          </div>
          <p className="goal-visual-budget-note">
            The visualization-only budget is saved for future goal charts. It does not post money,
            change an account balance, or affect cash-allocation rules. The existing monthly
            contribution above is a separate input for the cash-allocation rule.
          </p>
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
