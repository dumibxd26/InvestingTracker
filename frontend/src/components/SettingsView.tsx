import { useEffect, useState, type FormEvent } from "react";
import { ArrowRightLeft, CircleHelp, KeyRound, LogOut, Save, ShieldCheck } from "lucide-react";
import { ApiError, api } from "../api";
import type {
  AccountSummary,
  AccountTaxProfileUpdatePayload,
  Currency,
  TaxReportingMethod,
  UserProfile,
} from "../types";

interface SettingsViewProps {
  profile: UserProfile;
  accounts: AccountSummary[];
  onSaved: (profile: UserProfile) => Promise<void>;
  onLogout: () => void;
}

export function SettingsView({ profile, accounts, onSaved, onLogout }: SettingsViewProps) {
  const [displayName, setDisplayName] = useState(profile.display_name);
  const [baseCurrency, setBaseCurrency] = useState<Currency>(profile.base_currency);
  const [usdPerEur, setUsdPerEur] = useState(profile.usd_per_eur ?? "");
  const [taxCountry, setTaxCountry] = useState(profile.tax_residence_country_code ?? "");
  const [taxYear, setTaxYear] = useState(profile.tax_year ? String(profile.tax_year) : "");
  const [minimumWage, setMinimumWage] = useState(profile.tax_minimum_monthly_wage ?? "");
  const [accountTax, setAccountTax] = useState<
    Record<string, { brokerCountryCode: string; method: TaxReportingMethod }>
  >({});
  const [busy, setBusy] = useState(false);
  const [savingAccountId, setSavingAccountId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [accountTaxError, setAccountTaxError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    setDisplayName(profile.display_name);
    setBaseCurrency(profile.base_currency);
    setUsdPerEur(profile.usd_per_eur ?? "");
    setTaxCountry(profile.tax_residence_country_code ?? "");
    setTaxYear(profile.tax_year ? String(profile.tax_year) : "");
    setMinimumWage(profile.tax_minimum_monthly_wage ?? "");
  }, [profile]);

  useEffect(() => {
    setAccountTax(Object.fromEntries(accounts.map((account) => [
      account.id,
      {
        brokerCountryCode: account.broker_country_code ?? "",
        method: account.tax_reporting_method,
      },
    ])));
  }, [accounts]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.updateProfile({
        display_name: displayName,
        base_currency: baseCurrency,
        usd_per_eur: usdPerEur.trim() || null,
        tax_residence_country_code: taxCountry.trim().toUpperCase() || null,
        tax_year: taxCountry.trim() ? Number(taxYear) : null,
        tax_minimum_monthly_wage:
          taxCountry.trim() && taxYear.trim() ? minimumWage.trim() || null : null,
      });
      await onSaved(updated);
      setMessage("Your personal settings are saved.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Your settings could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function saveAccountTax(accountId: string) {
    const settings = accountTax[accountId];
    if (!settings) return;
    setSavingAccountId(accountId);
    setAccountTaxError("");
    try {
      await api.updateAccountTaxProfile(accountId, {
        broker_country_code: settings.brokerCountryCode.trim().toUpperCase() || null,
        tax_reporting_method: settings.method,
      } satisfies AccountTaxProfileUpdatePayload);
      await onSaved(profile);
    } catch (cause) {
      setAccountTaxError(
        cause instanceof ApiError ? cause.message : "The account tax method could not be saved.",
      );
    } finally {
      setSavingAccountId(null);
    }
  }

  return (
    <div className="page-content">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Your application account</div>
          <h1>Profile settings.</h1>
          <p>Manage your sign-in profile and the currency assumptions used to value your own accounts.</p>
        </div>
      </div>
      <div className="settings-grid">
        <section className="panel settings-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">Personal profile</div>
              <h2>Workspace preferences</h2>
            </div>
            <span className="policy-icon"><ArrowRightLeft size={18} /></span>
          </div>
          <form className="settings-form" onSubmit={save}>
            <div className="settings-identity">
              <span className="profile-avatar">{profile.username.slice(0, 2).toUpperCase()}</span>
              <span><strong>@{profile.username}</strong><small>Application username · used to sign in</small></span>
            </div>
            <label className="form-field">
              <span>Display name</span>
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required minLength={2} maxLength={80} />
            </label>
            <label className="form-field">
              <span>Base reporting currency</span>
              <select value={baseCurrency} onChange={(event) => setBaseCurrency(event.target.value as Currency)}>
                <option value="EUR">EUR · Euro</option>
                <option value="USD">USD · US dollar</option>
                <option value="RON">RON · Romanian leu</option>
              </select>
            </label>
            <label className="form-field">
              <span>USD per EUR reference rate <small>optional · manually supplied</small></span>
              <input
                type="number"
                min="0.000001"
                max="100"
                step="0.000001"
                value={usdPerEur}
                onChange={(event) => setUsdPerEur(event.target.value)}
                placeholder="No rate configured"
              />
              <small>Enter how many USD equal 1 EUR. The app does not silently substitute a market rate.</small>
            </label>
            <div className="settings-tax-profile">
              <div>
                <div className="eyebrow">Tax residency</div>
                <strong>Country rules for estimates</strong>
                <p>
                  This is your tax residence, not your broker's country. Tax treatment depends
                  on residence, account wrapper, instrument source, and the event date.
                </p>
              </div>
              <div className="form-row">
                <label className="form-field">
                  <span>Tax residence country code</span>
                  <input
                    value={taxCountry}
                    onChange={(event) => {
                      const nextCountry = event.target.value.toUpperCase();
                      if (nextCountry !== taxCountry) setMinimumWage("");
                      setTaxCountry(nextCountry);
                    }}
                    minLength={2}
                    maxLength={2}
                    pattern="[A-Z]{2}"
                    placeholder="e.g. RO"
                  />
                </label>
                <label className="form-field">
                  <span>Tax year</span>
                  <input
                    type="number"
                    min="2000"
                    max="2100"
                    value={taxYear}
                    required={Boolean(taxCountry)}
                    onChange={(event) => {
                      if (event.target.value !== taxYear) setMinimumWage("");
                      setTaxYear(event.target.value);
                    }}
                    disabled={!taxCountry}
                    placeholder="e.g. 2026"
                  />
                </label>
              </div>
              <label className="form-field">
                <span>Minimum gross monthly wage at tax-year start · optional</span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={minimumWage}
                  onChange={(event) => setMinimumWage(event.target.value)}
                  disabled={!taxCountry}
                  placeholder="Optional reference for future CASS estimates"
                />
                <small>
                  Saved as a reference only. CASS is not currently calculated because the app
                  does not aggregate all qualifying realized income for a tax year.
                </small>
                <small>Changing tax residence or year clears this value so it is not reused for a different jurisdiction or tax year.</small>
              </label>
              <div className={`tax-pack-status tax-pack-${profile.tax_rules_status}`}>
                <strong>
                  {profile.tax_rules_status === "partial"
                    ? `Rule pack: ${profile.tax_rule_version} · partial`
                    : profile.tax_rules_status === "unsupported"
                      ? "No built-in rule pack for this country/year"
                      : profile.tax_rules_status === "not_configured"
                        ? "Tax residence not configured"
                        : `Rule pack: ${profile.tax_rules_status}`}
                </strong>
                {profile.tax_rule_sources.map((source) => (
                  <a href={source} key={source} target="_blank" rel="noreferrer">
                    Official source
                  </a>
                ))}
                {profile.tax_rule_limitations.map((limitation) => <small key={limitation}>{limitation}</small>)}
                <small>
                  Only the Romanian 2026 partial pack is implemented. Other country/year
                  combinations are unsupported; any fallback is explicitly a legacy/manual
                  estimate, not a country-specific determination or tax filing advice.
                </small>
              </div>
            </div>
            {error && <div className="inline-error" role="alert">{error}</div>}
            {message && <div className="settings-saved" role="status">{message}</div>}
            <div className="settings-save-row">
              <span className="settings-hint">Your settings are saved to your application profile.</span>
              <button className="button button-primary" type="submit" disabled={busy}>
                <Save size={15} /> {busy ? "Saving…" : "Save settings"}
              </button>
            </div>
          </form>
          <div className="settings-logout-row">
            <span>
              <strong>Application account</strong>
              <small>Sign out of @{profile.username} on this browser.</small>
            </span>
            <button className="button button-secondary" type="button" onClick={onLogout}>
              <LogOut size={15} /> Sign out
            </button>
          </div>
          {accounts.length > 0 && (
            <section className="settings-tax-accounts">
              <div>
                <div className="eyebrow">Per-account tax handling</div>
                <h3>Broker reporting method</h3>
                <p>
                  Select this from your broker's tax documents. It is not inferred from the
                  provider name or exchange. Romania's local withholding rates are used only
                  when the broker country is explicitly set to RO.
                </p>
              </div>
              {accountTaxError && <div className="inline-error" role="alert">{accountTaxError}</div>}
              {accounts.map((account) => {
                const settings = accountTax[account.id];
                if (!settings) return null;
                return (
                  <div className="settings-tax-account-row" key={account.id}>
                    <strong>{account.display_name}</strong>
                    <label className="form-field">
                      <span>Broker country</span>
                      <input
                        value={settings.brokerCountryCode}
                        minLength={2}
                        maxLength={2}
                        pattern="[A-Z]{2}"
                        placeholder="e.g. RO"
                        onChange={(event) => setAccountTax((current) => ({
                          ...current,
                          [account.id]: {
                            ...settings,
                            brokerCountryCode: event.target.value.toUpperCase(),
                          },
                        }))}
                      />
                    </label>
                    <label className="form-field">
                      <span>Tax reporting</span>
                      <select
                        value={settings.method}
                        onChange={(event) => setAccountTax((current) => ({
                          ...current,
                          [account.id]: {
                            ...settings,
                            method: event.target.value as TaxReportingMethod,
                          },
                        }))}
                      >
                        <option value="legacy_manual">Manual / legacy per-holding rate</option>
                        <option value="withholding_agent">Broker withholds at source</option>
                        <option value="annual_self_assessment">Annual self-assessment</option>
                        <option value="tax_exempt">Tax-exempt wrapper</option>
                      </select>
                    </label>
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={savingAccountId === account.id}
                      onClick={() => void saveAccountTax(account.id)}
                    >
                      <Save size={14} />
                      {savingAccountId === account.id ? "Saving…" : "Save"}
                    </button>
                  </div>
                );
              })}
            </section>
          )}
        </section>
        <aside className="settings-aside">
          <section className="panel settings-info-panel">
            <span className="next-step-icon"><ShieldCheck size={18} /></span>
            <div className="eyebrow">Account separation</div>
            <h2>Your portfolio belongs to this sign-in.</h2>
            <p>Accounts, goals, cash-flow schedules, policies, and recommendation history are scoped to your registered application user.</p>
          </section>
          <section className="panel settings-info-panel">
            <span className="next-step-icon"><KeyRound size={18} /></span>
            <div className="eyebrow">Password security</div>
            <h2>Passwords are not stored in plain text.</h2>
            <p>Sign-in uses Argon2 password hashing and revocable, expiring login sessions. Password recovery is not enabled in this local prototype.</p>
          </section>
          <div className="privacy-note"><CircleHelp size={15} /><span>Manual bank/broker accounts are separate from this username/password application account. Bank connectivity is not enabled.</span></div>
        </aside>
      </div>
    </div>
  );
}
