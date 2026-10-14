import { useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from "react-native";
import DateTimePicker from "@react-native-community/datetimepicker";
import { SafeAreaView, type Edge } from "react-native-safe-area-context";
import { formatDate } from "./format";
import { colors, radius } from "./theme";

export function Page({
  children,
  refreshing = false,
  onRefresh,
  contentStyle,
  safeEdges = ["top"],
}: {
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
  contentStyle?: StyleProp<ViewStyle>;
  safeEdges?: Edge[];
}) {
  return (
    <SafeAreaView edges={safeEdges} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={[styles.pageContent, contentStyle]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.primary}
              colors={[colors.primary]}
            />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function ScreenHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <View style={styles.screenHeader}>
      <Text style={styles.eyebrow}>{eyebrow.toUpperCase()}</Text>
      <Text style={styles.screenTitle}>{title}</Text>
      {subtitle ? <Text style={styles.screenSubtitle}>{subtitle}</Text> : null}
    </View>
  );
}

export function SectionHeading({
  title,
  action,
  onAction,
}: {
  title: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.sectionHeading}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {action && onAction ? (
        <Pressable onPress={onAction} accessibilityRole="button">
          <Text style={styles.sectionAction}>{action}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function Card({
  children,
  style,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function MetricCard({
  label,
  value,
  detail,
  accent = false,
}: {
  label: string;
  value: string;
  detail?: string;
  accent?: boolean;
}) {
  return (
    <Card style={accent ? styles.metricCardAccent : styles.metricCard}>
      <Text style={[styles.metricLabel, accent && styles.metricLabelAccent]}>
        {label}
      </Text>
      <Text
        style={[styles.metricValue, accent && styles.metricValueAccent]}
        numberOfLines={1}
        adjustsFontSizeToFit
      >
        {value}
      </Text>
      {detail ? (
        <Text style={[styles.metricDetail, accent && styles.metricDetailAccent]}>
          {detail}
        </Text>
      ) : null}
    </Card>
  );
}

export function ActionButton({
  label,
  onPress,
  loading = false,
  disabled = false,
  secondary = false,
  danger = false,
}: {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  secondary?: boolean;
  danger?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        secondary && styles.buttonSecondary,
        danger && styles.buttonDanger,
        (disabled || loading) && styles.buttonDisabled,
        pressed && !disabled && !loading && styles.buttonPressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={secondary ? colors.primary : colors.surface} />
      ) : (
        <Text
          style={[
            styles.buttonText,
            secondary && styles.buttonTextSecondary,
            danger && styles.buttonTextDanger,
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

export function Field({
  label,
  helper,
  keyboardType,
  onChangeText,
  style,
  ...props
}: TextInputProps & { label: string; helper?: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        placeholderTextColor={colors.muted}
        selectionColor={colors.primary}
        style={[styles.input, props.multiline && styles.multilineInput, style]}
        keyboardType={keyboardType}
        onChangeText={
          onChangeText
            ? (value) =>
                onChangeText(
                  keyboardType === "decimal-pad"
                    ? value.replace(/,/g, ".")
                    : value,
                )
            : undefined
        }
        {...props}
      />
      {helper ? <Text style={styles.helper}>{helper}</Text> : null}
    </View>
  );
}

export function DateField({
  label,
  value,
  onChange,
  placeholder = "Select a date",
  optional = false,
  maximumDate,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  optional?: boolean;
  maximumDate?: Date;
}) {
  const [open, setOpen] = useState(false);
  const parsed = value ? new Date(`${value.slice(0, 10)}T12:00:00`) : new Date();
  const selectedDate = Number.isNaN(parsed.valueOf()) ? new Date() : parsed;

  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.dateRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${label}: ${value ? formatDate(value) : placeholder}`}
          onPress={() => setOpen(true)}
          style={styles.dateButton}
        >
          <Text style={value ? styles.dateValue : styles.datePlaceholder}>
            {value ? formatDate(value) : placeholder}
          </Text>
        </Pressable>
        {optional && value ? (
          <Pressable
            accessibilityRole="button"
            onPress={() => onChange("")}
            style={styles.dateClear}
          >
            <Text style={styles.dateClearText}>Clear</Text>
          </Pressable>
        ) : null}
      </View>
      {open ? (
        <DateTimePicker
          value={selectedDate}
          mode="date"
          display={Platform.OS === "ios" ? "compact" : "default"}
          maximumDate={maximumDate}
          onChange={(_event, date) => {
            setOpen(false);
            if (!date) return;
            const localDate = new Date(
              date.getTime() - date.getTimezoneOffset() * 60_000,
            );
            onChange(localDate.toISOString().slice(0, 10));
          }}
        />
      ) : null}
    </View>
  );
}

export function ChoiceGroup({
  label,
  options,
  value,
  onChange,
}: {
  label?: string;
  options: { label: string; value: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <View style={styles.choiceGroup}>
      {label ? <Text style={styles.fieldLabel}>{label}</Text> : null}
      <View style={styles.chipWrap}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              key={option.value}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => onChange(option.value)}
              style={[styles.chip, selected && styles.chipSelected]}
            >
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export function Badge({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "neutral" | "positive" | "warning";
}) {
  return (
    <View
      style={[
        styles.badge,
        tone === "positive" && styles.badgePositive,
        tone === "warning" && styles.badgeWarning,
      ]}
    >
      <Text
        style={[
          styles.badgeText,
          tone === "positive" && styles.badgeTextPositive,
          tone === "warning" && styles.badgeTextWarning,
        ]}
      >
        {label}
      </Text>
    </View>
  );
}

export function ProgressBar({ value }: { value: number }) {
  const progress = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: progress }}
      style={styles.progressTrack}
    >
      <View style={[styles.progressFill, { width: `${progress}%` }]} />
    </View>
  );
}

export function Notice({
  children,
  tone = "error",
}: {
  children: ReactNode;
  tone?: "error" | "info";
}) {
  return (
    <View style={[styles.notice, tone === "info" && styles.noticeInfo]}>
      <Text style={[styles.noticeText, tone === "info" && styles.noticeTextInfo]}>
        {children}
      </Text>
    </View>
  );
}

export function FormSheet({
  visible,
  title,
  subtitle,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <SafeAreaView edges={["top", "bottom"]} style={styles.sheetSafeArea}>
        <KeyboardAvoidingView
          style={styles.sheetKeyboard}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <View style={styles.sheetHeading}>
            <View style={styles.sheetHeadingCopy}>
              <Text style={styles.sheetTitle}>{title}</Text>
              {subtitle ? <Text style={styles.sheetSubtitle}>{subtitle}</Text> : null}
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close form"
              onPress={onClose}
              style={styles.closeButton}
            >
              <Text style={styles.closeButtonText}>Close</Text>
            </Pressable>
          </View>
          <ScrollView
            style={styles.sheetScroll}
            contentContainerStyle={styles.sheetContent}
            keyboardShouldPersistTaps="handled"
          >
            {children}
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

export function LoadingState({
  label = "Loading your private workspace",
  error,
  onRetry,
}: {
  label?: string;
  error?: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.stateContainer}>
      <View style={styles.stateMark}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
      <Text style={styles.stateTitle}>{error ? "Your snapshot is unavailable" : label}</Text>
      {error ? <Notice>{error}</Notice> : null}
      {error && onRetry ? (
        <ActionButton label="Try again" onPress={onRetry} secondary />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.background },
  pageContent: { padding: 20, paddingBottom: 36, gap: 18 },
  screenHeader: { gap: 7, marginBottom: 2 },
  eyebrow: {
    color: colors.primary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.4,
  },
  screenTitle: { color: colors.text, fontSize: 29, fontWeight: "800", letterSpacing: -0.8 },
  screenSubtitle: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  sectionHeading: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 4,
  },
  sectionTitle: { color: colors.text, fontSize: 17, fontWeight: "800" },
  sectionAction: { color: colors.primary, fontSize: 13, fontWeight: "700" },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.medium,
    padding: 16,
    gap: 10,
  },
  metricCard: { flex: 1, minWidth: "46%" },
  metricCardAccent: {
    flex: 1,
    minWidth: "46%",
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  metricLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", lineHeight: 16 },
  metricLabelAccent: { color: "#D5E6DC" },
  metricValue: { color: colors.text, fontSize: 20, fontWeight: "800" },
  metricValueAccent: { color: "#FFFFFF" },
  metricDetail: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  metricDetailAccent: { color: "#D5E6DC" },
  button: {
    minHeight: 48,
    borderRadius: radius.small,
    paddingHorizontal: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.primary,
  },
  buttonSecondary: { backgroundColor: colors.primarySoft },
  buttonDanger: { backgroundColor: colors.dangerSoft },
  buttonDisabled: { opacity: 0.55 },
  buttonPressed: { opacity: 0.82 },
  buttonText: { color: colors.surface, fontSize: 14, fontWeight: "800" },
  buttonTextSecondary: { color: colors.primary },
  buttonTextDanger: { color: colors.danger },
  field: { gap: 7 },
  fieldLabel: { color: colors.text, fontSize: 12, fontWeight: "700" },
  dateRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  dateButton: {
    flex: 1,
    minHeight: 47,
    justifyContent: "center",
    paddingHorizontal: 13,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.small,
    backgroundColor: colors.surface,
  },
  dateValue: { color: colors.text, fontSize: 15 },
  datePlaceholder: { color: colors.muted, fontSize: 15 },
  dateClear: { padding: 9 },
  dateClearText: { color: colors.primary, fontSize: 12, fontWeight: "800" },
  input: {
    minHeight: 47,
    paddingHorizontal: 13,
    paddingVertical: 11,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.small,
    color: colors.text,
    backgroundColor: colors.surface,
    fontSize: 15,
  },
  multilineInput: { minHeight: 100, textAlignVertical: "top" },
  helper: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  choiceGroup: { gap: 8 },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 13,
    paddingVertical: 9,
    backgroundColor: colors.surface,
  },
  chipSelected: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  chipText: { color: colors.muted, fontSize: 12, fontWeight: "700" },
  chipTextSelected: { color: colors.primary },
  badge: {
    alignSelf: "flex-start",
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 5,
    backgroundColor: colors.surfaceMuted,
  },
  badgePositive: { backgroundColor: colors.primarySoft },
  badgeWarning: { backgroundColor: colors.warningSoft },
  badgeText: { color: colors.muted, fontSize: 10, fontWeight: "800" },
  badgeTextPositive: { color: colors.positive },
  badgeTextWarning: { color: colors.warning },
  progressTrack: {
    height: 7,
    overflow: "hidden",
    borderRadius: 999,
    backgroundColor: colors.surfaceMuted,
  },
  progressFill: { height: "100%", borderRadius: 999, backgroundColor: colors.primary },
  notice: {
    borderWidth: 1,
    borderColor: "#F0C9C1",
    borderRadius: radius.small,
    padding: 12,
    backgroundColor: colors.dangerSoft,
  },
  noticeInfo: { borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  noticeText: { color: colors.danger, fontSize: 13, lineHeight: 19 },
  noticeTextInfo: { color: colors.text },
  sheetSafeArea: { flex: 1, backgroundColor: colors.background },
  sheetKeyboard: { flex: 1 },
  sheetHeading: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    padding: 20,
    paddingBottom: 14,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  sheetHeadingCopy: { flex: 1, paddingRight: 12, gap: 4 },
  sheetTitle: { color: colors.text, fontSize: 21, fontWeight: "800" },
  sheetSubtitle: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  closeButton: { paddingHorizontal: 8, paddingVertical: 6 },
  closeButtonText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  sheetScroll: { flex: 1 },
  sheetContent: { gap: 15, padding: 20, paddingBottom: 40 },
  stateContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 15,
    padding: 28,
    backgroundColor: colors.background,
  },
  stateMark: {
    width: 64,
    height: 64,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
    backgroundColor: colors.primarySoft,
  },
  stateTitle: { color: colors.text, fontSize: 17, fontWeight: "800", textAlign: "center" },
});
