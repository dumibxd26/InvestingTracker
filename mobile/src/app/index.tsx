import { Redirect } from "expo-router";
import { LoadingState } from "../ui";
import { useSession } from "../session";

export default function IndexRoute() {
  const { profile, authChecking } = useSession();
  if (authChecking) {
    return <LoadingState label="Opening your private workspace" />;
  }
  return <Redirect href={profile ? "/(app)/(tabs)" : "/(auth)"} />;
}
