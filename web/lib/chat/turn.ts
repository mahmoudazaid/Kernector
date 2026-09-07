import type { ChatAskResponse } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/generated/schema";
import { sanitizeStoredChatMessage } from "@/lib/chat/sanitize";

export type Citation = components["schemas"]["CitationResponse"];
export type ToolUsed = components["schemas"]["ToolUsedResponse"];
export type RunMeta = components["schemas"]["RunMetaResponse"];
export type ToolRun = components["schemas"]["ToolRunResponse"];

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  displayOnly?: boolean;
  citations?: Citation[];
  toolsUsed?: ToolUsed[];
  run?: RunMeta | null;
  toolRun?: ToolRun | null;
};

export type HistoryTurn = {
  role: "user" | "assistant";
  content: string;
};

export type TurnSuccess = {
  kind: "success";
  response: ChatAskResponse;
};

export type TurnFailure = {
  kind: "rejected" | "operational" | "unavailable";
  message: string;
};

export type TurnResult = TurnSuccess | TurnFailure;

let nextId = 0;

function newId(prefix: string): string {
  nextId += 1;
  return `${prefix}-${nextId}`;
}

/**
 * Advance the id counter past any `u-N` / `a-N` / `err-N` ids already present
 * so restored transcripts do not collide with freshly minted turns.
 */
export function seedIds(messages: readonly { id: string }[]): void {
  let max = nextId;
  for (const message of messages) {
    const match = /^(?:u|a|err)-(\d+)$/.exec(message.id);
    if (match) {
      max = Math.max(max, Number(match[1]));
    }
  }
  nextId = max;
}

/**
 * Project transcript rows into model history, skipping display-only errors.
 */
export function historyForModel(messages: readonly ChatMessage[]): HistoryTurn[] {
  return messages.flatMap((message) => {
    if (message.displayOnly) {
      return [];
    }
    if (!message.content.trim()) {
      return [];
    }
    return [{ role: message.role, content: message.content }];
  });
}

/**
 * Classify an API failure into rejected / unavailable / operational kinds.
 */
export function classifyFailure(error: ApiError): TurnFailure {
  if (error.status === 422) {
    return { kind: "rejected", message: error.detail };
  }
  if (error.status === 0) {
    return { kind: "unavailable", message: error.detail };
  }
  return { kind: "operational", message: error.detail };
}

/**
 * Apply one turn outcome to the transcript (immutable).
 *
 * Rejection pops the just-appended user message. Operational failure keeps it
 * and appends a display-only assistant row.
 */
export function applyTurnResult(
  messages: readonly ChatMessage[],
  result: TurnResult,
): ChatMessage[] {
  if (result.kind === "success") {
    const { response } = result;
    const id = newId("a");
    const answer =
      typeof response.answer === "string" ? response.answer : "";
    // Constructed with a fresh id, literal role, and string content — never null.
    const sanitized = sanitizeStoredChatMessage({
      id,
      role: "assistant",
      content: answer,
      citations: response.citations,
      toolsUsed: response.tools_used,
      run: response.run ?? null,
      toolRun: response.tool_run ?? null,
    })!;
    return [
      ...messages,
      {
        id: sanitized.id,
        role: "assistant",
        content: sanitized.content,
        citations: sanitized.citations as Citation[] | undefined,
        toolsUsed: sanitized.toolsUsed as ToolUsed[] | undefined,
        run: (sanitized.run as RunMeta | null | undefined) ?? null,
        toolRun: (sanitized.toolRun as ToolRun | null | undefined) ?? null,
      },
    ];
  }
  if (result.kind === "rejected") {
    if (messages.length === 0) {
      return [];
    }
    const last = messages[messages.length - 1];
    if (last.role === "user") {
      return messages.slice(0, -1);
    }
    return [...messages];
  }
  return [
    ...messages,
    {
      id: newId("err"),
      role: "assistant",
      content: result.message,
      displayOnly: true,
    },
  ];
}

/**
 * Append a user message before calling the ask API.
 */
export function appendUserMessage(
  messages: readonly ChatMessage[],
  content: string,
): ChatMessage[] {
  return [...messages, { id: newId("u"), role: "user", content }];
}
