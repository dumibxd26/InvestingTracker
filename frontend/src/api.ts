import type {
  AuthResponse,
  ChatMessage,
  ChatReply,
  Currency,
  HoldingCreatePayload,
  HoldingCreated,
  HoldingUpdatePayload,
  CashReceiptPayload,
  CashFlowSchedule,
  CashFlowSchedulePayload,
  AccountCreatePayload,
  AccountSummary,
  AccountSubaccount,
  InitialPortfolioAccountPayload,
  InitialPortfolioHoldingPayload,
  InitialPortfolioResponse,
  Dashboard,
  FundingRule,
  GoalCreatePayload,
  GoalRecord,
  GoalUpdatePayload,
  FixedDepositCreatePayload,
  FixedDepositCreated,
  ProfileUpdatePayload,
  Policy,
  RecommendationPreview,
  RegisterPayload,
  MarketDataStatus,
  MarketRefreshResult,
  MarketSymbol,
  PortfolioProjection,
  StockPurchasePlanPayload,
  SubaccountInterestPayload,
  StockSalePayload,
  StockSaleRecord,
  UserProfile,
  VestingGrantPayload,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
const AUTH_STORAGE_KEY = "northstar-access-token";
let accessToken =
  typeof window === "undefined" ? null : window.sessionStorage.getItem(AUTH_STORAGE_KEY);

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (typeof window === "undefined") return;
  if (token) {
    window.sessionStorage.setItem(AUTH_STORAGE_KEY, token);
  } else {
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      "Could not reach the API. Start the backend and database, then try again.",
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
      }
    } catch {
      // Keep the HTTP status message when the server did not send JSON.
    }
    if (
      response.status === 401 &&
      accessToken &&
      path !== "/auth/login" &&
      path !== "/auth/register"
    ) {
      setAccessToken(null);
      window.dispatchEvent(new Event("northstar-auth-expired"));
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  register: async (payload: RegisterPayload) => {
    const response = await request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setAccessToken(response.access_token);
    return response;
  },

  login: async (username: string, password: string) => {
    const response = await request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setAccessToken(response.access_token);
    return response;
  },

  me: () => request<UserProfile>("/auth/me"),

  logout: async () => {
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
    }
  },

  updateProfile: (payload: ProfileUpdatePayload) =>
    request<UserProfile>("/profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  dashboard: (currency: Currency, signal?: AbortSignal) =>
    request<Dashboard>(`/dashboard?currency=${currency}`, { signal }),

  portfolioProjection: (targetDate: string, currency: Currency, signal?: AbortSignal) =>
    request<PortfolioProjection>(
      `/projections/portfolio?target_date=${encodeURIComponent(targetDate)}&currency=${currency}`,
      { signal },
    ),

  createAccount: (payload: AccountCreatePayload) =>
    request<AccountSummary>("/accounts", { method: "POST", body: JSON.stringify(payload) }),

  initializePortfolio: (
    accounts: InitialPortfolioAccountPayload[],
    holdings: InitialPortfolioHoldingPayload[],
  ) =>
    request<InitialPortfolioResponse>("/portfolio/initialize", {
      method: "POST",
      body: JSON.stringify({ accounts, holdings }),
    }),

  createAccountSubaccount: (
    accountId: string,
    payload: {
      currency: Currency;
      opening_balance: string;
      annual_interest_rate?: string;
      interest_start_date?: string;
    },
  ) =>
    request<AccountSubaccount>(`/accounts/${encodeURIComponent(accountId)}/subaccounts`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateSubaccountInterest: (
    accountId: string,
    subaccountId: string,
    payload: SubaccountInterestPayload,
  ) =>
    request<AccountSubaccount>(
      `/accounts/${encodeURIComponent(accountId)}/subaccounts/${encodeURIComponent(subaccountId)}/interest`,
      { method: "PUT", body: JSON.stringify(payload) },
    ),

  createStockPurchasePlan: (payload: StockPurchasePlanPayload) =>
    request<{ id: string }>("/stock-purchase-plans", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteStockPurchasePlan: (planId: string) =>
    request<void>(`/stock-purchase-plans/${encodeURIComponent(planId)}`, { method: "DELETE" }),

  deleteAccount: (accountId: string) =>
    request<void>(`/accounts/${encodeURIComponent(accountId)}`, { method: "DELETE" }),

  marketDataStatus: () => request<MarketDataStatus>("/market/status"),

  searchSymbols: (query: string, signal?: AbortSignal) =>
    request<{ results: MarketSymbol[] }>(
      `/market/search?q=${encodeURIComponent(query)}`,
      { signal },
    ),

  addHolding: (payload: HoldingCreatePayload) =>
    request<HoldingCreated>("/holdings", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateHolding: (holdingId: string, payload: HoldingUpdatePayload) =>
    request<void>(`/holdings/${encodeURIComponent(holdingId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteHolding: (holdingId: string) =>
    request<void>(`/holdings/${encodeURIComponent(holdingId)}`, { method: "DELETE" }),

  sellHolding: (holdingId: string, payload: StockSalePayload) =>
    request<StockSaleRecord>(`/holdings/${encodeURIComponent(holdingId)}/sell`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  refreshMarketData: () =>
    request<MarketRefreshResult>("/market/refresh", { method: "POST" }),

  createGoal: (payload: GoalCreatePayload) =>
    request<GoalRecord>("/goals", { method: "POST", body: JSON.stringify(payload) }),

  listGoals: () => request<GoalRecord[]>("/goals"),

  updateGoal: (goalId: string, payload: GoalUpdatePayload) =>
    request<GoalRecord>(`/goals/${encodeURIComponent(goalId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteGoal: (goalId: string) =>
    request<void>(`/goals/${encodeURIComponent(goalId)}`, { method: "DELETE" }),

  createDeposit: (payload: FixedDepositCreatePayload) =>
    request<FixedDepositCreated>("/deposits", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteDeposit: (depositId: string) =>
    request<void>(`/deposits/${encodeURIComponent(depositId)}`, { method: "DELETE" }),

  updatePolicy: (payload: {
    funding_rule: FundingRule;
    emergency_reserve: string;
    target_weights: Record<string, string>;
  }) => request<Policy>("/policy", { method: "PUT", body: JSON.stringify(payload) }),

  updateGoalShares: (shares: { goal_id: string; percentage: string }[]) =>
    request("/goals/funding-shares", {
      method: "PUT",
      body: JSON.stringify({ shares }),
    }),

  previewAllocation: (amount: string, currency: Currency) =>
    request<RecommendationPreview>("/recommendations/preview", {
      method: "POST",
      body: JSON.stringify({ amount, currency }),
    }),

  askAssistant: (question: string, history: ChatMessage[], apiKey: string) =>
    request<ChatReply>("/chat", {
      method: "POST",
      headers: { "X-Provider-API-Key": apiKey },
      body: JSON.stringify({ question, history }),
    }),

  createCashFlowSchedule: (payload: CashFlowSchedulePayload) =>
    request<CashFlowSchedule>("/cash-flow-schedules", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  archiveCashFlowSchedule: (scheduleId: string) =>
    request<CashFlowSchedule>(`/cash-flow-schedules/${encodeURIComponent(scheduleId)}`, {
      method: "DELETE",
    }),

  createVestingGrant: (payload: VestingGrantPayload) =>
    request<{ id: string }>("/vesting-grants", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteVestingGrant: (grantId: string) =>
    request<void>(`/vesting-grants/${encodeURIComponent(grantId)}`, { method: "DELETE" }),

  recordExtraCash: (payload: CashReceiptPayload) =>
    request("/cash-flows/extra-cash", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
