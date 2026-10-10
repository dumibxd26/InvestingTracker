import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { ApiError, api } from "../api";
import type { HoldingSummary } from "../types";

interface EditHoldingDialogProps {
  holding: HoldingSummary;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export function EditHoldingDialog({ holding, onClose, onSaved }: EditHoldingDialogProps) {
  const [quantity, setQuantity] = useState(holding.quantity);
  const [averageCost, setAverageCost] = useState(holding.average_cost);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.updateHolding(holding.id, { quantity, average_cost: averageCost });
      await onSaved();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The holding could not be updated.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="modal-card holding-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-holding-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Update your position</div>
            <h2 id="edit-holding-title">Edit {holding.symbol}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Update the total shares held and weighted average cost per share. The market quote is
          unchanged; refresh quotes separately to retrieve a new provider price.
        </p>
        <form className="goal-form" onSubmit={submit}>
          <label className="form-field">
            <span>Number of shares</span>
            <input
              type="number"
              min="0.00000001"
              max="1000000000"
              step="any"
              required
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>Average cost per share ({holding.price_currency})</span>
            <input
              type="number"
              min="0.00000001"
              max="100000000"
              step="any"
              required
              value={averageCost}
              onChange={(event) => setAverageCost(event.target.value)}
            />
          </label>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
