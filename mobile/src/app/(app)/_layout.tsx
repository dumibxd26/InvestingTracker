import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import { Redirect, Stack } from "expo-router";
import { api, ApiError } from "../../api";
import type { Currency, Dashboard } from "../../types";
import { colors } from "../../theme";
import { LoadingState } from "../../ui";
import { useSession } from "../../session";
import { WorkspaceContext } from "../../workspace";

export default function WorkspaceLayout() {
  const { profile, authChecking, saveProfile: updateSessionProfile, logout } =
    useSession();
  const [currency, setCurrency] = useState<Currency>(
    profile?.base_currency ?? "EUR",
  );
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const hasLoadedData = useRef(false);
  const dashboardRequest = useRef<AbortController | null>(null);

  const fetchDashboard = useCallback(async (controller: AbortController) => {
    try {
      const result = await api.dashboard(currency, controller.signal);
      if (!controller.signal.aborted) {
        setDashboard(result);
        hasLoadedData.current = true;
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The wealth snapshot could not be loaded.",
      );
    } finally {
      if (dashboardRequest.current === controller) {
        dashboardRequest.current = null;
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [currency]);

  useEffect(() => {
    if (!profile) return;
    dashboardRequest.current?.abort();
    const controller = new AbortController();
    dashboardRequest.current = controller;
    void Promise.resolve().then(() => {
      if (!controller.signal.aborted) return fetchDashboard(controller);
    });
    return () => {
      controller.abort();
      if (dashboardRequest.current === controller) {
        dashboardRequest.current = null;
      }
    };
  }, [fetchDashboard, profile]);

  const reload = useCallback(async () => {
    if (!profile) return;
    dashboardRequest.current?.abort();
    const controller = new AbortController();
    dashboardRequest.current = controller;
    setError("");
    if (hasLoadedData.current) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    await fetchDashboard(controller);
  }, [fetchDashboard, profile]);

  useEffect(() => {
    if (!profile) return;
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void reload();
    });
    const interval = setInterval(() => {
      if (AppState.currentState === "active") void reload();
    }, 60_000);
    return () => {
      subscription.remove();
      clearInterval(interval);
    };
  }, [profile, reload]);

  const saveProfile = useCallback(
    (updatedProfile: NonNullable<typeof profile>) => {
      updateSessionProfile(updatedProfile);
      setCurrency(updatedProfile.base_currency);
    },
    [updateSessionProfile],
  );

  if (authChecking) {
    return <LoadingState label="Opening your private workspace" />;
  }
  if (!profile) {
    return <Redirect href="/(auth)" />;
  }

  return (
    <WorkspaceContext.Provider
      value={{
        profile,
        dashboard,
        currency,
        setCurrency,
        loading,
        refreshing,
        error,
        reload,
        saveProfile,
        logout,
      }}
    >
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.surface },
          headerTintColor: colors.primary,
          headerTitleStyle: { color: colors.text, fontWeight: "800" },
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen
          name="compensation"
          options={{ title: "Equity & deposits" }}
        />
        <Stack.Screen name="assistant" options={{ title: "AI assistant" }} />
        <Stack.Screen
          name="settings"
          options={{ title: "Profile settings" }}
        />
      </Stack>
    </WorkspaceContext.Provider>
  );
}
