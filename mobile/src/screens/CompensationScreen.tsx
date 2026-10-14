import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { api, ApiError } from "../api";
import { formatDate, formatMoney, formatNumber, localDateValue } from "../format";
import type {
  Dashboard,
  MarketSymbol,
  StockPurchasePlanPayload,
  VestingGrantPayload,
} from "../types";
import { colors } from "../theme";
import {
  ActionButton,
  Badge,
  Card,
  ChoiceGroup,
  DateField,
  Field,
  FormSheet,
  LoadingState,
  Notice,
  Page,
  ScreenHeader,
  SectionHeading,
} from "../ui";
import { useWorkspace } from "../workspace";

type CompensationAction = "grant" | "purchase" | null;
const EMPTY_ACCOUNTS: Dashboard["accounts"] = [];

function percentValue(value: string): string {
  return String(Number(value) / 100);
}

export function CompensationScreen() {
  const { dashboard, currency, refreshing, error, reload } = useWorkspace();
  const [action, setAction] = useState<CompensationAction>(null);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [formError, setFormError] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSymbol[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<MarketSymbol | null>(null);

  const [grantType, setGrantType] = useState<"rsu" | "option">("rsu");
  const [grantLabel, setGrantLabel] = useState("");
  const [grantDate, setGrantDate] = useState(localDateValue());
  const [grantUnits, setGrantUnits] = useState("");
  const [durationMonths, setDurationMonths] = useState("");
  const [cliffMonths, setCliffMonths] = useState("");
  const [intervalMonths, setIntervalMonths] = useState("");
  const [taxPercent, setTaxPercent] = useState("");
  const [shortSaleTaxPercent, setShortSaleTaxPercent] = useState("");
  const [longSaleTaxPercent, setLongSaleTaxPercent] = useState("");
  const [longTermMonths, setLongTermMonths] = useState("");
  const [strikePrice, setStrikePrice] = useState("");

  const [planName, setPlanName] = useState("");
  const [shareAccountId, setShareAccountId] = useState("");
  const [walletId, setWalletId] = useState("");
  const [shares, setShares] = useState("");
  const [purchaseDate, setPurchaseDate] = useState(localDateValue());
  const [discountPercent, setDiscountPercent] = useState("");
  const [receiptTaxPercent, setReceiptTaxPercent] = useState("");
  const [profitTaxPercent, setProfitTaxPercent] = useState("");
  const [referencePrice, setReferencePrice] = useState("");

  const accounts = dashboard?.accounts ?? EMPTY_ACCOUNTS;
  const shareAccounts = useMemo(
    () =>
      accounts.filter(
        (account) =>
          account.account_type !== "SAVINGS" && !account.is_sample,
      ),
    [accounts],
  );
  const fundingWallets = useMemo(
    () =>
      accounts
        .filter(
          (account) =>
            account.account_type !== "EMPLOYER_PLAN" && !account.is_sample,
        )
        .flatMap((account) =>
          account.subaccounts.map((subaccount) => ({
            account,
            subaccount,
          })),
        ),
    [accounts],
  );
  const selectedWallet = fundingWallets.find(
    ({ subaccount }) => subaccount.id === walletId,
  );
  const totalGross = (dashboard?.vesting ?? []).reduce(
    (sum, grant) => sum + Number(grant.gross_value),
    0,
  );
  const totalNet = (dashboard?.vesting ?? []).reduce(
    (sum, grant) => sum + Number(grant.estimated_net_value),
    0,
  );
  const scheduledPlans = (dashboard?.purchase_plans ?? []).filter(
    (plan) => plan.status === "scheduled",
  );
  const scheduledBenefit = scheduledPlans.reduce(
    (sum, plan) => sum + Number(plan.net_benefit),
    0,
  );

  useEffect(() => {
    if (
      !action ||
      !dashboard?.market_data_provider_configured ||
      selectedSymbol ||
      query.trim().length < 2
    ) {
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => {
      setSearching(true);
      setFormError("");
      void api
        .searchSymbols(query.trim(), controller.signal)
        .then((response) =>
          setResults(
            response.results.filter(
              (result) => result.instrument_type === "STOCK",
            ),
          ),
        )
        .catch((cause) => {
          if (!controller.signal.aborted) {
            setResults([]);
            setFormError(
              cause instanceof ApiError
                ? cause.message
                : "Symbol search failed.",
            );
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 300);
    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, [action, dashboard?.market_data_provider_configured, query, selectedSymbol]);

  function openForm(nextAction: Exclude<CompensationAction, null>) {
    setAction(nextAction);
    setFormError("");
    setQuery("");
    setResults([]);
    setSearching(false);
    setSelectedSymbol(null);
    if (nextAction === "grant") {
      setGrantType("rsu");
      setGrantLabel("");
      setGrantDate(localDateValue());
      setGrantUnits("");
      setDurationMonths("");
      setCliffMonths("");
      setIntervalMonths("");
      setTaxPercent("");
      setShortSaleTaxPercent("");
      setLongSaleTaxPercent("");
      setLongTermMonths("");
      setStrikePrice("");
    } else {
      const account = shareAccounts[0];
      const wallet =
        fundingWallets.find(({ subaccount }) => subaccount.currency === currency) ??
        fundingWallets[0];
      setPlanName("");
      setShareAccountId(account?.id ?? "");
      setWalletId(wallet?.subaccount.id ?? "");
      setShares("");
      setPurchaseDate(localDateValue());
      setDiscountPercent("");
      setReceiptTaxPercent("");
      setProfitTaxPercent("");
      setReferencePrice("");
    }
  }

  async function saveGrant() {
    if (!selectedSymbol) {
      setFormError("Choose a stock listing.");
      return;
    }
    const units = Number(grantUnits);
    const duration = Number(durationMonths);
    const cliff = Number(cliffMonths);
    const interval = Number(intervalMonths);
    const longTerm = Number(longTermMonths);
    const rates = [taxPercent, shortSaleTaxPercent, longSaleTaxPercent].map(Number);
    if (!Number.isFinite(units) || units <= 0) {
      setFormError("Total units must be greater than zero.");
      return;
    }
    if (
      !Number.isInteger(duration) ||
      !Number.isInteger(cliff) ||
      !Number.isInteger(interval) ||
      duration <= 0 ||
      duration > 600 ||
      cliff < 0 ||
      cliff > duration ||
      interval <= 0 ||
      interval > 60
    ) {
      setFormError("Enter a valid vesting duration, cliff, and interval in months.");
      return;
    }
    if (
      [taxPercent, shortSaleTaxPercent, longSaleTaxPercent].some(
        (value) => !value.trim(),
      ) ||
      rates.some((rate) => !Number.isFinite(rate) || rate < 0 || rate > 100) ||
      !Number.isInteger(longTerm) ||
      longTerm <= 0 ||
      longTerm > 1200
    ) {
      setFormError("Enter sale and vesting tax assumptions from 0 to 100%, and a positive long-term holding period.");
      return;
    }
    if (
      grantType === "option" &&
      (!strikePrice.trim() ||
        !Number.isFinite(Number(strikePrice)) ||
        Number(strikePrice) <= 0)
    ) {
      setFormError("Enter a valid option strike price.");
      return;
    }

    const payload: VestingGrantPayload = {
      symbol: selectedSymbol.symbol,
      mic_code: selectedSymbol.mic_code,
      exchange: selectedSymbol.exchange,
      grant_type: grantType,
      ...(grantLabel.trim() ? { grant_label: grantLabel.trim() } : {}),
      grant_date: grantDate,
      total_units: grantUnits.trim(),
      duration_months: duration,
      cliff_months: cliff,
      interval_months: interval,
      tax_rate_assumption: percentValue(taxPercent),
      short_term_sale_tax_rate: percentValue(shortSaleTaxPercent),
      long_term_sale_tax_rate: percentValue(longSaleTaxPercent),
      long_term_holding_period_days: Math.round((longTerm * 365) / 12),
      ...(grantType === "option" ? { strike_price: strikePrice.trim() } : {}),
    };

    setBusy(true);
    setFormError("");
    try {
      await api.createVestingGrant(payload);
      await reload();
      setAction(null);
    } catch (cause) {
      setFormError(
        cause instanceof ApiError ? cause.message : "The grant could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function savePurchasePlan() {
    if (!selectedSymbol || !selectedWallet || !shareAccountId) {
      setFormError("Choose a stock listing, share account, and funding wallet.");
      return;
    }
    const inputRates = [
      discountPercent,
      receiptTaxPercent,
      profitTaxPercent,
    ].map(Number);
    if (
      !Number.isFinite(Number(shares)) ||
      Number(shares) <= 0 ||
      Number(shares) > 1_000_000_000 ||
      [discountPercent, receiptTaxPercent, profitTaxPercent].some(
        (value) => !value.trim(),
      ) ||
      inputRates.some(
        (rate) => !Number.isFinite(rate) || rate < 0 || rate > 100,
      ) ||
      Number(discountPercent) >= 100
    ) {
      setFormError("Enter positive shares and rate assumptions from 0 to 100%.");
      return;
    }
    if (
      referencePrice.trim() &&
      (!Number.isFinite(Number(referencePrice)) || Number(referencePrice) <= 0)
    ) {
      setFormError("Reference price must be greater than zero.");
      return;
    }
    const payload: StockPurchasePlanPayload = {
      ...(planName.trim() ? { name: planName.trim() } : {}),
      symbol: selectedSymbol.symbol,
      mic_code: selectedSymbol.mic_code,
      exchange: selectedSymbol.exchange,
      account_id: shareAccountId,
      subaccount_id: selectedWallet.subaccount.id,
      shares: shares.trim(),
      purchase_date: purchaseDate,
      discount_rate: percentValue(discountPercent),
      receipt_tax_rate: percentValue(receiptTaxPercent),
      sale_profit_tax_rate: percentValue(profitTaxPercent),
      ...(referencePrice.trim()
        ? { reference_price: referencePrice.trim() }
        : {}),
    };

    setBusy(true);
    setFormError("");
    try {
      await api.createStockPurchasePlan(payload);
      await reload();
      setAction(null);
    } catch (cause) {
      setFormError(
        cause instanceof ApiError
          ? cause.message
          : "The purchase plan could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  function deleteGrant(id: string, symbol: string) {
    Alert.alert(
      "Remove equity grant?",
      `Remove the ${symbol} grant from InvestingTracker? This does not change your employer plan.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .deleteVestingGrant(id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not remove grant",
                  cause instanceof ApiError ? cause.message : "Please try again.",
                ),
              )
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }

  function deletePlan(id: string, name: string, status: string) {
    Alert.alert(
      "Remove purchase plan?",
      status === "scheduled"
        ? `Remove "${name}"? Nothing has been bought or deducted yet.`
        : `Remove the history record "${name}"? Owned shares and cash stay unchanged.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .deleteStockPurchasePlan(id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not remove plan",
                  cause instanceof ApiError ? cause.message : "Please try again.",
                ),
              )
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }

  if (!dashboard) {
    return (
      <LoadingState
        label="Loading equity and deposits"
        error={error}
        onRetry={() => void reload()}
      />
    );
  }

  return (
    <>
      <Page
        refreshing={refreshing}
        onRefresh={() => void reload()}
        safeEdges={["bottom"]}
      >
        <ScreenHeader
          eyebrow="Future liquidity, clearly labelled"
          title="Equity & deposits."
          subtitle="Unvested awards are estimates, not shares you own or cash available to spend."
        />
        {error ? <Notice>{error}</Notice> : null}
        <View style={styles.metrics}>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>UNVESTED GRANTS | GROSS</Text>
            <Text style={styles.metricValue}>{formatMoney(totalGross, currency)}</Text>
            <Text style={styles.cardMeta}>Latest cached quote</Text>
          </Card>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>AFTER ASSUMED TAX AT VEST</Text>
            <Text style={styles.metricValue}>{formatMoney(totalNet, currency)}</Text>
            <Text style={styles.cardMeta}>Estimate only</Text>
          </Card>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>DEPOSITS AT MATURITY</Text>
            <Text style={styles.metricValue}>
              {formatMoney(dashboard.totals.fixed_deposits, currency)}
            </Text>
            <Text style={styles.cardMeta}>{dashboard.deposits.length} tracked deposits</Text>
          </Card>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>SCHEDULED PURCHASE BENEFIT</Text>
            <Text style={styles.metricValue}>
              {formatMoney(scheduledBenefit, currency)}
            </Text>
            <Text style={styles.cardMeta}>{scheduledPlans.length} scheduled plans</Text>
          </Card>
        </View>
        <View style={styles.actions}>
          <ActionButton
            label="Add equity grant"
            onPress={() => openForm("grant")}
            disabled={!dashboard.market_data_provider_configured}
            secondary
          />
          <ActionButton
            label="Plan discounted share purchase"
            onPress={() => openForm("purchase")}
            disabled={
              !dashboard.market_data_provider_configured ||
              !shareAccounts.length ||
              !fundingWallets.length
            }
          />
        </View>
        {!dashboard.market_data_provider_configured ? (
          <Text style={styles.cardMeta}>
            Configure TWELVE_DATA_API_KEY on the backend to search stock
            listings for grants and purchase plans.
          </Text>
        ) : null}
        <SectionHeading title={`Equity grants (${dashboard.vesting.length})`} />
        {dashboard.vesting.length ? (
          dashboard.vesting.map((grant) => (
            <Card key={grant.id}>
              <View style={styles.cardTop}>
                <View style={styles.grantCopy}>
                  <Text style={styles.cardTitle}>
                    {grant.grant_label || grant.symbol}
                  </Text>
                  <Text style={styles.cardMeta}>
                    {grant.symbol}  |  {grant.grant_type.toUpperCase()}  |{" "}
                    {formatNumber(grant.units)} units
                  </Text>
                </View>
                <Badge
                  label={`${formatNumber(grant.vested_percent, 0)}% vested`}
                  tone={Number(grant.vested_percent) >= 100 ? "positive" : "warning"}
                />
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.cardMeta}>Gross estimate</Text>
                <Text style={styles.cardValue}>
                  {formatMoney(grant.gross_value, currency)}
                </Text>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.cardMeta}>Estimated net at vest</Text>
                <Text style={styles.cardValue}>
                  {formatMoney(grant.estimated_net_value, currency)}
                </Text>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.cardMeta}>Next vest date</Text>
                <Text style={styles.cardValue}>
                  {formatDate(grant.next_vest_date)}
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                onPress={() => deleteGrant(grant.id, grant.symbol)}
                style={styles.removeAction}
              >
                <Text style={styles.removeText}>Remove grant</Text>
              </Pressable>
            </Card>
          ))
        ) : (
          <Card>
            <Text style={styles.cardMeta}>No employer equity grants tracked.</Text>
          </Card>
        )}

        <SectionHeading title={`Purchase plans (${dashboard.purchase_plans.length})`} />
        {dashboard.purchase_plans.length ? (
          dashboard.purchase_plans.map((plan) => (
            <Card key={plan.id}>
              <View style={styles.cardTop}>
                <View style={styles.grantCopy}>
                  <Text style={styles.cardTitle}>{plan.name}</Text>
                  <Text style={styles.cardMeta}>
                    {formatNumber(plan.shares)} x {plan.symbol}  |{" "}
                    {plan.account_name}  |  {formatDate(plan.purchase_date)}
                  </Text>
                </View>
                <Badge
                  label={plan.status === "executed" ? "Bought" : "Scheduled"}
                  tone={plan.status === "executed" ? "positive" : "warning"}
                />
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.cardMeta}>Purchase cost</Text>
                <Text style={styles.cardValue}>
                  {formatMoney(plan.purchase_cost, plan.reporting_currency)}
                </Text>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.cardMeta}>Net discount benefit</Text>
                <Text style={styles.cardValue}>
                  {formatMoney(plan.net_benefit, plan.reporting_currency)}
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                onPress={() =>
                  deletePlan(plan.id, plan.name, plan.status)
                }
                style={styles.removeAction}
              >
                <Text style={styles.removeText}>Remove plan</Text>
              </Pressable>
            </Card>
          ))
        ) : (
          <Card>
            <Text style={styles.cardMeta}>No share purchase plans tracked.</Text>
          </Card>
        )}
        <Notice tone="info">
          These are estimates only. InvestingTracker does not connect to or
          execute trades in your employer plan.
        </Notice>
      </Page>

      <FormSheet
        visible={action === "grant"}
        title="Add an equity grant"
        subtitle="Unvested awards stay separate from owned shares and cash."
        onClose={() => {
          setAction(null);
          setResults([]);
          setSearching(false);
        }}
      >
        <SymbolSearch
          query={query}
          selected={selectedSymbol}
          results={results}
          searching={searching}
          onQuery={(value) => {
            setSelectedSymbol(null);
            setQuery(value);
            setResults([]);
            setSearching(false);
            setFormError("");
          }}
          onSelect={(symbol) => {
            setSelectedSymbol(symbol);
            setQuery(symbol.symbol);
            setResults([]);
            setSearching(false);
            setFormError("");
          }}
        />
        <Field
          label="Award name (optional)"
          value={grantLabel}
          onChangeText={setGrantLabel}
          placeholder="e.g. Annual award"
          maxLength={80}
        />
        <ChoiceGroup
          label="Award type"
          options={[
            { label: "RSU", value: "rsu" },
            { label: "Option", value: "option" },
          ]}
          value={grantType}
          onChange={(value) => setGrantType(value as "rsu" | "option")}
        />
        <DateField
          label="Grant date"
          value={grantDate}
          onChange={setGrantDate}
        />
        <Field
          label="Total units"
          value={grantUnits}
          onChangeText={setGrantUnits}
          placeholder="e.g. 100"
          keyboardType="decimal-pad"
        />
        <Field
          label="Vesting duration (months)"
          value={durationMonths}
          onChangeText={setDurationMonths}
          placeholder="e.g. 48"
          keyboardType="number-pad"
        />
        <Field
          label="Cliff (months)"
          value={cliffMonths}
          onChangeText={setCliffMonths}
          placeholder="e.g. 12"
          keyboardType="number-pad"
        />
        <Field
          label="Vesting interval (months)"
          value={intervalMonths}
          onChangeText={setIntervalMonths}
          placeholder="e.g. 3"
          keyboardType="number-pad"
        />
        {grantType === "option" ? (
          <Field
            label="Strike price"
            value={strikePrice}
            onChangeText={setStrikePrice}
            placeholder="Enter strike price"
            keyboardType="decimal-pad"
          />
        ) : null}
        <Field
          label="Tax rate assumed at vest (%)"
          value={taxPercent}
          onChangeText={setTaxPercent}
          placeholder="Enter your assumption"
          keyboardType="decimal-pad"
        />
        <Field
          label="Short-term sale tax assumption (%)"
          value={shortSaleTaxPercent}
          onChangeText={setShortSaleTaxPercent}
          placeholder="Enter your assumption"
          keyboardType="decimal-pad"
        />
        <Field
          label="Long-term sale tax assumption (%)"
          value={longSaleTaxPercent}
          onChangeText={setLongSaleTaxPercent}
          placeholder="Enter your assumption"
          keyboardType="decimal-pad"
        />
        <Field
          label="Long-term holding period (months)"
          value={longTermMonths}
          onChangeText={setLongTermMonths}
          placeholder="Enter your assumption"
          keyboardType="number-pad"
        />
        {formError ? <Notice>{formError}</Notice> : null}
        <ActionButton
          label="Save grant"
          onPress={() => void saveGrant()}
          loading={busy}
          disabled={!selectedSymbol}
        />
      </FormSheet>

      <FormSheet
        visible={action === "purchase"}
        title="Plan a discounted share purchase"
        subtitle="Nothing is counted in your wealth until the purchase date."
        onClose={() => {
          setAction(null);
          setResults([]);
          setSearching(false);
        }}
      >
        <SymbolSearch
          query={query}
          selected={selectedSymbol}
          results={results}
          searching={searching}
          onQuery={(value) => {
            setSelectedSymbol(null);
            setQuery(value);
            setResults([]);
            setSearching(false);
            setFormError("");
          }}
          onSelect={(symbol) => {
            setSelectedSymbol(symbol);
            setQuery(symbol.symbol);
            setResults([]);
            setSearching(false);
            setFormError("");
          }}
        />
        <Field
          label="Plan name (optional)"
          value={planName}
          onChangeText={setPlanName}
          placeholder="e.g. Q1 purchase"
          maxLength={80}
        />
        <ChoiceGroup
          label="Account where shares will be held"
          options={shareAccounts.map((account) => ({
            label: account.display_name,
            value: account.id,
          }))}
          value={shareAccountId}
          onChange={setShareAccountId}
        />
        <ChoiceGroup
          label="Funding wallet"
          options={fundingWallets.map(({ account, subaccount }) => ({
            label: `${account.display_name} ${subaccount.currency}`,
            value: subaccount.id,
          }))}
          value={walletId}
          onChange={setWalletId}
        />
        <Field
          label="Shares to buy"
          value={shares}
          onChangeText={setShares}
          placeholder="e.g. 10"
          keyboardType="decimal-pad"
        />
        <DateField
          label="Purchase date"
          value={purchaseDate}
          onChange={setPurchaseDate}
        />
        <Field
          label="Discount rate (%)"
          value={discountPercent}
          onChangeText={setDiscountPercent}
          placeholder="Enter your plan rate"
          keyboardType="decimal-pad"
        />
        <Field
          label="Receipt tax assumption (%)"
          value={receiptTaxPercent}
          onChangeText={setReceiptTaxPercent}
          placeholder="Enter your assumption"
          keyboardType="decimal-pad"
        />
        <Field
          label="Later profit tax assumption (%)"
          value={profitTaxPercent}
          onChangeText={setProfitTaxPercent}
          placeholder="Enter your assumption"
          keyboardType="decimal-pad"
        />
        <Field
          label="Reference market price (optional)"
          value={referencePrice}
          onChangeText={setReferencePrice}
          placeholder="Uses latest quote when blank"
          keyboardType="decimal-pad"
        />
        {formError ? <Notice>{formError}</Notice> : null}
        <ActionButton
          label="Save purchase plan"
          onPress={() => void savePurchasePlan()}
          loading={busy}
          disabled={!selectedSymbol || !selectedWallet || !shareAccountId}
        />
      </FormSheet>
    </>
  );
}

function SymbolSearch({
  query,
  selected,
  results,
  searching,
  onQuery,
  onSelect,
}: {
  query: string;
  selected: MarketSymbol | null;
  results: MarketSymbol[];
  searching: boolean;
  onQuery: (value: string) => void;
  onSelect: (symbol: MarketSymbol) => void;
}) {
  return (
    <View style={styles.searchBlock}>
      <Field
        label="Underlying stock"
        value={selected ? `${selected.symbol} | ${selected.name}` : query}
        onChangeText={onQuery}
        placeholder="Company or ticker, e.g. Microsoft"
        autoCapitalize="characters"
        autoCorrect={false}
      />
      {searching ? <Text style={styles.cardMeta}>Searching listings...</Text> : null}
      {selected ? (
        <Badge
          label={`${selected.symbol} | ${selected.exchange} | ${selected.currency}`}
          tone="positive"
        />
      ) : null}
      {!selected && results.length ? (
        <View style={styles.searchResults}>
          {results.map((result) => (
            <Pressable
              accessibilityRole="button"
              key={`${result.symbol}-${result.mic_code ?? result.exchange}`}
              onPress={() => onSelect(result)}
              style={styles.searchResult}
            >
              <Text style={styles.cardTitle}>{result.symbol}</Text>
              <Text style={styles.cardMeta}>
                {result.name}  |  {result.exchange}  |  {result.currency}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  metrics: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  metric: { flex: 1, minWidth: "46%", gap: 6 },
  metricLabel: { color: colors.muted, fontSize: 9, fontWeight: "800", letterSpacing: 0.4 },
  metricValue: { color: colors.text, fontSize: 17, fontWeight: "800" },
  actions: { gap: 8 },
  cardTop: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 10 },
  grantCopy: { flex: 1, gap: 4 },
  cardTitle: { color: colors.text, fontSize: 14, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  cardValue: { color: colors.text, fontSize: 12, fontWeight: "700" },
  removeAction: { alignSelf: "flex-start", paddingVertical: 4 },
  removeText: { color: colors.danger, fontSize: 12, fontWeight: "700" },
  searchBlock: { gap: 9 },
  searchResults: { borderRadius: 12, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  searchResult: { padding: 12, gap: 3, backgroundColor: colors.surface, borderBottomColor: colors.border, borderBottomWidth: 1 },
});
