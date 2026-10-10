import { useEffect, useMemo, useState } from "react";
import { AlertCircle, ArrowRight, Check, Plus, Save, SlidersHorizontal, Target } from "lucide-react";
import { api, ApiError } from "../api";
import { amount, dateLabel, goalLabel } from "../format";
import type { AssetClass, Currency, Dashboard, FundingRule } from "../types";

interface GoalsViewProps {
  data: Dashboard;
  currency: Currency;
  onAddGoal: () => void;
  onSaved: () => Promise<void>;
}

const assetClasses: AssetClass[] = ["equities", "fixed_income", "satellite"];

function percentageUnits(value: string): bigint | null {
  const normalized = value.trim();
  if (!/^\d{1,3}(?:\.\d{0,2})?$/.test(normalized)) return null;
  const [whole, fraction = ""] = normalized.split(".");
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0") || "0");
}

function percentageRatio(value: string): string {
  const units = percentageUnits(value);
  if (units === null) return "0";
  const whole = units / 10000n;
  const fraction = (units % 10000n).toString().padStart(4, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : `${whole}`;
}

export function GoalsView({ data, currency, onAddGoal, onSaved }: GoalsViewProps) {
  const [fundingRule, setFundingRule] = useState<FundingRule>(data.policy.funding_rule);
  const [reserve, setReserve] = useState(data.policy.emergency_reserve);
  const [weights, setWeights] = useState<Record<AssetClass, string>>({
    equities: String(Number(data.policy.target_weights.equities) * 100),
    fixed_income: String(Number(data.policy.target_weights.fixed_income) * 100),
    satellite: String(Number(data.policy.target_weights.satellite) * 100),
  });
  const [shares, setShares] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setFundingRule(data.policy.funding_rule);
    setReserve(data.policy.emergency_reserve);
    setWeights({
      equities: String(Number(data.policy.target_weights.equities) * 100),
      fixed_income: String(Number(data.policy.target_weights.fixed_income) * 100),
      satellite: String(Number(data.policy.target_weights.satellite) * 100),
    });
    setShares(
      Object.fromEntries(data.goals.map((goal) => [
        goal.id,
        String(Number(goal.fixed_percent ?? "0") * 100),
      ])),
    );
  }, [data]);

  const targetTotalUnits = useMemo(
    () => assetClasses.reduce((sum, asset) => sum + (percentageUnits(weights[asset]) ?? 0n), 0n),
    [weights],
  );
  const shareTotalUnits = useMemo(
    () => data.goals.reduce((sum, goal) => sum + (percentageUnits(shares[goal.id] ?? "0") ?? 0n), 0n),
    [data.goals, shares],
  );

  async function savePolicy() {
    setError("");
    setMessage("");
    if (targetTotalUnits !== 10000n) {
      setError("Asset-class target weights must add up to 100%.");
      return;
    }
    if (fundingRule === "fixed_percentages" && shareTotalUnits !== 10000n) {
      setError("Fixed goal shares must add up to 100% before this funding rule can be saved.");
      return;
    }
    setSaving(true);
    try {
      if (shareTotalUnits === 10000n) {
        await api.updateGoalShares(
          data.goals.map((goal) => ({
            goal_id: goal.id,
            percentage: percentageRatio(shares[goal.id] ?? "0"),
          })),
        );
      }
      await api.updatePolicy({
        funding_rule: fundingRule,
        emergency_reserve: reserve,
        target_weights: {
          equities: percentageRatio(weights.equities),
          fixed_income: percentageRatio(weights.fixed_income),
          satellite: percentageRatio(weights.satellite),
        },
      });
      await onSaved();
      setMessage("Your funding preferences are saved.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The funding preferences could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Your money, your meaning</div>
          <h1>Goals & plan.</h1>
          <p>Choose what matters, then decide how you want new money to support it.</p>
        </div>
        <button className="button button-primary" onClick={onAddGoal}><Plus size={17} /> Add a goal</button>
      </div>

      <section className="panel goals-explainer">
        <div className="explainer-mark"><Target size={20} /></div>
        <div>
          <strong>A goal is a purpose—not a separate account.</strong>
          <p>Set a deadline, priority, and comfort with risk. You can keep investments together at your broker while tracking different goals here.</p>
        </div>
      </section>

      <section className="panel goals-list-panel">
        <div className="panel-heading">
          <div><div className="eyebrow">Your priorities</div><h2>{data.goals.length} active goals</h2></div>
          <span className="panel-kicker">You can change these any time</span>
        </div>
        <div className="full-goals-list">
          {data.goals.map((goal) => {
            const target = goal.goal_type === "passive_income" ? goal.target_annual_income : goal.target_amount;
            const label = goal.goal_type === "passive_income" ? "estimated annual income" : "earmarked amount";
            const progress = Math.min(Number(goal.progress_percent), 100);
            return (
              <article className="full-goal-row" key={goal.id}>
                <div className="full-goal-main">
                  <span className="goal-icon goal-wealth"><Target size={17} /></span>
                  <div className="full-goal-copy">
                    <div className="full-goal-title"><h3>{goal.name}</h3><span className="goal-type">{goalLabel(goal.goal_type)}</span></div>
                    <div className="full-goal-meta">
                      <span>Priority {goal.priority}</span>
                      <span>{goal.risk_level} risk comfort</span>
                      <span>{goal.flexibility === "essential" ? "Essential date" : "Flexible date"}</span>
                    </div>
                  </div>
                </div>
                <div className="full-goal-progress">
                  <div className="full-goal-value"><strong>{amount(goal.current_amount, currency)}</strong><span>of {target ? amount(target, currency) : "not set"}</span></div>
                  <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
                  <small>{progress.toFixed(0)}% · {label}</small>
                </div>
                <div className="full-goal-right">
                  <span className="monthly-needed">{amount(goal.monthly_contribution, currency)}<small>/ month planned</small></span>
                  <span className="goal-date">{goal.target_date ? dateLabel(goal.target_date, { month: "short", year: "numeric" }) : "Ongoing"}</span>
                </div>
              </article>
            );
          })}
          {data.goals.length === 0 && <div className="empty-state"><Target size={22} /><strong>No goals yet</strong><span>Add one to start shaping your plan.</span></div>}
        </div>
      </section>

      <div className="section-heading policy-section-heading">
        <div><div className="eyebrow">Personalise the rules</div><h2>How should new cash be divided?</h2></div>
      </div>
      <div className="policy-grid">
        <section className="panel policy-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Goal funding</div><h2>Choose a funding rule</h2></div>
            <span className="policy-icon"><SlidersHorizontal size={18} /></span>
          </div>
          <label className="form-field">
            <span>When new money is available</span>
            <select value={fundingRule} onChange={(event) => setFundingRule(event.target.value as FundingRule)}>
              <option value="priority_first">Fund higher-priority goals first</option>
              <option value="proportional">Divide by monthly contribution needs</option>
              <option value="fixed_percentages">Use fixed percentages I set</option>
            </select>
          </label>
          <p className="policy-help">
            {fundingRule === "priority_first"
              ? "Goals receive up to their planned monthly contribution in priority order; any remainder goes to the highest-priority goal."
              : fundingRule === "proportional"
                ? "Cash is split in proportion to each goal’s planned monthly contribution."
                : "Each active goal receives the share you set below. Shares must total exactly 100%."}
          </p>
          <div className="fixed-shares-list">
            {data.goals.map((goal) => (
              <label className="share-row" key={goal.id}>
                <span><strong>{goal.name}</strong><small>Priority {goal.priority}</small></span>
                <span className="input-suffix share-input">
                  <input
                    aria-label={`${goal.name} fixed funding share percentage`}
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={shares[goal.id] ?? "0"}
                    onChange={(event) => setShares((current) => ({ ...current, [goal.id]: event.target.value }))}
                  />
                  <span>%</span>
                </span>
              </label>
            ))}
            {data.goals.length > 0 && (
              <div className={`share-total ${shareTotalUnits === 10000n ? "share-valid" : "share-invalid"}`}>
                <span>Fixed shares</span><strong>{(Number(shareTotalUnits) / 100).toFixed(2)}%</strong>
                {shareTotalUnits === 10000n && <Check size={15} />}
              </div>
            )}
          </div>
        </section>

        <section className="panel policy-panel">
          <div className="panel-heading">
            <div><div className="eyebrow">Investment guardrails</div><h2>Reserve & target mix</h2></div>
            <span className="policy-icon"><SlidersHorizontal size={18} /></span>
          </div>
          <label className="form-field reserve-field">
            <span>Emergency reserve target ({currency})</span>
            <input type="number" min="0" step="100" value={reserve} onChange={(event) => setReserve(event.target.value)} />
          </label>
          <p className="policy-help">Fresh cash fills a reserve shortfall before the allocation preview routes the remainder.</p>
          <div className="mix-fields">
            <div className="mix-fields-heading"><span>Portfolio target allocation</span><span>{(Number(targetTotalUnits) / 100).toFixed(0)}% / 100%</span></div>
            {assetClasses.map((asset) => (
              <label className="mix-row" key={asset}>
                <span className={`legend-dot legend-${asset}`} />
                <span>{asset === "equities" ? "Equities" : asset === "fixed_income" ? "Fixed income" : "Satellite"}</span>
                <span className="input-suffix share-input">
                  <input
                    aria-label={`${asset} target percentage`}
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={weights[asset]}
                    onChange={(event) => setWeights((current) => ({ ...current, [asset]: event.target.value }))}
                  />
                  <span>%</span>
                </span>
              </label>
            ))}
          </div>
          <div className="policy-button-row">
            <span className="policy-save-status" aria-live="polite">{error || message}</span>
            <button className="button button-primary" onClick={savePolicy} disabled={saving}>
              <Save size={15} /> {saving ? "Saving…" : "Save my rules"}
            </button>
          </div>
        </section>
      </div>

      <section className="panel plan-note">
        <AlertCircle size={17} />
        <p>Goal progress is sample data entered for this prototype. Assets are not yet assigned to goals, and a goal’s displayed progress should not be treated as an account balance.</p>
        <span>Learn how it works <ArrowRight size={14} /></span>
      </section>
    </div>
  );
}
