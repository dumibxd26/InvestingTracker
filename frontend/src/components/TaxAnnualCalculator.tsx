import { useEffect, useState } from "react";
import { Calculator, RefreshCw } from "lucide-react";
import { ApiError, api } from "../api";
import { amount } from "../format";
import type { TaxAnnualSummary, UserProfile } from "../types";

interface TaxAnnualCalculatorProps {
  profile: UserProfile;
}

function statusLabel(status: string): string {
  switch (status) {
    case "country_rule_estimate":
      return "Estimated from the selected country rules";
    case "incomplete":
      return "Incomplete";
    case "unsupported":
      return "No supported calculator for this country/year";
    case "not_configured":
      return "Tax residence and year are not configured";
    default:
      return status;
  }
}

export function TaxAnnualCalculator({ profile }: TaxAnnualCalculatorProps) {
  const [qualifyingIncome, setQualifyingIncome] = useState("");
  const [summary, setSummary] = useState<TaxAnnualSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSummary(null);
    setError("");
  }, [profile.tax_residence_country_code, profile.tax_year]);

  async function calculate() {
    if (!qualifyingIncome.trim()) {
      setError("Enter your total qualifying annual investment income in RON.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.calculateAnnualTaxSummary({
        annual_qualifying_income_ron: qualifyingIncome.trim(),
      });
      setSummary(result);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "The annual tax estimate could not be calculated.",
      );
    } finally {
      setBusy(false);
    }
  }

  const configured = Boolean(
    profile.tax_residence_country_code && profile.tax_year,
  );

  return (
    <section className="tax-annual-calculator">
      <div className="tax-annual-heading">
        <div>
          <div className="eyebrow">Year-end estimate · {profile.tax_year ?? "—"}</div>
          <h3>Investment-income CASS calculator</h3>
        </div>
        <span className="status-pill status-planned">
          {profile.tax_residence_country_code ?? "Country not set"}
        </span>
      </div>
      <p>
        Enter your total annual non-salary income from the categories subject to CASS, in RON,
        after checking all brokers and other eligible sources. Do not include salary. For
        foreign-currency income, apply the legally appropriate annual conversion before
        entering the total. CASS is 10% of a threshold-based base, not 10% of all income.
      </p>
      <div className="tax-annual-input-row">
        <label className="form-field">
          <span>Qualifying annual income · RON</span>
          <input
            type="number"
            min="0"
            max="1000000000"
            step="0.01"
            value={qualifyingIncome}
            onChange={(event) => setQualifyingIncome(event.target.value)}
            disabled={!configured || busy}
            placeholder="e.g. 30000"
          />
        </label>
        <button
          className="button button-primary"
          type="button"
          onClick={() => void calculate()}
          disabled={!configured || busy}
        >
          {busy ? <RefreshCw className="spin-icon" size={15} /> : <Calculator size={15} />}
          {busy ? "Calculating…" : "Calculate CASS"}
        </button>
      </div>
      <small className="tax-annual-hint">
        This uses your saved tax residence/year and the rule pack’s minimum wage for 1 January,
        unless you saved a manual override above. Save profile changes before calculating.
      </small>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {summary && (
        <div className="tax-annual-result" role="status">
          <div className="tax-annual-result-top">
            <span>
              <small>{statusLabel(summary.cass_status)}</small>
              <strong>
                {summary.estimated_cass_ron === null
                  ? "No CASS amount calculated"
                  : amount(summary.estimated_cass_ron, "RON", 2)}
              </strong>
            </span>
            <span className="tax-annual-rate">
              {summary.cass_rate === null
                ? "—"
                : `${(Number(summary.cass_rate) * 100).toFixed(0)}% CASS`}
            </span>
          </div>
          {summary.minimum_monthly_wage_ron && (
            <small>
              Minimum wage used: {amount(summary.minimum_monthly_wage_ron, "RON", 2)} per month
              · rule pack {summary.rule_version}
            </small>
          )}
          {summary.threshold_bands.length > 0 && (
            <div className="tax-threshold-list">
              {summary.threshold_bands.map((band) => (
                <div key={band.wage_multiple}>
                  <span>
                    {band.wage_multiple}× minimum wage · threshold{" "}
                    {amount(band.threshold_ron, "RON", 2)}
                  </span>
                  <strong>
                    {band.cass_at_threshold_ron
                      ? amount(band.cass_at_threshold_ron, "RON", 2)
                      : "—"}
                  </strong>
                </div>
              ))}
            </div>
          )}
          {summary.cass_taxable_base_ron !== null && (
            <small>
              Applied contribution base: {amount(summary.cass_taxable_base_ron, "RON", 2)}
              {summary.qualifying_income_ron !== null
                ? ` · qualifying income entered: ${amount(summary.qualifying_income_ron, "RON", 2)}`
                : ""}
            </small>
          )}
          {summary.warnings.map((warning) => (
            <small className="tax-annual-warning" key={warning}>{warning}</small>
          ))}
          {summary.source_urls.map((source) => (
            <a href={source} key={source} target="_blank" rel="noreferrer">
              Official source
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
