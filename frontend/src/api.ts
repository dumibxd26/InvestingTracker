import type {
  ChatMessage,
  ChatReply,
  Currency,
  CashFlowSchedule,
  CashFlowSchedulePayload,
  Dashboard,
  FundingRule,
  GoalCreatePayload,
  Policy,
  RecommendationPreview,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

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
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  dashboard: (currency: Currency, signal?: AbortSignal) =>
    request<Dashboard>(`/dashboard?currency=${currency}`, { signal }),

  createGoal: (payload: GoalCreatePayload) =>
    request(`/goals`, { method: "POST", body: JSON.stringify(payload) }),

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
};
