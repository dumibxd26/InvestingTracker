import { useState, type FormEvent } from "react";
import { Landmark, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { AccountType, Currency, UserProfile } from "../types";

type InterestModel = "SAME_ACCOUNT" | "SEPARATE_ACCOUNT";

interface AccountDialogProps {
  profile: UserProfile;
  onClose: () => void;
  onCreated: () => Promise<void>;
}

export function AccountDialog({ profile, onClose, onCreated }: AccountDialogProps) {
  const [currency, setCurrency] = useState<Currency>(profile.base_currency);
  const [accountType, setAccountType] = useState<AccountType>("BROKERAGE");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [interestModel, setInterestModel] = useState<InterestModel>("SAME_ACCOUNT");
  const [interestRateEntered, setInterestRateEntered] = useState(false);
  const supportsInterest = accountType !== "EMPLOYER_PLAN";
  const offersInterestModel = accountType === "BANK";
  const separateInterestAccount = offersInterestModel && interestModel === "SEPARATE_ACCOUNT";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const providerCode = String(form.get("provider") ?? "MANUAL");
    const interestPercent = supportsInterest ? String(form.get("interestPercent") ?? "").trim() : "";
    const interestFields = interestPercent
      ? {
          annual_interest_rate: String(Number(interestPercent) / 100),
          interest_start_date: String(form.get("interestStart") || ""),
        }
      : {};

    try {
      await api.createAccount({
        display_name: String(form.get("name") ?? "").trim(),
        provider_code: providerCode,
        account_type: accountType,
        currency,
        opening_cash: String(form.get("openingCash") || "0"),
        ...(separateInterestAccount ? {} : interestFields),
      });
      if (separateInterestAccount && interestPercent) {
        try {
          await api.createAccount({
            display_name: String(form.get("interestAccountName") ?? "").trim(),
            provider_code: providerCode,
            account_type: "SAVINGS",
            currency,
            opening_cash: "0",
            ...interestFields,
          });
        } catch (cause) {
          await onCreated();
          setError(
            `The spending account was saved, but its interest account could not be created: ${
              cause instanceof ApiError ? cause.message : "unknown error"
            }. Add it from the Portfolio page.`,
          );
          return;
        }
      }
      await onCreated();
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The account could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title">
        <div className="modal-heading">
          <div>
            <div className="eyebrow">Saved in your local database</div>
            <h2 id="account-dialog-title">Add an account</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="modal-intro">
          Set up a bank or broker, then add currency sub-accounts for EUR, USD, or RON. The selected currency and opening cash create its first sub-account.
        </p>
        <form className="goal-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Account name</span>
            <input name="name" required minLength={2} maxLength={80} placeholder="e.g. Main brokerage" autoFocus />
          </label>
          <div className="form-row">
            <label className="form-field">
              <span>Institution</span>
              <select name="provider" defaultValue="MANUAL">
                <option value="MANUAL">Manual entry</option>
                <option value="INTERACTIVE_BROKERS">Interactive Brokers</option>
                <option value="TRADE_REPUBLIC">Trade Republic</option>
                <option value="XTB">XTB</option>
                <option value="CHARLES_SCHWAB">Charles Schwab</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
            <label className="form-field">
              <span>Account type</span>
              <select value={accountType} onChange={(event) => setAccountType(event.target.value as AccountType)}>
                <option value="BROKERAGE">Brokerage</option>
                <option value="BANK">Bank account</option>
                <option value="SAVINGS">Savings / deposit</option>
                <option value="EMPLOYER_PLAN">Employer plan</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label className="form-field">
              <span>Initial sub-account currency</span>
              <select value={currency} onChange={(event) => setCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
                <option value="RON">RON · Romanian leu</option>
              </select>
            </label>
            <label className="form-field">
              <span>{accountType === "EMPLOYER_PLAN" ? "Opening cash balance · unavailable" : `Opening balance (${currency})`}</span>
              {accountType === "EMPLOYER_PLAN" ? (
                <input name="openingCash" type="number" value="0" disabled />
              ) : (
                <input name="openingCash" type="number" min="0" max="100000000" step="0.01" defaultValue="0" />
              )}
            </label>
          </div>
          {supportsInterest && (
            <div className="grant-tax-fields">
              <div className="eyebrow">Economy account interest · optional</div>
              {offersInterestModel && (
                <fieldset className="interest-model-choice">
                  <legend>Where is the interest paid?</legend>
                  <label className="interest-model-option">
                    <input
                      type="radio"
                      name="interestModel"
                      checked={interestModel === "SAME_ACCOUNT"}
                      onChange={() => setInterestModel("SAME_ACCOUNT")}
                    />
                    <span>This bank account is also the interest account (Salt, XTB)</span>
                  </label>
                  <label className="interest-model-option">
                    <input
                      type="radio"
                      name="interestModel"
                      checked={interestModel === "SEPARATE_ACCOUNT"}
                      onChange={() => setInterestModel("SEPARATE_ACCOUNT")}
                    />
                    <span>Separate interest account, apart from spending (ING, BT)</span>
                  </label>
                </fieldset>
              )}
              {separateInterestAccount && (
                <label className="form-field">
                  <span>Interest account name</span>
                  <input
                    name="interestAccountName"
                    required={interestRateEntered}
                    minLength={2}
                    maxLength={80}
                    placeholder="e.g. ING savings"
                  />
                </label>
              )}
              <div className="form-row">
                <label className="form-field">
                  <span>Annual interest rate (%)</span>
                  <input
                    name="interestPercent"
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    placeholder="e.g. 3.5"
                    onChange={(event) => setInterestRateEntered(event.target.value.trim() !== "")}
                  />
                </label>
                <label className="form-field">
                  <span>Interest counts from</span>
                  <input name="interestStart" type="date" defaultValue={new Date().toLocaleDateString("sv-SE")} />
                </label>
              </div>
              <p className="quiet-copy">The yearly rate is divided by 12 and credited to the balance once a month on the same day of the month. Leave the rate blank for no interest. It is an estimate, not a bank connection.</p>
              {separateInterestAccount && (
                <p className="quiet-copy">The interest account is created as a savings account in the same currency, starting at 0. The spending account earns no interest. Move money into the interest account with Add funds on the Portfolio page.</p>
              )}
            </div>
          )}
          <div className="account-storage-note">
            <Landmark size={15} />
            <span>This creates the bank/broker and its first currency sub-account. Additional currencies can be added from the Portfolio page; no sign-in or broker sync is enabled.</span>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save account"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
