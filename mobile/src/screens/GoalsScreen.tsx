import { useState } from "react";
import {
  Alert,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { api, ApiError } from "../api";
import { formatDate, formatMoney } from "../format";
import type { Currency, GoalCreatePayload, GoalType, GoalRecord, ContributionRule, MoneyBasis } from "../types";
import { PlanningEditor, basisOptions } from "../components/PlanningEditor";
import { ContributionRulesEditor } from "../components/ContributionRulesEditor";
import { ContributionPreview } from "../components/ContributionPreview";
import { newRule } from "../planning";
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
  ProgressBar,
  ScreenHeader,
  SectionHeading,
} from "../ui";
import { useWorkspace } from "../workspace";

const goalTypes: { label: string; value: GoalType }[] = [
  { label: "Wealth", value: "wealth" },
  { label: "Retirement", value: "retirement" },
  { label: "Passive income", value: "passive_income" },
  { label: "Purchase", value: "purchase" },
  { label: "Preservation", value: "preservation" },
  { label: "Debt repayment", value: "debt_repayment" },
  { label: "Custom", value: "custom" },
];

const riskOptions = [
  { label: "Low", value: "low" },
  { label: "Moderate", value: "moderate" },
  { label: "High", value: "high" },
];

export function GoalsScreen() {
  const { dashboard, currency, refreshing, error, reload } = useWorkspace();
  const [createOpen, setCreateOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [targetCurrency, setTargetCurrency] = useState<Currency>(currency);
  const [name, setName] = useState("");
  const [goalType, setGoalType] = useState<GoalType | "">("");
  const [target, setTarget] = useState("");
  const [monthlyContribution, setMonthlyContribution] = useState("0");
  const [targetDate, setTargetDate] = useState("");
  const [editingGoal, setEditingGoal] = useState<GoalRecord | null>(null);
  const [rules, setRules] = useState<ContributionRule[] | null>(() => [newRule()]);
  const [targetBasis, setTargetBasis] = useState<MoneyBasis>("real");
  const [inflation, setInflation] = useState("");
  const [revision, setRevision] = useState(0);
  const [riskLevel, setRiskLevel] = useState<"low" | "moderate" | "high" | "">("");
  const [flexibility, setFlexibility] = useState<"essential" | "flexible" | "">("");

  async function createGoal() {
    if (name.trim().length < 2) {
      setFormError("Enter a goal name.");
      return;
    }
    if (!goalType || !riskLevel || !flexibility) {
      setFormError("Choose a goal type, risk comfort, and flexibility.");
      return;
    }
    if (!target.trim() || !Number.isFinite(Number(target)) || Number(target) <= 0) {
      setFormError("Set a target amount greater than zero.");
      return;
    }
    if (
      !Number.isFinite(Number(monthlyContribution)) ||
      Number(monthlyContribution) < 0
    ) {
      setFormError("Monthly contribution must be zero or more.");
      return;
    }

    const payload: GoalCreatePayload = {
      name: name.trim(),
      goal_type: goalType,
      target_currency: targetCurrency,
      target_money_basis: targetBasis,
      annual_inflation_rate: inflation === "" ? null : String(Number(inflation) / 100),
      contribution_rules: rules,
      risk_level: riskLevel,
      monthly_contribution: monthlyContribution || "0",
      flexibility,
      current_amount: editingGoal?.current_amount ?? "0",
      current_annual_income: editingGoal?.current_annual_income ?? "0",
      linked_account_ids: editingGoal?.linked_account_ids ?? [],
      holding_allocations: editingGoal?.holding_allocations ?? [],
      fixed_deposit_allocations: editingGoal?.fixed_deposit_allocations ?? [],
      ...(editingGoal ? {
        visualization_budget_amount: editingGoal.visualization_budget_amount,
        visualization_budget_period: editingGoal.visualization_budget_period,
        ...(editingGoal.fixed_percent == null ? {} : { fixed_percent: editingGoal.fixed_percent }),
      } : {}),
      ...(target.trim()
        ? goalType === "passive_income"
          ? { target_annual_income: target.trim() }
          : { target_amount: target.trim() }
        : {}),
      ...(targetDate.trim() ? { target_date: targetDate.trim() } : {}),
    };

    setBusy(true);
    setFormError("");
    try {
      if (editingGoal) await api.updateGoal(editingGoal.id, { ...payload, current_amount: payload.current_amount ?? "0", current_annual_income: payload.current_annual_income ?? "0" });
      else await api.createGoal(payload);
      await reload();
      setRevision(r => r + 1);
      setCreateOpen(false);
      setName("");
      setTarget("");
      setMonthlyContribution("0");
      setTargetDate("");
    } catch (cause) {
      setFormError(
        cause instanceof ApiError
          ? cause.message
          : "The goal could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function editGoal(id: string) {
    setBusy(true);
    try {
      const goal = (await api.listGoals()).find(g => g.id === id);
      if (!goal) throw new Error("Goal not found.");
      setEditingGoal(goal); setName(goal.name); setGoalType(goal.goal_type);
      setTargetCurrency(goal.target_currency);
      setTarget((goal.goal_type === "passive_income" ? goal.target_annual_income : goal.target_amount) ?? "");
      setMonthlyContribution(goal.monthly_contribution); setTargetDate(goal.target_date ?? "");
      setRiskLevel(goal.risk_level); setFlexibility(goal.flexibility);
      setRules(goal.contribution_rules ?? null); setTargetBasis(goal.target_money_basis ?? "real");
      setInflation(goal.annual_inflation_rate == null ? "" : String(Number(goal.annual_inflation_rate) * 100));
      setFormError(""); setCreateOpen(true);
    } catch (e) { Alert.alert("Could not load goal", String(e)); }
    finally { setBusy(false); }
  }

  function deleteGoal(id: string, goalName: string) {
    Alert.alert(
      "Delete goal?",
      `Remove "${goalName}" from your active goals? Its history will be archived.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            setBusy(true);
            void api
              .deleteGoal(id)
              .then(reload)
              .catch((cause) =>
                Alert.alert(
                  "Could not delete goal",
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
        label="Loading your goals"
        error={error}
        onRetry={() => void reload()}
      />
    );
  }

  return (
    <>
      <Page refreshing={refreshing} onRefresh={() => void reload()}>
        <ScreenHeader
          eyebrow="Your money, your meaning"
          title="Goals & plan."
          subtitle="Choose what matters, then decide how future contributions can support it."
        />
        {error ? <Notice>{error}</Notice> : null}
        <Card style={styles.explainer}>
          <Text style={styles.explainerTitle}>
            A goal is a purpose, not a separate account.
          </Text>
          <Text style={styles.cardMeta}>
            Set a deadline and comfort with risk. Investments can
            stay together while you track different purposes.
          </Text>
        </Card>
        <PlanningEditor currency={currency} onSaved={async () => { setRevision(r => r + 1); await reload(); }} />
        <ActionButton
          label="Add a goal"
          onPress={() => {
            setFormError("");
            setTargetCurrency(currency);
            setName("");
            setGoalType("");
            setTarget("");
            setMonthlyContribution("0");
            setTargetDate("");
            setEditingGoal(null); setRules([newRule()]); setTargetBasis("real"); setInflation("");
            setRiskLevel("");
            setFlexibility("");
            setCreateOpen(true);
          }}
        />
        <SectionHeading title={`${dashboard.goals.length} active goals`} />
        {dashboard.goals.length ? (
          dashboard.goals.map((goal) => {
            const progress = Number(goal.progress_percent);
            const targetValue =
              goal.goal_type === "passive_income"
                ? goal.target_annual_income
                : goal.target_amount;
            return (
              <Card key={goal.id}>
                <View style={styles.goalTop}>
                  <View style={styles.goalCopy}>
                    <Text style={styles.goalName}>{goal.name}</Text>
                    <Text style={styles.cardMeta}>
                      {goal.goal_type.replace(/_/g, " ")} · {goal.target_money_basis === "nominal" ? "Nominal target" : "Today's-money target"}
                    </Text>
                  </View>
                  <Badge
                    label={`${Math.round(Number.isFinite(progress) ? progress : 0)}%`}
                    tone={progress >= 100 ? "positive" : "neutral"}
                  />
                </View>
                <ProgressBar value={progress} />
                <View style={styles.goalMetaRow}>
                  <View style={styles.goalCopy}>
                    <Text style={styles.currentAmount}>
                      {formatMoney(goal.current_amount, goal.currency)}
                    </Text>
                    <Text style={styles.cardMeta}>
                      of{" "}
                      {targetValue
                        ? formatMoney(targetValue, goal.currency)
                        : "no target set"}
                    </Text>
                  </View>
                  <Text style={styles.cardMeta}>
                    {goal.target_date ? formatDate(goal.target_date) : "Ongoing"}
                  </Text>
                </View>
                <View style={styles.goalMetaRow}>
                  <Text style={styles.cardMeta}>
                    {formatMoney(goal.monthly_contribution, goal.currency)} / month
                  </Text>
                  <Text style={styles.cardMeta}>
                    {goal.risk_level} risk  |  {goal.flexibility}
                  </Text>
                </View>
                <ContributionPreview goalId={goal.id} revision={`${revision}:${JSON.stringify(goal)}`} />
                <ActionButton label="Edit goal" disabled={busy} onPress={() => void editGoal(goal.id)} />
                <Pressable
                  accessibilityRole="button"
                  onPress={() => deleteGoal(goal.id, goal.name)}
                  style={styles.removeAction}
                >
                  <Text style={styles.removeText}>Delete goal</Text>
                </Pressable>
              </Card>
            );
          })
        ) : (
          <Card>
            <Text style={styles.cardMeta}>
              Your workspace has no active goals yet.
            </Text>
          </Card>
        )}
        <SectionHeading title="Funding preferences" />
        <Card>
          <View style={styles.goalMetaRow}>
            <Text style={styles.cardMeta}>Goal funding</Text>
            <Text style={styles.cardValue}>
              {dashboard.policy.funding_rule
                ? dashboard.policy.funding_rule.replace(/_/g, " ")
                : "Not configured"}
            </Text>
          </View>
          <View style={styles.goalMetaRow}>
            <Text style={styles.cardMeta}>Emergency reserve target</Text>
            <Text style={styles.cardValue}>
              {formatMoney(dashboard.policy.emergency_reserve, currency)}
            </Text>
          </View>
          <Text style={styles.cardMeta}>
            Asset targets:{" "}
            {Object.entries(dashboard.policy.target_weights)
              .map(
                ([asset, weight]) =>
                  `${asset.replace("_", " ")} ${Math.round(Number(weight) * 100)}%`,
              )
              .join("  |  ")}
          </Text>
        </Card>
      </Page>

      <FormSheet
        visible={createOpen}
        title={editingGoal ? "Edit goal" : "Create a goal"}
        subtitle="You choose the purpose, target, and contribution timeline."
        onClose={() => setCreateOpen(false)}
      >
        <Field
          label="Goal name"
          value={name}
          onChangeText={setName}
          placeholder="e.g. Financial independence"
          maxLength={100}
        />
        <ChoiceGroup
          label="Goal type"
          options={goalTypes}
          value={goalType}
          onChange={(value) => setGoalType(value as GoalType)}
        />
        <ChoiceGroup
          label="Target currency"
          options={[
            { label: "EUR", value: "EUR" },
            { label: "USD", value: "USD" },
            { label: "RON", value: "RON" },
          ]}
          value={targetCurrency}
          onChange={(value) => setTargetCurrency(value as Currency)}
        />
        <Field
          label={goalType === "passive_income" ? "Annual income target" : "Target amount"}
          value={target}
          onChangeText={setTarget}
          placeholder="Optional"
          keyboardType="decimal-pad"
        />
        <Field
          label="Fixed monthly amount (nominal; used only in fixed monthly mode)"
          value={monthlyContribution}
          onChangeText={setMonthlyContribution}
          placeholder="0"
          keyboardType="decimal-pad"
          editable={rules === null}
        />
        <DateField
          label="Target date (optional)"
          value={targetDate}
          onChange={setTargetDate}
          optional
        />
        <ChoiceGroup label="Target amount basis" options={basisOptions} value={targetBasis} onChange={v => setTargetBasis(v as MoneyBasis)} />
        <Text>Real targets use reference-date purchasing power; nominal targets are fixed future amounts.</Text>
        <Field label="Target-cost annual inflation override (%; optional)" value={inflation} onChangeText={setInflation} keyboardType="numbers-and-punctuation" helper="Target cost only. Income and contributions use the global timeline." />
        <ContributionRulesEditor rules={rules} onChange={setRules} currency={targetCurrency} />
        <ChoiceGroup
          label="Risk comfort"
          options={riskOptions}
          value={riskLevel}
          onChange={(value) =>
            setRiskLevel(value as "low" | "moderate" | "high")
          }
        />
        <ChoiceGroup
          label="Flexibility"
          options={[
            { label: "Essential", value: "essential" },
            { label: "Flexible", value: "flexible" },
          ]}
          value={flexibility}
          onChange={(value) =>
            setFlexibility(value as "essential" | "flexible")
          }
        />
        {formError ? <Notice>{formError}</Notice> : null}
        <ActionButton
          label="Save goal"
          onPress={() => void createGoal()}
          loading={busy}
          disabled={!name.trim()}
        />
      </FormSheet>
    </>
  );
}

const styles = StyleSheet.create({
  explainer: { backgroundColor: colors.primarySoft, borderColor: colors.primarySoft },
  explainerTitle: { color: colors.primaryDark, fontSize: 15, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  goalTop: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 10 },
  goalCopy: { flex: 1, gap: 4 },
  goalName: { color: colors.text, fontSize: 15, fontWeight: "800" },
  goalMetaRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  currentAmount: { color: colors.text, fontSize: 16, fontWeight: "800" },
  cardValue: { color: colors.text, fontSize: 12, fontWeight: "700", textAlign: "right" },
  removeAction: { alignSelf: "flex-start", paddingVertical: 4 },
  removeText: { color: colors.danger, fontSize: 12, fontWeight: "700" },
});
