import { useState, type FormEvent } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck, Sparkles, X } from "lucide-react";
import { api, ApiError } from "../api";
import { amount, assetLabel, dateLabel, fundingLabel } from "../format";
import type { Currency, RecommendationPreview } from "../types";

interface AllocationSimulatorProps {
  currency: Currency;
  onClose: () => void;
}

export function AllocationSimulator({ currency, onClose }: AllocationSimulatorProps) {
  const [cashAmount, setCashAmount] = useState("");
  const [preview, setPreview] = useState<RecommendationPreview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      setPreview(await api.previewAllocation(cashAmount, currency));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The allocation preview could not be generated.");
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card allocation-modal" role="dialog" aria-modal="true" aria-labelledby="allocation-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Decision support · no trading</div>
            <h2 id="allocation-title">Preview fresh cash</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">Try a hypothetical contribution to see how your saved goals and target allocation would guide it.</p>
        <form className="simulator-form" onSubmit={submit}>
          <label className="form-field">
            <span>Amount that has become available</span>
            <div className="input-suffix amount-input">
              <span>{currency}</span>
              <input
                aria-label={`Hypothetical amount in ${currency}`}
                type="number"
                min="0.01"
                max="100000000"
                step="0.01"
                required
                placeholder="Enter available cash"
                value={cashAmount}
                onChange={(event) => setCashAmount(event.target.value)}
              />
            </div>
          </label>
          <button className="button button-primary" type="submit" disabled={loading}>
            <Sparkles size={16} /> {loading ? "Preparing preview…" : "Generate preview"}
          </button>
        </form>

        {error && <div className="inline-error" role="alert">{error}</div>}
        {preview && (
          <div className="preview-results">
            <div className="preview-summary">
              <div>
                <span>Available after reserve top-up</span>
                <strong>{amount(preview.deployable_amount, preview.base_currency)}</strong>
              </div>
              <div>
                <span>Remaining for investment buckets</span>
                <strong>{amount(preview.investable_amount, preview.base_currency)}</strong>
              </div>
              <div className="summary-mini">
                <span>Reserve top-up</span><strong>{amount(preview.reserve_top_up, preview.base_currency)}</strong>
              </div>
              <div className="summary-mini">
                <span>Near-term goal cash</span><strong>{amount(preview.retained_for_near_term_goals, preview.base_currency)}</strong>
              </div>
            </div>

            <div className="preview-section">
              <div className="preview-section-heading"><h3>By goal</h3><span>{fundingLabel(preview.funding_rule)} logic</span></div>
              {preview.goal_allocations.map((line) => (
                <div className="preview-row" key={line.goal_id}>
                  <span><strong>{line.goal_name}</strong><small>{line.rationale}</small></span>
                  <strong>{amount(line.amount, preview.base_currency)}</strong>
                </div>
              ))}
              {preview.goal_allocations.length === 0 && <p className="quiet-copy">No active goals are set.</p>}
            </div>

            <div className="preview-section">
              <div className="preview-section-heading"><h3>Portfolio target mix</h3><span>Buy-only · class level</span></div>
              {preview.asset_allocations.map((line) => (
                <div className="preview-row" key={line.asset_class}>
                  <span><strong>{assetLabel(line.asset_class)}</strong><small>{Number(line.post_contribution_weight).toFixed(1)}% after contribution · target {(Number(line.target_weight) * 100).toFixed(0)}%</small></span>
                  <strong>{amount(line.amount, preview.base_currency)}</strong>
                </div>
              ))}
            </div>

            {Number(preview.passive_income_gap) > 0 && (
              <div className="income-gap-note">
                <ArrowRight size={15} />
                <span>Estimated annual income gap: <strong>{amount(preview.passive_income_gap, preview.base_currency)}</strong>. The current allocation is not yield-optimised.</span>
              </div>
            )}

            <div className="preview-warnings">
              {preview.warnings.map((warning, index) => (
                <div key={index}><AlertTriangle size={14} /><span>{warning}</span></div>
              ))}
            </div>
            <div className="preview-footer">
              <span><CheckCircle2 size={15} /> Preview only · expires {dateLabel(preview.expires_at, { hour: "2-digit", minute: "2-digit" })}</span>
              <button className="button button-secondary" type="button" onClick={onClose}>Done</button>
            </div>
          </div>
        )}
        {!preview && !error && (
          <div className="simulator-safety">
            <ShieldCheck size={16} />
            <span>This simulation does not create a cash-flow record or place a trade.</span>
          </div>
        )}
      </section>
    </div>
  );
}
