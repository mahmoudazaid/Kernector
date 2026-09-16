import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type ChatAskRequest = components["schemas"]["ChatAskRequest"];
export type ChatAskResponse = components["schemas"]["ChatAskResponse"];
export type PendingToolApprovalResponse =
  components["schemas"]["PendingToolApprovalResponse"];
export type ToolApprovalDecisionRequest =
  components["schemas"]["ToolApprovalDecisionRequest"];
export type ToolApprovalDecisionResponse =
  components["schemas"]["ToolApprovalDecisionResponse"];
export type ChatExportDestinationRequest =
  components["schemas"]["ChatExportDestinationRequest"];
export type ChatExportDestinationResponse =
  components["schemas"]["ChatExportDestinationResponse"];

/** Grounded ask turns routinely exceed the default 10s client timeout. */
export const CHAT_ASK_TIMEOUT_MS = 120_000;

export type AskChatOptions = {
  baseUrl: string;
  body: ChatAskRequest;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Run one grounded ask turn via ``POST /api/v1/chat/ask``.
 */
export async function askChat(
  options: AskChatOptions,
): Promise<ChatAskResponse> {
  const request = options.request ?? apiRequest;
  return request<ChatAskResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/chat/ask",
    method: "POST",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? CHAT_ASK_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

export type ClearChatCheckpointOptions = {
  baseUrl: string;
  conversationId: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Clear short-term agent checkpoints via
 * ``DELETE /api/v1/chat/threads/{conversation_id}/checkpoint``.
 */
export async function clearChatCheckpoint(
  options: ClearChatCheckpointOptions,
): Promise<void> {
  const request = options.request ?? apiRequest;
  const id = encodeURIComponent(options.conversationId);
  await request<undefined>({
    baseUrl: options.baseUrl,
    path: `/api/v1/chat/threads/${id}/checkpoint`,
    method: "DELETE",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Best-effort clear with one retry on transient failure.
 * Returns true when the server accepted the clear (204).
 */
export async function clearChatCheckpointBestEffort(
  options: ClearChatCheckpointOptions,
): Promise<boolean> {
  try {
    await clearChatCheckpoint(options);
    return true;
  } catch {
    try {
      await clearChatCheckpoint(options);
      return true;
    } catch {
      return false;
    }
  }
}

export type DecideToolApprovalOptions = {
  baseUrl: string;
  conversationId: string;
  approvalId: string;
  body: ToolApprovalDecisionRequest;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Approve or reject a pending tool call via
 * ``POST /api/v1/chat/threads/{conversation_id}/approvals/{approval_id}``.
 */
export async function decideToolApproval(
  options: DecideToolApprovalOptions,
): Promise<ToolApprovalDecisionResponse> {
  const request = options.request ?? apiRequest;
  const conversationId = encodeURIComponent(options.conversationId);
  const approvalId = encodeURIComponent(options.approvalId);
  return request<ToolApprovalDecisionResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/chat/threads/${conversationId}/approvals/${approvalId}`,
    method: "POST",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? CHAT_ASK_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

export type PutChatExportDestinationOptions = {
  baseUrl: string;
  conversationId: string;
  body: ChatExportDestinationRequest;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Persist Drive export folder via
 * ``PUT /api/v1/chat/threads/{conversation_id}/export-destination``.
 */
export async function putChatExportDestination(
  options: PutChatExportDestinationOptions,
): Promise<ChatExportDestinationResponse> {
  const request = options.request ?? apiRequest;
  const conversationId = encodeURIComponent(options.conversationId);
  return request<ChatExportDestinationResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/chat/threads/${conversationId}/export-destination`,
    method: "PUT",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
