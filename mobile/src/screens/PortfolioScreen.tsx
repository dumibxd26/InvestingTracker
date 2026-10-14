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
  AccountType,
  Currency,
  Dashboard,
  Deposit,
  HoldingCreatePayload,
  MarketSymbol,
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

type PortfolioAction = "account" | "holding" | "deposit" | null;
const EMPTY_ACCOUNTS: Dashboard["accounts"] = [];

const accountTypes: { label: string; value: AccountType }[] = [
  { label: "Brokerage", value: "BROKERAGE" },
  { label: "Bank", value: "BANK" },
  { label: "Savings", value: "SAVINGS" },
  { label: "Employer plan", value: "EMPLOYER_PLAN" },
];

const currencyOptions: { label: string; value: Currency }[] = [
  { label: "EUR", value: "EUR" },
  { label: "USD", value: "USD" },
  { label: "RON", value: "RON" },
];

export function PortfolioScreen() {
  const {
    dashboard,
    currency,
    refreshing,
    error,
    reload,
  } = useWorkspace();
  const [action, setAction] = useState<PortfolioAction>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  const [accountName, setAccountName] = useState("");
  const [accountType, setAccountType] = useState<AccountType>("BROKERAGE");
  const [accountCurrency, setAccountCurrency] = useState<Currency>(currency);
  const [openingCash, setOpeningCash] = useState("0");

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [symbols, setSymbols] = useState<MarketSymbol[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<MarketSymbol | null>(null);
  const [accountId, setAccountId] = useState("");
  const [subaccountId, setSubaccountId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [averageCost, setAverageCost] = useState("");
  const [purchaseDate, setPurchaseDate] = useState(localDateValue());
  const [taxDomicile, setTaxDomicile] = useState("");

  const [depositName, setDepositName] = useState("");
  const [depositAccountId, setDepositAccountId] = useState("");
  const [depositSubaccountId, setDepositSubaccountId] = useState("");
  const [depositPrincipal, setDepositPrincipal] = useState("");
  const [depositRate, setDepositRate] = useState("");
  const [depositStartDate, setDepositStartDate] = useState(localDateValue());
  const [depositMonths, setDepositMonths] = useState("12");
  const [capitalizeInterest, setCapitalizeInterest] = useState(true);

  const accounts = dashboard?.accounts ?? EMPTY_ACCOUNTS;
  const eligibleAccounts = useMemo(
    () =>
      accounts.filter(
        (account) =>
          account.account_type !== "SAVINGS" && !account.is_sample,
      ),
    [accounts],
  );
  const wallets = useMemo(
    () =>
      accounts.flatMap((account) =>
        account.subaccounts.map((subaccount) => ({
          account,
          subaccount,
        })),
      ),
    [accounts],
  );
  const selectedAccount = eligibleAccounts.find(
    (account) => account.id === accountId,
  );
  const selectedWallet = selectedAccount?.subaccounts.find(
    (subaccount) => subaccount.id === subaccountId,
  );
  const selectedDepositWallet = wallets.find(
    ({ subaccount }) => subaccount.id === depositSubaccountId,
  );

  useEffect(() => {
    if (action !== "holding" || selectedSymbol || query.trim().length < 2) {
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => {
      setSearching(true);
      void api
        .searchSymbols(query.trim(), controller.signal)
        .then((response) => setSymbols(response.results))
        .catch((cause) => {
          if (!controller.signal.aborted) {
            setActionError(
              cause instanceof ApiError
                ? cause.message
                : "Symbol search failed.",
            );
            setSymbols([]);
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
  }, [action, query, selectedSymbol]);

  function openAction(nextAction: Exclude<PortfolioAction, null>) {
    setActionError("");
    setAction(nextAction);
    setSymbols([]);
    setSearching(false);
    if (nextAction === "holding") {
      const firstAccount = eligibleAccounts[0];
      setAccountId(firstAccount?.id ?? "");
      setSubaccountId(
        firstAccount?.subaccounts.find((wallet) => wallet.is_primary)?.id ??
          firstAccount?.subaccounts[0]?.id ??
          "",
      );
      setQuery("");
      setSelectedSymbol(null);
      setSymbols([]);
      setQuantity("");
      setAverageCost("");
      setPurchaseDate(localDateValue());
      setTaxDomicile("");
    }
    if (nextAction === "deposit") {
      const wallet =
        wallets.find(({ subaccount }) => subaccount.currency === currency) ??
        wallets[0];
      setDepositAccountId(wallet?.account.id ?? "");
      setDepositSubaccountId(wallet?.subaccount.id ?? "");
      setDepositName("");
      setDepositPrincipal("");
      setDepositRate("");
      setDepositStartDate(localDateValue());
      setDepositMonths("12");
      setCapitalizeInterest(true);
    }
  }

  async function finishAction(operation: () => Promise<void>) {
    setActionError("");
    setBusy(true);
    try {
      await operation();
      await reload();
      setAction(null);
      setSearching(false);
    } catch (cause) {
      setActionError(
        cause instanceof ApiError
          ? cause.message
          : "The portfolio change could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  function createAccount() {
    if (accountName.trim().length < 2) {
      setActionError("Enter an account name with at least two characters.");
      return;
    }
    if (
      accountType === "EMPLOYER_PLAN" &&
      Number(openingCash) > 0
    ) {
      setActionError("Employer-plan accounts cannot have an opening cash balance.");
      return;
    }
    void finishAction(async () => {
      await api.createAccount({
        display_name: accountName.trim(),
        provider_code: "MANUAL",
        account_type: accountType,
        currency: accountCurrency,
        opening_cash: openingCash || "0",
      });
      setAccountName("");
      setOpeningCash("0");
    });
  }

  function createHolding() {
    if (!selectedSymbol || !selectedAccount || !selectedWallet) {
      setActionError("Choose a listing, account, and funding wallet.");
      return;
    }
    if (
      !Number.isFinite(Number(quantity)) ||
      Number(quantity) <= 0 ||
      !Number.isFinite(Number(averageCost)) ||
      Number(averageCost) <= 0
    ) {
      setActionError("Enter a positive share quantity and average cost.");
      return;
    }
    const payload: HoldingCreatePayload = {
      account_id: selectedAccount.id,
      subaccount_id: selectedWallet.id,
      symbol: selectedSymbol.symbol,
      mic_code: selectedSymbol.mic_code,
      exchange: selectedSymbol.exchange,
      instrument_type: selectedSymbol.instrument_type,
      quantity: quantity.trim(),
      average_cost: averageCost.trim(),
      average_cost_currency: selectedSymbol.currency,
      purchase_date: purchaseDate,
      tax_domicile_country_code: taxDomicile.trim().toUpperCase() || null,
    };
    void finishAction(async () => {
      await api.addHolding(payload);
    });
  }

  function createDeposit() {
    if (!selectedDepositWallet || !depositName.trim()) {
      setActionError("Choose a funding wallet and enter a deposit name.");
      return;
    }
    if (
      !depositPrincipal.trim() ||
      !depositRate.trim() ||
      !depositMonths.trim()
    ) {
      setActionError("Complete the principal, annual rate, and term.");
      return;
    }
    void finishAction(async () => {
      await api.createDeposit({
        account_id: selectedDepositWallet.account.id,
        subaccount_id: selectedDepositWallet.subaccount.id,
        name: depositName.trim(),
        principal: depositPrincipal.trim(),
        start_date: depositStartDate,
        period_months: Number(depositMonths),
        annual_profit_rate: String(Number(depositRate) / 100),
        capitalization: capitalizeInterest,
      });
    });
  }

  function removeHolding(id: string, symbol: string) {
    Alert.alert(
      "Remove holding?",
      `Remove ${symbol} from this tracker? This does not change your actual brokerage account.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .deleteHolding(id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not remove holding",
                  cause instanceof ApiError ? cause.message : "Please try again.",
                ),
              )
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }

  function removeAccount(id: string, name: string) {
    Alert.alert(
      "Remove account?",
      `Remove "${name}" and its tracked balances, holdings, and deposits from InvestingTracker? This does not change your actual account.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .deleteAccount(id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not remove account",
                  cause instanceof ApiError ? cause.message : "Please try again.",
                ),
              )
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }

  function removeDeposit(deposit: Deposit) {
    Alert.alert(
      "Remove fixed deposit?",
      `Remove "${deposit.name}" and return its principal to the tracked wallet?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .deleteDeposit(deposit.id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not remove deposit",
                  cause instanceof ApiError ? cause.message : "Please try again.",
                ),
              )
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }

  async function refreshQuotes() {
    setBusy(true);
    setActionError("");
    try {
      const result = await api.refreshMarketData();
      await reload();
      const summary = `Updated ${result.updated_symbols.length} quote(s) and ${result.updated_fx_pairs.length} FX rate(s).`;
      if (result.errors.length) {
        Alert.alert("Market data refreshed with notes", `${summary}\n\n${result.errors.join(" ")}`);
      } else {
        Alert.alert("Market data refreshed", summary);
      }
    } catch (cause) {
      Alert.alert(
        "Market data could not be refreshed",
        cause instanceof ApiError ? cause.message : "Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!dashboard) {
    return (
      <LoadingState
        label="Loading your portfolio"
        error={error}
        onRetry={() => void reload()}
      />
    );
  }

  return (
    <>
      <Page refreshing={refreshing} onRefresh={() => void reload()}>
        <ScreenHeader
          eyebrow="Your accounts and owned assets"
          title="Portfolio."
          subtitle="Track the accounts, balances, holdings, and deposits you choose."
        />
        {error ? <Notice>{error}</Notice> : null}
        <View style={styles.actionGrid}>
          <ActionButton
            label="Add account"
            onPress={() => openAction("account")}
            secondary
          />
          <ActionButton
            label="Add holding"
            onPress={() => openAction("holding")}
            disabled={!dashboard.market_data_provider_configured || !eligibleAccounts.length}
            secondary
          />
          <ActionButton
            label="Add deposit"
            onPress={() => openAction("deposit")}
            disabled={!wallets.length}
            secondary
          />
        </View>
        {!dashboard.market_data_provider_configured ? (
          <Text style={styles.helpText}>
            Configure TWELVE_DATA_API_KEY on the backend to search listings and
            refresh market quotes.
          </Text>
        ) : null}
        {dashboard.market_data_provider_configured ? (
          <ActionButton
            label="Refresh quotes and FX rates"
            onPress={() => void refreshQuotes()}
            loading={busy}
            secondary
          />
        ) : null}

        {actionError && action === null ? <Notice>{actionError}</Notice> : null}
        <SectionHeading title={`Accounts (${dashboard.accounts.length})`} />
        {dashboard.accounts.length ? (
          dashboard.accounts.map((account) => (
            <Card key={account.id}>
              <View style={styles.rowBetween}>
                <View style={styles.flex}>
                  <Text style={styles.cardTitle}>{account.display_name}</Text>
                  <Text style={styles.cardMeta}>
                    {account.account_type.toLowerCase().replace("_", " ")}
                    {account.is_sample ? "  |  Legacy sample data" : ""}
                  </Text>
                </View>
                <Text style={styles.money}>
                  {formatMoney(account.cash_balance, account.currency)}
                </Text>
              </View>
              {account.subaccounts.map((wallet) => (
                <View key={wallet.id} style={styles.walletRow}>
                  <Text style={styles.cardMeta}>
                    {wallet.currency} wallet{wallet.is_primary ? "  |  Primary" : ""}
                  </Text>
                  <Text style={styles.cardValue}>
                    {formatMoney(wallet.cash_balance, wallet.currency)}
                  </Text>
                </View>
              ))}
              {!account.is_sample ? (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => removeAccount(account.id, account.display_name)}
                  style={styles.removeAction}
                >
                  <Text style={styles.removeText}>Remove account</Text>
                </Pressable>
              ) : null}
            </Card>
          ))
        ) : (
          <Card>
            <Text style={styles.cardMeta}>
              Your workspace is empty. Add an account to start tracking.
            </Text>
          </Card>
        )}

        <SectionHeading title={`Holdings (${dashboard.holdings.length})`} />
        {dashboard.holdings.length ? (
          dashboard.holdings.map((holding) => (
            <Card key={holding.id}>
              <View style={styles.rowBetween}>
                <View style={styles.flex}>
                  <Text style={styles.cardTitle}>{holding.symbol}</Text>
                  <Text style={styles.cardMeta}>
                    {holding.name}  |  {holding.account_name}
                  </Text>
                </View>
                <View style={styles.alignEnd}>
                  <Text style={styles.money}>
                    {formatMoney(holding.market_value, currency)}
                  </Text>
                  <Text style={styles.cardMeta}>
                    {formatNumber(holding.quantity)} shares
                  </Text>
                </View>
              </View>
              <View style={styles.walletRow}>
                <Text style={styles.cardMeta}>Estimated gain</Text>
                <Text
                  style={[
                    styles.cardValue,
                    Number(holding.estimated_gain) < 0 && styles.negative,
                  ]}
                >
                  {formatMoney(holding.estimated_gain, currency)} (
                  {formatNumber(holding.estimated_gain_percent, 1)}%)
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                onPress={() => removeHolding(holding.id, holding.symbol)}
                style={styles.removeAction}
              >
                <Text style={styles.removeText}>Remove holding</Text>
              </Pressable>
            </Card>
          ))
        ) : (
          <Card>
            <Text style={styles.cardMeta}>
              No holdings yet. Add a market-listed stock or ETF to your portfolio.
            </Text>
          </Card>
        )}

        <SectionHeading title={`Fixed deposits (${dashboard.deposits.length})`} />
        {dashboard.deposits.length ? (
          dashboard.deposits.map((deposit) => (
            <Card key={deposit.id}>
              <View style={styles.rowBetween}>
                <View style={styles.flex}>
                  <Text style={styles.cardTitle}>{deposit.name}</Text>
                  <Text style={styles.cardMeta}>
                    Matures {formatDate(deposit.maturity_date)}
                  </Text>
                </View>
                <Badge
                  label={`${formatNumber(Number(deposit.annual_rate) * 100, 2)}%`}
                  tone="positive"
                />
              </View>
              <View style={styles.walletRow}>
                <Text style={styles.cardMeta}>Current estimate</Text>
                <Text style={styles.cardValue}>
                  {formatMoney(deposit.current_value, deposit.currency)}
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                onPress={() => removeDeposit(deposit)}
                style={styles.removeAction}
              >
                <Text style={styles.removeText}>Remove deposit</Text>
              </Pressable>
            </Card>
          ))
        ) : (
          <Card>
            <Text style={styles.cardMeta}>No term deposits are tracked.</Text>
          </Card>
        )}
      </Page>

      <FormSheet
        visible={action === "account"}
        title="Add an account"
        subtitle="A manual record only. This does not connect to your bank or broker."
        onClose={() => setAction(null)}
      >
        <Field
          label="Account name"
          value={accountName}
          onChangeText={setAccountName}
          placeholder="e.g. Main brokerage"
          maxLength={100}
        />
        <ChoiceGroup
          label="Account type"
          options={accountTypes}
          value={accountType}
          onChange={(value) => {
            const nextType = value as AccountType;
            setAccountType(nextType);
            if (nextType === "EMPLOYER_PLAN") setOpeningCash("0");
          }}
        />
        <ChoiceGroup
          label="Opening balance currency"
          options={currencyOptions}
          value={accountCurrency}
          onChange={(value) => setAccountCurrency(value as Currency)}
        />
        <Field
          label="Opening cash balance"
          value={openingCash}
          onChangeText={setOpeningCash}
          placeholder="0"
          keyboardType="decimal-pad"
          editable={accountType !== "EMPLOYER_PLAN"}
        />
        {actionError ? <Notice>{actionError}</Notice> : null}
        <ActionButton
          label="Save account"
          onPress={createAccount}
          loading={busy}
          disabled={!accountName.trim()}
        />
      </FormSheet>

      <FormSheet
        visible={action === "holding"}
        title="Add a stock or ETF"
        subtitle="Search a market listing, then record its quantity and average cost."
        onClose={() => {
          setAction(null);
          setSearching(false);
        }}
      >
        {!dashboard.market_data_provider_configured ? (
          <Notice>
            Configure TWELVE_DATA_API_KEY on the backend to search listings.
          </Notice>
        ) : (
          <>
            <Field
              label="Company or ticker"
              value={selectedSymbol ? `${selectedSymbol.symbol} | ${selectedSymbol.name}` : query}
              onChangeText={(value) => {
                setSelectedSymbol(null);
                setQuery(value);
                setActionError("");
                setSymbols([]);
                setSearching(false);
              }}
              placeholder="e.g. Microsoft or MSFT"
              autoCapitalize="characters"
              autoCorrect={false}
            />
            {searching ? (
              <Text style={styles.cardMeta}>Searching market listings...</Text>
            ) : null}
            {!selectedSymbol && symbols.length ? (
              <View style={styles.searchResults}>
                {symbols.map((result) => (
                  <Pressable
                    key={`${result.symbol}-${result.mic_code ?? result.exchange}`}
                    accessibilityRole="button"
                    onPress={() => {
                      setSelectedSymbol(result);
                      setQuery(result.symbol);
                      setSymbols([]);
                      setSearching(false);
                      setActionError("");
                    }}
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
            {selectedSymbol ? (
              <Badge
                label={`${selectedSymbol.instrument_type} | ${selectedSymbol.exchange} | ${selectedSymbol.currency}`}
                tone="positive"
              />
            ) : null}
            <ChoiceGroup
              label="Account"
              options={eligibleAccounts.map((account) => ({
                label: account.display_name,
                value: account.id,
              }))}
              value={accountId}
              onChange={(value) => {
                setAccountId(value);
                const selected = eligibleAccounts.find(
                  (account) => account.id === value,
                );
                setSubaccountId(
                  selected?.subaccounts.find((wallet) => wallet.is_primary)?.id ??
                    selected?.subaccounts[0]?.id ??
                    "",
                );
              }}
            />
            {selectedAccount ? (
              <ChoiceGroup
                label="Funding wallet"
                options={selectedAccount.subaccounts.map((wallet) => ({
                  label: `${wallet.currency} ${formatMoney(wallet.cash_balance, wallet.currency)}`,
                  value: wallet.id,
                }))}
                value={subaccountId}
                onChange={setSubaccountId}
              />
            ) : null}
            <Field
              label="Shares owned"
              value={quantity}
              onChangeText={setQuantity}
              placeholder="e.g. 5"
              keyboardType="decimal-pad"
            />
            <Field
              label={`Average cost per share (${selectedSymbol?.currency ?? "listing currency"})`}
              value={averageCost}
              onChangeText={setAverageCost}
              placeholder="e.g. 120.00"
              keyboardType="decimal-pad"
            />
            <DateField
              label="Purchase date"
              value={purchaseDate}
              onChange={setPurchaseDate}
            />
            <Field
              label="Security tax domicile country code (optional)"
              value={taxDomicile}
              onChangeText={setTaxDomicile}
              placeholder="e.g. US"
              autoCapitalize="characters"
              maxLength={2}
            />
          </>
        )}
        {actionError ? <Notice>{actionError}</Notice> : null}
        <ActionButton
          label="Save holding"
          onPress={createHolding}
          loading={busy}
          disabled={!selectedSymbol || !selectedAccount || !selectedWallet}
        />
      </FormSheet>

      <FormSheet
        visible={action === "deposit"}
        title="Add a fixed deposit"
        subtitle="Interest and maturity values are estimates, not bank confirmations."
        onClose={() => {
          setAction(null);
          setSearching(false);
        }}
      >
        <Field
          label="Deposit name"
          value={depositName}
          onChangeText={setDepositName}
          placeholder="e.g. 12-month savings"
          maxLength={100}
        />
        <ChoiceGroup
          label="Fund from account"
          options={accounts.map((account) => ({
            label: account.display_name,
            value: account.id,
          }))}
          value={depositAccountId}
          onChange={(value) => {
            setDepositAccountId(value);
            const account = accounts.find((item) => item.id === value);
            setDepositSubaccountId(
              account?.subaccounts.find((wallet) => wallet.is_primary)?.id ??
                account?.subaccounts[0]?.id ??
                "",
            );
          }}
        />
        {accounts.find((account) => account.id === depositAccountId) ? (
          <ChoiceGroup
            label="Funding wallet"
            options={
              accounts
                .find((account) => account.id === depositAccountId)
                ?.subaccounts.map((wallet) => ({
                  label: `${wallet.currency} ${formatMoney(wallet.cash_balance, wallet.currency)}`,
                  value: wallet.id,
                })) ?? []
            }
            value={depositSubaccountId}
            onChange={setDepositSubaccountId}
          />
        ) : null}
        <Field
          label="Principal"
          value={depositPrincipal}
          onChangeText={setDepositPrincipal}
          placeholder="0"
          keyboardType="decimal-pad"
        />
        <Field
          label="Annual rate (%)"
          value={depositRate}
          onChangeText={setDepositRate}
          placeholder="e.g. 4.5"
          keyboardType="decimal-pad"
        />
        <DateField
          label="Start date"
          value={depositStartDate}
          onChange={setDepositStartDate}
          maximumDate={new Date()}
        />
        <Field
          label="Term (months)"
          value={depositMonths}
          onChangeText={setDepositMonths}
          placeholder="12"
          keyboardType="number-pad"
        />
        <ChoiceGroup
          label="Interest treatment"
          options={[
            { label: "Reinvest interest", value: "yes" },
            { label: "Simple interest", value: "no" },
          ]}
          value={capitalizeInterest ? "yes" : "no"}
          onChange={(value) => setCapitalizeInterest(value === "yes")}
        />
        {actionError ? <Notice>{actionError}</Notice> : null}
        <ActionButton
          label="Save deposit"
          onPress={createDeposit}
          loading={busy}
          disabled={!depositName.trim() || !selectedDepositWallet}
        />
      </FormSheet>
    </>
  );
}

const styles = StyleSheet.create({
  actionGrid: { gap: 8 },
  helpText: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  flex: { flex: 1, gap: 4 },
  alignEnd: { alignItems: "flex-end", gap: 4 },
  cardTitle: { color: colors.text, fontSize: 14, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  money: { color: colors.text, fontSize: 15, fontWeight: "800" },
  cardValue: { color: colors.text, fontSize: 12, fontWeight: "700" },
  walletRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  removeAction: { alignSelf: "flex-start", paddingVertical: 5 },
  removeText: { color: colors.danger, fontSize: 12, fontWeight: "700" },
  negative: { color: colors.danger },
  searchResults: { borderRadius: 12, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  searchResult: { padding: 12, gap: 3, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
});
