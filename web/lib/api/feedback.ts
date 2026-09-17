import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type UpsertResponseFeedbackRequest =
  components["schemas"]["UpsertResponseFeedbackRequest"];
export type ResponseFeedbackResponse =
  components["schemas"]["ResponseFeedbackResponse"];
export type FeedbackRating = UpsertResponseFeedbackRequest["rating"];
export type FeedbackReason = NonNullable<UpsertResponseFeedbackRequest["reason"]>;

export type UpsertResponseFeedbackOptions = {
  baseUrl: string;
  requestId: string;
  body: UpsertResponseFeedbackRequest;
  conversationId?: string | null;
  clientMessageId?: string | null;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type ClearResponseFeedbackOptions = {
  baseUrl: string;
  requestId: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type GetResponseFeedbackOptions = {
  baseUrl: string;
  requestId: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

function feedbackPath(requestId: string, query?: Record<string, string>): string {
  const encoded = encodeURIComponent(requestId);
  const base = `/api/v1/responses/${encoded}/feedback`;
  if (!query || Object.keys(query).length === 0) {
    return base;
  }
  const params = new URLSearchParams(query);
  return `${base}?${params.toString()}`;
}

/**
 * Load a thumbs rating via ``GET /api/v1/responses/{request_id}/feedback``.
 */
export async function getResponseFeedback(
  options: GetResponseFeedbackOptions,
): Promise<ResponseFeedbackResponse> {
  const request = options.request ?? apiRequest;
  return request<ResponseFeedbackResponse>({
    baseUrl: options.baseUrl,
    path: feedbackPath(options.requestId),
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Create or update a thumbs rating via
 * ``PUT /api/v1/responses/{request_id}/feedback``.
 */
export async function upsertResponseFeedback(
  options: UpsertResponseFeedbackOptions,
): Promise<ResponseFeedbackResponse> {
  const request = options.request ?? apiRequest;
  const query: Record<string, string> = {};
  if (options.conversationId?.trim()) {
    query.conversation_id = options.conversationId.trim();
  }
  if (options.clientMessageId?.trim()) {
    query.client_message_id = options.clientMessageId.trim();
  }
  return request<ResponseFeedbackResponse>({
    baseUrl: options.baseUrl,
    path: feedbackPath(options.requestId, query),
    method: "PUT",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Clear a thumbs rating via
 * ``DELETE /api/v1/responses/{request_id}/feedback``.
 */
export async function clearResponseFeedback(
  options: ClearResponseFeedbackOptions,
): Promise<void> {
  const request = options.request ?? apiRequest;
  await request<undefined>({
    baseUrl: options.baseUrl,
    path: feedbackPath(options.requestId),
    method: "DELETE",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
