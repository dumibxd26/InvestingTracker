import { useMemo, useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { AccountSummary, Currency, HoldingSummary } from "../types";
import {
  TransferFeeFields,
  emptyFeeDraft,
  feePayload,
  resolveFee,
  type FeeDraft,
} from "./TransferFeeFields";

interface TransferStockDialogProps {
  holding: HoldingSummary;
  accounts: AccountSummary[];
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function uniqueCurrencies(account: AccountSummary | undefined): Currency[] {
  if (!account) return [];
  return Array.from(new Set(account.subaccounts.map((wallet) => wallet.currency)));
}

export function TransferStockDialog({ holding, accounts, onClose, onSaved }: TransferStockDialogProps) {
  const destinations = useMemo(
    () =>
      accounts.filter(
        (account) =>
          !account.is_sample &&
          account.account_type !== "EMPLOYER_PLAN" &&
          account.id !== holding.account_id,
      ),
    [accounts, holding.account_id],
  );
  const sourceAccount = accounts.find((account) => account.id === holding.account_id);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [destinationId, setDestinationId] = useState(destinations[0]?.id ?? "");
  const [transferDate, setTransferDate] = useState(todayIsoDate());
  const [quantity, setQuantity] = useState(holding.quantity);
  const [fee, setFee] = useState<FeeDraft>(emptyFeeDraft);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const destinationAccount = destinations.find((account) => account.id === destinationId);
  const sourceCurrencies = uniqueCurrencies(sourceAccount);
  const destinationCurrencies = uniqueCurrencies(destinationAccount);
  const resolvedFee = destinationAccount
    ? resolveFee(fee, sourceCurrencies, destinationCurrencies)
    : null;
  const parsedQuantity = Number(quantity);
  const quantityValid =
    parsedQuantity > 0 && parsedQuantity <= Number(holding.quantity);
  const dateValid = transferDate >= holding.purchase_date && transferDate <= todayIsoDate();
  const feeWallet =
    resolvedFee && resolvedFee.side === "SOURCE" ? sourceAccount : destinationAccount;
  const feeWalletBalance = feeWallet?.subaccounts.find(
    (wallet) => wallet.currency === resolvedFee?.currency,
  )?.cash_balance;
  const feeValid =
    resolvedFee === null ||
    (resolvedFee.amount > 0 && resolvedFee.amount <= Number(feeWalletBalance ?? 0));
  const linkedToGoal = holding.assigned_goal_id !== null;
  const canSubmit =
    destinationAccount !== undefined && quantityValid && dateValid && feeValid && !linkedToGoal;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!destinationAccount) return;
    setSaving(true);
    setError("");
    try {
      const record = await api.transferStock(holding.id, {
        idempotency_key: idempotencyKey,
        destination_account_id: destinationAccount.id,
        transfer_date: transferDate,
        ...(parsedQuantity < Number(holding.quantity) ? { quantity } : {}),
        ...feePayload(resolvedFee),
      });
      await onSaved(
        `Moved ${record.quantity} ${record.symbol} from ${record.source_account_name} to ${record.destination_account_name}.`,
      );
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The stock transfer could not be recorded.");
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
        aria-labelledby="transfer-stock-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Move shares</div>
            <h2 id="transfer-stock-title">Transfer {holding.symbol}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Moves shares and their cost basis from {holding.account_name} to another account. No cash
          is credited for the shares. Only the optional fee leaves a wallet. Holdings linked to a
          goal must be unlinked first.
        </p>
        {destinations.length === 0 ? (
          <p className="quiet-copy">Add another non-employer account to transfer shares to.</p>
        ) : (
          <form className="goal-form" onSubmit={submit}>
            <div className="form-row">
              <label className="form-field">
                <span>To account</span>
                <select
                  required
                  value={destinationId}
                  onChange={(event) => setDestinationId(event.target.value)}
                >
                  {destinations.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.display_name} ({account.account_type.toLowerCase()})
                    </option>
                  ))}
                </select>
              </label>
              <label className="form-field">
                <span>Transfer date</span>
                <input
                  type="date"
                  required
                  min={holding.purchase_date}
                  max={todayIsoDate()}
                  value={transferDate}
                  onChange={(event) => setTransferDate(event.target.value)}
                />
              </label>
            </div>
            <label className="form-field">
              <span>Shares to move (of {holding.quantity})</span>
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
            {destinationAccount && (
              <TransferFeeFields
                value={fee}
                onChange={setFee}
                sourceLabel={`${holding.account_name} wallet`}
                destinationLabel={`${destinationAccount.display_name} wallet`}
                sourceCurrencies={sourceCurrencies}
                destinationCurrencies={destinationCurrencies}
              />
            )}
            <p className="quiet-copy">
              {resolvedFee && !feeValid
                ? `The fee is larger than the ${amount(feeWalletBalance ?? "0", resolvedFee.currency, 2)} available in that wallet.`
                : resolvedFee
                  ? `Fee of ${amount(resolvedFee.amountText, resolvedFee.currency, 2)} is deducted from the ${resolvedFee.side === "SOURCE" ? "source" : "destination"} wallet in ${resolvedFee.currency}.`
                  : "No fee is charged. Enter one above if your bank or broker deducts a transfer fee or tax."}
            </p>
            {!quantityValid && quantity !== "" && (
              <div className="inline-error" role="alert">
                Enter between 0 and {holding.quantity} shares.
              </div>
            )}
            {!dateValid && (
              <div className="inline-error" role="alert">
                The transfer date must be between {holding.purchase_date} and today.
              </div>
            )}
            {linkedToGoal && (
              <div className="inline-error" role="alert">
                This holding is linked to a goal. Unlink it before transferring.
              </div>
            )}
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={onClose}>
                Cancel
              </button>
              <button className="button button-primary" type="submit" disabled={saving || !canSubmit}>
                {saving ? "Transferring…" : "Transfer shares"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
