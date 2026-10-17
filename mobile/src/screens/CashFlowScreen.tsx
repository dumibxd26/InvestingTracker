import { useMemo, useState } from "react";
import * as Crypto from "expo-crypto";
import {
  Alert,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { api, ApiError } from "../api";
import { formatDate, formatMoney, localDateValue } from "../format";
import type {
  Dashboard,
  Currency,
  FlowKind,
  Recurrence,
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
import { PercentField } from "../components/PlanningEditor";

type CashFlowAction = "schedule" | "cash" | null;
const EMPTY_ACCOUNTS: Dashboard["accounts"] = [];

const flowOptions: { label: string; value: FlowKind }[] = [
  { label: "Salary", value: "salary" },
  { label: "Bonus", value: "bonus" },
  { label: "Windfall", value: "windfall" },
  { label: "Dividend", value: "dividend" },
  { label: "Interest", value: "interest" },
  { label: "Bill", value: "bill" },
  { label: "Contribution", value: "contribution" },
];

const recurrenceOptions: { label: string; value: Recurrence }[] = [
  { label: "Once", value: "one_time" },
  { label: "Monthly", value: "monthly" },
  { label: "Quarterly", value: "quarterly" },
  { label: "Yearly", value: "annual" },
];

const currencies: { label: string; value: Currency }[] = [
  { label: "EUR", value: "EUR" },
  { label: "USD", value: "USD" },
  { label: "RON", value: "RON" },
];

export function CashFlowScreen() {
  const { dashboard, currency, refreshing, error, reload } = useWorkspace();
  const [action, setAction] = useState<CashFlowAction>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<FlowKind>("salary");
  const [amount, setAmount] = useState("");
  const [recurrence, setRecurrence] = useState<Recurrence>("monthly");
  const [startDate, setStartDate] = useState(localDateValue());
  const [endDate, setEndDate] = useState("");
  const [forecastCurrency, setForecastCurrency] = useState<Currency>(currency);
  const [autoPost, setAutoPost] = useState(true);
  const [scheduleWalletId, setScheduleWalletId] = useState("");
  const [annualGrowth, setAnnualGrowth] = useState("0");
  const [salaryBonus, setSalaryBonus] = useState(false);
  const [salaryScheduleId, setSalaryScheduleId] = useState("");
  const [salaryPercentage, setSalaryPercentage] = useState("0.1");

  const [cashSource, setCashSource] = useState("");
  const [cashAmount, setCashAmount] = useState("");
  const [receivedDate, setReceivedDate] = useState(localDateValue());
  const [cashWalletId, setCashWalletId] = useState("");
  const [cashIdempotencyKey, setCashIdempotencyKey] = useState(
    () => Crypto.randomUUID(),
  );

  const accounts = dashboard?.accounts ?? EMPTY_ACCOUNTS;
  const wallets = useMemo(
    () =>
      accounts
        .filter((account) => account.account_type !== "EMPLOYER_PLAN")
        .flatMap((account) =>
          account.subaccounts.map((subaccount) => ({
            account,
            subaccount,
          })),
        ),
    [accounts],
  );
  const scheduleWallet = wallets.find(
    ({ subaccount }) => subaccount.id === scheduleWalletId,
  );
  const cashWallet = wallets.find(
    ({ subaccount }) => subaccount.id === cashWalletId,
  );
  const forecast = (dashboard?.cash_flows ?? []).filter(
    (flow) => flow.status === "forecast",
  );
  const forecastInflows = forecast
    .filter((flow) => flow.direction === "inflow")
    .reduce((sum, flow) => sum + Number(flow.reporting_amount ?? "0"), 0);
  const forecastOutflows = forecast
    .filter((flow) => flow.direction === "outflow")
    .reduce((sum, flow) => sum + Number(flow.reporting_amount ?? "0"), 0);
  const salaryOrBonus = kind === "salary" || kind === "bonus";
  const shouldAutoPost = salaryOrBonus && autoPost;
  const isSalaryBonus = kind === "bonus" && salaryBonus;
  const salaries = (dashboard?.cash_flow_schedules ?? []).filter(schedule =>
    schedule.kind === "salary" && schedule.is_active && schedule.recurrence !== "one_time",
  );

  function openSchedule() {
    const wallet =
      wallets.find(({ subaccount }) => subaccount.currency === currency) ??
      wallets[0];
    setScheduleWalletId(wallet?.subaccount.id ?? "");
    setLabel("");
    setKind("salary");
    setAmount("");
    setAnnualGrowth("0");
    setSalaryBonus(false);
    setSalaryScheduleId("");
    setSalaryPercentage("0.1");
    setRecurrence("monthly");
    setStartDate(localDateValue());
    setEndDate("");
    setForecastCurrency(currency);
    setAutoPost(Boolean(wallet));
    setFormError("");
    setAction("schedule");
  }

  function openCash() {
    const wallet =
      wallets.find(({ subaccount }) => subaccount.currency === currency) ??
      wallets[0];
    setCashWalletId(wallet?.subaccount.id ?? "");
    setCashSource("");
    setCashAmount("");
    setReceivedDate(localDateValue());
    setFormError("");
    setAction("cash");
  }

  async function createSchedule() {
    if (label.trim().length < 2 || (!isSalaryBonus && !amount.trim())) {
      setFormError("Enter a label and, for fixed payments, an amount.");
      return;
    }
    if (!isSalaryBonus && (
      !Number.isFinite(Number(amount)) ||
      Number(amount) <= 0 ||
      Number(amount) > 100_000_000
    )) {
      setFormError("Enter an amount greater than zero and at most 100,000,000.");
      return;
    }
    if (kind === "salary" && recurrence !== "one_time" && (
      !annualGrowth.trim() || !Number.isFinite(Number(annualGrowth)) ||
      Number(annualGrowth) < -0.5 || Number(annualGrowth) > 1
    )) {
      setFormError("Expected annual salary increase must be between -50% and 100%.");
      return;
    }
    if (isSalaryBonus && (
      !salaryScheduleId || !salaryPercentage.trim() ||
      !Number.isFinite(Number(salaryPercentage)) ||
      Number(salaryPercentage) <= 0 || Number(salaryPercentage) > 1
    )) {
      setFormError("Choose a salary and a bonus percentage greater than 0% and at most 100%.");
      return;
    }
    if (shouldAutoPost && !scheduleWallet) {
      setFormError("Choose a tracked currency wallet for automatic credits.");
      return;
    }
    if (shouldAutoPost && startDate < localDateValue()) {
      setFormError("Automatic income schedules cannot start in the past.");
      return;
    }
    if (
      recurrence !== "one_time" &&
      endDate.trim() &&
      endDate.trim() < startDate
    ) {
      setFormError("The last expected date cannot be before the first date.");
      return;
    }
    setBusy(true);
    setFormError("");
    try {
      await api.createCashFlowSchedule({
        label: label.trim(),
        kind,
        ...(isSalaryBonus ? {
          salary_schedule_id: salaryScheduleId,
          salary_percentage: salaryPercentage,
        } : { amount: amount.trim() }),
        annual_growth_rate: kind === "salary" && recurrence !== "one_time" ? annualGrowth : "0",
        currency: shouldAutoPost && scheduleWallet
          ? scheduleWallet.subaccount.currency
          : forecastCurrency,
        recurrence,
        start_date: startDate,
        ...(recurrence !== "one_time" && endDate.trim()
          ? { end_date: endDate.trim() }
          : {}),
        auto_post: shouldAutoPost,
        ...(shouldAutoPost && scheduleWallet
          ? {
              account_id: scheduleWallet.account.id,
              subaccount_id: scheduleWallet.subaccount.id,
            }
          : {}),
      });
      await reload();
      setAction(null);
    } catch (cause) {
      setFormError(
        cause instanceof ApiError
          ? cause.message
          : "The cash-flow schedule could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function recordCash() {
    if (!cashWallet || !cashAmount.trim() || !cashSource.trim()) {
      setFormError("Choose a wallet and enter a source and amount.");
      return;
    }
    if (
      !Number.isFinite(Number(cashAmount)) ||
      Number(cashAmount) <= 0 ||
      Number(cashAmount) > 100_000_000
    ) {
      setFormError("Enter an amount greater than zero and at most 100,000,000.");
      return;
    }
    setBusy(true);
    setFormError("");
    try {
      await api.recordExtraCash({
        account_id: cashWallet.account.id,
        subaccount_id: cashWallet.subaccount.id,
        source: cashSource.trim(),
        amount: cashAmount.trim(),
        received_date: receivedDate,
        idempotency_key: cashIdempotencyKey,
      });
      await reload();
      setAction(null);
      setCashIdempotencyKey(Crypto.randomUUID());
    } catch (cause) {
      setFormError(
        cause instanceof ApiError
          ? cause.message
          : "The cash receipt could not be recorded.",
      );
    } finally {
      setBusy(false);
    }
  }

  function archiveSchedule(id: string, scheduleLabel: string, auto: boolean) {
    Alert.alert(
      "Stop this schedule?",
      `Stop future ${auto ? "automatic credits and forecasts" : "forecasts"} for "${scheduleLabel}"? Any linked bonus schedules will also stop. Already posted entries will remain.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Stop schedule",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .archiveCashFlowSchedule(id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not stop schedule",
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
        label="Loading your cash flow"
        error={error}
        onRetry={() => void reload()}
      />
    );
  }

  return (
    <>
      <Page refreshing={refreshing} onRefresh={() => void reload()}>
        <ScreenHeader
          eyebrow="Plan for money in motion"
          title="Cash flow."
          subtitle="Forecast income and expenses, or record cash that has already arrived."
        />
        {error ? <Notice>{error}</Notice> : null}
        <View style={styles.actionStack}>
          <ActionButton
            label="Add a schedule"
            onPress={openSchedule}
            secondary
          />
          <ActionButton
            label="Record extra cash received"
            onPress={openCash}
            disabled={!wallets.length}
          />
        </View>
        <View style={styles.metrics}>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>AVAILABLE CASH</Text>
            <Text style={styles.metricValue}>
              {formatMoney(dashboard.totals.available_cash, currency)}
            </Text>
            <Text style={styles.cardMeta}>Forecasts are excluded</Text>
          </Card>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>RESERVE TARGET</Text>
            <Text style={styles.metricValue}>
              {formatMoney(dashboard.totals.emergency_reserve_target, currency)}
            </Text>
            <Text style={styles.cardMeta}>Your selected floor</Text>
          </Card>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>UPCOMING INFLOWS</Text>
            <Text style={styles.metricValue}>
              {formatMoney(forecastInflows, currency)}
            </Text>
            <Text style={styles.cardMeta}>Visible forecast events</Text>
          </Card>
          <Card style={styles.metric}>
            <Text style={styles.metricLabel}>UPCOMING BILLS</Text>
            <Text style={styles.metricValue}>
              {formatMoney(forecastOutflows, currency)}
            </Text>
            <Text style={styles.cardMeta}>Visible forecast events</Text>
          </Card>
        </View>

        <SectionHeading title="Cash-flow ledger" />
        {dashboard.cash_flows.length ? (
          dashboard.cash_flows.map((flow) => {
            const isOutflow = flow.direction === "outflow";
            const isTransfer = flow.direction === "transfer";
            return (
              <Card key={flow.id} style={styles.flowCard}>
                <View style={styles.flowGlyph}>
                  <Text style={styles.flowGlyphText}>
                    {isOutflow ? "-" : isTransfer ? "<>" : "+"}
                  </Text>
                </View>
                <View style={styles.flowCopy}>
                  <Text style={styles.cardTitle}>{flow.label}</Text>
                  <Text style={styles.cardMeta}>
                    {flow.status === "forecast" ? "Expected " : "Received "}
                    {formatDate(flow.expected_date ?? flow.occurred_at)}
                    {flow.recurrence
                      ? `  |  ${flow.recurrence.replace("_", " ")}`
                      : ""}
                  </Text>
                </View>
                <View style={styles.flowAmount}>
                  <Text
                    style={[
                      styles.flowValue,
                      isOutflow && styles.negative,
                      flow.status === "forecast" && !isOutflow && styles.forecast,
                    ]}
                  >
                    {isOutflow ? "-" : isTransfer ? "" : "+"}
                    {formatMoney(flow.amount, flow.currency)}
                  </Text>
                  <Badge
                    label={flow.status === "forecast" ? "Forecast" : "Confirmed"}
                    tone={flow.status === "forecast" ? "warning" : "positive"}
                  />
                </View>
              </Card>
            );
          })
        ) : (
          <Card>
            <Text style={styles.cardMeta}>
              No upcoming or recorded cash flows yet.
            </Text>
          </Card>
        )}

        <SectionHeading title="Active schedules" />
        {dashboard.cash_flow_schedules.filter((schedule) => schedule.is_active)
          .length ? (
          dashboard.cash_flow_schedules
            .filter((schedule) => schedule.is_active)
            .map((schedule) => (
              <Card key={schedule.id}>
                <View style={styles.scheduleTop}>
                  <View style={styles.flowCopy}>
                    <Text style={styles.cardTitle}>{schedule.label}</Text>
                    <Text style={styles.cardMeta}>
                      {schedule.kind}  |  {schedule.recurrence.replace("_", " ")}
                      {schedule.auto_post ? "  |  Automatic tracked credit" : ""}
                      {Number(schedule.annual_growth_rate) !== 0 ? `  |  ${Number(schedule.annual_growth_rate) * 100}% expected annual raise` : ""}
                      {schedule.salary_schedule_id ? `  |  Follows ${dashboard.cash_flow_schedules.find(item => item.id === schedule.salary_schedule_id)?.label ?? "linked salary"} raises` : ""}
                    </Text>
                  </View>
                  <Badge
                    label={schedule.salary_schedule_id
                      ? `${Number(schedule.salary_percentage) * 100}% of annual salary`
                      : `${formatMoney(schedule.amount, schedule.currency)} / ${schedule.recurrence === "one_time" ? "once" : schedule.recurrence}`}
                  />
                </View>
                <Text style={styles.cardMeta}>
                  Starts {formatDate(schedule.start_date)}
                  {schedule.end_date
                    ? `  |  Ends ${formatDate(schedule.end_date)}`
                    : ""}
                </Text>
                <Pressable
                  accessibilityRole="button"
                  onPress={() =>
                    archiveSchedule(
                      schedule.id,
                      schedule.label,
                      schedule.auto_post,
                    )
                  }
                  style={styles.removeAction}
                >
                  <Text style={styles.removeText}>Stop schedule</Text>
                </Pressable>
              </Card>
            ))
        ) : (
          <Card>
            <Text style={styles.cardMeta}>No active schedules.</Text>
          </Card>
        )}
        <Notice tone="info">
          Forecasts never enter available cash. Automatic salary and bonus
          entries only update InvestingTracker&apos;s tracked balance, not your bank.
        </Notice>
      </Page>

      <FormSheet
        visible={action === "schedule"}
        title="Add a cash-flow schedule"
        subtitle={
          shouldAutoPost
            ? "Automatic posting is bookkeeping only. It does not transfer money."
            : "Forecasts help you plan and do not change account balances."
        }
        onClose={() => setAction(null)}
      >
        <Field
          label="What is this for?"
          value={label}
          onChangeText={setLabel}
          placeholder="e.g. Monthly salary"
          maxLength={100}
        />
        <ChoiceGroup
          label="Type"
          options={flowOptions}
          value={kind}
          onChange={(value) => {
            setKind(value as FlowKind);
            setSalaryBonus(false); setSalaryScheduleId("");
            if (value === "bonus") setRecurrence("annual");
          }}
        />
        {!isSalaryBonus && <Field
          label="Amount"
          value={amount}
          onChangeText={setAmount}
          placeholder="0"
          keyboardType="decimal-pad"
        />}
        {kind === "salary" && recurrence !== "one_time" && <>
          <PercentField label="Expected annual salary increase (%)" rate={annualGrowth} onChange={setAnnualGrowth} />
          <Notice tone="info">Enter net salary and the total nominal raise before inflation. Growth compounds from the first payment date, prorated for partial years. Forecasts and opted-in credits use the increased amount.</Notice>
        </>}
        {kind === "bonus" && <>
          <ChoiceGroup label="Bonus calculation" value={salaryBonus ? "salary" : "fixed"} options={[
            { label: "Fixed amount", value: "fixed" },
            { label: "% of annual salary", value: "salary" },
          ]} onChange={value => {
            setSalaryBonus(value === "salary");
            if (value === "salary") setRecurrence("annual");
          }} />
          {isSalaryBonus && <>
            {salaries.length ? <ChoiceGroup label="Linked salary schedule"
              value={salaryScheduleId}
              options={salaries.map(salary => ({ label: `${salary.label} (${salary.currency})`, value: salary.id }))}
              onChange={value => {
                setSalaryScheduleId(value);
                const salary = salaries.find(item => item.id === value);
                if (salary && startDate < salary.start_date) setStartDate(salary.start_date);
              }} /> : <Notice>Add a recurring salary schedule first, then add its annual bonus.</Notice>}
            <PercentField label="Bonus share of annual salary (%)" rate={salaryPercentage} onChange={setSalaryPercentage} />
            <Notice tone="info">Uses annualized salary at each bonus payment date: monthly × 12 or quarterly × 4, including expected salary raises once. Payments stop outside the salary period. Stopping the salary also stops linked bonuses.</Notice>
          </>}
        </>}
        {salaryOrBonus ? (
          <>
            <ChoiceGroup
              label="Deposit into"
              options={wallets.map(({ account, subaccount }) => ({
                label: `${account.display_name} ${subaccount.currency}`,
                value: subaccount.id,
              }))}
              value={scheduleWalletId}
              onChange={setScheduleWalletId}
            />
            <ChoiceGroup
              label="Balance tracking"
              options={[
                { label: "Auto-credit wallet", value: "yes" },
                { label: "Forecast only", value: "no" },
              ]}
              value={autoPost ? "yes" : "no"}
              onChange={(value) => setAutoPost(value === "yes")}
            />
          </>
        ) : null}
        {shouldAutoPost && <Notice tone="info">Automatic credits use expected raises and calculated bonus amounts. Choose forecast only if actual payments need manual confirmation.</Notice>}
        {!shouldAutoPost && (
          <ChoiceGroup
            label="Forecast currency"
            options={currencies}
            value={forecastCurrency}
            onChange={(value) => setForecastCurrency(value as Currency)}
          />
        )}
        <ChoiceGroup
          label="How often?"
          options={isSalaryBonus ? recurrenceOptions.filter(option => option.value === "annual") : recurrenceOptions}
          value={recurrence}
          onChange={(value) => setRecurrence(value as Recurrence)}
        />
        <DateField
          label={recurrence === "one_time" ? "Expected date" : "First expected date"}
          value={startDate}
          onChange={setStartDate}
        />
        {recurrence !== "one_time" ? (
          <DateField
            label="Last expected date (optional)"
            value={endDate}
            onChange={setEndDate}
            optional
          />
        ) : null}
        {formError ? <Notice>{formError}</Notice> : null}
        <ActionButton
          label="Save schedule"
          onPress={() => void createSchedule()}
          loading={busy}
          disabled={!label.trim() || (isSalaryBonus ? !salaryScheduleId : !amount.trim())}
        />
      </FormSheet>

      <FormSheet
        visible={action === "cash"}
        title="Record extra cash"
        subtitle="This updates only the selected wallet in InvestingTracker."
        onClose={() => setAction(null)}
      >
        <ChoiceGroup
          label="Credit to"
          options={wallets.map(({ account, subaccount }) => ({
            label: `${account.display_name} ${subaccount.currency}`,
            value: subaccount.id,
          }))}
          value={cashWalletId}
          onChange={setCashWalletId}
        />
        <Field
          label="Source"
          value={cashSource}
          onChangeText={setCashSource}
          placeholder="e.g. Annual bonus"
          maxLength={100}
        />
        <Field
          label={`Amount${cashWallet ? ` (${cashWallet.subaccount.currency})` : ""}`}
          value={cashAmount}
          onChangeText={setCashAmount}
          placeholder="0"
          keyboardType="decimal-pad"
        />
        <DateField
          label="Received date"
          value={receivedDate}
          onChange={setReceivedDate}
        />
        {formError ? <Notice>{formError}</Notice> : null}
        <ActionButton
          label="Record cash received"
          onPress={() => void recordCash()}
          loading={busy}
          disabled={!cashSource.trim() || !cashAmount.trim() || !cashWallet}
        />
      </FormSheet>
    </>
  );
}

const styles = StyleSheet.create({
  actionStack: { gap: 8 },
  metrics: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  metric: { flex: 1, minWidth: "46%", gap: 6 },
  metricLabel: { color: colors.muted, fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  metricValue: { color: colors.text, fontSize: 17, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  flowCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12 },
  flowGlyph: { width: 33, height: 33, alignItems: "center", justifyContent: "center", borderRadius: 12, backgroundColor: colors.primarySoft },
  flowGlyphText: { color: colors.primary, fontSize: 14, fontWeight: "900" },
  flowCopy: { flex: 1, gap: 4 },
  cardTitle: { color: colors.text, fontSize: 13, fontWeight: "800" },
  flowAmount: { alignItems: "flex-end", gap: 6 },
  flowValue: { color: colors.positive, fontSize: 12, fontWeight: "800" },
  negative: { color: colors.danger },
  forecast: { color: colors.warning },
  scheduleTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  removeAction: { alignSelf: "flex-start", paddingVertical: 4 },
  removeText: { color: colors.danger, fontSize: 12, fontWeight: "700" },
});
