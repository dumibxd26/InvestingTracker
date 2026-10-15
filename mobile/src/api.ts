import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import type {
  AccountCreatePayload,
  AccountSummary,
  AccountTaxProfileUpdatePayload,
  AuthResponse,
  CashFlowSchedule,
  CashFlowSchedulePayload,
  CashReceiptPayload,
  ChatMessage,
  ChatReply,
  Currency,
  Dashboard,
  FixedDepositCreatePayload,
  GoalCreatePayload,
  FinancialPlanPayload,
  ContributionSchedule,
  GoalRecord,
  GoalUpdatePayload,
  GoalSummary,
  HoldingCreatePayload,
  MarketRefreshResult,
  MarketSymbol,
  ProfileUpdatePayload,
  RegisterPayload,
  StockPurchasePlanPayload,
  TaxAnnualSummary,
  TaxAnnualSummaryPayload,
  UserProfile,
  VestingGrantPayload,
} from "./types";

const API_BASE =
  process.env.EXPO_PUBLIC_API_BASE_URL?.trim() ||
  Platform.select({
    android: "http://10.0.2.2:8000/api",
    default: "http://localhost:8000/api",
  }) ||
  "http://localhost:8000/api";
const AUTH_STORAGE_KEY = "investingtracker-access-token";

let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | undefined;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function restoreAccessToken(): Promise<string | null> {
  accessToken = await SecureStore.getItemAsync(AUTH_STORAGE_KEY);
  return accessToken;
}

async function setAccessToken(token: string | null): Promise<void> {
  if (token) {
    await SecureStore.setItemAsync(AUTH_STORAGE_KEY, token);
  } else {
    accessToken = null;
    await SecureStore.deleteItemAsync(AUTH_STORAGE_KEY);
  }
  accessToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | undefined): void {
  unauthorizedHandler = handler;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init?.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "Could not reach the API. Start the backend and check the mobile API URL.",
      0,
    );
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload: unknown = await response.json();
      if (
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof payload.detail === "string"
      ) {
        message = payload.detail;
      } else if (typeof payload === "object" && payload !== null && "detail" in payload && Array.isArray(payload.detail)) {
        message = payload.detail.map((item: unknown) =>
          typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : "Invalid input",
        ).join("; ");
      }
    } catch {
      message = `Request failed (${response.status})`;
    }
    if (
      response.status === 401 &&
      accessToken &&
      path !== "/auth/login" &&
      path !== "/auth/register"
    ) {
      try {
        await setAccessToken(null);
      } finally {
        unauthorizedHandler?.();
      }
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  register: async (payload: RegisterPayload): Promise<AuthResponse> => {
    const response = await request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await setAccessToken(response.access_token);
    return response;
  },

  login: async (username: string, password: string): Promise<AuthResponse> => {
    const response = await request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    await setAccessToken(response.access_token);
    return response;
  },

  me: () => request<UserProfile>("/auth/me"),

  logout: async (): Promise<void> => {
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } finally {
      await setAccessToken(null);
    }
  },

  updateProfile: (payload: ProfileUpdatePayload) =>
    request<UserProfile>("/profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  updateAccountTaxProfile: (
    accountId: string,
    payload: AccountTaxProfileUpdatePayload,
  ) =>
    request<AccountSummary>(
      `/accounts/${encodeURIComponent(accountId)}/tax-profile`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  dashboard: (currency: Currency, signal?: AbortSignal) =>
    request<Dashboard>(`/dashboard?currency=${currency}`, { signal }),

  createAccount: (payload: AccountCreatePayload) =>
    request<AccountSummary>("/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteAccount: (accountId: string) =>
    request<void>(`/accounts/${encodeURIComponent(accountId)}`, {
      method: "DELETE",
    }),

  searchSymbols: (query: string, signal?: AbortSignal) =>
    request<{ results: MarketSymbol[] }>(
      `/market/search?q=${encodeURIComponent(query)}`,
      { signal },
    ),

  addHolding: (payload: HoldingCreatePayload) =>
    request<{ id: string }>("/holdings", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteHolding: (holdingId: string) =>
    request<void>(`/holdings/${encodeURIComponent(holdingId)}`, {
      method: "DELETE",
    }),

  refreshMarketData: () =>
    request<MarketRefreshResult>("/market/refresh", { method: "POST" }),

  createGoal: (payload: GoalCreatePayload) =>
    request<GoalSummary>("/goals", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listGoals: () => request<GoalRecord[]>("/goals"),
  updateGoal: (id: string, payload: GoalUpdatePayload) =>
    request<GoalRecord>(`/goals/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  financialPlan: () => request<FinancialPlanPayload>("/financial-plan"),
  saveFinancialPlan: (payload: FinancialPlanPayload) =>
    request<FinancialPlanPayload>("/financial-plan", { method: "PUT", body: JSON.stringify(payload) }),
  goalContributions: (id: string, months = 120) =>
    request<ContributionSchedule>(`/goals/${encodeURIComponent(id)}/contributions?months=${months}`),

  deleteGoal: (goalId: string) =>
    request<void>(`/goals/${encodeURIComponent(goalId)}`, {
      method: "DELETE",
    }),

  createDeposit: (payload: FixedDepositCreatePayload) =>
    request<{ id: string }>("/deposits", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteDeposit: (depositId: string) =>
    request<void>(`/deposits/${encodeURIComponent(depositId)}`, {
      method: "DELETE",
    }),

  createCashFlowSchedule: (payload: CashFlowSchedulePayload) =>
    request<CashFlowSchedule>("/cash-flow-schedules", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  archiveCashFlowSchedule: (scheduleId: string) =>
    request<CashFlowSchedule>(
      `/cash-flow-schedules/${encodeURIComponent(scheduleId)}`,
      { method: "DELETE" },
    ),

  recordExtraCash: (payload: CashReceiptPayload) =>
    request("/cash-flows/extra-cash", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createVestingGrant: (payload: VestingGrantPayload) =>
    request<{ id: string }>("/vesting-grants", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createStockPurchasePlan: (payload: StockPurchasePlanPayload) =>
    request<{ id: string }>("/stock-purchase-plans", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteVestingGrant: (grantId: string) =>
    request<void>(`/vesting-grants/${encodeURIComponent(grantId)}`, {
      method: "DELETE",
    }),

  deleteStockPurchasePlan: (planId: string) =>
    request<void>(`/stock-purchase-plans/${encodeURIComponent(planId)}`, {
      method: "DELETE",
    }),

  askAssistant: (question: string, history: ChatMessage[], apiKey: string) =>
    request<ChatReply>("/chat", {
      method: "POST",
      headers: { "X-Provider-API-Key": apiKey },
      body: JSON.stringify({ question, history }),
    }),

  calculateAnnualTaxSummary: (payload: TaxAnnualSummaryPayload) =>
    request<TaxAnnualSummary>("/taxes/annual-summary", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
