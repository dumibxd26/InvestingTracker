import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { formatDate, formatMoney } from "../format";
import { availableCurrencies } from "../currency";
import { colors } from "../theme";
import {
  Badge,
  Card,
  ChoiceGroup,
  LoadingState,
  MetricCard,
  Notice,
  Page,
  ProgressBar,
  ScreenHeader,
  SectionHeading,
} from "../ui";
import { useWorkspace } from "../workspace";

export function OverviewScreen() {
  const router = useRouter();
  const { dashboard, currency, setCurrency, refreshing, error, reload } =
    useWorkspace();

  if (!dashboard) {
    return (
      <LoadingState
        label="Bringing your picture together"
        error={error}
        onRetry={() => void reload()}
      />
    );
  }

  const totals = dashboard.totals;

  return (
    <Page refreshing={refreshing} onRefresh={() => void reload()}>
      <ScreenHeader
        eyebrow={new Intl.DateTimeFormat("en-GB", {
          weekday: "long",
          day: "numeric",
          month: "long",
        }).format(new Date())}
        title="Your wealth, in focus."
        subtitle="A clearer view of what you have, what you are building, and what comes next."
      />
      <ChoiceGroup
        label="Reporting currency"
        options={availableCurrencies(dashboard.profile.base_currency, dashboard).map(
          (value) => ({ label: value, value }),
        )}
        value={currency}
        onChange={(value) => setCurrency(value as typeof currency)}
      />
      {error ? <Notice>{error}</Notice> : null}
      {dashboard.sample_data ? (
        <Notice tone="info">
          Legacy sample data is not connected to your personal accounts.
        </Notice>
      ) : null}

      {dashboard.accounts.length === 0 ? (
        <Card style={styles.setupCard}>
          <Text style={styles.setupKicker}>START WITH YOUR ACCOUNTS</Text>
          <Text style={styles.setupTitle}>
            Bring your accounts and investments together
          </Text>
          <Text style={styles.setupCopy}>
            Add a bank or brokerage account, then track the balances and
            investments you choose.
          </Text>
          <Text
            accessibilityRole="button"
            onPress={() => router.navigate("/(app)/(tabs)/portfolio")}
            style={styles.link}
          >
            Set up portfolio
          </Text>
        </Card>
      ) : null}

      <View style={styles.metricGrid}>
        <MetricCard
          label="TOTAL TRACKED WEALTH"
          value={formatMoney(totals.net_worth, currency)}
          detail="After estimated tax"
          accent
        />
        <MetricCard
          label="OWNED INVESTMENTS"
          value={formatMoney(totals.invested_assets, currency)}
          detail={`${dashboard.holdings.length} positions`}
        />
        <MetricCard
          label="AVAILABLE CASH"
          value={formatMoney(totals.available_cash, currency)}
          detail={
            Number(totals.reserve_shortfall) > 0
              ? `${formatMoney(totals.reserve_shortfall, currency)} reserve gap`
              : "Reserve target on track"
          }
        />
        <MetricCard
          label="FIXED DEPOSITS"
          value={formatMoney(totals.fixed_deposits, currency)}
          detail={`${dashboard.deposits.length} tracked deposits`}
        />
      </View>

      <SectionHeading
        title="Your accounts"
        action="See all"
        onAction={() => router.navigate("/(app)/(tabs)/portfolio")}
      />
      {dashboard.account_wealth.length ? (
        dashboard.account_wealth.slice(0, 4).map((account) => (
          <Card key={account.id} style={styles.accountCard}>
            <View style={styles.rowBetween}>
              <View style={styles.flex}>
                <Text style={styles.cardTitle}>{account.display_name}</Text>
                <Text style={styles.cardMeta}>
                  {account.account_type.toLowerCase().replace(/_/g, " ")}
                </Text>
              </View>
              <Text style={styles.money}>
                {formatMoney(account.total_after_tax_value, currency)}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={styles.cardMeta}>Cash</Text>
              <Text style={styles.cardValue}>
                {formatMoney(account.cash_value, currency)}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={styles.cardMeta}>Owned holdings after tax</Text>
              <Text style={styles.cardValue}>
                {formatMoney(account.after_tax_holdings_value, currency)}
              </Text>
            </View>
          </Card>
        ))
      ) : (
        <Card>
          <Text style={styles.cardMeta}>No accounts have been added yet.</Text>
        </Card>
      )}

      <SectionHeading
        title="Goals"
        action="View goals"
        onAction={() => router.navigate("/(app)/(tabs)/goals")}
      />
      {dashboard.goals.length ? (
        dashboard.goals.slice(0, 3).map((goal) => {
          const progress = Number(goal.progress_percent);
          const target =
            goal.goal_type === "passive_income"
              ? goal.target_annual_income
              : goal.target_amount;
          return (
            <Card key={goal.id}>
              <View style={styles.rowBetween}>
                <View style={styles.flex}>
                  <Text style={styles.cardTitle}>{goal.name}</Text>
                  <Text style={styles.cardMeta}>
                    {goal.target_date ? `Target ${formatDate(goal.target_date)}` : "Ongoing"}
                  </Text>
                </View>
                <Badge
                  label={`${Math.round(Number.isFinite(progress) ? progress : 0)}%`}
                  tone={progress >= 100 ? "positive" : "neutral"}
                />
              </View>
              <ProgressBar value={progress} />
              <Text style={styles.cardMeta}>
                {formatMoney(goal.current_amount, goal.currency)} of{" "}
                {target ? formatMoney(target, goal.currency) : "no target set"}
              </Text>
            </Card>
          );
        })
      ) : (
        <Card>
          <Text style={styles.cardMeta}>
            Set a goal to give your investment plan a purpose.
          </Text>
        </Card>
      )}

      <SectionHeading
        title="Recent cash flow"
        action="View ledger"
        onAction={() => router.navigate("/(app)/(tabs)/cashflow")}
      />
      {dashboard.cash_flows.length ? (
        dashboard.cash_flows.slice(0, 4).map((flow) => (
          <Card key={flow.id} style={styles.flowCard}>
            <View style={styles.flex}>
              <Text style={styles.cardTitle}>{flow.label}</Text>
              <Text style={styles.cardMeta}>
                {flow.status === "forecast" ? "Expected" : "Recorded"}{" "}
                {formatDate(flow.expected_date ?? flow.occurred_at)}
              </Text>
            </View>
            <View style={styles.flowAmount}>
              <Text
                style={[
                  styles.flowValue,
                  flow.direction === "outflow" && styles.negative,
                ]}
              >
                {flow.direction === "outflow" ? "-" : "+"}
                {formatMoney(flow.amount, flow.currency)}
              </Text>
              <Badge
                label={flow.status === "forecast" ? "Forecast" : "Confirmed"}
                tone={flow.status === "forecast" ? "warning" : "positive"}
              />
            </View>
          </Card>
        ))
      ) : (
        <Card>
          <Text style={styles.cardMeta}>No cash flows recorded or forecast.</Text>
        </Card>
      )}

      {dashboard.warnings.length ? (
        <Card style={styles.warningCard}>
          <Text style={styles.warningTitle}>Data notes</Text>
          {dashboard.warnings.slice(0, 3).map((warning) => (
            <Text key={warning} style={styles.cardMeta}>
              {warning}
            </Text>
          ))}
        </Card>
      ) : null}

      <Text style={styles.asOf}>Snapshot {formatDate(dashboard.as_of)}</Text>
    </Page>
  );
}

const styles = StyleSheet.create({
  metricGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  setupCard: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  setupKicker: { color: colors.accent, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  setupTitle: { color: "#FFFFFF", fontSize: 20, fontWeight: "800", lineHeight: 26 },
  setupCopy: { color: "#D2E1D7", fontSize: 13, lineHeight: 19 },
  link: { color: colors.accent, fontSize: 13, fontWeight: "800", paddingVertical: 4 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  flex: { flex: 1, gap: 4 },
  accountCard: { gap: 13 },
  cardTitle: { color: colors.text, fontSize: 14, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  money: { color: colors.text, fontSize: 16, fontWeight: "800" },
  cardValue: { color: colors.text, fontSize: 12, fontWeight: "700" },
  flowCard: { flexDirection: "row", alignItems: "center", gap: 10 },
  flowAmount: { alignItems: "flex-end", gap: 7 },
  flowValue: { color: colors.positive, fontSize: 13, fontWeight: "800" },
  negative: { color: colors.danger },
  warningCard: { backgroundColor: "#FFF9EA", borderColor: "#F1E0B4" },
  warningTitle: { color: colors.warning, fontSize: 13, fontWeight: "800" },
  asOf: { color: colors.muted, fontSize: 10, textAlign: "center", paddingTop: 4 },
});
