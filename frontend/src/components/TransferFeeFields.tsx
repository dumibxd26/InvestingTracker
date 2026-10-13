import type { Currency, TransferFeePayload, TransferFeeSide } from "../types";

export interface FeeDraft {
  amount: string;
  side: TransferFeeSide;
  currency: Currency;
}

export interface ResolvedFee {
  amountText: string;
  amount: number;
  side: TransferFeeSide;
  currency: Currency;
}

export const emptyFeeDraft: FeeDraft = { amount: "", side: "SOURCE", currency: "EUR" };

interface TransferFeeFieldsProps {
  value: FeeDraft;
  onChange: (next: FeeDraft) => void;
  sourceLabel: string;
  destinationLabel: string;
  sourceCurrencies: Currency[];
  destinationCurrencies: Currency[];
}

function sideCurrencies(
  side: TransferFeeSide,
  sourceCurrencies: Currency[],
  destinationCurrencies: Currency[],
): Currency[] {
  return side === "SOURCE" ? sourceCurrencies : destinationCurrencies;
}

export function resolveFeeCurrency(
  draft: FeeDraft,
  sourceCurrencies: Currency[],
  destinationCurrencies: Currency[],
): Currency | undefined {
  const options = sideCurrencies(draft.side, sourceCurrencies, destinationCurrencies);
  return options.includes(draft.currency) ? draft.currency : options[0];
}

export function resolveFee(
  draft: FeeDraft,
  sourceCurrencies: Currency[],
  destinationCurrencies: Currency[],
): ResolvedFee | null {
  if (draft.amount.trim() === "") return null;
  const currency = resolveFeeCurrency(draft, sourceCurrencies, destinationCurrencies);
  if (!currency) return null;
  return {
    amountText: draft.amount,
    amount: Number(draft.amount),
    side: draft.side,
    currency,
  };
}

export function feePayload(fee: ResolvedFee | null): TransferFeePayload {
  if (!fee) return {};
  return {
    fee_amount: fee.amountText,
    fee_currency: fee.currency,
    fee_side: fee.side,
  };
}

export function TransferFeeFields({
  value,
  onChange,
  sourceLabel,
  destinationLabel,
  sourceCurrencies,
  destinationCurrencies,
}: TransferFeeFieldsProps) {
  const currencies = sideCurrencies(value.side, sourceCurrencies, destinationCurrencies);
  const currency = resolveFeeCurrency(value, sourceCurrencies, destinationCurrencies);

  return (
    <div className="form-row">
      <label className="form-field">
        <span>Fee / tax (optional)</span>
        <input
          type="number"
          min="0.01"
          step="any"
          value={value.amount}
          onChange={(event) => onChange({ ...value, amount: event.target.value })}
        />
      </label>
      <label className="form-field">
        <span>Deducted from</span>
        <select
          value={value.side}
          onChange={(event) => {
            const side = event.target.value as TransferFeeSide;
            const firstCurrency = sideCurrencies(side, sourceCurrencies, destinationCurrencies)[0];
            onChange({ ...value, side, currency: firstCurrency ?? value.currency });
          }}
        >
          <option value="SOURCE">{sourceLabel}</option>
          <option value="DESTINATION">{destinationLabel}</option>
        </select>
      </label>
      {currencies.length > 1 && (
        <label className="form-field">
          <span>Fee currency</span>
          <select
            value={currency ?? ""}
            onChange={(event) => onChange({ ...value, currency: event.target.value as Currency })}
          >
            {currencies.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}
