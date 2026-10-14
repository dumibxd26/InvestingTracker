import { useCallback, useEffect, useState } from "react";
import { StatusBar } from "expo-status-bar";
import { Stack } from "expo-router";
import { SafeAreaProvider } from "react-native-safe-area-context";
import {
  api,
  ApiError,
  restoreAccessToken,
  setUnauthorizedHandler,
} from "../api";
import type { AuthResponse, UserProfile } from "../types";
import { colors } from "../theme";
import { SessionContext } from "../session";

export default function RootLayout() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [authNotice, setAuthNotice] = useState("");

  useEffect(() => {
    let active = true;
    setUnauthorizedHandler(() => {
      if (!active) return;
      setProfile(null);
      setAuthNotice("Your sign-in session expired. Sign in again to continue.");
    });

    void (async () => {
      try {
        const token = await restoreAccessToken();
        if (!token) return;
        const currentProfile = await api.me();
        if (active) setProfile(currentProfile);
      } catch (cause) {
        if (!active) return;
        setAuthNotice(
          cause instanceof ApiError && cause.status === 401
            ? "Your sign-in session expired. Sign in again to continue."
            : cause instanceof ApiError
              ? cause.message
              : "The saved sign-in could not be restored. Sign in again to continue.",
        );
      } finally {
        if (active) setAuthChecking(false);
      }
    })();

    return () => {
      active = false;
      setUnauthorizedHandler(undefined);
    };
  }, []);

  const authenticate = useCallback((response: AuthResponse) => {
    setAuthNotice("");
    setProfile(response.user);
  }, []);

  const saveProfile = useCallback((updatedProfile: UserProfile) => {
    setProfile(updatedProfile);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setProfile(null);
      setAuthNotice("");
    }
  }, []);

  return (
    <SafeAreaProvider>
      <SessionContext.Provider
        value={{
          profile,
          authChecking,
          authNotice,
          authenticate,
          saveProfile,
          logout,
        }}
      >
        <StatusBar style={profile ? "dark" : "light"} />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: colors.surface },
            headerTintColor: colors.primary,
            headerTitleStyle: { color: colors.text, fontWeight: "800" },
            contentStyle: { backgroundColor: colors.background },
          }}
        >
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Protected guard={Boolean(profile)}>
            <Stack.Screen name="(app)" options={{ headerShown: false }} />
          </Stack.Protected>
          <Stack.Protected guard={!profile}>
            <Stack.Screen name="(auth)" options={{ headerShown: false }} />
          </Stack.Protected>
        </Stack>
      </SessionContext.Provider>
    </SafeAreaProvider>
  );
}
