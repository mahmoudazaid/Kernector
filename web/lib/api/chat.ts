import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type ChatAskRequest = components["schemas"]["ChatAskRequest"];
export type ChatAskResponse = components["schemas"]["ChatAskResponse"];

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
