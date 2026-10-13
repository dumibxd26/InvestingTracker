import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { HoldingSummary } from "../types";

interface SellHoldingDialogProps {
  holding: HoldingSummary;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SellHoldingDialog({ holding, onClose, onSaved }: SellHoldingDialogProps) {
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [sellDate, setSellDate] = useState(todayIsoDate());
  const [sellPrice, setSellPrice] = useState("");
  const [quantity, setQuantity] = useState(holding.quantity);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const parsedPrice = Number(sellPrice);
  const parsedQuantity = Number(quantity);
  const previewProceeds =
    parsedPrice > 0 && parsedQuantity > 0 ? parsedPrice * parsedQuantity : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.sellHolding(holding.id, {
        idempotency_key: idempotencyKey,
        sell_date: sellDate,
        sell_price: sellPrice,
        quantity,
      });
      await onSaved();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The sale could not be recorded.");
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
        aria-labelledby="sell-holding-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Record a sale</div>
            <h2 id="sell-holding-title">Sell {holding.symbol}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Proceeds are credited to the {holding.price_currency} wallet in {holding.account_name}.
          Enter the price per share you actually received after tax, in {holding.price_currency}.
          Leave the share count at the full position to sell everything; a smaller number keeps the
          rest of the position.
        </p>
        <form className="goal-form" onSubmit={submit}>
          <div className="form-row">
            <label className="form-field">
              <span>Sell date</span>
              <input
                type="date"
                required
                min={holding.purchase_date}
                max={todayIsoDate()}
                value={sellDate}
                onChange={(event) => setSellDate(event.target.value)}
              />
            </label>
            <label className="form-field">
              <span>Shares to sell</span>
              <input
                type="number"
                min="0.00000001"
                max={holding.quantity}
                step="any"
                required
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
            </label>
          </div>
          <label className="form-field">
            <span>After-tax price per share ({holding.price_currency})</span>
            <input
              type="number"
              min="0.00000001"
              max="100000000"
              step="any"
              required
              value={sellPrice}
              placeholder={`Current quote ${amount(holding.price, holding.price_currency, 2)}`}
              onChange={(event) => setSellPrice(event.target.value)}
            />
          </label>
          <p className="quiet-copy">
            {previewProceeds === null
              ? "Enter a price and share count to preview the cash that will be credited."
              : `Cash credited: ${amount(previewProceeds.toFixed(4), holding.price_currency, 2)} · cost basis ${amount(
                  (parsedQuantity * Number(holding.average_cost)).toFixed(4),
                  holding.price_currency,
                  2,
                )}`}
          </p>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Recording…" : "Record sale"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
