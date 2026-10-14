import { useRouter } from "expo-router";
import { AuthScreen } from "../../screens/AuthScreen";
import { useSession } from "../../session";

export default function AuthRoute() {
  const router = useRouter();
  const { authNotice, authenticate } = useSession();
  return (
    <AuthScreen
      notice={authNotice}
      onAuthenticated={(response) => {
        authenticate(response);
        router.replace("/(app)/(tabs)");
      }}
    />
  );
}
