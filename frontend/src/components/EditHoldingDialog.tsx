import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { ApiError, api } from "../api";
import type { Currency, HoldingSummary } from "../types";

interface EditHoldingDialogProps {
  holding: HoldingSummary;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export function EditHoldingDialog({ holding, onClose, onSaved }: EditHoldingDialogProps) {
  const [quantity, setQuantity] = useState(holding.quantity);
  const [averageCost, setAverageCost] = useState(holding.average_cost);
  const [averageCostCurrency, setAverageCostCurrency] = useState<Currency>(
    holding.price_currency,
  );
  const [purchaseDate, setPurchaseDate] = useState(holding.purchase_date);
  const [riskTier, setRiskTier] = useState<"X" | "Y" | "Z">(holding.risk_tier);
  const [expectedReturnPercent, setExpectedReturnPercent] = useState(
    String(Number(holding.expected_annual_return) * 100),
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.updateHolding(holding.id, {
        quantity,
        average_cost: averageCost,
        average_cost_currency: averageCostCurrency,
        purchase_date: purchaseDate,
        risk_tier: riskTier,
        expected_annual_return: String(Number(expectedReturnPercent) / 100),
      });
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
          Update the total shares, average cost, purchase date, and editable projection assumptions. Risk tiers are qualitative categories, not measured volatility.
          {holding.funding_currency
            ? " Any cost-basis change is converted and applied to the original funding wallet."
            : " This position was imported as already owned, so editing it will not change cash."}
          {" "}The market quote is unchanged.
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
          <div className="form-row">
            <label className="form-field">
              <span>Relative risk tier</span>
              <select value={riskTier} onChange={(event) => setRiskTier(event.target.value as "X" | "Y" | "Z")}>
                <option value="X">X · lower relative risk (e.g. diversified/index ETF)</option>
                <option value="Y">Y · moderate / concentrated exposure</option>
                <option value="Z">Z · high volatility / speculative</option>
              </select>
            </label>
            <label className="form-field">
              <span>Expected annual total return (%)</span>
              <input
                type="number"
                min="-99"
                max="100"
                step="0.1"
                value={expectedReturnPercent}
                onChange={(event) => setExpectedReturnPercent(event.target.value)}
                required
              />
            </label>
          </div>
          <p className="quiet-copy">
            The return is an editable nominal planning assumption including dividends, not a forecast. Existing positions start at 5%. Risk tier is a qualitative label and changing it does not automatically raise the return assumption.
          </p>
          <label className="form-field">
            <span>Average cost per share</span>
            <div className="average-cost-input">
              <input
                type="number"
                min="0.00000001"
                max="100000000"
                step="any"
                required
                value={averageCost}
                onChange={(event) => setAverageCost(event.target.value)}
              />
              <select
                aria-label="Average cost currency"
                value={averageCostCurrency}
                onChange={(event) =>
                  setAverageCostCurrency(event.target.value as Currency)
                }
              >
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="RON">RON</option>
              </select>
            </div>
          </label>
          <label className="form-field">
            <span>Purchase date</span>
            <input
              type="date"
              required
              value={purchaseDate}
              onChange={(event) => setPurchaseDate(event.target.value)}
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
