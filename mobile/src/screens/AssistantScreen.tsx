import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { api, ApiError } from "../api";
import { formatMoney } from "../format";
import type { ChatMessage } from "../types";
import { colors } from "../theme";
import {
  ActionButton,
  Card,
  Field,
  Notice,
  Page,
  ScreenHeader,
  SectionHeading,
} from "../ui";
import { useWorkspace } from "../workspace";

const suggestions = [
  "What does my available cash include?",
  "Explain my current investment mix.",
  "How would a new contribution be split?",
];

export function AssistantScreen() {
  const { dashboard, currency } = useWorkspace();
  const [apiKey, setApiKey] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function ask(rawQuestion: string) {
    const normalized = rawQuestion.trim();
    if (!normalized || busy) return;
    if (!apiKey.trim()) {
      setError("Enter your OpenAI-compatible API key before asking a question.");
      return;
    }
    setError("");
    setQuestion("");
    const history = messages.slice(-8);
    const nextMessages = [
      ...messages,
      { role: "user" as const, content: normalized },
    ];
    setMessages(nextMessages);
    setBusy(true);
    try {
      const reply = await api.askAssistant(
        normalized,
        history,
        apiKey.trim(),
      );
      setMessages([
        ...nextMessages,
        { role: "assistant", content: reply.answer },
      ]);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The assistant request could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page safeEdges={["bottom"]}>
      <ScreenHeader
        eyebrow="Read-only | grounded in your tracker"
        title="Ask with context."
        subtitle="Explore your numbers and goals in plain language. The assistant cannot change your plan."
      />
      <Card style={styles.privacyCard}>
        <Text style={styles.privacyTitle}>Your model access</Text>
        <Text style={styles.cardMeta}>
          Bring your own OpenAI-compatible API key. It is held in memory and
          sent only with a question; it is not saved in your profile.
        </Text>
        <Field
          label="Provider API key"
          value={apiKey}
          onChangeText={setApiKey}
          placeholder="Enter your key"
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="off"
          textContentType="none"
        />
        <Text style={styles.cardMeta}>
          The assistant receives a compact snapshot only when you submit.
        </Text>
      </Card>

      <Card style={styles.chatCard}>
        <View style={styles.chatHeading}>
          <View style={styles.botIcon}>
            <Text style={styles.botIconText}>AI</Text>
          </View>
          <View style={styles.chatHeadingCopy}>
            <Text style={styles.chatTitle}>InvestingTracker assistant</Text>
            <Text style={styles.cardMeta}>Current app snapshot | read only</Text>
          </View>
        </View>
        {messages.length === 0 ? (
          <View style={styles.welcome}>
            <Text style={styles.welcomeTitle}>
              A second perspective, not a black box.
            </Text>
            <Text style={styles.cardMeta}>
              Ask about recorded calculations, goals, or cash flow. Check the
              figures and assumptions in the tracker.
            </Text>
            {suggestions.map((suggestion) => (
              <Pressable
                accessibilityRole="button"
                key={suggestion}
                disabled={busy}
                onPress={() => void ask(suggestion)}
                style={styles.suggestion}
              >
                <Text style={styles.suggestionText}>{suggestion}</Text>
              </Pressable>
            ))}
          </View>
        ) : (
          <View style={styles.messages}>
            {messages.map((message, index) => (
              <View
                key={`${message.role}-${index}`}
                style={[
                  styles.message,
                  message.role === "user" && styles.userMessage,
                ]}
              >
                <Text style={styles.messageAuthor}>
                  {message.role === "assistant" ? "InvestingTracker" : "You"}
                </Text>
                <Text style={styles.messageText}>{message.content}</Text>
              </View>
            ))}
            {busy ? (
              <Text style={styles.cardMeta}>InvestingTracker is thinking...</Text>
            ) : null}
          </View>
        )}
        <Field
          label="Your question"
          value={question}
          onChangeText={setQuestion}
          placeholder="Ask about goals, cash flow, or allocation..."
          multiline
          maxLength={2000}
        />
        {error ? <Notice>{error}</Notice> : null}
        <ActionButton
          label="Send question"
          onPress={() => void ask(question)}
          loading={busy}
          disabled={!question.trim()}
        />
      </Card>

      {dashboard ? (
        <Card>
          <SectionHeading title="Snapshot context" />
          <View style={styles.snapshotRow}>
            <Text style={styles.cardMeta}>Tracked net worth</Text>
            <Text style={styles.snapshotValue}>
              {formatMoney(dashboard.totals.net_worth, currency)}
            </Text>
          </View>
          <View style={styles.snapshotRow}>
            <Text style={styles.cardMeta}>Active goals</Text>
            <Text style={styles.snapshotValue}>
              {dashboard.goals.length}
            </Text>
          </View>
          <View style={styles.snapshotRow}>
            <Text style={styles.cardMeta}>Portfolio positions</Text>
            <Text style={styles.snapshotValue}>
              {dashboard.holdings.length}
            </Text>
          </View>
        </Card>
      ) : null}
      <Notice tone="info">
        AI responses can be wrong and are not financial or tax advice.
      </Notice>
    </Page>
  );
}

const styles = StyleSheet.create({
  privacyCard: { backgroundColor: colors.primarySoft, borderColor: colors.primarySoft },
  privacyTitle: { color: colors.primaryDark, fontSize: 15, fontWeight: "800" },
  cardMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  chatCard: { gap: 14 },
  chatHeading: { flexDirection: "row", alignItems: "center", gap: 10 },
  botIcon: { width: 38, height: 38, alignItems: "center", justifyContent: "center", borderRadius: 13, backgroundColor: colors.primary },
  botIconText: { color: "#FFFFFF", fontSize: 12, fontWeight: "900" },
  chatHeadingCopy: { flex: 1, gap: 3 },
  chatTitle: { color: colors.text, fontSize: 14, fontWeight: "800" },
  welcome: { gap: 10 },
  welcomeTitle: { color: colors.text, fontSize: 17, fontWeight: "800" },
  suggestion: { padding: 11, borderRadius: 10, backgroundColor: colors.surfaceMuted },
  suggestionText: { color: colors.primary, fontSize: 12, fontWeight: "700", lineHeight: 17 },
  messages: { gap: 10 },
  message: { padding: 12, borderRadius: 12, backgroundColor: colors.surfaceMuted, gap: 5 },
  userMessage: { backgroundColor: colors.primarySoft },
  messageAuthor: { color: colors.primary, fontSize: 10, fontWeight: "800" },
  messageText: { color: colors.text, fontSize: 13, lineHeight: 19 },
  snapshotRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  snapshotValue: { color: colors.text, fontSize: 13, fontWeight: "800" },
});
