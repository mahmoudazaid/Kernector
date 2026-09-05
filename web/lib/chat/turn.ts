import type { ChatAskResponse } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/generated/schema";

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
 * Classify an API failure the way Streamlit ``run_ask_turn`` classifies errors.
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
    return [
      ...messages,
      {
        id: newId("a"),
        role: "assistant",
        content: response.answer,
        citations: response.citations,
        toolsUsed: response.tools_used,
        run: response.run ?? null,
        toolRun: response.tool_run ?? null,
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
