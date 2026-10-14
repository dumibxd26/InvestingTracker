import { createContext, useContext } from "react";
import type { Currency, Dashboard, UserProfile } from "./types";

export interface WorkspaceContextValue {
  profile: UserProfile;
  dashboard: Dashboard | null;
  currency: Currency;
  setCurrency: (currency: Currency) => void;
  loading: boolean;
  refreshing: boolean;
  error: string;
  reload: () => Promise<void>;
  saveProfile: (profile: UserProfile) => void;
  logout: () => Promise<void>;
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const workspace = useContext(WorkspaceContext);
  if (!workspace) {
    throw new Error("Workspace screens must be rendered inside WorkspaceContext.");
  }
  return workspace;
}
