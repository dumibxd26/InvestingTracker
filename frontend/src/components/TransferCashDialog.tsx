import { useMemo, useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { AccountSummary, AccountSubaccount } from "../types";

interface TransferCashDialogProps {
  accounts: AccountSummary[];
  initialSourceId?: string;
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}

interface WalletOption {
  wallet: AccountSubaccount;
  accountName: string;
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function TransferCashDialog({
  accounts,
  initialSourceId,
  onClose,
  onSaved,
}: TransferCashDialogProps) {
  const options = useMemo<WalletOption[]>(
    () =>
      accounts
        .filter((account) => !account.is_sample && account.account_type !== "EMPLOYER_PLAN")
        .flatMap((account) =>
          account.subaccounts.map((wallet) => ({ wallet, accountName: account.display_name })),
        ),
    [accounts],
  );
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [sourceId, setSourceId] = useState(
    () => options.find((option) => option.wallet.id === initialSourceId)?.wallet.id ?? options[0]?.wallet.id ?? "",
  );
  const [destinationId, setDestinationId] = useState(
    () => options.find((option) => option.wallet.id !== sourceId)?.wallet.id ?? "",
  );
  const [transferDate, setTransferDate] = useState(todayIsoDate());
  const [sourceAmount, setSourceAmount] = useState("");
  const [destinationAmount, setDestinationAmount] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const source = options.find((option) => option.wallet.id === sourceId);
  const destination = options.find((option) => option.wallet.id === destinationId);
  const crossCurrency =
    source !== undefined && destination !== undefined
      ? source.wallet.currency !== destination.wallet.currency
      : false;
  const parsedSource = Number(sourceAmount);
  const sourceValid = parsedSource > 0 && source !== undefined && parsedSource <= Number(source.wallet.cash_balance);
  const canSubmit =
    source !== undefined &&
    destination !== undefined &&
    source.wallet.id !== destination.wallet.id &&
    sourceValid &&
    (!crossCurrency || Number(destinationAmount) > 0);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!source || !destination) return;
    setSaving(true);
    setError("");
    try {
      const record = await api.transferCash({
        idempotency_key: idempotencyKey,
        source_subaccount_id: source.wallet.id,
        destination_subaccount_id: destination.wallet.id,
        transfer_date: transferDate,
        source_amount: sourceAmount,
        ...(crossCurrency ? { destination_amount: destinationAmount } : {}),
      });
      await onSaved(
        `Moved ${amount(record.source_amount, record.source_currency, 2)} from ${record.source_account_name} to ${record.destination_account_name} (${amount(record.destination_amount, record.destination_currency, 2)} received).`,
      );
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The transfer could not be recorded.");
    } finally {
      setSaving(false);
    }
  }

  function optionLabel(option: WalletOption): string {
    return `${option.accountName} · ${option.wallet.currency} (${amount(option.wallet.cash_balance, option.wallet.currency, 2)})`;
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
        aria-labelledby="transfer-cash-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Move money</div>
            <h2 id="transfer-cash-title">Transfer between accounts</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Moves tracked cash from one wallet to another, for example from XTB to ING. No trade or
          cash-flow entry is created. Employer-plan accounts are not available here.
        </p>
        {options.length < 2 ? (
          <p className="quiet-copy">Add at least two wallets to make a transfer.</p>
        ) : (
          <form className="goal-form" onSubmit={submit}>
            <div className="form-row">
              <label className="form-field">
                <span>From</span>
                <select
                  required
                  value={sourceId}
                  onChange={(event) => {
                    setSourceId(event.target.value);
                    if (event.target.value === destinationId) {
                      setDestinationId(
                        options.find((option) => option.wallet.id !== event.target.value)?.wallet.id ?? "",
                      );
                    }
                  }}
                >
                  {options.map((option) => (
                    <option key={option.wallet.id} value={option.wallet.id}>
                      {optionLabel(option)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="form-field">
                <span>To</span>
                <select
                  required
                  value={destinationId}
                  onChange={(event) => setDestinationId(event.target.value)}
                >
                  {options.map((option) => (
                    <option
                      key={option.wallet.id}
                      value={option.wallet.id}
                      disabled={option.wallet.id === sourceId}
                    >
                      {optionLabel(option)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-row">
              <label className="form-field">
                <span>Transfer date</span>
                <input
                  type="date"
                  required
                  max={todayIsoDate()}
                  value={transferDate}
                  onChange={(event) => setTransferDate(event.target.value)}
                />
              </label>
              <label className="form-field">
                <span>Amount sent{source ? ` (${source.wallet.currency})` : ""}</span>
                <input
                  type="number"
                  min="0.01"
                  max={source?.wallet.cash_balance}
                  step="any"
                  required
                  value={sourceAmount}
                  onChange={(event) => setSourceAmount(event.target.value)}
                />
              </label>
            </div>
            {crossCurrency && (
              <label className="form-field">
                <span>Amount received ({destination?.wallet.currency})</span>
                <input
                  type="number"
                  min="0.01"
                  step="any"
                  required
                  value={destinationAmount}
                  onChange={(event) => setDestinationAmount(event.target.value)}
                />
              </label>
            )}
            <p className="quiet-copy">
              {source && sourceAmount && !sourceValid
                ? `Only ${amount(source.wallet.cash_balance, source.wallet.currency, 2)} is available in this wallet.`
                : crossCurrency
                  ? "The wallets use different currencies, so enter the amount the destination actually received."
                  : "Both wallets use the same currency, so the received amount equals the amount sent."}
            </p>
            {source && destination && source.wallet.id === destination.wallet.id && (
              <div className="inline-error" role="alert">Choose two different wallets.</div>
            )}
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={onClose}>
                Cancel
              </button>
              <button className="button button-primary" type="submit" disabled={saving || !canSubmit}>
                {saving ? "Transferring…" : "Transfer"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
