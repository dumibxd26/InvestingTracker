import { useState } from "react";
import {
  Alert,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { api, ApiError } from "../api";
import { formatMoney } from "../format";
import type {
  AccountSummary,
  Currency,
  TaxAnnualSummary,
  TaxReportingMethod,
} from "../types";
import { colors } from "../theme";
import {
  ActionButton,
  Card,
  ChoiceGroup,
  Field,
  LoadingState,
  Notice,
  Page,
  ScreenHeader,
  SectionHeading,
} from "../ui";
import { useWorkspace } from "../workspace";

type AccountTaxSettings = {
  country: string;
  method: TaxReportingMethod;
};

const currencyOptions: { label: string; value: Currency }[] = [
  { label: "EUR", value: "EUR" },
  { label: "USD", value: "USD" },
  { label: "RON", value: "RON" },
];

const taxMethods: { label: string; value: TaxReportingMethod }[] = [
  { label: "Legacy/manual", value: "legacy_manual" },
  { label: "Withholding agent", value: "withholding_agent" },
  { label: "Annual self-assessment", value: "annual_self_assessment" },
  { label: "Tax exempt", value: "tax_exempt" },
];

function accountTaxSettings(account: AccountSummary): AccountTaxSettings {
  return {
    country: account.broker_country_code ?? "",
    method: account.tax_reporting_method,
  };
}

export function SettingsScreen() {
  const {
    profile,
    dashboard,
    saveProfile,
    reload,
    logout,
    refreshing,
  } = useWorkspace();
  const [displayName, setDisplayName] = useState(profile.display_name);
  const [baseCurrency, setBaseCurrency] = useState<Currency>(
    profile.base_currency,
  );
  const [usdPerEur, setUsdPerEur] = useState(profile.usd_per_eur ?? "");
  const [taxCountry, setTaxCountry] = useState(
    profile.tax_residence_country_code ?? "",
  );
  const [taxYear, setTaxYear] = useState(
    profile.tax_year ? String(profile.tax_year) : "",
  );
  const [minimumWage, setMinimumWage] = useState(
    profile.tax_minimum_monthly_wage ?? "",
  );
  const [annualIncome, setAnnualIncome] = useState("");
  const [accountTax, setAccountTax] = useState<
    Record<string, AccountTaxSettings>
  >({});
  const [summary, setSummary] = useState<TaxAnnualSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [savingAccountId, setSavingAccountId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [taxError, setTaxError] = useState("");
  const [accountTaxError, setAccountTaxError] = useState("");

  async function savePersonalSettings() {
    if (displayName.trim().length < 2) {
      setError("Display name must contain at least two characters.");
      return;
    }
    if (taxCountry.trim() && !/^[A-Za-z]{2}$/.test(taxCountry.trim())) {
      setError("Tax residence must be a two-letter country code.");
      return;
    }
    if (taxCountry.trim() && taxYear.trim()) {
      const year = Number(taxYear);
      if (!Number.isInteger(year) || year < 2000 || year > 2100) {
        setError("Tax year must be between 2000 and 2100.");
        return;
      }
    }

    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.updateProfile({
        display_name: displayName.trim(),
        base_currency: baseCurrency,
        usd_per_eur: usdPerEur.trim() || null,
        tax_residence_country_code: taxCountry.trim().toUpperCase() || null,
        tax_year: taxCountry.trim() && taxYear.trim() ? Number(taxYear) : null,
        tax_minimum_monthly_wage:
          taxCountry.trim() && taxYear.trim()
            ? minimumWage.trim() || null
            : null,
      });
      saveProfile(updated);
      setMessage("Your personal settings are saved.");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Your settings could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  function updateAccountTax(
    accountId: string,
    patch: Partial<AccountTaxSettings>,
  ) {
    const account = dashboard?.accounts.find((item) => item.id === accountId);
    if (!account) return;
    setAccountTax((current) => ({
      ...current,
      [accountId]: {
        ...(current[accountId] ?? accountTaxSettings(account)),
        ...patch,
      },
    }));
  }

  async function saveAccountSettings(accountId: string) {
    const account = dashboard?.accounts.find((item) => item.id === accountId);
    if (!account) return;
    const settings = accountTax[accountId] ?? accountTaxSettings(account);
    const country = settings.country.trim().toUpperCase();
    if (country && !/^[A-Z]{2}$/.test(country)) {
      setAccountTaxError("Broker country must be a two-letter country code.");
      return;
    }
    setSavingAccountId(accountId);
    setAccountTaxError("");
    try {
      await api.updateAccountTaxProfile(accountId, {
        broker_country_code: country || null,
        tax_reporting_method: settings.method,
      });
      await reload();
      setAccountTax((current) => {
        const next = { ...current };
        delete next[accountId];
        return next;
      });
    } catch (cause) {
      setAccountTaxError(
        cause instanceof ApiError
          ? cause.message
          : "The account tax method could not be saved.",
      );
    } finally {
      setSavingAccountId(null);
    }
  }

  async function calculateTax() {
    if (!annualIncome.trim() || !Number.isFinite(Number(annualIncome))) {
      setTaxError("Enter qualifying annual investment income in RON.");
      return;
    }
    if (Number(annualIncome) < 0) {
      setTaxError("Income cannot be negative.");
      return;
    }
    setTaxError("");
    setSummary(null);
    setBusy(true);
    try {
      setSummary(
        await api.calculateAnnualTaxSummary({
          annual_qualifying_income_ron: annualIncome.trim(),
        }),
      );
    } catch (cause) {
      setTaxError(
        cause instanceof ApiError
          ? cause.message
          : "The annual estimate could not be calculated.",
      );
    } finally {
      setBusy(false);
    }
  }

  function confirmLogout() {
    Alert.alert(
      "Sign out?",
      "Your local sign-in token will be removed from this device.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Sign out",
          style: "destructive",
          onPress: () => {
            void logout().catch((cause) =>
              Alert.alert(
                "Signed out locally",
                cause instanceof ApiError
                  ? cause.message
                  : "The server could not confirm sign-out. Your device token was removed.",
              ),
            );
          },
        },
      ],
    );
  }

  if (!dashboard) {
    return (
      <LoadingState
        label="Loading profile settings"
        error={error}
        onRetry={() => void reload()}
      />
    );
  }

  return (
    <Page
      refreshing={refreshing}
      onRefresh={() => void reload()}
      safeEdges={["bottom"]}
    >
      <ScreenHeader
        eyebrow="Your application account"
        title="Profile settings."
        subtitle="Manage your sign-in profile and valuation assumptions."
      />
      <Card>
        <SectionHeading title="Personal profile" />
        <Text style={styles.username}>@{profile.username}</Text>
        <Field
          label="Display name"
          value={displayName}
          onChangeText={setDisplayName}
          placeholder="Your name"
          autoCapitalize="words"
          maxLength={80}
        />
        <ChoiceGroup
          label="Base reporting currency"
          options={currencyOptions}
          value={baseCurrency}
          onChange={(value) => setBaseCurrency(value as Currency)}
        />
        <Field
          label="USD per EUR reference rate (optional)"
          value={usdPerEur}
          onChangeText={setUsdPerEur}
          placeholder="No rate configured"
          keyboardType="decimal-pad"
          helper="Manually supplied. The app does not silently substitute a rate."
        />
        <Field
          label="Tax residence country code (optional)"
          value={taxCountry}
          onChangeText={setTaxCountry}
          placeholder="e.g. RO"
          autoCapitalize="characters"
          maxLength={2}
        />
        <Field
          label="Tax year (optional)"
          value={taxYear}
          onChangeText={setTaxYear}
          placeholder="e.g. 2026"
          keyboardType="number-pad"
        />
        <Field
          label="Minimum monthly wage in RON (optional)"
          value={minimumWage}
          onChangeText={setMinimumWage}
          placeholder="Only for supported country rules"
          keyboardType="decimal-pad"
        />
        {error ? <Notice>{error}</Notice> : null}
        {message ? <Notice tone="info">{message}</Notice> : null}
        <ActionButton
          label="Save profile settings"
          onPress={() => void savePersonalSettings()}
          loading={busy}
        />
      </Card>

      <SectionHeading title="Account tax profiles" />
      {accountTaxError ? <Notice>{accountTaxError}</Notice> : null}
      {dashboard.accounts.map((account) => {
        const settings =
          accountTax[account.id] ?? accountTaxSettings(account);
        return (
          <Card key={account.id}>
            <Text style={styles.accountName}>{account.display_name}</Text>
            <Text style={styles.cardMeta}>
              {account.account_type.toLowerCase().replace("_", " ")}
            </Text>
            <Field
              label="Broker country code"
              value={settings.country}
              onChangeText={(value) =>
                updateAccountTax(account.id, { country: value })
              }
              placeholder="e.g. RO"
              autoCapitalize="characters"
              maxLength={2}
            />
            <ChoiceGroup
              label="Tax reporting method"
              options={taxMethods}
              value={settings.method}
              onChange={(value) =>
                updateAccountTax(account.id, {
                  method: value as TaxReportingMethod,
                })
              }
            />
            <ActionButton
              label="Save account tax profile"
              onPress={() => void saveAccountSettings(account.id)}
              loading={savingAccountId === account.id}
              disabled={account.is_sample}
              secondary
            />
          </Card>
        );
      })}
      {!dashboard.accounts.length ? (
        <Card>
          <Text style={styles.cardMeta}>
            Add an account before configuring its broker tax treatment.
          </Text>
        </Card>
      ) : null}

      <Card>
        <SectionHeading title="Annual CASS estimate" />
        <Text style={styles.cardMeta}>
          For supported Romania tax rules only. Enter qualifying investment
          income in RON; this estimate is not a filing calculation.
        </Text>
        <Field
          label="Annual qualifying income (RON)"
          value={annualIncome}
          onChangeText={setAnnualIncome}
          placeholder="0"
          keyboardType="decimal-pad"
        />
        {taxError ? <Notice>{taxError}</Notice> : null}
        <ActionButton
          label="Calculate estimate"
          onPress={() => void calculateTax()}
          loading={busy}
          secondary
        />
        {summary ? (
          <View style={styles.summary}>
            <View style={styles.summaryRow}>
              <Text style={styles.cardMeta}>Rule status</Text>
              <Text style={styles.summaryValue}>{summary.rule_status}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.cardMeta}>Tax year</Text>
              <Text style={styles.summaryValue}>
                {summary.tax_year ?? "Not configured"}
              </Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.cardMeta}>Estimated CASS</Text>
              <Text style={styles.summaryValue}>
                {summary.estimated_cass_ron
                  ? formatMoney(summary.estimated_cass_ron, "RON")
                  : "Not calculated"}
              </Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.cardMeta}>CASS status</Text>
              <Text style={styles.summaryValue}>{summary.cass_status}</Text>
            </View>
            {summary.warnings.map((warning) => (
              <Text key={warning} style={styles.cardMeta}>
                {warning}
              </Text>
            ))}
            {!summary.complete_for_filing ? (
              <Notice tone="info">
                This estimate is incomplete for filing. Review its limitations
                and source links in the web app.
              </Notice>
            ) : null}
          </View>
        ) : null}
      </Card>

      <ActionButton
        label="Sign out"
        onPress={confirmLogout}
        secondary
      />
    </Page>
  );
}

const styles = StyleSheet.create({
  username: { color: colors.primary, fontSize: 13, fontWeight: "800" },
  accountName: { color: colors.text, fontSize: 14, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  summary: { gap: 10, paddingTop: 4 },
  summaryRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  summaryValue: { color: colors.text, fontSize: 12, fontWeight: "700", textAlign: "right" },
});
