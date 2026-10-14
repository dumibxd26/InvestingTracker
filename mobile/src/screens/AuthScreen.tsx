import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError } from "../api";
import type { AuthResponse, Currency } from "../types";
import { ActionButton, ChoiceGroup, Field, Notice } from "../ui";
import { colors, radius } from "../theme";

const currencies: { label: string; value: Currency }[] = [
  { label: "EUR", value: "EUR" },
  { label: "USD", value: "USD" },
  { label: "RON", value: "RON" },
];

export function AuthScreen({
  notice,
  onAuthenticated,
}: {
  notice: string;
  onAuthenticated: (response: AuthResponse) => void;
}) {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [displayName, setDisplayName] = useState("");
  const [currency, setCurrency] = useState<Currency | "">("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [usdPerEur, setUsdPerEur] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    if (mode === "register" && password.length < 12) {
      setError("Choose a password with at least 12 characters.");
      return;
    }
    if (mode === "register" && !currency) {
      setError("Choose your base reporting currency to continue.");
      return;
    }
    setBusy(true);
    try {
      const normalizedUsername = username.trim().toLowerCase();
      let response: AuthResponse;
      if (mode === "login") {
        response = await api.login(normalizedUsername, password);
      } else {
        response = await api.register({
          username: normalizedUsername,
          password,
          base_currency: currency as Currency,
          ...(displayName.trim()
            ? { display_name: displayName.trim() }
            : {}),
          ...(usdPerEur.trim() ? { usd_per_eur: usdPerEur.trim() } : {}),
        });
      }
      onAuthenticated(response);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "We could not complete sign-in.",
      );
    } finally {
      setBusy(false);
    }
  }

  function changeMode(nextMode: "register" | "login") {
    setMode(nextMode);
    setError("");
  }

  return (
    <SafeAreaView edges={["top", "bottom"]} style={styles.safeArea}>
      <KeyboardAvoidingView
        style={styles.keyboard}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.hero}>
            <View style={styles.brandMark}>
              <View style={styles.brandMarkInner} />
            </View>
            <Text style={styles.brand}>InvestingTracker</Text>
            <Text style={styles.heroEyebrow}>A clearer relationship with money</Text>
            <Text style={styles.heroTitle}>
              Your whole financial picture.{"\n"}
              <Text style={styles.heroEmphasis}>Finally in one place.</Text>
            </Text>
            <Text style={styles.heroCopy}>
              Bring your accounts, goals, and future cash flows together in one
              private workspace.
            </Text>
            <Text style={styles.privacy}>
              Your data stays in your local InvestingTracker database.
            </Text>
          </View>

          <View style={styles.formCard}>
            <Text style={styles.formEyebrow}>YOUR PRIVATE WORKSPACE</Text>
            <Text style={styles.formTitle}>
              {mode === "register" ? "Create your account" : "Welcome back"}
            </Text>
            <Text style={styles.formCopy}>
              {mode === "register"
                ? "Start with a blank workspace. Add only what you want to track."
                : "Sign in to open your financial workspace."}
            </Text>
            {notice ? <Notice tone="info">{notice}</Notice> : null}

            {mode === "register" ? (
              <>
                <Field
                  label="Display name (optional)"
                  value={displayName}
                  onChangeText={setDisplayName}
                  placeholder="What should we call you?"
                  autoCapitalize="words"
                  maxLength={80}
                />
                <ChoiceGroup
                  label="Reporting currency"
                  options={currencies}
                  value={currency}
                  onChange={(value) => setCurrency(value as Currency)}
                />
              </>
            ) : null}

            <Field
              label="Username"
              value={username}
              onChangeText={setUsername}
              placeholder="Choose a username"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="username"
              textContentType="username"
              maxLength={32}
            />
            <Field
              label="Password"
              value={password}
              onChangeText={setPassword}
              placeholder={
                mode === "register" ? "At least 12 characters" : "Your password"
              }
              secureTextEntry
              autoCapitalize="none"
              autoComplete={mode === "register" ? "new-password" : "password"}
              textContentType={
                mode === "register" ? "newPassword" : "password"
              }
              maxLength={128}
            />
            {mode === "register" ? (
              <Field
                label="Manual USD per EUR reference (optional)"
                value={usdPerEur}
                onChangeText={setUsdPerEur}
                placeholder="Leave blank until you set a rate"
                keyboardType="decimal-pad"
                helper="Only needed when valuing USD and EUR together."
              />
            ) : null}
            {error ? <Notice>{error}</Notice> : null}
            <ActionButton
              label={
                mode === "register" ? "Create personal account" : "Sign in"
              }
              onPress={() => void submit()}
              loading={busy}
              disabled={!username.trim() || !password}
            />
            <View style={styles.modeSwitch}>
              <Text style={styles.modeCopy}>
                {mode === "register"
                  ? "Already have an account?"
                  : "New to InvestingTracker?"}
              </Text>
              <Pressable
                accessibilityRole="button"
                onPress={() =>
                  changeMode(mode === "register" ? "login" : "register")
                }
              >
                <Text style={styles.modeAction}>
                  {mode === "register" ? "Sign in" : "Create an account"}
                </Text>
              </Pressable>
            </View>
            <Text style={styles.localNote}>
              This local prototype has no email recovery or cloud backup yet.
              Keep your password safe.
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.primaryDark },
  keyboard: { flex: 1 },
  content: { flexGrow: 1, padding: 20, gap: 22, paddingBottom: 32 },
  hero: { gap: 13, paddingTop: 10 },
  brandMark: {
    width: 38,
    height: 38,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 13,
    backgroundColor: colors.accent,
  },
  brandMarkInner: {
    width: 15,
    height: 15,
    borderRadius: 5,
    backgroundColor: colors.primaryDark,
    transform: [{ rotate: "45deg" }],
  },
  brand: { color: "#FFFFFF", fontSize: 16, fontWeight: "800" },
  heroEyebrow: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.2,
    marginTop: 14,
  },
  heroTitle: { color: "#FFFFFF", fontSize: 28, fontWeight: "800", lineHeight: 34 },
  heroEmphasis: { color: colors.accent },
  heroCopy: { color: "#D5E6DC", fontSize: 14, lineHeight: 21, maxWidth: 440 },
  privacy: { color: "#C4D8CC", fontSize: 11, fontWeight: "600" },
  formCard: {
    gap: 15,
    backgroundColor: colors.surface,
    borderRadius: radius.large,
    padding: 20,
    borderColor: "rgba(255,255,255,0.55)",
    borderWidth: 1,
  },
  formEyebrow: {
    color: colors.primary,
    fontSize: 10,
    letterSpacing: 1.3,
    fontWeight: "800",
  },
  formTitle: { color: colors.text, fontSize: 24, fontWeight: "800" },
  formCopy: { color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: -8 },
  modeSwitch: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    flexWrap: "wrap",
  },
  modeCopy: { color: colors.muted, fontSize: 12 },
  modeAction: { color: colors.primary, fontSize: 12, fontWeight: "800" },
  localNote: { color: colors.muted, fontSize: 11, lineHeight: 16, textAlign: "center" },
});
