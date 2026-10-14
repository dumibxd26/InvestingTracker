import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "../theme";
import { Card, Page, ScreenHeader } from "../ui";
import { useWorkspace } from "../workspace";

const destinations: {
  title: string;
  copy: string;
  href: "/(app)/compensation" | "/(app)/assistant" | "/(app)/settings";
  icon: string;
}[] = [
  {
    title: "Equity & deposits",
    copy: "Employer awards, planned share purchases, and term deposits.",
    href: "/(app)/compensation",
    icon: "E",
  },
  {
    title: "AI assistant",
    copy: "Ask read-only questions about your current tracker snapshot.",
    href: "/(app)/assistant",
    icon: "A",
  },
  {
    title: "Profile settings",
    copy: "Update your name, currency, and tax assumptions.",
    href: "/(app)/settings",
    icon: "S",
  },
];

export function MoreScreen() {
  const router = useRouter();
  const { profile, dashboard } = useWorkspace();

  return (
    <Page>
      <ScreenHeader
        eyebrow="Plan & learn"
        title="More."
        subtitle="Explore the rest of your private financial workspace."
      />
      <Card style={styles.profileCard}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>
            {profile.username.slice(0, 1).toUpperCase()}
          </Text>
        </View>
        <View style={styles.profileCopy}>
          <Text style={styles.profileName}>{profile.display_name}</Text>
          <Text style={styles.profileMeta}>
            @{profile.username}  |  {profile.base_currency} reporting currency
          </Text>
        </View>
      </Card>
      {destinations.map((destination) => (
        <Pressable
          accessibilityRole="button"
          key={destination.href}
          onPress={() => router.push(destination.href)}
          style={({ pressed }) => [pressed && styles.pressed]}
        >
          <Card style={styles.destination}>
            <View style={styles.destinationIcon}>
              <Text style={styles.destinationIconText}>{destination.icon}</Text>
            </View>
            <View style={styles.destinationCopy}>
              <Text style={styles.destinationTitle}>{destination.title}</Text>
              <Text style={styles.destinationDescription}>
                {destination.copy}
              </Text>
            </View>
            <Text style={styles.chevron}>{"\u203A"}</Text>
          </Card>
        </Pressable>
      ))}
      <Card style={styles.privacyCard}>
        <Text style={styles.privacyTitle}>You stay in control</Text>
        <Text style={styles.privacyCopy}>
          No automatic trades. Changes in InvestingTracker only update your
          tracked records, not your bank or brokerage accounts.
        </Text>
      </Card>
      {dashboard?.sample_data ? (
        <Text style={styles.sampleNote}>
          This workspace includes legacy sample data. Review it in Portfolio.
        </Text>
      ) : null}
    </Page>
  );
}

const styles = StyleSheet.create({
  profileCard: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: { width: 42, height: 42, borderRadius: 15, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#FFFFFF", fontSize: 17, fontWeight: "800" },
  profileCopy: { flex: 1, gap: 4 },
  profileName: { color: colors.text, fontSize: 15, fontWeight: "800" },
  profileMeta: { color: colors.muted, fontSize: 11 },
  destination: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14 },
  destinationIcon: { width: 38, height: 38, alignItems: "center", justifyContent: "center", borderRadius: 13, backgroundColor: colors.primarySoft },
  destinationIconText: { color: colors.primary, fontSize: 14, fontWeight: "900" },
  destinationCopy: { flex: 1, gap: 4 },
  destinationTitle: { color: colors.text, fontSize: 14, fontWeight: "800" },
  destinationDescription: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  chevron: { color: colors.primary, fontSize: 23, fontWeight: "600" },
  privacyCard: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  privacyTitle: { color: "#FFFFFF", fontSize: 14, fontWeight: "800" },
  privacyCopy: { color: "#D5E6DC", fontSize: 12, lineHeight: 18 },
  sampleNote: { color: colors.warning, fontSize: 11, lineHeight: 16 },
  pressed: { opacity: 0.82 },
});
