import { createContext, useContext } from "react";
import type { AuthResponse, UserProfile } from "./types";

export interface SessionContextValue {
  profile: UserProfile | null;
  authChecking: boolean;
  authNotice: string;
  authenticate: (response: AuthResponse) => void;
  saveProfile: (profile: UserProfile) => void;
  logout: () => Promise<void>;
}

export const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("Session screens must be rendered inside SessionContext.");
  }
  return session;
}
